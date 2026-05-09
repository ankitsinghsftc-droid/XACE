//! # Parallelization Safety Model — SGC Stage 7
//!
//! Final validation pass on the ExecutionPlan produced by the scheduler.
//! Verifies that every parallel ExecutionGroup is truly safe for concurrent
//! execution by checking all pairwise system conflicts within each group.
//!
//! ## Why a Final Pass
//! The ParallelGroupAnalyzer (Stage 5 sub-module) uses a greedy algorithm.
//! Greedy algorithms are correct by design but the safety model provides an
//! independent second opinion. If a bug in the scheduler produced a parallel
//! group with conflicting systems, this stage catches it before the plan
//! is committed and used by the runtime.
//!
//! ## What Is Checked
//! For every parallel ExecutionGroup (parallel == true):
//!   For every pair (A, B) in the group:
//!     1. No WAW conflict (no shared writes)
//!     2. No RAW hazard in either direction
//!     3. Both systems are marked deterministic
//!
//! ## Iteration
//! plan.phases is BTreeMap<u8, PhaseSchedule>. Each PhaseSchedule has
//! groups: Vec<ExecutionGroup>. We iterate phases → groups → pairs.
//!
//! ## Output
//! Returns Ok(()) if the plan is safe, or
//! Err(CompilationError::Conflict(_)) if any parallel group is unsafe.

use xace_core::runtime::execution_plan::ExecutionPlan;
use crate::compilation_error::{CompilationError, ConflictError};
use crate::graph_construction::hazard_detector::HazardDetector;
use crate::graph_construction::system_edge::RawSystemGraph;

// ── Safety Violation ──────────────────────────────────────────────────────────

/// A parallel safety violation found in an ExecutionGroup.
#[derive(Debug, Clone)]
pub struct SafetyViolation {
    pub group_id:          String,
    pub system_a:          String,
    pub system_b:          String,
    pub violation_kind:    SafetyViolationKind,
    pub involved_type_ids: Vec<u32>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SafetyViolationKind {
    WriteWriteConflict,
    ReadWriteHazard,
    NonDeterministicSystem,
}

impl SafetyViolation {
    pub fn description(&self) -> String {
        match self.violation_kind {
            SafetyViolationKind::WriteWriteConflict => format!(
                "Parallel group '{}': systems '{}' and '{}' both write \
                 component type(s) {:?} — WAW conflict in parallel group",
                self.group_id, self.system_a, self.system_b, self.involved_type_ids
            ),
            SafetyViolationKind::ReadWriteHazard => format!(
                "Parallel group '{}': system '{}' writes component type(s) {:?} \
                 that system '{}' reads — RAW hazard in parallel group",
                self.group_id, self.system_a, self.involved_type_ids, self.system_b
            ),
            SafetyViolationKind::NonDeterministicSystem => format!(
                "Parallel group '{}': system '{}' is marked non-deterministic \
                 and cannot participate in parallel execution",
                self.group_id, self.system_a
            ),
        }
    }
}

// ── Parallelization Safety Model ──────────────────────────────────────────────

/// SGC Stage 7 — validates the ExecutionPlan for parallelization safety.
///
/// Stateless — one call to `validate()` per compilation.
pub struct ParallelizationSafetyModel;

impl ParallelizationSafetyModel {
    /// Validates all parallel execution groups in the plan.
    ///
    /// Iterates: plan.phases (BTreeMap<u8, PhaseSchedule>) →
    ///           schedule.groups (Vec<ExecutionGroup>) →
    ///           filter parallel groups →
    ///           pairwise system checks.
    ///
    /// Returns Ok(()) if all parallel groups are safe.
    /// Returns Err on the first safety violation found.
    pub fn validate(
        plan:  &ExecutionPlan,
        graph: &RawSystemGraph,
    ) -> Result<(), CompilationError> {
        // Iterate phases in ordinal order (BTreeMap key order, D11).
        for schedule in plan.phases.values() {
            for group in schedule.groups.iter().filter(|g| g.parallel) {
                Self::validate_parallel_group(&group.group_id, &group.systems, graph)?;
            }
        }
        Ok(())
    }

    /// Validates one parallel group — checks all pairwise combinations.
    fn validate_parallel_group(
        group_id:   &str,
        system_ids: &[String],
        graph:      &RawSystemGraph,
    ) -> Result<(), CompilationError> {
        // Sorted pairs (i < j) for deterministic pair iteration (D11)
        for i in 0..system_ids.len() {
            for j in (i + 1)..system_ids.len() {
                let id_a = &system_ids[i];
                let id_b = &system_ids[j];

                let node_a = graph.nodes.get(id_a.as_str()).ok_or_else(|| {
                    CompilationError::InternalError(format!(
                        "SafetyModel: system '{}' in ExecutionPlan not found in graph",
                        id_a
                    ))
                })?;

                let node_b = graph.nodes.get(id_b.as_str()).ok_or_else(|| {
                    CompilationError::InternalError(format!(
                        "SafetyModel: system '{}' in ExecutionPlan not found in graph",
                        id_b
                    ))
                })?;

                // Check 1: determinism requirement
                if !node_a.deterministic {
                    return Err(Self::non_deterministic_error(group_id, id_a, id_b));
                }
                if !node_b.deterministic {
                    return Err(Self::non_deterministic_error(group_id, id_b, id_a));
                }

                // Check 2: WAW conflict
                let waw = HazardDetector::detect_waw(node_a, node_b);
                if !waw.is_empty() {
                    let type_ids: Vec<u32> = waw.into_iter().collect();
                    return Err(CompilationError::Conflict(ConflictError {
                        system_a:   id_a.clone(),
                        system_b:   id_b.clone(),
                        conflicting_component_type_ids: type_ids.iter().copied().collect(),
                        description: format!(
                            "Parallel group '{}': WAW conflict between '{}' and '{}' \
                             on component type(s) {:?}. \
                             The scheduler placed conflicting systems in a parallel group.",
                            group_id, id_a, id_b, type_ids
                        ),
                    }));
                }

                // Check 3: RAW hazard (both directions)
                let raw_a_b = HazardDetector::detect_raw_a_to_b(node_a, node_b);
                if !raw_a_b.is_empty() {
                    let type_ids: Vec<u32> = raw_a_b.into_iter().collect();
                    return Err(CompilationError::Conflict(ConflictError {
                        system_a:   id_a.clone(),
                        system_b:   id_b.clone(),
                        conflicting_component_type_ids: type_ids.iter().copied().collect(),
                        description: format!(
                            "Parallel group '{}': RAW hazard — '{}' writes component(s) \
                             {:?} that '{}' reads. \
                             The scheduler placed hazardous systems in a parallel group.",
                            group_id, id_a, type_ids, id_b
                        ),
                    }));
                }

                let raw_b_a = HazardDetector::detect_raw_a_to_b(node_b, node_a);
                if !raw_b_a.is_empty() {
                    let type_ids: Vec<u32> = raw_b_a.into_iter().collect();
                    return Err(CompilationError::Conflict(ConflictError {
                        system_a:   id_b.clone(),
                        system_b:   id_a.clone(),
                        conflicting_component_type_ids: type_ids.iter().copied().collect(),
                        description: format!(
                            "Parallel group '{}': RAW hazard — '{}' writes component(s) \
                             {:?} that '{}' reads.",
                            group_id, id_b, type_ids, id_a
                        ),
                    }));
                }
            }
        }
        Ok(())
    }

    fn non_deterministic_error(
        group_id:  &str,
        bad_sys:   &str,
        other_sys: &str,
    ) -> CompilationError {
        CompilationError::Conflict(ConflictError {
            system_a:   bad_sys.to_string(),
            system_b:   other_sys.to_string(),
            conflicting_component_type_ids: std::collections::BTreeSet::new(),
            description: format!(
                "Parallel group '{}': system '{}' is non-deterministic and cannot \
                 participate in parallel execution.",
                group_id, bad_sys
            ),
        })
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::runtime::execution_group::ExecutionGroup;
    use xace_core::runtime::execution_plan::{ExecutionPlan, PhaseSchedule};
    use xace_core::runtime::phase_enum::PhaseEnum;
    use xace_core::schema::system_definition::{ExecutionPhase, SystemDefinition, SystemVersion};
    use crate::graph_construction::graph_construction_layer::GraphConstructionLayer;
    use crate::phase_segmentation::phase_segmentation_layer::PhaseSegmentationLayer;
    use crate::dependency_resolution::dependency_resolution_engine::DependencyResolutionEngine;
    use crate::conflict_analyzer::conflict_analyzer::ConflictAnalyzer;
    use crate::scheduler::deterministic_scheduler_builder::{DeterministicSchedulerBuilder, PlanInspector};

    fn def(id: &str, reads: Vec<u32>, writes: Vec<u32>) -> SystemDefinition {
        SystemDefinition {
            id:            id.into(),
            display_name:  id.into(),
            phase:         ExecutionPhase::Simulation,
            reads,
            writes,
            depends_on:    vec![],
            deterministic: true,
            version:       SystemVersion::INITIAL,
            description:   String::new(),
        }
    }

    fn full_pipeline(
        defs: &[SystemDefinition],
    ) -> (ExecutionPlan, RawSystemGraph) {
        let graph   = GraphConstructionLayer::build(defs).unwrap();
        let buckets = PhaseSegmentationLayer::segment(&graph).unwrap();
        let ordered = DependencyResolutionEngine::resolve(&buckets).unwrap();
        let report  = ConflictAnalyzer::analyze(&buckets, &graph).unwrap();
        let plan    = DeterministicSchedulerBuilder::build(&ordered, &report, "0.1.0", 1);
        (plan, graph)
    }

    // ── Safe plans ────────────────────────────────────────────────────────────

    #[test]
    fn valid_serial_plan_passes() {
        let defs = vec![
            def("sys_a", vec![], vec![1]),
            def("sys_b", vec![], vec![1]), // WAW → serial
        ];
        let (plan, graph) = full_pipeline(&defs);
        assert!(ParallelizationSafetyModel::validate(&plan, &graph).is_ok());
    }

    #[test]
    fn valid_parallel_plan_passes() {
        let defs = vec![
            def("sys_a", vec![6],   vec![6]),
            def("sys_b", vec![100], vec![100]), // no conflict
        ];
        let (plan, graph) = full_pipeline(&defs);
        let parallel_count = PlanInspector::parallel_groups(&plan).len();
        assert!(parallel_count > 0, "Expected at least one parallel group");
        assert!(ParallelizationSafetyModel::validate(&plan, &graph).is_ok());
    }

    #[test]
    fn empty_plan_passes() {
        let (plan, graph) = full_pipeline(&[]);
        assert!(ParallelizationSafetyModel::validate(&plan, &graph).is_ok());
    }

    // ── Injected violations ───────────────────────────────────────────────────

    #[test]
    fn waw_in_parallel_group_rejected() {
        // Build graph with real nodes so SafetyModel can look them up.
        let defs = vec![
            def("sys_a", vec![], vec![1]),
            def("sys_b", vec![], vec![1]),
        ];
        let graph = GraphConstructionLayer::build(&defs).unwrap();

        // Manually inject a parallel group containing both conflicting systems.
        let bad_plan = ExecutionPlan::new(
            "0.1.0",
            1,
            0,
            "test_hash",
            vec![PhaseSchedule::new(
                PhaseEnum::Simulation,
                vec![ExecutionGroup {
                    parallel:                  true, // WRONG — these conflict on WAW
                    systems:                   vec!["sys_a".into(), "sys_b".into()],
                    group_id:                  "bad_parallel_group".into(),
                    phase:                     PhaseEnum::Simulation,
                    serialization_constraints: vec![],
                    execution_index:           0,
                }],
            )],
            "test_cgs_hash",
        );

        let result = ParallelizationSafetyModel::validate(&bad_plan, &graph);
        assert!(result.is_err(), "WAW conflict in parallel group must be rejected");
        assert!(result.unwrap_err().is_conflict());
    }

    #[test]
    fn raw_in_parallel_group_rejected() {
        let defs = vec![
            def("sys_writer", vec![],  vec![5]),
            def("sys_reader", vec![5], vec![]),
        ];
        let graph = GraphConstructionLayer::build(&defs).unwrap();

        let bad_plan = ExecutionPlan::new(
            "0.1.0",
            1,
            0,
            "test_hash",
            vec![PhaseSchedule::new(
                PhaseEnum::Simulation,
                vec![ExecutionGroup {
                    parallel:                  true, // WRONG — RAW hazard
                    systems:                   vec!["sys_reader".into(), "sys_writer".into()],
                    group_id:                  "bad_raw_group".into(),
                    phase:                     PhaseEnum::Simulation,
                    serialization_constraints: vec![],
                    execution_index:           0,
                }],
            )],
            "test_cgs_hash",
        );

        let result = ParallelizationSafetyModel::validate(&bad_plan, &graph);
        assert!(result.is_err(), "RAW hazard in parallel group must be rejected");
    }

    // ── Zombie chase ──────────────────────────────────────────────────────────

    #[test]
    fn zombie_chase_plan_passes_safety_model() {
        let defs = vec![
            def("InputSystem",    vec![6, 1],     vec![5]),
            def("MovementSystem", vec![5, 1],     vec![1]),
            def("AISystem",       vec![160, 1],   vec![5, 101]),
            def("DamageSystem",   vec![101, 100], vec![100, 101]),
            def("DeathSystem",    vec![100],       vec![]),
        ];
        let (plan, graph) = full_pipeline(&defs);
        assert!(
            ParallelizationSafetyModel::validate(&plan, &graph).is_ok(),
            "Zombie chase plan must pass parallelization safety validation"
        );
    }
}