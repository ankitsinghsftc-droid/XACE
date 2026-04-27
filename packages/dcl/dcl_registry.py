"""
dcl_registry.py — CompositeComponentRegistry

The single component registry that assembles all three component layers
into one queryable registry at game load time:

    Layer 1: UCL Core    — 10 frozen components, always present
    Layer 2: DCL domains — XACE-owned domain packages, declared in game_config.yaml
    Layer 3: GCL         — per-game developer components, loaded from game project

This registry is the source of truth for all component type validation
throughout the Python pipeline (Schema Factory, GDE, PIL).

Per Audit 1 — the three-layer architecture is locked. UCL Core is frozen.
DCL is versioned and XACE-owned. GCL is developer-owned and validated by XACE.

Global Invariant I11: GCL components must never enter DCL or UCL namespaces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set
import logging

logger = logging.getLogger(__name__)


# ── Component Layer ────────────────────────────────────────────────────────────

class ComponentLayer(Enum):
    """
    Which layer of the three-layer component architecture a component
    definition belongs to.

    Layer assignment is permanent — a component can never move between layers.
    GCL components must never enter DCL or UCL namespaces (I11).
    """
    UCL_CORE = "ucl_core"
    DCL      = "dcl"
    GCL      = "gcl"


# ── Component Field Definition ─────────────────────────────────────────────────

@dataclass
class ComponentFieldDefinition:
    """
    Definition of a single field within a component schema.

    Used by the Schema Factory and GDE to validate mutation values
    against declared field types before allowing CGS commit.
    """
    field_name: str
    field_type: str          # "f32", "f64", "i32", "i64", "u32", "u64",
                             # "bool", "str", "list", "dict", "enum", "struct"
    is_required: bool = True
    default_value: Optional[str] = None   # JSON string or None
    description: str = ""

    def is_numeric(self) -> bool:
        """Returns True if this field holds a numeric value."""
        return self.field_type in {"f32", "f64", "i32", "i64", "u32", "u64"}

    def is_collection(self) -> bool:
        """Returns True if this field holds a collection value."""
        return self.field_type in {"list", "dict"}


# ── Component Definition ───────────────────────────────────────────────────────

@dataclass
class ComponentDefinition:
    """
    The complete schema definition for one component type.

    Stored in the CompositeComponentRegistry for every registered
    component type. Used by:
    - Schema Factory: validates actor component declarations
    - Mutation Gate: validates component type IDs before writes
    - GDE: validates DSL path component references
    - PIL: builds LLM context with component vocabulary
    """
    type_id: int                         # Unique numeric ID, frozen after assignment
    type_name: str                       # e.g. "COMP_TRANSFORM_V1"
    layer: ComponentLayer                # Which layer owns this component
    domain: str                          # e.g. "ucl", "combat", "rpg", "my_game"
    version: int                         # Schema version (1 = initial)
    fields: List[ComponentFieldDefinition] = field(default_factory=list)
    description: str = ""
    is_universal: bool = False           # True if every entity must have this

    def get_field(self, field_name: str) -> Optional[ComponentFieldDefinition]:
        """Returns the field definition by name, or None if not found."""
        for f in self.fields:
            if f.field_name == field_name:
                return f
        return None

    def has_field(self, field_name: str) -> bool:
        """Returns True if this component has a field with the given name."""
        return any(f.field_name == field_name for f in self.fields)

    def field_names(self) -> List[str]:
        """Returns all field names for this component."""
        return [f.field_name for f in self.fields]

    def required_fields(self) -> List[ComponentFieldDefinition]:
        """Returns only the required fields for this component."""
        return [f for f in self.fields if f.is_required]

    @property
    def fully_qualified_name(self) -> str:
        """Returns domain-prefixed name: e.g. 'combat.COMP_HEALTH_V1'"""
        return f"{self.domain}.{self.type_name}"


# ── UCL Core Stubs ─────────────────────────────────────────────────────────────

def _build_ucl_core_definitions() -> List[ComponentDefinition]:
    """
    Builds the 10 frozen UCL Core component definitions.

    These mirror the Rust UCL Core types in packages/core/src/ucl/.
    They are hardcoded here — never loaded from file — because
    UCL Core is frozen forever (Audit 1).

    Type IDs 1-10 are permanently reserved for UCL Core.
    DCL type IDs start at 100. GCL type IDs start at 10000.
    """
    return [
        ComponentDefinition(
            type_id=1,
            type_name="COMP_TRANSFORM_V1",
            layer=ComponentLayer.UCL_CORE,
            domain="ucl",
            version=1,
            description="Spatial position, rotation, scale, and parent hierarchy.",
            fields=[
                ComponentFieldDefinition("position", "struct", True, None,
                    "Vec3 world position"),
                ComponentFieldDefinition("rotation", "struct", True, None,
                    "Quaternion rotation (x,y,z,w)"),
                ComponentFieldDefinition("scale", "struct", True, None,
                    "Vec3 scale (1,1,1 = no scale)"),
                ComponentFieldDefinition("parent_entity_id", "u64", False, "0",
                    "Parent entity ID or 0 for world-space"),
            ]
        ),
        ComponentDefinition(
            type_id=2,
            type_name="COMP_IDENTITY_V1",
            layer=ComponentLayer.UCL_CORE,
            domain="ucl",
            version=1,
            description="Entity name, type, faction, tags, and prefab origin.",
            fields=[
                ComponentFieldDefinition("entity_name", "str", True, None,
                    "Human-readable entity name"),
                ComponentFieldDefinition("entity_type", "enum", True, None,
                    "EntityType enum value"),
                ComponentFieldDefinition("faction", "str", False, '""',
                    "Faction or team identifier"),
                ComponentFieldDefinition("tags", "list", False, "[]",
                    "Sorted string tag list"),
                ComponentFieldDefinition("prefab_id", "str", False, '""',
                    "Schema prefab this entity was spawned from"),
                ComponentFieldDefinition("is_runtime_spawned", "bool", False, "false",
                    "True if spawned during gameplay, not defined in CGS"),
            ]
        ),
        ComponentDefinition(
            type_id=3,
            type_name="COMP_RENDER_V1",
            layer=ComponentLayer.UCL_CORE,
            domain="ucl",
            version=1,
            description="Visual representation — mesh, sprite, or particle. Asset reference typed.",
            fields=[
                ComponentFieldDefinition("render_type", "enum", True, None,
                    "RenderType enum: Mesh3D|Sprite2D|ParticleEffect|Invisible|WorldSpaceUi"),
                ComponentFieldDefinition("asset_reference", "struct", True, None,
                    "Typed AssetReference — never a raw string (Audit 2)"),
                ComponentFieldDefinition("material_ref", "struct", False, "null",
                    "Optional material AssetReference override"),
                ComponentFieldDefinition("visible", "bool", False, "true",
                    "Whether entity is rendered"),
                ComponentFieldDefinition("cast_shadows", "bool", False, "true",
                    "Whether entity casts shadows (Mesh3D only)"),
                ComponentFieldDefinition("layer", "i32", False, "0",
                    "Render layer for draw order"),
                ComponentFieldDefinition("render_order", "i32", False, "0",
                    "Draw order within same layer"),
            ]
        ),
        ComponentDefinition(
            type_id=4,
            type_name="COMP_COLLIDER_V1",
            layer=ComponentLayer.UCL_CORE,
            domain="ucl",
            version=1,
            description="Physical collision boundary: shape, size, trigger vs solid, layer mask.",
            fields=[
                ComponentFieldDefinition("shape", "enum", True, None,
                    "ColliderShape: Box|Sphere|Capsule|ConvexHull|Mesh"),
                ComponentFieldDefinition("size", "struct", True, None,
                    "ColliderSize — interpretation depends on shape"),
                ComponentFieldDefinition("offset", "struct", False, None,
                    "ColliderOffset from entity transform origin"),
                ComponentFieldDefinition("is_trigger", "bool", False, "false",
                    "True = overlap detection only, no physics forces"),
                ComponentFieldDefinition("layer_mask", "u32", False, "1",
                    "Bitmask of collision layers this collider interacts with"),
                ComponentFieldDefinition("physics_material", "struct", False, None,
                    "Friction and bounciness properties"),
            ]
        ),
        ComponentDefinition(
            type_id=5,
            type_name="COMP_VELOCITY_V1",
            layer=ComponentLayer.UCL_CORE,
            domain="ucl",
            version=1,
            description="Linear and angular velocity with configurable speed limits.",
            fields=[
                ComponentFieldDefinition("linear", "struct", False, None,
                    "VelocityVec3 linear velocity (units per second)"),
                ComponentFieldDefinition("angular", "struct", False, None,
                    "VelocityVec3 angular velocity (radians per second)"),
                ComponentFieldDefinition("max_linear_speed", "f32", False, "0.0",
                    "Max linear speed — 0.0 means no limit"),
                ComponentFieldDefinition("max_angular_speed", "f32", False, "0.0",
                    "Max angular speed — 0.0 means no limit"),
            ]
        ),
        ComponentDefinition(
            type_id=6,
            type_name="COMP_INPUT_V1",
            layer=ComponentLayer.UCL_CORE,
            domain="ucl",
            version=1,
            description="Control source routing: Human, AI proxy, or network remote.",
            fields=[
                ComponentFieldDefinition("controller_id", "u32", True, None,
                    "Physical or logical controller ID"),
                ComponentFieldDefinition("control_type", "enum", True, None,
                    "ControlType: Human|AiProxy|NetworkRemote"),
                ComponentFieldDefinition("input_profile_id", "str", False, '"default"',
                    "Input mapping profile ID"),
                ComponentFieldDefinition("is_enabled", "bool", False, "true",
                    "Whether input is currently active"),
            ]
        ),
        ComponentDefinition(
            type_id=7,
            type_name="COMP_EVENT_V1",
            layer=ComponentLayer.UCL_CORE,
            domain="ucl",
            version=1,
            description="In-world event carrier. Events never modify state directly (I9).",
            fields=[
                ComponentFieldDefinition("event_id", "u64", False, "0",
                    "Assigned by EventBus — never set manually"),
                ComponentFieldDefinition("creation_tick", "u64", True, None,
                    "Tick this event was created"),
                ComponentFieldDefinition("creation_phase", "u8", True, None,
                    "Phase discriminant during which event was emitted"),
                ComponentFieldDefinition("event_type", "struct", True, None,
                    "EventType enum value"),
                ComponentFieldDefinition("source_entity_id", "u64", True, None,
                    "Entity that emitted this event — never NULL_ENTITY_ID"),
                ComponentFieldDefinition("target_entity_id", "u64", False, "0",
                    "Target entity — 0 for broadcast events"),
                ComponentFieldDefinition("payload", "dict", False, "{}",
                    "BTreeMap<String, String> event data"),
                ComponentFieldDefinition("is_consumed", "bool", False, "false",
                    "True when processed by receiving system"),
            ]
        ),
        ComponentDefinition(
            type_id=8,
            type_name="COMP_LIFETIME_V1",
            layer=ComponentLayer.UCL_CORE,
            domain="ucl",
            version=1,
            description="Automatic expiry timer in ticks. Destroy, disable, loop, or emit on expire.",
            fields=[
                ComponentFieldDefinition("max_lifetime_ticks", "u64", True, None,
                    "Ticks before expiry — must be > 0"),
                ComponentFieldDefinition("current_lifetime_ticks", "u64", False, "0",
                    "Ticks elapsed since creation"),
                ComponentFieldDefinition("on_expire_action", "enum", False, '"Destroy"',
                    "OnExpireAction: Destroy|Disable|EmitEvent|Loop"),
                ComponentFieldDefinition("is_paused", "bool", False, "false",
                    "If true, lifetime counter is frozen"),
            ]
        ),
        ComponentDefinition(
            type_id=9,
            type_name="COMP_GAMESTATE_V1",
            layer=ComponentLayer.UCL_CORE,
            domain="ucl",
            version=1,
            description="Global game session state: phase, score, elapsed ticks, match state.",
            fields=[
                ComponentFieldDefinition("current_phase", "enum", False, '"Initializing"',
                    "GamePhase enum value"),
                ComponentFieldDefinition("score", "i64", False, "0",
                    "Current session score — signed for penalties"),
                ComponentFieldDefinition("time_elapsed_ticks", "u64", False, "0",
                    "Ticks elapsed in active gameplay"),
                ComponentFieldDefinition("active_mode_id", "str", False, '""',
                    "ID of the currently active CGS GameMode"),
                ComponentFieldDefinition("match_state", "enum", False, '"Idle"',
                    "MatchState: Idle|Countdown|Active|RoundEnd|MatchEnd|Overtime"),
            ]
        ),
        ComponentDefinition(
            type_id=10,
            type_name="COMP_AUTHORITY_V1",
            layer=ComponentLayer.UCL_CORE,
            domain="ucl",
            version=1,
            description="Network authority type, replication mode, prediction, and sync rate.",
            fields=[
                ComponentFieldDefinition("authority_type", "enum", False, '"Local"',
                    "AuthorityType: Local|Server|ClientOwned|Shared"),
                ComponentFieldDefinition("owner_peer_id", "u32", False, "0",
                    "Peer ID of owning client — 0 for local/server"),
                ComponentFieldDefinition("replication_mode", "enum", False, '"Unreliable"',
                    "ReplicationMode: Unreliable|Reliable|ServerOnly"),
                ComponentFieldDefinition("prediction_enabled", "bool", False, "false",
                    "True for ClientOwned entities on owning client"),
                ComponentFieldDefinition("reconciliation_mode", "enum", False, '"Interpolate"',
                    "ReconciliationMode: Snap|Interpolate"),
                ComponentFieldDefinition("sync_rate_divisor", "u8", False, "1",
                    "Replicate every Nth tick — 1 means every tick"),
                ComponentFieldDefinition("is_replicated", "bool", False, "false",
                    "True if this entity's state is sent to peers"),
            ]
        ),
    ]


# ── CompositeComponentRegistry ─────────────────────────────────────────────────

class CompositeComponentRegistry:
    """
    The assembled registry of all component types across all three layers.

    Assembled once at game load from:
    - UCL Core (10 frozen components — always present)
    - DCL domain packages (declared in game_config.yaml)
    - GCL components (loaded from game project gcl/ folder)

    Used by Schema Factory, GDE, and PIL for all component validation.
    Never modified after assembly — treat as read-only after build().

    ## Type ID Ranges (reserved and frozen)
    1-10    : UCL Core (COMP_TRANSFORM_V1 through COMP_AUTHORITY_V1)
    100-9999: DCL domain components
    10000+  : GCL developer components

    ## Name Uniqueness
    All type_names must be unique across all three layers (I11).
    GCL names must not collide with UCL or DCL names.
    """

    # Type ID range boundaries
    UCL_CORE_ID_MIN: int = 1
    UCL_CORE_ID_MAX: int = 10
    DCL_ID_MIN: int = 100
    DCL_ID_MAX: int = 9999
    GCL_ID_MIN: int = 10000

    def __init__(self) -> None:
        # Primary storage: type_id → ComponentDefinition
        self._by_id: Dict[int, ComponentDefinition] = {}
        # Secondary index: type_name → ComponentDefinition
        self._by_name: Dict[str, ComponentDefinition] = {}
        # Loaded domain names
        self._loaded_domains: Set[str] = set()
        # Whether the registry has been finalized
        self._finalized: bool = False

    # ── Build Phase ────────────────────────────────────────────────────────────

    def register(self, definition: ComponentDefinition) -> None:
        """
        Registers one component definition into the registry.

        Raises ValueError on:
        - Type ID already registered
        - Type name already registered (I11)
        - Type ID out of range for declared layer
        - Registry already finalized
        """
        if self._finalized:
            raise RuntimeError(
                "CompositeComponentRegistry is finalized — "
                "no registrations allowed after build() completes"
            )

        # Validate ID uniqueness
        if definition.type_id in self._by_id:
            existing = self._by_id[definition.type_id]
            raise ValueError(
                f"Component type_id {definition.type_id} already registered "
                f"as '{existing.type_name}' — cannot register '{definition.type_name}'"
            )

        # Validate name uniqueness (I11)
        if definition.type_name in self._by_name:
            existing = self._by_name[definition.type_name]
            raise ValueError(
                f"Component type_name '{definition.type_name}' already registered "
                f"in {existing.layer.value} layer — name collision forbidden (I11)"
            )

        # Validate type ID is in the correct range for its layer
        self._validate_id_range(definition)

        self._by_id[definition.type_id] = definition
        self._by_name[definition.type_name] = definition
        self._loaded_domains.add(definition.domain)

        logger.debug(
            "Registered %s [type_id=%d, layer=%s, domain=%s]",
            definition.type_name,
            definition.type_id,
            definition.layer.value,
            definition.domain,
        )

    def _validate_id_range(self, definition: ComponentDefinition) -> None:
        """Validates the type_id is within the correct range for its layer."""
        type_id = definition.type_id
        layer = definition.layer

        if layer == ComponentLayer.UCL_CORE:
            if not (self.UCL_CORE_ID_MIN <= type_id <= self.UCL_CORE_ID_MAX):
                raise ValueError(
                    f"UCL Core component '{definition.type_name}' has type_id "
                    f"{type_id} outside reserved UCL range "
                    f"[{self.UCL_CORE_ID_MIN}-{self.UCL_CORE_ID_MAX}]"
                )
        elif layer == ComponentLayer.DCL:
            if not (self.DCL_ID_MIN <= type_id <= self.DCL_ID_MAX):
                raise ValueError(
                    f"DCL component '{definition.type_name}' has type_id "
                    f"{type_id} outside DCL range "
                    f"[{self.DCL_ID_MIN}-{self.DCL_ID_MAX}]"
                )
        elif layer == ComponentLayer.GCL:
            if type_id < self.GCL_ID_MIN:
                raise ValueError(
                    f"GCL component '{definition.type_name}' has type_id "
                    f"{type_id} below GCL minimum {self.GCL_ID_MIN}"
                )

    def finalize(self) -> None:
        """
        Finalizes the registry — no further registrations allowed.

        Called after all UCL, DCL, and GCL components are registered.
        Validates the complete registry for consistency.
        """
        self._validate_registry()
        self._finalized = True
        logger.info(
            "CompositeComponentRegistry finalized: %d components "
            "(%d UCL, %d DCL, %d GCL) across %d domains",
            self.total_count(),
            self.count_by_layer(ComponentLayer.UCL_CORE),
            self.count_by_layer(ComponentLayer.DCL),
            self.count_by_layer(ComponentLayer.GCL),
            len(self._loaded_domains),
        )

    def _validate_registry(self) -> None:
        """
        Validates the complete registry for internal consistency.

        Checks:
        - Exactly 10 UCL Core components
        - All UCL Core type IDs 1-10 are present
        - No name collisions between layers (I11)
        - All definitions are structurally valid
        """
        # Must have exactly 10 UCL Core components
        ucl_count = self.count_by_layer(ComponentLayer.UCL_CORE)
        if ucl_count != 10:
            raise ValueError(
                f"Registry must have exactly 10 UCL Core components — "
                f"found {ucl_count}"
            )

        # All UCL Core IDs 1-10 must be present
        for type_id in range(1, 11):
            if type_id not in self._by_id:
                raise ValueError(
                    f"UCL Core type_id {type_id} is missing from registry"
                )

        # All definitions must have non-empty type names
        for definition in self._by_id.values():
            if not definition.type_name:
                raise ValueError(
                    f"Component type_id {definition.type_id} has empty type_name"
                )

    # ── Query API ──────────────────────────────────────────────────────────────

    def get_by_id(self, type_id: int) -> Optional[ComponentDefinition]:
        """Returns the component definition for the given type ID."""
        return self._by_id.get(type_id)

    def get_by_name(self, type_name: str) -> Optional[ComponentDefinition]:
        """Returns the component definition for the given type name."""
        return self._by_name.get(type_name)

    def contains_id(self, type_id: int) -> bool:
        """Returns True if the given type ID is registered."""
        return type_id in self._by_id

    def contains_name(self, type_name: str) -> bool:
        """Returns True if the given type name is registered."""
        return type_name in self._by_name

    def all_definitions(self) -> List[ComponentDefinition]:
        """
        Returns all component definitions sorted by type_id ascending.
        Sorted for deterministic processing (D11).
        """
        return sorted(self._by_id.values(), key=lambda d: d.type_id)

    def definitions_for_layer(
        self, layer: ComponentLayer
    ) -> List[ComponentDefinition]:
        """
        Returns all component definitions for the given layer,
        sorted by type_id ascending (D11).
        """
        return sorted(
            [d for d in self._by_id.values() if d.layer == layer],
            key=lambda d: d.type_id,
        )

    def definitions_for_domain(self, domain: str) -> List[ComponentDefinition]:
        """
        Returns all component definitions for the given domain,
        sorted by type_id ascending (D11).
        """
        return sorted(
            [d for d in self._by_id.values() if d.domain == domain],
            key=lambda d: d.type_id,
        )

    def ucl_core_definitions(self) -> List[ComponentDefinition]:
        """Returns the 10 UCL Core component definitions sorted by type_id."""
        return self.definitions_for_layer(ComponentLayer.UCL_CORE)

    def dcl_definitions(self) -> List[ComponentDefinition]:
        """Returns all DCL component definitions sorted by type_id."""
        return self.definitions_for_layer(ComponentLayer.DCL)

    def gcl_definitions(self) -> List[ComponentDefinition]:
        """Returns all GCL component definitions sorted by type_id."""
        return self.definitions_for_layer(ComponentLayer.GCL)

    def all_type_ids(self) -> List[int]:
        """Returns all registered type IDs sorted ascending (D11)."""
        return sorted(self._by_id.keys())

    def all_type_names(self) -> List[str]:
        """Returns all registered type names sorted ascending (D11)."""
        return sorted(self._by_name.keys())

    def total_count(self) -> int:
        """Returns the total number of registered components."""
        return len(self._by_id)

    def count_by_layer(self, layer: ComponentLayer) -> int:
        """Returns the count of components in the given layer."""
        return sum(1 for d in self._by_id.values() if d.layer == layer)

    def loaded_domains(self) -> List[str]:
        """Returns the names of all loaded domains sorted ascending."""
        return sorted(self._loaded_domains)

    def is_finalized(self) -> bool:
        """Returns True if this registry has been finalized."""
        return self._finalized

    def validate_component_reference(
        self, type_id: int
    ) -> tuple[bool, Optional[str]]:
        """
        Validates that a component type_id is registered.

        Returns (True, None) if valid.
        Returns (False, error_message) if invalid.

        Used by Schema Factory and GDE for pre-commit validation.
        """
        if not self.contains_id(type_id):
            return False, (
                f"Component type_id {type_id} is not registered in "
                f"CompositeComponentRegistry — unknown component type"
            )
        return True, None

    def validate_field_reference(
        self, type_id: int, field_name: str
    ) -> tuple[bool, Optional[str]]:
        """
        Validates that a component field reference is valid.

        Returns (True, None) if both the component and field exist.
        Returns (False, error_message) if either is not found.

        Used by GDE path resolver and PIL schema path validator.
        """
        definition = self.get_by_id(type_id)
        if definition is None:
            return False, (
                f"Component type_id {type_id} not registered"
            )
        if not definition.has_field(field_name):
            return False, (
                f"Field '{field_name}' not found in component "
                f"'{definition.type_name}' — valid fields: "
                f"{definition.field_names()}"
            )
        return True, None

    def __repr__(self) -> str:
        return (
            f"CompositeComponentRegistry("
            f"total={self.total_count()}, "
            f"ucl={self.count_by_layer(ComponentLayer.UCL_CORE)}, "
            f"dcl={self.count_by_layer(ComponentLayer.DCL)}, "
            f"gcl={self.count_by_layer(ComponentLayer.GCL)}, "
            f"finalized={self._finalized})"
        )


# ── Factory Function ───────────────────────────────────────────────────────────

def build_ucl_only_registry() -> CompositeComponentRegistry:
    """
    Builds a registry containing only the UCL Core 10 components.

    Used for testing and for contexts where only core component
    validation is needed (e.g. early-phase Schema Factory tests).

    The returned registry is finalized — no further registrations allowed.
    """
    registry = CompositeComponentRegistry()
    for definition in _build_ucl_core_definitions():
        registry.register(definition)
    registry.finalize()
    return registry


# ── Tests ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    print("Running CompositeComponentRegistry self-tests...")
    errors: List[str] = []

    # Test 1: UCL-only registry has 10 components
    registry = build_ucl_only_registry()
    assert registry.total_count() == 10, \
        f"Expected 10 UCL components, got {registry.total_count()}"
    assert registry.is_finalized(), "Registry should be finalized after build"
    print("  PASS: UCL-only registry has exactly 10 components")

    # Test 2: All 10 UCL type IDs present
    for type_id in range(1, 11):
        assert registry.contains_id(type_id), \
            f"Missing UCL Core type_id {type_id}"
    print("  PASS: All UCL Core type IDs 1-10 present")

    # Test 3: Type name lookup works
    transform = registry.get_by_name("COMP_TRANSFORM_V1")
    assert transform is not None, "COMP_TRANSFORM_V1 not found by name"
    assert transform.type_id == 1, f"Expected type_id=1, got {transform.type_id}"
    print("  PASS: Type name lookup works")

    # Test 4: Type ID lookup works
    authority = registry.get_by_id(10)
    assert authority is not None, "type_id=10 not found"
    assert authority.type_name == "COMP_AUTHORITY_V1", \
        f"Expected COMP_AUTHORITY_V1, got {authority.type_name}"
    print("  PASS: Type ID lookup works")

    # Test 5: All definitions sorted ascending
    ids = registry.all_type_ids()
    assert ids == sorted(ids), "Type IDs not sorted ascending"
    print("  PASS: Type IDs are sorted ascending")

    # Test 6: Layer filtering
    ucl_defs = registry.ucl_core_definitions()
    assert len(ucl_defs) == 10, f"Expected 10 UCL defs, got {len(ucl_defs)}"
    assert len(registry.dcl_definitions()) == 0, \
        "UCL-only registry should have no DCL definitions"
    print("  PASS: Layer filtering works")

    # Test 7: Field validation
    valid, err = registry.validate_field_reference(1, "position")
    assert valid, f"position should be valid on COMP_TRANSFORM_V1: {err}"
    valid, err = registry.validate_field_reference(1, "nonexistent_field")
    assert not valid, "nonexistent_field should not be valid"
    print("  PASS: Field validation works")

    # Test 8: Duplicate registration raises error
    try:
        registry2 = CompositeComponentRegistry()
        defs = _build_ucl_core_definitions()
        for d in defs:
            registry2.register(d)
        # Try registering COMP_TRANSFORM_V1 again
        registry2.register(defs[0])
        errors.append("Should have raised ValueError for duplicate type_id")
    except ValueError:
        print("  PASS: Duplicate type_id raises ValueError")

    # Test 9: Finalized registry rejects new registrations
    try:
        registry.register(ComponentDefinition(
            type_id=100,
            type_name="COMP_TEST",
            layer=ComponentLayer.DCL,
            domain="test",
            version=1,
        ))
        errors.append("Should have raised RuntimeError after finalization")
    except RuntimeError:
        print("  PASS: Finalized registry rejects new registrations")

    # Test 10: Component reference validation
    valid, err = registry.validate_component_reference(1)
    assert valid, "type_id=1 should be valid"
    valid, err = registry.validate_component_reference(9999)
    assert not valid, "type_id=9999 should not be valid"
    print("  PASS: Component reference validation works")

    # Test 11: all_definitions returns sorted list
    all_defs = registry.all_definitions()
    assert all_defs[0].type_id == 1, "First definition should be type_id=1"
    assert all_defs[-1].type_id == 10, "Last definition should be type_id=10"
    print("  PASS: all_definitions returns sorted list")

    if errors:
        print(f"\nFAILED: {len(errors)} errors:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print(f"\nAll tests passed. Registry: {registry}")