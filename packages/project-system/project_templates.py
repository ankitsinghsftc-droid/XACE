"""
project_templates.py - starter template catalog and CGS generation.

Templates here are intentionally gameplay-general. They create small playable
or inspectable worlds using current runtime systems, while keeping rendering,
terrain, materials, audio, and editor-native work owned by the selected engine.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any


SCHEMA_VERSION = "0.1.0"


@dataclass(frozen=True)
class TemplateDefinition:
    template_id: str
    label: str
    description: str
    recommended_engines: tuple[str, ...]
    domains: tuple[str, ...]
    playable: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "label": self.label,
            "description": self.description,
            "recommended_engines": list(self.recommended_engines),
            "domains": list(self.domains),
            "playable": self.playable,
        }


_TEMPLATES: tuple[TemplateDefinition, ...] = (
    TemplateDefinition(
        "blank_3d",
        "Blank 3D",
        "One controllable player in an empty bounded world.",
        ("godot", "unity", "unreal", "headless"),
        ("world", "character"),
        True,
    ),
    TemplateDefinition(
        "top_down_adventure",
        "Top-down Adventure",
        "Player movement, camera-friendly bounds, and one collectible object.",
        ("godot", "unity", "unreal"),
        ("world", "character", "interaction", "rpg"),
        True,
    ),
    TemplateDefinition(
        "fps_prototype",
        "FPS Prototype",
        "First-person movement starter with generic interactable target.",
        ("godot", "unity", "unreal"),
        ("world", "character", "interaction"),
        True,
    ),
    TemplateDefinition(
        "third_person",
        "Third-person",
        "Third-person movement starter with a follow-camera intent in metadata.",
        ("godot", "unity", "unreal"),
        ("world", "character", "camera"),
        True,
    ),
    TemplateDefinition(
        "rpg",
        "RPG",
        "Movement plus general inventory, item pickup, and interaction systems.",
        ("godot", "unity", "unreal"),
        ("world", "character", "interaction", "rpg", "persistence"),
        True,
    ),
    TemplateDefinition(
        "horror_chase",
        "Horror Chase",
        "Player movement with one generic chasing enemy and health loop.",
        ("godot", "unity", "unreal"),
        ("world", "character", "ai", "combat"),
        True,
    ),
    TemplateDefinition(
        "action_combat",
        "Action Combat",
        "Generic close-combat starter structure without weapon-specific rules.",
        ("godot", "unity", "unreal"),
        ("world", "character", "interaction", "combat", "rpg"),
        True,
    ),
    TemplateDefinition(
        "multiplayer_lobby",
        "Multiplayer Lobby",
        "Local starter lobby shape for future session/network product wiring.",
        ("godot", "unity", "unreal", "headless"),
        ("world", "character", "network"),
        False,
    ),
)

_ALIASES = {
    "empty": "blank_3d",
    "blank": "blank_3d",
    "top_down": "top_down_adventure",
    "fps": "fps_prototype",
    "horror": "horror_chase",
    "zombie_chase": "horror_chase",
    "sword_combat": "action_combat",
}


def list_templates() -> list[TemplateDefinition]:
    return list(_TEMPLATES)


def list_template_ids(include_aliases: bool = False) -> list[str]:
    ids = [template.template_id for template in _TEMPLATES]
    if include_aliases:
        ids.extend(sorted(_ALIASES))
    return ids


def get_template(template_id: str) -> TemplateDefinition:
    canonical = canonical_template_id(template_id)
    for template in _TEMPLATES:
        if template.template_id == canonical:
            return template
    raise ValueError(f"unknown template: {template_id}")


def canonical_template_id(template_id: str) -> str:
    key = template_id.strip().lower()
    return _ALIASES.get(key, key)


def make_template(template_id: str, name: str) -> dict[str, Any]:
    canonical = canonical_template_id(template_id)
    template = get_template(canonical)
    cgs = _base_cgs(name, template)
    mode = cgs["modes"][0]

    if canonical == "blank_3d":
        mode["actors"].append(player_actor(camera_mode="orbit"))
        mode["systems"].append(system("MovementSystem", "Simulation", [1, 5], [1], ["InputSystem"]))
    elif canonical in {"top_down_adventure", "fps_prototype", "third_person"}:
        camera = {
            "top_down_adventure": "top_down",
            "fps_prototype": "first_person",
            "third_person": "third_person",
        }[canonical]
        mode["actors"].append(player_actor(camera_mode=camera))
        mode["actors"].append(generic_pickup_actor("actor_pickup_01", "Sample Object", 3.0, 0.0))
        mode["systems"].extend([
            system("MovementSystem", "Simulation", [1, 5], [1], ["InputSystem"]),
            system("InteractionSystem", "Simulation", [1, 2, 6, 260], [6, 260], ["MovementSystem"]),
        ])
    elif canonical == "rpg":
        mode["actors"].append(player_actor(camera_mode="third_person", inventory=True))
        mode["actors"].append(generic_pickup_actor("actor_item_01", "Starter Item", 2.0, 0.0))
        mode["systems"].extend([
            system("MovementSystem", "Simulation", [1, 5], [1], ["InputSystem"]),
            system("InteractionSystem", "Simulation", [1, 2, 6, 260], [6, 260], ["MovementSystem"]),
            system("InventorySystem", "Simulation", [1, 2, 6, 201, 205, 260], [1, 6, 201, 205, 260], ["InteractionSystem"]),
        ])
    elif canonical == "horror_chase":
        mode["actors"].append(player_actor(camera_mode="third_person", health=100.0))
        mode["actors"].append(ai_actor("actor_enemy_01", "Chaser", 5.0, 5.0))
        mode["systems"].extend(chase_systems())
        mode["rules"].extend(death_rules("actor_player", "actor_enemy_01"))
    elif canonical == "action_combat":
        mode["actors"].append(player_actor(camera_mode="third_person", inventory=True, health=100.0))
        mode["actors"].append(generic_pickup_actor("actor_tool_01", "Training Tool", 2.0, 1.0))
        mode["actors"].append(ai_actor("actor_training_target", "Training Target", 6.0, 0.0, speed=0.0))
        mode["systems"].extend([
            system("MovementSystem", "Simulation", [1, 5], [1], ["InputSystem"]),
            system("InteractionSystem", "Simulation", [1, 2, 6, 260], [6, 260], ["MovementSystem"]),
            system("InventorySystem", "Simulation", [1, 2, 6, 201, 205, 260], [1, 6, 201, 205, 260], ["InteractionSystem"]),
            system("DamageSystem", "Simulation", [100, 101], [100, 101], ["InventorySystem"]),
            system("DeathSystem", "PostSimulation", [100], [], ["DamageSystem"]),
        ])
    elif canonical == "multiplayer_lobby":
        mode["actors"].append(player_actor("actor_player_1", "Player One", -1.5, 0.0, camera_mode="third_person"))
        mode["actors"].append(player_actor("actor_player_2", "Player Two", 1.5, 0.0, camera_mode="third_person"))
        mode["systems"].append(system("MovementSystem", "Simulation", [1, 5], [1], ["InputSystem"]))
        cgs["metadata"]["networking"] = {
            "mode": "lobby",
            "authority": "host",
            "max_players": 4,
            "status": "template_metadata_only",
        }
    else:
        raise ValueError(f"unknown template: {template_id}")

    cgs["metadata"]["cgs_hash"] = stable_cgs_hash(cgs)
    return cgs


def stable_cgs_hash(cgs: dict[str, Any]) -> str:
    """Return the canonical lowercase SHA-256 CGS digest, 64 hex chars."""
    stripped = copy.deepcopy(cgs)
    stripped.setdefault("metadata", {}).pop("cgs_hash", None)
    canonical = json.dumps(stripped, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def slug_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in name.strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or "XACE_Project"


def _base_cgs(name: str, template: TemplateDefinition) -> dict[str, Any]:
    return {
        "metadata": {
            "name": slug_name(name),
            "cgs_hash": "",
            "version": SCHEMA_VERSION,
            "schema_version": SCHEMA_VERSION,
            "description": template.description,
            "template_id": template.template_id,
            "domains": list(template.domains),
            "engine_boundary": {
                "xace_owns": ["rules", "schemas", "events", "runtime", "saves", "networking", "semantic_bindings"],
                "engine_owns": ["rendering", "lighting", "terrain", "materials", "animation_playback", "audio_playback"],
            },
        },
        "global_systems": [
            system("InputSystem", "Input", [6], [5]),
            system("SaveSystem", "PostSimulation", [1, 100], []),
        ],
        "modes": [
            {
                "id": "mode_gameplay",
                "schema_version": SCHEMA_VERSION,
                "is_default": True,
                "actors": [],
                "systems": [],
                "rules": [],
            }
        ],
    }


def system(
    system_id: str,
    phase: str,
    reads: list[int],
    writes: list[int],
    depends_on: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": system_id,
        "phase": phase,
        "reads": reads,
        "writes": writes,
        "depends_on": depends_on or [],
        "deterministic": True,
    }


def player_actor(
    actor_id: str = "actor_player",
    display_name: str = "Player",
    x: float = 0.0,
    z: float = 0.0,
    *,
    camera_mode: str = "third_person",
    inventory: bool = False,
    health: float = 100.0,
) -> dict[str, Any]:
    components = [
        component(1, "COMP_TRANSFORM_V1", transform_defaults(x, z)),
        component(5, "COMP_VELOCITY_V1", velocity_defaults(5.0)),
        component(6, "COMP_INPUT_V1", input_defaults(camera_mode)),
        component(100, "COMP_HEALTH_V1", health_defaults(health)),
        component(2, "COMP_IDENTITY_V1", identity_defaults(display_name)),
    ]
    if inventory:
        components.append(component(201, "COMP_INVENTORY_V1", inventory_defaults()))
    return {
        "id": actor_id,
        "actor_type": "PlayerCharacter",
        "control_type": "Human",
        "components": components,
    }


def ai_actor(
    actor_id: str,
    display_name: str,
    x: float,
    z: float,
    *,
    speed: float = 3.5,
) -> dict[str, Any]:
    return {
        "id": actor_id,
        "actor_type": "Agent",
        "control_type": "AiProxy",
        "components": [
            component(1, "COMP_TRANSFORM_V1", transform_defaults(x, z, bounds=False)),
            component(5, "COMP_VELOCITY_V1", velocity_defaults(speed)),
            component(100, "COMP_HEALTH_V1", health_defaults(30.0)),
            component(2, "COMP_IDENTITY_V1", identity_defaults(display_name)),
            component(160, "COMP_AI_V1", {
                "behavior_model": "CHASE" if speed > 0.0 else "IDLE",
                "detection_radius": 20.0,
                "attack_range": 1.5,
                "attack_damage": 10.0,
                "attack_cooldown": 1.0,
                "speed": speed,
            }),
        ],
    }


def generic_pickup_actor(actor_id: str, display_name: str, x: float, z: float) -> dict[str, Any]:
    return {
        "id": actor_id,
        "actor_type": "Item",
        "control_type": "WorldObject",
        "components": [
            component(1, "COMP_TRANSFORM_V1", transform_defaults(x, z, bounds=False)),
            component(2, "COMP_IDENTITY_V1", identity_defaults(display_name)),
            component(205, "COMP_ITEM_V1", {
                "item_id": actor_id,
                "display_name": display_name,
                "quantity": 1,
                "slot_type": "generic",
                "weight": 1.0,
                "is_pickable": True,
                "owner_entity_id": 0,
                "inventory_slot_id": "",
                "is_equipped": False,
                "is_in_world": True,
            }),
            component(260, "COMP_INTERACTION_V1", {
                "is_interactable": True,
                "interaction_type": "PickUp",
                "prompt_text": f"Pick up {display_name}",
                "range": 2.0,
                "interaction_count": 0,
                "max_interactions": 0,
            }),
        ],
    }


def chase_systems() -> list[dict[str, Any]]:
    return [
        system("MovementSystem", "Simulation", [1, 5], [1], ["InputSystem"]),
        system("AISystem", "Simulation", [160, 1], [5, 101], ["MovementSystem"]),
        system("DamageSystem", "Simulation", [101, 100], [100, 101], ["AISystem"]),
        system("DeathSystem", "PostSimulation", [100], [], ["DamageSystem"]),
    ]


def death_rules(player_id: str, enemy_id: str) -> list[dict[str, Any]]:
    return [
        {
            "id": "rule_player_death",
            "condition": f"{player_id}.COMP_HEALTH_V1.current <= 0",
            "effect": "game_over(reason='player_died')",
            "priority": 1,
            "is_active": True,
        },
        {
            "id": "rule_enemy_death",
            "condition": f"{enemy_id}.COMP_HEALTH_V1.current <= 0",
            "effect": f"destroy_actor({enemy_id})",
            "priority": 2,
            "is_active": True,
        },
    ]


def component(type_id: int, name: str, defaults: dict[str, Any]) -> dict[str, Any]:
    return {"type_id": type_id, "name": name, "defaults": defaults}


def transform_defaults(x: float, z: float, *, bounds: bool = True) -> dict[str, Any]:
    data = {
        "position_x": x,
        "position_y": 0.0,
        "position_z": z,
        "rotation_y": 0.0,
    }
    if bounds:
        data.update({
            "bounds_min_x": -12.0,
            "bounds_max_x": 12.0,
            "bounds_min_z": -12.0,
            "bounds_max_z": 12.0,
        })
    return data


def velocity_defaults(speed: float) -> dict[str, Any]:
    return {
        "max_linear_speed": speed,
        "max_angular_speed": 360.0,
        "linear_x": 0.0,
        "linear_y": 0.0,
        "linear_z": 0.0,
    }


def input_defaults(camera_mode: str) -> dict[str, Any]:
    return {
        "move_x": 0.0,
        "move_z": 0.0,
        "camera_mode": camera_mode,
        "action_map": {
            "MoveForward": ["W", "Up"],
            "MoveBack": ["S", "Down"],
            "MoveLeft": ["A", "Left"],
            "MoveRight": ["D", "Right"],
            "Interact": ["E"],
            "Pickup": ["E"],
            "Attack": ["MouseLeft", "Ctrl"],
            "Dash": ["Shift"],
        },
    }


def health_defaults(health: float) -> dict[str, Any]:
    return {
        "current": health,
        "max": health,
        "regen_rate": 0.0,
        "is_invincible": False,
    }


def identity_defaults(display_name: str) -> dict[str, Any]:
    key = slug_name(display_name).lower()
    return {
        "name": display_name,
        "mesh_id": f"{key}_mesh",
        "mesh_id_path": "",
    }


def inventory_defaults() -> dict[str, Any]:
    return {
        "slots": [],
        "max_capacity": 20,
        "current_count": 0,
        "weight_current": 0.0,
        "weight_max": 50.0,
        "equipped_slot_id": "",
        "equipped_item_entity_id": 0,
    }
