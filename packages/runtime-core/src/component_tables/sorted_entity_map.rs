//! # Sorted Entity Map
//!
//! A deterministic sorted map guaranteeing EntityID-ordered iteration.
//! This is the core data structure that enforces Determinism Rule D3.
//!
//! ## Why This Exists
//! Every component table must iterate entities in EntityID ascending
//! order (D3). Using a standard HashMap would produce random iteration
//! order across runs, breaking determinism. BTreeMap guarantees
//! ascending key order automatically — no sorting needed at query time.
//!
//! ## Design
//! SortedEntityMap<V> is a thin, typed wrapper around BTreeMap<EntityID, V>.
//! It provides a domain-specific API that makes D3 compliance explicit
//! and prevents accidental use of non-deterministic data structures.
//!
//! ## Serialization
//! BTreeMap serializes with stable key ordering (D11). Identical
//! component data always produces identical serialized bytes.

use std::collections::BTreeMap;
use xace_core::entity_id::EntityID;

// ── Sorted Entity Map ─────────────────────────────────────────────────────────

/// A deterministic map from EntityID to component data.
///
/// Wraps BTreeMap<EntityID, V> to guarantee EntityID-ascending iteration
/// order (D3) across all operations. This is the storage primitive
/// used by every ComponentTable in the runtime.
///
/// ## Iteration Order Guarantee
/// All iterators produced by this type yield entries in EntityID
/// ascending order. This guarantee is unconditional — it holds
/// regardless of insertion order, deletion order, or update order.
pub struct SortedEntityMap<V> {
    inner: BTreeMap<EntityID, V>,
}

impl<V> SortedEntityMap<V> {
    /// Creates a new empty SortedEntityMap.
    pub fn new() -> Self {
        Self {
            inner: BTreeMap::new(),
        }
    }

    /// Inserts or replaces a value for the given EntityID.
    /// Returns the previous value if one existed.
    pub fn insert(&mut self, entity_id: EntityID, value: V) -> Option<V> {
        self.inner.insert(entity_id, value)
    }

    /// Removes the value for the given EntityID.
    /// Returns the removed value if it existed.
    pub fn remove(&mut self, entity_id: EntityID) -> Option<V> {
        self.inner.remove(&entity_id)
    }

    /// Returns a reference to the value for the given EntityID.
    pub fn get(&self, entity_id: EntityID) -> Option<&V> {
        self.inner.get(&entity_id)
    }

    /// Returns a mutable reference to the value for the given EntityID.
    pub fn get_mut(&mut self, entity_id: EntityID) -> Option<&mut V> {
        self.inner.get_mut(&entity_id)
    }

    /// Returns true if the given EntityID has a value in this map.
    pub fn contains(&self, entity_id: EntityID) -> bool {
        self.inner.contains_key(&entity_id)
    }

    /// Returns the number of entries in this map.
    pub fn len(&self) -> usize {
        self.inner.len()
    }

    /// Returns true if this map has no entries.
    pub fn is_empty(&self) -> bool {
        self.inner.is_empty()
    }

    /// Removes all entries from this map.
    pub fn clear(&mut self) {
        self.inner.clear();
    }

    /// Returns all EntityIDs in ascending order (D3).
    /// BTreeMap iteration is always ascending by key.
    pub fn entity_ids(&self) -> Vec<EntityID> {
        self.inner.keys().copied().collect()
    }

    /// Returns an iterator over (EntityID, &V) pairs in EntityID ASC order.
    pub fn iter(&self) -> impl Iterator<Item = (EntityID, &V)> {
        self.inner.iter().map(|(&id, v)| (id, v))
    }

    /// Returns an iterator over (EntityID, &mut V) pairs in EntityID ASC order.
    pub fn iter_mut(&mut self) -> impl Iterator<Item = (EntityID, &mut V)> {
        self.inner.iter_mut().map(|(&id, v)| (id, v))
    }

    /// Returns an iterator over EntityIDs only, in ascending order (D3).
    pub fn keys(&self) -> impl Iterator<Item = EntityID> + '_ {
        self.inner.keys().copied()
    }

    /// Returns an iterator over values only, in EntityID ascending order.
    pub fn values(&self) -> impl Iterator<Item = &V> {
        self.inner.values()
    }

    /// Returns a mutable iterator over values only.
    pub fn values_mut(&mut self) -> impl Iterator<Item = &mut V> {
        self.inner.values_mut()
    }

    /// Returns a reference to the underlying BTreeMap.
    /// Used by SnapshotEngine for serialization.
    pub fn as_btree(&self) -> &BTreeMap<EntityID, V> {
        &self.inner
    }

    /// Consumes this map and returns the underlying BTreeMap.
    pub fn into_btree(self) -> BTreeMap<EntityID, V> {
        self.inner
    }

    /// Creates a SortedEntityMap from a BTreeMap.
    /// Used during snapshot restore.
    pub fn from_btree(map: BTreeMap<EntityID, V>) -> Self {
        Self { inner: map }
    }

    /// Returns the entry for an EntityID for in-place mutation.
    pub fn entry(
        &mut self,
        entity_id: EntityID,
    ) -> std::collections::btree_map::Entry<'_, EntityID, V> {
        self.inner.entry(entity_id)
    }
}

impl<V: Clone> SortedEntityMap<V> {
    /// Returns a clone of the entire map.
    /// Used by SnapshotEngine for deep copy snapshots.
    pub fn deep_clone(&self) -> Self {
        Self {
            inner: self.inner.clone(),
        }
    }
}

impl<V: PartialEq> SortedEntityMap<V> {
    /// Returns true if two maps have identical content.
    /// Used by DeterminismGuard for world hash verification.
    pub fn is_equal_to(&self, other: &Self) -> bool {
        self.inner == other.inner
    }
}

impl<V> Default for SortedEntityMap<V> {
    fn default() -> Self {
        Self::new()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn insert_and_get() {
        let mut map: SortedEntityMap<String> = SortedEntityMap::new();
        map.insert(1, "entity_one".into());
        assert_eq!(map.get(1), Some(&"entity_one".to_string()));
        assert_eq!(map.get(2), None);
    }

    #[test]
    fn iteration_is_always_ascending() {
        let mut map: SortedEntityMap<i32> = SortedEntityMap::new();
        map.insert(5, 50);
        map.insert(1, 10);
        map.insert(3, 30);
        map.insert(2, 20);
        map.insert(4, 40);
        let ids: Vec<EntityID> = map.keys().collect();
        assert_eq!(ids, vec![1, 2, 3, 4, 5]);
    }

    #[test]
    fn entity_ids_sorted_ascending() {
        let mut map: SortedEntityMap<u32> = SortedEntityMap::new();
        map.insert(10, 1);
        map.insert(2, 2);
        map.insert(7, 3);
        let ids = map.entity_ids();
        assert_eq!(ids, vec![2, 7, 10]);
    }

    #[test]
    fn remove_works_correctly() {
        let mut map: SortedEntityMap<i32> = SortedEntityMap::new();
        map.insert(1, 100);
        map.insert(2, 200);
        let removed = map.remove(1);
        assert_eq!(removed, Some(100));
        assert!(!map.contains(1));
        assert_eq!(map.len(), 1);
    }

    #[test]
    fn remove_nonexistent_returns_none() {
        let mut map: SortedEntityMap<i32> = SortedEntityMap::new();
        assert_eq!(map.remove(999), None);
    }

    #[test]
    fn contains_correct() {
        let mut map: SortedEntityMap<i32> = SortedEntityMap::new();
        map.insert(1, 42);
        assert!(map.contains(1));
        assert!(!map.contains(2));
    }

    #[test]
    fn len_and_is_empty() {
        let mut map: SortedEntityMap<i32> = SortedEntityMap::new();
        assert!(map.is_empty());
        assert_eq!(map.len(), 0);
        map.insert(1, 1);
        assert!(!map.is_empty());
        assert_eq!(map.len(), 1);
    }

    #[test]
    fn clear_empties_map() {
        let mut map: SortedEntityMap<i32> = SortedEntityMap::new();
        map.insert(1, 1);
        map.insert(2, 2);
        map.clear();
        assert!(map.is_empty());
    }

    #[test]
    fn iter_yields_ascending_order() {
        let mut map: SortedEntityMap<i32> = SortedEntityMap::new();
        map.insert(3, 30);
        map.insert(1, 10);
        map.insert(2, 20);
        let pairs: Vec<(EntityID, i32)> = map.iter().map(|(id, v)| (id, *v)).collect();
        assert_eq!(pairs, vec![(1, 10), (2, 20), (3, 30)]);
    }

    #[test]
    fn get_mut_modifies_value() {
        let mut map: SortedEntityMap<i32> = SortedEntityMap::new();
        map.insert(1, 10);
        if let Some(v) = map.get_mut(1) {
            *v = 99;
        }
        assert_eq!(map.get(1), Some(&99));
    }

    #[test]
    fn deep_clone_is_independent() {
        let mut map: SortedEntityMap<i32> = SortedEntityMap::new();
        map.insert(1, 100);
        let mut cloned = map.deep_clone();
        cloned.insert(1, 999);
        assert_eq!(map.get(1), Some(&100)); // original unchanged
        assert_eq!(cloned.get(1), Some(&999));
    }

    #[test]
    fn is_equal_to_identical_maps() {
        let mut a: SortedEntityMap<i32> = SortedEntityMap::new();
        let mut b: SortedEntityMap<i32> = SortedEntityMap::new();
        a.insert(1, 10);
        a.insert(2, 20);
        b.insert(1, 10);
        b.insert(2, 20);
        assert!(a.is_equal_to(&b));
    }

    #[test]
    fn is_equal_to_different_maps() {
        let mut a: SortedEntityMap<i32> = SortedEntityMap::new();
        let mut b: SortedEntityMap<i32> = SortedEntityMap::new();
        a.insert(1, 10);
        b.insert(1, 99);
        assert!(!a.is_equal_to(&b));
    }

    #[test]
    fn from_btree_preserves_order() {
        use std::collections::BTreeMap;
        let mut btree = BTreeMap::new();
        btree.insert(5u64, "five");
        btree.insert(1u64, "one");
        btree.insert(3u64, "three");
        let map: SortedEntityMap<&str> = SortedEntityMap::from_btree(btree);
        let ids = map.entity_ids();
        assert_eq!(ids, vec![1, 3, 5]);
    }

    #[test]
    fn determinism_same_insertions_same_iteration() {
        let mut map1: SortedEntityMap<i32> = SortedEntityMap::new();
        let mut map2: SortedEntityMap<i32> = SortedEntityMap::new();
        for i in [5, 2, 8, 1, 4] {
            map1.insert(i, i as i32 * 10);
            map2.insert(i, i as i32 * 10);
        }
        let ids1: Vec<EntityID> = map1.keys().collect();
        let ids2: Vec<EntityID> = map2.keys().collect();
        assert_eq!(ids1, ids2);
    }
}
