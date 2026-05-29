"""
memory_store.py - in-memory backing store for PIL memory layers.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MemoryLayer(str, Enum):
    DESIGN = "design"
    STRUCTURAL = "structural"
    BEHAVIORAL = "behavioral"
    SESSION = "session"
    SAFETY = "safety"


@dataclass
class MemoryEntry:
    entry_id: str
    layer: MemoryLayer
    content: str
    relevance_score: float = 0.0
    tags: set[str] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


class MemoryStore:
    """Small process-local store shared by the five memory layer views."""

    def __init__(self, session_id: str = "", max_entries: dict | None = None) -> None:
        self.session_id = session_id
        self._max_entries = max_entries or {}
        self._entries: dict[str, MemoryEntry] = {}
        self._turn_index = 0

    @property
    def turn_index(self) -> int:
        return self._turn_index

    def advance_turn(self) -> int:
        self._turn_index += 1
        return self._turn_index

    def add(
        self,
        layer: MemoryLayer,
        content: str,
        relevance_score: float = 0.0,
        tags: set[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryEntry:
        entry = MemoryEntry(
            entry_id=uuid.uuid4().hex,
            layer=MemoryLayer(layer),
            content=content,
            relevance_score=float(relevance_score),
            tags=set(tags or set()),
            metadata=dict(metadata or {}),
        )
        self._entries[entry.entry_id] = entry
        self._enforce_layer_limit(entry.layer)
        return entry

    def remove(self, entry_id: str) -> MemoryEntry | None:
        return self._entries.pop(entry_id, None)

    def find_by_id(self, entry_id: str) -> MemoryEntry | None:
        return self._entries.get(entry_id)

    def get_layer(self, layer: MemoryLayer) -> list[MemoryEntry]:
        wanted = MemoryLayer(layer)
        return [entry for entry in self._entries.values() if entry.layer == wanted]

    def get_by_tag(self, tag: str) -> list[MemoryEntry]:
        return [entry for entry in self._entries.values() if tag in entry.tags]

    def clear_layer(self, layer: MemoryLayer) -> None:
        wanted = MemoryLayer(layer)
        for entry_id in [
            entry.entry_id for entry in self._entries.values() if entry.layer == wanted
        ]:
            self._entries.pop(entry_id, None)

    def count(self, layer: MemoryLayer | None = None) -> int:
        if layer is None:
            return len(self._entries)
        return len(self.get_layer(layer))

    def stats(self) -> dict:
        by_layer = {
            layer.value: self.count(layer)
            for layer in MemoryLayer
        }
        return {
            "total_entries": len(self._entries),
            "by_layer": by_layer,
            "turn_index": self._turn_index,
        }

    def _enforce_layer_limit(self, layer: MemoryLayer) -> None:
        limit = self._max_entries.get(layer, self._max_entries.get(layer.value))
        if not limit:
            return

        entries = sorted(self.get_layer(layer), key=lambda entry: entry.created_at)
        while len(entries) > int(limit):
            oldest = entries.pop(0)
            self._entries.pop(oldest.entry_id, None)
