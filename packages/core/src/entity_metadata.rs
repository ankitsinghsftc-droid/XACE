//! # Entity Metadata
//!
//! Combines an entity's identity, lifecycle state, and temporal markers
//! into a single struct that the EntityStore maintains per entity.
//!
//! EntityMetadata is the complete record of an entity's existence —
//! from the tick it was created to the tick it was destroyed.
//! It is stored, snapshotted, and restored as a unit.
//!
//! ## Relationship to other files
//! - Uses `EntityID` from entity_id.rs
//! - Uses `EntityState` from entity_state.rs
//! - Owned and managed by EntityStore (Phase 2)
//! - Included in WorldSnapshot verbatim (Phase 5)

use serde::{Deserialize, Serialize};
use crate::entity_id::{EntityID, NULL_ENTITY_ID};
use crate::entity_state::EntityState;

// ── Tick Type ─────────────────────────────────────────────────────────────────

/// A simulation tick counter. Represents one discrete step of the XACE runtime.
///
/// Tick is u64 — effectively infinite at any realistic simulation rate.
/// Used throughout the runtime to timestamp events, mutations, and snapshots.
/// Never frame-based — determinism rule D7 forbids frame-dependent timing.
pub type Tick = u64;

/// Sentinel value meaning "this tick has not occurred yet" or "not applicable."
///
/// Used in `destroyed_tick` when an entity is still alive — the field exists
/// in the struct but has no meaningful value until destruction occurs.
pub const NO_TICK: Tick = u64::MAX;

// ── Entity Metadata ───────────────────────────────────────────────────────────

/// The complete identity and lifecycle record for a single entity.
///
/// Maintained by the EntityStore for every entity that has ever existed
/// in the current world session — including destroyed and archived ones.
/// This is what makes replay integrity and network determinism possible:
/// the full history of every entity's existence is preserved.
///
/// Serializable for inclusion in WorldSnapshot (Phase 5).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EntityMetadata {
    /// The unique identifier for this entity.
    /// Immutable after creation. Never NULL_ENTITY_ID.
    pub id: EntityID,

    /// Current lifecycle state of this entity.
    /// Transitions enforced by Mutation Gate via EntityState::can_transition_to.
    pub state: EntityState,

    /// The simulation tick on which this entity was created.
    /// Immutable after creation. Used for ordering and replay validation.
    pub created_tick: Tick,

    /// The simulation tick on which this entity was destroyed.
    /// Set to NO_TICK while the entity is alive.
    /// Set by the Mutation Gate during destroy processing (D4).
    pub destroyed_tick: Tick,

    /// Snapshot of tags at the time of this metadata record.
    ///
    /// Tags are lightweight string labels used for filtering and grouping
    /// (e.g. "player", "enemy", "projectile"). Stored here for fast access
    /// without querying COMP_IDENTITY_V1. Kept in sorted order for
    /// deterministic comparison and hashing (D11).
    pub tags: Vec<String>,
}

impl EntityMetadata {
    /// Creates metadata for a newly spawned entity.
    ///
    /// - State is set to Active immediately
    /// - created_tick is stamped with the current tick
    /// - destroyed_tick is NO_TICK (entity is alive)
    /// - tags start empty; populated when COMP_IDENTITY_V1 is attached
    ///
    /// ## Panics
    /// Panics if `id` is NULL_ENTITY_ID — null entities must never enter
    /// the EntityStore. This is a programming error, not a runtime error.
    pub fn new(id: EntityID, created_tick: Tick) -> Self {
        assert_ne!(
            id, NULL_ENTITY_ID,
            "EntityMetadata::new called with NULL_ENTITY_ID — \
             the entity store must never contain the null entity"
        );
        Self {
            id,
            state: EntityState::Active,
            created_tick,
            destroyed_tick: NO_TICK,
            tags: Vec::new(),
        }
    }

    /// Creates metadata for a newly spawned entity with initial tags.
    ///
    /// Tags are sorted immediately to maintain deterministic ordering (D11).
    pub fn new_with_tags(id: EntityID, created_tick: Tick, mut tags: Vec<String>) -> Self {
        assert_ne!(
            id, NULL_ENTITY_ID,
            "EntityMetadata::new_with_tags called with NULL_ENTITY_ID"
        );
        tags.sort();
        Self {
            id,
            state: EntityState::Active,
            created_tick,
            destroyed_tick: NO_TICK,
            tags,
        }
    }

    /// Returns true if this entity is currently alive and active.
    pub fn is_alive(&self) -> bool {
        self.state.is_alive()
    }

    /// Returns true if this entity still occupies a slot in the EntityStore.
    pub fn is_present(&self) -> bool {
        self.state.is_present()
    }

    /// Returns true if this entity has been fully removed from the world.
    pub fn is_removed(&self) -> bool {
        self.state.is_removed()
    }

    /// Returns true if this entity has a specific tag.
    ///
    /// Uses binary search since tags are always sorted — O(log n).
    pub fn has_tag(&self, tag: &str) -> bool {
        self.tags.binary_search_by(|t| t.as_str().cmp(tag)).is_ok()
    }

    /// Adds a tag to this entity's tag set, maintaining sorted order.
    ///
    /// No-op if the tag already exists. Sorted insertion preserves
    /// deterministic ordering for snapshot hashing (D11).
    pub fn add_tag(&mut self, tag: String) {
        match self.tags.binary_search(&tag) {
            Ok(_) => {} // already present — no duplicates
            Err(pos) => self.tags.insert(pos, tag),
        }
    }

    /// Removes a tag from this entity's tag set.
    ///
    /// No-op if the tag does not exist.
    pub fn remove_tag(&mut self, tag: &str) {
        if let Ok(pos) = self.tags.binary_search_by(|t| t.as_str().cmp(tag)) {
            self.tags.remove(pos);
        }
    }

    /// Marks this entity as destroyed at the given tick.
    ///
    /// Called by the Mutation Gate during destroy processing.
    /// Transitions state from DestroyRequested → Destroyed and
    /// stamps the destroyed_tick. The entity moves to Archived
    /// in the subsequent archival pass.
    ///
    /// Returns false if the transition is invalid (already destroyed, etc.)
    pub fn mark_destroyed(&mut self, tick: Tick) -> bool {
        if self.state.can_transition_to(EntityState::Destroyed) {
            self.state = EntityState::Destroyed;
            self.destroyed_tick = tick;
            true
        } else {
            false
        }
    }

    /// Marks this entity as archived.
    ///
    /// Called after destruction processing is complete.
    /// Terminal state — no further transitions are possible.
    ///
    /// Returns false if the transition is invalid.
    pub fn mark_archived(&mut self) -> bool {
        if self.state.can_transition_to(EntityState::Archived) {
            self.state = EntityState::Archived;
            true
        } else {
            false
        }
    }

    /// Returns how many ticks this entity was alive.
    ///
    /// Returns None if the entity has not been destroyed yet.
    /// Used for lifetime tracking, analytics, and replay validation.
    pub fn lifetime_ticks(&self) -> Option<Tick> {
        if self.destroyed_tick == NO_TICK {
            None
        } else {
            Some(self.destroyed_tick.saturating_sub(self.created_tick))
        }
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn new_entity_is_active() {
        let meta = EntityMetadata::new(1, 0);
        assert!(meta.is_alive());
        assert!(meta.is_present());
        assert!(!meta.is_removed());
    }

    #[test]
    fn new_entity_has_no_destroyed_tick() {
        let meta = EntityMetadata::new(1, 0);
        assert_eq!(meta.destroyed_tick, NO_TICK);
        assert_eq!(meta.lifetime_ticks(), None);
    }

    #[test]
    #[should_panic]
    fn null_entity_id_panics() {
        EntityMetadata::new(NULL_ENTITY_ID, 0);
    }

    #[test]
    fn tags_are_sorted_on_creation() {
        let meta = EntityMetadata::new_with_tags(
            1, 0,
            vec!["zombie".into(), "enemy".into(), "ai".into()]
        );
        assert_eq!(meta.tags, vec!["ai", "enemy", "zombie"]);
    }

    #[test]
    fn add_tag_maintains_sort_order() {
        let mut meta = EntityMetadata::new(1, 0);
        meta.add_tag("player".into());
        meta.add_tag("active".into());
        meta.add_tag("human".into());
        assert_eq!(meta.tags, vec!["active", "human", "player"]);
    }

    #[test]
    fn add_tag_no_duplicates() {
        let mut meta = EntityMetadata::new(1, 0);
        meta.add_tag("player".into());
        meta.add_tag("player".into());
        assert_eq!(meta.tags.len(), 1);
    }

    #[test]
    fn has_tag_works_correctly() {
        let mut meta = EntityMetadata::new(1, 0);
        meta.add_tag("enemy".into());
        assert!(meta.has_tag("enemy"));
        assert!(!meta.has_tag("player"));
    }

    #[test]
    fn remove_tag_works() {
        let mut meta = EntityMetadata::new(1, 0);
        meta.add_tag("enemy".into());
        meta.remove_tag("enemy");
        assert!(!meta.has_tag("enemy"));
    }

    #[test]
    fn mark_destroyed_stamps_tick() {
        let mut meta = EntityMetadata::new(1, 0);
        meta.state = EntityState::DestroyRequested;
        assert!(meta.mark_destroyed(42));
        assert_eq!(meta.destroyed_tick, 42);
        assert_eq!(meta.lifetime_ticks(), Some(42));
    }

    #[test]
    fn mark_archived_after_destroyed() {
        let mut meta = EntityMetadata::new(1, 0);
        meta.state = EntityState::DestroyRequested;
        meta.mark_destroyed(10);
        assert!(meta.mark_archived());
        assert!(meta.is_removed());
    }

    #[test]
    fn cannot_destroy_already_archived() {
        let mut meta = EntityMetadata::new(1, 0);
        meta.state = EntityState::Archived;
        assert!(!meta.mark_destroyed(99));
    }

    #[test]
    fn lifetime_ticks_calculated_correctly() {
        let mut meta = EntityMetadata::new(1, 10);
        meta.state = EntityState::DestroyRequested;
        meta.mark_destroyed(55);
        assert_eq!(meta.lifetime_ticks(), Some(45));
    }
}
