//! # Audio Feedback Handler
//!
//! Processes `AudioComplete` and `AudioPositionUpdate` feedback.
//!
//! ## AudioComplete
//! When an audio clip finishes playing, the engine sends `AudioComplete`.
//! The handler emits a game event through the EventBus so systems can
//! trigger follow-up actions (play next clip, transition music state,
//! trigger game event on dialogue completion).
//!
//! ## AudioPositionUpdate
//! For 3D positional audio, the engine tracks where a moving audio source
//! is in world space and reports it back. XACE uses this to keep its
//! audio state synchronized — particularly for the MUSIC_STATE component
//! which uses distance-based intensity.

use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::wire::feedback_payload::FeedbackType;

use crate::feedback_message::TypedFeedbackPayload;
use crate::feedback_router::FeedbackHandler;
use crate::feedback_type_enum::FeedbackHandlerKind;

// ── Audio Feedback Handler ────────────────────────────────────────────────────

/// Handles `AudioComplete` and `AudioPositionUpdate` feedback.
pub struct AudioFeedbackHandler {
    completions_processed: std::sync::atomic::AtomicU64,
    position_updates_processed: std::sync::atomic::AtomicU64,
    loop_completions: std::sync::atomic::AtomicU64,
}

impl AudioFeedbackHandler {
    pub fn new() -> Self {
        Self {
            completions_processed: std::sync::atomic::AtomicU64::new(0),
            position_updates_processed: std::sync::atomic::AtomicU64::new(0),
            loop_completions: std::sync::atomic::AtomicU64::new(0),
        }
    }

    pub fn completions_processed(&self) -> u64 {
        self.completions_processed.load(std::sync::atomic::Ordering::Relaxed)
    }

    pub fn position_updates_processed(&self) -> u64 {
        self.position_updates_processed.load(std::sync::atomic::Ordering::Relaxed)
    }

    pub fn loop_completions(&self) -> u64 {
        self.loop_completions.load(std::sync::atomic::Ordering::Relaxed)
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

    fn can_handle(&self, ft: FeedbackType) -> bool {
        matches!(ft, FeedbackType::AudioComplete | FeedbackType::AudioPositionUpdate)
    }

    fn handle(&self, payload: &TypedFeedbackPayload) -> Result<(), XaceError> {
        match payload {
            TypedFeedbackPayload::AudioComplete(completion) => {
                if completion.entity_id == 0 {
                    return Err(XaceError::RecoverableError {
                        message: "AudioFeedbackHandler: AudioComplete has null entity_id".into(),
                        context: ErrorContext::new("AudioFeedbackHandler", "handle_completion"),
                        max_retries: 0,
                        retry_count: 0,
                    });
                }

                if completion.asset_id.is_empty() {
                    return Err(XaceError::RecoverableError {
                        message: "AudioFeedbackHandler: AudioComplete has empty asset_id".into(),
                        context: ErrorContext::new("AudioFeedbackHandler", "handle_completion"),
                        max_retries: 0,
                        retry_count: 0,
                    });
                }

                // TODO (Phase 9 wiring): emit AudioComplete game event via EventBus:
                //   let event = Event::broadcast(
                //       completion.entity_id,
                //       EventType::Domain(format!("audio.complete.{}", completion.asset_id)),
                //       current_tick,
                //       PhaseEnum::PostSimulation,
                //   ).with_payload("asset_id", &completion.asset_id)
                //    .with_payload("did_loop", &completion.did_loop.to_string());
                //   event_bus.emit(event)?;

                if completion.did_loop {
                    self.loop_completions
                        .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                }

                self.completions_processed
                    .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                Ok(())
            }

            TypedFeedbackPayload::AudioPositionUpdate { entity_id, position_json } => {
                if *entity_id == 0 {
                    return Err(XaceError::RecoverableError {
                        message: "AudioFeedbackHandler: AudioPositionUpdate has null entity_id".into(),
                        context: ErrorContext::new("AudioFeedbackHandler", "handle_position"),
                        max_retries: 0,
                        retry_count: 0,
                    });
                }

                // Validate position JSON is parseable
                if serde_json::from_str::<serde_json::Value>(position_json).is_err() {
                    return Err(XaceError::RecoverableError {
                        message: format!(
                            "AudioFeedbackHandler: position_json is not valid JSON: '{}'",
                            &position_json[..position_json.len().min(80)]
                        ),
                        context: ErrorContext::new("AudioFeedbackHandler", "handle_position"),
                        max_retries: 0,
                        retry_count: 0,
                    });
                }

                // TODO (Phase 9 wiring): update COMP_AUDIO_EMITTER_V1 position
                // via Mutation Gate for 3D audio synchronization.

                self.position_updates_processed
                    .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                Ok(())
            }

            other => Err(XaceError::RecoverableError {
                message: format!(
                    "AudioFeedbackHandler: unexpected payload type {:?}",
                    other.feedback_type()
                ),
                context: ErrorContext::new("AudioFeedbackHandler", "handle"),
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
    use xace_core::wire::feedback_payload::AudioCompleteFeedback;

    fn completion(entity_id: u64, asset_id: &str, did_loop: bool) -> TypedFeedbackPayload {
        TypedFeedbackPayload::AudioComplete(AudioCompleteFeedback {
            entity_id,
            asset_id: asset_id.into(),
            did_loop,
            generated_frame: 1,
        })
    }

    fn pos_update(entity_id: u64, json: &str) -> TypedFeedbackPayload {
        TypedFeedbackPayload::AudioPositionUpdate {
            entity_id,
            position_json: json.into(),
        }
    }

    #[test]
    fn handler_kind_is_audio() {
        assert_eq!(AudioFeedbackHandler::new().kind(), FeedbackHandlerKind::Audio);
    }

    #[test]
    fn can_handle_both_audio_types() {
        let h = AudioFeedbackHandler::new();
        assert!(h.can_handle(FeedbackType::AudioComplete));
        assert!(h.can_handle(FeedbackType::AudioPositionUpdate));
        assert!(!h.can_handle(FeedbackType::PhysicsSettled));
    }

    #[test]
    fn handle_valid_completion_succeeds() {
        let h = AudioFeedbackHandler::new();
        h.handle(&completion(1, "footstep_sfx_v1", false)).unwrap();
        assert_eq!(h.completions_processed(), 1);
        assert_eq!(h.loop_completions(), 0);
    }

    #[test]
    fn handle_loop_completion_increments_loop_count() {
        let h = AudioFeedbackHandler::new();
        h.handle(&completion(1, "bg_music_v1", true)).unwrap();
        assert_eq!(h.loop_completions(), 1);
    }

    #[test]
    fn null_entity_in_completion_fails() {
        let h = AudioFeedbackHandler::new();
        assert!(h.handle(&completion(0, "sfx", false)).is_err());
    }

    #[test]
    fn empty_asset_id_fails() {
        let h = AudioFeedbackHandler::new();
        assert!(h.handle(&completion(1, "", false)).is_err());
    }

    #[test]
    fn valid_position_update_succeeds() {
        let h = AudioFeedbackHandler::new();
        h.handle(&pos_update(1, r#"{"x":1.0,"y":0.0,"z":5.0}"#)).unwrap();
        assert_eq!(h.position_updates_processed(), 1);
    }

    #[test]
    fn null_entity_in_position_update_fails() {
        let h = AudioFeedbackHandler::new();
        assert!(h.handle(&pos_update(0, r#"{"x":0}"#)).is_err());
    }

    #[test]
    fn invalid_position_json_fails() {
        let h = AudioFeedbackHandler::new();
        assert!(h.handle(&pos_update(1, "not json")).is_err());
    }

    #[test]
    fn wrong_payload_type_returns_err() {
        let h = AudioFeedbackHandler::new();
        let wrong = TypedFeedbackPayload::InputDeviceUpdate {
            entity_id: 1,
            device_json: "{}".into(),
        };
        assert!(h.handle(&wrong).is_err());
    }
}