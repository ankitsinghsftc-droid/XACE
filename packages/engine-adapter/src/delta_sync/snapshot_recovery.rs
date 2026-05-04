//! # Snapshot Recovery
//!
//! Builds and manages full `SnapshotPayload` transmissions for initial
//! engine connection and desync recovery.
//!
//! ## When a SNAPSHOT is Sent
//! 1. **Initial connection** — engine adapter just connected, has no world state.
//! 2. **Desync recovery** — `ResyncDetector` detected a sequence gap, schema
//!    mismatch, or explicit snapshot request from the engine.
//! 3. **Periodic refresh** (Phase 15) — sent every N ticks in multiplayer to
//!    prevent long-session drift.
//!
//! ## What a SNAPSHOT Contains
//! A `SnapshotPayload` is the wire-format subset of `WorldSnapshot` — only
//! what the engine adapter needs to reconstruct its scene:
//! - All Active and Disabled entities
//! - All component data for each entity
//! - Schema and ExecutionPlan versions for validation
//! - The `last_delta_sequence_id` so the engine can reset its sequence tracker
//!
//! ## Post-Snapshot DELTA Sequencing
//! After sending a SNAPSHOT, the engine adapter resets its DELTA sequence
//! tracker to `last_delta_sequence_id + 1` (the value carried in the snapshot).
//! The `SnapshotRecovery` struct tracks this and provides the correct
//! `next_delta_sequence_id` to embed in the snapshot payload.
//!
//! ## Compressor Reset
//! After a SNAPSHOT is sent, the `DeltaCompressor` cache must be rebuilt
//! from the snapshot payload — the engine now holds exactly the snapshot state,
//! so future DELTA compression must compare against that baseline.
//! `SnapshotRecovery::build_payload()` returns the payload ready for
//! `DeltaCompressor::rebuild_from_snapshot()`.

use xace_core::entity_state::EntityState;
use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::runtime::world_snapshot::WorldSnapshot;
use xace_core::wire::snapshot_payload::{
    SnapshotComponentRecord, SnapshotEntityRecord, SnapshotPayload, SnapshotReason,
};

// ── Recovery Metrics ──────────────────────────────────────────────────────────

/// Accumulated metrics for snapshot transmission.
#[derive(Debug, Clone, Default)]
pub struct SnapshotRecoveryMetrics {
    /// Total snapshots built.
    pub snapshots_built: u64,
    /// Total entities included across all snapshots.
    pub total_entities_sent: u64,
    /// Total component instances included across all snapshots.
    pub total_components_sent: u64,
    /// Snapshots sent due to initial connection.
    pub initial_connection_count: u64,
    /// Snapshots sent due to desync recovery.
    pub desync_recovery_count: u64,
    /// Snapshots sent due to explicit request.
    pub explicit_request_count: u64,
}

// ── Snapshot Recovery ─────────────────────────────────────────────────────────

/// Builds `SnapshotPayload` values from a `WorldSnapshot` for transmission
/// to the engine adapter.
///
/// ## One Instance Per Connection
/// Create a new `SnapshotRecovery` when an engine adapter connects.
/// It tracks the `last_delta_sequence_id` so each snapshot carries the
/// correct baseline for the engine's sequence tracker.
pub struct SnapshotRecovery {
    /// The schema version for this session.
    schema_version: String,

    /// The ExecutionPlan version for this session.
    execution_plan_version: u32,

    /// The most recent DELTA `sequence_id` sent before this snapshot.
    /// Embedded in the snapshot so the engine can re-anchor its tracker.
    last_delta_sequence_id: u64,

    /// Accumulated metrics.
    metrics: SnapshotRecoveryMetrics,
}

impl SnapshotRecovery {
    // ── Construction ──────────────────────────────────────────────────────────

    /// Creates a new `SnapshotRecovery` for a new engine connection.
    ///
    /// `last_delta_sequence_id` should be 0 for the initial connection
    /// (no DELTAs have been sent yet) or the most recent DELTA sequence_id
    /// for recovery snapshots.
    pub fn new(
        schema_version: impl Into<String>,
        execution_plan_version: u32,
        last_delta_sequence_id: u64,
    ) -> Self {
        Self {
            schema_version: schema_version.into(),
            execution_plan_version,
            last_delta_sequence_id,
            metrics: SnapshotRecoveryMetrics::default(),
        }
    }

    // ── Primary API ───────────────────────────────────────────────────────────

    /// Updates the `last_delta_sequence_id`.
    ///
    /// Call this every time a DELTA is successfully sent so the next
    /// snapshot carries the correct sequence baseline.
    pub fn update_last_delta_sequence(&mut self, sequence_id: u64) {
        self.last_delta_sequence_id = sequence_id;
    }

    /// Builds a `SnapshotPayload` from the current `WorldSnapshot`.
    ///
    /// Includes all Active and Disabled entities with their full component data.
    /// Excludes DestroyRequested, Destroyed, and Archived entities — the engine
    /// has no use for entities that no longer exist in the scene.
    ///
    /// The payload is ready to serialize and send as a SNAPSHOT WireMessage,
    /// and to pass to `DeltaCompressor::rebuild_from_snapshot()`.
    ///
    /// Returns `Err` if the world snapshot fails its structural validation.
    pub fn build_payload(
        &mut self,
        world_snapshot: &WorldSnapshot,
        reason: SnapshotReason,
    ) -> Result<SnapshotPayload, XaceError> {
        // Validate the snapshot before building — don't send a corrupted snapshot
        world_snapshot.validate().map_err(|e| XaceError::FatalError {
            message: format!(
                "SnapshotRecovery: WorldSnapshot validation failed — {}",
                e
            ),
            context: ErrorContext::new("SnapshotRecovery", "build_payload")
                .with_tick(world_snapshot.tick),
            snapshot_recovery_possible: false,
        })?;

        // Update metrics counter for this reason type
        match reason {
            SnapshotReason::InitialConnection  => self.metrics.initial_connection_count += 1,
            SnapshotReason::DesyncRecovery     => self.metrics.desync_recovery_count += 1,
            SnapshotReason::ExplicitRequest    => self.metrics.explicit_request_count += 1,
            SnapshotReason::PeriodicRefresh    => {}
        }

        let mut payload = SnapshotPayload::new(
            world_snapshot.tick,
            &self.schema_version,
            self.execution_plan_version,
            &world_snapshot.cgs_hash,
            &world_snapshot.world_hash,
            self.last_delta_sequence_id,
            reason,
        );

        // Build entity records from the entity store and component tables
        let entity_store = &world_snapshot.entity_store_snapshot;
        let component_tables = &world_snapshot.component_tables_snapshot;

        let mut entity_count = 0usize;
        let mut component_count = 0usize;

        for entity_record in &entity_store.entities {
            // Only include Active and Disabled entities
            match entity_record.state {
                EntityState::Active | EntityState::Disabled => {}
                _ => continue,
            }

            let mut wire_entity = SnapshotEntityRecord::new(
                entity_record.entity_id,
                entity_record.state.clone(),
            );
            wire_entity.tags = entity_record.tags.clone();

            // Collect all component data for this entity from all tables
            // component_tables.tables is BTreeMap<type_id, table> — type_id ASC (D11)
            for (type_id, table) in &component_tables.tables {
                if let Some(component_json) = table.get(entity_record.entity_id) {
                    wire_entity.add_component(SnapshotComponentRecord::new(
                        *type_id,
                        &table.component_type_name,
                        component_json,
                    ));
                    component_count += 1;
                }
            }

            payload.add_entity(wire_entity);
            entity_count += 1;
        }

        self.metrics.snapshots_built += 1;
        self.metrics.total_entities_sent += entity_count as u64;
        self.metrics.total_components_sent += component_count as u64;

        Ok(payload)
    }

    /// Builds a partial snapshot containing only the specified entity IDs.
    ///
    /// Used for late-join interest management in Phase 15 — only send the
    /// entities relevant to the joining peer's area of interest.
    pub fn build_partial_payload(
        &mut self,
        world_snapshot: &WorldSnapshot,
        entity_ids: &[u64],
        reason: SnapshotReason,
    ) -> Result<SnapshotPayload, XaceError> {
        let mut payload = self.build_payload(world_snapshot, reason)?;
        payload.is_full = false;

        // Filter to only the requested entity IDs
        let id_set: std::collections::BTreeSet<u64> =
            entity_ids.iter().copied().collect();
        payload.entities.retain(|e| id_set.contains(&e.entity_id));

        Ok(payload)
    }

    // ── Inspection ────────────────────────────────────────────────────────────

    /// Returns the current `last_delta_sequence_id`.
    pub fn last_delta_sequence_id(&self) -> u64 {
        self.last_delta_sequence_id
    }

    /// Returns accumulated snapshot recovery metrics.
    pub fn metrics(&self) -> &SnapshotRecoveryMetrics {
        &self.metrics
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::entity_state::EntityState;
    use xace_core::runtime::world_snapshot::{
        ComponentTableSnapshot, EntityRecord, WorldSnapshot,
    };

    fn recovery() -> SnapshotRecovery {
        SnapshotRecovery::new("0.1.0", 1, 0)
    }

    fn world_snapshot_with_entities(
        tick: u64,
        entities: Vec<(u64, EntityState)>,
    ) -> WorldSnapshot {
        let mut snap = WorldSnapshot::empty("0.1.0", 1, 42);
        snap.tick = tick;
        snap.world_hash = "hash_abc".into();
        snap.cgs_hash = "cgs_hash".into();

        for (id, state) in entities {
            snap.entity_store_snapshot
                .entities
                .push(EntityRecord::new(id, state, 0));
        }
        if let Some(max_id) = snap.entity_store_snapshot.entities.iter().map(|e| e.entity_id).max() {
            snap.entity_store_snapshot.next_entity_id = max_id + 1;
        }
        snap
    }

    // ── Basic Payload Construction ────────────────────────────────────────────

    #[test]
    fn build_payload_includes_active_entities() {
        let mut r = recovery();
        let snap = world_snapshot_with_entities(1, vec![
            (1, EntityState::Active),
            (2, EntityState::Active),
        ]);
        let payload = r.build_payload(&snap, SnapshotReason::InitialConnection).unwrap();
        assert_eq!(payload.entity_count(), 2);
        assert!(payload.contains_entity(1));
        assert!(payload.contains_entity(2));
    }

    #[test]
    fn build_payload_includes_disabled_entities() {
        let mut r = recovery();
        let snap = world_snapshot_with_entities(1, vec![
            (1, EntityState::Active),
            (2, EntityState::Disabled),
        ]);
        let payload = r.build_payload(&snap, SnapshotReason::InitialConnection).unwrap();
        assert_eq!(payload.entity_count(), 2);
    }

    #[test]
    fn build_payload_excludes_destroyed_and_archived() {
        let mut r = recovery();
        let snap = world_snapshot_with_entities(1, vec![
            (1, EntityState::Active),
            (2, EntityState::Destroyed),
            (3, EntityState::Archived),
            (4, EntityState::DestroyRequested),
        ]);
        let payload = r.build_payload(&snap, SnapshotReason::InitialConnection).unwrap();
        assert_eq!(payload.entity_count(), 1);
        assert!(payload.contains_entity(1));
        assert!(!payload.contains_entity(2));
        assert!(!payload.contains_entity(3));
        assert!(!payload.contains_entity(4));
    }

    #[test]
    fn build_payload_carries_correct_tick() {
        let mut r = recovery();
        let snap = world_snapshot_with_entities(42, vec![]);
        // Empty snap needs a world_hash — re-add manually
        let mut snap2 = snap;
        snap2.world_hash = "h".into();
        // validate() requires world_hash non-empty and plan_version >= 1
        let payload = r.build_payload(&snap2, SnapshotReason::InitialConnection).unwrap();
        assert_eq!(payload.tick, 42);
    }

    #[test]
    fn build_payload_carries_last_delta_sequence_id() {
        let mut r = SnapshotRecovery::new("0.1.0", 1, 55);
        let mut snap = world_snapshot_with_entities(1, vec![]);
        snap.world_hash = "h".into();
        let payload = r.build_payload(&snap, SnapshotReason::DesyncRecovery).unwrap();
        assert_eq!(payload.last_delta_sequence_id, 55);
    }

    // ── Component Inclusion ───────────────────────────────────────────────────

    #[test]
    fn build_payload_includes_component_data() {
        let mut r = recovery();
        let mut snap = world_snapshot_with_entities(1, vec![(1, EntityState::Active)]);
        snap.world_hash = "h".into();

        let mut table = ComponentTableSnapshot::new(1, "COMP_TRANSFORM_V1");
        table.set(1, r#"{"x":10,"y":20}"#);
        snap.component_tables_snapshot.set_table(table);

        let payload = r.build_payload(&snap, SnapshotReason::InitialConnection).unwrap();
        let entity = payload.get_entity(1).unwrap();
        assert_eq!(entity.component_count(), 1);
        assert!(entity.has_component(1));
        let comp = entity.get_component(1).unwrap();
        assert!(comp.data_json.contains("10"));
    }

    // ── Partial Snapshot ──────────────────────────────────────────────────────

    #[test]
    fn build_partial_payload_filters_to_requested_entities() {
        let mut r = recovery();
        let mut snap = world_snapshot_with_entities(1, vec![
            (1, EntityState::Active),
            (2, EntityState::Active),
            (3, EntityState::Active),
        ]);
        snap.world_hash = "h".into();

        let payload = r
            .build_partial_payload(&snap, &[1, 3], SnapshotReason::InitialConnection)
            .unwrap();
        assert_eq!(payload.entity_count(), 2);
        assert!(payload.contains_entity(1));
        assert!(!payload.contains_entity(2));
        assert!(payload.contains_entity(3));
        assert!(!payload.is_full, "Partial snapshot must have is_full=false");
    }

    // ── Sequence Tracking ─────────────────────────────────────────────────────

    #[test]
    fn update_last_delta_sequence_reflected_in_next_payload() {
        let mut r = recovery();
        r.update_last_delta_sequence(100);
        assert_eq!(r.last_delta_sequence_id(), 100);
    }

    // ── Metrics ───────────────────────────────────────────────────────────────

    #[test]
    fn metrics_count_snapshots_by_reason() {
        let mut r = recovery();
        let mut snap = world_snapshot_with_entities(1, vec![(1, EntityState::Active)]);
        snap.world_hash = "h".into();

        r.build_payload(&snap, SnapshotReason::InitialConnection).unwrap();
        r.build_payload(&snap, SnapshotReason::DesyncRecovery).unwrap();
        r.build_payload(&snap, SnapshotReason::ExplicitRequest).unwrap();

        let m = r.metrics();
        assert_eq!(m.snapshots_built, 3);
        assert_eq!(m.initial_connection_count, 1);
        assert_eq!(m.desync_recovery_count, 1);
        assert_eq!(m.explicit_request_count, 1);
    }

    #[test]
    fn metrics_count_entities_and_components() {
        let mut r = recovery();
        let snap = world_snapshot_with_entities(1, vec![
            (1, EntityState::Active),
            (2, EntityState::Active),
        ]);
        let mut snap = snap;
        snap.world_hash = "h".into();

        r.build_payload(&snap, SnapshotReason::InitialConnection).unwrap();
        assert_eq!(r.metrics().total_entities_sent, 2);
    }

    // ── Validation Failure ────────────────────────────────────────────────────

    #[test]
    fn build_payload_fails_for_invalid_snapshot() {
        let mut r = recovery();
        // WorldSnapshot with empty world_hash fails validate()
        let snap = WorldSnapshot::empty("0.1.0", 1, 42); // world_hash is ""
        let result = r.build_payload(&snap, SnapshotReason::InitialConnection);
        assert!(result.is_err(), "Invalid snapshot must produce Err");
    }
}