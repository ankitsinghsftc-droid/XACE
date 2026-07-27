//! # Entity Store
//!
//! The authoritative registry of every entity that has ever existed
//! in the XACE world — alive, disabled, destroyed, or archived.
//!
//! ## Global Invariant I1
//! Component tables must never contain EntityIDs not in the EntityStore.
//! The EntityStore is the source of truth for entity existence.
//! The MutationGate validates entity existence before every component write.
//!
//! ## Determinism (D2, D3)
//! EntityIDs are never reused after destruction — destroyed IDs are
//! permanently archived (D2). get_all_alive() always returns entities
//! sorted by EntityID ASC (D3) — this ordering is mandatory for all
//! system iteration to be deterministic.
//!
//! ## Design
//! The EntityStore uses a BTreeMap<EntityID, EntityMetadata> internally.
//! BTreeMap guarantees EntityID-ascending iteration order automatically (D3).
//! No sorting needed at query time — the structure maintains it always.

use super::entity_archive::EntityArchive;
use super::entity_id_generator::EntityIdGenerator;
use std::collections::BTreeMap;
use xace_core::entity_id::{EntityID, NULL_ENTITY_ID};
use xace_core::entity_metadata::{EntityMetadata, Tick};
use xace_core::entity_state::EntityState;
use xace_core::errors::xace_error::{ErrorContext, XaceError};

// ── Entity Store ──────────────────────────────────────────────────────────────

/// The authoritative registry of all entities in the XACE world.
///
/// Maintains a complete record of every entity that has ever existed —
/// including destroyed and archived entities. This completeness is
/// required for:
/// - Replay integrity (D2 — IDs never reused)
/// - Network determinism (peers must agree on entity history)
/// - Snapshot restore (I10 — exact state reconstruction)
///
/// ## Thread Safety
/// EntityStore is not thread-safe on its own. The PhaseOrchestrator
/// ensures single-threaded access during mutation gate application.
/// Systems read entity lists via SystemContext which provides
/// controlled access.
pub struct EntityStore {
    /// All entity records sorted by EntityID ASC (D3).
    /// BTreeMap guarantees ascending key order automatically.
    entities: BTreeMap<EntityID, EntityMetadata>,

    /// Monotonic ID generator — never reuses IDs (D2).
    id_generator: EntityIdGenerator,

    /// Permanent archive of destroyed entity IDs (D2).
    archive: EntityArchive,
}

#[derive(Debug, Clone)]
pub struct EntityStoreRollbackSnapshot {
    entity_records: Vec<EntityMetadata>,
    next_entity_id: EntityID,
    archived_ids: Vec<(EntityID, Tick)>,
}

impl EntityStore {
    /// Creates a new empty EntityStore.
    /// ID generator starts at 1 — NULL_ENTITY_ID (0) is never generated.
    pub fn new() -> Self {
        Self {
            entities: BTreeMap::new(),
            id_generator: EntityIdGenerator::new(),
            archive: EntityArchive::new(),
        }
    }

    // ── Entity Creation ────────────────────────────────────────────────────

    /// Creates a new entity and returns its unique EntityID.
    ///
    /// The entity starts in Active state. Its ID is monotonically
    /// increasing and will never be reused (D2).
    ///
    /// Called by the MutationGate when processing spawn requests.
    /// Never called directly by systems.
    pub fn create_entity(&mut self, created_tick: Tick) -> Result<EntityID, XaceError> {
        let id = self.id_generator.next_id();

        // Sanity check — generator must never produce NULL_ENTITY_ID
        debug_assert_ne!(
            id, NULL_ENTITY_ID,
            "EntityIdGenerator produced NULL_ENTITY_ID — this is a bug"
        );

        let metadata = EntityMetadata::new(id, created_tick);
        self.entities.insert(id, metadata);

        Ok(id)
    }

    // ── Entity Destruction ─────────────────────────────────────────────────

    /// Marks an entity as DestroyRequested at the given tick.
    ///
    /// This is the first step of destruction. The entity is still
    /// present and readable but no new writes are accepted.
    /// Full destruction is completed by complete_destroy().
    ///
    /// Called by the MutationGate when processing destroy requests.
    pub fn request_destroy(&mut self, entity_id: EntityID, tick: Tick) -> Result<(), XaceError> {
        let metadata = self.get_mut_or_error(entity_id, "request_destroy")?;

        if !metadata
            .state
            .can_transition_to(EntityState::DestroyRequested)
        {
            return Err(XaceError::ValidationFailure {
                message: format!(
                    "Entity {} cannot transition from {:?} to DestroyRequested",
                    entity_id, metadata.state
                ),
                context: ErrorContext::new("EntityStore", "request_destroy").with_tick(tick),
                rule_violated: "entity_lifecycle".into(),
                failed_path: format!("entity:{}", entity_id),
            });
        }

        metadata.state = EntityState::DestroyRequested;
        Ok(())
    }

    /// Completes the destruction of a DestroyRequested entity.
    ///
    /// Transitions: DestroyRequested → Destroyed → Archived
    /// Stamps the destroyed_tick on the metadata.
    /// Permanently archives the EntityID — it will never be reused (D2).
    ///
    /// Called by the MutationGate during apply_all() destroy phase.
    pub fn complete_destroy(&mut self, entity_id: EntityID, tick: Tick) -> Result<(), XaceError> {
        {
            let metadata = self.get_mut_or_error(entity_id, "complete_destroy")?;

            if !metadata.mark_destroyed(tick) {
                return Err(XaceError::ValidationFailure {
                    message: format!(
                        "Entity {} is not in DestroyRequested state — \
                         cannot complete destruction",
                        entity_id
                    ),
                    context: ErrorContext::new("EntityStore", "complete_destroy").with_tick(tick),
                    rule_violated: "entity_lifecycle".into(),
                    failed_path: format!("entity:{}", entity_id),
                });
            }

            metadata.mark_archived();
        }

        // Permanently archive this ID — never to be reused (D2)
        self.archive.archive_id(entity_id, tick);

        Ok(())
    }

    // ── Entity State Changes ───────────────────────────────────────────────

    /// Transitions an entity to Disabled state.
    ///
    /// Disabled entities are excluded from system queries
    /// but remain in the store with all components intact.
    pub fn disable_entity(&mut self, entity_id: EntityID, tick: Tick) -> Result<(), XaceError> {
        let metadata = self.get_mut_or_error(entity_id, "disable_entity")?;

        if !metadata.state.can_transition_to(EntityState::Disabled) {
            return Err(XaceError::ValidationFailure {
                message: format!(
                    "Entity {} cannot be disabled from state {:?}",
                    entity_id, metadata.state
                ),
                context: ErrorContext::new("EntityStore", "disable_entity").with_tick(tick),
                rule_violated: "entity_lifecycle".into(),
                failed_path: format!("entity:{}", entity_id),
            });
        }

        metadata.state = EntityState::Disabled;
        Ok(())
    }

    /// Transitions a Disabled entity back to Active state.
    pub fn enable_entity(&mut self, entity_id: EntityID, tick: Tick) -> Result<(), XaceError> {
        let metadata = self.get_mut_or_error(entity_id, "enable_entity")?;

        if !metadata.state.can_transition_to(EntityState::Active) {
            return Err(XaceError::ValidationFailure {
                message: format!(
                    "Entity {} cannot be enabled from state {:?}",
                    entity_id, metadata.state
                ),
                context: ErrorContext::new("EntityStore", "enable_entity").with_tick(tick),
                rule_violated: "entity_lifecycle".into(),
                failed_path: format!("entity:{}", entity_id),
            });
        }

        metadata.state = EntityState::Active;
        Ok(())
    }

    // ── Tag Management ─────────────────────────────────────────────────────

    /// Adds a tag to an entity's metadata.
    /// Tags are maintained in sorted order (D11).
    pub fn add_tag(&mut self, entity_id: EntityID, tag: String) -> Result<(), XaceError> {
        let metadata = self.get_mut_or_error(entity_id, "add_tag")?;
        metadata.add_tag(tag);
        Ok(())
    }

    /// Removes a tag from an entity's metadata.
    pub fn remove_tag(&mut self, entity_id: EntityID, tag: &str) -> Result<(), XaceError> {
        let metadata = self.get_mut_or_error(entity_id, "remove_tag")?;
        metadata.remove_tag(tag);
        Ok(())
    }

    // ── Query API ──────────────────────────────────────────────────────────

    /// Returns true if the entity exists in any non-archived state.
    pub fn exists(&self, entity_id: EntityID) -> bool {
        self.entities
            .get(&entity_id)
            .map(|m| m.is_present())
            .unwrap_or(false)
    }

    /// Returns true if the entity is currently Active.
    pub fn is_alive(&self, entity_id: EntityID) -> bool {
        self.entities
            .get(&entity_id)
            .map(|m| m.is_alive())
            .unwrap_or(false)
    }

    /// Returns the metadata for the given entity, if it exists.
    pub fn get_metadata(&self, entity_id: EntityID) -> Option<&EntityMetadata> {
        self.entities.get(&entity_id)
    }

    /// Returns all Active entity IDs sorted by EntityID ASC (D3).
    ///
    /// This is the primary query used by systems. BTreeMap guarantees
    /// ascending order — no sorting needed at query time.
    ///
    /// Only Active entities are returned. Disabled, DestroyRequested,
    /// Destroyed, and Archived entities are excluded.
    pub fn get_all_alive(&self) -> Vec<EntityID> {
        self.entities
            .iter()
            .filter(|(_, m)| m.is_alive())
            .map(|(id, _)| *id)
            .collect()
        // BTreeMap iteration is already sorted by key ASC (D3)
    }

    /// Returns all present entity IDs (Active + Disabled + DestroyRequested)
    /// sorted by EntityID ASC (D3).
    ///
    /// Used by the SnapshotEngine to capture all entities that have
    /// component data in the ComponentTableStore.
    pub fn get_all_present(&self) -> Vec<EntityID> {
        self.entities
            .iter()
            .filter(|(_, m)| m.is_present())
            .map(|(id, _)| *id)
            .collect()
    }

    /// Returns all entity IDs that have the given tag, sorted ASC (D3).
    pub fn get_by_tag(&self, tag: &str) -> Vec<EntityID> {
        self.entities
            .iter()
            .filter(|(_, m)| m.is_alive() && m.has_tag(tag))
            .map(|(id, _)| *id)
            .collect()
    }

    /// Returns the total count of all entity records including archived.
    pub fn total_count(&self) -> usize {
        self.entities.len()
    }

    /// Returns the count of currently alive (Active) entities.
    pub fn alive_count(&self) -> usize {
        self.entities.values().filter(|m| m.is_alive()).count()
    }

    /// Returns the count of present entities (Active + Disabled + DestroyRequested).
    pub fn present_count(&self) -> usize {
        self.entities.values().filter(|m| m.is_present()).count()
    }

    /// Returns the next EntityID that would be generated.
    /// Used by SnapshotEngine to capture generator state for restore.
    pub fn peek_next_id(&self) -> EntityID {
        self.id_generator.peek_next()
    }

    /// Returns a reference to the entity archive.
    /// Used by SnapshotEngine and DeterminismGuard.
    pub fn archive(&self) -> &EntityArchive {
        &self.archive
    }

    // ── Snapshot Support ───────────────────────────────────────────────────

    /// Restores the entity store from snapshot data.
    ///
    /// Called by the SnapshotEngine during snapshot restore (I10).
    /// Clears all current state and rebuilds from the provided records.
    ///
    /// After restore the ID generator is set to next_entity_id to prevent
    /// ID collision with any entity that existed before the snapshot.
    pub fn restore_from_snapshot(
        &mut self,
        entity_records: Vec<EntityMetadata>,
        next_entity_id: EntityID,
        archived_ids: Vec<(EntityID, Tick)>,
    ) {
        self.entities.clear();
        self.archive = EntityArchive::new();

        let inferred_archived_ids: Vec<(EntityID, Tick)> = entity_records
            .iter()
            .filter(|metadata| metadata.state == xace_core::entity_state::EntityState::Archived)
            .map(|metadata| (metadata.id, metadata.destroyed_tick))
            .collect();

        for metadata in entity_records {
            self.entities.insert(metadata.id, metadata);
        }

        for (id, tick) in inferred_archived_ids {
            self.archive.archive_id(id, tick);
        }

        for (id, tick) in archived_ids {
            self.archive.archive_id(id, tick);
        }

        self.id_generator.restore_to(next_entity_id);
    }

    /// Captures an exact rollback image of the entity store, including the
    /// monotonic ID counter and permanent archive.
    pub fn rollback_snapshot(&self) -> EntityStoreRollbackSnapshot {
        EntityStoreRollbackSnapshot {
            entity_records: self.all_metadata_sorted().into_iter().cloned().collect(),
            next_entity_id: self.peek_next_id(),
            archived_ids: self.archive.all_entries_sorted(),
        }
    }

    /// Restores a rollback image captured by `rollback_snapshot()`.
    pub fn restore_rollback_snapshot(&mut self, snapshot: EntityStoreRollbackSnapshot) {
        self.restore_from_snapshot(
            snapshot.entity_records,
            snapshot.next_entity_id,
            snapshot.archived_ids,
        );
    }

    /// Returns all entity metadata records sorted by EntityID ASC (D3).
    /// Used by SnapshotEngine to serialize the complete entity store.
    pub fn all_metadata_sorted(&self) -> Vec<&EntityMetadata> {
        // BTreeMap iteration is already sorted by key ASC
        self.entities.values().collect()
    }

    // ── Internal Helpers ───────────────────────────────────────────────────

    /// Returns a mutable reference to entity metadata or a ValidationFailure error.
    fn get_mut_or_error(
        &mut self,
        entity_id: EntityID,
        operation: &str,
    ) -> Result<&mut EntityMetadata, XaceError> {
        self.entities
            .get_mut(&entity_id)
            .ok_or_else(|| XaceError::ValidationFailure {
                message: format!("Entity {} does not exist in EntityStore", entity_id),
                context: ErrorContext::new("EntityStore", operation),
                rule_violated: "I1".into(),
                failed_path: format!("entity:{}", entity_id),
            })
    }
}

impl Default for EntityStore {
    fn default() -> Self {
        Self::new()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn store() -> EntityStore {
        EntityStore::new()
    }

    #[test]
    fn create_entity_returns_nonzero_id() {
        let mut s = store();
        let id = s.create_entity(0).unwrap();
        assert_ne!(id, NULL_ENTITY_ID);
    }

    #[test]
    fn created_entity_is_alive() {
        let mut s = store();
        let id = s.create_entity(0).unwrap();
        assert!(s.is_alive(id));
        assert!(s.exists(id));
    }

    #[test]
    fn ids_are_monotonically_increasing() {
        let mut s = store();
        let a = s.create_entity(0).unwrap();
        let b = s.create_entity(0).unwrap();
        let c = s.create_entity(0).unwrap();
        assert!(a < b && b < c);
    }

    #[test]
    fn get_all_alive_sorted_ascending() {
        let mut s = store();
        let a = s.create_entity(0).unwrap();
        let b = s.create_entity(0).unwrap();
        let c = s.create_entity(0).unwrap();
        let alive = s.get_all_alive();
        assert_eq!(alive, vec![a, b, c]);
        // Verify sorted
        for window in alive.windows(2) {
            assert!(window[0] < window[1]);
        }
    }

    #[test]
    fn disabled_entity_not_in_alive() {
        let mut s = store();
        let id = s.create_entity(0).unwrap();
        s.disable_entity(id, 1).unwrap();
        assert!(!s.get_all_alive().contains(&id));
        assert!(s.exists(id));
    }

    #[test]
    fn enabled_entity_returns_to_alive() {
        let mut s = store();
        let id = s.create_entity(0).unwrap();
        s.disable_entity(id, 1).unwrap();
        s.enable_entity(id, 2).unwrap();
        assert!(s.is_alive(id));
        assert!(s.get_all_alive().contains(&id));
    }

    #[test]
    fn destroy_request_removes_from_alive() {
        let mut s = store();
        let id = s.create_entity(0).unwrap();
        s.request_destroy(id, 1).unwrap();
        assert!(!s.is_alive(id));
        assert!(s.exists(id));
    }

    #[test]
    fn complete_destroy_archives_entity() {
        let mut s = store();
        let id = s.create_entity(0).unwrap();
        s.request_destroy(id, 1).unwrap();
        s.complete_destroy(id, 2).unwrap();
        assert!(!s.exists(id));
        assert!(!s.is_alive(id));
        assert!(s.archive().is_archived(id));
    }

    #[test]
    fn archived_id_tracked_in_archive() {
        let mut s = store();
        let id = s.create_entity(0).unwrap();
        s.request_destroy(id, 1).unwrap();
        s.complete_destroy(id, 2).unwrap();
        assert!(s.archive().is_archived(id));
    }

    #[test]
    fn destroy_without_request_fails() {
        let mut s = store();
        let id = s.create_entity(0).unwrap();
        // Complete destroy without request should fail
        let result = s.complete_destroy(id, 1);
        assert!(result.is_err());
    }

    #[test]
    fn nonexistent_entity_operations_fail() {
        let mut s = store();
        assert!(s.disable_entity(999, 0).is_err());
        assert!(s.enable_entity(999, 0).is_err());
        assert!(s.request_destroy(999, 0).is_err());
    }

    #[test]
    fn tags_maintained_on_entity() {
        let mut s = store();
        let id = s.create_entity(0).unwrap();
        s.add_tag(id, "enemy".into()).unwrap();
        s.add_tag(id, "ai".into()).unwrap();
        let meta = s.get_metadata(id).unwrap();
        assert!(meta.has_tag("enemy"));
        assert!(meta.has_tag("ai"));
    }

    #[test]
    fn get_by_tag_returns_correct_entities() {
        let mut s = store();
        let player = s.create_entity(0).unwrap();
        let enemy1 = s.create_entity(0).unwrap();
        let enemy2 = s.create_entity(0).unwrap();
        s.add_tag(player, "player".into()).unwrap();
        s.add_tag(enemy1, "enemy".into()).unwrap();
        s.add_tag(enemy2, "enemy".into()).unwrap();
        let enemies = s.get_by_tag("enemy");
        assert_eq!(enemies.len(), 2);
        assert!(enemies.contains(&enemy1));
        assert!(enemies.contains(&enemy2));
        assert!(!enemies.contains(&player));
    }

    #[test]
    fn alive_count_correct() {
        let mut s = store();
        s.create_entity(0).unwrap();
        s.create_entity(0).unwrap();
        let id = s.create_entity(0).unwrap();
        s.disable_entity(id, 1).unwrap();
        assert_eq!(s.alive_count(), 2);
        assert_eq!(s.present_count(), 3);
    }

    #[test]
    fn snapshot_restore_rebuilds_correctly() {
        let mut s = store();
        let id1 = s.create_entity(0).unwrap();
        let id2 = s.create_entity(0).unwrap();

        let records: Vec<EntityMetadata> = s.all_metadata_sorted().into_iter().cloned().collect();
        let next_id = s.peek_next_id();

        let mut s2 = EntityStore::new();
        s2.restore_from_snapshot(records, next_id, vec![]);

        assert!(s2.is_alive(id1));
        assert!(s2.is_alive(id2));
        assert_eq!(s2.peek_next_id(), next_id);
    }

    #[test]
    fn total_count_includes_all_states() {
        let mut s = store();
        let _id1 = s.create_entity(0).unwrap();
        let id2 = s.create_entity(0).unwrap();
        s.request_destroy(id2, 1).unwrap();
        s.complete_destroy(id2, 2).unwrap();
        // id2 is archived — still in entities map
        assert_eq!(s.total_count(), 2);
    }
}
