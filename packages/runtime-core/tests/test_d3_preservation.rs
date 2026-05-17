/*!
# test_d3_preservation.rs — D3 Determinism Preservation Tests

## The Rule Being Tested

    D3: Entity iteration order is EntityID ASC at all times.

This is a **hard invariant** — not a suggestion. Any violation means
replays diverge and multiplayer desyncs. The tests here are the
specification: if any of them fails, archetype storage is broken and
must not be merged.

## Why D3 is Non-Trivial for Archetype Storage

BTreeMap satisfies D3 trivially: BTreeMap iterates in key order.

Archetype storage groups entities by component composition, so within
each archetype, entities are NOT stored in EntityID order — they're in
insertion order, with swap-remove relocations. The k-way merge in
`SortedMergeIterator` reconstructs global EntityID order across archetypes.

These tests verify:
    1. Single archetype: iter_sorted() is EntityID ASC ✓
    2. Multiple archetypes: SortedMergeIterator produces global ASC order ✓
    3. After add_entity in arbitrary order: still sorted ✓
    4. After remove_entity (triggers swap-remove): still sorted ✓
    5. After add_component (triggers entity migration): still sorted ✓
    6. After remove_component (triggers entity migration): still sorted ✓
    7. Large random insertion order: still sorted ✓
    8. Mixed archetype compositions: still sorted ✓
*/

use std::collections::BTreeMap;

use xace_runtime_core::component_tables::{
    archetype_storage::ArchetypeStorage,
    storage_strategy::TypeId,
};
use xace_runtime_core::query_engine::vectorized_query::Query;


// ── Type IDs ──────────────────────────────────────────────────────────────────

const POS: TypeId = 1;
const VEL: TypeId = 5;
const HP:  TypeId = 100;
const AI:  TypeId = 160;


// ── Helper ────────────────────────────────────────────────────────────────────

fn bytes(v: f32) -> Vec<u8> { v.to_le_bytes().to_vec() }

fn assert_sorted_asc(ids: &[u64], context: &str) {
    for window in ids.windows(2) {
        assert!(
            window[0] < window[1],
            "D3 VIOLATION: EntityID {} appears before {} — not in ASC order. Context: {}",
            window[0], window[1], context
        );
    }
}

fn insert_entity(
    storage: &mut ArchetypeStorage,
    eid:     u64,
    types:   &[TypeId],
) {
    let mut comps = BTreeMap::new();
    for &t in types {
        comps.insert(t, bytes(eid as f32));
    }
    storage.add_entity(eid, comps).unwrap();
}

fn collect_sorted_ids(storage: &ArchetypeStorage) -> Vec<u64> {
    storage.iter_sorted().map(|(e, _)| e).collect()
}


// ── Single Archetype ──────────────────────────────────────────────────────────

#[test]
fn d3_single_archetype_insertion_order_sorted() {
    let mut s = ArchetypeStorage::new();
    // Insert in reverse order
    for eid in [5, 3, 1, 4, 2].iter().copied() {
        insert_entity(&mut s, eid, &[POS, VEL]);
    }
    let ids = collect_sorted_ids(&s);
    assert_eq!(ids, vec![1, 2, 3, 4, 5]);
    assert_sorted_asc(&ids, "single archetype, reverse insertion order");
}

#[test]
fn d3_single_archetype_random_insertion_sorted() {
    let mut s = ArchetypeStorage::new();
    let insert_order = vec![17u64, 3, 99, 42, 1, 88, 7, 56, 23, 14];
    for eid in &insert_order {
        insert_entity(&mut s, *eid, &[POS, HP]);
    }
    let ids = collect_sorted_ids(&s);
    assert_sorted_asc(&ids, "single archetype, random insertion order");
    assert_eq!(ids.len(), insert_order.len());
}


// ── Multiple Archetypes ───────────────────────────────────────────────────────

#[test]
fn d3_multiple_archetypes_global_sorted() {
    let mut s = ArchetypeStorage::new();

    // Archetype A: POS+VEL (entities 2, 5, 7)
    insert_entity(&mut s, 5, &[POS, VEL]);
    insert_entity(&mut s, 2, &[POS, VEL]);
    insert_entity(&mut s, 7, &[POS, VEL]);

    // Archetype B: POS+HP (entities 1, 4, 6)
    insert_entity(&mut s, 4, &[POS, HP]);
    insert_entity(&mut s, 1, &[POS, HP]);
    insert_entity(&mut s, 6, &[POS, HP]);

    // Archetype C: POS+VEL+AI (entity 3)
    insert_entity(&mut s, 3, &[POS, VEL, AI]);

    let ids = collect_sorted_ids(&s);
    assert_eq!(ids, vec![1, 2, 3, 4, 5, 6, 7]);
    assert_sorted_asc(&ids, "k-way merge across three archetypes");
}

#[test]
fn d3_four_archetypes_interleaved_ids() {
    let mut s = ArchetypeStorage::new();

    // EntityIDs interleave across archetypes
    insert_entity(&mut s, 8,  &[POS]);
    insert_entity(&mut s, 1,  &[POS, VEL]);
    insert_entity(&mut s, 6,  &[POS]);
    insert_entity(&mut s, 3,  &[POS, VEL, HP]);
    insert_entity(&mut s, 10, &[VEL]);
    insert_entity(&mut s, 2,  &[POS, VEL]);
    insert_entity(&mut s, 9,  &[HP]);
    insert_entity(&mut s, 5,  &[POS, VEL, HP]);
    insert_entity(&mut s, 4,  &[POS, VEL]);
    insert_entity(&mut s, 7,  &[POS]);

    let ids = collect_sorted_ids(&s);
    assert_eq!(ids, vec![1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
    assert_sorted_asc(&ids, "four archetypes with interleaved EntityIDs");
}


// ── After Removal ─────────────────────────────────────────────────────────────

#[test]
fn d3_preserved_after_entity_removal() {
    let mut s = ArchetypeStorage::new();
    for eid in 1..=10u64 {
        insert_entity(&mut s, eid, &[POS, VEL]);
    }

    // Remove some entities
    for eid in [3u64, 7, 1, 9].iter() {
        s.remove_entity(*eid).unwrap();
    }

    let ids = collect_sorted_ids(&s);
    assert_eq!(ids, vec![2, 4, 5, 6, 8, 10]);
    assert_sorted_asc(&ids, "after removing entities 1, 3, 7, 9");
}

#[test]
fn d3_preserved_after_removing_first_and_last() {
    let mut s = ArchetypeStorage::new();
    for eid in 1..=5u64 {
        insert_entity(&mut s, eid, &[POS]);
    }
    s.remove_entity(1).unwrap();
    s.remove_entity(5).unwrap();

    let ids = collect_sorted_ids(&s);
    assert_eq!(ids, vec![2, 3, 4]);
    assert_sorted_asc(&ids, "after removing first (1) and last (5)");
}

#[test]
fn d3_preserved_after_removal_across_archetypes() {
    let mut s = ArchetypeStorage::new();
    insert_entity(&mut s, 1, &[POS]);
    insert_entity(&mut s, 2, &[POS, VEL]);
    insert_entity(&mut s, 3, &[POS]);
    insert_entity(&mut s, 4, &[POS, VEL]);
    insert_entity(&mut s, 5, &[POS]);

    // Remove alternating entities across archetypes
    s.remove_entity(2).unwrap();
    s.remove_entity(4).unwrap();

    let ids = collect_sorted_ids(&s);
    assert_eq!(ids, vec![1, 3, 5]);
    assert_sorted_asc(&ids, "removal across two archetypes");
}


// ── After Add/Remove Component (Migration) ────────────────────────────────────

#[test]
fn d3_preserved_after_add_component_migration() {
    let mut s = ArchetypeStorage::new();
    for eid in [3, 1, 5, 2, 4].iter().copied() {
        insert_entity(&mut s, eid, &[POS]);
    }

    // Add VEL to entities 2 and 4 — they migrate to a new archetype
    s.add_component(2, VEL, bytes(0.0)).unwrap();
    s.add_component(4, VEL, bytes(0.0)).unwrap();

    let ids = collect_sorted_ids(&s);
    assert_eq!(ids, vec![1, 2, 3, 4, 5]);
    assert_sorted_asc(&ids, "after add_component migration for entities 2 and 4");
}

#[test]
fn d3_preserved_after_remove_component_migration() {
    let mut s = ArchetypeStorage::new();
    for eid in 1..=5u64 {
        insert_entity(&mut s, eid, &[POS, VEL, HP]);
    }

    // Remove VEL from entities 2 and 4
    s.remove_component(2, VEL).unwrap();
    s.remove_component(4, VEL).unwrap();

    let ids = collect_sorted_ids(&s);
    assert_eq!(ids, vec![1, 2, 3, 4, 5]);
    assert_sorted_asc(&ids, "after remove_component migration for entities 2 and 4");
}

#[test]
fn d3_preserved_after_full_migration_sequence() {
    let mut s = ArchetypeStorage::new();

    // Mixed initial compositions
    insert_entity(&mut s, 10, &[POS]);
    insert_entity(&mut s, 20, &[POS, VEL]);
    insert_entity(&mut s, 30, &[POS, HP]);
    insert_entity(&mut s, 40, &[POS, VEL, HP]);
    insert_entity(&mut s, 50, &[POS]);

    // Chain of migrations
    s.add_component(10, VEL, bytes(0.0)).unwrap();   // 10: POS → POS+VEL
    s.remove_component(40, HP).unwrap();              // 40: POS+VEL+HP → POS+VEL
    s.add_component(30, VEL, bytes(0.0)).unwrap();    // 30: POS+HP → POS+VEL+HP
    s.remove_entity(20).unwrap();                     // 20: removed

    let ids = collect_sorted_ids(&s);
    assert_eq!(ids, vec![10, 30, 40, 50]);
    assert_sorted_asc(&ids, "after mixed migration and removal sequence");
}


// ── Large Scale Stress Test ───────────────────────────────────────────────────

#[test]
fn d3_large_random_insertion_order_across_many_archetypes() {
    use std::collections::HashSet;

    let mut s = ArchetypeStorage::new();
    let n     = 500usize;

    // Pseudo-random insertion order (deterministic seed via manual shuffle)
    let mut eids: Vec<u64> = (1..=(n as u64)).collect();
    // Simple knuth shuffle with fixed seed
    let mut seed = 12345u64;
    for i in (1..n).rev() {
        seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
        let j = (seed >> 33) as usize % (i + 1);
        eids.swap(i, j);
    }

    // 4 archetype compositions
    let comps_for = |eid: u64| -> &'static [TypeId] {
        match eid % 4 {
            0 => &[POS, VEL, HP, AI],
            1 => &[POS, VEL, HP],
            2 => &[POS, HP],
            _ => &[POS],
        }
    };

    for eid in &eids {
        insert_entity(&mut s, *eid, comps_for(*eid));
    }

    let ids = collect_sorted_ids(&s);
    assert_eq!(ids.len(), n, "all entities must be present");

    // D3: must be globally sorted
    assert_sorted_asc(&ids, "large random insertion across 4 archetype compositions");

    // Must contain exactly the right entities
    let expected: HashSet<u64> = (1..=(n as u64)).collect();
    let actual:   HashSet<u64> = ids.iter().copied().collect();
    assert_eq!(expected, actual, "no entities may be lost or duplicated");
}

#[test]
fn d3_query_filtered_results_also_sorted() {
    let mut s = ArchetypeStorage::new();
    for eid in [9, 3, 7, 1, 5].iter().copied() {
        insert_entity(&mut s, eid, &[POS, VEL]);
    }
    for eid in [8, 2, 6, 4].iter().copied() {
        insert_entity(&mut s, eid, &[POS]);  // no VEL
    }

    // Query for entities with VEL
    let q   = Query::any_with(VEL);
    let ids = q.entity_ids(&s);

    assert_eq!(ids, vec![1, 3, 5, 7, 9]);
    assert_sorted_asc(&ids, "query-filtered results must also be in EntityID ASC order");
}


// ── Archetype Index Consistency ───────────────────────────────────────────────

#[test]
fn d3_index_consistent_after_swap_remove_chain() {
    // Removes the first entity added — forces the last entity to move to row 0
    // This is the trickiest swap-remove case for index consistency.
    let mut s = ArchetypeStorage::new();
    let entities = [100u64, 1, 50, 25, 75];
    for eid in entities.iter() {
        insert_entity(&mut s, *eid, &[POS, VEL]);
    }

    // Remove entities in order — each triggers a swap-remove
    for eid in [100u64, 25, 75].iter() {
        s.remove_entity(*eid).unwrap();
        // After each removal, the remaining entities must still be accessible
        let ids = collect_sorted_ids(&s);
        assert_sorted_asc(&ids, &format!("after removing entity {}", eid));
    }

    let final_ids = collect_sorted_ids(&s);
    assert_eq!(final_ids, vec![1, 50]);
    assert_sorted_asc(&final_ids, "final state after swap-remove chain");

    // Verify component access still works for surviving entities
    assert!(s.get_component(1,  POS).is_ok());
    assert!(s.get_component(50, POS).is_ok());
}