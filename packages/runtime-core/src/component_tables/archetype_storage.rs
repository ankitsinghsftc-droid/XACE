/*!
# archetype_storage.rs — Archetype-Based Component Storage

The main entity-component storage backend for archetype mode.

## Public API

```rust
let mut storage = ArchetypeStorage::new();

// Insert a new entity with components
storage.add_entity(entity_id, components_map);

// Read a component
let bytes = storage.get_component(entity_id, COMP_POSITION_ID);

// Modify a component in place
storage.modify_component(entity_id, COMP_POSITION_ID, new_bytes);

// Add or remove components — entity migrates to a different archetype
storage.add_component(entity_id, COMP_VELOCITY_ID, vel_bytes);
storage.remove_component(entity_id, COMP_HEALTH_ID);

// Destroy an entity
storage.remove_entity(entity_id);

// D3-compliant iteration across all archetypes
for (entity_id, bundle) in storage.iter_sorted() {
    let position = bundle.get(COMP_POSITION_ID);
    // ...
}
```

## Archetype Migration

When `add_component` or `remove_component` changes an entity's component set:
1. Look up current archetype + row
2. Remove entity from old archetype (swap-remove returns all current components)
3. Compute new component set (insert or remove the target type_id)
4. Find or create the destination archetype
5. Insert entity into destination archetype with the merged components
6. Update ArchetypeIndex with the new location

This is O(C log A) where C = component count for that entity, A = archetype count.
Migration is the price paid for cache-friendly iteration. In practice, structural
changes (add/remove components) are rare compared to in-place modifies — most
ticks involve only `set_component` operations which are O(log A) and never migrate.

## D-Rule Compliance

D3 (sorted entity iteration):  iter_sorted() yields EntityID ASC via k-way merge.
D4 (mutation order):           ArchetypeStorage is called by Mutation Gate only.
D11 (stable serialization):    columns iterated in TypeId ASC, entities in EntityID ASC.
*/

use std::collections::{BTreeMap, BTreeSet};

use crate::component_tables::archetype::{Archetype, ComponentBundle};
use crate::component_tables::archetype_index::{ArchetypeIndex, ArchetypeLocation};
use crate::component_tables::storage_strategy::{ArchetypeId, EntityId, TypeId};

// ── Storage Errors ────────────────────────────────────────────────────────────

#[derive(Debug, thiserror::Error)]
pub enum ArchetypeStorageError {
    #[error("entity {0} not found")]
    EntityNotFound(EntityId),

    #[error("entity {0} already exists")]
    EntityAlreadyExists(EntityId),

    #[error("entity {entity} does not have component type {type_id}")]
    ComponentNotFound { entity: EntityId, type_id: TypeId },

    #[error("entity {entity} already has component type {type_id}")]
    ComponentAlreadyExists { entity: EntityId, type_id: TypeId },

    #[error("archetype id {0} not found")]
    ArchetypeNotFound(ArchetypeId),
}

pub type Result<T> = std::result::Result<T, ArchetypeStorageError>;

// ── Archetype Storage ─────────────────────────────────────────────────────────

#[derive(Debug, Default)]
pub struct ArchetypeStorage {
    /// All archetypes keyed by their component set.
    archetypes_by_set: BTreeMap<BTreeSet<TypeId>, ArchetypeId>,

    /// All archetypes keyed by ID for fast lookup.
    archetypes: BTreeMap<ArchetypeId, Archetype>,

    /// Global EntityID → location index.
    index: ArchetypeIndex,

    /// Monotonically increasing archetype ID. Deterministic across runs
    /// given identical entity creation sequence.
    next_archetype_id: ArchetypeId,
}

impl ArchetypeStorage {
    pub fn new() -> Self {
        Self {
            archetypes_by_set: BTreeMap::new(),
            archetypes: BTreeMap::new(),
            index: ArchetypeIndex::new(),
            next_archetype_id: 1, // 0 reserved for "no archetype"
        }
    }

    pub fn with_capacity_hint(expected_max_entities: usize) -> Self {
        let mut s = Self::new();
        let _ = s.index = ArchetypeIndex::with_capacity(expected_max_entities);
        s
    }

    // ── Entity Lifecycle ──────────────────────────────────────────────────────

    /// Inserts a new entity with the given components.
    pub fn add_entity(
        &mut self,
        entity_id: EntityId,
        components: BTreeMap<TypeId, Vec<u8>>,
    ) -> Result<()> {
        if self.index.contains(entity_id) {
            return Err(ArchetypeStorageError::EntityAlreadyExists(entity_id));
        }

        let component_set: BTreeSet<TypeId> = components.keys().copied().collect();
        let archetype_id = self.get_or_create_archetype(component_set);

        let archetype = self
            .archetypes
            .get_mut(&archetype_id)
            .expect("archetype just created/looked up");
        let row = archetype.add_entity(entity_id, components);

        self.index
            .insert(entity_id, ArchetypeLocation::new(archetype_id, row));
        Ok(())
    }

    /// Removes an entity entirely from storage.
    pub fn remove_entity(&mut self, entity_id: EntityId) -> Result<()> {
        let location = self
            .index
            .remove(entity_id)
            .ok_or(ArchetypeStorageError::EntityNotFound(entity_id))?;

        self.swap_remove_and_reindex(entity_id, location)?;
        Ok(())
    }

    // ── Component Lifecycle ───────────────────────────────────────────────────

    /// Reads a component value for an entity.
    pub fn get_component(&self, entity_id: EntityId, type_id: TypeId) -> Result<&[u8]> {
        let loc = self
            .index
            .lookup(entity_id)
            .ok_or(ArchetypeStorageError::EntityNotFound(entity_id))?;
        let archetype = self
            .archetypes
            .get(&loc.archetype_id)
            .ok_or(ArchetypeStorageError::ArchetypeNotFound(loc.archetype_id))?;
        archetype
            .columns
            .get(&type_id)
            .and_then(|col| col.get(loc.row))
            .ok_or(ArchetypeStorageError::ComponentNotFound {
                entity: entity_id,
                type_id,
            })
    }

    /// Modifies a component value in place.
    /// Returns the previous value.
    pub fn modify_component(
        &mut self,
        entity_id: EntityId,
        type_id: TypeId,
        new_value: Vec<u8>,
    ) -> Result<Vec<u8>> {
        let loc = self
            .index
            .lookup(entity_id)
            .ok_or(ArchetypeStorageError::EntityNotFound(entity_id))?;
        let archetype = self
            .archetypes
            .get_mut(&loc.archetype_id)
            .ok_or(ArchetypeStorageError::ArchetypeNotFound(loc.archetype_id))?;
        archetype
            .set_component(entity_id, type_id, new_value)
            .ok_or(ArchetypeStorageError::ComponentNotFound {
                entity: entity_id,
                type_id,
            })
    }

    /// Adds a component to an entity. Migrates the entity to a new archetype.
    pub fn add_component(
        &mut self,
        entity_id: EntityId,
        type_id: TypeId,
        value: Vec<u8>,
    ) -> Result<()> {
        let loc = self
            .index
            .lookup(entity_id)
            .ok_or(ArchetypeStorageError::EntityNotFound(entity_id))?;

        // Check: does the entity already have this component?
        {
            let archetype = self
                .archetypes
                .get(&loc.archetype_id)
                .ok_or(ArchetypeStorageError::ArchetypeNotFound(loc.archetype_id))?;
            if archetype.component_set.contains(&type_id) {
                return Err(ArchetypeStorageError::ComponentAlreadyExists {
                    entity: entity_id,
                    type_id,
                });
            }
        }

        // Migrate to new archetype
        self.migrate_with_component_change(entity_id, loc, |components| {
            components.insert(type_id, value);
        })
    }

    /// Removes a component from an entity. Migrates the entity to a new archetype.
    pub fn remove_component(&mut self, entity_id: EntityId, type_id: TypeId) -> Result<Vec<u8>> {
        let loc = self
            .index
            .lookup(entity_id)
            .ok_or(ArchetypeStorageError::EntityNotFound(entity_id))?;

        // Verify the entity has this component
        {
            let archetype = self
                .archetypes
                .get(&loc.archetype_id)
                .ok_or(ArchetypeStorageError::ArchetypeNotFound(loc.archetype_id))?;
            if !archetype.component_set.contains(&type_id) {
                return Err(ArchetypeStorageError::ComponentNotFound {
                    entity: entity_id,
                    type_id,
                });
            }
        }

        // Extract the removed component value during migration
        let mut removed_value: Option<Vec<u8>> = None;
        self.migrate_with_component_change(entity_id, loc, |components| {
            removed_value = components.remove(&type_id);
        })?;

        Ok(removed_value.expect("component existence verified above"))
    }

    // ── Iteration ─────────────────────────────────────────────────────────────

    /// Iterates ALL entities in EntityID ASC order across all archetypes.
    /// This is the D3-compliant iteration.
    ///
    /// Uses the global index for sorted order; lookup back to archetype for components.
    pub fn iter_sorted(&self) -> impl Iterator<Item = (EntityId, ComponentBundle<'_>)> + '_ {
        self.index
            .iter_sorted()
            .filter_map(move |(entity_id, loc)| {
                self.archetypes.get(&loc.archetype_id).map(|arch| {
                    (
                        entity_id,
                        ComponentBundle {
                            entity_id,
                            row: loc.row,
                            archetype: arch,
                        },
                    )
                })
            })
    }

    /// Iterates entities matching the required component set.
    /// Result is in EntityID ASC order.
    pub fn query<'a>(
        &'a self,
        required: &'a BTreeSet<TypeId>,
    ) -> impl Iterator<Item = (EntityId, ComponentBundle<'a>)> + 'a {
        // Filter to archetypes containing all required components
        let matching_archetype_ids: BTreeSet<ArchetypeId> = self
            .archetypes
            .iter()
            .filter(|(_, a)| a.matches_query(required))
            .map(|(&id, _)| id)
            .collect();

        self.index
            .iter_sorted()
            .filter_map(move |(entity_id, loc)| {
                if !matching_archetype_ids.contains(&loc.archetype_id) {
                    return None;
                }
                self.archetypes.get(&loc.archetype_id).map(|arch| {
                    (
                        entity_id,
                        ComponentBundle {
                            entity_id,
                            row: loc.row,
                            archetype: arch,
                        },
                    )
                })
            })
    }

    /// Returns the archetype an entity belongs to.
    pub fn archetype_of(&self, entity_id: EntityId) -> Option<ArchetypeId> {
        self.index.lookup(entity_id).map(|l| l.archetype_id)
    }

    /// Returns access to an archetype by ID.
    pub fn archetype(&self, archetype_id: ArchetypeId) -> Option<&Archetype> {
        self.archetypes.get(&archetype_id)
    }

    /// Iterates all archetypes — primarily for the sorted_merge_iterator
    /// and benchmarks.
    pub fn iter_archetypes(&self) -> impl Iterator<Item = &Archetype> + '_ {
        self.archetypes.values()
    }

    // ── Diagnostics ───────────────────────────────────────────────────────────

    pub fn entity_count(&self) -> usize {
        self.index.len()
    }
    pub fn archetype_count(&self) -> usize {
        self.archetypes.len()
    }
    pub fn contains_entity(&self, entity_id: EntityId) -> bool {
        self.index.contains(entity_id)
    }

    pub fn entity_distribution(&self) -> BTreeMap<ArchetypeId, usize> {
        self.index.count_by_archetype()
    }

    // ── Internal: Archetype Lookup/Creation ───────────────────────────────────

    fn get_or_create_archetype(&mut self, component_set: BTreeSet<TypeId>) -> ArchetypeId {
        if let Some(&id) = self.archetypes_by_set.get(&component_set) {
            return id;
        }
        let id = self.next_archetype_id;
        self.next_archetype_id += 1;
        let arch = Archetype::new(id, component_set.clone());
        self.archetypes.insert(id, arch);
        self.archetypes_by_set.insert(component_set, id);
        id
    }

    // ── Internal: Entity Migration ────────────────────────────────────────────

    /// Migrates an entity between archetypes by mutating its component bundle.
    /// The closure receives the entity's components and mutates them in place
    /// (adding or removing entries). The destination archetype is determined
    /// from the mutated component set.
    fn migrate_with_component_change<F>(
        &mut self,
        entity_id: EntityId,
        loc: ArchetypeLocation,
        mutator: F,
    ) -> Result<()>
    where
        F: FnOnce(&mut BTreeMap<TypeId, Vec<u8>>),
    {
        // 1. Remove from current archetype, capturing all components
        let mut components = {
            let arch = self
                .archetypes
                .get_mut(&loc.archetype_id)
                .ok_or(ArchetypeStorageError::ArchetypeNotFound(loc.archetype_id))?;
            let removed = arch
                .remove_entity(entity_id)
                .ok_or(ArchetypeStorageError::EntityNotFound(entity_id))?;

            // 1b. If swap-remove relocated another entity, update its index entry
            self.fix_swap_index(loc)?;
            removed
        };

        // 2. Apply the mutation (add or remove a component)
        mutator(&mut components);

        // 3. Find / create destination archetype and insert
        let new_set: BTreeSet<TypeId> = components.keys().copied().collect();
        let new_arch_id = self.get_or_create_archetype(new_set);
        let arch = self
            .archetypes
            .get_mut(&new_arch_id)
            .expect("destination archetype just created");
        let new_row = arch.add_entity(entity_id, components);

        // 4. Update the index
        self.index
            .update_location(entity_id, ArchetypeLocation::new(new_arch_id, new_row));
        Ok(())
    }

    /// After a swap-remove, the entity that was at the last row is now at `loc.row`.
    /// Update the global index for that entity.
    fn fix_swap_index(&mut self, loc: ArchetypeLocation) -> Result<()> {
        let archetype = self
            .archetypes
            .get(&loc.archetype_id)
            .ok_or(ArchetypeStorageError::ArchetypeNotFound(loc.archetype_id))?;
        // After swap_remove, the entity now at loc.row is the one that was relocated.
        // (entity_ids[loc.row] is the swapped entity.) Update its index entry.
        if let Some(swapped_entity) = archetype.entity_at(loc.row) {
            self.index.update_location(
                swapped_entity,
                ArchetypeLocation::new(loc.archetype_id, loc.row),
            );
        }
        Ok(())
    }

    /// Full swap-remove + reindex for entity removal.
    fn swap_remove_and_reindex(
        &mut self,
        entity_id: EntityId,
        loc: ArchetypeLocation,
    ) -> Result<()> {
        let arch = self
            .archetypes
            .get_mut(&loc.archetype_id)
            .ok_or(ArchetypeStorageError::ArchetypeNotFound(loc.archetype_id))?;
        arch.remove_entity(entity_id)
            .ok_or(ArchetypeStorageError::EntityNotFound(entity_id))?;
        // Reindex the swapped entity (if any)
        self.fix_swap_index(loc)?;
        Ok(())
    }
}
