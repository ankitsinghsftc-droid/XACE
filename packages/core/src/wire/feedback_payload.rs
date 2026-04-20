//! # Feedback Payload
//!
//! Defines the engine feedback message types sent from the engine
//! adapter to the XACE runtime every tick. Engine feedback is the
//! return channel — XACE sends commands, the engine sends results back.
//!
//! ## Audit 6 — Engine Feedback Protocol
//! Communication between XACE and the engine is bidirectional.
//! XACE sends StateDelta commands to the engine each tick.
//! The engine sends back a FeedbackPayload containing:
//! - Animation state updates (current state, normalized time)
//! - Physics results (ragdoll settle positions)
//! - Visibility query results (raycast results)
//! - Audio completion notifications
//! - Input device updates (extended input)
//! - Performance metrics (ms/tick per system)
//! - Asset resolution updates
//! - Engine-side errors
//!
//! ## Global Invariant I13
//! Engine feedback is processed ONLY at tick boundaries — never mid-tick.
//! The FeedbackBuffer drains at the START of each tick before any
//! phase runs. This ensures deterministic feedback integration.
//!
//! ## Determinism
//! Feedback messages are sorted by (generated_frame ASC, entity_id ASC)
//! before processing. Same feedback sequence = same world state (D9).
//! Feedback is included in replay files for exact replay fidelity.

use std::collections::BTreeMap;
use serde::{Deserialize, Serialize};
use crate::entity_id::EntityID;

// ── Feedback Type ─────────────────────────────────────────────────────────────

/// The type of engine feedback message.
///
/// Ten feedback types covering all bidirectional communication
/// from the engine adapter back to the XACE runtime.
/// Discriminants are frozen — part of the public wire protocol.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[repr(u8)]
pub enum FeedbackType {
    /// Current animation state, normalized time, and layer states.
    /// Written back to COMP_ANIMATION_V2 fields by animation handler.
    AnimationStateUpdate = 0,

    /// A specific animation trigger point was reached.
    /// Causes XACE to fire the associated game event.
    AnimationEventFired = 1,

    /// A ragdoll or physics object reached its final resting position.
    /// Physics handler updates COMP_TRANSFORM_V1 via Mutation Gate.
    PhysicsSettled = 2,

    /// Result of a visibility raycast query.
    /// Written to COMP_PERCEPTION_V1.visibility_result via Mutation Gate.
    VisibilityQueryResult = 3,

    /// An audio clip finished playing.
    /// Allows XACE to trigger follow-up events or state changes.
    AudioComplete = 4,

    /// A 3D audio source moved in the engine scene.
    /// Used to keep XACE's audio state synchronized.
    AudioPositionUpdate = 5,

    /// Extended input update — touch, gyro, voice amplitude.
    /// Supplements the standard INPUT message for special input devices.
    InputDeviceUpdate = 6,

    /// Engine performance metrics for the previous tick.
    /// Fed into the PIL performance risk guard (Phase 13) for real data.
    PerformanceMetrics = 7,

    /// One or more PLACEHOLDER asset references transitioned to LINKED.
    /// The Asset Registry updates asset status on receipt.
    AssetResolutionUpdate = 8,

    /// An engine-side error that XACE should know about.
    /// Logged and surfaced to the builder UI. Never causes runtime halt.
    EngineError = 9,
}

impl FeedbackType {
    pub fn as_u8(&self) -> u8 {
        *self as u8
    }

    pub fn from_u8(value: u8) -> Option<Self> {
        match value {
            0 => Some(FeedbackType::AnimationStateUpdate),
            1 => Some(FeedbackType::AnimationEventFired),
            2 => Some(FeedbackType::PhysicsSettled),
            3 => Some(FeedbackType::VisibilityQueryResult),
            4 => Some(FeedbackType::AudioComplete),
            5 => Some(FeedbackType::AudioPositionUpdate),
            6 => Some(FeedbackType::InputDeviceUpdate),
            7 => Some(FeedbackType::PerformanceMetrics),
            8 => Some(FeedbackType::AssetResolutionUpdate),
            9 => Some(FeedbackType::EngineError),
            _ => None,
        }
    }

    pub fn name(&self) -> &'static str {
        match self {
            FeedbackType::AnimationStateUpdate => "AnimationStateUpdate",
            FeedbackType::AnimationEventFired => "AnimationEventFired",
            FeedbackType::PhysicsSettled => "PhysicsSettled",
            FeedbackType::VisibilityQueryResult => "VisibilityQueryResult",
            FeedbackType::AudioComplete => "AudioComplete",
            FeedbackType::AudioPositionUpdate => "AudioPositionUpdate",
            FeedbackType::InputDeviceUpdate => "InputDeviceUpdate",
            FeedbackType::PerformanceMetrics => "PerformanceMetrics",
            FeedbackType::AssetResolutionUpdate => "AssetResolutionUpdate",
            FeedbackType::EngineError => "EngineError",
        }
    }
}

impl std::fmt::Display for FeedbackType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.name())
    }
}

// ── Individual Feedback Message Types ─────────────────────────────────────────

/// Animation state written back from the engine after it processes
/// COMP_ANIMATION_V2 commands. XACE updates the component fields
/// via Mutation Gate on receipt.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AnimationStateUpdateFeedback {
    /// The entity whose animation state updated.
    pub entity_id: EntityID,

    /// Current animation state name per layer.
    /// BTreeMap<layer_name, current_state> — sorted for determinism (D11).
    pub active_state_per_layer: BTreeMap<String, String>,

    /// Current playback position (0.0 = start, 1.0 = end) per layer.
    pub normalized_time_per_layer: BTreeMap<String, f32>,

    /// Whether the animation is currently transitioning between states.
    pub is_transitioning: bool,

    /// The engine frame on which this feedback was generated.
    /// Used for deterministic sort ordering within the FeedbackBuffer.
    pub generated_frame: u64,
}

/// Notification that a specific animation event trigger was reached.
/// XACE processes this at the next tick boundary and fires the
/// associated game event via the EventBus.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AnimationEventFiredFeedback {
    /// The entity whose animation fired the event.
    pub entity_id: EntityID,

    /// The animation event ID that was triggered.
    pub event_id: String,

    /// The animation state that triggered the event.
    pub state_name: String,

    /// The normalized time at which the event fired (0.0 - 1.0).
    pub trigger_at_normalized_time: f32,

    /// The engine frame on which this feedback was generated.
    pub generated_frame: u64,
}

/// Physics object has reached its final resting position.
/// The physics handler writes the final position to COMP_TRANSFORM_V1
/// via the Mutation Gate so XACE's authoritative state matches the engine.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PhysicsSettledFeedback {
    /// The entity that settled.
    pub entity_id: EntityID,

    /// Final position serialized as JSON {"x": f32, "y": f32, "z": f32}.
    pub final_position_json: String,

    /// Final rotation serialized as JSON {"x": f32, "y": f32, "z": f32, "w": f32}.
    pub final_rotation_json: String,

    /// The engine frame on which this feedback was generated.
    pub generated_frame: u64,
}

/// Result of a visibility raycast query initiated by XACE.
/// XACE writes COMP_PERCEPTION_V1.visibility_query_pending = true →
/// engine performs raycast → engine returns result next tick →
/// visibility handler writes result to COMP_PERCEPTION_V1.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct VisibilityQueryResultFeedback {
    /// The entity that initiated the visibility query (the observer).
    pub observer_entity_id: EntityID,

    /// The entity being observed (the target).
    pub target_entity_id: EntityID,

    /// Whether the observer can see the target.
    /// True = line of sight exists. False = occluded.
    pub can_see: bool,

    /// Distance between observer and target in world units.
    /// 0.0 if can_see is false and distance could not be measured.
    pub distance: f32,

    /// The engine frame on which this feedback was generated.
    pub generated_frame: u64,
}

/// An audio clip finished playing on an entity.
/// Allows XACE to trigger follow-up events or state changes
/// without polling the engine for audio completion state.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AudioCompleteFeedback {
    /// The entity whose audio completed.
    pub entity_id: EntityID,

    /// The asset ID of the audio clip that completed.
    pub asset_id: String,

    /// Whether the clip looped (reached end and restarted)
    /// or stopped (reached end and halted).
    pub did_loop: bool,

    /// The engine frame on which this feedback was generated.
    pub generated_frame: u64,
}

/// Performance metrics from the engine for the previous tick.
/// Fed into the PIL's performance risk guard for real usage data.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PerformanceMetricsFeedback {
    /// Milliseconds the engine spent processing the previous tick's delta.
    pub engine_delta_apply_ms: f32,

    /// Total draw calls issued in the previous frame.
    pub draw_calls: u32,

    /// Number of active physics contacts in the previous frame.
    pub physics_contacts: u32,

    /// Active entity count as seen by the engine.
    /// Cross-referenced with XACE's EntityStore for desync detection.
    pub engine_entity_count: u32,

    /// The engine frame on which this feedback was generated.
    pub generated_frame: u64,
}

/// One or more asset references transitioned from PLACEHOLDER to LINKED.
/// The Asset Registry updates asset status on receipt.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AssetResolutionUpdateFeedback {
    /// Asset IDs that are now fully linked in the engine.
    /// BTreeMap<asset_id, resolved_path> — sorted for determinism (D11).
    pub resolved_assets: BTreeMap<String, String>,

    /// The engine frame on which this feedback was generated.
    pub generated_frame: u64,
}

/// An engine-side error that XACE should know about.
/// Never causes XACE runtime to halt — logged and surfaced to UI.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EngineErrorFeedback {
    /// The entity related to this error, if any.
    /// NULL_ENTITY_ID if the error is not entity-specific.
    pub entity_id: EntityID,

    /// Error code from the engine adapter.
    pub error_code: String,

    /// Human-readable error description.
    pub error_message: String,

    /// The engine frame on which this feedback was generated.
    pub generated_frame: u64,
}

// ── Feedback Message ──────────────────────────────────────────────────────────

/// A single feedback message from the engine adapter to XACE.
///
/// Wraps one of the ten feedback types with its sort key fields.
/// The FeedbackBuffer accumulates these each tick and sorts them
/// by (generated_frame ASC, entity_id ASC) before draining (I13).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct FeedbackMessage {
    /// What kind of feedback this is.
    pub feedback_type: FeedbackType,

    /// The primary entity this feedback relates to.
    /// Used as the secondary sort key in the FeedbackBuffer (I13).
    /// NULL_ENTITY_ID for non-entity feedback (PerformanceMetrics, etc.)
    pub entity_id: EntityID,

    /// The engine frame this feedback was generated in.
    /// Primary sort key in the FeedbackBuffer.
    pub generated_frame: u64,

    /// The typed feedback data serialized as JSON.
    /// Deserialized by the appropriate feedback handler in Phase 7.
    pub payload_json: String,
}

impl FeedbackMessage {
    /// Returns the deterministic sort key for this feedback message.
    /// FeedbackBuffer sorts by (generated_frame ASC, entity_id ASC) (I13).
    pub fn sort_key(&self) -> (u64, EntityID) {
        (self.generated_frame, self.entity_id)
    }
}

// ── Feedback Payload ──────────────────────────────────────────────────────────

/// The complete engine feedback payload for one tick.
///
/// Sent by the engine adapter to XACE every tick via a FEEDBACK
/// WireMessage. Contains all feedback messages generated by the
/// engine during that tick's processing.
///
/// ## Processing (I13)
/// The FeedbackBuffer accumulates incoming FeedbackPayloads between ticks.
/// At the START of each tick, before any phase runs, the buffer drains:
/// 1. Collect all FeedbackMessages from the buffer
/// 2. Sort by (generated_frame ASC, entity_id ASC)
/// 3. Route each message to its registered handler
/// 4. Handlers write results to components via Mutation Gate
/// 5. Mutation Gate processes all handler writes before Initialization phase
///
/// ## Replay Fidelity
/// FeedbackPayloads are logged to the feedback_log for replay.
/// Replays must replay the same feedback sequence to produce
/// identical world state (same world_hash at each tick).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FeedbackPayload {
    /// The tick this feedback was generated for.
    pub tick: u64,

    /// All feedback messages from this tick.
    /// Unsorted on arrival — sorted by FeedbackBuffer before processing.
    pub messages: Vec<FeedbackMessage>,
}

impl FeedbackPayload {
    /// Creates an empty feedback payload for the given tick.
    pub fn empty(tick: u64) -> Self {
        Self {
            tick,
            messages: Vec::new(),
        }
    }

    /// Returns true if there are no feedback messages this tick.
    pub fn is_empty(&self) -> bool {
        self.messages.is_empty()
    }

    /// Returns the total number of feedback messages.
    pub fn message_count(&self) -> usize {
        self.messages.len()
    }

    /// Adds a feedback message to this payload.
    pub fn add_message(&mut self, message: FeedbackMessage) {
        self.messages.push(message);
    }

    /// Returns all messages of a specific feedback type.
    pub fn messages_of_type(
        &self,
        feedback_type: FeedbackType,
    ) -> Vec<&FeedbackMessage> {
        self.messages
            .iter()
            .filter(|m| m.feedback_type == feedback_type)
            .collect()
    }

    /// Sorts all messages by (generated_frame ASC, entity_id ASC).
    /// Called by the FeedbackBuffer before draining (I13).
    /// Returns the sorted messages without modifying self.
    pub fn sorted_messages(&self) -> Vec<&FeedbackMessage> {
        let mut messages: Vec<&FeedbackMessage> = self.messages.iter().collect();
        messages.sort_by_key(|m| m.sort_key());
        messages
    }

    /// Returns the count of messages for each feedback type.
    /// Used by the builder UI performance panel and Design Mentor.
    pub fn type_counts(&self) -> BTreeMap<u8, usize> {
        let mut counts = BTreeMap::new();
        for msg in &self.messages {
            *counts.entry(msg.feedback_type.as_u8()).or_insert(0) += 1;
        }
        counts
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn make_message(
        feedback_type: FeedbackType,
        entity_id: EntityID,
        generated_frame: u64,
    ) -> FeedbackMessage {
        FeedbackMessage {
            feedback_type,
            entity_id,
            generated_frame,
            payload_json: "{}".into(),
        }
    }

    #[test]
    fn empty_payload_is_empty() {
        let payload = FeedbackPayload::empty(0);
        assert!(payload.is_empty());
        assert_eq!(payload.message_count(), 0);
    }

    #[test]
    fn add_message_increases_count() {
        let mut payload = FeedbackPayload::empty(1);
        payload.add_message(make_message(
            FeedbackType::AnimationStateUpdate,
            1,
            100,
        ));
        assert_eq!(payload.message_count(), 1);
        assert!(!payload.is_empty());
    }

    #[test]
    fn sorted_messages_by_frame_then_entity() {
        let mut payload = FeedbackPayload::empty(1);
        payload.add_message(make_message(FeedbackType::PhysicsSettled, 5, 10));
        payload.add_message(make_message(FeedbackType::AnimationStateUpdate, 1, 8));
        payload.add_message(make_message(FeedbackType::AudioComplete, 3, 10));
        let sorted = payload.sorted_messages();
        // frame 8 first
        assert_eq!(sorted[0].generated_frame, 8);
        // frame 10, entity 3 before entity 5
        assert_eq!(sorted[1].generated_frame, 10);
        assert_eq!(sorted[1].entity_id, 3);
        assert_eq!(sorted[2].entity_id, 5);
    }

    #[test]
    fn messages_of_type_filters_correctly() {
        let mut payload = FeedbackPayload::empty(1);
        payload.add_message(make_message(
            FeedbackType::AnimationStateUpdate, 1, 0
        ));
        payload.add_message(make_message(
            FeedbackType::AnimationStateUpdate, 2, 0
        ));
        payload.add_message(make_message(
            FeedbackType::PhysicsSettled, 3, 0
        ));
        let anim = payload.messages_of_type(FeedbackType::AnimationStateUpdate);
        assert_eq!(anim.len(), 2);
        let physics = payload.messages_of_type(FeedbackType::PhysicsSettled);
        assert_eq!(physics.len(), 1);
    }

    #[test]
    fn type_counts_correct() {
        let mut payload = FeedbackPayload::empty(1);
        payload.add_message(make_message(FeedbackType::AnimationStateUpdate, 1, 0));
        payload.add_message(make_message(FeedbackType::AnimationStateUpdate, 2, 0));
        payload.add_message(make_message(FeedbackType::PhysicsSettled, 3, 0));
        let counts = payload.type_counts();
        assert_eq!(
            counts.get(&FeedbackType::AnimationStateUpdate.as_u8()),
            Some(&2)
        );
        assert_eq!(
            counts.get(&FeedbackType::PhysicsSettled.as_u8()),
            Some(&1)
        );
    }

    #[test]
    fn feedback_type_roundtrip() {
        for i in 0u8..10 {
            let ft = FeedbackType::from_u8(i).unwrap();
            assert_eq!(ft.as_u8(), i);
        }
    }

    #[test]
    fn invalid_feedback_type_returns_none() {
        assert!(FeedbackType::from_u8(10).is_none());
        assert!(FeedbackType::from_u8(255).is_none());
    }

    #[test]
    fn all_feedback_types_have_names() {
        for i in 0u8..10 {
            let ft = FeedbackType::from_u8(i).unwrap();
            assert!(!ft.name().is_empty());
        }
    }

    #[test]
    fn sort_key_uses_frame_then_entity() {
        let msg1 = make_message(FeedbackType::PhysicsSettled, 5, 10);
        let msg2 = make_message(FeedbackType::PhysicsSettled, 3, 10);
        let msg3 = make_message(FeedbackType::PhysicsSettled, 1, 8);
        assert!(msg3.sort_key() < msg2.sort_key());
        assert!(msg2.sort_key() < msg1.sort_key());
    }

    #[test]
    fn feedback_type_display() {
        assert_eq!(
            FeedbackType::AnimationStateUpdate.to_string(),
            "AnimationStateUpdate"
        );
        assert_eq!(FeedbackType::EngineError.to_string(), "EngineError");
    }

    #[test]
    fn tick_stored_in_payload() {
        let payload = FeedbackPayload::empty(42);
        assert_eq!(payload.tick, 42);
    }
}