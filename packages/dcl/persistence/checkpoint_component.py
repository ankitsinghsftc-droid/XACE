"""COMP_CHECKPOINT_V1 schema owner."""

from __future__ import annotations

from enum import Enum
from math import isfinite
from typing import Any, Mapping

from ..dcl_registry import ComponentDefinition, ComponentFieldDefinition, ComponentLayer

TYPE_ID = 361
TYPE_NAME = "COMP_CHECKPOINT_V1"
DOMAIN = "persistence"


class CheckpointType(str, Enum):
    MANUAL = "MANUAL"
    AUTO = "AUTO"
    STORY = "STORY"
    RESPAWN = "RESPAWN"


def build_definition() -> ComponentDefinition:
    return ComponentDefinition(
        type_id=TYPE_ID,
        type_name=TYPE_NAME,
        layer=ComponentLayer.DCL,
        domain=DOMAIN,
        version=1,
        description="Checkpoint metadata for save triggers and respawn restoration.",
        fields=[
            ComponentFieldDefinition("checkpoint_type", "enum", False, '"MANUAL"', "MANUAL|AUTO|STORY|RESPAWN."),
            ComponentFieldDefinition("world_state_hash", "str", False, '""', "World hash captured at checkpoint creation."),
            ComponentFieldDefinition("respawn_position", "struct", False, None, "Vec3 respawn world position."),
            ComponentFieldDefinition("activation_tick", "u64", False, "0", "Tick when checkpoint activated."),
            ComponentFieldDefinition("is_activated", "bool", False, "false", "True once checkpoint is available."),
            ComponentFieldDefinition("triggers_autosave", "bool", False, "true", "Whether activation requests autosave."),
        ],
    )


def default_payload() -> dict[str, Any]:
    return {
        "checkpoint_type": CheckpointType.MANUAL.value,
        "world_state_hash": "",
        "respawn_position": {"x": 0.0, "y": 0.0, "z": 0.0},
        "activation_tick": 0,
        "is_activated": False,
        "triggers_autosave": True,
    }


def validate_payload(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, Mapping):
        return ["payload must be a mapping"]
    if _normalise_checkpoint_type(payload.get("checkpoint_type", CheckpointType.MANUAL.value)) is None:
        errors.append("checkpoint_type is not valid")
    world_hash = payload.get("world_state_hash", "")
    if not isinstance(world_hash, str):
        errors.append("world_state_hash must be a string")
    if not _is_vec3(payload.get("respawn_position", {"x": 0, "y": 0, "z": 0})):
        errors.append("respawn_position must be a finite Vec3")
    if not isinstance(payload.get("activation_tick", 0), int) or int(payload.get("activation_tick", 0)) < 0:
        errors.append("activation_tick must be a non-negative integer")
    if not isinstance(payload.get("is_activated", False), bool):
        errors.append("is_activated must be boolean")
    if not isinstance(payload.get("triggers_autosave", True), bool):
        errors.append("triggers_autosave must be boolean")
    return errors


def normalise_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise TypeError("payload must be a mapping")
    data = default_payload()
    data.update(dict(payload))
    checkpoint_type = _normalise_checkpoint_type(data["checkpoint_type"])
    if checkpoint_type is None:
        raise ValueError("checkpoint_type is not valid")
    if not _is_vec3(data["respawn_position"]):
        raise ValueError("respawn_position must be a finite Vec3")
    data["checkpoint_type"] = checkpoint_type
    data["world_state_hash"] = str(data["world_state_hash"]).strip()
    data["respawn_position"] = {axis: float(data["respawn_position"].get(axis, 0.0)) for axis in ("x", "y", "z")}
    data["activation_tick"] = int(data["activation_tick"])
    if data["activation_tick"] < 0:
        raise ValueError("activation_tick must be a non-negative integer")
    data["is_activated"] = _normalise_bool(data["is_activated"], "is_activated")
    data["triggers_autosave"] = _normalise_bool(data["triggers_autosave"], "triggers_autosave")
    return data


def _is_vec3(value: Any) -> bool:
    return isinstance(value, Mapping) and all(axis in value and isinstance(value[axis], (int, float)) and isfinite(float(value[axis])) for axis in ("x", "y", "z"))


def _normalise_checkpoint_type(value: Any) -> str | None:
    text = str(value).strip()
    if not text:
        return None
    aliases = {item.value: item.value for item in CheckpointType}
    aliases.update({item.value.title(): item.value for item in CheckpointType})
    aliases.update({item.value.lower(): item.value for item in CheckpointType})
    return aliases.get(text)


def _normalise_bool(value: Any, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes", "on"}:
            return True
        if text in {"false", "0", "no", "off"}:
            return False
    raise ValueError(f"{field_name} must be boolean")
