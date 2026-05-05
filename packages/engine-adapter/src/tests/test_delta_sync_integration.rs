//! # Phase 8 — Delta Sync End-to-End Integration Tests
//!
//! Tests the complete delta sync pipeline under real-world conditions:
//! StateDelta → DeltaBuilder → DeltaCompressor → DeltaSyncEngine → WireMessage
//! → MockEngineAdapter → FeedbackBuffer → handlers.
//!
//! ## Coverage (MASTER_PLAN Phase 8)
//! 1. End-to-end: StateDelta produces correct WireMessage, mock engine applies it
//! 2. Sequence gap detection → ResyncDetector triggers SNAPSHOT recovery
//! 3. Full resync cycle: gap detected → SNAPSHOT sent → engine resets → deltas resume
//! 4. Performance: 100 entities, measure compressed delta byte size and field reduction
//! 5. Compressor efficiency: unchanged fields eliminated across tick sequences
//! 6. Ordering enforcement: D4 order in all produced DeltaPayloads

use std::collections::BTreeMap;

use xace_core::entity_state::EntityState;
use xace_core::runtime::state_delta::{
    AddedComponent, ComponentChange, DestroyedEntity, FieldChange, RemovedComponent,
    SpawnedEntity, StateDelta,
};
use xace_core::runtime::world_snapshot::{EntityRecord, WorldSnapshot};
use xace_core::wire::delta_payload::{DeltaPayload, WireComponentData, WireSpawnedEntity};
use xace_core::wire::snapshot_payload::{SnapshotPayload, SnapshotReason};

use xace_engine_adapter::delta_sync::delta_builder::DeltaBuilder;
use xace_engine_adapter::delta_sync::delta_compressor::DeltaCompressor;
use xace_engine_adapter::delta_sync::delta_sync_engine::{DeltaSyncEngine, DeltaSyncOutput};
use xace_engine_adapter::delta_sync::resync_detector::{
    ResyncConfig, ResyncDetector, ResyncTrigger,
};
use xace_engine_adapter::delta_sync::snapshot_recovery::SnapshotRecovery;

// ── Helpers ───────────────────────────────────────────────────────────────────

fn empty_delta(tick: u64) -> StateDelta {
    StateDelta::empty(tick, "0.1.0")
}

fn delta_with_spawn(tick: u64, entity_id: u64, actor: &str) -> StateDelta {
    let mut d = empty_delta(tick);
    d.record_spawn(SpawnedEntity::new(entity_id, actor));
    d
}

fn delta_with_field(tick: u64, entity_id: u64, field: &str, val: &str) -> StateDelta {
    let mut d = empty_delta(tick);
    d.record_component_update(
        entity_id,
        ComponentChange::single_field(1, "COMP_TRANSFORM_V1", field, val),
    );
    d
}

fn delta_with_many_entities(tick: u64, entity_count: u64) -> StateDelta {
    let mut d = empty_delta(tick);
    for i in 1..=entity_count {
        d.record_spawn(
            SpawnedEntity::new(i, "actor_zombie")
                .with_component(1, &format!(r#"{{"x":{i},"y":0,"z":0}}"#)),
        );
    }
    d
}

fn valid_world_snapshot(tick: u64, entity_count: u64) -> WorldSnapshot {
    let mut s = WorldSnapshot::empty("0.1.0", 1, 42);
    s.tick       = tick;
    s.world_hash = "hash_valid".into();
    s.cgs_hash   = "cgs_hash".into();
    for i in 1..=entity_count {
        s.entity_store_snapshot
            .entities
            .push(EntityRecord::new(i, EntityState::Active, 0));
    }
    if entity_count > 0 {
        s.entity_store_snapshot.next_entity_id = entity_count + 1;
    }
    s
}

fn engine() -> DeltaSyncEngine {
    DeltaSyncEngine::new(
        "0.1.0", 1, "default", 1,
        ResyncConfig {
            cooldown_ticks: 3,
            max_tick_drift: 100,
            tick_drift_detection: true,
        },
    )
}

// ── Mock Engine Adapter ───────────────────────────────────────────────────────
// Simulates a Unity adapter that receives DELTA/SNAPSHOT messages,
// applies them to a local entity store, and tracks sequence numbers.

struct MockEngineAdapter {
    /// EntityID → BTreeMap<component_type_id, component_json>
    entity_store: BTreeMap<u64, BTreeMap<u32, String>>,
    /// Sequence IDs of DELTAs received (for gap detection simulation)
    received_sequences: Vec<u64>,
    /// How many snapshots received
    snapshot_count: usize,
    /// How many deltas received
    delta_count: usize,
    /// Simulated next expected delta sequence (for gap detection)
    next_expected_seq: u64,
    /// Whether a gap has been detected
    gap_detected: bool,
}

impl MockEngineAdapter {
    fn new() -> Self {
        Self {
            entity_store: BTreeMap::new(),
            received_sequences: Vec::new(),
            snapshot_count: 0,
            delta_count: 0,
            next_expected_seq: 1,
            gap_detected: false,
        }
    }

    fn apply_output(&mut self, output: &DeltaSyncOutput) {
        match output {
            DeltaSyncOutput::Snapshot(snap) => self.apply_snapshot(snap),
            DeltaSyncOutput::Delta(delta)   => self.apply_delta(delta),
            DeltaSyncOutput::Nothing        => {}
        }
    }

    fn apply_snapshot(&mut self, snap: &SnapshotPayload) {
        self.entity_store.clear();
        for entity in &snap.entities {
            let entry = self.entity_store.entry(entity.entity_id).or_default();
            for (type_id, comp) in &entity.components {
                entry.insert(*type_id, comp.data_json.clone());
            }
        }
        // Reset sequence tracker from snapshot's last_delta_sequence_id
        self.next_expected_seq = snap.last_delta_sequence_id + 1;
        self.gap_detected = false;
        self.snapshot_count += 1;
    }

    fn apply_delta(&mut self, delta: &DeltaPayload) {
        // Sequence gap detection
        if delta.sequence_id < self.next_expected_seq {
            return; // duplicate — ignore
        }
        if delta.sequence_id > self.next_expected_seq {
            self.gap_detected = true;
        }
        self.next_expected_seq = delta.sequence_id + 1;
        self.received_sequences.push(delta.sequence_id);
        self.delta_count += 1;

        // Apply spawns
        for spawned in &delta.spawned_entities {
            let entry = self.entity_store.entry(spawned.entity_id).or_default();
            for comp in &spawned.initial_components {
                entry.insert(comp.component_type_id, comp.data_json.clone());
            }
        }

        // Apply modifications
        for (entity_id, entity_update) in &delta.modified_entities {
            let entry = self.entity_store.entry(*entity_id).or_default();
            for (type_id, comp_update) in &entity_update.component_updates {
                // Field-level update: merge into existing component JSON
                let comp_json = entry.entry(*type_id).or_insert_with(|| "{}".into());
                // In real adapter this would parse and merge JSON fields.
                // For test purposes we replace with a marker that fields changed.
                let field_names: Vec<&str> = comp_update.field_changes
                    .iter()
                    .map(|f| f.field_name.as_str())
                    .collect();
                *comp_json = format!(
                    "{{\"updated_fields\":{:?}}}",
                    field_names
                );
            }
        }

        // Apply destroys
        for destroyed in &delta.destroyed_entities {
            self.entity_store.remove(&destroyed.entity_id);
        }
    }

    fn entity_count(&self) -> usize {
        self.entity_store.len()
    }
}

// =============================================================================
// 1. End-to-End Pipeline Tests
// =============================================================================

#[cfg(test)]
mod e2e_pipeline {
    use super::*;

    #[test]
    fn first_tick_always_produces_snapshot() {
        let mut eng = engine();
        let snap = valid_world_snapshot(0, 0);
        let output = eng.process_tick(&empty_delta(0), &snap).unwrap();
        assert!(matches!(output, DeltaSyncOutput::Snapshot(_)),
            "First tick must produce SNAPSHOT (initial connection)");
    }

    #[test]
    fn snapshot_resets_mock_engine_entity_store() {
        let mut eng = engine();
        let snap = valid_world_snapshot(0, 5); // 5 entities
        let output = eng.process_tick(&empty_delta(0), &snap).unwrap();

        let mut mock = MockEngineAdapter::new();
        mock.apply_output(&output);

        assert_eq!(mock.snapshot_count, 1);
        assert_eq!(mock.entity_count(), 5);
        assert_eq!(mock.next_expected_seq, 1); // snap.last_delta_seq=0, so next=1
    }

    #[test]
    fn spawn_delta_arrives_at_mock_engine() {
        let mut eng = engine();
        let snap = valid_world_snapshot(0, 0);
        eng.process_tick(&empty_delta(0), &snap).unwrap(); // initial snapshot

        let mut mock = MockEngineAdapter::new();

        let output = eng.process_tick(&delta_with_spawn(1, 1, "actor_player"), &snap).unwrap();
        mock.apply_output(&output);

        assert!(matches!(output, DeltaSyncOutput::Delta(_)));
        assert_eq!(mock.delta_count, 1);
        assert_eq!(mock.entity_count(), 1);
    }

    #[test]
    fn destroy_delta_removes_entity_from_mock_engine() {
        let mut eng = engine();
        let snap = valid_world_snapshot(0, 1);
        let output0 = eng.process_tick(&empty_delta(0), &snap).unwrap(); // snapshot

        let mut mock = MockEngineAdapter::new();
        mock.apply_output(&output0);
        assert_eq!(mock.entity_count(), 1);

        let mut d = empty_delta(1);
        d.record_destroy(DestroyedEntity::new(1, 0));
        let output1 = eng.process_tick(&d, &snap).unwrap();
        mock.apply_output(&output1);

        assert_eq!(mock.entity_count(), 0, "Entity must be removed after DELTA destroy");
    }

    #[test]
    fn delta_sequence_ids_monotonically_increase() {
        let mut eng = engine();
        let snap = valid_world_snapshot(0, 1);
        eng.process_tick(&empty_delta(0), &snap).unwrap(); // snapshot

        let mut sequences = Vec::new();
        for tick in 1..=10 {
            let d = delta_with_spawn(tick, tick, "actor_zombie");
            if let DeltaSyncOutput::Delta(payload) = eng.process_tick(&d, &snap).unwrap() {
                sequences.push(payload.sequence_id);
            }
        }

        // Each sequence must be strictly greater than the previous
        for i in 1..sequences.len() {
            assert!(
                sequences[i] > sequences[i - 1],
                "Sequence IDs must be monotonically increasing: {:?}",
                sequences
            );
        }
    }

    #[test]
    fn empty_delta_after_snapshot_returns_nothing() {
        let mut eng = engine();
        let snap = valid_world_snapshot(0, 0);
        eng.process_tick(&empty_delta(0), &snap).unwrap();

        let output = eng.process_tick(&empty_delta(1), &snap).unwrap();
        assert!(matches!(output, DeltaSyncOutput::Nothing));
    }

    #[test]
    fn d4_ordering_spawn_before_destroy_in_delta() {
        // D4: spawn → add → modify → remove → destroy
        let mut d = empty_delta(1);
        d.record_spawn(SpawnedEntity::new(1, "actor_player"));
        d.record_destroy(DestroyedEntity::new(99, 0)); // destroy a different entity
        d.record_component_update(
            2,
            ComponentChange::single_field(1, "COMP_TRANSFORM_V1", "x", "5.0"),
        );

        let (payload, _) = DeltaBuilder::build(&d, 1);

        // Verify D4 ordering: spawned first, then modified, then destroyed
        assert_eq!(payload.spawned_entities.len(), 1);
        assert_eq!(payload.spawned_entities[0].entity_id, 1);
        assert!(payload.modified_entities.contains_key(&2));
        assert_eq!(payload.destroyed_entities.len(), 1);
        assert_eq!(payload.destroyed_entities[0].entity_id, 99);
    }
}

// =============================================================================
// 2. Sequence Gap Detection → SNAPSHOT Recovery
// =============================================================================

#[cfg(test)]
mod sequence_gap_and_recovery {
    use super::*;

    #[test]
    fn sequence_gap_detected_by_mock_engine() {
        let mut eng = engine();
        let snap = valid_world_snapshot(0, 0);
        eng.process_tick(&empty_delta(0), &snap).unwrap();

        let mut mock = MockEngineAdapter::new();

        // Send tick 1 and tick 2 normally
        let o1 = eng.process_tick(&delta_with_spawn(1, 1, "actor"), &snap).unwrap();
        mock.apply_output(&o1);
        let o2 = eng.process_tick(&delta_with_spawn(2, 2, "actor"), &snap).unwrap();
        mock.apply_output(&o2);

        // Simulate: tick 3's delta is dropped (gap)
        // We advance the engine but mock never receives it
        let _dropped = eng.process_tick(&delta_with_spawn(3, 3, "actor"), &snap).unwrap();

        // Tick 4 arrives at mock — mock detects gap (seq 4 arrived, expected 3)
        let o4 = eng.process_tick(&delta_with_spawn(4, 4, "actor"), &snap).unwrap();
        if let DeltaSyncOutput::Delta(payload) = &o4 {
            // Simulate mock receiving seq 4 when it expected seq 3
            let expected = mock.next_expected_seq;
            let received = payload.sequence_id;
            if received > expected {
                mock.gap_detected = true;
            }
            mock.apply_output(&o4);
        }

        assert!(mock.gap_detected, "Mock engine must detect the sequence gap");
    }

    #[test]
    fn resync_detector_raises_trigger_on_gap_report() {
        let mut det = ResyncDetector::new(ResyncConfig {
            cooldown_ticks: 0, max_tick_drift: 100, tick_drift_detection: true,
        });
        det.report_sequence_gap(3, 5);
        assert!(det.needs_resync());
        assert!(matches!(
            det.pending_trigger(),
            Some(ResyncTrigger::SequenceGap { expected_sequence: 3, received_sequence: 5 })
        ));
    }

    #[test]
    fn resync_detector_produces_snapshot_at_next_tick() {
        let mut eng = engine();
        let snap = valid_world_snapshot(0, 3);
        eng.process_tick(&empty_delta(0), &snap).unwrap(); // initial snapshot

        // Engine reports a sequence gap
        eng.report_sequence_gap(2, 5);
        assert!(eng.needs_resync());

        // Next tick must produce SNAPSHOT not DELTA
        let output = eng.process_tick(&delta_with_spawn(5, 1, "actor"), &snap).unwrap();
        assert!(
            matches!(output, DeltaSyncOutput::Snapshot(_)),
            "Gap must trigger SNAPSHOT recovery"
        );
    }

    #[test]
    fn full_resync_cycle_engine_reanchors_sequence() {
        let mut eng = engine();
        let snap = valid_world_snapshot(0, 2);

        // Initial SNAPSHOT
        let o0 = eng.process_tick(&empty_delta(0), &snap).unwrap();
        let mut mock = MockEngineAdapter::new();
        mock.apply_output(&o0);

        // Normal deltas ticks 1–2
        for tick in 1..=2u64 {
            let o = eng.process_tick(&delta_with_spawn(tick, tick, "actor"), &snap).unwrap();
            mock.apply_output(&o);
        }

        // Report gap → trigger recovery
        eng.report_sequence_gap(3, 7);
        let recovery_output = eng.process_tick(&empty_delta(3), &snap).unwrap();
        assert!(matches!(recovery_output, DeltaSyncOutput::Snapshot(_)),
            "Recovery tick must produce SNAPSHOT");

        // Extract last_delta_sequence_id from the recovery snapshot
        if let DeltaSyncOutput::Snapshot(ref snap_payload) = recovery_output {
            // Re-anchor mock from snapshot
            mock.apply_output(&recovery_output);
            // Mock's next_expected_seq must now be last_delta_seq + 1
            assert_eq!(
                mock.next_expected_seq,
                snap_payload.last_delta_sequence_id + 1,
                "Mock must re-anchor sequence tracker from SNAPSHOT"
            );
        }

        // Deltas after recovery should work normally
        let o_post = eng.process_tick(&delta_with_spawn(4, 99, "actor_new"), &snap).unwrap();
        assert!(matches!(o_post, DeltaSyncOutput::Delta(_)),
            "Delta must resume normally after recovery");
        mock.apply_output(&o_post);
    }

    #[test]
    fn cooldown_prevents_snapshot_flood() {
        let mut det = ResyncDetector::new(ResyncConfig {
            cooldown_ticks: 5, max_tick_drift: 100, tick_drift_detection: true,
        });
        // First resync fires at tick 0
        det.request_resync(ResyncTrigger::InitialConnection);
        det.check_and_consume(0).unwrap();
        det.mark_snapshot_sent(0);

        // Request again immediately
        det.request_resync(ResyncTrigger::ExplicitRequest);

        // Ticks 1–4 are in cooldown
        for tick in 1..5u64 {
            assert!(
                det.check_and_consume(tick).is_none(),
                "Cooldown must suppress SNAPSHOT at tick {}", tick
            );
        }

        // Tick 5 is past cooldown
        assert!(
            det.check_and_consume(5).is_some(),
            "SNAPSHOT must fire after cooldown expires"
        );
    }

    #[test]
    fn schema_version_mismatch_triggers_resync() {
        let mut det = ResyncDetector::with_defaults();
        det.report_schema_mismatch("0.1.0", "0.2.0");
        assert!(det.needs_resync());
        assert!(matches!(
            det.pending_trigger(),
            Some(ResyncTrigger::SchemaVersionDrift { .. })
        ));
    }

    #[test]
    fn explicit_snapshot_request_fires_immediately_after_cooldown() {
        let mut eng = engine();
        let snap = valid_world_snapshot(0, 0);
        eng.process_tick(&empty_delta(0), &snap).unwrap(); // initial snapshot (tick 0)

        // Wait past cooldown (3 ticks in our config)
        eng.process_tick(&empty_delta(1), &snap).unwrap();
        eng.process_tick(&empty_delta(2), &snap).unwrap();
        eng.process_tick(&empty_delta(3), &snap).unwrap();

        eng.report_explicit_snapshot_request();
        let output = eng.process_tick(&empty_delta(4), &snap).unwrap();
        assert!(
            matches!(output, DeltaSyncOutput::Snapshot(_)),
            "Explicit SNAPSHOT request must fire immediately (past cooldown)"
        );
    }
}

// =============================================================================
// 3. Performance Test — 100 Entities
// =============================================================================

#[cfg(test)]
mod performance {
    use super::*;

    /// Measures the compressed delta size for 100 entities all updating one field.
    /// This is the core Phase 8 performance benchmark.
    #[test]
    fn compressed_delta_100_entities_first_tick_reasonable_size() {
        let entity_count = 100u64;
        let d = delta_with_many_entities(1, entity_count);
        let (payload, metrics) = DeltaBuilder::build(&d, 1);

        // 100 spawns should all be present
        assert_eq!(payload.spawned_entities.len() as u64, entity_count);

        // Serialized size check: 100 simple entities should be under 64 KiB
        let json = serde_json::to_string(&payload).unwrap();
        let size_bytes = json.len();
        assert!(
            size_bytes < 64 * 1024,
            "100-entity delta must be under 64 KiB, got {} bytes",
            size_bytes
        );

        println!(
            "[Phase 8 Perf] 100 entity spawns: {} bytes ({:.1} KiB)",
            size_bytes,
            size_bytes as f64 / 1024.0
        );
    }

    /// Compressor eliminates unchanged fields: 100 entities, only 1 actually moved.
    #[test]
    fn compressor_eliminates_unchanged_fields_at_100_entities() {
        let entity_count = 100u64;
        let mut compressor = DeltaCompressor::new();

        // First tick: all 100 entities spawn with x=0
        let d1 = delta_with_many_entities(1, entity_count);
        let (mut p1, _) = DeltaBuilder::build(&d1, 1);
        compressor.compress(&mut p1);

        // Second tick: only entity 1 moves to x=5. All others stay at x=0.
        let mut d2 = empty_delta(2);
        for i in 1..=entity_count {
            let x = if i == 1 { "5.0" } else { "0.0" };
            d2.record_component_update(
                i,
                ComponentChange::single_field(
                    1, "COMP_TRANSFORM_V1",
                    "x", x,
                ),
            );
        }
        let (mut p2, _) = DeltaBuilder::build(&d2, 2);

        // Before compression: 100 entity updates, each with 1 field
        let fields_before = p2.modified_entities.len();
        compressor.compress(&mut p2);

        // After compression: only entity 1 should remain (99 eliminated)
        let fields_after = p2.modified_entities.len();

        assert_eq!(fields_after, 1,
            "Only the 1 changed entity must survive compression, got {}", fields_after);
        assert!(
            fields_before > fields_after,
            "Compressor must eliminate unchanged entities: before={} after={}",
            fields_before, fields_after
        );

        let m = compressor.metrics();
        assert!(
            m.entity_updates_eliminated >= 99,
            "At least 99 entity updates must be eliminated, got {}",
            m.entity_updates_eliminated
        );
        assert!(
            m.compression_ratio() >= 0.9,
            "Compression ratio must be ≥ 90% for 99/100 unchanged entities, got {:.2}",
            m.compression_ratio()
        );

        println!(
            "[Phase 8 Perf] 100 entities, 1 changed: eliminated={}, ratio={:.1}%",
            m.entity_updates_eliminated,
            m.compression_ratio() * 100.0
        );
    }

    /// End-to-end size test: 100 entities ticking for 10 ticks with small changes.
    #[test]
    fn delta_size_100_entities_10_ticks_within_budget() {
        let entity_count = 100u64;
        let mut eng = engine();
        let snap = valid_world_snapshot(0, entity_count);

        // Initial snapshot
        eng.process_tick(&empty_delta(0), &snap).unwrap();

        let mut total_delta_bytes = 0usize;
        let mut delta_count = 0;

        for tick in 1..=10u64 {
            // Each tick: only one entity moves
            let moving_entity = (tick % entity_count) + 1;
            let d = delta_with_field(
                tick, moving_entity, "x",
                &format!("{}", tick as f32 * 0.1),
            );
            let output = eng.process_tick(&d, &snap).unwrap();

            match &output {
                DeltaSyncOutput::Delta(payload) => {
                    let json = serde_json::to_string(payload).unwrap();
                    total_delta_bytes += json.len();
                    delta_count += 1;
                }
                DeltaSyncOutput::Nothing => {
                    // Compression eliminated this tick — good
                }
                DeltaSyncOutput::Snapshot(_) => {
                    panic!("Unexpected SNAPSHOT during normal ticking");
                }
            }
        }

        let avg_bytes = if delta_count > 0 {
            total_delta_bytes / delta_count
        } else {
            0
        };

        // Each delta should be tiny — just one field change per tick
        assert!(
            avg_bytes < 4 * 1024,
            "Average delta must be under 4 KiB for 1-field-change tick, got {} bytes",
            avg_bytes
        );

        println!(
            "[Phase 8 Perf] 100 entities, 10 ticks, 1 change/tick: \
             {} deltas sent, avg {} bytes/delta",
            delta_count, avg_bytes
        );
    }

    /// Verify the compressor cache grows proportionally with entity count but
    /// stays bounded (no memory leak on sustained operation).
    #[test]
    fn compressor_cache_bounded_at_entity_count() {
        let entity_count = 100u64;
        let mut compressor = DeltaCompressor::new();

        // Tick 1: spawn 100 entities
        let d1 = delta_with_many_entities(1, entity_count);
        let (mut p1, _) = DeltaBuilder::build(&d1, 1);
        compressor.compress(&mut p1);

        assert_eq!(
            compressor.cached_entity_count() as u64,
            entity_count,
            "Cache must hold exactly {} entities after spawn", entity_count
        );

        // Tick 2: destroy all 100 entities
        let mut d2 = empty_delta(2);
        for i in 1..=entity_count {
            d2.record_destroy(DestroyedEntity::new(i, 0));
        }
        let (mut p2, _) = DeltaBuilder::build(&d2, 2);
        compressor.compress(&mut p2);

        assert_eq!(
            compressor.cached_entity_count(),
            0,
            "Cache must be empty after all entities destroyed"
        );
    }
}

// =============================================================================
// 4. Snapshot Recovery — Compressor Reseed
// =============================================================================

#[cfg(test)]
mod snapshot_reseed {
    use super::*;
    use xace_core::runtime::world_snapshot::ComponentTableSnapshot;

    #[test]
    fn compressor_reseed_from_snapshot_prevents_incorrect_elimination() {
        let mut compressor = DeltaCompressor::new();

        // Prime compressor: entity 1 has x=10.0
        let mut d1 = empty_delta(1);
        d1.record_component_update(
            1,
            ComponentChange::single_field(1, "COMP_TRANSFORM_V1", "x", "10.0"),
        );
        let (mut p1, _) = DeltaBuilder::build(&d1, 1);
        compressor.compress(&mut p1);

        // Resync: build a snapshot where entity 1 has x=99.0 (different state)
        let mut snap = valid_world_snapshot(2, 1);
        snap.world_hash = "h".into();
        let mut table = ComponentTableSnapshot::new(1, "COMP_TRANSFORM_V1");
        table.set(1, r#"{"x":99.0,"y":0.0,"z":0.0}"#);
        snap.component_tables_snapshot.set_table(table);

        let mut recovery = SnapshotRecovery::new("0.1.0", 1, 10);
        let snap_payload = recovery.build_payload(&snap, SnapshotReason::DesyncRecovery).unwrap();

        // Reseed compressor from snapshot
        compressor.rebuild_from_snapshot(&snap_payload);

        // Now send a delta with x=10.0 — this differs from the snapshot's x=99.0
        // Without reseed, compressor would think x=10.0 is unchanged (from old cache)
        // With reseed, compressor knows x=99.0 is current, so x=10.0 is a real change
        let mut d2 = empty_delta(3);
        d2.record_component_update(
            1,
            ComponentChange::single_field(1, "COMP_TRANSFORM_V1", "x", "10.0"),
        );
        let (mut p2, _) = DeltaBuilder::build(&d2, 3);
        compressor.compress(&mut p2);

        // x=10.0 must NOT be eliminated — it differs from the reseeded x=99.0
        assert!(
            p2.modified_entities.contains_key(&1),
            "After reseed from snapshot, delta must include changed fields"
        );
    }

    #[test]
    fn snapshot_recovery_includes_correct_last_delta_sequence() {
        let mut recovery = SnapshotRecovery::new("0.1.0", 1, 0);
        recovery.update_last_delta_sequence(42);

        let mut snap = valid_world_snapshot(5, 0);
        snap.world_hash = "h".into();
        let payload = recovery
            .build_payload(&snap, SnapshotReason::InitialConnection)
            .unwrap();

        assert_eq!(
            payload.last_delta_sequence_id, 42,
            "Snapshot must carry the last DELTA sequence ID for engine re-anchoring"
        );
    }

    #[test]
    fn snapshot_recovery_excludes_destroyed_entities() {
        let mut recovery = SnapshotRecovery::new("0.1.0", 1, 0);

        let mut snap = WorldSnapshot::empty("0.1.0", 1, 42);
        snap.world_hash = "h".into();
        snap.cgs_hash = "c".into();
        snap.entity_store_snapshot.entities = vec![
            EntityRecord::new(1, EntityState::Active, 0),
            EntityRecord::new(2, EntityState::Destroyed, 0),
            EntityRecord::new(3, EntityState::Archived, 0),
            EntityRecord::new(4, EntityState::Active, 0),
        ];
        snap.entity_store_snapshot.next_entity_id = 5;

        let payload = recovery
            .build_payload(&snap, SnapshotReason::DesyncRecovery)
            .unwrap();

        assert_eq!(payload.entity_count(), 2, "Only Active entities in SNAPSHOT");
        assert!(payload.contains_entity(1));
        assert!(payload.contains_entity(4));
        assert!(!payload.contains_entity(2));
        assert!(!payload.contains_entity(3));
    }
}

// =============================================================================
// 5. Compressor Efficiency Across Long Sessions
// =============================================================================

#[cfg(test)]
mod compressor_efficiency {
    use super::*;

    #[test]
    fn unchanged_entity_never_sent_after_first_tick() {
        let mut compressor = DeltaCompressor::new();

        // Tick 1: entity 1 spawns at x=5, y=10
        let mut p1 = DeltaPayload::empty(1, 1, "0.1.0");
        let mut spawn = WireSpawnedEntity::new(1, "actor");
        spawn.add_component(WireComponentData::new(
            1, "COMP_TRANSFORM", r#"{"x":5,"y":10}"#,
        ));
        p1.add_spawn(spawn);
        compressor.compress(&mut p1);

        // Ticks 2–20: same entity, same values — should never appear in delta
        let mut times_sent = 0;
        for tick in 2..=20u64 {
            let mut d = empty_delta(tick);
            d.record_component_update(
                1,
                ComponentChange::multi_field(1, "COMP_TRANSFORM_V1", vec![
                    FieldChange::new("x", "5"),
                    FieldChange::new("y", "10"),
                ]),
            );
            let (mut payload, _) = DeltaBuilder::build(&d, tick);
            compressor.compress(&mut payload);
            if payload.modified_entities.contains_key(&1) {
                times_sent += 1;
            }
        }

        assert_eq!(
            times_sent, 0,
            "Unchanged entity must NEVER appear in delta after initial spawn"
        );
    }

    #[test]
    fn changed_field_always_sent() {
        let mut compressor = DeltaCompressor::new();

        // Prime: entity 1, x=0
        let mut d1 = empty_delta(1);
        d1.record_component_update(
            1, ComponentChange::single_field(1, "T", "x", "0"),
        );
        let (mut p1, _) = DeltaBuilder::build(&d1, 1);
        compressor.compress(&mut p1);

        // Each tick: x increments — must always be sent
        for tick in 2..=10u64 {
            let val = format!("{}", tick);
            let mut d = empty_delta(tick);
            d.record_component_update(
                1, ComponentChange::single_field(1, "T", "x", &val),
            );
            let (mut payload, _) = DeltaBuilder::build(&d, tick);
            compressor.compress(&mut payload);

            assert!(
                payload.modified_entities.contains_key(&1),
                "Changed field must always appear in delta at tick {}", tick
            );
        }
    }

    #[test]
    fn multi_component_partial_change_only_changed_components_sent() {
        let mut compressor = DeltaCompressor::new();

        // Prime: entity 1 has two components — TRANSFORM (type 1) and VELOCITY (type 2)
        let mut p1 = DeltaPayload::empty(1, 1, "0.1.0");
        let mut spawn = WireSpawnedEntity::new(1, "actor");
        spawn.add_component(WireComponentData::new(1, "COMP_TRANSFORM", r#"{"x":0}"#));
        spawn.add_component(WireComponentData::new(2, "COMP_VELOCITY", r#"{"vx":0}"#));
        p1.add_spawn(spawn);
        compressor.compress(&mut p1);

        // Tick 2: only TRANSFORM changes
        let mut d2 = empty_delta(2);
        d2.record_component_update(
            1, ComponentChange::single_field(1, "COMP_TRANSFORM", "x", "1"),
        );
        d2.record_component_update(
            1, ComponentChange::single_field(2, "COMP_VELOCITY", "vx", "0"), // unchanged
        );
        let (mut p2, _) = DeltaBuilder::build(&d2, 2);
        compressor.compress(&mut p2);

        if let Some(entity_update) = p2.modified_entities.get(&1) {
            // TRANSFORM must be present (changed x=0→1)
            assert!(
                entity_update.component_updates.contains_key(&1),
                "Changed TRANSFORM must be in delta"
            );
            // VELOCITY must NOT be present (unchanged vx=0)
            assert!(
                !entity_update.component_updates.contains_key(&2),
                "Unchanged VELOCITY must be eliminated from delta"
            );
        } else {
            panic!("Entity 1 must be in modified_entities (TRANSFORM changed)");
        }
    }
}

// =============================================================================
// 6. DeltaSyncEngine Metrics
// =============================================================================

#[cfg(test)]
mod engine_metrics {
    use super::*;

    #[test]
    fn metrics_accurately_count_all_output_types() {
        let mut eng = engine();
        let snap = valid_world_snapshot(0, 1);

        // tick 0: snapshot
        eng.process_tick(&empty_delta(0), &snap).unwrap();

        // tick 1: delta (spawn)
        eng.process_tick(&delta_with_spawn(1, 1, "actor"), &snap).unwrap();

        // tick 2: nothing (empty)
        eng.process_tick(&empty_delta(2), &snap).unwrap();

        // tick 3: identical field — compressed to nothing
        eng.process_tick(&delta_with_field(3, 1, "x", "1.0"), &snap).unwrap(); // primes
        eng.process_tick(&delta_with_field(4, 1, "x", "1.0"), &snap).unwrap(); // identical

        // trigger resync (past cooldown)
        for _ in 0..5 { eng.process_tick(&empty_delta(5), &snap).unwrap(); }
        eng.report_explicit_snapshot_request();
        eng.process_tick(&empty_delta(10), &snap).unwrap(); // recovery snapshot

        let m = eng.metrics();
        assert!(m.snapshot_ticks >= 2, "At least 2 snapshots: initial + recovery");
        assert!(m.delta_ticks >= 1, "At least 1 delta tick");
        assert!(m.ticks_processed >= 6);
    }

    #[test]
    fn compressor_metrics_reported_through_engine() {
        let mut eng = engine();
        let snap = valid_world_snapshot(0, 0);
        eng.process_tick(&empty_delta(0), &snap).unwrap();

        // Send same field twice — second should be compressed away
        eng.process_tick(&delta_with_field(1, 1, "pos", r#"{"x":1}"#), &snap).unwrap();
        eng.process_tick(&delta_with_field(2, 1, "pos", r#"{"x":1}"#), &snap).unwrap();

        let cm = eng.compressor_metrics();
        assert!(
            cm.fields_before >= 1,
            "Compressor must have seen at least one field"
        );
    }
}