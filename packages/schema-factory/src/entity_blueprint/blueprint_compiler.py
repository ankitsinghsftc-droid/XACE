"""
blueprint_compiler.py — BlueprintCompiler
==========================================
Compiles raw actor definition dicts from the CGS into immutable
EntityBlueprints with fully resolved component defaults.

## Input Format
Each actor_definition dict follows the CGS canonical structure:

    {
        "id":           "actor_zombie",
        "actor_type":   "ENEMY",
        "control_type": "AI_PROXY",      # optional, default "AI_PROXY"
        "prefab_id":    None,             # optional
        "components": [
            {
                "type_id":  100,          # int — CompositeComponentRegistry key
                "defaults": {             # field_name → value
                    "current": 80,
                    "max":     80,
                    "regen_rate": 0.0,
                }
            },
            ...
        ],
        "tags":       ["hostile"],        # optional
        "mode_scope": [],                 # optional; empty = all modes
    }

## Registry Protocol
BlueprintCompiler accepts any object implementing ComponentRegistryProtocol.
This decouples the compiler from the concrete DCL registry implementation,
which is assembled at game load time (packages/dcl/dcl_registry.py, Phase 1).

## Validation
Every component type_id referenced in an actor_definition must exist in
the CompositeComponentRegistry. Unknown type_ids are hard errors — they
indicate a GCL naming collision, a typo, or a domain that wasn't declared
in game_config.yaml (I11).

## Error Strategy
compile_one() raises BlueprintCompilationError on the first violation.
compile_all() collects all errors across all definitions and raises once
with the full list, so the designer sees every problem in one shot.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from .entity_blueprint import EntityBlueprint, EntityBlueprintBuilder
from .blueprint_registry import BlueprintRegistry, BlueprintRegistryError


# ── Component Registry Protocol ───────────────────────────────────────────────

@runtime_checkable
class ComponentRegistryProtocol(Protocol):
    """
    Minimal interface the BlueprintCompiler requires from any registry.

    The concrete implementation is CompositeComponentRegistry (Phase 1 Python),
    but the compiler only needs these two methods, keeping it decoupled.
    """

    def has_component(self, type_id: int) -> bool:
        """Returns True if the given component type_id is registered."""
        ...

    def get_field_names(self, type_id: int) -> set[str]:
        """
        Returns the valid field names for a component type.
        Returns an empty set if the type is unknown (caller handles).
        """
        ...


# ── Compilation Error ─────────────────────────────────────────────────────────

@dataclass
class BlueprintCompilationError(Exception):
    """
    Raised when one or more actor definitions fail validation.

    Attributes
    ----------
    errors : list[str]
        Full list of validation error messages.
        Each message names the offending blueprint ID and the rule violated.
    """

    errors: list[str]

    def __str__(self) -> str:
        header = f"BlueprintCompiler: {len(self.errors)} error(s):"
        lines  = "\n".join(f"  [{i+1}] {e}" for i, e in enumerate(self.errors))
        return f"{header}\n{lines}"


# ── Validation Helpers ────────────────────────────────────────────────────────

_VALID_ACTOR_TYPES: frozenset[str] = frozenset({
    "PLAYER", "ENEMY", "NPC", "PROJECTILE", "PICKUP",
    "TRIGGER", "WORLD_OBJECT", "CAMERA", "MANAGER", "UNKNOWN",
})

_VALID_CONTROL_TYPES: frozenset[str] = frozenset({
    "HUMAN", "AI_PROXY", "NETWORK_REMOTE", "NONE",
})


def _validate_actor_definition(
    defn:     dict[str, Any],
    registry: ComponentRegistryProtocol,
) -> list[str]:
    """
    Validates one raw actor_definition dict.
    Returns a list of error strings (empty = valid).
    """
    errors: list[str] = []
    bp_id  = defn.get("id", "<missing_id>")

    # ── Required fields ───────────────────────────────────────────────────────
    if not defn.get("id"):
        errors.append(
            "Actor definition has an empty or missing 'id'. "
            "Every actor must have a unique non-empty ID."
        )
        return errors  # can't proceed without an ID

    if not defn.get("actor_type"):
        errors.append(f"[{bp_id}] Missing required field 'actor_type'.")

    actor_type = defn.get("actor_type", "")
    if actor_type and actor_type not in _VALID_ACTOR_TYPES:
        errors.append(
            f"[{bp_id}] Unknown actor_type '{actor_type}'. "
            f"Valid types: {sorted(_VALID_ACTOR_TYPES)}"
        )

    control_type = defn.get("control_type", "AI_PROXY")
    if control_type not in _VALID_CONTROL_TYPES:
        errors.append(
            f"[{bp_id}] Unknown control_type '{control_type}'. "
            f"Valid types: {sorted(_VALID_CONTROL_TYPES)}"
        )

    # ── Component validation ──────────────────────────────────────────────────
    components = defn.get("components", [])
    if not isinstance(components, list):
        errors.append(
            f"[{bp_id}] 'components' must be a list, "
            f"got {type(components).__name__}."
        )
        return errors

    seen_type_ids: set[int] = set()

    for comp in components:
        if not isinstance(comp, dict):
            errors.append(
                f"[{bp_id}] Each component entry must be a dict, "
                f"got {type(comp).__name__}."
            )
            continue

        type_id = comp.get("type_id")
        if type_id is None:
            errors.append(f"[{bp_id}] Component entry missing 'type_id'.")
            continue

        if not isinstance(type_id, int):
            errors.append(
                f"[{bp_id}] Component 'type_id' must be an int, "
                f"got {type(type_id).__name__} ({type_id!r})."
            )
            continue

        # No duplicate type_ids within one actor definition
        if type_id in seen_type_ids:
            errors.append(
                f"[{bp_id}] Duplicate component type_id {type_id}. "
                f"Each component type may appear at most once per actor."
            )
            continue
        seen_type_ids.add(type_id)

        # type_id must exist in the CompositeComponentRegistry (I11)
        if not registry.has_component(type_id):
            errors.append(
                f"[{bp_id}] Component type_id {type_id} is not registered "
                f"in the CompositeComponentRegistry. Ensure the domain "
                f"containing this component is declared in game_config.yaml, "
                f"or that the GCL component has been loaded."
            )
            continue

        # Validate field names against registry schema
        defaults = comp.get("defaults", {})
        if not isinstance(defaults, dict):
            errors.append(
                f"[{bp_id}] Component {type_id} 'defaults' must be a dict, "
                f"got {type(defaults).__name__}."
            )
            continue

        valid_fields = registry.get_field_names(type_id)
        if valid_fields:  # empty set means registry doesn't enforce fields
            for field_name in defaults:
                if field_name not in valid_fields:
                    errors.append(
                        f"[{bp_id}] Component {type_id} has no field "
                        f"'{field_name}'. Valid fields: {sorted(valid_fields)}"
                    )

    # ── Tags ──────────────────────────────────────────────────────────────────
    tags = defn.get("tags", [])
    if not isinstance(tags, list):
        errors.append(
            f"[{bp_id}] 'tags' must be a list of strings, "
            f"got {type(tags).__name__}."
        )
    else:
        for tag in tags:
            if not isinstance(tag, str) or not tag:
                errors.append(
                    f"[{bp_id}] Each tag must be a non-empty string, "
                    f"got {tag!r}."
                )

    # ── Mode scope ────────────────────────────────────────────────────────────
    mode_scope = defn.get("mode_scope", [])
    if not isinstance(mode_scope, list):
        errors.append(
            f"[{bp_id}] 'mode_scope' must be a list of mode ID strings, "
            f"got {type(mode_scope).__name__}."
        )

    return errors


# ── Blueprint Compiler ────────────────────────────────────────────────────────

class BlueprintCompiler:
    """
    Compiles raw CGS actor definitions into EntityBlueprints.

    Stateless — one call to compile_all() per SchemaFactory.compile() run.
    The registry is passed in, not stored — BlueprintCompiler has no
    mutable state of its own.

    Usage
    -----
        registry  = CompositeComponentRegistry(...)
        compiler  = BlueprintCompiler(registry)
        reg       = compiler.compile_all(cgs["modes"][0]["actors"], "0.1.0")
    """

    def __init__(self, registry: ComponentRegistryProtocol) -> None:
        if not isinstance(registry, ComponentRegistryProtocol):
            raise TypeError(
                "BlueprintCompiler requires a ComponentRegistryProtocol. "
                f"Got {type(registry).__name__}."
            )
        self._registry = registry

    # ── Public API ────────────────────────────────────────────────────────────

    def compile_one(
        self,
        actor_definition: dict[str, Any],
        schema_version:   str = "0.1.0",
    ) -> EntityBlueprint:
        """
        Compiles a single actor_definition dict into an EntityBlueprint.

        Raises
        ------
        BlueprintCompilationError
            If the definition fails any validation check.
        """
        errors = _validate_actor_definition(actor_definition, self._registry)
        if errors:
            raise BlueprintCompilationError(errors)
        return self._build_blueprint(actor_definition, schema_version)

    def compile_all(
        self,
        actor_definitions: list[dict[str, Any]],
        schema_version:    str = "0.1.0",
    ) -> BlueprintRegistry:
        """
        Compiles all actor definitions from a CGS mode (or global actors list)
        into a populated BlueprintRegistry.

        Collects ALL validation errors across all definitions before raising,
        so the designer sees every problem at once rather than fix-one-recompile.

        Raises
        ------
        BlueprintCompilationError
            If any definition fails validation.
        BlueprintRegistryError
            If duplicate blueprint IDs are present across definitions.
        """
        all_errors: list[str] = []
        blueprints: list[EntityBlueprint] = []

        for defn in actor_definitions:
            errors = _validate_actor_definition(defn, self._registry)
            if errors:
                all_errors.extend(errors)
            else:
                blueprints.append(self._build_blueprint(defn, schema_version))

        if all_errors:
            raise BlueprintCompilationError(all_errors)

        reg = BlueprintRegistry()
        try:
            reg.register_all(blueprints)
        except BlueprintRegistryError as exc:
            raise BlueprintCompilationError([str(exc)]) from exc

        return reg

    # ── Internal ──────────────────────────────────────────────────────────────

    def _build_blueprint(
        self,
        defn:           dict[str, Any],
        schema_version: str,
    ) -> EntityBlueprint:
        """
        Builds an EntityBlueprint from a validated actor_definition dict.
        Assumes _validate_actor_definition() has already passed.
        """
        builder = EntityBlueprintBuilder(
            blueprint_id=defn["id"],
            actor_type=defn["actor_type"],
        )

        builder.set_control_type(defn.get("control_type", "AI_PROXY"))
        builder.set_prefab_id(defn.get("prefab_id"))
        builder.set_mode_scope(defn.get("mode_scope", []))

        for tag in defn.get("tags", []):
            builder.add_tag(tag)

        for comp in defn.get("components", []):
            builder.set_component_defaults(
                comp["type_id"],
                comp.get("defaults", {}),
            )

        return builder.build(schema_version=schema_version)