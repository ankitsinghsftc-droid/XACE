//! # COMP_LIFETIME_V1
//!
//! The automatic expiry component. Tracks how long an entity has existed
//! and destroys it automatically when its maximum lifetime is reached.
//!
//! ## Why this is UCL Core
//! Temporary entities exist in every genre — projectiles, spell effects,
//! particle emitters, floating damage numbers, timed power-ups, spawned
//! obstacles. Without a universal lifetime mechanism, every game would
//! need to implement its own cleanup system. This component makes the
//! LifetimeSystem a single generic system that works for all genres.
//!
//! ## How it Works
//! The LifetimeSystem runs each tick, increments `current_lifetime_ticks`
//! on every entity with this component, and submits a DestroyRequested
//! mutation via the Mutation Gate when `current_lifetime_ticks` reaches
//! `max_lifetime_ticks`. The entity then flows through the normal
//! destruction pipeline (DestroyRequested → Destroyed → Archived).
//!
//! ## Determinism
//! Lifetime is tracked in ticks, never in seconds or frames (D7).
//! The same entity always expires at exactly the same tick regardless
//! of frame rate, machine speed, or rendering performance.

use serde::{Deserialize, Serialize};
use crate::entity_metadata::Tick;

/// Component type ID for COMP_LIFETIME_V1. Frozen forever.
pub const COMP_LIFETIME_V1_ID: u32 = 8;

// ── Expiry Action ─────────────────────────────────────────────────────────────

/// What the LifetimeSystem should do when an entity's lifetime expires.
///
/// The default is Destroy — the entity is removed from the world.
/// Other actions allow for recycling, disabling, or triggering events
/// without full destruction.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum OnExpireAction {
    /// Submit a DestroyRequested mutation — entity is fully removed.
    /// This is the most common action for projectiles, effects, pickups.
    Destroy,

    /// Submit a Disabled state change — entity stays in world but
    /// stops participating in simulation. Can be re-activated later.
    /// Useful for object pooling where entities are recycled.
    Disable,

    /// Emit a Domain event ("lifetime.expired") and take no other action.
    /// The receiving system decides what to do. Useful when expiry
    /// should trigger complex logic (boss phase change, wave end, etc.)
    EmitEvent,

    /// Reset current_lifetime_ticks to zero and continue running.
    /// Entity loops indefinitely. Useful for repeating effects or
    /// cyclic game state entities.
    Loop,
}

impl Default for OnExpireAction {
    fn default() -> Self {
        OnExpireAction::Destroy
    }
}

impl std::fmt::Display for OnExpireAction {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            OnExpireAction::Destroy => write!(f, "Destroy"),
            OnExpireAction::Disable => write!(f, "Disable"),
            OnExpireAction::EmitEvent => write!(f, "EmitEvent"),
            OnExpireAction::Loop => write!(f, "Loop"),
        }
    }
}

// ── Component ─────────────────────────────────────────────────────────────────

/// COMP_LIFETIME_V1 — Automatic expiry timer for temporary entities.
///
/// UCL Core component. Attach to any entity that should automatically
/// expire after a fixed number of ticks. The LifetimeSystem processes
/// all entities with this component every tick.
///
/// ## Tick-Based Timing
/// To convert real time to ticks: ticks = seconds × simulation_rate.
/// At 60Hz simulation rate: 1 second = 60 ticks, 0.5 seconds = 30 ticks.
/// The simulation rate is defined in the CGS TimeController settings.
///
/// ## Pausing Lifetime
/// Set `is_paused = true` to freeze the lifetime counter without
/// removing the component. Useful for entities that should only
/// expire while in a specific state (active combat zone, etc.)
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LifetimeComponent {
    /// Maximum number of ticks this entity is allowed to live.
    /// When current_lifetime_ticks reaches this value, on_expire_action fires.
    /// Must be greater than zero — validated by Mutation Gate on creation.
    pub max_lifetime_ticks: Tick,

    /// How many ticks this entity has been alive.
    /// Incremented by the LifetimeSystem each tick this entity is Active.
    /// Reset to zero if on_expire_action is Loop.
    pub current_lifetime_ticks: Tick,

    /// What happens when current_lifetime_ticks reaches max_lifetime_ticks.
    pub on_expire_action: OnExpireAction,

    /// If true, the LifetimeSystem skips incrementing this entity's counter.
    /// Lifetime is effectively frozen until is_paused is set back to false.
    pub is_paused: bool,
}

impl LifetimeComponent {
    /// Creates a lifetime component that destroys the entity after N ticks.
    /// This is the most common usage — projectiles, effects, pickups.
    pub fn destroy_after(max_lifetime_ticks: Tick) -> Self {
        assert!(
            max_lifetime_ticks > 0,
            "max_lifetime_ticks must be greater than zero"
        );
        Self {
            max_lifetime_ticks,
            current_lifetime_ticks: 0,
            on_expire_action: OnExpireAction::Destroy,
            is_paused: false,
        }
    }

    /// Creates a lifetime component that disables the entity after N ticks.
    /// Useful for object pooling — entity is recycled rather than destroyed.
    pub fn disable_after(max_lifetime_ticks: Tick) -> Self {
        assert!(
            max_lifetime_ticks > 0,
            "max_lifetime_ticks must be greater than zero"
        );
        Self {
            max_lifetime_ticks,
            current_lifetime_ticks: 0,
            on_expire_action: OnExpireAction::Disable,
            is_paused: false,
        }
    }

    /// Creates a looping lifetime component.
    /// Entity resets its counter when it expires — runs indefinitely.
    pub fn looping(cycle_ticks: Tick) -> Self {
        assert!(
            cycle_ticks > 0,
            "cycle_ticks must be greater than zero"
        );
        Self {
            max_lifetime_ticks: cycle_ticks,
            current_lifetime_ticks: 0,
            on_expire_action: OnExpireAction::Loop,
            is_paused: false,
        }
    }

    /// Creates a lifetime component that emits an event on expiry.
    /// Receiving system decides what action to take.
    pub fn emit_event_after(max_lifetime_ticks: Tick) -> Self {
        assert!(
            max_lifetime_ticks > 0,
            "max_lifetime_ticks must be greater than zero"
        );
        Self {
            max_lifetime_ticks,
            current_lifetime_ticks: 0,
            on_expire_action: OnExpireAction::EmitEvent,
            is_paused: false,
        }
    }

    /// Returns true if this entity has reached or exceeded its lifetime.
    pub fn is_expired(&self) -> bool {
        self.current_lifetime_ticks >= self.max_lifetime_ticks
    }

    /// Returns how many ticks remain before expiry.
    /// Returns zero if already expired.
    pub fn ticks_remaining(&self) -> Tick {
        self.max_lifetime_ticks
            .saturating_sub(self.current_lifetime_ticks)
    }

    /// Returns the fraction of lifetime consumed (0.0 = fresh, 1.0 = expired).
    /// Useful for fading effects, progress bars, visual feedback.
    pub fn lifetime_fraction(&self) -> f32 {
        if self.max_lifetime_ticks == 0 {
            return 1.0;
        }
        (self.current_lifetime_ticks as f32 / self.max_lifetime_ticks as f32)
            .clamp(0.0, 1.0)
    }

    /// Advances the lifetime counter by one tick.
    /// Called by the LifetimeSystem each tick if is_paused is false.
    /// Returns true if the entity has now expired.
    pub fn tick(&mut self) -> bool {
        if self.is_paused {
            return false;
        }
        self.current_lifetime_ticks = self.current_lifetime_ticks.saturating_add(1);
        self.is_expired()
    }

    /// Resets the lifetime counter to zero.
    /// Called by the LifetimeSystem when on_expire_action is Loop.
    pub fn reset(&mut self) {
        self.current_lifetime_ticks = 0;
    }

    /// Pauses lifetime progression.
    pub fn pause(&mut self) {
        self.is_paused = true;
    }

    /// Resumes lifetime progression.
    pub fn resume(&mut self) {
        self.is_paused = false;
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fresh_entity_not_expired() {
        let lt = LifetimeComponent::destroy_after(60);
        assert!(!lt.is_expired());
        assert_eq!(lt.ticks_remaining(), 60);
    }

    #[test]
    fn expires_after_max_ticks() {
        let mut lt = LifetimeComponent::destroy_after(3);
        lt.tick();
        lt.tick();
        lt.tick();
        assert!(lt.is_expired());
        assert_eq!(lt.ticks_remaining(), 0);
    }

    #[test]
    fn tick_returns_true_on_expiry() {
        let mut lt = LifetimeComponent::destroy_after(1);
        let expired = lt.tick();
        assert!(expired);
    }

    #[test]
    fn tick_returns_false_before_expiry() {
        let mut lt = LifetimeComponent::destroy_after(5);
        let expired = lt.tick();
        assert!(!expired);
    }

    #[test]
    fn paused_entity_does_not_progress() {
        let mut lt = LifetimeComponent::destroy_after(10);
        lt.pause();
        lt.tick();
        lt.tick();
        lt.tick();
        assert_eq!(lt.current_lifetime_ticks, 0);
        assert!(!lt.is_expired());
    }

    #[test]
    fn resume_allows_progression() {
        let mut lt = LifetimeComponent::destroy_after(2);
        lt.pause();
        lt.tick();
        lt.resume();
        lt.tick();
        assert_eq!(lt.current_lifetime_ticks, 1);
    }

    #[test]
    fn reset_clears_counter() {
        let mut lt = LifetimeComponent::looping(5);
        lt.tick();
        lt.tick();
        lt.reset();
        assert_eq!(lt.current_lifetime_ticks, 0);
    }

    #[test]
    fn lifetime_fraction_zero_when_fresh() {
        let lt = LifetimeComponent::destroy_after(100);
        assert_eq!(lt.lifetime_fraction(), 0.0);
    }

    #[test]
    fn lifetime_fraction_one_when_expired() {
        let mut lt = LifetimeComponent::destroy_after(1);
        lt.tick();
        assert_eq!(lt.lifetime_fraction(), 1.0);
    }

    #[test]
    fn lifetime_fraction_halfway() {
        let mut lt = LifetimeComponent::destroy_after(10);
        for _ in 0..5 { lt.tick(); }
        assert!((lt.lifetime_fraction() - 0.5).abs() < 1e-5);
    }

    #[test]
    #[should_panic]
    fn zero_max_lifetime_panics() {
        LifetimeComponent::destroy_after(0);
    }

    #[test]
    fn disable_after_has_correct_action() {
        let lt = LifetimeComponent::disable_after(30);
        assert_eq!(lt.on_expire_action, OnExpireAction::Disable);
    }

    #[test]
    fn looping_has_correct_action() {
        let lt = LifetimeComponent::looping(60);
        assert_eq!(lt.on_expire_action, OnExpireAction::Loop);
    }

    #[test]
    fn ticks_remaining_never_underflows() {
        let mut lt = LifetimeComponent::destroy_after(2);
        lt.tick(); lt.tick(); lt.tick(); lt.tick();
        assert_eq!(lt.ticks_remaining(), 0);
    }
}