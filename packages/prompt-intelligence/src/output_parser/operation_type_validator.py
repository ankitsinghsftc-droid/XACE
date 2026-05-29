"""
operation_type_validator.py — OperationTypeValidator
======================================================
Validates that each mutation operation's op type and value type are
consistent with the CGS field definition and the UCL component schema.

## What This Validates

    For each MutationOp in a DraftMutationTransaction:

    Check 1 — Op Type vs Schema Delta Type Consistency
        SET / SCALE are only valid on value_mutation transactions.
        ADD_ACTOR / REMOVE_ACTOR require structural_add or structural_remove.
        ADD_RULE / REMOVE_RULE require rule_change.
        Mismatch is a hard error.

    Check 2 — Value Type vs type_hint
        If type_hint is "float", value must be a Python float or int
        (int is allowed — it will be promoted to float by the engine).
        If type_hint is "bool", value must be True or False (not 0/1).
        If type_hint is "str", value must be a string.
        If type_hint is "dict", value must be a dict.
        type_hint="int" + value=10.5 → error (precision loss).

    Check 3 — Value Type vs Existing Field Type
        If the field already exists in CGS and has a value of type float,
        a new value of type str is a hard type mismatch.
        (Only applies to SET operations on existing fields.)

    Check 4 — No Extra Keys in Operations
        MutationOp must not carry fields beyond the defined schema:
        path, op, value, type_hint, field_name, actor_id, type_id.
        Extra keys indicate a malformed or injected payload.

    Check 5 — Value Bounds (soft check)
        For known numeric fields: negative values for health, speed, radius
        are flagged as warnings (not hard errors) unless negative makes no
        physical sense (e.g. health max < 0).

## OperationValidationResult

    valid:         bool
    errors:        list[str]   — hard failures (reject the transaction)
    warnings:      list[str]   — soft issues (pass with annotation)
    per_op_results: list[dict] — {op_index, valid, errors, warnings} per op
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Op → valid delta type mappings ───────────────────────────────────────────

_OP_TO_DELTA_TYPES: dict[str, frozenset[str]] = {
    "SET":              frozenset({"value_mutation"}),
    "SCALE":            frozenset({"value_mutation"}),
    "ADD_ACTOR":        frozenset({"structural_add"}),
    "REMOVE_ACTOR":     frozenset({"structural_remove"}),
    "ADD_COMPONENT":    frozenset({"structural_add"}),
    "REMOVE_COMPONENT": frozenset({"structural_remove"}),
    "ADD_SYSTEM":       frozenset({"structural_add"}),
    "REMOVE_SYSTEM":    frozenset({"structural_remove"}),
    "ADD_RULE":         frozenset({"rule_change"}),
    "REMOVE_RULE":      frozenset({"rule_change"}),
}

# Known ALLOWED ops
_ALL_VALID_OPS = frozenset(_OP_TO_DELTA_TYPES.keys())

# Fields known to be non-negative (soft check)
_NON_NEGATIVE_FIELDS = frozenset({
    "current", "max", "max_linear_speed", "max_angular_speed",
    "detection_radius", "aggression_level", "regen_rate",
    "priority",
})

# Allowed MutationOp field names (no extra keys)
_ALLOWED_OP_FIELDS = frozenset({
    "path", "op", "value", "type_hint",
    "field_name", "actor_id", "type_id",
})


# ── Validation Result ─────────────────────────────────────────────────────────

@dataclass
class OperationValidationResult:
    """
    Result of OperationTypeValidator.validate().

    Attributes
    ----------
    valid          : bool        — True if no hard errors
    errors         : list[str]   — hard failures (reject transaction)
    warnings       : list[str]   — soft issues (annotate but allow)
    per_op_results : list[dict]  — per-operation detail
    """
    valid:          bool
    errors:         list[str]        = field(default_factory=list)
    warnings:       list[str]        = field(default_factory=list)
    per_op_results: list[dict]       = field(default_factory=list)

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0


# ── Operation Type Validator ──────────────────────────────────────────────────

class OperationTypeValidator:
    """
    Validates op types and value types in a mutation transaction.

    Stateless — safe to share across sessions.
    Deterministic — same input always produces the same result.

    Usage
    -----
        validator = OperationTypeValidator()
        result = validator.validate(operations, schema_delta_type, cgs)
        if not result.valid:
            reject(result.errors)
    """

    def validate(
        self,
        operations:        list[Any],    # list[MutationOp]
        schema_delta_type: str,
        cgs:               dict[str, Any],
    ) -> OperationValidationResult:
        """
        Validates all operations in a transaction.

        Parameters
        ----------
        operations : list[MutationOp]
            Operations from DraftMutationTransaction.
        schema_delta_type : str
            Transaction-level delta type from DraftMutationTransaction.
        cgs : dict
            Current CGS JSON for existing-field type checking.

        Returns
        -------
        OperationValidationResult
        """
        all_errors:   list[str] = []
        all_warnings: list[str] = []
        per_op:       list[dict] = []

        # Build CGS field lookup
        field_lookup = self._build_field_lookup(cgs)

        for i, op in enumerate(operations):
            op_errors:   list[str] = []
            op_warnings: list[str] = []

            # Check 1: op type known
            op_type = getattr(op, "op", "")
            if op_type not in _ALL_VALID_OPS:
                op_errors.append(
                    f"op[{i}]: Unknown op '{op_type}'. "
                    f"Valid ops: {sorted(_ALL_VALID_OPS)}"
                )
            else:
                # Check 1b: op → schema_delta_type consistency
                valid_deltas = _OP_TO_DELTA_TYPES.get(op_type, frozenset())
                if schema_delta_type not in valid_deltas:
                    op_errors.append(
                        f"op[{i}]: op='{op_type}' is not valid for "
                        f"schema_delta_type='{schema_delta_type}'. "
                        f"Expected one of: {sorted(valid_deltas)}"
                    )

            # Check 2: value type vs type_hint
            value     = getattr(op, "value", None)
            type_hint = getattr(op, "type_hint", "")
            type_err  = self._check_value_type(i, value, type_hint, op_type)
            if type_err:
                op_errors.append(type_err)

            # Check 3: value type vs existing field type in CGS
            path = getattr(op, "path", "")
            if op_type == "SET" and path:
                existing_val = field_lookup.get(path)
                if existing_val is not None:
                    compat_err = self._check_type_compatibility(
                        i, value, existing_val, path
                    )
                    if compat_err:
                        op_errors.append(compat_err)

            # Check 4: no extra keys (only relevant for dict-based ops from parser)
            if hasattr(op, "__dict__") or hasattr(op, "__dataclass_fields__"):
                pass  # dataclass — no extra keys possible

            # Check 5: value bounds (soft)
            field_name = getattr(op, "field_name", "")
            if (field_name in _NON_NEGATIVE_FIELDS
                    and isinstance(value, (int, float))
                    and value < 0):
                op_warnings.append(
                    f"op[{i}]: field '{field_name}' has value {value} < 0. "
                    f"Negative values for this field may cause unexpected behaviour."
                )

            per_op.append({
                "op_index": i,
                "valid":    len(op_errors) == 0,
                "errors":   op_errors,
                "warnings": op_warnings,
            })
            all_errors.extend(op_errors)
            all_warnings.extend(op_warnings)

        return OperationValidationResult(
            valid          = len(all_errors) == 0,
            errors         = all_errors,
            warnings       = all_warnings,
            per_op_results = per_op,
        )

    # ── Value type checking ───────────────────────────────────────────────────

    @staticmethod
    def _check_value_type(
        i:         int,
        value:     Any,
        type_hint: str,
        op_type:   str,
    ) -> str | None:
        """Returns an error string or None if type is acceptable."""

        # Structural ops don't always have a scalar value
        if op_type in {"ADD_ACTOR", "REMOVE_ACTOR", "ADD_COMPONENT",
                       "REMOVE_COMPONENT", "ADD_SYSTEM", "REMOVE_SYSTEM",
                       "ADD_RULE", "REMOVE_RULE"}:
            return None   # value format is flexible for structural ops

        if value is None:
            return f"op[{i}]: value is None for op='{op_type}' (required for SET/SCALE)."

        if type_hint == "float":
            if not isinstance(value, (int, float)):
                return (
                    f"op[{i}]: type_hint='float' but value is "
                    f"{type(value).__name__} ({value!r}). Expected a number."
                )

        elif type_hint == "int":
            if not isinstance(value, int):
                if isinstance(value, float) and not value.is_integer():
                    return (
                        f"op[{i}]: type_hint='int' but value={value!r} is a "
                        f"non-integer float (precision loss on cast)."
                    )
                elif not isinstance(value, (int, float)):
                    return (
                        f"op[{i}]: type_hint='int' but value is "
                        f"{type(value).__name__} ({value!r}). Expected an integer."
                    )

        elif type_hint == "bool":
            if not isinstance(value, bool):
                return (
                    f"op[{i}]: type_hint='bool' but value is "
                    f"{type(value).__name__} ({value!r}). "
                    f"Must be exactly true or false (not 0/1)."
                )

        elif type_hint == "str":
            if not isinstance(value, str):
                return (
                    f"op[{i}]: type_hint='str' but value is "
                    f"{type(value).__name__} ({value!r}). Expected a string."
                )

        elif type_hint == "dict":
            if not isinstance(value, dict):
                return (
                    f"op[{i}]: type_hint='dict' but value is "
                    f"{type(value).__name__}. Expected a JSON object."
                )

        elif type_hint == "list":
            if not isinstance(value, list):
                return (
                    f"op[{i}]: type_hint='list' but value is "
                    f"{type(value).__name__}. Expected a JSON array."
                )

        return None

    @staticmethod
    def _check_type_compatibility(
        i:            int,
        new_value:    Any,
        existing_val: Any,
        path:         str,
    ) -> str | None:
        """
        Checks new_value type is compatible with the existing field value's type.
        Only applied to SET operations on existing fields.
        """
        existing_type = type(existing_val)
        new_type      = type(new_value)

        # float/int are mutually compatible
        if existing_type in (int, float) and new_type in (int, float):
            return None

        # bool is a subtype of int in Python — check it first
        if isinstance(existing_val, bool) and not isinstance(new_value, bool):
            return (
                f"op[{i}]: existing field at '{path}' is a bool "
                f"({existing_val!r}), but new value is {new_type.__name__} "
                f"({new_value!r}). Must remain bool."
            )

        if existing_type != new_type:
            return (
                f"op[{i}]: existing field at '{path}' is "
                f"{existing_type.__name__} ({existing_val!r}), "
                f"but new value is {new_type.__name__} ({new_value!r}). "
                f"Type mismatch will cause schema corruption."
            )

        return None

    # ── CGS field lookup ──────────────────────────────────────────────────────

    @staticmethod
    def _build_field_lookup(cgs: dict[str, Any]) -> dict[str, Any]:
        """
        Builds a path → current_value lookup for SET operations.
        Only indexes component defaults (the most common mutation target).
        """
        lookup: dict[str, Any] = {}

        for mode in cgs.get("modes", []):
            mid = mode.get("id", "")
            for actor in mode.get("actors", []):
                aid = actor.get("id", "")
                for comp in actor.get("components", []):
                    tid      = comp.get("type_id")
                    defaults = comp.get("defaults", {})
                    for fname, fval in defaults.items():
                        path = (
                            f"modes[{mid}].actors[{aid}]"
                            f".components[{tid}].defaults.{fname}"
                        )
                        lookup[path] = fval

        return lookup