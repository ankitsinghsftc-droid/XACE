//! # Animation Feedback Handler
//!
//! Processes `AnimationStateUpdate` and `AnimationEventFired` feedback
//! from the engine adapter.
//!
//! ## AnimationStateUpdate
//! The engine writes back animation state every tick:
//! - `current_normalized_time` — playback position (0.0–1.0) per layer
//! - `is_transitioning` — whether the animator is mid-transition
//! - `active_state_per_layer` — current state name per layer
//!
//! These are written to `COMP_ANIMATION_V2` fields via the Mutation Gate.
//! XACE's authoritative `COMP_ANIMATION_V2` then reflects actual engine state
//! rather than the last command XACE sent — closing the feedback loop (Audit 3).
//!
//! ## AnimationEventFired
//! When a pending_event trigger point is reached in the engine animator,
//! the engine sends `AnimationEventFired`. The handler:
//! 1. Emits the associated game event through the EventBus
//! 2. Marks the pending_event as consumed in `COMP_ANIMATION_V2`
//!
//! This replaces the old "floating string" animation event model — animation
//! events are now first-class game events with full EventBus routing (Audit 3).

use xace_core::wire::feedback_payload::FeedbackType;

use crate::feedback_message::TypedFeedbackPayload;
use crate::feedback_router::FeedbackHandler;
use crate::feedback_type_enum::FeedbackHandlerKind;
use xace_core::errors::xace_error::{ErrorContext, XaceError};

// ── Animation Feedback Handler ────────────────────────────────────────────────

/// Handles `AnimationStateUpdate` and `AnimationEventFired` feedback.
///
/// In Phase 7, writes are logged (full Mutation Gate integration in Phase 9
/// when systems are wired together). The handler validates the payload and
/// records what would be written — full write-back happens in the
/// animation system wiring pass.
pub struct AnimationFeedbackHandler {
    /// Counts processed per type for metrics.
    state_update_count: std::sync::atomic::AtomicU64,
    event_fired_count: std::sync::atomic::AtomicU64,
}

impl AnimationFeedbackHandler {
    pub fn new() -> Self {
        Self {
            state_update_count: std::sync::atomic::AtomicU64::new(0),
            event_fired_count: std::sync::atomic::AtomicU64::new(0),
        }
    }

    pub fn state_update_count(&self) -> u64 {
        self.state_update_count.load(std::sync::atomic::Ordering::Relaxed)
    }

    pub fn event_fired_count(&self) -> u64 {
        self.event_fired_count.load(std::sync::atomic::Ordering::Relaxed)
    }
}

impl Default for AnimationFeedbackHandler {
    fn default() -> Self {
        Self::new()
    }
}

impl FeedbackHandler for AnimationFeedbackHandler {
    fn kind(&self) -> FeedbackHandlerKind {
        FeedbackHandlerKind::Animation
    }

    fn name(&self) -> &str {
        "AnimationFeedbackHandler"
    }

    fn can_handle(&self, ft: FeedbackType) -> bool {
        matches!(
            ft,
            FeedbackType::AnimationStateUpdate | FeedbackType::AnimationEventFired
        )
    }

    fn handle(&self, payload: &TypedFeedbackPayload) -> Result<(), XaceError> {
        match payload {
            TypedFeedbackPayload::AnimationStateUpdate(update) => {
                // Validate entity is present
                if update.entity_id == 0 {
                    return Err(XaceError::RecoverableError {
                        message: "AnimationFeedbackHandler: AnimationStateUpdate has null entity_id".into(),
                        context: ErrorContext::new("AnimationFeedbackHandler", "handle_state_update"),
                        max_retries: 0,
                        retry_count: 0,
                    });
                }

                // TODO (Phase 9 wiring): write back to COMP_ANIMATION_V2 via Mutation Gate:
                //   - active_state_per_layer   ← update.active_state_per_layer
                //   - normalized_time          ← update.normalized_time_per_layer
                //   - is_transitioning         ← update.is_transitioning
                //
                // mutation_gate.request_modify_component(
                //     update.entity_id,
                //     COMP_ANIMATION_V2_TYPE_ID,
                //     build_animation_patch(update),
                // )?;

                self.state_update_count
                    .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                Ok(())
            }

            TypedFeedbackPayload::AnimationEventFired(fired) => {
                if fired.entity_id == 0 {
                    return Err(XaceError::RecoverableError {
                        message: "AnimationFeedbackHandler: AnimationEventFired has null entity_id".into(),
                        context: ErrorContext::new("AnimationFeedbackHandler", "handle_event_fired"),
                        max_retries: 0,
                        retry_count: 0,
                    });
                }

                // TODO (Phase 9 wiring): emit the associated game event via EventBus:
                //   let event = Event::broadcast(
                //       fired.entity_id,
                //       EventType::Domain(fired.event_id.clone()),
                //       current_tick,
                //       PhaseEnum::PostSimulation,
                //   ).with_payload("state_name", &fired.state_name)
                //    .with_payload("normalized_time", &fired.trigger_at_normalized_time.to_string());
                //   event_bus.emit(event)?;
                //
                // TODO: mark pending_event as consumed in COMP_ANIMATION_V2 via Mutation Gate.

                self.event_fired_count
                    .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                Ok(())
            }

            other => Err(XaceError::RecoverableError {
                message: format!(
                    "AnimationFeedbackHandler: received unexpected payload type {:?}",
                    other.feedback_type()
                ),
                context: ErrorContext::new("AnimationFeedbackHandler", "handle"),
                max_retries: 0,
                retry_count: 0,
            }),
        }
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;
    use xace_core::wire::feedback_payload::{
        AnimationEventFiredFeedback, AnimationStateUpdateFeedback,
    };

    fn state_update(entity_id: u64) -> TypedFeedbackPayload {
        TypedFeedbackPayload::AnimationStateUpdate(AnimationStateUpdateFeedback {
            entity_id,
            active_state_per_layer: BTreeMap::from([("base".into(), "run".into())]),
            normalized_time_per_layer: BTreeMap::from([("base".into(), 0.5)]),
            is_transitioning: false,
            generated_frame: 1,
        })
    }

    fn event_fired(entity_id: u64) -> TypedFeedbackPayload {
        TypedFeedbackPayload::AnimationEventFired(AnimationEventFiredFeedback {
            entity_id,
            event_id: "footstep".into(),
            state_name: "run".into(),
            trigger_at_normalized_time: 0.3,
            generated_frame: 1,
        })
    }

    #[test]
    fn handler_kind_is_animation() {
        assert_eq!(AnimationFeedbackHandler::new().kind(), FeedbackHandlerKind::Animation);
    }

    #[test]
    fn can_handle_both_animation_types() {
        let h = AnimationFeedbackHandler::new();
        assert!(h.can_handle(FeedbackType::AnimationStateUpdate));
        assert!(h.can_handle(FeedbackType::AnimationEventFired));
        assert!(!h.can_handle(FeedbackType::PhysicsSettled));
    }

    #[test]
    fn handle_state_update_valid_entity() {
        let h = AnimationFeedbackHandler::new();
        assert!(h.handle(&state_update(1)).is_ok());
        assert_eq!(h.state_update_count(), 1);
    }

    #[test]
    fn handle_state_update_null_entity_returns_err() {
        let h = AnimationFeedbackHandler::new();
        assert!(h.handle(&state_update(0)).is_err());
    }

    #[test]
    fn handle_event_fired_valid_entity() {
        let h = AnimationFeedbackHandler::new();
        assert!(h.handle(&event_fired(5)).is_ok());
        assert_eq!(h.event_fired_count(), 1);
    }

    #[test]
    fn handle_event_fired_null_entity_returns_err() {
        let h = AnimationFeedbackHandler::new();
        assert!(h.handle(&event_fired(0)).is_err());
    }

    #[test]
    fn handle_wrong_payload_type_returns_err() {
        let h = AnimationFeedbackHandler::new();
        let wrong = TypedFeedbackPayload::AudioPositionUpdate {
            entity_id: 1,
            position_json: "{}".into(),
        };
        assert!(h.handle(&wrong).is_err());
    }

    #[test]
    fn counts_accumulate_across_calls() {
        let h = AnimationFeedbackHandler::new();
        for _ in 0..5 {
            h.handle(&state_update(1)).ok();
        }
        for _ in 0..3 {
            h.handle(&event_fired(1)).ok();
        }
        assert_eq!(h.state_update_count(), 5);
        assert_eq!(h.event_fired_count(), 3);
    }
}