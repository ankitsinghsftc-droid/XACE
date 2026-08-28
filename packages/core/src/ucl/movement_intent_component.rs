//! # COMP_MOVEMENT_INTENT_V1
//!
//! Engine-neutral movement intent produced from semantic input (or AI) and
//! consumed by deterministic movement systems. Numeric fields use Fixed64
//! micro-units so intent can be replayed without authoritative floating point.

use crate::fixed_point::Fixed64;
use serde::{Deserialize, Serialize};

/// Frozen component type ID for COMP_MOVEMENT_INTENT_V1.
pub const COMP_MOVEMENT_INTENT_V1_ID: u32 = 120;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MovementIntentComponent {
    /// Desired local/world movement direction on the horizontal X axis.
    pub direction_x: Fixed64,

    /// Optional vertical direction for flying/swimming movement primitives.
    pub direction_y: Fixed64,

    /// Desired local/world movement direction on the horizontal Z axis.
    pub direction_z: Fixed64,

    /// True while the sprint/dash modifier is held.
    pub sprint_requested: bool,

    /// One-tick rising-edge request consumed by jump-capable movement systems.
    pub jump_requested: bool,

    /// Current held state used to derive deterministic jump edges.
    pub jump_held: bool,

    /// True while the crouch modifier is held.
    pub crouch_requested: bool,
}

impl MovementIntentComponent {
    pub const fn neutral() -> Self {
        Self {
            direction_x: Fixed64::ZERO,
            direction_y: Fixed64::ZERO,
            direction_z: Fixed64::ZERO,
            sprint_requested: false,
            jump_requested: false,
            jump_held: false,
            crouch_requested: false,
        }
    }
}

impl Default for MovementIntentComponent {
    fn default() -> Self {
        Self::neutral()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn neutral_intent_is_deterministic_and_inactive() {
        let intent = MovementIntentComponent::neutral();
        assert_eq!(intent.direction_x, Fixed64::ZERO);
        assert_eq!(intent.direction_y, Fixed64::ZERO);
        assert_eq!(intent.direction_z, Fixed64::ZERO);
        assert!(!intent.jump_requested);
        assert!(!intent.jump_held);
    }

    #[test]
    fn fixed_intent_serializes_as_raw_micro_units() {
        let intent = MovementIntentComponent {
            direction_x: Fixed64::from_millis(500),
            ..MovementIntentComponent::neutral()
        };
        let encoded = serde_json::to_value(intent).unwrap();
        assert_eq!(encoded["direction_x"], 500_000);
    }
}
