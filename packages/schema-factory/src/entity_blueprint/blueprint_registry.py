"""
blueprint_registry.py — BlueprintRegistry
==========================================
Stores compiled EntityBlueprints produced by BlueprintCompiler.
Provides lookup by blueprint ID and by actor type.

## Ownership
The BlueprintRegistry is owned by CompiledSchemaPackage.
It is populated once by BlueprintCompiler during SchemaFactory.compile()
and is read-only thereafter (I3).

## Determinism (D11)
All iteration methods return results sorted by blueprint ID ascending.
Same CGS → identical registry contents in identical iteration order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

from .entity_blueprint import EntityBlueprint


# ── Registry Error ────────────────────────────────────────────────────────────

class BlueprintRegistryError(Exception):
    """Raised when a BlueprintRegistry invariant is violated."""


# ── Blueprint Registry ────────────────────────────────────────────────────────

@dataclass
class BlueprintRegistry:
    """
    Stores and indexes compiled EntityBlueprints.

    All mutation happens during the compilation phase only.
    After SchemaFactory.compile() returns, the registry is treated
    as immutable — no new blueprints are registered at runtime (I3).

    Attributes
    ----------
    _blueprints : dict[str, EntityBlueprint]
        Internal store keyed by blueprint ID (ascending sort guaranteed
        by iteration methods, not by insertion order).
    """

    _blueprints: dict[str, EntityBlueprint] = field(
        default_factory=dict, repr=False
    )

    # ── Registration ──────────────────────────────────────────────────────────

    def register(self, blueprint: EntityBlueprint) -> None:
        """
        Registers a compiled blueprint.

        Raises
        ------
        BlueprintRegistryError
            If a blueprint with the same ID is already registered.
            Duplicate IDs are a schema invariant violation (I8).
        """
        if blueprint.id in self._blueprints:
            raise BlueprintRegistryError(
                f"Blueprint '{blueprint.id}' is already registered. "
                f"Duplicate blueprint IDs are not permitted — every actor "
                f"definition in the CGS must have a unique ID."
            )
        self._blueprints[blueprint.id] = blueprint

    def register_all(self, blueprints: list[EntityBlueprint]) -> None:
        """
        Registers multiple blueprints. Fails atomically on first duplicate.
        On failure, no partial state is committed.
        """
        # Validate before mutating (I8 — atomic or nothing)
        seen: set[str] = set(self._blueprints.keys())
        for bp in blueprints:
            if bp.id in seen:
                raise BlueprintRegistryError(
                    f"Duplicate blueprint ID '{bp.id}' in batch registration. "
                    f"No blueprints from this batch were registered."
                )
            seen.add(bp.id)
        # All clear — commit
        for bp in blueprints:
            self._blueprints[bp.id] = bp

    # ── Lookup ────────────────────────────────────────────────────────────────

    def get(self, blueprint_id: str) -> EntityBlueprint | None:
        """Returns the blueprint with the given ID, or None."""
        return self._blueprints.get(blueprint_id)

    def get_required(self, blueprint_id: str) -> EntityBlueprint:
        """
        Returns the blueprint with the given ID.

        Raises
        ------
        BlueprintRegistryError
            If no blueprint with this ID exists.
        """
        bp = self._blueprints.get(blueprint_id)
        if bp is None:
            raise BlueprintRegistryError(
                f"Blueprint '{blueprint_id}' not found in registry. "
                f"Registered IDs: {sorted(self._blueprints.keys())}"
            )
        return bp

    def get_by_actor_type(self, actor_type: str) -> list[EntityBlueprint]:
        """
        Returns all blueprints with the given actor_type, sorted by ID (D11).
        Returns an empty list if no blueprints match.
        """
        return sorted(
            (bp for bp in self._blueprints.values() if bp.actor_type == actor_type),
            key=lambda bp: bp.id,
        )

    def get_for_mode(self, mode_id: str) -> list[EntityBlueprint]:
        """
        Returns all blueprints active in the given game mode, sorted by ID (D11).
        Blueprints with an empty mode_scope are active in all modes.
        """
        return sorted(
            (bp for bp in self._blueprints.values() if bp.is_active_in_mode(mode_id)),
            key=lambda bp: bp.id,
        )

    def get_with_component(self, component_type_id: int) -> list[EntityBlueprint]:
        """
        Returns all blueprints that include the given component type, sorted (D11).
        Useful for impact analysis before schema mutations.
        """
        return sorted(
            (bp for bp in self._blueprints.values() if bp.has_component(component_type_id)),
            key=lambda bp: bp.id,
        )

    def contains(self, blueprint_id: str) -> bool:
        """Returns True if a blueprint with this ID is registered."""
        return blueprint_id in self._blueprints

    # ── Iteration ─────────────────────────────────────────────────────────────

    def all_blueprints(self) -> list[EntityBlueprint]:
        """Returns all blueprints sorted by ID ascending (D11)."""
        return sorted(self._blueprints.values(), key=lambda bp: bp.id)

    def all_ids(self) -> list[str]:
        """Returns all blueprint IDs sorted ascending (D11)."""
        return sorted(self._blueprints.keys())

    def all_actor_types(self) -> list[str]:
        """Returns the set of distinct actor types, sorted ascending (D11)."""
        return sorted({bp.actor_type for bp in self._blueprints.values()})

    def __iter__(self) -> Iterator[EntityBlueprint]:
        """Iterates blueprints in sorted ID order (D11)."""
        return iter(self.all_blueprints())

    def __len__(self) -> int:
        return len(self._blueprints)

    def __repr__(self) -> str:
        return f"BlueprintRegistry({len(self)} blueprints: {self.all_ids()})"

    # ── Validation ────────────────────────────────────────────────────────────

    def validate_no_orphaned_components(
        self, valid_component_type_ids: set[int]
    ) -> list[str]:
        """
        Checks that every component_type_id referenced by any blueprint
        exists in the provided valid set (the CompositeComponentRegistry).

        Returns a list of error strings (empty = valid).
        Used by SchemaValidationContract invariant I1.
        """
        errors: list[str] = []
        for bp in self.all_blueprints():
            for type_id in bp.component_ids():
                if type_id not in valid_component_type_ids:
                    errors.append(
                        f"Blueprint '{bp.id}' references component type_id "
                        f"{type_id} which is not in the CompositeComponentRegistry."
                    )
        return errors