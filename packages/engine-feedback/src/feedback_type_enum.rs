//! Feedback type dispatch metadata.
//!
//! `FeedbackType` itself lives in `xace-core` as part of the wire contract.
//! This module adds runtime-side classification used by routers, handlers,
//! metrics, and safety checks.

pub use xace_core::wire::feedback_payload::FeedbackType;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum FeedbackHandlerKind {
    Animation,
    Physics,
    Visibility,
    Audio,
    Input,
    Performance,
    Asset,
    Error,
}

impl FeedbackHandlerKind {
    pub const ALL: [FeedbackHandlerKind; 8] = [
        FeedbackHandlerKind::Animation,
        FeedbackHandlerKind::Physics,
        FeedbackHandlerKind::Visibility,
        FeedbackHandlerKind::Audio,
        FeedbackHandlerKind::Input,
        FeedbackHandlerKind::Performance,
        FeedbackHandlerKind::Asset,
        FeedbackHandlerKind::Error,
    ];

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Animation => "animation",
            Self::Physics => "physics",
            Self::Visibility => "visibility",
            Self::Audio => "audio",
            Self::Input => "input",
            Self::Performance => "performance",
            Self::Asset => "asset",
            Self::Error => "error",
        }
    }

    pub fn display_name(self) -> &'static str {
        match self {
            Self::Animation => "AnimationHandler",
            Self::Physics => "PhysicsHandler",
            Self::Visibility => "VisibilityHandler",
            Self::Audio => "AudioHandler",
            Self::Input => "InputHandler",
            Self::Performance => "PerformanceHandler",
            Self::Asset => "AssetHandler",
            Self::Error => "ErrorHandler",
        }
    }
}

impl std::fmt::Display for FeedbackHandlerKind {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.display_name())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FeedbackEffect {
    MutationGateWrite,
    EventEmission,
    DiagnosticsOnly,
    InputAugmentation,
    AssetRegistryUpdate,
}

pub trait FeedbackTypeExt {
    fn handler_kind(&self) -> FeedbackHandlerKind;
    fn effect(&self) -> FeedbackEffect;
    fn requires_mutation_gate(&self) -> bool;
    fn can_produce_events(&self) -> bool;
    fn is_informational(&self) -> bool;
    fn requires_entity_id(&self) -> bool;
    fn is_entity_scoped(&self) -> bool;
    fn is_high_volume(&self) -> bool;
    fn route_priority(&self) -> u8;
    fn stable_name(&self) -> &'static str;
}

impl FeedbackTypeExt for FeedbackType {
    fn handler_kind(&self) -> FeedbackHandlerKind {
        match self {
            FeedbackType::AnimationStateUpdate | FeedbackType::AnimationEventFired => {
                FeedbackHandlerKind::Animation
            }
            FeedbackType::PhysicsSettled => FeedbackHandlerKind::Physics,
            FeedbackType::VisibilityQueryResult => FeedbackHandlerKind::Visibility,
            FeedbackType::AudioComplete | FeedbackType::AudioPositionUpdate => {
                FeedbackHandlerKind::Audio
            }
            FeedbackType::InputDeviceUpdate => FeedbackHandlerKind::Input,
            FeedbackType::PerformanceMetrics => FeedbackHandlerKind::Performance,
            FeedbackType::AssetResolutionUpdate => FeedbackHandlerKind::Asset,
            FeedbackType::EngineError => FeedbackHandlerKind::Error,
        }
    }

    fn effect(&self) -> FeedbackEffect {
        match self {
            FeedbackType::AnimationStateUpdate
            | FeedbackType::PhysicsSettled
            | FeedbackType::VisibilityQueryResult => FeedbackEffect::MutationGateWrite,
            FeedbackType::AnimationEventFired
            | FeedbackType::AudioComplete
            | FeedbackType::AudioPositionUpdate => FeedbackEffect::EventEmission,
            FeedbackType::InputDeviceUpdate => FeedbackEffect::InputAugmentation,
            FeedbackType::AssetResolutionUpdate => FeedbackEffect::AssetRegistryUpdate,
            FeedbackType::PerformanceMetrics | FeedbackType::EngineError => {
                FeedbackEffect::DiagnosticsOnly
            }
        }
    }

    fn requires_mutation_gate(&self) -> bool {
        self.effect() == FeedbackEffect::MutationGateWrite
    }

    fn can_produce_events(&self) -> bool {
        self.effect() == FeedbackEffect::EventEmission
    }

    fn is_informational(&self) -> bool {
        matches!(
            self.effect(),
            FeedbackEffect::DiagnosticsOnly | FeedbackEffect::AssetRegistryUpdate
        )
    }

    fn requires_entity_id(&self) -> bool {
        !matches!(
            self,
            FeedbackType::PerformanceMetrics
                | FeedbackType::AssetResolutionUpdate
                | FeedbackType::InputDeviceUpdate
        )
    }

    fn is_entity_scoped(&self) -> bool {
        self.requires_entity_id()
    }

    fn is_high_volume(&self) -> bool {
        matches!(
            self,
            FeedbackType::AnimationStateUpdate
                | FeedbackType::PhysicsSettled
                | FeedbackType::VisibilityQueryResult
                | FeedbackType::AudioPositionUpdate
                | FeedbackType::InputDeviceUpdate
                | FeedbackType::PerformanceMetrics
        )
    }

    fn route_priority(&self) -> u8 {
        match self {
            FeedbackType::EngineError => 0,
            FeedbackType::InputDeviceUpdate => 10,
            FeedbackType::PhysicsSettled => 20,
            FeedbackType::VisibilityQueryResult => 30,
            FeedbackType::AnimationEventFired => 40,
            FeedbackType::AnimationStateUpdate => 50,
            FeedbackType::AudioComplete => 60,
            FeedbackType::AudioPositionUpdate => 70,
            FeedbackType::AssetResolutionUpdate => 80,
            FeedbackType::PerformanceMetrics => 90,
        }
    }

    fn stable_name(&self) -> &'static str {
        self.name()
    }
}

pub fn all_feedback_types() -> &'static [FeedbackType] {
    &FeedbackType::ALL
}

pub fn handler_kind_for(feedback_type: FeedbackType) -> FeedbackHandlerKind {
    feedback_type.handler_kind()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn all_core_types_are_exposed() {
        assert_eq!(all_feedback_types().len(), 10);
        for (idx, feedback_type) in all_feedback_types().iter().copied().enumerate() {
            assert_eq!(feedback_type.as_u8(), idx as u8);
            assert!(!feedback_type.stable_name().is_empty());
        }
    }

    #[test]
    fn dispatch_mapping_is_stable() {
        assert_eq!(
            FeedbackType::AnimationEventFired.handler_kind(),
            FeedbackHandlerKind::Animation
        );
        assert_eq!(
            FeedbackType::VisibilityQueryResult.handler_kind(),
            FeedbackHandlerKind::Visibility
        );
        assert_eq!(
            FeedbackType::PerformanceMetrics.handler_kind(),
            FeedbackHandlerKind::Performance
        );
    }

    #[test]
    fn effect_helpers_match_handler_contracts() {
        assert!(FeedbackType::PhysicsSettled.requires_mutation_gate());
        assert!(FeedbackType::AudioComplete.can_produce_events());
        assert!(FeedbackType::EngineError.is_informational());
        assert!(!FeedbackType::PerformanceMetrics.requires_entity_id());
        assert!(!FeedbackType::InputDeviceUpdate.requires_entity_id());
    }
}
