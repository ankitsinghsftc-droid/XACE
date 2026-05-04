//! # Physics Feedback Handler
//!
//! Processes `PhysicsSettled` feedback from the engine adapter.
//!
//! ## What PhysicsSettled Means
//! When a ragdoll or physics-simulated object reaches its final resting
//! position, the engine sends `PhysicsSettled`. XACE cannot compute this
//! position deterministically — ragdoll dynamics are engine-owned — so
//! the engine is the authoritative source.
//!
//! The handler writes the engine-reported final position and rotation
//! back to `COMP_TRANSFORM_V1` via the Mutation Gate. This is one of
//! the few cases where the engine adapter indirectly influences
//! authoritative XACE state — but always via the Mutation Gate (I2),
//! never by direct write (D13).
//!
//! ## Why This Is Safe (D13 preserved)
//! The engine adapter does not write state — it sends feedback.
//! The handler (XACE-side) reads the feedback and submits a mutation
//! through the Mutation Gate. The Mutation Gate applies it in the
//! correct phase (D4). The adapter never touches `IEntityStore` or
//! `IComponentTable` directly.
//!
//! ## Position JSON Validation
//! `final_position_json` must be a JSON object with numeric x, y, z fields.
//! `final_rotation_json` must be a JSON object with numeric x, y, z, w fields.
//! Both are validated before any mutation is submitted.

use xace_core::errors::xace_error::{ErrorContext, XaceError};

use crate::feedback_message::TypedFeedbackPayload;
use crate::feedback_router::FeedbackHandler;
use crate::feedback_type_enum::FeedbackHandlerKind;

// ── Position/Rotation Validation ──────────────────────────────────────────────

/// Validates that a JSON string is a well-formed position object {x, y, z}.
fn validate_position_json(json: &str, context: &str) -> Result<(), XaceError> {
    let v: serde_json::Value =
        serde_json::from_str(json).map_err(|e| XaceError::RecoverableError {
            message: format!(
                "PhysicsFeedbackHandler: {} is not valid JSON — {}",
                context, e
            ),
            context: ErrorContext::new("PhysicsFeedbackHandler", context),
            max_retries: 0,
            retry_count: 0,
        })?;

    let obj = v.as_object().ok_or_else(|| XaceError::RecoverableError {
        message: format!(
            "PhysicsFeedbackHandler: {} must be a JSON object",
            context
        ),
        context: ErrorContext::new("PhysicsFeedbackHandler", context),
        max_retries: 0,
        retry_count: 0,
    })?;

    for field in &["x", "y", "z"] {
        if obj.get(*field).and_then(|v| v.as_f64()).is_none() {
            return Err(XaceError::RecoverableError {
                message: format!(
                    "PhysicsFeedbackHandler: {} missing or non-numeric field '{}'",
                    context, field
                ),
                context: ErrorContext::new("PhysicsFeedbackHandler", context),
                max_retries: 0,
                retry_count: 0,
            });
        }
    }
    Ok(())
}

/// Validates that a JSON string is a well-formed rotation object {x, y, z, w}.
fn validate_rotation_json(json: &str) -> Result<(), XaceError> {
    let v: serde_json::Value =
        serde_json::from_str(json).map_err(|e| XaceError::RecoverableError {
            message: format!(
                "PhysicsFeedbackHandler: rotation JSON is invalid — {}",
                e
            ),
            context: ErrorContext::new("PhysicsFeedbackHandler", "validate_rotation"),
            max_retries: 0,
            retry_count: 0,
        })?;

    let obj = v.as_object().ok_or_else(|| XaceError::RecoverableError {
        message: "PhysicsFeedbackHandler: rotation_json must be a JSON object".into(),
        context: ErrorContext::new("PhysicsFeedbackHandler", "validate_rotation"),
        max_retries: 0,
        retry_count: 0,
    })?;

    for field in &["x", "y", "z", "w"] {
        if obj.get(*field).and_then(|v| v.as_f64()).is_none() {
            return Err(XaceError::RecoverableError {
                message: format!(
                    "PhysicsFeedbackHandler: rotation_json missing or non-numeric field '{}'",
                    field
                ),
                context: ErrorContext::new("PhysicsFeedbackHandler", "validate_rotation"),
                max_retries: 0,
                retry_count: 0,
            });
        }
    }
    Ok(())
}

// ── Physics Feedback Handler ──────────────────────────────────────────────────

/// Handles `PhysicsSettled` feedback — writes final ragdoll position to
/// `COMP_TRANSFORM_V1` via Mutation Gate.
pub struct PhysicsFeedbackHandler {
    settled_count: std::sync::atomic::AtomicU64,
    validation_failure_count: std::sync::atomic::AtomicU64,
}

impl PhysicsFeedbackHandler {
    pub fn new() -> Self {
        Self {
            settled_count: std::sync::atomic::AtomicU64::new(0),
            validation_failure_count: std::sync::atomic::AtomicU64::new(0),
        }
    }

    pub fn settled_count(&self) -> u64 {
        self.settled_count.load(std::sync::atomic::Ordering::Relaxed)
    }

    pub fn validation_failure_count(&self) -> u64 {
        self.validation_failure_count.load(std::sync::atomic::Ordering::Relaxed)
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
            TypedFeedbackPayload::PhysicsSettled(s) => s,
            other => {
                return Err(XaceError::RecoverableError {
                    message: format!(
                        "PhysicsFeedbackHandler: unexpected payload type {:?}",
                        other.feedback_type()
                    ),
                    context: ErrorContext::new("PhysicsFeedbackHandler", "handle"),
                    max_retries: 0,
                    retry_count: 0,
                })
            }
        };

        if settled.entity_id == 0 {
            self.validation_failure_count
                .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            return Err(XaceError::RecoverableError {
                message: "PhysicsFeedbackHandler: PhysicsSettled has null entity_id".into(),
                context: ErrorContext::new("PhysicsFeedbackHandler", "handle"),
                max_retries: 0,
                retry_count: 0,
            });
        }

        // Validate position and rotation JSON before any mutation
        if let Err(e) = validate_position_json(&settled.final_position_json, "final_position_json") {
            self.validation_failure_count
                .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            return Err(e);
        }
        if let Err(e) = validate_rotation_json(&settled.final_rotation_json) {
            self.validation_failure_count
                .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            return Err(e);
        }

        // TODO (Phase 9 wiring): write to COMP_TRANSFORM_V1 via Mutation Gate:
        //   let patch = format!(
        //       r#"{{"position":{},"rotation":{}}}"#,
        //       settled.final_position_json,
        //       settled.final_rotation_json,
        //   );
        //   mutation_gate.request_modify_component(
        //       settled.entity_id,
        //       COMP_TRANSFORM_V1_TYPE_ID,
        //       patch,
        //   )?;

        self.settled_count
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        Ok(())
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::wire::feedback_payload::PhysicsSettledFeedback;

    fn settled(entity_id: u64) -> TypedFeedbackPayload {
        TypedFeedbackPayload::PhysicsSettled(PhysicsSettledFeedback {
            entity_id,
            final_position_json: r#"{"x":1.0,"y":0.0,"z":0.0}"#.into(),
            final_rotation_json: r#"{"x":0.0,"y":0.0,"z":0.0,"w":1.0}"#.into(),
            generated_frame: 1,
        })
    }

    fn settled_bad_pos(entity_id: u64) -> TypedFeedbackPayload {
        TypedFeedbackPayload::PhysicsSettled(PhysicsSettledFeedback {
            entity_id,
            final_position_json: r#"{"bad":true}"#.into(),
            final_rotation_json: r#"{"x":0.0,"y":0.0,"z":0.0,"w":1.0}"#.into(),
            generated_frame: 1,
        })
    }

    #[test]
    fn handler_kind_is_physics() {
        assert_eq!(PhysicsFeedbackHandler::new().kind(), FeedbackHandlerKind::Physics);
    }

    #[test]
    fn can_handle_physics_settled_only() {
        let h = PhysicsFeedbackHandler::new();
        assert!(h.can_handle(FeedbackType::PhysicsSettled));
        assert!(!h.can_handle(FeedbackType::AnimationStateUpdate));
    }

    #[test]
    fn handle_valid_settled_succeeds() {
        let h = PhysicsFeedbackHandler::new();
        assert!(h.handle(&settled(1)).is_ok());
        assert_eq!(h.settled_count(), 1);
    }

    #[test]
    fn handle_null_entity_fails() {
        let h = PhysicsFeedbackHandler::new();
        assert!(h.handle(&settled(0)).is_err());
        assert_eq!(h.validation_failure_count(), 1);
    }

    #[test]
    fn handle_invalid_position_json_fails() {
        let h = PhysicsFeedbackHandler::new();
        assert!(h.handle(&settled_bad_pos(1)).is_err());
        assert_eq!(h.validation_failure_count(), 1);
    }

    #[test]
    fn handle_missing_rotation_w_field_fails() {
        let h = PhysicsFeedbackHandler::new();
        let bad = TypedFeedbackPayload::PhysicsSettled(PhysicsSettledFeedback {
            entity_id: 1,
            final_position_json: r#"{"x":0.0,"y":0.0,"z":0.0}"#.into(),
            final_rotation_json: r#"{"x":0.0,"y":0.0,"z":0.0}"#.into(), // missing w
            generated_frame: 1,
        });
        assert!(h.handle(&bad).is_err());
    }

    #[test]
    fn wrong_payload_type_returns_err() {
        let h = PhysicsFeedbackHandler::new();
        let wrong = TypedFeedbackPayload::AudioPositionUpdate {
            entity_id: 1,
            position_json: "{}".into(),
        };
        assert!(h.handle(&wrong).is_err());
    }
}