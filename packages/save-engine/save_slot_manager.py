"""Save slot metadata management.

The slot manager owns create/list/delete/rename operations and thumbnail
storage. It does not serialize game state; the orchestrator owns layer writes.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


METADATA_FILE = "metadata.json"
THUMBNAIL_FILE = "thumbnail.bin"


class SaveSlotError(RuntimeError):
    """Raised when save slot metadata cannot be managed safely."""


@dataclass(frozen=True, order=True)
class SaveSlotRecord:
    slot_id: str
    display_name: str
    schema_version: str
    created_at: str
    last_played: str
    play_time_ticks: int = 0
    cgs_hash: str = ""
    layers: tuple[str, ...] = ()
    thumbnail_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "display_name": self.display_name,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "last_played": self.last_played,
            "play_time_ticks": self.play_time_ticks,
            "cgs_hash": self.cgs_hash,
            "layers": list(self.layers),
            "thumbnail_path": self.thumbnail_path,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "SaveSlotRecord":
        slot_id = _normalise_slot_id(data.get("slot_id", ""))
        schema_version = _non_empty_text(data.get("schema_version", ""), "schema_version")
        created_at = str(data.get("created_at") or _utc_now())
        last_played = str(data.get("last_played") or created_at)
        play_time = int(data.get("play_time_ticks", 0))
        if play_time < 0:
            raise SaveSlotError("play_time_ticks must be non-negative")
        layers = tuple(sorted(str(layer).upper() for layer in data.get("layers", []) if str(layer)))
        return cls(
            slot_id=slot_id,
            display_name=str(data.get("display_name") or slot_id),
            schema_version=schema_version,
            created_at=created_at,
            last_played=last_played,
            play_time_ticks=play_time,
            cgs_hash=str(data.get("cgs_hash", "")),
            layers=layers,
            thumbnail_path=str(data.get("thumbnail_path", "")),
        )


class SaveSlotManager:
    """Manages save slot directories and metadata files."""

    def __init__(self, root: str | Path, *, current_schema_version: str) -> None:
        self.root = Path(root)
        self.current_schema_version = _non_empty_text(
            current_schema_version, "current_schema_version"
        )

    def create_slot(
        self,
        slot_id: str,
        *,
        display_name: str = "",
        cgs_hash: str = "",
        overwrite: bool = False,
    ) -> SaveSlotRecord:
        slot = _normalise_slot_id(slot_id)
        slot_dir = self._slot_dir(slot)
        if slot_dir.exists() and not overwrite:
            raise SaveSlotError(f"save slot already exists: {slot}")
        slot_dir.mkdir(parents=True, exist_ok=True)
        now = _utc_now()
        record = SaveSlotRecord(
            slot_id=slot,
            display_name=str(display_name).strip() or slot,
            schema_version=self.current_schema_version,
            created_at=now,
            last_played=now,
            cgs_hash=str(cgs_hash).strip(),
            layers=(),
        )
        self.write_record(record)
        return record

    def list_slots(self) -> list[SaveSlotRecord]:
        if not self.root.exists():
            return []
        records: list[SaveSlotRecord] = []
        for entry in self.root.iterdir():
            if not entry.is_dir():
                continue
            metadata_path = entry / METADATA_FILE
            if metadata_path.exists():
                records.append(self.read_record(entry.name))
        return sorted(records, key=lambda record: record.slot_id)

    def read_record(self, slot_id: str) -> SaveSlotRecord:
        slot = _normalise_slot_id(slot_id)
        path = self._slot_dir(slot) / METADATA_FILE
        if not path.exists():
            raise SaveSlotError(f"save slot metadata not found: {slot}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, Mapping):
            raise SaveSlotError(f"save slot metadata must be an object: {slot}")
        return SaveSlotRecord.from_mapping(data)

    def write_record(self, record: SaveSlotRecord) -> None:
        slot_dir = self._slot_dir(record.slot_id)
        slot_dir.mkdir(parents=True, exist_ok=True)
        data = _stable_json(record.to_dict()).encode("utf-8")
        _atomic_write(slot_dir / METADATA_FILE, data)

    def rename_slot(self, slot_id: str, new_slot_id: str, *, display_name: str | None = None) -> SaveSlotRecord:
        old_slot = _normalise_slot_id(slot_id)
        new_slot = _normalise_slot_id(new_slot_id)
        old_dir = self._slot_dir(old_slot)
        new_dir = self._slot_dir(new_slot)
        if not old_dir.exists():
            raise SaveSlotError(f"save slot not found: {old_slot}")
        if new_dir.exists():
            raise SaveSlotError(f"target save slot already exists: {new_slot}")
        os.replace(old_dir, new_dir)
        record = self.read_record(new_slot)
        renamed = SaveSlotRecord(
            slot_id=new_slot,
            display_name=display_name if display_name is not None else record.display_name,
            schema_version=record.schema_version,
            created_at=record.created_at,
            last_played=_utc_now(),
            play_time_ticks=record.play_time_ticks,
            cgs_hash=record.cgs_hash,
            layers=record.layers,
            thumbnail_path=record.thumbnail_path.replace(old_slot, new_slot),
        )
        self.write_record(renamed)
        return renamed

    def delete_slot(self, slot_id: str) -> None:
        slot = _normalise_slot_id(slot_id)
        slot_dir = self._slot_dir(slot)
        if not slot_dir.exists():
            raise SaveSlotError(f"save slot not found: {slot}")
        shutil.rmtree(slot_dir)

    def write_thumbnail(self, slot_id: str, data: bytes, *, content_type: str = "image/png") -> SaveSlotRecord:
        if not isinstance(data, (bytes, bytearray)):
            raise SaveSlotError("thumbnail data must be bytes")
        if len(data) > 2_000_000:
            raise SaveSlotError("thumbnail must be <= 2MB")
        slot = _normalise_slot_id(slot_id)
        record = self.read_record(slot)
        thumbnail_path = self._slot_dir(slot) / THUMBNAIL_FILE
        _atomic_write(thumbnail_path, bytes(data))
        updated = SaveSlotRecord(
            slot_id=record.slot_id,
            display_name=record.display_name,
            schema_version=record.schema_version,
            created_at=record.created_at,
            last_played=_utc_now(),
            play_time_ticks=record.play_time_ticks,
            cgs_hash=record.cgs_hash,
            layers=record.layers,
            thumbnail_path=str(thumbnail_path),
        )
        self.write_record(updated)
        sidecar = {"content_type": content_type, "bytes": len(data)}
        _atomic_write(thumbnail_path.with_suffix(".json"), _stable_json(sidecar).encode("utf-8"))
        return updated

    def _slot_dir(self, slot_id: str) -> Path:
        return self.root / slot_id


def _stable_json(data: Mapping[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _normalise_slot_id(slot_id: Any) -> str:
    text = _non_empty_text(slot_id, "slot_id")
    safe = "".join(char if char.isascii() and (char.isalnum() or char in {"_", "-"}) else "_" for char in text)
    if safe in {".", ".."}:
        raise SaveSlotError("slot_id must not be a relative path marker")
    return safe


def _non_empty_text(value: Any, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise SaveSlotError(f"{field_name} must not be empty")
    return text


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
