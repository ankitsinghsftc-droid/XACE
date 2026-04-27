"""
dcl_loader.py — DCL Domain Loader

Loads DCL domain packages declared in game_config.yaml and registers
their components into the CompositeComponentRegistry.

## Loading Flow
1. Read game_config.yaml to find declared domain names
2. Import each domain's Python module from packages/dcl/{domain}/
3. Call the domain module's get_domain_package() factory function
4. Resolve dependency ordering via DomainRegistry
5. Register all component definitions into CompositeComponentRegistry

## game_config.yaml Format
```yaml
game_id: "my-game-uuid"
game_name: "My Game"
dcl_domains:
  - combat
  - character
  - rpg
gcl_path: "gcl/"
```

## Domain Module Contract
Every DCL domain module must export one function:

    def get_domain_package() -> DomainPackage:
        ...

The loader calls this function to get the domain's package.
If the function is missing, loading fails with a clear error.

## Error Handling
The loader never silently ignores errors. Any missing domain,
invalid component, or dependency failure raises DclLoadError
with a full description of what went wrong.
"""

from __future__ import annotations

import importlib
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .dcl_registry import (
    CompositeComponentRegistry,
    ComponentDefinition,
    ComponentLayer,
    _build_ucl_core_definitions,
)
from .domain_package import DomainPackage, DomainRegistry

logger = logging.getLogger(__name__)


# ── DCL Load Error ─────────────────────────────────────────────────────────────

class DclLoadError(Exception):
    """
    Raised when DCL loading fails for any reason.

    Always includes a human-readable description of what went wrong
    and which domain or file caused the failure.
    """
    pass


# ── Game Config ────────────────────────────────────────────────────────────────

@dataclass
class GameConfig:
    """
    Parsed contents of game_config.yaml.

    Defines which DCL domains this game uses and where the GCL
    components live. Loaded by DclLoader before domain registration.
    """
    game_id: str
    game_name: str
    dcl_domains: List[str] = field(default_factory=list)
    gcl_path: str = "gcl/"
    xace_version: str = "0.1.0"

    def validate(self) -> List[str]:
        """
        Validates the game config for basic correctness.

        Returns a list of error strings. Empty means valid.
        """
        errors: List[str] = []

        if not self.game_id:
            errors.append("game_id must not be empty")

        if not self.game_name:
            errors.append("game_name must not be empty")

        # Check for duplicate domain declarations
        seen: Dict[str, int] = {}
        for i, domain in enumerate(self.dcl_domains):
            if not domain:
                errors.append(f"dcl_domains[{i}] is empty")
            elif domain in seen:
                errors.append(
                    f"Duplicate domain declaration: '{domain}' "
                    f"appears at index {seen[domain]} and {i}"
                )
            else:
                seen[domain] = i

        return errors


# ── Load Result ────────────────────────────────────────────────────────────────

@dataclass
class DclLoadResult:
    """
    The result of a successful DCL load operation.

    Contains the finalized CompositeComponentRegistry and metadata
    about what was loaded. Passed to the Schema Factory and GDE
    as the authoritative component registry for this game session.
    """
    registry: CompositeComponentRegistry
    game_config: GameConfig
    loaded_domains: List[str]         # domain names in load order
    load_warnings: List[str]          # non-fatal warnings during load

    @property
    def domain_count(self) -> int:
        """Number of DCL domains loaded."""
        return len(self.loaded_domains)

    @property
    def total_component_count(self) -> int:
        """Total components in the registry (UCL + DCL + GCL)."""
        return self.registry.total_count()

    def __repr__(self) -> str:
        return (
            f"DclLoadResult("
            f"game='{self.game_config.game_name}', "
            f"domains={self.loaded_domains}, "
            f"total_components={self.total_component_count}, "
            f"warnings={len(self.load_warnings)})"
        )


# ── DCL Loader ─────────────────────────────────────────────────────────────────

class DclLoader:
    """
    Loads DCL domain packages and assembles the CompositeComponentRegistry.

    The DclLoader is the entry point for all component registration.
    It reads game_config.yaml, loads declared domains, resolves
    dependencies, and produces a finalized CompositeComponentRegistry.

    ## Usage
```python
    loader = DclLoader(dcl_package_root="packages/dcl")
    result = loader.load_from_config(game_config)
    registry = result.registry  # ready to use
```

    ## DCL Package Root
    dcl_package_root is the filesystem path to the packages/dcl/ directory.
    Each domain lives at: {dcl_package_root}/{domain_name}/
    Each domain exports get_domain_package() from its __init__.py.
    """

    def __init__(self, dcl_package_root: str = "packages/dcl") -> None:
        """
        Creates a DclLoader.

        Args:
            dcl_package_root: Path to the packages/dcl directory.
                              Used to locate domain Python modules.
        """
        self.dcl_package_root = dcl_package_root
        self._domain_registry = DomainRegistry()
        self._warnings: List[str] = []

    # ── Public API ─────────────────────────────────────────────────────────────

    def load_from_config(self, game_config: GameConfig) -> DclLoadResult:
        """
        Loads all DCL domains declared in the game config and assembles
        the CompositeComponentRegistry.

        This is the primary entry point for DCL loading.

        Steps:
        1. Validate game_config
        2. Build registry with UCL Core (always)
        3. Load and register each declared DCL domain
        4. GCL loading is handled separately by GclLoader
        5. Finalize and return the registry

        Raises:
            DclLoadError: if any domain fails to load or validate
        """
        self._warnings = []

        # Step 1: Validate config
        config_errors = game_config.validate()
        if config_errors:
            raise DclLoadError(
                f"game_config validation failed:\n"
                + "\n".join(f"  - {e}" for e in config_errors)
            )

        logger.info(
            "Loading DCL for game '%s' — domains: %s",
            game_config.game_name,
            game_config.dcl_domains,
        )

        # Step 2: Build registry starting with UCL Core
        registry = CompositeComponentRegistry()
        self._register_ucl_core(registry)

        # Step 3: Load each declared domain
        loaded_domains: List[str] = []
        if game_config.dcl_domains:
            loaded_domains = self._load_domains(
                game_config.dcl_domains, registry
            )

        # Step 4: Finalize registry (GCL added separately by GclLoader)
        # Note: we don't finalize here — GclLoader needs to add GCL first.
        # The caller finalizes after GCL loading is complete.
        # For UCL-only or DCL-only use, caller calls registry.finalize().

        logger.info(
            "DCL load complete: %d domains, %d total components (UCL+DCL), "
            "%d warnings",
            len(loaded_domains),
            registry.total_count(),
            len(self._warnings),
        )

        return DclLoadResult(
            registry=registry,
            game_config=game_config,
            loaded_domains=loaded_domains,
            load_warnings=list(self._warnings),
        )

    def load_from_yaml(self, config_path: str) -> DclLoadResult:
        """
        Loads DCL from a game_config.yaml file path.

        Parses the YAML file and delegates to load_from_config().
        Requires PyYAML: pip install pyyaml

        Raises:
            DclLoadError: if the file cannot be read or parsed
        """
        try:
            import yaml  # type: ignore
        except ImportError:
            raise DclLoadError(
                "PyYAML is required for YAML config loading. "
                "Install it with: pip install pyyaml"
            )

        if not os.path.exists(config_path):
            raise DclLoadError(
                f"game_config.yaml not found at: {config_path}"
            )

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
        except Exception as e:
            raise DclLoadError(
                f"Failed to parse game_config.yaml at '{config_path}': {e}"
            )

        if not isinstance(raw, dict):
            raise DclLoadError(
                f"game_config.yaml must be a YAML mapping, got {type(raw).__name__}"
            )

        game_config = GameConfig(
            game_id=raw.get("game_id", ""),
            game_name=raw.get("game_name", ""),
            dcl_domains=raw.get("dcl_domains", []),
            gcl_path=raw.get("gcl_path", "gcl/"),
            xace_version=raw.get("xace_version", "0.1.0"),
        )

        return self.load_from_config(game_config)

    # ── UCL Core Registration ──────────────────────────────────────────────────

    def _register_ucl_core(
        self, registry: CompositeComponentRegistry
    ) -> None:
        """
        Registers the 10 frozen UCL Core components into the registry.

        UCL Core is always loaded — no game can opt out of these.
        Called before any DCL or GCL registration.
        """
        logger.debug("Registering UCL Core (10 frozen components)")
        for definition in _build_ucl_core_definitions():
            registry.register(definition)
        logger.debug("UCL Core registration complete")

    # ── Domain Loading ─────────────────────────────────────────────────────────

    def _load_domains(
        self,
        requested_domains: List[str],
        registry: CompositeComponentRegistry,
    ) -> List[str]:
        """
        Loads all requested domains and their dependencies.

        Returns the list of domain names in load order.
        Raises DclLoadError on any failure.
        """
        # First, load all domain packages into the domain registry
        # so dependency resolution can see all of them
        self._preload_domain_packages(requested_domains)

        # Resolve load order including transitive dependencies
        try:
            load_order = self._domain_registry.resolve_load_order(
                requested_domains
            )
        except ValueError as e:
            raise DclLoadError(f"Domain dependency resolution failed: {e}")

        logger.debug("Resolved domain load order: %s", load_order)

        # Register each domain's components in resolved order
        for domain_name in load_order:
            package = self._domain_registry.get_domain(domain_name)
            if package is None:
                raise DclLoadError(
                    f"Domain '{domain_name}' was in load order but "
                    f"not found in domain registry — this is a bug"
                )
            self._register_domain(package, registry)

        return load_order

    def _preload_domain_packages(self, domain_names: List[str]) -> None:
        """
        Imports and validates all domain packages before registration.

        Preloading ensures all packages are valid before any registration
        begins — so we don't end up with a partially-registered registry
        if a later domain fails.
        """
        # Collect all domains including potential dependencies
        all_domains: List[str] = list(domain_names)

        # Load each requested domain
        for domain_name in all_domains:
            if self._domain_registry.has_domain(domain_name):
                continue  # Already preloaded (e.g. as a dependency)

            package = self._import_domain_package(domain_name)

            # Also preload dependencies
            for dep in package.dependencies:
                if not self._domain_registry.has_domain(dep):
                    dep_package = self._import_domain_package(dep)
                    self._domain_registry.register_domain(dep_package)

            self._domain_registry.register_domain(package)

    def _import_domain_package(self, domain_name: str) -> DomainPackage:
        """
        Imports a domain module and calls its get_domain_package() factory.

        The domain module must be importable as:
            packages.dcl.{domain_name}

        And must export:
            def get_domain_package() -> DomainPackage

        Raises DclLoadError if the module cannot be imported or
        does not export get_domain_package.
        """
        module_path = f"packages.dcl.{domain_name}"

        try:
            module = importlib.import_module(module_path)
        except ModuleNotFoundError:
            # Try alternative path without package prefix
            try:
                module = importlib.import_module(f"dcl.{domain_name}")
            except ModuleNotFoundError:
                raise DclLoadError(
                    f"DCL domain '{domain_name}' module not found. "
                    f"Expected module at: {module_path} or dcl.{domain_name}\n"
                    f"Make sure packages/dcl/{domain_name}/__init__.py exists "
                    f"and exports get_domain_package()"
                )
        except Exception as e:
            raise DclLoadError(
                f"Failed to import DCL domain '{domain_name}': {e}"
            )

        # Get the factory function
        factory = getattr(module, "get_domain_package", None)
        if factory is None:
            raise DclLoadError(
                f"DCL domain module '{module_path}' does not export "
                f"get_domain_package() — every domain module must define this function"
            )

        if not callable(factory):
            raise DclLoadError(
                f"DCL domain '{module_path}'.get_domain_package is not callable"
            )

        # Call the factory
        try:
            package = factory()
        except Exception as e:
            raise DclLoadError(
                f"DCL domain '{domain_name}'.get_domain_package() raised "
                f"an exception: {e}"
            )

        if not isinstance(package, DomainPackage):
            raise DclLoadError(
                f"DCL domain '{domain_name}'.get_domain_package() returned "
                f"{type(package).__name__} instead of DomainPackage"
            )

        logger.debug(
            "Imported domain package '%s' v%d (%d components)",
            package.domain_name,
            package.domain_version,
            package.component_count,
        )

        return package

    def _register_domain(
        self,
        package: DomainPackage,
        registry: CompositeComponentRegistry,
    ) -> None:
        """
        Registers all components from a domain package into the registry.

        Components are registered in type_id ascending order (D11).
        Any registration failure raises DclLoadError immediately.
        """
        logger.debug(
            "Registering domain '%s' (%d components)",
            package.domain_name,
            package.component_count,
        )

        for component in package.sorted_components():
            try:
                registry.register(component)
            except ValueError as e:
                raise DclLoadError(
                    f"Failed to register component '{component.type_name}' "
                    f"from domain '{package.domain_name}': {e}"
                )

        logger.info(
            "Domain '%s' registered: %d components (type_ids %d-%d)",
            package.domain_name,
            package.component_count,
            package.id_block_start,
            package.id_block_start + package.component_count - 1,
        )

    # ── Utilities ──────────────────────────────────────────────────────────────

    def warnings(self) -> List[str]:
        """Returns all warnings generated during the last load operation."""
        return list(self._warnings)

    def _warn(self, message: str) -> None:
        """Records a non-fatal warning."""
        logger.warning(message)
        self._warnings.append(message)


# ── Convenience Functions ──────────────────────────────────────────────────────

def load_dcl_for_game(
    game_id: str,
    game_name: str,
    dcl_domains: List[str],
    dcl_package_root: str = "packages/dcl",
) -> DclLoadResult:
    """
    Convenience function for loading DCL with a minimal config.

    Creates a GameConfig from the given parameters and delegates
    to DclLoader.load_from_config().

    Usage:
        result = load_dcl_for_game(
            game_id="my-uuid",
            game_name="My Game",
            dcl_domains=["combat", "character", "ai"],
        )
        registry = result.registry
    """
    config = GameConfig(
        game_id=game_id,
        game_name=game_name,
        dcl_domains=dcl_domains,
    )
    loader = DclLoader(dcl_package_root=dcl_package_root)
    return loader.load_from_config(config)


def load_ucl_only(game_id: str, game_name: str) -> DclLoadResult:
    """
    Loads only the UCL Core 10 components with no DCL domains.

    Useful for testing, early-phase development, and contexts
    where only core component validation is needed.

    The returned registry is NOT finalized — caller must call
    registry.finalize() before use, after adding any GCL components.
    """
    config = GameConfig(
        game_id=game_id,
        game_name=game_name,
        dcl_domains=[],
    )
    loader = DclLoader()
    return loader.load_from_config(config)


# ── Tests ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    print("Running DclLoader self-tests...")
    errors_found: List[str] = []

    # Test 1: GameConfig validation — valid config
    config = GameConfig(
        game_id="test-uuid-001",
        game_name="Test Game",
        dcl_domains=["combat", "ai"],
    )
    config_errors = config.validate()
    assert not config_errors, f"Valid config should have no errors: {config_errors}"
    print("  PASS: Valid GameConfig validates correctly")

    # Test 2: GameConfig validation — empty game_id
    bad_config = GameConfig(
        game_id="",
        game_name="Test Game",
        dcl_domains=[],
    )
    bad_errors = bad_config.validate()
    assert any("game_id" in e for e in bad_errors), \
        "Should report empty game_id"
    print("  PASS: Empty game_id fails validation")

    # Test 3: GameConfig validation — duplicate domains
    dup_config = GameConfig(
        game_id="test-uuid",
        game_name="Test",
        dcl_domains=["combat", "ai", "combat"],
    )
    dup_errors = dup_config.validate()
    assert any("Duplicate" in e for e in dup_errors), \
        "Should report duplicate domain"
    print("  PASS: Duplicate domain declaration fails validation")

    # Test 4: UCL-only load succeeds
    result = load_ucl_only("test-uuid-002", "Test Game")
    assert result.registry.total_count() == 10, \
        f"UCL-only should have 10 components, got {result.registry.total_count()}"
    assert result.domain_count == 0, \
        "UCL-only should have no DCL domains"
    assert result.registry.contains_name("COMP_TRANSFORM_V1"), \
        "UCL-only registry should contain COMP_TRANSFORM_V1"
    print("  PASS: UCL-only load produces 10 UCL components")

    # Test 5: UCL-only load has no warnings
    assert not result.load_warnings, \
        f"UCL-only load should have no warnings: {result.load_warnings}"
    print("  PASS: UCL-only load has no warnings")

    # Test 6: UCL Core components are in correct layer
    for type_id in range(1, 11):
        defn = result.registry.get_by_id(type_id)
        assert defn is not None, f"UCL type_id {type_id} missing"
        assert defn.layer == ComponentLayer.UCL_CORE, \
            f"type_id {type_id} should be UCL_CORE layer"
    print("  PASS: All UCL Core components have correct layer")

    # Test 7: DclLoadResult repr works
    repr_str = repr(result)
    assert "Test Game" in repr_str, "repr should include game name"
    print("  PASS: DclLoadResult repr works")

    # Test 8: load_from_config with empty domains list
    empty_domains_config = GameConfig(
        game_id="test-uuid-003",
        game_name="Minimal Game",
        dcl_domains=[],
    )
    loader = DclLoader()
    empty_result = loader.load_from_config(empty_domains_config)
    assert empty_result.registry.total_count() == 10, \
        "Empty domains should still have 10 UCL components"
    assert empty_result.loaded_domains == [], \
        "No domains loaded"
    print("  PASS: Empty domain list loads only UCL Core")

    # Test 9: DclLoadError raised for invalid game_id
    try:
        bad_loader = DclLoader()
        bad_loader.load_from_config(GameConfig(
            game_id="",
            game_name="Bad",
            dcl_domains=[],
        ))
        errors_found.append("Should have raised DclLoadError for empty game_id")
    except DclLoadError:
        print("  PASS: Invalid config raises DclLoadError")

    # Test 10: GameConfig with valid domains list
    full_config = GameConfig(
        game_id="test-uuid-004",
        game_name="Full Game",
        dcl_domains=["combat", "character", "rpg"],
        gcl_path="my_game/gcl/",
    )
    assert full_config.dcl_domains == ["combat", "character", "rpg"]
    assert full_config.gcl_path == "my_game/gcl/"
    print("  PASS: GameConfig stores domain list and gcl_path correctly")

    if errors_found:
        print(f"\nFAILED: {len(errors_found)} errors:")
        for e in errors_found:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print(f"\nAll tests passed.")