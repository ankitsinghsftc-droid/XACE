//! # Entity State
//!
//! Defines the lifecycle state of every entity in the XACE runtime.
//! State transitions are strict and unidirectional — an entity cannot
//! go from Destroyed back to Active.
//!
//! ## Lifecycle
//! Created → Active → Disabled → DestroyRequested → Destroyed → Archived
//!
//! State changes are never direct — they always go through the Mutation Gate (I2).

use serde::{Deserialize, Serialize};

// ── Entity State ──────────────────────────────────────────────────────────────

/// The current lifecycle state of an entity.
///
/// States are ordered by progression — an entity moves forward through
/// this lifecycle and never backward. The Mutation Gate enforces all
/// valid transitions; invalid transitions produce a ValidationFailure.
///
/// Serializable so it can be included in WorldSnapshot (Phase 5).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum EntityState {
    /// Entity exists and participates fully in simulation.
    ///
    /// Systems can read and write its components. It is included in
    /// query results. This is the normal operating state.
    Active,

    /// Entity exists but is excluded from simulation.
    ///
    /// Systems do not process it. It does not appear in query results.
    /// Components are preserved. Can be re-activated via Mutation Gate.
    /// Useful for pooled objects, sleeping actors, inactive spawners.
    Disabled,

    /// Entity has been marked for destruction this tick.
    ///
    /// Set by a system requesting destruction via the Mutation Gate.
    /// The Mutation Gate processes actual destruction at the end of the
    /// current tick in the remove→destroy phase (D4). During this tick,
    /// the entity is still readable but no new writes are accepted.
    DestroyRequested,

    /// Entity has been fully removed from the EntityStore.
    ///
    /// Its EntityID is permanently archived (D2) — it will never be
    /// reused. Component data has been cleared. The entity cannot be
    /// queried or written to. This state is transient — the entity moves
    /// to Archived immediately after destruction processing completes.
    Destroyed,

    /// Entity is permanently retired from the world.
    ///
    /// Its EntityID remains in the archive forever to prevent reuse (D2).
    /// This state exists for replay integrity and network determinism —
    /// a replayed session must never generate an ID that was previously
    /// destroyed, as that would corrupt component table lookups.
    Archived,
}

impl EntityState {
    /// Returns true if this entity is alive and participating in simulation.
    ///
    /// Only Active entities appear in query engine results.
    pub fn is_alive(&self) -> bool {
        matches!(self, EntityState::Active)
    }

    /// Returns true if this entity still exists in the EntityStore in any form.
    ///
    /// Destroyed and Archived entities are no longer in the store.
    pub fn is_present(&self) -> bool {
        matches!(self, EntityState::Active | EntityState::Disabled | EntityState::DestroyRequested)
    }

    /// Returns true if this entity has been fully removed.
    ///
    /// Used by the archive system to determine which IDs to permanently reserve.
    pub fn is_removed(&self) -> bool {
        matches!(self, EntityState::Destroyed | EntityState::Archived)
    }

    /// Returns true if this state transition is valid.
    ///
    /// Enforces the strict unidirectional lifecycle. Called by the
    /// Mutation Gate's validator before applying any state change.
    ///
    /// Valid transitions:
    /// - Active        → Disabled, DestroyRequested
    /// - Disabled      → Active, DestroyRequested  
    /// - DestroyRequested → Destroyed
    /// - Destroyed     → Archived
    /// - Archived      → (none — terminal state)
    pub fn can_transition_to(&self, next: EntityState) -> bool {
        match (self, next) {
            (EntityState::Active, EntityState::Disabled) => true,
            (EntityState::Active, EntityState::DestroyRequested) => true,
            (EntityState::Disabled, EntityState::Active) => true,
            (EntityState::Disabled, EntityState::DestroyRequested) => true,
            (EntityState::DestroyRequested, EntityState::Destroyed) => true,
            (EntityState::Destroyed, EntityState::Archived) => true,
            _ => false,
        }
    }
}

impl std::fmt::Display for EntityState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            EntityState::Active => write!(f, "Active"),
            EntityState::Disabled => write!(f, "Disabled"),
            EntityState::DestroyRequested => write!(f, "DestroyRequested"),
            EntityState::Destroyed => write!(f, "Destroyed"),
            EntityState::Archived => write!(f, "Archived"),
        }
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn active_is_alive() {
        assert!(EntityState::Active.is_alive());
        assert!(!EntityState::Disabled.is_alive());
        assert!(!EntityState::Archived.is_alive());
    }

    #[test]
    fn present_states_are_correct() {
        assert!(EntityState::Active.is_present());
        assert!(EntityState::Disabled.is_present());
        assert!(EntityState::DestroyRequested.is_present());
        assert!(!EntityState::Destroyed.is_present());
        assert!(!EntityState::Archived.is_present());
    }

    #[test]
    fn removed_states_are_correct() {
        assert!(EntityState::Destroyed.is_removed());
        assert!(EntityState::Archived.is_removed());
        assert!(!EntityState::Active.is_removed());
    }

    #[test]
    fn valid_transitions_are_accepted() {
        assert!(EntityState::Active.can_transition_to(EntityState::Disabled));
        assert!(EntityState::Active.can_transition_to(EntityState::DestroyRequested));
        assert!(EntityState::Disabled.can_transition_to(EntityState::Active));
        assert!(EntityState::Disabled.can_transition_to(EntityState::DestroyRequested));
        assert!(EntityState::DestroyRequested.can_transition_to(EntityState::Destroyed));
        assert!(EntityState::Destroyed.can_transition_to(EntityState::Archived));
    }

    #[test]
    fn invalid_transitions_are_rejected() {
        assert!(!EntityState::Active.can_transition_to(EntityState::Archived));
        assert!(!EntityState::Archived.can_transition_to(EntityState::Active));
        assert!(!EntityState::Destroyed.can_transition_to(EntityState::Active));
        assert!(!EntityState::DestroyRequested.can_transition_to(EntityState::Active));
    }

    #[test]
    fn archived_is_terminal() {
        // Archived cannot transition to anything
        let states = [
            EntityState::Active,
            EntityState::Disabled,
            EntityState::DestroyRequested,
            EntityState::Destroyed,
            EntityState::Archived,
        ];
        for state in states {
            assert!(!EntityState::Archived.can_transition_to(state));
        }
    }

    #[test]
    fn display_is_human_readable() {
        assert_eq!(EntityState::Active.to_string(), "Active");
        assert_eq!(EntityState::Archived.to_string(), "Archived");
    }
}