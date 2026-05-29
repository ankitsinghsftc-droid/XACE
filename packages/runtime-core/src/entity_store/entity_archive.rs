//! # Entity Archive
//!
//! Permanent registry of destroyed entity IDs. Once an EntityID enters
//! the archive it can never leave — it is reserved forever (D2).
//!
//! ## Why Permanent Archiving Matters
//! Without permanent ID reservation, a destroyed entity's ID could be
//! reassigned to a new entity. This would corrupt:
//! - Replay systems: old input referencing entity 42 would affect wrong entity
//! - Network sync: peers tracking destroyed entity 42 see wrong entity
//! - Snapshots: restoring a snapshot would have ID conflicts
//!
//! The archive is the mechanism that makes D2 enforceable.
//! It is included in WorldSnapshot for complete replay integrity.
//!
//! ## Memory Consideration
//! At 60 ticks/second, 8 bytes per EntityID:
//! 1 million destroyed entities = 8MB of archive data.
//! This is acceptable for the determinism guarantee it provides.
//! Very long-running sessions with millions of destroyed entities
//! may need archive compaction — a future optimization.

use std::collections::BTreeMap;
use xace_core::entity_id::EntityID;
use xace_core::entity_metadata::Tick;

// ── Entity Archive ────────────────────────────────────────────────────────────

/// Permanent registry of destroyed entity IDs.
///
/// Every EntityID that was ever destroyed is permanently stored here.
/// The archive ensures these IDs are never reassigned to new entities.
///
/// ## BTreeMap for Determinism
/// Uses BTreeMap<EntityID, Tick> for deterministic iteration order (D11).
/// Key = the archived EntityID.
/// Value = the tick on which the entity was destroyed.
/// The destruction tick is stored for replay validation and debugging.
///
/// ## Immutability After Archive
/// Once an ID is archived it cannot be removed. There is no
/// unarchive() method. This immutability is the guarantee.
pub struct EntityArchive {
    /// Archived EntityID → destruction tick.
    /// BTreeMap guarantees EntityID-ascending iteration order (D11).
    archived: BTreeMap<EntityID, Tick>,
}

impl EntityArchive {
    /// Creates an empty archive.
    pub fn new() -> Self {
        Self {
            archived: BTreeMap::new(),
        }
    }

    /// Permanently archives an EntityID at the given destruction tick.
    ///
    /// Called by EntityStore.complete_destroy() after successful destruction.
    /// No-op if the ID is already archived (idempotent — safe to call twice).
    ///
    /// ## Idempotency
    /// If called twice with the same ID, the first destruction tick
    /// is preserved. The second call is silently ignored.
    pub fn archive_id(&mut self, entity_id: EntityID, destroyed_at_tick: Tick) {
        // entry() preserves existing value on duplicate — idempotent
        self.archived.entry(entity_id).or_insert(destroyed_at_tick);
    }

    /// Returns true if the given EntityID has been permanently archived.
    pub fn is_archived(&self, entity_id: EntityID) -> bool {
        self.archived.contains_key(&entity_id)
    }

    /// Returns the destruction tick for an archived entity, if found.
    /// Returns None if the entity was never archived.
    pub fn destroyed_at_tick(&self, entity_id: EntityID) -> Option<Tick> {
        self.archived.get(&entity_id).copied()
    }

    /// Returns the total number of archived entity IDs.
    pub fn archived_count(&self) -> usize {
        self.archived.len()
    }

    /// Returns true if the archive is empty (no entities destroyed yet).
    pub fn is_empty(&self) -> bool {
        self.archived.is_empty()
    }

    /// Returns all archived entity IDs sorted ascending (D11).
    /// Used by SnapshotEngine for serialization.
    pub fn all_archived_ids(&self) -> Vec<EntityID> {
        // BTreeMap iteration is already sorted ascending
        self.archived.keys().copied().collect()
    }

    /// Returns all archived entries as (EntityID, destroyed_tick) pairs
    /// sorted by EntityID ascending (D11).
    /// Used by SnapshotEngine for complete archive serialization.
    pub fn all_entries_sorted(&self) -> Vec<(EntityID, Tick)> {
        self.archived
            .iter()
            .map(|(&id, &tick)| (id, tick))
            .collect()
    }

    /// Returns true if the archive contains all IDs in the given slice.
    /// Used by DeterminismGuard to validate replay archive integrity.
    pub fn contains_all(&self, ids: &[EntityID]) -> bool {
        ids.iter().all(|id| self.archived.contains_key(id))
    }

    /// Merges another archive into this one.
    ///
    /// Used during snapshot restore to rebuild the archive from
    /// serialized data. Existing entries are preserved (first-write wins).
    pub fn merge(&mut self, other: Vec<(EntityID, Tick)>) {
        for (id, tick) in other {
            self.archive_id(id, tick);
        }
    }
}

impl Default for EntityArchive {
    fn default() -> Self {
        Self::new()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn new_archive_is_empty() {
        let archive = EntityArchive::new();
        assert!(archive.is_empty());
        assert_eq!(archive.archived_count(), 0);
    }

    #[test]
    fn archive_id_stores_correctly() {
        let mut archive = EntityArchive::new();
        archive.archive_id(1, 42);
        assert!(archive.is_archived(1));
        assert_eq!(archive.archived_count(), 1);
    }

    #[test]
    fn is_archived_false_for_unknown() {
        let archive = EntityArchive::new();
        assert!(!archive.is_archived(999));
    }

    #[test]
    fn destroyed_at_tick_correct() {
        let mut archive = EntityArchive::new();
        archive.archive_id(5, 100);
        assert_eq!(archive.destroyed_at_tick(5), Some(100));
        assert_eq!(archive.destroyed_at_tick(6), None);
    }

    #[test]
    fn archive_is_idempotent() {
        let mut archive = EntityArchive::new();
        archive.archive_id(1, 10);
        archive.archive_id(1, 20); // Second call — should not overwrite
        assert_eq!(archive.archived_count(), 1);
        // First tick is preserved
        assert_eq!(archive.destroyed_at_tick(1), Some(10));
    }

    #[test]
    fn all_archived_ids_sorted_ascending() {
        let mut archive = EntityArchive::new();
        archive.archive_id(5, 0);
        archive.archive_id(1, 0);
        archive.archive_id(3, 0);
        let ids = archive.all_archived_ids();
        assert_eq!(ids, vec![1, 3, 5]);
    }

    #[test]
    fn all_entries_sorted_ascending() {
        let mut archive = EntityArchive::new();
        archive.archive_id(10, 100);
        archive.archive_id(2, 50);
        archive.archive_id(7, 75);
        let entries = archive.all_entries_sorted();
        assert_eq!(entries[0].0, 2);
        assert_eq!(entries[1].0, 7);
        assert_eq!(entries[2].0, 10);
    }

    #[test]
    fn contains_all_correct() {
        let mut archive = EntityArchive::new();
        archive.archive_id(1, 0);
        archive.archive_id(2, 0);
        archive.archive_id(3, 0);
        assert!(archive.contains_all(&[1, 2, 3]));
        assert!(!archive.contains_all(&[1, 2, 4]));
        assert!(archive.contains_all(&[]));
    }

    #[test]
    fn merge_combines_archives() {
        let mut archive = EntityArchive::new();
        archive.archive_id(1, 10);
        let other = vec![(2, 20), (3, 30)];
        archive.merge(other);
        assert!(archive.is_archived(1));
        assert!(archive.is_archived(2));
        assert!(archive.is_archived(3));
        assert_eq!(archive.archived_count(), 3);
    }

    #[test]
    fn merge_preserves_existing_entries() {
        let mut archive = EntityArchive::new();
        archive.archive_id(1, 10);
        // Merge tries to overwrite with different tick
        archive.merge(vec![(1, 99)]);
        // Original tick preserved
        assert_eq!(archive.destroyed_at_tick(1), Some(10));
    }

    #[test]
    fn multiple_entities_archived_correctly() {
        let mut archive = EntityArchive::new();
        for id in 1u64..=100 {
            archive.archive_id(id, id * 10);
        }
        assert_eq!(archive.archived_count(), 100);
        for id in 1u64..=100 {
            assert!(archive.is_archived(id));
            assert_eq!(archive.destroyed_at_tick(id), Some(id * 10));
        }
    }
}
