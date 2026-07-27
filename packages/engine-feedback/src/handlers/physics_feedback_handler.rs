//! Physics feedback handler.
//!
//! Engine-owned physics feedback is converted into deterministic transform
//! write actions. The handler validates payloads and queues actions only; the
//! authoritative component write must still happen later through Mutation Gate.

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, MutexGuard};

use serde::{Deserialize, Serialize};
use xace_core::entity_id::EntityID;
use xace_core::errors::xace_error::{ErrorContext, XaceError};

use crate::feedback_message::TypedFeedbackPayload;
use crate::feedback_router::FeedbackHandler;
use crate::feedback_type_enum::FeedbackHandlerKind;

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct Vec3Feedback {
    pub x: f64,
    pub y: f64,
    pub z: f64,
}

impl Vec3Feedback {
    fn validate(self, field: &'static str) -> Result<Self, XaceError> {
        if self.x.is_finite() && self.y.is_finite() && self.z.is_finite() {
            Ok(self)
        } else {
            Err(recoverable(field, "position contains a non-finite value"))
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct QuatFeedback {
    pub x: f64,
    pub y: f64,
    pub z: f64,
    pub w: f64,
}

impl QuatFeedback {
    fn validate(self) -> Result<Self, XaceError> {
        if self.x.is_finite() && self.y.is_finite() && self.z.is_finite() && self.w.is_finite() {
            Ok(self)
        } else {
            Err(recoverable(
                "validate_rotation",
                "rotation contains a non-finite value",
            ))
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct PhysicsTransformWriteAction {
    pub entity_id: EntityID,
    pub generated_frame: u64,
    pub final_position: Vec3Feedback,
    pub final_rotation: QuatFeedback,
    pub canonical_position_json: String,
    pub canonical_rotation_json: String,
    pub sequence: u64,
}

impl PhysicsTransformWriteAction {
    pub fn sort_key(&self) -> (u64, EntityID, u64) {
        (self.generated_frame, self.entity_id, self.sequence)
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct PhysicsFeedbackMetrics {
    pub settled_count: u64,
    pub validation_failure_count: u64,
    pub poison_recoveries: u64,
}

pub struct PhysicsFeedbackHandler {
    actions: Mutex<Vec<PhysicsTransformWriteAction>>,
    sequence: AtomicU64,
    metrics: Mutex<PhysicsFeedbackMetrics>,
}

impl PhysicsFeedbackHandler {
    pub fn new() -> Self {
        Self {
            actions: Mutex::new(Vec::new()),
            sequence: AtomicU64::new(0),
            metrics: Mutex::new(PhysicsFeedbackMetrics::default()),
        }
    }

    pub fn settled_count(&self) -> u64 {
        self.metrics().settled_count
    }

    pub fn validation_failure_count(&self) -> u64 {
        self.metrics().validation_failure_count
    }

    pub fn pending_action_count(&self) -> usize {
        self.lock_actions().len()
    }

    pub fn metrics(&self) -> PhysicsFeedbackMetrics {
        self.lock_metrics().clone()
    }

    pub fn drain_actions_sorted(&self) -> Vec<PhysicsTransformWriteAction> {
        let mut actions = std::mem::take(&mut *self.lock_actions());
        actions.sort_by_key(PhysicsTransformWriteAction::sort_key);
        actions
    }

    fn next_sequence(&self) -> u64 {
        self.sequence.fetch_add(1, Ordering::Relaxed)
    }

    fn validation_error(&self, operation: &'static str, message: impl Into<String>) -> XaceError {
        self.lock_metrics().validation_failure_count += 1;
        recoverable(operation, message)
    }

    fn parse_position(&self, json: &str) -> Result<Vec3Feedback, XaceError> {
        serde_json::from_str::<Vec3Feedback>(json)
            .map_err(|err| {
                self.validation_error(
                    "validate_position",
                    format!("final_position_json is invalid: {}", err),
                )
            })?
            .validate("validate_position")
            .map_err(|err| {
                self.lock_metrics().validation_failure_count += 1;
                err
            })
    }

    fn parse_rotation(&self, json: &str) -> Result<QuatFeedback, XaceError> {
        serde_json::from_str::<QuatFeedback>(json)
            .map_err(|err| {
                self.validation_error(
                    "validate_rotation",
                    format!("final_rotation_json is invalid: {}", err),
                )
            })?
            .validate()
            .map_err(|err| {
                self.lock_metrics().validation_failure_count += 1;
                err
            })
    }

    fn lock_actions(&self) -> MutexGuard<'_, Vec<PhysicsTransformWriteAction>> {
        match self.actions.lock() {
            Ok(guard) => guard,
            Err(poisoned) => {
                self.lock_metrics().poison_recoveries += 1;
                poisoned.into_inner()
            }
        }
    }

    fn lock_metrics(&self) -> MutexGuard<'_, PhysicsFeedbackMetrics> {
        match self.metrics.lock() {
            Ok(guard) => guard,
            Err(poisoned) => poisoned.into_inner(),
        }
    }
}

impl Default for PhysicsFeedbackHandler {
    fn default() -> Self {
        Self::new()
    }
}

impl FeedbackHandler for PhysicsFeedbackHandler {
    fn kind(&self) -> FeedbackHandlerKind {
        FeedbackHandlerKind::Physics
    }

    fn name(&self) -> &str {
        "PhysicsFeedbackHandler"
    }

    fn handle(&self, payload: &TypedFeedbackPayload) -> Result<(), XaceError> {
        let settled = match payload {
            TypedFeedbackPayload::PhysicsSettled(settled) => settled,
            other => {
                return Err(recoverable(
                    "handle",
                    format!("unexpected payload type {:?}", other.feedback_type()),
                ))
            }
        };

        if settled.entity_id == 0 {
            return Err(self.validation_error("handle", "PhysicsSettled has null entity_id"));
        }

        let final_position = self.parse_position(&settled.final_position_json)?;
        let final_rotation = self.parse_rotation(&settled.final_rotation_json)?;
        let canonical_position_json = serde_json::to_string(&final_position).map_err(|err| {
            self.validation_error("handle", format!("failed to encode position: {}", err))
        })?;
        let canonical_rotation_json = serde_json::to_string(&final_rotation).map_err(|err| {
            self.validation_error("handle", format!("failed to encode rotation: {}", err))
        })?;

        self.lock_actions().push(PhysicsTransformWriteAction {
            entity_id: settled.entity_id,
            generated_frame: settled.generated_frame,
            final_position,
            final_rotation,
            canonical_position_json,
            canonical_rotation_json,
            sequence: self.next_sequence(),
        });
        self.lock_metrics().settled_count += 1;
        Ok(())
    }
}

fn recoverable(operation: &'static str, message: impl Into<String>) -> XaceError {
    XaceError::RecoverableError {
        message: format!("PhysicsFeedbackHandler: {}", message.into()),
        context: ErrorContext::new("PhysicsFeedbackHandler", operation),
        max_retries: 0,
        retry_count: 0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::wire::feedback_payload::{
        AudioPositionUpdateFeedback, FeedbackType, PhysicsSettledFeedback,
    };

    fn settled(entity_id: u64) -> TypedFeedbackPayload {
        TypedFeedbackPayload::PhysicsSettled(PhysicsSettledFeedback {
            entity_id,
            final_position_json: r#"{"x":1.0,"y":0.0,"z":0.0}"#.into(),
            final_rotation_json: r#"{"x":0.0,"y":0.0,"z":0.0,"w":1.0}"#.into(),
            generated_frame: 1,
        })
    }

    #[test]
    fn handler_kind_is_physics() {
        assert_eq!(
            PhysicsFeedbackHandler::new().kind(),
            FeedbackHandlerKind::Physics
        );
    }

    #[test]
    fn can_handle_physics_settled_only() {
        let handler = PhysicsFeedbackHandler::new();
        assert!(handler.can_handle(FeedbackType::PhysicsSettled));
        assert!(!handler.can_handle(FeedbackType::AnimationStateUpdate));
    }

    #[test]
    fn handle_valid_settled_records_transform_action() {
        let handler = PhysicsFeedbackHandler::new();
        handler.handle(&settled(1)).unwrap();

        assert_eq!(handler.settled_count(), 1);
        let actions = handler.drain_actions_sorted();
        assert_eq!(actions[0].entity_id, 1);
        assert_eq!(
            actions[0].canonical_rotation_json,
            r#"{"x":0.0,"y":0.0,"z":0.0,"w":1.0}"#
        );
    }

    #[test]
    fn handle_null_entity_fails() {
        let handler = PhysicsFeedbackHandler::new();
        assert!(handler.handle(&settled(0)).is_err());
        assert_eq!(handler.validation_failure_count(), 1);
    }

    #[test]
    fn handle_invalid_position_json_fails() {
        let handler = PhysicsFeedbackHandler::new();
        let bad = TypedFeedbackPayload::PhysicsSettled(PhysicsSettledFeedback {
            entity_id: 1,
            final_position_json: r#"{"bad":true}"#.into(),
            final_rotation_json: r#"{"x":0.0,"y":0.0,"z":0.0,"w":1.0}"#.into(),
            generated_frame: 1,
        });
        assert!(handler.handle(&bad).is_err());
        assert_eq!(handler.validation_failure_count(), 1);
    }

    #[test]
    fn non_finite_rotation_fails() {
        let handler = PhysicsFeedbackHandler::new();
        let bad = TypedFeedbackPayload::PhysicsSettled(PhysicsSettledFeedback {
            entity_id: 1,
            final_position_json: r#"{"x":0.0,"y":0.0,"z":0.0}"#.into(),
            final_rotation_json: r#"{"x":0.0,"y":0.0,"z":0.0,"w":1e999}"#.into(),
            generated_frame: 1,
        });
        assert!(handler.handle(&bad).is_err());
    }

    #[test]
    fn wrong_payload_type_returns_err() {
        let handler = PhysicsFeedbackHandler::new();
        let wrong = TypedFeedbackPayload::AudioPositionUpdate(AudioPositionUpdateFeedback {
            entity_id: 1,
            position_json: "{}".into(),
            generated_frame: 1,
        });
        assert!(handler.handle(&wrong).is_err());
    }
}
