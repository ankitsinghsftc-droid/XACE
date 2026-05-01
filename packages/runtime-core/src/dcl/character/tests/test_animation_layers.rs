//! # Animation Layer Manager Integration Tests

use crate::dcl::character::animation_layer_manager::{
    AnimationLayerManager, TransitionRequest,
};
use crate::dcl::character::animation_state_validator::{
    AnimationControllerDefinition, AnimationStateValidator, ParameterType,
    AnimationValidationErrorType,
};

fn standard_controller() -> AnimationControllerDefinition {
    AnimationControllerDefinition::permissive(
        "ctrl_player",
        vec!["Idle", "Run", "Jump", "Attack", "Death"],
        vec!["Base", "Upper", "Additive"],
    )
    .with_parameter("speed", ParameterType::Float)
    .with_parameter("is_grounded", ParameterType::Bool)
    .with_parameter("attack_trigger", ParameterType::Trigger)
}

// ── Layer Manager Tests ───────────────────────────────────────────────────────

#[test]
fn full_layer_lifecycle() {
    let mut m = AnimationLayerManager::new();
    m.add_layer("Base", "Idle").unwrap();
    m.add_layer("Upper", "Idle").unwrap();
    m.add_layer("Additive", "Empty").unwrap();

    assert_eq!(m.layer_count(), 3);
    assert_eq!(m.current_state("Base"), Some("Idle"));

    // Transition Base to Run
    m.request_transition(TransitionRequest::immediate("Base", "Run")).unwrap();
    assert_eq!(m.current_state("Base"), Some("Run"));

    // Upper still Idle
    assert_eq!(m.current_state("Upper"), Some("Idle"));
}

#[test]
fn blended_transition_completes_correctly() {
    let mut m = AnimationLayerManager::new();
    m.add_layer("Base", "Idle").unwrap();

    m.request_transition(
        TransitionRequest::blended("Base", "Run", 0.5)
    ).unwrap();

    // Partial progress
    let done = m.tick_transitions(0.4);
    assert!(done.is_empty());
    assert_eq!(m.current_state("Base"), Some("Idle")); // Not yet

    // Complete
    let done = m.tick_transitions(0.7);
    assert_eq!(done, vec!["Base"]);
    assert_eq!(m.current_state("Base"), Some("Run"));
}

#[test]
fn layer_names_alphabetical_order() {
    let mut m = AnimationLayerManager::new();
    m.add_layer("Z_Additive", "Empty").unwrap();
    m.add_layer("A_Base", "Idle").unwrap();
    m.add_layer("M_Upper", "Idle").unwrap();
    let names = m.layer_names();
    assert_eq!(names, vec!["A_Base", "M_Upper", "Z_Additive"]);
}

#[test]
fn to_json_contains_all_layers() {
    let mut m = AnimationLayerManager::new();
    m.add_layer("Base", "Idle").unwrap();
    m.add_layer("Upper", "Attack").unwrap();
    let json = m.to_json();
    assert!(json.contains("Base"));
    assert!(json.contains("Upper"));
    assert!(json.contains("Idle"));
    assert!(json.contains("Attack"));
}

#[test]
fn weight_management() {
    let mut m = AnimationLayerManager::new();
    m.add_layer("Upper", "Attack").unwrap();
    m.set_weight("Upper", 0.7).unwrap();
    assert!((m.get_layer("Upper").unwrap().weight - 0.7).abs() < 0.001);
}

// ── State Validator Integration Tests ─────────────────────────────────────────

#[test]
fn validator_and_manager_integrated_workflow() {
    let ctrl = standard_controller();
    let validator = AnimationStateValidator::new();
    let mut manager = AnimationLayerManager::new();
    manager.add_layer("Base", "Idle").unwrap();

    // Validate before applying
    let result = validator.validate_transition(
        "Base", "Idle", "Run", &ctrl
    );
    assert!(result.is_valid());

    // Apply after validation
    manager.request_transition(
        TransitionRequest::immediate("Base", "Run")
    ).unwrap();
    assert_eq!(manager.current_state("Base"), Some("Run"));
}

#[test]
fn validator_blocks_invalid_state_before_manager() {
    let ctrl = standard_controller();
    let validator = AnimationStateValidator::new();

    let result = validator.validate_transition(
        "Base", "Idle", "Flying", &ctrl // Invalid state
    );
    assert!(!result.is_valid());
    assert_eq!(
        result.errors[0].error_type,
        AnimationValidationErrorType::InvalidState
    );
    // Manager should NOT be updated when validation fails
}

#[test]
fn all_valid_parameters_pass() {
    let ctrl = standard_controller();
    let v = AnimationStateValidator::new();
    assert!(v.validate_parameter("speed", "3.14", &ctrl).is_valid());
    assert!(v.validate_parameter("is_grounded", "true", &ctrl).is_valid());
    assert!(v.validate_parameter("attack_trigger", "true", &ctrl).is_valid());
}

#[test]
fn snapshot_validation_full_state() {
    let ctrl = standard_controller();
    let v = AnimationStateValidator::new();
    let mut snapshot = std::collections::BTreeMap::new();
    snapshot.insert("Base".to_string(), "Run".to_string());
    snapshot.insert("Upper".to_string(), "Attack".to_string());
    snapshot.insert("Additive".to_string(), "Idle".to_string());
    let result = v.validate_snapshot(&snapshot, &ctrl);
    assert!(result.is_valid());
}

#[test]
fn determinism_two_managers_same_transitions_same_state() {
    let mut m1 = AnimationLayerManager::new();
    let mut m2 = AnimationLayerManager::new();
    m1.add_layer("Base", "Idle").unwrap();
    m2.add_layer("Base", "Idle").unwrap();

    for (state, duration) in [("Run", 0.3), ("Jump", 0.2), ("Idle", 0.1)] {
        m1.request_transition(
            TransitionRequest::blended("Base", state, duration)
        ).unwrap();
        m2.request_transition(
            TransitionRequest::blended("Base", state, duration)
        ).unwrap();
        m1.tick_transitions(1.0);
        m2.tick_transitions(1.0);
    }

    assert_eq!(m1.current_state("Base"), m2.current_state("Base"));
    assert_eq!(m1.to_json(), m2.to_json());
}