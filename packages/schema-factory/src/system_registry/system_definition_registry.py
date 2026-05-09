"""
system_definition_registry.py — SystemDefinitionRegistry
=========================================================
Python schema-layer representation of game systems and a registry
that stores and validates them before they are handed to the SGC.

## Two SystemDefinition Types
The Rust `xace_core::schema::system_definition::SystemDefinition` is the
runtime struct consumed by the SGC pipeline. This module defines its Python
counterpart — `SchemaSystemDefinition` — which lives in the Schema Factory
and is used for design-time validation.

Both share the same field semantics. The Schema Factory compiles
SchemaSystemDefinition → dict → serialised JSON → deserialised by the Rust
core. The JSON bridge keeps the two layers decoupled.

## Validation Responsibility
SystemDefinitionRegistry validates:
    1. Unique system IDs (no duplicates)
    2. All component type_ids in reads/writes exist in ComponentDefinitionRegistry
    3. Phase assignments are valid ExecutionPhase values
    4. No self-references in depends_on

SystemValidator (system_validator.py) handles per-definition rules.
This registry handles cross-definition rules (duplicate IDs, etc.).

## Phase Vocabulary
Matches Rust ExecutionPhase ordinals exactly:
    Initialization=0, Input=1, Simulation=2, PostSimulation=3, Cleanup=4
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..component_registry.component_definition_registry import (
        ComponentDefinitionRegistry,
    )

# ── Execution Phase ───────────────────────────────────────────────────────────

VALID_PHASES: frozenset[str] = frozenset({
    "Initialization",
    "Input",
    "Simulation",
    "PostSimulation",
    "Cleanup",
})

PHASE_ORDINALS: dict[str, int] = {
    "Initialization":  0,
    "Input":           1,
    "Simulation":      2,
    "PostSimulation":  3,
    "Cleanup":         4,
}


# ── Schema System Definition ──────────────────────────────────────────────────

@dataclass(frozen=True)
class SchemaSystemDefinition:
    """
    Python schema-layer representation of one game system.

    Mirrors xace_core::schema::system_definition::SystemDefinition (Rust).
    Produced by the GDE and validated by the Schema Factory before being
    serialised to JSON and consumed by the SGC pipeline.

    Attributes
    ----------
    id : str
        Unique system identifier within the CGS.
        Examples: "sys_movement", "sys_ai_behavior", "sys_damage"
    display_name : str
        Human-readable name shown in the builder UI.
    phase : str
        Execution phase. Must be one of VALID_PHASES.
    reads : tuple[int, ...]
        Component type IDs this system reads each tick. Sorted ascending (D11).
    writes : tuple[int, ...]
        Component type IDs this system writes via MutationGate. Sorted (D11).
    depends_on : tuple[str, ...]
        Explicit ordering dependencies: other system IDs that must run first.
    deterministic : bool
        Must be True for all XACE systems. False triggers a validation warning.
    version_major : int
        Implementation version major. Embedded in ExecutionPlan.
    version_minor : int
        Implementation version minor.
    description : str
        Plain-English description for Design Mentor and builder UI.
    """

    id:             str
    display_name:   str
    phase:          str
    reads:          tuple[int, ...]   = ()
    writes:         tuple[int, ...]   = ()
    depends_on:     tuple[str, ...]   = ()
    deterministic:  bool              = True
    version_major:  int               = 1
    version_minor:  int               = 0
    description:    str               = ""

    def phase_ordinal(self) -> int:
        """Returns the integer ordinal of this system's phase (0–4)."""
        return PHASE_ORDINALS.get(self.phase, -1)

    def reads_component(self, type_id: int) -> bool:
        return type_id in self.reads

    def writes_component(self, type_id: int) -> bool:
        return type_id in self.writes

    def all_referenced_type_ids(self) -> list[int]:
        """Returns all type_ids in reads + writes, deduplicated, sorted (D11)."""
        return sorted(set(self.reads) | set(self.writes))

    def to_rust_dict(self) -> dict:
        """
        Serialises to a dict matching the Rust SystemDefinition JSON schema.
        Used by SchemaFactory to produce the JSON payload for the SGC.
        """
        return {
            "id":            self.id,
            "display_name":  self.display_name,
            "phase":         self.phase,
            "reads":         sorted(self.reads),
            "writes":        sorted(self.writes),
            "depends_on":    sorted(self.depends_on),
            "deterministic": self.deterministic,
            "version": {
                "major": self.version_major,
                "minor": self.version_minor,
            },
            "description":   self.description,
        }

    def __repr__(self) -> str:
        return (
            f"SchemaSystemDefinition(id={self.id!r}, phase={self.phase!r}, "
            f"reads={list(self.reads)}, writes={list(self.writes)})"
        )


# ── Registry Error ────────────────────────────────────────────────────────────

class SystemDefinitionRegistryError(Exception):
    """Raised when a SystemDefinitionRegistry invariant is violated."""


# ── System Definition Registry ────────────────────────────────────────────────

@dataclass
class SystemDefinitionRegistry:
    """
    Stores and validates SchemaSystemDefinitions.

    Populated once per SchemaFactory.compile() run. Read-only after the
    CompiledSchemaPackage is returned (I3).

    Cross-definition checks performed here:
    - Unique system IDs (no duplicates)
    - All depends_on references resolve to known system IDs

    Per-definition checks are delegated to SystemValidator.
    """

    _systems: dict[str, SchemaSystemDefinition] = field(
        default_factory=dict, repr=False
    )

    # ── Registration ──────────────────────────────────────────────────────────

    def register(self, system: SchemaSystemDefinition) -> None:
        """
        Registers one system definition.

        Raises
        ------
        SystemDefinitionRegistryError
            If a system with the same ID already exists.
        """
        if system.id in self._systems:
            raise SystemDefinitionRegistryError(
                f"System '{system.id}' is already registered. "
                f"Every system in the CGS must have a unique ID."
            )
        self._systems[system.id] = system

    def register_all(self, systems: list[SchemaSystemDefinition]) -> None:
        """
        Registers multiple systems atomically.
        Validates uniqueness across the batch before committing any (I8).
        """
        seen: set[str] = set(self._systems.keys())
        for sys in systems:
            if sys.id in seen:
                raise SystemDefinitionRegistryError(
                    f"Duplicate system ID '{sys.id}' in registration batch. "
                    f"No systems from this batch were registered."
                )
            seen.add(sys.id)
        for sys in systems:
            self._systems[sys.id] = sys

    # ── Lookup ────────────────────────────────────────────────────────────────

    def get(self, system_id: str) -> SchemaSystemDefinition | None:
        return self._systems.get(system_id)

    def get_required(self, system_id: str) -> SchemaSystemDefinition:
        sys = self._systems.get(system_id)
        if sys is None:
            raise SystemDefinitionRegistryError(
                f"System '{system_id}' not found. "
                f"Registered IDs: {sorted(self._systems.keys())}"
            )
        return sys

    def get_by_phase(self, phase: str) -> list[SchemaSystemDefinition]:
        """Returns all systems in the given phase, sorted by ID (D11)."""
        return sorted(
            (s for s in self._systems.values() if s.phase == phase),
            key=lambda s: s.id,
        )

    def get_writers_of(self, type_id: int) -> list[SchemaSystemDefinition]:
        """Returns all systems that write the given component type, sorted (D11)."""
        return sorted(
            (s for s in self._systems.values() if s.writes_component(type_id)),
            key=lambda s: s.id,
        )

    def get_readers_of(self, type_id: int) -> list[SchemaSystemDefinition]:
        """Returns all systems that read the given component type, sorted (D11)."""
        return sorted(
            (s for s in self._systems.values() if s.reads_component(type_id)),
            key=lambda s: s.id,
        )

    def contains(self, system_id: str) -> bool:
        return system_id in self._systems

    # ── Iteration ─────────────────────────────────────────────────────────────

    def all_systems(self) -> list[SchemaSystemDefinition]:
        """Returns all systems sorted by ID ascending (D11)."""
        return sorted(self._systems.values(), key=lambda s: s.id)

    def all_ids(self) -> list[str]:
        return sorted(self._systems.keys())

    # ── Cross-Definition Validation ───────────────────────────────────────────

    def validate_dependency_references(self) -> list[str]:
        """
        Checks that every depends_on entry in every system resolves to a
        known system ID. Returns error strings (empty = valid).
        """
        errors: list[str] = []
        for sys in self.all_systems():
            for dep_id in sys.depends_on:
                if dep_id == sys.id:
                    errors.append(
                        f"System '{sys.id}' lists itself in depends_on. "
                        f"A system cannot depend on itself."
                    )
                elif dep_id not in self._systems:
                    errors.append(
                        f"System '{sys.id}' depends_on '{dep_id}' "
                        f"which is not registered in the CGS. "
                        f"Add the missing system or remove the dependency."
                    )
        return errors

    def validate_component_references(
        self, component_registry: "ComponentDefinitionRegistry"
    ) -> list[str]:
        """
        Checks that all component type_ids in reads/writes exist in the
        ComponentDefinitionRegistry. Returns error strings (empty = valid).
        """
        errors: list[str] = []
        for sys in self.all_systems():
            errors.extend(
                component_registry.validate_type_ids(
                    sys.all_referenced_type_ids()
                )
            )
        return errors

    def to_rust_dicts(self) -> list[dict]:
        """
        Serialises all systems to Rust-compatible dicts, sorted by ID (D11).
        Used by SchemaFactory to build the SGC input payload.
        """
        return [s.to_rust_dict() for s in self.all_systems()]

    # ── Stats ─────────────────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._systems)

    def __repr__(self) -> str:
        phases = {p: len(self.get_by_phase(p)) for p in VALID_PHASES
                  if self.get_by_phase(p)}
        return f"SystemDefinitionRegistry({len(self)} systems, phases={phases})"