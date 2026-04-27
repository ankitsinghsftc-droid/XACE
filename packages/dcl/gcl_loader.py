"""
gcl_loader.py — Game Component Library Loader

Loads developer-defined GCL components from the game project's gcl/
folder and registers them into the CompositeComponentRegistry after
UCL Core and DCL domain components are registered.

## GCL Folder Structure
A game project's GCL lives in a folder declared in game_config.yaml:

    my_game/
    └── gcl/
        ├── __init__.py
        └── components.py   ← exports get_gcl_components()

## GCL Module Contract
The GCL module must export one function:

    def get_gcl_components() -> List[ComponentDefinition]:
        ...

The loader calls this, runs all components through GclValidator,
and registers the valid ones into the CompositeComponentRegistry.

## When GCL Loading Happens
GCL loading happens AFTER DCL loading and BEFORE registry finalization:
1. DclLoader loads UCL Core + DCL domains
2. GclLoader loads GCL components
3. Caller calls registry.finalize()

This ordering ensures GCL validation can check for collisions with
both UCL and DCL names (I11).
"""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import List, Optional

from .dcl_registry import (
    ComponentDefinition,
    ComponentLayer,
    CompositeComponentRegistry,
)
from .gcl_validator import GclValidator, GclValidationResult

logger = logging.getLogger(__name__)


# ── GCL Load Error ─────────────────────────────────────────────────────────────

class GclLoadError(Exception):
    """
    Raised when GCL loading fails for any reason.

    Always includes a human-readable description of what went wrong.
    """
    pass


# ── GCL Load Result ────────────────────────────────────────────────────────────

@dataclass
class GclLoadResult:
    """
    The result of a GCL load operation.

    Contains the count of components loaded and any validation
    warnings that were non-fatal during loading.
    """
    components_loaded: int
    components_rejected: int
    validation_warnings: List[str] = field(default_factory=list)
    rejected_component_names: List[str] = field(default_factory=list)

    @property
    def any_rejected(self) -> bool:
        return self.components_rejected > 0

    def __repr__(self) -> str:
        return (
            f"GclLoadResult("
            f"loaded={self.components_loaded}, "
            f"rejected={self.components_rejected}, "
            f"warnings={len(self.validation_warnings)})"
        )


# ── GCL Loader ─────────────────────────────────────────────────────────────────

class GclLoader:
    """
    Loads GCL components from the game project folder.

    GCL components are developer-defined components that extend the
    component vocabulary for a specific game. They live outside XACE
    in the game project folder and are loaded at game startup.

    ## Strict vs Lenient Mode
    strict=True (default): Any invalid GCL component raises GclLoadError.
    strict=False: Invalid components are skipped with warnings logged.

    Use strict=True for production. Use strict=False for development
    when you want the game to load even with some broken GCL components.
    """

    def __init__(self, strict: bool = True) -> None:
        """
        Creates a GclLoader.

        Args:
            strict: If True, any GCL validation error raises GclLoadError.
                    If False, invalid components are skipped with warnings.
        """
        self.strict = strict
        self._validator = GclValidator()

    def load_from_path(
        self,
        gcl_path: str,
        registry: CompositeComponentRegistry,
    ) -> GclLoadResult:
        """
        Loads GCL components from the given folder path.

        The folder must contain a Python module that exports
        get_gcl_components() returning List[ComponentDefinition].

        Looks for the GCL module in this order:
        1. {gcl_path}/__init__.py (if it exports get_gcl_components)
        2. {gcl_path}/components.py

        Args:
            gcl_path: Path to the game project's gcl/ folder.
            registry: The CompositeComponentRegistry to register into.
                      Must not be finalized yet.

        Returns:
            GclLoadResult with counts and any warnings.

        Raises:
            GclLoadError: If strict=True and any component is invalid,
                          or if the GCL module cannot be found/loaded.
        """
        if registry.is_finalized():
            raise GclLoadError(
                "Cannot load GCL into a finalized registry. "
                "GCL loading must happen before registry.finalize() is called."
            )

        if not gcl_path:
            logger.info("No GCL path specified — skipping GCL loading")
            return GclLoadResult(
                components_loaded=0,
                components_rejected=0,
            )

        if not os.path.exists(gcl_path):
            if self.strict:
                raise GclLoadError(
                    f"GCL path does not exist: '{gcl_path}'. "
                    f"Create the folder and add a components.py file."
                )
            else:
                logger.warning(
                    "GCL path '%s' does not exist — skipping GCL loading",
                    gcl_path,
                )
                return GclLoadResult(
                    components_loaded=0,
                    components_rejected=0,
                    validation_warnings=[
                        f"GCL path '{gcl_path}' does not exist"
                    ],
                )

        # Import the GCL module
        definitions = self._import_gcl_components(gcl_path)

        if not definitions:
            logger.info("GCL module at '%s' returned no components", gcl_path)
            return GclLoadResult(
                components_loaded=0,
                components_rejected=0,
            )

        # Validate the batch
        return self._validate_and_register(definitions, registry, gcl_path)

    def load_from_definitions(
        self,
        definitions: List[ComponentDefinition],
        registry: CompositeComponentRegistry,
    ) -> GclLoadResult:
        """
        Loads GCL components directly from a list of ComponentDefinitions.

        Used for testing and for programmatic GCL registration without
        a file system. Skips file loading and goes straight to validation.

        Args:
            definitions: List of GCL ComponentDefinition instances.
            registry: The registry to register into (not finalized).

        Returns:
            GclLoadResult with counts and any warnings.
        """
        if registry.is_finalized():
            raise GclLoadError(
                "Cannot load GCL into a finalized registry."
            )

        if not definitions:
            return GclLoadResult(
                components_loaded=0,
                components_rejected=0,
            )

        return self._validate_and_register(
            definitions, registry, source="direct"
        )

    # ── Private Methods ────────────────────────────────────────────────────────

    def _import_gcl_components(
        self, gcl_path: str
    ) -> List[ComponentDefinition]:
        """
        Imports the GCL module and calls get_gcl_components().

        Tries __init__.py first, then components.py.
        Raises GclLoadError if neither can be found or loaded.
        """
        # Candidates in order of preference
        candidates = [
            os.path.join(gcl_path, "__init__.py"),
            os.path.join(gcl_path, "components.py"),
        ]

        module = None
        loaded_from: Optional[str] = None

        for candidate in candidates:
            if os.path.exists(candidate):
                module = self._load_module_from_file(candidate)
                loaded_from = candidate
                break

        if module is None:
            msg = (
                f"No GCL module found in '{gcl_path}'. "
                f"Expected one of: {candidates}. "
                f"Create components.py that exports get_gcl_components()."
            )
            if self.strict:
                raise GclLoadError(msg)
            else:
                logger.warning(msg)
                return []

        # Get the factory function
        factory = getattr(module, "get_gcl_components", None)
        if factory is None:
            msg = (
                f"GCL module '{loaded_from}' does not export "
                f"get_gcl_components(). Add this function returning "
                f"List[ComponentDefinition]."
            )
            if self.strict:
                raise GclLoadError(msg)
            else:
                logger.warning(msg)
                return []

        # Call the factory
        try:
            definitions = factory()
        except Exception as e:
            raise GclLoadError(
                f"GCL module '{loaded_from}'.get_gcl_components() raised "
                f"an exception: {e}"
            )

        if not isinstance(definitions, list):
            raise GclLoadError(
                f"GCL module '{loaded_from}'.get_gcl_components() returned "
                f"{type(definitions).__name__} instead of list"
            )

        logger.debug(
            "GCL module '%s' returned %d component definitions",
            loaded_from,
            len(definitions),
        )

        return definitions

    def _load_module_from_file(self, file_path: str):
        """
        Dynamically loads a Python module from a file path.

        Uses importlib.util for clean module loading without
        polluting sys.path unnecessarily.
        """
        module_name = f"_gcl_{os.path.basename(os.path.dirname(file_path))}"
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            raise GclLoadError(
                f"Cannot create module spec for '{file_path}'"
            )
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            raise GclLoadError(
                f"Failed to execute GCL module '{file_path}': {e}"
            )
        return module

    def _validate_and_register(
        self,
        definitions: List[ComponentDefinition],
        registry: CompositeComponentRegistry,
        source: str = "unknown",
    ) -> GclLoadResult:
        """
        Validates and registers a list of GCL component definitions.

        In strict mode: raises GclLoadError if any component is invalid.
        In lenient mode: skips invalid components, logs warnings.
        """
        # Run batch validation first
        batch_result = self._validator.validate_batch(definitions, registry)

        if not batch_result.is_valid and self.strict:
            raise GclLoadError(
                f"GCL component validation failed for source '{source}':\n"
                + "\n".join(f"  ERROR: {e}" for e in batch_result.errors)
                + (
                    "\n" + "\n".join(
                        f"  WARNING: {w}" for w in batch_result.warnings
                    ) if batch_result.warnings else ""
                )
            )

        # Log warnings regardless of mode
        for warning in batch_result.warnings:
            logger.warning("GCL warning: %s", warning)

        # Register valid components
        loaded_count = 0
        rejected_count = 0
        rejected_names: List[str] = []
        all_warnings = list(batch_result.warnings)

        for definition in sorted(definitions, key=lambda d: d.type_id):
            # Validate individually to get per-component errors
            individual_result = self._validator.validate_component(
                definition, registry
            )

            if not individual_result.is_valid:
                if self.strict:
                    # Already raised above — this shouldn't be reached
                    raise GclLoadError(
                        f"GCL component '{definition.type_name}' is invalid: "
                        + "; ".join(individual_result.errors)
                    )
                else:
                    # Lenient mode: skip this component
                    logger.warning(
                        "Skipping invalid GCL component '%s': %s",
                        definition.type_name,
                        "; ".join(individual_result.errors),
                    )
                    rejected_count += 1
                    rejected_names.append(definition.type_name)
                    all_warnings.extend(individual_result.errors)
                    continue

            # Register the valid component
            try:
                registry.register(definition)
                loaded_count += 1
                logger.debug(
                    "Registered GCL component '%s' [type_id=%d]",
                    definition.type_name,
                    definition.type_id,
                )
            except ValueError as e:
                if self.strict:
                    raise GclLoadError(
                        f"Failed to register GCL component "
                        f"'{definition.type_name}': {e}"
                    )
                else:
                    logger.warning(
                        "Failed to register GCL component '%s': %s",
                        definition.type_name, e,
                    )
                    rejected_count += 1
                    rejected_names.append(definition.type_name)

        logger.info(
            "GCL load complete: %d loaded, %d rejected, %d warnings",
            loaded_count,
            rejected_count,
            len(all_warnings),
        )

        return GclLoadResult(
            components_loaded=loaded_count,
            components_rejected=rejected_count,
            validation_warnings=all_warnings,
            rejected_component_names=rejected_names,
        )


# ── Tests ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from .dcl_registry import (
        build_ucl_only_registry,
        ComponentFieldDefinition,
    )

    print("Running GclLoader self-tests...")
    errors_found: List[str] = []

    def make_gcl(
        type_id: int = 10001,
        type_name: str = "COMP_MY_CUSTOM_V1",
        domain: str = "my_game",
    ) -> ComponentDefinition:
        return ComponentDefinition(
            type_id=type_id,
            type_name=type_name,
            layer=ComponentLayer.GCL,
            domain=domain,
            version=1,
            fields=[ComponentFieldDefinition("value", "f32", True)],
        )

    # Test 1: Load valid GCL component directly
    registry = build_ucl_only_registry()
    # UCL-only is finalized — need a fresh one for GCL
    from .dcl_registry import CompositeComponentRegistry, _build_ucl_core_definitions
    fresh_registry = CompositeComponentRegistry()
    for d in _build_ucl_core_definitions():
        fresh_registry.register(d)

    loader = GclLoader(strict=True)
    result = loader.load_from_definitions(
        [make_gcl(10001, "COMP_MY_CUSTOM_V1")],
        fresh_registry,
    )
    assert result.components_loaded == 1, \
        f"Expected 1 loaded, got {result.components_loaded}"
    assert result.components_rejected == 0
    assert fresh_registry.contains_name("COMP_MY_CUSTOM_V1")
    print("  PASS: Valid GCL component loads correctly")

    # Test 2: Strict mode rejects invalid component
    fresh2 = CompositeComponentRegistry()
    for d in _build_ucl_core_definitions():
        fresh2.register(d)

    loader_strict = GclLoader(strict=True)
    try:
        loader_strict.load_from_definitions(
            [make_gcl(type_id=500)],  # Below GCL minimum
            fresh2,
        )
        errors_found.append("Should have raised GclLoadError for invalid type_id")
    except GclLoadError:
        print("  PASS: Strict mode raises GclLoadError for invalid component")

    # Test 3: Lenient mode skips invalid component
    fresh3 = CompositeComponentRegistry()
    for d in _build_ucl_core_definitions():
        fresh3.register(d)

    loader_lenient = GclLoader(strict=False)
    result_lenient = loader_lenient.load_from_definitions(
        [
            make_gcl(type_id=500, type_name="COMP_BAD_V1"),  # Invalid
            make_gcl(type_id=10002, type_name="COMP_GOOD_V1"),  # Valid
        ],
        fresh3,
    )
    assert result_lenient.components_loaded == 1, \
        f"Lenient should load 1 valid, got {result_lenient.components_loaded}"
    assert result_lenient.components_rejected == 1
    assert "COMP_BAD_V1" in result_lenient.rejected_component_names
    print("  PASS: Lenient mode skips invalid and loads valid components")

    # Test 4: Finalized registry raises GclLoadError
    try:
        loader.load_from_definitions(
            [make_gcl()],
            registry,  # Already finalized
        )
        errors_found.append("Should have raised GclLoadError for finalized registry")
    except GclLoadError:
        print("  PASS: Finalized registry raises GclLoadError")

    # Test 5: Empty definitions list returns zero counts
    fresh4 = CompositeComponentRegistry()
    for d in _build_ucl_core_definitions():
        fresh4.register(d)

    result_empty = loader.load_from_definitions([], fresh4)
    assert result_empty.components_loaded == 0
    assert result_empty.components_rejected == 0
    print("  PASS: Empty definitions list returns zero counts")

    # Test 6: Components loaded in type_id ascending order
    fresh5 = CompositeComponentRegistry()
    for d in _build_ucl_core_definitions():
        fresh5.register(d)

    result_order = loader.load_from_definitions(
        [
            make_gcl(type_id=10005, type_name="COMP_LAST_V1"),
            make_gcl(type_id=10001, type_name="COMP_FIRST_V1"),
            make_gcl(type_id=10003, type_name="COMP_MIDDLE_V1"),
        ],
        fresh5,
    )
    assert result_order.components_loaded == 3
    all_ids = fresh5.all_type_ids()
    gcl_ids = [i for i in all_ids if i >= 10000]
    assert gcl_ids == sorted(gcl_ids), "GCL IDs should be sorted"
    print("  PASS: Components registered in type_id ascending order")

    # Test 7: GclLoadResult repr works
    repr_str = repr(result)
    assert "loaded=1" in repr_str
    print("  PASS: GclLoadResult repr works")

    # Test 8: Non-existent path in lenient mode returns warning
    fresh6 = CompositeComponentRegistry()
    for d in _build_ucl_core_definitions():
        fresh6.register(d)

    lenient_loader = GclLoader(strict=False)
    path_result = lenient_loader.load_from_path(
        "/nonexistent/path/gcl",
        fresh6,
    )
    assert path_result.components_loaded == 0
    assert len(path_result.validation_warnings) > 0
    print("  PASS: Non-existent path in lenient mode returns warning")

    if errors_found:
        print(f"\nFAILED: {len(errors_found)} errors:")
        for e in errors_found:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print(f"\nAll tests passed.")