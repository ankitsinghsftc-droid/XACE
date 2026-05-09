"""
compiled_schema_package.py — CompiledSchemaPackage
====================================================
Immutable output of SchemaFactory.compile().

The CompiledSchemaPackage is the single artifact that downstream stages
consume. It contains:
    - BlueprintRegistry        — all entity blueprints, compiled and indexed
    - ComponentDefinitionRegistry — full UCL+DCL+GCL component schema
    - SystemDefinitionRegistry — all system declarations, validated
    - SchemaVersionManager     — full CGS version chain
    - Validation metadata      — invariant check results, warnings

## Immutability
The package is frozen after compile() returns. No downstream stage may
modify any registry contained within it (I3). The SGC, Design Mentor,
and builder UI all read from this package — they never write to it.

## Lifecycle
CGS mutated → SchemaFactory.compile() → new CompiledSchemaPackage
The old package is discarded. There is never more than one
CompiledSchemaPackage per game session (the current one).

## What Is NOT in the Package
The raw CGS dict is not stored here. The package holds the compiled
outputs only. Callers that need the raw CGS read it from CGSManager
(Phase 12). This keeps the package compact and avoids confusion
between the source of truth (CGS) and the compiled projection (package).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .entity_blueprint.blueprint_registry import BlueprintRegistry
    from .component_registry.component_definition_registry import (
        ComponentDefinitionRegistry,
    )
    from .system_registry.system_definition_registry import (
        SystemDefinitionRegistry,
    )
    from .versioning.schema_version_manager import SchemaVersionManager
    from .validation.invariant_checker import InvariantReport
    from .validation.schema_validation_contract import ValidationReport


# ── Compiled Schema Package ───────────────────────────────────────────────────

@dataclass(frozen=True)
class CompiledSchemaPackage:
    """
    Immutable compiled output of SchemaFactory.compile().

    Attributes
    ----------
    schema_version : str
        MAJOR.MINOR.PATCH version of the CGS this package was compiled from.
        Matches metadata.version in the source CGS dict.
    cgs_hash : str
        SHA-256 hash of the source CGS content.
        Used by the runtime to detect stale ExecutionPlans (D10, I7).
    blueprint_registry : BlueprintRegistry
        All compiled EntityBlueprints, indexed by ID and actor_type.
    component_registry : ComponentDefinitionRegistry
        Full UCL+DCL+GCL component schema registry.
    system_registry : SystemDefinitionRegistry
        All validated system declarations, ready for SGC input.
    version_manager : SchemaVersionManager
        CGS version chain with full snapshot history.
    validation_report : ValidationReport
        Structural validation results from SchemaValidationContract.
    invariant_report : InvariantReport
        Invariant check results from InvariantChecker.
    compilation_warnings : tuple[str, ...]
        Non-fatal warnings collected during compilation.
        Surfaced in the builder UI for designer review.
    default_mode_id : str | None
        ID of the mode marked is_default=True, or None if not set.
    all_mode_ids : tuple[str, ...]
        All mode IDs declared in this CGS, in declaration order.
    game_name : str
        From CGS metadata.name. Shown in builder UI and Design Mentor.
    """

    schema_version:       str
    cgs_hash:             str
    blueprint_registry:   "BlueprintRegistry"
    component_registry:   "ComponentDefinitionRegistry"
    system_registry:      "SystemDefinitionRegistry"
    version_manager:      "SchemaVersionManager"
    validation_report:    "ValidationReport"
    invariant_report:     "InvariantReport"
    compilation_warnings: tuple[str, ...]
    default_mode_id:      str | None
    all_mode_ids:         tuple[str, ...]
    game_name:            str                  = ""

    # ── Validity ──────────────────────────────────────────────────────────────

    @property
    def is_valid(self) -> bool:
        """
        True if both the structural validation and all invariant checks pass.
        A package with is_valid=False should not be used by the runtime.
        """
        return (
            self.validation_report.is_valid
            and self.invariant_report.is_valid
        )

    @property
    def has_warnings(self) -> bool:
        return (
            len(self.compilation_warnings) > 0
            or self.validation_report.has_warnings
            or self.invariant_report.has_warnings
            if hasattr(self.invariant_report, "has_warnings")
            else len(self.compilation_warnings) > 0
        )

    def all_errors(self) -> list[str]:
        """Returns all hard errors from validation and invariant checks."""
        return (
            self.validation_report.errors
            + self.invariant_report.all_errors()
        )

    def all_warnings(self) -> list[str]:
        """Returns all warnings from every source."""
        return (
            list(self.compilation_warnings)
            + self.validation_report.warnings
        )

    # ── Registry Access ───────────────────────────────────────────────────────

    def total_blueprint_count(self) -> int:
        return len(self.blueprint_registry)

    def total_system_count(self) -> int:
        return len(self.system_registry)

    def total_component_type_count(self) -> int:
        return len(self.component_registry)

    def mode_count(self) -> int:
        return len(self.all_mode_ids)

    def has_mode(self, mode_id: str) -> bool:
        return mode_id in self.all_mode_ids

    # ── SGC Input Serialisation ───────────────────────────────────────────────

    def to_sgc_input(self) -> list[dict[str, Any]]:
        """
        Serialises all system definitions to the list of dicts expected by
        the Rust SGC pipeline (xace_core::schema::system_definition::SystemDefinition).

        Used by SchemaFactory to build the SGC compilation payload.
        Returns systems sorted by ID (D11).
        """
        return self.system_registry.to_rust_dicts()

    # ── Display ───────────────────────────────────────────────────────────────

    def summary(self) -> str:
        status = "VALID" if self.is_valid else "INVALID"
        return (
            f"CompiledSchemaPackage [{status}] "
            f"v{self.schema_version} '{self.game_name}': "
            f"{self.total_blueprint_count()} blueprints, "
            f"{self.total_system_count()} systems, "
            f"{self.total_component_type_count()} component types, "
            f"{self.mode_count()} mode(s)"
        )

    def __repr__(self) -> str:
        return f"CompiledSchemaPackage({self.summary()})"