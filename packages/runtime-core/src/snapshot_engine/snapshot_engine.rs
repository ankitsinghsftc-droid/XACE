//! # Snapshot Engine
//!
//! Takes deterministic snapshots of the complete world state and
//! restores them exactly. Foundation for rollback, replay,
//! network resync, and save/load.
//!
//! ## Global Invariant I10
//! Snapshot restore must reconstruct world state exactly.
//! restore_snapshot(take_snapshot()) must produce a world state
//! that generates identical output on all subsequent ticks.
//!
//! ## Phase 5 Implementation
//! Deep copy on take_snapshot() — every component table row is cloned.
//! Copy-on-write optimization is planned for v2.
//!
//! ## Determinism (D9)
//! Every snapshot includes a world_hash computed from the full
//! serialized state. The DeterminismGuard (Phase 6) validates
//! this hash on every replay tick.

use super::snapshot_serializer::SnapshotSerializer;
use super::snapshot_store::{RetentionPolicy, SnapshotStore};
use crate::component_tables::ComponentTableStore;
use crate::entity_store::EntityStore;
use xace_core::entity_metadata::Tick;
use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::runtime::world_snapshot::{
    ComponentTableRecord, ComponentTablesSnapshot, EntityRecord, EntityStoreSnapshot,
    EventQueueState, MutationQueueState, RngState, WorldSnapshot,
};

// ── Snapshot Engine ───────────────────────────────────────────────────────────

/// Takes and restores deterministic WorldSnapshots.
///
/// Wraps EntityStore and ComponentTableStore access to produce
/// complete, self-consistent snapshots of all world state.
pub struct SnapshotEngine {
    /// Snapshot storage with retention policy.
    store: SnapshotStore,

    /// Deterministic serializer for hash computation (D9).
    serializer: SnapshotSerializer,

    /// Current schema version — embedded in every snapshot.
    schema_version: String,

    /// Current execution plan version — embedded in every snapshot.
    execution_plan_version: u32,

    /// World seed for RNG state snapshots (D6).
    world_seed: u64,
}

impl SnapshotEngine {
    /// Creates a new SnapshotEngine with the given retention policy.
    pub fn new(
        schema_version: impl Into<String>,
        execution_plan_version: u32,
        world_seed: u64,
        policy: RetentionPolicy,
    ) -> Self {
        Self {
            store: SnapshotStore::new(policy),
            serializer: SnapshotSerializer::new(),
            schema_version: schema_version.into(),
            execution_plan_version,
            world_seed,
        }
    }

    /// Creates a standard engine with KeepLastN(8) retention.
    pub fn standard(
        schema_version: impl Into<String>,
        execution_plan_version: u32,
        world_seed: u64,
    ) -> Self {
        Self::new(
            schema_version,
            execution_plan_version,
            world_seed,
            RetentionPolicy::KeepLastN(8),
        )
    }

    // ── Snapshot Taking ────────────────────────────────────────────────────

    /// Captures the complete world state at the given tick.
    ///
    /// ## What Is Captured
    /// - All entity records (including archived) from EntityStore
    /// - All component rows from ComponentTableStore
    /// - RNG state (world_seed + stream positions)
    /// - Schema and execution plan versions
    /// - World hash computed from full serialized state (D9)
    ///
    /// ## Performance
    /// Deep copy — O(entities × components) time and memory.
    /// Phase 5 baseline. Copy-on-write in v2.
    pub fn take_snapshot(
        &mut self,
        tick: Tick,
        entity_store: &EntityStore,
        table_store: &ComponentTableStore,
    ) -> Result<WorldSnapshot, XaceError> {
        // Capture entity store state
        let entity_store_snapshot = self.capture_entity_store(entity_store, tick);

        // Capture component tables state (deep copy)
        let component_tables_snapshot = self.capture_component_tables(table_store);

        // Capture RNG state
        let rng_state = RngState {
            world_seed: self.world_seed,
            stream_positions: std::collections::BTreeMap::new(), // populated by DeterministicRng in Phase 6
        };

        // Build snapshot with empty hash first
        let mut snapshot = WorldSnapshot {
            tick,
            time_seconds: tick as f64 / 60.0,
            schema_version: self.schema_version.clone(),
            execution_plan_version: self.execution_plan_version,
            cgs_hash: String::new(),
            is_clean: true,
            entity_store_snapshot,
            component_tables_snapshot,
            rng_state,
            event_queue_state: EventQueueState::empty(),
            mutation_queue_state: MutationQueueState::empty(),
            world_hash: String::new(),
        };

        // Compute world hash from serialized state (D9)
        let world_hash = self.serializer.compute_hash(&snapshot)?;
        snapshot.world_hash = world_hash;

        Ok(snapshot)
    }

    /// Takes a snapshot and stores it in the snapshot store.
    ///
    /// Convenience method combining take_snapshot() + store().
    pub fn take_and_store(
        &mut self,
        tick: Tick,
        entity_store: &EntityStore,
        table_store: &ComponentTableStore,
    ) -> Result<WorldSnapshot, XaceError> {
        let snapshot = self.take_snapshot(tick, entity_store, table_store)?;
        let snapshot_clone = snapshot.clone_minimal();
        self.store.store(snapshot_clone)?;
        Ok(snapshot)
    }

    // ── Snapshot Restore ───────────────────────────────────────────────────

    /// Restores the world to the exact state captured in the snapshot.
    ///
    /// After restore:
    /// - EntityStore reflects snapshot entity states
    /// - ComponentTableStore reflects snapshot component data
    /// - World hash matches snapshot.world_hash
    ///
    /// ## Validation (I7, I10)
    /// Returns error if snapshot schema_version doesn't match current.
    /// Returns error if world hash verification fails after restore.
    pub fn restore_snapshot(
        &mut self,
        snapshot: &WorldSnapshot,
        entity_store: &mut EntityStore,
        table_store: &mut ComponentTableStore,
    ) -> Result<(), XaceError> {
        // Validate schema version (I7, D10)
        if snapshot.schema_version != self.schema_version {
            return Err(XaceError::ValidationFailure {
                message: format!(
                    "Cannot restore snapshot with schema_version '{}' — \
                     current schema_version is '{}' (I7, D10)",
                    snapshot.schema_version, self.schema_version
                ),
                context: ErrorContext::new("SnapshotEngine", "restore_snapshot")
                    .with_tick(snapshot.tick),
                rule_violated: "I7".into(),
                failed_path: "schema_version".into(),
            });
        }

        // Restore EntityStore
        self.restore_entity_store(snapshot, entity_store);

        // Restore ComponentTableStore
        self.restore_component_tables(snapshot, table_store);

        // Verify world hash after restore (D9, I10)
        let restored_snapshot = self.take_snapshot(snapshot.tick, entity_store, table_store)?;

        if restored_snapshot.world_hash != snapshot.world_hash {
            return Err(XaceError::FatalError {
                message: format!(
                    "World hash mismatch after restore at tick {} — \
                     expected '{}', got '{}'. Snapshot restore failed (I10, D9)",
                    snapshot.tick, snapshot.world_hash, restored_snapshot.world_hash,
                ),
                context: ErrorContext::new("SnapshotEngine", "restore_snapshot")
                    .with_tick(snapshot.tick),
                snapshot_recovery_possible: false,
            });
        }

        Ok(())
    }

    // ── Store Access ───────────────────────────────────────────────────────

    /// Stores a pre-built snapshot.
    pub fn store_snapshot(&mut self, snapshot: WorldSnapshot) -> Result<(), XaceError> {
        self.store.store(snapshot)
    }

    /// Returns the stored snapshot for the given tick.
    pub fn get_snapshot(&self, tick: Tick) -> Option<&WorldSnapshot> {
        self.store.get(tick)
    }

    /// Returns the most recent stored snapshot.
    pub fn latest_snapshot(&self) -> Option<&WorldSnapshot> {
        self.store.latest()
    }

    /// Returns the nearest snapshot at or before the given tick.
    /// Used by the rollback system.
    pub fn nearest_snapshot_for_rollback(&self, tick: Tick) -> Option<&WorldSnapshot> {
        self.store.nearest_before_or_at(tick)
    }

    /// Verifies that two snapshots represent identical world state.
    pub fn verify_match(&self, snapshot_a: &WorldSnapshot, snapshot_b: &WorldSnapshot) -> bool {
        snapshot_a.world_hash == snapshot_b.world_hash && !snapshot_a.world_hash.is_empty()
    }

    /// Marks a tick as a checkpoint in the snapshot store.
    pub fn mark_checkpoint(&mut self, tick: Tick) {
        self.store.mark_checkpoint(tick);
    }

    /// Returns the number of stored snapshots.
    pub fn stored_count(&self) -> usize {
        self.store.count()
    }

    /// Updates schema version after CGS mutation.
    pub fn update_schema_version(
        &mut self,
        schema_version: impl Into<String>,
        execution_plan_version: u32,
    ) {
        self.schema_version = schema_version.into();
        self.execution_plan_version = execution_plan_version;
    }

    // ── Internal — Capture ─────────────────────────────────────────────────

    fn capture_entity_store(&self, entity_store: &EntityStore, tick: Tick) -> EntityStoreSnapshot {
        // All entity metadata sorted by EntityID ASC (D3)
        let entities: Vec<EntityRecord> = entity_store
            .all_metadata_sorted()
            .into_iter()
            .map(|meta| EntityRecord {
                entity_id: meta.id,
                state: meta.state.clone(),
                created_tick: meta.created_tick,
                destroyed_tick: meta.destroyed_tick,
                tags: meta.tags.clone(),
            })
            .collect();

        EntityStoreSnapshot {
            next_entity_id: entity_store.peek_next_id(),
            entities,
        }
    }

    fn capture_component_tables(
        &self,
        table_store: &ComponentTableStore,
    ) -> ComponentTablesSnapshot {
        let mut tables = std::collections::BTreeMap::new();

        // Tables in type_id ascending order (D11)
        for (type_id, table) in table_store.all_tables() {
            // Rows in EntityID ascending order (D3)
            let rows: std::collections::BTreeMap<u64, String> = table
                .iter()
                .map(|(entity_id, json)| (entity_id, json.to_string()))
                .collect();

            tables.insert(
                type_id,
                xace_core::runtime::world_snapshot::ComponentTableSnapshot {
                    component_type_id: type_id,
                    component_type_name: String::new(), // or fetch actual name if available
                    rows,
                },
            );
        }

        ComponentTablesSnapshot { tables }
    }

    // ── Internal — Restore ─────────────────────────────────────────────────

    fn restore_entity_store(&self, snapshot: &WorldSnapshot, entity_store: &mut EntityStore) {
        let store_snap = &snapshot.entity_store_snapshot;

        // Rebuild entity metadata from snapshot records
        let records: Vec<xace_core::entity_metadata::EntityMetadata> = store_snap
            .entities
            .iter()
            .map(|r| xace_core::entity_metadata::EntityMetadata {
                id: r.entity_id,
                state: r.state.clone(),
                created_tick: r.created_tick,
                destroyed_tick: r.destroyed_tick,
                tags: r.tags.clone(),
            })
            .collect();

        entity_store.restore_from_snapshot(
            records,
            store_snap.next_entity_id,
            vec![], // archived_ids not in snapshot struct yet — added in Phase 6
        );
    }

    fn restore_component_tables(
        &self,
        snapshot: &WorldSnapshot,
        table_store: &mut ComponentTableStore,
    ) {
        for (type_id, table_record) in &snapshot.component_tables_snapshot.tables {
            if let Some(table) = table_store.get_table_mut(*type_id) {
                let entries: Vec<(u64, String)> = table_record
                    .rows
                    .iter()
                    .map(|(id, json)| (*id, json.clone()))
                    .collect();
                table.restore_from_snapshot(entries);
            }
        }
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::component_tables::ComponentTableStore;
    use crate::entity_store::EntityStore;

    fn setup() -> (SnapshotEngine, EntityStore, ComponentTableStore) {
        let engine = SnapshotEngine::standard("0.1.0", 1, 42);
        let entity_store = EntityStore::new();
        let mut table_store = ComponentTableStore::new();
        table_store.register_table(1, "COMP_TRANSFORM_V1").unwrap();
        table_store.register_table(2, "COMP_IDENTITY_V1").unwrap();
        (engine, entity_store, table_store)
    }

    #[test]
    fn take_snapshot_captures_entities() {
        let (mut engine, mut es, ts) = setup();
        let id = es.create_entity(0).unwrap();
        let snap = engine.take_snapshot(10, &es, &ts).unwrap();
        assert_eq!(snap.tick, 10);
        assert!(snap
            .entity_store_snapshot
            .entities
            .iter()
            .any(|e| e.entity_id == id));
    }

    #[test]
    fn take_snapshot_captures_components() {
        let (mut engine, mut es, mut ts) = setup();
        let id = es.create_entity(0).unwrap();
        ts.add_component(id, 1, r#"{"x":5.0}"#.into(), 0).unwrap();
        let snap = engine.take_snapshot(0, &es, &ts).unwrap();
        let table = snap.component_tables_snapshot.tables.get(&1).unwrap();
        assert!(table.rows.contains_key(&id));
    }

    #[test]
    fn snapshot_has_world_hash() {
        let (mut engine, es, ts) = setup();
        let snap = engine.take_snapshot(0, &es, &ts).unwrap();
        assert!(!snap.world_hash.is_empty());
        assert_eq!(snap.world_hash.len(), 16);
    }

    #[test]
    fn identical_worlds_identical_hash() {
        let (mut engine1, mut es1, mut ts1) = setup();
        let (mut engine2, mut es2, mut ts2) = setup();

        for store in [&mut es1, &mut es2] {
            store.create_entity(0).unwrap();
        }
        for ts in [&mut ts1, &mut ts2] {
            ts.add_component(1, 1, r#"{"x":1.0}"#.into(), 0).unwrap();
        }

        let snap1 = engine1.take_snapshot(5, &es1, &ts1).unwrap();
        let snap2 = engine2.take_snapshot(5, &es2, &ts2).unwrap();
        assert_eq!(snap1.world_hash, snap2.world_hash);
    }

    #[test]
    fn different_worlds_different_hash() {
        let (mut engine1, mut es1, mut ts1) = setup();
        let (mut engine2, mut es2, mut ts2) = setup();

        es1.create_entity(0).unwrap();
        // es2 has no entities

        let snap1 = engine1.take_snapshot(0, &es1, &ts1).unwrap();
        let snap2 = engine2.take_snapshot(0, &es2, &ts2).unwrap();
        assert_ne!(snap1.world_hash, snap2.world_hash);
    }

    #[test]
    fn restore_reconstructs_entities() {
        let (mut engine, mut es, ts) = setup();
        es.create_entity(0).unwrap();
        es.create_entity(0).unwrap();
        let snap = engine.take_snapshot(0, &es, &ts).unwrap();

        // Clear and restore
        let mut es2 = EntityStore::new();
        let mut ts2 = ComponentTableStore::new();
        ts2.register_table(1, "COMP_TRANSFORM_V1").unwrap();
        ts2.register_table(2, "COMP_IDENTITY_V1").unwrap();

        engine.restore_snapshot(&snap, &mut es2, &mut ts2).unwrap();
        assert_eq!(es2.alive_count(), 2);
    }

    #[test]
    fn restore_reconstructs_components() {
        let (mut engine, mut es, mut ts) = setup();
        let id = es.create_entity(0).unwrap();
        ts.add_component(id, 1, r#"{"x":9.0}"#.into(), 0).unwrap();
        let snap = engine.take_snapshot(0, &es, &ts).unwrap();

        let mut es2 = EntityStore::new();
        let mut ts2 = ComponentTableStore::new();
        ts2.register_table(1, "COMP_TRANSFORM_V1").unwrap();
        ts2.register_table(2, "COMP_IDENTITY_V1").unwrap();

        engine.restore_snapshot(&snap, &mut es2, &mut ts2).unwrap();
        assert_eq!(ts2.get_component(id, 1), Some(r#"{"x":9.0}"#));
    }

    #[test]
    fn restore_wrong_schema_version_fails() {
        let (mut engine, es, ts) = setup();
        let mut snap = engine.take_snapshot(0, &es, &ts).unwrap();
        snap.schema_version = "9.9.9".into(); // Wrong version

        let mut es2 = EntityStore::new();
        let mut ts2 = ComponentTableStore::new();
        ts2.register_table(1, "COMP_TRANSFORM_V1").unwrap();
        ts2.register_table(2, "COMP_IDENTITY_V1").unwrap();

        assert!(engine.restore_snapshot(&snap, &mut es2, &mut ts2).is_err());
    }

    #[test]
    fn take_and_store_increments_stored_count() {
        let (mut engine, es, ts) = setup();
        engine.take_and_store(0, &es, &ts).unwrap();
        engine.take_and_store(1, &es, &ts).unwrap();
        assert_eq!(engine.stored_count(), 2);
    }

    #[test]
    fn verify_match_identical_hashes() {
        let (mut engine, es, ts) = setup();
        let snap1 = engine.take_snapshot(0, &es, &ts).unwrap();
        let snap2 = engine.take_snapshot(0, &es, &ts).unwrap();
        // Same world state at same tick = same hash
        assert!(engine.verify_match(&snap1, &snap2));
    }

    #[test]
    fn nearest_snapshot_for_rollback() {
        let (mut engine, es, ts) = setup();
        engine.take_and_store(10, &es, &ts).unwrap();
        engine.take_and_store(20, &es, &ts).unwrap();
        engine.take_and_store(30, &es, &ts).unwrap();
        let nearest = engine.nearest_snapshot_for_rollback(25);
        assert_eq!(nearest.unwrap().tick, 20);
    }
}
