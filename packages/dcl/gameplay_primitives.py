"""Versioned, reusable gameplay primitive catalog.

Catalog entries are engine-neutral contracts. A primitive is admitted only
when its schema, system, event, input, asset, save, and network facets can be
materialized into committed CGS and replayed through the real runtime.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping


REQUIRED_FACETS = ("schema", "system", "event", "input", "asset", "save", "network")
TASK_REQUIRED_GENRES = (
    "platformer", "rpg", "shooter", "survival", "puzzle", "strategy",
    "simulation", "inventory", "combat", "multiplayer_combat",
)
RUNTIME_SYSTEM_CONTRACTS = {
    "InputSystem": ("Input", (5, 6), (5,)),
    "MovementIntentSystem": ("Input", (6, 120), (120,)),
    "PlatformerMotionSystem": ("Simulation", (5, 120, 125), (5, 125)),
    "MovementSystem": ("Simulation", (1, 5), (1,)),
    "InteractionSystem": ("Simulation", (1, 2, 6, 260), (6, 260)),
    "InventorySystem": ("Simulation", (1, 6, 201, 205, 260), (1, 201, 205, 260)),
    "AISystem": ("Simulation", (1, 2, 160), (5, 101)),
    "DamageSystem": ("Simulation", (100, 101), (100, 101)),
    "DeathSystem": ("Simulation", (100,), ()),
}
RUNTIME_SYSTEM_IDS = frozenset(RUNTIME_SYSTEM_CONTRACTS)
SEMANTIC_INPUT_ACTIONS = {"Move", "Jump", "Crouch", "Dash", "Attack", "Interact", "Pickup"}
SEMANTIC_EVENT_CONTRACTS = {
    "movement.jump_started": ("actor_entity_id", "movement_state"),
    "movement.landed": ("actor_entity_id", "movement_state"),
    "interaction.focused": ("actor_entity_id", "target_entity_id", "interaction_state"),
    "interaction.unfocused": ("actor_entity_id", "target_entity_id", "interaction_state"),
    "interaction.interacted": (
        "actor_entity_id", "target_entity_id", "interaction_state", "interaction_type",
    ),
    "interaction.accepted": (
        "actor_entity_id", "target_entity_id", "interaction_state", "interaction_type",
    ),
    "inventory.pickup_requested": ("actor_entity_id", "item_entity_id", "inventory_state"),
    "inventory.pickup_accepted": ("actor_entity_id", "item_entity_id", "inventory_state"),
    "inventory.pickup_rejected": (
        "actor_entity_id", "item_entity_id", "inventory_state", "reason",
    ),
    "inventory.equipped": ("actor_entity_id", "item_entity_id", "inventory_state"),
    "inventory.equip_rejected": (
        "actor_entity_id", "item_entity_id", "inventory_state", "reason",
    ),
    "inventory.dropped": ("actor_entity_id", "item_entity_id", "inventory_state"),
    "inventory.drop_rejected": (
        "actor_entity_id", "item_entity_id", "inventory_state", "reason",
    ),
    "combat.attack_started": ("actor_entity_id",),
    "combat.hit_confirmed": ("source_entity_id", "target_entity_id"),
    "combat.blocked": ("source_entity_id", "target_entity_id"),
    "combat.parried": ("source_entity_id", "target_entity_id"),
    "combat.killed": ("source_entity_id", "target_entity_id"),
    "animation.command_requested": ("entity_id",),
    "animation.playback_started": ("entity_id",),
    "animation.playback_completed": ("entity_id",),
    "audio.playback_requested": ("entity_id",),
    "audio.playback_completed": ("entity_id",),
    "vfx.playback_requested": ("entity_id",),
    "vfx.playback_completed": ("entity_id",),
}
CANONICAL_COMPONENT_CONTRACTS = {
    1: ("COMP_TRANSFORM_V1", "ucl"),
    2: ("COMP_IDENTITY_V1", "ucl"),
    5: ("COMP_VELOCITY_V1", "ucl"),
    6: ("COMP_INPUT_V1", "ucl"),
    10: ("COMP_AUTHORITY_V1", "ucl"),
    100: ("COMP_HEALTH_V1", "dcl.combat"),
    101: ("COMP_DAMAGE_V1", "dcl.combat"),
    102: ("COMP_HITBOX_V1", "dcl.combat"),
    103: ("COMP_SHIELD_V1", "dcl.combat"),
    104: ("COMP_STATUS_EFFECT_V1", "dcl.combat"),
    120: ("COMP_MOVEMENT_INTENT_V1", "dcl.character"),
    125: ("COMP_KINEMATIC_CHARACTER_V1", "dcl.character"),
    140: ("COMP_RIGIDBODY_V1", "dcl.physics"),
    160: ("COMP_AI_V1", "dcl.ai"),
    161: ("COMP_PATROL_V1", "dcl.ai"),
    200: ("COMP_STATS_V1", "dcl.rpg"),
    201: ("COMP_INVENTORY_V1", "dcl.rpg"),
    202: ("COMP_ABILITY_V1", "dcl.rpg"),
    203: ("COMP_PROGRESSION_V1", "dcl.rpg"),
    204: ("COMP_ECONOMY_V1", "dcl.rpg"),
    205: ("COMP_ITEM_V1", "dcl.rpg"),
    230: ("COMP_SPAWNER_V1", "dcl.world"),
    231: ("COMP_TRIGGERZONE_V1", "dcl.world"),
    232: ("COMP_PERSISTENCE_V1", "dcl.world"),
    234: ("COMP_ENVIRONMENT_V1", "dcl.world"),
    260: ("COMP_INTERACTION_V1", "dcl.interaction"),
    262: ("COMP_PUZZLE_V1", "dcl.interaction"),
    263: ("COMP_USABLE_V1", "dcl.interaction"),
    320: ("COMP_REPLICATION_V1", "dcl.network"),
    321: ("COMP_NETWORK_TRANSFORM_V1", "dcl.network"),
    322: ("COMP_PLAYER_SESSION_V1", "dcl.network"),
    360: ("COMP_SAVE_SLOT_V1", "dcl.persistence"),
    361: ("COMP_CHECKPOINT_V1", "dcl.persistence"),
    362: ("COMP_PLAYER_PROFILE_V1", "dcl.persistence"),
}
ASSET_TYPE_WIRE_NAMES = {"AudioClip": "AUDIO_CLIP", "Particle": "PARTICLE"}


@dataclass(frozen=True)
class ComponentPrimitive:
    type_id: int
    name: str
    defaults: Mapping[str, Any]
    source: str


@dataclass(frozen=True)
class SystemPrimitive:
    system_id: str
    phase: str
    reads: tuple[int, ...]
    writes: tuple[int, ...]
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class EventPrimitive:
    name: str
    required_payload_keys: tuple[str, ...]


@dataclass(frozen=True)
class InputPrimitive:
    action: str
    kind: str
    phase: str
    target_field: str


@dataclass(frozen=True)
class AssetPrimitive:
    binding_id: str
    event_name: str
    playback_kind: str
    asset_id: str
    asset_type: str
    semantic_action: str
    priority: int


@dataclass(frozen=True)
class SavePrimitive:
    component_type_ids: tuple[int, ...]
    strategy: str
    save_layer: str


@dataclass(frozen=True)
class NetworkPrimitive:
    component_type_ids: tuple[int, ...]
    authority: str
    replication_mode: str
    prediction_enabled: bool


@dataclass(frozen=True)
class GameplayPrimitive:
    primitive_id: str
    version: str
    display_name: str
    genres: tuple[str, ...]
    facets: tuple[str, ...]
    components: tuple[ComponentPrimitive, ...]
    systems: tuple[SystemPrimitive, ...]
    events: tuple[EventPrimitive, ...]
    inputs: tuple[InputPrimitive, ...]
    assets: tuple[AssetPrimitive, ...]
    save: SavePrimitive
    network: NetworkPrimitive


def _catalog_component(type_id: int, defaults: Mapping[str, Any]) -> ComponentPrimitive:
    name, source = CANONICAL_COMPONENT_CONTRACTS[type_id]
    return ComponentPrimitive(type_id, name, defaults, source)


def _component_set(
    save_key: str,
    actions: tuple[str, ...],
    extras: tuple[ComponentPrimitive, ...],
    *,
    authority: str = "Local",
    replication_mode: str = "None",
    prediction_enabled: bool = False,
) -> tuple[ComponentPrimitive, ...]:
    action_set = set(actions)
    components = [
        _catalog_component(1, {
            "position_x": 0, "position_y": 0, "position_z": 0,
            "bounds_min_x": -24000000, "bounds_max_x": 24000000,
            "bounds_min_z": -24000000, "bounds_max_z": 24000000,
        }),
        _catalog_component(2, {
            "entity_name": "Primitive Player", "entity_type": "Player",
            "faction": "player", "tags": ["player"], "prefab_id": "",
            "is_runtime_spawned": False,
        }),
        _catalog_component(5, {
            "linear_x": 0, "linear_y": 0, "linear_z": 0,
            "max_linear_speed": 6000000,
        }),
        _catalog_component(6, {
            "move_x": 1000000, "move_z": 0,
            "attack_started": False,
            "interact_started": False,
            "pickup_started": False,
            "dash_pressed": False,
            "jump_started": False,
            "crouch_pressed": False,
            "active_actions": sorted(action_set),
        }),
        _catalog_component(10, {
            "authority_type": authority, "owner_peer_id": 1 if authority != "Local" else 0,
            "replication_mode": replication_mode,
            "prediction_enabled": prediction_enabled,
            "reconciliation_mode": "Interpolate",
            "sync_rate_divisor": 1,
            "is_replicated": replication_mode != "None",
        }),
        _catalog_component(232, {
            "save_key": save_key, "auto_save": True,
            "data_schema_id": f"{save_key}.v1", "last_saved_tick": 0,
            "is_dirty": False, "save_layer": "Progress",
        }),
        _catalog_component(320, {
            "replication_mode": replication_mode, "priority": 1000000,
            "last_replicated_tick": 0, "dirty_flags": [],
            "relevance_radius": 0, "sync_rate_divisor": 1,
        }),
    ]
    components.extend(extras)
    return tuple(sorted(components, key=lambda component: component.type_id))


def _system(system_id: str, *dependencies: str) -> SystemPrimitive:
    phase, reads, writes = RUNTIME_SYSTEM_CONTRACTS[system_id]
    return SystemPrimitive(system_id, phase, reads, writes, tuple(dependencies))


def _systems(*system_ids: str) -> tuple[SystemPrimitive, ...]:
    systems: list[SystemPrimitive] = []
    for system_id in system_ids:
        dependencies = (systems[-1].system_id,) if systems else ()
        systems.append(_system(system_id, *dependencies))
    return tuple(systems)


def _event(name: str) -> EventPrimitive:
    return EventPrimitive(name, SEMANTIC_EVENT_CONTRACTS[name])


def _input(
    action: str,
    target_field: str,
    *,
    kind: str = "button",
    phase: str = "started",
) -> InputPrimitive:
    return InputPrimitive(action, kind, phase, target_field)


def _audio(
    binding_id: str,
    event_name: str,
    asset_id: str,
    priority: int,
) -> AssetPrimitive:
    return AssetPrimitive(
        binding_id, event_name, "Audio", asset_id, "AudioClip", "play", priority,
    )


def _vfx(
    binding_id: str,
    event_name: str,
    asset_id: str,
    priority: int,
) -> AssetPrimitive:
    return AssetPrimitive(
        binding_id, event_name, "Vfx", asset_id, "Particle", "spawn", priority,
    )


PLATFORMER_COMPONENTS = (
    ComponentPrimitive(1, "COMP_TRANSFORM_V1", {
        "position_x": 0, "position_y": 0, "position_z": 0,
        "bounds_min_x": -24000000, "bounds_max_x": 24000000,
        "bounds_min_z": -24000000, "bounds_max_z": 24000000,
    }, "ucl"),
    ComponentPrimitive(5, "COMP_VELOCITY_V1", {
        "linear_x": 0, "linear_y": 0, "linear_z": 0,
        "max_linear_speed": 30000000,
    }, "ucl"),
    ComponentPrimitive(6, "COMP_INPUT_V1", {
        "move_x": 1000000, "move_z": 0,
        "jump_pressed": True, "jump_started": True,
        "crouch_pressed": False, "dash_pressed": False,
        "active_actions": ["Jump", "Move"],
    }, "ucl"),
    ComponentPrimitive(10, "COMP_AUTHORITY_V1", {
        "authority_type": "Local", "owner_peer_id": 0,
        "replication_mode": "Unreliable", "prediction_enabled": False,
        "reconciliation_mode": "Interpolate", "sync_rate_divisor": 1,
        "is_replicated": False,
    }, "ucl"),
    ComponentPrimitive(120, "COMP_MOVEMENT_INTENT_V1", {
        "direction_x": 0, "direction_y": 0, "direction_z": 0,
        "sprint_requested": False, "jump_requested": True,
        "jump_held": False, "crouch_requested": False,
    }, "dcl.character"),
    ComponentPrimitive(125, "COMP_KINEMATIC_CHARACTER_V1", {
        "grounded": True, "was_grounded": True,
        "max_horizontal_speed": 6000000, "jump_impulse": 12000000,
        "gravity_per_tick": 500000, "terminal_fall_speed": 30000000,
        "coyote_ticks": 6, "coyote_ticks_remaining": 6,
        "jump_buffer_ticks": 6, "jump_buffer_ticks_remaining": 0,
        "max_jumps": 1, "jumps_used": 0,
    }, "dcl.character"),
    ComponentPrimitive(232, "COMP_PERSISTENCE_V1", {
        "save_key": "platformer.player", "auto_save": True,
        "data_schema_id": "platformer.player.v1", "last_saved_tick": 0,
        "is_dirty": False, "save_layer": "Progress",
    }, "dcl.world"),
    ComponentPrimitive(320, "COMP_REPLICATION_V1", {
        "replication_mode": "None", "priority": 1000000,
        "last_replicated_tick": 0, "dirty_flags": [],
        "relevance_radius": 0, "sync_rate_divisor": 1,
    }, "dcl.network"),
    ComponentPrimitive(361, "COMP_CHECKPOINT_V1", {
        "checkpoint_type": "RESPAWN", "world_state_hash": "",
        "respawn_position": {"x": 0, "y": 0, "z": 0},
        "activation_tick": 0, "is_activated": True,
        "triggers_autosave": True,
    }, "dcl.persistence"),
)


PLATFORMER_KINEMATIC_MOVEMENT_V1 = GameplayPrimitive(
    primitive_id="platformer.kinematic_movement.v1",
    version="1.0.0",
    display_name="Platformer Kinematic Movement",
    genres=("platformer",),
    facets=REQUIRED_FACETS,
    components=PLATFORMER_COMPONENTS,
    systems=(
        SystemPrimitive("MovementIntentSystem", "Input", (6, 120), (120,)),
        SystemPrimitive(
            "PlatformerMotionSystem", "Simulation", (5, 120, 125), (5, 125),
            ("MovementIntentSystem",),
        ),
        SystemPrimitive(
            "MovementSystem", "Simulation", (1, 5), (1,),
            ("PlatformerMotionSystem",),
        ),
    ),
    events=(
        EventPrimitive("movement.jump_started", ("actor_entity_id", "movement_state")),
        EventPrimitive("movement.landed", ("actor_entity_id", "movement_state")),
    ),
    inputs=(
        InputPrimitive("Move", "axis_2d", "changed", "direction_x,direction_z"),
        InputPrimitive("Jump", "button", "started|performed", "jump_requested,jump_held"),
    ),
    assets=(
        AssetPrimitive(
            "platformer.jump.audio.v1", "movement.jump_started", "Audio",
            "platformer_jump_sfx_v1", "AudioClip", "play", 0,
        ),
        AssetPrimitive(
            "platformer.land.vfx.v1", "movement.landed", "Vfx",
            "platformer_land_particle_v1", "Particle", "spawn", 1,
        ),
    ),
    save=SavePrimitive((232, 361), "component_snapshot", "Progress"),
    network=NetworkPrimitive((10, 320), "Local", "None", False),
)


_HEALTH = _catalog_component(100, {
    "current": 100000000, "max": 100000000, "regen_rate": 0,
    "is_invincible": False, "death_behavior": "DestroyEntity", "last_damage_tick": 0,
})
_DAMAGE = _catalog_component(101, {
    "damage_type": "Physical", "amount": 1000000, "source_entity_id": 0,
    "applied_tick": 0, "is_consumed": False, "can_crit": True,
})
_HITBOX = _catalog_component(102, {
    "shape": "Capsule", "size": {"x": 1000000, "y": 2000000, "z": 1000000},
    "offset": {"x": 0, "y": 1000000, "z": 0}, "damage_multiplier": 1000000,
    "hitbox_type": "Body", "is_active": True,
})
_SHIELD = _catalog_component(103, {
    "current": 25000000, "max": 25000000, "regen_rate": 0,
    "regen_delay_ticks": 120, "absorption_ratio": 1000000, "last_hit_tick": 0,
})
_STATUS_EFFECT = _catalog_component(104, {
    "effect_type": "Custom", "intensity": 1000000, "duration_ticks": 0,
    "elapsed_ticks": 0, "source_entity_id": 0, "tick_damage": 0,
    "is_consumed": True,
})
_RIGIDBODY = _catalog_component(140, {
    "mass": 1000000, "drag": 0, "angular_drag": 50000, "use_gravity": False,
    "is_kinematic": True, "freeze_position_x": False, "freeze_position_y": True,
    "freeze_position_z": False, "freeze_rotation_x": True,
    "freeze_rotation_y": True, "freeze_rotation_z": True,
})
_AI = _catalog_component(160, {
    "behavior_model": "Attack", "current_state": "AcquireTarget", "target_entity_id": 0,
    "detection_radius": 20000000, "attack_range": 1500000,
    "attack_damage": 1000000, "move_speed": 3000000,
    "aggression_level": 1000000, "memory": {},
    "home_position": {"x": 0, "y": 0, "z": 0},
})
_PATROL = _catalog_component(161, {
    "waypoints": [{"x": 0, "y": 0, "z": 0}, {"x": 5000000, "y": 0, "z": 0}],
    "current_waypoint_index": 0, "patrol_mode": "Loop",
    "wait_ticks_at_waypoint": 60, "wait_ticks_remaining": 0, "move_speed": 3000000,
})
_STATS = _catalog_component(200, {
    "base_values": {"defense": 5000000, "strength": 10000000},
    "current_values": {"defense": 5000000, "strength": 10000000},
    "modifiers": [],
})
_INVENTORY = _catalog_component(201, {
    "slots": [], "max_capacity": 20, "current_count": 0, "equipped_slot_id": "",
    "weight_current": 0, "weight_max": 100000000,
})
_ABILITY = _catalog_component(202, {
    "ability_id": "basic_attack", "is_unlocked": True, "cooldown_ticks": 30,
    "cooldown_remaining": 0, "resource_cost": 0, "is_active": False,
    "activation_tick": 0,
})
_PROGRESSION = _catalog_component(203, {
    "level": 1, "experience": 0, "experience_to_next": 100000000,
    "skill_points": 0, "max_level": 100,
})
_ECONOMY = _catalog_component(204, {
    "currencies": {"gold": 0}, "transaction_history": [],
})
_ITEM = _catalog_component(205, {
    "item_id": "starter_item", "display_name": "Starter Item", "quantity": 1,
    "slot_type": "hand", "weight": 1000000, "is_pickable": True,
    "owner_entity_id": 0, "inventory_slot_id": "", "is_equipped": False,
    "world_state": "World",
})
_SPAWNER = _catalog_component(230, {
    "blueprint_id": "unit.basic.v1", "spawn_rate_ticks": 60, "max_count": 10,
    "current_count": 0, "spawn_radius": 3000000, "is_active": True,
    "ticks_since_last_spawn": 0,
})
_TRIGGERZONE = _catalog_component(231, {
    "shape": "Box", "dimensions": {"x": 2000000, "y": 2000000, "z": 2000000},
    "filter_tags": ["player"], "on_enter_action": "interaction.focused",
    "on_exit_action": "interaction.unfocused", "is_active": True, "entities_inside": [],
})
_ENVIRONMENT = _catalog_component(234, {
    "environment_preset": "default", "weather_type": "Clear", "wind_speed": 0,
    "wind_direction": {"x": 0, "y": 0, "z": 0}, "ambient_temperature": 20000000,
    "is_water_volume": False,
})
_INTERACTION = _catalog_component(260, {
    "interaction_type": "Use", "range": 3000000, "is_interactable": True,
    "required_tag": "", "prompt_text": "Interact", "interaction_count": 0,
    "max_interactions": 0,
})
_PUZZLE = _catalog_component(262, {
    "puzzle_id": "logic_gate.v1", "is_solved": False, "element_states": {"switch": 0},
    "solution": {"switch": 1}, "attempts": 0, "solved_tick": 0,
})
_USABLE = _catalog_component(263, {
    "use_action": "interaction.accepted", "charges": -1, "cooldown_ticks": 0,
    "cooldown_remaining": 0, "is_usable": True,
})
_NETWORK_TRANSFORM = _catalog_component(321, {
    "last_known_position": {"x": 0, "y": 0, "z": 0},
    "interpolation_target": {"x": 0, "y": 0, "z": 0},
    "extrapolation_velocity": {"x": 0, "y": 0, "z": 0},
    "network_timestamp": 0, "snap_threshold": 5000000, "interpolation_ticks": 2,
})
_PLAYER_SESSION = _catalog_component(322, {
    "peer_id": 1, "session_state": "Live", "latency_ms": 0,
    "input_sequence_id": 0, "authority_level": "Server", "display_name": "Player One",
})
_SAVE_SLOT = _catalog_component(360, {
    "slot_id": "slot-1", "schema_version": "1.0.0",
    "created_at": "2026-01-01T00:00:00Z", "last_played": "2026-01-01T00:00:00Z",
    "play_time_ticks": 0, "display_name": "Primitive Save", "is_autosave": True,
})
_CHECKPOINT = _catalog_component(361, {
    "checkpoint_type": "AUTO", "world_state_hash": "",
    "respawn_position": {"x": 0, "y": 0, "z": 0}, "activation_tick": 0,
    "is_activated": True, "triggers_autosave": True,
})
_PLAYER_PROFILE = _catalog_component(362, {
    "profile_id": "primitive-player", "display_name": "Player", "achievements": [],
    "settings": {}, "total_play_time": 0, "last_played_slot_id": "slot-1",
    "statistics": {},
})


RPG_ADVENTURE_LOOP_V1 = GameplayPrimitive(
    primitive_id="rpg.adventure_loop.v1",
    version="1.0.0",
    display_name="RPG Adventure Loop",
    genres=("rpg",),
    facets=REQUIRED_FACETS,
    components=_component_set(
        "rpg.player", ("Move", "Interact", "Pickup", "Attack"),
        (
            _HEALTH, _DAMAGE, _STATS, _INVENTORY, _ABILITY, _PROGRESSION,
            _ECONOMY, _ITEM, _INTERACTION, _PLAYER_PROFILE,
        ),
    ),
    systems=_systems(
        "InputSystem", "InteractionSystem", "InventorySystem", "DamageSystem", "DeathSystem",
    ),
    events=(
        _event("inventory.pickup_accepted"),
        _event("inventory.equipped"),
        _event("combat.killed"),
    ),
    inputs=(
        _input("Move", "move_x,move_z", kind="axis_2d", phase="changed"),
        _input("Interact", "interact_started"),
        _input("Pickup", "pickup_started"),
        _input("Attack", "attack_started"),
    ),
    assets=(
        _audio(
            "rpg.pickup.audio.v1", "inventory.pickup_accepted",
            "rpg_pickup_sfx_v1", 0,
        ),
        _vfx("rpg.kill.vfx.v1", "combat.killed", "rpg_kill_vfx_v1", 1),
    ),
    save=SavePrimitive((100, 200, 201, 203, 204, 232, 362), "component_snapshot", "Progress"),
    network=NetworkPrimitive((10, 320), "Local", "None", False),
)


SHOOTER_COMBAT_LOOP_V1 = GameplayPrimitive(
    primitive_id="shooter.combat_loop.v1",
    version="1.0.0",
    display_name="Shooter Combat Loop",
    genres=("shooter",),
    facets=REQUIRED_FACETS,
    components=_component_set(
        "shooter.player", ("Move", "Attack", "Dash"),
        (_HEALTH, _DAMAGE, _HITBOX, _AI, _CHECKPOINT),
    ),
    systems=_systems(
        "InputSystem", "AISystem", "MovementSystem", "DamageSystem", "DeathSystem",
    ),
    events=(
        _event("combat.attack_started"),
        _event("combat.hit_confirmed"),
        _event("combat.killed"),
    ),
    inputs=(
        _input("Move", "move_x,move_z", kind="axis_2d", phase="changed"),
        _input("Attack", "attack_started"),
        _input("Dash", "dash_pressed"),
    ),
    assets=(
        _audio(
            "shooter.attack.audio.v1", "combat.attack_started",
            "shooter_attack_sfx_v1", 0,
        ),
        _vfx(
            "shooter.hit.vfx.v1", "combat.hit_confirmed",
            "shooter_hit_vfx_v1", 1,
        ),
    ),
    save=SavePrimitive((100, 232, 361), "component_snapshot", "Progress"),
    network=NetworkPrimitive((10, 320), "Local", "None", False),
)


SURVIVAL_GATHER_AND_DEFEND_V1 = GameplayPrimitive(
    primitive_id="survival.gather_and_defend.v1",
    version="1.0.0",
    display_name="Survival Gather and Defend",
    genres=("survival",),
    facets=REQUIRED_FACETS,
    components=_component_set(
        "survival.player", ("Move", "Interact", "Pickup", "Attack"),
        (
            _HEALTH, _DAMAGE, _AI, _INVENTORY, _ITEM, _ENVIRONMENT,
            _INTERACTION, _CHECKPOINT,
        ),
    ),
    systems=_systems(
        "InputSystem", "InteractionSystem", "InventorySystem", "AISystem",
        "DamageSystem", "DeathSystem",
    ),
    events=(
        _event("inventory.pickup_accepted"),
        _event("combat.hit_confirmed"),
        _event("combat.killed"),
    ),
    inputs=(
        _input("Move", "move_x,move_z", kind="axis_2d", phase="changed"),
        _input("Interact", "interact_started"),
        _input("Pickup", "pickup_started"),
        _input("Attack", "attack_started"),
    ),
    assets=(
        _audio(
            "survival.pickup.audio.v1", "inventory.pickup_accepted",
            "survival_pickup_sfx_v1", 0,
        ),
        _vfx(
            "survival.hit.vfx.v1", "combat.hit_confirmed",
            "survival_hit_vfx_v1", 1,
        ),
    ),
    save=SavePrimitive((100, 201, 232, 234, 361), "component_snapshot", "Progress"),
    network=NetworkPrimitive((10, 320), "Local", "None", False),
)


PUZZLE_INTERACTION_LOOP_V1 = GameplayPrimitive(
    primitive_id="puzzle.interaction_loop.v1",
    version="1.0.0",
    display_name="Puzzle Interaction Loop",
    genres=("puzzle",),
    facets=REQUIRED_FACETS,
    components=_component_set(
        "puzzle.player", ("Move", "Interact"),
        (_TRIGGERZONE, _INTERACTION, _PUZZLE, _USABLE, _CHECKPOINT),
    ),
    systems=_systems("InputSystem", "MovementSystem", "InteractionSystem"),
    events=(
        _event("interaction.interacted"),
        _event("interaction.accepted"),
    ),
    inputs=(
        _input("Move", "move_x,move_z", kind="axis_2d", phase="changed"),
        _input("Interact", "interact_started"),
    ),
    assets=(
        _audio(
            "puzzle.interact.audio.v1", "interaction.interacted",
            "puzzle_interact_sfx_v1", 0,
        ),
        _vfx(
            "puzzle.accepted.vfx.v1", "interaction.accepted",
            "puzzle_accepted_vfx_v1", 1,
        ),
    ),
    save=SavePrimitive((232, 262, 361), "component_snapshot", "Progress"),
    network=NetworkPrimitive((10, 320), "Local", "None", False),
)


STRATEGY_UNIT_COMMAND_V1 = GameplayPrimitive(
    primitive_id="strategy.unit_command.v1",
    version="1.0.0",
    display_name="Strategy Unit Command",
    genres=("strategy",),
    facets=REQUIRED_FACETS,
    components=_component_set(
        "strategy.commander", ("Move", "Attack"),
        (_HEALTH, _DAMAGE, _AI, _PATROL, _ECONOMY, _SPAWNER, _CHECKPOINT),
    ),
    systems=_systems(
        "InputSystem", "AISystem", "MovementSystem", "DamageSystem", "DeathSystem",
    ),
    events=(
        _event("combat.attack_started"),
        _event("combat.hit_confirmed"),
        _event("combat.killed"),
    ),
    inputs=(
        _input("Move", "move_x,move_z", kind="axis_2d", phase="changed"),
        _input("Attack", "attack_started"),
    ),
    assets=(
        _audio(
            "strategy.command.audio.v1", "combat.attack_started",
            "strategy_command_sfx_v1", 0,
        ),
        _vfx(
            "strategy.kill.vfx.v1", "combat.killed",
            "strategy_unit_removed_vfx_v1", 1,
        ),
    ),
    save=SavePrimitive((100, 161, 204, 230, 232, 361), "component_snapshot", "Progress"),
    network=NetworkPrimitive((10, 320), "Local", "None", False),
)


SIMULATION_INTERACTIVE_ENTITY_V1 = GameplayPrimitive(
    primitive_id="simulation.interactive_entity.v1",
    version="1.0.0",
    display_name="Simulation Interactive Entity",
    genres=("simulation",),
    facets=REQUIRED_FACETS,
    components=_component_set(
        "simulation.actor", ("Move", "Interact"),
        (_RIGIDBODY, _ENVIRONMENT, _INTERACTION, _USABLE, _SAVE_SLOT),
    ),
    systems=_systems("InputSystem", "MovementSystem", "InteractionSystem"),
    events=(
        _event("interaction.interacted"),
        _event("interaction.accepted"),
    ),
    inputs=(
        _input("Move", "move_x,move_z", kind="axis_2d", phase="changed"),
        _input("Interact", "interact_started"),
    ),
    assets=(
        _audio(
            "simulation.interact.audio.v1", "interaction.interacted",
            "simulation_interact_sfx_v1", 0,
        ),
        _vfx(
            "simulation.accepted.vfx.v1", "interaction.accepted",
            "simulation_accepted_vfx_v1", 1,
        ),
    ),
    save=SavePrimitive((140, 232, 234, 360), "component_snapshot", "World"),
    network=NetworkPrimitive((10, 320), "Local", "None", False),
)


INVENTORY_ITEM_LIFECYCLE_V1 = GameplayPrimitive(
    primitive_id="inventory.item_lifecycle.v1",
    version="1.0.0",
    display_name="Inventory Item Lifecycle",
    genres=("inventory",),
    facets=REQUIRED_FACETS,
    components=_component_set(
        "inventory.owner", ("Move", "Interact", "Pickup"),
        (_INVENTORY, _ITEM, _INTERACTION, _PLAYER_PROFILE),
    ),
    systems=_systems(
        "InputSystem", "InteractionSystem", "InventorySystem",
    ),
    events=(
        _event("inventory.pickup_accepted"),
        _event("inventory.equipped"),
        _event("inventory.dropped"),
    ),
    inputs=(
        _input("Move", "move_x,move_z", kind="axis_2d", phase="changed"),
        _input("Interact", "interact_started"),
        _input("Pickup", "pickup_started"),
    ),
    assets=(
        _audio(
            "inventory.pickup.audio.v1", "inventory.pickup_accepted",
            "inventory_pickup_sfx_v1", 0,
        ),
        _audio(
            "inventory.equip.audio.v1", "inventory.equipped",
            "inventory_equip_sfx_v1", 1,
        ),
        _vfx(
            "inventory.drop.vfx.v1", "inventory.dropped",
            "inventory_drop_vfx_v1", 2,
        ),
    ),
    save=SavePrimitive((201, 205, 232, 362), "component_snapshot", "Progress"),
    network=NetworkPrimitive((10, 320), "Local", "None", False),
)


COMBAT_DAMAGE_RESOLUTION_V1 = GameplayPrimitive(
    primitive_id="combat.damage_resolution.v1",
    version="1.0.0",
    display_name="Combat Damage Resolution",
    genres=("combat",),
    facets=REQUIRED_FACETS,
    components=_component_set(
        "combat.fighter", ("Move", "Attack", "Dash"),
        (_HEALTH, _DAMAGE, _HITBOX, _SHIELD, _STATUS_EFFECT, _CHECKPOINT),
    ),
    systems=_systems("InputSystem", "MovementSystem", "DamageSystem", "DeathSystem"),
    events=(
        _event("combat.attack_started"),
        _event("combat.hit_confirmed"),
        _event("combat.blocked"),
        _event("combat.parried"),
        _event("combat.killed"),
    ),
    inputs=(
        _input("Move", "move_x,move_z", kind="axis_2d", phase="changed"),
        _input("Attack", "attack_started"),
        _input("Dash", "dash_pressed"),
    ),
    assets=(
        _audio(
            "combat.attack.audio.v1", "combat.attack_started",
            "combat_attack_sfx_v1", 0,
        ),
        _vfx(
            "combat.hit.vfx.v1", "combat.hit_confirmed",
            "combat_hit_vfx_v1", 1,
        ),
        _audio(
            "combat.parry.audio.v1", "combat.parried",
            "combat_parry_sfx_v1", 2,
        ),
    ),
    save=SavePrimitive((100, 103, 104, 232, 361), "component_snapshot", "Progress"),
    network=NetworkPrimitive((10, 320), "Local", "None", False),
)


MULTIPLAYER_AUTHORITATIVE_COMBAT_V1 = GameplayPrimitive(
    primitive_id="multiplayer_combat.authoritative_loop.v1",
    version="1.0.0",
    display_name="Multiplayer Authoritative Combat",
    genres=("multiplayer_combat",),
    facets=REQUIRED_FACETS,
    components=_component_set(
        "multiplayer_combat.player", ("Move", "Attack", "Dash"),
        (_HEALTH, _DAMAGE, _HITBOX, _AI, _NETWORK_TRANSFORM, _PLAYER_SESSION, _PLAYER_PROFILE),
        authority="Server", replication_mode="Unreliable", prediction_enabled=False,
    ),
    systems=_systems(
        "InputSystem", "AISystem", "MovementSystem", "DamageSystem", "DeathSystem",
    ),
    events=(
        _event("combat.attack_started"),
        _event("combat.hit_confirmed"),
        _event("combat.killed"),
    ),
    inputs=(
        _input("Move", "move_x,move_z", kind="axis_2d", phase="changed"),
        _input("Attack", "attack_started"),
        _input("Dash", "dash_pressed"),
    ),
    assets=(
        _audio(
            "multiplayer_combat.attack.audio.v1", "combat.attack_started",
            "multiplayer_combat_attack_sfx_v1", 0,
        ),
        _vfx(
            "multiplayer_combat.hit.vfx.v1", "combat.hit_confirmed",
            "multiplayer_combat_hit_vfx_v1", 1,
        ),
    ),
    save=SavePrimitive((100, 232, 362), "component_snapshot", "Progress"),
    network=NetworkPrimitive(
        (1, 5, 10, 100, 320, 321, 322), "Server", "Unreliable", False,
    ),
)


GAMEPLAY_PRIMITIVES = (
    PLATFORMER_KINEMATIC_MOVEMENT_V1,
    RPG_ADVENTURE_LOOP_V1,
    SHOOTER_COMBAT_LOOP_V1,
    SURVIVAL_GATHER_AND_DEFEND_V1,
    PUZZLE_INTERACTION_LOOP_V1,
    STRATEGY_UNIT_COMMAND_V1,
    SIMULATION_INTERACTIVE_ENTITY_V1,
    INVENTORY_ITEM_LIFECYCLE_V1,
    COMBAT_DAMAGE_RESOLUTION_V1,
    MULTIPLAYER_AUTHORITATIVE_COMBAT_V1,
)


def covered_genres(
    primitives: tuple[GameplayPrimitive, ...] = GAMEPLAY_PRIMITIVES,
) -> tuple[str, ...]:
    covered = {genre for primitive in primitives for genre in primitive.genres}
    return tuple(genre for genre in TASK_REQUIRED_GENRES if genre in covered)


def remaining_genres(
    primitives: tuple[GameplayPrimitive, ...] = GAMEPLAY_PRIMITIVES,
) -> tuple[str, ...]:
    covered = set(covered_genres(primitives))
    return tuple(genre for genre in TASK_REQUIRED_GENRES if genre not in covered)


def validate_catalog(
    primitives: tuple[GameplayPrimitive, ...] = GAMEPLAY_PRIMITIVES,
) -> list[str]:
    findings: list[str] = []
    seen_ids: set[str] = set()
    for primitive in primitives:
        prefix = primitive.primitive_id or "<empty>"
        if not primitive.primitive_id:
            findings.append("primitive_id must not be empty")
        elif primitive.primitive_id in seen_ids:
            findings.append(f"duplicate primitive_id: {primitive.primitive_id}")
        seen_ids.add(primitive.primitive_id)
        findings.extend(_validate_primitive(prefix, primitive))
    return findings


def _validate_primitive(prefix: str, primitive: GameplayPrimitive) -> list[str]:
    findings: list[str] = []
    if primitive.facets != REQUIRED_FACETS:
        findings.append(f"{prefix}: facets must equal {REQUIRED_FACETS}")
    if not primitive.genres:
        findings.append(f"{prefix}: at least one genre is required")
    unknown_genres = sorted(set(primitive.genres) - set(TASK_REQUIRED_GENRES))
    if unknown_genres:
        findings.append(f"{prefix}: unknown genres {unknown_genres}")

    component_ids = [component.type_id for component in primitive.components]
    if not component_ids:
        findings.append(f"{prefix}: schema facet must declare components")
    if len(component_ids) != len(set(component_ids)):
        findings.append(f"{prefix}: duplicate component type IDs")
    if component_ids != sorted(component_ids):
        findings.append(f"{prefix}: component type IDs must be sorted")
    declared = set(component_ids)
    for component in primitive.components:
        if component.type_id <= 0 or not component.name or not component.source:
            findings.append(f"{prefix}: invalid component {component.type_id}")
        canonical = CANONICAL_COMPONENT_CONTRACTS.get(component.type_id)
        if canonical is None:
            findings.append(f"{prefix}: component {component.type_id} is not a frozen catalog type")
        elif (component.name, component.source) != canonical:
            findings.append(
                f"{prefix}: component {component.type_id} must be {canonical[0]} from {canonical[1]}"
            )
        for path in _float_paths(component.defaults):
            findings.append(f"{prefix}: authoritative float at component {component.type_id}.{path}")

    if not primitive.systems:
        findings.append(f"{prefix}: system facet must declare runtime systems")
    findings.extend(_validate_systems(prefix, primitive.systems, declared))
    event_names = [event.name for event in primitive.events]
    if not event_names:
        findings.append(f"{prefix}: event facet must declare semantic events")
    if len(event_names) != len(set(event_names)):
        findings.append(f"{prefix}: duplicate semantic events")
    for event in primitive.events:
        contract = SEMANTIC_EVENT_CONTRACTS.get(event.name)
        if contract is None:
            findings.append(f"{prefix}: unregistered semantic event {event.name}")
        elif event.required_payload_keys != contract:
            findings.append(f"{prefix}: semantic event {event.name} payload contract mismatch")
    input_actions = [input_item.action for input_item in primitive.inputs]
    if not input_actions:
        findings.append(f"{prefix}: input facet must declare semantic inputs")
    if len(input_actions) != len(set(input_actions)):
        findings.append(f"{prefix}: duplicate semantic inputs")
    for action in input_actions:
        if action not in SEMANTIC_INPUT_ACTIONS:
            findings.append(f"{prefix}: unregistered semantic input {action}")
    if not primitive.assets:
        findings.append(f"{prefix}: asset facet must declare semantic bindings")
    binding_ids = [asset.binding_id for asset in primitive.assets]
    asset_ids = [asset.asset_id for asset in primitive.assets]
    if len(binding_ids) != len(set(binding_ids)):
        findings.append(f"{prefix}: duplicate asset binding IDs")
    if len(asset_ids) != len(set(asset_ids)):
        findings.append(f"{prefix}: duplicate asset IDs")
    event_name_set = set(event_names)
    for asset in primitive.assets:
        if asset.event_name not in event_name_set:
            findings.append(f"{prefix}: asset {asset.binding_id} references unknown event")
        if asset.asset_type not in ASSET_TYPE_WIRE_NAMES:
            findings.append(f"{prefix}: asset {asset.binding_id} has unsupported type {asset.asset_type}")
        expected_kind = {"AudioClip": "Audio", "Particle": "Vfx"}.get(asset.asset_type)
        if expected_kind is not None and asset.playback_kind != expected_kind:
            findings.append(f"{prefix}: asset {asset.binding_id} playback kind/type mismatch")
        expected_action = {"Audio": "play", "Vfx": "spawn"}.get(asset.playback_kind)
        if expected_action is not None and asset.semantic_action != expected_action:
            findings.append(f"{prefix}: asset {asset.binding_id} semantic action mismatch")
        if asset.priority < 0:
            findings.append(f"{prefix}: asset {asset.binding_id} priority must be non-negative")

    facet_component_ids = primitive.save.component_type_ids + primitive.network.component_type_ids
    if not primitive.save.component_type_ids:
        findings.append(f"{prefix}: save facet must reference components")
    if not primitive.network.component_type_ids:
        findings.append(f"{prefix}: network facet must reference components")
    for label, type_ids in (
        ("save", primitive.save.component_type_ids),
        ("network", primitive.network.component_type_ids),
    ):
        if tuple(sorted(set(type_ids))) != type_ids:
            findings.append(f"{prefix}: {label} component type IDs must be sorted and unique")
    for type_id in facet_component_ids:
        if type_id not in declared:
            findings.append(f"{prefix}: facet references undeclared component {type_id}")
    if primitive.save.strategy != "component_snapshot":
        findings.append(f"{prefix}: unsupported save strategy {primitive.save.strategy}")
    if primitive.save.save_layer not in {"Session", "Progress", "World"}:
        findings.append(f"{prefix}: unsupported save layer {primitive.save.save_layer}")
    if primitive.network.authority not in {"Local", "Owner", "Host", "Server"}:
        findings.append(f"{prefix}: unsupported network authority {primitive.network.authority}")
    if primitive.network.replication_mode not in {
        "None", "ServerOnly", "Unreliable", "Reliable", "OwnerOnly",
    }:
        findings.append(
            f"{prefix}: unsupported replication mode {primitive.network.replication_mode}"
        )
    return findings


def _validate_systems(
    prefix: str,
    systems: tuple[SystemPrimitive, ...],
    declared_components: set[int],
) -> list[str]:
    findings: list[str] = []
    system_ids = [system.system_id for system in systems]
    if len(system_ids) != len(set(system_ids)):
        findings.append(f"{prefix}: duplicate system IDs")
    seen: set[str] = set()
    for index, system in enumerate(systems):
        if system.system_id not in RUNTIME_SYSTEM_IDS:
            findings.append(f"{prefix}: no built-in runtime executor for {system.system_id}")
        else:
            expected_phase, expected_reads, expected_writes = RUNTIME_SYSTEM_CONTRACTS[
                system.system_id
            ]
            if system.phase != expected_phase:
                findings.append(
                    f"{prefix}: {system.system_id} phase must be {expected_phase}"
                )
            if system.reads != expected_reads:
                findings.append(
                    f"{prefix}: {system.system_id} reads must match runtime {expected_reads}"
                )
            if system.writes != expected_writes:
                findings.append(
                    f"{prefix}: {system.system_id} writes must match runtime {expected_writes}"
                )
        for field_name, values in (("reads", system.reads), ("writes", system.writes)):
            if tuple(sorted(set(values))) != values:
                findings.append(f"{prefix}: {system.system_id} {field_name} must be sorted and unique")
            unknown = sorted(set(values) - declared_components)
            if unknown:
                findings.append(f"{prefix}: {system.system_id} {field_name} undeclared {unknown}")
        if index > 0 and not system.depends_on:
            findings.append(f"{prefix}: {system.system_id} must declare an explicit dependency")
        for dependency in system.depends_on:
            if dependency not in seen:
                findings.append(
                    f"{prefix}: {system.system_id} dependency {dependency} must precede it"
                )
        seen.add(system.system_id)
    return findings


def _float_paths(value: Any, path: str = "defaults") -> list[str]:
    if isinstance(value, float):
        return [path]
    if isinstance(value, Mapping):
        paths: list[str] = []
        for key in sorted(value):
            paths.extend(_float_paths(value[key], f"{path}.{key}"))
        return paths
    if isinstance(value, (list, tuple)):
        paths = []
        for index, item in enumerate(value):
            paths.extend(_float_paths(item, f"{path}[{index}]"))
        return paths
    return []


def _component_schema(component: ComponentPrimitive) -> dict[str, Any]:
    return {
        "type_id": component.type_id,
        "name": component.name,
        "defaults": copy.deepcopy(dict(component.defaults)),
        "source": component.source,
    }


def _system_record(system: SystemPrimitive) -> dict[str, Any]:
    return {
        "id": system.system_id,
        "phase": system.phase,
        "reads": list(system.reads),
        "writes": list(system.writes),
        "depends_on": list(system.depends_on),
        "deterministic": True,
        "parallel": False,
    }


def _asset_binding(asset: AssetPrimitive) -> dict[str, Any]:
    return {
        "binding_id": asset.binding_id,
        "event_name": asset.event_name,
        "playback_kind": asset.playback_kind,
        "asset": {
            "id": asset.asset_id,
            "asset_type": asset.asset_type,
            "status": "Placeholder",
        },
        "semantic_action": asset.semantic_action,
        "entity_selector": "SourceEntity",
        "parameters": {},
        "priority": asset.priority,
    }


def build_primitive_cgs(primitive: GameplayPrimitive) -> dict[str, Any]:
    findings = _validate_primitive(primitive.primitive_id, primitive)
    if findings:
        raise ValueError("invalid gameplay primitive: " + "; ".join(findings))
    components = [_component_schema(component) for component in primitive.components]
    cgs: dict[str, Any] = {
        "format": "xace.cgs.export",
        "format_version": "1.0.0",
        "metadata": {
            "name": primitive.display_name,
            "version": primitive.version,
            "schema_version": "0.1.0",
            "execution_plan_version": 1,
            "primitive_id": primitive.primitive_id,
            "primitive_genres": list(primitive.genres),
            "primitive_facets": list(primitive.facets),
        },
        "component_schemas": components,
        "global_systems": [_system_record(system) for system in primitive.systems],
        "semantic_events": [
            {"name": event.name, "required_payload_keys": list(event.required_payload_keys)}
            for event in primitive.events
        ],
        "input_bindings": [
            {
                "action": input_item.action,
                "kind": input_item.kind,
                "phase": input_item.phase,
                "target_field": input_item.target_field,
            }
            for input_item in primitive.inputs
        ],
        "semantic_bindings": {
            "bindings": [_asset_binding(asset) for asset in primitive.assets],
        },
        "assets": [
            {
                "id": asset.asset_id,
                "asset_type": ASSET_TYPE_WIRE_NAMES[asset.asset_type],
                "status": "PLACEHOLDER",
            }
            for asset in primitive.assets
        ],
        "save_contract": {
            "component_type_ids": list(primitive.save.component_type_ids),
            "strategy": primitive.save.strategy,
            "save_layer": primitive.save.save_layer,
            "scope": "deterministic_component_state",
        },
        "network_contract": {
            "component_type_ids": list(primitive.network.component_type_ids),
            "authority": primitive.network.authority,
            "replication_mode": primitive.network.replication_mode,
            "prediction_enabled": primitive.network.prediction_enabled,
            "scope": "declarative_policy",
        },
        "modes": [{
            "id": "default",
            "schema_version": "0.1.0",
            "is_default": True,
            "actors": [{
                "id": primitive.primitive_id.replace(".", "_") + "_actor",
                "spawn_count": 1,
                "components": [
                    {key: copy.deepcopy(value) for key, value in component.items() if key != "source"}
                    for component in components
                ],
            }],
            "systems": [],
            "rules": [],
        }],
    }
    cgs["metadata"]["cgs_hash"] = committed_cgs_hash(cgs)
    return cgs


def committed_cgs_hash(cgs: Mapping[str, Any]) -> str:
    stripped = copy.deepcopy(dict(cgs))
    metadata = stripped.get("metadata")
    if isinstance(metadata, dict):
        metadata.pop("cgs_hash", None)
    canonical = json.dumps(
        stripped, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
