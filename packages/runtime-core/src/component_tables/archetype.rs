/*!
# archetype.rs — Single Archetype

One `Archetype` represents the set of entities sharing the same component composition.

## Layout (Structure of Arrays)

```text
Archetype { components: {1, 5, 100} }
├── entity_ids:  [e1, e2, e3, e4]                  ← aligned with column rows
├── columns:
│   ├── TypeId 1 (Position):  [pos1, pos2, pos3, pos4]
│   ├── TypeId 5 (Velocity):  [vel1, vel2, vel3, vel4]
│   └── TypeId 100 (Health):  [hp1,  hp2,  hp3,  hp4]
└── entity_index: BTreeMap<EntityId, row>
                  { e1: 0, e2: 1, e3: 2, e4: 3 }
```

## Row Operations

- **Insert**: `O(log n)` for entity_index lookup + `O(1)` push to each column
- **Remove**: `O(log n)` lookup + `O(1)` swap_remove on each column
- **Modify**: `O(log n)` lookup + `O(1)` column write

## Sorted Iteration (D3 Contract)

`entity_index` is a `BTreeMap<EntityId, row>`. Iterating it yields entities in
EntityID ASC order, satisfying D3 within this archetype. The k-way merge across
archetypes (see `sorted_merge_iterator.rs`) preserves D3 globally.

## Swap Remove

Removing a row uses swap-remove: the last row is moved into the vacated slot,
and the column shrinks by one. This is O(1) for fixed-size columns and keeps
the entity_ids Vec contiguous.

Entity index for the swapped row is updated to point at the new row.
*/

use std::collections::{BTreeMap, BTreeSet};

use crate::component_tables::storage_strategy::{ArchetypeId, EntityId, TypeId};

// ── Component Column ──────────────────────────────────────────────────────────

/// Type-erased column of component data for a single TypeId within an archetype.
///
/// Internally `Vec<Vec<u8>>` — each inner Vec is one component's serialised bytes.
/// The runtime-core layer can replace this with typed columns for max throughput;
/// this generic representation is sufficient for the >5x benchmark gate.
#[derive(Debug, Clone, Default)]
pub struct ComponentColumn {
    pub type_id: TypeId,
    pub rows: Vec<Vec<u8>>,
}

impl ComponentColumn {
    pub fn new(type_id: TypeId) -> Self {
        Self {
            type_id,
            rows: Vec::new(),
        }
    }

    /// Appends one component value, returning its row index.
    pub fn push(&mut self, value: Vec<u8>) -> usize {
        let row = self.rows.len();
        self.rows.push(value);
        row
    }

    /// Reads the component at `row`.
    pub fn get(&self, row: usize) -> Option<&[u8]> {
        self.rows.get(row).map(|v| v.as_slice())
    }

    /// Writes a new value at `row`. Returns the old value if the row exists.
    pub fn set(&mut self, row: usize, value: Vec<u8>) -> Option<Vec<u8>> {
        if row < self.rows.len() {
            let old = std::mem::replace(&mut self.rows[row], value);
            Some(old)
        } else {
            None
        }
    }

    /// Removes the row using swap-remove. Returns the removed value.
    /// The last row is moved into `row`'s position.
    pub fn swap_remove(&mut self, row: usize) -> Option<Vec<u8>> {
        if row < self.rows.len() {
            Some(self.rows.swap_remove(row))
        } else {
            None
        }
    }

    pub fn len(&self) -> usize {
        self.rows.len()
    }
    pub fn is_empty(&self) -> bool {
        self.rows.is_empty()
    }

    /// Iterates rows in column order (NOT EntityID order).
    /// Use Archetype::iter_sorted for EntityID-sorted iteration.
    pub fn iter(&self) -> impl Iterator<Item = (usize, &[u8])> + '_ {
        self.rows.iter().enumerate().map(|(i, v)| (i, v.as_slice()))
    }
}

// ── Archetype ─────────────────────────────────────────────────────────────────

/// One archetype: a collection of entities sharing identical component composition.
#[derive(Debug, Clone)]
pub struct Archetype {
    pub id: ArchetypeId,
    pub component_set: BTreeSet<TypeId>, // canonical sorted set
    pub columns: BTreeMap<TypeId, ComponentColumn>,
    pub entity_ids: Vec<EntityId>, // aligned with column rows
    pub entity_index: BTreeMap<EntityId, usize>, // entity_id → row (sorted)
}

impl Archetype {
    pub fn new(id: ArchetypeId, component_set: BTreeSet<TypeId>) -> Self {
        let mut columns = BTreeMap::new();
        for &type_id in &component_set {
            columns.insert(type_id, ComponentColumn::new(type_id));
        }
        Self {
            id,
            component_set,
            columns,
            entity_ids: Vec::new(),
            entity_index: BTreeMap::new(),
        }
    }

    // ── Entity Insertion ──────────────────────────────────────────────────────

    /// Adds an entity with the given components. Returns the row index.
    ///
    /// # Panics
    /// Panics if `components` does not exactly match `self.component_set`.
    /// Use ArchetypeStorage::add_entity for safe archetype routing.
    pub fn add_entity(
        &mut self,
        entity_id: EntityId,
        components: BTreeMap<TypeId, Vec<u8>>,
    ) -> usize {
        debug_assert_eq!(
            components.keys().copied().collect::<BTreeSet<_>>(),
            self.component_set,
            "Archetype {} expects components {:?}, got {:?}",
            self.id,
            self.component_set,
            components.keys().collect::<Vec<_>>()
        );
        debug_assert!(
            !self.entity_index.contains_key(&entity_id),
            "Entity {} already exists in archetype {}",
            entity_id,
            self.id
        );

        let row = self.entity_ids.len();
        self.entity_ids.push(entity_id);
        self.entity_index.insert(entity_id, row);
        for (type_id, value) in components {
            let col = self
                .columns
                .get_mut(&type_id)
                .expect("column missing — invariant violated");
            col.push(value);
        }
        row
    }

    // ── Entity Removal ────────────────────────────────────────────────────────

    /// Removes an entity from this archetype using swap-remove.
    ///
    /// Returns the removed components as a `BTreeMap<TypeId, Vec<u8>>` so the
    /// caller can re-insert into a different archetype (for add/remove component
    /// migration scenarios).
    ///
    /// Returns None if the entity is not in this archetype.
    pub fn remove_entity(&mut self, entity_id: EntityId) -> Option<BTreeMap<TypeId, Vec<u8>>> {
        let row = self.entity_index.remove(&entity_id)?;
        let last_row = self.entity_ids.len() - 1;

        // Move the swapped-in entity's index entry (if not removing the last row)
        if row != last_row {
            let swapped_entity = self.entity_ids[last_row];
            self.entity_ids.swap_remove(row);
            self.entity_index.insert(swapped_entity, row);
        } else {
            self.entity_ids.pop();
        }

        // Swap-remove each column at the same row
        let mut removed = BTreeMap::new();
        for (&type_id, col) in self.columns.iter_mut() {
            if let Some(val) = col.swap_remove(row) {
                removed.insert(type_id, val);
            }
        }
        Some(removed)
    }

    // ── Component Access ──────────────────────────────────────────────────────

    /// Reads a component for an entity in this archetype.
    pub fn get_component(&self, entity_id: EntityId, type_id: TypeId) -> Option<&[u8]> {
        let row = *self.entity_index.get(&entity_id)?;
        self.columns.get(&type_id)?.get(row)
    }

    /// Writes a component for an entity in this archetype.
    /// Returns the old value, or None if the entity or column does not exist.
    pub fn set_component(
        &mut self,
        entity_id: EntityId,
        type_id: TypeId,
        value: Vec<u8>,
    ) -> Option<Vec<u8>> {
        let row = *self.entity_index.get(&entity_id)?;
        self.columns.get_mut(&type_id)?.set(row, value)
    }

    /// Returns all components for an entity as a BTreeMap.
    pub fn get_entity_components(&self, entity_id: EntityId) -> Option<BTreeMap<TypeId, Vec<u8>>> {
        let row = *self.entity_index.get(&entity_id)?;
        let mut bundle = BTreeMap::new();
        for (&type_id, col) in &self.columns {
            if let Some(bytes) = col.get(row) {
                bundle.insert(type_id, bytes.to_vec());
            }
        }
        Some(bundle)
    }

    // ── Iteration ─────────────────────────────────────────────────────────────

    /// Iterates entities in EntityID ASC order (D3 compliance within this archetype).
    /// Yields (EntityId, row_index).
    pub fn iter_sorted(&self) -> impl Iterator<Item = (EntityId, usize)> + '_ {
        self.entity_index.iter().map(|(&e, &r)| (e, r))
    }

    /// Iterates rows in column order (NOT EntityID-sorted).
    /// Faster but breaks D3 — use only when caller will re-sort externally.
    pub fn iter_unsorted(&self) -> impl Iterator<Item = (EntityId, usize)> + '_ {
        self.entity_ids.iter().enumerate().map(|(r, &e)| (e, r))
    }

    /// Returns the entity ID at a specific row.
    pub fn entity_at(&self, row: usize) -> Option<EntityId> {
        self.entity_ids.get(row).copied()
    }

    pub fn entity_count(&self) -> usize {
        self.entity_ids.len()
    }
    pub fn is_empty(&self) -> bool {
        self.entity_ids.is_empty()
    }

    /// Returns true if this archetype contains the given entity.
    pub fn contains(&self, entity_id: EntityId) -> bool {
        self.entity_index.contains_key(&entity_id)
    }

    /// Returns true if this archetype has all of the requested component types.
    /// Used by query_engine to filter archetypes during query matching.
    pub fn matches_query(&self, required: &BTreeSet<TypeId>) -> bool {
        required.is_subset(&self.component_set)
    }
}

// ── Component Bundle (for queries) ────────────────────────────────────────────

/// Borrowed snapshot of one entity's components within an archetype.
/// Used by `vectorized_query.rs` to expose tuple-style component access.
#[derive(Debug)]
pub struct ComponentBundle<'a> {
    pub entity_id: EntityId,
    pub row: usize,
    pub archetype: &'a Archetype,
}

impl<'a> ComponentBundle<'a> {
    pub fn get(&self, type_id: TypeId) -> Option<&[u8]> {
        self.archetype.columns.get(&type_id)?.get(self.row)
    }
}
