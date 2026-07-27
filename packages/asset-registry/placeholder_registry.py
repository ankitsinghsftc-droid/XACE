"""
placeholder_registry.py — Tracks all PLACEHOLDER asset references.

Specialised registry layer on top of AssetManifest focused on the
PLACEHOLDER lifecycle — the most common state during active game development.

## Why a Dedicated Registry
During game creation, most assets start as PLACEHOLDERs. The zero-experience
flow (CLAUDE.md Audit 2) is:
  1. Entity created → refs auto-registered as PLACEHOLDER
  2. Builder shows "7 assets are placeholders — game runs but looks like grey boxes"
  3. Designer builds game logic first
  4. Designer links real assets when ready

The PlaceholderRegistry tracks:
  - Which entities own which placeholder refs (for the builder UI panel)
  - When each placeholder was created (for staleness reporting)
  - How many placeholders exist per AssetType (for the asset status panel)

## Relationship to AssetManifest
PlaceholderRegistry does not duplicate AssetReference storage — it stores
asset_ids only and delegates to AssetManifest for the full reference data.
When a placeholder transitions to LINKED, the registry is notified via
mark_linked() and removes the entry from its tracking set.

## Auto-Registration Flow
```
EntityDefinition created in GDE
  └── AssetNamingPolicy.generate() → asset_id
        └── AssetReference.make_placeholder(asset_id, asset_type)
              └── AssetManifest.register(ref)
                    └── PlaceholderRegistry.track(asset_id, entity_id, asset_type)
```
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from asset_type_enum import AssetType


# ── Placeholder Entry ─────────────────────────────────────────────────────────

@dataclass
class PlaceholderEntry:
    """Tracking record for one PLACEHOLDER asset reference."""
    asset_id: str
    asset_type: AssetType
    entity_id: Optional[str]          # entity that owns this reference, if known
    created_at: datetime = field(default_factory=datetime.utcnow)
    schema_version_at_creation: str = "unknown"

    @property
    def age_seconds(self) -> float:
        """Seconds elapsed since this placeholder was created."""
        return (datetime.utcnow() - self.created_at).total_seconds()

    def to_dict(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "asset_type": self.asset_type.value,
            "entity_id": self.entity_id,
            "created_at": self.created_at.isoformat(),
            "schema_version_at_creation": self.schema_version_at_creation,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PlaceholderEntry":
        return cls(
            asset_id=data["asset_id"],
            asset_type=AssetType.from_string(data["asset_type"]),
            entity_id=data.get("entity_id"),
            created_at=datetime.fromisoformat(data["created_at"]),
            schema_version_at_creation=data.get("schema_version_at_creation", "unknown"),
        )


# ── Placeholder Registry ──────────────────────────────────────────────────────

class PlaceholderRegistry:
    """
    Tracks all PLACEHOLDER asset references for the builder UI and
    the zero-experience asset linking workflow.

    Entries are added on auto-registration and removed when an asset
    transitions to LINKED (or is removed from the CGS entirely).
    """

    def __init__(self) -> None:
        # Primary: asset_id → PlaceholderEntry
        self._entries: dict[str, PlaceholderEntry] = {}

        # Secondary index: entity_id → set of asset_ids
        self._by_entity: dict[str, set[str]] = {}

        # Secondary index: AssetType → set of asset_ids
        self._by_type: dict[AssetType, set[str]] = {}

    # ── Registration ──────────────────────────────────────────────────────

    def track(
        self,
        asset_id: str,
        asset_type: AssetType,
        entity_id: Optional[str] = None,
        schema_version: str = "unknown",
    ) -> None:
        """
        Begins tracking a newly created PLACEHOLDER asset.

        Called immediately after AssetManifest.register() for PLACEHOLDER refs.
        Idempotent — calling track() for an already-tracked asset_id is a no-op.
        """
        if asset_id in self._entries:
            return  # already tracked

        entry = PlaceholderEntry(
            asset_id=asset_id,
            asset_type=asset_type,
            entity_id=entity_id,
            schema_version_at_creation=schema_version,
        )
        self._entries[asset_id] = entry

        # Update secondary indices
        if entity_id:
            self._by_entity.setdefault(entity_id, set()).add(asset_id)

        self._by_type.setdefault(asset_type, set()).add(asset_id)

    def track_many(
        self,
        entries: list[tuple[str, AssetType, Optional[str]]],
        schema_version: str = "unknown",
    ) -> None:
        """
        Tracks multiple placeholders in one call.
        Each entry is (asset_id, asset_type, entity_id_or_none).
        """
        for asset_id, asset_type, entity_id in entries:
            self.track(asset_id, asset_type, entity_id, schema_version)

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def mark_linked(self, asset_id: str) -> bool:
        """
        Removes a placeholder from tracking when it transitions to LINKED.
        Returns True if the entry was found and removed, False if not tracked.
        """
        entry = self._entries.pop(asset_id, None)
        if entry is None:
            return False

        # Clean up secondary indices
        if entry.entity_id and entry.entity_id in self._by_entity:
            self._by_entity[entry.entity_id].discard(asset_id)
            if not self._by_entity[entry.entity_id]:
                del self._by_entity[entry.entity_id]

        if entry.asset_type in self._by_type:
            self._by_type[entry.asset_type].discard(asset_id)
            if not self._by_type[entry.asset_type]:
                del self._by_type[entry.asset_type]

        return True

    def remove(self, asset_id: str) -> bool:
        """
        Removes a placeholder when the owning entity is deleted from the CGS.
        Returns True if found and removed.
        """
        return self.mark_linked(asset_id)  # same cleanup logic

    # ── Queries ───────────────────────────────────────────────────────────

    def is_tracked(self, asset_id: str) -> bool:
        """Returns True if this asset_id is currently a tracked placeholder."""
        return asset_id in self._entries

    def get_entry(self, asset_id: str) -> Optional[PlaceholderEntry]:
        """Returns the PlaceholderEntry for the given asset_id, or None."""
        return self._entries.get(asset_id)

    def get_for_entity(self, entity_id: str) -> list[PlaceholderEntry]:
        """
        Returns all placeholder entries owned by the given entity.
        Sorted by asset_id for determinism (D11).
        """
        ids = sorted(self._by_entity.get(entity_id, set()))
        return [self._entries[i] for i in ids if i in self._entries]

    def get_for_type(self, asset_type: AssetType) -> list[PlaceholderEntry]:
        """
        Returns all placeholder entries of the given AssetType.
        Sorted by asset_id.
        """
        ids = sorted(self._by_type.get(asset_type, set()))
        return [self._entries[i] for i in ids if i in self._entries]

    def get_all(self) -> list[PlaceholderEntry]:
        """Returns all tracked placeholder entries sorted by asset_id."""
        return [self._entries[k] for k in sorted(self._entries.keys())]

    def get_stale(self, older_than_seconds: float) -> list[PlaceholderEntry]:
        """
        Returns placeholders that have been waiting longer than the given
        threshold. Used by asset_report to flag long-lived placeholders.
        """
        return [
            e for e in self.get_all()
            if e.age_seconds > older_than_seconds
        ]

    def total_count(self) -> int:
        """Total number of tracked placeholder references."""
        return len(self._entries)

    def count_for_type(self, asset_type: AssetType) -> int:
        """Count of placeholders of the given type."""
        return len(self._by_type.get(asset_type, set()))

    def entity_ids_with_placeholders(self) -> list[str]:
        """
        Returns entity IDs that have at least one placeholder reference.
        Sorted ascending (D11).
        """
        return sorted(self._by_entity.keys())

    # ── Builder UI Summary ────────────────────────────────────────────────

    def builder_summary(self) -> str:
        """
        The zero-experience message shown in the builder UI.
        CLAUDE.md Audit 2: "7 assets are placeholders — game runs but looks like grey boxes"
        """
        n = self.total_count()
        if n == 0:
            return "All assets linked ✓"
        noun = "asset" if n == 1 else "assets"
        verb = "is" if n == 1 else "are"
        return (
            f"{n} {noun} {verb} placeholder"
            f"{'s' if n != 1 else ''} — "
            "game runs but looks like grey boxes"
        )

    def type_breakdown(self) -> dict[str, int]:
        """
        Returns placeholder counts per AssetType for the builder UI panel.
        Only types with at least one placeholder are included.
        """
        return {
            t.value: count
            for t, ids in self._by_type.items()
            if (count := len(ids)) > 0
        }

    # ── Serialization ─────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "entries": [e.to_dict() for e in self.get_all()],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PlaceholderRegistry":
        registry = cls()
        for entry_data in data.get("entries", []):
            entry = PlaceholderEntry.from_dict(entry_data)
            registry._entries[entry.asset_id] = entry
            if entry.entity_id:
                registry._by_entity.setdefault(entry.entity_id, set()).add(entry.asset_id)
            registry._by_type.setdefault(entry.asset_type, set()).add(entry.asset_id)
        return registry

    def __len__(self) -> int:
        return len(self._entries)

    def __repr__(self) -> str:
        return f"PlaceholderRegistry(count={len(self._entries)})"