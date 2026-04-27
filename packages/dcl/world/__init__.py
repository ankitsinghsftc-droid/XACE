"""
DCL World Domain — packages/dcl/world/__init__.py

Provides world and environment components:
- COMP_SPAWNER_V1        (type_id=230)
- COMP_TRIGGERZONE_V1    (type_id=231)
- COMP_PERSISTENCE_V1    (type_id=232)
- COMP_WORLDSTREAMING_V1 (type_id=233)
- COMP_ENVIRONMENT_V1    (type_id=234)
- COMP_DESTRUCTIBLE_V1   (type_id=235)

Type ID block: 230-259 (world reserved range)
"""

from __future__ import annotations
from ..dcl_registry import (
    ComponentDefinition,
    ComponentFieldDefinition,
    ComponentLayer,
)
from ..domain_package import DomainPackage


def get_domain_package() -> DomainPackage:
    return DomainPackage(
        domain_name="world",
        display_name="World Domain",
        domain_version=1,
        description="World systems — spawners, triggers, persistence, streaming, environment, destructibles.",
        dependencies=[],
        components=[
            ComponentDefinition(
                type_id=230,
                type_name="COMP_SPAWNER_V1",
                layer=ComponentLayer.DCL,
                domain="world",
                version=1,
                description="Entity spawner — creates entities at a defined rate up to a maximum count.",
                fields=[
                    ComponentFieldDefinition(
                        "blueprint_id", "str", True, None,
                        "Actor definition ID to spawn."
                    ),
                    ComponentFieldDefinition(
                        "spawn_rate_ticks", "u64", False, "60",
                        "Ticks between each spawn attempt."
                    ),
                    ComponentFieldDefinition(
                        "max_count", "u32", False, "10",
                        "Maximum number of spawned entities alive at once."
                    ),
                    ComponentFieldDefinition(
                        "current_count", "u32", False, "0",
                        "Current number of alive spawned entities."
                    ),
                    ComponentFieldDefinition(
                        "spawn_radius", "f32", False, "3.0",
                        "Radius around spawner in which entities are placed."
                    ),
                    ComponentFieldDefinition(
                        "is_active", "bool", False, "true",
                        "Whether spawner is currently spawning."
                    ),
                    ComponentFieldDefinition(
                        "ticks_since_last_spawn", "u64", False, "0",
                        "Tick counter since last spawn."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=231,
                type_name="COMP_TRIGGERZONE_V1",
                layer=ComponentLayer.DCL,
                domain="world",
                version=1,
                description="A trigger volume that detects entity overlap and emits events.",
                fields=[
                    ComponentFieldDefinition(
                        "shape", "enum", False, '"Box"',
                        "TriggerShape: Box|Sphere|Capsule"
                    ),
                    ComponentFieldDefinition(
                        "dimensions", "struct", False, None,
                        "Trigger dimensions — same format as ColliderSize."
                    ),
                    ComponentFieldDefinition(
                        "filter_tags", "list", False, "[]",
                        "Only entities with at least one of these tags trigger this zone. "
                        "Empty list = all entities trigger."
                    ),
                    ComponentFieldDefinition(
                        "on_enter_action", "str", False, '""',
                        "Event type name emitted when entity enters."
                    ),
                    ComponentFieldDefinition(
                        "on_exit_action", "str", False, '""',
                        "Event type name emitted when entity exits."
                    ),
                    ComponentFieldDefinition(
                        "is_active", "bool", False, "true",
                        "Whether this trigger zone is currently active."
                    ),
                    ComponentFieldDefinition(
                        "entities_inside", "list", False, "[]",
                        "List of EntityIDs currently inside this zone."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=232,
                type_name="COMP_PERSISTENCE_V1",
                layer=ComponentLayer.DCL,
                domain="world",
                version=1,
                description="Controls how and when this entity's state is saved (Audit 7).",
                fields=[
                    ComponentFieldDefinition(
                        "save_key", "str", True, None,
                        "Unique key for this entity in the save file."
                    ),
                    ComponentFieldDefinition(
                        "auto_save", "bool", False, "true",
                        "Whether this entity's state is auto-saved on dirty."
                    ),
                    ComponentFieldDefinition(
                        "data_schema_id", "str", False, '""',
                        "Save data schema ID for migration compatibility."
                    ),
                    ComponentFieldDefinition(
                        "last_saved_tick", "u64", False, "0",
                        "Tick of last successful save."
                    ),
                    ComponentFieldDefinition(
                        "is_dirty", "bool", False, "false",
                        "True when state has changed since last save."
                    ),
                    ComponentFieldDefinition(
                        "save_layer", "enum", False, '"World"',
                        "SaveLayer: Session|Progress|World"
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=233,
                type_name="COMP_WORLDSTREAMING_V1",
                layer=ComponentLayer.DCL,
                domain="world",
                version=1,
                description="World chunk streaming state for infinite or large worlds.",
                fields=[
                    ComponentFieldDefinition(
                        "chunk_id", "str", True, None,
                        "Unique chunk identifier in the world grid."
                    ),
                    ComponentFieldDefinition(
                        "load_radius", "f32", False, "100.0",
                        "Distance at which this chunk is loaded."
                    ),
                    ComponentFieldDefinition(
                        "priority", "u32", False, "0",
                        "Loading priority — higher loads sooner."
                    ),
                    ComponentFieldDefinition(
                        "is_loaded", "bool", False, "false",
                        "Whether this chunk is currently loaded in the engine."
                    ),
                    ComponentFieldDefinition(
                        "streaming_state", "enum", False, '"Unloaded"',
                        "StreamingState: Unloaded|Loading|Loaded|Unloading"
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=234,
                type_name="COMP_ENVIRONMENT_V1",
                layer=ComponentLayer.DCL,
                domain="world",
                version=1,
                description="Environment zone — weather, lighting, atmosphere settings.",
                fields=[
                    ComponentFieldDefinition(
                        "environment_preset", "str", False, '"default"',
                        "Named environment preset ID from the engine asset library."
                    ),
                    ComponentFieldDefinition(
                        "weather_type", "enum", False, '"Clear"',
                        "WeatherType: Clear|Cloudy|Rain|Storm|Snow|Fog|Sandstorm"
                    ),
                    ComponentFieldDefinition(
                        "wind_speed", "f32", False, "0.0",
                        "Wind speed in units per second."
                    ),
                    ComponentFieldDefinition(
                        "wind_direction", "struct", False, None,
                        "Normalized Vec3 wind direction."
                    ),
                    ComponentFieldDefinition(
                        "ambient_temperature", "f32", False, "20.0",
                        "Ambient temperature in Celsius. Gameplay use only."
                    ),
                    ComponentFieldDefinition(
                        "is_water_volume", "bool", False, "false",
                        "True if this zone is a water volume for buoyancy."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=235,
                type_name="COMP_DESTRUCTIBLE_V1",
                layer=ComponentLayer.DCL,
                domain="world",
                version=1,
                description="Destructible object state — tracks damage and destruction stages.",
                fields=[
                    ComponentFieldDefinition(
                        "max_health", "f32", True, None,
                        "Health before destruction."
                    ),
                    ComponentFieldDefinition(
                        "current_health", "f32", True, None,
                        "Current health."
                    ),
                    ComponentFieldDefinition(
                        "destruction_stage", "u32", False, "0",
                        "Current damage stage (0=intact, max=destroyed)."
                    ),
                    ComponentFieldDefinition(
                        "max_stages", "u32", False, "3",
                        "Number of visual damage stages before destruction."
                    ),
                    ComponentFieldDefinition(
                        "debris_blueprint_id", "str", False, '""',
                        "Actor ID to spawn as debris on destruction."
                    ),
                    ComponentFieldDefinition(
                        "is_destroyed", "bool", False, "false",
                        "True when fully destroyed."
                    ),
                ],
            ),
        ],
    )