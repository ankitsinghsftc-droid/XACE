//! # Deterministic Scheduler Builder — SGC Stage 5
//!
//! Converts the OrderedGraph and ConflictReport into a concrete ExecutionPlan v1
//! by assigning a per-phase execution index to every ExecutionGroup and grouping
//! groups into PhaseSchedules inside the ExecutionPlan.
//!
//! ## Input → Output
//! Input:  &OrderedGraph (from Stage 3) + &ConflictReport (from Stage 4)
//! Output: ExecutionPlan — the authoritative execution contract for the runtime
//!
//! ## What the Scheduler Does
//! 1. Calls ParallelGroupAnalyzer to get ParallelWindows per phase
//! 2. Groups windows by phase ordinal (BTreeMap → sorted, D11)
//! 3. Converts each window into an ExecutionGroup with a per-phase execution_index
//! 4. Wraps each phase's groups into a PhaseSchedule
//! 5. Computes a stable SHA-256 hash over all groups in phase ordinal order
//! 6. Assembles via ExecutionPlan::new() → BTreeMap<u8, PhaseSchedule> internally
//!
//! ## ExecutionPlan v1 Structure
//! ExecutionPlan
//!   └── phases: BTreeMap<u8, PhaseSchedule>   (keyed by phase ordinal)
//!         └── PhaseSchedule.groups: Vec<ExecutionGroup>  (ordered by execution_index)
//!
//! ## Determinism (D1, D11)
//! The plan is the authoritative definition of system execution order.
//! Systems within each parallel group are sorted lexicographically (D11).
//! The plan hash changes if any system is added, removed, or reordered (D9).

use std::collections::BTreeMap;

use sha2::{Digest, Sha256};
use xace_core::runtime::execution_group::ExecutionGroup;
use xace_core::runtime::execution_plan::{ExecutionPlan, PhaseSchedule};
use xace_core::runtime::phase_enum::PhaseEnum;

use crate::conflict_analyzer::conflict_analyzer::ConflictReport;
use crate::dependency_resolution::dependency_resolution_engine::OrderedGraph;
use crate::scheduler::parallel_group_analyzer::{ParallelGroupAnalyzer, ParallelWindow};

// ── Deterministic Scheduler Builder ──────────────────────────────────────────

/// SGC Stage 5 — produces the ExecutionPlan from ordered + conflict data.
///
/// Stateless — one call to `build()` per compilation.
pub struct DeterministicSchedulerBuilder;

impl DeterministicSchedulerBuilder {
    /// Builds the ExecutionPlan from the ordered graph and conflict report.
    ///
    /// ## Arguments
    /// - `ordered_graph`:   topologically sorted systems per phase (Stage 3 output)
    /// - `conflict_report`: serialization constraints per phase (Stage 4 output)
    /// - `schema_version`:  the CGS version this plan was compiled from
    /// - `plan_version`:    monotonically increasing plan identifier
    pub fn build(
        ordered_graph: &OrderedGraph,
        conflict_report: &ConflictReport,
        schema_version: &str,
        plan_version: u32,
    ) -> ExecutionPlan {
        // Step 1: Get parallel windows across all phases from the analyzer.
        let windows = ParallelGroupAnalyzer::analyze_all(ordered_graph, conflict_report);

        // Step 2: Group window indices by phase ordinal.
        // BTreeMap sorts by key → phases processed in Initialization→Cleanup order (D11).
        let mut by_phase: BTreeMap<u8, Vec<usize>> = BTreeMap::new();
        for (i, window) in windows.iter().enumerate() {
            by_phase.entry(window.phase.as_u8()).or_default().push(i);
        }

        // Step 3: Build ExecutionGroups with per-phase execution_index.
        // Collect all groups for hashing (must be in same order as phase_schedules).
        let mut all_groups: Vec<ExecutionGroup> = Vec::new();
        let mut phase_schedules: Vec<PhaseSchedule> = Vec::new();

        for (_, window_indices) in &by_phase {
            let mut phase_groups: Vec<ExecutionGroup> = Vec::new();
            for (exec_idx, &win_idx) in window_indices.iter().enumerate() {
                let group = Self::window_to_execution_group(&windows[win_idx], exec_idx as u32);
                all_groups.push(group.clone());
                phase_groups.push(group);
            }
            // All windows in this phase share the same phase value.
            let phase = windows[window_indices[0]].phase;
            phase_schedules.push(PhaseSchedule::new(phase, phase_groups));
        }

        // Step 4: Compute deterministic plan hash over all groups in phase order (D9, D11).
        let plan_hash = Self::compute_plan_hash(&all_groups, schema_version, plan_version);

        // Step 5: Assemble final ExecutionPlan.
        // ExecutionPlan::new() builds BTreeMap<u8, PhaseSchedule> and all_system_ids internally.
        ExecutionPlan::new(
            schema_version,
            plan_version,
            0, // created_tick: set to current tick by caller at runtime init
            plan_hash,
            phase_schedules,
            "", // compiled_from_cgs_hash: set by GDE/CGS manager, not SGC
        )
    }

    /// Builds and verifies all expected systems appear in the plan.
    pub fn build_and_verify(
        ordered_graph: &OrderedGraph,
        conflict_report: &ConflictReport,
        schema_version: &str,
        plan_version: u32,
    ) -> Result<ExecutionPlan, String> {
        let plan = Self::build(ordered_graph, conflict_report, schema_version, plan_version);

        let expected = ordered_graph.total_system_count();
        let actual = plan.total_system_count();

        if actual != expected {
            return Err(format!(
                "SchedulerBuilder: expected {} systems but plan contains {}. \
                 System(s) lost during scheduling.",
                expected, actual
            ));
        }
        Ok(plan)
    }

    // ── Internal ──────────────────────────────────────────────────────────────

    /// Converts a ParallelWindow into an ExecutionGroup with the given per-phase index.
    ///
    /// Parallel groups: systems sorted lexicographically (D11).
    /// Sequential groups: order preserved from topological sort (D1).
    fn window_to_execution_group(window: &ParallelWindow, execution_index: u32) -> ExecutionGroup {
        let mut systems = window.systems.clone();
        if window.is_parallel {
            systems.sort_unstable(); // lexicographic sort for deterministic merge (D11)
        }

        let serialization_constraints: Vec<String> = if !window.is_parallel && systems.len() > 1 {
            systems
                .windows(2)
                .map(|pair| format!("{}_before_{}", pair[0], pair[1]))
                .collect()
        } else {
            Vec::new()
        };

        ExecutionGroup {
            parallel: window.is_parallel,
            systems,
            group_id: window.group_id(),
            phase: window.phase,
            serialization_constraints,
            execution_index,
        }
    }

    /// Computes a stable SHA-256 hash of the plan content (D9, D11).
    ///
    /// Inputs: all groups in phase ordinal order, schema_version, plan_version.
    /// Same input → identical 64-character hex string, always.
    fn compute_plan_hash(
        groups: &[ExecutionGroup],
        schema_version: &str,
        plan_version: u32,
    ) -> String {
        let mut h = Sha256::new();
        h.update((schema_version.len() as u64).to_be_bytes());
        h.update(schema_version.as_bytes());
        h.update(plan_version.to_be_bytes());
        h.update((groups.len() as u64).to_be_bytes());
        for group in groups {
            h.update([group.phase.as_u8()]);
            h.update([u8::from(group.parallel)]);
            h.update((group.systems.len() as u64).to_be_bytes());
            for sys_id in &group.systems {
                h.update((sys_id.len() as u64).to_be_bytes());
                h.update(sys_id.as_bytes());
            }
        }
        h.finalize().iter().map(|b| format!("{:02x}", b)).collect()
    }
}

// ── Plan Inspector ────────────────────────────────────────────────────────────

/// Read-only inspection utilities for a built ExecutionPlan.
///
/// Wraps the `ExecutionPlan`'s `BTreeMap<u8, PhaseSchedule>` structure
/// so callers don't need to navigate the nested phase → schedule → groups hierarchy.
pub struct PlanInspector;

impl PlanInspector {
    /// Returns all system IDs across all phases in execution order.
    /// Delegates to `ExecutionPlan::all_systems_in_order()`.
    pub fn all_systems_in_order(plan: &ExecutionPlan) -> Vec<&str> {
        plan.all_systems_in_order()
    }

    /// Returns all parallel ExecutionGroups across all phases.
    /// Iterates phases in ordinal order (BTreeMap key order, D11).
    pub fn parallel_groups(plan: &ExecutionPlan) -> Vec<&ExecutionGroup> {
        plan.phases
            .values()
            .flat_map(|schedule| schedule.groups.iter())
            .filter(|g| g.parallel)
            .collect()
    }

    /// Returns all serial ExecutionGroups across all phases.
    /// Iterates phases in ordinal order (BTreeMap key order, D11).
    pub fn serial_groups(plan: &ExecutionPlan) -> Vec<&ExecutionGroup> {
        plan.phases
            .values()
            .flat_map(|schedule| schedule.groups.iter())
            .filter(|g| !g.parallel)
            .collect()
    }

    /// Returns the total number of systems in the plan.
    pub fn total_system_count(plan: &ExecutionPlan) -> usize {
        plan.total_system_count()
    }

    /// Returns all ExecutionGroups in the given phase, in execution_index order.
    /// Returns an empty Vec if the phase has no systems.
    pub fn groups_for_phase<'a>(
        plan: &'a ExecutionPlan,
        phase: PhaseEnum,
    ) -> Vec<&'a ExecutionGroup> {
        plan.get_phase(phase)
            .map(|schedule| schedule.groups.iter().collect())
            .unwrap_or_default()
    }

    /// Returns true if `system_a` is globally ordered before `system_b`.
    /// Returns false if either system is not in the plan.
    pub fn is_before(plan: &ExecutionPlan, system_a: &str, system_b: &str) -> bool {
        let all = plan.all_systems_in_order();
        match (
            all.iter().position(|&s| s == system_a),
            all.iter().position(|&s| s == system_b),
        ) {
            (Some(a), Some(b)) => a < b,
            _ => false,
        }
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::conflict_analyzer::conflict_analyzer::ConflictAnalyzer;
    use crate::dependency_resolution::dependency_resolution_engine::DependencyResolutionEngine;
    use crate::graph_construction::graph_construction_layer::GraphConstructionLayer;
    use crate::phase_segmentation::phase_segmentation_layer::PhaseSegmentationLayer;
    use xace_core::runtime::phase_enum::PhaseEnum;
    use xace_core::schema::system_definition::{ExecutionPhase, SystemDefinition, SystemVersion};

    /// Builds a SystemDefinition in the Simulation phase.
    fn def(id: &str, reads: Vec<u32>, writes: Vec<u32>) -> SystemDefinition {
        SystemDefinition {
            id: id.into(),
            display_name: id.into(),
            phase: ExecutionPhase::Simulation,
            reads,
            writes,
            depends_on: vec![],
            deterministic: true,
            version: SystemVersion::INITIAL,
            description: String::new(),
        }
    }

    fn build_plan(defs: &[SystemDefinition]) -> ExecutionPlan {
        let graph = GraphConstructionLayer::build(defs).unwrap();
        let buckets = PhaseSegmentationLayer::segment(&graph).unwrap();
        let ordered = DependencyResolutionEngine::resolve(&buckets).unwrap();
        let report = ConflictAnalyzer::analyze(&buckets, &graph).unwrap();
        DeterministicSchedulerBuilder::build(&ordered, &report, "0.1.0", 1)
    }

    #[test]
    fn single_system_one_serial_group() {
        let plan = build_plan(&[def("sys_a", vec![], vec![])]);
        // One Simulation phase, one serial group
        assert_eq!(plan.phases.len(), 1);
        let groups = PlanInspector::groups_for_phase(&plan, PhaseEnum::Simulation);
        assert_eq!(groups.len(), 1);
        assert!(!groups[0].parallel);
        assert_eq!(groups[0].systems, vec!["sys_a"]);
    }

    #[test]
    fn two_independent_systems_parallel_group() {
        let defs = vec![
            def("sys_a", vec![6], vec![6]),
            def("sys_b", vec![100], vec![100]),
        ];
        let plan = build_plan(&defs);
        let parallel = PlanInspector::parallel_groups(&plan);
        assert_eq!(
            parallel.len(),
            1,
            "Independent systems must be in one parallel group"
        );
        assert_eq!(parallel[0].systems.len(), 2);
    }

    #[test]
    fn waw_conflict_two_serial_groups() {
        let defs = vec![
            def("sys_a", vec![], vec![1]),
            def("sys_b", vec![], vec![1]), // WAW on component 1
        ];
        let plan = build_plan(&defs);
        // Both systems are in Simulation — one phase, two serial groups
        let groups = PlanInspector::groups_for_phase(&plan, PhaseEnum::Simulation);
        assert_eq!(groups.len(), 2, "WAW conflict produces two serial groups");
        assert!(
            groups.iter().all(|g| !g.parallel),
            "WAW groups must be serial"
        );
    }

    #[test]
    fn plan_hash_is_64_hex_chars() {
        let plan = build_plan(&[def("sys_a", vec![], vec![])]);
        assert_eq!(plan.plan_hash.len(), 64, "SHA-256 hex is always 64 chars");
        assert!(plan.plan_hash.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn plan_hash_deterministic() {
        let defs = vec![
            def("sys_a", vec![6], vec![6]),
            def("sys_b", vec![100], vec![100]),
        ];
        assert_eq!(
            build_plan(&defs).plan_hash,
            build_plan(&defs).plan_hash,
            "Same input must produce identical plan hash (D11)"
        );
    }

    #[test]
    fn plan_carries_schema_and_version() {
        let graph = GraphConstructionLayer::build(&[def("sys_a", vec![], vec![])]).unwrap();
        let buckets = PhaseSegmentationLayer::segment(&graph).unwrap();
        let ordered = DependencyResolutionEngine::resolve(&buckets).unwrap();
        let report = ConflictAnalyzer::analyze(&buckets, &graph).unwrap();
        let plan = DeterministicSchedulerBuilder::build(&ordered, &report, "1.2.3", 42);
        assert_eq!(plan.schema_version, "1.2.3");
        assert_eq!(plan.plan_version, 42);
    }

    #[test]
    fn inspector_is_before_raw_ordering() {
        let defs = vec![def("sys_a", vec![], vec![5]), def("sys_b", vec![5], vec![])];
        let plan = build_plan(&defs);
        assert!(PlanInspector::is_before(&plan, "sys_a", "sys_b"));
        assert!(!PlanInspector::is_before(&plan, "sys_b", "sys_a"));
    }

    #[test]
    fn build_and_verify_counts_correct() {
        let defs = vec![def("sys_a", vec![], vec![]), def("sys_b", vec![], vec![])];
        let graph = GraphConstructionLayer::build(&defs).unwrap();
        let buckets = PhaseSegmentationLayer::segment(&graph).unwrap();
        let ordered = DependencyResolutionEngine::resolve(&buckets).unwrap();
        let report = ConflictAnalyzer::analyze(&buckets, &graph).unwrap();
        let result = DeterministicSchedulerBuilder::build_and_verify(&ordered, &report, "0.1.0", 1);
        assert!(result.is_ok());
        assert_eq!(PlanInspector::total_system_count(&result.unwrap()), 2);
    }

    #[test]
    fn zombie_chase_plan_ordering_satisfied() {
        let defs = vec![
            def("InputSystem", vec![6, 1], vec![5]),
            def("MovementSystem", vec![5, 1], vec![1]),
            def("AISystem", vec![160, 1], vec![5, 101]),
            def("DamageSystem", vec![101, 100], vec![100, 101]),
            def("DeathSystem", vec![100], vec![]),
        ];
        let plan = build_plan(&defs);
        assert_eq!(PlanInspector::total_system_count(&plan), 5);
        assert!(PlanInspector::is_before(
            &plan,
            "AISystem",
            "MovementSystem"
        ));
        assert!(PlanInspector::is_before(&plan, "AISystem", "DamageSystem"));
        assert!(PlanInspector::is_before(
            &plan,
            "DamageSystem",
            "DeathSystem"
        ));
        assert!(!plan.plan_hash.is_empty());
    }
}
