"""
entity_blueprint.py — EntityBlueprint
======================================
Compiled representation of one CGS actor definition.

The blueprint_compiler reads a raw actor definition dict from the CGS and
produces an EntityBlueprint with fully resolved component defaults.
The runtime spawner reads EntityBlueprints to instantiate entities — it
never touches the raw CGS directly (I3).

## Immutability
EntityBlueprints are frozen after compilation. The Schema Factory
produces them once per CGS version; a new CGS version produces new
blueprints via the blueprint_compiler.

## Component Defaults
component_defaults maps component_type_id (int) → dict of field_name → value.
Only fields explicitly set in the actor definition are stored. The runtime
fills remaining fields from the component schema's own defaults.

Example:
    {
        1:   {"entity_name": "Zombie", "entity_type": "ENEMY", "tags": ["hostile"]},
        100: {"current": 80, "max": 80, "regen_rate": 0.0},
        160: {"behavior_model": "CHASE", "detection_radius": 12.0},
    }

## Mode Scope
An empty mode_scope means the blueprint is active in ALL game modes.
A non-empty mode_scope lists exactly which mode IDs activate this blueprint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EntityBlueprint:
    """
    Compiled, immutable representation of one CGS actor definition.

    Produced by BlueprintCompiler. Stored in BlueprintRegistry.
    Consumed by the runtime spawner and Design Mentor.

    Attributes
    ----------
    id : str
        Unique actor identifier. Matches ActorDefinition.id in the CGS.
        Examples: "actor_player", "actor_zombie", "actor_health_pickup"

    actor_type : str
        Actor type enum value from ActorDefinition.
        Examples: "PLAYER", "ENEMY", "PROJECTILE", "PICKUP", "NPC"

    component_defaults : dict[int, dict[str, Any]]
        Resolved default field values per component type.
        Key: component_type_id (int, matches CompositeComponentRegistry).
        Value: dict of field_name → default_value for that component.
        Fields absent from this dict use the component schema's own defaults.

    tags : tuple[str, ...]
        Immutable tag set for this entity type.
        Copied from COMP_IDENTITY_V1.tags in the actor definition.
        Used for query filtering and interaction rules.

    prefab_id : str | None
        Optional prefab asset reference ID.
        None when the entity has no associated prefab (e.g. pure-logic entities).

    mode_scope : tuple[str, ...]
        Game mode IDs in which this blueprint is active.
        Empty tuple = active in ALL modes.
        Non-empty = active ONLY in the listed modes.

    control_type : str
        How this entity receives input.
        One of: "HUMAN", "AI_PROXY", "NETWORK_REMOTE", "NONE"

    schema_version : str
        The CGS schema version this blueprint was compiled from.
        Used for migration validation when loading old saves (Audit 7).
    """

    id:                  str
    actor_type:          str
    component_defaults:  dict[int, dict[str, Any]]
    tags:                tuple[str, ...]        = field(default_factory=tuple)
    prefab_id:           str | None             = None
    mode_scope:          tuple[str, ...]        = field(default_factory=tuple)
    control_type:        str                    = "AI_PROXY"
    schema_version:      str                    = "0.1.0"

    # ── Queries ───────────────────────────────────────────────────────────────

    def has_component(self, component_type_id: int) -> bool:
        """Returns True if this blueprint includes the given component type."""
        return component_type_id in self.component_defaults

    def component_ids(self) -> list[int]:
        """Returns component type IDs in ascending order (D11)."""
        return sorted(self.component_defaults.keys())

    def defaults_for(self, component_type_id: int) -> dict[str, Any]:
        """
        Returns the resolved default field values for a component type.
        Returns an empty dict if the component is not in this blueprint.
        """
        return dict(self.component_defaults.get(component_type_id, {}))

    def is_active_in_mode(self, mode_id: str) -> bool:
        """
        Returns True if this blueprint is active in the given game mode.
        An empty mode_scope means active in ALL modes.
        """
        if not self.mode_scope:
            return True
        return mode_id in self.mode_scope

    def is_player_controlled(self) -> bool:
        """Returns True if this entity is controlled by a human player."""
        return self.control_type == "HUMAN"

    def is_network_replicated(self) -> bool:
        """Returns True if this entity receives network input."""
        return self.control_type == "NETWORK_REMOTE"

    # ── Display ───────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"EntityBlueprint(id={self.id!r}, actor_type={self.actor_type!r}, "
            f"components={self.component_ids()}, "
            f"mode_scope={list(self.mode_scope) or 'ALL'})"
        )


# ── Builder ───────────────────────────────────────────────────────────────────

class EntityBlueprintBuilder:
    """
    Mutable builder for EntityBlueprint.

    Used by BlueprintCompiler to accumulate component defaults before
    freezing into an immutable EntityBlueprint.

    Usage
    -----
        builder = EntityBlueprintBuilder("actor_zombie", "ENEMY")
        builder.set_component_defaults(100, {"current": 80, "max": 80})
        builder.set_component_defaults(160, {"behavior_model": "CHASE"})
        builder.add_tag("hostile")
        blueprint = builder.build(schema_version="0.1.0")
    """

    def __init__(self, blueprint_id: str, actor_type: str) -> None:
        self._id:                 str                    = blueprint_id
        self._actor_type:         str                    = actor_type
        self._component_defaults: dict[int, dict[str, Any]] = {}
        self._tags:               list[str]              = []
        self._prefab_id:          str | None             = None
        self._mode_scope:         list[str]              = []
        self._control_type:       str                    = "AI_PROXY"

    def set_component_defaults(
        self, component_type_id: int, defaults: dict[str, Any]
    ) -> "EntityBlueprintBuilder":
        """Sets or replaces defaults for one component type."""
        self._component_defaults[component_type_id] = dict(defaults)
        return self

    def add_tag(self, tag: str) -> "EntityBlueprintBuilder":
        if tag not in self._tags:
            self._tags.append(tag)
        return self

    def set_prefab_id(self, prefab_id: str | None) -> "EntityBlueprintBuilder":
        self._prefab_id = prefab_id
        return self

    def set_mode_scope(self, mode_ids: list[str]) -> "EntityBlueprintBuilder":
        self._mode_scope = list(mode_ids)
        return self

    def set_control_type(self, control_type: str) -> "EntityBlueprintBuilder":
        self._control_type = control_type
        return self

    def build(self, schema_version: str = "0.1.0") -> EntityBlueprint:
        """Freezes the builder into an immutable EntityBlueprint."""
        return EntityBlueprint(
            id=self._id,
            actor_type=self._actor_type,
            component_defaults=dict(self._component_defaults),
            tags=tuple(sorted(self._tags)),        # sorted for D11
            prefab_id=self._prefab_id,
            mode_scope=tuple(self._mode_scope),
            control_type=self._control_type,
            schema_version=schema_version,
        )