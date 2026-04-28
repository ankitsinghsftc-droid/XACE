//! # Query Cache
//!
//! Caches query results keyed by sorted component type sets.
//! Invalidation is based on ComponentTableStore version tracking —
//! a cached result is stale when the store version changes.
//!
//! ## Cache Key
//! The cache key is a sorted Vec<u32> of component type IDs.
//! Sorting normalizes query order — [1,2] and [2,1] share one entry.
//!
//! ## Invalidation Strategy
//! Two invalidation modes:
//! 1. Version-based: Each entry stores the store version it was computed at.
//!    If the current store version differs, the entry is stale.
//! 2. Component-based: invalidate_for_component() removes all entries
//!    that include the given component type ID.
//!
//! ## Determinism
//! The cache never affects query results — only performance.
//! A cache miss produces the same result as a cache hit (D3).

use std::collections::BTreeMap;
use xace_core::entity_id::EntityID;
use super::query_engine::QueryCacheStats;

// ── Cache Entry ───────────────────────────────────────────────────────────────

/// A single cached query result.
struct CacheEntry {
    /// The cached EntityID list sorted ascending (D3).
    entity_ids: Vec<EntityID>,
    /// The ComponentTableStore version when this result was computed.
    /// Entry is stale if current store version != this value.
    store_version: u64,
    /// The tick when this entry was last accessed.
    last_accessed_tick: u64,
}

// ── Query Cache ───────────────────────────────────────────────────────────────

/// Cache for query engine results.
///
/// Stores results keyed by sorted component type ID sets.
/// Entries are validated against the store version before use.
pub struct QueryCache {
    /// BTreeMap for deterministic iteration order (D11).
    /// Key: sorted component type IDs.
    /// Value: cached result entry.
    entries: BTreeMap<Vec<u32>, CacheEntry>,

    /// Performance counters.
    total_queries: u64,
    cache_hits: u64,
    cache_misses: u64,
}

impl QueryCache {
    pub fn new() -> Self {
        Self {
            entries: BTreeMap::new(),
            total_queries: 0,
            cache_hits: 0,
            cache_misses: 0,
        }
    }

    /// Returns cached entity IDs if the entry exists and is not stale.
    ///
    /// An entry is stale if the current store_version differs from
    /// the version when the entry was computed.
    ///
    /// Returns None on cache miss or stale entry.
    pub fn get(
        &mut self,
        key: &[u32],
        current_store_version: u64,
    ) -> Option<&Vec<EntityID>> {
        self.total_queries += 1;

        let entry = self.entries.get(key)?;

        if entry.store_version != current_store_version {
            // Stale — version changed since this was cached
            self.cache_misses += 1;
            return None;
        }

        self.cache_hits += 1;
        // Return reference — borrow checker requires separate lookup
        self.entries.get(key).map(|e| &e.entity_ids)
    }

    /// Stores a query result in the cache.
    pub fn store(
        &mut self,
        key: Vec<u32>,
        entity_ids: Vec<EntityID>,
        store_version: u64,
        current_tick: u64,
    ) {
        self.entries.insert(key, CacheEntry {
            entity_ids,
            store_version,
            last_accessed_tick: current_tick,
        });
        // Count as a miss since we had to compute it
        if self.total_queries > 0 && self.cache_hits + self.cache_misses < self.total_queries {
            self.cache_misses += 1;
        }
    }

    /// Removes all cache entries that include the given component type ID.
    ///
    /// Called when a component of this type is written to — any cached
    /// query that includes this component type may now be stale.
    pub fn invalidate_for_component(&mut self, component_type_id: u32) {
        self.entries.retain(|key, _| !key.contains(&component_type_id));
    }

    /// Removes all cache entries.
    pub fn invalidate_all(&mut self) {
        self.entries.clear();
    }

    /// Returns the number of cached entries.
    pub fn entry_count(&self) -> usize {
        self.entries.len()
    }

    /// Returns true if the cache has no entries.
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    /// Returns current cache performance statistics.
    pub fn stats(&self) -> QueryCacheStats {
        QueryCacheStats {
            total_queries: self.total_queries,
            cache_hits: self.cache_hits,
            cache_misses: self.cache_misses,
            cached_entries: self.entries.len(),
        }
    }
}

impl Default for QueryCache {
    fn default() -> Self {
        Self::new()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn miss_on_empty_cache() {
        let mut cache = QueryCache::new();
        assert!(cache.get(&[1, 2], 0).is_none());
    }

    #[test]
    fn hit_after_store() {
        let mut cache = QueryCache::new();
        cache.store(vec![1, 2], vec![1, 2, 3], 42, 0);
        let result = cache.get(&[1, 2], 42);
        assert!(result.is_some());
        assert_eq!(result.unwrap(), &vec![1u64, 2, 3]);
    }

    #[test]
    fn stale_on_version_change() {
        let mut cache = QueryCache::new();
        cache.store(vec![1, 2], vec![1], 10, 0);
        // Version changed
        assert!(cache.get(&[1, 2], 11).is_none());
    }

    #[test]
    fn invalidate_for_component_removes_relevant() {
        let mut cache = QueryCache::new();
        cache.store(vec![1, 2], vec![1], 0, 0);
        cache.store(vec![2, 5], vec![2], 0, 0);
        cache.store(vec![1, 5], vec![3], 0, 0);
        cache.invalidate_for_component(2);
        // Entries with component 2 removed
        assert!(cache.get(&[1, 2], 0).is_none());
        assert!(cache.get(&[2, 5], 0).is_none());
        // Entry without component 2 still valid
        assert!(cache.get(&[1, 5], 0).is_some());
    }

    #[test]
    fn invalidate_all_clears_everything() {
        let mut cache = QueryCache::new();
        cache.store(vec![1], vec![1], 0, 0);
        cache.store(vec![2], vec![2], 0, 0);
        cache.invalidate_all();
        assert!(cache.is_empty());
        assert_eq!(cache.entry_count(), 0);
    }

    #[test]
    fn stats_track_hits_and_misses() {
        let mut cache = QueryCache::new();
        cache.store(vec![1], vec![1], 5, 0);
        cache.get(&[1], 5); // hit
        cache.get(&[1], 5); // hit
        cache.get(&[2], 5); // miss — not in cache
        let stats = cache.stats();
        assert_eq!(stats.cache_hits, 2);
        assert_eq!(stats.total_queries, 3);
    }

    #[test]
    fn entry_count_correct() {
        let mut cache = QueryCache::new();
        assert_eq!(cache.entry_count(), 0);
        cache.store(vec![1], vec![], 0, 0);
        cache.store(vec![2], vec![], 0, 0);
        assert_eq!(cache.entry_count(), 2);
    }
}