//! Animation feedback handler.
//!
//! The handler validates animation feedback from engine adapters and records
//! deterministic actions for the runtime to apply later through Mutation Gate
//! and EventBus. It never mutates authoritative state directly, preserving I2,
//! I5, I9, I13, and D13 from `CLAUDE.md`.

use std::collections::BTreeMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, MutexGuard};

use xace_core::entity_id::EntityID;
use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::wire::feedback_payload::FeedbackType;

use crate::feedback_message::TypedFeedbackPayload;
use crate::feedback_router::FeedbackHandler;
use crate::feedback_type_enum::FeedbackHandlerKind;

#[derive(Debug, Clone, PartialEq)]
pub struct AnimationStateWriteAction {
    pub entity_id: EntityID,
    pub generated_frame: u64,
    pub active_state_per_layer: BTreeMap<String, String>,
    pub normalized_time_per_layer: BTreeMap<String, f32>,
    pub is_transitioning: bool,
    pub sequence: u64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct AnimationEventAction {
    pub entity_id: EntityID,
    pub event_id: String,
    pub state_name: String,
    pub trigger_at_normalized_time: f32,
    pub generated_frame: u64,
    pub sequence: u64,
}

#[derive(Debug, Clone, PartialEq)]
pub enum AnimationFeedbackAction {
    StateWrite(AnimationStateWriteAction),
    EventFired(AnimationEventAction),
}

impl AnimationFeedbackAction {
    pub fn sort_key(&self) -> (u64, EntityID, u8, u64) {
        match self {
            Self::StateWrite(action) => {
                (action.generated_frame, action.entity_id, 0, action.sequence)
            }
            Self::EventFired(action) => {
                (action.generated_frame, action.entity_id, 1, action.sequence)
            }
        }
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct AnimationFeedbackMetrics {
    pub state_updates_processed: u64,
    pub events_processed: u64,
    pub validation_failures: u64,
    pub poison_recoveries: u64,
}

pub struct AnimationFeedbackHandler {
    actions: Mutex<Vec<AnimationFeedbackAction>>,
    sequence: AtomicU64,
    metrics: Mutex<AnimationFeedbackMetrics>,
}

impl AnimationFeedbackHandler {
    pub fn new() -> Self {
        Self {
            actions: Mutex::new(Vec::new()),
            sequence: AtomicU64::new(0),
            metrics: Mutex::new(AnimationFeedbackMetrics::default()),
        }
    }

    pub fn state_update_count(&self) -> u64 {
        self.metrics().state_updates_processed
    }

    pub fn event_fired_count(&self) -> u64 {
        self.metrics().events_processed
    }

    pub fn validation_failure_count(&self) -> u64 {
        self.metrics().validation_failures
    }

    pub fn pending_action_count(&self) -> usize {
        self.lock_actions().len()
    }

    pub fn metrics(&self) -> AnimationFeedbackMetrics {
        self.lock_metrics().clone()
    }

    pub fn drain_actions_sorted(&self) -> Vec<AnimationFeedbackAction> {
        let mut actions = std::mem::take(&mut *self.lock_actions());
        actions.sort_by_key(AnimationFeedbackAction::sort_key);
        actions
    }

    fn next_sequence(&self) -> u64 {
        self.sequence.fetch_add(1, Ordering::Relaxed)
    }

    fn push_action(&self, action: AnimationFeedbackAction) {
        self.lock_actions().push(action);
    }

    fn record_state_update(&self) {
        self.lock_metrics().state_updates_processed += 1;
    }

    fn record_event(&self) {
        self.lock_metrics().events_processed += 1;
    }

    fn validation_error(&self, operation: &'static str, message: impl Into<String>) -> XaceError {
        self.lock_metrics().validation_failures += 1;
        recoverable(operation, message)
    }

    fn lock_actions(&self) -> MutexGuard<'_, Vec<AnimationFeedbackAction>> {
        match self.actions.lock() {
            Ok(guard) => guard,
            Err(poisoned) => {
                self.lock_metrics().poison_recoveries += 1;
                poisoned.into_inner()
            }
        }
    }

    fn lock_metrics(&self) -> MutexGuard<'_, AnimationFeedbackMetrics> {
        match self.metrics.lock() {
            Ok(guard) => guard,
            Err(poisoned) => poisoned.into_inner(),
        }
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

    fn can_handle(&self, feedback_type: FeedbackType) -> bool {
        matches!(
            feedback_type,
            FeedbackType::AnimationStateUpdate | FeedbackType::AnimationEventFired
        )
    }

    fn handle(&self, payload: &TypedFeedbackPayload) -> Result<(), XaceError> {
        match payload {
            TypedFeedbackPayload::AnimationStateUpdate(update) => {
                if update.entity_id == 0 {
                    return Err(self.validation_error(
                        "handle_state_update",
                        "AnimationStateUpdate has null entity_id",
                    ));
                }
                if update.active_state_per_layer.is_empty() {
                    return Err(self.validation_error(
                        "handle_state_update",
                        "AnimationStateUpdate has no active states",
                    ));
                }
                for (layer, state) in &update.active_state_per_layer {
                    if layer.trim().is_empty() || state.trim().is_empty() {
                        return Err(self.validation_error(
                            "handle_state_update",
                            "AnimationStateUpdate contains an empty layer or state name",
                        ));
                    }
                }
                for (layer, value) in &update.normalized_time_per_layer {
                    if layer.trim().is_empty() || !value.is_finite() || !(0.0..=1.0).contains(value)
                    {
                        return Err(self.validation_error(
                            "handle_state_update",
                            format!(
                                "AnimationStateUpdate normalized time for layer '{}' is invalid: {}",
                                layer, value
                            ),
                        ));
                    }
                }

                self.push_action(AnimationFeedbackAction::StateWrite(
                    AnimationStateWriteAction {
                        entity_id: update.entity_id,
                        generated_frame: update.generated_frame,
                        active_state_per_layer: update.active_state_per_layer.clone(),
                        normalized_time_per_layer: update.normalized_time_per_layer.clone(),
                        is_transitioning: update.is_transitioning,
                        sequence: self.next_sequence(),
                    },
                ));
                self.record_state_update();
                Ok(())
            }
            TypedFeedbackPayload::AnimationEventFired(fired) => {
                if fired.entity_id == 0 {
                    return Err(self.validation_error(
                        "handle_event_fired",
                        "AnimationEventFired has null entity_id",
                    ));
                }
                if fired.event_id.trim().is_empty() || fired.state_name.trim().is_empty() {
                    return Err(self.validation_error(
                        "handle_event_fired",
                        "AnimationEventFired has empty event_id or state_name",
                    ));
                }
                if !fired.trigger_at_normalized_time.is_finite()
                    || !(0.0..=1.0).contains(&fired.trigger_at_normalized_time)
                {
                    return Err(self.validation_error(
                        "handle_event_fired",
                        format!(
                            "AnimationEventFired trigger time is invalid: {}",
                            fired.trigger_at_normalized_time
                        ),
                    ));
                }

                self.push_action(AnimationFeedbackAction::EventFired(AnimationEventAction {
                    entity_id: fired.entity_id,
                    event_id: fired.event_id.clone(),
                    state_name: fired.state_name.clone(),
                    trigger_at_normalized_time: fired.trigger_at_normalized_time,
                    generated_frame: fired.generated_frame,
                    sequence: self.next_sequence(),
                }));
                self.record_event();
                Ok(())
            }
            other => Err(recoverable(
                "handle",
                format!("unexpected payload type {:?}", other.feedback_type()),
            )),
        }
    }
}

fn recoverable(operation: &'static str, message: impl Into<String>) -> XaceError {
    XaceError::RecoverableError {
        message: format!("AnimationFeedbackHandler: {}", message.into()),
        context: ErrorContext::new("AnimationFeedbackHandler", operation),
        max_retries: 0,
        retry_count: 0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;
    use xace_core::wire::feedback_payload::{
        AnimationEventFiredFeedback, AnimationStateUpdateFeedback, AudioPositionUpdateFeedback,
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
        assert_eq!(
            AnimationFeedbackHandler::new().kind(),
            FeedbackHandlerKind::Animation
        );
    }

    #[test]
    fn can_handle_both_animation_types() {
        let handler = AnimationFeedbackHandler::new();
        assert!(handler.can_handle(FeedbackType::AnimationStateUpdate));
        assert!(handler.can_handle(FeedbackType::AnimationEventFired));
        assert!(!handler.can_handle(FeedbackType::PhysicsSettled));
    }

    #[test]
    fn handle_state_update_records_action() {
        let handler = AnimationFeedbackHandler::new();
        handler.handle(&state_update(1)).unwrap();

        assert_eq!(handler.state_update_count(), 1);
        let actions = handler.drain_actions_sorted();
        assert!(matches!(actions[0], AnimationFeedbackAction::StateWrite(_)));
    }

    #[test]
    fn handle_event_fired_records_event_action() {
        let handler = AnimationFeedbackHandler::new();
        handler.handle(&event_fired(5)).unwrap();

        assert_eq!(handler.event_fired_count(), 1);
        let actions = handler.drain_actions_sorted();
        assert!(matches!(actions[0], AnimationFeedbackAction::EventFired(_)));
    }

    #[test]
    fn invalid_state_update_is_rejected_and_counted() {
        let handler = AnimationFeedbackHandler::new();
        assert!(handler.handle(&state_update(0)).is_err());
        assert_eq!(handler.validation_failure_count(), 1);
        assert_eq!(handler.pending_action_count(), 0);
    }

    #[test]
    fn invalid_event_trigger_time_is_rejected() {
        let handler = AnimationFeedbackHandler::new();
        let bad = TypedFeedbackPayload::AnimationEventFired(AnimationEventFiredFeedback {
            entity_id: 1,
            event_id: "bad".into(),
            state_name: "run".into(),
            trigger_at_normalized_time: f32::NAN,
            generated_frame: 1,
        });
        assert!(handler.handle(&bad).is_err());
    }

    #[test]
    fn actions_drain_in_deterministic_order() {
        let handler = AnimationFeedbackHandler::new();
        let mut later = match state_update(2) {
            TypedFeedbackPayload::AnimationStateUpdate(update) => update,
            _ => unreachable!(),
        };
        later.generated_frame = 9;
        handler
            .handle(&TypedFeedbackPayload::AnimationStateUpdate(later))
            .unwrap();
        handler.handle(&event_fired(1)).unwrap();

        let actions = handler.drain_actions_sorted();
        assert_eq!(actions[0].sort_key().0, 1);
        assert_eq!(actions[1].sort_key().0, 9);
    }

    #[test]
    fn handle_wrong_payload_type_returns_err() {
        let handler = AnimationFeedbackHandler::new();
        let wrong = TypedFeedbackPayload::AudioPositionUpdate(AudioPositionUpdateFeedback {
            entity_id: 1,
            position_json: "{}".into(),
            generated_frame: 1,
        });
        assert!(handler.handle(&wrong).is_err());
    }
}
