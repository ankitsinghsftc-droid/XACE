"""
asset_reference.py — Python-side AssetReference struct (Audit 2).

Mirrors packages/core/src/assets/asset_reference.rs exactly.
Every asset reference in the CGS and Asset Registry uses this struct —
NEVER a raw string.

## Why Typed References (Audit 2)
Raw strings like "character_knight_mesh_v1" cannot be validated, tracked,
or status-checked. A typed AssetReference carries:
  - A unique asset_id (the canonical name, never changes after assignment)
  - The AssetType (what kind of asset this is)
  - The AssetStatus (PLACEHOLDER / LINKED / MISSING / UNRESOLVED)
  - Optionally, the resolved_path (the engine-side file path when LINKED)

The Asset Registry holds the authoritative AssetReference for each asset_id.
The CGS stores only the asset_id string — the full reference is resolved
through the registry at validation time.

## Serialization
AssetReference serializes to/from a JSON dict with four keys:
  {"asset_id": str, "asset_type": str, "status": str, "resolved_path": str|null}

This is the format used in CGS snapshots and feedback payloads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from asset_type_enum import AssetType
from asset_status_enum import AssetStatus


@dataclass
class AssetReference:
    """
    A typed, trackable reference to an engine asset.

    ## Immutable Fields
    asset_id and asset_type are set at creation and never change.
    Status and resolved_path are mutable — they change as the asset
    moves through its lifecycle.

    ## Naming Convention (Audit 2)
    asset_id follows the pattern: [entity_type]_[entity_name]_[asset_type]_v[N]
    Examples: character_knight_mesh_v1, enemy_dragon_roar_sfx_v1
    Use AssetNamingPolicy.generate() to produce canonical IDs.
    """

    # Unique identifier — follows naming convention, never reused
    asset_id: str

    # What kind of asset this is — immutable after creation
    asset_type: AssetType

    # Current lifecycle state
    status: AssetStatus = field(default=AssetStatus.PLACEHOLDER)

    # Engine-side file path — only populated when status == LINKED
    resolved_path: Optional[str] = field(default=None)

    # ── Validation ────────────────────────────────────────────────────────

    def __post_init__(self) -> None:
        if not self.asset_id:
            raise ValueError("AssetReference: asset_id must not be empty")
        if not self.asset_id.replace("_", "").replace("-", "").replace(".", "").isalnum():
            raise ValueError(
                f"AssetReference: asset_id '{self.asset_id}' contains invalid characters. "
                "Use only letters, digits, underscores, hyphens, and dots."
            )
        if self.status == AssetStatus.LINKED and not self.resolved_path:
            raise ValueError(
                f"AssetReference '{self.asset_id}': status is LINKED but resolved_path is None. "
                "A LINKED asset must have a resolved_path."
            )
        if self.status != AssetStatus.LINKED and self.resolved_path is not None:
            raise ValueError(
                f"AssetReference '{self.asset_id}': resolved_path is set but status is "
                f"{self.status.value}. Only LINKED assets carry a resolved_path."
            )

    # ── Status Transitions ────────────────────────────────────────────────

    def link(self, resolved_path: str) -> None:
        """
        Transitions this reference from PLACEHOLDER or MISSING to LINKED.

        Raises ValueError if:
        - resolved_path is empty
        - status is UNRESOLVED (cannot be resolved this way — it's a bug)
        """
        if not resolved_path:
            raise ValueError(
                f"AssetReference.link(): resolved_path must not be empty "
                f"for asset '{self.asset_id}'"
            )
        if self.status == AssetStatus.UNRESOLVED:
            raise ValueError(
                f"AssetReference '{self.asset_id}' is UNRESOLVED — it was never "
                "registered. Fix the registration bug before linking."
            )
        self.status = AssetStatus.LINKED
        self.resolved_path = resolved_path

    def mark_missing(self) -> None:
        """
        Transitions this reference from LINKED to MISSING.
        Called when the linked file can no longer be found.
        """
        if self.status != AssetStatus.LINKED:
            raise ValueError(
                f"AssetReference.mark_missing(): asset '{self.asset_id}' "
                f"is not LINKED (current status: {self.status.value})"
            )
        self.status = AssetStatus.MISSING
        self.resolved_path = None

    def revert_to_placeholder(self) -> None:
        """
        Resets this reference back to PLACEHOLDER.
        Used when an asset link is intentionally removed.
        """
        self.status = AssetStatus.PLACEHOLDER
        self.resolved_path = None

    # ── Classification ────────────────────────────────────────────────────

    @property
    def is_placeholder(self) -> bool:
        return self.status == AssetStatus.PLACEHOLDER

    @property
    def is_linked(self) -> bool:
        return self.status == AssetStatus.LINKED

    @property
    def is_missing(self) -> bool:
        return self.status == AssetStatus.MISSING

    @property
    def is_unresolved(self) -> bool:
        return self.status == AssetStatus.UNRESOLVED

    @property
    def blocks_cgs_commit(self) -> bool:
        """True if this reference blocks CGS commit (I12). Only UNRESOLVED does."""
        return self.status.blocks_cgs_commit

    @property
    def is_renderable(self) -> bool:
        """True if the engine can render/play this asset."""
        return self.status.is_renderable

    # ── Serialization ─────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """
        Serializes to a JSON-compatible dict.
        Format: {"asset_id": str, "asset_type": str, "status": str, "resolved_path": str|null}
        """
        return {
            "asset_id": self.asset_id,
            "asset_type": self.asset_type.value,
            "status": self.status.value,
            "resolved_path": self.resolved_path,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AssetReference":
        """
        Deserializes from a JSON-compatible dict.
        Raises ValueError if required fields are missing or invalid.
        """
        required = {"asset_id", "asset_type", "status"}
        missing = required - data.keys()
        if missing:
            raise ValueError(
                f"AssetReference.from_dict(): missing required fields: {missing}"
            )
        return cls(
            asset_id=data["asset_id"],
            asset_type=AssetType.from_string(data["asset_type"]),
            status=AssetStatus.from_string(data["status"]),
            resolved_path=data.get("resolved_path"),
        )

    @classmethod
    def make_placeholder(cls, asset_id: str, asset_type: AssetType) -> "AssetReference":
        """
        Creates a new PLACEHOLDER AssetReference.
        This is the correct factory for auto-registration (Audit 2 zero-experience flow).
        """
        return cls(asset_id=asset_id, asset_type=asset_type, status=AssetStatus.PLACEHOLDER)

    @classmethod
    def make_unresolved(cls, asset_id: str, asset_type: AssetType) -> "AssetReference":
        """
        Creates an UNRESOLVED AssetReference.
        Only used when a CGS reference is detected that was never registered.
        """
        return cls(asset_id=asset_id, asset_type=asset_type, status=AssetStatus.UNRESOLVED)

    def __repr__(self) -> str:
        path_part = f", path='{self.resolved_path}'" if self.resolved_path else ""
        return (
            f"AssetReference(id='{self.asset_id}', "
            f"type={self.asset_type.value}, "
            f"status={self.status.value}{path_part})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AssetReference):
            return NotImplemented
        return self.asset_id == other.asset_id

    def __hash__(self) -> int:
        return hash(self.asset_id)