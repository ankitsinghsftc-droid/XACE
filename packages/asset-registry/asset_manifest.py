"""
asset_manifest.py — Central registry of all AssetReference instances.

The AssetManifest is the authoritative in-memory store of every asset
reference that exists in the current XACE session. It is the single
source of truth for asset state — not the CGS, not the engine adapter.

## Responsibilities
- Store and retrieve AssetReference by asset_id
- Track counts by AssetType and AssetStatus for the builder UI
- Detect duplicate registrations
- Provide bulk query methods used by asset_validator and asset_report

## Relationship to the CGS
The CGS stores only asset_id strings. When the Schema Factory or GDE
needs to validate a reference, it calls manifest.get(asset_id) and
checks the returned AssetReference.status. If the manifest has no entry
for an asset_id found in the CGS, it is UNRESOLVED (I12 violation).

## Persistence
The manifest serializes to JSON for save/load. It is rebuilt from the
saved session file at session start, not from the CGS itself.

## Thread Safety
The manifest is not thread-safe. It is always accessed from the
schema mutation pipeline (single-threaded in Phase 12/13). The engine
feedback receiver (engine_sync_receiver.py) calls manifest methods
only at tick boundaries, which are safe by the same contract as I13.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterator, Optional

from asset_reference import AssetReference
from asset_status_enum import AssetStatus
from asset_type_enum import AssetType


# ── Manifest Metrics ──────────────────────────────────────────────────────────

@dataclass
class ManifestMetrics:
    """Snapshot of manifest state for reporting and the builder UI."""
    total_references: int = 0
    by_status: dict[str, int] = field(default_factory=dict)
    by_type: dict[str, int] = field(default_factory=dict)
    placeholder_count: int = 0
    linked_count: int = 0
    missing_count: int = 0
    unresolved_count: int = 0

    @property
    def has_blockers(self) -> bool:
        """True if any UNRESOLVED references exist (I12)."""
        return self.unresolved_count > 0

    @property
    def has_warnings(self) -> bool:
        """True if any MISSING references exist."""
        return self.missing_count > 0

    @property
    def builder_summary(self) -> str:
        """
        One-line summary for the builder UI status bar.
        Matches the zero-experience UX described in CLAUDE.md Audit 2.
        """
        parts = []
        if self.placeholder_count:
            parts.append(
                f"{self.placeholder_count} asset"
                f"{'s' if self.placeholder_count != 1 else ''} "
                f"{'are' if self.placeholder_count != 1 else 'is'} "
                "placeholder"
                f"{'s' if self.placeholder_count != 1 else ''} "
                "— game runs but looks like grey boxes"
            )
        if self.missing_count:
            parts.append(
                f"{self.missing_count} asset"
                f"{'s' if self.missing_count != 1 else ''} missing"
            )
        if self.unresolved_count:
            parts.append(
                f"{self.unresolved_count} unresolved "
                f"(blocks save)"
            )
        if not parts:
            return f"All {self.linked_count} assets linked ✓"
        return " · ".join(parts)


# ── Asset Manifest ────────────────────────────────────────────────────────────

class AssetManifest:
    """
    Authoritative registry of all AssetReference instances in the session.

    ## Indexing
    Primary index: asset_id → AssetReference (O(1) lookup)
    Secondary index: AssetStatus → set[asset_id] (O(1) status queries)
    Tertiary index: AssetType → set[asset_id] (O(1) type queries)

    All indices are kept consistent on every mutation.
    """

    def __init__(self) -> None:
        # Primary store: asset_id → AssetReference
        self._refs: dict[str, AssetReference] = {}

        # Secondary index: status → set of asset_ids
        self._by_status: dict[AssetStatus, set[str]] = defaultdict(set)

        # Tertiary index: type → set of asset_ids
        self._by_type: dict[AssetType, set[str]] = defaultdict(set)

        # Registration counter for duplicate detection
        self._registration_count: int = 0

    # ── Registration ──────────────────────────────────────────────────────

    def register(self, ref: AssetReference) -> None:
        """
        Registers an AssetReference in the manifest.

        If an asset with the same asset_id already exists, the existing
        entry is preserved and a ValueError is raised.
        Use update_status() to change an existing reference's status.

        Raises:
            ValueError if asset_id is already registered.
        """
        if ref.asset_id in self._refs:
            raise ValueError(
                f"AssetManifest.register(): asset_id '{ref.asset_id}' is already "
                "registered. Use update_status() or link() to change its state."
            )
        self._refs[ref.asset_id] = ref
        self._by_status[ref.status].add(ref.asset_id)
        self._by_type[ref.asset_type].add(ref.asset_id)
        self._registration_count += 1

    def register_many(self, refs: list[AssetReference]) -> list[str]:
        """
        Registers multiple references. Returns list of asset_ids that
        failed (already registered) — does not raise, just skips them.
        """
        failed = []
        for ref in refs:
            try:
                self.register(ref)
            except ValueError:
                failed.append(ref.asset_id)
        return failed

    def register_or_update(self, ref: AssetReference) -> bool:
        """
        Registers if new, updates status/path if existing.
        Returns True if newly registered, False if updated.
        Used by engine_sync_receiver for bulk LINKED transitions.
        """
        if ref.asset_id not in self._refs:
            self.register(ref)
            return True
        existing = self._refs[ref.asset_id]
        self._update_indices(existing, ref.status, ref.resolved_path)
        return False

    # ── Retrieval ─────────────────────────────────────────────────────────

    def get(self, asset_id: str) -> Optional[AssetReference]:
        """Returns the AssetReference for the given ID, or None."""
        return self._refs.get(asset_id)

    def get_or_raise(self, asset_id: str) -> AssetReference:
        """Returns the AssetReference or raises KeyError."""
        ref = self._refs.get(asset_id)
        if ref is None:
            raise KeyError(
                f"AssetManifest: asset_id '{asset_id}' not found. "
                "It may be UNRESOLVED — check the CGS for stale references."
            )
        return ref

    def contains(self, asset_id: str) -> bool:
        """Returns True if asset_id is registered."""
        return asset_id in self._refs

    # ── Status Updates ────────────────────────────────────────────────────

    def link(self, asset_id: str, resolved_path: str) -> None:
        """
        Transitions an asset from PLACEHOLDER or MISSING to LINKED.
        Updates all secondary indices.

        Raises:
            KeyError if asset_id not registered.
            ValueError if asset is UNRESOLVED.
        """
        ref = self.get_or_raise(asset_id)
        old_status = ref.status
        ref.link(resolved_path)
        self._reindex(asset_id, old_status, ref.status)

    def mark_missing(self, asset_id: str) -> None:
        """
        Transitions a LINKED asset to MISSING.
        Called when a file-watcher detects a linked file was deleted or moved.
        """
        ref = self.get_or_raise(asset_id)
        old_status = ref.status
        ref.mark_missing()
        self._reindex(asset_id, old_status, ref.status)

    def revert_to_placeholder(self, asset_id: str) -> None:
        """Resets an asset reference back to PLACEHOLDER."""
        ref = self.get_or_raise(asset_id)
        old_status = ref.status
        ref.revert_to_placeholder()
        self._reindex(asset_id, old_status, ref.status)

    # ── Queries ───────────────────────────────────────────────────────────

    def get_by_status(self, status: AssetStatus) -> list[AssetReference]:
        """
        Returns all references with the given status.
        Sorted by asset_id for determinism (D11).
        """
        ids = sorted(self._by_status.get(status, set()))
        return [self._refs[i] for i in ids]

    def get_by_type(self, asset_type: AssetType) -> list[AssetReference]:
        """
        Returns all references of the given type.
        Sorted by asset_id for determinism (D11).
        """
        ids = sorted(self._by_type.get(asset_type, set()))
        return [self._refs[i] for i in ids]

    def get_all_unresolved(self) -> list[AssetReference]:
        """
        Returns all UNRESOLVED references — the I12 blockers.
        Sorted by asset_id.
        """
        return self.get_by_status(AssetStatus.UNRESOLVED)

    def get_all_placeholders(self) -> list[AssetReference]:
        """Returns all PLACEHOLDER references, sorted by asset_id."""
        return self.get_by_status(AssetStatus.PLACEHOLDER)

    def get_all_missing(self) -> list[AssetReference]:
        """Returns all MISSING references, sorted by asset_id."""
        return self.get_by_status(AssetStatus.MISSING)

    def get_all_linked(self) -> list[AssetReference]:
        """Returns all LINKED references, sorted by asset_id."""
        return self.get_by_status(AssetStatus.LINKED)

    def all_refs(self) -> Iterator[AssetReference]:
        """Iterates all references in asset_id ascending order (D11)."""
        for key in sorted(self._refs.keys()):
            yield self._refs[key]

    def count_by_status(self, status: AssetStatus) -> int:
        """Returns the count of references in the given status."""
        return len(self._by_status.get(status, set()))

    def count_by_type(self, asset_type: AssetType) -> int:
        """Returns the count of references of the given type."""
        return len(self._by_type.get(asset_type, set()))

    def total_count(self) -> int:
        """Returns total number of registered references."""
        return len(self._refs)

    def has_unresolved(self) -> bool:
        """True if any UNRESOLVED references exist (fast path for I12 check)."""
        return bool(self._by_status.get(AssetStatus.UNRESOLVED))

    # ── Metrics ───────────────────────────────────────────────────────────

    def compute_metrics(self) -> ManifestMetrics:
        """
        Computes a full metrics snapshot.
        Called by asset_report.py and the builder UI status bar.
        """
        by_status = {
            s.value: len(ids)
            for s, ids in self._by_status.items()
            if ids
        }
        by_type = {
            t.value: len(ids)
            for t, ids in self._by_type.items()
            if ids
        }
        return ManifestMetrics(
            total_references=len(self._refs),
            by_status=by_status,
            by_type=by_type,
            placeholder_count=len(self._by_status.get(AssetStatus.PLACEHOLDER, set())),
            linked_count=len(self._by_status.get(AssetStatus.LINKED, set())),
            missing_count=len(self._by_status.get(AssetStatus.MISSING, set())),
            unresolved_count=len(self._by_status.get(AssetStatus.UNRESOLVED, set())),
        )

    # ── Serialization ─────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serializes the manifest to a JSON-compatible dict."""
        return {
            "references": [ref.to_dict() for ref in self.all_refs()],
            "registration_count": self._registration_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AssetManifest":
        """Deserializes an AssetManifest from a saved dict."""
        manifest = cls()
        for ref_data in data.get("references", []):
            ref = AssetReference.from_dict(ref_data)
            manifest._refs[ref.asset_id] = ref
            manifest._by_status[ref.status].add(ref.asset_id)
            manifest._by_type[ref.asset_type].add(ref.asset_id)
        manifest._registration_count = data.get("registration_count", len(manifest._refs))
        return manifest

    def to_json(self, indent: int = 2) -> str:
        """Serializes to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_json(cls, json_str: str) -> "AssetManifest":
        """Deserializes from a JSON string."""
        return cls.from_dict(json.loads(json_str))

    # ── Internal ──────────────────────────────────────────────────────────

    def _reindex(
        self, asset_id: str, old_status: AssetStatus, new_status: AssetStatus
    ) -> None:
        """Updates the secondary status index after a status transition."""
        if old_status in self._by_status:
            self._by_status[old_status].discard(asset_id)
        self._by_status[new_status].add(asset_id)

    def _update_indices(
        self,
        ref: AssetReference,
        new_status: AssetStatus,
        new_path: Optional[str],
    ) -> None:
        """Updates an existing ref's status and path, keeping indices consistent."""
        old_status = ref.status
        ref.status = new_status
        ref.resolved_path = new_path
        self._reindex(ref.asset_id, old_status, new_status)

    def __len__(self) -> int:
        return len(self._refs)

    def __repr__(self) -> str:
        m = self.compute_metrics()
        return (
            f"AssetManifest(total={m.total_references}, "
            f"linked={m.linked_count}, "
            f"placeholder={m.placeholder_count}, "
            f"missing={m.missing_count}, "
            f"unresolved={m.unresolved_count})"
        )