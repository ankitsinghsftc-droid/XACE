//! # COMP_RENDER_V1
//!
//! The visual representation component. Tells the engine adapter what to
//! render for this entity — mesh, sprite, particle, or nothing.
//!
//! ## Why this is UCL Core
//! Every game has something to display. Even "invisible" entities like
//! trigger zones need a render component (set to invisible) so the engine
//! adapter has a complete picture of every entity's visual state.
//!
//! ## Asset References
//! Per Audit 2, asset references are NEVER raw strings. They are typed
//! AssetReference structs with a state (PLACEHOLDER/LINKED/MISSING/UNRESOLVED).
//! The engine adapter reads the state and handles each case appropriately.
//! UNRESOLVED references block CGS commit entirely (I12).
//!
//! ## Engine Responsibility
//! XACE stores and transmits render data. The engine performs actual rendering.
//! XACE never calls render APIs directly — Layer 7 responsibility only.

use serde::{Deserialize, Serialize};

/// Component type ID for COMP_RENDER_V1. Frozen forever.
pub const COMP_RENDER_V1_ID: u32 = 3;

// ── Asset Reference (Audit 2) ─────────────────────────────────────────────────

/// The state of an asset reference in the XACE asset pipeline.
///
/// Four states cover the complete lifecycle of any asset from
/// initial entity creation through full visual production.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum AssetStatus {
    /// Auto-created by XACE when an entity is first defined.
    /// No real asset file exists yet. Game logic runs normally.
    /// Visuals are blocked — engine renders a grey placeholder.
    /// This is the default state for all new asset references.
    Placeholder,

    /// A real asset file has been mapped to this reference.
    /// Engine can render it fully.
    Linked,

    /// Was linked, but the asset file can no longer be found.
    /// Warning state — not a blocker. Game continues running
    /// with a fallback visual until the asset is re-linked.
    Missing,

    /// Reference exists in CGS but was never registered in the asset pipeline.
    /// This is a bug. Blocks CGS commit entirely (I12, Global Invariant).
    /// Must be resolved before any schema mutation can be committed.
    Unresolved,
}

impl Default for AssetStatus {
    fn default() -> Self {
        AssetStatus::Placeholder
    }
}

/// The type of asset being referenced.
///
/// Determines how the engine adapter interprets and loads the asset.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum AssetType {
    Mesh,
    Texture,
    Material,
    AnimationController,
    AudioClip,
    AudioMusic,
    Sprite,
    Particle,
    Prefab,
    Font,
}

/// A typed, tracked reference to an external asset.
///
/// Never a raw string. Always carries its type and current pipeline status.
/// Auto-named by convention: `[entity_type]_[entity_name]_[asset_type]_v[N]`
/// Example: `character_knight_mesh_v1`, `enemy_dragon_roar_sfx_v1`
///
/// The asset registry (Phase 7) manages the mapping from this ID
/// to actual file paths on disk or in the engine's asset database.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AssetReference {
    /// Unique identifier for this asset. Follows auto-naming convention.
    pub id: String,

    /// What kind of asset this reference points to.
    pub asset_type: AssetType,

    /// Current state in the asset pipeline.
    pub status: AssetStatus,
}

impl AssetReference {
    /// Creates a new asset reference in Placeholder state.
    /// This is the correct way to create any new asset reference —
    /// always starts as Placeholder, never as Linked or Unresolved.
    pub fn placeholder(id: impl Into<String>, asset_type: AssetType) -> Self {
        Self {
            id: id.into(),
            asset_type,
            status: AssetStatus::Placeholder,
        }
    }

    /// Returns true if this reference is safe to commit to CGS.
    /// Unresolved references block commit (I12).
    pub fn is_committable(&self) -> bool {
        !matches!(self.status, AssetStatus::Unresolved)
    }

    /// Returns true if the engine can render this asset right now.
    pub fn is_renderable(&self) -> bool {
        matches!(self.status, AssetStatus::Linked)
    }
}

// ── Render Type ───────────────────────────────────────────────────────────────

/// How this entity should be rendered by the engine.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum RenderType {
    /// A 3D mesh asset. Most common for 3D games.
    Mesh3D,
    /// A 2D sprite. Used for 2D games or billboard elements.
    Sprite2D,
    /// A particle system effect (fire, smoke, sparks, etc.)
    ParticleEffect,
    /// No visual representation. Entity exists logically only.
    /// Used for trigger zones, controllers, and logical entities.
    Invisible,
    /// A UI element rendered in world space.
    WorldSpaceUi,
}

impl Default for RenderType {
    fn default() -> Self {
        RenderType::Mesh3D
    }
}

// ── Render Layer ──────────────────────────────────────────────────────────────

/// Render layer for draw order control.
///
/// Lower values render first (behind). Higher values render on top.
/// Engine adapter maps these to engine-specific layer systems.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub struct RenderLayer(pub i32);

impl RenderLayer {
    pub const BACKGROUND: RenderLayer = RenderLayer(-100);
    pub const DEFAULT: RenderLayer    = RenderLayer(0);
    pub const FOREGROUND: RenderLayer = RenderLayer(100);
    pub const UI: RenderLayer         = RenderLayer(1000);
}

impl Default for RenderLayer {
    fn default() -> Self {
        RenderLayer::DEFAULT
    }
}

// ── Component ─────────────────────────────────────────────────────────────────

/// COMP_RENDER_V1 — Visual representation of an entity.
///
/// UCL Core component. Tells the engine adapter exactly what to render,
/// how to render it, and whether it should cast shadows or be visible at all.
///
/// The engine adapter reads this component each tick via the StateDelta
/// and updates the engine scene accordingly. XACE never calls render APIs.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RenderComponent {
    /// How this entity should be rendered.
    pub render_type: RenderType,

    /// Reference to the primary visual asset (mesh, sprite, particle).
    /// Always a typed AssetReference — never a raw string (Audit 2).
    /// Starts as Placeholder when entity is first created.
    pub asset_reference: AssetReference,

    /// Reference to the material applied to the asset.
    /// None means use the asset's default material.
    pub material_ref: Option<AssetReference>,

    /// Whether this entity is currently visible.
    /// False = entity exists but engine renders nothing.
    /// Systems can toggle this without destroying the entity.
    pub visible: bool,

    /// Whether this entity casts shadows in the engine.
    /// Only relevant when render_type is Mesh3D.
    pub cast_shadows: bool,

    /// Render layer controlling draw order.
    pub layer: RenderLayer,

    /// Render order within the same layer.
    /// Higher values render on top of lower values within the same layer.
    pub render_order: i32,
}

impl RenderComponent {
    /// Creates a visible 3D mesh render component with a placeholder asset.
    ///
    /// `asset_id` should follow the auto-naming convention:
    /// `[entity_type]_[entity_name]_mesh_v1`
    pub fn mesh(asset_id: impl Into<String>) -> Self {
        Self {
            render_type: RenderType::Mesh3D,
            asset_reference: AssetReference::placeholder(asset_id, AssetType::Mesh),
            material_ref: None,
            visible: true,
            cast_shadows: true,
            layer: RenderLayer::DEFAULT,
            render_order: 0,
        }
    }

    /// Creates a visible 2D sprite render component with a placeholder asset.
    pub fn sprite(asset_id: impl Into<String>) -> Self {
        Self {
            render_type: RenderType::Sprite2D,
            asset_reference: AssetReference::placeholder(asset_id, AssetType::Sprite),
            material_ref: None,
            visible: true,
            cast_shadows: false,
            layer: RenderLayer::DEFAULT,
            render_order: 0,
        }
    }

    /// Creates an invisible render component.
    /// Used for logical entities like trigger zones and controllers.
    /// Still needs a render component so the engine adapter has a
    /// complete record of every entity's visual state.
    pub fn invisible() -> Self {
        Self {
            render_type: RenderType::Invisible,
            asset_reference: AssetReference::placeholder(
                "none", AssetType::Mesh
            ),
            material_ref: None,
            visible: false,
            cast_shadows: false,
            layer: RenderLayer::DEFAULT,
            render_order: 0,
        }
    }

    /// Returns true if this component has any unresolved asset references.
    /// Unresolved references block CGS commit (I12).
    pub fn has_unresolved_refs(&self) -> bool {
        !self.asset_reference.is_committable()
            || self.material_ref
                .as_ref()
                .map(|r| !r.is_committable())
                .unwrap_or(false)
    }
}

impl Default for RenderComponent {
    fn default() -> Self {
        Self::invisible()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mesh_component_starts_as_placeholder() {
        let r = RenderComponent::mesh("player_knight_mesh_v1");
        assert_eq!(r.asset_reference.status, AssetStatus::Placeholder);
        assert!(!r.asset_reference.is_renderable());
        assert!(r.asset_reference.is_committable());
    }

    #[test]
    fn invisible_component_not_visible() {
        let r = RenderComponent::invisible();
        assert!(!r.visible);
        assert_eq!(r.render_type, RenderType::Invisible);
    }

    #[test]
    fn unresolved_ref_blocks_commit() {
        let mut r = RenderComponent::mesh("test_mesh_v1");
        r.asset_reference.status = AssetStatus::Unresolved;
        assert!(r.has_unresolved_refs());
        assert!(!r.asset_reference.is_committable());
    }

    #[test]
    fn linked_ref_is_renderable() {
        let mut r = RenderComponent::mesh("test_mesh_v1");
        r.asset_reference.status = AssetStatus::Linked;
        assert!(r.asset_reference.is_renderable());
        assert!(r.asset_reference.is_committable());
    }

    #[test]
    fn missing_ref_is_committable_but_not_renderable() {
        let mut r = RenderComponent::mesh("test_mesh_v1");
        r.asset_reference.status = AssetStatus::Missing;
        assert!(r.asset_reference.is_committable());
        assert!(!r.asset_reference.is_renderable());
    }

    #[test]
    fn render_layer_ordering() {
        assert!(RenderLayer::BACKGROUND < RenderLayer::DEFAULT);
        assert!(RenderLayer::DEFAULT < RenderLayer::FOREGROUND);
        assert!(RenderLayer::FOREGROUND < RenderLayer::UI);
    }

    #[test]
    fn sprite_does_not_cast_shadows() {
        let r = RenderComponent::sprite("ui_healthbar_sprite_v1");
        assert!(!r.cast_shadows);
    }
}