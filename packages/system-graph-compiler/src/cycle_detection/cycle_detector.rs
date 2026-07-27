//! # Cycle Detector — SGC Cycle Detection Stage
//!
//! DFS-based cycle detection with Gray/Black vertex coloring.
//! Operates on individual PhaseBuckets produced by PhaseSegmentationLayer.
//!
//! ## Why Per-Bucket
//! The topological sorter already detects cycles implicitly (Kahn's algorithm
//! leaves nodes with in-degree > 0 when a cycle exists). CycleDetector provides
//! a richer diagnostic: it names the exact systems in the cycle and classifies
//! each edge, enabling CycleDiagnostics to suggest targeted fixes.
//!
//! ## Edge Filtering
//! PhaseOrder edges are excluded as a defensive guard — they should already be
//! absent from PhaseBuckets (PhaseSegmentationLayer filters them in Stage 2).
//! Cross-phase cycles are physically impossible once segmentation runs: a system
//! in Initialization cannot have an intra-bucket edge to Simulation.
//!
//! ## Cycle Normalization (D11)
//! All detected cycle paths are rotated to start from the lexicographically
//! smallest system_id. Guarantees identical error messages regardless of which
//! node the DFS happens to visit first.
//!
//! ## Hard vs Soft Cycles
//! Every cycle detected here is a hard CompilationError — there is no soft cycle
//! in an ECS graph after phase segmentation. A "soft cycle" would only arise from
//! cross-phase dependency suggestions, which are handled by PhaseValidator.
//!
//! ## Determinism (D11)
//! DFS visits nodes in BTreeMap key order (system_id ASC). Neighbor lists are
//! built from BTreeMap edge iteration. Both are deterministic by construction.

use std::collections::BTreeMap;

use crate::compilation_error::{CompilationError, CycleError, EdgeType};
use crate::graph_construction::system_edge::RawSystemGraph;
use crate::phase_segmentation::phase_segmentation_layer::PhaseBucket;

// ── Vertex Color ──────────────────────────────────────────────────────────────

/// DFS vertex colouring.
///
/// White → not yet visited.
/// Gray  → currently on the DFS stack (active path).
/// Black → fully explored; no cycle reachable from this vertex.
#[derive(Debug, Clone, PartialEq, Eq)]
enum VertexColor {
    White,
    Gray,
    Black,
}

// ── Cycle Detector ────────────────────────────────────────────────────────────

/// Detects hard dependency cycles in a PhaseBucket using iterative DFS.
///
/// Stateless — one call to `check()` per bucket per compilation pass.
pub struct CycleDetector;

impl CycleDetector {
    /// Convenience method for the SGC pipeline.
    ///
    /// Segments the full `RawSystemGraph` into PhaseBuckets and checks each
    /// bucket for cycles. Called by `SgcPipeline` before the topological sorter
    /// so that cycle errors carry the full path + suggestions rather than
    /// Kahn's residual-node failure.
    ///
    /// Returns `Ok(())` if every phase bucket is acyclic.
    /// Returns the first `Err(CompilationError::Cycle(_))` encountered.
    /// Buckets are checked in phase ordinal order (D11).
    pub fn detect_in_graph(graph: &RawSystemGraph) -> Result<(), CompilationError> {
        use crate::phase_segmentation::phase_segmentation_layer::PhaseSegmentationLayer;
        let buckets = PhaseSegmentationLayer::segment(graph)?;
        for bucket in &buckets {
            Self::check(bucket)?;
        }
        Ok(())
    }

    /// Checks a single PhaseBucket for dependency cycles.
    ///
    /// Returns `Ok(())` if the bucket is acyclic.
    /// Returns `Err(CompilationError::Cycle(_))` on the first cycle found.
    ///
    /// Visits nodes in BTreeMap key order (system_id ASC, D11).
    /// PhaseOrder edges are skipped defensively even if somehow present.
    pub fn check(bucket: &PhaseBucket) -> Result<(), CompilationError> {
        // All nodes start White.
        let mut colors: BTreeMap<&str, VertexColor> = bucket
            .nodes
            .keys()
            .map(|id| (id.as_str(), VertexColor::White))
            .collect();

        // Visit every unvisited node (handles disconnected subgraphs).
        // BTreeMap iteration is sorted by key → deterministic visit order (D11).
        let node_ids: Vec<&str> = bucket.nodes.keys().map(|s| s.as_str()).collect();

        for &start in &node_ids {
            if colors[start] == VertexColor::White {
                if let Some(cycle_path) = Self::dfs(start, bucket, &mut colors) {
                    let edge_types = Self::extract_edge_types(&cycle_path, bucket);
                    let normalized = Self::normalize_cycle(cycle_path);
                    return Err(CompilationError::Cycle(CycleError::new(
                        normalized, edge_types,
                    )));
                }
            }
        }

        Ok(())
    }

    /// Iterative DFS with explicit stack to avoid stack-overflow on large graphs.
    ///
    /// Each stack frame carries: (node, iterator_position_in_neighbor_list).
    /// On first entry to a node → color Gray.
    /// When all neighbors exhausted → color Black, pop frame.
    /// Back edge to a Gray node → cycle detected, reconstruct path.
    ///
    /// Returns `Some(cycle_path)` on cycle, `None` if subtree is acyclic.
    fn dfs<'a>(
        start: &'a str,
        bucket: &'a PhaseBucket,
        colors: &mut BTreeMap<&'a str, VertexColor>,
    ) -> Option<Vec<String>> {
        // Build adjacency list once (sorted by (from,to) key — already sorted in BTreeMap).
        // Stack frames: (node_id, neighbor_index).
        // parent_map reconstructs the path on cycle detection.
        let mut parent: BTreeMap<&'a str, Option<&'a str>> = BTreeMap::new();
        // Stack: Vec<(node, neighbors_snapshot, next_neighbor_idx)>
        let mut stack: Vec<(&'a str, Vec<&'a str>, usize)> = Vec::new();

        colors.insert(start, VertexColor::Gray);
        parent.insert(start, None);
        stack.push((start, Self::neighbors(start, bucket), 0));

        while let Some((node, neighbors, idx)) = stack.last_mut() {
            let node = *node; // copy to avoid borrow issues
            if *idx < neighbors.len() {
                let neighbor = neighbors[*idx];
                *idx += 1;

                match colors.get(neighbor).cloned().unwrap_or(VertexColor::White) {
                    VertexColor::Gray => {
                        // Back edge → cycle. neighbor is the cycle start (it's Gray).
                        let cycle = Self::reconstruct_cycle(neighbor, node, &parent);
                        return Some(cycle);
                    }
                    VertexColor::White => {
                        colors.insert(neighbor, VertexColor::Gray);
                        parent.insert(neighbor, Some(node));
                        let nbrs = Self::neighbors(neighbor, bucket);
                        stack.push((neighbor, nbrs, 0));
                    }
                    VertexColor::Black => {
                        // Already fully explored — no cycle this way.
                    }
                }
            } else {
                // All neighbors of `node` explored — mark Black and pop.
                colors.insert(node, VertexColor::Black);
                stack.pop();
            }
        }

        None
    }

    /// Collects outgoing neighbors of `node` in sorted order (D11).
    /// Excludes PhaseOrder edges defensively (should already be absent).
    fn neighbors<'a>(node: &str, bucket: &'a PhaseBucket) -> Vec<&'a str> {
        bucket
            .edges
            .iter()
            .filter(|((from, _), edge)| {
                from.as_str() == node && edge.edge_type != EdgeType::PhaseOrder
            })
            .map(|((_, to), _)| to.as_str())
            .collect()
        // BTreeMap iteration already sorted by (from, to) key → deterministic (D11).
    }

    /// Reconstructs the cycle path using the parent map.
    ///
    /// `cycle_start` — the Gray node we found a back edge to.
    /// `current`     — the node from which the back edge originates.
    ///
    /// Walks parent pointers from `current` back to `cycle_start`, then
    /// reverses to get forward execution order.
    ///
    /// Result: `[cycle_start, ..., current]`
    /// The implicit closing edge is `current → cycle_start`.
    fn reconstruct_cycle(
        cycle_start: &str,
        current: &str,
        parent: &BTreeMap<&str, Option<&str>>,
    ) -> Vec<String> {
        let mut path: Vec<String> = Vec::new();
        let mut node = current;

        // Walk backwards from `current` to `cycle_start` via parent pointers.
        loop {
            path.push(node.to_string());
            if node == cycle_start {
                break;
            }
            match parent.get(node) {
                Some(Some(p)) => node = p,
                // Parent chain broken before reaching cycle_start — defensive break.
                _ => break,
            }
        }

        // path is [current, ..., cycle_start] — reverse to get forward order.
        path.reverse();
        // Result: [cycle_start, ..., current]
        // Closing edge: current → cycle_start (implicit; shown in cycle_display()).
        path
    }

    /// Extracts the EdgeType for each consecutive pair in the cycle path,
    /// including the closing edge from the last node back to the first.
    ///
    /// Returns a Vec of length `cycle_path.len()` — one type per edge.
    fn extract_edge_types(cycle_path: &[String], bucket: &PhaseBucket) -> Vec<EdgeType> {
        let n = cycle_path.len();
        let mut types = Vec::with_capacity(n);

        for i in 0..n {
            let from = &cycle_path[i];
            let to = &cycle_path[(i + 1) % n]; // wraps around for closing edge
            let key = (from.clone(), to.clone());
            let edge_type = bucket
                .edges
                .get(&key)
                .map(|e| e.edge_type.clone())
                // Fallback: treat missing edge as ExplicitDependency for display.
                .unwrap_or(EdgeType::ExplicitDependency);
            types.push(edge_type);
        }

        types
    }

    /// Normalizes a cycle path to start from the lexicographically smallest
    /// system_id. Guarantees identical error messages regardless of traversal
    /// entry point (D11).
    ///
    /// Example: `["sys_c", "sys_a", "sys_b"]` → `["sys_a", "sys_b", "sys_c"]`
    pub fn normalize_cycle(mut path: Vec<String>) -> Vec<String> {
        if path.is_empty() {
            return path;
        }

        // Find the index of the lexicographically smallest element.
        let min_idx = path
            .iter()
            .enumerate()
            .min_by(|(_, a), (_, b)| a.cmp(b))
            .map(|(i, _)| i)
            .unwrap_or(0);

        // Rotate left so the smallest element is at index 0.
        path.rotate_left(min_idx);
        path
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::graph_construction::system_edge::SystemEdge;
    use crate::graph_construction::system_node::SystemNode;
    use crate::phase_segmentation::phase_segmentation_layer::PhaseBucket;
    use std::collections::BTreeMap;
    use xace_core::runtime::phase_enum::PhaseEnum;

    // ── Helpers ───────────────────────────────────────────────────────────────

    /// Builds a PhaseBucket from a node list and an explicit-dependency edge list.
    fn make_bucket(nodes: &[&str], edges: &[(&str, &str)]) -> PhaseBucket {
        PhaseBucket {
            phase: PhaseEnum::Simulation,
            nodes: nodes
                .iter()
                .map(|&id| (id.to_string(), SystemNode::new(id, PhaseEnum::Simulation)))
                .collect(),
            edges: edges
                .iter()
                .map(|&(from, to)| {
                    let key = (from.to_string(), to.to_string());
                    let edge = SystemEdge::explicit_dependency(from, to);
                    (key, edge)
                })
                .collect(),
        }
    }

    // ── Acyclic cases ─────────────────────────────────────────────────────────

    #[test]
    fn empty_bucket_is_acyclic() {
        let bucket = make_bucket(&[], &[]);
        assert!(CycleDetector::check(&bucket).is_ok());
    }

    #[test]
    fn single_node_no_self_loop_is_acyclic() {
        let bucket = make_bucket(&["sys_a"], &[]);
        assert!(CycleDetector::check(&bucket).is_ok());
    }

    #[test]
    fn linear_chain_three_nodes_acyclic() {
        // sys_a → sys_b → sys_c
        let bucket = make_bucket(
            &["sys_a", "sys_b", "sys_c"],
            &[("sys_a", "sys_b"), ("sys_b", "sys_c")],
        );
        assert!(CycleDetector::check(&bucket).is_ok());
    }

    #[test]
    fn diamond_graph_acyclic() {
        // sys_a → sys_b, sys_a → sys_c, sys_b → sys_d, sys_c → sys_d
        let bucket = make_bucket(
            &["sys_a", "sys_b", "sys_c", "sys_d"],
            &[
                ("sys_a", "sys_b"),
                ("sys_a", "sys_c"),
                ("sys_b", "sys_d"),
                ("sys_c", "sys_d"),
            ],
        );
        assert!(CycleDetector::check(&bucket).is_ok());
    }

    #[test]
    fn disconnected_acyclic_components() {
        // Two independent chains: sys_a → sys_b  and  sys_c → sys_d
        let bucket = make_bucket(
            &["sys_a", "sys_b", "sys_c", "sys_d"],
            &[("sys_a", "sys_b"), ("sys_c", "sys_d")],
        );
        assert!(CycleDetector::check(&bucket).is_ok());
    }

    // ── Hard cycle cases ──────────────────────────────────────────────────────

    #[test]
    fn two_node_cycle_detected() {
        // sys_a → sys_b → sys_a
        let bucket = make_bucket(
            &["sys_a", "sys_b"],
            &[("sys_a", "sys_b"), ("sys_b", "sys_a")],
        );
        let result = CycleDetector::check(&bucket);
        assert!(result.is_err());
        assert!(result.unwrap_err().is_cycle());
    }

    #[test]
    fn three_node_cycle_detected() {
        // sys_a → sys_b → sys_c → sys_a
        let bucket = make_bucket(
            &["sys_a", "sys_b", "sys_c"],
            &[("sys_a", "sys_b"), ("sys_b", "sys_c"), ("sys_c", "sys_a")],
        );
        let result = CycleDetector::check(&bucket);
        assert!(result.is_err());
        if let Err(CompilationError::Cycle(ce)) = result {
            // Normalized: must start from lex-smallest
            assert_eq!(
                ce.cycle_path[0], "sys_a",
                "Cycle path must start from lex-smallest node (D11)"
            );
            assert_eq!(
                ce.cycle_path.len(),
                3,
                "Three-node cycle must have three path entries"
            );
        } else {
            panic!("Expected Cycle error");
        }
    }

    #[test]
    fn cycle_path_normalized_regardless_of_dfs_entry() {
        // The cycle is sys_c → sys_a → sys_b → sys_c.
        // DFS will enter at sys_a (BTreeMap order), but normalization
        // must still produce [sys_a, sys_b, sys_c] as the canonical form.
        let bucket = make_bucket(
            &["sys_a", "sys_b", "sys_c"],
            &[("sys_c", "sys_a"), ("sys_a", "sys_b"), ("sys_b", "sys_c")],
        );
        if let Err(CompilationError::Cycle(ce)) = CycleDetector::check(&bucket) {
            assert_eq!(
                ce.cycle_path[0], "sys_a",
                "Cycle must start from lex-smallest node sys_a (D11)"
            );
        } else {
            panic!("Expected Cycle error");
        }
    }

    #[test]
    fn cycle_with_tail_still_detected() {
        // sys_x → sys_a → sys_b → sys_a (sys_x is a tail, not in the cycle)
        let bucket = make_bucket(
            &["sys_a", "sys_b", "sys_x"],
            &[("sys_x", "sys_a"), ("sys_a", "sys_b"), ("sys_b", "sys_a")],
        );
        let result = CycleDetector::check(&bucket);
        assert!(result.is_err());
        assert!(result.unwrap_err().is_cycle());
    }

    // ── PhaseOrder exclusion ──────────────────────────────────────────────────

    #[test]
    fn phase_order_edge_excluded_from_cycle_detection() {
        // sys_a → sys_b via ExplicitDependency (real constraint).
        // sys_b → sys_a via PhaseOrder (must be ignored — not a real cycle).
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
                // PhaseOrder edge — must be skipped by cycle detector.
                m.insert(
                    ("sys_b".into(), "sys_a".into()),
                    SystemEdge::phase_order("sys_b", "sys_a"),
                );
                m
            },
        };
        // Only the ExplicitDependency edge exists logically.
        // sys_a → sys_b is a DAG — no cycle.
        assert!(
            CycleDetector::check(&bucket).is_ok(),
            "PhaseOrder back-edge must not be treated as a cycle"
        );
    }

    // ── CycleError payload ────────────────────────────────────────────────────

    #[test]
    fn cycle_error_has_non_empty_description_and_suggestions() {
        let bucket = make_bucket(
            &["sys_a", "sys_b"],
            &[("sys_a", "sys_b"), ("sys_b", "sys_a")],
        );
        if let Err(CompilationError::Cycle(ce)) = CycleDetector::check(&bucket) {
            assert!(
                !ce.description.is_empty(),
                "CycleError must have a description"
            );
            assert!(
                !ce.suggestions.is_empty(),
                "CycleError must have suggestions"
            );
            assert_eq!(
                ce.edge_types.len(),
                ce.cycle_path.len(),
                "One EdgeType per edge in the cycle path"
            );
        } else {
            panic!("Expected Cycle error");
        }
    }

    #[test]
    fn cycle_error_edge_types_match_path_length() {
        // Three-node cycle — three edges, three edge_types.
        let bucket = make_bucket(
            &["sys_a", "sys_b", "sys_c"],
            &[("sys_a", "sys_b"), ("sys_b", "sys_c"), ("sys_c", "sys_a")],
        );
        if let Err(CompilationError::Cycle(ce)) = CycleDetector::check(&bucket) {
            assert_eq!(
                ce.edge_types.len(),
                ce.cycle_path.len(),
                "edge_types.len() must equal cycle_path.len()"
            );
        } else {
            panic!("Expected Cycle error");
        }
    }

    // ── normalize_cycle ───────────────────────────────────────────────────────

    #[test]
    fn normalize_empty_path_is_stable() {
        let result = CycleDetector::normalize_cycle(vec![]);
        assert!(result.is_empty());
    }

    #[test]
    fn normalize_single_element_unchanged() {
        let result = CycleDetector::normalize_cycle(vec!["sys_a".into()]);
        assert_eq!(result, vec!["sys_a"]);
    }

    #[test]
    fn normalize_already_minimal_unchanged() {
        let path = vec![
            "sys_a".to_string(),
            "sys_b".to_string(),
            "sys_c".to_string(),
        ];
        let result = CycleDetector::normalize_cycle(path.clone());
        assert_eq!(result, path);
    }

    #[test]
    fn normalize_rotates_to_lex_minimum() {
        // [sys_c, sys_a, sys_b] → [sys_a, sys_b, sys_c]
        let path = vec![
            "sys_c".to_string(),
            "sys_a".to_string(),
            "sys_b".to_string(),
        ];
        let result = CycleDetector::normalize_cycle(path);
        assert_eq!(result, vec!["sys_a", "sys_b", "sys_c"]);
    }

    #[test]
    fn normalize_middle_element_minimum() {
        // [sys_z, sys_a, sys_m] — sys_a is minimum at index 1
        let path = vec![
            "sys_z".to_string(),
            "sys_a".to_string(),
            "sys_m".to_string(),
        ];
        let result = CycleDetector::normalize_cycle(path);
        assert_eq!(result[0], "sys_a");
        assert_eq!(result.len(), 3);
    }

    // ── Zombie chase — must be acyclic ────────────────────────────────────────

    #[test]
    fn zombie_chase_five_systems_acyclic() {
        use crate::graph_construction::graph_construction_layer::GraphConstructionLayer;
        use crate::phase_segmentation::phase_segmentation_layer::PhaseSegmentationLayer;
        use xace_core::schema::system_definition::SystemDefinition;

        fn def(id: &str, reads: Vec<u32>, writes: Vec<u32>, deps: Vec<&str>) -> SystemDefinition {
            let mut def = SystemDefinition::with_spec(
                id,
                id,
                xace_core::schema::system_definition::ExecutionPhase::Simulation,
                reads,
                writes,
            );
            def.depends_on = deps.into_iter().map(String::from).collect();
            def
        }

        let defs = vec![
            def("InputSystem", vec![6, 1], vec![5], vec![]),
            def("MovementSystem", vec![5, 1], vec![1], vec![]),
            def("AISystem", vec![160, 1], vec![5, 101], vec![]),
            def("DamageSystem", vec![101, 100], vec![100, 101], vec![]),
            def("DeathSystem", vec![100], vec![], vec![]),
        ];

        let graph = GraphConstructionLayer::build(&defs).unwrap();
        let buckets = PhaseSegmentationLayer::segment(&graph).unwrap();

        for bucket in &buckets {
            assert!(
                CycleDetector::check(bucket).is_ok(),
                "Zombie chase Simulation bucket must be acyclic"
            );
        }
    }
}
