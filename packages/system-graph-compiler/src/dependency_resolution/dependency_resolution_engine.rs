//! # Dependency Resolution Engine — SGC Stage 3
//!
//! Orchestrates the TopologicalSorter across all PhaseBuckets and
//! assembles the results into an OrderedGraph.
//!
//! ## Input → Output
//! Input:  Vec<PhaseBucket> from PhaseSegmentationLayer (phase ordinal order)
//! Output: OrderedGraph — per-phase sorted system lists, ready for scheduler
//!
//! ## Processing
//! Each PhaseBucket is sorted independently via TopologicalSorter (Kahn's).
//! The results are assembled in bucket order — same as phase ordinal order.
//!
//! ## Error Propagation
//! If any phase bucket contains a cycle, the engine returns the first
//! CompilationError::Cycle encountered. Buckets are processed in phase
//! ordinal order so the first failing phase is always reported.
//!
//! ## OrderedGraph
//! The OrderedGraph is the final output of Stage 3. It carries:
//! - An ordered Vec<String> of system IDs per phase
//! - The phase identity for each ordered list
//! - Aggregate metadata: total system count, phase count
//!
//! The ConflictAnalyzer (Stage 4) and Scheduler (Stage 5) both consume
//! the OrderedGraph to determine parallelization opportunities.

use crate::compilation_error::CompilationError;
use crate::dependency_resolution::topological_sorter::{SortedPhase, TopologicalSorter};
use crate::phase_segmentation::phase_segmentation_layer::PhaseBucket;
use xace_core::runtime::phase_enum::PhaseEnum;

// ── Ordered Phase ─────────────────────────────────────────────────────────────

/// One phase's systems in their topologically sorted execution order.
/// Produced by DependencyResolutionEngine for each PhaseBucket.
#[derive(Debug, Clone)]
pub struct OrderedPhase {
    /// The phase these systems belong to.
    pub phase: PhaseEnum,

    /// System IDs in deterministic topological order, tie-broken
    /// lexicographically (D11). Execute left to right.
    pub ordered_systems: Vec<String>,
}

impl OrderedPhase {
    /// Returns the position of a system in this phase's ordered list.
    /// Returns None if the system is not in this phase.
    pub fn position_of(&self, system_id: &str) -> Option<usize> {
        self.ordered_systems.iter().position(|s| s == system_id)
    }

    /// Returns true if system_a is ordered before system_b in this phase.
    /// Panics if either system is not in this phase.
    pub fn is_before(&self, system_a: &str, system_b: &str) -> bool {
        let pos_a = self
            .position_of(system_a)
            .unwrap_or_else(|| panic!("system '{}' not in phase {:?}", system_a, self.phase));
        let pos_b = self
            .position_of(system_b)
            .unwrap_or_else(|| panic!("system '{}' not in phase {:?}", system_b, self.phase));
        pos_a < pos_b
    }

    pub fn system_count(&self) -> usize {
        self.ordered_systems.len()
    }
}

// ── Ordered Graph ─────────────────────────────────────────────────────────────

/// The complete topologically-ordered system execution plan across all phases.
///
/// Produced by DependencyResolutionEngine. Consumed by:
/// - ConflictAnalyzer (Stage 4): detects parallel opportunities
/// - DeterministicSchedulerBuilder (Stage 5): assigns execution indices
#[derive(Debug, Clone)]
pub struct OrderedGraph {
    /// Per-phase ordered system lists, in phase ordinal order.
    /// Only phases with at least one system are included.
    pub phases: Vec<OrderedPhase>,
}

impl OrderedGraph {
    /// Returns the total number of systems across all phases.
    pub fn total_system_count(&self) -> usize {
        self.phases.iter().map(|p| p.system_count()).sum()
    }

    /// Returns the number of phases with at least one system.
    pub fn phase_count(&self) -> usize {
        self.phases.len()
    }

    /// Returns the OrderedPhase for the given phase, or None.
    pub fn phase(&self, phase: PhaseEnum) -> Option<&OrderedPhase> {
        self.phases.iter().find(|p| p.phase == phase)
    }

    /// Returns all system IDs across all phases in execution order.
    /// Phase ordinal order is preserved — Initialization systems first.
    pub fn all_systems_in_order(&self) -> Vec<&str> {
        self.phases
            .iter()
            .flat_map(|p| p.ordered_systems.iter().map(|s| s.as_str()))
            .collect()
    }

    /// Returns the global execution position of a system across all phases.
    /// Returns None if the system is not in any phase.
    pub fn global_position(&self, system_id: &str) -> Option<usize> {
        let mut offset = 0;
        for phase in &self.phases {
            if let Some(pos) = phase.position_of(system_id) {
                return Some(offset + pos);
            }
            offset += phase.system_count();
        }
        None
    }

    /// Returns all systems in the given phase in order, or empty slice.
    pub fn systems_in_phase(&self, phase: PhaseEnum) -> &[String] {
        self.phases
            .iter()
            .find(|p| p.phase == phase)
            .map(|p| p.ordered_systems.as_slice())
            .unwrap_or(&[])
    }
}

// ── Dependency Resolution Engine ──────────────────────────────────────────────

/// SGC Stage 3 — produces the OrderedGraph from phase buckets.
///
/// Stateless — one call to `resolve()` per compilation.
pub struct DependencyResolutionEngine;

impl DependencyResolutionEngine {
    /// Resolves topological ordering for all phase buckets.
    ///
    /// Processes buckets in phase ordinal order. Returns the first cycle
    /// error encountered, or Ok(OrderedGraph) if all phases are acyclic.
    pub fn resolve(buckets: &[PhaseBucket]) -> Result<OrderedGraph, CompilationError> {
        let mut phases: Vec<OrderedPhase> = Vec::with_capacity(buckets.len());

        for bucket in buckets {
            let sorted: SortedPhase = TopologicalSorter::sort(bucket)?;
            phases.push(OrderedPhase {
                phase: sorted.phase,
                ordered_systems: sorted.ordered_systems,
            });
        }

        Ok(OrderedGraph { phases })
    }

    /// Resolves and validates that all system_ids from the original graph
    /// appear in the ordered output. Used as a post-condition check.
    pub fn resolve_and_verify(
        buckets: &[PhaseBucket],
        expected_count: usize,
    ) -> Result<OrderedGraph, CompilationError> {
        let graph = Self::resolve(buckets)?;

        if graph.total_system_count() != expected_count {
            return Err(CompilationError::InternalError(format!(
                "DependencyResolutionEngine: expected {} systems in OrderedGraph \
                 but found {}. Some systems were lost during sorting.",
                expected_count,
                graph.total_system_count()
            )));
        }

        Ok(graph)
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::graph_construction::graph_construction_layer::GraphConstructionLayer;
    use crate::phase_segmentation::phase_segmentation_layer::PhaseSegmentationLayer;
    use xace_core::runtime::phase_enum::PhaseEnum;
    use xace_core::schema::system_definition::SystemDefinition;

    fn def(
        id: &str,
        phase: PhaseEnum,
        reads: Vec<u32>,
        writes: Vec<u32>,
        deps: Vec<&str>,
    ) -> SystemDefinition {
        let mut def = SystemDefinition::with_spec(id, id, phase.into(), reads, writes);
        def.depends_on = deps.into_iter().map(String::from).collect();
        def
    }

    fn resolve(defs: &[SystemDefinition]) -> Result<OrderedGraph, CompilationError> {
        let graph = GraphConstructionLayer::build(defs).unwrap();
        let buckets = PhaseSegmentationLayer::segment(&graph).unwrap();
        DependencyResolutionEngine::resolve(&buckets)
    }

    // ── Basic resolution ──────────────────────────────────────────────────────

    #[test]
    fn empty_input_produces_empty_graph() {
        let result = resolve(&[]).unwrap();
        assert_eq!(result.total_system_count(), 0);
        assert_eq!(result.phase_count(), 0);
    }

    #[test]
    fn single_system_resolved() {
        let defs = vec![def("sys_a", PhaseEnum::Simulation, vec![], vec![], vec![])];
        let graph = resolve(&defs).unwrap();
        assert_eq!(graph.total_system_count(), 1);
        assert_eq!(graph.phase_count(), 1);
        assert_eq!(graph.systems_in_phase(PhaseEnum::Simulation), &["sys_a"]);
    }

    #[test]
    fn multi_phase_all_systems_present() {
        let defs = vec![
            def(
                "sys_init",
                PhaseEnum::Initialization,
                vec![],
                vec![],
                vec![],
            ),
            def("sys_a", PhaseEnum::Simulation, vec![], vec![], vec![]),
            def("sys_b", PhaseEnum::Simulation, vec![], vec![], vec![]),
            def(
                "sys_post",
                PhaseEnum::PostSimulation,
                vec![],
                vec![],
                vec![],
            ),
        ];
        let graph = resolve(&defs).unwrap();
        assert_eq!(graph.total_system_count(), 4);
        assert_eq!(graph.phase_count(), 3);
    }

    // ── Phase ordering ────────────────────────────────────────────────────────

    #[test]
    fn phases_in_ordinal_order() {
        let defs = vec![
            def(
                "sys_post",
                PhaseEnum::PostSimulation,
                vec![],
                vec![],
                vec![],
            ),
            def(
                "sys_init",
                PhaseEnum::Initialization,
                vec![],
                vec![],
                vec![],
            ),
            def("sys_sim", PhaseEnum::Simulation, vec![], vec![], vec![]),
        ];
        let graph = resolve(&defs).unwrap();
        let ordinals: Vec<u8> = graph.phases.iter().map(|p| p.phase.as_u8()).collect();
        assert_eq!(ordinals, vec![0, 2, 3]); // Init=0, Sim=2, Post=3
    }

    // ── OrderedPhase API ──────────────────────────────────────────────────────

    #[test]
    fn position_of_returns_correct_index() {
        let defs = vec![
            def("sys_a", PhaseEnum::Simulation, vec![], vec![], vec![]),
            def(
                "sys_b",
                PhaseEnum::Simulation,
                vec![],
                vec![],
                vec!["sys_a"],
            ),
            def(
                "sys_c",
                PhaseEnum::Simulation,
                vec![],
                vec![],
                vec!["sys_b"],
            ),
        ];
        let graph = resolve(&defs).unwrap();
        let phase = graph.phase(PhaseEnum::Simulation).unwrap();
        assert_eq!(phase.position_of("sys_a"), Some(0));
        assert_eq!(phase.position_of("sys_b"), Some(1));
        assert_eq!(phase.position_of("sys_c"), Some(2));
        assert_eq!(phase.position_of("sys_ghost"), None);
    }

    #[test]
    fn is_before_correct() {
        let defs = vec![
            def("sys_a", PhaseEnum::Simulation, vec![], vec![], vec![]),
            def(
                "sys_b",
                PhaseEnum::Simulation,
                vec![],
                vec![],
                vec!["sys_a"],
            ),
        ];
        let graph = resolve(&defs).unwrap();
        let phase = graph.phase(PhaseEnum::Simulation).unwrap();
        assert!(phase.is_before("sys_a", "sys_b"));
        assert!(!phase.is_before("sys_b", "sys_a"));
    }

    // ── OrderedGraph API ──────────────────────────────────────────────────────

    #[test]
    fn global_position_cross_phase() {
        let defs = vec![
            def(
                "sys_init",
                PhaseEnum::Initialization,
                vec![],
                vec![],
                vec![],
            ),
            def("sys_a", PhaseEnum::Simulation, vec![], vec![], vec![]),
            def("sys_b", PhaseEnum::Simulation, vec![], vec![], vec![]),
        ];
        let graph = resolve(&defs).unwrap();
        // sys_init is at global position 0 (first in Initialization)
        assert_eq!(graph.global_position("sys_init"), Some(0));
        // sys_a and sys_b are at global positions 1 and 2
        let pos_a = graph.global_position("sys_a").unwrap();
        let pos_b = graph.global_position("sys_b").unwrap();
        assert!(pos_a >= 1 && pos_a <= 2);
        assert!(pos_b >= 1 && pos_b <= 2);
        assert_ne!(pos_a, pos_b);
    }

    #[test]
    fn all_systems_in_order_concatenates_phases() {
        let defs = vec![
            def(
                "sys_init",
                PhaseEnum::Initialization,
                vec![],
                vec![],
                vec![],
            ),
            def("sys_sim", PhaseEnum::Simulation, vec![], vec![], vec![]),
        ];
        let graph = resolve(&defs).unwrap();
        let all = graph.all_systems_in_order();
        assert_eq!(all.len(), 2);
        assert_eq!(all[0], "sys_init"); // Initialization first
        assert_eq!(all[1], "sys_sim"); // Simulation second
    }

    #[test]
    fn systems_in_phase_empty_for_absent_phase() {
        let defs = vec![def("sys_a", PhaseEnum::Simulation, vec![], vec![], vec![])];
        let graph = resolve(&defs).unwrap();
        assert!(graph.systems_in_phase(PhaseEnum::Initialization).is_empty());
        assert!(graph.systems_in_phase(PhaseEnum::Cleanup).is_empty());
    }

    // ── Stable ordering (D11) ─────────────────────────────────────────────────

    #[test]
    fn resolution_deterministic_across_input_orders() {
        let make_defs = |order: &[&str]| -> Vec<SystemDefinition> {
            order
                .iter()
                .map(|&id| def(id, PhaseEnum::Simulation, vec![], vec![], vec![]))
                .collect()
        };

        let order_1 = make_defs(&["sys_z", "sys_a", "sys_m", "sys_b"]);
        let order_2 = make_defs(&["sys_b", "sys_z", "sys_a", "sys_m"]);
        let order_3 = make_defs(&["sys_m", "sys_b", "sys_z", "sys_a"]);

        let g1 = resolve(&order_1).unwrap();
        let g2 = resolve(&order_2).unwrap();
        let g3 = resolve(&order_3).unwrap();

        let systems_1 = g1.systems_in_phase(PhaseEnum::Simulation);
        let systems_2 = g2.systems_in_phase(PhaseEnum::Simulation);
        let systems_3 = g3.systems_in_phase(PhaseEnum::Simulation);

        assert_eq!(
            systems_1, systems_2,
            "Resolution must be deterministic (D11)"
        );
        assert_eq!(
            systems_1, systems_3,
            "Resolution must be deterministic (D11)"
        );

        // Independent systems → pure lex order: sys_a, sys_b, sys_m, sys_z
        assert_eq!(systems_1, &["sys_a", "sys_b", "sys_m", "sys_z"]);
    }

    // ── Full pipeline: zombie chase ───────────────────────────────────────────

    #[test]
    fn zombie_chase_resolve_and_verify() {
        let defs = vec![
            def(
                "InputSystem",
                PhaseEnum::Simulation,
                vec![6, 1],
                vec![5],
                vec![],
            ),
            def(
                "MovementSystem",
                PhaseEnum::Simulation,
                vec![5, 1],
                vec![1],
                vec![],
            ),
            def(
                "AISystem",
                PhaseEnum::Simulation,
                vec![160, 1],
                vec![5, 101],
                vec![],
            ),
            def(
                "DamageSystem",
                PhaseEnum::Simulation,
                vec![101, 100],
                vec![100, 101],
                vec![],
            ),
            def(
                "DeathSystem",
                PhaseEnum::Simulation,
                vec![100],
                vec![],
                vec![],
            ),
        ];
        let graph = GraphConstructionLayer::build(&defs).unwrap();
        let buckets = PhaseSegmentationLayer::segment(&graph).unwrap();
        let ordered = DependencyResolutionEngine::resolve_and_verify(&buckets, 5).unwrap();

        assert_eq!(ordered.total_system_count(), 5);

        let sim = ordered.phase(PhaseEnum::Simulation).unwrap();

        // All RAW ordering constraints must be satisfied
        assert!(
            sim.is_before("AISystem", "MovementSystem"),
            "AISystem must precede MovementSystem (RAW: VELOCITY)"
        );
        assert!(
            sim.is_before("AISystem", "DamageSystem"),
            "AISystem must precede DamageSystem (RAW: DAMAGE)"
        );
        assert!(
            sim.is_before("DamageSystem", "DeathSystem"),
            "DamageSystem must precede DeathSystem (RAW: HEALTH)"
        );
    }

    // ── Cycle propagation ─────────────────────────────────────────────────────

    #[test]
    fn cycle_in_bucket_propagates_as_error() {
        use crate::graph_construction::system_edge::SystemEdge;
        use crate::graph_construction::system_node::SystemNode;
        use crate::phase_segmentation::phase_segmentation_layer::PhaseBucket;
        use std::collections::BTreeMap;

        // Hand-craft a cyclic bucket
        let bucket = PhaseBucket {
            phase: PhaseEnum::Simulation,
            nodes: {
                let mut m = BTreeMap::new();
                m.insert(
                    "sys_a".into(),
                    SystemNode::new("sys_a", PhaseEnum::Simulation),
                );
                m.insert(
                    "sys_b".into(),
                    SystemNode::new("sys_b", PhaseEnum::Simulation),
                );
                m
            },
            edges: {
                let mut m = BTreeMap::new();
                m.insert(
                    ("sys_a".into(), "sys_b".into()),
                    SystemEdge::explicit_dependency("sys_a", "sys_b"),
                );
                m.insert(
                    ("sys_b".into(), "sys_a".into()),
                    SystemEdge::explicit_dependency("sys_b", "sys_a"),
                );
                m
            },
        };

        let result = DependencyResolutionEngine::resolve(&[bucket]);
        assert!(result.is_err());
        assert!(result.unwrap_err().is_cycle());
    }
}
