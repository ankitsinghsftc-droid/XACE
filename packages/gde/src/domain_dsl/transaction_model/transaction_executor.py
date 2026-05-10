"""
transaction_executor.py — TransactionExecutor
===============================================
Applies a validated DSLTransaction to a deep copy of the CGS.

This is the only place in the GDE where the CGS content actually changes.

## Atomicity Contract (I8)
TransactionExecutor works on a deep copy of the current CGS. If any
operation raises an error, the copy is discarded and the original CGS
is unchanged. The executor never partially modifies the stored CGS.

The flow is:
    1. Deep-copy current CGS → working copy
    2. Apply each operation to the working copy in order
    3. If all succeed → return working copy (CGSManager.commit() persists it)
    4. If any fail → raise TransactionExecutionError (working copy discarded)

## Execution of Each OpType

    SET target value        — parent[key] = value
    ADD target value        — parent[key] += value  (numeric)
    MULTIPLY target value   — parent[key] *= value  (numeric)
    DIVIDE target value     — parent[key] /= value  (numeric, non-zero)
    APPEND target value     — parent[key].append(value) (list)
    REMOVE target value     — parent[key].remove(value) (list, by value)
    DELETE target           — del parent[key]

    ADD_ACTOR target dict   — append dict to target list
    REMOVE_ACTOR target     — remove item with matching id from list
    ADD_COMPONENT target    — append component dict to actor["components"]
    REMOVE_COMPONENT target — remove component with matching type_id
    ADD_SYSTEM target dict  — append to global_systems or mode systems
    REMOVE_SYSTEM target    — remove system by id
    ADD_RULE target dict    — append to mode rules
    REMOVE_RULE target      — remove rule by id
    ADD_MODE target dict    — append to modes list
    REMOVE_MODE target      — remove mode by id

## PathResolver Usage
The executor uses PathResolver.write() for all operations, which tolerates
a missing leaf for ADD_*/APPEND operations but requires the parent to exist.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from ..path_addressing.path_resolver import PathResolver
from ...cgs.mutation_target_resolver import SchemaResolutionError
from .transaction_builder import (
    DSLTransaction, DSLOperation, OpType, TransactionBuildError
)


# ── Execution Error ───────────────────────────────────────────────────────────

@dataclass
class TransactionExecutionError(Exception):
    """
    Raised when a DSLTransaction cannot be fully applied.

    Attributes
    ----------
    operation_index : int
        The 0-based index of the operation that failed.
    operation : DSLOperation
        The failing operation.
    reason : str
        Human-readable explanation of the failure.
    """
    operation_index: int
    operation:       DSLOperation
    reason:          str

    def __str__(self) -> str:
        return (
            f"TransactionExecutionError at operation {self.operation_index} "
            f"({self.operation.op_type} '{self.operation.target}'): {self.reason}"
        )


# ── Transaction Executor ──────────────────────────────────────────────────────

class TransactionExecutor:
    """
    Applies DSLTransactions to a CGS copy atomically.

    One PathResolver is maintained per executor instance for the read cache.
    The cache is invalidated after each successful execution.

    Usage
    -----
        executor = TransactionExecutor()
        new_cgs  = executor.execute(transaction, current_cgs)
        # new_cgs is the mutated copy; current_cgs is untouched
    """

    def __init__(self) -> None:
        self._resolver = PathResolver()

    def execute(
        self,
        transaction: DSLTransaction,
        cgs:         dict[str, Any],
    ) -> dict[str, Any]:
        """
        Applies a DSLTransaction to a deep copy of cgs.

        Returns the mutated copy on full success.
        Raises TransactionExecutionError on any failure (original CGS untouched).

        Raises
        ------
        TransactionExecutionError
            If any operation cannot be applied.
        """
        # Deep copy — the original CGS is never touched (I8)
        working = copy.deepcopy(cgs)

        for op in transaction.operations:
            try:
                self._apply_operation(op, working)
            except TransactionExecutionError:
                raise
            except Exception as exc:
                raise TransactionExecutionError(
                    operation_index=op.operation_index,
                    operation=op,
                    reason=str(exc),
                ) from exc

        # Cache no longer valid after a write
        self._resolver.invalidate_cache()
        return working

    # ── Dispatcher ────────────────────────────────────────────────────────────

    def _apply_operation(
        self, op: DSLOperation, working: dict[str, Any]
    ) -> None:
        """Routes one DSLOperation to the appropriate apply method."""
        match op.op_type:
            # ── Value mutations ────────────────────────────────────────────────
            case OpType.SET:
                self._apply_set(op, working)
            case OpType.ADD:
                self._apply_numeric(op, working, lambda cur, v: cur + v)
            case OpType.MULTIPLY:
                self._apply_numeric(op, working, lambda cur, v: cur * v)
            case OpType.DIVIDE:
                if op.value == 0:
                    self._fail(op, "Division by zero.")
                self._apply_numeric(op, working, lambda cur, v: cur / v)
            case OpType.APPEND:
                self._apply_append(op, working)
            case OpType.REMOVE:
                self._apply_remove_from_list(op, working)
            case OpType.DELETE:
                self._apply_delete(op, working)
            # ── Structural adds ────────────────────────────────────────────────
            case OpType.ADD_ACTOR:
                self._apply_add_to_list(op, working, "actors", id_key="id")
            case OpType.ADD_SYSTEM:
                self._apply_add_system(op, working)
            case OpType.ADD_RULE:
                self._apply_add_to_list(op, working, "rules", id_key="id")
            case OpType.ADD_COMPONENT:
                self._apply_add_component(op, working)
            case OpType.ADD_MODE:
                self._apply_add_to_list(op, working, "modes", id_key="id")
            # ── Structural removes ─────────────────────────────────────────────
            case OpType.REMOVE_ACTOR:
                self._apply_remove_by_id(op, working, "actors")
            case OpType.REMOVE_SYSTEM:
                self._apply_remove_system(op, working)
            case OpType.REMOVE_RULE:
                self._apply_remove_by_id(op, working, "rules")
            case OpType.REMOVE_COMPONENT:
                self._apply_remove_component(op, working)
            case OpType.REMOVE_MODE:
                self._apply_remove_by_id(op, working, "modes")
            case _:
                self._fail(op, f"Unknown op_type '{op.op_type}'.")

    # ── Value Mutation Helpers ────────────────────────────────────────────────

    def _apply_set(self, op: DSLOperation, cgs: dict) -> None:
        """SET: parent[key] = value. Leaf may be new."""
        result = self._write_resolve(op, cgs)
        result.parent[result.key] = op.value

    def _apply_numeric(self, op: DSLOperation, cgs: dict, fn) -> None:
        """ADD/MULTIPLY/DIVIDE: parent[key] = fn(current, value)."""
        result = self._read_resolve(op, cgs)
        current = result.node
        if not isinstance(current, (int, float)):
            self._fail(
                op,
                f"Numeric operation on non-numeric value "
                f"'{current!r}' (type: {type(current).__name__}) at '{op.target}'.",
            )
        result.parent[result.key] = fn(current, op.value)

    def _apply_append(self, op: DSLOperation, cgs: dict) -> None:
        """APPEND: list at target gets op.value appended."""
        result = self._read_resolve(op, cgs)
        if not isinstance(result.node, list):
            self._fail(
                op,
                f"APPEND requires a list at '{op.target}', "
                f"got {type(result.node).__name__}.",
            )
        result.node.append(op.value)

    def _apply_remove_from_list(self, op: DSLOperation, cgs: dict) -> None:
        """REMOVE: removes op.value from the list at target."""
        result = self._read_resolve(op, cgs)
        if not isinstance(result.node, list):
            self._fail(op, f"REMOVE requires a list at '{op.target}'.")
        if op.value not in result.node:
            self._fail(
                op,
                f"Value {op.value!r} not found in list at '{op.target}'. "
                f"Cannot remove a value that doesn't exist.",
            )
        result.node.remove(op.value)

    def _apply_delete(self, op: DSLOperation, cgs: dict) -> None:
        """DELETE: removes the key from its parent dict."""
        result = self._read_resolve(op, cgs)
        if not isinstance(result.parent, dict):
            self._fail(op, f"DELETE requires a dict parent at '{op.target}'.")
        del result.parent[result.key]

    # ── Structural Mutation Helpers ───────────────────────────────────────────

    def _apply_add_to_list(
        self,
        op:     DSLOperation,
        cgs:    dict,
        list_key: str,
        id_key: str,
    ) -> None:
        """
        ADD_ACTOR / ADD_RULE / ADD_MODE:
        Resolves the parent container list and appends op.value (a dict).
        Rejects if an item with the same id_key already exists.
        """
        if not isinstance(op.value, dict):
            self._fail(op, f"ADD_{list_key.upper()} value must be a dict.")
        new_id = op.value.get(id_key)
        if not new_id:
            self._fail(
                op,
                f"ADD value dict must have a non-empty '{id_key}' field.",
            )
        # Resolve the parent container (e.g. "modes.mode_default.actors")
        result = self._write_resolve(op, cgs)
        container = result.node if result.exists else result.parent
        if not isinstance(container, list):
            # The target IS the list — check via parent
            container = result.parent
        if not isinstance(container, list):
            self._fail(op, f"ADD target must resolve to a list, got {type(container).__name__}.")
        # Duplicate check
        if any(item.get(id_key) == new_id for item in container if isinstance(item, dict)):
            self._fail(
                op,
                f"Item with {id_key}='{new_id}' already exists in the list at '{op.target}'. "
                f"Use a unique ID for new items.",
            )
        container.append(op.value)

    def _apply_add_system(self, op: DSLOperation, cgs: dict) -> None:
        """ADD_SYSTEM: appends to global_systems or a mode's systems list."""
        if not isinstance(op.value, dict):
            self._fail(op, "ADD_SYSTEM value must be a system definition dict.")
        sys_id = op.value.get("id")
        if not sys_id:
            self._fail(op, "System dict must have a non-empty 'id' field.")
        # Target path tells us WHERE — global or mode-specific
        target_lower = op.target.lower()
        if "global_systems" in target_lower:
            container = cgs.setdefault("global_systems", [])
        else:
            # Resolve to the mode's systems list
            result = self._write_resolve(op, cgs)
            container = result.node if result.exists and isinstance(result.node, list) else []
        if any(s.get("id") == sys_id for s in container if isinstance(s, dict)):
            self._fail(op, f"System '{sys_id}' already exists at '{op.target}'.")
        container.append(op.value)

    def _apply_add_component(self, op: DSLOperation, cgs: dict) -> None:
        """ADD_COMPONENT: appends a component dict to an actor's components list."""
        if not isinstance(op.value, dict):
            self._fail(op, "ADD_COMPONENT value must be a component dict.")
        type_id = op.value.get("type_id")
        if type_id is None:
            self._fail(op, "Component dict must have a 'type_id' field.")
        result = self._write_resolve(op, cgs)
        container = result.node if result.exists and isinstance(result.node, list) else None
        if container is None:
            # Target may be the actor — find components sub-list
            actor_result = self._read_resolve_path(op.target, cgs)
            container = actor_result.node.get("components") if isinstance(actor_result.node, dict) else None
        if not isinstance(container, list):
            self._fail(op, f"Cannot resolve components list at '{op.target}'.")
        if any(c.get("type_id") == type_id for c in container if isinstance(c, dict)):
            self._fail(op, f"Component type_id {type_id} already exists on this actor.")
        container.append(op.value)

    def _apply_remove_by_id(
        self, op: DSLOperation, cgs: dict, list_key: str
    ) -> None:
        """REMOVE_ACTOR / REMOVE_RULE / REMOVE_MODE: removes item by id from list."""
        result = self._write_resolve(op, cgs)
        container = result.parent if isinstance(result.parent, list) else None
        if container is None:
            self._fail(op, f"Cannot resolve list container at '{op.target}'.")
        target_id = result.node.get("id") if isinstance(result.node, dict) else None
        if target_id is None:
            self._fail(op, f"Target item at '{op.target}' has no 'id' field.")
        original_len = len(container)
        container[:] = [
            item for item in container
            if not (isinstance(item, dict) and item.get("id") == target_id)
        ]
        if len(container) == original_len:
            self._fail(op, f"Item with id='{target_id}' not found at '{op.target}'.")

    def _apply_remove_system(self, op: DSLOperation, cgs: dict) -> None:
        """REMOVE_SYSTEM: removes system by id from global or mode systems."""
        result = self._write_resolve(op, cgs)
        if not isinstance(result.node, dict):
            self._fail(op, f"System at '{op.target}' is not a dict.")
        sys_id = result.node.get("id")
        container = result.parent if isinstance(result.parent, list) else None
        if not container:
            self._fail(op, f"Cannot resolve systems list at '{op.target}'.")
        container[:] = [s for s in container if s.get("id") != sys_id]

    def _apply_remove_component(self, op: DSLOperation, cgs: dict) -> None:
        """REMOVE_COMPONENT: removes component by type_id from actor components."""
        result = self._write_resolve(op, cgs)
        if not isinstance(result.node, dict):
            self._fail(op, f"Component at '{op.target}' is not a dict.")
        type_id  = result.node.get("type_id")
        container = result.parent if isinstance(result.parent, list) else None
        if not container:
            self._fail(op, f"Cannot resolve components list at '{op.target}'.")
        container[:] = [c for c in container if c.get("type_id") != type_id]

    # ── Resolution Shortcuts ──────────────────────────────────────────────────

    def _read_resolve(self, op: DSLOperation, cgs: dict):
        try:
            return self._resolver.read(op.target, cgs)
        except SchemaResolutionError as exc:
            self._fail(op, str(exc))

    def _write_resolve(self, op: DSLOperation, cgs: dict):
        try:
            return self._resolver.write(op.target, cgs)
        except SchemaResolutionError as exc:
            self._fail(op, str(exc))

    def _read_resolve_path(self, path: str, cgs: dict):
        try:
            return self._resolver.read(path, cgs)
        except SchemaResolutionError as exc:
            raise SchemaResolutionError(str(exc)) from exc

    @staticmethod
    def _fail(op: DSLOperation, reason: str) -> None:
        raise TransactionExecutionError(
            operation_index=op.operation_index,
            operation=op,
            reason=reason,
        )