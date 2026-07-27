//! # Snapshot Engine Integration Tests

use crate::component_tables::ComponentTableStore;
use crate::entity_store::EntityStore;
use crate::snapshot_engine::snapshot_engine::SnapshotEngine;
use crate::snapshot_engine::snapshot_store::RetentionPolicy;

fn setup() -> (SnapshotEngine, EntityStore, ComponentTableStore) {
    let engine = SnapshotEngine::standard("0.1.0", 1, 12345);
    let entity_store = EntityStore::new();
    let mut table_store = ComponentTableStore::new();
    table_store.register_table(1, "COMP_TRANSFORM_V1").unwrap();
    table_store.register_table(2, "COMP_IDENTITY_V1").unwrap();
    (engine, entity_store, table_store)
}

// ── Hash Determinism Tests (D9) ───────────────────────────────────────────────

#[test]
fn same_world_same_hash_three_times() {
    let (mut engine, mut es, mut ts) = setup();
    let id = es.create_entity(0).unwrap();
    ts.add_component(id, 1, r#"{"x":1.0,"y":0.0}"#.into(), 0)
        .unwrap();

    let h1 = engine.take_snapshot(0, &es, &ts).unwrap().world_hash;
    let h2 = engine.take_snapshot(0, &es, &ts).unwrap().world_hash;
    let h3 = engine.take_snapshot(0, &es, &ts).unwrap().world_hash;
    assert_eq!(h1, h2);
    assert_eq!(h2, h3);
}

#[test]
fn component_change_changes_hash() {
    let (mut engine, mut es, mut ts) = setup();
    let id = es.create_entity(0).unwrap();
    ts.add_component(id, 1, r#"{"x":0.0}"#.into(), 0).unwrap();
    let h1 = engine.take_snapshot(0, &es, &ts).unwrap().world_hash;

    ts.update_component(id, 1, r#"{"x":5.0}"#.into(), 1)
        .unwrap();
    let h2 = engine.take_snapshot(0, &es, &ts).unwrap().world_hash;
    assert_ne!(h1, h2);
}

#[test]
fn entity_addition_changes_hash() {
    let (mut engine, mut es, ts) = setup();
    let h1 = engine.take_snapshot(0, &es, &ts).unwrap().world_hash;
    es.create_entity(0).unwrap();
    let h2 = engine.take_snapshot(0, &es, &ts).unwrap().world_hash;
    assert_ne!(h1, h2);
}

// ── Snapshot Roundtrip Tests (I10) ────────────────────────────────────────────

#[test]
fn snapshot_roundtrip_preserves_entity_count() {
    let (mut engine, mut es, ts) = setup();
    for _ in 0..5 {
        es.create_entity(0).unwrap();
    }
    let snap = engine.take_snapshot(0, &es, &ts).unwrap();

    let mut es2 = EntityStore::new();
    let mut ts2 = ComponentTableStore::new();
    ts2.register_table(1, "COMP_TRANSFORM_V1").unwrap();
    ts2.register_table(2, "COMP_IDENTITY_V1").unwrap();

    engine.restore_snapshot(&snap, &mut es2, &mut ts2).unwrap();
    assert_eq!(es2.alive_count(), 5);
}

#[test]
fn snapshot_roundtrip_preserves_component_data() {
    let (mut engine, mut es, mut ts) = setup();
    let id = es.create_entity(0).unwrap();
    ts.add_component(id, 1, r#"{"x":3.14}"#.into(), 0).unwrap();
    ts.add_component(id, 2, r#"{"name":"player"}"#.into(), 0)
        .unwrap();

    let snap = engine.take_snapshot(0, &es, &ts).unwrap();

    let mut es2 = EntityStore::new();
    let mut ts2 = ComponentTableStore::new();
    ts2.register_table(1, "COMP_TRANSFORM_V1").unwrap();
    ts2.register_table(2, "COMP_IDENTITY_V1").unwrap();

    engine.restore_snapshot(&snap, &mut es2, &mut ts2).unwrap();
    assert_eq!(ts2.get_component(id, 1), Some(r#"{"x":3.14}"#));
    assert_eq!(ts2.get_component(id, 2), Some(r#"{"name":"player"}"#));
}

#[test]
fn hash_matches_after_restore() {
    let (mut engine, mut es, mut ts) = setup();
    let id = es.create_entity(0).unwrap();
    ts.add_component(id, 1, r#"{"x":1.0}"#.into(), 0).unwrap();
    let snap = engine.take_snapshot(10, &es, &ts).unwrap();
    let original_hash = snap.world_hash.clone();

    let mut es2 = EntityStore::new();
    let mut ts2 = ComponentTableStore::new();
    ts2.register_table(1, "COMP_TRANSFORM_V1").unwrap();
    ts2.register_table(2, "COMP_IDENTITY_V1").unwrap();

    engine.restore_snapshot(&snap, &mut es2, &mut ts2).unwrap();

    // After restore, recomputing hash must match original
    let restored_snap = engine.take_snapshot(10, &es2, &ts2).unwrap();
    assert_eq!(restored_snap.world_hash, original_hash);
}

// ── Rollback Tests ────────────────────────────────────────────────────────────

#[test]
fn rollback_to_earlier_tick() {
    let (mut engine, mut es, mut ts) = setup();
    let id = es.create_entity(0).unwrap();

    // Snapshot at tick 0 — entity has x=0
    ts.add_component(id, 1, r#"{"x":0.0}"#.into(), 0).unwrap();
    engine.take_and_store(0, &es, &ts).unwrap();

    // Advance to tick 10 — entity has x=10
    ts.update_component(id, 1, r#"{"x":10.0}"#.into(), 10)
        .unwrap();
    engine.take_and_store(10, &es, &ts).unwrap();

    // Rollback to tick 0
    let rollback_snap = engine.get_snapshot(0).unwrap().clone();
    engine
        .restore_snapshot(&rollback_snap, &mut es, &mut ts)
        .unwrap();

    // World should be at tick 0 state
    assert_eq!(ts.get_component(id, 1), Some(r#"{"x":0.0}"#));
}

#[test]
fn retention_policy_limits_stored_snapshots() {
    let mut engine = SnapshotEngine::new("0.1.0", 1, 42, RetentionPolicy::KeepLastN(3));
    let es = EntityStore::new();
    let mut ts = ComponentTableStore::new();
    ts.register_table(1, "COMP_TRANSFORM_V1").unwrap();

    for tick in 0u64..6 {
        engine.take_and_store(tick, &es, &ts).unwrap();
    }
    assert_eq!(engine.stored_count(), 3);
}

#[test]
fn checkpoint_snapshot_not_purged() {
    let mut engine = SnapshotEngine::new("0.1.0", 1, 42, RetentionPolicy::KeepLastN(2));
    let es = EntityStore::new();
    let mut ts = ComponentTableStore::new();
    ts.register_table(1, "COMP_TRANSFORM_V1").unwrap();

    engine.mark_checkpoint(0);
    for tick in 0u64..4 {
        engine.take_and_store(tick, &es, &ts).unwrap();
    }
    // Tick 0 is checkpoint — must survive KeepLastN eviction
    assert!(engine.get_snapshot(0).is_some());
}
