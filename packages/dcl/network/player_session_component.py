"""COMP_PLAYER_SESSION_V1 schema owner."""

from __future__ import annotations

from enum import Enum
from typing import Any, Mapping

from ..dcl_registry import ComponentDefinition, ComponentFieldDefinition, ComponentLayer

TYPE_ID = 322
TYPE_NAME = "COMP_PLAYER_SESSION_V1"
DOMAIN = "network"


class SessionState(str, Enum):
    CONNECTING = "Connecting"
    SYNCING = "Syncing"
    LIVE = "Live"
    DESYNCED = "Desynced"
    DISCONNECTED = "Disconnected"


class AuthorityLevel(str, Enum):
    NONE = "None"
    INPUT_ONLY = "InputOnly"
    ENTITY_OWNER = "EntityOwner"
    HOST = "Host"
    SERVER = "Server"


def build_definition() -> ComponentDefinition:
    return ComponentDefinition(
        type_id=TYPE_ID,
        type_name=TYPE_NAME,
        layer=ComponentLayer.DCL,
        domain=DOMAIN,
        version=1,
        description="Connected player session state for multiplayer and late join workflows.",
        fields=[
            ComponentFieldDefinition("peer_id", "u64", True, None, "Stable network peer id."),
            ComponentFieldDefinition("session_state", "enum", False, '"Connecting"', "SessionState: Connecting|Syncing|Live|Desynced|Disconnected."),
            ComponentFieldDefinition("latency_ms", "u32", False, "0", "Latest round-trip latency estimate."),
            ComponentFieldDefinition("input_sequence_id", "u64", False, "0", "Last accepted input sequence for this peer."),
            ComponentFieldDefinition("authority_level", "enum", False, '"InputOnly"', "AuthorityLevel: None|InputOnly|EntityOwner|Host|Server."),
            ComponentFieldDefinition("display_name", "str", False, '"Player"', "Player display name."),
        ],
    )


def default_payload() -> dict[str, Any]:
    return {
        "peer_id": 0,
        "session_state": SessionState.CONNECTING.value,
        "latency_ms": 0,
        "input_sequence_id": 0,
        "authority_level": AuthorityLevel.INPUT_ONLY.value,
        "display_name": "Player",
    }


def validate_payload(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload.get("peer_id"), int) or int(payload.get("peer_id", 0)) <= 0:
        errors.append("peer_id must be a positive integer")
    if str(payload.get("session_state", SessionState.CONNECTING.value)) not in {item.value for item in SessionState}:
        errors.append("session_state is not a valid SessionState")
    if not _non_negative_int(payload.get("latency_ms", 0)):
        errors.append("latency_ms must be a non-negative integer")
    if not _non_negative_int(payload.get("input_sequence_id", 0)):
        errors.append("input_sequence_id must be a non-negative integer")
    if str(payload.get("authority_level", AuthorityLevel.INPUT_ONLY.value)) not in {item.value for item in AuthorityLevel}:
        errors.append("authority_level is not a valid AuthorityLevel")
    if not isinstance(payload.get("display_name", "Player"), str):
        errors.append("display_name must be a string")
    return errors


def normalise_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = default_payload()
    data.update(dict(payload))
    data["peer_id"] = int(data["peer_id"])
    data["session_state"] = str(data["session_state"])
    data["latency_ms"] = int(data["latency_ms"])
    data["input_sequence_id"] = int(data["input_sequence_id"])
    data["authority_level"] = str(data["authority_level"])
    data["display_name"] = str(data["display_name"]).strip() or "Player"
    return data


def _non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and value >= 0
