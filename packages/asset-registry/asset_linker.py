"""
asset_linker.py — Manages the PLACEHOLDER → LINKED transition (Audit 2).

The AssetLinker is the only authorised path for transitioning an asset
reference from PLACEHOLDER (or MISSING) to LINKED. It validates the
resolved path, updates both the AssetManifest and PlaceholderRegistry
atomically, and records a link audit trail.

## Why a Dedicated Linker
Direct calls to manifest.link() would bypass:
  1. Path validation (does the file extension match the AssetType?)
  2. PlaceholderRegistry cleanup (the tracker must be updated)
  3. Link history (the audit trail used by asset_cleanup_manager)
  4. Bulk linking from engine feedback (engine_sync_receiver delegates here)

## Link Sources
Links originate from two places:
  - Designer action in the builder UI (single link, explicit path)
  - Engine feedback (bulk LINKED transitions in AssetResolutionUpdateFeedback)

Both paths go through AssetLinker.link() or AssetLinker.link_bulk().

## Path Validation
The linker checks that the file extension is plausible for the AssetType.
It does NOT check that the file actually exists on disk — that is the
engine adapter's responsibility. If the engine later cannot find the file,
it sends AssetResolutionUpdate feedback and the linker marks it MISSING.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from asset_manifest import AssetManifest
from asset_naming_policy import AssetNamingPolicy
from asset_reference import AssetReference
from asset_status_enum import AssetStatus
from asset_type_enum import AssetType
from placeholder_registry import PlaceholderRegistry


# ── Extension Whitelist ───────────────────────────────────────────────────────

# Maps AssetType → valid file extensions (lowercase, with dot).
# Used for soft validation — warns but does not block on mismatch.
VALID_EXTENSIONS: dict[AssetType, list[str]] = {
    AssetType.MESH:                 [".fbx", ".obj", ".gltf", ".glb", ".mesh"],
    AssetType.TEXTURE:              [".png", ".jpg", ".jpeg", ".tga", ".exr", ".bmp", ".dds"],
    AssetType.MATERIAL:             [".mat", ".material", ".uasset"],
    AssetType.ANIMATION_CONTROLLER: [".controller", ".anim", ".uasset", ".tres"],
    AssetType.ANIMATION_CLIP:       [".anim", ".fbx", ".glb", ".gltf", ".uasset", ".res", ".tres"],
    AssetType.AUDIO_CLIP:           [".wav", ".ogg", ".mp3", ".aiff", ".flac"],
    AssetType.AUDIO_MUSIC:          [".wav", ".ogg", ".mp3", ".aiff", ".flac"],
    AssetType.SPRITE:               [".png", ".jpg", ".jpeg", ".tga", ".sprite"],
    AssetType.PARTICLE:             [".prefab", ".niagara", ".tscn", ".tres", ".vfx"],
    AssetType.PREFAB:               [".prefab", ".uasset", ".tscn", ".scn"],
    AssetType.FONT:                 [".ttf", ".otf", ".fnt", ".asset"],
}


# ── Link Record ───────────────────────────────────────────────────────────────

@dataclass
class LinkRecord:
    """Audit trail entry for one asset link operation."""
    asset_id: str
    asset_type: AssetType
    resolved_path: str
    linked_at: datetime = field(default_factory=datetime.utcnow)
    source: str = "manual"          # "manual" | "engine_feedback" | "migration"
    previous_status: AssetStatus = AssetStatus.PLACEHOLDER
    extension_warning: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "asset_type": self.asset_type.value,
            "resolved_path": self.resolved_path,
            "linked_at": self.linked_at.isoformat(),
            "source": self.source,
            "previous_status": self.previous_status.value,
            "extension_warning": self.extension_warning,
        }


# ── Link Result ───────────────────────────────────────────────────────────────

@dataclass
class LinkResult:
    """Result of a link operation."""
    asset_id: str
    success: bool
    previous_status: Optional[AssetStatus] = None
    error: Optional[str] = None
    extension_warning: Optional[str] = None

    @property
    def has_warning(self) -> bool:
        return self.extension_warning is not None


# ── Asset Linker ──────────────────────────────────────────────────────────────

class AssetLinker:
    """
    Manages PLACEHOLDER → LINKED and MISSING → LINKED transitions.

    Always used instead of calling manifest.link() directly.
    Updates all downstream registries atomically.
    """

    def __init__(
        self,
        manifest: AssetManifest,
        placeholder_registry: PlaceholderRegistry,
    ) -> None:
        self._manifest = manifest
        self._placeholder_registry = placeholder_registry
        self._link_history: list[LinkRecord] = []

    # ── Single Link ───────────────────────────────────────────────────────

    def link(
        self,
        asset_id: str,
        resolved_path: str,
        source: str = "manual",
    ) -> LinkResult:
        """
        Links an asset to a resolved engine path.

        Args:
            asset_id: The asset to link.
            resolved_path: The engine-side file path.
            source: Where this link came from ("manual", "engine_feedback", "migration").

        Returns:
            LinkResult with success/failure details and any extension warnings.
        """
        if not resolved_path or not resolved_path.strip():
            return LinkResult(
                asset_id=asset_id,
                success=False,
                error="resolved_path must not be empty",
            )

        ref = self._manifest.get(asset_id)
        if ref is None:
            return LinkResult(
                asset_id=asset_id,
                success=False,
                error=f"asset_id '{asset_id}' not found in manifest",
            )

        if ref.status == AssetStatus.UNRESOLVED:
            return LinkResult(
                asset_id=asset_id,
                success=False,
                error=(
                    f"Cannot link UNRESOLVED asset '{asset_id}'. "
                    "It was never properly registered. Fix the registration bug first."
                ),
            )

        # Soft extension check — warn but do not block
        ext_warning = self._check_extension(resolved_path, ref.asset_type)

        previous_status = ref.status

        try:
            self._manifest.link(asset_id, resolved_path)
        except (KeyError, ValueError) as e:
            return LinkResult(
                asset_id=asset_id,
                success=False,
                error=str(e),
            )

        # Update placeholder registry if this was a placeholder
        if previous_status == AssetStatus.PLACEHOLDER:
            self._placeholder_registry.mark_linked(asset_id)

        # Record audit trail
        record = LinkRecord(
            asset_id=asset_id,
            asset_type=ref.asset_type,
            resolved_path=resolved_path,
            source=source,
            previous_status=previous_status,
            extension_warning=ext_warning,
        )
        self._link_history.append(record)

        return LinkResult(
            asset_id=asset_id,
            success=True,
            previous_status=previous_status,
            extension_warning=ext_warning,
        )

    # ── Bulk Link ─────────────────────────────────────────────────────────

    def link_bulk(
        self,
        links: dict[str, str],
        source: str = "engine_feedback",
    ) -> list[LinkResult]:
        """
        Links multiple assets in one call.

        Args:
            links: Dict of {asset_id: resolved_path}.
            source: Origin of this bulk link operation.

        Returns:
            List of LinkResult for each attempted link, in asset_id sorted order.
        """
        results = []
        for asset_id in sorted(links.keys()):  # sorted for determinism (D11)
            result = self.link(asset_id, links[asset_id], source=source)
            results.append(result)
        return results

    # ── Mark Missing ──────────────────────────────────────────────────────

    def mark_missing(self, asset_id: str) -> LinkResult:
        """
        Marks a LINKED asset as MISSING (file deleted or moved).
        Called by the engine feedback handler or file watcher.
        """
        ref = self._manifest.get(asset_id)
        if ref is None:
            return LinkResult(
                asset_id=asset_id,
                success=False,
                error=f"asset_id '{asset_id}' not found in manifest",
            )
        if ref.status != AssetStatus.LINKED:
            return LinkResult(
                asset_id=asset_id,
                success=False,
                error=(
                    f"Cannot mark '{asset_id}' as MISSING — "
                    f"current status is {ref.status.value}, expected LINKED"
                ),
            )

        try:
            self._manifest.mark_missing(asset_id)
        except (KeyError, ValueError) as e:
            return LinkResult(asset_id=asset_id, success=False, error=str(e))

        return LinkResult(
            asset_id=asset_id,
            success=True,
            previous_status=AssetStatus.LINKED,
        )

    # ── History ───────────────────────────────────────────────────────────

    def link_history(self) -> list[LinkRecord]:
        """Returns the full link audit trail, newest first."""
        return list(reversed(self._link_history))

    def history_for_asset(self, asset_id: str) -> list[LinkRecord]:
        """Returns all link records for a specific asset, newest first."""
        return [r for r in reversed(self._link_history) if r.asset_id == asset_id]

    def link_count(self) -> int:
        """Total number of successful link operations performed."""
        return sum(1 for r in self._link_history)

    # ── Internal ──────────────────────────────────────────────────────────

    def _check_extension(
        self, resolved_path: str, asset_type: AssetType
    ) -> Optional[str]:
        """
        Returns a warning string if the file extension doesn't match the type,
        or None if the extension is valid or unknown.
        """
        import os
        ext = os.path.splitext(resolved_path)[1].lower()
        if not ext:
            return None  # No extension — cannot validate, no warning
        valid = VALID_EXTENSIONS.get(asset_type, [])
        if valid and ext not in valid:
            return (
                f"File extension '{ext}' is unusual for {asset_type.value} assets. "
                f"Expected one of: {', '.join(valid)}"
            )
        return None
