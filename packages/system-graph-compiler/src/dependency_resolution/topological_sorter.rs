//! # Topological Sorter
//!
//! Implements Kahn's algorithm to produce a deterministic topological
//! ordering of systems within one phase bucket.
//!
//! ## Kahn's Algorithm
//! 1. Compute in-degree for every node (edges pointing TO it)
//! 2. Seed the processing queue with all zero-in-degree nodes
//! 3. Repeatedly:
//!    a. Pop the lexicographically smallest node (tie-break, D11)
//!    b. Append it to the ordered output
//!    c. Decrement in-degrees of its successors
//!    d. Enqueue any successor whose in-degree just reached 0
//! 4. If all nodes processed → return ordered list (Ok)
//! 5. If nodes remain unprocessed → cycle detected (Err)
//!
//! ## Tie-Breaking (D11)
//! When multiple nodes reach in-degree 0 simultaneously, the one with the
//! lexicographically smallest system_id is processed first. This makes the
//! output stable across machines and runs given identical input.
//!
//! Implementation: BTreeSet as the ready queue. BTreeSet::pop_first() always
//! removes and returns the smallest element — no explicit sorting needed.
//!
//! ## Cycle Detection and Reporting
//! When Kahn's terminates with unprocessed nodes remaining, those nodes
//! participate in at least one cycle. A DFS traces the cycle path, which is
//! normalized to start from the lexicographically smallest node for
//! deterministic error messages.
//!
//! ## Scope
//! The sorter operates on ONE PhaseBucket at a time.
//! The DependencyResolutionEngine (the layer above) calls it once per bucket
//! and assembles the results into an OrderedGraph.

use std::collections::{BTreeMap, BTreeSet};
use crate::compilation_error::{CompilationError, CycleError, EdgeType};
use crate::graph_construction::system_edge::SystemEdge;
use crate::phase_segmentation::phase_segmentation_layer::PhaseBucket;

// ── Sort Result ───────────────────────────────────────────────────────────────

/// The output of a successful topological sort on one phase bucket.
#[derive(Debug, Clone)]
pub struct SortedPhase {
    pub phase:           xace_core::runtime::phase_enum::PhaseEnum,
    /// System IDs in topological order — safe to execute left to right.
    /// Tie-broken lexicographically (D11).
    pub ordered_systems: Vec<String>,
}

// ── Topological Sorter ────────────────────────────────────────────────────────

pub struct TopologicalSorter;

impl TopologicalSorter {
    /// Topologically sorts all systems in a PhaseBucket using Kahn's algorithm.
    ///
    /// Returns `Ok(SortedPhase)` if the bucket is acyclic.
    /// Returns `Err(CompilationError::Cycle(_))` if a cycle is detected.
    ///
    /// Tie-breaking: when multiple systems are simultaneously ready (in-degree 0),
    /// the lexicographically smallest system_id is processed first (D11).
    pub fn sort(bucket: &PhaseBucket) -> Result<SortedPhase, CompilationError> {
        // Build in-degree map and adjacency list from the bucket
        let mut in_degree  = bucket.in_degree_map();
        let adjacency      = Self::build_adjacency(bucket);

        // Seed: all nodes with in-degree 0 — BTreeSet gives lex order (D11)
        let mut ready: BTreeSet<String> = in_degree
            .iter()
            .filter(|(_, &deg)| deg == 0)
            .map(|(id, _)| id.clone())
            .collect();

        let mut ordered: Vec<String> = Vec::with_capacity(bucket.system_count());

        while let Some(system_id) = Self::pop_first(&mut ready) {
            ordered.push(system_id.clone());

            // Decrement in-degree of successors
            if let Some(successors) = adjacency.get(&system_id) {
                for successor in successors {
                    let deg = in_degree.entry(successor.clone()).or_insert(0);
                    *deg = deg.saturating_sub(1);
                    if *deg == 0 {
                        ready.insert(successor.clone());
                    }
                }
            }
        }

        // If not all nodes were processed, a cycle exists
        if ordered.len() != bucket.system_count() {
            let cycle = Self::extract_cycle(&in_degree, &adjacency);
            return Err(CompilationError::Cycle(cycle));
        }

        Ok(SortedPhase {
            phase:           bucket.phase,
            ordered_systems: ordered,
        })
    }

    // ── Internal ──────────────────────────────────────────────────────────────

    /// Builds an adjacency list: system_id → sorted Vec<successor_system_id>.
    /// BTreeMap + sorted Vec guarantees deterministic iteration (D11).
    fn build_adjacency(bucket: &PhaseBucket) -> BTreeMap<String, Vec<String>> {
        let mut adj: BTreeMap<String, Vec<String>> = bucket
            .nodes
            .keys()
            .map(|id| (id.clone(), Vec::new()))
            .collect();

        // bucket.edges is BTreeMap — iteration is already (from, to) sorted (D11)
        for ((from, to), _) in &bucket.edges {
            adj.entry(from.clone())
               .or_default()
               .push(to.clone());
        }

        // Sort each successor list for deterministic in-degree decrement order
        for successors in adj.values_mut() {
            successors.sort_unstable();
        }

        adj
    }

    /// Pops and returns the lexicographically smallest item from a BTreeSet.
    /// Returns None if the set is empty.
    fn pop_first(set: &mut BTreeSet<String>) -> Option<String> {
        // BTreeSet iteration is ascending — first() is the smallest
        let first = set.iter().next()?.clone();
        set.remove(&first);
        Some(first)
    }

    /// Extracts a cycle path from the remaining unprocessed nodes.
    ///
    /// After Kahn's terminates, nodes with in-degree > 0 are in cycles.
    /// DFS from the lexicographically smallest remaining node finds the cycle.
    /// The path is rotated to start from the lex-smallest node in the cycle (D11).
    fn extract_cycle(
        in_degree: &BTreeMap<String, usize>,
        adjacency: &BTreeMap<String, Vec<String>>,
    ) -> CycleError {
        // Collect remaining nodes (those with in-degree > 0)
        let remaining: BTreeSet<String> = in_degree
            .iter()
            .filter(|(_, &deg)| deg > 0)
            .map(|(id, _)| id.clone())
            .collect();

        // DFS from the lex-smallest remaining node
        let start = remaining.iter().next().cloned().unwrap_or_default();
        let cycle_path = Self::dfs_cycle(&start, &remaining, adjacency);

        // Determine edge types along the cycle path for the error
        let edge_types = vec![EdgeType::ExplicitDependency; cycle_path.len().saturating_sub(1)];

        CycleError::new(cycle_path, edge_types)
    }

    /// DFS to find a cycle path starting from `start`, restricted to `allowed` nodes.
    /// Returns the cycle as a Vec<String> starting from the lex-smallest node.
    fn dfs_cycle(
        start:     &str,
        allowed:   &BTreeSet<String>,
        adjacency: &BTreeMap<String, Vec<String>>,
    ) -> Vec<String> {
        let mut visited: Vec<String> = Vec::new();
        let mut seen:    BTreeSet<String> = BTreeSet::new();
        let mut current = start.to_string();

        loop {
            if seen.contains(&current) {
                // Found the cycle — extract the cycle portion
                let cycle_start = visited
                    .iter()
                    .position(|s| s == &current)
                    .unwrap_or(0);
                let mut cycle = visited[cycle_start..].to_vec();
                cycle.push(current); // close the cycle

                // Normalize: rotate to start from lex-smallest (D11)
                return Self::normalize_cycle(cycle);
            }
            seen.insert(current.clone());
            visited.push(current.clone());

            // Follow first successor that is still in allowed set
            let next = adjacency
                .get(&current)
                .and_then(|succs| succs.iter().find(|s| allowed.contains(*s)))
                .cloned();

            match next {
                Some(n) => current = n,
                None    => break, // dead end — can happen with multi-cycle graphs
            }
        }

        // Fallback: return whatever we found
        visited
    }

    /// Rotates a cycle Vec to start from the lexicographically smallest element (D11).
    fn normalize_cycle(mut cycle: Vec<String>) -> Vec<String> {
        if cycle.is_empty() { return cycle; }
        // Find the position of the lex-smallest element (excluding closing duplicate)
        let body = &cycle[..cycle.len().saturating_sub(1)];
        let min_pos = body
            .iter()
            .enumerate()
            .min_by_key(|(_, s)| s.as_str())
            .map(|(i, _)| i)
            .unwrap_or(0);

        // Rotate the body, then append the closing element
        let body_len = cycle.len() - 1;
        let mut body: Vec<String> = cycle.drain(..body_len).collect();
        body.rotate_left(min_pos);
        body.push(body[0].clone()); // close the cycle
        body
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::runtime::phase_enum::PhaseEnum;
    use xace_core::schema::system_definition::SystemDefinition;
    use crate::graph_construction::graph_construction_layer::GraphConstructionLayer;
    use crate::phase_segmentation::phase_segmentation_layer::PhaseSegmentationLayer;

    fn def(id: &str, reads: Vec<u32>, writes: Vec<u32>, deps: Vec<&str>) -> SystemDefinition {
        SystemDefinition {
            id: id.into(), phase: PhaseEnum::Simulation, reads, writes,
            depends_on: deps.into_iter().map(String::from).collect(),
            deterministic: true, version: 1,
        }
    }

    fn sort_defs(defs: &[SystemDefinition]) -> Result<SortedPhase, CompilationError> {
        let graph   = GraphConstructionLayer::build(defs).unwrap();
        let buckets = PhaseSegmentationLayer::segment(&graph).unwrap();
        assert_eq!(buckets.len(), 1);
        TopologicalSorter::sort(&buckets[0])
    }

    // ── Basic ordering ────────────────────────────────────────────────────────

    #[test]
    fn single_system_sorts_trivially() {
        let defs = vec![def("sys_a", vec![], vec![], vec![])];
        let sorted = sort_defs(&defs).unwrap();
        assert_eq!(sorted.ordered_systems, vec!["sys_a"]);
    }

    #[test]
    fn two_independent_systems_sorted_lex() {
        // No edges — both have in-degree 0; lex order decides
        let defs = vec![
            def("sys_z", vec![], vec![], vec![]),
            def("sys_a", vec![], vec![], vec![]),
        ];
        let sorted = sort_defs(&defs).unwrap();
        // "sys_a" < "sys_z" lex → sys_a first
        assert_eq!(sorted.ordered_systems[0], "sys_a");
        assert_eq!(sorted.ordered_systems[1], "sys_z");
    }

    #[test]
    fn explicit_chain_a_before_b_before_c() {
        let defs = vec![
            def("sys_a", vec![], vec![], vec![]),
            def("sys_b", vec![], vec![], vec!["sys_a"]),
            def("sys_c", vec![], vec![], vec!["sys_b"]),
        ];
        let sorted = sort_defs(&defs).unwrap();
        assert_eq!(sorted.ordered_systems, vec!["sys_a", "sys_b", "sys_c"]);
    }

    #[test]
    fn diamond_dependency_both_paths_respected() {
        // sys_a → sys_b, sys_a → sys_c, sys_b → sys_d, sys_c → sys_d
        let defs = vec![
            def("sys_a", vec![], vec![], vec![]),
            def("sys_b", vec![], vec![], vec!["sys_a"]),
            def("sys_c", vec![], vec![], vec!["sys_a"]),
            def("sys_d", vec![], vec![], vec!["sys_b", "sys_c"]),
        ];
        let sorted = sort_defs(&defs).unwrap();
        let order = &sorted.ordered_systems;
        // sys_a must be first, sys_d must be last
        assert_eq!(order[0], "sys_a");
        assert_eq!(order[3], "sys_d");
        // sys_b and sys_c both after sys_a, both before sys_d
        let b_pos = order.iter().position(|s| s == "sys_b").unwrap();
        let c_pos = order.iter().position(|s| s == "sys_c").unwrap();
        let d_pos = order.iter().position(|s| s == "sys_d").unwrap();
        assert!(b_pos > 0 && b_pos < d_pos);
        assert!(c_pos > 0 && c_pos < d_pos);
    }

    // ── RAW hazard ordering ───────────────────────────────────────────────────

    #[test]
    fn raw_hazard_forces_correct_order() {
        // sys_ai writes VELOCITY(5), sys_movement reads VELOCITY(5)
        // GraphConstructionLayer adds RAW edge: sys_ai → sys_movement
        let defs = vec![
            def("sys_movement", vec![5], vec![1], vec![]),  // reads VELOCITY
            def("sys_ai",       vec![],  vec![5], vec![]),  // writes VELOCITY
        ];
        let sorted = sort_defs(&defs).unwrap();
        let ai_pos  = sorted.ordered_systems.iter().position(|s| s == "sys_ai").unwrap();
        let mov_pos = sorted.ordered_systems.iter().position(|s| s == "sys_movement").unwrap();
        assert!(ai_pos < mov_pos, "sys_ai must precede sys_movement (RAW: VELOCITY)");
    }

    // ── WAW tie-break ordering ────────────────────────────────────────────────

    #[test]
    fn waw_tie_break_lex_order() {
        // Both write TRANSFORM(1). "sys_movement" < "sys_physics" → movement first
        let defs = vec![
            def("sys_physics",  vec![], vec![1], vec![]),
            def("sys_movement", vec![], vec![1], vec![]),
        ];
        let sorted = sort_defs(&defs).unwrap();
        let mov_pos  = sorted.ordered_systems.iter().position(|s| s == "sys_movement").unwrap();
        let phys_pos = sorted.ordered_systems.iter().position(|s| s == "sys_physics").unwrap();
        assert!(mov_pos < phys_pos, "sys_movement before sys_physics (WAW lex tie-break)");
    }

    // ── Determinism ───────────────────────────────────────────────────────────

    #[test]
    fn sort_deterministic_regardless_of_input_order() {
        // Same systems in different input order → same sorted output
        let defs_order_1 = vec![
            def("sys_movement", vec![5], vec![1], vec![]),
            def("sys_ai",       vec![],  vec![5], vec![]),
            def("sys_input",    vec![6], vec![5], vec![]),
        ];
        let defs_order_2 = vec![
            def("sys_ai",       vec![],  vec![5], vec![]),
            def("sys_input",    vec![6], vec![5], vec![]),
            def("sys_movement", vec![5], vec![1], vec![]),
        ];
        let sorted_1 = sort_defs(&defs_order_1).unwrap();
        let sorted_2 = sort_defs(&defs_order_2).unwrap();
        assert_eq!(
            sorted_1.ordered_systems, sorted_2.ordered_systems,
            "Sort must be deterministic regardless of input order (D11)"
        );
    }

    // ── Cycle Detection ───────────────────────────────────────────────────────

    #[test]
    fn two_node_cycle_detected() {
        // Manually build bucket with a 2-node cycle (bypassing GraphConstructionLayer)
        use crate::phase_segmentation::phase_segmentation_layer::PhaseBucket;
        use crate::graph_construction::system_node::SystemNode;
        use crate::graph_construction::system_edge::SystemEdge;

        let mut bucket = PhaseBucket {
            phase: PhaseEnum::Simulation,
            nodes: {
                let mut m = BTreeMap::new();
                m.insert("sys_a".into(), SystemNode::new("sys_a", PhaseEnum::Simulation));
                m.insert("sys_b".into(), SystemNode::new("sys_b", PhaseEnum::Simulation));
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

        let result = TopologicalSorter::sort(&bucket);
        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(err.is_cycle(), "Must detect cycle");
        if let CompilationError::Cycle(cycle_err) = err {
            assert!(!cycle_err.cycle_path.is_empty());
        }
    }

    #[test]
    fn no_cycle_on_valid_graph() {
        let defs = vec![
            def("sys_a", vec![], vec![], vec![]),
            def("sys_b", vec![], vec![], vec!["sys_a"]),
            def("sys_c", vec![], vec![], vec!["sys_b"]),
        ];
        assert!(sort_defs(&defs).is_ok());
    }

    // ── Zombie chase ordering ─────────────────────────────────────────────────

    #[test]
    fn zombie_chase_produces_valid_order() {
        let defs = vec![
            def("InputSystem",    vec![6, 1],     vec![5],       vec![]),
            def("MovementSystem", vec![5, 1],     vec![1],       vec![]),
            def("AISystem",       vec![160, 1],   vec![5, 101],  vec![]),
            def("DamageSystem",   vec![101, 100], vec![100, 101], vec![]),
            def("DeathSystem",    vec![100],      vec![],        vec![]),
        ];
        let sorted = sort_defs(&defs).unwrap();
        assert_eq!(sorted.ordered_systems.len(), 5);

        let order = &sorted.ordered_systems;
        // MovementSystem reads VELOCITY(5) — must come after both InputSystem and AISystem
        let mov_pos    = order.iter().position(|s| s == "MovementSystem").unwrap();
        let input_pos  = order.iter().position(|s| s == "InputSystem").unwrap();
        let ai_pos     = order.iter().position(|s| s == "AISystem").unwrap();
        let damage_pos = order.iter().position(|s| s == "DamageSystem").unwrap();
        let death_pos  = order.iter().position(|s| s == "DeathSystem").unwrap();

        assert!(input_pos < mov_pos,
            "InputSystem must precede MovementSystem (both write VELOCITY)");
        assert!(ai_pos < mov_pos,
            "AISystem must precede MovementSystem (RAW: VELOCITY)");
        // DamageSystem reads DAMAGE(101) written by AISystem → DAM after AI
        assert!(ai_pos < damage_pos,
            "AISystem must precede DamageSystem (RAW: DAMAGE)");
        // DeathSystem reads HEALTH(100) written by DamageSystem
        assert!(damage_pos < death_pos,
            "DamageSystem must precede DeathSystem (RAW: HEALTH)");
    }
}