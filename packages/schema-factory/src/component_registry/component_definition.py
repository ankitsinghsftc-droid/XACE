"""
component_definition.py — ComponentDefinition
==============================================
Schema-layer representation of one component type.

ComponentDefinition is the Schema Factory's view of a component — it carries
the field schema, validation rules, and serialization notes needed to validate
CGS mutations and actor definitions. It is distinct from the runtime
component struct (which lives in Rust UCL/DCL packages).

## Three-Layer Component Architecture (Audit 1)
UCL Core  — type_ids 1–10,     domain="ucl",        frozen forever
DCL       — type_ids 100–9999, domain="dcl/<name>", versioned
GCL       — type_ids 10000+,   domain="gcl",        per-game

## Field Types
Field types use a portable string vocabulary so the Schema Factory can
validate CGS mutations without importing Rust types:
    "float", "int", "str", "bool",
    "list[str]", "list[int]", "list[float]",
    "dict", "AssetReference", "EntityID", "enum:<EnumName>"

## Validation Rules
ValidationRule entries are applied by invariant_checker when a mutation
targets a field. Rules are evaluated in declaration order; the first
failing rule produces the error message.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Field Definition ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FieldDefinition:
    """
    Schema definition of one field within a component.

    Attributes
    ----------
    name : str
        Field name as declared in the component struct.
        Must match the Rust/Python field name exactly.
    field_type : str
        Portable type string. Examples:
        "float", "int", "str", "bool",
        "list[str]", "AssetReference", "enum:BehaviorModel"
    required : bool
        If True, this field must be present when the component is added
        to an entity blueprint. Missing required fields are a hard error.
    default : Any
        Default value used when the field is absent from actor_definition
        component defaults. None means no default (required=True implied).
    description : str
        Human-readable description shown in the builder UI and Design Mentor.
    """

    name:        str
    field_type:  str
    required:    bool       = True
    default:     Any        = None
    description: str        = ""

    def has_default(self) -> bool:
        """Returns True if this field has an explicit default value."""
        return self.default is not None or not self.required


# ── Validation Rule ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ValidationRule:
    """
    A single validation constraint applied to one field.

    rule_type vocabulary
    --------------------
    "range"      — params: {"min": float, "max": float}
    "enum"       — params: {"values": list[str]}
    "non_empty"  — params: {}  (string/list must not be empty)
    "positive"   — params: {}  (numeric must be > 0)
    "non_negative" — params: {} (numeric must be >= 0)
    "max_length" — params: {"max": int}
    "regex"      — params: {"pattern": str}
    """

    field:     str
    rule_type: str
    params:    dict[str, Any] = field(default_factory=dict)
    message:   str            = ""

    def error_message(self, field_name: str, value: Any) -> str:
        """Returns the validation error message for a failing value."""
        if self.message:
            return self.message
        match self.rule_type:
            case "range":
                return (
                    f"Field '{field_name}' value {value!r} is out of range "
                    f"[{self.params.get('min')}, {self.params.get('max')}]."
                )
            case "enum":
                return (
                    f"Field '{field_name}' value {value!r} is not a valid option. "
                    f"Valid values: {self.params.get('values', [])}."
                )
            case "non_empty":
                return f"Field '{field_name}' must not be empty."
            case "positive":
                return f"Field '{field_name}' must be positive (> 0), got {value!r}."
            case "non_negative":
                return f"Field '{field_name}' must be non-negative (>= 0), got {value!r}."
            case "max_length":
                return (
                    f"Field '{field_name}' length {len(value)} exceeds "
                    f"maximum {self.params.get('max')}."
                )
            case _:
                return (
                    f"Field '{field_name}' failed validation rule '{self.rule_type}'."
                )

    def validate(self, value: Any) -> bool:
        """Returns True if the value passes this rule."""
        try:
            match self.rule_type:
                case "range":
                    mn = self.params.get("min")
                    mx = self.params.get("max")
                    if mn is not None and value < mn:
                        return False
                    if mx is not None and value > mx:
                        return False
                    return True
                case "enum":
                    return value in self.params.get("values", [])
                case "non_empty":
                    return bool(value)
                case "positive":
                    return value > 0
                case "non_negative":
                    return value >= 0
                case "max_length":
                    return len(value) <= self.params.get("max", 0)
                case _:
                    return True  # unknown rules pass silently
        except (TypeError, AttributeError):
            return False


# ── Component Definition ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class ComponentDefinition:
    """
    Schema-layer definition of one component type.

    Owned by ComponentDefinitionRegistry. Used by:
    - BlueprintCompiler (field name validation)
    - InvariantChecker  (field value validation on mutations)
    - SnapshotEngine    (serialization rule lookup)
    - Design Mentor     (component vocabulary for plain-English descriptions)

    Attributes
    ----------
    type_id : int
        Unique component type ID. Matches CompositeComponentRegistry key.
        UCL: 1–10. DCL: 100–9999. GCL: 10000+.
    name : str
        Canonical component name. Example: "COMP_HEALTH_V1"
    domain : str
        Component layer. One of: "ucl", "dcl/<domain_name>", "gcl"
        Examples: "ucl", "dcl/combat", "dcl/character", "gcl"
    version : str
        Component schema version. Format: "<major>.<minor>"
        Incremented when field schema changes in a breaking way.
    field_definitions : tuple[FieldDefinition, ...]
        All fields in this component, in declaration order.
    validation_rules : tuple[ValidationRule, ...]
        Ordered validation constraints applied to field values.
    description : str
        Human-readable description for the builder UI.
    is_ucl_core : bool
        True if this component is part of the frozen UCL core (type_id 1–10).
        UCL core components cannot be removed or modified (Audit 1).
    """

    type_id:            int
    name:               str
    domain:             str
    version:            str                          = "1.0"
    field_definitions:  tuple[FieldDefinition, ...]  = ()
    validation_rules:   tuple[ValidationRule, ...]   = ()
    description:        str                          = ""
    is_ucl_core:        bool                         = False

    # ── Field Queries ─────────────────────────────────────────────────────────

    def field_names(self) -> set[str]:
        """Returns the set of all field names in this component."""
        return {f.name for f in self.field_definitions}

    def get_field(self, field_name: str) -> FieldDefinition | None:
        """Returns the FieldDefinition for the given field name, or None."""
        for f in self.field_definitions:
            if f.name == field_name:
                return f
        return None

    def required_fields(self) -> list[FieldDefinition]:
        """Returns fields where required=True, in declaration order."""
        return [f for f in self.field_definitions if f.required]

    def optional_fields(self) -> list[FieldDefinition]:
        """Returns fields where required=False, in declaration order."""
        return [f for f in self.field_definitions if not f.required]

    def rules_for_field(self, field_name: str) -> list[ValidationRule]:
        """Returns all ValidationRules targeting the given field name."""
        return [r for r in self.validation_rules if r.field == field_name]

    # ── Validation ────────────────────────────────────────────────────────────

    def validate_defaults(self, defaults: dict[str, Any]) -> list[str]:
        """
        Validates a component defaults dict from an actor_definition.

        Checks:
        - All provided field names exist in this component schema
        - All required fields are present (or have schema-level defaults)
        - All values pass their ValidationRules

        Returns a list of error strings (empty = valid).
        """
        errors: list[str] = []
        valid_names = self.field_names()

        # Unknown field names
        for name in defaults:
            if name not in valid_names:
                errors.append(
                    f"Component {self.name} (type_id={self.type_id}): "
                    f"unknown field '{name}'. "
                    f"Valid fields: {sorted(valid_names)}"
                )

        # Required fields without a provided or schema-level default
        for fd in self.required_fields():
            if fd.name not in defaults and not fd.has_default():
                errors.append(
                    f"Component {self.name} (type_id={self.type_id}): "
                    f"required field '{fd.name}' ({fd.field_type}) "
                    f"is missing and has no schema default."
                )

        # Field-level validation rules
        for field_name, value in defaults.items():
            for rule in self.rules_for_field(field_name):
                if not rule.validate(value):
                    errors.append(
                        f"Component {self.name} (type_id={self.type_id}): "
                        + rule.error_message(field_name, value)
                    )

        return errors

    # ── Display ───────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"ComponentDefinition(type_id={self.type_id}, "
            f"name={self.name!r}, domain={self.domain!r}, "
            f"version={self.version!r}, "
            f"fields={[f.name for f in self.field_definitions]})"
        )