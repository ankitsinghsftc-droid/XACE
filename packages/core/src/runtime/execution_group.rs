//! # Execution Group
//!
//! A group of systems that run together within a single phase.
//! Systems in a parallel group run concurrently. Systems in a
//! sequential group run one after another in declared order.
//!
//! ## What an Execution Group Is
//! The SGC partitions systems within each phase into execution groups.
//! A group is the unit of parallel/sequential scheduling in the runtime.
//!
//! Example ExecutionPlan for Simulation phase:
//! Group 1 (sequential): [InputSystem]
//! Group 2 (parallel):   [MovementSystem, AISystem, HealthRegenSystem]
//! Group 3 (sequential): [DamageSystem]
//! Group 4 (parallel):   [AnimationSystem, AudioSystem]
//!
//! Group 2 runs only after Group 1 completes.
//! Within Group 2, all three systems run concurrently.
//! Group 3 runs only after Group 2 fully completes.
//!
//! ## Parallel Safety
//! The SGC's parallelization_safety_model verifies that systems in
//! a parallel group have no shared writes and no RAW hazards.
//! If any hazard exists, systems are placed in separate sequential groups.
//!
//! ## Determinism (D1)
//! Systems within a sequential group run in the exact order declared
//! in the `systems` vec — never reordered at runtime.
//! Systems within a parallel group produce deterministic output because
//! the SGC only groups systems with truly independent write sets.
//! Thread-local event buffers are merged in system_id order at phase end.

use serde::{Deserialize, Serialize};
use crate::runtime::phase_enum::PhaseEnum;

// ── Execution Group ───────────────────────────────────────────────────────────

/// A group of systems scheduled to run together in a phase.
///
/// Produced by the SGC and embedded in the ExecutionPlan.
/// Read by the PhaseOrchestrator at runtime to drive tick execution.
///
/// ## Group ID
/// Group IDs are assigned by the SGC during ExecutionPlan compilation.
/// Format: "{phase_name}_group_{index}" — e.g. "Simulation_group_0".
/// Immutable once assigned — embedded in the ExecutionPlan hash.
///
/// ## Serialization Constraints
/// Some systems must not run in parallel even without data hazards —
/// for example, systems that call external APIs or have hidden global state.
/// `serialization_constraints` lists system IDs that must run sequentially
/// even if the SGC's hazard analysis would allow parallelism.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ExecutionGroup {
    /// Unique identifier for this group within its phase.
    /// Format: "{PhaseName}_group_{index}"
    /// Example: "Simulation_group_2"
    pub group_id: String,

    /// The phase this group belongs to.
    /// All systems in this group must be assigned to this phase.
    pub phase: PhaseEnum,

    /// Whether systems in this group run in parallel.
    /// true  = parallel execution (thread pool, deterministic merge)
    /// false = sequential execution (strict declaration order)
    pub parallel: bool,

    /// The system IDs in this group, in execution order.
    ///
    /// For sequential groups: systems run in this exact order.
    /// For parallel groups: systems run concurrently but this order
    /// is used for deterministic event buffer merge at phase end.
    ///
    /// Always sorted by system_id within parallel groups (D11)
    /// to ensure deterministic merge order regardless of thread completion.
    pub systems: Vec<String>,

    /// System IDs within this group that must run sequentially
    /// even though the group is marked parallel.
    ///
    /// Used for systems with hidden external dependencies that the
    /// SGC's static analysis cannot detect. Empty for most groups.
    pub serialization_constraints: Vec<String>,

    /// The execution index of this group within its phase.
    /// Groups run in ascending execution_index order.
    /// Assigned by the SGC scheduler — immutable after assignment.
    pub execution_index: u32,
}

impl ExecutionGroup {
    /// Creates a sequential execution group.
    ///
    /// Systems run in declaration order, one after another.
    /// Used when systems have data dependencies between them.
    pub fn sequential(
        group_id: impl Into<String>,
        phase: PhaseEnum,
        systems: Vec<String>,
        execution_index: u32,
    ) -> Self {
        Self {
            group_id: group_id.into(),
            phase,
            parallel: false,
            systems,
            serialization_constraints: Vec::new(),
            execution_index,
        }
    }

    /// Creates a parallel execution group.
    ///
    /// Systems run concurrently via thread pool.
    /// SGC guarantees no shared writes and no RAW hazards between them.
    /// Event buffers are merged in system_id order at phase end (D11).
    pub fn parallel(
        group_id: impl Into<String>,
        phase: PhaseEnum,
        mut systems: Vec<String>,
        execution_index: u32,
    ) -> Self {
        // Sort systems by ID for deterministic merge order (D11)
        systems.sort();
        Self {
            group_id: group_id.into(),
            phase,
            parallel: true,
            systems,
            serialization_constraints: Vec::new(),
            execution_index,
        }
    }

    /// Returns true if this group contains a system with the given ID.
    pub fn contains_system(&self, system_id: &str) -> bool {
        self.systems.iter().any(|s| s == system_id)
    }

    /// Returns the number of systems in this group.
    pub fn system_count(&self) -> usize {
        self.systems.len()
    }

    /// Returns true if this group is empty (no systems).
    /// Empty groups are produced by the SGC as errors — never valid.
    pub fn is_empty(&self) -> bool {
        self.systems.is_empty()
    }

    /// Returns true if a system in this group has a serialization constraint.
    pub fn has_serialization_constraint(&self, system_id: &str) -> bool {
        self.serialization_constraints.iter().any(|s| s == system_id)
    }

    /// Returns true if this group is safe to run in parallel.
    /// A parallel group with serialization constraints on ALL systems
    /// is effectively sequential and should have been marked as such.
    pub fn is_effectively_parallel(&self) -> bool {
        if !self.parallel {
            return false;
        }
        // If every system has a serialization constraint, it's sequential
        if self.systems.len() > 0
            && self.serialization_constraints.len() >= self.systems.len()
        {
            return false;
        }
        true
    }

    /// Validates this group for structural correctness.
    ///
    /// Checks:
    /// - group_id is not empty
    /// - At least one system declared
    /// - No duplicate system IDs
    /// - All serialization_constraints reference systems in this group
    pub fn validate(&self) -> Result<(), String> {
        if self.group_id.is_empty() {
            return Err("ExecutionGroup group_id must not be empty".into());
        }

        if self.systems.is_empty() {
            return Err(format!(
                "ExecutionGroup {} has no systems — empty groups are invalid",
                self.group_id
            ));
        }

        // Check duplicate system IDs
        let mut seen = std::collections::HashSet::new();
        for sys in &self.systems {
            if !seen.insert(sys.as_str()) {
                return Err(format!(
                    "ExecutionGroup {} has duplicate system ID: {}",
                    self.group_id, sys
                ));
            }
        }

        // All serialization constraints must reference systems in this group
        for constraint in &self.serialization_constraints {
            if !self.contains_system(constraint) {
                return Err(format!(
                    "ExecutionGroup {} serialization constraint '{}' \
                     references a system not in this group",
                    self.group_id, constraint
                ));
            }
        }

        Ok(())
    }
}

impl std::fmt::Display for ExecutionGroup {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "{}[{}]({} systems, {})",
            self.group_id,
            self.phase,
            self.systems.len(),
            if self.parallel { "parallel" } else { "sequential" }
        )
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sequential_group_not_parallel() {
        let group = ExecutionGroup::sequential(
            "Simulation_group_0",
            PhaseEnum::Simulation,
            vec!["sys_input".into()],
            0,
        );
        assert!(!group.parallel);
        assert!(!group.is_effectively_parallel());
    }

    #[test]
    fn parallel_group_is_parallel() {
        let group = ExecutionGroup::parallel(
            "Simulation_group_1",
            PhaseEnum::Simulation,
            vec!["sys_movement".into(), "sys_ai".into()],
            1,
        );
        assert!(group.parallel);
        assert!(group.is_effectively_parallel());
    }

    #[test]
    fn parallel_group_sorts_systems() {
        let group = ExecutionGroup::parallel(
            "Simulation_group_1",
            PhaseEnum::Simulation,
            vec![
                "sys_movement".into(),
                "sys_ai".into(),
                "sys_health".into(),
            ],
            1,
        );
        assert_eq!(group.systems[0], "sys_ai");
        assert_eq!(group.systems[1], "sys_health");
        assert_eq!(group.systems[2], "sys_movement");
    }

    #[test]
    fn contains_system_works() {
        let group = ExecutionGroup::sequential(
            "Input_group_0",
            PhaseEnum::Input,
            vec!["sys_input".into()],
            0,
        );
        assert!(group.contains_system("sys_input"));
        assert!(!group.contains_system("sys_movement"));
    }

    #[test]
    fn system_count_correct() {
        let group = ExecutionGroup::parallel(
            "Simulation_group_1",
            PhaseEnum::Simulation,
            vec!["sys_a".into(), "sys_b".into(), "sys_c".into()],
            1,
        );
        assert_eq!(group.system_count(), 3);
    }

    #[test]
    fn empty_group_detected() {
        let group = ExecutionGroup::sequential(
            "Simulation_group_0",
            PhaseEnum::Simulation,
            vec![],
            0,
        );
        assert!(group.is_empty());
    }

    #[test]
    fn validate_passes_for_valid_group() {
        let group = ExecutionGroup::sequential(
            "Simulation_group_0",
            PhaseEnum::Simulation,
            vec!["sys_input".into()],
            0,
        );
        assert!(group.validate().is_ok());
    }

    #[test]
    fn validate_fails_for_empty_id() {
        let group = ExecutionGroup::sequential(
            "",
            PhaseEnum::Simulation,
            vec!["sys_input".into()],
            0,
        );
        assert!(group.validate().is_err());
    }

    #[test]
    fn validate_fails_for_no_systems() {
        let group = ExecutionGroup::sequential(
            "Simulation_group_0",
            PhaseEnum::Simulation,
            vec![],
            0,
        );
        assert!(group.validate().is_err());
    }

    #[test]
    fn validate_fails_for_duplicate_systems() {
        let mut group = ExecutionGroup::sequential(
            "Simulation_group_0",
            PhaseEnum::Simulation,
            vec!["sys_input".into(), "sys_input".into()],
            0,
        );
        group.parallel = false;
        assert!(group.validate().is_err());
    }

    #[test]
    fn validate_fails_for_invalid_constraint() {
        let mut group = ExecutionGroup::parallel(
            "Simulation_group_1",
            PhaseEnum::Simulation,
            vec!["sys_movement".into()],
            1,
        );
        group.serialization_constraints.push("sys_nonexistent".into());
        assert!(group.validate().is_err());
    }

    #[test]
    fn serialization_constraint_detected() {
        let mut group = ExecutionGroup::parallel(
            "Simulation_group_1",
            PhaseEnum::Simulation,
            vec!["sys_movement".into(), "sys_ai".into()],
            1,
        );
        group.serialization_constraints.push("sys_movement".into());
        assert!(group.has_serialization_constraint("sys_movement"));
        assert!(!group.has_serialization_constraint("sys_ai"));
    }

    #[test]
    fn display_includes_phase_and_count() {
        let group = ExecutionGroup::parallel(
            "Simulation_group_1",
            PhaseEnum::Simulation,
            vec!["sys_movement".into(), "sys_ai".into()],
            1,
        );
        let display = group.to_string();
        assert!(display.contains("Simulation"));
        assert!(display.contains("parallel"));
        assert!(display.contains("2"));
    }

    #[test]
    fn execution_index_stored_correctly() {
        let group = ExecutionGroup::sequential(
            "Cleanup_group_0",
            PhaseEnum::Cleanup,
            vec!["sys_cleanup".into()],
            7,
        );
        assert_eq!(group.execution_index, 7);
    }

    #[test]
    fn phase_stored_correctly() {
        let group = ExecutionGroup::sequential(
            "Input_group_0",
            PhaseEnum::Input,
            vec!["sys_input".into()],
            0,
        );
        assert_eq!(group.phase, PhaseEnum::Input);
    }
}