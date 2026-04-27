"""
domain_package.py — DCL Domain Package Definition

A DomainPackage is the metadata and component loader for one DCL domain.
Each domain (combat, character, physics, ai, etc.) is a self-contained
package that games opt into via game_config.yaml.

The DclLoader reads game_config.yaml, finds the declared domains,
loads each DomainPackage, and registers its components into the
CompositeComponentRegistry.

## Domain Package Responsibilities
- Declare domain identity (name, version, description)
- Provide all ComponentDefinition instances for this domain
- Declare dependencies on other domains (e.g. character depends on physics)
- Validate internal consistency before registration

## Type ID Assignment for DCL Domains
Each domain has a reserved type ID block within the DCL range (100-9999).
This prevents collisions when multiple domains are loaded together.

combat/      : 100-119
character/   : 120-139
physics/     : 140-159
ai/          : 160-179
stealth/     : 180-199
rpg/         : 200-229
world/       : 230-259
interaction/ : 260-279
camera/      : 280-299
audio/       : 300-319
network/     : 320-339
ui/          : 340-359
persistence/ : 360-379
(reserved)   : 380-9999 for future domains and GCL
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import logging

from .dcl_registry import ComponentDefinition, ComponentLayer

logger = logging.getLogger(__name__)


# ── Domain ID Blocks ───────────────────────────────────────────────────────────

# Reserved type ID block for each DCL domain.
# Start ID is inclusive. Each domain gets 20 IDs by default.
# Treat these as frozen once any game ships with this DCL version.
DOMAIN_ID_BLOCKS: Dict[str, int] = {
    "combat":      100,
    "character":   120,
    "physics":     140,
    "ai":          160,
    "stealth":     180,
    "rpg":         200,
    "world":       230,
    "interaction": 260,
    "camera":      280,
    "audio":       300,
    "network":     320,
    "ui":          340,
    "persistence": 360,
}

DOMAIN_BLOCK_SIZE: int = 20  # IDs reserved per domain


def get_domain_id_start(domain_name: str) -> int:
    """
    Returns the starting type ID for the given domain.

    Raises ValueError if the domain name is not recognized.
    This prevents accidental type ID collisions between domains.
    """
    if domain_name not in DOMAIN_ID_BLOCKS:
        raise ValueError(
            f"Unknown DCL domain '{domain_name}' — not in DOMAIN_ID_BLOCKS. "
            f"Known domains: {sorted(DOMAIN_ID_BLOCKS.keys())}"
        )
    return DOMAIN_ID_BLOCKS[domain_name]


# ── Domain Package ─────────────────────────────────────────────────────────────

@dataclass
class DomainPackage:
    """
    Metadata and component definitions for one DCL domain package.

    A DomainPackage is the unit of DCL loading. Each domain is
    an independent, versioned package that can be declared in
    game_config.yaml. Games only pay the cost of domains they use.

    ## Versioning
    domain_version tracks the schema version of this domain's components.
    When fields are added or changed, domain_version increments.
    The Schema Factory uses domain_version for save migration (Audit 7).

    ## Dependencies
    Some domains depend on others. For example:
    - stealth depends on ai (needs COMP_PERCEPTION_V1)
    - character animation depends on physics (needs COMP_RIGIDBODY_V1)

    The DclLoader resolves and loads dependencies before the declaring domain.
    Circular dependencies are a loading error.
    """
    # Domain identity
    domain_name: str              # e.g. "combat", "rpg", "physics"
    display_name: str             # e.g. "Combat Domain", "RPG Domain"
    domain_version: int           # Incremented when component schemas change
    description: str              # What this domain provides

    # Component definitions provided by this domain
    components: List[ComponentDefinition] = field(default_factory=list)

    # Other domain names this domain requires to be loaded first
    dependencies: List[str] = field(default_factory=list)

    # Whether this domain has been validated and is ready to register
    _validated: bool = field(default=False, init=False, repr=False)

    @property
    def id_block_start(self) -> int:
        """Returns the starting type ID for this domain's component block."""
        return get_domain_id_start(self.domain_name)

    @property
    def id_block_end(self) -> int:
        """Returns the ending type ID (exclusive) for this domain."""
        return self.id_block_start + DOMAIN_BLOCK_SIZE

    @property
    def component_count(self) -> int:
        """Returns the number of components in this domain."""
        return len(self.components)

    def get_component(self, type_name: str) -> Optional[ComponentDefinition]:
        """Returns the component definition by type name, or None."""
        for comp in self.components:
            if comp.type_name == type_name:
                return comp
        return None

    def has_component(self, type_name: str) -> bool:
        """Returns True if this domain defines the given component type."""
        return any(c.type_name == type_name for c in self.components)

    def component_names(self) -> List[str]:
        """Returns all component type names in this domain, sorted."""
        return sorted(c.type_name for c in self.components)

    def validate(self) -> List[str]:
        """
        Validates this domain package for internal consistency.

        Returns a list of error strings. Empty list means valid.

        Checks:
        - domain_name is not empty and is a known domain
        - domain_version >= 1
        - All component type_ids are within this domain's reserved block
        - All component type_names are non-empty
        - All components have layer=DCL
        - No duplicate type_ids within this domain
        - No duplicate type_names within this domain
        - Component count does not exceed block size
        """
        errors: List[str] = []

        # Validate domain name
        if not self.domain_name:
            errors.append("domain_name must not be empty")
            return errors  # Cannot continue without valid domain name

        if self.domain_name not in DOMAIN_ID_BLOCKS:
            errors.append(
                f"domain_name '{self.domain_name}' is not a recognized DCL domain"
            )

        # Validate version
        if self.domain_version < 1:
            errors.append(
                f"domain_version must be >= 1, got {self.domain_version}"
            )

        # Validate component count
        if len(self.components) > DOMAIN_BLOCK_SIZE:
            errors.append(
                f"Domain '{self.domain_name}' has {len(self.components)} components "
                f"but block size is {DOMAIN_BLOCK_SIZE}"
            )

        # Validate each component
        seen_ids: Dict[int, str] = {}
        seen_names: Dict[str, int] = {}

        for comp in self.components:
            # Must have non-empty type name
            if not comp.type_name:
                errors.append(
                    f"Component with type_id={comp.type_id} has empty type_name"
                )
                continue

            # Must be DCL layer
            if comp.layer != ComponentLayer.DCL:
                errors.append(
                    f"Component '{comp.type_name}' in domain '{self.domain_name}' "
                    f"has layer={comp.layer.value} — DCL domain components "
                    f"must have layer=DCL"
                )

            # Must be in this domain's ID block
            block_start = self.id_block_start
            block_end = self.id_block_end
            if not (block_start <= comp.type_id < block_end):
                errors.append(
                    f"Component '{comp.type_name}' has type_id={comp.type_id} "
                    f"outside domain '{self.domain_name}' reserved block "
                    f"[{block_start}-{block_end})"
                )

            # Duplicate type_id check
            if comp.type_id in seen_ids:
                errors.append(
                    f"Duplicate type_id {comp.type_id} in domain "
                    f"'{self.domain_name}': "
                    f"'{seen_ids[comp.type_id]}' and '{comp.type_name}'"
                )
            else:
                seen_ids[comp.type_id] = comp.type_name

            # Duplicate type_name check
            if comp.type_name in seen_names:
                errors.append(
                    f"Duplicate type_name '{comp.type_name}' in domain "
                    f"'{self.domain_name}': "
                    f"type_ids {seen_names[comp.type_name]} and {comp.type_id}"
                )
            else:
                seen_names[comp.type_name] = comp.type_id

        if not errors:
            self._validated = True

        return errors

    def is_valid(self) -> bool:
        """Returns True if this domain has been validated with no errors."""
        return self._validated

    def sorted_components(self) -> List[ComponentDefinition]:
        """Returns components sorted by type_id ascending (D11)."""
        return sorted(self.components, key=lambda c: c.type_id)

    def __repr__(self) -> str:
        return (
            f"DomainPackage("
            f"domain='{self.domain_name}', "
            f"version={self.domain_version}, "
            f"components={self.component_count}, "
            f"valid={self._validated})"
        )


# ── Domain Registry ────────────────────────────────────────────────────────────

class DomainRegistry:
    """
    Registry of all known DCL domain packages.

    Maintains the catalog of available domains and resolves
    dependency ordering before loading into CompositeComponentRegistry.

    The DclLoader populates this from game_config.yaml declarations.
    """

    def __init__(self) -> None:
        self._domains: Dict[str, DomainPackage] = {}

    def register_domain(self, package: DomainPackage) -> None:
        """
        Registers a domain package.

        Validates the package before registration.
        Raises ValueError if validation fails or domain already registered.
        """
        if package.domain_name in self._domains:
            raise ValueError(
                f"Domain '{package.domain_name}' is already registered"
            )

        errors = package.validate()
        if errors:
            raise ValueError(
                f"DomainPackage '{package.domain_name}' failed validation:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

        self._domains[package.domain_name] = package
        logger.debug(
            "Registered domain '%s' v%d with %d components",
            package.domain_name,
            package.domain_version,
            package.component_count,
        )

    def get_domain(self, domain_name: str) -> Optional[DomainPackage]:
        """Returns the domain package for the given name, or None."""
        return self._domains.get(domain_name)

    def has_domain(self, domain_name: str) -> bool:
        """Returns True if the domain is registered."""
        return domain_name in self._domains

    def all_domains(self) -> List[DomainPackage]:
        """Returns all registered domains sorted by name (D11)."""
        return sorted(self._domains.values(), key=lambda d: d.domain_name)

    def resolve_load_order(
        self, requested_domains: List[str]
    ) -> List[str]:
        """
        Resolves the correct load order for the requested domains,
        including any dependencies.

        Uses topological sort to ensure dependencies are loaded
        before the domains that require them.

        Returns ordered list of domain names to load.
        Raises ValueError if a dependency is missing or circular.
        """
        # Collect all required domains including transitive dependencies
        required: Dict[str, bool] = {}
        self._collect_dependencies(requested_domains, required)

        # Topological sort
        ordered: List[str] = []
        visited: Dict[str, str] = {}  # name -> "visiting" | "done"

        def visit(name: str) -> None:
            if name in visited:
                if visited[name] == "visiting":
                    raise ValueError(
                        f"Circular dependency detected involving domain '{name}'"
                    )
                return  # already done

            visited[name] = "visiting"
            package = self._domains.get(name)
            if package is None:
                raise ValueError(
                    f"Domain '{name}' is required but not registered. "
                    f"Available: {sorted(self._domains.keys())}"
                )

            for dep in package.dependencies:
                visit(dep)

            visited[name] = "done"
            ordered.append(name)

        for domain_name in sorted(required.keys()):  # sorted for determinism
            visit(domain_name)

        return ordered

    def _collect_dependencies(
        self,
        domain_names: List[str],
        collected: Dict[str, bool],
    ) -> None:
        """Recursively collects all required domains including dependencies."""
        for name in domain_names:
            if name in collected:
                continue
            collected[name] = True
            package = self._domains.get(name)
            if package and package.dependencies:
                self._collect_dependencies(package.dependencies, collected)

    def total_component_count(self) -> int:
        """Returns total number of components across all registered domains."""
        return sum(d.component_count for d in self._domains.values())

    def __repr__(self) -> str:
        return (
            f"DomainRegistry("
            f"domains={sorted(self._domains.keys())}, "
            f"total_components={self.total_component_count()})"
        )


# ── Tests ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from .dcl_registry import ComponentFieldDefinition

    print("Running DomainPackage self-tests...")
    errors_found: List[str] = []

    # Test 1: Domain ID block lookup
    assert get_domain_id_start("combat") == 100, "combat should start at 100"
    assert get_domain_id_start("character") == 120, "character should start at 120"
    assert get_domain_id_start("rpg") == 200, "rpg should start at 200"
    print("  PASS: Domain ID block lookup correct")

    # Test 2: Unknown domain raises ValueError
    try:
        get_domain_id_start("unknown_domain")
        errors_found.append("Should have raised ValueError for unknown domain")
    except ValueError:
        print("  PASS: Unknown domain raises ValueError")

    # Test 3: Valid domain package validates correctly
    combat_package = DomainPackage(
        domain_name="combat",
        display_name="Combat Domain",
        domain_version=1,
        description="Health, damage, hitbox, shield, status effects",
        components=[
            ComponentDefinition(
                type_id=100,
                type_name="COMP_HEALTH_V1",
                layer=ComponentLayer.DCL,
                domain="combat",
                version=1,
                description="Entity health tracking",
                fields=[
                    ComponentFieldDefinition("current", "f32", True),
                    ComponentFieldDefinition("max", "f32", True),
                ]
            ),
        ]
    )
    validation_errors = combat_package.validate()
    assert not validation_errors, f"Valid package should have no errors: {validation_errors}"
    assert combat_package.is_valid(), "Package should be valid after validation"
    print("  PASS: Valid domain package validates correctly")

    # Test 4: Component outside ID block fails validation
    bad_package = DomainPackage(
        domain_name="combat",
        display_name="Combat Domain",
        domain_version=1,
        description="Test",
        components=[
            ComponentDefinition(
                type_id=999,  # Outside combat block (100-119)
                type_name="COMP_BAD_V1",
                layer=ComponentLayer.DCL,
                domain="combat",
                version=1,
            ),
        ]
    )
    bad_errors = bad_package.validate()
    assert any("outside domain" in e for e in bad_errors), \
        "Should report ID outside block"
    print("  PASS: Component outside ID block fails validation")

    # Test 5: Wrong layer fails validation
    wrong_layer_package = DomainPackage(
        domain_name="combat",
        display_name="Combat Domain",
        domain_version=1,
        description="Test",
        components=[
            ComponentDefinition(
                type_id=100,
                type_name="COMP_TEST_V1",
                layer=ComponentLayer.UCL_CORE,  # Wrong layer
                domain="combat",
                version=1,
            ),
        ]
    )
    layer_errors = wrong_layer_package.validate()
    assert any("layer=ucl_core" in e for e in layer_errors), \
        "Should report wrong layer"
    print("  PASS: Wrong layer fails validation")

    # Test 6: DomainRegistry resolves load order
    registry = DomainRegistry()
    stealth_package = DomainPackage(
        domain_name="stealth",
        display_name="Stealth Domain",
        domain_version=1,
        description="Stealth components",
        components=[],
        dependencies=["ai"],
    )
    ai_package = DomainPackage(
        domain_name="ai",
        display_name="AI Domain",
        domain_version=1,
        description="AI components",
        components=[],
    )

    # Register without components to test ordering
    ai_package._validated = True
    stealth_package._validated = True
    registry._domains["ai"] = ai_package
    registry._domains["stealth"] = stealth_package

    order = registry.resolve_load_order(["stealth"])
    assert order.index("ai") < order.index("stealth"), \
        "ai must load before stealth"
    print("  PASS: Dependency resolution loads ai before stealth")

    # Test 7: Circular dependency raises ValueError
    circular_a = DomainPackage(
        domain_name="combat",
        display_name="Combat",
        domain_version=1,
        description="Test",
        components=[],
        dependencies=["rpg"],
    )
    circular_b = DomainPackage(
        domain_name="rpg",
        display_name="RPG",
        domain_version=1,
        description="Test",
        components=[],
        dependencies=["combat"],
    )
    circular_registry = DomainRegistry()
    circular_registry._domains["combat"] = circular_a
    circular_registry._domains["rpg"] = circular_b
    try:
        circular_registry.resolve_load_order(["combat"])
        errors_found.append("Should have raised ValueError for circular dependency")
    except ValueError:
        print("  PASS: Circular dependency raises ValueError")

    # Test 8: sorted_components returns ascending order
    multi_comp_package = DomainPackage(
        domain_name="combat",
        display_name="Combat",
        domain_version=1,
        description="Test",
        components=[
            ComponentDefinition(102, "COMP_HITBOX_V1", ComponentLayer.DCL, "combat", 1),
            ComponentDefinition(100, "COMP_HEALTH_V1", ComponentLayer.DCL, "combat", 1),
            ComponentDefinition(101, "COMP_DAMAGE_V1", ComponentLayer.DCL, "combat", 1),
        ]
    )
    sorted_comps = multi_comp_package.sorted_components()
    assert sorted_comps[0].type_id == 100
    assert sorted_comps[1].type_id == 101
    assert sorted_comps[2].type_id == 102
    print("  PASS: sorted_components returns ascending order")

    if errors_found:
        print(f"\nFAILED: {len(errors_found)} errors:")
        for e in errors_found:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print(f"\nAll tests passed.")