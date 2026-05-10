"""
type_checker.py — TypeChecker
================================
Validates that mutation values are type-compatible with the component field
definitions they target in the CGS.

## Responsibility
The TypeChecker sits inside ConsistencyValidator and runs after
PathResolver has confirmed a path exists. It answers: "Is this value
a legal assignment for this field?"

## Type Rules
Field types come from ComponentDefinition.field_definitions[n].field_type.
Valid field_type strings (from component_definition.py):
    "float", "int", "str", "bool",
    "list[str]", "list[int]", "list[float]",
    "dict", "AssetReference", "EntityID", "enum:<EnumName>"

## Coercion
Safe numeric coercions are allowed and noted (not errors):
    int → float field    : allowed (3 is a valid float)
    float → int field    : BLOCKED (3.5 is not a valid int — data loss)
    int → bool field     : BLOCKED (use True/False explicitly)
    str → enum field     : allowed if str is a valid enum value

## AssetReference
AssetReference fields accept dicts with keys: id, asset_type, status.
Inline strings are rejected — all asset refs must be typed objects (Audit 2).

## EntityID
EntityID fields accept positive integers or 0 (NULL_ENTITY_ID).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# ── Type Check Result ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TypeCheckResult:
    """Result of one type-check operation."""
    is_valid:       bool
    field_path:     str
    expected_type:  str
    actual_type:    str
    value_repr:     str
    error:          str    = ""
    warning:        str    = ""
    coercion_note:  str    = ""    # non-empty when value was safely coercible

    def __repr__(self) -> str:
        status = "OK" if self.is_valid else f"FAIL: {self.error}"
        return f"TypeCheckResult({self.field_path!r}: {status})"


# ── Known Enum Values ─────────────────────────────────────────────────────────

_ENUM_VALUES: dict[str, frozenset[str]] = {
    "BehaviorModel":   frozenset({"CHASE", "PATROL", "IDLE", "FLEE", "GUARD"}),
    "ControlType":     frozenset({"HUMAN", "AI_PROXY", "NETWORK_REMOTE", "NONE"}),
    "EntityState":     frozenset({"ACTIVE", "DISABLED", "DESTROY_REQUESTED",
                                   "DESTROYED", "ARCHIVED"}),
    "DeathBehavior":   frozenset({"DESTROY", "DISABLE", "RESPAWN", "PERSIST"}),
    "AssetStatus":     frozenset({"PLACEHOLDER", "LINKED", "MISSING", "UNRESOLVED"}),
    "AssetType":       frozenset({"MESH", "TEXTURE", "MATERIAL", "ANIMATION_CONTROLLER",
                                   "AUDIO_CLIP", "AUDIO_MUSIC", "SPRITE", "PARTICLE",
                                   "PREFAB", "FONT"}),
    "IKMode":          frozenset({"DISABLED", "LOOK_AT", "HANDS", "FEET",
                                   "HANDS_AND_FEET", "FULL_BODY"}),
    "NetworkMode":     frozenset({"OFFLINE", "HOST", "CLIENT",
                                   "DEDICATED_SERVER", "PEER_TO_PEER"}),
    "CheckpointType":  frozenset({"MANUAL", "AUTO", "STORY", "RESPAWN"}),
    "CloudSyncMode":   frozenset({"STEAM", "EPIC", "PSN", "XBOX", "CUSTOM", "NONE"}),
}


# ── Valid AssetReference Keys ─────────────────────────────────────────────────

_ASSET_REF_REQUIRED_KEYS = frozenset({"id", "asset_type", "status"})


# ── Type Checker ──────────────────────────────────────────────────────────────

class TypeChecker:
    """
    Validates mutation values against declared field types.

    Stateless — call check() per (value, field_type) pair.

    Usage
    -----
        checker = TypeChecker()
        result  = checker.check(
            value=80.0,
            field_type="float",
            field_path="modes.mode_default.actors.actor_player.components.100.defaults.current"
        )
    """

    def check(
        self,
        value:      Any,
        field_type: str,
        field_path: str = "",
    ) -> TypeCheckResult:
        """
        Validates a value against a field_type string.

        Parameters
        ----------
        value : Any
            The mutation value to check.
        field_type : str
            The declared field type from ComponentDefinition.
        field_path : str
            The CGS path for error messages.

        Returns
        -------
        TypeCheckResult
            is_valid=True if the value is acceptable.
        """
        actual_type = type(value).__name__
        value_repr  = repr(value)[:60]

        match field_type:
            case "float":
                return self._check_float(value, field_path, actual_type, value_repr)
            case "int":
                return self._check_int(value, field_path, actual_type, value_repr)
            case "str":
                return self._check_str(value, field_path, actual_type, value_repr)
            case "bool":
                return self._check_bool(value, field_path, actual_type, value_repr)
            case "dict":
                return self._check_dict(value, field_path, actual_type, value_repr)
            case "list[str]":
                return self._check_list(value, field_path, actual_type, value_repr, "str")
            case "list[int]":
                return self._check_list(value, field_path, actual_type, value_repr, "int")
            case "list[float]":
                return self._check_list(value, field_path, actual_type, value_repr, "float")
            case "AssetReference":
                return self._check_asset_reference(value, field_path, actual_type, value_repr)
            case "EntityID":
                return self._check_entity_id(value, field_path, actual_type, value_repr)
            case _ if field_type.startswith("enum:"):
                enum_name = field_type[5:]
                return self._check_enum(value, enum_name, field_path, actual_type, value_repr)
            case _:
                # Unknown type — pass with a warning rather than blocking
                return TypeCheckResult(
                    is_valid=True,
                    field_path=field_path,
                    expected_type=field_type,
                    actual_type=actual_type,
                    value_repr=value_repr,
                    warning=(
                        f"Unknown field_type '{field_type}' — "
                        f"type checking skipped for this field."
                    ),
                )

    def check_many(
        self,
        values:     dict[str, Any],
        field_types: dict[str, str],
        path_prefix: str = "",
    ) -> list[TypeCheckResult]:
        """
        Checks multiple field values against their declared types.
        Returns one TypeCheckResult per field. All checks run (no early exit).
        """
        results: list[TypeCheckResult] = []
        for field_name, value in sorted(values.items()):
            ftype = field_types.get(field_name, "")
            if not ftype:
                continue
            path = f"{path_prefix}.{field_name}" if path_prefix else field_name
            results.append(self.check(value, ftype, path))
        return results

    # ── Type Handlers ─────────────────────────────────────────────────────────

    @staticmethod
    def _check_float(value, path, actual, vrepr) -> TypeCheckResult:
        if isinstance(value, bool):
            return TypeCheckResult(
                is_valid=False, field_path=path,
                expected_type="float", actual_type=actual, value_repr=vrepr,
                error="Bool is not a valid float. Use 0.0 or 1.0 instead.",
            )
        if isinstance(value, (int, float)):
            note = "int coerced to float" if isinstance(value, int) else ""
            return TypeCheckResult(
                is_valid=True, field_path=path,
                expected_type="float", actual_type=actual, value_repr=vrepr,
                coercion_note=note,
            )
        return TypeCheckResult(
            is_valid=False, field_path=path,
            expected_type="float", actual_type=actual, value_repr=vrepr,
            error=f"Expected a number, got {actual} ({vrepr}).",
        )

    @staticmethod
    def _check_int(value, path, actual, vrepr) -> TypeCheckResult:
        if isinstance(value, bool):
            return TypeCheckResult(
                is_valid=False, field_path=path,
                expected_type="int", actual_type=actual, value_repr=vrepr,
                error="Bool is not a valid int. Use 0 or 1 explicitly.",
            )
        if isinstance(value, float) and not value.is_integer():
            return TypeCheckResult(
                is_valid=False, field_path=path,
                expected_type="int", actual_type=actual, value_repr=vrepr,
                error=f"{vrepr} is a decimal — cannot assign to an int field without data loss.",
            )
        if isinstance(value, (int, float)):
            return TypeCheckResult(
                is_valid=True, field_path=path,
                expected_type="int", actual_type=actual, value_repr=vrepr,
            )
        return TypeCheckResult(
            is_valid=False, field_path=path,
            expected_type="int", actual_type=actual, value_repr=vrepr,
            error=f"Expected a whole number, got {actual} ({vrepr}).",
        )

    @staticmethod
    def _check_str(value, path, actual, vrepr) -> TypeCheckResult:
        if isinstance(value, str):
            return TypeCheckResult(
                is_valid=True, field_path=path,
                expected_type="str", actual_type=actual, value_repr=vrepr,
            )
        return TypeCheckResult(
            is_valid=False, field_path=path,
            expected_type="str", actual_type=actual, value_repr=vrepr,
            error=f"Expected a string, got {actual} ({vrepr}).",
        )

    @staticmethod
    def _check_bool(value, path, actual, vrepr) -> TypeCheckResult:
        if isinstance(value, bool):
            return TypeCheckResult(
                is_valid=True, field_path=path,
                expected_type="bool", actual_type=actual, value_repr=vrepr,
            )
        return TypeCheckResult(
            is_valid=False, field_path=path,
            expected_type="bool", actual_type=actual, value_repr=vrepr,
            error=(
                f"Expected true or false, got {actual} ({vrepr}). "
                f"Do not use 0/1 for boolean fields — use True/False."
            ),
        )

    @staticmethod
    def _check_dict(value, path, actual, vrepr) -> TypeCheckResult:
        if isinstance(value, dict):
            return TypeCheckResult(
                is_valid=True, field_path=path,
                expected_type="dict", actual_type=actual, value_repr=vrepr,
            )
        return TypeCheckResult(
            is_valid=False, field_path=path,
            expected_type="dict", actual_type=actual, value_repr=vrepr,
            error=f"Expected a dict, got {actual} ({vrepr}).",
        )

    @staticmethod
    def _check_list(value, path, actual, vrepr, item_type) -> TypeCheckResult:
        if not isinstance(value, list):
            return TypeCheckResult(
                is_valid=False, field_path=path,
                expected_type=f"list[{item_type}]", actual_type=actual, value_repr=vrepr,
                error=f"Expected a list, got {actual} ({vrepr}).",
            )
        bad_items = [
            i for i, v in enumerate(value)
            if not _is_type(v, item_type)
        ]
        if bad_items:
            return TypeCheckResult(
                is_valid=False, field_path=path,
                expected_type=f"list[{item_type}]", actual_type=actual, value_repr=vrepr,
                error=(
                    f"List item(s) at index {bad_items} are not of type {item_type}."
                ),
            )
        return TypeCheckResult(
            is_valid=True, field_path=path,
            expected_type=f"list[{item_type}]", actual_type=actual, value_repr=vrepr,
        )

    @staticmethod
    def _check_asset_reference(value, path, actual, vrepr) -> TypeCheckResult:
        if isinstance(value, str):
            return TypeCheckResult(
                is_valid=False, field_path=path,
                expected_type="AssetReference", actual_type=actual, value_repr=vrepr,
                error=(
                    "AssetReference fields must be a dict with keys "
                    "'id', 'asset_type', and 'status', not a raw string. "
                    "XACE requires typed asset references everywhere (Audit 2)."
                ),
            )
        if not isinstance(value, dict):
            return TypeCheckResult(
                is_valid=False, field_path=path,
                expected_type="AssetReference", actual_type=actual, value_repr=vrepr,
                error=f"Expected an AssetReference dict, got {actual}.",
            )
        missing = _ASSET_REF_REQUIRED_KEYS - set(value.keys())
        if missing:
            return TypeCheckResult(
                is_valid=False, field_path=path,
                expected_type="AssetReference", actual_type=actual, value_repr=vrepr,
                error=f"AssetReference dict missing required keys: {sorted(missing)}.",
            )
        return TypeCheckResult(
            is_valid=True, field_path=path,
            expected_type="AssetReference", actual_type=actual, value_repr=vrepr,
        )

    @staticmethod
    def _check_entity_id(value, path, actual, vrepr) -> TypeCheckResult:
        if isinstance(value, bool):
            return TypeCheckResult(
                is_valid=False, field_path=path,
                expected_type="EntityID", actual_type=actual, value_repr=vrepr,
                error="EntityID must be a non-negative integer, not a bool.",
            )
        if isinstance(value, int) and value >= 0:
            return TypeCheckResult(
                is_valid=True, field_path=path,
                expected_type="EntityID", actual_type=actual, value_repr=vrepr,
            )
        return TypeCheckResult(
            is_valid=False, field_path=path,
            expected_type="EntityID", actual_type=actual, value_repr=vrepr,
            error=f"EntityID must be a non-negative integer, got {actual} ({vrepr}).",
        )

    @staticmethod
    def _check_enum(value, enum_name, path, actual, vrepr) -> TypeCheckResult:
        valid_values = _ENUM_VALUES.get(enum_name)
        if valid_values is None:
            return TypeCheckResult(
                is_valid=True, field_path=path,
                expected_type=f"enum:{enum_name}", actual_type=actual, value_repr=vrepr,
                warning=f"Unknown enum '{enum_name}' — values not validated.",
            )
        if not isinstance(value, str):
            return TypeCheckResult(
                is_valid=False, field_path=path,
                expected_type=f"enum:{enum_name}", actual_type=actual, value_repr=vrepr,
                error=f"enum:{enum_name} requires a string value, got {actual}.",
            )
        if value not in valid_values:
            return TypeCheckResult(
                is_valid=False, field_path=path,
                expected_type=f"enum:{enum_name}", actual_type=actual, value_repr=vrepr,
                error=(
                    f"'{value}' is not a valid {enum_name}. "
                    f"Valid values: {sorted(valid_values)}"
                ),
            )
        return TypeCheckResult(
            is_valid=True, field_path=path,
            expected_type=f"enum:{enum_name}", actual_type=actual, value_repr=vrepr,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_type(value: Any, type_name: str) -> bool:
    match type_name:
        case "str":   return isinstance(value, str)
        case "int":   return isinstance(value, int) and not isinstance(value, bool)
        case "float": return isinstance(value, (int, float)) and not isinstance(value, bool)
        case _:       return True