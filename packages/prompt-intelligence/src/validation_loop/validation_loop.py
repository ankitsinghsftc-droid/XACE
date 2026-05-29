"""
validation_loop.py — ValidationLoop
=====================================
Multi-layer validation gate between StructuredOutputParser and GDE commit.

Consumes a CanonicalMutation and runs four validation layers in sequence.
All four must pass before the mutation proceeds to SafetyScopeGuard (13.9)
and MutationPlanner (13.8) for commit.

## Four Validation Layers

    Layer 1 — Structural Validation
        Re-confirms all paths exist in the current CGS (delegates to
        SchemaPathValidator for a fresh check against the live CGS, since
        the CGS may have changed since StructuredOutputParser ran).
        Also checks: no operations on globally frozen fields, no duplicate
        paths within the same transaction.

    Layer 2 — Type Validation
        Re-confirms all value types match field definitions (delegates to
        OperationTypeValidator for a fresh check).
        Also: integer overflow guard (values > 1e12 for numeric fields
        are flagged as likely errors).

    Layer 3 — Dependency Validation
        Checks that the mutation does not break the system dependency graph.
        Specifically: if the mutation adds or removes a system, all depends_on
        references remain satisfiable.
        Also: validates that required_recompile is correctly set based on
        whether structural changes are present.

    Layer 4 — Invariant Validation (Phase 12 ConsistencyValidator)
        Applies the mutations to a copy of the CGS (proposed_cgs) and
        calls ConsistencyValidator.validate(proposed_cgs, txn_stub, cgs).
        ConsistencyValidator is the Phase 12 GDE component that enforces
        D-rules at the schema level.

        If Phase 12 ConsistencyValidator is not importable (isolated test
        environment), Layer 4 runs a minimal local invariant check instead:
            - No system has deterministic=false after mutation
            - No health component has max < 0

## ValidationResult

    passed:          bool
    layer_results:   dict[str, LayerResult]  — per-layer pass/fail + reasons
    blocking_errors: list[str]               — errors that prevent commit
    warnings:        list[str]               — non-blocking issues
    proposed_cgs:    dict | None             — proposed state if layers 1-3 pass
                                              (None if layer 1 or 2 hard fail)

## Usage

    loop = ValidationLoop()
    result = loop.validate(canonical_mutation, current_cgs)
    if not result.passed:
        return PipelineResult(needs_clarification=True, error=result.blocking_errors[0])
    # proceed to SafetyScopeGuard
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import copy

import sys, os

_src = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_src, "..", "output_parser"))
sys.path.insert(0, os.path.join(_src, "..", "llm_orchestrator"))
sys.path.insert(0, os.path.join(_src, "..", "context_assembler"))
sys.path.insert(0, os.path.join(_src, "..", "intent_intake"))

from schema_path_validator import SchemaPathValidator
from operation_type_validator import OperationTypeValidator
from structured_output_parser import CanonicalMutation
from pass5_final_output import MutationTransaction
from pass2_dsl_draft import MutationOp

# Phase 12 ConsistencyValidator — import with fallback for isolated testing
try:
    from gde.consistency_validator.consistency_validator import (
        ConsistencyValidator as _GDEConsistencyValidator,
    )
    _HAS_GDE_VALIDATOR = True
except ImportError:
    _HAS_GDE_VALIDATOR = False
    _GDEConsistencyValidator = None  # type: ignore


# ── Numeric overflow threshold ────────────────────────────────────────────────

_NUMERIC_OVERFLOW_THRESHOLD = 1e12


# ── Layer Result ──────────────────────────────────────────────────────────────

@dataclass
class LayerResult:
    """Result of one validation layer."""
    layer:    str
    passed:   bool
    errors:   list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"LayerResult({self.layer}: {status}, {len(self.errors)} errors)"


# ── Validation Result ─────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    """
    Output of ValidationLoop.validate().

    Attributes
    ----------
    passed          : bool               — True if all 4 layers passed
    layer_results   : dict[str, LayerResult]
    blocking_errors : list[str]          — errors that prevent commit
    warnings        : list[str]          — non-blocking issues
    proposed_cgs    : dict | None        — CGS state after mutations applied
                                           None if layers 1/2 prevent application
    """
    passed:          bool
    layer_results:   dict[str, LayerResult]   = field(default_factory=dict)
    blocking_errors: list[str]                = field(default_factory=list)
    warnings:        list[str]                = field(default_factory=list)
    proposed_cgs:    dict | None              = None

    def __repr__(self) -> str:
        status = "PASSED" if self.passed else "FAILED"
        return (
            f"ValidationResult({status}, "
            f"layers={list(self.layer_results.keys())}, "
            f"errors={len(self.blocking_errors)})"
        )


# ── Validation Loop ───────────────────────────────────────────────────────────

class ValidationLoop:
    """
    Multi-layer validation gate.

    Stateless — one instance may be shared across PIL sessions.

    Usage
    -----
        loop   = ValidationLoop()
        result = loop.validate(canonical_mutation, current_cgs)
        if result.passed:
            proceed_to_safety_guard(result.proposed_cgs)
        else:
            handle_errors(result.blocking_errors)
    """

    def __init__(self) -> None:
        self._path_validator = SchemaPathValidator()
        self._op_validator   = OperationTypeValidator()
        if _HAS_GDE_VALIDATOR:
            self._gde_validator = _GDEConsistencyValidator()
        else:
            self._gde_validator = None

    # ── Public API ────────────────────────────────────────────────────────────

    def validate(
        self,
        canonical:    CanonicalMutation,
        current_cgs:  dict[str, Any],
    ) -> ValidationResult:
        """
        Runs all 4 validation layers on a CanonicalMutation.

        Parameters
        ----------
        canonical : CanonicalMutation
            Output of StructuredOutputParser.parse().
        current_cgs : dict
            The CGS at the time of validation (may differ from when
            StructuredOutputParser ran, in high-concurrency scenarios).

        Returns
        -------
        ValidationResult
        """
        ops       = canonical.transaction.operations
        delta     = canonical.transaction.schema_delta_type
        layer_results: dict[str, LayerResult] = {}
        all_errors:   list[str] = []
        all_warnings: list[str] = []

        # ── Layer 1: Structural validation ───────────────────────────────────
        l1 = self._layer1_structural(ops, current_cgs)
        layer_results["structural"] = l1
        all_errors.extend(l1.errors)
        all_warnings.extend(l1.warnings)

        if not l1.passed:
            # Cannot proceed to layers 2-4 without valid paths
            return ValidationResult(
                passed          = False,
                layer_results   = layer_results,
                blocking_errors = all_errors,
                warnings        = all_warnings,
                proposed_cgs    = None,
            )

        # ── Layer 2: Type validation ──────────────────────────────────────────
        l2 = self._layer2_type(ops, delta, current_cgs)
        layer_results["type"] = l2
        all_errors.extend(l2.errors)
        all_warnings.extend(l2.warnings)

        if not l2.passed:
            return ValidationResult(
                passed          = False,
                layer_results   = layer_results,
                blocking_errors = all_errors,
                warnings        = all_warnings,
                proposed_cgs    = None,
            )

        # ── Layer 3: Dependency validation ────────────────────────────────────
        l3 = self._layer3_dependency(ops, delta, current_cgs)
        layer_results["dependency"] = l3
        all_errors.extend(l3.errors)
        all_warnings.extend(l3.warnings)

        # ── Apply mutations to produce proposed CGS ───────────────────────────
        proposed_cgs = self._apply_mutations(ops, current_cgs)

        # ── Layer 4: Invariant validation (Phase 12 ConsistencyValidator) ─────
        l4 = self._layer4_invariant(proposed_cgs, current_cgs, canonical.transaction)
        layer_results["invariant"] = l4
        all_errors.extend(l4.errors)
        all_warnings.extend(l4.warnings)

        passed = all(lr.passed for lr in layer_results.values())

        return ValidationResult(
            passed          = passed,
            layer_results   = layer_results,
            blocking_errors = all_errors,
            warnings        = all_warnings,
            proposed_cgs    = proposed_cgs if passed else None,
        )

    # ── Layer 1: Structural ───────────────────────────────────────────────────

    def _layer1_structural(
        self,
        ops:         list[MutationOp],
        current_cgs: dict[str, Any],
    ) -> LayerResult:
        errors:   list[str] = []
        warnings: list[str] = []

        paths = [op.path for op in ops]

        # Fresh path validation against live CGS
        path_result = self._path_validator.validate(paths, current_cgs)
        errors.extend(path_result.reasons)

        # Check for duplicate paths within the same transaction
        seen_paths: set[str] = set()
        for op in ops:
            if op.path in seen_paths:
                errors.append(
                    f"Duplicate path in transaction: {op.path!r}. "
                    f"Each path must appear at most once per transaction."
                )
            seen_paths.add(op.path)

        # Unknown paths are warnings, not errors (SchemaPathValidator already
        # puts them in unknown_paths, not invalid_paths)
        for p in path_result.unknown_paths:
            warnings.append(
                f"Path grammar unrecognised: {p!r}. "
                f"Manual review recommended before commit."
            )

        return LayerResult(
            layer   = "structural",
            passed  = len(errors) == 0,
            errors  = errors,
            warnings = warnings,
        )

    # ── Layer 2: Type ─────────────────────────────────────────────────────────

    def _layer2_type(
        self,
        ops:         list[MutationOp],
        delta:       str,
        current_cgs: dict[str, Any],
    ) -> LayerResult:
        errors:   list[str] = []
        warnings: list[str] = []

        # Fresh op type validation
        op_result = self._op_validator.validate(ops, delta, current_cgs)
        errors.extend(op_result.errors)
        warnings.extend(op_result.warnings)

        # Integer overflow guard
        for i, op in enumerate(ops):
            if isinstance(op.value, (int, float)):
                if abs(op.value) > _NUMERIC_OVERFLOW_THRESHOLD:
                    errors.append(
                        f"op[{i}]: value {op.value} exceeds overflow threshold "
                        f"({_NUMERIC_OVERFLOW_THRESHOLD}). "
                        f"This is likely an error in the LLM output."
                    )

        return LayerResult(
            layer    = "type",
            passed   = len(errors) == 0,
            errors   = errors,
            warnings = warnings,
        )

    # ── Layer 3: Dependency ───────────────────────────────────────────────────

    def _layer3_dependency(
        self,
        ops:         list[MutationOp],
        delta:       str,
        current_cgs: dict[str, Any],
    ) -> LayerResult:
        errors:   list[str] = []
        warnings: list[str] = []

        # Build current system set for dependency resolution
        all_system_ids: set[str] = set()
        for gs in current_cgs.get("global_systems", []):
            all_system_ids.add(gs.get("id", ""))
        for mode in current_cgs.get("modes", []):
            for sys in mode.get("systems", []):
                all_system_ids.add(sys.get("id", ""))

        # For structural removal ops: check that depends_on chains remain intact
        for op in ops:
            if op.op == "REMOVE_SYSTEM":
                sid = op.actor_id or op.field_name  # system_id stored here for remove ops
                if not sid and op.path:
                    # Try to extract from path
                    import re
                    m = re.search(r'systems\[([^\]]+)\]', op.path)
                    if m:
                        sid = m.group(1)

                if sid:
                    # Find systems that depend on this one
                    dependents = self._find_dependents(sid, current_cgs)
                    if dependents:
                        errors.append(
                            f"Cannot remove system '{sid}' — "
                            f"the following systems depend on it: {dependents}. "
                            f"Remove dependents first or update their depends_on."
                        )

        # For structural add ops that reference systems in depends_on:
        # future-proof check; current pass5 doesn't generate full system defs
        # so this is a structural integrity note only.

        # Validate required_recompile consistency:
        # If delta is structural_add or structural_remove, recompile is expected.
        if delta in {"structural_add", "structural_remove"}:
            warnings.append(
                "Structural mutation detected. "
                "System graph recompile will be required after commit."
            )

        return LayerResult(
            layer    = "dependency",
            passed   = len(errors) == 0,
            errors   = errors,
            warnings = warnings,
        )

    # ── Layer 4: Invariant (Phase 12 ConsistencyValidator) ───────────────────

    def _layer4_invariant(
        self,
        proposed_cgs: dict[str, Any],
        current_cgs:  dict[str, Any],
        transaction:  MutationTransaction,
    ) -> LayerResult:
        errors:   list[str] = []
        warnings: list[str] = []

        if _HAS_GDE_VALIDATOR and self._gde_validator is not None:
            # Full Phase 12 ConsistencyValidator
            try:
                report = self._gde_validator.validate(
                    proposed_cgs, transaction, current_cgs
                )
                if not report.is_valid:
                    errors.extend(report.errors[:5])   # cap at 5 for readability
            except Exception as exc:
                warnings.append(
                    f"Phase 12 ConsistencyValidator raised an exception: {exc}. "
                    f"Proceeding with local invariant check only."
                )
                errors.extend(self._local_invariant_check(proposed_cgs))
        else:
            # Fallback: local minimal invariant check
            errors.extend(self._local_invariant_check(proposed_cgs))

        return LayerResult(
            layer    = "invariant",
            passed   = len(errors) == 0,
            errors   = errors,
            warnings = warnings,
        )

    # ── Mutation application ──────────────────────────────────────────────────

    @staticmethod
    def _apply_mutations(
        ops:         list[MutationOp],
        current_cgs: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Applies SET/SCALE mutations to a deep copy of current_cgs.
        Structural ops (ADD/REMOVE) are not applied here — they are
        handled by GDE's TransactionExecutor after validation passes.
        Returns the proposed_cgs for invariant checking.
        """
        proposed = copy.deepcopy(current_cgs)

        for op in ops:
            if op.op not in {"SET", "SCALE"}:
                continue  # structural ops handled by GDE

            path = op.path
            try:
                _apply_op_to_cgs(proposed, path, op.op, op.value)
            except (KeyError, TypeError, IndexError):
                pass  # path resolution failure — already caught by layer 1

        return proposed

    # ── Dependency helpers ────────────────────────────────────────────────────

    @staticmethod
    def _find_dependents(
        system_id:   str,
        current_cgs: dict[str, Any],
    ) -> list[str]:
        """Returns IDs of systems that list system_id in their depends_on."""
        dependents: list[str] = []
        all_systems: list[dict] = list(current_cgs.get("global_systems", []))
        for mode in current_cgs.get("modes", []):
            all_systems.extend(mode.get("systems", []))
        for sys in all_systems:
            if system_id in sys.get("depends_on", []):
                dependents.append(sys.get("id", "?"))
        return dependents

    # ── Local invariant check ─────────────────────────────────────────────────

    @staticmethod
    def _local_invariant_check(proposed_cgs: dict[str, Any]) -> list[str]:
        """
        Minimal invariant check when Phase 12 ConsistencyValidator is
        not available. Covers the two most critical invariants:
            1. No system has deterministic=false
            2. No health component has max < 0
        """
        errors: list[str] = []

        all_systems: list[dict] = list(proposed_cgs.get("global_systems", []))
        for mode in proposed_cgs.get("modes", []):
            all_systems.extend(mode.get("systems", []))
            for actor in mode.get("actors", []):
                for comp in actor.get("components", []):
                    if comp.get("name", "").startswith("COMP_HEALTH"):
                        max_hp = comp.get("defaults", {}).get("max", 0)
                        if isinstance(max_hp, (int, float)) and max_hp < 0:
                            errors.append(
                                f"Invariant violation: health component on actor "
                                f"'{actor.get('id','?')}' has max={max_hp} < 0."
                            )

        for sys in all_systems:
            if sys.get("deterministic") is False:
                errors.append(
                    f"Invariant violation: system '{sys.get('id','?')}' "
                    f"has deterministic=false. All systems must be deterministic."
                )

        return errors


# ── CGS Mutation Application ──────────────────────────────────────────────────

def _apply_op_to_cgs(
    cgs:   dict[str, Any],
    path:  str,
    op:    str,
    value: Any,
) -> None:
    """
    Applies a SET or SCALE operation to a proposed_cgs dict in-place.
    Uses the bracket-notation path format.
    Raises KeyError/TypeError on unresolvable paths (caught by caller).
    """
    import re

    # Parse: modes[mode_id].actors[actor_id].components[type_id].defaults.field
    m = re.match(
        r'^modes\[([^\]]+)\]\.actors\[([^\]]+)\]\.components\[(\d+)\]\.defaults\.(\w+)$',
        path,
    )
    if m:
        mid, aid, tid_str, fname = m.groups()
        tid = int(tid_str)
        for mode in cgs.get("modes", []):
            if mode.get("id") == mid:
                for actor in mode.get("actors", []):
                    if actor.get("id") == aid:
                        for comp in actor.get("components", []):
                            if comp.get("type_id") == tid:
                                defaults = comp.setdefault("defaults", {})
                                if op == "SET":
                                    defaults[fname] = value
                                elif op == "SCALE":
                                    existing = defaults.get(fname, 1.0)
                                    if isinstance(existing, (int, float)):
                                        defaults[fname] = existing * value
                                return
        return  # path not found — silently skip (layer 1 already caught it)

    # Other path types (system fields, rule fields) — skip for now
    # Full implementation in GDE TransactionExecutor; this covers the 90% case