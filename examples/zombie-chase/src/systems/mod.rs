//! System implementations for the zombie chase vertical slice.
//!
//! Execution order (from cgs::execution_order()):
//! 1. InputSystem    — player input → VELOCITY intent
//! 2. MovementSystem — VELOCITY → TRANSFORM integration
//! 3. AISystem       — zombie chase → VELOCITY + DAMAGE
//! 4. DamageSystem   — DAMAGE → HEALTH reduction
//! 5. DeathSystem    — HEALTH <= 0 → entity destroy

pub mod ai_system;
pub mod damage_system;
pub mod death_system;
pub mod input_system;
pub mod movement_system;
