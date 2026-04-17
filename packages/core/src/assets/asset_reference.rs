//! # Asset Reference
//!
//! The typed asset reference struct used everywhere in XACE.
//! Per Audit 2 — asset references are NEVER raw strings.
//! Always a typed AssetReference with a known status.
//!
//! ## Why Typed References
//! Raw strings break at runtime with no warning — a typo in an asset
//! path only fails when the engine tries to load it. Typed references
//! with explicit status (PLACEHOLDER/LINKED/MISSING/UNRESOLVED) make
//! asset state visible at the schema level, not just at load time.
//!
//! ## Auto-Naming Convention
//! Asset IDs follow a strict convention:
//! [entity_type]_[entity_name]_[asset_type]_v[N]
//! Examples:
//!   character_knight_mesh_v1
//!   enemy_dragon_roar_sfx_v1
//!   prop_chest_texture_v1
//!
//! This convention is enforced by the Asset Registry (Phase 7).
//! The AssetReference struct stores the ID — validation happens upstream.
//!
//! ## Global Invariant I12
//! UNRESOLVED asset references must never enter a committed CGS.
//! The Schema Factory validates this before every commit.
//! An UNRESOLVED reference means the asset was referenced in a schema
//! definition but never registered in the asset pipeline — this is a bug.

use serde::{Deserialize, Serialize};
use crate::assets::asset_type::AssetType;
use crate::assets::asset_status::AssetStatus;

// ── Asset Reference ───────────────────────────────────────────────────────────

/// A typed, tracked reference to an external asset.
///
/// Used everywhere an asset is referenced in XACE — component fields,
/// schema definitions, blueprint declarations. Never a raw string.
///
/// ## Lifecycle
/// UNRESOLVED → PLACEHOLDER → LINKED | MISSING
///
/// New entities start with PLACEHOLDER references auto-created by XACE.
/// The asset pipeline transitions them to LINKED when real files are mapped.
/// MISSING means a previously linked file can no longer be found.
/// UNRESOLVED blocks CGS commit entirely (I12).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AssetReference {
    /// Unique identifier for this asset.
    /// Follows auto-naming convention: [entity_type]_[name]_[type]_v[N]
    /// Assigned by the Asset Registry — never set manually.
    pub id: String,

    /// What kind of asset this reference points to.
    /// Determines how the engine adapter loads and uses the asset.
    pub asset_type: AssetType,

    /// Current state in the asset pipeline.
    /// Drives how the engine adapter handles this reference each tick.
    pub status: AssetStatus,
}

impl AssetReference {
    /// Creates a new asset reference in Placeholder state.
    ///
    /// This is the correct and only way to create a new asset reference.
    /// All new references start as Placeholder — never as Linked or Unresolved.
    /// The asset pipeline transitions status from Placeholder to Linked
    /// when a real file is mapped via the Asset Linker (Phase 7).
    pub fn placeholder(id: impl Into<String>, asset_type: AssetType) -> Self {
        Self {
            id: id.into(),
            asset_type,
            status: AssetStatus::Placeholder,
        }
    }

    /// Creates a linked asset reference pointing to a real asset.
    ///
    /// Only the Asset Linker (Phase 7) should call this — not game systems.
    /// Used when importing existing projects that already have assets mapped.
    pub fn linked(id: impl Into<String>, asset_type: AssetType) -> Self {
        Self {
            id: id.into(),
            asset_type,
            status: AssetStatus::Linked,
        }
    }

    /// Creates a sentinel "none" reference for fields that have no asset.
    ///
    /// Used for optional asset fields like `material_ref` in RenderComponent
    /// when no material override is needed. Distinct from Placeholder —
    /// "none" means intentionally empty, not "pending a real asset."
    pub fn none() -> Self {
        Self {
            id: "none".into(),
            asset_type: AssetType::Mesh,
            status: AssetStatus::Placeholder,
        }
    }

    /// Returns true if this reference is safe to commit to CGS.
    ///
    /// Only UNRESOLVED references block commit (I12).
    /// Placeholder, Linked, and Missing are all committable —
    /// they represent known states in the asset pipeline.
    pub fn is_committable(&self) -> bool {
        !matches!(self.status, AssetStatus::Unresolved)
    }

    /// Returns true if the engine can render this asset right now.
    /// Only Linked references have a real file the engine can load.
    pub fn is_renderable(&self) -> bool {
        matches!(self.status, AssetStatus::Linked)
    }

    /// Returns true if this reference is in Placeholder state.
    /// Placeholder = auto-created, no real file yet, game logic works.
    pub fn is_placeholder(&self) -> bool {
        matches!(self.status, AssetStatus::Placeholder)
    }

    /// Returns true if this reference is missing its linked file.
    /// Missing = was linked, file no longer found. Warning, not blocker.
    pub fn is_missing(&self) -> bool {
        matches!(self.status, AssetStatus::Missing)
    }

    /// Returns true if this reference is unresolved.
    /// Unresolved = referenced in schema but never registered. Bug. Blocks commit.
    pub fn is_unresolved(&self) -> bool {
        matches!(self.status, AssetStatus::Unresolved)
    }

    /// Transitions this reference to Linked state.
    /// Called by the Asset Linker when a real file is mapped to this ID.
    pub fn mark_linked(&mut self) {
        self.status = AssetStatus::Linked;
    }

    /// Transitions this reference to Missing state.
    /// Called by the Asset Validator when a previously linked file is not found.
    pub fn mark_missing(&mut self) {
        self.status = AssetStatus::Missing;
    }

    /// Transitions this reference to Unresolved state.
    /// Called by the Asset Validator when a reference is found in the schema
    /// but has never been registered in the asset pipeline.
    pub fn mark_unresolved(&mut self) {
        self.status = AssetStatus::Unresolved;
    }
}

impl std::fmt::Display for AssetReference {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}[{:?}]({:?})", self.id, self.asset_type, self.status)
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn placeholder_starts_as_placeholder() {
        let r = AssetReference::placeholder(
            "character_knight_mesh_v1",
            AssetType::Mesh
        );
        assert!(r.is_placeholder());
        assert!(!r.is_renderable());
        assert!(r.is_committable());
        assert!(!r.is_unresolved());
    }

    #[test]
    fn linked_reference_is_renderable() {
        let r = AssetReference::linked("character_knight_mesh_v1", AssetType::Mesh);
        assert!(r.is_renderable());
        assert!(r.is_committable());
        assert!(!r.is_placeholder());
    }

    #[test]
    fn unresolved_blocks_commit() {
        let mut r = AssetReference::placeholder("bad_ref", AssetType::Texture);
        r.mark_unresolved();
        assert!(r.is_unresolved());
        assert!(!r.is_committable());
    }

    #[test]
    fn missing_is_committable_not_renderable() {
        let mut r = AssetReference::linked("old_asset_v1", AssetType::AudioClip);
        r.mark_missing();
        assert!(r.is_missing());
        assert!(r.is_committable());
        assert!(!r.is_renderable());
    }

    #[test]
    fn mark_linked_transitions_from_placeholder() {
        let mut r = AssetReference::placeholder("mesh_v1", AssetType::Mesh);
        r.mark_linked();
        assert!(r.is_renderable());
        assert!(!r.is_placeholder());
    }

    #[test]
    fn none_reference_is_committable() {
        let r = AssetReference::none();
        assert!(r.is_committable());
        assert_eq!(r.id, "none");
    }

    #[test]
    fn display_includes_id_and_status() {
        let r = AssetReference::placeholder("knight_mesh_v1", AssetType::Mesh);
        let display = r.to_string();
        assert!(display.contains("knight_mesh_v1"));
    }

    #[test]
    fn asset_type_preserved() {
        let r = AssetReference::placeholder("sfx_v1", AssetType::AudioClip);
        assert_eq!(r.asset_type, AssetType::AudioClip);
    }
}