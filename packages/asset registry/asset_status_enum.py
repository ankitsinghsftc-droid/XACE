"""
asset_status_enum.py — AssetStatus enumeration for the XACE Asset Registry.

Mirrors packages/core/src/assets/asset_status_enum.rs exactly.
Every AssetReference carries one of these four states at all times.

## The Four States (Audit 2)

PLACEHOLDER → The asset exists in the registry but no real file has been
  linked yet. Game logic runs. Engine renders nothing (grey box / silence).
  This is the correct starting state for all auto-registered references.

LINKED → A real engine asset file has been mapped to this reference.
  The engine can render/play it. This is the healthy production state.

MISSING → The reference was previously LINKED but the file can no longer
  be found (deleted, renamed, moved). Warning — not a blocker. The engine
  falls back to placeholder rendering. The designer must re-link.

UNRESOLVED → A reference appears in the CGS but was never registered in
  the Asset Registry. This is a bug — it means the CGS was mutated without
  going through the proper auto-registration flow. UNRESOLVED references
  BLOCK CGS commit (Global Invariant I12).

## State Transitions
```
                 register()
  (new ref) ──────────────────→ PLACEHOLDER
                                     │
                    asset_linker      │ link(path)
                    confirms file ────┘
                                     │
                                     ↓
                                  LINKED ←─── re-link after MISSING
                                     │
                    file deleted      │
                    or moved ─────────┘
                                     │
                                     ↓
                                  MISSING
```
UNRESOLVED never transitions to another state — it is an error condition
that must be resolved by the developer who introduced the invalid mutation.
"""

from enum import Enum


class AssetStatus(str, Enum):
    """
    The lifecycle state of an asset reference.

    String values are the canonical serialization used in CGS JSON.
    """

    PLACEHOLDER = "PLACEHOLDER"
    """
    Auto-created by XACE when an entity is defined.
    No real asset file linked. Game logic works; visuals/audio blocked.
    The builder UI displays: "N assets are placeholders — game runs but
    looks like grey boxes."
    """

    LINKED = "LINKED"
    """
    A real engine asset file is mapped to this reference.
    Engine can render or play it. This is the healthy production state.
    """

    MISSING = "MISSING"
    """
    Previously LINKED but the file can no longer be found.
    Warning only — not a blocker for CGS commit.
    Engine falls back to placeholder rendering.
    Designer must re-link.
    """

    UNRESOLVED = "UNRESOLVED"
    """
    Reference exists in CGS but was never registered in the Asset Registry.
    This is a bug — always blocks CGS commit (I12).
    Must be resolved before any schema mutation can be committed.
    """

    # ── Classification Properties ──────────────────────────────────────────

    @property
    def blocks_cgs_commit(self) -> bool:
        """
        Returns True if an asset in this state blocks CGS commit.
        Only UNRESOLVED blocks commit (I12).
        """
        return self == AssetStatus.UNRESOLVED

    @property
    def is_renderable(self) -> bool:
        """
        Returns True if the engine can render/play this asset.
        Only LINKED assets are renderable.
        """
        return self == AssetStatus.LINKED

    @property
    def is_error_state(self) -> bool:
        """
        Returns True if this status represents an error condition.
        UNRESOLVED is a bug. MISSING is a warning.
        """
        return self == AssetStatus.UNRESOLVED

    @property
    def is_warning_state(self) -> bool:
        """Returns True if this status requires designer attention."""
        return self == AssetStatus.MISSING

    @property
    def builder_ui_label(self) -> str:
        """Short label for the builder UI asset status panel."""
        labels = {
            AssetStatus.PLACEHOLDER: "Placeholder",
            AssetStatus.LINKED: "Linked ✓",
            AssetStatus.MISSING: "Missing ⚠",
            AssetStatus.UNRESOLVED: "Unresolved ✗",
        }
        return labels[self]

    @property
    def builder_ui_description(self) -> str:
        """Detailed description for the builder UI tooltip."""
        descriptions = {
            AssetStatus.PLACEHOLDER: (
                "No asset linked yet. Game logic works but this will render "
                "as a grey box or play as silence. Link a real asset when ready."
            ),
            AssetStatus.LINKED: (
                "Asset is linked and the engine can render or play it."
            ),
            AssetStatus.MISSING: (
                "This asset was previously linked but the file can no longer "
                "be found. Re-link it or the engine will fall back to placeholder."
            ),
            AssetStatus.UNRESOLVED: (
                "This reference exists in your game design but was never "
                "registered. This is a bug — fix it before saving."
            ),
        }
        return descriptions[self]

    @classmethod
    def from_string(cls, value: str) -> "AssetStatus":
        """Parses AssetStatus from string. Raises ValueError for unknown values."""
        try:
            return cls(value.upper())
        except ValueError:
            raise ValueError(
                f"Unknown AssetStatus: '{value}'. "
                f"Valid states: {[s.value for s in cls]}"
            )

    @classmethod
    def healthy_states(cls) -> list["AssetStatus"]:
        """Returns states that do not require designer action."""
        return [cls.PLACEHOLDER, cls.LINKED]

    @classmethod
    def problem_states(cls) -> list["AssetStatus"]:
        """Returns states that require designer attention."""
        return [cls.MISSING, cls.UNRESOLVED]