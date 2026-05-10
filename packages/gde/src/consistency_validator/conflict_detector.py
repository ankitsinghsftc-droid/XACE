"""
conflict_detector.py — ConflictDetector
=========================================
Detects conflicting operations within a single DSLTransaction before
it is applied to the CGS.

## What Is a Conflict?
A conflict is a logical contradiction within one transaction — operations
that cannot both be meaningfully applied at the same time.

## Conflict Types

    DUPLICATE_SET   — same path SET to two different values in the same txn
                      (SET health=80 + SET health=60 → which wins?)

    CONTRADICTORY_REMOVE — ADD an actor then REMOVE_ACTOR it in the same txn
                           (net effect is nothing — probably a prompt error)

    SELF_CANCELLING     — ADD +10 and REMOVE -10 on the same numeric path
                          (net effect is zero — almost certainly a bug)

    NUMERIC_IMPOSSIBLE  — MULTIPLY 0 on a path that must be nonzero per design

    RANGE_CONFLICT      — SET a value that violates min > max on related paths
                          (SET health.max = 50 when SET health.current = 80)

## Detection Strategy
The detector scans the operation list in declaration order.
It builds an operation index keyed by target path and checks:
    1. Duplicate paths for value mutations (DUPLICATE_SET)
    2. ADD followed by REMOVE_* for the same entity ID (CONTRADICTORY_REMOVE)
    3. Numeric self-cancelling pairs (SELF_CANCELLING)
    4. Health/max vs health/current ordering violations (RANGE_CONFLICT)

## Output
Returns a list of ConflictReport objects. Each describes one conflict,
its severity (error vs warning), and the involved operation indices.
ConflictDetector does NOT block — it returns reports; ConsistencyValidator
decides whether to fail based on severity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain_dsl.transaction_model.transaction_builder import DSLOperation, OpType


# ── Conflict Report ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ConflictReport:
    """
    Describes one detected conflict between operations.

    Attributes
    ----------
    conflict_type : str
        One of: DUPLICATE_SET, CONTRADICTORY_REMOVE, SELF_CANCELLING,
                NUMERIC_IMPOSSIBLE, RANGE_CONFLICT
    operation_indices : tuple[int, ...]
        Indices of the conflicting operations in the transaction.
    target_paths : tuple[str, ...]
        The CGS paths involved in the conflict.
    description : str
        Plain-English explanation of the conflict.
    severity : str
        "error" — the transaction should be rejected.
        "warning" — suspicious but may be intentional.
    """

    conflict_type:     str
    operation_indices: tuple[int, ...]
    target_paths:      tuple[str, ...]
    description:       str
    severity:          str   = "error"   # "error" | "warning"

    @property
    def is_blocking(self) -> bool:
        return self.severity == "error"

    def __repr__(self) -> str:
        return (
            f"ConflictReport({self.conflict_type}, "
            f"ops={list(self.operation_indices)}, "
            f"severity={self.severity})"
        )


# ── Conflict Detector ─────────────────────────────────────────────────────────

class ConflictDetector:
    """
    Detects logical conflicts within a DSLTransaction operation list.

    Stateless — call detect() once per transaction. All operations are
    scanned before any report is returned.

    Usage
    -----
        detector = ConflictDetector()
        reports  = detector.detect(transaction.operations)
        errors   = [r for r in reports if r.is_blocking]
    """

    def detect(
        self, operations: tuple[DSLOperation, ...]
    ) -> list[ConflictReport]:
        """
        Scans all operations and returns all detected conflicts.

        Parameters
        ----------
        operations : tuple[DSLOperation, ...]
            The operations from a DSLTransaction, in declaration order.

        Returns
        -------
        list[ConflictReport]
            All detected conflicts. May be empty (no conflicts).
        """
        reports: list[ConflictReport] = []

        reports.extend(self._detect_duplicate_sets(operations))
        reports.extend(self._detect_contradictory_structural(operations))
        reports.extend(self._detect_self_cancelling(operations))
        reports.extend(self._detect_range_conflicts(operations))

        return reports

    # ── Duplicate SET ─────────────────────────────────────────────────────────

    @staticmethod
    def _detect_duplicate_sets(
        operations: tuple[DSLOperation, ...]
    ) -> list[ConflictReport]:
        """DUPLICATE_SET — same path SET to two different values."""
        reports:   list[ConflictReport]  = []
        path_ops:  dict[str, list[int]]  = {}

        for op in operations:
            if op.op_type in (OpType.SET,) and not op.is_structural:
                path_ops.setdefault(op.target, []).append(op.operation_index)

        for path, indices in sorted(path_ops.items()):
            if len(indices) <= 1:
                continue
            # Get values at each occurrence
            values = [operations[i].value for i in indices if i < len(operations)]
            if len(set(str(v) for v in values)) > 1:
                reports.append(ConflictReport(
                    conflict_type="DUPLICATE_SET",
                    operation_indices=tuple(indices),
                    target_paths=(path,),
                    description=(
                        f"Path '{path}' is SET to {len(indices)} different values "
                        f"({values}) in the same transaction. "
                        f"Only the last SET would take effect — this is likely a prompt error. "
                        f"Remove the conflicting operations or split into separate transactions."
                    ),
                    severity="error",
                ))

        return reports

    # ── Contradictory Structural ──────────────────────────────────────────────

    @staticmethod
    def _detect_contradictory_structural(
        operations: tuple[DSLOperation, ...]
    ) -> list[ConflictReport]:
        """
        CONTRADICTORY_REMOVE — ADD_ACTOR then REMOVE_ACTOR on the same entity.
        Net effect is no change; this is almost certainly a prompt error.
        """
        reports: list[ConflictReport] = []

        add_paths:    dict[str, int] = {}
        remove_paths: dict[str, int] = {}

        for op in operations:
            if op.op_type in OpType.structural_adds():
                add_paths[op.target] = op.operation_index
            elif op.op_type in OpType.structural_removes():
                remove_paths[op.target] = op.operation_index

        for path in sorted(set(add_paths) & set(remove_paths)):
            add_idx    = add_paths[path]
            remove_idx = remove_paths[path]
            reports.append(ConflictReport(
                conflict_type="CONTRADICTORY_REMOVE",
                operation_indices=(add_idx, remove_idx),
                target_paths=(path,),
                description=(
                    f"Transaction adds and then removes the same node at '{path}'. "
                    f"The net effect is no change — both operations cancel each other out. "
                    f"This is likely a prompt misunderstanding. Remove both operations "
                    f"or keep only the one that matches the design intent."
                ),
                severity="error",
            ))

        return reports

    # ── Self-Cancelling Numeric ───────────────────────────────────────────────

    @staticmethod
    def _detect_self_cancelling(
        operations: tuple[DSLOperation, ...]
    ) -> list[ConflictReport]:
        """
        SELF_CANCELLING — ADD +N then ADD -N (or vice versa) on same path.
        Net effect is zero change.
        """
        reports:  list[ConflictReport] = []
        add_ops:  dict[str, list[tuple[int, Any]]] = {}

        for op in operations:
            if op.op_type == OpType.ADD and isinstance(op.value, (int, float)):
                add_ops.setdefault(op.target, []).append(
                    (op.operation_index, op.value)
                )

        for path, entries in sorted(add_ops.items()):
            if len(entries) < 2:
                continue
            total = sum(v for _, v in entries)
            if total == 0:
                indices = tuple(i for i, _ in entries)
                reports.append(ConflictReport(
                    conflict_type="SELF_CANCELLING",
                    operation_indices=indices,
                    target_paths=(path,),
                    description=(
                        f"The ADD operations on '{path}' sum to zero "
                        f"({[v for _, v in entries]}). "
                        f"This change has no net effect. "
                        f"Verify the signs of the values are correct."
                    ),
                    severity="warning",
                ))

        return reports

    # ── Range Conflict ────────────────────────────────────────────────────────

    @staticmethod
    def _detect_range_conflicts(
        operations: tuple[DSLOperation, ...]
    ) -> list[ConflictReport]:
        """
        RANGE_CONFLICT — detects health.current > health.max within same txn.
        Only checks paths that end in known min/max field pairs.
        """
        reports: list[ConflictReport] = []

        _ORDERED_PAIRS = [
            ("current", "max"),    # health.current must be <= health.max
        ]

        # Index all SET operations by path
        set_values: dict[str, tuple[int, Any]] = {}
        for op in operations:
            if op.op_type == OpType.SET and op.value is not None:
                set_values[op.target] = (op.operation_index, op.value)

        # For each pair, look for both members being SET in the same txn
        for lo_field, hi_field in _ORDERED_PAIRS:
            lo_paths = {
                p for p in set_values
                if p.endswith(f".{lo_field}")
            }
            for lo_path in sorted(lo_paths):
                hi_path = lo_path[: -len(lo_field)] + hi_field
                if hi_path not in set_values:
                    continue

                lo_idx, lo_val = set_values[lo_path]
                hi_idx, hi_val = set_values[hi_path]

                if not isinstance(lo_val, (int, float)) or \
                   not isinstance(hi_val, (int, float)):
                    continue

                if lo_val > hi_val:
                    reports.append(ConflictReport(
                        conflict_type="RANGE_CONFLICT",
                        operation_indices=(lo_idx, hi_idx),
                        target_paths=(lo_path, hi_path),
                        description=(
                            f"Transaction sets {lo_field}={lo_val} > {hi_field}={hi_val} "
                            f"at '{lo_path[:-len(lo_field)].rstrip('.')}'. "
                            f"The {lo_field} value must not exceed {hi_field}. "
                            f"Adjust the values so {lo_field} ≤ {hi_field}."
                        ),
                        severity="error",
                    ))

        return reports