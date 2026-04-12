//! # COMP_VELOCITY_V1
//!
//! The motion component. Stores current linear and angular velocity for
//! any entity that moves through the world. Consumed by movement systems
//! and the physics engine adapter each tick.
//!
//! ## Why this is UCL Core
//! Movement is universal. Every genre has entities that move — characters,
//! projectiles, vehicles, cameras, falling objects. Without velocity as a
//! core concept, movement systems cannot exist in a generic way.
//!
//! ## XACE vs Engine Responsibility
//! XACE stores and updates velocity values through systems and the
//! Mutation Gate. The engine adapter reads velocity and applies it
//! to the physics simulation. XACE never integrates velocity into
//! position directly — that is the engine's job (Layer 7).
//!
//! ## Determinism
//! All velocity values are f32. Speed limits are enforced by the
//! MovementSystem via the Mutation Gate, never by the engine.
//! This keeps clamping logic deterministic and engine-independent (D6).

use serde::{Deserialize, Serialize};

/// Component type ID for COMP_VELOCITY_V1. Frozen forever.
pub const COMP_VELOCITY_V1_ID: u32 = 5;

// ── Velocity Vector ───────────────────────────────────────────────────────────

/// A 3D velocity vector in units per second.
///
/// Used for both linear velocity (world-space movement) and
/// angular velocity (rotation rate in radians per second).
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct VelocityVec3 {
    pub x: f32,
    pub y: f32,
    pub z: f32,
}

impl VelocityVec3 {
    pub const ZERO: VelocityVec3 = VelocityVec3 { x: 0.0, y: 0.0, z: 0.0 };

    pub fn new(x: f32, y: f32, z: f32) -> Self {
        Self { x, y, z }
    }

    /// Returns the magnitude (length) of this velocity vector.
    /// Used to check against speed limits.
    pub fn magnitude(&self) -> f32 {
        (self.x * self.x + self.y * self.y + self.z * self.z).sqrt()
    }

    /// Returns true if this velocity is effectively zero.
    /// Uses a small epsilon to avoid floating point noise.
    pub fn is_zero(&self) -> bool {
        self.magnitude() < 1e-6
    }

    /// Returns a new vector scaled by the given factor.
    pub fn scaled(&self, factor: f32) -> Self {
        Self {
            x: self.x * factor,
            y: self.y * factor,
            z: self.z * factor,
        }
    }

    /// Clamps this velocity to a maximum magnitude.
    /// Returns the original vector if already within limit.
    pub fn clamped_to(&self, max_magnitude: f32) -> Self {
        let mag = self.magnitude();
        if mag <= max_magnitude || mag < 1e-6 {
            *self
        } else {
            let scale = max_magnitude / mag;
            self.scaled(scale)
        }
    }
}

impl Default for VelocityVec3 {
    fn default() -> Self {
        VelocityVec3::ZERO
    }
}

// ── Component ─────────────────────────────────────────────────────────────────

/// COMP_VELOCITY_V1 — Linear and angular velocity for a moving entity.
///
/// UCL Core component. Written by movement systems, AI systems, and
/// physics feedback handlers. Read by the engine adapter to drive
/// physics simulation.
///
/// ## Speed Limits
/// `max_linear_speed` and `max_angular_speed` define the caps for this
/// entity. A value of 0.0 means no limit. The MovementSystem enforces
/// these limits by clamping velocity before writing via Mutation Gate.
/// The engine adapter also receives these limits for reference but
/// XACE is the authority on clamping (D13).
///
/// ## Relationship to COMP_RIGIDBODY_V1 (DCL)
/// COMP_VELOCITY_V1 stores the current velocity state.
/// COMP_RIGIDBODY_V1 (in dcl/physics/) stores mass, drag, and
/// physics material properties that affect how velocity changes.
/// They are separate because not every moving entity needs full
/// rigidbody physics — a kinematic character has velocity but
/// no physics mass.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct VelocityComponent {
    /// Current linear velocity in world space (units per second).
    /// Written by MovementSystem, AISystem, physics feedback handler.
    pub linear: VelocityVec3,

    /// Current angular velocity in radians per second.
    /// x = pitch rate, y = yaw rate, z = roll rate.
    pub angular: VelocityVec3,

    /// Maximum allowed linear speed in units per second.
    /// 0.0 means no limit enforced by XACE (engine may still cap).
    /// MovementSystem clamps `linear` to this before committing.
    pub max_linear_speed: f32,

    /// Maximum allowed angular speed in radians per second.
    /// 0.0 means no limit enforced by XACE.
    pub max_angular_speed: f32,
}

impl VelocityComponent {
    /// Creates a stationary entity with no velocity and no speed limits.
    pub fn stationary() -> Self {
        Self {
            linear: VelocityVec3::ZERO,
            angular: VelocityVec3::ZERO,
            max_linear_speed: 0.0,
            max_angular_speed: 0.0,
        }
    }

    /// Creates a velocity component with defined speed limits.
    /// Entity starts stationary — velocity is applied by systems.
    pub fn with_limits(max_linear_speed: f32, max_angular_speed: f32) -> Self {
        Self {
            linear: VelocityVec3::ZERO,
            angular: VelocityVec3::ZERO,
            max_linear_speed,
            max_angular_speed,
        }
    }

    /// Returns true if this entity is currently moving (linear or angular).
    pub fn is_moving(&self) -> bool {
        !self.linear.is_zero() || !self.angular.is_zero()
    }

    /// Returns true if linear velocity exceeds the defined maximum.
    /// Returns false if max_linear_speed is 0.0 (no limit).
    pub fn is_over_linear_limit(&self) -> bool {
        if self.max_linear_speed <= 0.0 {
            return false;
        }
        self.linear.magnitude() > self.max_linear_speed
    }

    /// Returns true if angular velocity exceeds the defined maximum.
    /// Returns false if max_angular_speed is 0.0 (no limit).
    pub fn is_over_angular_limit(&self) -> bool {
        if self.max_angular_speed <= 0.0 {
            return false;
        }
        self.angular.magnitude() > self.max_angular_speed
    }

    /// Returns the linear velocity clamped to max_linear_speed.
    /// Returns current linear velocity unchanged if no limit is set.
    /// Used by MovementSystem before writing via Mutation Gate.
    pub fn clamped_linear(&self) -> VelocityVec3 {
        if self.max_linear_speed <= 0.0 {
            self.linear
        } else {
            self.linear.clamped_to(self.max_linear_speed)
        }
    }

    /// Returns the angular velocity clamped to max_angular_speed.
    pub fn clamped_angular(&self) -> VelocityVec3 {
        if self.max_angular_speed <= 0.0 {
            self.angular
        } else {
            self.angular.clamped_to(self.max_angular_speed)
        }
    }

    /// Stops all movement instantly.
    /// Called by systems on entity death, freeze effects, etc.
    pub fn stop(&mut self) {
        self.linear = VelocityVec3::ZERO;
        self.angular = VelocityVec3::ZERO;
    }
}

impl Default for VelocityComponent {
    fn default() -> Self {
        Self::stationary()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stationary_is_not_moving() {
        let v = VelocityComponent::stationary();
        assert!(!v.is_moving());
    }

    #[test]
    fn moving_entity_detected() {
        let mut v = VelocityComponent::stationary();
        v.linear = VelocityVec3::new(1.0, 0.0, 0.0);
        assert!(v.is_moving());
    }

    #[test]
    fn stop_clears_all_velocity() {
        let mut v = VelocityComponent::stationary();
        v.linear = VelocityVec3::new(5.0, 3.0, 1.0);
        v.angular = VelocityVec3::new(0.0, 1.0, 0.0);
        v.stop();
        assert!(!v.is_moving());
    }

    #[test]
    fn magnitude_calculated_correctly() {
        let v = VelocityVec3::new(3.0, 4.0, 0.0);
        assert!((v.magnitude() - 5.0).abs() < 1e-5);
    }

    #[test]
    fn zero_velocity_is_zero() {
        assert!(VelocityVec3::ZERO.is_zero());
    }

    #[test]
    fn clamped_to_respects_limit() {
        let v = VelocityVec3::new(3.0, 4.0, 0.0); // magnitude = 5.0
        let clamped = v.clamped_to(2.5);
        assert!((clamped.magnitude() - 2.5).abs() < 1e-5);
    }

    #[test]
    fn clamped_to_does_not_shrink_if_under_limit() {
        let v = VelocityVec3::new(1.0, 0.0, 0.0); // magnitude = 1.0
        let clamped = v.clamped_to(5.0);
        assert_eq!(clamped, v);
    }

    #[test]
    fn over_linear_limit_detected() {
        let mut v = VelocityComponent::with_limits(5.0, 0.0);
        v.linear = VelocityVec3::new(10.0, 0.0, 0.0);
        assert!(v.is_over_linear_limit());
    }

    #[test]
    fn no_limit_never_over() {
        let mut v = VelocityComponent::stationary();
        v.linear = VelocityVec3::new(9999.0, 0.0, 0.0);
        assert!(!v.is_over_linear_limit());
    }

    #[test]
    fn clamped_linear_respects_max() {
        let mut v = VelocityComponent::with_limits(5.0, 0.0);
        v.linear = VelocityVec3::new(10.0, 0.0, 0.0);
        let clamped = v.clamped_linear();
        assert!((clamped.magnitude() - 5.0).abs() < 1e-5);
    }

    #[test]
    fn scaled_velocity_correct() {
        let v = VelocityVec3::new(2.0, 4.0, 0.0);
        let scaled = v.scaled(0.5);
        assert_eq!(scaled.x, 1.0);
        assert_eq!(scaled.y, 2.0);
    }
}