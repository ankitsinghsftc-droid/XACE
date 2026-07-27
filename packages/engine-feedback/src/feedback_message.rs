//! Typed helpers around core feedback wire messages.

pub use xace_core::wire::feedback_payload::{
    AnimationEventFiredFeedback, AnimationStateUpdateFeedback, AssetResolutionUpdateFeedback,
    AudioCompleteFeedback, AudioPositionUpdateFeedback, EngineErrorFeedback, FeedbackMessage,
    FeedbackPayload, FeedbackType, InputDeviceUpdateFeedback, PerformanceMetricsFeedback,
    PhysicsSettledFeedback, VisibilityQueryResultFeedback,
};

use xace_core::entity_id::EntityID;
use xace_core::errors::xace_error::{ErrorContext, XaceError};

use crate::feedback_type_enum::FeedbackTypeExt;

#[derive(Debug, Clone, PartialEq)]
pub enum TypedFeedbackPayload {
    AnimationStateUpdate(AnimationStateUpdateFeedback),
    AnimationEventFired(AnimationEventFiredFeedback),
    PhysicsSettled(PhysicsSettledFeedback),
    VisibilityQueryResult(VisibilityQueryResultFeedback),
    AudioComplete(AudioCompleteFeedback),
    AudioPositionUpdate(AudioPositionUpdateFeedback),
    InputDeviceUpdate(InputDeviceUpdateFeedback),
    PerformanceMetrics(PerformanceMetricsFeedback),
    AssetResolutionUpdate(AssetResolutionUpdateFeedback),
    EngineError(EngineErrorFeedback),
}

impl TypedFeedbackPayload {
    pub fn feedback_type(&self) -> FeedbackType {
        match self {
            Self::AnimationStateUpdate(_) => FeedbackType::AnimationStateUpdate,
            Self::AnimationEventFired(_) => FeedbackType::AnimationEventFired,
            Self::PhysicsSettled(_) => FeedbackType::PhysicsSettled,
            Self::VisibilityQueryResult(_) => FeedbackType::VisibilityQueryResult,
            Self::AudioComplete(_) => FeedbackType::AudioComplete,
            Self::AudioPositionUpdate(_) => FeedbackType::AudioPositionUpdate,
            Self::InputDeviceUpdate(_) => FeedbackType::InputDeviceUpdate,
            Self::PerformanceMetrics(_) => FeedbackType::PerformanceMetrics,
            Self::AssetResolutionUpdate(_) => FeedbackType::AssetResolutionUpdate,
            Self::EngineError(_) => FeedbackType::EngineError,
        }
    }

    pub fn generated_frame(&self) -> u64 {
        match self {
            Self::AnimationStateUpdate(v) => v.generated_frame,
            Self::AnimationEventFired(v) => v.generated_frame,
            Self::PhysicsSettled(v) => v.generated_frame,
            Self::VisibilityQueryResult(v) => v.generated_frame,
            Self::AudioComplete(v) => v.generated_frame,
            Self::AudioPositionUpdate(v) => v.generated_frame,
            Self::InputDeviceUpdate(v) => v.generated_frame,
            Self::PerformanceMetrics(v) => v.generated_frame,
            Self::AssetResolutionUpdate(v) => v.generated_frame,
            Self::EngineError(v) => v.generated_frame,
        }
    }

    pub fn entity_id(&self) -> EntityID {
        match self {
            Self::AnimationStateUpdate(v) => v.entity_id,
            Self::AnimationEventFired(v) => v.entity_id,
            Self::PhysicsSettled(v) => v.entity_id,
            Self::VisibilityQueryResult(v) => v.observer_entity_id,
            Self::AudioComplete(v) => v.entity_id,
            Self::AudioPositionUpdate(v) => v.entity_id,
            Self::InputDeviceUpdate(v) => v.entity_id,
            Self::PerformanceMetrics(_) | Self::AssetResolutionUpdate(_) => 0,
            Self::EngineError(v) => v.entity_id,
        }
    }
}

pub trait FeedbackMessageExt {
    fn parse_typed(&self) -> Result<TypedFeedbackPayload, XaceError>;
    fn validate_contract(&self) -> Result<(), XaceError>;
    fn payload_size_bytes(&self) -> usize;
    fn sort_key(&self) -> (u64, EntityID, u8);
    fn dedupe_key(&self) -> (u64, EntityID, u8, u64);
    fn entity_in_range(&self, min_entity_id: EntityID, max_entity_id: EntityID) -> bool;
}

impl FeedbackMessageExt for FeedbackMessage {
    fn parse_typed(&self) -> Result<TypedFeedbackPayload, XaceError> {
        self.validate_contract()?;
        let typed = match self.feedback_type {
            FeedbackType::AnimationStateUpdate => {
                TypedFeedbackPayload::AnimationStateUpdate(parse_payload(self)?)
            }
            FeedbackType::AnimationEventFired => {
                TypedFeedbackPayload::AnimationEventFired(parse_payload(self)?)
            }
            FeedbackType::PhysicsSettled => {
                TypedFeedbackPayload::PhysicsSettled(parse_payload(self)?)
            }
            FeedbackType::VisibilityQueryResult => {
                TypedFeedbackPayload::VisibilityQueryResult(parse_payload(self)?)
            }
            FeedbackType::AudioComplete => {
                TypedFeedbackPayload::AudioComplete(parse_payload(self)?)
            }
            FeedbackType::AudioPositionUpdate => {
                TypedFeedbackPayload::AudioPositionUpdate(parse_payload(self)?)
            }
            FeedbackType::InputDeviceUpdate => {
                TypedFeedbackPayload::InputDeviceUpdate(parse_payload(self)?)
            }
            FeedbackType::PerformanceMetrics => {
                TypedFeedbackPayload::PerformanceMetrics(parse_payload(self)?)
            }
            FeedbackType::AssetResolutionUpdate => {
                TypedFeedbackPayload::AssetResolutionUpdate(parse_payload(self)?)
            }
            FeedbackType::EngineError => TypedFeedbackPayload::EngineError(parse_payload(self)?),
        };

        if typed.feedback_type() != self.feedback_type {
            return Err(recoverable(
                "parse_typed",
                format!(
                    "typed feedback mismatch: envelope={} payload={}",
                    self.feedback_type,
                    typed.feedback_type()
                ),
            ));
        }
        Ok(typed)
    }

    fn validate_contract(&self) -> Result<(), XaceError> {
        self.validate()
            .map_err(|detail| recoverable("validate_contract", detail))?;
        if self.feedback_type.requires_entity_id() && self.entity_id == 0 {
            return Err(recoverable(
                "validate_contract",
                format!("{} requires a non-zero entity_id", self.feedback_type),
            ));
        }
        Ok(())
    }

    fn payload_size_bytes(&self) -> usize {
        self.payload_json.len()
    }

    fn sort_key(&self) -> (u64, EntityID, u8) {
        (
            self.generated_frame,
            self.entity_id,
            self.feedback_type.as_u8(),
        )
    }

    fn dedupe_key(&self) -> (u64, EntityID, u8, u64) {
        (
            self.generated_frame,
            self.entity_id,
            self.feedback_type.as_u8(),
            stable_payload_hash(&self.payload_json),
        )
    }

    fn entity_in_range(&self, min_entity_id: EntityID, max_entity_id: EntityID) -> bool {
        self.entity_id >= min_entity_id && self.entity_id <= max_entity_id
    }
}

fn parse_payload<T: serde::de::DeserializeOwned>(msg: &FeedbackMessage) -> Result<T, XaceError> {
    serde_json::from_str(&msg.payload_json).map_err(|err| {
        recoverable(
            "parse_typed",
            format!(
                "failed to parse {} payload for entity {} frame {}: {}",
                msg.feedback_type, msg.entity_id, msg.generated_frame, err
            ),
        )
    })
}

fn stable_payload_hash(payload: &str) -> u64 {
    let mut hash = 0xcbf2_9ce4_8422_2325u64;
    for byte in payload.as_bytes() {
        hash ^= *byte as u64;
        hash = hash.wrapping_mul(0x1000_0000_01b3);
    }
    hash
}

fn recoverable(operation: &'static str, message: impl Into<String>) -> XaceError {
    XaceError::RecoverableError {
        message: format!("FeedbackMessage: {}", message.into()),
        context: ErrorContext::new("FeedbackMessage", operation),
        max_retries: 0,
        retry_count: 0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    #[test]
    fn parses_animation_state_payload() {
        let payload = AnimationStateUpdateFeedback {
            entity_id: 1,
            active_state_per_layer: BTreeMap::from([("base".to_string(), "run".to_string())]),
            normalized_time_per_layer: BTreeMap::from([("base".to_string(), 0.5)]),
            is_transitioning: false,
            generated_frame: 7,
        };
        let msg =
            FeedbackMessage::from_typed_payload(FeedbackType::AnimationStateUpdate, 1, 7, &payload)
                .unwrap();

        assert!(matches!(
            msg.parse_typed().unwrap(),
            TypedFeedbackPayload::AnimationStateUpdate(_)
        ));
    }

    #[test]
    fn sort_key_includes_type_for_stable_ties() {
        let a = FeedbackMessage::new(FeedbackType::AudioComplete, 1, 1, "{}");
        let b = FeedbackMessage::new(FeedbackType::PhysicsSettled, 1, 1, "{}");
        assert_ne!(a.sort_key(), b.sort_key());
    }

    #[test]
    fn entity_requirement_is_enforced() {
        let msg = FeedbackMessage::new(FeedbackType::PhysicsSettled, 0, 1, "{}");
        assert!(msg.validate_contract().is_err());
        let metrics = FeedbackMessage::new(FeedbackType::PerformanceMetrics, 0, 1, "{}");
        assert!(metrics.validate_contract().is_ok());
    }

    #[test]
    fn dedupe_key_changes_with_payload() {
        let a = FeedbackMessage::new(FeedbackType::EngineError, 1, 1, r#"{"a":1}"#);
        let b = FeedbackMessage::new(FeedbackType::EngineError, 1, 1, r#"{"a":2}"#);
        assert_ne!(a.dedupe_key(), b.dedupe_key());
    }
}
