use std::fs;

use xace_core::runtime::world_snapshot::WorldSnapshot;
use xace_save_engine::FileSaveEngine;

fn temp_root(name: &str) -> std::path::PathBuf {
    let root =
        std::env::temp_dir().join(format!("xace_save_engine_{}_{}", name, std::process::id()));
    let _ = fs::remove_dir_all(&root);
    root
}

fn snapshot(tick: u64) -> WorldSnapshot {
    let mut snapshot = WorldSnapshot::empty("0.1.0", 1, 42);
    snapshot.tick = tick;
    snapshot.world_hash = format!("hash_{tick}");
    snapshot
}

#[test]
fn session_save_roundtrips_snapshot() {
    let root = temp_root("roundtrip");
    let engine = FileSaveEngine::new(&root, "0.1.0");
    let saved = snapshot(100);

    engine.save_session("slot_1", "Slot 1", &saved).unwrap();
    let loaded = engine.load_session("slot_1").unwrap();

    assert_eq!(loaded.tick, 100);
    assert_eq!(loaded.schema_version, "0.1.0");
    assert_eq!(loaded.world_hash, "hash_100");

    let _ = fs::remove_dir_all(root);
}

#[test]
fn progress_and_world_layers_are_separate() {
    let root = temp_root("layers");
    let engine = FileSaveEngine::new(&root, "0.1.0");

    engine.save_progress("slot_1", r#"{"level":3}"#).unwrap();
    engine
        .save_world_state("slot_1", r#"{"door_open":true}"#)
        .unwrap();

    assert_eq!(engine.load_progress("slot_1").unwrap(), r#"{"level":3}"#);
    assert_eq!(
        engine.load_world_state("slot_1").unwrap(),
        r#"{"door_open":true}"#
    );

    let _ = fs::remove_dir_all(root);
}

#[test]
fn schema_mismatch_is_rejected() {
    let root = temp_root("schema");
    let old_engine = FileSaveEngine::new(&root, "0.1.0");
    old_engine
        .save_session("slot_1", "Slot 1", &snapshot(1))
        .unwrap();

    let new_engine = FileSaveEngine::new(&root, "0.2.0");
    assert!(new_engine.load_session("slot_1").is_err());

    let _ = fs::remove_dir_all(root);
}

#[test]
fn slot_listing_is_sorted() {
    let root = temp_root("listing");
    let engine = FileSaveEngine::new(&root, "0.1.0");
    engine.save_session("slot_b", "B", &snapshot(1)).unwrap();
    engine.save_session("slot_a", "A", &snapshot(2)).unwrap();

    let slots = engine.list_slots().unwrap();
    assert_eq!(slots[0].slot_id, "slot_a");
    assert_eq!(slots[1].slot_id, "slot_b");

    let _ = fs::remove_dir_all(root);
}
