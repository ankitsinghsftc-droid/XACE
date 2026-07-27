use crate::feedback_router::FeedbackHandler;
use crate::feedback_type_enum::FeedbackHandlerKind;
use crate::handlers::{
    AnimationFeedbackHandler, AudioFeedbackHandler, InputFeedbackHandler,
    PerformanceFeedbackHandler, PhysicsFeedbackHandler, VisibilityFeedbackHandler,
};
use xace_core::wire::feedback_payload::FeedbackType;

#[test]
fn default_handlers_advertise_stable_kinds() {
    assert_eq!(
        AnimationFeedbackHandler::new().kind(),
        FeedbackHandlerKind::Animation
    );
    assert_eq!(
        PhysicsFeedbackHandler::new().kind(),
        FeedbackHandlerKind::Physics
    );
    assert_eq!(
        VisibilityFeedbackHandler::new().kind(),
        FeedbackHandlerKind::Visibility
    );
    assert_eq!(
        AudioFeedbackHandler::new().kind(),
        FeedbackHandlerKind::Audio
    );
    assert_eq!(
        InputFeedbackHandler::new().kind(),
        FeedbackHandlerKind::Input
    );
    assert_eq!(
        PerformanceFeedbackHandler::new().kind(),
        FeedbackHandlerKind::Performance
    );
}

#[test]
fn default_handlers_accept_only_their_feedback_types() {
    let animation = AnimationFeedbackHandler::new();
    assert!(animation.can_handle(FeedbackType::AnimationStateUpdate));
    assert!(animation.can_handle(FeedbackType::AnimationEventFired));
    assert!(!animation.can_handle(FeedbackType::PhysicsSettled));

    let physics = PhysicsFeedbackHandler::new();
    assert!(physics.can_handle(FeedbackType::PhysicsSettled));
    assert!(!physics.can_handle(FeedbackType::AudioComplete));

    let visibility = VisibilityFeedbackHandler::new();
    assert!(visibility.can_handle(FeedbackType::VisibilityQueryResult));
    assert!(!visibility.can_handle(FeedbackType::PerformanceMetrics));

    let audio = AudioFeedbackHandler::new();
    assert!(audio.can_handle(FeedbackType::AudioComplete));
    assert!(audio.can_handle(FeedbackType::AudioPositionUpdate));
    assert!(!audio.can_handle(FeedbackType::InputDeviceUpdate));

    let input = InputFeedbackHandler::new();
    assert!(input.can_handle(FeedbackType::InputDeviceUpdate));
    assert!(!input.can_handle(FeedbackType::AnimationStateUpdate));

    let performance = PerformanceFeedbackHandler::new();
    assert!(performance.can_handle(FeedbackType::PerformanceMetrics));
    assert!(!performance.can_handle(FeedbackType::VisibilityQueryResult));
}
