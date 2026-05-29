// ============================================================================
// packages/runtime-core/src/query_engine/vectorized_query.rs
// ============================================================================
/*!
# vectorized_query.rs — Archetype-Aware Component Query

Builds queries that filter archetypes by required component sets, then iterate
matching entities via the sorted-merge iterator.

## Why "Vectorized"

In BTreeMap storage, querying "all entities with Position + Velocity" requires
checking each entity individually for both components: O(N) entities × O(log T)
per component lookup = O(N log T).

In archetype storage, the query first filters archetypes by component set:
O(A) archetypes vs O(N) entities, where A << N. Only matching archetypes are
iterated. Within an archetype, ALL entities have ALL queried components, so
no per-entity check is needed.

For "all entities with Position": archetype iterates the Position column linearly.
This is the cache-friendly vectorized path.
*/

use std::collections::BTreeSet;

use crate::component_tables::archetype::ComponentBundle;
use crate::component_tables::archetype_storage::ArchetypeStorage;
use crate::component_tables::storage_strategy::{ArchetypeId, EntityId, TypeId};
use crate::query_engine::sorted_merge_iterator::SortedMergeIterator;

// ── Query Builder ─────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Default)]
pub struct Query {
    required: BTreeSet<TypeId>,
    excluded: BTreeSet<TypeId>,
}

impl Query {
    pub fn new() -> Self {
        Self::default()
    }

    /// Entities matching this query must have ALL of these component types.
    pub fn with(mut self, type_id: TypeId) -> Self {
        self.required.insert(type_id);
        self
    }

    pub fn with_many(mut self, type_ids: impl IntoIterator<Item = TypeId>) -> Self {
        self.required.extend(type_ids);
        self
    }

    /// Entities matching this query must NOT have any of these component types.
    pub fn without(mut self, type_id: TypeId) -> Self {
        self.excluded.insert(type_id);
        self
    }

    pub fn without_many(mut self, type_ids: impl IntoIterator<Item = TypeId>) -> Self {
        self.excluded.extend(type_ids);
        self
    }

    /// Resolves matching archetype IDs from the storage.
    pub fn matching_archetypes(&self, storage: &ArchetypeStorage) -> BTreeSet<ArchetypeId> {
        storage
            .iter_archetypes()
            .filter(|a| {
                a.matches_query(&self.required)
                    && self.excluded.iter().all(|t| !a.component_set.contains(t))
            })
            .map(|a| a.id)
            .collect()
    }

    /// Executes the query against storage, returning a sorted iterator
    /// over matching entities. D3-compliant.
    pub fn execute<'a>(&self, storage: &'a ArchetypeStorage) -> SortedMergeIterator<'a> {
        let archetype_ids = self.matching_archetypes(storage);
        SortedMergeIterator::new_filtered(storage, &archetype_ids)
    }

    /// Counts entities matching this query (without iterating components).
    pub fn count(&self, storage: &ArchetypeStorage) -> usize {
        let matching = self.matching_archetypes(storage);
        storage
            .iter_archetypes()
            .filter(|a| matching.contains(&a.id))
            .map(|a| a.entity_count())
            .sum()
    }

    /// Convenience: collects all matching entity IDs in sorted order.
    pub fn entity_ids(&self, storage: &ArchetypeStorage) -> Vec<EntityId> {
        self.execute(storage).map(|(e, _)| e).collect()
    }
}

// ── Convenience Constructors ──────────────────────────────────────────────────

impl Query {
    /// `Query::all([1, 5, 100])` — all components must be present.
    pub fn all(type_ids: impl IntoIterator<Item = TypeId>) -> Self {
        Self::new().with_many(type_ids)
    }

    /// `Query::any_with(5)` — one required component.
    pub fn any_with(type_id: TypeId) -> Self {
        Self::new().with(type_id)
    }
}
