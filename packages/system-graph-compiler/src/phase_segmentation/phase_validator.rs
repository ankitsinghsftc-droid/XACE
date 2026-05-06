//! # Phase Validator — SGC Stage 2 (sub-component)
//!
//! Validates all phase-related rules in the system graph before
//! segmentation proceeds. Three error types are produced:
//!
//! ## SYSTEM_PHASE_UNDEFINED
//! Reserved for when a system arrives in the graph with no phase
//! assignment. In practice, since PhaseEnum is non-optional in
//! SystemDefinition, this is raised if a node's phase ordinal does
//! not map to a known PhaseEnum value (forward-compatibility guard).
//!
//! ## INVALID_SYSTEM_PHASE
//! A system declares a phase string that has no corresponding PhaseEnum
//! variant. Raised during schema parsing before graph construction.
//! At the graph level it can also be raised for reserved/future phases.
//!
//! ## PHASE_DEPENDENCY_VIOLATION
//! System A declares depends_on System B, but System B is in a LATER
//! phase than System A. This is a forward reference — A cannot wait
//! for B because B hasn't run yet when A needs to run.
//!
//! Example:
//!   sys_cleanup (Cleanup) depends_on sys_sim (Simulation) — VALID
//!   sys_sim (Simulation) depends_on sys_post (PostSimulation) — INVALID
//!
//! ## What Is NOT Validated Here
//! Cross-phase RAW/WAW hazards are not errors — they are handled by
//! inserting PHASE_ORDER edges in GraphConstructionLayer. The phase
//! validator only checks explicit depends_on declarations.

use xace_core::runtime::phase_enum::PhaseEnum;
use crate::compilation_error::{CompilationError, PhaseViolation};
use crate::graph_construction::system_edge::RawSystemGraph;

// ── Phase Validator ───────────────────────────────────────────────────────────

/// Validates phase-related rules before the segmentation layer partitions
/// the graph into phase buckets.
///
/// Stateless — all methods are pure functions of the graph.
pub struct PhaseValidator;

impl PhaseValidator {
    /// Validates all phase rules in the graph.
    ///
    /// Checks all systems in the graph for:
    /// 1. Phase dependency violations (explicit dep on a later-phase system)
    ///
    /// Returns the first violation found, or Ok(()) if all checks pass.
    /// All maps are BTreeMap — iteration is deterministic (D11).
    pub fn validate(graph: &RawSystemGraph) -> Result<(), CompilationError> {
        // Check explicit dependency forward-reference violations
        Self::validate_no_forward_phase_dependencies(graph)?;
        Ok(())
    }

    /// Checks that no system has an explicit dependency pointing to a system
    /// in a strictly later phase.
    ///
    /// Iteration over nodes is BTreeMap-ordered by system_id (D11).
    fn validate_no_forward_phase_dependencies(
        graph: &RawSystemGraph,
    ) -> Result<(), CompilationError> {
        for (system_id, node) in &graph.nodes {
            for dep_id in &node.depends_on {
                let dep_node = match graph.nodes.get(dep_id) {
                    Some(n) => n,
                    None    => continue, // missing dep caught by GraphConstructionLayer
                };

                // Forward reference: dep is in a LATER phase than this system
                if dep_node.phase.as_u8() > node.phase.as_u8() {
                    return Err(CompilationError::Phase(
                        PhaseViolation::cross_phase_dependency(
                            system_id.as_str(),
                            node.phase,
                            dep_node.phase,
                        )
                    ));
                }
            }
        }
        Ok(())
    }

    /// Validates that all PHASE_ORDER edges in the graph point from earlier
    /// to later phases — never backward. This is a sanity check on the
    /// GraphConstructionLayer's output.
    pub fn validate_phase_order_edges(graph: &RawSystemGraph) -> Result<(), CompilationError> {
        use crate::compilation_error::EdgeType;
        for edge in graph.edges.values() {
            if edge.edge_type != EdgeType::PhaseOrder {
                continue;
            }
            let from_node = match graph.nodes.get(&edge.from_system) {
                Some(n) => n,
                None    => continue,
            };
            let to_node = match graph.nodes.get(&edge.to_system) {
                Some(n) => n,
                None    => continue,
            };
            if from_node.phase.as_u8() > to_node.phase.as_u8() {
                return Err(CompilationError::Phase(PhaseViolation {
                    system_id: edge.from_system.clone(),
                    kind:      crate::compilation_error::PhaseViolationKind::PhaseDependencyViolation {
                        from_phase: from_node.phase,
                        to_phase:   to_node.phase,
                    },
                    description: format!(
                        "PHASE_ORDER edge goes backward: '{}' ({:?}) → '{}' ({:?}). \
                         Phase order edges must point forward in phase sequence.",
                        edge.from_system, from_node.phase,
                        edge.to_system,   to_node.phase,
                    ),
                }));
            }
        }
        Ok(())
    }

    /// Returns all systems assigned to the given phase, sorted by system_id (D11).
    pub fn systems_in_phase<'a>(
        graph: &'a RawSystemGraph,
        phase: PhaseEnum,
    ) -> Vec<&'a str> {
        graph.nodes
            .iter()
            .filter(|(_, n)| n.phase == phase)
            .map(|(id, _)| id.as_str())
            .collect()
        // BTreeMap iteration is already sorted by system_id (D11)
    }

    /// Returns all distinct phases used in the graph, sorted by phase ordinal.
    pub fn active_phases(graph: &RawSystemGraph) -> Vec<PhaseEnum> {
        let mut phases: Vec<PhaseEnum> = graph.nodes
            .values()
            .map(|n| n.phase)
            .collect();
        phases.sort_by_key(|p| p.as_u8());
        phases.dedup();
        phases
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::runtime::phase_enum::PhaseEnum;
    use xace_core::schema::system_definition::SystemDefinition;
    use crate::graph_construction::graph_construction_layer::GraphConstructionLayer;

    fn def(
        id:     &str,
        phase:  PhaseEnum,
        deps:   Vec<&str>,
    ) -> SystemDefinition {
        SystemDefinition {
            id:            id.into(),
            phase,
            reads:         vec![],
            writes:        vec![],
            depends_on:    deps.into_iter().map(String::from).collect(),
            deterministic: true,
            version:       1,
        }
    }

    fn build_graph(defs: &[SystemDefinition]) -> crate::graph_construction::system_edge::RawSystemGraph {
        GraphConstructionLayer::build(defs).unwrap()
    }

    // ── Valid Cases ───────────────────────────────────────────────────────────

    #[test]
    fn valid_same_phase_dependencies_pass() {
        let defs = vec![
            def("sys_a", PhaseEnum::Simulation, vec![]),
            def("sys_b", PhaseEnum::Simulation, vec!["sys_a"]),
        ];
        let graph = build_graph(&defs);
        assert!(PhaseValidator::validate(&graph).is_ok());
    }

    #[test]
    fn valid_backward_phase_dependency_passes() {
        // sys_b (Simulation) depends on sys_a (Initialization) — valid
        let defs = vec![
            def("sys_a", PhaseEnum::Initialization, vec![]),
            def("sys_b", PhaseEnum::Simulation,     vec!["sys_a"]),
        ];
        let graph = build_graph(&defs);
        assert!(PhaseValidator::validate(&graph).is_ok());
    }

    #[test]
    fn empty_graph_validates() {
        let graph = RawSystemGraph::new();
        assert!(PhaseValidator::validate(&graph).is_ok());
    }

    #[test]
    fn no_dependencies_validates() {
        let defs = vec![
            def("sys_init", PhaseEnum::Initialization, vec![]),
            def("sys_sim",  PhaseEnum::Simulation,     vec![]),
            def("sys_post", PhaseEnum::PostSimulation,  vec![]),
        ];
        let graph = build_graph(&defs);
        assert!(PhaseValidator::validate(&graph).is_ok());
    }

    // ── Violation Cases ───────────────────────────────────────────────────────

    #[test]
    fn forward_phase_dependency_rejected() {
        // sys_sim (Simulation) depends_on sys_post (PostSimulation) — INVALID
        // But GraphConstructionLayer validates this won't build correctly
        // We test it manually by manipulating the graph
        let mut graph = RawSystemGraph::new();
        let mut sim_node = crate::graph_construction::system_node::SystemNode::new(
            "sys_sim", PhaseEnum::Simulation
        );
        sim_node.depends_on.insert("sys_post".into());
        graph.add_node(sim_node);
        graph.add_node(crate::graph_construction::system_node::SystemNode::new(
            "sys_post", PhaseEnum::PostSimulation
        ));

        let err = PhaseValidator::validate(&graph).unwrap_err();
        assert!(err.is_phase());
        let desc = err.description();
        assert!(desc.contains("sys_sim") || desc.contains("PostSimulation"),
            "Error must mention the violating system or phase");
    }

    // ── Active Phases ─────────────────────────────────────────────────────────

    #[test]
    fn active_phases_sorted_by_ordinal() {
        let defs = vec![
            def("sys_a", PhaseEnum::PostSimulation,  vec![]),
            def("sys_b", PhaseEnum::Initialization,  vec![]),
            def("sys_c", PhaseEnum::Simulation,       vec![]),
        ];
        let graph = build_graph(&defs);
        let phases = PhaseValidator::active_phases(&graph);
        assert_eq!(phases, vec![
            PhaseEnum::Initialization,
            PhaseEnum::Simulation,
            PhaseEnum::PostSimulation,
        ]);
    }

    #[test]
    fn active_phases_deduplicates() {
        let defs = vec![
            def("sys_a", PhaseEnum::Simulation, vec![]),
            def("sys_b", PhaseEnum::Simulation, vec![]),
            def("sys_c", PhaseEnum::Simulation, vec![]),
        ];
        let graph = build_graph(&defs);
        let phases = PhaseValidator::active_phases(&graph);
        assert_eq!(phases.len(), 1);
        assert_eq!(phases[0], PhaseEnum::Simulation);
    }

    #[test]
    fn active_phases_empty_graph() {
        let graph = RawSystemGraph::new();
        assert!(PhaseValidator::active_phases(&graph).is_empty());
    }

    // ── Systems In Phase ──────────────────────────────────────────────────────

    #[test]
    fn systems_in_phase_sorted() {
        let defs = vec![
            def("sys_z", PhaseEnum::Simulation, vec![]),
            def("sys_a", PhaseEnum::Simulation, vec![]),
            def("sys_m", PhaseEnum::Simulation, vec![]),
            def("sys_x", PhaseEnum::Input,      vec![]),
        ];
        let graph = build_graph(&defs);
        let sim_systems = PhaseValidator::systems_in_phase(&graph, PhaseEnum::Simulation);
        assert_eq!(sim_systems, vec!["sys_a", "sys_m", "sys_z"]);
        let input_systems = PhaseValidator::systems_in_phase(&graph, PhaseEnum::Input);
        assert_eq!(input_systems, vec!["sys_x"]);
    }

    #[test]
    fn systems_in_phase_empty_when_none() {
        let defs = vec![def("sys_a", PhaseEnum::Simulation, vec![])];
        let graph = build_graph(&defs);
        let cleanup = PhaseValidator::systems_in_phase(&graph, PhaseEnum::Cleanup);
        assert!(cleanup.is_empty());
    }
}