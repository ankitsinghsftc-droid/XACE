//! # Serialization Group Builder
//!
//! Builds SerializationGroups from the conflict data in a phase bucket —
//! groups of systems that CANNOT safely run in parallel with each other.
//!
//! ## What Is a Serialization Group
//! A serialization group is a maximal set of systems where every pair
//! has at least one hazard (WAW or RAW). Any two systems within the same
//! group must run in strict serial order — they cannot be parallelized.
//!
//! Systems in DIFFERENT serialization groups have no hazards between them
//! and are candidates for parallel execution (subject to further checks by
//! the ParallelGroupAnalyzer).
//!
//! ## Algorithm — Union-Find (Path Compression)
//! 1. Start with each system in its own group (singleton)
//! 2. For each hazard (WAW or RAW) between system A and system B:
//!    → Union their groups
//! 3. After all unions: collect final groups
//!
//! Union-Find is the natural fit here because serialization is transitive:
//! if A conflicts with B, and B conflicts with C, then A, B, and C must all
//! be serialized together — even if A has no direct conflict with C.
//!
//! ## Determinism (D11)
//! All sets and maps are BTreeMap/BTreeSet sorted by system_id.
//! The final groups are sorted: systems within each group sorted by system_id,
//! groups sorted by their minimum member system_id.

use std::collections::{BTreeMap, BTreeSet};
use crate::graph_construction::system_edge::RawSystemGraph;
use crate::graph_construction::hazard_detector::HazardDetector;
use crate::compilation_error::EdgeType;

// ── Serialization Group ───────────────────────────────────────────────────────

/// A set of systems that cannot safely run in parallel.
/// Every pair within the group has at least one WAW or RAW hazard.
#[derive(Debug, Clone)]
pub struct SerializationGroup {
    /// System IDs that must be serialized, sorted ascending (D11).
    pub members: BTreeSet<String>,

    /// Human-readable explanation of why this group must be serialized.
    pub reason: String,
}

impl SerializationGroup {
    /// Returns true if this group contains the given system.
    pub fn contains(&self, system_id: &str) -> bool {
        self.members.contains(system_id)
    }

    /// Returns true if the group has more than one member
    /// (i.e., actual serialization constraints exist).
    pub fn is_constrained(&self) -> bool {
        self.members.len() > 1
    }

    /// Returns the lexicographically smallest member (canonical representative).
    pub fn representative(&self) -> &str {
        self.members.iter().next().map(|s| s.as_str()).unwrap_or("")
    }
}

// ── Union-Find ────────────────────────────────────────────────────────────────

/// Simple Union-Find structure for grouping conflicting systems.
/// Keys are system_id strings. Parent map uses BTreeMap (D11).
struct UnionFind {
    parent: BTreeMap<String, String>,
}

impl UnionFind {
    fn new(system_ids: &[&str]) -> Self {
        let parent = system_ids
            .iter()
            .map(|&id| (id.to_string(), id.to_string()))
            .collect();
        Self { parent }
    }

    /// Finds the root representative of a system's group.
    /// Path compression is not applied here (simple version, correctness over speed).
    fn find(&self, id: &str) -> String {
        let mut current = id.to_string();
        loop {
            let parent = self.parent.get(&current).cloned().unwrap_or(current.clone());
            if parent == current {
                return current;
            }
            current = parent;
        }
    }

    /// Unions the groups of system_a and system_b.
    /// The lex-smaller root becomes the parent for deterministic results (D11).
    fn union(&mut self, a: &str, b: &str) {
        let root_a = self.find(a);
        let root_b = self.find(b);
        if root_a == root_b { return; }
        // Lex-smaller root becomes the canonical parent (D11)
        let (parent, child) = if root_a <= root_b {
            (root_a, root_b)
        } else {
            (root_b, root_a)
        };
        self.parent.insert(child, parent);
    }

    /// Collects all systems into their groups.
    /// Returns BTreeMap<root, BTreeSet<members>> sorted by root (D11).
    fn groups(&self) -> BTreeMap<String, BTreeSet<String>> {
        let mut groups: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
        for system_id in self.parent.keys() {
            let root = self.find(system_id);
            groups.entry(root).or_default().insert(system_id.clone());
        }
        groups
    }
}

// ── Serialization Group Builder ───────────────────────────────────────────────

/// Builds SerializationGroups from the hazard data in a system graph.
/// Called by ConflictAnalyzer with the phase-local subset of nodes.
pub struct SerializationGroupBuilder;

impl SerializationGroupBuilder {
    /// Builds serialization groups for the systems in one phase bucket.
    ///
    /// Uses Union-Find over all WAW and RAW hazard pairs.
    /// Returns groups sorted by representative system_id (D11).
    pub fn build_for_phase(
        system_ids: &[&str],
        graph:      &RawSystemGraph,
    ) -> Vec<SerializationGroup> {
        if system_ids.is_empty() {
            return Vec::new();
        }

        let mut uf = UnionFind::new(system_ids);

        // Process pairs in sorted order for determinism (D11)
        for i in 0..system_ids.len() {
            for j in (i + 1)..system_ids.len() {
                let id_a = system_ids[i];
                let id_b = system_ids[j];

                let node_a = match graph.nodes.get(id_a) {
                    Some(n) => n,
                    None    => continue,
                };
                let node_b = match graph.nodes.get(id_b) {
                    Some(n) => n,
                    None    => continue,
                };

                // Union if any hazard exists between the pair
                if HazardDetector::has_any_hazard(node_a, node_b) {
                    uf.union(id_a, id_b);
                }
            }
        }

        // Collect groups, sorted by root (D11)
        let groups = uf.groups();
        let mut result: Vec<SerializationGroup> = groups
            .into_values()
            .map(|members| {
                let is_constrained = members.len() > 1;
                let reason = if is_constrained {
                    format!(
                        "Systems {:?} have WAW or RAW hazards between them \
                         and must run in serial order.",
                        members.iter().collect::<Vec<_>>()
                    )
                } else {
                    "No conflicts — this system has no serialization constraints.".into()
                };
                SerializationGroup { members, reason }
            })
            .collect();

        // Sort groups by their representative (lex-smallest member) for D11
        result.sort_by(|a, b| a.representative().cmp(b.representative()));
        result
    }

    /// Returns the serialization group containing the given system_id,
    /// or None if the system is not in any of the provided groups.
    pub fn find_group<'a>(
        system_id: &str,
        groups:    &'a [SerializationGroup],
    ) -> Option<&'a SerializationGroup> {
        groups.iter().find(|g| g.contains(system_id))
    }

    /// Returns true if system_a and system_b are in the same serialization group.
    pub fn are_serialized(
        system_a: &str,
        system_b: &str,
        groups:   &[SerializationGroup],
    ) -> bool {
        groups.iter().any(|g| g.contains(system_a) && g.contains(system_b))
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::runtime::phase_enum::PhaseEnum;
    use xace_core::schema::system_definition::SystemDefinition;
    use crate::graph_construction::graph_construction_layer::GraphConstructionLayer;

    fn def(id: &str, reads: Vec<u32>, writes: Vec<u32>) -> SystemDefinition {
        SystemDefinition {
            id: id.into(), phase: PhaseEnum::Simulation, reads, writes,
            depends_on: vec![], deterministic: true, version: 1,
        }
    }

    fn build_and_group(defs: &[SystemDefinition]) -> Vec<SerializationGroup> {
        let graph = GraphConstructionLayer::build(defs).unwrap();
        let ids: Vec<&str> = graph.nodes.keys().map(|s| s.as_str()).collect();
        SerializationGroupBuilder::build_for_phase(&ids, &graph)
    }

    // ── Basic grouping ────────────────────────────────────────────────────────

    #[test]
    fn no_hazards_all_singletons() {
        let defs = vec![
            def("sys_a", vec![6],   vec![6]),
            def("sys_b", vec![100], vec![100]),
            def("sys_c", vec![160], vec![]),
        ];
        let groups = build_and_group(&defs);
        // Each system in its own group
        assert_eq!(groups.len(), 3);
        assert!(groups.iter().all(|g| !g.is_constrained()));
    }

    #[test]
    fn waw_conflict_groups_two_systems() {
        // Both write TRANSFORM(1) → WAW → same group
        let defs = vec![
            def("sys_movement", vec![], vec![1]),
            def("sys_physics",  vec![], vec![1]),
        ];
        let groups = build_and_group(&defs);
        // One constrained group containing both
        let constrained: Vec<_> = groups.iter().filter(|g| g.is_constrained()).collect();
        assert_eq!(constrained.len(), 1);
        assert!(constrained[0].contains("sys_movement"));
        assert!(constrained[0].contains("sys_physics"));
    }

    #[test]
    fn raw_hazard_groups_two_systems() {
        // sys_a writes VELOCITY(5), sys_b reads VELOCITY(5) → RAW → same group
        let defs = vec![
            def("sys_a", vec![],  vec![5]),
            def("sys_b", vec![5], vec![]),
        ];
        let groups = build_and_group(&defs);
        let constrained: Vec<_> = groups.iter().filter(|g| g.is_constrained()).collect();
        assert_eq!(constrained.len(), 1);
        assert!(constrained[0].contains("sys_a") && constrained[0].contains("sys_b"));
    }

    #[test]
    fn transitivity_groups_three_systems() {
        // sys_a ↔ sys_b (WAW), sys_b ↔ sys_c (RAW), sys_a and sys_c no direct conflict
        // Transitivity: all three in same group
        let defs = vec![
            def("sys_a", vec![],  vec![1, 5]),
            def("sys_b", vec![5], vec![1]),   // WAW with sys_a (writes 1), RAW: reads sys_a's 5
            def("sys_c", vec![1], vec![]),    // reads TRANSFORM written by sys_a and sys_b
        ];
        let groups = build_and_group(&defs);
        let constrained: Vec<_> = groups.iter().filter(|g| g.is_constrained()).collect();
        // All three must be in the same group due to transitivity
        let big_group = constrained.iter().find(|g| g.members.len() == 3);
        assert!(big_group.is_some(), "Transitivity must group all three systems");
    }

    #[test]
    fn independent_pairs_form_separate_groups() {
        // Pair 1: sys_a ↔ sys_b (WAW on 1)
        // Pair 2: sys_c ↔ sys_d (WAW on 5)
        // No connection between pairs
        let defs = vec![
            def("sys_a", vec![], vec![1]),
            def("sys_b", vec![], vec![1]),
            def("sys_c", vec![], vec![5]),
            def("sys_d", vec![], vec![5]),
        ];
        let groups = build_and_group(&defs);
        let constrained: Vec<_> = groups.iter().filter(|g| g.is_constrained()).collect();
        assert_eq!(constrained.len(), 2, "Two independent conflict pairs → two groups");
        assert!(!SerializationGroupBuilder::are_serialized("sys_a", "sys_c", &groups));
        assert!(!SerializationGroupBuilder::are_serialized("sys_b", "sys_d", &groups));
        assert!(SerializationGroupBuilder::are_serialized("sys_a", "sys_b", &groups));
        assert!(SerializationGroupBuilder::are_serialized("sys_c", "sys_d", &groups));
    }

    #[test]
    fn groups_sorted_by_representative() {
        let defs = vec![
            def("sys_z", vec![], vec![1]),
            def("sys_m", vec![], vec![2]),
            def("sys_a", vec![], vec![3]),
        ];
        let groups = build_and_group(&defs);
        let reps: Vec<&str> = groups.iter().map(|g| g.representative()).collect();
        assert_eq!(reps, sorted_reps(&reps), "Groups must be sorted by representative (D11)");
    }

    fn sorted_reps<'a>(reps: &[&'a str]) -> Vec<&'a str> {
        let mut v = reps.to_vec();
        v.sort();
        v
    }

    #[test]
    fn find_group_returns_correct_group() {
        let defs = vec![
            def("sys_a", vec![], vec![1]),
            def("sys_b", vec![], vec![1]), // WAW with sys_a
        ];
        let groups = build_and_group(&defs);
        let found = SerializationGroupBuilder::find_group("sys_a", &groups);
        assert!(found.is_some());
        assert!(found.unwrap().contains("sys_b"));
    }

    #[test]
    fn empty_system_list_produces_no_groups() {
        let graph = GraphConstructionLayer::build(&[]).unwrap();
        let groups = SerializationGroupBuilder::build_for_phase(&[], &graph);
        assert!(groups.is_empty());
    }
}