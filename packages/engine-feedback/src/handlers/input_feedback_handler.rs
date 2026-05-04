//! # Input Feedback Handler
//!
//! Processes `InputDeviceUpdate` feedback — extended input from devices
//! that cannot be captured in the standard INPUT wire message.
//!
//! ## Standard INPUT vs InputDeviceUpdate
//! The standard `MessageType::Input` message carries keyboard, mouse, and
//! gamepad digital/analog data — the inputs most games need most of the time.
//!
//! `InputDeviceUpdate` feedback covers the long tail of input hardware:
//! - Touch input (multi-touch gestures, touch pressure)
//! - Gyroscope / accelerometer data
//! - Voice amplitude (for voice-activated mechanics)
//! - Eye tracking
//! - Any platform-specific extended input
//!
//! The payload is device-specific JSON — XACE does not attempt to parse
//! device schemas here. The raw JSON is stored and made available to
//! input systems that know how to interpret their device's data.
//!
//! ## Determinism Note
//! Extended input arrives as feedback (engine → XACE) rather than the
//! standard INPUT channel. It is processed at tick boundaries (I13) and
//! subject to the same determinism rules as all other feedback. The
//! device_json must be deterministic for replay to work — the engine
//! adapter must ensure it serializes input state with stable field ordering.

use xace_core::errors::xace_error::{ErrorContext, XaceError};

use crate::feedback_message::TypedFeedbackPayload;
use crate::feedback_router::FeedbackHandler;
use crate::feedback_type_enum::FeedbackHandlerKind;

// ── Input Feedback Handler ────────────────────────────────────────────────────

/// Handles `InputDeviceUpdate` — extended device input feedback.
pub struct InputFeedbackHandler {
    updates_processed: std::sync::atomic::AtomicU64,
    invalid_json_count: std::sync::atomic::AtomicU64,
}

impl InputFeedbackHandler {
    pub fn new() -> Self {
        Self {
            updates_processed: std::sync::atomic::AtomicU64::new(0),
            invalid_json_count: std::sync::atomic::AtomicU64::new(0),
        }
    }

    pub fn updates_processed(&self) -> u64 {
        self.updates_processed.load(std::sync::atomic::Ordering::Relaxed)
    }

    pub fn invalid_json_count(&self) -> u64 {
        self.invalid_json_count.load(std::sync::atomic::Ordering::Relaxed)
    }
}

impl Default for InputFeedbackHandler {
    fn default() -> Self {
        Self::new()
    }
}

impl FeedbackHandler for InputFeedbackHandler {
    fn kind(&self) -> FeedbackHandlerKind {
        FeedbackHandlerKind::Input
    }

    fn name(&self) -> &str {
        "InputFeedbackHandler"
    }

    fn handle(&self, payload: &TypedFeedbackPayload) -> Result<(), XaceError> {
        let (entity_id, device_json) = match payload {
            TypedFeedbackPayload::InputDeviceUpdate { entity_id, device_json } => {
                (*entity_id, device_json.as_str())
            }
            other => {
                return Err(XaceError::RecoverableError {
                    message: format!(
                        "InputFeedbackHandler: unexpected payload type {:?}",
                        other.feedback_type()
                    ),
                    context: ErrorContext::new("InputFeedbackHandler", "handle"),
                    max_retries: 0,
                    retry_count: 0,
                })
            }
        };

        // entity_id == 0 means device-level input (not attached to a specific entity)
        // This is valid — a gyroscope may report data before a player entity is spawned.

        // Validate the device JSON is at minimum parseable
        if serde_json::from_str::<serde_json::Value>(device_json).is_err() {
            self.invalid_json_count
                .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            return Err(XaceError::RecoverableError {
                message: format!(
                    "InputFeedbackHandler: device_json is not valid JSON for entity={}",
                    entity_id
                ),
                context: ErrorContext::new("InputFeedbackHandler", "handle"),
                max_retries: 0,
                retry_count: 0,
            });
        }

        // TODO (Phase 9 wiring): store parsed device input data for retrieval
        // by input systems. The InputSystem reads this alongside the standard
        // InputPacket to compose the full input state for the tick.
        //
        // For example, a touch-gesture input system would:
        //   let gestures = parse_touch_gestures(device_json);
        //   input_store.record_device_input(entity_id, current_tick, device_json);

        self.updates_processed
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        Ok(())
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn update(entity_id: u64, json: &str) -> TypedFeedbackPayload {
        TypedFeedbackPayload::InputDeviceUpdate {
            entity_id,
            device_json: json.into(),
        }
    }

    #[test]
    fn handler_kind_is_input() {
        assert_eq!(InputFeedbackHandler::new().kind(), FeedbackHandlerKind::Input);
    }

    #[test]
    fn can_handle_input_device_update_only() {
        let h = InputFeedbackHandler::new();
        assert!(h.can_handle(FeedbackType::InputDeviceUpdate));
        assert!(!h.can_handle(FeedbackType::AudioComplete));
    }

    #[test]
    fn valid_device_json_with_entity_succeeds() {
        let h = InputFeedbackHandler::new();
        h.handle(&update(1, r#"{"touch_x":0.5,"touch_y":0.3}"#)).unwrap();
        assert_eq!(h.updates_processed(), 1);
    }

    #[test]
    fn entity_zero_allowed_for_device_level_input() {
        // Gyroscope data before player entity spawned — valid
        let h = InputFeedbackHandler::new();
        h.handle(&update(0, r#"{"gyro_x":0.01,"gyro_y":0.0,"gyro_z":0.0}"#)).unwrap();
        assert_eq!(h.updates_processed(), 1);
    }

    #[test]
    fn invalid_json_returns_err_and_counted() {
        let h = InputFeedbackHandler::new();
        assert!(h.handle(&update(1, "not valid json")).is_err());
        assert_eq!(h.invalid_json_count(), 1);
        assert_eq!(h.updates_processed(), 0);
    }

    #[test]
    fn empty_json_object_is_valid() {
        let h = InputFeedbackHandler::new();
        h.handle(&update(1, "{}")).unwrap();
        assert_eq!(h.updates_processed(), 1);
    }

    #[test]
    fn wrong_payload_type_returns_err() {
        let h = InputFeedbackHandler::new();
        let wrong = TypedFeedbackPayload::AudioPositionUpdate {
            entity_id: 1,
            position_json: "{}".into(),
        };
        assert!(h.handle(&wrong).is_err());
    }
}