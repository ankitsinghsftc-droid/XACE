//! # Feedback Buffer Integration Tests
//!
//! Integration tests for the complete feedback pipeline:
//! FeedbackBuffer → FeedbackValidator → FeedbackRouter → Handlers
//!
//! ## Coverage
//! - Buffer accumulation across multiple ticks
//! - Deterministic drain ordering (I13, D9)
//! - Validator filtering with all rejection types
//! - Router dispatch to correct handlers
//! - End-to-end: append → drain → validate → route
//! - Thread safety: concurrent appends with single drain
//! - FeedbackLog recording and retrieval
//! - FeedbackReplayLoader injection into buffer

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;
    use std::sync::Arc;

    use xace_core::wire::feedback_payload::{
        AnimationStateUpdateFeedback, FeedbackMessage, FeedbackType,
        PerformanceMetricsFeedback, PhysicsSettledFeedback, VisibilityQueryResultFeedback,
    };

    use crate::feedback_buffer::FeedbackBuffer;
    use crate::feedback_log::FeedbackLog;
    use crate::feedback_message::{FeedbackMessageExt, TypedFeedbackPayload};
    use crate::feedback_replay_loader::FeedbackReplayLoader;
    use crate::feedback_router::FeedbackRouter;
    use crate::feedback_validator::{FeedbackValidator, ValidatorConfig};
    use crate::handlers::physics_feedback_handler::PhysicsFeedbackHandler;
    use crate::handlers::performance_feedback_handler::PerformanceFeedbackHandler;

    // ── Message Factories ─────────────────────────────────────────────────────

    fn physics_msg(entity_id: u64, frame: u64) -> FeedbackMessage {
        FeedbackMessage {
            feedback_type: FeedbackType::PhysicsSettled,
            entity_id,
            generated_frame: frame,
            payload_json: serde_json::to_string(&PhysicsSettledFeedback {
                entity_id,
                final_position_json: r#"{"x":1.0,"y":0.0,"z":0.0}"#.into(),
                final_rotation_json: r#"{"x":0.0,"y":0.0,"z":0.0,"w":1.0}"#.into(),
                generated_frame: frame,
            }).unwrap(),
        }
    }

    fn anim_msg(entity_id: u64, frame: u64) -> FeedbackMessage {
        FeedbackMessage {
            feedback_type: FeedbackType::AnimationStateUpdate,
            entity_id,
            generated_frame: frame,
            payload_json: serde_json::to_string(&AnimationStateUpdateFeedback {
                entity_id,
                active_state_per_layer: BTreeMap::from([("base".into(), "run".into())]),
                normalized_time_per_layer: BTreeMap::from([("base".into(), 0.5)]),
                is_transitioning: false,
                generated_frame: frame,
            }).unwrap(),
        }
    }

    fn perf_msg(frame: u64) -> FeedbackMessage {
        FeedbackMessage {
            feedback_type: FeedbackType::PerformanceMetrics,
            entity_id: 0,
            generated_frame: frame,
            payload_json: serde_json::to_string(&PerformanceMetricsFeedback {
                engine_delta_apply_ms: 8.5,
                draw_calls: 1200,
                physics_contacts: 30,
                engine_entity_count: 200,
                generated_frame: frame,
            }).unwrap(),
        }
    }

    fn vis_msg(observer: u64, target: u64, frame: u64) -> FeedbackMessage {
        FeedbackMessage {
            feedback_type: FeedbackType::VisibilityQueryResult,
            entity_id: observer,
            generated_frame: frame,
            payload_json: serde_json::to_string(&VisibilityQueryResultFeedback {
                observer_entity_id: observer,
                target_entity_id: target,
                can_see: true,
                distance: 15.0,
                generated_frame: frame,
            }).unwrap(),
        }
    }

    fn bad_json_msg(ft: FeedbackType, entity_id: u64) -> FeedbackMessage {
        FeedbackMessage {
            feedback_type: ft,
            entity_id,
            generated_frame: 1,
            payload_json: "not valid json".into(),
        }
    }

    // =========================================================================
    // FeedbackBuffer — Core Behaviour
    // =========================================================================

    #[test]
    fn buffer_empty_initially() {
        let b = FeedbackBuffer::new();
        assert!(b.is_empty());
    }

    #[test]
    fn buffer_append_and_drain_roundtrip() {
        let b = FeedbackBuffer::new();
        b.append(physics_msg(1, 1));
        b.append(physics_msg(2, 2));
        let drained = b.drain_sorted();
        assert_eq!(drained.len(), 2);
        assert!(b.is_empty());
    }

    #[test]
    fn buffer_drain_sorted_by_frame_then_entity() {
        let b = FeedbackBuffer::new();
        b.append(physics_msg(5, 10));
        b.append(physics_msg(1, 8));
        b.append(physics_msg(3, 10));
        let drained = b.drain_sorted();
        // Frame 8 comes first, then frame 10 sorted by entity
        assert_eq!(drained[0].generated_frame, 8);
        assert_eq!(drained[1].generated_frame, 10);
        assert_eq!(drained[1].entity_id, 3);
        assert_eq!(drained[2].entity_id, 5);
    }

    #[test]
    fn buffer_drain_deterministic_across_identical_inputs() {
        let fill = || {
            let b = FeedbackBuffer::new();
            b.append(physics_msg(3, 2));
            b.append(physics_msg(1, 1));
            b.append(physics_msg(2, 2));
            b
        };
        let order_a: Vec<u64> = fill().drain_sorted().iter().map(|m| m.entity_id).collect();
        let order_b: Vec<u64> = fill().drain_sorted().iter().map(|m| m.entity_id).collect();
        assert_eq!(order_a, order_b, "Drain order must be deterministic (D9)");
    }

    #[test]
    fn buffer_append_batch_all_arrive() {
        let b = FeedbackBuffer::new();
        b.append_batch(vec![physics_msg(1, 1), anim_msg(2, 1), perf_msg(1)]);
        assert_eq!(b.pending_count(), 3);
    }

    #[test]
    fn buffer_clear_removes_all() {
        let b = FeedbackBuffer::new();
        b.append(physics_msg(1, 1));
        b.clear();
        assert!(b.is_empty());
    }

    // =========================================================================
    // FeedbackBuffer — Thread Safety
    // =========================================================================

    #[test]
    fn concurrent_appends_all_arrive_in_drain() {
        use std::thread;

        let buffer = FeedbackBuffer::new();
        let mut handles = vec![];

        for i in 0..20u64 {
            let b = buffer.clone();
            handles.push(thread::spawn(move || {
                b.append(physics_msg(i + 1, i));
            }));
        }
        for h in handles { h.join().unwrap(); }

        let drained = buffer.drain_sorted();
        assert_eq!(drained.len(), 20);
    }

    // =========================================================================
    // FeedbackValidator — Filtering
    // =========================================================================

    #[test]
    fn validator_passes_valid_messages() {
        let mut v = FeedbackValidator::with_defaults();
        assert!(v.validate(&physics_msg(1, 1)).is_valid());
        assert!(v.validate(&anim_msg(2, 2)).is_valid());
        assert!(v.validate(&perf_msg(3)).is_valid());
    }

    #[test]
    fn validator_rejects_empty_payload() {
        let mut v = FeedbackValidator::with_defaults();
        let bad = FeedbackMessage {
            feedback_type: FeedbackType::PhysicsSettled,
            entity_id: 1,
            generated_frame: 1,
            payload_json: String::new(),
        };
        assert!(!v.validate(&bad).is_valid());
    }

    #[test]
    fn validator_rejects_invalid_json() {
        let mut v = FeedbackValidator::with_defaults();
        assert!(!v.validate(&bad_json_msg(FeedbackType::PhysicsSettled, 1)).is_valid());
    }

    #[test]
    fn validator_rejects_null_entity_for_physics() {
        let mut v = FeedbackValidator::with_defaults();
        assert!(!v.validate(&physics_msg(0, 1)).is_valid());
    }

    #[test]
    fn validator_allows_null_entity_for_performance_metrics() {
        let mut v = FeedbackValidator::with_defaults();
        assert!(v.validate(&perf_msg(1)).is_valid()); // entity_id=0 allowed
    }

    #[test]
    fn validator_filter_valid_keeps_valid_subset() {
        let mut v = FeedbackValidator::with_defaults();
        let messages = vec![
            physics_msg(1, 1),
            bad_json_msg(FeedbackType::AudioComplete, 2),
            anim_msg(3, 3),
            physics_msg(0, 4), // null entity
        ];
        let valid = v.filter_valid(messages);
        assert_eq!(valid.len(), 2);
    }

    #[test]
    fn validator_reset_for_next_tick_allows_re_validation() {
        let mut v = FeedbackValidator::with_defaults();
        v.validate(&physics_msg(1, 5)); // primes dedup set
        v.reset_for_next_tick();
        // Same message should be valid again after reset
        assert!(v.validate(&physics_msg(1, 5)).is_valid());
    }

    // =========================================================================
    // FeedbackRouter — Dispatch
    // =========================================================================

    #[test]
    fn router_dispatches_physics_to_physics_handler() {
        let mut r = FeedbackRouter::new();
        let h = PhysicsFeedbackHandler::new();
        // We can't move h and still track it without Arc, so test via route result
        r.register(Box::new(PhysicsFeedbackHandler::new()));
        assert!(r.route(&physics_msg(1, 1)).is_ok());
        assert_eq!(r.metrics().total_routed, 1);
    }

    #[test]
    fn router_dispatches_perf_to_perf_handler() {
        let mut r = FeedbackRouter::new();
        r.register(Box::new(PerformanceFeedbackHandler::new()));
        assert!(r.route(&perf_msg(1)).is_ok());
        assert_eq!(r.metrics().total_routed, 1);
    }

    #[test]
    fn router_unhandled_type_logs_and_continues() {
        let mut r = FeedbackRouter::new();
        // No handler registered for physics
        let result = r.route(&physics_msg(1, 1));
        assert!(result.is_ok());
        assert_eq!(r.metrics().unhandled_count, 1);
    }

    #[test]
    fn router_route_all_accumulates_errors() {
        let mut r = FeedbackRouter::new();
        r.register(Box::new(PhysicsFeedbackHandler::new()));
        // Send bad JSON — parse will fail
        let bad = bad_json_msg(FeedbackType::PhysicsSettled, 1);
        let errors = r.route_all(vec![bad, physics_msg(1, 1)]);
        assert_eq!(errors.len(), 1); // one parse failure, one success
        assert_eq!(r.metrics().parse_failures, 1);
        assert_eq!(r.metrics().total_routed, 1);
    }

    // =========================================================================
    // End-to-End Pipeline: Buffer → Validate → Route
    // =========================================================================

    #[test]
    fn full_pipeline_processes_mixed_batch() {
        let buffer = FeedbackBuffer::new();

        // Simulate engine adapter appending multiple feedback types
        buffer.append(physics_msg(1, 5));
        buffer.append(anim_msg(2, 5));
        buffer.append(perf_msg(5));
        buffer.append(bad_json_msg(FeedbackType::PhysicsSettled, 99)); // invalid

        // Tick START: drain and validate
        let mut validator = FeedbackValidator::with_defaults();
        let raw = buffer.drain_sorted();
        let valid = validator.filter_valid(raw);

        // Valid: physics(1), anim(2), perf — bad_json rejected
        assert_eq!(valid.len(), 3);
        assert_eq!(validator.metrics().messages_invalid, 1);

        // Route valid messages
        let mut router = FeedbackRouter::new();
        router.register(Box::new(PhysicsFeedbackHandler::new()));
        router.register(Box::new(PerformanceFeedbackHandler::new()));

        let errors = router.route_all(valid);
        // anim has no handler registered — unhandled (not an error)
        assert!(errors.is_empty());
        assert_eq!(router.metrics().total_routed, 2); // physics + perf
        assert_eq!(router.metrics().unhandled_count, 1); // anim
    }

    // =========================================================================
    // FeedbackLog
    // =========================================================================

    #[test]
    fn feedback_log_records_and_retrieves_by_tick() {
        let mut log = FeedbackLog::new("0.1.0", 1);
        log.record_tick(1, vec![physics_msg(1, 1), anim_msg(2, 1)]);
        log.record_tick(2, vec![perf_msg(2)]);

        assert_eq!(log.messages_at(1).len(), 2);
        assert_eq!(log.messages_at(2).len(), 1);
        assert_eq!(log.messages_at(99).len(), 0);
    }

    #[test]
    fn feedback_log_serializes_to_json_and_back() {
        let mut log = FeedbackLog::new("0.1.0", 1);
        log.record_tick(5, vec![physics_msg(1, 5)]);
        log.record_tick(6, vec![anim_msg(2, 6)]);

        let json = serde_json::to_string(&log).unwrap();
        let restored: FeedbackLog = serde_json::from_str(&json).unwrap();
        assert_eq!(restored.tick_count(), 2);
        assert_eq!(restored.messages_at(5).len(), 1);
    }

    #[test]
    fn feedback_log_trim_before_removes_old_entries() {
        let mut log = FeedbackLog::new("0.1.0", 1);
        for tick in 0..10 {
            log.record_tick(tick, vec![physics_msg(1, tick)]);
        }
        log.trim_before(5);
        assert_eq!(log.tick_count(), 5); // ticks 5-9 remain
    }

    // =========================================================================
    // FeedbackReplayLoader
    // =========================================================================

    #[test]
    fn replay_loader_injects_correct_messages_per_tick() {
        let buffer = FeedbackBuffer::new();
        let mut loader = FeedbackReplayLoader::new(buffer.clone(), "0.1.0", 1);

        let mut log = FeedbackLog::new("0.1.0", 1);
        log.record_tick(1, vec![physics_msg(1, 1), anim_msg(2, 1)]);
        log.record_tick(2, vec![perf_msg(2)]);

        loader.begin_replay(log).unwrap();

        loader.inject_for_tick(1).unwrap();
        let drained_tick1 = buffer.drain_sorted();
        assert_eq!(drained_tick1.len(), 2);

        loader.inject_for_tick(2).unwrap();
        let drained_tick2 = buffer.drain_sorted();
        assert_eq!(drained_tick2.len(), 1);
        assert_eq!(drained_tick2[0].feedback_type, FeedbackType::PerformanceMetrics);
    }

    #[test]
    fn replay_loader_rejects_incompatible_schema() {
        let buffer = FeedbackBuffer::new();
        let mut loader = FeedbackReplayLoader::new(buffer, "0.1.0", 1);
        let log = FeedbackLog::new("9.9.9", 1); // wrong schema
        assert!(loader.begin_replay(log).is_err());
    }

    #[test]
    fn replay_loader_finish_produces_correct_report() {
        let buffer = FeedbackBuffer::new();
        let mut loader = FeedbackReplayLoader::new(buffer.clone(), "0.1.0", 1);

        let mut log = FeedbackLog::new("0.1.0", 1);
        log.record_tick(1, vec![physics_msg(1, 1)]);
        log.record_tick(2, vec![]);
        log.record_tick(3, vec![anim_msg(1, 3), anim_msg(2, 3)]);

        loader.begin_replay(log).unwrap();
        loader.inject_for_tick(1).unwrap();
        loader.inject_for_tick(2).unwrap();
        loader.inject_for_tick(3).unwrap();

        let report = loader.finish_replay();
        assert_eq!(report.ticks_processed, 3);
        assert_eq!(report.ticks_with_feedback, 2);
        assert_eq!(report.ticks_without_feedback, 1);
        assert_eq!(report.total_messages_injected, 3);
        assert!(report.full_coverage);
    }

    // =========================================================================
    // TypedFeedbackPayload Parsing
    // =========================================================================

    #[test]
    fn parse_typed_physics_settled() {
        let msg = physics_msg(5, 1);
        let typed = msg.parse_typed().unwrap();
        assert!(matches!(typed, TypedFeedbackPayload::PhysicsSettled(_)));
        assert_eq!(typed.feedback_type(), FeedbackType::PhysicsSettled);
    }

    #[test]
    fn parse_typed_animation_state_update() {
        let msg = anim_msg(3, 1);
        let typed = msg.parse_typed().unwrap();
        assert!(matches!(typed, TypedFeedbackPayload::AnimationStateUpdate(_)));
    }

    #[test]
    fn parse_typed_performance_metrics() {
        let msg = perf_msg(1);
        let typed = msg.parse_typed().unwrap();
        assert!(matches!(typed, TypedFeedbackPayload::PerformanceMetrics(_)));
    }

    #[test]
    fn parse_typed_bad_json_returns_err() {
        let msg = bad_json_msg(FeedbackType::PhysicsSettled, 1);
        assert!(msg.parse_typed().is_err());
    }

    #[test]
    fn sort_key_ordering_matches_drain_order() {
        // Manually verify sort_key produces same ordering as drain_sorted
        let msgs = vec![
            physics_msg(5, 10),
            physics_msg(1, 8),
            physics_msg(3, 10),
        ];
        let mut sorted = msgs.clone();
        sorted.sort_by_key(|m| m.sort_key());

        assert_eq!(sorted[0].generated_frame, 8);
        assert_eq!(sorted[1].generated_frame, 10);
        assert_eq!(sorted[1].entity_id, 3);
        assert_eq!(sorted[2].entity_id, 5);
    }
}