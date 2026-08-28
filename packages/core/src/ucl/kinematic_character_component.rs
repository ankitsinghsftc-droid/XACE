//! # COMP_KINEMATIC_CHARACTER_V1
//!
//! Deterministic configuration and state for reusable kinematic character
//! motion. The component deliberately contains no engine collision objects:
//! adapters may feed grounded state back, while XACE owns jump buffering,
//! coyote time, gravity, and jump-count transitions.

use crate::fixed_point::Fixed64;
use serde::{Deserialize, Serialize};

/// Frozen character-domain component type ID.
pub const COMP_KINEMATIC_CHARACTER_V1_ID: u32 = 125;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct KinematicCharacterComponent {
    pub grounded: bool,
    pub was_grounded: bool,
    pub max_horizontal_speed: Fixed64,
    pub jump_impulse: Fixed64,
    pub gravity_per_tick: Fixed64,
    pub terminal_fall_speed: Fixed64,
    pub coyote_ticks: u32,
    pub coyote_ticks_remaining: u32,
    pub jump_buffer_ticks: u32,
    pub jump_buffer_ticks_remaining: u32,
    pub max_jumps: u32,
    pub jumps_used: u32,
}

impl KinematicCharacterComponent {
    /// A conservative, engine-neutral 60 Hz platformer baseline.
    pub const fn platformer_defaults() -> Self {
        Self {
            grounded: true,
            was_grounded: true,
            max_horizontal_speed: Fixed64::from_units(6),
            jump_impulse: Fixed64::from_units(12),
            gravity_per_tick: Fixed64::from_millis(500),
            terminal_fall_speed: Fixed64::from_units(30),
            coyote_ticks: 6,
            coyote_ticks_remaining: 6,
            jump_buffer_ticks: 6,
            jump_buffer_ticks_remaining: 0,
            max_jumps: 1,
            jumps_used: 0,
        }
    }
}

impl Default for KinematicCharacterComponent {
    fn default() -> Self {
        Self::platformer_defaults()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn platformer_defaults_have_bounded_jump_and_fall_state() {
        let state = KinematicCharacterComponent::platformer_defaults();
        assert!(state.grounded);
        assert_eq!(state.max_jumps, 1);
        assert!(state.jump_impulse > Fixed64::ZERO);
        assert!(state.gravity_per_tick > Fixed64::ZERO);
        assert!(state.terminal_fall_speed > state.jump_impulse);
    }

    #[test]
    fn platformer_defaults_serialize_without_floats() {
        let encoded =
            serde_json::to_value(KinematicCharacterComponent::platformer_defaults()).unwrap();
        assert_eq!(encoded["max_horizontal_speed"], 6_000_000);
        assert_eq!(encoded["gravity_per_tick"], 500_000);
    }
}
