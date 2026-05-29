//! # Graph Construction Layer — SGC Stage 1
//!
//! Builds the RawSystemGraph from a flat list of SystemDefinitions.
//! This is the entry point of the SGC pipeline. Every subsequent
//! compiler stage consumes the RawSystemGraph produced here.
//!
//! ## What This Layer Does
//! 1. Validates: no empty system_ids, no duplicate ids, no unknown depends_on refs
//! 2. Builds one SystemNode per SystemDefinition
//! 3. Adds EXPLICIT_DEPENDENCY edges for all depends_on declarations
//! 4. Adds PHASE_ORDER edges for all cross-phase system pairs
//! 5. Calls HazardDetector for every (A, B) pair in the same phase:
//!    - RAW hazards → READ_AFTER_WRITE edges
//!    - WAW conflicts → WRITE_AFTER_WRITE edges (lexicographic tie-break)
//!
//! ## Edge Priority in RawSystemGraph
//! If multiple edge types apply to the same (from, to) pair, the graph
//! keeps only the highest-priority type. Priority order (highest first):
//!   EXPLICIT_DEPENDENCY > READ_AFTER_WRITE > WRITE_AFTER_WRITE > PHASE_ORDER
//! This is enforced by RawSystemGraph::add_edge().
//!
//! ## Phase Conversion
//! SystemDefinition.phase is ExecutionPhase (schema layer).
//! SystemNode.phase is PhaseEnum (runtime layer).
//! Both share identical u8 ordinals 0–4 — conversion via as_u8()/from_u8()
//! is infallible for valid ExecutionPhase values.
//!
//! ## Determinism (D11)
//! All iteration uses BTreeMap / BTreeSet sorted by system_id.
//! Same input SystemDefinitions in any order → identical RawSystemGraph.

use std::collections::{BTreeMap, BTreeSet};
use xace_core::runtime::phase_enum::PhaseEnum;
use xace_core::schema::system_definition::SystemDefinition;

use crate::compilation_error::{CompilationError, InvalidSystemDefinition};
use crate::graph_construction::hazard_detector::HazardDetector;
use crate::graph_construction::system_edge::{RawSystemGraph, SystemEdge};
use crate::graph_construction::system_node::SystemNode;

// ── Graph Construction Layer ──────────────────────────────────────────────────

/// SGC Stage 1 — builds the raw dependency graph from system definitions.
///
/// Stateless — one call to `build()` per compilation.
pub struct GraphConstructionLayer;

impl GraphConstructionLayer {
    /// Builds a RawSystemGraph from a slice of SystemDefinitions.
    ///
    /// ## Steps
    /// 1. Validate all definitions (empty ids, duplicates, unknown deps)
    /// 2. Build SystemNodes
    /// 3. Add EXPLICIT_DEPENDENCY edges
    /// 4. Add PHASE_ORDER edges for cross-phase pairs
    /// 5. Add RAW / WAW hazard edges for same-phase pairs
    ///
    /// Returns Err(CompilationError) if validation fails.
    /// Returns Ok(RawSystemGraph) on success.
    pub fn build(definitions: &[SystemDefinition]) -> Result<RawSystemGraph, CompilationError> {
        // Step 1: Validate
        Self::validate_definitions(definitions)?;

        // Step 2: Build nodes — BTreeMap<system_id, SystemNode> sorted (D11)
        let nodes: BTreeMap<String, SystemNode> = definitions
            .iter()
            .map(|def| {
                let node = Self::node_from_definition(def);
                (node.system_id.clone(), node)
            })
            .collect();

        let mut graph = RawSystemGraph::new();
        for node in nodes.values() {
            graph.add_node(node.clone());
        }

        // Sorted system_ids for deterministic pair iteration (D11)
        let system_ids: Vec<&str> = nodes.keys().map(|s| s.as_str()).collect();

        // Step 3: EXPLICIT_DEPENDENCY edges
        for node in nodes.values() {
            // depends_on is BTreeSet — sorted iteration (D11)
            for dep_id in &node.depends_on {
                // dep_id must run before this node
                graph.add_edge(SystemEdge::explicit_dependency(dep_id, &node.system_id));
            }
        }

        // Step 4 + 5: Process every (A, B) pair once
        // system_ids is already sorted — pairs are (i, j) with i < j (D11)
        for i in 0..system_ids.len() {
            for j in (i + 1)..system_ids.len() {
                let id_a = system_ids[i];
                let id_b = system_ids[j];
                let node_a = &nodes[id_a];
                let node_b = &nodes[id_b];

                if node_a.phase == node_b.phase {
                    // Same phase: detect RAW and WAW hazards
                    let report = HazardDetector::detect(node_a, node_b);
                    for edge in report.edges {
                        graph.add_edge(edge);
                    }
                } else {
                    // Cross-phase: add PHASE_ORDER edge from earlier to later
                    let (earlier, later) = Self::phase_order_pair(node_a, node_b);
                    graph.add_edge(SystemEdge::phase_order(
                        earlier.system_id.clone(),
                        later.system_id.clone(),
                    ));
                }
            }
        }

        Ok(graph)
    }

    // ── Internal ──────────────────────────────────────────────────────────────

    /// Validates all definitions before building the graph.
    /// Collects the first error found and returns it.
    fn validate_definitions(definitions: &[SystemDefinition]) -> Result<(), CompilationError> {
        // Build ID set for dependency validation
        let known_ids: BTreeSet<&str> = definitions.iter().map(|d| d.id.as_str()).collect();

        let mut seen_ids: BTreeSet<&str> = BTreeSet::new();

        for def in definitions {
            // No empty system_id
            if def.id.is_empty() {
                return Err(CompilationError::InvalidDefinition(
                    InvalidSystemDefinition::missing_id(),
                ));
            }

            // No duplicate system_ids
            if !seen_ids.insert(def.id.as_str()) {
                return Err(CompilationError::InvalidDefinition(
                    InvalidSystemDefinition {
                        system_id: def.id.clone(),
                        field: "id".into(),
                        reason: format!(
                            "Duplicate system_id '{}' — every system must have a unique id.",
                            def.id
                        ),
                    },
                ));
            }

            // All depends_on references must resolve to known systems
            for dep in &def.depends_on {
                if !known_ids.contains(dep.as_str()) {
                    return Err(CompilationError::InvalidDefinition(
                        InvalidSystemDefinition::unknown_dependency(&def.id, dep),
                    ));
                }
                // A system cannot depend on itself
                if dep == &def.id {
                    return Err(CompilationError::InvalidDefinition(
                        InvalidSystemDefinition {
                            system_id: def.id.clone(),
                            field: "depends_on".into(),
                            reason: format!(
                                "System '{}' lists itself in depends_on — \
                                 a system cannot depend on itself.",
                                def.id
                            ),
                        },
                    ));
                }
            }
        }
        Ok(())
    }

    /// Builds a SystemNode from a SystemDefinition.
    ///
    /// Converts ExecutionPhase (schema layer) → PhaseEnum (runtime layer).
    /// Both enums share identical u8 ordinals 0–4 — conversion is infallible
    /// for any valid ExecutionPhase value.
    fn node_from_definition(def: &SystemDefinition) -> SystemNode {
        // ExecutionPhase and PhaseEnum share the same ordinals (0=Init … 4=Cleanup).
        let phase = PhaseEnum::from_u8(def.phase.as_u8())
            .expect("ExecutionPhase ordinal always maps to a valid PhaseEnum");
        SystemNode::new(&def.id, phase)
            .with_reads(def.reads.iter().copied())
            .with_writes(def.writes.iter().copied())
            .with_depends_on(def.depends_on.iter().cloned())
            .with_version(def.version.major)
    }

    /// Returns (earlier_phase_node, later_phase_node) based on phase ordinal.
    fn phase_order_pair<'a>(
        a: &'a SystemNode,
        b: &'a SystemNode,
    ) -> (&'a SystemNode, &'a SystemNode) {
        if a.phase.as_u8() < b.phase.as_u8() {
            (a, b)
        } else {
            (b, a)
        }
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::compilation_error::EdgeType;
    use xace_core::schema::system_definition::{ExecutionPhase, SystemDefinition, SystemVersion};

    // ── Helpers ───────────────────────────────────────────────────────────────

    /// Builds a SystemDefinition with all required fields.
    fn def(
        id: &str,
        phase: ExecutionPhase,
        reads: Vec<u32>,
        writes: Vec<u32>,
        depends_on: Vec<&str>,
    ) -> SystemDefinition {
        SystemDefinition {
            id: id.into(),
            display_name: id.into(),
            phase,
            reads,
            writes,
            depends_on: depends_on.into_iter().map(String::from).collect(),
            deterministic: true,
            version: SystemVersion::INITIAL,
            description: String::new(),
        }
    }

    /// Shorthand: Simulation phase, no deps.
    fn sim(id: &str, reads: Vec<u32>, writes: Vec<u32>) -> SystemDefinition {
        def(id, ExecutionPhase::Simulation, reads, writes, vec![])
    }

    // ── Validation ────────────────────────────────────────────────────────────

    #[test]
    fn empty_definitions_builds_empty_graph() {
        let graph = GraphConstructionLayer::build(&[]).unwrap();
        assert_eq!(graph.node_count(), 0);
        assert_eq!(graph.edge_count(), 0);
    }

    #[test]
    fn single_system_no_edges() {
        let defs = vec![sim("sys_input", vec![6], vec![6])];
        let graph = GraphConstructionLayer::build(&defs).unwrap();
        assert_eq!(graph.node_count(), 1);
        assert_eq!(graph.edge_count(), 0);
    }

    #[test]
    fn empty_system_id_rejected() {
        let defs = vec![sim("", vec![], vec![])];
        let err = GraphConstructionLayer::build(&defs).unwrap_err();
        assert!(matches!(err, CompilationError::InvalidDefinition(_)));
    }

    #[test]
    fn duplicate_system_id_rejected() {
        let defs = vec![
            sim("sys_a", vec![], vec![]),
            sim("sys_a", vec![], vec![]), // duplicate
        ];
        let err = GraphConstructionLayer::build(&defs).unwrap_err();
        assert!(matches!(err, CompilationError::InvalidDefinition(_)));
    }

    #[test]
    fn unknown_dependency_rejected() {
        let defs = vec![def(
            "sys_a",
            ExecutionPhase::Simulation,
            vec![],
            vec![],
            vec!["sys_ghost"], // doesn't exist
        )];
        let err = GraphConstructionLayer::build(&defs).unwrap_err();
        assert!(matches!(err, CompilationError::InvalidDefinition(ref e)
            if e.reason.contains("sys_ghost")));
    }

    #[test]
    fn self_dependency_rejected() {
        let defs = vec![def(
            "sys_a",
            ExecutionPhase::Simulation,
            vec![],
            vec![],
            vec!["sys_a"], // self-reference
        )];
        assert!(GraphConstructionLayer::build(&defs).is_err());
    }

    // ── Node Construction ─────────────────────────────────────────────────────

    #[test]
    fn nodes_built_from_definitions() {
        let defs = vec![
            sim("sys_movement", vec![1, 5], vec![1]),
            sim("sys_ai", vec![160, 1], vec![5]),
        ];
        let graph = GraphConstructionLayer::build(&defs).unwrap();
        assert_eq!(graph.node_count(), 2);
        let movement_node = graph.nodes.get("sys_movement").unwrap();
        assert!(movement_node.reads(1));
        assert!(movement_node.writes(1));
        assert!(!movement_node.writes(5));
    }

    // ── Explicit Dependency Edges ─────────────────────────────────────────────

    #[test]
    fn explicit_dependency_edge_added() {
        let defs = vec![
            sim("sys_a", vec![], vec![]),
            def(
                "sys_b",
                ExecutionPhase::Simulation,
                vec![],
                vec![],
                vec!["sys_a"],
            ),
        ];
        let graph = GraphConstructionLayer::build(&defs).unwrap();
        let key = ("sys_a".to_string(), "sys_b".to_string());
        let edge = graph.edges.get(&key).expect("explicit dep edge must exist");
        assert_eq!(edge.edge_type, EdgeType::ExplicitDependency);
    }

    // ── RAW Edges ─────────────────────────────────────────────────────────────

    #[test]
    fn raw_edge_added_for_hazard() {
        let defs = vec![
            sim("sys_ai", vec![160], vec![5]),
            sim("sys_movement", vec![5], vec![1]),
        ];
        let graph = GraphConstructionLayer::build(&defs).unwrap();
        let key = ("sys_ai".to_string(), "sys_movement".to_string());
        let edge = graph.edges.get(&key).expect("RAW edge must exist");
        assert_eq!(edge.edge_type, EdgeType::ReadAfterWrite);
    }

    // ── WAW Edges ─────────────────────────────────────────────────────────────

    #[test]
    fn waw_edge_added_with_lex_tie_break() {
        let defs = vec![
            sim("sys_physics", vec![], vec![1]),
            sim("sys_movement", vec![], vec![1]),
        ];
        let graph = GraphConstructionLayer::build(&defs).unwrap();
        // sys_movement < sys_physics lex → sys_movement runs first
        let key = ("sys_movement".to_string(), "sys_physics".to_string());
        let edge = graph.edges.get(&key).expect("WAW edge must exist");
        assert_eq!(edge.edge_type, EdgeType::WriteAfterWrite);
    }

    // ── Phase Order Edges ─────────────────────────────────────────────────────

    #[test]
    fn phase_order_edge_added_for_cross_phase() {
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
        ];
        let graph = GraphConstructionLayer::build(&defs).unwrap();
        let key = ("sys_init".to_string(), "sys_sim".to_string());
        let edge = graph.edges.get(&key).expect("PhaseOrder edge must exist");
        assert_eq!(edge.edge_type, EdgeType::PhaseOrder);
    }

    #[test]
    fn no_same_phase_edge_between_independent_systems() {
        let defs = vec![
            sim("sys_input", vec![6], vec![6]),
            sim("sys_health", vec![100], vec![100]),
        ];
        let graph = GraphConstructionLayer::build(&defs).unwrap();
        assert_eq!(graph.edge_count(), 0, "No overlap = no edges");
    }

    // ── Determinism (D11) ─────────────────────────────────────────────────────

    #[test]
    fn graph_deterministic_regardless_of_input_order() {
        let defs_order1 = vec![
            sim("sys_movement", vec![1, 5], vec![1]),
            sim("sys_ai", vec![160, 1], vec![5]),
            sim("sys_damage", vec![101, 100], vec![100]),
        ];
        let defs_order2 = vec![
            sim("sys_damage", vec![101, 100], vec![100]),
            sim("sys_movement", vec![1, 5], vec![1]),
            sim("sys_ai", vec![160, 1], vec![5]),
        ];

        let graph1 = GraphConstructionLayer::build(&defs_order1).unwrap();
        let graph2 = GraphConstructionLayer::build(&defs_order2).unwrap();

        assert_eq!(graph1.node_count(), graph2.node_count());
        assert_eq!(graph1.edge_count(), graph2.edge_count());

        let ids1 = graph1.system_ids();
        let ids2 = graph2.system_ids();
        assert_eq!(ids1, ids2, "Node order must be deterministic (D11)");

        let edges1: Vec<_> = graph1.edges.keys().collect();
        let edges2: Vec<_> = graph2.edges.keys().collect();
        assert_eq!(edges1, edges2, "Edge order must be deterministic (D11)");
    }

    // ── Explicit Beats Phase Order ────────────────────────────────────────────

    #[test]
    fn explicit_dependency_beats_phase_order_for_same_pair() {
        let defs = vec![
            def(
                "sys_init",
                ExecutionPhase::Initialization,
                vec![],
                vec![],
                vec![],
            ),
            def(
                "sys_a",
                ExecutionPhase::Simulation,
                vec![],
                vec![],
                vec!["sys_init"],
            ),
        ];
        let graph = GraphConstructionLayer::build(&defs).unwrap();
        let key = ("sys_init".to_string(), "sys_a".to_string());
        let edge = graph.edges.get(&key).unwrap();
        assert_eq!(
            edge.edge_type,
            EdgeType::ExplicitDependency,
            "ExplicitDependency must beat PhaseOrder for same (from, to) pair"
        );
    }

    // ── Full Zombie Chase Scenario ────────────────────────────────────────────

    #[test]
    fn zombie_chase_systems_produce_correct_graph() {
        let defs = vec![
            def(
                "InputSystem",
                ExecutionPhase::Simulation,
                vec![6, 1],
                vec![5],
                vec![],
            ),
            def(
                "MovementSystem",
                ExecutionPhase::Simulation,
                vec![5, 1],
                vec![1],
                vec![],
            ),
            def(
                "AISystem",
                ExecutionPhase::Simulation,
                vec![160, 1],
                vec![5, 101],
                vec![],
            ),
            def(
                "DamageSystem",
                ExecutionPhase::Simulation,
                vec![101, 100],
                vec![100, 101],
                vec![],
            ),
            def(
                "DeathSystem",
                ExecutionPhase::Simulation,
                vec![100],
                vec![],
                vec![],
            ),
        ];
        let graph = GraphConstructionLayer::build(&defs).unwrap();
        assert_eq!(graph.node_count(), 5);

        let raw_key = ("InputSystem".to_string(), "MovementSystem".to_string());
        assert!(
            graph.edges.contains_key(&raw_key),
            "InputSystem must precede MovementSystem (RAW: VELOCITY)"
        );

        let raw_key2 = ("AISystem".to_string(), "MovementSystem".to_string());
        assert!(
            graph.edges.contains_key(&raw_key2),
            "AISystem must precede MovementSystem (RAW: VELOCITY)"
        );

        let waw_key = ("AISystem".to_string(), "InputSystem".to_string());
        assert!(
            graph.edges.contains_key(&waw_key),
            "AISystem and InputSystem WAW on VELOCITY must be serialized"
        );
    }
}
