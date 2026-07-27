//! # Phase Segmentation Layer — SGC Stage 2
//!
//! Partitions the RawSystemGraph into PhaseBuckets — one per active phase.
//! Each PhaseBucket contains only the nodes and edges that belong to that
//! phase, with all cross-phase edges removed.
//!
//! ## Why Segmentation
//! The topological sorter (Stage 3) works within a single phase at a time.
//! Systems in Simulation cannot be topologically ordered relative to systems
//! in Initialization — they run at completely different times. Segmentation
//! isolates each phase so Kahn's algorithm only sees the relevant subgraph.
//!
//! ## What Gets Filtered
//! PHASE_ORDER edges are removed from each phase bucket — they only carry
//! the global phase ordering guarantee, which is already encoded by
//! processing buckets in phase ordinal order.
//!
//! EXPLICIT_DEPENDENCY, READ_AFTER_WRITE, and WRITE_AFTER_WRITE edges
//! within the same phase are retained in the bucket.
//!
//! Cross-phase explicit dependencies (sys_b depends_on sys_a where sys_a
//! is in an earlier phase) are also excluded from the bucket — by the time
//! the topological sorter runs on phase N's bucket, all systems in earlier
//! phases have already been assigned their execution index.
//!
//! ## Bucket Ordering
//! PhaseBuckets are returned in phase ordinal order:
//! Initialization(0) → Input(1) → Simulation(2) → PostSimulation(3) → Cleanup(4)
//! Empty phases are omitted.
//!
//! ## Determinism (D11)
//! All BTreeMaps in PhaseBucket are keyed by system_id / (from, to) pairs.
//! Same RawSystemGraph → identical PhaseBuckets, always.

use crate::compilation_error::{CompilationError, EdgeType};
use crate::graph_construction::system_edge::{RawSystemGraph, SystemEdge};
use crate::graph_construction::system_node::SystemNode;
use crate::phase_segmentation::phase_validator::PhaseValidator;
use std::collections::BTreeMap;
use xace_core::runtime::phase_enum::PhaseEnum;

// ── Phase Bucket ──────────────────────────────────────────────────────────────

/// One phase's portion of the system dependency graph.
///
/// Contains only the nodes and intra-phase edges for this phase.
/// Consumed by the DependencyResolutionEngine (Stage 3).
#[derive(Debug)]
pub struct PhaseBucket {
    /// The phase this bucket represents.
    pub phase: PhaseEnum,

    /// Systems in this phase, keyed by system_id ascending (D11).
    pub nodes: BTreeMap<String, SystemNode>,

    /// Intra-phase ordering edges, keyed by (from, to) ascending (D11).
    /// PHASE_ORDER edges and cross-phase edges are excluded.
    pub edges: BTreeMap<(String, String), SystemEdge>,
}

impl PhaseBucket {
    fn new(phase: PhaseEnum) -> Self {
        Self {
            phase,
            nodes: BTreeMap::new(),
            edges: BTreeMap::new(),
        }
    }

    /// Returns the number of systems in this phase.
    pub fn system_count(&self) -> usize {
        self.nodes.len()
    }

    /// Returns the number of intra-phase ordering edges.
    pub fn edge_count(&self) -> usize {
        self.edges.len()
    }

    /// Returns true if this phase has no systems.
    pub fn is_empty(&self) -> bool {
        self.nodes.is_empty()
    }

    /// Returns all system IDs in this phase, sorted ascending (D11).
    pub fn system_ids(&self) -> Vec<&str> {
        self.nodes.keys().map(|s| s.as_str()).collect()
    }

    /// Returns all edges originating from the given system_id.
    pub fn edges_from(&self, system_id: &str) -> Vec<&SystemEdge> {
        self.edges
            .iter()
            .filter(|((from, _), _)| from == system_id)
            .map(|(_, e)| e)
            .collect()
    }

    /// Returns in-degree of each node (number of edges pointing TO it).
    /// Used by Kahn's algorithm in the topological sorter.
    /// Returns BTreeMap<system_id, in_degree> sorted (D11).
    pub fn in_degree_map(&self) -> BTreeMap<String, usize> {
        let mut degrees: BTreeMap<String, usize> =
            self.nodes.keys().map(|id| (id.clone(), 0usize)).collect();

        for ((_from, to), _) in &self.edges {
            *degrees.entry(to.clone()).or_insert(0) += 1;
        }
        degrees
    }
}

// ── Phase Segmentation Layer ──────────────────────────────────────────────────

/// SGC Stage 2 — partitions the RawSystemGraph into per-phase subgraphs.
///
/// Stateless — one call to `segment()` per compilation.
pub struct PhaseSegmentationLayer;

impl PhaseSegmentationLayer {
    /// Partitions the RawSystemGraph into PhaseBuckets.
    ///
    /// Steps:
    /// 1. Run PhaseValidator — fail on phase violations
    /// 2. Determine active phases in ordinal order
    /// 3. For each phase: collect nodes and intra-phase non-PHASE_ORDER edges
    /// 4. Return buckets in phase ordinal order (empty phases omitted)
    pub fn segment(graph: &RawSystemGraph) -> Result<Vec<PhaseBucket>, CompilationError> {
        // Step 1: Validate phase rules
        PhaseValidator::validate(graph)?;

        // Step 2: Collect active phases in ordinal order
        let active_phases = PhaseValidator::active_phases(graph);
        if active_phases.is_empty() {
            return Ok(Vec::new());
        }

        // Step 3: Build one bucket per active phase
        let buckets: Vec<PhaseBucket> = active_phases
            .into_iter()
            .map(|phase| {
                let mut bucket = PhaseBucket::new(phase);

                // Add nodes in this phase (BTreeMap → sorted by system_id, D11)
                for (id, node) in &graph.nodes {
                    if node.phase == phase {
                        bucket.nodes.insert(id.clone(), node.clone());
                    }
                }

                // Add intra-phase edges — exclude PHASE_ORDER and cross-phase edges
                for ((from, to), edge) in &graph.edges {
                    if edge.edge_type == EdgeType::PhaseOrder {
                        continue; // Phase order is handled by bucket order, not edges
                    }
                    let from_in_phase = bucket.nodes.contains_key(from.as_str());
                    let to_in_phase = bucket.nodes.contains_key(to.as_str());
                    if from_in_phase && to_in_phase {
                        bucket
                            .edges
                            .insert((from.clone(), to.clone()), edge.clone());
                    }
                    // Cross-phase explicit dependencies: the earlier phase already
                    // completed by the time this phase runs — no edge needed here.
                }

                bucket
            })
            .filter(|b| !b.is_empty()) // omit phases with no systems
            .collect();

        Ok(buckets)
    }

    /// Returns a summary of how many systems are in each phase.
    /// Useful for diagnostics. BTreeMap<phase_ordinal, count> sorted (D11).
    pub fn phase_summary(graph: &RawSystemGraph) -> BTreeMap<u8, usize> {
        let mut summary: BTreeMap<u8, usize> = BTreeMap::new();
        for node in graph.nodes.values() {
            *summary.entry(node.phase.as_u8()).or_insert(0) += 1;
        }
        summary
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::compilation_error::EdgeType;
    use crate::graph_construction::graph_construction_layer::GraphConstructionLayer;
    use xace_core::runtime::phase_enum::PhaseEnum;
    use xace_core::schema::system_definition::{SystemDefinition, SystemVersion};

    fn def(
        id: &str,
        phase: PhaseEnum,
        reads: Vec<u32>,
        writes: Vec<u32>,
        deps: Vec<&str>,
    ) -> SystemDefinition {
        SystemDefinition {
            id: id.into(),
            display_name: id.into(),
            phase: phase.into(),
            reads,
            writes,
            depends_on: deps.into_iter().map(String::from).collect(),
            deterministic: true,
            version: SystemVersion::INITIAL,
            description: String::new(),
        }
    }

    fn sim(id: &str) -> SystemDefinition {
        def(id, PhaseEnum::Simulation, vec![], vec![], vec![])
    }

    fn segment(defs: &[SystemDefinition]) -> Vec<PhaseBucket> {
        let graph = GraphConstructionLayer::build(defs).unwrap();
        PhaseSegmentationLayer::segment(&graph).unwrap()
    }

    // ── Basic Segmentation ────────────────────────────────────────────────────

    #[test]
    fn empty_graph_produces_no_buckets() {
        let buckets = segment(&[]);
        assert!(buckets.is_empty());
    }

    #[test]
    fn single_phase_produces_one_bucket() {
        let defs = vec![sim("sys_a"), sim("sys_b"), sim("sys_c")];
        let buckets = segment(&defs);
        assert_eq!(buckets.len(), 1);
        assert_eq!(buckets[0].phase, PhaseEnum::Simulation);
        assert_eq!(buckets[0].system_count(), 3);
    }

    #[test]
    fn multiple_phases_produce_multiple_buckets() {
        let defs = vec![
            def(
                "sys_init",
                PhaseEnum::Initialization,
                vec![],
                vec![],
                vec![],
            ),
            def("sys_sim", PhaseEnum::Simulation, vec![], vec![], vec![]),
            def(
                "sys_post",
                PhaseEnum::PostSimulation,
                vec![],
                vec![],
                vec![],
            ),
        ];
        let buckets = segment(&defs);
        assert_eq!(buckets.len(), 3);
        assert_eq!(buckets[0].phase, PhaseEnum::Initialization);
        assert_eq!(buckets[1].phase, PhaseEnum::Simulation);
        assert_eq!(buckets[2].phase, PhaseEnum::PostSimulation);
    }

    #[test]
    fn buckets_in_phase_ordinal_order() {
        // Definitions in arbitrary order — buckets must be sorted by phase ordinal
        let defs = vec![
            def(
                "sys_post",
                PhaseEnum::PostSimulation,
                vec![],
                vec![],
                vec![],
            ),
            def("sys_cleanup", PhaseEnum::Cleanup, vec![], vec![], vec![]),
            def(
                "sys_init",
                PhaseEnum::Initialization,
                vec![],
                vec![],
                vec![],
            ),
            def("sys_input", PhaseEnum::Input, vec![], vec![], vec![]),
            def("sys_sim", PhaseEnum::Simulation, vec![], vec![], vec![]),
        ];
        let buckets = segment(&defs);
        assert_eq!(buckets.len(), 5);
        let ordinals: Vec<u8> = buckets.iter().map(|b| b.phase.as_u8()).collect();
        assert_eq!(ordinals, vec![0, 1, 2, 3, 4]);
    }

    #[test]
    fn empty_phases_omitted() {
        // Only Initialization and Cleanup used — Input, Simulation, PostSimulation empty
        let defs = vec![
            def(
                "sys_init",
                PhaseEnum::Initialization,
                vec![],
                vec![],
                vec![],
            ),
            def("sys_cleanup", PhaseEnum::Cleanup, vec![], vec![], vec![]),
        ];
        let buckets = segment(&defs);
        assert_eq!(buckets.len(), 2);
        assert_eq!(buckets[0].phase, PhaseEnum::Initialization);
        assert_eq!(buckets[1].phase, PhaseEnum::Cleanup);
    }

    // ── Edge Filtering ────────────────────────────────────────────────────────

    #[test]
    fn phase_order_edges_excluded_from_buckets() {
        // sys_init (Initialization) and sys_sim (Simulation) get a PHASE_ORDER edge
        // but it must NOT appear in either bucket's edge set
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
        let buckets = segment(&defs);
        for bucket in &buckets {
            for edge in bucket.edges.values() {
                assert_ne!(
                    edge.edge_type,
                    EdgeType::PhaseOrder,
                    "PHASE_ORDER edges must never appear in phase buckets"
                );
            }
        }
    }

    #[test]
    fn intra_phase_raw_edges_retained_in_bucket() {
        // sys_ai writes VELOCITY(5), sys_movement reads VELOCITY(5) — same phase
        let defs = vec![
            def("sys_ai", PhaseEnum::Simulation, vec![160], vec![5], vec![]),
            def(
                "sys_movement",
                PhaseEnum::Simulation,
                vec![5],
                vec![1],
                vec![],
            ),
        ];
        let buckets = segment(&defs);
        assert_eq!(buckets.len(), 1);
        let bucket = &buckets[0];
        // Edge sys_ai → sys_movement must be in the bucket
        let key = ("sys_ai".to_string(), "sys_movement".to_string());
        assert!(
            bucket.edges.contains_key(&key),
            "RAW edge must be retained in phase bucket"
        );
        assert_eq!(bucket.edges[&key].edge_type, EdgeType::ReadAfterWrite);
    }

    #[test]
    fn cross_phase_explicit_dep_excluded_from_buckets() {
        // sys_sim (Simulation) depends on sys_init (Initialization)
        // The explicit dep edge sys_init→sys_sim is cross-phase — excluded from both buckets
        let defs = vec![
            def(
                "sys_init",
                PhaseEnum::Initialization,
                vec![],
                vec![],
                vec![],
            ),
            def(
                "sys_sim",
                PhaseEnum::Simulation,
                vec![],
                vec![],
                vec!["sys_init"],
            ),
        ];
        let buckets = segment(&defs);
        assert_eq!(buckets.len(), 2);
        // Neither bucket should contain the cross-phase edge
        for bucket in &buckets {
            let cross_key = ("sys_init".to_string(), "sys_sim".to_string());
            assert!(
                !bucket.edges.contains_key(&cross_key),
                "Cross-phase edges must be excluded from phase buckets"
            );
        }
    }

    #[test]
    fn intra_phase_explicit_dep_retained() {
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
        let buckets = segment(&defs);
        assert_eq!(buckets.len(), 1);
        let key = ("sys_a".to_string(), "sys_b".to_string());
        assert!(
            buckets[0].edges.contains_key(&key),
            "Intra-phase explicit dep must be retained"
        );
        assert_eq!(
            buckets[0].edges[&key].edge_type,
            EdgeType::ExplicitDependency
        );
    }

    // ── In-Degree Map ─────────────────────────────────────────────────────────

    #[test]
    fn in_degree_map_correct() {
        // sys_a → sys_b, sys_a → sys_c: sys_b and sys_c have in-degree 1
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
                vec!["sys_a"],
            ),
        ];
        let buckets = segment(&defs);
        let degrees = buckets[0].in_degree_map();
        assert_eq!(degrees["sys_a"], 0);
        assert_eq!(degrees["sys_b"], 1);
        assert_eq!(degrees["sys_c"], 1);
    }

    #[test]
    fn in_degree_map_chain() {
        // sys_a → sys_b → sys_c (via explicit deps)
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
        let buckets = segment(&defs);
        let degrees = buckets[0].in_degree_map();
        assert_eq!(degrees["sys_a"], 0, "Root has in-degree 0");
        assert_eq!(degrees["sys_b"], 1);
        assert_eq!(degrees["sys_c"], 1);
    }

    // ── Node Content ──────────────────────────────────────────────────────────

    #[test]
    fn bucket_nodes_sorted_by_system_id() {
        let defs = vec![sim("sys_z"), sim("sys_a"), sim("sys_m")];
        let buckets = segment(&defs);
        let ids = buckets[0].system_ids();
        assert_eq!(ids, vec!["sys_a", "sys_m", "sys_z"]);
    }

    #[test]
    fn each_system_in_exactly_one_bucket() {
        let defs = vec![
            def("sys_a", PhaseEnum::Initialization, vec![], vec![], vec![]),
            def("sys_b", PhaseEnum::Simulation, vec![], vec![], vec![]),
            def("sys_c", PhaseEnum::Simulation, vec![], vec![], vec![]),
            def("sys_d", PhaseEnum::Cleanup, vec![], vec![], vec![]),
        ];
        let buckets = segment(&defs);
        let total_systems: usize = buckets.iter().map(|b| b.system_count()).sum();
        assert_eq!(
            total_systems, 4,
            "Each system must appear in exactly one bucket"
        );
    }

    // ── Phase Summary ─────────────────────────────────────────────────────────

    #[test]
    fn phase_summary_counts_correctly() {
        let defs = vec![
            def("s1", PhaseEnum::Simulation, vec![], vec![], vec![]),
            def("s2", PhaseEnum::Simulation, vec![], vec![], vec![]),
            def("s3", PhaseEnum::PostSimulation, vec![], vec![], vec![]),
        ];
        let graph = GraphConstructionLayer::build(&defs).unwrap();
        let summary = PhaseSegmentationLayer::phase_summary(&graph);
        assert_eq!(summary[&2], 2); // Simulation = ordinal 2
        assert_eq!(summary[&3], 1); // PostSimulation = ordinal 3
        assert!(!summary.contains_key(&0)); // Initialization not used
    }

    // ── Phase Validation ──────────────────────────────────────────────────────

    #[test]
    fn forward_phase_dependency_rejected_by_segment() {
        // Manually build a graph with a forward dep (bypassing GraphConstructionLayer)
        let mut graph = RawSystemGraph::new();
        let mut sim_node = crate::graph_construction::system_node::SystemNode::new(
            "sys_sim",
            PhaseEnum::Simulation,
        );
        sim_node.depends_on.insert("sys_post".into());
        graph.add_node(sim_node);
        graph.add_node(crate::graph_construction::system_node::SystemNode::new(
            "sys_post",
            PhaseEnum::PostSimulation,
        ));
        let result = PhaseSegmentationLayer::segment(&graph);
        assert!(result.is_err());
        assert!(result.unwrap_err().is_phase());
    }

    // ── Full Zombie Chase ─────────────────────────────────────────────────────

    #[test]
    fn zombie_chase_all_simulation_one_bucket() {
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
        let buckets = segment(&defs);
        assert_eq!(
            buckets.len(),
            1,
            "All zombie chase systems are in Simulation"
        );
        assert_eq!(buckets[0].phase, PhaseEnum::Simulation);
        assert_eq!(buckets[0].system_count(), 5);
        // All intra-phase hazard edges retained, PHASE_ORDER excluded (none exist)
        for edge in buckets[0].edges.values() {
            assert_ne!(edge.edge_type, EdgeType::PhaseOrder);
        }
    }
}
