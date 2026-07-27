//! Engine-to-XACE feedback payloads.
//!
//! Feedback is the controlled return channel from engine adapters to the
//! runtime. It is buffered and processed at tick boundaries only, so every
//! message carries deterministic sort keys and can be replayed exactly.

use std::collections::BTreeMap;

use serde::{de::DeserializeOwned, Deserialize, Serialize};

use crate::entity_id::{EntityID, NULL_ENTITY_ID};
use crate::entity_metadata::Tick;

/// Stable feedback type identifiers.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
#[repr(u8)]
pub enum FeedbackType {
    AnimationStateUpdate = 0,
    AnimationEventFired = 1,
    PhysicsSettled = 2,
    VisibilityQueryResult = 3,
    AudioComplete = 4,
    AudioPositionUpdate = 5,
    InputDeviceUpdate = 6,
    PerformanceMetrics = 7,
    AssetResolutionUpdate = 8,
    EngineError = 9,
}

impl FeedbackType {
    pub const ALL: [FeedbackType; 10] = [
        FeedbackType::AnimationStateUpdate,
        FeedbackType::AnimationEventFired,
        FeedbackType::PhysicsSettled,
        FeedbackType::VisibilityQueryResult,
        FeedbackType::AudioComplete,
        FeedbackType::AudioPositionUpdate,
        FeedbackType::InputDeviceUpdate,
        FeedbackType::PerformanceMetrics,
        FeedbackType::AssetResolutionUpdate,
        FeedbackType::EngineError,
    ];

    pub fn as_u8(self) -> u8 {
        self as u8
    }

    pub fn from_u8(value: u8) -> Option<Self> {
        match value {
            0 => Some(Self::AnimationStateUpdate),
            1 => Some(Self::AnimationEventFired),
            2 => Some(Self::PhysicsSettled),
            3 => Some(Self::VisibilityQueryResult),
            4 => Some(Self::AudioComplete),
            5 => Some(Self::AudioPositionUpdate),
            6 => Some(Self::InputDeviceUpdate),
            7 => Some(Self::PerformanceMetrics),
            8 => Some(Self::AssetResolutionUpdate),
            9 => Some(Self::EngineError),
            _ => None,
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            Self::AnimationStateUpdate => "AnimationStateUpdate",
            Self::AnimationEventFired => "AnimationEventFired",
            Self::PhysicsSettled => "PhysicsSettled",
            Self::VisibilityQueryResult => "VisibilityQueryResult",
            Self::AudioComplete => "AudioComplete",
            Self::AudioPositionUpdate => "AudioPositionUpdate",
            Self::InputDeviceUpdate => "InputDeviceUpdate",
            Self::PerformanceMetrics => "PerformanceMetrics",
            Self::AssetResolutionUpdate => "AssetResolutionUpdate",
            Self::EngineError => "EngineError",
        }
    }

    pub fn payload_kind(self) -> &'static str {
        match self {
            Self::AnimationStateUpdate => "AnimationStateUpdateFeedback",
            Self::AnimationEventFired => "AnimationEventFiredFeedback",
            Self::PhysicsSettled => "PhysicsSettledFeedback",
            Self::VisibilityQueryResult => "VisibilityQueryResultFeedback",
            Self::AudioComplete => "AudioCompleteFeedback",
            Self::AudioPositionUpdate => "AudioPositionUpdateFeedback",
            Self::InputDeviceUpdate => "InputDeviceUpdateFeedback",
            Self::PerformanceMetrics => "PerformanceMetricsFeedback",
            Self::AssetResolutionUpdate => "AssetResolutionUpdateFeedback",
            Self::EngineError => "EngineErrorFeedback",
        }
    }

    pub fn entity_scoped(self) -> bool {
        !matches!(
            self,
            Self::PerformanceMetrics | Self::AssetResolutionUpdate | Self::InputDeviceUpdate
        )
    }
}

impl std::fmt::Display for FeedbackType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.name())
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AnimationStateUpdateFeedback {
    pub entity_id: EntityID,
    pub active_state_per_layer: BTreeMap<String, String>,
    pub normalized_time_per_layer: BTreeMap<String, f32>,
    pub is_transitioning: bool,
    pub generated_frame: u64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AnimationEventFiredFeedback {
    pub entity_id: EntityID,
    pub event_id: String,
    pub state_name: String,
    pub trigger_at_normalized_time: f32,
    pub generated_frame: u64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PhysicsSettledFeedback {
    pub entity_id: EntityID,
    pub final_position_json: String,
    pub final_rotation_json: String,
    pub generated_frame: u64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct VisibilityQueryResultFeedback {
    pub observer_entity_id: EntityID,
    pub target_entity_id: EntityID,
    pub can_see: bool,
    pub distance: f32,
    pub generated_frame: u64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AudioCompleteFeedback {
    pub entity_id: EntityID,
    pub asset_id: String,
    pub did_loop: bool,
    pub generated_frame: u64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AudioPositionUpdateFeedback {
    pub entity_id: EntityID,
    pub position_json: String,
    pub generated_frame: u64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct InputDeviceUpdateFeedback {
    pub entity_id: EntityID,
    pub device_id: String,
    pub values_json: String,
    pub generated_frame: u64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PerformanceMetricsFeedback {
    pub engine_delta_apply_ms: f32,
    pub draw_calls: u32,
    pub physics_contacts: u32,
    pub engine_entity_count: u32,
    pub generated_frame: u64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AssetResolutionUpdateFeedback {
    pub resolved_assets: BTreeMap<String, String>,
    pub generated_frame: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EngineErrorFeedback {
    pub entity_id: EntityID,
    pub error_code: String,
    pub error_message: String,
    pub generated_frame: u64,
}

/// One feedback message and its deterministic sort keys.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FeedbackMessage {
    pub feedback_type: FeedbackType,
    pub entity_id: EntityID,
    pub generated_frame: u64,
    pub payload_json: String,
}

impl FeedbackMessage {
    pub fn new(
        feedback_type: FeedbackType,
        entity_id: EntityID,
        generated_frame: u64,
        payload_json: impl Into<String>,
    ) -> Self {
        Self {
            feedback_type,
            entity_id,
            generated_frame,
            payload_json: payload_json.into(),
        }
    }

    pub fn from_typed_payload<T: Serialize>(
        feedback_type: FeedbackType,
        entity_id: EntityID,
        generated_frame: u64,
        payload: &T,
    ) -> Result<Self, serde_json::Error> {
        Ok(Self::new(
            feedback_type,
            entity_id,
            generated_frame,
            serde_json::to_string(payload)?,
        ))
    }

    pub fn sort_key(&self) -> (u64, EntityID, u8) {
        (
            self.generated_frame,
            self.entity_id,
            self.feedback_type.as_u8(),
        )
    }

    pub fn decode_payload<T: DeserializeOwned>(&self) -> Result<T, serde_json::Error> {
        serde_json::from_str(&self.payload_json)
    }

    pub fn payload_value(&self) -> Result<serde_json::Value, serde_json::Error> {
        self.decode_payload()
    }

    pub fn payload_size_bytes(&self) -> usize {
        self.payload_json.len()
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.feedback_type.entity_scoped() && self.entity_id == NULL_ENTITY_ID {
            return Err(format!(
                "{} feedback requires a non-null entity_id",
                self.feedback_type
            ));
        }
        if self.payload_json.is_empty() {
            return Err(format!(
                "{} feedback payload_json must not be empty",
                self.feedback_type
            ));
        }
        serde_json::from_str::<serde_json::Value>(&self.payload_json).map_err(|err| {
            format!(
                "{} feedback payload_json is invalid JSON: {}",
                self.feedback_type, err
            )
        })?;
        Ok(())
    }
}

/// Feedback batch for one simulation tick.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FeedbackPayload {
    pub tick: Tick,
    pub messages: Vec<FeedbackMessage>,
}

impl FeedbackPayload {
    pub fn empty(tick: Tick) -> Self {
        Self {
            tick,
            messages: Vec::new(),
        }
    }

    pub fn is_empty(&self) -> bool {
        self.messages.is_empty()
    }

    pub fn message_count(&self) -> usize {
        self.messages.len()
    }

    pub fn add_message(&mut self, message: FeedbackMessage) {
        self.messages.push(message);
    }

    pub fn add_typed_message<T: Serialize>(
        &mut self,
        feedback_type: FeedbackType,
        entity_id: EntityID,
        generated_frame: u64,
        payload: &T,
    ) -> Result<(), serde_json::Error> {
        self.messages.push(FeedbackMessage::from_typed_payload(
            feedback_type,
            entity_id,
            generated_frame,
            payload,
        )?);
        Ok(())
    }

    pub fn messages_of_type(&self, feedback_type: FeedbackType) -> Vec<&FeedbackMessage> {
        self.messages
            .iter()
            .filter(|message| message.feedback_type == feedback_type)
            .collect()
    }

    pub fn sorted_messages(&self) -> Vec<&FeedbackMessage> {
        let mut messages: Vec<&FeedbackMessage> = self.messages.iter().collect();
        messages.sort_by_key(|message| message.sort_key());
        messages
    }

    pub fn sort_in_place(&mut self) {
        self.messages.sort_by_key(FeedbackMessage::sort_key);
    }

    pub fn type_counts(&self) -> BTreeMap<u8, usize> {
        let mut counts = BTreeMap::new();
        for message in &self.messages {
            *counts.entry(message.feedback_type.as_u8()).or_insert(0) += 1;
        }
        counts
    }

    pub fn frame_range(&self) -> Option<(u64, u64)> {
        let min = self
            .messages
            .iter()
            .map(|message| message.generated_frame)
            .min()?;
        let max = self
            .messages
            .iter()
            .map(|message| message.generated_frame)
            .max()?;
        Some((min, max))
    }

    pub fn total_payload_bytes(&self) -> usize {
        self.messages
            .iter()
            .map(FeedbackMessage::payload_size_bytes)
            .sum()
    }

    pub fn validate(&self) -> Result<(), String> {
        for message in &self.messages {
            message.validate()?;
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_message(
        feedback_type: FeedbackType,
        entity_id: EntityID,
        generated_frame: u64,
    ) -> FeedbackMessage {
        FeedbackMessage::new(feedback_type, entity_id, generated_frame, "{}")
    }

    #[test]
    fn feedback_type_contract_is_stable() {
        for (idx, feedback_type) in FeedbackType::ALL.iter().copied().enumerate() {
            assert_eq!(feedback_type.as_u8(), idx as u8);
            assert_eq!(FeedbackType::from_u8(idx as u8), Some(feedback_type));
            assert!(!feedback_type.name().is_empty());
            assert!(!feedback_type.payload_kind().is_empty());
        }
        assert!(FeedbackType::from_u8(10).is_none());
    }

    #[test]
    fn empty_payload_is_empty() {
        let payload = FeedbackPayload::empty(0);
        assert!(payload.is_empty());
        assert_eq!(payload.message_count(), 0);
        assert!(payload.validate().is_ok());
    }

    #[test]
    fn add_message_increases_count() {
        let mut payload = FeedbackPayload::empty(1);
        payload.add_message(make_message(FeedbackType::AnimationStateUpdate, 1, 100));
        assert_eq!(payload.message_count(), 1);
        assert!(!payload.is_empty());
        assert!(payload.validate().is_ok());
    }

    #[test]
    fn sorted_messages_by_frame_entity_and_type() {
        let mut payload = FeedbackPayload::empty(1);
        payload.add_message(make_message(FeedbackType::PhysicsSettled, 5, 10));
        payload.add_message(make_message(FeedbackType::AnimationStateUpdate, 1, 8));
        payload.add_message(make_message(FeedbackType::AudioComplete, 3, 10));
        payload.add_message(make_message(FeedbackType::AnimationEventFired, 3, 10));

        let sorted = payload.sorted_messages();
        assert_eq!(sorted[0].generated_frame, 8);
        assert_eq!(sorted[1].entity_id, 3);
        assert_eq!(sorted[1].feedback_type, FeedbackType::AnimationEventFired);
        assert_eq!(sorted[2].feedback_type, FeedbackType::AudioComplete);
        assert_eq!(sorted[3].entity_id, 5);
    }

    #[test]
    fn type_counts_and_filters_work() {
        let mut payload = FeedbackPayload::empty(1);
        payload.add_message(make_message(FeedbackType::AnimationStateUpdate, 1, 0));
        payload.add_message(make_message(FeedbackType::AnimationStateUpdate, 2, 0));
        payload.add_message(make_message(FeedbackType::PhysicsSettled, 3, 0));

        assert_eq!(
            payload
                .messages_of_type(FeedbackType::AnimationStateUpdate)
                .len(),
            2
        );
        assert_eq!(
            payload
                .type_counts()
                .get(&FeedbackType::AnimationStateUpdate.as_u8()),
            Some(&2)
        );
    }

    #[test]
    fn typed_payload_roundtrip_works() {
        let feedback = EngineErrorFeedback {
            entity_id: 42,
            error_code: "missing_mesh".into(),
            error_message: "mesh not loaded".into(),
            generated_frame: 7,
        };
        let msg = FeedbackMessage::from_typed_payload(FeedbackType::EngineError, 42, 7, &feedback)
            .unwrap();
        let decoded: EngineErrorFeedback = msg.decode_payload().unwrap();
        assert_eq!(decoded.error_code, "missing_mesh");
        assert!(msg.validate().is_ok());
    }

    #[test]
    fn validation_rejects_invalid_json_and_null_entity_for_scoped_feedback() {
        let bad_json = FeedbackMessage::new(FeedbackType::EngineError, 1, 0, "not-json");
        assert!(bad_json.validate().is_err());

        let null_entity = FeedbackMessage::new(FeedbackType::EngineError, NULL_ENTITY_ID, 0, "{}");
        assert!(null_entity.validate().is_err());

        let metrics =
            FeedbackMessage::new(FeedbackType::PerformanceMetrics, NULL_ENTITY_ID, 0, "{}");
        assert!(metrics.validate().is_ok());
    }

    #[test]
    fn frame_range_and_payload_size_are_reported() {
        let mut payload = FeedbackPayload::empty(1);
        assert_eq!(payload.frame_range(), None);
        payload.add_message(make_message(
            FeedbackType::PerformanceMetrics,
            NULL_ENTITY_ID,
            10,
        ));
        payload.add_message(make_message(
            FeedbackType::PerformanceMetrics,
            NULL_ENTITY_ID,
            15,
        ));
        assert_eq!(payload.frame_range(), Some((10, 15)));
        assert!(payload.total_payload_bytes() > 0);
    }

    #[test]
    fn display_is_stable() {
        assert_eq!(
            FeedbackType::AnimationStateUpdate.to_string(),
            "AnimationStateUpdate"
        );
        assert_eq!(FeedbackType::EngineError.to_string(), "EngineError");
    }
}
