//! # Query Engine
//!
//! The primary interface for systems to find entities with specific
//! component combinations. All queries return EntityIDs sorted
//! ascending (D3) — determinism is unconditional.
//!
//! ## Design
//! The QueryEngine sits on top of ComponentTableStore and provides
//! a cached intersection query interface. Systems call query() with
//! a list of required component type IDs and receive a sorted list
//! of EntityIDs that have all of those components.
//!
//! ## Query Cache
//! Results are cached by component type set. The cache is invalidated
//! when any component in the queried set is written to. This makes
//! repeated identical queries within a tick essentially free.
//!
//! ## Determinism (D3)
//! Every query result is sorted by EntityID ASC. This guarantee
//! holds regardless of cache state, table modification order, or
//! the order in which component_type_ids are passed to query().

use super::query_cache::QueryCache;
use crate::component_tables::component_table_store::ComponentTableStore;
use xace_core::entity_id::EntityID;
use xace_core::errors::xace_error::XaceError;

// ── Query Result ──────────────────────────────────────────────────────────────

/// The result of a component intersection query.
///
/// Contains the sorted list of EntityIDs that have all requested
/// component types. Always sorted by EntityID ASC (D3).
#[derive(Debug, Clone, PartialEq)]
pub struct QueryResult {
    /// EntityIDs sorted ascending (D3).
    pub entity_ids: Vec<EntityID>,
    /// Whether this result came from cache or was freshly computed.
    pub from_cache: bool,
}

impl QueryResult {
    pub fn empty() -> Self {
        Self {
            entity_ids: Vec::new(),
            from_cache: false,
        }
    }

    pub fn len(&self) -> usize {
        self.entity_ids.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entity_ids.is_empty()
    }

    pub fn contains(&self, entity_id: EntityID) -> bool {
        self.entity_ids.binary_search(&entity_id).is_ok()
    }
}

// ── Query Engine ──────────────────────────────────────────────────────────────

/// Cached, deterministic entity query system.
///
/// Systems call query() each tick to find entities matching a
/// component signature. Results are cached and invalidated when
/// any relevant component table is written to.
///
/// ## Query Key Normalization
/// Component type IDs are always sorted before use as cache keys.
/// query(&[5, 1, 3]) and query(&[1, 3, 5]) produce identical results
/// and share the same cache entry.
///
/// ## Integration
/// The QueryEngine holds a reference to the ComponentTableStore for
/// live queries and a QueryCache for result caching.
/// The PhaseOrchestrator owns both and passes references here.
pub struct QueryEngine {
    /// Cache of recent query results keyed by sorted component type sets.
    cache: QueryCache,
}

impl QueryEngine {
    /// Creates a new QueryEngine with an empty cache.
    pub fn new() -> Self {
        Self {
            cache: QueryCache::new(),
        }
    }

    /// Executes an intersection query — returns all EntityIDs that have
    /// ALL of the specified component types, sorted ascending (D3).
    ///
    /// ## Query Key Normalization
    /// component_type_ids are sorted before lookup — query order
    /// does not affect results or cache behavior.
    ///
    /// ## Cache Behavior
    /// Returns cached result if valid. Recomputes and caches if stale
    /// or if this query has not been seen before.
    ///
    /// ## Empty Query
    /// Returns empty result for empty component_type_ids slice.
    /// Systems querying with no components get nothing — not all entities.
    pub fn query(
        &mut self,
        component_type_ids: &[u32],
        store: &ComponentTableStore,
        current_tick: u64,
    ) -> Result<QueryResult, XaceError> {
        if component_type_ids.is_empty() {
            return Ok(QueryResult::empty());
        }

        // Normalize key — sort component type IDs for consistent caching
        let mut key: Vec<u32> = component_type_ids.to_vec();
        key.sort();

        // Check cache validity
        let store_version = store.combined_version();
        if let Some(cached) = self.cache.get(&key, store_version) {
            return Ok(QueryResult {
                entity_ids: cached.clone(),
                from_cache: true,
            });
        }

        // Cache miss or stale — compute fresh result
        let entity_ids = store.entities_with_all_components(&key);

        // Verify sort order (debug builds only)
        #[cfg(debug_assertions)]
        for window in entity_ids.windows(2) {
            debug_assert!(
                window[0] < window[1],
                "QueryEngine: entities_with_all_components returned unsorted result"
            );
        }

        // Store in cache
        self.cache
            .store(key, entity_ids.clone(), store_version, current_tick);

        Ok(QueryResult {
            entity_ids,
            from_cache: false,
        })
    }

    /// Executes a query with an additional tag filter.
    ///
    /// Returns EntityIDs that have all requested components AND
    /// have the specified tag in their EntityStore metadata.
    /// Tag filtering happens post-query — the base query uses the cache.
    pub fn query_with_tag(
        &mut self,
        component_type_ids: &[u32],
        tag: &str,
        store: &ComponentTableStore,
        tag_lookup: &dyn Fn(EntityID, &str) -> bool,
        current_tick: u64,
    ) -> Result<QueryResult, XaceError> {
        let base = self.query(component_type_ids, store, current_tick)?;
        let filtered: Vec<EntityID> = base
            .entity_ids
            .into_iter()
            .filter(|&id| tag_lookup(id, tag))
            .collect();
        // Already sorted since we filtered from sorted list
        Ok(QueryResult {
            entity_ids: filtered,
            from_cache: false,
        })
    }

    /// Invalidates all cached results for queries that include
    /// the given component type ID.
    ///
    /// Called by the MutationGate after applying mutations that
    /// write to a specific component type. Ensures stale results
    /// are not returned in subsequent queries.
    pub fn invalidate_for_component(&mut self, component_type_id: u32) {
        self.cache.invalidate_for_component(component_type_id);
    }

    /// Invalidates the entire query cache.
    ///
    /// Called after bulk operations like snapshot restore where
    /// any cached result may be stale.
    pub fn invalidate_all(&mut self) {
        self.cache.invalidate_all();
    }

    /// Returns cache statistics for debugging and performance monitoring.
    pub fn cache_stats(&self) -> QueryCacheStats {
        self.cache.stats()
    }

    /// Returns the number of cached query results.
    pub fn cached_query_count(&self) -> usize {
        self.cache.entry_count()
    }
}

impl Default for QueryEngine {
    fn default() -> Self {
        Self::new()
    }
}

/// Statistics about query cache performance.
#[derive(Debug, Clone)]
pub struct QueryCacheStats {
    pub total_queries: u64,
    pub cache_hits: u64,
    pub cache_misses: u64,
    pub cached_entries: usize,
}

impl QueryCacheStats {
    pub fn hit_rate(&self) -> f64 {
        if self.total_queries == 0 {
            return 0.0;
        }
        self.cache_hits as f64 / self.total_queries as f64
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::component_tables::ComponentTableStore;

    fn setup() -> (QueryEngine, ComponentTableStore) {
        let mut store = ComponentTableStore::new();
        store.register_table(1, "COMP_TRANSFORM_V1").unwrap();
        store.register_table(2, "COMP_IDENTITY_V1").unwrap();
        store.register_table(5, "COMP_VELOCITY_V1").unwrap();
        (QueryEngine::new(), store)
    }

    #[test]
    fn empty_query_returns_empty() {
        let (mut qe, store) = setup();
        let result = qe.query(&[], &store, 0).unwrap();
        assert!(result.is_empty());
    }

    #[test]
    fn single_component_query() {
        let (mut qe, mut store) = setup();
        store.add_component(1, 1, "{}".into(), 0).unwrap();
        store.add_component(2, 1, "{}".into(), 0).unwrap();
        let result = qe.query(&[1], &store, 0).unwrap();
        assert_eq!(result.entity_ids, vec![1, 2]);
    }

    #[test]
    fn multi_component_intersection() {
        let (mut qe, mut store) = setup();
        store.add_component(1, 1, "{}".into(), 0).unwrap();
        store.add_component(1, 2, "{}".into(), 0).unwrap();
        store.add_component(2, 1, "{}".into(), 0).unwrap(); // only transform
        let result = qe.query(&[1, 2], &store, 0).unwrap();
        assert_eq!(result.entity_ids, vec![1]);
    }

    #[test]
    fn query_order_does_not_affect_result() {
        let (mut qe, mut store) = setup();
        store.add_component(1, 1, "{}".into(), 0).unwrap();
        store.add_component(1, 2, "{}".into(), 0).unwrap();
        let r1 = qe.query(&[1, 2], &store, 0).unwrap();
        let r2 = qe.query(&[2, 1], &store, 0).unwrap();
        assert_eq!(r1.entity_ids, r2.entity_ids);
    }

    #[test]
    fn result_is_sorted_ascending() {
        let (mut qe, mut store) = setup();
        for id in [5u64, 1, 3, 2, 4] {
            store.add_component(id, 1, "{}".into(), 0).unwrap();
        }
        let result = qe.query(&[1], &store, 0).unwrap();
        for window in result.entity_ids.windows(2) {
            assert!(window[0] < window[1]);
        }
    }

    #[test]
    fn cache_hit_on_repeated_query() {
        let (mut qe, mut store) = setup();
        store.add_component(1, 1, "{}".into(), 0).unwrap();
        let r1 = qe.query(&[1], &store, 0).unwrap();
        assert!(!r1.from_cache);
        let r2 = qe.query(&[1], &store, 0).unwrap();
        assert!(r2.from_cache);
        assert_eq!(r1.entity_ids, r2.entity_ids);
    }

    #[test]
    fn cache_invalidated_after_write() {
        let (mut qe, mut store) = setup();
        store.add_component(1, 1, "{}".into(), 0).unwrap();
        let _ = qe.query(&[1], &store, 0).unwrap();
        // Write to component table — version increases
        store.add_component(2, 1, "{}".into(), 1).unwrap();
        // Next query should recompute
        let r = qe.query(&[1], &store, 1).unwrap();
        assert!(!r.from_cache);
        assert_eq!(r.entity_ids, vec![1, 2]);
    }

    #[test]
    fn query_with_tag_filters_correctly() {
        let (mut qe, mut store) = setup();
        store.add_component(1, 1, "{}".into(), 0).unwrap();
        store.add_component(2, 1, "{}".into(), 0).unwrap();
        store.add_component(3, 1, "{}".into(), 0).unwrap();

        // Mock tag lookup — only entity 2 has "enemy" tag
        let tag_lookup = |id: EntityID, tag: &str| -> bool { id == 2 && tag == "enemy" };

        let result = qe
            .query_with_tag(&[1], "enemy", &store, &tag_lookup, 0)
            .unwrap();
        assert_eq!(result.entity_ids, vec![2]);
    }

    #[test]
    fn invalidate_all_clears_cache() {
        let (mut qe, mut store) = setup();
        store.add_component(1, 1, "{}".into(), 0).unwrap();
        let _ = qe.query(&[1], &store, 0).unwrap();
        assert!(qe.cached_query_count() > 0);
        qe.invalidate_all();
        assert_eq!(qe.cached_query_count(), 0);
    }

    #[test]
    fn query_missing_table_returns_empty() {
        let (mut qe, store) = setup();
        let result = qe.query(&[999], &store, 0).unwrap();
        assert!(result.is_empty());
    }

    #[test]
    fn contains_works_on_result() {
        let (mut qe, mut store) = setup();
        store.add_component(1, 1, "{}".into(), 0).unwrap();
        store.add_component(3, 1, "{}".into(), 0).unwrap();
        let result = qe.query(&[1], &store, 0).unwrap();
        assert!(result.contains(1));
        assert!(result.contains(3));
        assert!(!result.contains(2));
    }
}
