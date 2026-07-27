//! Extended input feedback handler.
//!
//! `InputDeviceUpdate` represents device data that is not part of the
//! canonical network INPUT packet, such as touch, gyro, eye tracking, or voice
//! amplitude. The handler validates the envelope and records deterministic
//! tick-boundary updates for the InputSystem to consume.

use std::collections::BTreeMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, MutexGuard};

use serde_json::Value;
use xace_core::entity_id::EntityID;
use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::wire::feedback_payload::FeedbackType;

use crate::feedback_message::TypedFeedbackPayload;
use crate::feedback_router::FeedbackHandler;
use crate::feedback_type_enum::FeedbackHandlerKind;

#[derive(Debug, Clone, PartialEq)]
pub struct InputDeviceUpdateAction {
    pub entity_id: EntityID,
    pub device_id: String,
    pub generated_frame: u64,
    pub canonical_values_json: String,
    pub sequence: u64,
}

impl InputDeviceUpdateAction {
    pub fn sort_key(&self) -> (u64, EntityID, &str, u64) {
        (
            self.generated_frame,
            self.entity_id,
            self.device_id.as_str(),
            self.sequence,
        )
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct InputFeedbackMetrics {
    pub updates_processed: u64,
    pub invalid_json_count: u64,
    pub validation_failures: u64,
    pub device_level_updates: u64,
    pub per_device_counts: BTreeMap<String, u64>,
    pub poison_recoveries: u64,
}

pub struct InputFeedbackHandler {
    actions: Mutex<Vec<InputDeviceUpdateAction>>,
    sequence: AtomicU64,
    metrics: Mutex<InputFeedbackMetrics>,
}

impl InputFeedbackHandler {
    pub fn new() -> Self {
        Self {
            actions: Mutex::new(Vec::new()),
            sequence: AtomicU64::new(0),
            metrics: Mutex::new(InputFeedbackMetrics::default()),
        }
    }

    pub fn updates_processed(&self) -> u64 {
        self.metrics().updates_processed
    }

    pub fn invalid_json_count(&self) -> u64 {
        self.metrics().invalid_json_count
    }

    pub fn validation_failure_count(&self) -> u64 {
        self.metrics().validation_failures
    }

    pub fn pending_action_count(&self) -> usize {
        self.lock_actions().len()
    }

    pub fn metrics(&self) -> InputFeedbackMetrics {
        self.lock_metrics().clone()
    }

    pub fn drain_actions_sorted(&self) -> Vec<InputDeviceUpdateAction> {
        let mut actions = std::mem::take(&mut *self.lock_actions());
        actions.sort_by(|left, right| left.sort_key().cmp(&right.sort_key()));
        actions
    }

    fn next_sequence(&self) -> u64 {
        self.sequence.fetch_add(1, Ordering::Relaxed)
    }

    fn validation_error(&self, operation: &'static str, message: impl Into<String>) -> XaceError {
        self.lock_metrics().validation_failures += 1;
        recoverable(operation, message)
    }

    fn parse_values(&self, values_json: &str) -> Result<String, XaceError> {
        let value = serde_json::from_str::<Value>(values_json).map_err(|err| {
            let mut metrics = self.lock_metrics();
            metrics.invalid_json_count += 1;
            metrics.validation_failures += 1;
            recoverable("handle", format!("values_json is invalid: {}", err))
        })?;
        serde_json::to_string(&value).map_err(|err| {
            self.validation_error(
                "handle",
                format!("failed to encode canonical values_json: {}", err),
            )
        })
    }

    fn lock_actions(&self) -> MutexGuard<'_, Vec<InputDeviceUpdateAction>> {
        match self.actions.lock() {
            Ok(guard) => guard,
            Err(poisoned) => {
                self.lock_metrics().poison_recoveries += 1;
                poisoned.into_inner()
            }
        }
    }

    fn lock_metrics(&self) -> MutexGuard<'_, InputFeedbackMetrics> {
        match self.metrics.lock() {
            Ok(guard) => guard,
            Err(poisoned) => poisoned.into_inner(),
        }
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

    fn can_handle(&self, feedback_type: FeedbackType) -> bool {
        feedback_type == FeedbackType::InputDeviceUpdate
    }

    fn handle(&self, payload: &TypedFeedbackPayload) -> Result<(), XaceError> {
        let update = match payload {
            TypedFeedbackPayload::InputDeviceUpdate(update) => update,
            other => {
                return Err(recoverable(
                    "handle",
                    format!("unexpected payload type {:?}", other.feedback_type()),
                ))
            }
        };

        let device_id = update.device_id.trim();
        if device_id.is_empty() {
            return Err(self.validation_error("handle", "InputDeviceUpdate has empty device_id"));
        }
        let canonical_values_json = self.parse_values(&update.values_json)?;

        self.lock_actions().push(InputDeviceUpdateAction {
            entity_id: update.entity_id,
            device_id: device_id.to_string(),
            generated_frame: update.generated_frame,
            canonical_values_json,
            sequence: self.next_sequence(),
        });

        let mut metrics = self.lock_metrics();
        metrics.updates_processed += 1;
        if update.entity_id == 0 {
            metrics.device_level_updates += 1;
        }
        *metrics
            .per_device_counts
            .entry(device_id.to_string())
            .or_insert(0) += 1;
        Ok(())
    }
}

fn recoverable(operation: &'static str, message: impl Into<String>) -> XaceError {
    XaceError::RecoverableError {
        message: format!("InputFeedbackHandler: {}", message.into()),
        context: ErrorContext::new("InputFeedbackHandler", operation),
        max_retries: 0,
        retry_count: 0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::wire::feedback_payload::{
        AudioPositionUpdateFeedback, FeedbackType, InputDeviceUpdateFeedback,
    };

    fn update(entity_id: u64, json: &str) -> TypedFeedbackPayload {
        TypedFeedbackPayload::InputDeviceUpdate(InputDeviceUpdateFeedback {
            entity_id,
            device_id: "test-device".into(),
            values_json: json.into(),
            generated_frame: 1,
        })
    }

    #[test]
    fn handler_kind_is_input() {
        assert_eq!(
            InputFeedbackHandler::new().kind(),
            FeedbackHandlerKind::Input
        );
    }

    #[test]
    fn can_handle_input_device_update_only() {
        let handler = InputFeedbackHandler::new();
        assert!(handler.can_handle(FeedbackType::InputDeviceUpdate));
        assert!(!handler.can_handle(FeedbackType::AudioComplete));
    }

    #[test]
    fn valid_device_json_records_action() {
        let handler = InputFeedbackHandler::new();
        handler
            .handle(&update(1, r#"{"touch_x":0.5,"touch_y":0.3}"#))
            .unwrap();

        assert_eq!(handler.updates_processed(), 1);
        let actions = handler.drain_actions_sorted();
        assert_eq!(actions[0].device_id, "test-device");
        assert_eq!(
            actions[0].canonical_values_json,
            r#"{"touch_x":0.5,"touch_y":0.3}"#
        );
    }

    #[test]
    fn entity_zero_allowed_for_device_level_input() {
        let handler = InputFeedbackHandler::new();
        handler
            .handle(&update(0, r#"{"gyro_x":0.01,"gyro_y":0.0,"gyro_z":0.0}"#))
            .unwrap();
        assert_eq!(handler.metrics().device_level_updates, 1);
    }

    #[test]
    fn invalid_json_returns_err_and_counted() {
        let handler = InputFeedbackHandler::new();
        assert!(handler.handle(&update(1, "not valid json")).is_err());
        assert_eq!(handler.invalid_json_count(), 1);
        assert_eq!(handler.updates_processed(), 0);
    }

    #[test]
    fn empty_device_id_is_rejected() {
        let handler = InputFeedbackHandler::new();
        let bad = TypedFeedbackPayload::InputDeviceUpdate(InputDeviceUpdateFeedback {
            entity_id: 1,
            device_id: "  ".into(),
            values_json: "{}".into(),
            generated_frame: 1,
        });
        assert!(handler.handle(&bad).is_err());
        assert_eq!(handler.validation_failure_count(), 1);
    }

    #[test]
    fn actions_drain_in_deterministic_order() {
        let handler = InputFeedbackHandler::new();
        let a = TypedFeedbackPayload::InputDeviceUpdate(InputDeviceUpdateFeedback {
            entity_id: 2,
            device_id: "touch".into(),
            values_json: "{}".into(),
            generated_frame: 10,
        });
        let b = TypedFeedbackPayload::InputDeviceUpdate(InputDeviceUpdateFeedback {
            entity_id: 1,
            device_id: "gyro".into(),
            values_json: "{}".into(),
            generated_frame: 1,
        });
        handler.handle(&a).unwrap();
        handler.handle(&b).unwrap();

        let actions = handler.drain_actions_sorted();
        assert_eq!(actions[0].generated_frame, 1);
        assert_eq!(actions[1].generated_frame, 10);
    }

    #[test]
    fn wrong_payload_type_returns_err() {
        let handler = InputFeedbackHandler::new();
        let wrong = TypedFeedbackPayload::AudioPositionUpdate(AudioPositionUpdateFeedback {
            entity_id: 1,
            position_json: "{}".into(),
            generated_frame: 1,
        });
        assert!(handler.handle(&wrong).is_err());
    }
}
