/*!
# test_archetype.rs — Archetype and ArchetypeStorage Tests

Unit tests for:
- Archetype column management (insert, remove, modify, swap-remove)
- ArchetypeStorage API (add/remove entity, add/remove component, query)
- Entity migration between archetypes on component structure change
- ArchetypeIndex consistency after every mutation
*/

use std::collections::{BTreeMap, BTreeSet};

use xace_runtime_core::component_tables::{
    archetype::Archetype,
    archetype_index::{ArchetypeIndex, ArchetypeLocation},
    archetype_storage::ArchetypeStorage,
    storage_strategy::{ArchetypeId, EntityId, TypeId},
};

// ── Type IDs ──────────────────────────────────────────────────────────────────

const POS: TypeId = 1;
const VEL: TypeId = 5;
const HP: TypeId = 100;
const AI: TypeId = 160;

// ── Helpers ───────────────────────────────────────────────────────────────────

fn bytes(v: f32) -> Vec<u8> {
    v.to_le_bytes().to_vec()
}
fn u32_bytes(v: u32) -> Vec<u8> {
    v.to_le_bytes().to_vec()
}

fn storage_with_entities(entity_specs: &[(EntityId, &[TypeId])]) -> ArchetypeStorage {
    let mut storage = ArchetypeStorage::new();
    for &(eid, types) in entity_specs {
        let mut comps = BTreeMap::new();
        for &t in types {
            comps.insert(t, bytes(eid as f32));
        }
        storage.add_entity(eid, comps).unwrap();
    }
    storage
}

// ── Archetype Tests ───────────────────────────────────────────────────────────

mod archetype_tests {
    use super::*;

    fn make_archetype() -> Archetype {
        let set = [POS, VEL, HP].iter().copied().collect();
        Archetype::new(1, set)
    }

    fn add(arch: &mut Archetype, eid: EntityId) -> usize {
        let mut comps = BTreeMap::new();
        comps.insert(POS, bytes(eid as f32));
        comps.insert(VEL, bytes(0.0));
        comps.insert(HP, bytes(100.0));
        arch.add_entity(eid, comps)
    }

    #[test]
    fn add_entity_increments_count() {
        let mut a = make_archetype();
        assert_eq!(a.entity_count(), 0);
        add(&mut a, 1);
        add(&mut a, 2);
        assert_eq!(a.entity_count(), 2);
    }

    #[test]
    fn get_component_returns_inserted_value() {
        let mut a = make_archetype();
        add(&mut a, 42);
        let val = a.get_component(42, POS).unwrap();
        let f = f32::from_le_bytes(val.try_into().unwrap());
        assert_eq!(f, 42.0_f32);
    }

    #[test]
    fn set_component_updates_value() {
        let mut a = make_archetype();
        add(&mut a, 10);
        let old = a.set_component(10, HP, bytes(50.0)).unwrap();
        let old_f = f32::from_le_bytes(old.try_into().unwrap());
        assert_eq!(old_f, 100.0);
        let new_val = a.get_component(10, HP).unwrap();
        let new_f = f32::from_le_bytes(new_val.try_into().unwrap());
        assert_eq!(new_f, 50.0);
    }

    #[test]
    fn remove_entity_decrements_count() {
        let mut a = make_archetype();
        add(&mut a, 1);
        add(&mut a, 2);
        a.remove_entity(1);
        assert_eq!(a.entity_count(), 1);
    }

    #[test]
    fn remove_entity_returns_components() {
        let mut a = make_archetype();
        add(&mut a, 7);
        let removed = a.remove_entity(7).unwrap();
        assert!(removed.contains_key(&POS));
        assert!(removed.contains_key(&VEL));
        assert!(removed.contains_key(&HP));
    }

    #[test]
    fn remove_entity_swap_reindex_preserves_other_entities() {
        let mut a = make_archetype();
        add(&mut a, 1);
        add(&mut a, 2);
        add(&mut a, 3);
        a.remove_entity(1); // entity 3 moves to row 0
                            // entity 2 and 3 should still be accessible
        assert!(a.get_component(2, POS).is_some());
        assert!(a.get_component(3, POS).is_some());
    }

    #[test]
    fn iter_sorted_is_entity_id_asc() {
        let mut a = make_archetype();
        add(&mut a, 3);
        add(&mut a, 1);
        add(&mut a, 2);
        let ids: Vec<EntityId> = a.iter_sorted().map(|(e, _)| e).collect();
        assert_eq!(ids, vec![1, 2, 3]);
    }

    #[test]
    fn contains_returns_true_for_added_entities() {
        let mut a = make_archetype();
        add(&mut a, 5);
        assert!(a.contains(5));
        assert!(!a.contains(99));
    }

    #[test]
    fn matches_query_true_for_subset() {
        let mut a = make_archetype();
        let req = [POS, VEL].iter().copied().collect();
        assert!(a.matches_query(&req));
    }

    #[test]
    fn matches_query_false_for_superset() {
        let mut a = make_archetype();
        // AI is not in the archetype
        let req = [POS, VEL, AI].iter().copied().collect();
        assert!(!a.matches_query(&req));
    }
}

// ── ArchetypeStorage Tests ────────────────────────────────────────────────────

mod archetype_storage_tests {
    use super::*;

    #[test]
    fn add_entity_is_accessible() {
        let mut s = ArchetypeStorage::new();
        let mut c = BTreeMap::new();
        c.insert(POS, bytes(1.0));
        c.insert(VEL, bytes(0.0));
        s.add_entity(1, c).unwrap();

        let val = s.get_component(1, POS).unwrap();
        let f = f32::from_le_bytes(val.try_into().unwrap());
        assert_eq!(f, 1.0);
    }

    #[test]
    fn add_entity_twice_returns_error() {
        let mut s = ArchetypeStorage::new();
        let mut c = BTreeMap::new();
        c.insert(POS, bytes(0.0));
        s.add_entity(1, c.clone()).unwrap();
        assert!(s.add_entity(1, c).is_err());
    }

    #[test]
    fn remove_entity_reduces_count() {
        let s = storage_with_entities(&[(1, &[POS, VEL]), (2, &[POS, VEL])]);
        let mut s = s;
        assert_eq!(s.entity_count(), 2);
        s.remove_entity(1).unwrap();
        assert_eq!(s.entity_count(), 1);
        assert!(!s.contains_entity(1));
        assert!(s.contains_entity(2));
    }

    #[test]
    fn remove_unknown_entity_returns_error() {
        let mut s = ArchetypeStorage::new();
        assert!(s.remove_entity(999).is_err());
    }

    #[test]
    fn modify_component_updates_value() {
        let mut s = storage_with_entities(&[(10, &[POS, HP])]);
        let old = s.modify_component(10, POS, bytes(99.0)).unwrap();
        let val = s.get_component(10, POS).unwrap();
        let f = f32::from_le_bytes(val.try_into().unwrap());
        assert_eq!(f, 99.0);
    }

    #[test]
    fn modify_component_unknown_entity_returns_error() {
        let mut s = ArchetypeStorage::new();
        assert!(s.modify_component(999, POS, bytes(0.0)).is_err());
    }

    #[test]
    fn get_component_unknown_type_returns_error() {
        let s = storage_with_entities(&[(1, &[POS])]);
        assert!(s.get_component(1, VEL).is_err());
    }

    #[test]
    fn add_component_migrates_archetype() {
        let mut s = storage_with_entities(&[(1, &[POS])]);
        let arch_before = s.archetype_of(1).unwrap();

        s.add_component(1, VEL, bytes(1.0)).unwrap();

        let arch_after = s.archetype_of(1).unwrap();
        assert_ne!(
            arch_before, arch_after,
            "entity must migrate to a new archetype"
        );

        // Component must be accessible in new archetype
        let val = s.get_component(1, VEL).unwrap();
        let f = f32::from_le_bytes(val.try_into().unwrap());
        assert_eq!(f, 1.0);

        // Old component must still be accessible
        let pos = s.get_component(1, POS).unwrap();
        assert!(!pos.is_empty());
    }

    #[test]
    fn add_component_already_present_returns_error() {
        let mut s = storage_with_entities(&[(1, &[POS, VEL])]);
        assert!(s.add_component(1, POS, bytes(0.0)).is_err());
    }

    #[test]
    fn remove_component_migrates_archetype() {
        let mut s = storage_with_entities(&[(1, &[POS, VEL, HP])]);
        let arch_before = s.archetype_of(1).unwrap();

        let removed = s.remove_component(1, VEL).unwrap();
        let f = f32::from_le_bytes(removed.as_slice().try_into().unwrap());
        assert_eq!(f, 1.0_f32); // initial value = eid as f32 = 1.0

        let arch_after = s.archetype_of(1).unwrap();
        assert_ne!(
            arch_before, arch_after,
            "entity must migrate to a new archetype"
        );

        // Removed component must be gone
        assert!(s.get_component(1, VEL).is_err());

        // Remaining components must still be accessible
        assert!(s.get_component(1, POS).is_ok());
        assert!(s.get_component(1, HP).is_ok());
    }

    #[test]
    fn remove_component_not_present_returns_error() {
        let mut s = storage_with_entities(&[(1, &[POS])]);
        assert!(s.remove_component(1, VEL).is_err());
    }

    #[test]
    fn multiple_entities_same_archetype() {
        let mut s = ArchetypeStorage::new();
        for eid in 1..=5u64 {
            let mut c = BTreeMap::new();
            c.insert(POS, bytes(eid as f32));
            c.insert(VEL, bytes(0.0));
            s.add_entity(eid, c).unwrap();
        }
        assert_eq!(s.entity_count(), 5);
        assert_eq!(
            s.archetype_count(),
            1,
            "all entities share the same archetype"
        );
    }

    #[test]
    fn different_component_sets_create_different_archetypes() {
        let s = storage_with_entities(&[(1, &[POS, VEL]), (2, &[POS, HP]), (3, &[POS, VEL, HP])]);
        assert_eq!(s.archetype_count(), 3);
    }

    #[test]
    fn entity_distribution_tracks_per_archetype_count() {
        let s = storage_with_entities(&[(1, &[POS, VEL]), (2, &[POS, VEL]), (3, &[POS, HP])]);
        let dist = s.entity_distribution();
        let total: usize = dist.values().sum();
        assert_eq!(total, 3);
    }

    #[test]
    fn query_returns_entities_with_required_components() {
        use xace_runtime_core::query_engine::vectorized_query::Query;

        let s = storage_with_entities(&[
            (1, &[POS, VEL, HP]), // matches
            (2, &[POS, VEL]),     // matches
            (3, &[POS, HP]),      // does NOT match (no VEL)
        ]);

        let q = Query::all([POS, VEL]);
        let ids = q.entity_ids(&s);
        assert_eq!(ids, vec![1, 2], "only entities with both POS and VEL");
    }

    #[test]
    fn index_remains_consistent_after_swap_remove() {
        let mut s = storage_with_entities(&[(1, &[POS, VEL]), (2, &[POS, VEL]), (3, &[POS, VEL])]);

        // Remove middle entity — triggers swap-remove (entity 3 moves to row 1)
        s.remove_entity(2).unwrap();

        // Both remaining entities must be accessible and unique
        assert!(s.contains_entity(1));
        assert!(s.contains_entity(3));
        assert!(!s.contains_entity(2));

        // Both must return correct component values
        let pos1 = s.get_component(1, POS).unwrap();
        let f1 = f32::from_le_bytes(pos1.try_into().unwrap());
        assert_eq!(f1, 1.0);

        let pos3 = s.get_component(3, POS).unwrap();
        let f3 = f32::from_le_bytes(pos3.try_into().unwrap());
        assert_eq!(f3, 3.0);
    }
}
