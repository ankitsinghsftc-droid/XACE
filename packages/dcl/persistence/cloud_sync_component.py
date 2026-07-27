"""COMP_CLOUD_SYNC_V1 schema owner."""

from __future__ import annotations

from enum import Enum
from typing import Any, Mapping

from ..dcl_registry import ComponentDefinition, ComponentFieldDefinition, ComponentLayer

TYPE_ID = 363
TYPE_NAME = "COMP_CLOUD_SYNC_V1"
DOMAIN = "persistence"


class CloudProvider(str, Enum):
    STEAM = "STEAM"
    EPIC = "EPIC"
    PSN = "PSN"
    XBOX = "XBOX"
    CUSTOM = "CUSTOM"
    NONE = "NONE"


class SyncState(str, Enum):
    IDLE = "IDLE"
    UPLOADING = "UPLOADING"
    DOWNLOADING = "DOWNLOADING"
    CONFLICT = "CONFLICT"
    ERROR = "ERROR"
    SYNCED = "SYNCED"


def build_definition() -> ComponentDefinition:
    return ComponentDefinition(
        type_id=TYPE_ID,
        type_name=TYPE_NAME,
        layer=ComponentLayer.DCL,
        domain=DOMAIN,
        version=1,
        description="Cloud save sync metadata and provider state.",
        fields=[
            ComponentFieldDefinition("provider", "enum", False, '"NONE"', "STEAM|EPIC|PSN|XBOX|CUSTOM|NONE."),
            ComponentFieldDefinition("last_sync_tick", "u64", False, "0", "Last successful sync tick."),
            ComponentFieldDefinition("sync_state", "enum", False, '"IDLE"', "IDLE|UPLOADING|DOWNLOADING|CONFLICT|ERROR|SYNCED."),
            ComponentFieldDefinition("remote_revision", "str", False, '""', "Provider-specific remote revision id."),
            ComponentFieldDefinition("auto_sync", "bool", False, "true", "Whether cloud sync may run automatically."),
            ComponentFieldDefinition("last_error", "str", False, '""', "Last provider error message, if any."),
        ],
    )


def default_payload() -> dict[str, Any]:
    return {
        "provider": CloudProvider.NONE.value,
        "last_sync_tick": 0,
        "sync_state": SyncState.IDLE.value,
        "remote_revision": "",
        "auto_sync": True,
        "last_error": "",
    }


def validate_payload(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, Mapping):
        return ["payload must be a mapping"]
    if _normalise_enum(payload.get("provider", CloudProvider.NONE.value), CloudProvider) is None:
        errors.append("provider is not a valid CloudProvider")
    if not isinstance(payload.get("last_sync_tick", 0), int) or int(payload.get("last_sync_tick", 0)) < 0:
        errors.append("last_sync_tick must be a non-negative integer")
    if _normalise_enum(payload.get("sync_state", SyncState.IDLE.value), SyncState) is None:
        errors.append("sync_state is not a valid SyncState")
    if not isinstance(payload.get("remote_revision", ""), str):
        errors.append("remote_revision must be a string")
    if not isinstance(payload.get("auto_sync", True), bool):
        errors.append("auto_sync must be boolean")
    if not isinstance(payload.get("last_error", ""), str):
        errors.append("last_error must be a string")
    return errors


def normalise_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise TypeError("payload must be a mapping")
    data = default_payload()
    data.update(dict(payload))
    provider = _normalise_enum(data["provider"], CloudProvider)
    if provider is None:
        raise ValueError("provider is not a valid CloudProvider")
    state = _normalise_enum(data["sync_state"], SyncState)
    if state is None:
        raise ValueError("sync_state is not a valid SyncState")
    data["provider"] = provider
    data["last_sync_tick"] = int(data["last_sync_tick"])
    if data["last_sync_tick"] < 0:
        raise ValueError("last_sync_tick must be a non-negative integer")
    data["sync_state"] = state
    data["remote_revision"] = str(data["remote_revision"]).strip()
    data["auto_sync"] = _normalise_bool(data["auto_sync"], "auto_sync")
    data["last_error"] = str(data["last_error"])
    return data


def _normalise_enum(value: Any, enum_type: type[Enum]) -> str | None:
    text = str(value).strip()
    if not text:
        return None
    aliases = {item.value: item.value for item in enum_type}
    aliases.update({item.value.title(): item.value for item in enum_type})
    aliases.update({item.value.lower(): item.value for item in enum_type})
    aliases.update({item.name: item.value for item in enum_type})
    aliases.update({item.name.lower(): item.value for item in enum_type})
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
