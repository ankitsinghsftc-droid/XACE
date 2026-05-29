//! # Query Engine Integration Tests

use crate::component_tables::ComponentTableStore;
use crate::query_engine::query_engine::QueryEngine;

fn setup() -> (QueryEngine, ComponentTableStore) {
    let mut store = ComponentTableStore::new();
    store.register_table(1, "COMP_TRANSFORM_V1").unwrap();
    store.register_table(2, "COMP_IDENTITY_V1").unwrap();
    store.register_table(5, "COMP_VELOCITY_V1").unwrap();
    store.register_table(6, "COMP_INPUT_V1").unwrap();
    (QueryEngine::new(), store)
}

#[test]
fn single_component_query_all_entities() {
    let (mut qe, mut store) = setup();
    for id in [3u64, 1, 4, 1, 5, 9, 2, 6] {
        let _ = store.add_component(id, 1, "{}".into(), 0);
    }
    let result = qe.query(&[1], &store, 0).unwrap();
    let ids = result.entity_ids;
    for window in ids.windows(2) {
        assert!(
            window[0] < window[1],
            "Not sorted: {} >= {}",
            window[0],
            window[1]
        );
    }
}

#[test]
fn query_no_matching_entities() {
    let (mut qe, store) = setup();
    let result = qe.query(&[1, 2], &store, 0).unwrap();
    assert!(result.is_empty());
}

#[test]
fn query_all_three_components() {
    let (mut qe, mut store) = setup();
    // Entity 1: all three
    store.add_component(1, 1, "{}".into(), 0).unwrap();
    store.add_component(1, 2, "{}".into(), 0).unwrap();
    store.add_component(1, 5, "{}".into(), 0).unwrap();
    // Entity 2: only two
    store.add_component(2, 1, "{}".into(), 0).unwrap();
    store.add_component(2, 2, "{}".into(), 0).unwrap();
    // Entity 3: only one
    store.add_component(3, 1, "{}".into(), 0).unwrap();

    let result = qe.query(&[1, 2, 5], &store, 0).unwrap();
    assert_eq!(result.entity_ids, vec![1]);
}

#[test]
fn cache_hit_rate_improves_with_repeated_queries() {
    let (mut qe, mut store) = setup();
    for id in 1u64..=10 {
        store.add_component(id, 1, "{}".into(), 0).unwrap();
    }
    // First query — cache miss
    let _ = qe.query(&[1], &store, 0).unwrap();
    // Repeated queries — cache hits
    for _ in 0..9 {
        let r = qe.query(&[1], &store, 0).unwrap();
        assert!(r.from_cache);
    }
    let stats = qe.cache_stats();
    assert!(stats.hit_rate() > 0.8);
}

#[test]
fn cache_invalidated_when_table_written() {
    let (mut qe, mut store) = setup();
    store.add_component(1, 1, "{}".into(), 0).unwrap();
    let _ = qe.query(&[1], &store, 0).unwrap();
    // Write invalidates
    store.add_component(2, 1, "{}".into(), 1).unwrap();
    let r = qe.query(&[1], &store, 1).unwrap();
    assert!(!r.from_cache);
    assert_eq!(r.entity_ids, vec![1, 2]);
}

#[test]
fn query_order_normalization_shares_cache() {
    let (mut qe, mut store) = setup();
    store.add_component(1, 1, "{}".into(), 0).unwrap();
    store.add_component(1, 2, "{}".into(), 0).unwrap();
    // First query establishes cache entry
    let r1 = qe.query(&[1, 2], &store, 0).unwrap();
    assert!(!r1.from_cache);
    // Reversed order — same cache entry
    let r2 = qe.query(&[2, 1], &store, 0).unwrap();
    assert!(r2.from_cache);
    assert_eq!(r1.entity_ids, r2.entity_ids);
}

#[test]
fn invalidate_all_forces_recompute() {
    let (mut qe, mut store) = setup();
    store.add_component(1, 1, "{}".into(), 0).unwrap();
    let _ = qe.query(&[1], &store, 0).unwrap();
    qe.invalidate_all();
    let r = qe.query(&[1], &store, 0).unwrap();
    assert!(!r.from_cache);
}

#[test]
fn determinism_two_engines_same_result() {
    let mut store = ComponentTableStore::new();
    store.register_table(1, "COMP_TRANSFORM_V1").unwrap();
    store.register_table(2, "COMP_IDENTITY_V1").unwrap();
    for id in [5u64, 2, 8, 1, 3] {
        store.add_component(id, 1, "{}".into(), 0).unwrap();
        store.add_component(id, 2, "{}".into(), 0).unwrap();
    }

    let mut qe1 = QueryEngine::new();
    let mut qe2 = QueryEngine::new();

    let r1 = qe1.query(&[1, 2], &store, 0).unwrap();
    let r2 = qe2.query(&[2, 1], &store, 0).unwrap();
    assert_eq!(r1.entity_ids, r2.entity_ids);
}
