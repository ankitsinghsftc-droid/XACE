"""
gcl_validator.py — Game Component Library Validator

Validates GCL (Game Component Library) components before they are
registered into the CompositeComponentRegistry.

## GCL Rules (Audit 1, Global Invariant I11)
1. No name collision with UCL or DCL component type names
2. No type_id collision with UCL (1-10) or DCL (100-9999) ranges
3. All GCL type_ids must be >= 10000
4. Field types must be valid XACE field types (no engine-specific types)
5. GCL components must never enter DCL or UCL namespaces
6. Domain field must identify the game project, not a XACE domain

## Why GCL Validation Matters
GCL components are developer-owned and loaded from outside XACE.
They could contain anything — invalid type IDs, name collisions,
unsupported field types, or attempts to shadow UCL/DCL components.
The validator is the safety boundary between developer code and
the authoritative registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
import logging

from .dcl_registry import (
    ComponentDefinition,
    ComponentFieldDefinition,
    ComponentLayer,
    CompositeComponentRegistry,
)

logger = logging.getLogger(__name__)


# ── Valid Field Types ──────────────────────────────────────────────────────────

# All field types that XACE supports in component definitions.
# Engine-specific types (UnityTransform, GodotNode, etc.) are forbidden.
# This set is frozen — adding new types requires a XACE version increment.
VALID_FIELD_TYPES: Set[str] = {
    # Numeric types
    "f32", "f64",
    "i8", "i16", "i32", "i64",
    "u8", "u16", "u32", "u64",
    # Boolean
    "bool",
    # String
    "str",
    # Collections
    "list", "dict",
    # Complex types
    "enum", "struct",
    # Asset reference (Audit 2 — typed, never raw string)
    "asset_reference",
    # Optional wrapper
    "optional",
}

# Field type prefixes that indicate engine-specific types (forbidden in GCL)
FORBIDDEN_FIELD_TYPE_PREFIXES: List[str] = [
    "unity_", "unreal_", "godot_", "engine_",
    "Unity", "Unreal", "Godot", "Engine",
    "GameObject", "Transform", "Node", "Actor",
    "MonoBehaviour", "Component", "ScriptableObject",
]

# Reserved name prefixes that GCL components must not use
RESERVED_NAME_PREFIXES: List[str] = [
    "COMP_TRANSFORM",
    "COMP_IDENTITY",
    "COMP_RENDER",
    "COMP_COLLIDER",
    "COMP_VELOCITY",
    "COMP_INPUT",
    "COMP_EVENT",
    "COMP_LIFETIME",
    "COMP_GAMESTATE",
    "COMP_AUTHORITY",
    "COMP_HEALTH",
    "COMP_DAMAGE",
    "COMP_HITBOX",
    "COMP_SHIELD",
    "COMP_STATUS_EFFECT",
    "COMP_MOVEMENT_INTENT",
    "COMP_ANIMATION",
    "COMP_IK",
    "COMP_CARRY",
    "COMP_RAGDOLL",
    "COMP_RIGIDBODY",
    "COMP_SURFACE",
    "COMP_BUOYANCY",
    "COMP_SOFT_BODY",
    "COMP_AI",
    "COMP_PATROL",
    "COMP_PERCEPTION",
    "COMP_CROWD",
    "COMP_STEALTH",
    "COMP_DISGUISE",
    "COMP_DETECTION",
    "COMP_STATS",
    "COMP_INVENTORY",
    "COMP_ABILITY",
    "COMP_PROGRESSION",
    "COMP_ECONOMY",
    "COMP_SPAWNER",
    "COMP_TRIGGERZONE",
    "COMP_PERSISTENCE",
    "COMP_WORLDSTREAMING",
    "COMP_ENVIRONMENT",
    "COMP_DESTRUCTIBLE",
    "COMP_INTERACTION",
    "COMP_DIALOGUE",
    "COMP_PUZZLE",
    "COMP_USABLE",
    "COMP_CAMERA",
    "COMP_AUDIO",
    "COMP_MUSIC",
    "COMP_REPLICATION",
    "COMP_NETWORK",
    "COMP_PLAYER_SESSION",
    "COMP_UI",
    "COMP_HUD",
    "COMP_MINIMAP",
    "COMP_SAVE",
    "COMP_CHECKPOINT",
    "COMP_PLAYER_PROFILE",
    "COMP_CLOUD",
]


# ── Validation Result ──────────────────────────────────────────────────────────

@dataclass
class GclValidationResult:
    """
    The result of validating one or more GCL component definitions.

    Contains all errors and warnings found during validation.
    A result with no errors is considered valid.
    Warnings are non-fatal — they are logged but do not block registration.
    """
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """True if there are no errors (warnings are acceptable)."""
        return len(self.errors) == 0

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    def add_error(self, message: str) -> None:
        self.errors.append(message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def merge(self, other: "GclValidationResult") -> None:
        """Merges another result into this one."""
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)

    def __repr__(self) -> str:
        return (
            f"GclValidationResult("
            f"valid={self.is_valid}, "
            f"errors={self.error_count}, "
            f"warnings={self.warning_count})"
        )


# ── GCL Validator ──────────────────────────────────────────────────────────────

class GclValidator:
    """
    Validates GCL component definitions before registry registration.

    The validator is stateless — it takes a registry (to check for
    collisions) and a list of definitions and returns a validation result.

    ## Validation Layers
    1. Type ID range check (must be >= 10000)
    2. Name collision check against registry (I11)
    3. Name prefix check (no XACE-reserved prefixes)
    4. Layer check (must be GCL)
    5. Field type validation (no engine-specific types)
    6. Field name uniqueness within component
    7. Version check (must be >= 1)
    8. Domain check (must not be a XACE domain name)
    """

    # XACE-owned domain names that GCL must not use
    XACE_DOMAIN_NAMES: Set[str] = {
        "ucl", "combat", "character", "physics", "ai",
        "stealth", "rpg", "world", "interaction", "camera",
        "audio", "network", "ui", "persistence",
    }

    def validate_component(
        self,
        definition: ComponentDefinition,
        registry: CompositeComponentRegistry,
    ) -> GclValidationResult:
        """
        Validates a single GCL component definition.

        Checks all GCL rules against the current registry state.
        Returns a GclValidationResult with any errors or warnings found.
        """
        result = GclValidationResult()

        # Rule 1: Type ID must be in GCL range (>= 10000)
        if definition.type_id < 10000:
            result.add_error(
                f"GCL component '{definition.type_name}' has type_id "
                f"{definition.type_id} which is below GCL minimum 10000. "
                f"UCL range: 1-10, DCL range: 100-9999, GCL range: 10000+"
            )

        # Rule 2: Type ID must not collide with registry
        if registry.contains_id(definition.type_id):
            existing = registry.get_by_id(definition.type_id)
            result.add_error(
                f"GCL component '{definition.type_name}' type_id "
                f"{definition.type_id} collides with already-registered "
                f"'{existing.type_name}' ({existing.layer.value} layer) — "
                f"choose a type_id >= 10000 that is not already in use"
            )

        # Rule 3: Type name must not collide with registry (I11)
        if registry.contains_name(definition.type_name):
            existing = registry.get_by_name(definition.type_name)
            result.add_error(
                f"GCL component type_name '{definition.type_name}' collides "
                f"with '{existing.type_name}' in {existing.layer.value} layer "
                f"— name collisions between layers are forbidden (I11)"
            )

        # Rule 4: Type name must not use XACE-reserved prefixes
        reserved_prefix = self._find_reserved_prefix(definition.type_name)
        if reserved_prefix:
            result.add_error(
                f"GCL component '{definition.type_name}' uses reserved "
                f"XACE name prefix '{reserved_prefix}'. GCL components must "
                f"use unique names that do not shadow XACE components"
            )

        # Rule 5: Layer must be GCL
        if definition.layer != ComponentLayer.GCL:
            result.add_error(
                f"GCL component '{definition.type_name}' has layer="
                f"'{definition.layer.value}' — GCL components must have "
                f"layer=ComponentLayer.GCL"
            )

        # Rule 6: Domain must not be a XACE-owned domain name
        if definition.domain in self.XACE_DOMAIN_NAMES:
            result.add_error(
                f"GCL component '{definition.type_name}' uses domain="
                f"'{definition.domain}' which is a XACE-owned domain name. "
                f"GCL components must use their game project name as domain "
                f"(e.g. 'my_game', 'zombie_shooter')"
            )

        # Rule 7: Domain must not be empty
        if not definition.domain:
            result.add_error(
                f"GCL component '{definition.type_name}' has empty domain. "
                f"GCL components must specify their game project name"
            )

        # Rule 8: Version must be >= 1
        if definition.version < 1:
            result.add_error(
                f"GCL component '{definition.type_name}' has version="
                f"{definition.version} — version must be >= 1"
            )

        # Rule 9: Type name must not be empty
        if not definition.type_name:
            result.add_error(
                f"GCL component with type_id={definition.type_id} "
                f"has empty type_name"
            )

        # Rule 10: Validate each field
        field_result = self._validate_fields(definition)
        result.merge(field_result)

        # Warning: GCL component with no fields
        if not definition.fields:
            result.add_warning(
                f"GCL component '{definition.type_name}' has no fields — "
                f"a component with no fields carries no data. "
                f"Consider adding at least one field."
            )

        return result

    def validate_batch(
        self,
        definitions: List[ComponentDefinition],
        registry: CompositeComponentRegistry,
    ) -> GclValidationResult:
        """
        Validates a batch of GCL component definitions.

        Also checks for collisions within the batch itself
        (two GCL components with the same type_id or type_name).

        Returns a merged GclValidationResult for the entire batch.
        """
        merged = GclValidationResult()

        # Check for intra-batch collisions before checking against registry
        batch_ids: Dict[int, str] = {}
        batch_names: Dict[str, int] = {}

        for definition in definitions:
            # Intra-batch type_id collision
            if definition.type_id in batch_ids:
                merged.add_error(
                    f"GCL batch has duplicate type_id {definition.type_id}: "
                    f"'{batch_ids[definition.type_id]}' and "
                    f"'{definition.type_name}'"
                )
            else:
                batch_ids[definition.type_id] = definition.type_name

            # Intra-batch type_name collision
            if definition.type_name in batch_names:
                merged.add_error(
                    f"GCL batch has duplicate type_name '{definition.type_name}': "
                    f"type_ids {batch_names[definition.type_name]} and "
                    f"{definition.type_id}"
                )
            else:
                batch_names[definition.type_name] = definition.type_id

        # Validate each component individually
        for definition in definitions:
            result = self.validate_component(definition, registry)
            merged.merge(result)

        return merged

    def _validate_fields(
        self, definition: ComponentDefinition
    ) -> GclValidationResult:
        """Validates all field definitions for a component."""
        result = GclValidationResult()
        seen_field_names: Set[str] = set()

        for f in definition.fields:
            # Field name must not be empty
            if not f.field_name:
                result.add_error(
                    f"Component '{definition.type_name}' has a field "
                    f"with empty field_name"
                )
                continue

            # Field name must be unique within component
            if f.field_name in seen_field_names:
                result.add_error(
                    f"Component '{definition.type_name}' has duplicate "
                    f"field_name '{f.field_name}'"
                )
            else:
                seen_field_names.add(f.field_name)

            # Field type must be valid
            field_type_error = self._validate_field_type(
                f.field_type, f.field_name, definition.type_name
            )
            if field_type_error:
                result.add_error(field_type_error)

        return result

    def _validate_field_type(
        self,
        field_type: str,
        field_name: str,
        component_name: str,
    ) -> Optional[str]:
        """
        Validates a single field type string.

        Returns an error string if invalid, or None if valid.
        """
        if not field_type:
            return (
                f"Component '{component_name}' field '{field_name}' "
                f"has empty field_type"
            )

        # Check for engine-specific type prefixes (forbidden)
        for prefix in FORBIDDEN_FIELD_TYPE_PREFIXES:
            if field_type.startswith(prefix):
                return (
                    f"Component '{component_name}' field '{field_name}' "
                    f"has engine-specific field_type '{field_type}'. "
                    f"Engine-specific types are forbidden in GCL components. "
                    f"Use XACE field types: {sorted(VALID_FIELD_TYPES)}"
                )

        # Check field type is in the valid set
        if field_type not in VALID_FIELD_TYPES:
            return (
                f"Component '{component_name}' field '{field_name}' "
                f"has unknown field_type '{field_type}'. "
                f"Valid types: {sorted(VALID_FIELD_TYPES)}"
            )

        return None

    def _find_reserved_prefix(self, type_name: str) -> Optional[str]:
        """
        Returns the reserved prefix that type_name starts with,
        or None if no reserved prefix is found.
        """
        for prefix in RESERVED_NAME_PREFIXES:
            if type_name.startswith(prefix):
                return prefix
        return None


# ── Tests ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from .dcl_registry import build_ucl_only_registry

    print("Running GclValidator self-tests...")
    errors_found: List[str] = []

    registry = build_ucl_only_registry()
    validator = GclValidator()

    def make_gcl_component(
        type_id: int = 10001,
        type_name: str = "COMP_MY_CUSTOM_V1",
        domain: str = "my_game",
        fields: Optional[List[ComponentFieldDefinition]] = None,
    ) -> ComponentDefinition:
        return ComponentDefinition(
            type_id=type_id,
            type_name=type_name,
            layer=ComponentLayer.GCL,
            domain=domain,
            version=1,
            fields=fields or [
                ComponentFieldDefinition("value", "f32", True)
            ],
        )

    # Test 1: Valid GCL component passes validation
    result = validator.validate_component(make_gcl_component(), registry)
    assert result.is_valid, f"Valid GCL component should pass: {result.errors}"
    print("  PASS: Valid GCL component passes validation")

    # Test 2: type_id below 10000 fails
    result = validator.validate_component(
        make_gcl_component(type_id=500), registry
    )
    assert not result.is_valid
    assert any("10000" in e for e in result.errors)
    print("  PASS: type_id below 10000 fails validation")

    # Test 3: Name collision with UCL fails (I11)
    result = validator.validate_component(
        make_gcl_component(
            type_id=10001,
            type_name="COMP_TRANSFORM_V1"
        ),
        registry,
    )
    assert not result.is_valid
    assert any("collides" in e for e in result.errors)
    print("  PASS: UCL name collision fails validation (I11)")

    # Test 4: Reserved name prefix fails
    result = validator.validate_component(
        make_gcl_component(type_name="COMP_HEALTH_CUSTOM_V1"),
        registry,
    )
    assert not result.is_valid
    assert any("reserved" in e for e in result.errors)
    print("  PASS: Reserved name prefix fails validation")

    # Test 5: Wrong layer fails
    bad_layer = ComponentDefinition(
        type_id=10001,
        type_name="COMP_MY_CUSTOM_V1",
        layer=ComponentLayer.DCL,  # Wrong
        domain="my_game",
        version=1,
    )
    result = validator.validate_component(bad_layer, registry)
    assert not result.is_valid
    assert any("layer" in e for e in result.errors)
    print("  PASS: Wrong layer fails validation")

    # Test 6: XACE domain name fails
    result = validator.validate_component(
        make_gcl_component(domain="combat"),
        registry,
    )
    assert not result.is_valid
    assert any("XACE-owned" in e for e in result.errors)
    print("  PASS: XACE domain name fails validation")

    # Test 7: Engine-specific field type fails
    result = validator.validate_component(
        make_gcl_component(
            fields=[ComponentFieldDefinition("obj", "GameObject", True)]
        ),
        registry,
    )
    assert not result.is_valid
    assert any("engine-specific" in e for e in result.errors)
    print("  PASS: Engine-specific field type fails validation")

    # Test 8: Invalid field type fails
    result = validator.validate_component(
        make_gcl_component(
            fields=[ComponentFieldDefinition("x", "unknown_type", True)]
        ),
        registry,
    )
    assert not result.is_valid
    assert any("unknown field_type" in e for e in result.errors)
    print("  PASS: Unknown field type fails validation")

    # Test 9: Duplicate field names fail
    result = validator.validate_component(
        make_gcl_component(
            fields=[
                ComponentFieldDefinition("value", "f32", True),
                ComponentFieldDefinition("value", "f32", True),
            ]
        ),
        registry,
    )
    assert not result.is_valid
    assert any("duplicate" in e.lower() for e in result.errors)
    print("  PASS: Duplicate field names fail validation")

    # Test 10: No fields produces warning not error
    result = validator.validate_component(
        make_gcl_component(fields=[]),
        registry,
    )
    assert result.is_valid, "No fields should warn not error"
    assert result.warning_count > 0, "Should have warning about no fields"
    print("  PASS: No fields produces warning not error")

    # Test 11: Batch collision detection
    batch = [
        make_gcl_component(type_id=10001, type_name="COMP_A_V1"),
        make_gcl_component(type_id=10001, type_name="COMP_B_V1"),  # ID collision
    ]
    batch_result = validator.validate_batch(batch, registry)
    assert not batch_result.is_valid
    assert any("duplicate type_id" in e for e in batch_result.errors)
    print("  PASS: Intra-batch type_id collision detected")

    # Test 12: Valid field types all pass
    for valid_type in ["f32", "f64", "i32", "u64", "bool", "str", "list",
                       "dict", "enum", "struct", "asset_reference"]:
        result = validator.validate_component(
            make_gcl_component(
                fields=[ComponentFieldDefinition("field", valid_type, True)]
            ),
            registry,
        )
        assert result.is_valid, \
            f"Field type '{valid_type}' should be valid: {result.errors}"
    print("  PASS: All valid field types pass validation")

    print(f"\nAll tests passed.")