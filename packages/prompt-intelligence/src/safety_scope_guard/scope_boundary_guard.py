"""
scope_boundary_guard.py — ScopeBoundaryGuard
=============================================
Verifies every operation path is within the AllowedMutationScope
defined when the LLMContextPacket was assembled.

## What It Checks

    1. Path Allow-List
       If scope.allowed_paths is non-empty, every op path must start
       with at least one allowed prefix. Paths that don't match any
       allowed prefix are blocked.
       Exception: ARCHITECT_MODE (scope.is_unrestricted=True) has no
       allow-list — all paths permitted (except permanently forbidden).

    2. Permanent Forbidden Domains
       Regardless of mode or allow-list, these path prefixes are always
       blocked:
           metadata.cgs_hash
           metadata.schema_version
           metadata.version
           tick_rate
           entity_id_format
           ucl_frozen
           mutation_gate_config

    3. Engine Core Domains
       Paths into engine-internal namespaces are blocked in all modes
       except ARCHITECT_MODE:
           engine.*
           scheduler.*
           physics_core.*
           renderer.*

    4. Structural Gating
       If scope.structural_change_allowed=False, any op type that is
       structural (ADD_ACTOR, REMOVE_*, ADD_SYSTEM, etc.) is blocked.
       This is the mode-level guard against structural changes for
       FULLY_ASSISTED mode.

## GuardResult

    passed:   bool
    severity: str        — "none" | "warning" | "block"
    findings: list[str]  — human-readable descriptions of violations
    guard:    str        — guard name (for SafetyScopeGuard aggregation)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "llm_orchestrator"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "context_assembler"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mutation_planner"))

from pass2_dsl_draft import MutationOp
from mutation_planner import CommittedMutationPlan
from llm_context_packet import AllowedMutationScope


# ── GuardResult (shared across all guards) ────────────────────────────────────

@dataclass
class GuardResult:
    """
    Result of one safety guard.

    Attributes
    ----------
    guard    : str        — guard name
    passed   : bool       — True if no blocking issues
    severity : str        — "none" | "warning" | "block"
    findings : list[str]  — violation descriptions
    """
    guard:    str
    passed:   bool
    severity: str              = "none"
    findings: list[str]        = field(default_factory=list)

    @property
    def is_blocking(self) -> bool:
        return self.severity == "block"

    @property
    def is_warning(self) -> bool:
        return self.severity == "warning"

    def __repr__(self) -> str:
        status = "PASS" if self.passed else f"FAIL({self.severity.upper()})"
        return f"GuardResult({self.guard}: {status}, {len(self.findings)} findings)"


# ── Forbidden path prefixes ───────────────────────────────────────────────────

_PERMANENT_FORBIDDEN: frozenset[str] = frozenset({
    "metadata.cgs_hash",
    "metadata.schema_version",
    "metadata.version",
    "tick_rate",
    "entity_id_format",
    "ucl_frozen",
    "mutation_gate_config",
    "snapshot_engine_config",
})

_ENGINE_CORE_PREFIXES: frozenset[str] = frozenset({
    "engine.",
    "scheduler.",
    "physics_core.",
    "renderer.",
    "ecs_runtime.",
})

_STRUCTURAL_OPS: frozenset[str] = frozenset({
    "ADD_ACTOR", "REMOVE_ACTOR",
    "ADD_COMPONENT", "REMOVE_COMPONENT",
    "ADD_SYSTEM", "REMOVE_SYSTEM",
    "ADD_RULE", "REMOVE_RULE",
})


# ── Scope Boundary Guard ──────────────────────────────────────────────────────

class ScopeBoundaryGuard:
    """
    Enforces AllowedMutationScope boundaries on every operation.

    Stateless — safe to share across sessions.
    Deterministic — same inputs always produce the same result.

    Usage
    -----
        guard  = ScopeBoundaryGuard()
        result = guard.check(plan, scope)
    """

    def check(
        self,
        plan:  CommittedMutationPlan,
        scope: AllowedMutationScope | None,
    ) -> GuardResult:
        """
        Checks all operations against the allowed scope.

        Parameters
        ----------
        plan  : CommittedMutationPlan
        scope : AllowedMutationScope | None
            If None, only permanent forbidden checks apply.

        Returns
        -------
        GuardResult
        """
        findings: list[str] = []
        is_architect = scope is None or scope.is_unrestricted

        for op in plan.ordered_ops:
            path    = op.path
            op_type = op.op

            # Check 1: permanent forbidden
            for fp in _PERMANENT_FORBIDDEN:
                if path.startswith(fp):
                    findings.append(
                        f"BLOCKED: Path '{path}' touches permanently forbidden "
                        f"field '{fp}'. This field is immutable."
                    )
                    break

            # Check 2: engine core domains (blocked except ARCHITECT_MODE)
            if not is_architect:
                for prefix in _ENGINE_CORE_PREFIXES:
                    if path.startswith(prefix):
                        findings.append(
                            f"BLOCKED: Path '{path}' touches engine-internal domain "
                            f"'{prefix}'. Engine internals are immutable in this mode."
                        )
                        break

            # Check 3: allow-list (only when scope has allowed_paths)
            if scope and not scope.is_unrestricted and not is_architect:
                if not scope.path_is_allowed(path):
                    if scope.path_is_forbidden(path):
                        findings.append(
                            f"BLOCKED: Path '{path}' is in the forbidden list "
                            f"for this call's scope."
                        )
                    else:
                        findings.append(
                            f"BLOCKED: Path '{path}' is outside the allowed scope "
                            f"for this intent. Allowed prefixes: "
                            f"{list(scope.allowed_paths)[:3]}"
                        )

            # Check 4: structural gating
            if (scope and not scope.structural_change_allowed
                    and op_type in _STRUCTURAL_OPS):
                findings.append(
                    f"BLOCKED: Operation '{op_type}' is structural but structural "
                    f"changes are not permitted in mode '{scope.mode}'. "
                    f"Use ADVANCED or ARCHITECT_MODE for structural operations."
                )

        passed   = len(findings) == 0
        severity = "block" if findings else "none"

        return GuardResult(
            guard    = "scope_boundary",
            passed   = passed,
            severity = severity,
            findings = findings,
        )