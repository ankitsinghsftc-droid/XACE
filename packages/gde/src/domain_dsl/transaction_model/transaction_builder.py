"""
transaction_builder.py — DSLOperation, DSLTransaction, TransactionBuilder
===========================================================================
Defines the atomic mutation unit of the GDE and the builder that
assembles ordered DSL operations into a validated DSLTransaction.

## DSLOperation
One atomic instruction targeting a single CGS node:
    op_type : SET | ADD | REMOVE | MULTIPLY | DIVIDE | APPEND | DELETE
              ADD_ACTOR | ADD_SYSTEM | ADD_RULE | ADD_COMPONENT
              REMOVE_ACTOR | REMOVE_SYSTEM | REMOVE_RULE | REMOVE_COMPONENT
    target  : fully-qualified CGS path (validated by PathParser before building)
    value   : new value for SET/ADD/MULTIPLY/DIVIDE/APPEND/ADD_* operations
    type_hint: optional declared type ("float", "int", "str", etc.)

## DSLTransaction
An ordered, atomic list of DSLOperations plus provenance metadata.
Mirrors xace_core::mutation::mutation_transaction::MutationTransaction (Rust).
The Python version is the design-time representation; the Rust version is
the runtime-applied form.

Atomicity contract (I8):
    Either ALL operations in a transaction succeed → new CGS committed,
    OR ANY operation fails → original CGS preserved, no partial state.

## TransactionBuilder
Fluent builder that accumulates operations, validates internal consistency,
and produces a sealed DSLTransaction. After build() is called the builder
is reset — each build produces one transaction.

## Validation Performed by Builder
    V1 — No duplicate target paths within one transaction (SET x=10 and SET x=5
         in the same transaction is always a bug or a conflict)
    V2 — Every path parses structurally (PathParser validates)
    V3 — Value type is consistent with type_hint when declared
    V4 — No operation targets the metadata.cgs_hash field directly
         (the hash is managed by CGSManager, not by mutations)
    V5 — Transaction must have at least one operation
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from ..path_addressing.path_parser import PathParser, PathParseError

if TYPE_CHECKING:
    from ..mutation_metadata.mutation_metadata_model import MutationMetadata


# ── Operation Types ───────────────────────────────────────────────────────────

class OpType:
    """String constants for all valid DSL operation types."""
    # Value mutations
    SET         = "SET"
    ADD         = "ADD"          # numeric add (+=)
    REMOVE      = "REMOVE"       # remove from list (by value)
    MULTIPLY    = "MULTIPLY"     # numeric multiply (*=)
    DIVIDE      = "DIVIDE"       # numeric divide (/=)
    APPEND      = "APPEND"       # append to list
    DELETE      = "DELETE"       # delete leaf key from dict

    # Structural mutations — add new nodes
    ADD_ACTOR       = "ADD_ACTOR"
    ADD_SYSTEM      = "ADD_SYSTEM"
    ADD_RULE        = "ADD_RULE"
    ADD_COMPONENT   = "ADD_COMPONENT"
    ADD_MODE        = "ADD_MODE"

    # Structural mutations — remove existing nodes
    REMOVE_ACTOR        = "REMOVE_ACTOR"
    REMOVE_SYSTEM       = "REMOVE_SYSTEM"
    REMOVE_RULE         = "REMOVE_RULE"
    REMOVE_COMPONENT    = "REMOVE_COMPONENT"
    REMOVE_MODE         = "REMOVE_MODE"

    @classmethod
    def all_valid(cls) -> frozenset[str]:
        return frozenset({
            cls.SET, cls.ADD, cls.REMOVE, cls.MULTIPLY, cls.DIVIDE,
            cls.APPEND, cls.DELETE,
            cls.ADD_ACTOR, cls.ADD_SYSTEM, cls.ADD_RULE,
            cls.ADD_COMPONENT, cls.ADD_MODE,
            cls.REMOVE_ACTOR, cls.REMOVE_SYSTEM, cls.REMOVE_RULE,
            cls.REMOVE_COMPONENT, cls.REMOVE_MODE,
        })

    @classmethod
    def structural_adds(cls) -> frozenset[str]:
        return frozenset({
            cls.ADD_ACTOR, cls.ADD_SYSTEM, cls.ADD_RULE,
            cls.ADD_COMPONENT, cls.ADD_MODE,
        })

    @classmethod
    def structural_removes(cls) -> frozenset[str]:
        return frozenset({
            cls.REMOVE_ACTOR, cls.REMOVE_SYSTEM, cls.REMOVE_RULE,
            cls.REMOVE_COMPONENT, cls.REMOVE_MODE,
        })

    @classmethod
    def numeric_ops(cls) -> frozenset[str]:
        return frozenset({cls.ADD, cls.MULTIPLY, cls.DIVIDE})


# ── Transaction Build Error ───────────────────────────────────────────────────

class TransactionBuildError(Exception):
    """Raised when TransactionBuilder.build() encounters validation errors."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(
            f"TransactionBuilder: {len(errors)} error(s):\n"
            + "\n".join(f"  [{i+1}] {e}" for i, e in enumerate(errors))
        )


# ── DSL Operation ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DSLOperation:
    """
    One atomic instruction in a DSLTransaction.

    Attributes
    ----------
    op_type : str
        Operation type from OpType constants.
    target : str
        Fully-qualified CGS path. Must be structurally valid (PathParser checked).
    value : Any
        New value for the operation. None for DELETE/structural-remove operations.
    type_hint : str
        Optional declared type for the value field. Used by TypeChecker.
        Examples: "float", "int", "str", "bool", "dict", "list[str]"
    operation_index : int
        0-based position in the parent transaction. Set by TransactionBuilder.
    description : str
        Human-readable description of this one step. Generated by PIL.
    """

    op_type:          str
    target:           str
    value:            Any    = None
    type_hint:        str    = ""
    operation_index:  int    = 0
    description:      str    = ""

    @property
    def is_structural(self) -> bool:
        return (
            self.op_type in OpType.structural_adds()
            or self.op_type in OpType.structural_removes()
        )

    @property
    def is_destructive(self) -> bool:
        return (
            self.op_type in OpType.structural_removes()
            or self.op_type == OpType.DELETE
        )

    @property
    def is_numeric(self) -> bool:
        return self.op_type in OpType.numeric_ops()

    def __repr__(self) -> str:
        val_repr = f"={self.value!r}" if self.value is not None else ""
        return f"DSLOperation({self.op_type} {self.target!r}{val_repr})"


# ── DSL Transaction ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DSLTransaction:
    """
    Ordered, atomic list of DSLOperations.

    Immutable after creation — produced by TransactionBuilder.build().
    Consumed by TransactionExecutor.execute().

    Attributes
    ----------
    transaction_id : str
        UUID4 hex. Matches MutationMetadata.transaction_id.
    operations : tuple[DSLOperation, ...]
        Ordered operations to apply atomically.
    metadata : MutationMetadata
        Provenance record for this transaction.
    schema_version_target : str
        CGS version this transaction targets. Verified before execution.
    atomic : bool
        Always True. All-or-nothing application is non-negotiable (I8).
    """

    transaction_id:        str
    operations:            tuple[DSLOperation, ...]
    metadata:              "MutationMetadata"
    schema_version_target: str
    atomic:                bool                     = True

    def operation_count(self) -> int:
        return len(self.operations)

    def has_destructive_operations(self) -> bool:
        return any(op.is_destructive for op in self.operations)

    def has_structural_changes(self) -> bool:
        return any(op.is_structural for op in self.operations)

    def all_targets(self) -> list[str]:
        return [op.target for op in self.operations]

    def __repr__(self) -> str:
        return (
            f"DSLTransaction(id={self.transaction_id[:8]}, "
            f"ops={self.operation_count()}, "
            f"v={self.schema_version_target})"
        )


# ── Transaction Builder ───────────────────────────────────────────────────────

class TransactionBuilder:
    """
    Fluent builder for DSLTransactions.

    Accumulates operations, then validates and seals them into an
    immutable DSLTransaction on build().

    Usage
    -----
        txn = (
            TransactionBuilder(metadata)
            .set("modes.mode_default.actors.actor_player.components.100.defaults.current", 80.0)
            .set("modes.mode_default.actors.actor_player.components.100.defaults.max",     80.0)
            .build()
        )
    """

    def __init__(self, metadata: "MutationMetadata") -> None:
        self._metadata   = metadata
        self._operations: list[DSLOperation] = []
        self._parser     = PathParser()

    # ── Fluent Operation Methods ──────────────────────────────────────────────

    def add_operation(self, operation: DSLOperation) -> "TransactionBuilder":
        """Adds a pre-built DSLOperation to the transaction."""
        self._operations.append(operation)
        return self

    def set(
        self, target: str, value: Any, type_hint: str = "", description: str = ""
    ) -> "TransactionBuilder":
        return self._op(OpType.SET, target, value, type_hint, description)

    def add(
        self, target: str, value: Any, type_hint: str = "float", description: str = ""
    ) -> "TransactionBuilder":
        return self._op(OpType.ADD, target, value, type_hint, description)

    def multiply(
        self, target: str, value: Any, description: str = ""
    ) -> "TransactionBuilder":
        return self._op(OpType.MULTIPLY, target, value, "float", description)

    def divide(
        self, target: str, value: Any, description: str = ""
    ) -> "TransactionBuilder":
        return self._op(OpType.DIVIDE, target, value, "float", description)

    def append(
        self, target: str, value: Any, type_hint: str = "", description: str = ""
    ) -> "TransactionBuilder":
        return self._op(OpType.APPEND, target, value, type_hint, description)

    def delete(self, target: str, description: str = "") -> "TransactionBuilder":
        return self._op(OpType.DELETE, target, None, "", description)

    def remove_from_list(
        self, target: str, value: Any, description: str = ""
    ) -> "TransactionBuilder":
        return self._op(OpType.REMOVE, target, value, "", description)

    def add_actor(
        self, target: str, actor_dict: dict, description: str = ""
    ) -> "TransactionBuilder":
        return self._op(OpType.ADD_ACTOR, target, actor_dict, "dict", description)

    def remove_actor(self, target: str, description: str = "") -> "TransactionBuilder":
        return self._op(OpType.REMOVE_ACTOR, target, None, "", description)

    def add_component(
        self, target: str, component_dict: dict, description: str = ""
    ) -> "TransactionBuilder":
        return self._op(OpType.ADD_COMPONENT, target, component_dict, "dict", description)

    def remove_component(self, target: str, description: str = "") -> "TransactionBuilder":
        return self._op(OpType.REMOVE_COMPONENT, target, None, "", description)

    def add_rule(
        self, target: str, rule_dict: dict, description: str = ""
    ) -> "TransactionBuilder":
        return self._op(OpType.ADD_RULE, target, rule_dict, "dict", description)

    def remove_rule(self, target: str, description: str = "") -> "TransactionBuilder":
        return self._op(OpType.REMOVE_RULE, target, None, "", description)

    def add_system(
        self, target: str, system_dict: dict, description: str = ""
    ) -> "TransactionBuilder":
        return self._op(OpType.ADD_SYSTEM, target, system_dict, "dict", description)

    # ── Build ─────────────────────────────────────────────────────────────────

    def build(self) -> DSLTransaction:
        """
        Validates accumulated operations and returns an immutable DSLTransaction.

        Raises
        ------
        TransactionBuildError
            If any validation check fails. All errors are collected first.
        """
        errors = self._validate()
        if errors:
            raise TransactionBuildError(errors)

        indexed_ops = tuple(
            DSLOperation(
                op_type=op.op_type,
                target=op.target,
                value=op.value,
                type_hint=op.type_hint,
                operation_index=i,
                description=op.description,
            )
            for i, op in enumerate(self._operations)
        )

        txn = DSLTransaction(
            transaction_id=self._metadata.transaction_id,
            operations=indexed_ops,
            metadata=self._metadata,
            schema_version_target=self._metadata.schema_version_target,
        )

        # Reset builder after successful build
        self._operations.clear()
        return txn

    # ── Internal ──────────────────────────────────────────────────────────────

    def _op(
        self,
        op_type:     str,
        target:      str,
        value:       Any,
        type_hint:   str,
        description: str,
    ) -> "TransactionBuilder":
        self._operations.append(DSLOperation(
            op_type=op_type, target=target, value=value,
            type_hint=type_hint, description=description,
        ))
        return self

    def _validate(self) -> list[str]:
        errors: list[str] = []

        # V5 — At least one operation
        if not self._operations:
            errors.append(
                "Transaction must contain at least one operation. "
                "Empty transactions are not permitted."
            )
            return errors

        seen_targets: dict[str, str] = {}   # target → first op_type

        for i, op in enumerate(self._operations):
            tag = f"[op {i}]"

            # Validate op_type
            if op.op_type not in OpType.all_valid():
                errors.append(
                    f"{tag} Unknown op_type '{op.op_type}'. "
                    f"Valid types: {sorted(OpType.all_valid())}"
                )

            # V2 — Structural path validation
            try:
                self._parser.parse(op.target)
            except PathParseError as exc:
                errors.append(f"{tag} Path parse error: {exc}")

            # V4 — Cannot target cgs_hash directly
            if "metadata.cgs_hash" in op.target:
                errors.append(
                    f"{tag} Mutation target '{op.target}' targets "
                    f"metadata.cgs_hash which is managed by CGSManager. "
                    f"This field cannot be mutated via a DSL operation."
                )

            # V1 — Duplicate target check (value mutations only)
            if not op.is_structural:
                if op.target in seen_targets:
                    errors.append(
                        f"{tag} Duplicate target '{op.target}' (also targeted by "
                        f"op_type '{seen_targets[op.target]}'). "
                        f"Mutating the same path twice in one transaction is a conflict."
                    )
                else:
                    seen_targets[op.target] = op.op_type

            # V3 — Value type consistency with type_hint
            if op.type_hint and op.value is not None:
                type_error = _check_type_hint(op.value, op.type_hint)
                if type_error:
                    errors.append(f"{tag} {type_error}")

        return errors


# ── Type Hint Checker ─────────────────────────────────────────────────────────

def _check_type_hint(value: Any, type_hint: str) -> str | None:
    """
    Returns an error string if value is inconsistent with type_hint.
    Returns None if the value is acceptable.
    """
    match type_hint:
        case "float":
            if not isinstance(value, (int, float)):
                return (
                    f"Expected float, got {type(value).__name__} ({value!r})."
                )
        case "int":
            if not isinstance(value, int) or isinstance(value, bool):
                return (
                    f"Expected int, got {type(value).__name__} ({value!r})."
                )
        case "str":
            if not isinstance(value, str):
                return (
                    f"Expected str, got {type(value).__name__} ({value!r})."
                )
        case "bool":
            if not isinstance(value, bool):
                return (
                    f"Expected bool, got {type(value).__name__} ({value!r})."
                )
        case "dict":
            if not isinstance(value, dict):
                return (
                    f"Expected dict, got {type(value).__name__} ({value!r})."
                )
        case "list" | "list[str]" | "list[int]" | "list[float]":
            if not isinstance(value, list):
                return (
                    f"Expected list, got {type(value).__name__} ({value!r})."
                )
    return None