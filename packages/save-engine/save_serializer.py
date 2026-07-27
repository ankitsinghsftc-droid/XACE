"""Deterministic save serialization for XACE.

Save files are engine-agnostic JSON envelopes. The serializer rejects
non-deterministic values, sorts every mapping key, rounds floats to a fixed
precision, and emits compact UTF-8 JSON so the same payload produces the same
bytes on every platform.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


FORMAT_VERSION = 1
DEFAULT_FLOAT_PRECISION = 6


class SaveSerializationError(ValueError):
    """Raised when a payload cannot be represented deterministically."""


class SaveLayer(str, Enum):
    SESSION = "SESSION"
    PROGRESS = "PROGRESS"
    WORLD = "WORLD"


@dataclass(frozen=True)
class SaveEnvelope:
    """Canonical save file envelope."""

    schema_version: str
    layer: SaveLayer
    payload: Mapping[str, Any]
    slot_id: str = ""
    cgs_hash: str = ""
    created_at: str = ""
    saved_at: str = ""
    format_version: int = FORMAT_VERSION
    migration_history: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format_version": self.format_version,
            "schema_version": self.schema_version,
            "layer": self.layer.value,
            "slot_id": self.slot_id,
            "cgs_hash": self.cgs_hash,
            "created_at": self.created_at,
            "saved_at": self.saved_at,
            "migration_history": list(self.migration_history),
            "payload": dict(self.payload),
        }


class SaveSerializer:
    """Serializes save envelopes into stable JSON bytes."""

    def __init__(self, float_precision: int = DEFAULT_FLOAT_PRECISION) -> None:
        if float_precision < 0:
            raise ValueError("float_precision must be non-negative")
        self.float_precision = float_precision

    def build_envelope(
        self,
        *,
        schema_version: str,
        layer: SaveLayer | str,
        payload: Mapping[str, Any],
        slot_id: str = "",
        cgs_hash: str = "",
        created_at: str = "",
        saved_at: str = "",
        migration_history: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]] = (),
    ) -> SaveEnvelope:
        schema = _non_empty_text(schema_version, "schema_version")
        save_layer = _normalise_layer(layer)
        if not isinstance(payload, Mapping):
            raise SaveSerializationError("payload must be a mapping")
        return SaveEnvelope(
            schema_version=schema,
            layer=save_layer,
            payload=payload,
            slot_id=str(slot_id).strip(),
            cgs_hash=str(cgs_hash).strip(),
            created_at=str(created_at).strip(),
            saved_at=str(saved_at).strip(),
            migration_history=tuple(migration_history),
        )

    def dumps(self, envelope: SaveEnvelope | Mapping[str, Any]) -> str:
        data = envelope.to_dict() if isinstance(envelope, SaveEnvelope) else dict(envelope)
        canonical = self.canonicalise(data)
        return json.dumps(
            canonical,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    def dump_bytes(self, envelope: SaveEnvelope | Mapping[str, Any]) -> bytes:
        return self.dumps(envelope).encode("utf-8")

    def canonicalise(self, value: Any) -> Any:
        return _canonicalise(value, self.float_precision)

    def deterministic_hash_input(self, envelope: SaveEnvelope | Mapping[str, Any]) -> bytes:
        return self.dump_bytes(envelope)


def _canonicalise(value: Any, float_precision: int) -> Any:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SaveSerializationError("float values must be finite")
        return round(value, float_precision)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key in sorted(value.keys(), key=lambda item: str(item)):
            text_key = str(key)
            if not text_key:
                raise SaveSerializationError("mapping keys must not be empty")
            result[text_key] = _canonicalise(value[key], float_precision)
        return result
    if isinstance(value, (list, tuple)):
        return [_canonicalise(item, float_precision) for item in value]
    raise SaveSerializationError(f"unsupported save value type: {type(value).__name__}")


def _normalise_layer(value: SaveLayer | str) -> SaveLayer:
    if isinstance(value, SaveLayer):
        return value
    text = str(value).strip().upper()
    try:
        return SaveLayer(text)
    except ValueError as exc:
        allowed = ", ".join(layer.value for layer in SaveLayer)
        raise SaveSerializationError(f"layer must be one of {allowed}") from exc


def _non_empty_text(value: Any, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise SaveSerializationError(f"{field_name} must not be empty")
    return text
