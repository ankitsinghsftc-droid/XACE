"""COMP_REPLICATION_V1 schema owner.

Replication is declarative DCL metadata. It describes how an entity should be
considered by network replication systems; it does not perform replication or
grant authority by itself.
"""

from __future__ import annotations

from enum import Enum
from math import isfinite
from typing import Any, Mapping

from ..dcl_registry import ComponentDefinition, ComponentFieldDefinition, ComponentLayer

TYPE_ID = 320
TYPE_NAME = "COMP_REPLICATION_V1"
DOMAIN = "network"


class ReplicationMode(str, Enum):
    NONE = "None"
    SERVER_ONLY = "ServerOnly"
    UNRELIABLE = "Unreliable"
    RELIABLE = "Reliable"
    OWNER_ONLY = "OwnerOnly"


def build_definition() -> ComponentDefinition:
    return ComponentDefinition(
        type_id=TYPE_ID,
        type_name=TYPE_NAME,
        layer=ComponentLayer.DCL,
        domain=DOMAIN,
        version=1,
        description=(
            "Entity replication policy: mode, priority, last replicated tick, "
            "and deterministic dirty flags."
        ),
        fields=[
            ComponentFieldDefinition(
                "replication_mode",
                "enum",
                False,
                '"Unreliable"',
                "ReplicationMode: None|ServerOnly|Unreliable|Reliable|OwnerOnly.",
            ),
            ComponentFieldDefinition(
                "priority",
                "f32",
                False,
                "1.0",
                "Replication priority. Higher values are considered first by replication managers.",
            ),
            ComponentFieldDefinition(
                "last_replicated_tick",
                "u64",
                False,
                "0",
                "Simulation tick when this entity was last replicated.",
            ),
            ComponentFieldDefinition(
                "dirty_flags",
                "list",
                False,
                "[]",
                "Sorted list of component or field flags requiring replication.",
            ),
            ComponentFieldDefinition(
                "relevance_radius",
                "f32",
                False,
                "0.0",
                "Interest radius in world units. 0 means globally relevant.",
            ),
            ComponentFieldDefinition(
                "sync_rate_divisor",
                "u32",
                False,
                "1",
                "Replicate at most every N ticks. 1 means every eligible tick.",
            ),
        ],
    )


def default_payload() -> dict[str, Any]:
    return {
        "replication_mode": ReplicationMode.UNRELIABLE.value,
        "priority": 1.0,
        "last_replicated_tick": 0,
        "dirty_flags": [],
        "relevance_radius": 0.0,
        "sync_rate_divisor": 1,
    }


def validate_payload(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    mode = str(payload.get("replication_mode", ReplicationMode.UNRELIABLE.value))
    if mode not in {item.value for item in ReplicationMode}:
        errors.append(f"replication_mode must be one of {[item.value for item in ReplicationMode]}")

    priority = payload.get("priority", 1.0)
    if not _finite_number(priority) or float(priority) < 0.0:
        errors.append("priority must be a finite non-negative number")

    last_tick = payload.get("last_replicated_tick", 0)
    if not _non_negative_int(last_tick):
        errors.append("last_replicated_tick must be a non-negative integer")

    dirty_flags = payload.get("dirty_flags", [])
    if not isinstance(dirty_flags, list) or not all(isinstance(flag, str) and flag for flag in dirty_flags):
        errors.append("dirty_flags must be a list of non-empty strings")
    elif dirty_flags != sorted(set(dirty_flags)):
        errors.append("dirty_flags must be sorted ascending with no duplicates")

    radius = payload.get("relevance_radius", 0.0)
    if not _finite_number(radius) or float(radius) < 0.0:
        errors.append("relevance_radius must be a finite non-negative number")

    divisor = payload.get("sync_rate_divisor", 1)
    if not _non_negative_int(divisor) or int(divisor) < 1:
        errors.append("sync_rate_divisor must be an integer >= 1")
    return errors


def normalise_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = default_payload()
    data.update(dict(payload))
    data["replication_mode"] = str(data["replication_mode"])
    data["priority"] = float(data["priority"])
    data["last_replicated_tick"] = int(data["last_replicated_tick"])
    data["dirty_flags"] = sorted(set(str(flag) for flag in data.get("dirty_flags", []) if str(flag)))
    data["relevance_radius"] = float(data["relevance_radius"])
    data["sync_rate_divisor"] = int(data["sync_rate_divisor"])
    return data


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and isfinite(float(value))


def _non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and value >= 0
