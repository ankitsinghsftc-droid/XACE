//! # Entity Store Tests
//!
//! Integration tests for the EntityStore covering the full entity
//! lifecycle, determinism guarantees, and snapshot restore correctness.

use crate::entity_store::entity_store::EntityStore;
use xace_core::entity_id::NULL_ENTITY_ID;
use xace_core::entity_state::EntityState;

// ── Creation Tests ─────────────────────────────────────────────────────────────

#[test]
fn create_entity_never_returns_null_id() {
    let mut store = EntityStore::new();
    for _ in 0..100 {
        let id = store.create_entity(0).unwrap();
        assert_ne!(id, NULL_ENTITY_ID);
    }
}

#[test]
fn created_entities_are_immediately_alive() {
    let mut store = EntityStore::new();
    let id = store.create_entity(0).unwrap();
    assert!(store.is_alive(id));
    assert!(store.exists(id));
}

#[test]
fn created_entity_metadata_has_correct_tick() {
    let mut store = EntityStore::new();
    let id = store.create_entity(42).unwrap();
    let meta = store.get_metadata(id).unwrap();
    assert_eq!(meta.created_tick, 42);
    assert_eq!(meta.id, id);
}

#[test]
fn created_entity_starts_active() {
    let mut store = EntityStore::new();
    let id = store.create_entity(0).unwrap();
    let meta = store.get_metadata(id).unwrap();
    assert_eq!(meta.state, EntityState::Active);
}

// ── ID Uniqueness Tests ────────────────────────────────────────────────────────

#[test]
fn all_created_ids_are_unique() {
    let mut store = EntityStore::new();
    let mut ids = std::collections::HashSet::new();
    for _ in 0..1000 {
        let id = store.create_entity(0).unwrap();
        assert!(ids.insert(id), "Duplicate ID generated: {}", id);
    }
}

#[test]
fn ids_are_strictly_increasing() {
    let mut store = EntityStore::new();
    let mut prev = 0u64;
    for _ in 0..100 {
        let id = store.create_entity(0).unwrap();
        assert!(id > prev, "ID {} not greater than previous {}", id, prev);
        prev = id;
    }
}

// ── Sort Order Tests (D3) ──────────────────────────────────────────────────────

#[test]
fn get_all_alive_sorted_ascending_d3() {
    let mut store = EntityStore::new();
    let a = store.create_entity(0).unwrap();
    let b = store.create_entity(0).unwrap();
    let c = store.create_entity(0).unwrap();
    let alive = store.get_all_alive();
    assert_eq!(alive, vec![a, b, c]);
    for window in alive.windows(2) {
        assert!(
            window[0] < window[1],
            "get_all_alive() not sorted: {} >= {}",
            window[0],
            window[1]
        );
    }
}

#[test]
fn get_all_alive_excludes_disabled() {
    let mut store = EntityStore::new();
    let a = store.create_entity(0).unwrap();
    let b = store.create_entity(0).unwrap();
    let c = store.create_entity(0).unwrap();
    store.disable_entity(b, 1).unwrap();
    let alive = store.get_all_alive();
    assert_eq!(alive, vec![a, c]);
    assert!(!alive.contains(&b));
}

#[test]
fn get_all_alive_excludes_destroy_requested() {
    let mut store = EntityStore::new();
    let a = store.create_entity(0).unwrap();
    let b = store.create_entity(0).unwrap();
    store.request_destroy(b, 1).unwrap();
    let alive = store.get_all_alive();
    assert_eq!(alive, vec![a]);
}

#[test]
fn get_all_present_includes_disabled_and_destroy_requested() {
    let mut store = EntityStore::new();
    let a = store.create_entity(0).unwrap();
    let b = store.create_entity(0).unwrap();
    let c = store.create_entity(0).unwrap();
    store.disable_entity(b, 1).unwrap();
    store.request_destroy(c, 1).unwrap();
    let present = store.get_all_present();
    assert_eq!(present.len(), 3);
    assert!(present.contains(&a));
    assert!(present.contains(&b));
    assert!(present.contains(&c));
}

// ── Lifecycle Transition Tests ─────────────────────────────────────────────────

#[test]
fn active_to_disabled_transition() {
    let mut store = EntityStore::new();
    let id = store.create_entity(0).unwrap();
    store.disable_entity(id, 1).unwrap();
    assert!(!store.is_alive(id));
    assert!(store.exists(id));
    let meta = store.get_metadata(id).unwrap();
    assert_eq!(meta.state, EntityState::Disabled);
}

#[test]
fn disabled_to_active_transition() {
    let mut store = EntityStore::new();
    let id = store.create_entity(0).unwrap();
    store.disable_entity(id, 1).unwrap();
    store.enable_entity(id, 2).unwrap();
    assert!(store.is_alive(id));
    let meta = store.get_metadata(id).unwrap();
    assert_eq!(meta.state, EntityState::Active);
}

#[test]
fn full_destruction_lifecycle() {
    let mut store = EntityStore::new();
    let id = store.create_entity(0).unwrap();

    // Active → DestroyRequested
    store.request_destroy(id, 10).unwrap();
    assert!(!store.is_alive(id));
    assert!(store.exists(id));

    // DestroyRequested → Destroyed → Archived
    store.complete_destroy(id, 11).unwrap();
    assert!(!store.exists(id));
    assert!(!store.is_alive(id));
    assert!(store.archive().is_archived(id));
}

#[test]
fn destroy_stamps_correct_tick() {
    let mut store = EntityStore::new();
    let id = store.create_entity(0).unwrap();
    store.request_destroy(id, 5).unwrap();
    store.complete_destroy(id, 6).unwrap();
    assert_eq!(store.archive().destroyed_at_tick(id), Some(6));
}

// ── Invalid Transition Tests ───────────────────────────────────────────────────

#[test]
fn cannot_destroy_without_request() {
    let mut store = EntityStore::new();
    let id = store.create_entity(0).unwrap();
    // complete_destroy without request_destroy should fail
    assert!(store.complete_destroy(id, 1).is_err());
}

#[test]
fn cannot_enable_already_active_entity() {
    let mut store = EntityStore::new();
    let id = store.create_entity(0).unwrap();
    assert!(store.enable_entity(id, 1).is_err());
}

#[test]
fn cannot_disable_already_disabled_entity() {
    let mut store = EntityStore::new();
    let id = store.create_entity(0).unwrap();
    store.disable_entity(id, 1).unwrap();
    assert!(store.disable_entity(id, 2).is_err());
}

#[test]
fn operations_on_nonexistent_entity_fail() {
    let mut store = EntityStore::new();
    assert!(store.disable_entity(999, 0).is_err());
    assert!(store.enable_entity(999, 0).is_err());
    assert!(store.request_destroy(999, 0).is_err());
    assert!(store.complete_destroy(999, 0).is_err());
    assert!(store.add_tag(999, "tag".into()).is_err());
}

// ── Archive Tests (D2) ────────────────────────────────────────────────────────

#[test]
fn archived_ids_never_returned_by_alive_query() {
    let mut store = EntityStore::new();
    let id = store.create_entity(0).unwrap();
    store.request_destroy(id, 1).unwrap();
    store.complete_destroy(id, 2).unwrap();
    assert!(!store.get_all_alive().contains(&id));
    assert!(!store.get_all_present().contains(&id));
}

#[test]
fn archive_tracks_all_destroyed_ids() {
    let mut store = EntityStore::new();
    let mut destroyed_ids = Vec::new();
    for i in 0..10 {
        let id = store.create_entity(0).unwrap();
        store.request_destroy(id, i).unwrap();
        store.complete_destroy(id, i + 1).unwrap();
        destroyed_ids.push(id);
    }
    for id in destroyed_ids {
        assert!(store.archive().is_archived(id));
    }
}

// ── Tag Tests ─────────────────────────────────────────────────────────────────

#[test]
fn tags_added_and_queried() {
    let mut store = EntityStore::new();
    let id = store.create_entity(0).unwrap();
    store.add_tag(id, "enemy".into()).unwrap();
    store.add_tag(id, "ai".into()).unwrap();
    let meta = store.get_metadata(id).unwrap();
    assert!(meta.has_tag("enemy"));
    assert!(meta.has_tag("ai"));
    assert!(!meta.has_tag("player"));
}

#[test]
fn tags_removed_correctly() {
    let mut store = EntityStore::new();
    let id = store.create_entity(0).unwrap();
    store.add_tag(id, "enemy".into()).unwrap();
    store.remove_tag(id, "enemy").unwrap();
    let meta = store.get_metadata(id).unwrap();
    assert!(!meta.has_tag("enemy"));
}

#[test]
fn get_by_tag_returns_sorted_ids() {
    let mut store = EntityStore::new();
    let a = store.create_entity(0).unwrap();
    let b = store.create_entity(0).unwrap();
    let c = store.create_entity(0).unwrap();
    store.add_tag(a, "enemy".into()).unwrap();
    store.add_tag(b, "player".into()).unwrap();
    store.add_tag(c, "enemy".into()).unwrap();
    let enemies = store.get_by_tag("enemy");
    assert_eq!(enemies, vec![a, c]);
    for window in enemies.windows(2) {
        assert!(window[0] < window[1]);
    }
}

#[test]
fn disabled_entity_not_returned_by_tag_query() {
    let mut store = EntityStore::new();
    let id = store.create_entity(0).unwrap();
    store.add_tag(id, "enemy".into()).unwrap();
    store.disable_entity(id, 1).unwrap();
    assert!(!store.get_by_tag("enemy").contains(&id));
}

// ── Count Tests ───────────────────────────────────────────────────────────────

#[test]
fn alive_count_accurate() {
    let mut store = EntityStore::new();
    let a = store.create_entity(0).unwrap();
    let b = store.create_entity(0).unwrap();
    let c = store.create_entity(0).unwrap();
    store.disable_entity(a, 1).unwrap();
    store.request_destroy(b, 1).unwrap();
    // Only c is alive
    assert!(store.is_alive(c));
    assert_eq!(store.alive_count(), 1);
}

#[test]
fn present_count_includes_disabled_and_destroy_requested() {
    let mut store = EntityStore::new();
    let a = store.create_entity(0).unwrap();
    let b = store.create_entity(0).unwrap();
    let c = store.create_entity(0).unwrap();
    store.disable_entity(a, 1).unwrap();
    store.request_destroy(b, 1).unwrap();
    store.complete_destroy(b, 2).unwrap();
    // a (disabled) + c (active) = 2 present
    assert!(store.is_alive(c));
    assert_eq!(store.present_count(), 2);
}

#[test]
fn total_count_includes_archived() {
    let mut store = EntityStore::new();
    let id = store.create_entity(0).unwrap();
    store.request_destroy(id, 1).unwrap();
    store.complete_destroy(id, 2).unwrap();
    // Archived entity still in map
    assert_eq!(store.total_count(), 1);
}

// ── Snapshot Restore Tests (I10) ───────────────────────────────────────────────

#[test]
fn snapshot_restore_preserves_alive_entities() {
    let mut store = EntityStore::new();
    let id1 = store.create_entity(0).unwrap();
    let id2 = store.create_entity(0).unwrap();

    let records: Vec<_> = store.all_metadata_sorted().into_iter().cloned().collect();
    let next_id = store.peek_next_id();
    let archive_entries = store.archive().all_entries_sorted();

    let mut restored = EntityStore::new();
    restored.restore_from_snapshot(records, next_id, archive_entries);

    assert!(restored.is_alive(id1));
    assert!(restored.is_alive(id2));
    assert_eq!(restored.alive_count(), 2);
}

#[test]
fn snapshot_restore_preserves_generator_state() {
    let mut store = EntityStore::new();
    store.create_entity(0).unwrap();
    store.create_entity(0).unwrap();
    let next_before = store.peek_next_id();

    let records: Vec<_> = store.all_metadata_sorted().into_iter().cloned().collect();

    let mut restored = EntityStore::new();
    restored.restore_from_snapshot(records, next_before, vec![]);

    assert_eq!(restored.peek_next_id(), next_before);

    // New IDs after restore must not collide with pre-snapshot IDs
    let new_id = restored.create_entity(0).unwrap();
    assert!(new_id >= next_before);
}

#[test]
fn snapshot_restore_preserves_archive() {
    let mut store = EntityStore::new();
    let id = store.create_entity(0).unwrap();
    store.request_destroy(id, 1).unwrap();
    store.complete_destroy(id, 2).unwrap();

    let records: Vec<_> = store.all_metadata_sorted().into_iter().cloned().collect();
    let next_id = store.peek_next_id();
    let archive_entries = store.archive().all_entries_sorted();

    let mut restored = EntityStore::new();
    restored.restore_from_snapshot(records, next_id, archive_entries);

    assert!(restored.archive().is_archived(id));
}

#[test]
fn determinism_same_operations_same_alive_order() {
    // Two stores with identical operations must produce identical get_all_alive()
    let mut store1 = EntityStore::new();
    let mut store2 = EntityStore::new();

    for tick in 0u64..5 {
        store1.create_entity(tick).unwrap();
        store2.create_entity(tick).unwrap();
    }

    assert_eq!(store1.get_all_alive(), store2.get_all_alive());
}
