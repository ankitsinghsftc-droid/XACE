"""COMP_SAVE_SLOT_V1 schema owner."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from ..dcl_registry import ComponentDefinition, ComponentFieldDefinition, ComponentLayer

TYPE_ID = 360
TYPE_NAME = "COMP_SAVE_SLOT_V1"
DOMAIN = "persistence"


def build_definition() -> ComponentDefinition:
    return ComponentDefinition(
        type_id=TYPE_ID,
        type_name=TYPE_NAME,
        layer=ComponentLayer.DCL,
        domain=DOMAIN,
        version=1,
        description="Save slot metadata with schema version for deterministic migration.",
        fields=[
            ComponentFieldDefinition("slot_id", "str", True, None, "Stable save slot identifier."),
            ComponentFieldDefinition("schema_version", "str", True, None, "Schema version this save was written with."),
            ComponentFieldDefinition("created_at", "str", True, None, "UTC ISO-8601 creation timestamp."),
            ComponentFieldDefinition("last_played", "str", False, '""', "UTC ISO-8601 timestamp for last load/save."),
            ComponentFieldDefinition("play_time_ticks", "u64", False, "0", "Accumulated play time in deterministic simulation ticks."),
            ComponentFieldDefinition("display_name", "str", False, '"Save Slot"', "Human-readable slot label."),
            ComponentFieldDefinition("is_autosave", "bool", False, "false", "True when the slot was produced by autosave."),
        ],
    )


def default_payload(slot_id: str = "", schema_version: str = "") -> dict[str, Any]:
    now = _utc_now()
    return {
        "slot_id": slot_id,
        "schema_version": schema_version,
        "created_at": now,
        "last_played": now,
        "play_time_ticks": 0,
        "display_name": "Save Slot",
        "is_autosave": False,
    }


def validate_payload(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, Mapping):
        return ["payload must be a mapping"]
    if not _non_empty_string(payload.get("slot_id")):
        errors.append("slot_id must be a non-empty string")
    if not _non_empty_string(payload.get("schema_version")):
        errors.append("schema_version must be a non-empty string")
    if not _iso_datetime(payload.get("created_at")):
        errors.append("created_at must be an ISO-8601 datetime string")
    last_played = payload.get("last_played", "")
    if last_played not in ("", None) and not _iso_datetime(last_played):
        errors.append("last_played must be empty or an ISO-8601 datetime string")
    if not isinstance(payload.get("play_time_ticks", 0), int) or int(payload.get("play_time_ticks", 0)) < 0:
        errors.append("play_time_ticks must be a non-negative integer")
    if not isinstance(payload.get("is_autosave", False), bool):
        errors.append("is_autosave must be boolean")
    if not isinstance(payload.get("display_name", "Save Slot"), str):
        errors.append("display_name must be a string")
    return errors


def normalise_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise TypeError("payload must be a mapping")
    data = default_payload()
    data.update(dict(payload))
    data["slot_id"] = str(data["slot_id"]).strip()
    data["schema_version"] = str(data["schema_version"]).strip()
    data["created_at"] = _normalise_datetime(data["created_at"])
    data["last_played"] = _normalise_datetime(data["last_played"]) if data.get("last_played") else ""
    data["play_time_ticks"] = int(data["play_time_ticks"])
    data["display_name"] = str(data.get("display_name", "Save Slot")).strip() or "Save Slot"
    data["is_autosave"] = _normalise_bool(data["is_autosave"], "is_autosave")
    return data


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalise_datetime(value: Any) -> str:
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _iso_datetime(value: Any) -> bool:
    try:
        _normalise_datetime(value)
        return True
    except (TypeError, ValueError):
        return False


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


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
