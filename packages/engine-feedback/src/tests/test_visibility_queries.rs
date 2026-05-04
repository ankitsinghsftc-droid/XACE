//! # Visibility Query Integration Tests
//!
//! Integration tests for the complete visibility query pipeline:
//! VisibilityQueryBatcher → engine adapter → VisibilityFeedbackHandler
//! → VisibilityResultStore → AI system reads result
//!
//! ## Coverage
//! - VisibilityQuery validation
//! - VisibilityQueryBatcher: dedup, ordering, size limit
//! - VisibilityResultStore: TTL, expiry, concurrent-safe reads
//! - VisibilityFeedbackHandler: valid/invalid feedback processing
//! - Full pipeline: query submission → feedback injection → result retrieval

#[cfg(test)]
mod tests {
    use xace_core::wire::feedback_payload::{
        FeedbackMessage, FeedbackType, VisibilityQueryResultFeedback,
    };

    use crate::feedback_message::TypedFeedbackPayload;
    use crate::handlers::visibility_feedback_handler::VisibilityFeedbackHandler;
    use crate::feedback_router::FeedbackHandler;
    use crate::visibility_query::visibility_query::{VisibilityQuery, VisibilityQueryResult};
    use crate::visibility_query::visibility_query_batcher::{
        BatcherConfig, VisibilityQueryBatcher,
    };
    use crate::visibility_query::visibility_result_store::VisibilityResultStore;

    // ── Helpers ───────────────────────────────────────────────────────────────

    fn vis_feedback(
        observer: u64,
        target: u64,
        can_see: bool,
        distance: f32,
        frame: u64,
    ) -> TypedFeedbackPayload {
        TypedFeedbackPayload::VisibilityQueryResult(VisibilityQueryResultFeedback {
            observer_entity_id: observer,
            target_entity_id: target,
            can_see,
            distance,
            generated_frame: frame,
        })
    }

    // =========================================================================
    // VisibilityQuery
    // =========================================================================

    #[test]
    fn query_new_stores_fields_correctly() {
        let q = VisibilityQuery::new(1, 2, 50.0);
        assert_eq!(q.observer_entity_id, 1);
        assert_eq!(q.target_entity_id, 2);
        assert!((q.max_distance - 50.0).abs() < 1e-5);
    }

    #[test]
    fn query_default_range_has_zero_distance() {
        let q = VisibilityQuery::with_default_range(3, 7);
        assert_eq!(q.max_distance, 0.0);
        assert!(!q.has_explicit_range());
    }

    #[test]
    fn query_validate_all_valid_cases() {
        assert!(VisibilityQuery::new(1, 2, 50.0).validate().is_ok());
        assert!(VisibilityQuery::new(1, 2, 0.0).validate().is_ok()); // zero distance ok
    }

    #[test]
    fn query_validate_all_invalid_cases() {
        assert!(VisibilityQuery::new(0, 2, 10.0).validate().is_err()); // null observer
        assert!(VisibilityQuery::new(1, 0, 10.0).validate().is_err()); // null target
        assert!(VisibilityQuery::new(5, 5, 10.0).validate().is_err()); // self-query
        assert!(VisibilityQuery::new(1, 2, -1.0).validate().is_err()); // negative distance
    }

    #[test]
    fn query_dedup_key_is_ordered_pair() {
        let q = VisibilityQuery::new(3, 9, 10.0);
        assert_eq!(q.dedup_key(), (3, 9));
    }

    #[test]
    fn query_reverse_direction_distinct_dedup_keys() {
        let q1 = VisibilityQuery::new(1, 5, 10.0);
        let q2 = VisibilityQuery::new(5, 1, 10.0);
        assert_ne!(q1.dedup_key(), q2.dedup_key());
    }

    // =========================================================================
    // VisibilityQueryBatcher
    // =========================================================================

    #[test]
    fn batcher_empty_produces_empty_batch() {
        let mut b = VisibilityQueryBatcher::with_defaults();
        assert!(b.take_batch().is_empty());
    }

    #[test]
    fn batcher_single_query_in_batch() {
        let mut b = VisibilityQueryBatcher::with_defaults();
        b.add(1, 2, 50.0);
        let batch = b.take_batch();
        assert_eq!(batch.len(), 1);
        assert_eq!(batch[0].observer_entity_id, 1);
        assert_eq!(batch[0].target_entity_id, 2);
    }

    #[test]
    fn batcher_deduplicates_same_pair() {
        let mut b = VisibilityQueryBatcher::with_defaults();
        b.add(1, 2, 10.0);
        b.add(1, 2, 20.0); // duplicate — larger distance kept
        b.add(1, 2, 5.0);  // duplicate — smaller ignored
        let batch = b.take_batch();
        assert_eq!(batch.len(), 1);
        assert!((batch[0].max_distance - 20.0).abs() < 1e-5);
        assert_eq!(b.metrics().duplicates_eliminated, 2);
    }

    #[test]
    fn batcher_distinct_pairs_all_included() {
        let mut b = VisibilityQueryBatcher::with_defaults();
        b.add(1, 2, 10.0);
        b.add(2, 1, 10.0); // reverse — distinct
        b.add(1, 3, 10.0);
        let batch = b.take_batch();
        assert_eq!(batch.len(), 3);
    }

    #[test]
    fn batcher_batch_sorted_observer_asc_target_asc() {
        let mut b = VisibilityQueryBatcher::with_defaults();
        b.add(5, 1, 10.0);
        b.add(1, 9, 10.0);
        b.add(1, 2, 10.0);
        let batch = b.take_batch();
        // Expected: (1,2), (1,9), (5,1)
        assert_eq!(batch[0].observer_entity_id, 1);
        assert_eq!(batch[0].target_entity_id, 2);
        assert_eq!(batch[1].target_entity_id, 9);
        assert_eq!(batch[2].observer_entity_id, 5);
    }

    #[test]
    fn batcher_ordering_deterministic_across_runs() {
        let fill = || {
            let mut b = VisibilityQueryBatcher::with_defaults();
            b.add(3, 1, 10.0);
            b.add(1, 5, 10.0);
            b.add(2, 2, 10.0); // self-query — silently discarded
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
        assert_eq!(run_a, run_b, "Batch ordering must be deterministic (D11)");
    }

    #[test]
    fn batcher_size_limit_drops_overflow() {
        let mut b = VisibilityQueryBatcher::new(BatcherConfig { max_queries_per_tick: 3 });
        for target in 1..=6 {
            b.add(99, target, 10.0);
        }
        let batch = b.take_batch();
        assert_eq!(batch.len(), 3);
        assert_eq!(b.metrics().overflow_dropped, 3);
    }

    #[test]
    fn batcher_invalid_queries_silently_discarded() {
        let mut b = VisibilityQueryBatcher::with_defaults();
        b.add(0, 2, 10.0); // null observer
        b.add(1, 0, 10.0); // null target
        b.add(5, 5, 10.0); // self-query
        assert!(b.is_empty());
    }

    #[test]
    fn batcher_take_clears_pending() {
        let mut b = VisibilityQueryBatcher::with_defaults();
        b.add(1, 2, 10.0);
        b.take_batch();
        assert!(b.is_empty());
    }

    // =========================================================================
    // VisibilityResultStore
    // =========================================================================

    #[test]
    fn result_store_empty_initially() {
        let s = VisibilityResultStore::new();
        assert!(s.is_empty());
    }

    #[test]
    fn result_store_and_retrieve_at_same_tick() {
        let mut s = VisibilityResultStore::new();
        s.store(VisibilityQueryResult::new(1, 2, true, 15.0, 5));
        let r = s.get(1, 2, 5).unwrap();
        assert!(r.can_see);
        assert!((r.distance - 15.0).abs() < 1e-5);
    }

    #[test]
    fn result_store_valid_one_tick_later() {
        let mut s = VisibilityResultStore::new();
        s.store(VisibilityQueryResult::new(1, 2, false, 0.0, 10));
        assert!(s.get(1, 2, 11).is_some()); // tick+1 still valid
    }

    #[test]
    fn result_store_expired_two_ticks_later() {
        let mut s = VisibilityResultStore::new();
        s.store(VisibilityQueryResult::new(1, 2, true, 10.0, 10));
        assert!(s.get(1, 2, 12).is_none()); // tick+2 expired
    }

    #[test]
    fn result_store_can_see_convenience() {
        let mut s = VisibilityResultStore::new();
        s.store(VisibilityQueryResult::new(1, 2, true, 10.0, 5));
        assert_eq!(s.can_see(1, 2, 5), Some(true));
        assert_eq!(s.can_see(9, 9, 5), None); // not stored
    }

    #[test]
    fn result_store_expire_tick_removes_old_results() {
        let mut s = VisibilityResultStore::new();
        s.store(VisibilityQueryResult::new(1, 2, true, 10.0, 3));
        s.store(VisibilityQueryResult::new(3, 4, false, 0.0, 7));
        s.store(VisibilityQueryResult::new(5, 6, true, 20.0, 8));
        // At tick 8: result from tick 3 expired, ticks 7 and 8 valid
        let expired = s.expire_tick(8);
        assert_eq!(expired, 1);
        assert_eq!(s.stored_count(), 2);
    }

    #[test]
    fn result_store_expire_all_when_far_ahead() {
        let mut s = VisibilityResultStore::new();
        for i in 0..5 {
            s.store(VisibilityQueryResult::new(i + 1, i + 100, true, 5.0, i));
        }
        s.expire_tick(100); // all expired
        assert!(s.is_empty());
    }

    #[test]
    fn result_store_metrics_track_hits_and_misses() {
        let mut s = VisibilityResultStore::new();
        s.store(VisibilityQueryResult::new(1, 2, true, 5.0, 1));
        s.get(1, 2, 1); // hit
        s.get(1, 2, 1); // hit
        s.get(3, 4, 1); // miss
        let m = s.metrics();
        assert_eq!(m.cache_hits, 2);
        assert_eq!(m.cache_misses, 1);
    }

    // =========================================================================
    // VisibilityFeedbackHandler
    // =========================================================================

    #[test]
    fn handler_processes_valid_visibility_result() {
        let h = VisibilityFeedbackHandler::new();
        h.handle(&vis_feedback(1, 2, true, 15.0, 1)).unwrap();
        assert_eq!(h.results_processed(), 1);
        assert_eq!(h.visible_count(), 1);
    }

    #[test]
    fn handler_counts_occluded_correctly() {
        let h = VisibilityFeedbackHandler::new();
        h.handle(&vis_feedback(1, 2, false, 0.0, 1)).unwrap();
        assert_eq!(h.occluded_count(), 1);
        assert_eq!(h.visible_count(), 0);
    }

    #[test]
    fn handler_rejects_null_observer() {
        let h = VisibilityFeedbackHandler::new();
        assert!(h.handle(&vis_feedback(0, 2, true, 10.0, 1)).is_err());
    }

    #[test]
    fn handler_rejects_null_target() {
        let h = VisibilityFeedbackHandler::new();
        assert!(h.handle(&vis_feedback(1, 0, true, 10.0, 1)).is_err());
    }

    #[test]
    fn handler_rejects_negative_distance() {
        let h = VisibilityFeedbackHandler::new();
        assert!(h.handle(&vis_feedback(1, 2, false, -5.0, 1)).is_err());
    }

    // =========================================================================
    // Full Pipeline: Query → Batcher → Handler → Store → AI Read
    // =========================================================================

    #[test]
    fn full_visibility_pipeline() {
        // Tick N: AI submits query for entity 1 to see entity 2
        let mut batcher = VisibilityQueryBatcher::with_defaults();
        batcher.add(1, 2, 50.0);
        let batch = batcher.take_batch();
        assert_eq!(batch.len(), 1);

        // Engine processes raycast and returns result (simulated)
        let handler = VisibilityFeedbackHandler::new();
        let result_payload = vis_feedback(1, 2, true, 15.5, 5);
        handler.handle(&result_payload).unwrap();
        assert_eq!(handler.results_processed(), 1);

        // Store the result so AI can read it next tick
        let mut store = VisibilityResultStore::new();
        store.store(VisibilityQueryResult::new(1, 2, true, 15.5, 5));

        // Tick N+1: AI reads the result
        let result = store.get(1, 2, 6).unwrap(); // tick+1 still valid
        assert!(result.can_see);
        assert!((result.distance - 15.5).abs() < 1e-5);

        // Tick N+2: result expired
        assert!(store.get(1, 2, 7).is_none());
    }

    #[test]
    fn multiple_observers_all_results_stored() {
        let mut store = VisibilityResultStore::new();
        let handler = VisibilityFeedbackHandler::new();

        // Multiple AI agents checking visibility to same target
        let results = vec![
            vis_feedback(1, 99, true, 10.0, 5),
            vis_feedback(2, 99, false, 0.0, 5),
            vis_feedback(3, 99, true, 25.0, 5),
        ];

        for r in &results {
            handler.handle(r).unwrap();
        }
        assert_eq!(handler.results_processed(), 3);
        assert_eq!(handler.visible_count(), 2);
        assert_eq!(handler.occluded_count(), 1);

        // Store results
        store.store(VisibilityQueryResult::new(1, 99, true, 10.0, 5));
        store.store(VisibilityQueryResult::new(2, 99, false, 0.0, 5));
        store.store(VisibilityQueryResult::new(3, 99, true, 25.0, 5));

        assert_eq!(store.stored_count(), 3);
        assert_eq!(store.can_see(1, 99, 5), Some(true));
        assert_eq!(store.can_see(2, 99, 5), Some(false));
        assert_eq!(store.can_see(3, 99, 5), Some(true));
    }
}