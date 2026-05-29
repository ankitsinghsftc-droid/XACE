//! # Animation State Validator
//!
//! Validates animation state transitions before they are applied to
//! COMP_ANIMATION_V2. Ensures transitions are valid according to
//! the animation controller's state machine definition.
//!
//! ## Validation Goals
//! - Prevent invalid state names from entering COMP_ANIMATION_V2
//! - Validate parameter types match their declarations
//! - Ensure layer names are valid for the controller
//! - Block contradictory parameter combinations
//!
//! ## Design
//! The validator is stateless — it takes a controller definition
//! and validates against it. Multiple entities can share one
//! validator instance since it holds no per-entity state.

use std::collections::{BTreeMap, BTreeSet};

// ── Parameter Type ────────────────────────────────────────────────────────────

/// The type of an animation controller parameter.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ParameterType {
    Bool,
    Float,
    Int,
    Trigger,
}

// ── Controller Definition ─────────────────────────────────────────────────────

/// The declared structure of one animation controller.
///
/// This mirrors the AnimationContract generated from COMP_ANIMATION_V2
/// (Audit 2, Asset Pipeline). Used by the validator to check that
/// state transitions and parameter mutations are valid.
#[derive(Debug, Clone)]
pub struct AnimationControllerDefinition {
    /// Controller asset ID.
    pub controller_id: String,

    /// All valid state names in this controller.
    /// BTreeSet for deterministic iteration (D11).
    pub valid_states: BTreeSet<String>,

    /// All valid layer names.
    pub valid_layers: BTreeSet<String>,

    /// Parameter declarations: name → type.
    pub parameters: BTreeMap<String, ParameterType>,

    /// Valid transitions: (from_state, to_state).
    /// Empty set means all transitions allowed.
    pub allowed_transitions: BTreeSet<(String, String)>,

    /// Whether to use strict transition validation.
    /// true = only allowed_transitions are valid.
    /// false = any state-to-state transition is valid.
    pub strict_transitions: bool,
}

impl AnimationControllerDefinition {
    /// Creates a permissive controller definition with the given states.
    /// All transitions allowed. Used when strict validation is not needed.
    pub fn permissive(
        controller_id: impl Into<String>,
        states: Vec<&str>,
        layers: Vec<&str>,
    ) -> Self {
        Self {
            controller_id: controller_id.into(),
            valid_states: states.iter().map(|s| s.to_string()).collect(),
            valid_layers: layers.iter().map(|s| s.to_string()).collect(),
            parameters: BTreeMap::new(),
            allowed_transitions: BTreeSet::new(),
            strict_transitions: false,
        }
    }

    pub fn with_parameter(mut self, name: impl Into<String>, param_type: ParameterType) -> Self {
        self.parameters.insert(name.into(), param_type);
        self
    }

    pub fn with_transition(mut self, from: impl Into<String>, to: impl Into<String>) -> Self {
        self.allowed_transitions.insert((from.into(), to.into()));
        self
    }
}

// ── Validation Error ──────────────────────────────────────────────────────────

/// An animation validation error.
#[derive(Debug, Clone, PartialEq)]
pub struct AnimationValidationError {
    pub error_type: AnimationValidationErrorType,
    pub message: String,
}

#[derive(Debug, Clone, PartialEq)]
pub enum AnimationValidationErrorType {
    InvalidState,
    InvalidLayer,
    InvalidParameter,
    InvalidParameterType,
    TransitionNotAllowed,
    InvalidWeight,
}

impl AnimationValidationError {
    pub fn new(error_type: AnimationValidationErrorType, message: impl Into<String>) -> Self {
        Self {
            error_type,
            message: message.into(),
        }
    }
}

// ── Validation Result ─────────────────────────────────────────────────────────

/// Result of an animation validation check.
#[derive(Debug)]
pub struct AnimationValidationResult {
    pub errors: Vec<AnimationValidationError>,
    pub warnings: Vec<String>,
}

impl AnimationValidationResult {
    pub fn valid() -> Self {
        Self {
            errors: Vec::new(),
            warnings: Vec::new(),
        }
    }

    pub fn is_valid(&self) -> bool {
        self.errors.is_empty()
    }

    pub fn add_error(&mut self, error: AnimationValidationError) {
        self.errors.push(error);
    }

    pub fn add_warning(&mut self, warning: impl Into<String>) {
        self.warnings.push(warning.into());
    }
}

// ── Animation State Validator ─────────────────────────────────────────────────

/// Validates animation state mutations before applying to COMP_ANIMATION_V2.
///
/// Stateless — all validation context passed as parameters.
/// Multiple entities can share one validator instance.
pub struct AnimationStateValidator;

impl AnimationStateValidator {
    pub fn new() -> Self {
        Self
    }

    /// Validates a state transition request.
    ///
    /// Checks:
    /// - from_state is a valid state (or empty for initial)
    /// - to_state is a valid state
    /// - transition is allowed (if strict mode)
    /// - layer_name is valid
    pub fn validate_transition(
        &self,
        layer_name: &str,
        from_state: &str,
        to_state: &str,
        controller: &AnimationControllerDefinition,
    ) -> AnimationValidationResult {
        let mut result = AnimationValidationResult::valid();

        // Validate layer name
        if !controller.valid_layers.contains(layer_name) {
            result.add_error(AnimationValidationError::new(
                AnimationValidationErrorType::InvalidLayer,
                format!(
                    "Layer '{}' not found in controller '{}' — \
                     valid layers: {:?}",
                    layer_name, controller.controller_id, controller.valid_layers,
                ),
            ));
        }

        // Validate target state
        if !controller.valid_states.contains(to_state) {
            result.add_error(AnimationValidationError::new(
                AnimationValidationErrorType::InvalidState,
                format!(
                    "State '{}' not found in controller '{}' — \
                     valid states: {:?}",
                    to_state, controller.controller_id, controller.valid_states,
                ),
            ));
        }

        // Validate from_state if not initial
        if !from_state.is_empty() && !controller.valid_states.contains(from_state) {
            result.add_error(AnimationValidationError::new(
                AnimationValidationErrorType::InvalidState,
                format!(
                    "Source state '{}' not found in controller '{}'",
                    from_state, controller.controller_id,
                ),
            ));
        }

        // Validate transition is allowed (strict mode only)
        if controller.strict_transitions && !from_state.is_empty() {
            let transition = (from_state.to_string(), to_state.to_string());
            if !controller.allowed_transitions.contains(&transition) {
                result.add_error(AnimationValidationError::new(
                    AnimationValidationErrorType::TransitionNotAllowed,
                    format!(
                        "Transition '{}' → '{}' not allowed in controller '{}'",
                        from_state, to_state, controller.controller_id,
                    ),
                ));
            }
        }

        result
    }

    /// Validates a parameter value update.
    ///
    /// Checks:
    /// - Parameter name is declared
    /// - Value type matches declared parameter type
    pub fn validate_parameter(
        &self,
        param_name: &str,
        value: &str, // JSON string value
        controller: &AnimationControllerDefinition,
    ) -> AnimationValidationResult {
        let mut result = AnimationValidationResult::valid();

        let Some(param_type) = controller.parameters.get(param_name) else {
            result.add_error(AnimationValidationError::new(
                AnimationValidationErrorType::InvalidParameter,
                format!(
                    "Parameter '{}' not declared in controller '{}' — \
                     declared parameters: {:?}",
                    param_name,
                    controller.controller_id,
                    controller.parameters.keys().collect::<Vec<_>>(),
                ),
            ));
            return result;
        };

        // Validate value matches declared type
        let type_valid = match param_type {
            ParameterType::Bool => value == "true" || value == "false",
            ParameterType::Float => value.parse::<f64>().is_ok(),
            ParameterType::Int => value.parse::<i64>().is_ok(),
            ParameterType::Trigger => value == "true" || value == "false",
        };

        if !type_valid {
            result.add_error(AnimationValidationError::new(
                AnimationValidationErrorType::InvalidParameterType,
                format!(
                    "Parameter '{}' expects type {:?} but got value '{}'",
                    param_name, param_type, value,
                ),
            ));
        }

        result
    }

    /// Validates a layer weight value.
    pub fn validate_weight(
        &self,
        layer_name: &str,
        weight: f32,
        controller: &AnimationControllerDefinition,
    ) -> AnimationValidationResult {
        let mut result = AnimationValidationResult::valid();

        if !controller.valid_layers.contains(layer_name) {
            result.add_error(AnimationValidationError::new(
                AnimationValidationErrorType::InvalidLayer,
                format!("Layer '{}' not found", layer_name),
            ));
        }

        if weight < 0.0 || weight > 1.0 {
            result.add_error(AnimationValidationError::new(
                AnimationValidationErrorType::InvalidWeight,
                format!(
                    "Weight {} for layer '{}' is out of range [0.0, 1.0]",
                    weight, layer_name,
                ),
            ));
        }

        result
    }

    /// Validates a complete COMP_ANIMATION_V2 layer state snapshot.
    ///
    /// Used during snapshot restore to verify animation state integrity.
    pub fn validate_snapshot(
        &self,
        layers: &BTreeMap<String, String>, // layer_name → current_state
        controller: &AnimationControllerDefinition,
    ) -> AnimationValidationResult {
        let mut result = AnimationValidationResult::valid();

        for (layer_name, state) in layers {
            if !controller.valid_layers.contains(layer_name.as_str()) {
                result.add_error(AnimationValidationError::new(
                    AnimationValidationErrorType::InvalidLayer,
                    format!("Snapshot contains unknown layer '{}'", layer_name),
                ));
            }
            if !controller.valid_states.contains(state.as_str()) {
                result.add_error(AnimationValidationError::new(
                    AnimationValidationErrorType::InvalidState,
                    format!(
                        "Snapshot layer '{}' has unknown state '{}'",
                        layer_name, state,
                    ),
                ));
            }
        }

        result
    }
}

impl Default for AnimationStateValidator {
    fn default() -> Self {
        Self::new()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn controller() -> AnimationControllerDefinition {
        AnimationControllerDefinition::permissive(
            "ctrl_player",
            vec!["Idle", "Run", "Jump", "Attack"],
            vec!["Base", "Upper"],
        )
        .with_parameter("speed", ParameterType::Float)
        .with_parameter("is_grounded", ParameterType::Bool)
        .with_parameter("attack", ParameterType::Trigger)
    }

    fn strict_controller() -> AnimationControllerDefinition {
        let mut ctrl = AnimationControllerDefinition::permissive(
            "ctrl_strict",
            vec!["Idle", "Run", "Jump"],
            vec!["Base"],
        );
        ctrl.strict_transitions = true;
        ctrl = ctrl.with_transition("Idle", "Run");
        ctrl = ctrl.with_transition("Run", "Jump");
        ctrl
    }

    #[test]
    fn valid_transition_passes() {
        let v = AnimationStateValidator::new();
        let result = v.validate_transition("Base", "Idle", "Run", &controller());
        assert!(result.is_valid());
    }

    #[test]
    fn invalid_target_state_fails() {
        let v = AnimationStateValidator::new();
        let result = v.validate_transition("Base", "Idle", "NonExistentState", &controller());
        assert!(!result.is_valid());
        assert!(result.errors[0].error_type == AnimationValidationErrorType::InvalidState);
    }

    #[test]
    fn invalid_layer_fails() {
        let v = AnimationStateValidator::new();
        let result = v.validate_transition("NonExistentLayer", "Idle", "Run", &controller());
        assert!(!result.is_valid());
    }

    #[test]
    fn strict_mode_blocks_unallowed_transition() {
        let v = AnimationStateValidator::new();
        let ctrl = strict_controller();
        // Idle → Jump not in allowed transitions
        let result = v.validate_transition("Base", "Idle", "Jump", &ctrl);
        assert!(!result.is_valid());
        assert_eq!(
            result.errors[0].error_type,
            AnimationValidationErrorType::TransitionNotAllowed
        );
    }

    #[test]
    fn strict_mode_allows_valid_transition() {
        let v = AnimationStateValidator::new();
        let ctrl = strict_controller();
        let result = v.validate_transition("Base", "Idle", "Run", &ctrl);
        assert!(result.is_valid());
    }

    #[test]
    fn valid_float_parameter() {
        let v = AnimationStateValidator::new();
        let result = v.validate_parameter("speed", "5.5", &controller());
        assert!(result.is_valid());
    }

    #[test]
    fn invalid_float_parameter() {
        let v = AnimationStateValidator::new();
        let result = v.validate_parameter("speed", "fast", &controller());
        assert!(!result.is_valid());
    }

    #[test]
    fn valid_bool_parameter() {
        let v = AnimationStateValidator::new();
        let result = v.validate_parameter("is_grounded", "true", &controller());
        assert!(result.is_valid());
        let result2 = v.validate_parameter("is_grounded", "false", &controller());
        assert!(result2.is_valid());
    }

    #[test]
    fn invalid_bool_parameter() {
        let v = AnimationStateValidator::new();
        let result = v.validate_parameter("is_grounded", "yes", &controller());
        assert!(!result.is_valid());
    }

    #[test]
    fn undeclared_parameter_fails() {
        let v = AnimationStateValidator::new();
        let result = v.validate_parameter("unknown_param", "1.0", &controller());
        assert!(!result.is_valid());
        assert_eq!(
            result.errors[0].error_type,
            AnimationValidationErrorType::InvalidParameter
        );
    }

    #[test]
    fn weight_in_range_valid() {
        let v = AnimationStateValidator::new();
        assert!(v.validate_weight("Base", 0.0, &controller()).is_valid());
        assert!(v.validate_weight("Base", 0.5, &controller()).is_valid());
        assert!(v.validate_weight("Base", 1.0, &controller()).is_valid());
    }

    #[test]
    fn weight_out_of_range_fails() {
        let v = AnimationStateValidator::new();
        assert!(!v.validate_weight("Base", 1.5, &controller()).is_valid());
        assert!(!v.validate_weight("Base", -0.1, &controller()).is_valid());
    }

    #[test]
    fn valid_snapshot_passes() {
        let v = AnimationStateValidator::new();
        let mut snapshot = BTreeMap::new();
        snapshot.insert("Base".into(), "Idle".into());
        snapshot.insert("Upper".into(), "Attack".into());
        let result = v.validate_snapshot(&snapshot, &controller());
        assert!(result.is_valid());
    }

    #[test]
    fn invalid_snapshot_state_fails() {
        let v = AnimationStateValidator::new();
        let mut snapshot = BTreeMap::new();
        snapshot.insert("Base".into(), "UnknownState".into());
        let result = v.validate_snapshot(&snapshot, &controller());
        assert!(!result.is_valid());
    }
}
