//! # COMP_IDENTITY_V1
//!
//! The naming and classification component. Every entity has an identity —
//! what it is called, what type it is, what faction it belongs to, what tags
//! it carries, and whether it was spawned at runtime or defined in the schema.
//!
//! ## Why this is UCL Core
//! Every game needs to distinguish entities from each other. Without identity,
//! you cannot filter, target, group, or refer to entities by name or type.
//! This applies to every genre without exception.

use serde::{Deserialize, Serialize};
use crate::entity_id::EntityID;

/// Component type ID for COMP_IDENTITY_V1. Frozen forever.
pub const COMP_IDENTITY_V1_ID: u32 = 2;

/// Classifies what role an entity plays in the game world.
///
/// Used by systems to quickly distinguish entity categories without
/// querying multiple components. Kept as a flat enum — complex
/// classification lives in tags and GCL components.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum EntityType {
    /// A player-controlled character.
    Player,
    /// An AI-controlled non-player character.
    Npc,
    /// A hostile AI-controlled entity.
    Enemy,
    /// A static or dynamic object in the world (crate, door, pickup).
    Prop,
    /// A trigger volume, invisible zone, or logical boundary.
    Zone,
    /// A projectile, spell effect, or short-lived gameplay object.
    Projectile,
    /// A camera entity controlled by the camera system.
    Camera,
    /// A spawner that creates other entities.
    Spawner,
    /// A UI element anchored in world space.
    WorldUi,
    /// A game management entity (game state, match controller, etc.)
    Controller,
    /// Developer-defined type not covered by the above.
    /// The string payload carries the custom type name.
    Custom(String),
}

impl Default for EntityType {
    fn default() -> Self {
        EntityType::Prop
    }
}

impl std::fmt::Display for EntityType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            EntityType::Player => write!(f, "Player"),
            EntityType::Npc => write!(f, "Npc"),
            EntityType::Enemy => write!(f, "Enemy"),
            EntityType::Prop => write!(f, "Prop"),
            EntityType::Zone => write!(f, "Zone"),
            EntityType::Projectile => write!(f, "Projectile"),
            EntityType::Camera => write!(f, "Camera"),
            EntityType::Spawner => write!(f, "Spawner"),
            EntityType::WorldUi => write!(f, "WorldUi"),
            EntityType::Controller => write!(f, "Controller"),
            EntityType::Custom(name) => write!(f, "Custom({})", name),
        }
    }
}

/// COMP_IDENTITY_V1 — Name, type, faction, tags, and origin of an entity.
///
/// UCL Core component. The primary way systems identify and classify
/// entities without needing to inspect multiple components.
///
/// ## Tags
/// Tags are sorted strings stored in ascending order for deterministic
/// iteration and binary search (D3, D11). Use `add_tag` / `remove_tag`
/// rather than mutating the vec directly.
///
/// ## Prefab vs Runtime
/// `prefab_id` links this entity back to its schema definition.
/// `is_runtime_spawned` distinguishes entities created dynamically
/// during gameplay from those defined statically in the CGS.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct IdentityComponent {
    /// Human-readable name for this entity instance.
    /// Does not need to be unique — use EntityID for uniqueness.
    /// Examples: "Player1", "Guard_NorthDoor", "ChestRoom3"
    pub entity_name: String,

    /// The role this entity plays in the game world.
    pub entity_type: EntityType,

    /// Faction or team this entity belongs to.
    /// Empty string means no faction (neutral).
    /// Examples: "player_team", "enemy_faction", "neutral"
    pub faction: String,

    /// Sorted tag set for lightweight filtering and grouping.
    /// Always maintained in ascending lexicographic order (D11).
    /// Examples: ["ai", "enemy", "patrolling"]
    pub tags: Vec<String>,

    /// The schema prefab ID this entity was instantiated from.
    /// Empty string if this entity has no prefab origin
    /// (fully runtime-generated or schema root entity).
    pub prefab_id: String,

    /// True if this entity was spawned dynamically during gameplay
    /// rather than defined statically in the CGS.
    ///
    /// Runtime-spawned entities are not part of the base schema snapshot
    /// but are included in the WorldSnapshot for replay and rollback.
    pub is_runtime_spawned: bool,
}

impl IdentityComponent {
    /// Creates a minimal identity with just a name and type.
    /// Faction is neutral, tags empty, no prefab, not runtime spawned.
    pub fn new(entity_name: impl Into<String>, entity_type: EntityType) -> Self {
        Self {
            entity_name: entity_name.into(),
            entity_type,
            faction: String::new(),
            tags: Vec::new(),
            prefab_id: String::new(),
            is_runtime_spawned: false,
        }
    }

    /// Creates a runtime-spawned entity identity.
    /// Used by the Spawner system when creating entities dynamically.
    pub fn runtime_spawned(
        entity_name: impl Into<String>,
        entity_type: EntityType,
        prefab_id: impl Into<String>,
    ) -> Self {
        Self {
            entity_name: entity_name.into(),
            entity_type,
            faction: String::new(),
            tags: Vec::new(),
            prefab_id: prefab_id.into(),
            is_runtime_spawned: true,
        }
    }

    /// Returns true if this entity belongs to the given faction.
    pub fn is_in_faction(&self, faction: &str) -> bool {
        self.faction == faction
    }

    /// Returns true if this entity has the given tag.
    /// Uses binary search — O(log n) — tags are always sorted.
    pub fn has_tag(&self, tag: &str) -> bool {
        self.tags.binary_search_by(|t| t.as_str().cmp(tag)).is_ok()
    }

    /// Adds a tag, maintaining sorted order. No-op if already present.
    pub fn add_tag(&mut self, tag: impl Into<String>) {
        let tag = tag.into();
        match self.tags.binary_search(&tag) {
            Ok(_) => {}
            Err(pos) => self.tags.insert(pos, tag),
        }
    }

    /// Removes a tag. No-op if not present.
    pub fn remove_tag(&mut self, tag: &str) {
        if let Ok(pos) = self.tags.binary_search_by(|t| t.as_str().cmp(tag)) {
            self.tags.remove(pos);
        }
    }

    /// Returns true if this entity has no faction assignment.
    pub fn is_neutral(&self) -> bool {
        self.faction.is_empty()
    }
}

impl Default for IdentityComponent {
    fn default() -> Self {
        Self::new("unnamed", EntityType::Prop)
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn new_identity_has_empty_tags() {
        let id = IdentityComponent::new("Player1", EntityType::Player);
        assert!(id.tags.is_empty());
        assert!(!id.is_runtime_spawned);
    }

    #[test]
    fn runtime_spawned_flag_set() {
        let id = IdentityComponent::runtime_spawned(
            "Zombie_42", EntityType::Enemy, "prefab_zombie"
        );
        assert!(id.is_runtime_spawned);
        assert_eq!(id.prefab_id, "prefab_zombie");
    }

    #[test]
    fn tags_maintained_sorted() {
        let mut id = IdentityComponent::new("Guard", EntityType::Npc);
        id.add_tag("patrolling");
        id.add_tag("alert");
        id.add_tag("hostile");
        assert_eq!(id.tags, vec!["alert", "hostile", "patrolling"]);
    }

    #[test]
    fn has_tag_works() {
        let mut id = IdentityComponent::new("Guard", EntityType::Npc);
        id.add_tag("enemy");
        assert!(id.has_tag("enemy"));
        assert!(!id.has_tag("player"));
    }

    #[test]
    fn remove_tag_works() {
        let mut id = IdentityComponent::new("Guard", EntityType::Npc);
        id.add_tag("enemy");
        id.remove_tag("enemy");
        assert!(!id.has_tag("enemy"));
    }

    #[test]
    fn no_duplicate_tags() {
        let mut id = IdentityComponent::new("Guard", EntityType::Npc);
        id.add_tag("enemy");
        id.add_tag("enemy");
        assert_eq!(id.tags.len(), 1);
    }

    #[test]
    fn faction_detection() {
        let mut id = IdentityComponent::new("Soldier", EntityType::Enemy);
        assert!(id.is_neutral());
        id.faction = "red_team".into();
        assert!(id.is_in_faction("red_team"));
        assert!(!id.is_neutral());
    }

    #[test]
    fn custom_entity_type_display() {
        let t = EntityType::Custom("BossMinion".into());
        assert_eq!(t.to_string(), "Custom(BossMinion)");
    }
}
