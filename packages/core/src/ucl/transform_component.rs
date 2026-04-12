//! # COMP_TRANSFORM_V1
//!
//! The spatial component. Every entity that exists in 3D space must have this.
//! Defines position, rotation, scale, and optional parent for hierarchy.
//!
//! ## Why this is UCL Core
//! Every game genre — platformer, RPG, shooter, puzzle — places entities in space.
//! Transform is the only component that is truly universal across all genres.
//!
//! ## Determinism
//! All float fields use f32. Precision is consistent and fixed across platforms (D8).
//! Serialization uses fixed decimal precision to ensure identical bytes (D11).

use serde::{Deserialize, Serialize};
use crate::entity_id::{EntityID, NULL_ENTITY_ID};

/// Component type ID for COMP_TRANSFORM_V1.
/// Unique u32 identifier used by ComponentTableStore to key tables.
/// These IDs are frozen — changing them breaks snapshot compatibility.
pub const COMP_TRANSFORM_V1_ID: u32 = 1;

/// 3D position vector.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct Vec3 {
    pub x: f32,
    pub y: f32,
    pub z: f32,
}

impl Vec3 {
    pub const ZERO: Vec3 = Vec3 { x: 0.0, y: 0.0, z: 0.0 };
    pub const ONE: Vec3  = Vec3 { x: 1.0, y: 1.0, z: 1.0 };

    pub fn new(x: f32, y: f32, z: f32) -> Self {
        Self { x, y, z }
    }
}

impl Default for Vec3 {
    fn default() -> Self { Self::ZERO }
}

/// Quaternion rotation (x, y, z, w).
///
/// Always stored as a unit quaternion. The engine adapter is responsible
/// for normalizing on receipt. XACE never performs quaternion math —
/// it stores and transmits rotation values only.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct Quat {
    pub x: f32,
    pub y: f32,
    pub z: f32,
    pub w: f32,
}

impl Quat {
    /// Identity quaternion — no rotation.
    pub const IDENTITY: Quat = Quat { x: 0.0, y: 0.0, z: 0.0, w: 1.0 };

    pub fn new(x: f32, y: f32, z: f32, w: f32) -> Self {
        Self { x, y, z, w }
    }
}

impl Default for Quat {
    fn default() -> Self { Self::IDENTITY }
}

/// COMP_TRANSFORM_V1 — Spatial transform for any entity existing in 3D space.
///
/// UCL Core component. Present on virtually every entity in every game.
/// Managed by the ComponentTable for COMP_TRANSFORM_V1_ID.
///
/// ## Parent Hierarchy
/// `parent_entity_id` of NULL_ENTITY_ID means no parent (world space).
/// When a parent is set, position/rotation/scale are in local space
/// relative to the parent. The engine adapter resolves world space.
///
/// XACE does not compute world-space transforms — it stores local transforms
/// and the engine resolves the hierarchy. This keeps the runtime
/// deterministic and free of recursive transform computation.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TransformComponent {
    /// Local position relative to parent (or world origin if no parent).
    pub position: Vec3,

    /// Local rotation as a unit quaternion.
    pub rotation: Quat,

    /// Local scale. (1.0, 1.0, 1.0) = no scaling.
    pub scale: Vec3,

    /// Optional parent entity for hierarchy.
    /// NULL_ENTITY_ID means this entity is in world space (no parent).
    /// The referenced entity must exist in the EntityStore — validated
    /// by the Mutation Gate before commit.
    pub parent_entity_id: EntityID,
}

impl TransformComponent {
    /// Creates a transform at the world origin with no parent.
    pub fn identity() -> Self {
        Self {
            position: Vec3::ZERO,
            rotation: Quat::IDENTITY,
            scale: Vec3::ONE,
            parent_entity_id: NULL_ENTITY_ID,
        }
    }

    /// Creates a transform at a specific position with no rotation, no parent.
    pub fn at_position(x: f32, y: f32, z: f32) -> Self {
        Self {
            position: Vec3::new(x, y, z),
            rotation: Quat::IDENTITY,
            scale: Vec3::ONE,
            parent_entity_id: NULL_ENTITY_ID,
        }
    }

    /// Returns true if this entity has a parent in the hierarchy.
    pub fn has_parent(&self) -> bool {
        self.parent_entity_id != NULL_ENTITY_ID
    }
}

impl Default for TransformComponent {
    fn default() -> Self {
        Self::identity()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn identity_transform_has_no_parent() {
        let t = TransformComponent::identity();
        assert!(!t.has_parent());
        assert_eq!(t.parent_entity_id, NULL_ENTITY_ID);
    }

    #[test]
    fn at_position_sets_correctly() {
        let t = TransformComponent::at_position(1.0, 2.0, 3.0);
        assert_eq!(t.position.x, 1.0);
        assert_eq!(t.position.y, 2.0);
        assert_eq!(t.position.z, 3.0);
        assert_eq!(t.rotation, Quat::IDENTITY);
        assert_eq!(t.scale, Vec3::ONE);
    }

    #[test]
    fn parent_detection_works() {
        let mut t = TransformComponent::identity();
        assert!(!t.has_parent());
        t.parent_entity_id = 42;
        assert!(t.has_parent());
    }

    #[test]
    fn default_is_identity() {
        let t = TransformComponent::default();
        assert_eq!(t.position, Vec3::ZERO);
        assert_eq!(t.rotation, Quat::IDENTITY);
        assert_eq!(t.scale, Vec3::ONE);
    }

    #[test]
    fn vec3_constants_correct() {
        assert_eq!(Vec3::ZERO.x, 0.0);
        assert_eq!(Vec3::ONE.x, 1.0);
    }

    #[test]
    fn quat_identity_correct() {
        assert_eq!(Quat::IDENTITY.w, 1.0);
        assert_eq!(Quat::IDENTITY.x, 0.0);
    }
}
