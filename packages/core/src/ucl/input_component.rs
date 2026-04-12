//! # COMP_INPUT_V1
//!
//! The control source component. Defines who or what controls this entity —
//! a human player, an AI proxy, or a remote network peer. Every entity
//! that receives input or control signals needs this component.
//!
//! ## Why this is UCL Core
//! Every game has controlled entities. The distinction between human,
//! AI, and network control is fundamental to every genre — singleplayer,
//! multiplayer, and AI-driven games all need to know who is driving
//! each entity. This cannot be a DCL concern because the runtime
//! needs this information at the lowest level to route input correctly.
//!
//! ## Input Flow
//! Human input: Engine collects → packages as InputPacket with tick stamp
//! (I14) → sends to XACE runtime → InputSystem reads this component to
//! know which controller maps to which entity → applies to movement/action.
//!
//! AI input: AISystem writes directly to movement/action components via
//! Mutation Gate — this component signals that the entity accepts AI commands.
//!
//! Network input: InputSynchroniser holds tick boundary until all peer
//! inputs arrive → routes to correct entity via controller_id (Phase 15).
//!
//! ## Determinism
//! Input is applied at tick boundaries only — never mid-tick (D12, I14).
//! The control_type determines which input pipeline processes this entity.

use serde::{Deserialize, Serialize};

/// Component type ID for COMP_INPUT_V1. Frozen forever.
pub const COMP_INPUT_V1_ID: u32 = 6;

// ── Control Type ──────────────────────────────────────────────────────────────

/// Defines who or what provides control signals to this entity.
///
/// This is the routing key for the input pipeline. The PhaseOrchestrator
/// and InputSystem use this to determine how to process control for
/// each entity each tick.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum ControlType {
    /// Controlled by a local human player.
    /// Input comes from the engine's input collector (keyboard, gamepad,
    /// mouse, touch) packaged as an InputPacket each tick.
    /// `controller_id` maps to the physical device index.
    Human,

    /// Controlled by an AI system.
    /// The AISystem reads perception and state, then writes movement
    /// and action intents directly via Mutation Gate.
    /// `controller_id` identifies which AI behavior profile drives this entity.
    AiProxy,

    /// Controlled by a remote network peer.
    /// Input arrives via the InputSynchroniser from the network layer.
    /// `controller_id` maps to the peer_id in the network session.
    /// Used in Phase 15 multiplayer — during Phase 1-14 this type
    /// exists in the type system but is not yet processed.
    NetworkRemote,
}

impl Default for ControlType {
    fn default() -> Self {
        ControlType::Human
    }
}

impl std::fmt::Display for ControlType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ControlType::Human => write!(f, "HUMAN"),
            ControlType::AiProxy => write!(f, "AI_PROXY"),
            ControlType::NetworkRemote => write!(f, "NETWORK_REMOTE"),
        }
    }
}

// ── Input Profile ─────────────────────────────────────────────────────────────

/// Identifies the input mapping profile for this entity.
///
/// An input profile defines how raw device inputs (button presses,
/// analog stick values) map to game actions (move_forward, jump, attack).
/// Profiles are defined in the CGS and resolved by the engine adapter.
///
/// Examples: "default_fps", "vehicle_controls", "menu_navigation"
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct InputProfileId(pub String);

impl InputProfileId {
    /// The default input profile. Maps standard gamepad/keyboard controls.
    pub fn default_profile() -> Self {
        Self("default".into())
    }

    pub fn new(id: impl Into<String>) -> Self {
        Self(id.into())
    }
}

impl Default for InputProfileId {
    fn default() -> Self {
        Self::default_profile()
    }
}

impl std::fmt::Display for InputProfileId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

// ── Component ─────────────────────────────────────────────────────────────────

/// COMP_INPUT_V1 — Control source and routing for an entity.
///
/// UCL Core component. Every entity that receives control signals —
/// from a player, AI, or network peer — must have this component.
/// Entities without this component are not processed by the input pipeline.
///
/// ## Controller ID
/// The meaning of `controller_id` depends on `control_type`:
/// - Human: physical device index (0 = first gamepad/keyboard)
/// - AiProxy: AI behavior instance ID defined in the CGS
/// - NetworkRemote: peer_id from the network session (Phase 15)
///
/// ## Enabling / Disabling
/// `is_enabled` allows temporarily suspending input processing
/// without removing the component — useful for cutscenes, death
/// animations, or UI-focus states where the entity should not
/// respond to input but retains its control configuration.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct InputComponent {
    /// Which physical or logical controller drives this entity.
    /// Interpretation depends on control_type.
    pub controller_id: u32,

    /// The source of control signals for this entity.
    pub control_type: ControlType,

    /// Which input mapping profile to use for action resolution.
    pub input_profile_id: InputProfileId,

    /// Whether input processing is currently active for this entity.
    /// False = entity ignores all input this tick, regardless of control_type.
    pub is_enabled: bool,
}

impl InputComponent {
    /// Creates a human-controlled input component for the first local player.
    /// Uses the default input profile and starts enabled.
    pub fn human_player(controller_id: u32) -> Self {
        Self {
            controller_id,
            control_type: ControlType::Human,
            input_profile_id: InputProfileId::default_profile(),
            is_enabled: true,
        }
    }

    /// Creates an AI-controlled input component.
    /// `behavior_id` identifies which AI behavior profile drives this entity.
    pub fn ai_controlled(behavior_id: u32) -> Self {
        Self {
            controller_id: behavior_id,
            control_type: ControlType::AiProxy,
            input_profile_id: InputProfileId::default_profile(),
            is_enabled: true,
        }
    }

    /// Creates a network-remote-controlled input component.
    /// `peer_id` maps to the network session peer (Phase 15).
    pub fn network_remote(peer_id: u32) -> Self {
        Self {
            controller_id: peer_id,
            control_type: ControlType::NetworkRemote,
            input_profile_id: InputProfileId::default_profile(),
            is_enabled: true,
        }
    }

    /// Returns true if this entity is controlled by a local human player.
    pub fn is_human_controlled(&self) -> bool {
        matches!(self.control_type, ControlType::Human)
    }

    /// Returns true if this entity is controlled by the AI system.
    pub fn is_ai_controlled(&self) -> bool {
        matches!(self.control_type, ControlType::AiProxy)
    }

    /// Returns true if this entity is controlled by a remote peer.
    pub fn is_network_controlled(&self) -> bool {
        matches!(self.control_type, ControlType::NetworkRemote)
    }

    /// Disables input processing for this entity.
    /// Used during cutscenes, death sequences, UI focus.
    pub fn disable(&mut self) {
        self.is_enabled = false;
    }

    /// Re-enables input processing for this entity.
    pub fn enable(&mut self) {
        self.is_enabled = true;
    }
}

impl Default for InputComponent {
    fn default() -> Self {
        Self::human_player(0)
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn human_player_is_human_controlled() {
        let input = InputComponent::human_player(0);
        assert!(input.is_human_controlled());
        assert!(!input.is_ai_controlled());
        assert!(!input.is_network_controlled());
    }

    #[test]
    fn ai_controlled_is_ai() {
        let input = InputComponent::ai_controlled(1);
        assert!(input.is_ai_controlled());
        assert!(!input.is_human_controlled());
    }

    #[test]
    fn network_remote_is_network() {
        let input = InputComponent::network_remote(42);
        assert!(input.is_network_controlled());
        assert!(!input.is_human_controlled());
    }

    #[test]
    fn starts_enabled() {
        let input = InputComponent::human_player(0);
        assert!(input.is_enabled);
    }

    #[test]
    fn disable_and_enable() {
        let mut input = InputComponent::human_player(0);
        input.disable();
        assert!(!input.is_enabled);
        input.enable();
        assert!(input.is_enabled);
    }

    #[test]
    fn controller_id_stored_correctly() {
        let input = InputComponent::human_player(2);
        assert_eq!(input.controller_id, 2);
    }

    #[test]
    fn control_type_display() {
        assert_eq!(ControlType::Human.to_string(), "HUMAN");
        assert_eq!(ControlType::AiProxy.to_string(), "AI_PROXY");
        assert_eq!(ControlType::NetworkRemote.to_string(), "NETWORK_REMOTE");
    }

    #[test]
    fn input_profile_default() {
        let profile = InputProfileId::default_profile();
        assert_eq!(profile.0, "default");
    }

    #[test]
    fn custom_input_profile() {
        let profile = InputProfileId::new("vehicle_controls");
        assert_eq!(profile.to_string(), "vehicle_controls");
    }
}