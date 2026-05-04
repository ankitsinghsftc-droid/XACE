//! # Visibility Query Batcher
//!
//! Collects `COMP_PERCEPTION_V1.visibility_query_pending` flags each tick,
//! deduplicates (observer, target) pairs, and produces a batch of
//! `VisibilityQuery` values ready for `IEngineAdapter::send_visibility_queries()`.
//!
//! ## Per-Tick Flow
//! ```text
//! PhaseOrchestrator (Simulation phase):
//!   1. Query all entities with COMP_PERCEPTION_V1 and visibility_query_pending=true
//!   2. For each: batcher.add(observer_id, target_id, max_distance)
//!   3. After Simulation phase: batch = batcher.take_batch()
//!   4. engine_adapter.send_visibility_queries(batch)
//!   5. batcher is now empty — ready for next tick
//! ```
//!
//! ## Deduplication
//! Multiple systems might independently request the same (observer, target)
//! visibility check in the same tick. Sending duplicate queries to the engine
//! wastes raycast budget. The batcher keeps only the first query for each
//! (observer, target) pair per tick.
//!
//! If the same pair is added with different `max_distance` values, the
//! **maximum** distance is kept — the larger range subsumes the smaller.
//!
//! ## Batch Size Limit
//! The batcher enforces a configurable maximum batch size. If more queries
//! are submitted than the limit, the excess are dropped and counted in
//! metrics. The PIL performance risk guard uses this count to warn when
//! AI systems are submitting too many visibility queries per tick.
//!
//! ## Determinism (D11)
//! The batch is sorted by `(observer_entity_id ASC, target_entity_id ASC)`
//! before being returned. Same set of pending queries → same batch → same
//! engine raycasts → same results next tick.

use std::collections::BTreeMap;

use xace_core::entity_id::EntityID;

use crate::visibility_query::visibility_query::VisibilityQuery;

// ── Batcher Configuration ─────────────────────────────────────────────────────

/// Configuration for the `VisibilityQueryBatcher`.
#[derive(Debug, Clone)]
pub struct BatcherConfig {
    /// Maximum number of queries per tick.
    /// Excess queries are dropped and counted in metrics.
    /// Default: 256 queries per tick — sufficient for large AI scenes.
    pub max_queries_per_tick: usize,
}

impl Default for BatcherConfig {
    fn default() -> Self {
        Self {
            max_queries_per_tick: 256,
        }
    }
}

// ── Batcher Metrics ───────────────────────────────────────────────────────────

#[derive(Debug, Clone, Default)]
pub struct BatcherMetrics {
    /// Total batches produced (one per tick that had pending queries).
    pub batches_produced: u64,
    /// Total queries submitted across all ticks.
    pub total_submitted: u64,
    /// Total duplicate (observer, target) pairs eliminated.
    pub duplicates_eliminated: u64,
    /// Total queries dropped because the batch size limit was exceeded.
    pub overflow_dropped: u64,
    /// Total ticks where at least one query was in the batch.
    pub non_empty_batch_ticks: u64,
}

// ── Visibility Query Batcher ──────────────────────────────────────────────────

/// Accumulates visibility queries for one tick and produces a deduplicated,
/// sorted, size-limited batch for the engine adapter.
pub struct VisibilityQueryBatcher {
    config: BatcherConfig,

    /// Deduplicated pending queries.
    /// BTreeMap<(observer_id, target_id), max_distance> — sorted key (D11).
    pending: BTreeMap<(EntityID, EntityID), f32>,

    metrics: BatcherMetrics,
}

impl VisibilityQueryBatcher {
    // ── Construction ──────────────────────────────────────────────────────────

    pub fn new(config: BatcherConfig) -> Self {
        Self {
            config,
            pending: BTreeMap::new(),
            metrics: BatcherMetrics::default(),
        }
    }

    pub fn with_defaults() -> Self {
        Self::new(BatcherConfig::default())
    }

    // ── Primary API ───────────────────────────────────────────────────────────

    /// Adds a visibility query to the current tick's batch.
    ///
    /// If the (observer, target) pair already exists, keeps the larger
    /// max_distance (larger range subsumes the smaller).
    /// If the batch is already at the size limit, the query is dropped.
    pub fn add(&mut self, observer: EntityID, target: EntityID, max_distance: f32) {
        self.metrics.total_submitted += 1;

        // Validate the pair
        if observer == 0 || target == 0 || observer == target {
            // Invalid query — silently discard (validation is VisibilityQuery's job)
            return;
        }

        let key = (observer, target);

        // Check if pair already exists
        if let Some(existing_distance) = self.pending.get_mut(&key) {
            self.metrics.duplicates_eliminated += 1;
            // Keep the larger range
            if max_distance > *existing_distance {
                *existing_distance = max_distance;
            }
            return;
        }

        // Check batch size limit
        if self.pending.len() >= self.config.max_queries_per_tick {
            self.metrics.overflow_dropped += 1;
            return;
        }

        self.pending.insert(key, max_distance);
    }

    /// Adds a `VisibilityQuery` directly (convenience wrapper).
    pub fn add_query(&mut self, query: VisibilityQuery) {
        self.add(
            query.observer_entity_id,
            query.target_entity_id,
            query.max_distance,
        );
    }

    /// Drains the batch, returning a sorted Vec of `VisibilityQuery` values.
    ///
    /// BTreeMap iteration is already `(observer ASC, target ASC)` — no
    /// additional sort required (D11).
    ///
    /// Clears the internal pending map — the batcher is empty after this call.
    /// Returns an empty Vec if no queries were added this tick.
    pub fn take_batch(&mut self) -> Vec<VisibilityQuery> {
        if self.pending.is_empty() {
            return Vec::new();
        }

        let batch: Vec<VisibilityQuery> = self
            .pending
            .iter()
            .map(|(&(observer, target), &max_distance)| {
                VisibilityQuery::new(observer, target, max_distance)
            })
            .collect();

        self.pending.clear();

        self.metrics.batches_produced += 1;
        self.metrics.non_empty_batch_ticks += 1;

        batch
    }

    // ── Inspection ────────────────────────────────────────────────────────────

    /// Returns the number of pending queries in the current tick's batch.
    pub fn pending_count(&self) -> usize {
        self.pending.len()
    }

    /// Returns true if no queries are pending.
    pub fn is_empty(&self) -> bool {
        self.pending.is_empty()
    }

    /// Returns accumulated batcher metrics.
    pub fn metrics(&self) -> &BatcherMetrics {
        &self.metrics
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn batcher() -> VisibilityQueryBatcher {
        VisibilityQueryBatcher::with_defaults()
    }

    fn small_batcher(max: usize) -> VisibilityQueryBatcher {
        VisibilityQueryBatcher::new(BatcherConfig { max_queries_per_tick: max })
    }

    // ── Basic Add / Take ──────────────────────────────────────────────────────

    #[test]
    fn empty_batcher_produces_empty_batch() {
        let mut b = batcher();
        let batch = b.take_batch();
        assert!(batch.is_empty());
    }

    #[test]
    fn add_single_query_appears_in_batch() {
        let mut b = batcher();
        b.add(1, 2, 50.0);
        let batch = b.take_batch();
        assert_eq!(batch.len(), 1);
        assert_eq!(batch[0].observer_entity_id, 1);
        assert_eq!(batch[0].target_entity_id, 2);
    }

    #[test]
    fn take_batch_clears_pending() {
        let mut b = batcher();
        b.add(1, 2, 50.0);
        b.take_batch();
        assert!(b.is_empty());
        assert_eq!(b.pending_count(), 0);
    }

    #[test]
    fn add_query_convenience_method_works() {
        let mut b = batcher();
        b.add_query(VisibilityQuery::new(3, 4, 20.0));
        assert_eq!(b.pending_count(), 1);
    }

    // ── Deduplication ─────────────────────────────────────────────────────────

    #[test]
    fn duplicate_pair_eliminated() {
        let mut b = batcher();
        b.add(1, 2, 10.0);
        b.add(1, 2, 10.0); // duplicate
        let batch = b.take_batch();
        assert_eq!(batch.len(), 1);
        assert_eq!(b.metrics().duplicates_eliminated, 1);
    }

    #[test]
    fn duplicate_keeps_larger_max_distance() {
        let mut b = batcher();
        b.add(1, 2, 10.0);
        b.add(1, 2, 50.0); // larger range — should win
        let batch = b.take_batch();
        assert_eq!(batch.len(), 1);
        assert!((batch[0].max_distance - 50.0).abs() < 1e-5);
    }

    #[test]
    fn duplicate_keeps_larger_when_first_is_bigger() {
        let mut b = batcher();
        b.add(1, 2, 100.0);
        b.add(1, 2, 30.0); // smaller — first should win
        let batch = b.take_batch();
        assert!((batch[0].max_distance - 100.0).abs() < 1e-5);
    }

    #[test]
    fn reverse_direction_is_not_duplicate() {
        // (A→B) and (B→A) are different queries — not symmetric
        let mut b = batcher();
        b.add(1, 2, 10.0);
        b.add(2, 1, 10.0);
        let batch = b.take_batch();
        assert_eq!(batch.len(), 2);
    }

    // ── Deterministic Ordering (D11) ──────────────────────────────────────────

    #[test]
    fn batch_sorted_by_observer_asc_then_target_asc() {
        let mut b = batcher();
        b.add(5, 2, 10.0);
        b.add(1, 9, 10.0);
        b.add(1, 3, 10.0);
        b.add(3, 1, 10.0);
        let batch = b.take_batch();
        // Expected order: (1,3), (1,9), (3,1), (5,2)
        assert_eq!(batch[0].observer_entity_id, 1);
        assert_eq!(batch[0].target_entity_id, 3);
        assert_eq!(batch[1].observer_entity_id, 1);
        assert_eq!(batch[1].target_entity_id, 9);
        assert_eq!(batch[2].observer_entity_id, 3);
        assert_eq!(batch[3].observer_entity_id, 5);
    }

    #[test]
    fn batch_order_deterministic_across_runs() {
        let fill = || {
            let mut b = batcher();
            b.add(5, 1, 10.0);
            b.add(2, 3, 10.0);
            b.add(1, 4, 10.0);
            b.take_batch()
        };

        let run_a: Vec<(u64, u64)> = fill()
            .iter()
            .map(|q| (q.observer_entity_id, q.target_entity_id))
            .collect();

        let run_b: Vec<(u64, u64)> = fill()
            .iter()
            .map(|q| (q.observer_entity_id, q.target_entity_id))
            .collect();

        assert_eq!(run_a, run_b, "Batch order must be deterministic (D11)");
    }

    // ── Size Limit ────────────────────────────────────────────────────────────

    #[test]
    fn batch_size_limit_enforced() {
        let mut b = small_batcher(3);
        b.add(1, 2, 10.0);
        b.add(1, 3, 10.0);
        b.add(1, 4, 10.0);
        b.add(1, 5, 10.0); // overflow — dropped
        let batch = b.take_batch();
        assert_eq!(batch.len(), 3);
        assert_eq!(b.metrics().overflow_dropped, 1);
    }

    #[test]
    fn overflow_counted_in_metrics() {
        let mut b = small_batcher(2);
        for target in 1..=5 {
            b.add(99, target, 10.0);
        }
        assert_eq!(b.metrics().overflow_dropped, 3);
    }

    // ── Invalid Inputs Silently Discarded ─────────────────────────────────────

    #[test]
    fn null_observer_silently_discarded() {
        let mut b = batcher();
        b.add(0, 2, 10.0);
        assert!(b.is_empty());
    }

    #[test]
    fn null_target_silently_discarded() {
        let mut b = batcher();
        b.add(1, 0, 10.0);
        assert!(b.is_empty());
    }

    #[test]
    fn self_query_silently_discarded() {
        let mut b = batcher();
        b.add(5, 5, 10.0);
        assert!(b.is_empty());
    }

    // ── Metrics ───────────────────────────────────────────────────────────────

    #[test]
    fn metrics_count_submitted_and_batches() {
        let mut b = batcher();
        b.add(1, 2, 10.0);
        b.add(1, 3, 10.0);
        b.add(1, 2, 20.0); // duplicate
        b.take_batch();

        let m = b.metrics();
        assert_eq!(m.total_submitted, 3);
        assert_eq!(m.duplicates_eliminated, 1);
        assert_eq!(m.batches_produced, 1);
        assert_eq!(m.non_empty_batch_ticks, 1);
    }
}