//! # Feedback Message
//!
//! Re-exports `FeedbackMessage` from `xace_core` and adds runtime-side
//! typed parsing helpers for each of the ten feedback payload variants.
//!
//! ## Why Typed Parsing Lives Here
//! `FeedbackMessage.payload_json` is an opaque JSON string in the core
//! wire type — this is correct for the wire layer (cross-language compatibility).
//! The runtime handlers need typed structs. Putting typed deserialization
//! in the handler files would scatter the JSON schema knowledge across
//! ten locations. Centralising it here means each handler calls one method
//! and gets a typed result, with the JSON schema in exactly one place.
//!
//! ## Ownership
//! `FeedbackMessage` is owned by `xace_core::wire::feedback_payload`.
//! This module adds an extension trait `FeedbackMessageExt` rather than
//! a new type so there is zero wrapping overhead at runtime.

pub use xace_core::wire::feedback_payload::{
    AnimationEventFiredFeedback, AnimationStateUpdateFeedback, AssetResolutionUpdateFeedback,
    AudioCompleteFeedback, EngineErrorFeedback, FeedbackMessage, FeedbackType,
    PerformanceMetricsFeedback, PhysicsSettledFeedback, VisibilityQueryResultFeedback,
};

use xace_core::errors::xace_error::{ErrorContext, XaceError};

// ── Typed Parse Result ────────────────────────────────────────────────────────

/// The fully typed payload of a `FeedbackMessage`.
///
/// Produced by `FeedbackMessageExt::parse_typed()`. Each variant
/// corresponds to one of the ten `FeedbackType` discriminants.
/// The handler receives this enum and pattern-matches rather than
/// calling `serde_json::from_str` directly.
#[derive(Debug, Clone)]
pub enum TypedFeedbackPayload {
    AnimationStateUpdate(AnimationStateUpdateFeedback),
    AnimationEventFired(AnimationEventFiredFeedback),
    PhysicsSettled(PhysicsSettledFeedback),
    VisibilityQueryResult(VisibilityQueryResultFeedback),
    AudioComplete(AudioCompleteFeedback),
    /// AudioPositionUpdate has no dedicated struct — position is in JSON only.
    /// The field is `entity_id` + `position_json` (x,y,z object string).
    AudioPositionUpdate { entity_id: u64, position_json: String },
    /// InputDeviceUpdate passes raw JSON through — the input handler decides
    /// how to interpret device-specific data.
    InputDeviceUpdate { entity_id: u64, device_json: String },
    PerformanceMetrics(PerformanceMetricsFeedback),
    AssetResolutionUpdate(AssetResolutionUpdateFeedback),
    EngineError(EngineErrorFeedback),
}

impl TypedFeedbackPayload {
    /// Returns the `FeedbackType` discriminant for this payload variant.
    pub fn feedback_type(&self) -> FeedbackType {
        match self {
            TypedFeedbackPayload::AnimationStateUpdate(_) => FeedbackType::AnimationStateUpdate,
            TypedFeedbackPayload::AnimationEventFired(_)  => FeedbackType::AnimationEventFired,
            TypedFeedbackPayload::PhysicsSettled(_)       => FeedbackType::PhysicsSettled,
            TypedFeedbackPayload::VisibilityQueryResult(_) => FeedbackType::VisibilityQueryResult,
            TypedFeedbackPayload::AudioComplete(_)        => FeedbackType::AudioComplete,
            TypedFeedbackPayload::AudioPositionUpdate { .. } => FeedbackType::AudioPositionUpdate,
            TypedFeedbackPayload::InputDeviceUpdate { .. }   => FeedbackType::InputDeviceUpdate,
            TypedFeedbackPayload::PerformanceMetrics(_)  => FeedbackType::PerformanceMetrics,
            TypedFeedbackPayload::AssetResolutionUpdate(_) => FeedbackType::AssetResolutionUpdate,
            TypedFeedbackPayload::EngineError(_)          => FeedbackType::EngineError,
        }
    }
}

// ── Extension Trait ───────────────────────────────────────────────────────────

/// Runtime-side extension methods on `FeedbackMessage`.
pub trait FeedbackMessageExt {
    /// Deserializes `payload_json` into the appropriate typed struct
    /// based on `feedback_type`.
    ///
    /// Returns `Ok(TypedFeedbackPayload)` on success.
    /// Returns `Err(RecoverableError)` on JSON parse failure — the message
    /// is logged and skipped, not fatal.
    fn parse_typed(&self) -> Result<TypedFeedbackPayload, XaceError>;

    /// Returns the sort key for deterministic ordering within the FeedbackBuffer.
    /// Sort order: `(generated_frame ASC, entity_id ASC)` (I13).
    fn sort_key(&self) -> (u64, u64);

    /// Returns true if this message belongs to an entity whose EntityID
    /// is within the given inclusive range. Used for interest-management
    /// filtering in Phase 15.
    fn entity_in_range(&self, min_entity_id: u64, max_entity_id: u64) -> bool;
}

impl FeedbackMessageExt for FeedbackMessage {
    fn parse_typed(&self) -> Result<TypedFeedbackPayload, XaceError> {
        let payload = match self.feedback_type {
            FeedbackType::AnimationStateUpdate => {
                let inner: AnimationStateUpdateFeedback =
                    parse_payload(&self.payload_json, "AnimationStateUpdate")?;
                TypedFeedbackPayload::AnimationStateUpdate(inner)
            }
            FeedbackType::AnimationEventFired => {
                let inner: AnimationEventFiredFeedback =
                    parse_payload(&self.payload_json, "AnimationEventFired")?;
                TypedFeedbackPayload::AnimationEventFired(inner)
            }
            FeedbackType::PhysicsSettled => {
                let inner: PhysicsSettledFeedback =
                    parse_payload(&self.payload_json, "PhysicsSettled")?;
                TypedFeedbackPayload::PhysicsSettled(inner)
            }
            FeedbackType::VisibilityQueryResult => {
                let inner: VisibilityQueryResultFeedback =
                    parse_payload(&self.payload_json, "VisibilityQueryResult")?;
                TypedFeedbackPayload::VisibilityQueryResult(inner)
            }
            FeedbackType::AudioComplete => {
                let inner: AudioCompleteFeedback =
                    parse_payload(&self.payload_json, "AudioComplete")?;
                TypedFeedbackPayload::AudioComplete(inner)
            }
            FeedbackType::AudioPositionUpdate => {
                let v: serde_json::Value = parse_json(&self.payload_json, "AudioPositionUpdate")?;
                TypedFeedbackPayload::AudioPositionUpdate {
                    entity_id: extract_u64(&v, "entity_id", "AudioPositionUpdate")?,
                    position_json: v
                        .get("position")
                        .map(|p| p.to_string())
                        .unwrap_or_default(),
                }
            }
            FeedbackType::InputDeviceUpdate => {
                let v: serde_json::Value = parse_json(&self.payload_json, "InputDeviceUpdate")?;
                TypedFeedbackPayload::InputDeviceUpdate {
                    entity_id: extract_u64(&v, "entity_id", "InputDeviceUpdate")?,
                    device_json: self.payload_json.clone(),
                }
            }
            FeedbackType::PerformanceMetrics => {
                let inner: PerformanceMetricsFeedback =
                    parse_payload(&self.payload_json, "PerformanceMetrics")?;
                TypedFeedbackPayload::PerformanceMetrics(inner)
            }
            FeedbackType::AssetResolutionUpdate => {
                let inner: AssetResolutionUpdateFeedback =
                    parse_payload(&self.payload_json, "AssetResolutionUpdate")?;
                TypedFeedbackPayload::AssetResolutionUpdate(inner)
            }
            FeedbackType::EngineError => {
                let inner: EngineErrorFeedback =
                    parse_payload(&self.payload_json, "EngineError")?;
                TypedFeedbackPayload::EngineError(inner)
            }
        };
        Ok(payload)
    }

    fn sort_key(&self) -> (u64, u64) {
        (self.generated_frame, self.entity_id)
    }

    fn entity_in_range(&self, min_entity_id: u64, max_entity_id: u64) -> bool {
        self.entity_id >= min_entity_id && self.entity_id <= max_entity_id
    }
}

// ── Internal Parse Helpers ────────────────────────────────────────────────────

fn parse_payload<T: serde::de::DeserializeOwned>(
    json: &str,
    type_name: &'static str,
) -> Result<T, XaceError> {
    serde_json::from_str(json).map_err(|e| XaceError::RecoverableError {
        message: format!(
            "FeedbackMessage: failed to parse {} payload — {}: json='{}'",
            type_name, e,
            &json[..json.len().min(120)]
        ),
        context: ErrorContext::new("FeedbackMessage", type_name),
        max_retries: 0,
        retry_count: 0,
    })
}

fn parse_json(json: &str, type_name: &'static str) -> Result<serde_json::Value, XaceError> {
    serde_json::from_str(json).map_err(|e| XaceError::RecoverableError {
        message: format!(
            "FeedbackMessage: failed to parse {} JSON — {}",
            type_name, e
        ),
        context: ErrorContext::new("FeedbackMessage", type_name),
        max_retries: 0,
        retry_count: 0,
    })
}

fn extract_u64(
    v: &serde_json::Value,
    field: &str,
    type_name: &'static str,
) -> Result<u64, XaceError> {
    v.get(field)
        .and_then(|f| f.as_u64())
        .ok_or_else(|| XaceError::RecoverableError {
            message: format!(
                "FeedbackMessage: missing or invalid '{}' field in {} payload",
                field, type_name
            ),
            context: ErrorContext::new("FeedbackMessage", type_name),
            max_retries: 0,
            retry_count: 0,
        })
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    fn make_msg(ft: FeedbackType, entity_id: u64, frame: u64, json: &str) -> FeedbackMessage {
        FeedbackMessage {
            feedback_type: ft,
            entity_id,
            generated_frame: frame,
            payload_json: json.to_string(),
        }
    }

    // ── AnimationStateUpdate ──────────────────────────────────────────────────

    #[test]
    fn parse_animation_state_update() {
        let json = serde_json::to_string(&AnimationStateUpdateFeedback {
            entity_id: 1,
            active_state_per_layer: BTreeMap::from([("base".into(), "run".into())]),
            normalized_time_per_layer: BTreeMap::from([("base".into(), 0.5)]),
            is_transitioning: false,
            generated_frame: 10,
        }).unwrap();

        let msg = make_msg(FeedbackType::AnimationStateUpdate, 1, 10, &json);
        let typed = msg.parse_typed().unwrap();
        assert!(matches!(typed, TypedFeedbackPayload::AnimationStateUpdate(_)));
        assert_eq!(typed.feedback_type(), FeedbackType::AnimationStateUpdate);
    }

    // ── PhysicsSettled ────────────────────────────────────────────────────────

    #[test]
    fn parse_physics_settled() {
        let json = serde_json::to_string(&PhysicsSettledFeedback {
            entity_id: 5,
            final_position_json: r#"{"x":1.0,"y":0.0,"z":0.0}"#.into(),
            final_rotation_json: r#"{"x":0.0,"y":0.0,"z":0.0,"w":1.0}"#.into(),
            generated_frame: 20,
        }).unwrap();

        let msg = make_msg(FeedbackType::PhysicsSettled, 5, 20, &json);
        let typed = msg.parse_typed().unwrap();
        assert!(matches!(typed, TypedFeedbackPayload::PhysicsSettled(_)));
    }

    // ── VisibilityQueryResult ─────────────────────────────────────────────────

    #[test]
    fn parse_visibility_query_result() {
        let json = serde_json::to_string(&VisibilityQueryResultFeedback {
            observer_entity_id: 1,
            target_entity_id: 2,
            can_see: true,
            distance: 15.5,
            generated_frame: 5,
        }).unwrap();

        let msg = make_msg(FeedbackType::VisibilityQueryResult, 1, 5, &json);
        let typed = msg.parse_typed().unwrap();
        if let TypedFeedbackPayload::VisibilityQueryResult(r) = typed {
            assert!(r.can_see);
            assert!((r.distance - 15.5).abs() < 1e-5);
        } else {
            panic!("Expected VisibilityQueryResult");
        }
    }

    // ── PerformanceMetrics ────────────────────────────────────────────────────

    #[test]
    fn parse_performance_metrics() {
        let json = serde_json::to_string(&PerformanceMetricsFeedback {
            engine_delta_apply_ms: 2.5,
            draw_calls: 1200,
            physics_contacts: 45,
            engine_entity_count: 300,
            generated_frame: 100,
        }).unwrap();

        let msg = make_msg(FeedbackType::PerformanceMetrics, 0, 100, &json);
        let typed = msg.parse_typed().unwrap();
        if let TypedFeedbackPayload::PerformanceMetrics(m) = typed {
            assert_eq!(m.draw_calls, 1200);
        } else {
            panic!("Expected PerformanceMetrics");
        }
    }

    // ── EngineError ───────────────────────────────────────────────────────────

    #[test]
    fn parse_engine_error() {
        let json = serde_json::to_string(&EngineErrorFeedback {
            entity_id: 0,
            error_code: "MESH_NOT_FOUND".into(),
            error_message: "Mesh asset missing".into(),
            generated_frame: 1,
        }).unwrap();

        let msg = make_msg(FeedbackType::EngineError, 0, 1, &json);
        let typed = msg.parse_typed().unwrap();
        if let TypedFeedbackPayload::EngineError(e) = typed {
            assert_eq!(e.error_code, "MESH_NOT_FOUND");
        } else {
            panic!("Expected EngineError");
        }
    }

    // ── Malformed JSON ────────────────────────────────────────────────────────

    #[test]
    fn malformed_json_returns_recoverable_error() {
        let msg = make_msg(FeedbackType::PhysicsSettled, 1, 1, "not json");
        assert!(msg.parse_typed().is_err());
    }

    // ── Sort Key ──────────────────────────────────────────────────────────────

    #[test]
    fn sort_key_is_frame_then_entity() {
        let msg = make_msg(FeedbackType::AudioComplete, 5, 10, "{}");
        assert_eq!(msg.sort_key(), (10, 5));
    }

    #[test]
    fn sort_key_ordering_frame_asc_entity_asc() {
        let m1 = make_msg(FeedbackType::PhysicsSettled, 3, 8, "{}");
        let m2 = make_msg(FeedbackType::PhysicsSettled, 1, 10, "{}");
        assert!(m1.sort_key() < m2.sort_key()); // frame 8 < frame 10
    }

    // ── entity_in_range ───────────────────────────────────────────────────────

    #[test]
    fn entity_in_range_correct() {
        let msg = make_msg(FeedbackType::AudioComplete, 50, 1, "{}");
        assert!(msg.entity_in_range(1, 100));
        assert!(msg.entity_in_range(50, 50));
        assert!(!msg.entity_in_range(51, 100));
        assert!(!msg.entity_in_range(1, 49));
    }
}