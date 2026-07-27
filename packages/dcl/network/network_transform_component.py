"""COMP_NETWORK_TRANSFORM_V1 schema owner."""

from __future__ import annotations

from math import isfinite
from typing import Any, Mapping

from ..dcl_registry import ComponentDefinition, ComponentFieldDefinition, ComponentLayer

TYPE_ID = 321
TYPE_NAME = "COMP_NETWORK_TRANSFORM_V1"
DOMAIN = "network"
VEC3_ZERO = {"x": 0.0, "y": 0.0, "z": 0.0}


def build_definition() -> ComponentDefinition:
    return ComponentDefinition(
        type_id=TYPE_ID,
        type_name=TYPE_NAME,
        layer=ComponentLayer.DCL,
        domain=DOMAIN,
        version=1,
        description=(
            "Network transform interpolation state: last known position, target, "
            "extrapolation velocity, and source network timestamp."
        ),
        fields=[
            ComponentFieldDefinition("last_known_position", "struct", True, None, "Vec3 authoritative position from last received update."),
            ComponentFieldDefinition("interpolation_target", "struct", True, None, "Vec3 target position for interpolation."),
            ComponentFieldDefinition("extrapolation_velocity", "struct", False, None, "Vec3 velocity used when updates are late."),
            ComponentFieldDefinition("network_timestamp", "u64", False, "0", "Remote tick or transport timestamp for this transform sample."),
            ComponentFieldDefinition("snap_threshold", "f32", False, "5.0", "Distance above which clients should snap rather than interpolate."),
            ComponentFieldDefinition("interpolation_ticks", "u32", False, "2", "Number of local ticks used to blend toward interpolation_target."),
        ],
    )


def default_payload() -> dict[str, Any]:
    return {
        "last_known_position": dict(VEC3_ZERO),
        "interpolation_target": dict(VEC3_ZERO),
        "extrapolation_velocity": dict(VEC3_ZERO),
        "network_timestamp": 0,
        "snap_threshold": 5.0,
        "interpolation_ticks": 2,
    }


def validate_payload(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in ("last_known_position", "interpolation_target", "extrapolation_velocity"):
        if not _is_vec3(payload.get(field)):
            errors.append(f"{field} must be a finite Vec3 dict with x/y/z")
    if not isinstance(payload.get("network_timestamp", 0), int) or int(payload.get("network_timestamp", 0)) < 0:
        errors.append("network_timestamp must be a non-negative integer")
    if not _finite_non_negative(payload.get("snap_threshold", 5.0)):
        errors.append("snap_threshold must be a finite non-negative number")
    if not isinstance(payload.get("interpolation_ticks", 2), int) or int(payload.get("interpolation_ticks", 2)) < 0:
        errors.append("interpolation_ticks must be a non-negative integer")
    return errors


def normalise_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = default_payload()
    data.update(dict(payload))
    for field in ("last_known_position", "interpolation_target", "extrapolation_velocity"):
        data[field] = _normalise_vec3(data[field])
    data["network_timestamp"] = int(data["network_timestamp"])
    data["snap_threshold"] = float(data["snap_threshold"])
    data["interpolation_ticks"] = int(data["interpolation_ticks"])
    return data


def _is_vec3(value: Any) -> bool:
    return isinstance(value, Mapping) and all(axis in value and _finite_number(value[axis]) for axis in ("x", "y", "z"))


def _normalise_vec3(value: Mapping[str, Any]) -> dict[str, float]:
    return {axis: float(value.get(axis, 0.0)) for axis in ("x", "y", "z")}


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and isfinite(float(value))


def _finite_non_negative(value: Any) -> bool:
    return _finite_number(value) and float(value) >= 0.0
