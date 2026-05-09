"""
schema_factory.py — SchemaFactory
===================================
Entry point for the Schema Factory package (Phase 11).

Orchestrates all submodules in the correct order and returns a
CompiledSchemaPackage. This is the single public API that downstream
stages (SGC, GDE, Design Mentor) call.

## Pipeline Order

    1. SchemaValidationContract.validate()
       Structural checks — blocks on any hard error before any submodule runs.

    2. ModeValidator.validate_all()
       Per-mode and cross-mode structural checks.

    3. ModeCompositionEngine.compose_all()
       Merges global_systems + per-mode overrides into ComposedModes.

    4. BlueprintCompiler.compile_all() [per mode]
       Compiles actor definitions into EntityBlueprints. Populates BlueprintRegistry.

    5. SystemValidator.validate_all() [all systems]
       Per-system validation against ComponentDefinitionRegistry.

    6. SystemDefinitionRegistry.validate_dependency_references()
       Cross-system depends_on resolution check.

    7. SchemaVersionManager
       Initialised from the CGS metadata, or restored from existing chain.

    8. InvariantChecker.check()
       Enforces all 15 global invariants.

    9. CompiledSchemaPackage assembled and returned.

## Error Strategy
SchemaFactory collects ALL errors from each stage before deciding whether
to raise. Within each stage, errors are also fully collected. The designer
sees the complete picture in one compilation attempt.

Raises SchemaFactoryError only after all stages have run. If only warnings
exist, the package is returned with is_valid=True and warnings populated.

## Component Registry Injection
SchemaFactory does not build the ComponentDefinitionRegistry — it receives
it as a constructor argument. The registry is assembled at game load time
from UCL+DCL+GCL (packages/dcl/dcl_registry.py, Phase 1). This keeps the
Schema Factory decoupled from the specific domain packages a game uses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .entity_blueprint.blueprint_compiler import BlueprintCompiler, BlueprintCompilationError
from .entity_blueprint.blueprint_registry import BlueprintRegistry
from .component_registry.component_definition_registry import ComponentDefinitionRegistry
from .system_registry.system_definition_registry import (
    SystemDefinitionRegistry,
    SchemaSystemDefinition,
    VALID_PHASES,
    SystemVersion,
)
from .system_registry.system_validator import SystemValidator
from .versioning.schema_version_manager import SchemaVersionManager
from .versioning.schema_snapshot import SchemaSnapshot
from .diff_migration.schema_diff_engine import SchemaDiffEngine
from .diff_migration.migration_rule_generator import MigrationRuleGenerator, MigrationPlan
from .mode_composition.mode_validator import ModeValidator
from .mode_composition.mode_composition_engine import ModeCompositionEngine, ComposedMode
from .validation.schema_validation_contract import SchemaValidationContract, ValidationReport
from .validation.invariant_checker import InvariantChecker, InvariantReport
from .compiled_schema_package import CompiledSchemaPackage


# ── Schema Factory Error ──────────────────────────────────────────────────────

@dataclass
class SchemaFactoryError(Exception):
    """
    Raised when SchemaFactory.compile() encounters hard errors.

    Attributes
    ----------
    errors : list[str]
        All hard error strings collected across every pipeline stage.
    stage : str
        The stage at which compilation was aborted.
        One of: "validation", "mode_validation", "blueprint_compilation",
                "system_validation", "invariant_check"
    """

    errors: list[str]
    stage:  str

    def __str__(self) -> str:
        header = f"SchemaFactory [{self.stage}]: {len(self.errors)} error(s):"
        lines  = "\n".join(f"  [{i+1}] {e}" for i, e in enumerate(self.errors))
        return f"{header}\n{lines}"


# ── Schema Factory ────────────────────────────────────────────────────────────

class SchemaFactory:
    """
    Compiles a CGS dict into a CompiledSchemaPackage.

    The component_registry must be pre-assembled (UCL + all declared DCL
    domains + GCL). SchemaFactory does not load components — it validates
    and compiles against the registry it receives.

    Usage
    -----
        # At game load time:
        component_registry = build_composite_registry(game_config)
        factory            = SchemaFactory(component_registry)

        # On each CGS mutation:
        package = factory.compile(cgs_dict, schema_version="0.1.1")
    """

    def __init__(self, component_registry: ComponentDefinitionRegistry) -> None:
        self._component_registry = component_registry

    # ── Public API ────────────────────────────────────────────────────────────

    def compile(
        self,
        cgs:            dict[str, Any],
        schema_version: str | None = None,
    ) -> CompiledSchemaPackage:
        """
        Compiles a CGS dict into an immutable CompiledSchemaPackage.

        Parameters
        ----------
        cgs : dict[str, Any]
            The full canonical CGS dict.
        schema_version : str | None
            If supplied, overrides the version in cgs["metadata"]["version"].
            Use this when the version was bumped by SchemaVersionManager
            before calling compile().

        Returns
        -------
        CompiledSchemaPackage
            Fully compiled package. is_valid=True if all checks pass.

        Raises
        ------
        SchemaFactoryError
            If any hard errors are found in any pipeline stage.
        """
        all_warnings: list[str] = []
        effective_version = schema_version or cgs.get("metadata", {}).get("version", "0.1.0")
        cgs_hash          = cgs.get("metadata", {}).get("cgs_hash", "")
        game_name         = cgs.get("metadata", {}).get("name", "")

        # ── Stage 1: Structural validation ───────────────────────────────────
        validation_report = self._run_validation(cgs)
        if not validation_report.is_valid:
            raise SchemaFactoryError(
                errors=validation_report.errors,
                stage="validation",
            )
        all_warnings.extend(validation_report.warnings)

        # ── Stage 2: Mode validation ──────────────────────────────────────────
        modes = cgs.get("modes", [])
        mode_validator  = ModeValidator(self._component_registry)
        mode_errors     = mode_validator.collect_errors(modes)
        if mode_errors:
            raise SchemaFactoryError(errors=mode_errors, stage="mode_validation")

        # ── Stage 3: Mode composition ─────────────────────────────────────────
        composition_result = ModeCompositionEngine.compose_all(cgs)
        for w in composition_result.warnings:
            all_warnings.append(w.message)

        # ── Stage 4: Blueprint compilation ───────────────────────────────────
        blueprint_registry = self._compile_blueprints(
            composition_result.composed_modes, effective_version
        )

        # ── Stage 5 + 6: System validation and registration ──────────────────
        system_registry = self._compile_systems(cgs, all_warnings)

        # ── Stage 7: Version manager ──────────────────────────────────────────
        version_manager = SchemaVersionManager.initialise(cgs)

        # ── Stage 8: Invariant checks ─────────────────────────────────────────
        invariant_report = self._run_invariant_check(cgs)
        if not invariant_report.is_valid:
            raise SchemaFactoryError(
                errors=invariant_report.all_errors(),
                stage="invariant_check",
            )

        # ── Stage 9: Assemble package ─────────────────────────────────────────
        return CompiledSchemaPackage(
            schema_version=effective_version,
            cgs_hash=cgs_hash,
            blueprint_registry=blueprint_registry,
            component_registry=self._component_registry,
            system_registry=system_registry,
            version_manager=version_manager,
            validation_report=validation_report,
            invariant_report=invariant_report,
            compilation_warnings=tuple(sorted(set(all_warnings))),
            default_mode_id=composition_result.default_mode_id,
            all_mode_ids=tuple(
                m.mode_id for m in composition_result.composed_modes
            ),
            game_name=game_name,
        )

    def compute_diff(
        self,
        old_cgs:      dict[str, Any],
        new_cgs:      dict[str, Any],
        from_version: str,
        from_hash:    str,
        to_version:   str,
        to_hash:      str,
    ) -> MigrationPlan:
        """
        Computes a MigrationPlan between two CGS versions.

        Used by SaveMigrationEngine (Phase 16) and by the builder version
        timeline when the designer wants to see what changed.

        Returns an empty MigrationPlan if the two CGS dicts are identical.
        """
        diff = SchemaDiffEngine.compute(
            old_cgs=old_cgs,
            new_cgs=new_cgs,
            from_version=from_version,
            from_hash=from_hash,
            to_version=to_version,
            to_hash=to_hash,
        )
        return MigrationRuleGenerator.generate(diff)

    # ── Internal pipeline stages ──────────────────────────────────────────────

    def _run_validation(self, cgs: dict[str, Any]) -> ValidationReport:
        contract = SchemaValidationContract(self._component_registry)
        return contract.validate(cgs)

    def _run_invariant_check(self, cgs: dict[str, Any]) -> InvariantReport:
        checker = InvariantChecker(self._component_registry)
        return checker.check(cgs)

    def _compile_blueprints(
        self,
        composed_modes: list[ComposedMode],
        schema_version: str,
    ) -> BlueprintRegistry:
        """
        Compiles all actors from all composed modes into a single BlueprintRegistry.
        Actors are keyed globally by ID — cross-mode duplicates were already
        caught by SchemaValidationContract (C1).
        """
        compiler = BlueprintCompiler(self._component_registry)
        registry = BlueprintRegistry()
        all_errors: list[str] = []

        for composed in composed_modes:
            try:
                mode_registry = compiler.compile_all(
                    composed.actors, schema_version=schema_version
                )
                for bp in mode_registry:
                    try:
                        registry.register(bp)
                    except Exception as exc:
                        all_errors.append(str(exc))
            except BlueprintCompilationError as exc:
                all_errors.extend(exc.errors)

        if all_errors:
            raise SchemaFactoryError(
                errors=all_errors,
                stage="blueprint_compilation",
            )

        return registry

    def _compile_systems(
        self,
        cgs:          dict[str, Any],
        warnings_out: list[str],
    ) -> SystemDefinitionRegistry:
        """
        Validates and registers all systems (global + per-mode) into a
        SystemDefinitionRegistry.

        Collects all errors before raising so the designer sees every
        system problem at once.
        """
        system_validator = SystemValidator(self._component_registry)
        registry         = SystemDefinitionRegistry()
        all_errors:  list[str] = []
        all_systems: list[SchemaSystemDefinition] = []

        # Collect global systems
        for sys_dict in cgs.get("global_systems", []):
            schema_sys = _dict_to_schema_system(sys_dict)
            if schema_sys is not None:
                all_systems.append(schema_sys)
            else:
                all_errors.append(
                    f"Could not parse global system: {sys_dict.get('id', '?')}"
                )

        # Collect per-mode systems (de-duplicated by ID — mode overrides global)
        seen_ids: set[str] = {s.id for s in all_systems}
        for mode in cgs.get("modes", []):
            for sys_dict in mode.get("systems", []):
                sys_id = sys_dict.get("id", "")
                if sys_id and sys_id not in seen_ids:
                    schema_sys = _dict_to_schema_system(sys_dict)
                    if schema_sys is not None:
                        all_systems.append(schema_sys)
                        seen_ids.add(sys_id)
                    else:
                        all_errors.append(
                            f"Could not parse system '{sys_id}' "
                            f"in mode '{mode.get('id', '?')}'."
                        )
                elif sys_id in seen_ids:
                    # Mode override — already captured from global or earlier mode
                    warnings_out.append(
                        f"System '{sys_id}' in mode '{mode.get('id', '?')}' "
                        f"is a duplicate/override — using first declaration."
                    )

        # Per-system validation
        results = system_validator.validate_all(all_systems)
        for result in results:
            all_errors.extend(result.errors)
            warnings_out.extend(result.warnings)

        if all_errors:
            raise SchemaFactoryError(
                errors=all_errors,
                stage="system_validation",
            )

        # Register all valid systems atomically (I8)
        try:
            registry.register_all(all_systems)
        except Exception as exc:
            raise SchemaFactoryError(
                errors=[str(exc)],
                stage="system_validation",
            ) from exc

        # Cross-system dependency check
        dep_errors = registry.validate_dependency_references()
        if dep_errors:
            raise SchemaFactoryError(
                errors=dep_errors,
                stage="system_validation",
            )

        return registry


# ── CGS Dict → SchemaSystemDefinition ────────────────────────────────────────

def _dict_to_schema_system(d: dict) -> SchemaSystemDefinition | None:
    """
    Converts a raw CGS system dict to a SchemaSystemDefinition.
    Returns None if required fields are missing.
    """
    sys_id = d.get("id", "")
    phase  = d.get("phase", "Simulation")
    if not sys_id:
        return None

    version_dict    = d.get("version", {})
    version_major   = version_dict.get("major", 1) if isinstance(version_dict, dict) else 1
    version_minor   = version_dict.get("minor", 0) if isinstance(version_dict, dict) else 0

    return SchemaSystemDefinition(
        id=sys_id,
        display_name=d.get("display_name", sys_id),
        phase=phase if phase in VALID_PHASES else "Simulation",
        reads=tuple(sorted(int(x) for x in d.get("reads", []))),
        writes=tuple(sorted(int(x) for x in d.get("writes", []))),
        depends_on=tuple(sorted(d.get("depends_on", []))),
        deterministic=bool(d.get("deterministic", True)),
        version_major=int(version_major),
        version_minor=int(version_minor),
        description=d.get("description", ""),
    )