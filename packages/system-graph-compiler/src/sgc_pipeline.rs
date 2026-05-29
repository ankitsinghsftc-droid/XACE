//! # SGC Pipeline — System Graph Compiler Entry Point
//!
//! Orchestrates all 7 SGC stages in order and returns an ExecutionPlan
//! or a CompilationError with full diagnostics.
//!
//! ## The 7 Stages (in pipeline order)
//! 1. **Graph Construction**    — SystemDefinitions → RawSystemGraph
//! 2. **Cycle Detection**       — DFS early abort before segmentation
//! 3. **Phase Segmentation**    — RawSystemGraph → Vec<PhaseBucket>
//! 4. **Dependency Resolution** — PhaseBuckets → OrderedGraph (Kahn's)
//! 5. **Conflict Analysis**     — OrderedGraph + Buckets → ConflictReport
//! 6. **Scheduling**            — OrderedGraph + Report → ExecutionPlan
//! 7. **Parallelization Safety**— ExecutionPlan validation pass
//!
//! ## Note on Cycle Detection Order
//! Cycle Detection (Stage 2) runs immediately after Graph Construction,
//! before segmentation. This provides richer DFS-based error messages
//! when a cycle is present. The Dependency Resolution stage (Stage 4)
//! also detects cycles via Kahn's algorithm as a fallback.

use xace_core::runtime::execution_plan::ExecutionPlan;
use xace_core::schema::system_definition::SystemDefinition;

use crate::compilation_error::CompilationError;
use crate::conflict_analyzer::conflict_analyzer::ConflictAnalyzer;
use crate::cycle_detection::cycle_detector::CycleDetector;
use crate::dependency_resolution::dependency_resolution_engine::DependencyResolutionEngine;
use crate::graph_construction::graph_construction_layer::GraphConstructionLayer;
use crate::parallelization::parallelization_safety_model::ParallelizationSafetyModel;
use crate::phase_segmentation::phase_segmentation_layer::PhaseSegmentationLayer;
use crate::scheduler::deterministic_scheduler_builder::DeterministicSchedulerBuilder;

// ── SGC Pipeline ──────────────────────────────────────────────────────────────

/// The System Graph Compiler entry point.
pub struct SgcPipeline;

impl SgcPipeline {
    /// Compiles a set of SystemDefinitions into an ExecutionPlan.
    pub fn compile(
        definitions: &[SystemDefinition],
        schema_version: &str,
        plan_version: u32,
    ) -> Result<ExecutionPlan, CompilationError> {
        // Stage 1: Graph Construction
        let graph = GraphConstructionLayer::build(definitions)?;

        // Stage 2: Cycle Detection (DFS — early abort with rich diagnostics)
        CycleDetector::detect_in_graph(&graph)?;

        // Stage 3: Phase Segmentation
        let buckets = PhaseSegmentationLayer::segment(&graph)?;

        // Stage 4: Dependency Resolution (Kahn's — per phase)
        let ordered = DependencyResolutionEngine::resolve(&buckets)?;

        // Stage 5: Conflict Analysis
        let report = ConflictAnalyzer::analyze(&buckets, &graph)?;

        // Stage 6: Scheduling
        let plan =
            DeterministicSchedulerBuilder::build(&ordered, &report, schema_version, plan_version);

        // Stage 7: Parallelization Safety
        ParallelizationSafetyModel::validate(&plan, &graph)?;

        Ok(plan)
    }

    /// Compiles with full post-condition verification.
    /// Confirms all systems from the input appear in the output plan.
    pub fn compile_and_verify(
        definitions: &[SystemDefinition],
        schema_version: &str,
        plan_version: u32,
    ) -> Result<ExecutionPlan, CompilationError> {
        let plan = Self::compile(definitions, schema_version, plan_version)?;

        let expected = definitions.len();
        let actual = plan.total_system_count();
        if actual != expected {
            return Err(CompilationError::InternalError(format!(
                "SgcPipeline verification: input {} systems but plan contains {}. \
                 System(s) lost in pipeline.",
                expected, actual
            )));
        }

        Ok(plan)
    }

    /// Returns a summary of what the pipeline would produce without
    /// building a full ExecutionPlan. Used for diagnostics and testing.
    pub fn dry_run(definitions: &[SystemDefinition]) -> Result<SgcSummary, CompilationError> {
        let graph = GraphConstructionLayer::build(definitions)?;
        CycleDetector::detect_in_graph(&graph)?;
        let buckets = PhaseSegmentationLayer::segment(&graph)?;
        let ordered = DependencyResolutionEngine::resolve(&buckets)?;
        let report = ConflictAnalyzer::analyze(&buckets, &graph)?;

        Ok(SgcSummary {
            total_systems: definitions.len(),
            active_phase_count: ordered.phase_count(),
            total_conflict_pairs: report.total_conflicts,
            constrained_group_count: report.constrained_group_count(),
            systems_per_phase: ordered
                .phases
                .iter()
                .map(|p| (p.phase.as_u8(), p.system_count()))
                .collect(),
        })
    }
}

// ── SGC Summary ───────────────────────────────────────────────────────────────

#[derive(Debug, Clone)]
pub struct SgcSummary {
    pub total_systems: usize,
    pub active_phase_count: usize,
    pub total_conflict_pairs: usize,
    pub constrained_group_count: usize,
    /// (phase_ordinal, system_count) pairs in phase ordinal order.
    pub systems_per_phase: Vec<(u8, usize)>,
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::graph_construction::system_node::SystemNode;
    use crate::scheduler::deterministic_scheduler_builder::PlanInspector;
    use xace_core::runtime::phase_enum::PhaseEnum;
    use xace_core::schema::system_definition::{ExecutionPhase, SystemDefinition, SystemVersion};

    fn def(
        id: &str,
        phase: ExecutionPhase,
        reads: Vec<u32>,
        writes: Vec<u32>,
        deps: Vec<&str>,
    ) -> SystemDefinition {
        SystemDefinition {
            id: id.into(),
            display_name: id.into(),
            phase,
            reads,
            writes,
            depends_on: deps.into_iter().map(String::from).collect(),
            deterministic: true,
            version: SystemVersion::INITIAL,
            description: String::new(),
        }
    }

    fn sim(id: &str, reads: Vec<u32>, writes: Vec<u32>) -> SystemDefinition {
        def(id, ExecutionPhase::Simulation, reads, writes, vec![])
    }

    // ── Happy path ────────────────────────────────────────────────────────────

    #[test]
    fn empty_definitions_compiles_to_empty_plan() {
        let plan = SgcPipeline::compile(&[], "0.1.0", 1).unwrap();
        assert_eq!(PlanInspector::total_system_count(&plan), 0);
    }

    #[test]
    fn single_system_compiles() {
        let defs = vec![sim("sys_a", vec![], vec![])];
        let plan = SgcPipeline::compile(&defs, "0.1.0", 1).unwrap();
        assert_eq!(PlanInspector::total_system_count(&plan), 1);
        assert_eq!(plan.schema_version, "0.1.0");
        assert_eq!(plan.plan_version, 1);
        assert_eq!(plan.plan_hash.len(), 64);
    }

    #[test]
    fn multi_phase_compiles() {
        let defs = vec![
            def(
                "sys_init",
                ExecutionPhase::Initialization,
                vec![],
                vec![],
                vec![],
            ),
            def(
                "sys_sim",
                ExecutionPhase::Simulation,
                vec![],
                vec![],
                vec![],
            ),
            def(
                "sys_post",
                ExecutionPhase::PostSimulation,
                vec![],
                vec![],
                vec![],
            ),
        ];
        let plan = SgcPipeline::compile(&defs, "0.1.0", 1).unwrap();
        assert_eq!(PlanInspector::total_system_count(&plan), 3);
    }

    // ── Error detection ───────────────────────────────────────────────────────

    #[test]
    fn duplicate_system_id_rejected() {
        let defs = vec![sim("sys_a", vec![], vec![]), sim("sys_a", vec![], vec![])];
        let err = SgcPipeline::compile(&defs, "0.1.0", 1).unwrap_err();
        assert!(matches!(err, CompilationError::InvalidDefinition(_)));
    }

    #[test]
    fn unknown_dependency_rejected() {
        let defs = vec![def(
            "sys_a",
            ExecutionPhase::Simulation,
            vec![],
            vec![],
            vec!["sys_ghost"],
        )];
        let err = SgcPipeline::compile(&defs, "0.1.0", 1).unwrap_err();
        assert!(matches!(err, CompilationError::InvalidDefinition(_)));
    }

    #[test]
    fn forward_phase_dependency_rejected() {
        // Manually build a graph with a forward dep to test segmentation error.
        let mut graph = crate::graph_construction::system_edge::RawSystemGraph::new();
        let mut sim_node = SystemNode::new("sys_sim", PhaseEnum::Simulation);
        sim_node.depends_on.insert("sys_post".into());
        graph.add_node(sim_node);
        graph.add_node(SystemNode::new("sys_post", PhaseEnum::PostSimulation));
        let result = PhaseSegmentationLayer::segment(&graph);
        assert!(result.is_err());
        assert!(result.unwrap_err().is_phase());
    }

    // ── Determinism (D11) ─────────────────────────────────────────────────────

    #[test]
    fn pipeline_deterministic_same_input_same_plan() {
        let defs = vec![
            sim("sys_movement", vec![5, 1], vec![1]),
            sim("sys_ai", vec![160, 1], vec![5]),
            sim("sys_damage", vec![101, 100], vec![100]),
        ];
        let plan_1 = SgcPipeline::compile(&defs, "0.1.0", 1).unwrap();
        let plan_2 = SgcPipeline::compile(&defs, "0.1.0", 1).unwrap();
        assert_eq!(
            plan_1.plan_hash, plan_2.plan_hash,
            "Same input must produce identical plan hash (D11)"
        );
        assert_eq!(
            PlanInspector::all_systems_in_order(&plan_1),
            PlanInspector::all_systems_in_order(&plan_2),
            "Same input must produce identical execution order (D11)"
        );
    }

    #[test]
    fn different_schema_versions_produce_different_hashes() {
        let defs = vec![sim("sys_a", vec![], vec![])];
        let plan_v1 = SgcPipeline::compile(&defs, "0.1.0", 1).unwrap();
        let plan_v2 = SgcPipeline::compile(&defs, "0.2.0", 1).unwrap();
        assert_ne!(plan_v1.plan_hash, plan_v2.plan_hash);
    }

    // ── Dry run ───────────────────────────────────────────────────────────────

    #[test]
    fn dry_run_returns_summary() {
        let defs = vec![
            sim("sys_a", vec![6], vec![6]),
            sim("sys_b", vec![100], vec![100]),
            sim("sys_c", vec![6], vec![6]), // WAW with sys_a
        ];
        let summary = SgcPipeline::dry_run(&defs).unwrap();
        assert_eq!(summary.total_systems, 3);
        assert_eq!(summary.active_phase_count, 1);
        assert!(summary.total_conflict_pairs > 0);
    }

    // ── Zombie chase full pipeline ────────────────────────────────────────────

    #[test]
    fn zombie_chase_full_pipeline() {
        let defs = vec![
            sim("InputSystem", vec![6, 1], vec![5]),
            sim("MovementSystem", vec![5, 1], vec![1]),
            sim("AISystem", vec![160, 1], vec![5, 101]),
            sim("DamageSystem", vec![101, 100], vec![100, 101]),
            sim("DeathSystem", vec![100], vec![]),
        ];

        let plan = SgcPipeline::compile_and_verify(&defs, "0.1.0", 1).unwrap();

        assert_eq!(PlanInspector::total_system_count(&plan), 5);
        assert_eq!(plan.schema_version, "0.1.0");
        assert!(!plan.plan_hash.is_empty());

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
        assert!(PlanInspector::is_before(
            &plan,
            "InputSystem",
            "MovementSystem"
        ));

        let plan_2 = SgcPipeline::compile_and_verify(&defs, "0.1.0", 1).unwrap();
        assert_eq!(
            plan.plan_hash, plan_2.plan_hash,
            "zombie chase plan hash must be identical across compilations (D11)"
        );
    }

    // ── Compile and verify ────────────────────────────────────────────────────

    #[test]
    fn compile_and_verify_succeeds() {
        let defs = vec![
            sim("sys_a", vec![], vec![]),
            sim("sys_b", vec![], vec![]),
            sim("sys_c", vec![], vec![]),
        ];
        let plan = SgcPipeline::compile_and_verify(&defs, "0.1.0", 1).unwrap();
        assert_eq!(PlanInspector::total_system_count(&plan), 3);
    }
}
