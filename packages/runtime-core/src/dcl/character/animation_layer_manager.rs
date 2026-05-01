//! # Animation Layer Manager
//!
//! Manages multi-layer animation state for COMP_ANIMATION_V2.
//!
//! ## Audit 3 — Multi-Layer Animation
//! COMP_ANIMATION_V2 has a `layers` dict — each layer has:
//! - current_state: active animation state name
//! - weight: blend weight (0.0-1.0)
//! - mask: body part mask string
//! - additive: whether this layer is additive
//!
//! The engine reads layer state from COMP_ANIMATION_V2 and applies
//! the blending. XACE manages the state machine transitions.
//!
//! ## Determinism
//! Layer state is stored in BTreeMap<String, LayerState> — alphabetical
//! layer name ordering for deterministic serialization (D11).

use std::collections::BTreeMap;

// ── Layer State ───────────────────────────────────────────────────────────────

/// The state of one animation layer.
///
/// Mirrors the structure of COMP_ANIMATION_V2.layers dict entries.
#[derive(Debug, Clone, PartialEq)]
pub struct LayerState {
    /// Current animation state name in this layer.
    pub current_state: String,

    /// Blend weight for this layer (0.0-1.0).
    /// 0.0 = invisible, 1.0 = full influence.
    pub weight: f32,

    /// Body part mask — which bones this layer affects.
    /// Empty string = full body.
    pub mask: String,

    /// Whether this layer blends additively on top of lower layers.
    pub additive: bool,

    /// Whether a transition is currently in progress.
    pub is_transitioning: bool,

    /// Duration of current transition in normalized time (0.0-1.0).
    pub transition_duration: f32,

    /// Current progress of transition (0.0-1.0).
    pub transition_progress: f32,

    /// Target state for pending transition.
    pub transition_target: Option<String>,
}

impl LayerState {
    /// Creates a new layer state in the given initial animation state.
    pub fn new(initial_state: impl Into<String>) -> Self {
        Self {
            current_state: initial_state.into(),
            weight: 1.0,
            mask: String::new(),
            additive: false,
            is_transitioning: false,
            transition_duration: 0.2,
            transition_progress: 0.0,
            transition_target: None,
        }
    }

    pub fn with_weight(mut self, weight: f32) -> Self {
        self.weight = weight.clamp(0.0, 1.0);
        self
    }

    pub fn with_mask(mut self, mask: impl Into<String>) -> Self {
        self.mask = mask.into();
        self
    }

    pub fn with_additive(mut self, additive: bool) -> Self {
        self.additive = additive;
        self
    }

    /// Returns true if this layer is currently in a transition.
    pub fn is_transitioning(&self) -> bool {
        self.is_transitioning
    }

    /// Returns true if this layer has completed its transition.
    pub fn transition_complete(&self) -> bool {
        self.is_transitioning && self.transition_progress >= 1.0
    }
}

// ── Transition Request ────────────────────────────────────────────────────────

/// A request to transition a layer to a new animation state.
#[derive(Debug, Clone)]
pub struct TransitionRequest {
    pub layer_name: String,
    pub target_state: String,
    pub duration_normalized: f32,
    pub force: bool, // If true, interrupts current transition
}

impl TransitionRequest {
    pub fn immediate(layer_name: impl Into<String>, target_state: impl Into<String>) -> Self {
        Self {
            layer_name: layer_name.into(),
            target_state: target_state.into(),
            duration_normalized: 0.0,
            force: true,
        }
    }

    pub fn blended(
        layer_name: impl Into<String>,
        target_state: impl Into<String>,
        duration: f32,
    ) -> Self {
        Self {
            layer_name: layer_name.into(),
            target_state: target_state.into(),
            duration_normalized: duration.clamp(0.0, 1.0),
            force: false,
        }
    }
}

// ── Animation Layer Manager ───────────────────────────────────────────────────

/// Manages multi-layer animation state machine.
///
/// Each entity with COMP_ANIMATION_V2 has one AnimationLayerManager
/// that tracks the state of all its animation layers.
///
/// Layer states are stored in BTreeMap for deterministic serialization (D11).
pub struct AnimationLayerManager {
    /// layer_name → LayerState. BTreeMap = alphabetical order (D11).
    layers: BTreeMap<String, LayerState>,
}

impl AnimationLayerManager {
    /// Creates a new manager with no layers.
    pub fn new() -> Self {
        Self {
            layers: BTreeMap::new(),
        }
    }

    /// Adds a new animation layer.
    ///
    /// Returns error message if a layer with this name already exists.
    pub fn add_layer(
        &mut self,
        layer_name: impl Into<String>,
        initial_state: impl Into<String>,
    ) -> Result<(), String> {
        let name = layer_name.into();
        if self.layers.contains_key(&name) {
            return Err(format!(
                "Layer '{}' already exists — cannot add duplicate layer",
                name
            ));
        }
        self.layers.insert(name, LayerState::new(initial_state));
        Ok(())
    }

    /// Returns the state of the given layer, if it exists.
    pub fn get_layer(&self, layer_name: &str) -> Option<&LayerState> {
        self.layers.get(layer_name)
    }

    /// Returns a mutable reference to a layer state.
    pub fn get_layer_mut(&mut self, layer_name: &str) -> Option<&mut LayerState> {
        self.layers.get_mut(layer_name)
    }

    /// Returns true if the given layer exists.
    pub fn has_layer(&self, layer_name: &str) -> bool {
        self.layers.contains_key(layer_name)
    }

    /// Returns the current animation state for the given layer.
    pub fn current_state(&self, layer_name: &str) -> Option<&str> {
        self.layers.get(layer_name).map(|l| l.current_state.as_str())
    }

    /// Returns all layer names in alphabetical order (D11).
    pub fn layer_names(&self) -> Vec<&str> {
        self.layers.keys().map(|s| s.as_str()).collect()
    }

    /// Returns the number of layers.
    pub fn layer_count(&self) -> usize {
        self.layers.len()
    }

    // ── Transition Management ──────────────────────────────────────────────

    /// Requests a state transition for the given layer.
    ///
    /// Immediate transitions (duration=0) switch state instantly.
    /// Blended transitions set is_transitioning=true and begin
    /// progress tracking.
    pub fn request_transition(
        &mut self,
        request: TransitionRequest,
    ) -> Result<(), String> {
        let layer = self.layers.get_mut(&request.layer_name).ok_or_else(|| {
            format!("Layer '{}' not found", request.layer_name)
        })?;

        // Don't interrupt active transition unless forced
        if layer.is_transitioning && !request.force {
            return Ok(()); // Silently ignore non-forced transition request
        }

        if request.duration_normalized <= 0.0 {
            // Immediate transition — snap to new state
            layer.current_state = request.target_state;
            layer.is_transitioning = false;
            layer.transition_progress = 0.0;
            layer.transition_target = None;
        } else {
            // Blended transition — begin progress tracking
            layer.is_transitioning = true;
            layer.transition_duration = request.duration_normalized;
            layer.transition_progress = 0.0;
            layer.transition_target = Some(request.target_state);
        }

        Ok(())
    }

    /// Advances transition progress for all layers.
    ///
    /// Called each tick with the normalized time delta.
    /// Completes transitions when progress reaches 1.0.
    ///
    /// Returns list of layer names that completed transitions this tick.
    pub fn tick_transitions(
        &mut self,
        delta_normalized: f32,
    ) -> Vec<String> {
        let mut completed = Vec::new();

        // BTreeMap iteration is alphabetical (D11)
        for (name, layer) in self.layers.iter_mut() {
            if !layer.is_transitioning {
                continue;
            }

            layer.transition_progress += delta_normalized;

            if layer.transition_progress >= 1.0 {
                // Complete the transition
                if let Some(target) = layer.transition_target.take() {
                    layer.current_state = target;
                }
                layer.is_transitioning = false;
                layer.transition_progress = 0.0;
                completed.push(name.clone());
            }
        }

        completed
    }

    // ── Weight Management ──────────────────────────────────────────────────

    /// Sets the blend weight for a layer.
    pub fn set_weight(
        &mut self,
        layer_name: &str,
        weight: f32,
    ) -> Result<(), String> {
        let layer = self.layers.get_mut(layer_name).ok_or_else(|| {
            format!("Layer '{}' not found", layer_name)
        })?;
        layer.weight = weight.clamp(0.0, 1.0);
        Ok(())
    }

    // ── Serialization Support ──────────────────────────────────────────────

    /// Serializes all layer states to JSON-compatible string.
    /// BTreeMap guarantees stable key ordering (D11).
    pub fn to_json(&self) -> String {
        let entries: Vec<String> = self.layers
            .iter()
            .map(|(name, state)| {
                format!(
                    r#""{}":{{"current_state":"{}","weight":{},"additive":{},"is_transitioning":{}}}"#,
                    name,
                    state.current_state,
                    state.weight,
                    state.additive,
                    state.is_transitioning,
                )
            })
            .collect();
        format!("{{{}}}", entries.join(","))
    }

    /// Returns all layer states as a BTreeMap for snapshot serialization (D11).
    pub fn all_states(&self) -> &BTreeMap<String, LayerState> {
        &self.layers
    }
}

impl Default for AnimationLayerManager {
    fn default() -> Self {
        Self::new()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn manager_with_layers() -> AnimationLayerManager {
        let mut m = AnimationLayerManager::new();
        m.add_layer("Base", "Idle").unwrap();
        m.add_layer("Upper", "Idle").unwrap();
        m
    }

    #[test]
    fn add_and_get_layer() {
        let m = manager_with_layers();
        assert!(m.has_layer("Base"));
        assert_eq!(m.current_state("Base"), Some("Idle"));
    }

    #[test]
    fn duplicate_layer_rejected() {
        let mut m = manager_with_layers();
        assert!(m.add_layer("Base", "Run").is_err());
    }

    #[test]
    fn layer_names_sorted_alphabetically() {
        let mut m = AnimationLayerManager::new();
        m.add_layer("Z_Layer", "Idle").unwrap();
        m.add_layer("A_Layer", "Idle").unwrap();
        m.add_layer("M_Layer", "Idle").unwrap();
        let names = m.layer_names();
        assert_eq!(names, vec!["A_Layer", "M_Layer", "Z_Layer"]);
    }

    #[test]
    fn immediate_transition_snaps_state() {
        let mut m = manager_with_layers();
        m.request_transition(
            TransitionRequest::immediate("Base", "Run")
        ).unwrap();
        assert_eq!(m.current_state("Base"), Some("Run"));
        assert!(!m.get_layer("Base").unwrap().is_transitioning());
    }

    #[test]
    fn blended_transition_sets_transitioning() {
        let mut m = manager_with_layers();
        m.request_transition(
            TransitionRequest::blended("Base", "Run", 0.3)
        ).unwrap();
        let layer = m.get_layer("Base").unwrap();
        assert!(layer.is_transitioning());
        assert_eq!(layer.transition_target, Some("Run".into()));
        // State not yet changed
        assert_eq!(layer.current_state, "Idle");
    }

    #[test]
    fn tick_transitions_completes_when_progress_reaches_1() {
        let mut m = manager_with_layers();
        m.request_transition(
            TransitionRequest::blended("Base", "Run", 0.5)
        ).unwrap();
        let completed = m.tick_transitions(1.0); // Advance past 1.0
        assert_eq!(completed, vec!["Base"]);
        assert_eq!(m.current_state("Base"), Some("Run"));
        assert!(!m.get_layer("Base").unwrap().is_transitioning());
    }

    #[test]
    fn tick_transitions_partial_progress() {
        let mut m = manager_with_layers();
        m.request_transition(
            TransitionRequest::blended("Base", "Run", 0.5)
        ).unwrap();
        let completed = m.tick_transitions(0.3); // Partial progress
        assert!(completed.is_empty());
        assert!(m.get_layer("Base").unwrap().is_transitioning());
        assert_eq!(m.current_state("Base"), Some("Idle")); // Not yet changed
    }

    #[test]
    fn non_forced_transition_blocked_during_active_transition() {
        let mut m = manager_with_layers();
        m.request_transition(
            TransitionRequest::blended("Base", "Run", 0.5)
        ).unwrap();
        // Non-forced transition while transitioning — should be ignored
        m.request_transition(TransitionRequest::blended("Base", "Jump", 0.3)).unwrap();
        assert_eq!(m.get_layer("Base").unwrap().transition_target, Some("Run".into()));
    }

    #[test]
    fn forced_transition_interrupts_active_transition() {
        let mut m = manager_with_layers();
        m.request_transition(
            TransitionRequest::blended("Base", "Run", 0.5)
        ).unwrap();
        // Forced transition interrupts
        m.request_transition(
            TransitionRequest::immediate("Base", "Jump")
        ).unwrap();
        assert_eq!(m.current_state("Base"), Some("Jump"));
        assert!(!m.get_layer("Base").unwrap().is_transitioning());
    }

    #[test]
    fn set_weight_clamps_to_range() {
        let mut m = manager_with_layers();
        m.set_weight("Base", 1.5).unwrap(); // Over 1.0
        assert_eq!(m.get_layer("Base").unwrap().weight, 1.0);
        m.set_weight("Base", -0.5).unwrap(); // Under 0.0
        assert_eq!(m.get_layer("Base").unwrap().weight, 0.0);
    }

    #[test]
    fn to_json_stable_output() {
        let m = manager_with_layers();
        let j1 = m.to_json();
        let j2 = m.to_json();
        assert_eq!(j1, j2);
        assert!(j1.contains("Base"));
        assert!(j1.contains("Upper"));
    }

    #[test]
    fn transition_on_nonexistent_layer_fails() {
        let mut m = manager_with_layers();
        assert!(m.request_transition(
            TransitionRequest::immediate("NonExistent", "Run")
        ).is_err());
    }
}