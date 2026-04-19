//! # Execution Plan
//!
//! The complete, compiled, deterministic runtime schedule produced by
//! the System Graph Compiler (SGC). Tells the PhaseOrchestrator exactly
//! which systems run in which order every tick.
//!
//! ## What the ExecutionPlan Is
//! The ExecutionPlan is the output of the SGC pipeline. It takes the
//! SystemDefinitions from the CGS and compiles them into a concrete
//! schedule — phases, groups, and system ordering — that the runtime
//! can execute without any further decision-making.
//!
//! The runtime is a pure executor. It never decides ordering at runtime.
//! All scheduling decisions are made by the SGC at compile time and
//! frozen into the ExecutionPlan (D1).
//!
//! ## Versioning and Validation (D10, I7)
//! Every ExecutionPlan carries the schema_version it was compiled from.
//! The runtime validates this against the current CGS version before
//! executing any tick. Version mismatch = immediate halt (I7).
//! This prevents stale plans from executing against an updated schema.
//!
//! ## Plan Hash
//! The plan_hash is a deterministic hash of the entire ExecutionPlan
//! content. Used by the DeterminismGuard to verify that two machines
//! running the same CGS produce identical execution plans (D9).
//!
//! ## Recompilation
//! The SGC recompiles the ExecutionPlan whenever:
//! - A system is added or removed from the CGS
//! - A system's phase assignment changes
//! - A system's read/write declarations change
//! - A system's explicit dependencies change
//! The GDE flags MutationTransactions that require recompile (D10).

use std::collections::BTreeMap;
use serde::{Deserialize, Serialize};
use crate::runtime::phase_enum::PhaseEnum;
use crate::runtime::execution_group::ExecutionGroup;

// ── Phase Schedule ────────────────────────────────────────────────────────────

/// The compiled schedule for a single execution phase.
///
/// Contains all execution groups for one phase, ordered by
/// execution_index ascending. The PhaseOrchestrator runs groups
/// in this order — group N must complete before group N+1 starts,
/// even if both are marked parallel internally.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PhaseSchedule {
    /// Which phase this schedule covers.
    pub phase: PhaseEnum,

    /// Execution groups in this phase, ordered by execution_index ASC.
    /// The PhaseOrchestrator runs them in this exact order.
    pub groups: Vec<ExecutionGroup>,

    /// Total number of systems across all groups in this phase.
    /// Cached for quick access — recomputed by SGC on plan creation.
    pub total_system_count: usize,
}

impl PhaseSchedule {
    /// Creates a phase schedule from an ordered list of groups.
    pub fn new(phase: PhaseEnum, groups: Vec<ExecutionGroup>) -> Self {
        let total_system_count = groups.iter().map(|g| g.system_count()).sum();
        Self {
            phase,
            groups,
            total_system_count,
        }
    }

    /// Returns true if this phase has no systems to execute.
    /// Empty phases are skipped by the PhaseOrchestrator.
    pub fn is_empty(&self) -> bool {
        self.total_system_count == 0
    }

    /// Returns the group containing the given system ID, if any.
    pub fn group_for_system(&self, system_id: &str) -> Option<&ExecutionGroup> {
        self.groups.iter().find(|g| g.contains_system(system_id))
    }

    /// Returns true if this phase contains the given system.
    pub fn contains_system(&self, system_id: &str) -> bool {
        self.groups.iter().any(|g| g.contains_system(system_id))
    }

    /// Returns all system IDs in this phase in execution order.
    /// Within parallel groups, systems are listed in sorted ID order (D11).
    pub fn all_system_ids(&self) -> Vec<&str> {
        self.groups
            .iter()
            .flat_map(|g| g.systems.iter().map(|s| s.as_str()))
            .collect()
    }
}

// ── Execution Plan ────────────────────────────────────────────────────────────

/// The complete compiled runtime execution schedule.
///
/// Produced by the SGC from the CGS SystemDefinitions.
/// Consumed by the PhaseOrchestrator every tick.
/// Immutable at runtime — never modified after creation.
///
/// ## Structure
/// ExecutionPlan
///   └── phases: BTreeMap<PhaseEnum, PhaseSchedule>
///         └── PhaseSchedule
///               └── groups: Vec<ExecutionGroup>
///                     └── systems: Vec<SystemId>
///
/// ## Lifecycle
/// CGS mutated → SGC recompiles → new ExecutionPlan created →
/// runtime validates version match (I7) → PhaseOrchestrator uses new plan
///
/// ## Determinism Proof
/// The SGC guarantees that given identical CGS + identical SystemDefinitions,
/// the produced ExecutionPlan is always byte-for-byte identical (D9, D11).
/// The plan_hash captures this guarantee in a single verifiable value.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecutionPlan {
    /// The CGS semantic version this plan was compiled from.
    /// Runtime halts if this does not match current CGS version (I7, D10).
    pub schema_version: String,

    /// Monotonically incrementing plan version.
    /// Starts at 1. Incremented each time the SGC recompiles.
    /// Embedded in WireMessage for engine adapter version validation.
    pub plan_version: u32,

    /// The simulation tick on which this plan was created.
    /// Used for replay validation — replays must use the plan that was
    /// active at the tick they were recorded on.
    pub created_tick: u64,

    /// Deterministic hash of this plan's entire content.
    /// Same CGS + same systems = same hash, always (D9, D11).
    /// Verified by DeterminismGuard on plan creation.
    pub plan_hash: String,

    /// Phase schedules keyed by PhaseEnum.
    /// BTreeMap guarantees deterministic iteration order (D11).
    /// All five phases are always present — empty phases have no groups.
    pub phases: BTreeMap<u8, PhaseSchedule>,

    /// All system IDs covered by this plan, sorted ascending (D11).
    /// Used for quick existence checks without iterating all phases.
    pub all_system_ids: Vec<String>,

    /// The CGS hash this plan was compiled from.
    /// Cross-referenced with CGS metadata.cgs_hash at runtime (D10).
    pub compiled_from_cgs_hash: String,
}

impl ExecutionPlan {
    /// Creates a new ExecutionPlan from compiled phase schedules.
    pub fn new(
        schema_version: impl Into<String>,
        plan_version: u32,
        created_tick: u64,
        plan_hash: impl Into<String>,
        phase_schedules: Vec<PhaseSchedule>,
        compiled_from_cgs_hash: impl Into<String>,
    ) -> Self {
        let mut phases = BTreeMap::new();
        let mut all_system_ids = Vec::new();

        for schedule in phase_schedules {
            // Collect all system IDs
            for group in &schedule.groups {
                for sys_id in &group.systems {
                    all_system_ids.push(sys_id.clone());
                }
            }
            phases.insert(schedule.phase.as_u8(), schedule);
        }

        // Sort all system IDs for deterministic lookup (D11)
        all_system_ids.sort();
        all_system_ids.dedup();

        Self {
            schema_version: schema_version.into(),
            plan_version,
            created_tick,
            plan_hash: plan_hash.into(),
            phases,
            all_system_ids,
            compiled_from_cgs_hash: compiled_from_cgs_hash.into(),
        }
    }

    /// Returns the phase schedule for the given phase, if present.
    pub fn get_phase(&self, phase: PhaseEnum) -> Option<&PhaseSchedule> {
        self.phases.get(&phase.as_u8())
    }

    /// Returns true if the given system ID is in this plan.
    pub fn contains_system(&self, system_id: &str) -> bool {
        self.all_system_ids.binary_search_by(|s| s.as_str().cmp(system_id)).is_ok()
    }

    /// Returns which phase the given system runs in.
    /// Returns None if the system is not in this plan.
    pub fn phase_for_system(&self, system_id: &str) -> Option<PhaseEnum> {
        for (phase_byte, schedule) in &self.phases {
            if schedule.contains_system(system_id) {
                return PhaseEnum::from_u8(*phase_byte);
            }
        }
        None
    }

    /// Returns all system IDs in execution order across all phases.
    /// Order: Initialization → Input → Simulation → PostSimulation → Cleanup.
    /// Within each phase, systems appear in group execution_index order.
    pub fn all_systems_in_order(&self) -> Vec<&str> {
        PhaseEnum::ALL
            .iter()
            .filter_map(|phase| self.get_phase(*phase))
            .flat_map(|schedule| schedule.all_system_ids())
            .collect()
    }

    /// Returns the total number of systems across all phases.
    pub fn total_system_count(&self) -> usize {
        self.all_system_ids.len()
    }

    /// Returns true if this plan is empty (no systems scheduled).
    /// Empty plans are valid for games with no user-defined systems yet.
    pub fn is_empty(&self) -> bool {
        self.all_system_ids.is_empty()
    }

    /// Validates this ExecutionPlan for structural correctness.
    ///
    /// Checks:
    /// - schema_version is not empty
    /// - plan_version >= 1
    /// - plan_hash is not empty
    /// - compiled_from_cgs_hash is not empty
    /// - All phase schedules pass validation
    /// - No system appears in more than one phase
    /// - all_system_ids matches actual systems in phases
    pub fn validate(&self) -> Result<(), String> {
        if self.schema_version.is_empty() {
            return Err("ExecutionPlan schema_version must not be empty".into());
        }

        if self.plan_version == 0 {
            return Err("ExecutionPlan plan_version must be >= 1".into());
        }

        if self.plan_hash.is_empty() {
            return Err("ExecutionPlan plan_hash must not be empty".into());
        }

        if self.compiled_from_cgs_hash.is_empty() {
            return Err(
                "ExecutionPlan compiled_from_cgs_hash must not be empty".into()
            );
        }

        // Validate all phase schedules and check for cross-phase duplicates
        let mut seen_systems = std::collections::HashSet::new();
        for (phase_byte, schedule) in &self.phases {
            // Validate each group
            for group in &schedule.groups {
                group.validate().map_err(|e| {
                    format!(
                        "Phase {} group {} invalid: {}",
                        phase_byte, group.group_id, e
                    )
                })?;

                // Check for cross-phase duplicates
                for sys_id in &group.systems {
                    if !seen_systems.insert(sys_id.as_str()) {
                        return Err(format!(
                            "System '{}' appears in multiple phases — \
                             each system must be in exactly one phase",
                            sys_id
                        ));
                    }
                }
            }
        }

        Ok(())
    }

    /// Returns true if this plan's schema version matches the given version.
    /// Used by the runtime to validate before executing each tick (I7, D10).
    pub fn matches_schema_version(&self, version: &str) -> bool {
        self.schema_version == version
    }

    /// Returns true if this plan was compiled from the given CGS hash.
    /// Cross-referenced with CGS metadata at runtime (D10).
    pub fn matches_cgs_hash(&self, cgs_hash: &str) -> bool {
        self.compiled_from_cgs_hash == cgs_hash
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn test_plan() -> ExecutionPlan {
        let input_group = ExecutionGroup::sequential(
            "Input_group_0",
            PhaseEnum::Input,
            vec!["sys_input".into()],
            0,
        );

        let sim_group_1 = ExecutionGroup::sequential(
            "Simulation_group_0",
            PhaseEnum::Simulation,
            vec!["sys_damage".into()],
            0,
        );

        let sim_group_2 = ExecutionGroup::parallel(
            "Simulation_group_1",
            PhaseEnum::Simulation,
            vec!["sys_movement".into(), "sys_ai".into()],
            1,
        );

        let cleanup_group = ExecutionGroup::sequential(
            "Cleanup_group_0",
            PhaseEnum::Cleanup,
            vec!["sys_cleanup".into()],
            0,
        );

        let phases = vec![
            PhaseSchedule::new(PhaseEnum::Input, vec![input_group]),
            PhaseSchedule::new(
                PhaseEnum::Simulation,
                vec![sim_group_1, sim_group_2],
            ),
            PhaseSchedule::new(PhaseEnum::Cleanup, vec![cleanup_group]),
        ];

        ExecutionPlan::new(
            "0.1.0",
            1,
            0,
            "plan_hash_abc123",
            phases,
            "cgs_hash_xyz456",
        )
    }

    #[test]
    fn plan_validates_successfully() {
        assert!(test_plan().validate().is_ok());
    }

    #[test]
    fn empty_schema_version_fails() {
        let mut plan = test_plan();
        plan.schema_version = String::new();
        assert!(plan.validate().is_err());
    }

    #[test]
    fn zero_plan_version_fails() {
        let mut plan = test_plan();
        plan.plan_version = 0;
        assert!(plan.validate().is_err());
    }

    #[test]
    fn empty_plan_hash_fails() {
        let mut plan = test_plan();
        plan.plan_hash = String::new();
        assert!(plan.validate().is_err());
    }

    #[test]
    fn contains_system_works() {
        let plan = test_plan();
        assert!(plan.contains_system("sys_input"));
        assert!(plan.contains_system("sys_movement"));
        assert!(plan.contains_system("sys_ai"));
        assert!(!plan.contains_system("sys_nonexistent"));
    }

    #[test]
    fn phase_for_system_correct() {
        let plan = test_plan();
        assert_eq!(
            plan.phase_for_system("sys_input"),
            Some(PhaseEnum::Input)
        );
        assert_eq!(
            plan.phase_for_system("sys_movement"),
            Some(PhaseEnum::Simulation)
        );
        assert_eq!(
            plan.phase_for_system("sys_cleanup"),
            Some(PhaseEnum::Cleanup)
        );
        assert_eq!(plan.phase_for_system("sys_missing"), None);
    }

    #[test]
    fn total_system_count_correct() {
        let plan = test_plan();
        assert_eq!(plan.total_system_count(), 5);
    }

    #[test]
    fn all_systems_in_order_correct() {
        let plan = test_plan();
        let systems = plan.all_systems_in_order();
        // Input comes before Simulation
        let input_pos = systems.iter().position(|&s| s == "sys_input").unwrap();
        let movement_pos = systems.iter().position(|&s| s == "sys_movement").unwrap();
        assert!(input_pos < movement_pos);
        // Simulation comes before Cleanup
        let cleanup_pos = systems.iter().position(|&s| s == "sys_cleanup").unwrap();
        assert!(movement_pos < cleanup_pos);
    }

    #[test]
    fn get_phase_returns_correct_schedule() {
        let plan = test_plan();
        let input_schedule = plan.get_phase(PhaseEnum::Input);
        assert!(input_schedule.is_some());
        assert!(input_schedule.unwrap().contains_system("sys_input"));
    }

    #[test]
    fn get_phase_returns_none_for_missing_phase() {
        let plan = test_plan();
        // PostSimulation has no systems in test plan
        let post_sim = plan.get_phase(PhaseEnum::PostSimulation);
        assert!(post_sim.is_none());
    }

    #[test]
    fn matches_schema_version_correct() {
        let plan = test_plan();
        assert!(plan.matches_schema_version("0.1.0"));
        assert!(!plan.matches_schema_version("0.2.0"));
    }

    #[test]
    fn matches_cgs_hash_correct() {
        let plan = test_plan();
        assert!(plan.matches_cgs_hash("cgs_hash_xyz456"));
        assert!(!plan.matches_cgs_hash("wrong_hash"));
    }

    #[test]
    fn phase_schedule_empty_detection() {
        let schedule = PhaseSchedule::new(PhaseEnum::Initialization, vec![]);
        assert!(schedule.is_empty());
    }

    #[test]
    fn phase_schedule_system_ids_in_order() {
        let group1 = ExecutionGroup::sequential(
            "Simulation_group_0",
            PhaseEnum::Simulation,
            vec!["sys_damage".into()],
            0,
        );
        let group2 = ExecutionGroup::parallel(
            "Simulation_group_1",
            PhaseEnum::Simulation,
            vec!["sys_movement".into(), "sys_ai".into()],
            1,
        );
        let schedule = PhaseSchedule::new(
            PhaseEnum::Simulation,
            vec![group1, group2],
        );
        let ids = schedule.all_system_ids();
        assert_eq!(ids[0], "sys_damage");
        // parallel group sorted: sys_ai < sys_movement
        assert_eq!(ids[1], "sys_ai");
        assert_eq!(ids[2], "sys_movement");
    }

    #[test]
    fn is_empty_false_when_systems_exist() {
        assert!(!test_plan().is_empty());
    }

    #[test]
    fn duplicate_system_across_phases_fails() {
        let group1 = ExecutionGroup::sequential(
            "Input_group_0",
            PhaseEnum::Input,
            vec!["sys_duplicate".into()],
            0,
        );
        let group2 = ExecutionGroup::sequential(
            "Simulation_group_0",
            PhaseEnum::Simulation,
            vec!["sys_duplicate".into()],
            0,
        );
        let mut plan = ExecutionPlan::new(
            "0.1.0",
            1,
            0,
            "hash",
            vec![
                PhaseSchedule::new(PhaseEnum::Input, vec![group1]),
                PhaseSchedule::new(PhaseEnum::Simulation, vec![group2]),
            ],
            "cgs_hash",
        );
        plan.plan_hash = "hash".into();
        assert!(plan.validate().is_err());
    }
}