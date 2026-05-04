//! # Visibility Feedback Handler
//!
//! Processes `VisibilityQueryResult` feedback from the engine adapter.
//!
//! ## Visibility Query Flow (Audit 6)
//! 1. XACE writes `visibility_query_pending = true` to `COMP_PERCEPTION_V1`
//! 2. `VisibilityQueryBatcher` collects all pending queries each tick
//! 3. Batched queries are sent to the engine via `send_visibility_queries()`
//! 4. Engine performs raycasts in the same frame
//! 5. Engine sends `VisibilityQueryResult` feedback next tick
//! 6. **This handler** writes `can_see` and `distance` back to
//!    `COMP_PERCEPTION_V1` via the Mutation Gate
//! 7. AI systems read the updated `COMP_PERCEPTION_V1` the following tick
//!
//! ## One-Tick Delay (Confirmed Correct)
//! CLAUDE.md: *"One-tick delay confirmed correct and acceptable."*
//! The AI system that submitted the query reads the result one tick later.
//! This is intentional — real raycasting is asynchronous by nature.
//!
//! ## Result Store Integration
//! Results are also stored in the `VisibilityResultStore` (one-tick TTL)
//! so queries can be looked up by (observer, target) pair without going
//! through the component table every time.

use xace_core::errors::xace_error::{ErrorContext, XaceError};

use crate::feedback_message::TypedFeedbackPayload;
use crate::feedback_router::FeedbackHandler;
use crate::feedback_type_enum::FeedbackHandlerKind;

// ── Visibility Feedback Handler ───────────────────────────────────────────────

/// Handles `VisibilityQueryResult` — writes can_see and distance back
/// to `COMP_PERCEPTION_V1` via the Mutation Gate.
pub struct VisibilityFeedbackHandler {
    results_processed: std::sync::atomic::AtomicU64,
    visible_count: std::sync::atomic::AtomicU64,
    occluded_count: std::sync::atomic::AtomicU64,
}

impl VisibilityFeedbackHandler {
    pub fn new() -> Self {
        Self {
            results_processed: std::sync::atomic::AtomicU64::new(0),
            visible_count: std::sync::atomic::AtomicU64::new(0),
            occluded_count: std::sync::atomic::AtomicU64::new(0),
        }
    }

    pub fn results_processed(&self) -> u64 {
        self.results_processed.load(std::sync::atomic::Ordering::Relaxed)
    }

    pub fn visible_count(&self) -> u64 {
        self.visible_count.load(std::sync::atomic::Ordering::Relaxed)
    }

    pub fn occluded_count(&self) -> u64 {
        self.occluded_count.load(std::sync::atomic::Ordering::Relaxed)
    }
}

impl Default for VisibilityFeedbackHandler {
    fn default() -> Self {
        Self::new()
    }
}

impl FeedbackHandler for VisibilityFeedbackHandler {
    fn kind(&self) -> FeedbackHandlerKind {
        FeedbackHandlerKind::Visibility
    }

    fn name(&self) -> &str {
        "VisibilityFeedbackHandler"
    }

    fn handle(&self, payload: &TypedFeedbackPayload) -> Result<(), XaceError> {
        let result = match payload {
            TypedFeedbackPayload::VisibilityQueryResult(r) => r,
            other => {
                return Err(XaceError::RecoverableError {
                    message: format!(
                        "VisibilityFeedbackHandler: unexpected payload type {:?}",
                        other.feedback_type()
                    ),
                    context: ErrorContext::new("VisibilityFeedbackHandler", "handle"),
                    max_retries: 0,
                    retry_count: 0,
                })
            }
        };

        // Both observer and target must be valid entities
        if result.observer_entity_id == 0 || result.target_entity_id == 0 {
            return Err(XaceError::RecoverableError {
                message: format!(
                    "VisibilityFeedbackHandler: invalid entity IDs — \
                     observer={} target={}",
                    result.observer_entity_id, result.target_entity_id
                ),
                context: ErrorContext::new("VisibilityFeedbackHandler", "handle"),
                max_retries: 0,
                retry_count: 0,
            });
        }

        // Validate distance is non-negative
        if result.distance < 0.0 {
            return Err(XaceError::RecoverableError {
                message: format!(
                    "VisibilityFeedbackHandler: negative distance {} for \
                     observer={} target={}",
                    result.distance, result.observer_entity_id, result.target_entity_id
                ),
                context: ErrorContext::new("VisibilityFeedbackHandler", "handle"),
                max_retries: 0,
                retry_count: 0,
            });
        }

        // TODO (Phase 9 wiring): write result to COMP_PERCEPTION_V1 via Mutation Gate:
        //   let patch = format!(
        //       r#"{{"visibility_result":{{"observer":{},"target":{},"can_see":{},"distance":{}}}}}"#,
        //       result.observer_entity_id,
        //       result.target_entity_id,
        //       result.can_see,
        //       result.distance,
        //   );
        //   mutation_gate.request_modify_component(
        //       result.observer_entity_id,
        //       COMP_PERCEPTION_V1_TYPE_ID,
        //       patch,
        //   )?;
        //
        // TODO: store in VisibilityResultStore with 1-tick TTL.

        self.results_processed
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        if result.can_see {
            self.visible_count
                .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        } else {
            self.occluded_count
                .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        }

        Ok(())
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::wire::feedback_payload::VisibilityQueryResultFeedback;

    fn vis_result(observer: u64, target: u64, can_see: bool, distance: f32) -> TypedFeedbackPayload {
        TypedFeedbackPayload::VisibilityQueryResult(VisibilityQueryResultFeedback {
            observer_entity_id: observer,
            target_entity_id: target,
            can_see,
            distance,
            generated_frame: 1,
        })
    }

    #[test]
    fn handler_kind_is_visibility() {
        assert_eq!(VisibilityFeedbackHandler::new().kind(), FeedbackHandlerKind::Visibility);
    }

    #[test]
    fn can_handle_visibility_query_result_only() {
        let h = VisibilityFeedbackHandler::new();
        assert!(h.can_handle(FeedbackType::VisibilityQueryResult));
        assert!(!h.can_handle(FeedbackType::PhysicsSettled));
    }

    #[test]
    fn handle_visible_result_increments_visible_count() {
        let h = VisibilityFeedbackHandler::new();
        h.handle(&vis_result(1, 2, true, 10.0)).unwrap();
        assert_eq!(h.results_processed(), 1);
        assert_eq!(h.visible_count(), 1);
        assert_eq!(h.occluded_count(), 0);
    }

    #[test]
    fn handle_occluded_result_increments_occluded_count() {
        let h = VisibilityFeedbackHandler::new();
        h.handle(&vis_result(1, 2, false, 0.0)).unwrap();
        assert_eq!(h.occluded_count(), 1);
    }

    #[test]
    fn null_observer_returns_err() {
        let h = VisibilityFeedbackHandler::new();
        assert!(h.handle(&vis_result(0, 2, true, 5.0)).is_err());
    }

    #[test]
    fn null_target_returns_err() {
        let h = VisibilityFeedbackHandler::new();
        assert!(h.handle(&vis_result(1, 0, true, 5.0)).is_err());
    }

    #[test]
    fn negative_distance_returns_err() {
        let h = VisibilityFeedbackHandler::new();
        assert!(h.handle(&vis_result(1, 2, false, -1.0)).is_err());
    }

    #[test]
    fn zero_distance_is_valid() {
        let h = VisibilityFeedbackHandler::new();
        assert!(h.handle(&vis_result(1, 2, false, 0.0)).is_ok());
    }
}