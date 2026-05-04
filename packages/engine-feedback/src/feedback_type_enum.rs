//! # Feedback Type Enum
//!
//! Re-exports `FeedbackType` from `xace_core` and adds runtime-side
//! handler dispatch mapping. Every feedback message received from the
//! engine adapter is routed to exactly one handler based on its type.
//!
//! ## Handler Assignment
//! Each `FeedbackType` maps to a `FeedbackHandlerKind` that identifies
//! which handler in the `feedback_router` processes it. This mapping
//! is the single authoritative source of truth — change it here and
//! the router changes automatically.
//!
//! ## Ten Feedback Types (Audit 6)
//! AnimationStateUpdate → AnimationHandler
//! AnimationEventFired  → AnimationHandler
//! PhysicsSettled       → PhysicsHandler
//! VisibilityQueryResult → VisibilityHandler
//! AudioComplete        → AudioHandler
//! AudioPositionUpdate  → AudioHandler
//! InputDeviceUpdate    → InputHandler
//! PerformanceMetrics   → PerformanceHandler
//! AssetResolutionUpdate → AssetHandler (Phase 14 Asset Registry)
//! EngineError          → ErrorHandler (log only, never halt)

pub use xace_core::wire::feedback_payload::FeedbackType;

// ── Handler Kind ──────────────────────────────────────────────────────────────

/// Identifies which handler processes a given `FeedbackType`.
///
/// Used by the `FeedbackRouter` to dispatch messages without a match
/// chain on every individual `FeedbackType` variant.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum FeedbackHandlerKind {
    /// Processes `AnimationStateUpdate` and `AnimationEventFired`.
    /// Writes current_normalized_time, is_transitioning, and
    /// active_state_per_layer back to `COMP_ANIMATION_V2`.
    Animation,

    /// Processes `PhysicsSettled`.
    /// Writes final resting position to `COMP_TRANSFORM_V1` via Mutation Gate.
    Physics,

    /// Processes `VisibilityQueryResult`.
    /// Writes can_see and distance to `COMP_PERCEPTION_V1` via Mutation Gate.
    Visibility,

    /// Processes `AudioComplete` and `AudioPositionUpdate`.
    /// Triggers follow-up game events for audio completion chains.
    Audio,

    /// Processes `InputDeviceUpdate`.
    /// Supplements the standard INPUT message for touch, gyro, and voice.
    Input,

    /// Processes `PerformanceMetrics`.
    /// Stores real engine performance data for the PIL performance risk guard.
    Performance,

    /// Processes `AssetResolutionUpdate`.
    /// Notifies the Asset Registry that PLACEHOLDER→LINKED transitions occurred.
    Asset,

    /// Processes `EngineError`.
    /// Logs the error and surfaces it to the builder UI. Never halts the runtime.
    Error,
}

impl std::fmt::Display for FeedbackHandlerKind {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            FeedbackHandlerKind::Animation   => write!(f, "AnimationHandler"),
            FeedbackHandlerKind::Physics     => write!(f, "PhysicsHandler"),
            FeedbackHandlerKind::Visibility  => write!(f, "VisibilityHandler"),
            FeedbackHandlerKind::Audio       => write!(f, "AudioHandler"),
            FeedbackHandlerKind::Input       => write!(f, "InputHandler"),
            FeedbackHandlerKind::Performance => write!(f, "PerformanceHandler"),
            FeedbackHandlerKind::Asset       => write!(f, "AssetHandler"),
            FeedbackHandlerKind::Error       => write!(f, "ErrorHandler"),
        }
    }
}

// ── Dispatch Mapping — Extension Trait ───────────────────────────────────────
//
// FeedbackType is defined in xace_core — Rust does not allow adding inherent
// methods to foreign types. We use an extension trait instead (the idiomatic fix).
// Import `FeedbackTypeExt` wherever these methods are needed.

/// Extension methods on `FeedbackType` for runtime handler dispatch.
pub trait FeedbackTypeExt {
    /// Returns the `FeedbackHandlerKind` responsible for processing this type.
    fn handler_kind(&self) -> FeedbackHandlerKind;

    /// Returns true if this type writes back via the Mutation Gate.
    fn requires_mutation_gate(&self) -> bool;

    /// Returns true if this type can emit a game Event via the EventBus.
    fn can_produce_events(&self) -> bool;

    /// Returns true if this type is purely informational (no runtime state changes).
    fn is_informational(&self) -> bool;
}

impl FeedbackTypeExt for FeedbackType {
    fn handler_kind(&self) -> FeedbackHandlerKind {
        match self {
            FeedbackType::AnimationStateUpdate  => FeedbackHandlerKind::Animation,
            FeedbackType::AnimationEventFired   => FeedbackHandlerKind::Animation,
            FeedbackType::PhysicsSettled        => FeedbackHandlerKind::Physics,
            FeedbackType::VisibilityQueryResult => FeedbackHandlerKind::Visibility,
            FeedbackType::AudioComplete         => FeedbackHandlerKind::Audio,
            FeedbackType::AudioPositionUpdate   => FeedbackHandlerKind::Audio,
            FeedbackType::InputDeviceUpdate     => FeedbackHandlerKind::Input,
            FeedbackType::PerformanceMetrics    => FeedbackHandlerKind::Performance,
            FeedbackType::AssetResolutionUpdate => FeedbackHandlerKind::Asset,
            FeedbackType::EngineError           => FeedbackHandlerKind::Error,
        }
    }

    fn requires_mutation_gate(&self) -> bool {
        matches!(
            self,
            FeedbackType::AnimationStateUpdate
                | FeedbackType::AnimationEventFired
                | FeedbackType::PhysicsSettled
                | FeedbackType::VisibilityQueryResult
        )
    }

    fn can_produce_events(&self) -> bool {
        matches!(
            self,
            FeedbackType::AnimationEventFired | FeedbackType::AudioComplete
        )
    }

    fn is_informational(&self) -> bool {
        matches!(
            self,
            FeedbackType::PerformanceMetrics
                | FeedbackType::AssetResolutionUpdate
                | FeedbackType::EngineError
        )
    }
}

/// Returns all ten feedback types in discriminant order.
/// Standalone function because `all()` cannot be part of the extension trait
/// (it returns a static slice, not a method on self).
pub fn all_feedback_types() -> &'static [FeedbackType] {
    &[
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
    ]
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn all_ten_types_covered() {
        assert_eq!(all_feedback_types().len(), 10);
    }

    #[test]
    fn all_types_have_a_handler_kind() {
        for ft in all_feedback_types() {
            let _ = ft.handler_kind(); // must not panic
        }
    }

    #[test]
    fn animation_types_map_to_animation_handler() {
        assert_eq!(
            FeedbackType::AnimationStateUpdate.handler_kind(),
            FeedbackHandlerKind::Animation
        );
        assert_eq!(
            FeedbackType::AnimationEventFired.handler_kind(),
            FeedbackHandlerKind::Animation
        );
    }

    #[test]
    fn physics_settled_maps_to_physics_handler() {
        assert_eq!(
            FeedbackType::PhysicsSettled.handler_kind(),
            FeedbackHandlerKind::Physics
        );
    }

    #[test]
    fn visibility_result_maps_to_visibility_handler() {
        assert_eq!(
            FeedbackType::VisibilityQueryResult.handler_kind(),
            FeedbackHandlerKind::Visibility
        );
    }

    #[test]
    fn audio_types_both_map_to_audio_handler() {
        assert_eq!(FeedbackType::AudioComplete.handler_kind(), FeedbackHandlerKind::Audio);
        assert_eq!(FeedbackType::AudioPositionUpdate.handler_kind(), FeedbackHandlerKind::Audio);
    }

    #[test]
    fn requires_mutation_gate_correct() {
        assert!(FeedbackType::AnimationStateUpdate.requires_mutation_gate());
        assert!(FeedbackType::PhysicsSettled.requires_mutation_gate());
        assert!(FeedbackType::VisibilityQueryResult.requires_mutation_gate());
        assert!(!FeedbackType::PerformanceMetrics.requires_mutation_gate());
        assert!(!FeedbackType::EngineError.requires_mutation_gate());
    }

    #[test]
    fn can_produce_events_correct() {
        assert!(FeedbackType::AnimationEventFired.can_produce_events());
        assert!(FeedbackType::AudioComplete.can_produce_events());
        assert!(!FeedbackType::PhysicsSettled.can_produce_events());
        assert!(!FeedbackType::PerformanceMetrics.can_produce_events());
    }

    #[test]
    fn is_informational_correct() {
        assert!(FeedbackType::PerformanceMetrics.is_informational());
        assert!(FeedbackType::AssetResolutionUpdate.is_informational());
        assert!(FeedbackType::EngineError.is_informational());
        assert!(!FeedbackType::AnimationStateUpdate.is_informational());
        assert!(!FeedbackType::PhysicsSettled.is_informational());
    }

    #[test]
    fn handler_kind_display_not_empty() {
        for ft in all_feedback_types() {
            assert!(!ft.handler_kind().to_string().is_empty());
        }
    }

    #[test]
    fn no_type_maps_to_wrong_handler() {
        // Spot-check cross-handler assignments
        assert_ne!(
            FeedbackType::PhysicsSettled.handler_kind(),
            FeedbackHandlerKind::Animation
        );
        assert_ne!(
            FeedbackType::AudioComplete.handler_kind(),
            FeedbackHandlerKind::Physics
        );
    }
}