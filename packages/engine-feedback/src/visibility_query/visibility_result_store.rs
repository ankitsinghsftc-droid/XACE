//! # Visibility Result Store
//!
//! Stores `VisibilityQueryResult` values with a one-tick TTL, keyed by
//! `(observer_entity_id, target_entity_id)` for O(1) lookup by AI systems.
//!
//! ## Why a Dedicated Store
//! After the `VisibilityFeedbackHandler` writes results to `COMP_PERCEPTION_V1`
//! via the Mutation Gate, the Mutation Gate defers the write until phase end.
//! AI systems that want to react to visibility results in the same tick
//! cannot yet read from the component (the mutation is still pending).
//!
//! The result store provides an alternative read path: the handler also
//! stores the result here immediately, and AI systems can read it from
//! the store during the same Simulation phase without waiting for the
//! Mutation Gate to apply the component write.
//!
//! ## One-Tick TTL (I13)
//! Results expire after exactly one tick. The store's `expire_tick()` method
//! must be called at the START of each tick (after feedback drain but before
//! systems run) to remove stale results. Reading an expired result returns
//! `None` — the AI system must re-submit the query.
//!
//! ## Determinism (D11)
//! `BTreeMap<(observer, target), result>` — deterministic iteration order.
//! Same query set → same result store contents → same AI decisions.

use std::collections::BTreeMap;

use xace_core::entity_id::EntityID;

use crate::visibility_query::visibility_query::VisibilityQueryResult;

// ── Store Metrics ─────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Default)]
pub struct ResultStoreMetrics {
    /// Total results stored across all ticks.
    pub total_stored: u64,
    /// Total results successfully retrieved (cache hits).
    pub cache_hits: u64,
    /// Total lookups that returned None (cache misses or expired).
    pub cache_misses: u64,
    /// Total results expired across all ticks.
    pub total_expired: u64,
}

// ── Visibility Result Store ───────────────────────────────────────────────────

/// One-tick TTL store for visibility query results.
///
/// Written by `VisibilityFeedbackHandler` each tick.
/// Read by AI systems during the same or next Simulation phase.
/// Expired by the PhaseOrchestrator at tick START.
pub struct VisibilityResultStore {
    /// BTreeMap for deterministic iteration (D11).
    results: BTreeMap<(EntityID, EntityID), VisibilityQueryResult>,
    metrics: ResultStoreMetrics,
}

impl VisibilityResultStore {
    // ── Construction ──────────────────────────────────────────────────────────

    pub fn new() -> Self {
        Self {
            results: BTreeMap::new(),
            metrics: ResultStoreMetrics::default(),
        }
    }

    // ── Write ─────────────────────────────────────────────────────────────────

    /// Stores a visibility query result.
    ///
    /// Overwrites any existing result for the same (observer, target) pair.
    /// Called by `VisibilityFeedbackHandler` after processing each result.
    pub fn store(&mut self, result: VisibilityQueryResult) {
        let key = (result.observer_entity_id, result.target_entity_id);
        self.results.insert(key, result);
        self.metrics.total_stored += 1;
    }

    /// Stores multiple results at once (more efficient for batch feedback).
    pub fn store_batch(&mut self, results: Vec<VisibilityQueryResult>) {
        for result in results {
            self.store(result);
        }
    }

    // ── Read ──────────────────────────────────────────────────────────────────

    /// Returns the visibility result for the given (observer, target) pair.
    ///
    /// Returns `None` if:
    /// - No result exists for this pair (query not yet returned)
    /// - The result has expired (older than one tick)
    ///
    /// AI systems call this during Simulation phase to read the result
    /// of a query they submitted the previous tick.
    pub fn get(
        &mut self,
        observer: EntityID,
        target: EntityID,
        current_tick: u64,
    ) -> Option<&VisibilityQueryResult> {
        let key = (observer, target);
        match self.results.get(&key) {
            Some(r) if r.is_valid_at(current_tick) => {
                self.metrics.cache_hits += 1;
                self.results.get(&key)
            }
            Some(_) => {
                // Expired
                self.metrics.cache_misses += 1;
                None
            }
            None => {
                self.metrics.cache_misses += 1;
                None
            }
        }
    }

    /// Returns whether the observer can see the target at the current tick.
    /// Convenience wrapper over `get()` — returns `None` if no result.
    pub fn can_see(
        &mut self,
        observer: EntityID,
        target: EntityID,
        current_tick: u64,
    ) -> Option<bool> {
        self.get(observer, target, current_tick).map(|r| r.can_see)
    }

    // ── Expiry ────────────────────────────────────────────────────────────────

    /// Expires all results older than `current_tick - 1`.
    ///
    /// Called at tick START before AI systems run. Removes results
    /// that are more than one tick old — they are no longer valid.
    /// Returns the count of results expired.
    pub fn expire_tick(&mut self, current_tick: u64) -> usize {
        let before = self.results.len();

        self.results.retain(|_, r| {
            if r.is_valid_at(current_tick) {
                true
            } else {
                r.is_expired = true;
                false
            }
        });

        let expired = before - self.results.len();
        self.metrics.total_expired += expired as u64;
        expired
    }

    /// Clears all stored results without expiry tracking.
    /// Called on session reset or transport reconnect.
    pub fn clear(&mut self) {
        self.results.clear();
    }

    // ── Inspection ────────────────────────────────────────────────────────────

    /// Returns the number of valid results currently stored.
    pub fn stored_count(&self) -> usize {
        self.results.len()
    }

    /// Returns true if the store has no results.
    pub fn is_empty(&self) -> bool {
        self.results.is_empty()
    }

    /// Returns accumulated store metrics.
    pub fn metrics(&self) -> &ResultStoreMetrics {
        &self.metrics
    }

    /// Returns all valid results at the current tick, sorted by
    /// `(observer_id ASC, target_id ASC)` (D11).
    pub fn all_valid_at(&mut self, current_tick: u64) -> Vec<&VisibilityQueryResult> {
        self.results
            .values()
            .filter(|r| r.is_valid_at(current_tick))
            .collect()
    }
}

impl Default for VisibilityResultStore {
    fn default() -> Self {
        Self::new()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn result(obs: u64, tgt: u64, can_see: bool, tick: u64) -> VisibilityQueryResult {
        VisibilityQueryResult::new(obs, tgt, can_see, 10.0, tick)
    }

    // ── Store / Get ───────────────────────────────────────────────────────────

    #[test]
    fn store_and_retrieve_result() {
        let mut s = VisibilityResultStore::new();
        s.store(result(1, 2, true, 5));
        let r = s.get(1, 2, 5).unwrap();
        assert!(r.can_see);
        assert_eq!(s.metrics().cache_hits, 1);
    }

    #[test]
    fn get_nonexistent_returns_none() {
        let mut s = VisibilityResultStore::new();
        assert!(s.get(1, 2, 5).is_none());
        assert_eq!(s.metrics().cache_misses, 1);
    }

    #[test]
    fn can_see_convenience_wrapper() {
        let mut s = VisibilityResultStore::new();
        s.store(result(1, 2, true, 5));
        assert_eq!(s.can_see(1, 2, 5), Some(true));
        assert_eq!(s.can_see(1, 2, 99), None); // expired
    }

    #[test]
    fn store_batch_stores_all() {
        let mut s = VisibilityResultStore::new();
        s.store_batch(vec![result(1, 2, true, 5), result(3, 4, false, 5)]);
        assert_eq!(s.stored_count(), 2);
    }

    #[test]
    fn newer_result_overwrites_older() {
        let mut s = VisibilityResultStore::new();
        s.store(result(1, 2, false, 5)); // can't see
        s.store(result(1, 2, true, 6)); // now can see
        let r = s.get(1, 2, 6).unwrap();
        assert!(r.can_see);
    }

    // ── TTL and Expiry ────────────────────────────────────────────────────────

    #[test]
    fn result_valid_at_same_tick() {
        let mut s = VisibilityResultStore::new();
        s.store(result(1, 2, true, 10));
        assert!(s.get(1, 2, 10).is_some());
    }

    #[test]
    fn result_valid_one_tick_later() {
        let mut s = VisibilityResultStore::new();
        s.store(result(1, 2, true, 10));
        assert!(s.get(1, 2, 11).is_some()); // tick+1 still valid
    }

    #[test]
    fn result_expired_two_ticks_later() {
        let mut s = VisibilityResultStore::new();
        s.store(result(1, 2, true, 10));
        assert!(s.get(1, 2, 12).is_none()); // tick+2 expired
    }

    #[test]
    fn expire_tick_removes_stale_results() {
        let mut s = VisibilityResultStore::new();
        s.store(result(1, 2, true, 5));
        s.store(result(3, 4, false, 7));
        s.store(result(5, 6, true, 8));

        // At tick 8: result from tick 5 is expired (8 > 5+1), tick 7 is still valid (8 == 7+1)
        let expired = s.expire_tick(8);
        assert_eq!(expired, 1); // tick 5 result removed
        assert_eq!(s.stored_count(), 2);
        assert_eq!(s.metrics().total_expired, 1);
    }

    #[test]
    fn expire_tick_removes_all_old_results() {
        let mut s = VisibilityResultStore::new();
        for i in 0..5u64 {
            s.store(result(i + 1, i + 100, true, i)); // ticks 0,1,2,3,4
        }
        // At tick 10: all results from ticks 0-4 are expired
        let expired = s.expire_tick(10);
        assert_eq!(expired, 5);
        assert!(s.is_empty());
    }

    #[test]
    fn clear_removes_all_results() {
        let mut s = VisibilityResultStore::new();
        s.store(result(1, 2, true, 1));
        s.store(result(3, 4, false, 1));
        s.clear();
        assert!(s.is_empty());
    }

    // ── Deterministic Ordering ────────────────────────────────────────────────

    #[test]
    fn all_valid_at_returns_sorted_results() {
        let mut s = VisibilityResultStore::new();
        s.store(result(5, 1, true, 10));
        s.store(result(1, 3, true, 10));
        s.store(result(1, 2, false, 10));

        let all = s.all_valid_at(10);
        assert_eq!(all.len(), 3);
        // BTreeMap order: (1,2), (1,3), (5,1)
        assert_eq!(all[0].observer_entity_id, 1);
        assert_eq!(all[0].target_entity_id, 2);
        assert_eq!(all[1].target_entity_id, 3);
        assert_eq!(all[2].observer_entity_id, 5);
    }

    // ── Metrics ───────────────────────────────────────────────────────────────

    #[test]
    fn metrics_track_hits_and_misses() {
        let mut s = VisibilityResultStore::new();
        s.store(result(1, 2, true, 5));
        s.get(1, 2, 5); // hit
        s.get(1, 2, 5); // hit
        s.get(3, 4, 5); // miss
        let m = s.metrics();
        assert_eq!(m.cache_hits, 2);
        assert_eq!(m.cache_misses, 1);
    }
}
