//! # Component Tables Integration Tests
//!
//! Tests covering SortedEntityMap, ComponentTable, and ComponentTableStore
//! together — focusing on determinism guarantees, sort order, and
//! snapshot consistency.

use crate::component_tables::component_table::ComponentTable;
use crate::component_tables::component_table_store::ComponentTableStore;
use crate::component_tables::sorted_entity_map::SortedEntityMap;

// ── SortedEntityMap Tests ──────────────────────────────────────────────────────

#[test]
fn sorted_map_always_iterates_ascending_regardless_of_insertion_order() {
    let mut map: SortedEntityMap<i32> = SortedEntityMap::new();
    for id in [100, 1, 50, 3, 77, 2] {
        map.insert(id, id as i32);
    }
    let ids: Vec<u64> = map.keys().collect();
    assert_eq!(ids, vec![1, 2, 3, 50, 77, 100]);
}

#[test]
fn sorted_map_determinism_two_maps_same_content_same_iteration() {
    let mut a: SortedEntityMap<String> = SortedEntityMap::new();
    let mut b: SortedEntityMap<String> = SortedEntityMap::new();
    for id in [5, 3, 1, 4, 2] {
        a.insert(id, format!("v{}", id));
        b.insert(id, format!("v{}", id));
    }
    let a_pairs: Vec<_> = a.iter().map(|(id, v)| (id, v.clone())).collect();
    let b_pairs: Vec<_> = b.iter().map(|(id, v)| (id, v.clone())).collect();
    assert_eq!(a_pairs, b_pairs);
}

#[test]
fn sorted_map_after_remove_iteration_still_sorted() {
    let mut map: SortedEntityMap<i32> = SortedEntityMap::new();
    for id in [1, 2, 3, 4, 5] {
        map.insert(id, id as i32);
    }
    map.remove(3);
    let ids: Vec<u64> = map.keys().collect();
    assert_eq!(ids, vec![1, 2, 4, 5]);
}

// ── ComponentTable Tests ───────────────────────────────────────────────────────

#[test]
fn table_add_update_remove_lifecycle() {
    let mut table = ComponentTable::new(1, "COMP_TRANSFORM_V1");
    let json = r#"{"position":{"x":1.0,"y":0.0,"z":0.0}}"#.to_string();

    table.add(1, json.clone(), 0).unwrap();
    assert!(table.has(1));
    assert_eq!(table.get(1), Some(json.as_str()));

    let updated = r#"{"position":{"x":5.0,"y":0.0,"z":0.0}}"#.to_string();
    table.update(1, updated.clone(), 1).unwrap();
    assert_eq!(table.get(1), Some(updated.as_str()));

    table.remove(1, 2).unwrap();
    assert!(!table.has(1));
    assert_eq!(table.count(), 0);
}

#[test]
fn table_iteration_order_is_deterministic_d3() {
    let mut table = ComponentTable::new(1, "COMP_TEST");
    for id in [10, 3, 7, 1, 5] {
        table.add(id, format!("{{\"id\":{}}}", id), 0).unwrap();
    }
    let ids: Vec<u64> = table.iter().map(|(id, _)| id).collect();
    assert_eq!(ids, vec![1, 3, 5, 7, 10]);
    for window in ids.windows(2) {
        assert!(window[0] < window[1],
            "Iteration not sorted: {} >= {}", window[0], window[1]);
    }
}

#[test]
fn table_version_tracks_all_write_operations() {
    let mut table = ComponentTable::new(1, "COMP_TEST");
    assert_eq!(table.version(), 0);

    table.add(1, "{}".into(), 0).unwrap();
    assert_eq!(table.version(), 1);

    table.add(2, "{}".into(), 0).unwrap();
    assert_eq!(table.version(), 2);

    table.update(1, "{\"x\":1}".into(), 1).unwrap();
    assert_eq!(table.version(), 3);

    table.remove(2, 1).unwrap();
    assert_eq!(table.version(), 4);

    table.remove_for_entity(999); // no-op
    assert_eq!(table.version(), 4); // unchanged

    table.remove_for_entity(1); // has entity
    assert_eq!(table.version(), 5);
}

#[test]
fn table_entity_ids_in_set_returns_sorted_intersection() {
    let mut table = ComponentTable::new(1, "COMP_TEST");
    for id in [2, 4, 6, 8, 10] {
        table.add(id, "{}".into(), 0).unwrap();
    }
    let set = vec![1, 2, 5, 6, 9, 10, 11];
    let result = table.entity_ids_in_set(&set);
    assert_eq!(result, vec![2, 6, 10]);
}

#[test]
fn table_deep_clone_independent_after_modification() {
    let mut original = ComponentTable::new(1, "COMP_TEST");
    original.add(1, r#"{"x":1}"#.into(), 0).unwrap();
    original.add(2, r#"{"x":2}"#.into(), 0).unwrap();

    let mut cloned = original.deep_clone();
    cloned.update(1, r#"{"x":999}"#.into(), 1).unwrap();
    cloned.add(3, r#"{"x":3}"#.into(), 1).unwrap();

    // Original unchanged
    assert_eq!(original.get(1), Some(r#"{"x":1}"#));
    assert!(!original.has(3));
    assert_eq!(original.count(), 2);
}

#[test]
fn table_snapshot_json_is_deterministic() {
    let mut t1 = ComponentTable::new(1, "COMP_TEST");
    let mut t2 = ComponentTable::new(1, "COMP_TEST");

    for id in [1, 2, 3] {
        let json = format!(r#"{{"id":{}}}"#, id);
        t1.add(id, json.clone(), 0).unwrap();
        t2.add(id, json, 0).unwrap();
    }

    assert_eq!(t1.to_snapshot_json(), t2.to_snapshot_json());
}

#[test]
fn table_restore_from_snapshot_replaces_all_data() {
    let mut table = ComponentTable::new(1, "COMP_TEST");
    table.add(1, r#"{"old":true}"#.into(), 0).unwrap();
    table.add(2, r#"{"old":true}"#.into(), 0).unwrap();

    table.restore_from_snapshot(vec![
        (10, r#"{"new":true}"#.into()),
        (20, r#"{"new":true}"#.into()),
    ]);

    assert!(!table.has(1));
    assert!(!table.has(2));
    assert!(table.has(10));
    assert!(table.has(20));
    assert_eq!(table.count(), 2);
}

// ── ComponentTableStore Tests ──────────────────────────────────────────────────

#[test]
fn store_multi_table_intersection_sorted_d3() {
    let mut store = ComponentTableStore::new();
    store.register_table(1, "COMP_TRANSFORM_V1").unwrap();
    store.register_table(2, "COMP_IDENTITY_V1").unwrap();
    store.register_table(5, "COMP_VELOCITY_V1").unwrap();

    // Entities with all three components
    for id in [1, 3, 5] {
        store.add_component(id, 1, "{}".into(), 0).unwrap();
        store.add_component(id, 2, "{}".into(), 0).unwrap();
        store.add_component(id, 5, "{}".into(), 0).unwrap();
    }
    // Entity with only transform + identity
    store.add_component(2, 1, "{}".into(), 0).unwrap();
    store.add_component(2, 2, "{}".into(), 0).unwrap();
    // Entity with only transform
    store.add_component(4, 1, "{}".into(), 0).unwrap();

    let all_three = store.entities_with_all_components(&[1, 2, 5]);
    assert_eq!(all_three, vec![1, 3, 5]);

    let two = store.entities_with_all_components(&[1, 2]);
    assert_eq!(two, vec![1, 2, 3, 5]);

    let one = store.entities_with_all_components(&[1]);
    assert_eq!(one, vec![1, 2, 3, 4, 5]);
}

#[test]
fn store_remove_all_for_entity_cleans_all_tables() {
    let mut store = ComponentTableStore::new();
    store.register_table(1, "COMP_TRANSFORM_V1").unwrap();
    store.register_table(2, "COMP_IDENTITY_V1").unwrap();

    store.add_component(42, 1, "{}".into(), 0).unwrap();
    store.add_component(42, 2, "{}".into(), 0).unwrap();
    store.add_component(1, 1, "{}".into(), 0).unwrap(); // other entity

    store.remove_all_for_entity(42);

    assert!(!store.has_component(42, 1));
    assert!(!store.has_component(42, 2));
    assert!(store.has_component(1, 1)); // other entity unaffected
}

#[test]
fn store_combined_version_increases_on_any_write() {
    let mut store = ComponentTableStore::new();
    store.register_table(1, "COMP_TRANSFORM_V1").unwrap();
    store.register_table(2, "COMP_IDENTITY_V1").unwrap();

    let v0 = store.combined_version();
    store.add_component(1, 1, "{}".into(), 0).unwrap();
    let v1 = store.combined_version();
    store.add_component(1, 2, "{}".into(), 0).unwrap();
    let v2 = store.combined_version();

    assert!(v1 > v0);
    assert!(v2 > v1);
}

#[test]
fn store_component_types_for_entity_sorted() {
    let mut store = ComponentTableStore::new();
    store.register_table(5, "COMP_VELOCITY_V1").unwrap();
    store.register_table(1, "COMP_TRANSFORM_V1").unwrap();
    store.register_table(3, "COMP_RENDER_V1").unwrap();

    store.add_component(1, 5, "{}".into(), 0).unwrap();
    store.add_component(1, 1, "{}".into(), 0).unwrap();
    store.add_component(1, 3, "{}".into(), 0).unwrap();

    let types = store.component_types_for_entity(1);
    assert_eq!(types, vec![1, 3, 5]); // sorted ascending
}

#[test]
fn store_all_type_ids_sorted_ascending() {
    let mut store = ComponentTableStore::new();
    store.register_table(9, "C9").unwrap();
    store.register_table(1, "C1").unwrap();
    store.register_table(5, "C5").unwrap();
    assert_eq!(store.all_type_ids(), vec![1, 5, 9]);
}

#[test]
fn store_deep_clone_produces_independent_copy() {
    let mut store = ComponentTableStore::new();
    store.register_table(1, "COMP_TRANSFORM_V1").unwrap();
    store.add_component(1, 1, r#"{"x":1}"#.into(), 0).unwrap();

    let cloned = store.deep_clone_all();
    store.update_component(1, 1, r#"{"x":999}"#.into(), 1).unwrap();

    let original_in_clone = cloned.get(&1).unwrap().get(1);
    assert_eq!(original_in_clone, Some(r#"{"x":1}"#));
}

#[test]
fn store_intersection_empty_when_no_common_entities() {
    let mut store = ComponentTableStore::new();
    store.register_table(1, "COMP_A").unwrap();
    store.register_table(2, "COMP_B").unwrap();

    store.add_component(1, 1, "{}".into(), 0).unwrap(); // only has A
    store.add_component(2, 2, "{}".into(), 0).unwrap(); // only has B

    let result = store.entities_with_all_components(&[1, 2]);
    assert!(result.is_empty());
}

#[test]
fn sort_order_consistency_across_repeated_queries() {
    let mut store = ComponentTableStore::new();
    store.register_table(1, "COMP_TEST").unwrap();

    for id in [8, 3, 1, 6, 2, 5] {
        store.add_component(id, 1, "{}".into(), 0).unwrap();
    }

    // Run the same query multiple times — must return identical results
    let r1 = store.entities_with_all_components(&[1]);
    let r2 = store.entities_with_all_components(&[1]);
    let r3 = store.entities_with_all_components(&[1]);

    assert_eq!(r1, r2);
    assert_eq!(r2, r3);
    assert_eq!(r1, vec![1, 2, 3, 5, 6, 8]);
}