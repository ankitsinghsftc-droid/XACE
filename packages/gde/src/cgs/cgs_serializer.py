"""
cgs_serializer.py — CGSSerializer
====================================
Deterministic serialisation and deserialisation of the CGS dict.

The serialised form is the canonical representation used for:
    - cgs_hash computation (D9, D11)
    - Persistence to disk / database
    - Wire transfer to engine adapters
    - Import/export between game projects

## Determinism Contract (D11)
The same CGS dict must always produce byte-identical JSON output.
This requires:
    1. Sorted keys at every nesting level (json.dumps sort_keys=True)
    2. No extra whitespace (separators=(",",":"))
    3. Consistent float representation — we round to 6 decimal places
       to avoid platform-specific float→string differences
    4. ASCII-safe encoding (ensure_ascii=True)

## Float Precision
Game-design floats (speeds, radii, damage values) are stored to 6 decimal
places. This is sufficient for all design-time values and avoids the
platform-specific float repr differences that break cross-machine hashes.
Runtime physics does its own fixed-precision arithmetic; the CGS float
values are starting-state and design-intent values only.

## Round-Trip Guarantee
deserialise(serialise(cgs)) must produce a dict that, when serialised again,
produces the same bytes. All standard JSON types satisfy this; avoid storing
non-JSON types (datetime, set, etc.) in the CGS.
"""

from __future__ import annotations

import json
import hashlib
from typing import Any


# ── Serialisation Constants ───────────────────────────────────────────────────

_FLOAT_PRECISION:  int = 6
_JSON_SEPARATORS:  tuple[str, str] = (",", ":")


# ── Float Normaliser ──────────────────────────────────────────────────────────

def _normalise_floats(obj: Any) -> Any:
    """
    Recursively rounds all floats in obj to _FLOAT_PRECISION decimal places.

    This is the single source of float normalisation for the entire GDE.
    Called before serialisation to ensure consistent representation.
    """
    match obj:
        case float():
            return round(obj, _FLOAT_PRECISION)
        case dict():
            # Sort keys while normalising — belt-and-suspenders for D11
            return {k: _normalise_floats(v) for k, v in sorted(obj.items())}
        case list():
            return [_normalise_floats(v) for v in obj]
        case _:
            return obj


# ── CGS Serializer ────────────────────────────────────────────────────────────

class CGSSerializer:
    """
    Deterministic serialiser for the Canonical Game Schema (CGS).

    Stateless — all methods are class methods. One CGSSerializer instance
    may be shared across the entire GDE without any state concerns.

    Usage
    -----
        json_str = CGSSerializer.serialise(cgs_dict)
        cgs_hash = CGSSerializer.compute_hash(cgs_dict)
        restored = CGSSerializer.deserialise(json_str)
    """

    # ── Serialise ─────────────────────────────────────────────────────────────

    @classmethod
    def serialise(cls, cgs: dict[str, Any]) -> str:
        """
        Serialises a CGS dict to canonical JSON.

        - All keys sorted recursively (D11)
        - All floats rounded to 6 decimal places
        - No whitespace beyond structural minimum
        - ASCII-safe

        Returns a UTF-8 string. The same dict always produces the same string.

        Raises
        ------
        CGSSerializationError
            If the dict contains a type that JSON cannot represent
            (e.g. datetime, set, bytes).
        """
        try:
            normalised = _normalise_floats(cgs)
            return json.dumps(
                normalised,
                sort_keys=True,
                separators=_JSON_SEPARATORS,
                ensure_ascii=True,
            )
        except (TypeError, ValueError) as exc:
            raise CGSSerializationError(
                f"CGS serialisation failed: {exc}. "
                f"Ensure all CGS values are JSON-serialisable types "
                f"(str, int, float, bool, list, dict, None)."
            ) from exc

    @classmethod
    def serialise_pretty(cls, cgs: dict[str, Any]) -> str:
        """
        Serialises to human-readable JSON (2-space indent).
        Used for file export, debug output, and builder UI display.
        NOT used for hash computation — always use serialise() for that.
        """
        try:
            normalised = _normalise_floats(cgs)
            return json.dumps(
                normalised,
                sort_keys=True,
                indent=2,
                ensure_ascii=True,
            )
        except (TypeError, ValueError) as exc:
            raise CGSSerializationError(
                f"CGS pretty-serialisation failed: {exc}."
            ) from exc

    # ── Deserialise ───────────────────────────────────────────────────────────

    @classmethod
    def deserialise(cls, json_str: str) -> dict[str, Any]:
        """
        Deserialises a canonical JSON string back to a CGS dict.

        Raises
        ------
        CGSSerializationError
            If the string is not valid JSON or does not decode to a dict.
        """
        if not json_str or not json_str.strip():
            raise CGSSerializationError(
                "Cannot deserialise an empty string."
            )
        try:
            result = json.loads(json_str)
        except json.JSONDecodeError as exc:
            raise CGSSerializationError(
                f"CGS JSON decode failed at line {exc.lineno}, "
                f"col {exc.colno}: {exc.msg}"
            ) from exc

        if not isinstance(result, dict):
            raise CGSSerializationError(
                f"Deserialised CGS must be a dict, "
                f"got {type(result).__name__}."
            )
        return result

    # ── Hash Computation ──────────────────────────────────────────────────────

    @classmethod
    def compute_hash(cls, cgs: dict[str, Any]) -> str:
        """
        Computes a deterministic SHA-256 hash of the CGS dict.

        Identical to SchemaVersionManager.compute_hash() — both use
        the same canonical serialisation. Having it here avoids a
        cross-package import in the GDE.

        Returns a 64-character lowercase hex string.
        """
        canonical = cls.serialise(cgs).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    # ── Comparison ────────────────────────────────────────────────────────────

    @classmethod
    def are_equal(cls, cgs_a: dict[str, Any], cgs_b: dict[str, Any]) -> bool:
        """
        Returns True if two CGS dicts serialise to identical bytes.
        Cheaper than hashing when you already have both dicts in memory.
        """
        return cls.serialise(cgs_a) == cls.serialise(cgs_b)

    # ── Partial Serialisation ─────────────────────────────────────────────────

    @classmethod
    def serialise_component_defaults(cls, defaults: dict[str, Any]) -> str:
        """
        Serialises a component defaults dict in canonical form.
        Used by MutationTargetResolver when generating patch JSON.
        """
        try:
            normalised = _normalise_floats(defaults)
            return json.dumps(
                normalised,
                sort_keys=True,
                separators=_JSON_SEPARATORS,
                ensure_ascii=True,
            )
        except (TypeError, ValueError) as exc:
            raise CGSSerializationError(
                f"Component defaults serialisation failed: {exc}."
            ) from exc

    @classmethod
    def deserialise_value(cls, value_str: str) -> Any:
        """
        Parses a single JSON value string (e.g. "42", '"hello"', "true").
        Used by the DSL path parser when extracting mutation values from
        user-typed expressions.
        """
        try:
            return json.loads(value_str)
        except json.JSONDecodeError as exc:
            raise CGSSerializationError(
                f"Could not parse value '{value_str}' as JSON: {exc.msg}"
            ) from exc


# ── Serialization Error ───────────────────────────────────────────────────────

class CGSSerializationError(Exception):
    """Raised when CGS serialisation or deserialisation fails."""