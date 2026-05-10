"""
consistency_validator.py — ConsistencyValidator
=================================================
Pre-commit validation: runs all four consistency sub-validators
against a proposed CGS and returns a unified ConsistencyReport.

This is the final gate before CGSManager.commit() is called.
If this passes, the transaction is applied. If it fails, the working
copy is discarded and the original CGS is preserved (I8).

## Sub-Validators
    PathResolver       — all paths in the transaction exist (or are new-node writable)
    TypeChecker        — values match declared component field types
    ConflictDetector   — no logical contradictions within the transaction
    InvariantEnforcer  — global CGS invariants hold after the mutation

## Pipeline
    1. TransactionExecutor applies the transaction to a CGS copy
    2. ConsistencyValidator.validate(proposed_cgs, transaction) runs
    3. If valid → CGSManager.commit(proposed_cgs, metadata) persists it
    4. If invalid → proposed_cgs is discarded, original CGS unchanged

## Report
ConsistencyReport aggregates errors and warnings from all sub-validators.
The GDE orchestrator surfaces these to the designer in plain English.

## Performance Target
< 50ms for typical mutations (CLAUDE.md: total prompt processing < 150ms).
PathResolver uses a read cache; TypeChecker and ConflictDetector are O(n)
in operation count. InvariantEnforcer is O(actors + systems + rules).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain_dsl.path_addressing.path_resolver import PathResolver
from .type_checker import TypeChecker, TypeCheckResult
from .conflict_detector import ConflictDetector, ConflictReport
from .invariant_enforcer import InvariantEnforcer, InvariantViolation, EnforcementResult
from ..domain_dsl.transaction_model.transaction_builder import DSLTransaction, DSLOperation, OpType


# ── Consistency Report ────────────────────────────────────────────────────────

@dataclass
class ConsistencyReport:
    """
    Aggregated result of all consistency checks.

    Attributes
    ----------
    errors : list[str]
        Hard failures — transaction must be rejected.
    warnings : list[str]
        Soft issues — transaction may proceed, designer should be informed.
    type_results : list[TypeCheckResult]
        Per-field type check results for the builder UI diff viewer.
    conflict_reports : list[ConflictReport]
        Intra-transaction conflict reports.
    invariant_result : EnforcementResult | None
        Full invariant enforcement result.
    """

    errors:            list[str]             = field(default_factory=list)
    warnings:          list[str]             = field(default_factory=list)
    type_results:      list[TypeCheckResult] = field(default_factory=list)
    conflict_reports:  list[ConflictReport]  = field(default_factory=list)
    invariant_result:  EnforcementResult | None = None

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    def blocking_conflict_count(self) -> int:
        return sum(1 for r in self.conflict_reports if r.is_blocking)

    def type_error_count(self) -> int:
        return sum(1 for r in self.type_results if not r.is_valid)

    def merge_invariant_result(self, er: EnforcementResult) -> None:
        self.invariant_result = er
        for v in er.violations:
            if v.is_blocking:
                self.errors.append(v.message)
            else:
                self.warnings.append(v.message)

    def __repr__(self) -> str:
        status = "VALID" if self.is_valid else f"INVALID ({len(self.errors)} errors)"
        return f"ConsistencyReport({status}, {len(self.warnings)} warnings)"


# ── Consistency Validator ─────────────────────────────────────────────────────

class ConsistencyValidator:
    """
    Runs all pre-commit consistency checks against a proposed CGS mutation.

    One instance per GDE session — the PathResolver inside maintains
    a read cache that is invalidated on each validate() call (the proposed
    CGS is a new dict each time).

    Usage
    -----
        validator = ConsistencyValidator()
        report    = validator.validate(proposed_cgs, transaction, original_cgs)
        if not report.is_valid:
            raise ConsistencyError(report.errors)
    """

    def __init__(self) -> None:
        self._path_resolver    = PathResolver()
        self._type_checker     = TypeChecker()
        self._conflict_detector = ConflictDetector()
        self._invariant_enforcer = InvariantEnforcer()

    def validate(
        self,
        proposed_cgs:  dict[str, Any],
        transaction:   DSLTransaction,
        original_cgs:  dict[str, Any] | None = None,
    ) -> ConsistencyReport:
        """
        Validates a proposed CGS against the transaction that produced it.

        All sub-validators run regardless of earlier failures
        (full error list returned in one pass).

        Parameters
        ----------
        proposed_cgs : dict[str, Any]
            The CGS dict produced by TransactionExecutor.execute().
        transaction : DSLTransaction
            The transaction that was applied to produce proposed_cgs.
        original_cgs : dict[str, Any] | None
            The CGS before the transaction (used for delta comparison).

        Returns
        -------
        ConsistencyReport
            Aggregated validation result. is_valid=True means safe to commit.
        """
        report = ConsistencyReport()

        # Invalidate path cache — proposed_cgs is a new dict
        self._path_resolver.invalidate_cache()

        # ── 1. Intra-transaction conflict detection ───────────────────────────
        self._run_conflict_detection(transaction.operations, report)

        # ── 2. Path existence checks on proposed CGS ─────────────────────────
        self._run_path_checks(transaction.operations, proposed_cgs, report)

        # ── 3. Type checks for SET/ADD/MULTIPLY/DIVIDE operations ─────────────
        self._run_type_checks(transaction.operations, proposed_cgs, report)

        # ── 4. Invariant enforcement on proposed CGS ──────────────────────────
        er = self._invariant_enforcer.enforce(proposed_cgs)
        report.merge_invariant_result(er)

        return report

    def validate_cgs_only(self, cgs: dict[str, Any]) -> ConsistencyReport:
        """
        Validates a CGS dict without an associated transaction.
        Used for validating an imported or restored CGS before accepting it.
        """
        report = ConsistencyReport()
        self._path_resolver.invalidate_cache()
        er = self._invariant_enforcer.enforce(cgs)
        report.merge_invariant_result(er)
        return report

    # ── Sub-Validator Runners ─────────────────────────────────────────────────

    def _run_conflict_detection(
        self,
        operations: tuple[DSLOperation, ...],
        report:     ConsistencyReport,
    ) -> None:
        conflicts = self._conflict_detector.detect(operations)
        report.conflict_reports.extend(conflicts)
        for cr in conflicts:
            if cr.is_blocking:
                report.errors.append(cr.description)
            else:
                report.warnings.append(cr.description)

    def _run_path_checks(
        self,
        operations:   tuple[DSLOperation, ...],
        proposed_cgs: dict[str, Any],
        report:       ConsistencyReport,
    ) -> None:
        """
        For read operations (ADD, MULTIPLY, DELETE) the target must exist.
        For write operations (SET) the path may be new (write-mode resolution).
        Structural ops are not path-checked here — their targets are containers.
        """
        for op in operations:
            if op.is_structural:
                continue
            if op.op_type in (OpType.SET, OpType.APPEND):
                # Write-mode: leaf may be new — check parent exists
                try:
                    self._path_resolver.write(op.target, proposed_cgs)
                except Exception as exc:
                    report.errors.append(
                        f"[Path] Operation {op.operation_index} ({op.op_type}) "
                        f"parent path not found for '{op.target}': {exc}"
                    )
            elif op.op_type != OpType.DELETE:
                # Read-mode: leaf must exist
                if not self._path_resolver.exists(op.target, proposed_cgs):
                    report.errors.append(
                        f"[Path] Operation {op.operation_index} ({op.op_type}) "
                        f"target '{op.target}' does not exist in the proposed CGS. "
                        f"The operation may reference a path that was removed by "
                        f"an earlier operation in this transaction."
                    )

    def _run_type_checks(
        self,
        operations:   tuple[DSLOperation, ...],
        proposed_cgs: dict[str, Any],
        report:       ConsistencyReport,
    ) -> None:
        """
        Checks value type against type_hint for value-mutation operations.
        Skips ops without a declared type_hint or without a value.
        """
        for op in operations:
            if op.op_type not in (
                OpType.SET, OpType.ADD, OpType.MULTIPLY, OpType.DIVIDE
            ):
                continue
            if op.value is None or not op.type_hint:
                continue

            result = self._type_checker.check(op.value, op.type_hint, op.target)
            report.type_results.append(result)

            if not result.is_valid:
                report.errors.append(
                    f"[Type] Operation {op.operation_index} ({op.op_type}) "
                    f"at '{op.target}': {result.error}"
                )
            elif result.warning:
                report.warnings.append(
                    f"[Type] Operation {op.operation_index}: {result.warning}"
                )
            elif result.coercion_note:
                report.warnings.append(
                    f"[Type] Operation {op.operation_index} "
                    f"at '{op.target}': {result.coercion_note}"
                )