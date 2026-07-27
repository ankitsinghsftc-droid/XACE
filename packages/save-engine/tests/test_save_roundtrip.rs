use std::fs;

use xace_core::runtime::world_snapshot::WorldSnapshot;
use xace_save_engine::{compute_asset_tree_hash, FileSaveEngine};

fn temp_root(name: &str) -> std::path::PathBuf {
    let root =
        std::env::temp_dir().join(format!("xace_save_engine_{}_{}", name, std::process::id()));
    let _ = fs::remove_dir_all(&root);
    root
}

fn snapshot(tick: u64) -> WorldSnapshot {
    let mut snapshot = WorldSnapshot::empty("0.1.0", 1, 42);
    snapshot.tick = tick;
    snapshot.world_hash = format!("{tick:064x}");
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
    assert_eq!(loaded.world_hash, format!("{:064x}", 100));

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

#[test]
fn project_session_records_deterministic_asset_hash() {
    let root = temp_root("asset_hash");
    let asset_root = root.join("assets");
    fs::create_dir_all(asset_root.join("meshes")).unwrap();
    fs::create_dir_all(asset_root.join("audio")).unwrap();
    fs::write(asset_root.join("meshes").join("hero.mesh"), b"mesh-data").unwrap();
    fs::write(asset_root.join("audio").join("theme.ogg"), b"music-data").unwrap();

    let engine = FileSaveEngine::new(root.join("saves"), "0.1.0");
    let expected_hash = compute_asset_tree_hash(&asset_root).unwrap();
    let mut saved = snapshot(7);
    saved.cgs_hash = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb".to_string();

    engine
        .save_project_session("slot_project", "Project Slot", &saved, &asset_root)
        .unwrap();
    let metadata = engine.load_metadata("slot_project").unwrap();
    let loaded = engine.load_session("slot_project").unwrap();

    assert_eq!(
        metadata.cgs_hash,
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    );
    assert_eq!(metadata.asset_hash, expected_hash);
    assert_eq!(
        loaded.cgs_hash,
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    );
    assert_eq!(loaded.world_hash, format!("{:064x}", 7));

    fs::write(asset_root.join("meshes").join("hero.mesh"), b"changed").unwrap();
    let changed_hash = compute_asset_tree_hash(&asset_root).unwrap();
    assert_ne!(changed_hash, metadata.asset_hash);

    let _ = fs::remove_dir_all(root);
}

#[test]
fn x10_016_save_recovery_restores_corrupt_session_and_metadata_pair() {
    let root = temp_root("x10_016_corrupt_session");
    let engine = FileSaveEngine::new(&root, "0.1.0");

    engine
        .save_session("slot_1", "Slot 1", &snapshot(11))
        .unwrap();
    engine
        .save_session("slot_1", "Slot 1", &snapshot(12))
        .unwrap();

    let slot_dir = root.join("slot_1");
    fs::write(slot_dir.join("session.json"), b"{partial").unwrap();
    fs::write(slot_dir.join(".xace_tmp_crash_session.json"), b"partial").unwrap();

    let report = engine.recover().unwrap();
    let loaded = engine.load_session("slot_1").unwrap();
    let metadata = engine.load_metadata("slot_1").unwrap();

    assert_eq!(report.temp_files_removed, 1);
    assert_eq!(report.files_restored, 2);
    assert!(report.errors.is_empty());
    assert_eq!(loaded.tick, 11);
    assert_eq!(metadata.tick, 11);

    let _ = fs::remove_dir_all(root);
}

#[test]
fn x10_016_save_recovery_restores_last_complete_slot_after_metadata_gap() {
    let root = temp_root("x10_016_metadata_gap");
    let engine = FileSaveEngine::new(&root, "0.1.0");

    engine
        .save_session("slot_1", "Slot 1", &snapshot(21))
        .unwrap();
    engine
        .save_session("slot_1", "Slot 1", &snapshot(22))
        .unwrap();

    let slot_dir = root.join("slot_1");
    let old_metadata = fs::read(slot_dir.join(".xace_bak_metadata.json")).unwrap();
    fs::write(slot_dir.join("metadata.json"), old_metadata).unwrap();

    let report = engine.recover().unwrap();
    let loaded = engine.load_session("slot_1").unwrap();
    let metadata = engine.load_metadata("slot_1").unwrap();

    assert_eq!(report.files_restored, 1);
    assert!(report.errors.is_empty());
    assert_eq!(loaded.tick, 21);
    assert_eq!(metadata.tick, 21);

    let _ = fs::remove_dir_all(root);
}
