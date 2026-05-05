"""
asset_cleanup_manager.py — Removes orphaned and stale asset references.

When entities are deleted from the CGS, their asset references become
orphaned — they exist in the manifest but no component field references
them anymore. Left uncleaned, orphaned refs accumulate and skew the
builder UI asset counts.

## Cleanup Triggers
1. Entity deleted from CGS → all asset_ids registered to that entity
   should be removed from the manifest and placeholder registry
2. CGS major version migration → old asset_ids that no longer match
   any component field should be purged
3. Manual cleanup request from the designer → clear all PLACEHOLDERs
   for a specific entity type

## What Is NOT Cleaned
- LINKED assets are never auto-cleaned — they represent real files
  the designer deliberately connected. Only the designer can unlink them.
- MISSING assets are not auto-cleaned — the designer may re-link them.
  They are flagged in the builder UI as warnings only.
- UNRESOLVED assets are not cleaned — they are errors that must be
  investigated, not silently removed.

## Safety Guarantee
The cleanup manager never deletes from the CGS. It only removes entries
from the AssetManifest and PlaceholderRegistry. The CGS remains the
single source of truth for game design (I3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from asset_manifest import AssetManifest
from asset_reference import AssetReference
from asset_status_enum import AssetStatus
from placeholder_registry import PlaceholderRegistry


# ── Cleanup Result ────────────────────────────────────────────────────────────

@dataclass
class CleanupResult:
    """Result of one cleanup operation."""
    operation: str
    removed_asset_ids: list[str] = field(default_factory=list)
    skipped_asset_ids: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @property
    def removed_count(self) -> int:
        return len(self.removed_asset_ids)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped_asset_ids)

    def to_dict(self) -> dict:
        return {
            "operation": self.operation,
            "removed_count": self.removed_count,
            "skipped_count": self.skipped_count,
            "removed_asset_ids": self.removed_asset_ids,
            "skipped_asset_ids": self.skipped_asset_ids,
            "timestamp": self.timestamp.isoformat(),
        }


# ── Cleanup Manager ───────────────────────────────────────────────────────────

class AssetCleanupManager:
    """
    Removes orphaned and stale asset references from the manifest and
    placeholder registry when entities are removed from the CGS.

    ## Safety Rules
    - Never removes LINKED refs (designer deliberately linked these)
    - Never removes MISSING refs (designer may re-link)
    - Never removes UNRESOLVED refs (these are errors, must be investigated)
    - Never touches the CGS (read-only access to schema, I3)
    """

    def __init__(
        self,
        manifest: AssetManifest,
        placeholder_registry: PlaceholderRegistry,
    ) -> None:
        self._manifest = manifest
        self._placeholder_registry = placeholder_registry
        self._cleanup_history: list[CleanupResult] = []

    # ── Primary API ───────────────────────────────────────────────────────

    def cleanup_for_entity(self, entity_id: str) -> CleanupResult:
        """
        Removes all PLACEHOLDER asset references owned by the given entity.

        Called when an entity is deleted from the CGS. Only removes
        PLACEHOLDER refs — LINKED and MISSING refs are preserved because
        the files they reference still exist and may be reused.

        Args:
            entity_id: The entity whose asset refs should be cleaned up.

        Returns:
            CleanupResult with lists of removed and skipped asset_ids.
        """
        result = CleanupResult(operation=f"cleanup_entity:{entity_id}")

        # Get all placeholder entries for this entity from the registry
        entries = self._placeholder_registry.get_for_entity(entity_id)

        for entry in entries:
            asset_id = entry.asset_id
            ref = self._manifest.get(asset_id)

            if ref is None:
                # Already gone — consistent with registry being ahead
                result.removed_asset_ids.append(asset_id)
                self._placeholder_registry.remove(asset_id)
                continue

            # Only remove PLACEHOLDER refs — never LINKED, MISSING, UNRESOLVED
            if ref.status == AssetStatus.PLACEHOLDER:
                self._remove_ref(asset_id)
                result.removed_asset_ids.append(asset_id)
            else:
                result.skipped_asset_ids.append(asset_id)

        self._cleanup_history.append(result)
        return result

    def cleanup_asset_ids(
        self,
        asset_ids: list[str],
        only_status: Optional[AssetStatus] = None,
    ) -> CleanupResult:
        """
        Removes a specific list of asset_ids from the manifest.

        Used during CGS migration when old asset IDs are no longer
        referenced by any component field.

        Args:
            asset_ids: The asset_ids to remove.
            only_status: If set, only removes refs with this status.
                         If None, removes PLACEHOLDER refs only (safe default).

        Returns:
            CleanupResult with removed and skipped counts.
        """
        target_status = only_status or AssetStatus.PLACEHOLDER
        result = CleanupResult(operation="cleanup_asset_ids")

        for asset_id in sorted(asset_ids):  # sorted for determinism (D11)
            ref = self._manifest.get(asset_id)
            if ref is None:
                result.skipped_asset_ids.append(asset_id)
                continue

            if ref.status != target_status:
                result.skipped_asset_ids.append(asset_id)
                continue

            # Safety: never remove LINKED, MISSING, or UNRESOLVED by accident
            if ref.status in (AssetStatus.LINKED, AssetStatus.MISSING,
                               AssetStatus.UNRESOLVED):
                result.skipped_asset_ids.append(asset_id)
                continue

            self._remove_ref(asset_id)
            result.removed_asset_ids.append(asset_id)

        self._cleanup_history.append(result)
        return result

    def cleanup_orphaned_placeholders(
        self,
        active_asset_ids: set[str],
    ) -> CleanupResult:
        """
        Removes PLACEHOLDER refs whose asset_ids are not in the active set.

        Called after a CGS migration or full re-scan. The active_asset_ids
        set is built by scanning every component field in the current CGS
        for asset_id references.

        Any PLACEHOLDER in the manifest that is NOT in active_asset_ids
        is considered orphaned and removed.

        Args:
            active_asset_ids: Set of asset_ids currently referenced in the CGS.

        Returns:
            CleanupResult with removal counts.
        """
        result = CleanupResult(operation="cleanup_orphaned_placeholders")

        all_placeholders = self._manifest.get_all_placeholders()
        for ref in all_placeholders:
            if ref.asset_id not in active_asset_ids:
                self._remove_ref(ref.asset_id)
                result.removed_asset_ids.append(ref.asset_id)
            else:
                result.skipped_asset_ids.append(ref.asset_id)

        self._cleanup_history.append(result)
        return result

    def cleanup_stale_placeholders(
        self,
        older_than_seconds: float = 86_400,  # 24 hours default
    ) -> CleanupResult:
        """
        Removes PLACEHOLDER refs that have been in that state longer than
        the given threshold.

        These are assets where the designer created an entity but never
        linked the asset. After 24 hours, they are almost certainly
        forgotten or from deleted test entities.

        NOTE: This is a conservative cleanup — only removes refs with no
        entity_id (truly orphaned), not refs with a known owning entity.

        Args:
            older_than_seconds: Age threshold in seconds. Default 24 hours.

        Returns:
            CleanupResult.
        """
        result = CleanupResult(operation=f"cleanup_stale_placeholders(>{older_than_seconds}s)")

        stale_entries = self._placeholder_registry.get_stale(older_than_seconds)

        for entry in stale_entries:
            # Only remove truly orphaned placeholders (no known entity)
            if entry.entity_id is not None:
                result.skipped_asset_ids.append(entry.asset_id)
                continue

            ref = self._manifest.get(entry.asset_id)
            if ref and ref.status == AssetStatus.PLACEHOLDER:
                self._remove_ref(entry.asset_id)
                result.removed_asset_ids.append(entry.asset_id)
            else:
                result.skipped_asset_ids.append(entry.asset_id)

        self._cleanup_history.append(result)
        return result

    # ── History ───────────────────────────────────────────────────────────

    def cleanup_history(self) -> list[CleanupResult]:
        """Returns all cleanup results, newest first."""
        return list(reversed(self._cleanup_history))

    def total_removed(self) -> int:
        """Total asset references removed across all cleanup operations."""
        return sum(r.removed_count for r in self._cleanup_history)

    # ── Internal ──────────────────────────────────────────────────────────

    def _remove_ref(self, asset_id: str) -> None:
        """
        Removes an asset reference from both the manifest and placeholder
        registry. The manifest is the primary store — both must be updated.
        """
        # Remove from placeholder registry first (no-op if not tracked)
        self._placeholder_registry.remove(asset_id)

        # Remove from manifest's internal dicts directly
        # (Manifest has no public remove() — access via internal dict)
        ref = self._manifest._refs.pop(asset_id, None)
        if ref is not None:
            self._manifest._by_status[ref.status].discard(asset_id)
            self._manifest._by_type[ref.asset_type].discard(asset_id)

    def __repr__(self) -> str:
        return (
            f"AssetCleanupManager("
            f"operations={len(self._cleanup_history)}, "
            f"total_removed={self.total_removed()})"
        )