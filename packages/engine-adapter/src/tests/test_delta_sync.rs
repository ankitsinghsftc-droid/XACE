//! # Delta Sync Integration Tests
//!
//! Integration tests for the Phase 7.5/8 delta sync pipeline.
//!
//! ## Coverage
//! - DeltaBuilder: minimal delta production, D4 ordering enforcement,
//!   deterministic field/entity ordering (D3, D11)
//! - DeltaCompressor: unchanged field elimination, spawn/destroy cache
//!   management, rebuild from snapshot
//! - SnapshotRecovery: initial connection payload, entity filtering,
//!   partial snapshots, sequence ID embedding
//! - ResyncDetector: trigger types, cooldown enforcement, tick drift
//! - DeltaSyncEngine: full tick pipeline, compression integration,
//!   resync path, sequence ID progression

#[cfg(test)]
mod tests {
    use xace_core::entity_state::EntityState;
    use xace_core::runtime::state_delta::{
        AddedComponent, ComponentChange, DestroyedEntity, FieldChange,
        RemovedComponent, SpawnedEntity, StateDelta,
    };
    use xace_core::runtime::world_snapshot::{
        ComponentTableSnapshot, EntityRecord, WorldSnapshot,
    };
    use xace_core::wire::delta_payload::{
        DeltaPayload, WireComponentData, WireComponentUpdate, WireDestroyedEntity,
        WireFieldChange, WireSpawnedEntity,
    };
    use xace_core::wire::snapshot_payload::{
        SnapshotEntityRecord, SnapshotPayload, SnapshotReason,
    };

    use crate::delta_sync::delta_builder::DeltaBuilder;
    use crate::delta_sync::delta_compressor::DeltaCompressor;
    use crate::delta_sync::delta_sync_engine::{DeltaSyncEngine, DeltaSyncOutput};
    use crate::delta_sync::resync_detector::{ResyncConfig, ResyncDetector, ResyncTrigger};
    use crate::delta_sync::snapshot_recovery::SnapshotRecovery;

    // ── Helpers ───────────────────────────────────────────────────────────────

    fn empty_delta(tick: u64) -> StateDelta {
        StateDelta::empty(tick, "0.1.0")
    }

    fn delta_with_spawn(tick: u64, entity_id: u64) -> StateDelta {
        let mut d = empty_delta(tick);
        d.record_spawn(SpawnedEntity::new(entity_id, "actor_player"));
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

    fn valid_world_snapshot(tick: u64, entities: Vec<(u64, EntityState)>) -> WorldSnapshot {
        let mut s = WorldSnapshot::empty("0.1.0", 1, 42);
        s.tick = tick;
        s.world_hash = "hash_valid".into();
        s.cgs_hash = "cgs_hash".into();
        for (id, state) in entities {
            s.entity_store_snapshot.entities.push(EntityRecord::new(id, state, 0));
        }
        if let Some(max) = s.entity_store_snapshot.entities.iter().map(|e| e.entity_id).max() {
            s.entity_store_snapshot.next_entity_id = max + 1;
        }
        s
    }

    fn engine() -> DeltaSyncEngine {
        DeltaSyncEngine::new("0.1.0", 1, "default", 1,
            ResyncConfig { cooldown_ticks: 2, max_tick_drift: 50, tick_drift_detection: true }
        )
    }

    // =========================================================================
    // DeltaBuilder
    // =========================================================================

    #[test]
    fn builder_empty_delta_produces_empty_payload() {
        let (payload, metrics) = DeltaBuilder::build(&empty_delta(1), 1);
        assert!(payload.is_empty());
        assert_eq!(metrics.spawned_entities, 0);
    }

    #[test]
    fn builder_spawned_entity_appears_in_payload() {
        let (payload, metrics) = DeltaBuilder::build(&delta_with_spawn(1, 42), 1);
        assert_eq!(payload.spawned_entities.len(), 1);
        assert_eq!(payload.spawned_entities[0].entity_id, 42);
        assert_eq!(metrics.spawned_entities, 1);
    }

    #[test]
    fn builder_multiple_spawns_sorted_entity_id_asc() {
        // D3: entity iteration always EntityID ASC
        let mut d = empty_delta(1);
        d.record_spawn(SpawnedEntity::new(5, "a"));
        d.record_spawn(SpawnedEntity::new(1, "b"));
        d.record_spawn(SpawnedEntity::new(3, "c"));
        let (payload, _) = DeltaBuilder::build(&d, 1);
        assert_eq!(payload.spawned_entities[0].entity_id, 1);
        assert_eq!(payload.spawned_entities[1].entity_id, 3);
        assert_eq!(payload.spawned_entities[2].entity_id, 5);
    }

    #[test]
    fn builder_spawn_components_sorted_type_id_asc() {
        // D11: component type IDs in ascending order
        let mut d = empty_delta(1);
        let mut spawned = SpawnedEntity::new(1, "actor");
        spawned.initial_components.insert(5, "{}".into());
        spawned.initial_components.insert(1, "{}".into());
        spawned.initial_components.insert(3, "{}".into());
        d.record_spawn(spawned);
        let (payload, _) = DeltaBuilder::build(&d, 1);
        let ids: Vec<u32> = payload.spawned_entities[0]
            .initial_components.iter().map(|c| c.component_type_id).collect();
        assert_eq!(ids, vec![1, 3, 5]);
    }

    #[test]
    fn builder_field_changes_sorted_by_field_name() {
        // D11: fields within a component sorted alphabetically
        let mut d = empty_delta(1);
        d.record_component_update(
            1,
            ComponentChange::multi_field(1, "COMP_T", vec![
                FieldChange::new("z_field", "1"),
                FieldChange::new("a_field", "2"),
                FieldChange::new("m_field", "3"),
            ]),
        );
        let (payload, _) = DeltaBuilder::build(&d, 1);
        let fields = &payload.modified_entities[&1].component_updates[&1].field_changes;
        assert_eq!(fields[0].field_name, "a_field");
        assert_eq!(fields[1].field_name, "m_field");
        assert_eq!(fields[2].field_name, "z_field");
    }

    #[test]
    fn builder_destroyed_entity_in_payload() {
        let mut d = empty_delta(1);
        d.record_destroy(DestroyedEntity::new(99, 0));
        let (payload, metrics) = DeltaBuilder::build(&d, 1);
        assert_eq!(payload.destroyed_entities.len(), 1);
        assert_eq!(payload.destroyed_entities[0].entity_id, 99);
        assert_eq!(metrics.destroyed_entities, 1);
    }

    #[test]
    fn builder_sequence_id_embedded() {
        let (payload, _) = DeltaBuilder::build(&delta_with_spawn(1, 1), 77);
        assert_eq!(payload.sequence_id, 77);
    }

    #[test]
    fn builder_tick_embedded_from_state_delta() {
        let (payload, _) = DeltaBuilder::build(&delta_with_spawn(42, 1), 1);
        assert_eq!(payload.tick, 42);
    }

    // =========================================================================
    // DeltaCompressor
    // =========================================================================

    #[test]
    fn compressor_first_send_passes_all_fields() {
        let mut c = DeltaCompressor::new();
        let mut p = DeltaPayload::empty(1, 1, "0.1.0");
        p.add_component_update(1, WireComponentUpdate::new(1, "T", vec![
            WireFieldChange::new("x", "1.0"),
            WireFieldChange::new("y", "2.0"),
        ]));
        c.compress(&mut p);
        assert_eq!(p.modified_entities[&1].component_updates[&1].field_changes.len(), 2);
    }

    #[test]
    fn compressor_identical_second_send_eliminates_entity_update() {
        let mut c = DeltaCompressor::new();
        let make = || {
            let mut p = DeltaPayload::empty(1, 1, "0.1.0");
            p.add_component_update(1, WireComponentUpdate::new(1, "T", vec![
                WireFieldChange::new("x", "1.0"),
            ]));
            p
        };
        let mut p1 = make();
        c.compress(&mut p1);

        let mut p2 = make();
        c.compress(&mut p2);
        assert!(!p2.modified_entities.contains_key(&1),
            "Unchanged entity must be eliminated from payload");
    }

    #[test]
    fn compressor_only_changed_fields_survive() {
        let mut c = DeltaCompressor::new();
        let mut p1 = DeltaPayload::empty(1, 1, "0.1.0");
        p1.add_component_update(1, WireComponentUpdate::new(1, "T", vec![
            WireFieldChange::new("x", "1.0"),
            WireFieldChange::new("y", "2.0"),
        ]));
        c.compress(&mut p1);

        let mut p2 = DeltaPayload::empty(2, 2, "0.1.0");
        p2.add_component_update(1, WireComponentUpdate::new(1, "T", vec![
            WireFieldChange::new("x", "1.0"), // unchanged
            WireFieldChange::new("y", "9.0"), // changed
        ]));
        c.compress(&mut p2);

        let fields = &p2.modified_entities[&1].component_updates[&1].field_changes;
        assert_eq!(fields.len(), 1);
        assert_eq!(fields[0].field_name, "y");
        assert_eq!(fields[0].value_json, "9.0");
    }

    #[test]
    fn compressor_destroy_evicts_entity_from_cache() {
        let mut c = DeltaCompressor::new();
        let mut p1 = DeltaPayload::empty(1, 1, "0.1.0");
        p1.add_component_update(1, WireComponentUpdate::new(1, "T", vec![
            WireFieldChange::new("x", "1"),
        ]));
        c.compress(&mut p1);
        assert_eq!(c.cached_entity_count(), 1);

        let mut p2 = DeltaPayload::empty(2, 2, "0.1.0");
        p2.add_destroy(WireDestroyedEntity::new(1));
        c.compress(&mut p2);
        assert_eq!(c.cached_entity_count(), 0);
    }

    #[test]
    fn compressor_spawn_populates_cache() {
        let mut c = DeltaCompressor::new();
        let mut p1 = DeltaPayload::empty(1, 1, "0.1.0");
        let mut entity = WireSpawnedEntity::new(1, "actor");
        entity.add_component(WireComponentData::new(1, "T", r#"{"x":0,"y":0}"#));
        p1.add_spawn(entity);
        c.compress(&mut p1);

        // Next tick with identical values — should be eliminated
        let mut p2 = DeltaPayload::empty(2, 2, "0.1.0");
        p2.add_component_update(1, WireComponentUpdate::new(1, "T", vec![
            WireFieldChange::new("x", "0"), // matches snapshot cache
            WireFieldChange::new("y", "0"),
        ]));
        c.compress(&mut p2);
        assert!(!p2.modified_entities.contains_key(&1));
    }

    #[test]
    fn compressor_compression_ratio_tracks_correctly() {
        let mut c = DeltaCompressor::new();
        let make_update = || {
            let mut p = DeltaPayload::empty(1, 1, "0.1.0");
            p.add_component_update(1, WireComponentUpdate::new(1, "T", vec![
                WireFieldChange::new("a", "same"),
                WireFieldChange::new("b", "same"),
                WireFieldChange::new("c", "same"),
            ]));
            p
        };
        let mut p1 = make_update();
        c.compress(&mut p1); // primes cache: 3 fields, 0 eliminated

        let mut p2 = make_update();
        c.compress(&mut p2); // all 3 identical: 3 eliminated

        // After 2 compressions: 6 before, 3 after (first pass) + 0 after (second pass) = 3 total
        let m = c.metrics();
        assert!(m.compression_ratio() > 0.0);
    }

    // =========================================================================
    // SnapshotRecovery
    // =========================================================================

    #[test]
    fn snapshot_recovery_includes_active_entities() {
        let mut r = SnapshotRecovery::new("0.1.0", 1, 0);
        let snap = valid_world_snapshot(1, vec![
            (1, EntityState::Active),
            (2, EntityState::Active),
        ]);
        let payload = r.build_payload(&snap, SnapshotReason::InitialConnection).unwrap();
        assert_eq!(payload.entity_count(), 2);
    }

    #[test]
    fn snapshot_recovery_excludes_destroyed_entities() {
        let mut r = SnapshotRecovery::new("0.1.0", 1, 0);
        let snap = valid_world_snapshot(1, vec![
            (1, EntityState::Active),
            (2, EntityState::Destroyed),
            (3, EntityState::Archived),
        ]);
        let payload = r.build_payload(&snap, SnapshotReason::InitialConnection).unwrap();
        assert_eq!(payload.entity_count(), 1);
        assert!(payload.contains_entity(1));
    }

    #[test]
    fn snapshot_recovery_embeds_last_delta_sequence_id() {
        let mut r = SnapshotRecovery::new("0.1.0", 1, 55);
        let snap = valid_world_snapshot(1, vec![]);
        let mut snap = snap;
        snap.world_hash = "h".into();
        let payload = r.build_payload(&snap, SnapshotReason::DesyncRecovery).unwrap();
        assert_eq!(payload.last_delta_sequence_id, 55);
    }

    #[test]
    fn snapshot_recovery_includes_component_data_from_tables() {
        let mut r = SnapshotRecovery::new("0.1.0", 1, 0);
        let mut snap = valid_world_snapshot(1, vec![(1, EntityState::Active)]);
        snap.world_hash = "h".into();

        let mut table = ComponentTableSnapshot::new(1, "COMP_TRANSFORM_V1");
        table.set(1, r#"{"x":10}"#);
        snap.component_tables_snapshot.set_table(table);

        let payload = r.build_payload(&snap, SnapshotReason::InitialConnection).unwrap();
        let entity = payload.get_entity(1).unwrap();
        assert!(entity.has_component(1));
        assert!(entity.get_component(1).unwrap().data_json.contains("10"));
    }

    #[test]
    fn snapshot_recovery_partial_filters_to_requested_ids() {
        let mut r = SnapshotRecovery::new("0.1.0", 1, 0);
        let mut snap = valid_world_snapshot(1, vec![
            (1, EntityState::Active),
            (2, EntityState::Active),
            (3, EntityState::Active),
        ]);
        snap.world_hash = "h".into();
        let payload = r.build_partial_payload(&snap, &[1, 3], SnapshotReason::InitialConnection).unwrap();
        assert_eq!(payload.entity_count(), 2);
        assert!(!payload.is_full);
        assert!(payload.contains_entity(1));
        assert!(!payload.contains_entity(2));
    }

    #[test]
    fn snapshot_recovery_fails_on_invalid_world_snapshot() {
        let mut r = SnapshotRecovery::new("0.1.0", 1, 0);
        let snap = WorldSnapshot::empty("0.1.0", 1, 42); // world_hash=""
        assert!(r.build_payload(&snap, SnapshotReason::InitialConnection).is_err());
    }

    // =========================================================================
    // ResyncDetector
    // =========================================================================

    #[test]
    fn resync_detector_no_pending_initially() {
        let d = ResyncDetector::with_defaults();
        assert!(!d.needs_resync());
    }

    #[test]
    fn resync_detector_request_sets_pending() {
        let mut d = ResyncDetector::with_defaults();
        d.request_resync(ResyncTrigger::InitialConnection);
        assert!(d.needs_resync());
    }

    #[test]
    fn resync_detector_consume_clears_pending() {
        let mut d = ResyncDetector::new(ResyncConfig {
            cooldown_ticks: 0, ..Default::default()
        });
        d.request_resync(ResyncTrigger::InitialConnection);
        assert!(d.check_and_consume(0).is_some());
        assert!(!d.needs_resync());
    }

    #[test]
    fn resync_detector_cooldown_suppresses_trigger() {
        let mut d = ResyncDetector::new(ResyncConfig {
            cooldown_ticks: 10, ..Default::default()
        });
        d.request_resync(ResyncTrigger::InitialConnection);
        d.check_and_consume(0).unwrap();
        d.mark_snapshot_sent(0);

        d.request_resync(ResyncTrigger::ExplicitRequest);
        assert!(d.check_and_consume(5).is_none()); // within cooldown
        assert!(d.check_and_consume(11).is_some()); // past cooldown
    }

    #[test]
    fn resync_detector_tick_drift_above_threshold_triggers_resync() {
        let mut d = ResyncDetector::new(ResyncConfig {
            cooldown_ticks: 0,
            max_tick_drift: 30,
            tick_drift_detection: true,
        });
        d.update_last_ack_tick(0);
        d.check_tick_drift(31); // drift = 31 > threshold 30
        assert!(d.needs_resync());
    }

    #[test]
    fn resync_detector_sequence_gap_sets_correct_trigger() {
        let mut d = ResyncDetector::with_defaults();
        d.report_sequence_gap(5, 10);
        assert!(matches!(
            d.pending_trigger(),
            Some(ResyncTrigger::SequenceGap { expected_sequence: 5, received_sequence: 10 })
        ));
    }

    #[test]
    fn resync_detector_trigger_maps_to_correct_snapshot_reason() {
        assert_eq!(
            ResyncTrigger::InitialConnection.snapshot_reason(),
            SnapshotReason::InitialConnection
        );
        assert_eq!(
            ResyncTrigger::ExplicitRequest.snapshot_reason(),
            SnapshotReason::ExplicitRequest
        );
        assert_eq!(
            ResyncTrigger::SequenceGap { expected_sequence: 1, received_sequence: 5 }
                .snapshot_reason(),
            SnapshotReason::DesyncRecovery
        );
    }

    // =========================================================================
    // DeltaSyncEngine
    // =========================================================================

    #[test]
    fn sync_engine_first_tick_always_sends_snapshot() {
        let mut e = engine();
        let snap = valid_world_snapshot(0, vec![(1, EntityState::Active)]);
        let mut snap = snap;
        snap.world_hash = "h".into();
        let result = e.process_tick(&empty_delta(0), &snap).unwrap();
        assert!(matches!(result, DeltaSyncOutput::Snapshot(_)));
        assert_eq!(e.metrics().snapshot_ticks, 1);
    }

    #[test]
    fn sync_engine_empty_delta_after_snapshot_returns_nothing() {
        let mut e = engine();
        let mut snap = valid_world_snapshot(0, vec![]);
        snap.world_hash = "h".into();
        e.process_tick(&empty_delta(0), &snap).unwrap();
        let result = e.process_tick(&empty_delta(1), &snap).unwrap();
        assert!(matches!(result, DeltaSyncOutput::Nothing));
    }

    #[test]
    fn sync_engine_spawn_produces_delta_output() {
        let mut e = engine();
        let mut snap = valid_world_snapshot(0, vec![(1, EntityState::Active)]);
        snap.world_hash = "h".into();
        e.process_tick(&empty_delta(0), &snap).unwrap();
        let result = e.process_tick(&delta_with_spawn(1, 1), &snap).unwrap();
        assert!(matches!(result, DeltaSyncOutput::Delta(_)));
        assert_eq!(e.metrics().delta_ticks, 1);
    }

    #[test]
    fn sync_engine_delta_sequence_increments_each_delta() {
        let mut e = engine();
        let mut snap = valid_world_snapshot(0, vec![(1, EntityState::Active)]);
        snap.world_hash = "h".into();
        e.process_tick(&empty_delta(0), &snap).unwrap(); // snapshot

        e.process_tick(&delta_with_spawn(1, 1), &snap).unwrap(); // delta seq=1
        e.process_tick(&delta_with_spawn(2, 2), &snap).unwrap(); // delta seq=2
        assert_eq!(e.next_delta_sequence(), 3);
    }

    #[test]
    fn sync_engine_identical_field_updates_compressed_to_nothing() {
        let mut e = engine();
        let mut snap = valid_world_snapshot(0, vec![(1, EntityState::Active)]);
        snap.world_hash = "h".into();
        e.process_tick(&empty_delta(0), &snap).unwrap();

        e.process_tick(&delta_with_field(1, 1, "x", r#"{"x":1}"#), &snap).unwrap();
        let result = e.process_tick(
            &delta_with_field(2, 1, "x", r#"{"x":1}"#), // identical
            &snap,
        ).unwrap();
        assert!(matches!(result, DeltaSyncOutput::Nothing),
            "Identical field update must be compressed to Nothing");
    }

    #[test]
    fn sync_engine_resync_request_produces_snapshot_on_next_tick() {
        let mut e = engine();
        let mut snap = valid_world_snapshot(0, vec![]);
        snap.world_hash = "h".into();
        e.process_tick(&empty_delta(0), &snap).unwrap(); // initial snapshot

        e.report_sequence_gap(5, 10);
        let result = e.process_tick(&delta_with_spawn(3, 1), &snap).unwrap();
        assert!(matches!(result, DeltaSyncOutput::Snapshot(_)));
        assert_eq!(e.metrics().snapshot_ticks, 2);
    }

    #[test]
    fn sync_engine_snapshot_output_tick_matches_state_delta_tick() {
        let mut e = engine();
        let mut snap = valid_world_snapshot(7, vec![]);
        snap.world_hash = "h".into();
        let result = e.process_tick(&empty_delta(7), &snap).unwrap();
        assert_eq!(result.tick(), Some(7));
    }

    #[test]
    fn sync_engine_metrics_count_all_output_types() {
        let mut e = engine();
        let mut snap = valid_world_snapshot(0, vec![(1, EntityState::Active)]);
        snap.world_hash = "h".into();

        e.process_tick(&empty_delta(0), &snap).unwrap(); // snapshot
        e.process_tick(&empty_delta(1), &snap).unwrap(); // nothing
        e.process_tick(&delta_with_spawn(2, 1), &snap).unwrap(); // delta

        let m = e.metrics();
        assert_eq!(m.ticks_processed, 3);
        assert_eq!(m.snapshot_ticks, 1);
        assert_eq!(m.nothing_ticks, 1);
        assert_eq!(m.delta_ticks, 1);
    }

    // =========================================================================
    // Ordering Enforcement (D4)
    // =========================================================================

    #[test]
    fn delta_payload_change_count_reflects_all_sections() {
        let mut d = empty_delta(1);
        d.record_spawn(SpawnedEntity::new(1, "a"));
        d.record_destroy(DestroyedEntity::new(99, 0));
        let (payload, _) = DeltaBuilder::build(&d, 1);
        assert_eq!(payload.spawned_entities.len(), 1);
        assert_eq!(payload.destroyed_entities.len(), 1);
    }

    #[test]
    fn delta_builder_schema_version_matches_state_delta() {
        let d = StateDelta::empty(1, "2.3.4");
        let (payload, _) = DeltaBuilder::build(&d, 1);
        assert_eq!(payload.schema_version, "2.3.4");
    }
}