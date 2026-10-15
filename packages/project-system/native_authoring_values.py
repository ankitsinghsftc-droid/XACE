"""NEC-003 exact authoring values. No runtime, filesystem or editor operations.

Native readers serialize decimals as text *before* crossing the JSON boundary.
Canonical fixed64 values are decimal strings, including values beyond JS 2**53.
Conversions are the inverse of the XP-016 native presentation contracts.
"""
from __future__ import annotations

import re
from fractions import Fraction
from pathlib import Path
import sys

from authoring_identity import exact, require, token

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "asset-registry"))
from asset_reference import AssetReference
from asset_type_enum import AssetType
from asset_status_enum import AssetStatus
from asset_reference_preflight import PLAYBACK_EXPECTED_TYPES

SCALE = 1_000_000
LIMIT = 8192 * SCALE
PROFILE = "fixed64_y_up_neg_z_v1"


def decimal(value: object) -> Fraction:
    require(type(value) is str and len(value) <= 96, "decimal must be bounded text")
    require(re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value) is not None,
            "invalid decimal (no exponent, nonfinite value or leading zero)")
    return Fraction(value)


def integer(value: object) -> int:
    require(type(value) is str and re.fullmatch(r"(?:0|-[1-9][0-9]*|[1-9][0-9]*)", value)
            is not None and len(value) <= 20, "expected canonical int64 string")
    result = int(value)
    require(-(2**63) <= result < 2**63, "int64 overflow")
    return result


def quantize(value: Fraction) -> tuple[str, bool]:
    """Round exact rationals to nearest, ties to even; report any lost fraction."""
    lower, remainder = divmod(value.numerator, value.denominator)
    rounded = lower + (2 * remainder > value.denominator or
                       (2 * remainder == value.denominator and lower % 2 != 0))
    require(-(2**63) <= rounded < 2**63, "fixed64 overflow")
    return str(rounded), remainder != 0


def normalize(engine: str, kind: str, value: object) -> tuple[object, list[str]]:
    require(engine in {"unity", "unreal", "godot"}, "unknown coordinate convention")
    if kind == "int64":
        return str(integer(value)), []
    if kind == "bool":
        require(type(value) is bool, "expected bool")
        return value, []
    if kind == "text":
        token(value, "semantic token", 1024)
        return value, []
    if kind == "asset":
        exact(value, {"asset_id", "asset_type", "status", "resolved_path"})
        for key in ("asset_id", "asset_type", "status"):
            token(value[key], key)
        if value["resolved_path"] is not None:
            token(value["resolved_path"], "resolved path", 4096)
        ref = AssetReference(value["asset_id"], AssetType(value["asset_type"]),
                             AssetStatus(value["status"]), value["resolved_path"])
        require(not ref.blocks_cgs_commit, "UNRESOLVED asset")
        return ref.to_dict(), []
    if kind == "binding":
        exact(value, {"binding_id", "event_name", "playback_kind", "asset"})
        for key in ("binding_id", "event_name", "playback_kind"):
            token(value[key], key)
        asset, _ = normalize(engine, "asset", value["asset"])
        expected = PLAYBACK_EXPECTED_TYPES.get(value["playback_kind"])
        require(expected is not None and asset["asset_type"] in expected,
                "unsupported semantic playback/type pairing")
        return dict(value, asset=asset), []
    require(kind in {"position", "offset", "size", "scale", "normal", "rotation"},
            "unknown field type")
    axes = "xyzw" if kind == "rotation" else "xyz"
    exact(value, set(axes))
    numbers = [decimal(value[k]) for k in axes]
    if engine == "unity":
        if kind in {"position", "offset", "normal"}:
            numbers[2] *= -1
        elif kind == "rotation":
            numbers[0] *= -1
            numbers[1] *= -1
    elif engine == "unreal":
        x, y, z = numbers[:3]
        if kind == "rotation":
            numbers = [-y, -z, x, numbers[3]]
        else:
            numbers = [y, z, -x if kind in {"position", "offset", "normal"} else x]
        if kind in {"position", "offset", "size"}:
            numbers = [n / 100 for n in numbers]
    converted = [quantize(n * SCALE) for n in numbers]
    result = {k: raw for k, (raw, _) in zip(axes, converted)}
    losses = [k for k, (_, lost) in zip(axes, converted) if lost]
    raw = [int(result[k]) for k in axes]
    if kind in {"position", "offset", "size"}:
        require(all(abs(n) <= LIMIT for n in raw), "world coordinate limit exceeded")
    if kind == "size":
        require(all(n > 0 for n in raw), "nonpositive size")
    if kind == "scale":
        require(all(n != 0 for n in raw), "zero scale")
    if kind in {"normal", "rotation"}:
        # Fixed-grid unit vectors; no implicit engine-style normalization.
        require(abs(sum(n*n for n in raw) - SCALE*SCALE) <= 4*SCALE,
                "nonunit normal/quaternion")
    if kind == "rotation":
        sign = next((int(result[k]) for k in "wxyz" if int(result[k]) != 0), 1)
        if sign < 0:
            result = {k: str(-int(v)) for k, v in result.items()}
    return result, losses


def geometry(fields: dict, parent: str | None) -> None:
    """Admit only the frozen World v3 AABB subset; never bake hierarchy/rotation."""
    require(parent is None, "authoritative geometry cannot have a parent")
    require(all(k in fields for k in ("transform.position", "transform.rotation",
                                      "transform.scale", "collision.size", "collision.offset",
                                      "collision.shape", "collision.profile", "collision.trigger")), "incomplete geometry")
    require(fields["collision.shape"] == "BOX" and fields["collision.profile"] == "world.aabb.v1",
            "unsupported authoritative geometry")
    require(fields["transform.rotation"] == dict(x="0", y="0", z="0", w=str(SCALE))
            and fields["transform.scale"] == dict.fromkeys("xyz", str(SCALE)),
            "rotated/scaled authoritative geometry unsupported")
    for axis in "xyz":
        size = int(fields["collision.size"][axis])
        center = int(fields["transform.position"][axis]) + int(fields["collision.offset"][axis])
        require(size % 2 == 0 and abs(center) + size // 2 <= LIMIT,
                "inexact half extent or out-of-bounds body")
