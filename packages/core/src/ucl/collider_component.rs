//! # COMP_COLLIDER_V1
//!
//! The physical boundary component. Defines the shape used for collision
//! detection between entities. Every entity that participates in physics
//! or overlap detection needs this component.
//!
//! ## Why this is UCL Core
//! Collision is fundamental to every game genre — platformers need ground
//! detection, shooters need hit detection, RPGs need interaction ranges,
//! puzzle games need object overlap. No genre escapes the need for
//! physical boundaries.
//!
//! ## Engine Responsibility
//! XACE defines collision shape and properties. The engine performs
//! actual collision detection and reports results back via the
//! Engine Feedback Protocol (Phase 7). XACE never runs physics itself.

use serde::{Deserialize, Serialize};

/// Component type ID for COMP_COLLIDER_V1. Frozen forever.
pub const COMP_COLLIDER_V1_ID: u32 = 4;

// ── Collider Shape ────────────────────────────────────────────────────────────

/// The geometric shape used for collision detection.
///
/// Simpler shapes (Sphere, Capsule) are faster to compute.
/// Box is the most common. Mesh is most accurate but most expensive.
/// The engine adapter maps these to engine-specific collision primitives.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum ColliderShape {
    /// Axis-aligned box. Most common shape. Fast collision detection.
    /// `size` in ColliderComponent defines half-extents (x, y, z).
    Box,

    /// Sphere. Fastest collision detection.
    /// Only `size.x` is used as the radius — y and z are ignored.
    Sphere,

    /// Capsule (cylinder with hemispherical caps). Common for characters.
    /// `size.x` = radius, `size.y` = half-height of the cylindrical part.
    Capsule,

    /// Convex hull around a mesh. More accurate than Box, slower than primitives.
    /// Requires a mesh asset — engine generates the hull automatically.
    ConvexHull,

    /// Exact mesh collision. Most accurate, most expensive.
    /// Only use for static geometry (terrain, walls). Never for moving entities.
    Mesh,
}

impl Default for ColliderShape {
    fn default() -> Self {
        ColliderShape::Box
    }
}

// ── Physics Material ──────────────────────────────────────────────────────────

/// Physical surface properties for collision response.
///
/// Determines how entities behave when they collide — do they bounce,
/// slide, or stop? The engine adapter maps these values to its
/// physics material system.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PhysicsMaterial {
    /// Resistance to sliding (0.0 = ice, 1.0 = rubber).
    pub friction: f32,

    /// Energy retained after collision (0.0 = no bounce, 1.0 = full bounce).
    pub bounciness: f32,
}

impl PhysicsMaterial {
    pub const DEFAULT: PhysicsMaterial = PhysicsMaterial {
        friction: 0.6,
        bounciness: 0.0,
    };

    pub const ICE: PhysicsMaterial = PhysicsMaterial {
        friction: 0.05,
        bounciness: 0.0,
    };

    pub const RUBBER: PhysicsMaterial = PhysicsMaterial {
        friction: 0.9,
        bounciness: 0.8,
    };

    pub fn new(friction: f32, bounciness: f32) -> Self {
        Self { friction, bounciness }
    }
}

impl Default for PhysicsMaterial {
    fn default() -> Self {
        PhysicsMaterial::DEFAULT
    }
}

// ── Collider Offset ───────────────────────────────────────────────────────────

/// A 3D offset applied to the collider relative to the entity's transform.
///
/// Allows the collision shape to be positioned differently from the
/// visual mesh. Common use: a character's collider is centered at the
/// hips, not at the origin.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct ColliderOffset {
    pub x: f32,
    pub y: f32,
    pub z: f32,
}

impl ColliderOffset {
    pub const ZERO: ColliderOffset = ColliderOffset { x: 0.0, y: 0.0, z: 0.0 };

    pub fn new(x: f32, y: f32, z: f32) -> Self {
        Self { x, y, z }
    }
}

impl Default for ColliderOffset {
    fn default() -> Self {
        ColliderOffset::ZERO
    }
}

// ── Collider Size ─────────────────────────────────────────────────────────────

/// The dimensions of the collider shape.
///
/// Interpretation depends on ColliderShape:
/// - Box: half-extents (x, y, z)
/// - Sphere: radius in x only (y, z ignored)
/// - Capsule: radius in x, half-height in y (z ignored)
/// - ConvexHull / Mesh: scale multiplier applied to the hull
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct ColliderSize {
    pub x: f32,
    pub y: f32,
    pub z: f32,
}

impl ColliderSize {
    /// Unit box — 1x1x1 half-extents (2x2x2 total).
    pub const UNIT: ColliderSize = ColliderSize { x: 0.5, y: 0.5, z: 0.5 };

    pub fn new(x: f32, y: f32, z: f32) -> Self {
        Self { x, y, z }
    }

    /// Convenience for sphere colliders — sets radius uniformly.
    pub fn sphere(radius: f32) -> Self {
        Self { x: radius, y: radius, z: radius }
    }

    /// Convenience for capsule colliders.
    pub fn capsule(radius: f32, half_height: f32) -> Self {
        Self { x: radius, y: half_height, z: radius }
    }
}

impl Default for ColliderSize {
    fn default() -> Self {
        ColliderSize::UNIT
    }
}

// ── Layer Mask ────────────────────────────────────────────────────────────────

/// Bitmask defining which collision layers this collider interacts with.
///
/// Each bit represents a layer (0-31). A collider only generates collision
/// events with other colliders whose layer bit is set in this mask.
///
/// Standard layer assignments (engine adapter maps these):
/// - Bit 0: Default
/// - Bit 1: Player
/// - Bit 2: Enemy
/// - Bit 3: Projectile
/// - Bit 4: Environment
/// - Bit 5: Trigger
/// - Bits 6-31: Game-specific
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct LayerMask(pub u32);

impl LayerMask {
    /// Collides with everything.
    pub const ALL: LayerMask = LayerMask(u32::MAX);
    /// Collides with nothing.
    pub const NONE: LayerMask = LayerMask(0);
    /// Default layer only.
    pub const DEFAULT: LayerMask = LayerMask(1);

    pub fn new(mask: u32) -> Self {
        Self(mask)
    }

    /// Returns true if this mask includes the given layer bit.
    pub fn includes_layer(&self, layer: u8) -> bool {
        self.0 & (1 << layer) != 0
    }

    /// Returns a new mask with the given layer bit set.
    pub fn with_layer(self, layer: u8) -> Self {
        LayerMask(self.0 | (1 << layer))
    }
}

impl Default for LayerMask {
    fn default() -> Self {
        LayerMask::DEFAULT
    }
}

// ── Component ─────────────────────────────────────────────────────────────────

/// COMP_COLLIDER_V1 — Physical collision boundary for an entity.
///
/// UCL Core component. Defines what shape the entity occupies in the
/// physics simulation, whether it blocks movement or only detects overlap,
/// and which other layers it interacts with.
///
/// ## Trigger vs Solid
/// `is_trigger = false` → solid collider, blocks movement, generates
///   physics contact forces.
/// `is_trigger = true` → trigger volume, detects overlap only, no physics
///   forces. Used for pickup zones, damage areas, dialogue triggers.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ColliderComponent {
    /// Geometric shape for collision detection.
    pub shape: ColliderShape,

    /// Dimensions of the collider. Interpretation depends on shape.
    pub size: ColliderSize,

    /// Offset from the entity's transform origin.
    pub offset: ColliderOffset,

    /// If true, this collider detects overlap only — no physics forces.
    /// If false, this is a solid collider that blocks movement.
    pub is_trigger: bool,

    /// Which collision layers this collider interacts with.
    pub layer_mask: LayerMask,

    /// Physical surface properties (friction, bounciness).
    /// Ignored when is_trigger is true.
    pub physics_material: PhysicsMaterial,
}

impl ColliderComponent {
    /// Creates a standard solid box collider.
    pub fn solid_box(size_x: f32, size_y: f32, size_z: f32) -> Self {
        Self {
            shape: ColliderShape::Box,
            size: ColliderSize::new(size_x, size_y, size_z),
            offset: ColliderOffset::ZERO,
            is_trigger: false,
            layer_mask: LayerMask::DEFAULT,
            physics_material: PhysicsMaterial::DEFAULT,
        }
    }

    /// Creates a standard solid sphere collider.
    pub fn solid_sphere(radius: f32) -> Self {
        Self {
            shape: ColliderShape::Sphere,
            size: ColliderSize::sphere(radius),
            offset: ColliderOffset::ZERO,
            is_trigger: false,
            layer_mask: LayerMask::DEFAULT,
            physics_material: PhysicsMaterial::DEFAULT,
        }
    }

    /// Creates a capsule collider. Common for player and NPC characters.
    pub fn capsule(radius: f32, half_height: f32) -> Self {
        Self {
            shape: ColliderShape::Capsule,
            size: ColliderSize::capsule(radius, half_height),
            offset: ColliderOffset::ZERO,
            is_trigger: false,
            layer_mask: LayerMask::DEFAULT,
            physics_material: PhysicsMaterial::DEFAULT,
        }
    }

    /// Creates a trigger volume — detects overlap, no physics forces.
    pub fn trigger_box(size_x: f32, size_y: f32, size_z: f32) -> Self {
        Self {
            shape: ColliderShape::Box,
            size: ColliderSize::new(size_x, size_y, size_z),
            offset: ColliderOffset::ZERO,
            is_trigger: true,
            layer_mask: LayerMask::ALL,
            physics_material: PhysicsMaterial::DEFAULT,
        }
    }
}

impl Default for ColliderComponent {
    fn default() -> Self {
        Self::solid_box(0.5, 0.5, 0.5)
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn solid_box_is_not_trigger() {
        let c = ColliderComponent::solid_box(1.0, 1.0, 1.0);
        assert!(!c.is_trigger);
        assert_eq!(c.shape, ColliderShape::Box);
    }

    #[test]
    fn trigger_box_is_trigger() {
        let c = ColliderComponent::trigger_box(2.0, 2.0, 2.0);
        assert!(c.is_trigger);
        assert_eq!(c.layer_mask, LayerMask::ALL);
    }

    #[test]
    fn sphere_size_uses_radius() {
        let c = ColliderComponent::solid_sphere(1.5);
        assert_eq!(c.size.x, 1.5);
    }

    #[test]
    fn capsule_sets_radius_and_height() {
        let c = ColliderComponent::capsule(0.4, 0.9);
        assert_eq!(c.size.x, 0.4);
        assert_eq!(c.size.y, 0.9);
    }

    #[test]
    fn layer_mask_includes_layer() {
        let mask = LayerMask::DEFAULT.with_layer(2);
        assert!(mask.includes_layer(0));
        assert!(mask.includes_layer(2));
        assert!(!mask.includes_layer(3));
    }

    #[test]
    fn layer_mask_none_excludes_all() {
        let mask = LayerMask::NONE;
        assert!(!mask.includes_layer(0));
        assert!(!mask.includes_layer(31));
    }

    #[test]
    fn layer_mask_all_includes_all() {
        let mask = LayerMask::ALL;
        assert!(mask.includes_layer(0));
        assert!(mask.includes_layer(15));
        assert!(mask.includes_layer(31));
    }

    #[test]
    fn physics_material_constants_valid() {
        assert!(PhysicsMaterial::ICE.friction < PhysicsMaterial::DEFAULT.friction);
        assert!(PhysicsMaterial::RUBBER.bounciness > PhysicsMaterial::DEFAULT.bounciness);
    }
}