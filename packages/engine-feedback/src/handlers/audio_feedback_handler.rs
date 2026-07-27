//! Audio feedback handler.
//!
//! Audio feedback is engine-owned state entering XACE at tick boundaries
//! (I13). This handler validates feedback and converts it into deterministic
//! action records for later EventBus or Mutation Gate application. It does not
//! mutate authoritative component state directly.

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, MutexGuard};

use serde::{Deserialize, Serialize};
use xace_core::entity_id::EntityID;
use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::wire::feedback_payload::FeedbackType;

use crate::feedback_message::TypedFeedbackPayload;
use crate::feedback_router::FeedbackHandler;
use crate::feedback_type_enum::FeedbackHandlerKind;

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct AudioPosition {
    pub x: f64,
    pub y: f64,
    pub z: f64,
}

impl AudioPosition {
    fn validate(self) -> Result<Self, XaceError> {
        if self.x.is_finite() && self.y.is_finite() && self.z.is_finite() {
            Ok(self)
        } else {
            Err(recoverable(
                "handle_position",
                "position contains a non-finite value",
            ))
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct AudioCompleteAction {
    pub entity_id: EntityID,
    pub asset_id: String,
    pub did_loop: bool,
    pub generated_frame: u64,
    pub sequence: u64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct AudioPositionWriteAction {
    pub entity_id: EntityID,
    pub generated_frame: u64,
    pub position: AudioPosition,
    pub canonical_position_json: String,
    pub sequence: u64,
}

#[derive(Debug, Clone, PartialEq)]
pub enum AudioFeedbackAction {
    Complete(AudioCompleteAction),
    PositionWrite(AudioPositionWriteAction),
}

impl AudioFeedbackAction {
    pub fn sort_key(&self) -> (u64, EntityID, u8, u64) {
        match self {
            Self::Complete(action) => {
                (action.generated_frame, action.entity_id, 0, action.sequence)
            }
            Self::PositionWrite(action) => {
                (action.generated_frame, action.entity_id, 1, action.sequence)
            }
        }
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct AudioFeedbackMetrics {
    pub completions_processed: u64,
    pub position_updates_processed: u64,
    pub loop_completions: u64,
    pub validation_failures: u64,
    pub poison_recoveries: u64,
}

pub struct AudioFeedbackHandler {
    actions: Mutex<Vec<AudioFeedbackAction>>,
    sequence: AtomicU64,
    metrics: Mutex<AudioFeedbackMetrics>,
}

impl AudioFeedbackHandler {
    pub fn new() -> Self {
        Self {
            actions: Mutex::new(Vec::new()),
            sequence: AtomicU64::new(0),
            metrics: Mutex::new(AudioFeedbackMetrics::default()),
        }
    }

    pub fn completions_processed(&self) -> u64 {
        self.metrics().completions_processed
    }

    pub fn position_updates_processed(&self) -> u64 {
        self.metrics().position_updates_processed
    }

    pub fn loop_completions(&self) -> u64 {
        self.metrics().loop_completions
    }

    pub fn validation_failure_count(&self) -> u64 {
        self.metrics().validation_failures
    }

    pub fn pending_action_count(&self) -> usize {
        self.lock_actions().len()
    }

    pub fn metrics(&self) -> AudioFeedbackMetrics {
        self.lock_metrics().clone()
    }

    pub fn drain_actions_sorted(&self) -> Vec<AudioFeedbackAction> {
        let mut actions = std::mem::take(&mut *self.lock_actions());
        actions.sort_by_key(AudioFeedbackAction::sort_key);
        actions
    }

    fn next_sequence(&self) -> u64 {
        self.sequence.fetch_add(1, Ordering::Relaxed)
    }

    fn validation_error(&self, operation: &'static str, message: impl Into<String>) -> XaceError {
        self.lock_metrics().validation_failures += 1;
        recoverable(operation, message)
    }

    fn parse_position(&self, position_json: &str) -> Result<AudioPosition, XaceError> {
        serde_json::from_str::<AudioPosition>(position_json)
            .map_err(|err| {
                self.validation_error(
                    "handle_position",
                    format!("position_json is invalid: {}", err),
                )
            })?
            .validate()
            .map_err(|err| {
                self.lock_metrics().validation_failures += 1;
                err
            })
    }

    fn lock_actions(&self) -> MutexGuard<'_, Vec<AudioFeedbackAction>> {
        match self.actions.lock() {
            Ok(guard) => guard,
            Err(poisoned) => {
                self.lock_metrics().poison_recoveries += 1;
                poisoned.into_inner()
            }
        }
    }

    fn lock_metrics(&self) -> MutexGuard<'_, AudioFeedbackMetrics> {
        match self.metrics.lock() {
            Ok(guard) => guard,
            Err(poisoned) => poisoned.into_inner(),
        }
    }
}

impl Default for AudioFeedbackHandler {
    fn default() -> Self {
        Self::new()
    }
}

impl FeedbackHandler for AudioFeedbackHandler {
    fn kind(&self) -> FeedbackHandlerKind {
        FeedbackHandlerKind::Audio
    }

    fn name(&self) -> &str {
        "AudioFeedbackHandler"
    }

    fn can_handle(&self, feedback_type: FeedbackType) -> bool {
        matches!(
            feedback_type,
            FeedbackType::AudioComplete | FeedbackType::AudioPositionUpdate
        )
    }

    fn handle(&self, payload: &TypedFeedbackPayload) -> Result<(), XaceError> {
        match payload {
            TypedFeedbackPayload::AudioComplete(completion) => {
                if completion.entity_id == 0 {
                    return Err(self.validation_error(
                        "handle_completion",
                        "AudioComplete has null entity_id",
                    ));
                }
                let asset_id = completion.asset_id.trim();
                if asset_id.is_empty() {
                    return Err(self.validation_error(
                        "handle_completion",
                        "AudioComplete has empty asset_id",
                    ));
                }

                self.lock_actions()
                    .push(AudioFeedbackAction::Complete(AudioCompleteAction {
                        entity_id: completion.entity_id,
                        asset_id: asset_id.to_string(),
                        did_loop: completion.did_loop,
                        generated_frame: completion.generated_frame,
                        sequence: self.next_sequence(),
                    }));

                let mut metrics = self.lock_metrics();
                metrics.completions_processed += 1;
                if completion.did_loop {
                    metrics.loop_completions += 1;
                }
                Ok(())
            }
            TypedFeedbackPayload::AudioPositionUpdate(update) => {
                if update.entity_id == 0 {
                    return Err(self.validation_error(
                        "handle_position",
                        "AudioPositionUpdate has null entity_id",
                    ));
                }
                let position = self.parse_position(&update.position_json)?;
                let canonical_position_json = serde_json::to_string(&position).map_err(|err| {
                    self.validation_error(
                        "handle_position",
                        format!("failed to encode canonical position: {}", err),
                    )
                })?;

                self.lock_actions().push(AudioFeedbackAction::PositionWrite(
                    AudioPositionWriteAction {
                        entity_id: update.entity_id,
                        generated_frame: update.generated_frame,
                        position,
                        canonical_position_json,
                        sequence: self.next_sequence(),
                    },
                ));
                self.lock_metrics().position_updates_processed += 1;
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
        message: format!("AudioFeedbackHandler: {}", message.into()),
        context: ErrorContext::new("AudioFeedbackHandler", operation),
        max_retries: 0,
        retry_count: 0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::wire::feedback_payload::{
        AudioCompleteFeedback, AudioPositionUpdateFeedback, InputDeviceUpdateFeedback,
    };

    fn completion(entity_id: u64, asset_id: &str, did_loop: bool) -> TypedFeedbackPayload {
        TypedFeedbackPayload::AudioComplete(AudioCompleteFeedback {
            entity_id,
            asset_id: asset_id.into(),
            did_loop,
            generated_frame: 1,
        })
    }

    fn pos_update(entity_id: u64, json: &str) -> TypedFeedbackPayload {
        TypedFeedbackPayload::AudioPositionUpdate(AudioPositionUpdateFeedback {
            entity_id,
            position_json: json.into(),
            generated_frame: 1,
        })
    }

    #[test]
    fn handler_kind_is_audio() {
        assert_eq!(
            AudioFeedbackHandler::new().kind(),
            FeedbackHandlerKind::Audio
        );
    }

    #[test]
    fn can_handle_both_audio_types() {
        let handler = AudioFeedbackHandler::new();
        assert!(handler.can_handle(FeedbackType::AudioComplete));
        assert!(handler.can_handle(FeedbackType::AudioPositionUpdate));
        assert!(!handler.can_handle(FeedbackType::PhysicsSettled));
    }

    #[test]
    fn handle_valid_completion_records_action() {
        let handler = AudioFeedbackHandler::new();
        handler
            .handle(&completion(1, "footstep_sfx_v1", false))
            .unwrap();

        assert_eq!(handler.completions_processed(), 1);
        let actions = handler.drain_actions_sorted();
        assert!(matches!(actions[0], AudioFeedbackAction::Complete(_)));
    }

    #[test]
    fn handle_loop_completion_increments_loop_count() {
        let handler = AudioFeedbackHandler::new();
        handler.handle(&completion(1, "bg_music_v1", true)).unwrap();
        assert_eq!(handler.loop_completions(), 1);
    }

    #[test]
    fn invalid_completion_is_rejected() {
        let handler = AudioFeedbackHandler::new();
        assert!(handler.handle(&completion(0, "sfx", false)).is_err());
        assert!(handler.handle(&completion(1, "   ", false)).is_err());
        assert_eq!(handler.validation_failure_count(), 2);
    }

    #[test]
    fn valid_position_update_records_canonical_position() {
        let handler = AudioFeedbackHandler::new();
        handler
            .handle(&pos_update(1, r#"{"x":1.0,"y":0.0,"z":5.0}"#))
            .unwrap();

        assert_eq!(handler.position_updates_processed(), 1);
        let actions = handler.drain_actions_sorted();
        match &actions[0] {
            AudioFeedbackAction::PositionWrite(action) => {
                assert_eq!(
                    action.canonical_position_json,
                    r#"{"x":1.0,"y":0.0,"z":5.0}"#
                );
            }
            _ => panic!("expected position write action"),
        }
    }

    #[test]
    fn invalid_position_update_fails() {
        let handler = AudioFeedbackHandler::new();
        assert!(handler.handle(&pos_update(0, r#"{"x":0}"#)).is_err());
        assert!(handler.handle(&pos_update(1, "not json")).is_err());
        assert_eq!(handler.pending_action_count(), 0);
    }

    #[test]
    fn wrong_payload_type_returns_err() {
        let handler = AudioFeedbackHandler::new();
        let wrong = TypedFeedbackPayload::InputDeviceUpdate(InputDeviceUpdateFeedback {
            entity_id: 1,
            device_id: "keyboard".into(),
            values_json: "{}".into(),
            generated_frame: 1,
        });
        assert!(handler.handle(&wrong).is_err());
    }
}
