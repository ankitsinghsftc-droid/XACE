"""
component_definition_registry.py — ComponentDefinitionRegistry
==============================================================
Maps component type IDs to their ComponentDefinitions.

This is the Schema Factory's authoritative source for component schemas.
It is built from the CompositeComponentRegistry (UCL + DCL + GCL) at the
start of each SchemaFactory.compile() run.

## Relationship to the Runtime DCL Registry
The runtime DCL registry (packages/dcl/dcl_registry.py) holds the
actual Python component classes used at game load time. The
ComponentDefinitionRegistry is a schema-layer projection: it holds
only the type_id→name→field_schema mapping needed for CGS validation.
The two registries are built from the same source data but serve
different consumers.

## Frozen UCL Core (Audit 1)
UCL type_ids 1–10 are registered as is_ucl_core=True.
These definitions cannot be removed or overwritten — any attempt
raises ComponentDefinitionRegistryError.

## Domain Type ID Ranges (locked per CLAUDE.md)
UCL core:       1–10
DCL combat:     100–119
DCL character:  120–139
DCL physics:    140–159
DCL ai:         160–179
DCL stealth:    180–199
DCL rpg:        200–229
DCL world:      230–259
DCL interaction:260–279
DCL camera:     280–299
DCL audio:      300–319
DCL network:    320–339
DCL ui:         340–359
DCL persistence:360–379
GCL:            10000+
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .component_definition import ComponentDefinition


# ── Registry Error ────────────────────────────────────────────────────────────

class ComponentDefinitionRegistryError(Exception):
    """Raised when a ComponentDefinitionRegistry invariant is violated."""


# ── Type ID Range Helpers ─────────────────────────────────────────────────────

_UCL_RANGE      = range(1,    11)
_DCL_RANGE      = range(100,  10000)
_GCL_MIN        = 10_000

def _domain_from_type_id(type_id: int) -> str:
    """Infers the expected domain string from a type_id."""
    if type_id in _UCL_RANGE:
        return "ucl"
    if type_id >= _GCL_MIN:
        return "gcl"
    # DCL sub-ranges
    ranges = {
        range(100, 120): "dcl/combat",
        range(120, 140): "dcl/character",
        range(140, 160): "dcl/physics",
        range(160, 180): "dcl/ai",
        range(180, 200): "dcl/stealth",
        range(200, 230): "dcl/rpg",
        range(230, 260): "dcl/world",
        range(260, 280): "dcl/interaction",
        range(280, 300): "dcl/camera",
        range(300, 320): "dcl/audio",
        range(320, 340): "dcl/network",
        range(340, 360): "dcl/ui",
        range(360, 380): "dcl/persistence",
    }
    for r, domain in ranges.items():
        if type_id in r:
            return domain
    return "dcl/unknown"


# ── Component Definition Registry ─────────────────────────────────────────────

@dataclass
class ComponentDefinitionRegistry:
    """
    Schema-layer registry: maps component type_id → ComponentDefinition.

    Built by SchemaFactory from the game's CompositeComponentRegistry.
    Consumed by BlueprintCompiler, InvariantChecker, and SystemValidator.

    Mutability
    ----------
    Mutable during the compilation phase (register/register_all).
    Treated as read-only once SchemaFactory.compile() returns it
    inside a CompiledSchemaPackage.
    """

    _definitions: dict[int, ComponentDefinition] = field(
        default_factory=dict, repr=False
    )

    # ── Registration ──────────────────────────────────────────────────────────

    def register(self, definition: ComponentDefinition) -> None:
        """
        Registers one ComponentDefinition.

        Raises
        ------
        ComponentDefinitionRegistryError
            - If a UCL core component (type_id 1–10) is already registered
              and the caller tries to overwrite it (UCL is frozen).
            - If a non-UCL component with the same type_id already exists.
        """
        existing = self._definitions.get(definition.type_id)

        if existing is not None:
            if existing.is_ucl_core:
                raise ComponentDefinitionRegistryError(
                    f"UCL core component type_id {definition.type_id} "
                    f"({existing.name}) is frozen and cannot be overwritten. "
                    f"The UCL core of 10 components is locked per Audit 1."
                )
            raise ComponentDefinitionRegistryError(
                f"Component type_id {definition.type_id} ({existing.name}) "
                f"is already registered. Use a different type_id or "
                f"increment the component version instead."
            )

        self._definitions[definition.type_id] = definition

    def register_all(self, definitions: list[ComponentDefinition]) -> None:
        """
        Registers multiple definitions atomically.
        On any duplicate, no definitions from the batch are committed (I8).
        """
        # Validate before mutating
        incoming_ids: dict[int, str] = {}
        for defn in definitions:
            existing = self._definitions.get(defn.type_id)
            if existing and existing.is_ucl_core:
                raise ComponentDefinitionRegistryError(
                    f"UCL core component type_id {defn.type_id} "
                    f"({existing.name}) is frozen — cannot overwrite."
                )
            if defn.type_id in incoming_ids:
                raise ComponentDefinitionRegistryError(
                    f"Duplicate type_id {defn.type_id} within the same "
                    f"registration batch ({defn.name} vs "
                    f"{incoming_ids[defn.type_id]})."
                )
            if existing is not None:
                raise ComponentDefinitionRegistryError(
                    f"Component type_id {defn.type_id} ({existing.name}) "
                    f"is already registered."
                )
            incoming_ids[defn.type_id] = defn.name

        # All clear — commit
        for defn in definitions:
            self._definitions[defn.type_id] = defn

    # ── Lookup ────────────────────────────────────────────────────────────────

    def get(self, type_id: int) -> ComponentDefinition | None:
        """Returns the ComponentDefinition for the given type_id, or None."""
        return self._definitions.get(type_id)

    def get_required(self, type_id: int) -> ComponentDefinition:
        """
        Returns the ComponentDefinition for the given type_id.

        Raises
        ------
        ComponentDefinitionRegistryError
            If the type_id is not registered.
        """
        defn = self._definitions.get(type_id)
        if defn is None:
            raise ComponentDefinitionRegistryError(
                f"Component type_id {type_id} is not registered in the "
                f"ComponentDefinitionRegistry. "
                f"Ensure the domain containing this component is declared "
                f"in game_config.yaml and loaded before compilation."
            )
        return defn

    def get_by_name(self, name: str) -> ComponentDefinition | None:
        """Returns the first ComponentDefinition with the given name, or None."""
        for defn in self._definitions.values():
            if defn.name == name:
                return defn
        return None

    def get_by_domain(self, domain: str) -> list[ComponentDefinition]:
        """
        Returns all definitions in the given domain, sorted by type_id (D11).
        Examples: get_by_domain("ucl"), get_by_domain("dcl/combat")
        """
        return sorted(
            (d for d in self._definitions.values() if d.domain == domain),
            key=lambda d: d.type_id,
        )

    # ── Protocol surface (used by BlueprintCompiler) ──────────────────────────

    def has_component(self, type_id: int) -> bool:
        """Returns True if the given type_id is registered."""
        return type_id in self._definitions

    def get_field_names(self, type_id: int) -> set[str]:
        """
        Returns all valid field names for the given component type.
        Returns an empty set if the type_id is not registered.
        """
        defn = self._definitions.get(type_id)
        return defn.field_names() if defn is not None else set()

    # ── Iteration ─────────────────────────────────────────────────────────────

    def all_definitions(self) -> list[ComponentDefinition]:
        """Returns all definitions sorted by type_id ascending (D11)."""
        return sorted(self._definitions.values(), key=lambda d: d.type_id)

    def all_type_ids(self) -> list[int]:
        """Returns all registered type_ids sorted ascending (D11)."""
        return sorted(self._definitions.keys())

    def ucl_definitions(self) -> list[ComponentDefinition]:
        """Returns the 10 UCL core component definitions, sorted by type_id."""
        return [d for d in self.all_definitions() if d.is_ucl_core]

    def dcl_definitions(self) -> list[ComponentDefinition]:
        """Returns all DCL component definitions, sorted by type_id."""
        return [
            d for d in self.all_definitions()
            if not d.is_ucl_core and d.type_id < _GCL_MIN
        ]

    def gcl_definitions(self) -> list[ComponentDefinition]:
        """Returns all GCL component definitions, sorted by type_id."""
        return [d for d in self.all_definitions() if d.type_id >= _GCL_MIN]

    def all_domains(self) -> list[str]:
        """Returns the set of distinct domain strings, sorted (D11)."""
        return sorted({d.domain for d in self._definitions.values()})

    # ── Validation ────────────────────────────────────────────────────────────

    def validate_type_ids(self, type_ids: list[int]) -> list[str]:
        """
        Checks that every type_id in the list is registered.
        Returns a list of error strings (empty = all valid).
        Used by SystemValidator when checking system read/write declarations.
        """
        errors: list[str] = []
        for tid in sorted(set(type_ids)):
            if not self.has_component(tid):
                errors.append(
                    f"Component type_id {tid} is not registered in the "
                    f"CompositeComponentRegistry "
                    f"(inferred domain: {_domain_from_type_id(tid)}). "
                    f"Ensure the required domain is declared in game_config.yaml."
                )
        return errors

    def validate_gcl_no_collision(self) -> list[str]:
        """
        Validates GCL components do not use names already taken by UCL/DCL.
        Returns error strings for any collisions (invariant I11).
        """
        ucl_dcl_names = {
            d.name for d in self._definitions.values()
            if d.type_id < _GCL_MIN
        }
        errors: list[str] = []
        for d in self.gcl_definitions():
            if d.name in ucl_dcl_names:
                errors.append(
                    f"GCL component '{d.name}' (type_id={d.type_id}) "
                    f"collides with an existing UCL/DCL component name. "
                    f"GCL components must have unique names (I11)."
                )
        return errors

    # ── Stats ─────────────────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._definitions)

    def __repr__(self) -> str:
        return (
            f"ComponentDefinitionRegistry("
            f"ucl={len(self.ucl_definitions())}, "
            f"dcl={len(self.dcl_definitions())}, "
            f"gcl={len(self.gcl_definitions())})"
        )