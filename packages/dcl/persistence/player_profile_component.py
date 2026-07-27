"""COMP_PLAYER_PROFILE_V1 schema owner."""

from __future__ import annotations

from math import isfinite
from typing import Any, Mapping

from ..dcl_registry import ComponentDefinition, ComponentFieldDefinition, ComponentLayer

TYPE_ID = 362
TYPE_NAME = "COMP_PLAYER_PROFILE_V1"
DOMAIN = "persistence"


def build_definition() -> ComponentDefinition:
    return ComponentDefinition(
        type_id=TYPE_ID,
        type_name=TYPE_NAME,
        layer=ComponentLayer.DCL,
        domain=DOMAIN,
        version=1,
        description="Cross-session profile data: display name, achievements, settings, and total play time.",
        fields=[
            ComponentFieldDefinition("profile_id", "str", True, None, "Stable profile identifier."),
            ComponentFieldDefinition("display_name", "str", False, '"Player"', "Player-facing display name."),
            ComponentFieldDefinition("achievements", "list", False, "[]", "Sorted achievement id list."),
            ComponentFieldDefinition("settings", "dict", False, "{}", "Deterministically keyed player settings."),
            ComponentFieldDefinition("total_play_time", "u64", False, "0", "Lifetime play time in deterministic ticks."),
            ComponentFieldDefinition("last_played_slot_id", "str", False, '""', "Most recently used save slot."),
            ComponentFieldDefinition("statistics", "dict", False, "{}", "Deterministically keyed profile statistics."),
        ],
    )


def default_payload(profile_id: str = "") -> dict[str, Any]:
    return {
        "profile_id": profile_id,
        "display_name": "Player",
        "achievements": [],
        "settings": {},
        "total_play_time": 0,
        "last_played_slot_id": "",
        "statistics": {},
    }


def validate_payload(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, Mapping):
        return ["payload must be a mapping"]
    if not isinstance(payload.get("profile_id"), str) or not payload.get("profile_id", "").strip():
        errors.append("profile_id must be a non-empty string")
    if not isinstance(payload.get("display_name", "Player"), str):
        errors.append("display_name must be a string")
    achievements = payload.get("achievements", [])
    if not isinstance(achievements, list) or not all(isinstance(item, str) and item for item in achievements):
        errors.append("achievements must be a list of non-empty strings")
    elif achievements != sorted(set(achievements)):
        errors.append("achievements must be sorted ascending with no duplicates")
    settings = payload.get("settings", {})
    errors.extend(_validate_string_keyed_json_map(settings, "settings"))
    if not isinstance(payload.get("total_play_time", 0), int) or int(payload.get("total_play_time", 0)) < 0:
        errors.append("total_play_time must be a non-negative integer")
    if not isinstance(payload.get("last_played_slot_id", ""), str):
        errors.append("last_played_slot_id must be a string")
    errors.extend(_validate_string_keyed_json_map(payload.get("statistics", {}), "statistics"))
    return errors


def normalise_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise TypeError("payload must be a mapping")
    data = default_payload()
    data.update(dict(payload))
    data["profile_id"] = str(data["profile_id"]).strip()
    data["display_name"] = str(data.get("display_name", "Player")).strip() or "Player"
    data["achievements"] = sorted(set(str(item) for item in data.get("achievements", []) if str(item)))
    data["settings"] = _normalise_string_keyed_map(data.get("settings", {}), "settings")
    data["total_play_time"] = int(data["total_play_time"])
    if data["total_play_time"] < 0:
        raise ValueError("total_play_time must be a non-negative integer")
    data["last_played_slot_id"] = str(data.get("last_played_slot_id", "")).strip()
    data["statistics"] = _normalise_string_keyed_map(data.get("statistics", {}), "statistics")
    return data


def _validate_string_keyed_json_map(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, Mapping):
        return [f"{field_name} must be a mapping with non-empty string keys"]
    if not all(isinstance(key, str) and key for key in value):
        return [f"{field_name} must use non-empty string keys"]
    if list(value.keys()) != sorted(value.keys()):
        return [f"{field_name} keys must be sorted ascending"]
    for key, item in value.items():
        if not _is_json_scalar_or_collection(item):
            return [f"{field_name}.{key} must be JSON-serializable"]
    return []


def _normalise_string_keyed_map(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping")
    normalised = {str(key): value[key] for key in sorted(value.keys()) if str(key)}
    for key, item in normalised.items():
        if not _is_json_scalar_or_collection(item):
            raise ValueError(f"{field_name}.{key} must be JSON-serializable")
    return normalised


def _is_json_scalar_or_collection(value: Any) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return isfinite(value)
    if isinstance(value, list):
        return all(_is_json_scalar_or_collection(item) for item in value)
    if isinstance(value, Mapping):
        return all(isinstance(key, str) and _is_json_scalar_or_collection(item) for key, item in value.items())
    return False
