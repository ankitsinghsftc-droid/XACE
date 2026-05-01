//! # Mutation Gate Integration Tests
//!
//! Tests covering ordering enforcement, atomicity, phase-boundary
//! application, and invalid mutation rejection.

use std::collections::BTreeMap;
use crate::mutation_gate::MutationGate;
use crate::entity_store::EntityStore;
use crate::component_tables::ComponentTableStore;

fn setup() -> (MutationGate, EntityStore, ComponentTableStore) {
    let gate = MutationGate::new();
    let entity_store = EntityStore::new();
    let mut table_store = ComponentTableStore::new();
    table_store.register_table(1, "COMP_TRANSFORM_V1").unwrap();
    table_store.register_table(2, "COMP_IDENTITY_V1").unwrap();
    table_store.register_table(5, "COMP_VELOCITY_V1").unwrap();
    (gate, entity_store, table_store)
}

// ── Ordering Enforcement Tests (D4) ───────────────────────────────────────────

#[test]
fn spawn_then_add_ordering_works() {
    let (mut gate, mut es, mut ts) = setup();
    // Request spawn with no initial components
    gate.request_spawn("actor_player", BTreeMap::new(), &ts, 0).unwrap();
    let delta = gate.apply_all(&mut es, &mut ts, 0).unwrap();
    let new_id = delta.spawned_entities[0].entity_id;
    // Now add a component to the spawned entity
    gate.request_add_component(new_id, 1, "{}", &es, &ts, 1).unwrap();
    gate.apply_all(&mut es, &mut ts, 1).unwrap();
    assert!(ts.has_component(new_id, 1));
}

#[test]
fn add_before_modify_ordering_enforced() {
    let (mut gate, mut es, mut ts) = setup();
    let id = es.create_entity(0).unwrap();
    // Add in queue 2
    gate.request_add_component(id, 1, r#"{"x":0}"#, &es, &ts, 0).unwrap();
    gate.apply_all(&mut es, &mut ts, 0).unwrap();
    // Modify in queue 3 (next tick)
    gate.request_modify_component(id, 1, r#"{"x":5}"#, &es, &ts, 1).unwrap();
    gate.apply_all(&mut es, &mut ts, 1).unwrap();
    assert_eq!(ts.get_component(id, 1), Some(r#"{"x":5}"#));
}

#[test]
fn destroy_applied_last_in_batch() {
    let (mut gate, mut es, mut ts) = setup();
    let existing = es.create_entity(0).unwrap();
    ts.add_component(existing, 1, "{}".into(), 0).unwrap();

    // In same apply batch:
    // - Spawn new entity (queue 1)
    // - Add component to existing (queue 2 — but existing is being destroyed)
    // - Destroy existing (queue 5 — applied last)
    gate.request_spawn("new", BTreeMap::new(), &ts, 1).unwrap();
    gate.request_destroy(existing, &es, 1).unwrap();

    let delta = gate.apply_all(&mut es, &mut ts, 1).unwrap();

    // New entity spawned
    assert_eq!(delta.spawned_entities.len(), 1);
    // Existing entity destroyed
    assert!(!es.exists(existing));
    assert!(es.archive().is_archived(existing));
}

// ── Direct Mutation Rejection Tests (I2) ──────────────────────────────────────

#[test]
fn null_entity_always_rejected() {
    let (mut gate, es, ts) = setup();
    assert!(gate.request_add_component(
        xace_core::entity_id::NULL_ENTITY_ID, 1, "{}", &es, &ts, 0
    ).is_err());
    assert!(gate.request_modify_component(
        xace_core::entity_id::NULL_ENTITY_ID, 1, "{}", &es, &ts, 0
    ).is_err());
    assert!(gate.request_remove_component(
        xace_core::entity_id::NULL_ENTITY_ID, 1, &es, &ts, 0
    ).is_err());
    assert!(gate.request_destroy(
        xace_core::entity_id::NULL_ENTITY_ID, &es, 0
    ).is_err());
    assert!(gate.is_empty());
}

#[test]
fn invalid_requests_never_enter_queue() {
    let (mut gate, es, ts) = setup();
    // All invalid — entity 999 doesn't exist
    let _ = gate.request_add_component(999, 1, "{}", &es, &ts, 0);
    let _ = gate.request_modify_component(999, 1, "{}", &es, &ts, 0);
    let _ = gate.request_remove_component(999, 1, &es, &ts, 0);
    let _ = gate.request_destroy(999, &es, 0);
    // Gate must be empty — none entered the queue
    assert!(gate.is_empty());
    assert_eq!(gate.pending_count(), 0);
}

// ── Atomicity Tests (I8) ──────────────────────────────────────────────────────

#[test]
fn apply_empty_gate_is_noop() {
    let (mut gate, mut es, mut ts) = setup();
    let initial_alive = es.alive_count();
    let delta = gate.apply_all(&mut es, &mut ts, 0).unwrap();
    assert!(delta.is_empty());
    assert_eq!(es.alive_count(), initial_alive);
}

#[test]
fn multiple_spawns_in_one_apply() {
    let (mut gate, mut es, mut ts) = setup();
    for _ in 0..5 {
        gate.request_spawn("actor", BTreeMap::new(), &ts, 0).unwrap();
    }
    let delta = gate.apply_all(&mut es, &mut ts, 0).unwrap();
    assert_eq!(delta.spawned_entities.len(), 5);
    assert_eq!(es.alive_count(), 5);
}

#[test]
fn spawned_entity_ids_are_unique_across_batches() {
    let (mut gate, mut es, mut ts) = setup();
    let mut all_ids = std::collections::HashSet::new();
    for tick in 0u64..5 {
        gate.request_spawn("actor", BTreeMap::new(), &ts, tick).unwrap();
        let delta = gate.apply_all(&mut es, &mut ts, tick).unwrap();
        let id = delta.spawned_entities[0].entity_id;
        assert!(all_ids.insert(id), "Duplicate entity ID: {}", id);
    }
}

// ── Delta Production Tests ────────────────────────────────────────────────────

#[test]
fn delta_records_spawn_correctly() {
    let (mut gate, mut es, mut ts) = setup();
    let mut init = BTreeMap::new();
    init.insert(1u32, r#"{"x":1.0}"#.to_string());
    gate.request_spawn("actor_player", init, &ts, 0).unwrap();
    let delta = gate.apply_all(&mut es, &mut ts, 0).unwrap();
    assert_eq!(delta.spawned_entities.len(), 1);
    assert_eq!(delta.spawned_entities[0].actor_id, "actor_player");
    assert!(delta.spawned_entities[0].initial_components.contains_key(&1));
}

#[test]
fn delta_records_destroy_correctly() {
    let (mut gate, mut es, mut ts) = setup();
    let id = es.create_entity(0).unwrap();
    gate.request_destroy(id, &es, 1).unwrap();
    let delta = gate.apply_all(&mut es, &mut ts, 1).unwrap();
    assert_eq!(delta.destroyed_entities.len(), 1);
    assert_eq!(delta.destroyed_entities[0].entity_id, id);
}

#[test]
fn delta_spawned_entities_sorted_ascending() {
    let (mut gate, mut es, mut ts) = setup();
    for _ in 0..5 {
        gate.request_spawn("actor", BTreeMap::new(), &ts, 0).unwrap();
    }
    let delta = gate.apply_all(&mut es, &mut ts, 0).unwrap();
    let ids: Vec<u64> = delta.spawned_entities.iter()
        .map(|e| e.entity_id)
        .collect();
    for window in ids.windows(2) {
        assert!(window[0] < window[1],
            "Spawned entities not sorted: {} >= {}", window[0], window[1]);
    }
}

// ── Phase Boundary Tests ──────────────────────────────────────────────────────

#[test]
fn gate_empty_after_successful_apply() {
    let (mut gate, mut es, mut ts) = setup();
    gate.request_spawn("actor", BTreeMap::new(), &ts, 0).unwrap();
    assert!(!gate.is_empty());
    gate.apply_all(&mut es, &mut ts, 0).unwrap();
    assert!(gate.is_empty());
}

#[test]
fn gate_accepts_new_requests_after_apply() {
    let (mut gate, mut es, mut ts) = setup();
    gate.request_spawn("actor1", BTreeMap::new(), &ts, 0).unwrap();
    gate.apply_all(&mut es, &mut ts, 0).unwrap();
    // Gate should accept new requests after apply
    gate.request_spawn("actor2", BTreeMap::new(), &ts, 1).unwrap();
    let delta = gate.apply_all(&mut es, &mut ts, 1).unwrap();
    assert_eq!(delta.spawned_entities.len(), 1);
    assert_eq!(es.alive_count(), 2);
}

#[test]
fn destroy_cleans_all_entity_components() {
    let (mut gate, mut es, mut ts) = setup();
    let id = es.create_entity(0).unwrap();
    ts.add_component(id, 1, "{}".into(), 0).unwrap();
    ts.add_component(id, 2, "{}".into(), 0).unwrap();
    ts.add_component(id, 5, "{}".into(), 0).unwrap();

    gate.request_destroy(id, &es, 1).unwrap();
    gate.apply_all(&mut es, &mut ts, 1).unwrap();

    assert!(!ts.has_component(id, 1));
    assert!(!ts.has_component(id, 2));
    assert!(!ts.has_component(id, 5));
    assert!(!es.exists(id));
}