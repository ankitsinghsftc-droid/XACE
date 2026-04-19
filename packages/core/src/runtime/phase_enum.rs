//! # Phase Enum
//!
//! Defines the fixed, immutable execution phases of the XACE runtime.
//! Phase order is a global invariant — it never changes, never reorders,
//! and is never extended at runtime.
//!
//! ## The Five Phases (Fixed Forever)
//! Initialization → Input → Simulation → PostSimulation → Cleanup
//!
//! Every system is assigned to exactly one phase. The PhaseOrchestrator
//! runs all systems in each phase before advancing to the next.
//! Systems in the same phase may run in parallel if the SGC determines
//! their read/write sets are conflict-free.
//!
//! ## Relationship to ExecutionPhase in system_definition.rs
//! ExecutionPhase (schema layer) and PhaseEnum (runtime layer) define
//! the same five phases. They are kept as separate types because:
//! - ExecutionPhase lives in the schema/CGS layer (Python-facing)
//! - PhaseEnum lives in the runtime layer (Rust-facing)
//! - They must match — validated by the SGC during compilation
//!
//! ## Determinism (D1)
//! System execution order is determined ONLY by the ExecutionPlan.
//! The PhaseOrchestrator never reorders systems within a phase.
//! Phase order itself is immutable — hardcoded, not configurable.

use serde::{Deserialize, Serialize};

// ── Phase Enum ────────────────────────────────────────────────────────────────

/// The fixed execution phases of the XACE runtime tick loop.
///
/// Phases run in strict ascending order every tick.
/// The PhaseOrchestrator enforces this order — no phase may be
/// skipped, reordered, or run twice in a single tick.
///
/// ## Per-Tick Sequence
/// For each tick the PhaseOrchestrator:
/// 1. Drains EngineFeedbackBuffer (before any phase — Audit 6)
/// 2. Runs Initialization phase systems
/// 3. Applies Mutation Gate deferred queue
/// 4. Dispatches EventBus deferred events
/// 5. Runs Input phase systems
/// 6. Applies Mutation Gate deferred queue
/// 7. Dispatches EventBus deferred events
/// 8. ... repeats for Simulation, PostSimulation, Cleanup
/// 9. Computes world_hash (DeterminismGuard — D9)
/// 10. Advances tick counter
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
pub enum PhaseEnum {
    /// World setup, entity spawning, initial state configuration.
    ///
    /// Runs at world load and whenever new entities are spawned.
    /// SpawnSystem and InitializationSystem run here.
    /// Most frames this phase has no active systems — skipped efficiently.
    Initialization = 0,

    /// Input collection and routing.
    ///
    /// Human input from engine adapter arrives here (D12, I14).
    /// AI input decisions computed here.
    /// Network input (Phase 15) synchronized here before tick advances.
    /// No gameplay mutation allowed in this phase — input only.
    Input = 1,

    /// Core game logic.
    ///
    /// The main gameplay phase. Movement, AI, combat, physics,
    /// abilities, game state evaluation — all run here.
    /// Most systems are declared in this phase.
    /// Parallel execution groups are most effective here.
    Simulation = 2,

    /// Post-simulation processing.
    ///
    /// Camera follow, animation state updates, UI data binding.
    /// Reads final Simulation state. Write access is restricted
    /// to cosmetic and presentation data only.
    /// Engine feedback for animation and audio processed here.
    PostSimulation = 3,

    /// Cleanup and housekeeping.
    ///
    /// Consumed event removal, DestroyRequested → Destroyed transitions,
    /// lifetime counter advancement, temporary state clearing.
    /// Last phase before world_hash is computed (D9).
    Cleanup = 4,
}

impl PhaseEnum {
    /// Returns all phases in execution order.
    /// Used by the PhaseOrchestrator to iterate phases each tick.
    pub const ALL: [PhaseEnum; 5] = [
        PhaseEnum::Initialization,
        PhaseEnum::Input,
        PhaseEnum::Simulation,
        PhaseEnum::PostSimulation,
        PhaseEnum::Cleanup,
    ];

    /// Returns the u8 discriminant for wire serialization and
    /// cross-language communication with Python/TypeScript layers.
    pub fn as_u8(&self) -> u8 {
        *self as u8
    }

    /// Constructs a PhaseEnum from its u8 discriminant.
    /// Returns None if the value is not a valid phase.
    pub fn from_u8(value: u8) -> Option<Self> {
        match value {
            0 => Some(PhaseEnum::Initialization),
            1 => Some(PhaseEnum::Input),
            2 => Some(PhaseEnum::Simulation),
            3 => Some(PhaseEnum::PostSimulation),
            4 => Some(PhaseEnum::Cleanup),
            _ => None,
        }
    }

    /// Returns the next phase in execution order.
    /// Returns None for Cleanup — it is the last phase.
    pub fn next(&self) -> Option<PhaseEnum> {
        match self {
            PhaseEnum::Initialization => Some(PhaseEnum::Input),
            PhaseEnum::Input => Some(PhaseEnum::Simulation),
            PhaseEnum::Simulation => Some(PhaseEnum::PostSimulation),
            PhaseEnum::PostSimulation => Some(PhaseEnum::Cleanup),
            PhaseEnum::Cleanup => None,
        }
    }

    /// Returns the previous phase in execution order.
    /// Returns None for Initialization — it is the first phase.
    pub fn previous(&self) -> Option<PhaseEnum> {
        match self {
            PhaseEnum::Initialization => None,
            PhaseEnum::Input => Some(PhaseEnum::Initialization),
            PhaseEnum::Simulation => Some(PhaseEnum::Input),
            PhaseEnum::PostSimulation => Some(PhaseEnum::Simulation),
            PhaseEnum::Cleanup => Some(PhaseEnum::PostSimulation),
        }
    }

    /// Returns true if this phase allows gameplay mutations.
    /// PostSimulation and Cleanup have restricted write access.
    pub fn allows_gameplay_writes(&self) -> bool {
        matches!(
            self,
            PhaseEnum::Initialization
                | PhaseEnum::Input
                | PhaseEnum::Simulation
        )
    }

    /// Returns true if this is the last phase in a tick.
    pub fn is_last(&self) -> bool {
        matches!(self, PhaseEnum::Cleanup)
    }

    /// Returns true if this is the first phase in a tick.
    pub fn is_first(&self) -> bool {
        matches!(self, PhaseEnum::Initialization)
    }

    /// Returns the canonical string name of this phase.
    /// Used in ExecutionPlan serialization and SGC output.
    pub fn name(&self) -> &'static str {
        match self {
            PhaseEnum::Initialization => "Initialization",
            PhaseEnum::Input => "Input",
            PhaseEnum::Simulation => "Simulation",
            PhaseEnum::PostSimulation => "PostSimulation",
            PhaseEnum::Cleanup => "Cleanup",
        }
    }
}

impl std::fmt::Display for PhaseEnum {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.name())
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn all_phases_count() {
        assert_eq!(PhaseEnum::ALL.len(), 5);
    }

    #[test]
    fn phases_in_correct_order() {
        let phases = PhaseEnum::ALL;
        for window in phases.windows(2) {
            assert!(window[0] < window[1]);
        }
    }

    #[test]
    fn first_phase_is_initialization() {
        assert_eq!(PhaseEnum::ALL[0], PhaseEnum::Initialization);
        assert!(PhaseEnum::Initialization.is_first());
    }

    #[test]
    fn last_phase_is_cleanup() {
        assert_eq!(PhaseEnum::ALL[4], PhaseEnum::Cleanup);
        assert!(PhaseEnum::Cleanup.is_last());
    }

    #[test]
    fn next_phase_progression() {
        assert_eq!(
            PhaseEnum::Initialization.next(),
            Some(PhaseEnum::Input)
        );
        assert_eq!(
            PhaseEnum::Input.next(),
            Some(PhaseEnum::Simulation)
        );
        assert_eq!(
            PhaseEnum::Simulation.next(),
            Some(PhaseEnum::PostSimulation)
        );
        assert_eq!(
            PhaseEnum::PostSimulation.next(),
            Some(PhaseEnum::Cleanup)
        );
        assert_eq!(PhaseEnum::Cleanup.next(), None);
    }

    #[test]
    fn previous_phase_progression() {
        assert_eq!(PhaseEnum::Initialization.previous(), None);
        assert_eq!(
            PhaseEnum::Input.previous(),
            Some(PhaseEnum::Initialization)
        );
        assert_eq!(
            PhaseEnum::Cleanup.previous(),
            Some(PhaseEnum::PostSimulation)
        );
    }

    #[test]
    fn roundtrip_u8_conversion() {
        for phase in PhaseEnum::ALL {
            let byte = phase.as_u8();
            let restored = PhaseEnum::from_u8(byte).unwrap();
            assert_eq!(phase, restored);
        }
    }

    #[test]
    fn invalid_u8_returns_none() {
        assert!(PhaseEnum::from_u8(5).is_none());
        assert!(PhaseEnum::from_u8(255).is_none());
    }

    #[test]
    fn allows_gameplay_writes_correct() {
        assert!(PhaseEnum::Initialization.allows_gameplay_writes());
        assert!(PhaseEnum::Input.allows_gameplay_writes());
        assert!(PhaseEnum::Simulation.allows_gameplay_writes());
        assert!(!PhaseEnum::PostSimulation.allows_gameplay_writes());
        assert!(!PhaseEnum::Cleanup.allows_gameplay_writes());
    }

    #[test]
    fn display_names_correct() {
        assert_eq!(PhaseEnum::Simulation.to_string(), "Simulation");
        assert_eq!(PhaseEnum::PostSimulation.to_string(), "PostSimulation");
        assert_eq!(PhaseEnum::Cleanup.to_string(), "Cleanup");
    }

    #[test]
    fn names_match_display() {
        for phase in PhaseEnum::ALL {
            assert_eq!(phase.name(), phase.to_string());
        }
    }

    #[test]
    fn only_cleanup_is_last() {
        assert!(!PhaseEnum::Initialization.is_last());
        assert!(!PhaseEnum::Simulation.is_last());
        assert!(PhaseEnum::Cleanup.is_last());
    }

    #[test]
    fn only_initialization_is_first() {
        assert!(PhaseEnum::Initialization.is_first());
        assert!(!PhaseEnum::Input.is_first());
        assert!(!PhaseEnum::Cleanup.is_first());
    }
}