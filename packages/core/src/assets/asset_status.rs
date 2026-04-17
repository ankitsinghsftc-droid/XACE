//! # Asset Status
//!
//! Defines the four possible states of an asset reference in the
//! XACE asset pipeline. Every AssetReference carries one of these
//! states at all times.
//!
//! ## The Four States
//! PLACEHOLDER → the default. Auto-created. No real file yet.
//! LINKED      → a real file is mapped. Engine can render it.
//! MISSING     → was linked, file no longer found. Warning only.
//! UNRESOLVED  → referenced in schema but never registered. Bug. Blocks commit.
//!
//! ## Zero-Experience Flow (Audit 2)
//! When a zero-experience user creates an entity, XACE auto-creates
//! all asset references as PLACEHOLDER. The game runs immediately —
//! entities appear as grey boxes. The builder UI shows:
//! "7 assets are placeholders — game runs but looks like grey boxes"
//! The user can build all game logic first, then link visuals when ready.
//! This is intentional — logic first, assets second.
//!
//! ## Global Invariant I12
//! UNRESOLVED references must never enter a committed CGS.
//! Schema Factory checks every asset reference before commit.
//! If any reference is UNRESOLVED, the commit is blocked entirely.

use serde::{Deserialize, Serialize};

// ── Asset Status ──────────────────────────────────────────────────────────────

/// The current state of an asset reference in the XACE asset pipeline.
///
/// Drives how the engine adapter handles each asset reference per tick.
/// Also drives the builder UI asset status panel display.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum AssetStatus {
    /// Auto-created by XACE when an entity is first defined.
    ///
    /// No real asset file exists yet. Game logic runs normally.
    /// The engine adapter renders a grey placeholder visual.
    /// This is the correct starting state for all new asset references.
    ///
    /// Transition: Placeholder → Linked (when Asset Linker maps a file)
    /// Committable: YES
    Placeholder,

    /// A real asset file has been successfully mapped to this reference.
    ///
    /// The engine adapter can load and render this asset fully.
    /// This is the production-ready state.
    ///
    /// Transition: Linked → Missing (if file is moved or deleted)
    /// Committable: YES
    /// Renderable: YES
    Linked,

    /// This reference was previously Linked but the file can no longer be found.
    ///
    /// The asset file was moved, renamed, or deleted after being linked.
    /// This is a warning state — not a blocker. The game continues running
    /// with a fallback visual (grey box) until the file is re-linked.
    /// The builder UI shows a warning icon on missing assets.
    ///
    /// Transition: Missing → Linked (when file is re-linked)
    /// Committable: YES
    /// Renderable: NO
    Missing,

    /// This reference exists in the CGS but was never registered
    /// in the asset pipeline.
    ///
    /// This is a bug state — it means a component field references an
    /// asset ID that the Asset Registry has never seen. This should never
    /// happen in normal usage — it indicates a schema corruption or a
    /// manually edited CGS file with invalid asset IDs.
    ///
    /// Blocks CGS commit entirely (I12, Global Invariant).
    /// The Schema Factory rejects any CGS containing UNRESOLVED references.
    ///
    /// Transition: Unresolved → Placeholder (when registered in asset pipeline)
    /// Committable: NO — blocks commit
    /// Renderable: NO
    Unresolved,
}

impl AssetStatus {
    /// Returns true if a CGS commit is allowed with this status.
    ///
    /// Only UNRESOLVED blocks commit (I12).
    /// Placeholder, Linked, and Missing are all safe to commit —
    /// they represent known, handled states in the pipeline.
    pub fn is_committable(&self) -> bool {
        !matches!(self, AssetStatus::Unresolved)
    }

    /// Returns true if the engine can render this asset right now.
    /// Only Linked assets have a real file the engine can load.
    pub fn is_renderable(&self) -> bool {
        matches!(self, AssetStatus::Linked)
    }

    /// Returns true if this status represents a problem that needs attention.
    /// Missing and Unresolved both need user action to resolve.
    pub fn needs_attention(&self) -> bool {
        matches!(self, AssetStatus::Missing | AssetStatus::Unresolved)
    }

    /// Returns true if this is a blocking problem.
    /// Only Unresolved is a hard blocker — Missing is a warning.
    pub fn is_blocking(&self) -> bool {
        matches!(self, AssetStatus::Unresolved)
    }

    /// Returns the builder UI display label for this status.
    /// Used in the asset status panel and asset reference tooltips.
    pub fn display_label(&self) -> &'static str {
        match self {
            AssetStatus::Placeholder => "Placeholder",
            AssetStatus::Linked => "Linked",
            AssetStatus::Missing => "Missing",
            AssetStatus::Unresolved => "Unresolved",
        }
    }

    /// Returns a short user-facing message explaining this status.
    /// Written in plain English — zero technical vocabulary (NLTL principle).
    pub fn user_message(&self) -> &'static str {
        match self {
            AssetStatus::Placeholder =>
                "No visual asset linked yet. Game runs but shows a grey box.",
            AssetStatus::Linked =>
                "Asset linked and ready. Engine can render this.",
            AssetStatus::Missing =>
                "Asset file was moved or deleted. Re-link to restore visuals.",
            AssetStatus::Unresolved =>
                "Asset reference is broken. This must be fixed before saving.",
        }
    }

    /// Returns the severity level of this status for UI prioritization.
    /// Higher number = more urgent.
    /// 0 = fine, 1 = info, 2 = warning, 3 = error
    pub fn severity(&self) -> u8 {
        match self {
            AssetStatus::Linked => 0,
            AssetStatus::Placeholder => 1,
            AssetStatus::Missing => 2,
            AssetStatus::Unresolved => 3,
        }
    }
}

impl std::fmt::Display for AssetStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.display_label())
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn placeholder_is_committable() {
        assert!(AssetStatus::Placeholder.is_committable());
    }

    #[test]
    fn linked_is_committable_and_renderable() {
        assert!(AssetStatus::Linked.is_committable());
        assert!(AssetStatus::Linked.is_renderable());
    }

    #[test]
    fn missing_is_committable_not_renderable() {
        assert!(AssetStatus::Missing.is_committable());
        assert!(!AssetStatus::Missing.is_renderable());
    }

    #[test]
    fn unresolved_blocks_commit() {
        assert!(!AssetStatus::Unresolved.is_committable());
        assert!(!AssetStatus::Unresolved.is_renderable());
    }

    #[test]
    fn only_linked_is_renderable() {
        assert!(!AssetStatus::Placeholder.is_renderable());
        assert!(AssetStatus::Linked.is_renderable());
        assert!(!AssetStatus::Missing.is_renderable());
        assert!(!AssetStatus::Unresolved.is_renderable());
    }

    #[test]
    fn needs_attention_correct() {
        assert!(!AssetStatus::Placeholder.needs_attention());
        assert!(!AssetStatus::Linked.needs_attention());
        assert!(AssetStatus::Missing.needs_attention());
        assert!(AssetStatus::Unresolved.needs_attention());
    }

    #[test]
    fn only_unresolved_is_blocking() {
        assert!(!AssetStatus::Placeholder.is_blocking());
        assert!(!AssetStatus::Linked.is_blocking());
        assert!(!AssetStatus::Missing.is_blocking());
        assert!(AssetStatus::Unresolved.is_blocking());
    }

    #[test]
    fn severity_ordering_correct() {
        assert!(AssetStatus::Linked.severity() < AssetStatus::Placeholder.severity());
        assert!(AssetStatus::Placeholder.severity() < AssetStatus::Missing.severity());
        assert!(AssetStatus::Missing.severity() < AssetStatus::Unresolved.severity());
    }

    #[test]
    fn display_labels_correct() {
        assert_eq!(AssetStatus::Placeholder.to_string(), "Placeholder");
        assert_eq!(AssetStatus::Linked.to_string(), "Linked");
        assert_eq!(AssetStatus::Missing.to_string(), "Missing");
        assert_eq!(AssetStatus::Unresolved.to_string(), "Unresolved");
    }

    #[test]
    fn user_messages_not_empty() {
        assert!(!AssetStatus::Placeholder.user_message().is_empty());
        assert!(!AssetStatus::Linked.user_message().is_empty());
        assert!(!AssetStatus::Missing.user_message().is_empty());
        assert!(!AssetStatus::Unresolved.user_message().is_empty());
    }
}