/*!
# archetype_index.rs — Global Entity Location Index

Maps `EntityId → ArchetypeLocation { archetype_id, row }`.

This is the entry point for any entity-based operation:
    "Where in archetype storage is entity 42?"
        → archetype_index.lookup(42)
        → ArchetypeLocation { archetype_id: 7, row: 12 }

## Why BTreeMap (not HashMap)?

D3 requires entity iteration in EntityID ASC order. BTreeMap iteration is
naturally sorted; HashMap iteration is unordered.

Lookups are O(log n) vs HashMap's O(1) — but for game entity counts (1K–100K),
the constant factor difference is negligible (~50ns vs ~20ns per lookup).
Determinism trumps the micro-benchmark.

## Updates During Swap-Remove

When `Archetype::remove_entity` swap-removes a row, the entity that was at
the last row is now at the removed row's index. `ArchetypeStorage` must call
`update_location` for that swapped entity to keep the index consistent.
*/

use std::collections::BTreeMap;

use crate::component_tables::storage_strategy::{ArchetypeId, EntityId};


// ── Archetype Location ────────────────────────────────────────────────────────

/// Where an entity lives in archetype storage.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ArchetypeLocation {
    pub archetype_id: ArchetypeId,
    pub row:          usize,
}

impl ArchetypeLocation {
    pub fn new(archetype_id: ArchetypeId, row: usize) -> Self {
        Self { archetype_id, row }
    }
}


// ── Archetype Index ───────────────────────────────────────────────────────────

#[derive(Debug, Default, Clone)]
pub struct ArchetypeIndex {
    inner: BTreeMap<EntityId, ArchetypeLocation>,
}

impl ArchetypeIndex {
    pub fn new() -> Self {
        Self { inner: BTreeMap::new() }
    }

    pub fn with_capacity(_cap: usize) -> Self {
        // BTreeMap has no with_capacity; ignore the hint for API symmetry.
        Self::new()
    }

    // ── CRUD ──────────────────────────────────────────────────────────────────

    /// Inserts or replaces an entity's location.
    /// Returns the previous location if the entity already existed.
    pub fn insert(
        &mut self,
        entity_id: EntityId,
        location:  ArchetypeLocation,
    ) -> Option<ArchetypeLocation> {
        self.inner.insert(entity_id, location)
    }

    /// Removes an entity's location and returns it.
    pub fn remove(&mut self, entity_id: EntityId) -> Option<ArchetypeLocation> {
        self.inner.remove(&entity_id)
    }

    /// Updates an existing entity's location.
    /// Used when swap-remove relocates the swapped entity to a different row.
    pub fn update_location(
        &mut self,
        entity_id:    EntityId,
        new_location: ArchetypeLocation,
    ) {
        self.inner.insert(entity_id, new_location);
    }

    pub fn lookup(&self, entity_id: EntityId) -> Option<ArchetypeLocation> {
        self.inner.get(&entity_id).copied()
    }

    pub fn contains(&self, entity_id: EntityId) -> bool {
        self.inner.contains_key(&entity_id)
    }

    pub fn len(&self) -> usize { self.inner.len() }
    pub fn is_empty(&self) -> bool { self.inner.is_empty() }

    // ── Iteration (D3-compliant) ──────────────────────────────────────────────

    /// Iterates all entities in EntityID ASC order.
    pub fn iter_sorted(&self) -> impl Iterator<Item = (EntityId, ArchetypeLocation)> + '_ {
        self.inner.iter().map(|(&e, &l)| (e, l))
    }

    /// Iterates only entities within a specific archetype.
    /// Order is EntityID ASC (since underlying iteration is sorted).
    pub fn iter_archetype(
        &self,
        archetype_id: ArchetypeId,
    ) -> impl Iterator<Item = (EntityId, ArchetypeLocation)> + '_ {
        self.inner.iter()
            .filter(move |(_, loc)| loc.archetype_id == archetype_id)
            .map(|(&e, &l)| (e, l))
    }

    /// Iterates entities within a range of EntityIDs (e.g. for delta sync).
    pub fn iter_range<R>(
        &self,
        range: R,
    ) -> impl Iterator<Item = (EntityId, ArchetypeLocation)> + '_
    where
        R: std::ops::RangeBounds<EntityId>,
    {
        self.inner.range(range).map(|(&e, &l)| (e, l))
    }

    /// Returns the smallest EntityID in the index, if any.
    pub fn min_entity(&self) -> Option<EntityId> {
        self.inner.keys().next().copied()
    }

    /// Returns the largest EntityID in the index, if any.
    pub fn max_entity(&self) -> Option<EntityId> {
        self.inner.keys().next_back().copied()
    }

    // ── Bulk Operations ───────────────────────────────────────────────────────

    /// Returns the count of entities in each archetype.
    /// Used for telemetry: `entities_per_archetype = {arch_id → count}`.
    pub fn count_by_archetype(&self) -> BTreeMap<ArchetypeId, usize> {
        let mut counts = BTreeMap::new();
        for (_, loc) in &self.inner {
            *counts.entry(loc.archetype_id).or_insert(0) += 1;
        }
        counts
    }

    /// Returns all entities in a given archetype, in EntityID ASC order.
    pub fn entities_in_archetype(&self, archetype_id: ArchetypeId) -> Vec<EntityId> {
        self.iter_archetype(archetype_id).map(|(e, _)| e).collect()
    }

    pub fn clear(&mut self) { self.inner.clear(); }
}