//! # Conflict Analyzer — SGC Stage 4
//!
//! Detects all write-write conflicts and read-write hazards in the
//! OrderedGraph, producing a ConflictReport with SerializationGroups
//! that tells the scheduler which systems cannot run in parallel.
//!
//! ## Input → Output
//! Input:  &OrderedGraph (from Stage 3) + &[PhaseBucket] (from Stage 2)
//! Output: ConflictReport — per-phase SerializationGroups + conflict lists
//!
//! ## What the Conflict Analyzer Does
//! Stage 1 (GraphConstructionLayer) already detected hazards and added edges.
//! Stage 4 re-examines those edges to build a higher-level structure:
//! SerializationGroups — clusters of systems that must all run serially.
//!
//! The distinction:
//! - Stage 1 produces edges (individual constraints between pairs)
//! - Stage 4 produces groups (transitive closures of all pairwise constraints)
//!
//! The scheduler needs groups, not individual edges, to build parallel
//! execution windows efficiently.
//!
//! ## ConflictReport
//! The report carries:
//! - All WAW conflict pairs (for diagnostics / builder UI)
//! - All RAW hazard pairs (for diagnostics)
//! - Direct same-phase ordering constraints (including explicit dependencies)
//! - Per-phase SerializationGroups (for the scheduler)
//! - A summary flag: requires_recompile if structural changes were made
//!
//! ## Determinism (D11)
//! All lists in ConflictReport are sorted by (system_a, system_b) pairs.
//! SerializationGroups are sorted by their representative system_id.

use crate::compilation_error::CompilationError;
use crate::conflict_analyzer::serialization_group_builder::{
    SerializationGroup, SerializationGroupBuilder,
};
use crate::graph_construction::hazard_detector::HazardDetector;
use crate::graph_construction::system_edge::RawSystemGraph;
use crate::phase_segmentation::phase_segmentation_layer::PhaseBucket;
use std::collections::{BTreeMap, BTreeSet};
use xace_core::runtime::phase_enum::PhaseEnum;

// ── Conflict Entry ────────────────────────────────────────────────────────────

/// One detected pairwise conflict between two systems.
#[derive(Debug, Clone)]
pub struct ConflictEntry {
    /// Lex-smaller system_id (D11).
    pub system_a: String,
    /// Lex-larger system_id (D11).
    pub system_b: String,
    /// Component type IDs involved.
    pub component_type_ids: BTreeSet<u32>,
    /// The phase both systems belong to.
    pub phase: PhaseEnum,
}

impl ConflictEntry {
    fn new(a: &str, b: &str, type_ids: BTreeSet<u32>, phase: PhaseEnum) -> Self {
        // Normalize: lex-smaller always goes in system_a (D11)
        let (system_a, system_b) = if a <= b {
            (a.to_string(), b.to_string())
        } else {
            (b.to_string(), a.to_string())
        };
        Self {
            system_a,
            system_b,
            component_type_ids: type_ids,
            phase,
        }
    }
}

// ── Conflict Report ───────────────────────────────────────────────────────────

/// Full conflict analysis results — output of ConflictAnalyzer.
///
/// Consumed by DeterministicSchedulerBuilder (Stage 5) to build
/// the final ExecutionPlan with correct parallel/serial groupings.
#[derive(Debug, Clone)]
pub struct ConflictReport {
    /// All write-write conflict pairs detected, sorted (D11).
    pub write_conflicts: Vec<ConflictEntry>,

    /// All read-write hazard pairs detected, sorted (D11).
    pub read_write_hazards: Vec<ConflictEntry>,

    /// Direct same-phase ordering constraints.
    ///
    /// Maps phase ordinal -> from_system -> directly ordered successor systems.
    /// These constraints stay separate from transitive component-conflict groups
    /// so dependency siblings may still execute in parallel after their common
    /// predecessor has completed.
    pub direct_ordering_constraints: BTreeMap<u8, BTreeMap<String, BTreeSet<String>>>,

    /// Per-phase serialization groups.
    /// BTreeMap<phase_ordinal, Vec<SerializationGroup>> sorted (D11).
    pub serialization_groups: BTreeMap<u8, Vec<SerializationGroup>>,

    /// Total number of systems analyzed.
    pub total_systems_analyzed: usize,

    /// Total number of conflicting pairs detected.
    pub total_conflicts: usize,
}

impl ConflictReport {
    fn new() -> Self {
        Self {
            write_conflicts: Vec::new(),
            read_write_hazards: Vec::new(),
            direct_ordering_constraints: BTreeMap::new(),
            serialization_groups: BTreeMap::new(),
            total_systems_analyzed: 0,
            total_conflicts: 0,
        }
    }

    /// Returns the serialization groups for a given phase, or empty slice.
    pub fn groups_for_phase(&self, phase: PhaseEnum) -> &[SerializationGroup] {
        self.serialization_groups
            .get(&phase.as_u8())
            .map(|v| v.as_slice())
            .unwrap_or(&[])
    }

    /// Returns true if the systems share a direct ordering edge in this phase.
    pub fn has_direct_ordering_constraint(
        &self,
        system_a: &str,
        system_b: &str,
        phase: PhaseEnum,
    ) -> bool {
        let Some(constraints) = self.direct_ordering_constraints.get(&phase.as_u8()) else {
            return false;
        };
        constraints
            .get(system_a)
            .is_some_and(|successors| successors.contains(system_b))
            || constraints
                .get(system_b)
                .is_some_and(|successors| successors.contains(system_a))
    }

    /// Returns true if system_a and system_b must be serialized in the given phase.
    ///
    /// Direct dependency edges serialize only the connected pair. Component
    /// hazards retain their existing transitive serialization-group behavior.
    pub fn must_serialize(&self, system_a: &str, system_b: &str, phase: PhaseEnum) -> bool {
        if self.has_direct_ordering_constraint(system_a, system_b, phase) {
            return true;
        }
        let groups = self.groups_for_phase(phase);
        SerializationGroupBuilder::are_serialized(system_a, system_b, groups)
    }

    /// Returns true if system_a and system_b can safely run in parallel.
    pub fn can_parallelize(&self, system_a: &str, system_b: &str, phase: PhaseEnum) -> bool {
        !self.must_serialize(system_a, system_b, phase)
    }

    /// Returns the number of constrained (multi-member) groups across all phases.
    pub fn constrained_group_count(&self) -> usize {
        self.serialization_groups
            .values()
            .flat_map(|groups| groups.iter())
            .filter(|g| g.is_constrained())
            .count()
    }

    /// Returns true if there are no conflicts at all (every system is parallelizable).
    pub fn is_conflict_free(&self) -> bool {
        self.total_conflicts == 0
    }
}

// ── Conflict Analyzer ─────────────────────────────────────────────────────────

/// SGC Stage 4 — detects all conflicts and builds the ConflictReport.
///
/// Stateless — one call to `analyze()` per compilation.
pub struct ConflictAnalyzer;

impl ConflictAnalyzer {
    /// Analyzes conflicts across all phase buckets.
    ///
    /// For each phase:
    ///   1. Scan all system pairs for WAW conflicts and RAW hazards
    ///   2. Build SerializationGroups via Union-Find (transitively)
    ///
    /// Returns Ok(ConflictReport) — this stage does not fail.
    /// (Unresolvable conflicts were caught in Stage 1; Stage 4 only classifies.)
    pub fn analyze(
        buckets: &[PhaseBucket],
        graph: &RawSystemGraph,
    ) -> Result<ConflictReport, CompilationError> {
        let mut report = ConflictReport::new();

        for bucket in buckets {
            let phase = bucket.phase;
            let sys_ids: Vec<&str> = bucket.system_ids();
            let sys_id_set: BTreeSet<&str> = sys_ids.iter().copied().collect();
            report.total_systems_analyzed += sys_ids.len();

            // Preserve direct graph ordering constraints for the parallel-window
            // pass. Keeping these pairwise avoids over-serializing dependency
            // siblings that share a predecessor but have no edge between them.
            let phase_constraints = report
                .direct_ordering_constraints
                .entry(phase.as_u8())
                .or_default();
            for edge in graph.edges.values() {
                if sys_id_set.contains(edge.from_system.as_str())
                    && sys_id_set.contains(edge.to_system.as_str())
                {
                    phase_constraints
                        .entry(edge.from_system.clone())
                        .or_default()
                        .insert(edge.to_system.clone());
                }
            }

            // ── Pairwise conflict detection ────────────────────────────────────
            // Sorted pairs: (sys_ids[i], sys_ids[j]) with i < j (D11)
            for i in 0..sys_ids.len() {
                for j in (i + 1)..sys_ids.len() {
                    let id_a = sys_ids[i];
                    let id_b = sys_ids[j];

                    let node_a = match graph.nodes.get(id_a) {
                        Some(n) => n,
                        None => continue,
                    };
                    let node_b = match graph.nodes.get(id_b) {
                        Some(n) => n,
                        None => continue,
                    };

                    // WAW conflicts
                    let waw = HazardDetector::detect_waw(node_a, node_b);
                    if !waw.is_empty() {
                        report
                            .write_conflicts
                            .push(ConflictEntry::new(id_a, id_b, waw, phase));
                        report.total_conflicts += 1;
                    }

                    // RAW hazards — both directions
                    let raw_a_to_b = HazardDetector::detect_raw_a_to_b(node_a, node_b);
                    if !raw_a_to_b.is_empty() {
                        report
                            .read_write_hazards
                            .push(ConflictEntry::new(id_a, id_b, raw_a_to_b, phase));
                        report.total_conflicts += 1;
                    }

                    let raw_b_to_a = HazardDetector::detect_raw_a_to_b(node_b, node_a);
                    if !raw_b_to_a.is_empty() {
                        report
                            .read_write_hazards
                            .push(ConflictEntry::new(id_b, id_a, raw_b_to_a, phase));
                        report.total_conflicts += 1;
                    }
                }
            }

            // ── Build serialization groups ─────────────────────────────────────
            let groups = SerializationGroupBuilder::build_for_phase(&sys_ids, graph);
            report.serialization_groups.insert(phase.as_u8(), groups);
        }

        Ok(report)
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

    fn def(id: &str, reads: Vec<u32>, writes: Vec<u32>) -> SystemDefinition {
        SystemDefinition::with_spec(
            id,
            id,
            xace_core::schema::system_definition::ExecutionPhase::Simulation,
            reads,
            writes,
        )
    }

    fn analyze(defs: &[SystemDefinition]) -> ConflictReport {
        let graph = GraphConstructionLayer::build(defs).unwrap();
        let buckets = PhaseSegmentationLayer::segment(&graph).unwrap();
        ConflictAnalyzer::analyze(&buckets, &graph).unwrap()
    }

    // ── Conflict-free ─────────────────────────────────────────────────────────

    #[test]
    fn no_overlap_produces_no_conflicts() {
        let defs = vec![
            def("sys_a", vec![6], vec![6]),
            def("sys_b", vec![100], vec![100]),
        ];
        let report = analyze(&defs);
        assert!(report.is_conflict_free());
        assert!(report.write_conflicts.is_empty());
        assert!(report.read_write_hazards.is_empty());
    }

    #[test]
    fn conflict_free_all_systems_parallelizable() {
        let defs = vec![
            def("sys_a", vec![6], vec![6]),
            def("sys_b", vec![100], vec![100]),
        ];
        let report = analyze(&defs);
        assert!(report.can_parallelize("sys_a", "sys_b", PhaseEnum::Simulation));
    }

    // ── WAW conflicts ─────────────────────────────────────────────────────────

    #[test]
    fn waw_conflict_detected() {
        let defs = vec![def("sys_a", vec![], vec![1]), def("sys_b", vec![], vec![1])];
        let report = analyze(&defs);
        assert_eq!(report.write_conflicts.len(), 1);
        let c = &report.write_conflicts[0];
        assert!(c.component_type_ids.contains(&1));
    }

    #[test]
    fn waw_systems_must_serialize() {
        let defs = vec![def("sys_a", vec![], vec![1]), def("sys_b", vec![], vec![1])];
        let report = analyze(&defs);
        assert!(report.must_serialize("sys_a", "sys_b", PhaseEnum::Simulation));
        assert!(!report.can_parallelize("sys_a", "sys_b", PhaseEnum::Simulation));
    }

    // ── RAW hazards ───────────────────────────────────────────────────────────

    #[test]
    fn raw_hazard_detected() {
        let defs = vec![
            def("sys_writer", vec![], vec![5]),
            def("sys_reader", vec![5], vec![]),
        ];
        let report = analyze(&defs);
        assert!(!report.read_write_hazards.is_empty());
        assert!(report.must_serialize("sys_reader", "sys_writer", PhaseEnum::Simulation));
    }

    #[test]
    fn raw_hazard_in_both_directions_detected() {
        // sys_a writes X that sys_b reads, sys_b writes Y that sys_a reads
        let defs = vec![
            def("sys_a", vec![5], vec![1]), // reads VELOCITY, writes TRANSFORM
            def("sys_b", vec![1], vec![5]), // reads TRANSFORM, writes VELOCITY
        ];
        let report = analyze(&defs);
        // RAW in both directions: a→b and b→a
        assert!(report.read_write_hazards.len() >= 2);
    }

    // ── Serialization groups ──────────────────────────────────────────────────

    #[test]
    fn serialization_groups_built_per_phase() {
        let defs = vec![def("sys_a", vec![], vec![1]), def("sys_b", vec![], vec![1])];
        let report = analyze(&defs);
        let groups = report.groups_for_phase(PhaseEnum::Simulation);
        assert!(!groups.is_empty());
        let constrained: Vec<_> = groups.iter().filter(|g| g.is_constrained()).collect();
        assert_eq!(constrained.len(), 1);
        assert!(constrained[0].contains("sys_a") && constrained[0].contains("sys_b"));
    }

    #[test]
    fn constrained_group_count_correct() {
        let defs = vec![
            def("sys_a", vec![], vec![1]),
            def("sys_b", vec![], vec![1]), // conflict with sys_a
            def("sys_c", vec![], vec![5]),
            def("sys_d", vec![], vec![5]), // conflict with sys_c
            def("sys_e", vec![], vec![]),  // no conflicts
        ];
        let report = analyze(&defs);
        assert_eq!(
            report.constrained_group_count(),
            2,
            "Two independent conflict pairs → two constrained groups"
        );
    }

    // ── Total counts ──────────────────────────────────────────────────────────

    #[test]
    fn total_systems_analyzed_correct() {
        let defs = vec![
            def("sys_a", vec![], vec![]),
            def("sys_b", vec![], vec![]),
            def("sys_c", vec![], vec![]),
        ];
        let report = analyze(&defs);
        assert_eq!(report.total_systems_analyzed, 3);
    }

    // ── Zombie chase ──────────────────────────────────────────────────────────

    #[test]
    fn zombie_chase_conflict_report() {
        let defs = vec![
            def("InputSystem", vec![6, 1], vec![5]),
            def("MovementSystem", vec![5, 1], vec![1]),
            def("AISystem", vec![160, 1], vec![5, 101]),
            def("DamageSystem", vec![101, 100], vec![100, 101]),
            def("DeathSystem", vec![100], vec![]),
        ];
        let report = analyze(&defs);
        assert_eq!(report.total_systems_analyzed, 5);

        // InputSystem and AISystem both write VELOCITY(5) → WAW conflict
        assert!(
            report.must_serialize("InputSystem", "AISystem", PhaseEnum::Simulation),
            "InputSystem and AISystem must serialize (WAW: VELOCITY)"
        );

        // AISystem writes VELOCITY(5) that MovementSystem reads → RAW
        assert!(
            report.must_serialize("AISystem", "MovementSystem", PhaseEnum::Simulation),
            "AISystem and MovementSystem must serialize (RAW: VELOCITY)"
        );

        // AISystem writes DAMAGE(101) that DamageSystem reads → RAW
        assert!(
            report.must_serialize("AISystem", "DamageSystem", PhaseEnum::Simulation),
            "AISystem and DamageSystem must serialize (RAW: DAMAGE)"
        );

        // DamageSystem writes HEALTH(100) that DeathSystem reads → RAW
        assert!(
            report.must_serialize("DamageSystem", "DeathSystem", PhaseEnum::Simulation),
            "DamageSystem and DeathSystem must serialize (RAW: HEALTH)"
        );
    }
}
