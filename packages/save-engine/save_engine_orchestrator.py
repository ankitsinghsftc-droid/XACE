"""High-level Save Engine orchestration for Audit 7.

The orchestrator owns file layout and routes Session, Progress, and World
layers through deterministic serialization, schema-gated deserialization, and
migration. It deliberately writes only complete envelopes with atomic replace.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from save_deserializer import LoadedSave, SaveDeserializer
from save_migration_engine import SaveMigrationEngine
from save_serializer import SaveEnvelope, SaveLayer, SaveSerializer


class SaveEngineError(RuntimeError):
    """Raised when a save operation cannot be completed."""


@dataclass(frozen=True)
class SaveWriteResult:
    slot_id: str
    layer: SaveLayer
    path: Path
    schema_version: str
    bytes_written: int


@dataclass(frozen=True)
class SaveLoadResult:
    slot_id: str
    layer: SaveLayer
    save: LoadedSave


class SaveEngineOrchestrator:
    """Coordinates deterministic save/load operations for all save layers."""

    METADATA_FILE = "metadata.json"

    def __init__(
        self,
        root: str | Path,
        *,
        current_schema_version: str,
        serializer: SaveSerializer | None = None,
        migration_engine: SaveMigrationEngine | None = None,
    ) -> None:
        self.root = Path(root)
        self.current_schema_version = _non_empty_text(
            current_schema_version, "current_schema_version"
        )
        self.serializer = serializer or SaveSerializer()
        self.migration_engine = migration_engine or SaveMigrationEngine()
        self.deserializer = SaveDeserializer(
            current_schema_version=self.current_schema_version,
            serializer=self.serializer,
            migration_engine=self.migration_engine,
        )

    def save_layer(
        self,
        *,
        slot_id: str,
        layer: SaveLayer | str,
        payload: Mapping[str, Any],
        display_name: str = "",
        cgs_hash: str = "",
        play_time_ticks: int = 0,
    ) -> SaveWriteResult:
        slot = _normalise_slot_id(slot_id)
        save_layer = _normalise_layer(layer)
        slot_dir = self._slot_dir(slot)
        slot_dir.mkdir(parents=True, exist_ok=True)

        existing_metadata = self._read_metadata(slot)
        now = _utc_now()
        created_at = str(existing_metadata.get("created_at") or now)
        envelope = self.serializer.build_envelope(
            schema_version=self.current_schema_version,
            layer=save_layer,
            payload=payload,
            slot_id=slot,
            cgs_hash=cgs_hash,
            created_at=created_at,
            saved_at=now,
        )
        data = self.serializer.dump_bytes(envelope)
        path = self._layer_path(slot, save_layer)
        _atomic_write(path, data)
        self._write_metadata(
            slot_id=slot,
            display_name=display_name or str(existing_metadata.get("display_name") or slot),
            schema_version=self.current_schema_version,
            cgs_hash=cgs_hash,
            created_at=created_at,
            last_played=now,
            play_time_ticks=play_time_ticks,
        )
        return SaveWriteResult(
            slot_id=slot,
            layer=save_layer,
            path=path,
            schema_version=self.current_schema_version,
            bytes_written=len(data),
        )

    def load_layer(
        self,
        *,
        slot_id: str,
        layer: SaveLayer | str,
        migration_plan: Any = None,
        persist_migration: bool = True,
    ) -> SaveLoadResult:
        slot = _normalise_slot_id(slot_id)
        save_layer = _normalise_layer(layer)
        path = self._layer_path(slot, save_layer)
        if not path.exists():
            raise SaveEngineError(f"save layer not found: {slot}/{save_layer.value}")
        loaded = self.deserializer.loads(path.read_text(encoding="utf-8"), migration_plan=migration_plan)
        if loaded.layer != save_layer:
            raise SaveEngineError(
                f"save layer mismatch: expected {save_layer.value}, found {loaded.layer.value}"
            )
        if loaded.migrated and persist_migration:
            _atomic_write(path, self.serializer.dump_bytes(loaded.envelope))
        return SaveLoadResult(slot_id=slot, layer=save_layer, save=loaded)

    def save_session(self, slot_id: str, world_snapshot: Mapping[str, Any], **kwargs: Any) -> SaveWriteResult:
        return self.save_layer(slot_id=slot_id, layer=SaveLayer.SESSION, payload=world_snapshot, **kwargs)

    def load_session(self, slot_id: str, **kwargs: Any) -> SaveLoadResult:
        return self.load_layer(slot_id=slot_id, layer=SaveLayer.SESSION, **kwargs)

    def save_progress(self, slot_id: str, progress: Mapping[str, Any], **kwargs: Any) -> SaveWriteResult:
        return self.save_layer(slot_id=slot_id, layer=SaveLayer.PROGRESS, payload=progress, **kwargs)

    def load_progress(self, slot_id: str, **kwargs: Any) -> SaveLoadResult:
        return self.load_layer(slot_id=slot_id, layer=SaveLayer.PROGRESS, **kwargs)

    def save_world(self, slot_id: str, world_state: Mapping[str, Any], **kwargs: Any) -> SaveWriteResult:
        return self.save_layer(slot_id=slot_id, layer=SaveLayer.WORLD, payload=world_state, **kwargs)

    def load_world(self, slot_id: str, **kwargs: Any) -> SaveLoadResult:
        return self.load_layer(slot_id=slot_id, layer=SaveLayer.WORLD, **kwargs)

    def list_slot_metadata(self) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        slots: list[dict[str, Any]] = []
        for entry in self.root.iterdir():
            if not entry.is_dir():
                continue
            metadata_path = entry / self.METADATA_FILE
            if not metadata_path.exists():
                continue
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise SaveEngineError(f"invalid metadata in {metadata_path}: {exc}") from exc
            if isinstance(metadata, Mapping):
                slots.append(dict(metadata))
        return sorted(slots, key=lambda item: str(item.get("slot_id", "")))

    def delete_slot(self, slot_id: str) -> None:
        slot_dir = self._slot_dir(_normalise_slot_id(slot_id))
        if not slot_dir.exists():
            raise SaveEngineError(f"save slot not found: {slot_id}")
        for path in sorted(slot_dir.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        slot_dir.rmdir()

    def _read_metadata(self, slot_id: str) -> dict[str, Any]:
        metadata_path = self._slot_dir(slot_id) / self.METADATA_FILE
        if not metadata_path.exists():
            return {}
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
        return dict(data) if isinstance(data, Mapping) else {}

    def _write_metadata(
        self,
        *,
        slot_id: str,
        display_name: str,
        schema_version: str,
        cgs_hash: str,
        created_at: str,
        last_played: str,
        play_time_ticks: int,
    ) -> None:
        if play_time_ticks < 0:
            raise SaveEngineError("play_time_ticks must be non-negative")
        metadata = self.serializer.canonicalise(
            {
                "slot_id": slot_id,
                "display_name": display_name,
                "schema_version": schema_version,
                "cgs_hash": cgs_hash,
                "created_at": created_at,
                "last_played": last_played,
                "play_time_ticks": int(play_time_ticks),
                "layers": self._present_layers(slot_id),
            }
        )
        text = json.dumps(metadata, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        _atomic_write(self._slot_dir(slot_id) / self.METADATA_FILE, text.encode("utf-8"))

    def _present_layers(self, slot_id: str) -> list[str]:
        return [
            layer.value
            for layer in SaveLayer
            if self._layer_path(slot_id, layer).exists()
        ]

    def _slot_dir(self, slot_id: str) -> Path:
        return self.root / slot_id

    def _layer_path(self, slot_id: str, layer: SaveLayer) -> Path:
        return self._slot_dir(slot_id) / f"{layer.value.lower()}.json"


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _normalise_layer(value: SaveLayer | str) -> SaveLayer:
    if isinstance(value, SaveLayer):
        return value
    try:
        return SaveLayer(str(value).strip().upper())
    except ValueError as exc:
        raise SaveEngineError(f"invalid save layer: {value!r}") from exc


def _normalise_slot_id(slot_id: str) -> str:
    text = _non_empty_text(slot_id, "slot_id")
    safe = "".join(char if char.isascii() and (char.isalnum() or char in {"_", "-"}) else "_" for char in text)
    if safe in {".", ".."}:
        raise SaveEngineError("slot_id must not be a relative path marker")
    return safe


def _non_empty_text(value: Any, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise SaveEngineError(f"{field_name} must not be empty")
    return text


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
