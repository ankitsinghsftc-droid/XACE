//! # Hazard Detector
//!
//! Detects RAW (read-after-write) and WAW (write-after-write) hazards
//! between pairs of system nodes in the same phase.
//!
//! ## What Is a Hazard
//! A hazard is a component access pattern that forces a specific
//! execution ordering between two systems:
//!
//! **RAW (Read-After-Write)**: System A writes component X, System B reads X.
//! B must run after A to see A's mutations. If B runs first it sees stale data.
//!
//! **WAW (Write-After-Write)**: Both A and B write component X.
//! One must run first — the final component value depends on order.
//! XACE resolves WAW with a deterministic tie-break: lexicographically
//! smaller system_id runs first. This makes WAW resolution stable across
//! all machines and reruns (D11).
//!
//! ## WAW Tie-Breaking Rule
//! If sys_ai and sys_movement both write COMP_VELOCITY_V1:
//!   "sys_ai" < "sys_movement" lexicographically
//!   → edge: sys_ai → sys_movement
//!   → sys_ai runs first, sys_movement's write is the final value
//!
//! ## Cross-Phase Hazards
//! The detector only reports hazards within the same phase.
//! Cross-phase ordering is handled by the PhaseOrder edge type in
//! GraphConstructionLayer — every system in an earlier phase implicitly
//! precedes every system in a later phase.
//!
//! ## Output
//! Returns a HazardReport containing all edges that must be added to the
//! RawSystemGraph for the given pair of systems. The GraphConstructionLayer
//! calls detect() for every (A, B) pair in the same phase.

use std::collections::BTreeSet;
use crate::graph_construction::system_edge::SystemEdge;
use crate::graph_construction::system_node::SystemNode;

// ── Hazard Report ─────────────────────────────────────────────────────────────

/// The hazards detected between two systems.
///
/// Returned by HazardDetector::detect(). All edges in this report
/// must be added to the RawSystemGraph by GraphConstructionLayer.
#[derive(Debug, Default)]
pub struct HazardReport {
    /// Edges to add to the graph for these two systems.
    pub edges: Vec<SystemEdge>,
    /// Component type IDs involved in RAW hazards (for diagnostics).
    pub raw_hazard_type_ids: BTreeSet<u32>,
    /// Component type IDs involved in WAW conflicts (for diagnostics).
    pub waw_conflict_type_ids: BTreeSet<u32>,
}

impl HazardReport {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn has_hazards(&self) -> bool {
        !self.edges.is_empty()
    }

    pub fn has_raw(&self) -> bool {
        !self.raw_hazard_type_ids.is_empty()
    }

    pub fn has_waw(&self) -> bool {
        !self.waw_conflict_type_ids.is_empty()
    }

    pub fn edge_count(&self) -> usize {
        self.edges.len()
    }
}

// ── Hazard Detector ───────────────────────────────────────────────────────────

/// Detects RAW and WAW hazards between pairs of system nodes.
///
/// Stateless — all methods are pure functions of the input nodes.
/// Called by GraphConstructionLayer for every (A, B) pair in the same phase.
pub struct HazardDetector;

impl HazardDetector {
    // ── Primary API ───────────────────────────────────────────────────────────

    /// Detects all hazards between node_a and node_b.
    ///
    /// Checks both directions:
    /// - node_a writes X, node_b reads X  → edge: node_a → node_b (RAW)
    /// - node_b writes X, node_a reads X  → edge: node_b → node_a (RAW)
    /// - Both write X → edge: lex_min → lex_max (WAW, tie-break)
    ///
    /// Only called for systems in the same phase.
    /// Cross-phase ordering is handled by GraphConstructionLayer.
    pub fn detect(node_a: &SystemNode, node_b: &SystemNode) -> HazardReport {
        let mut report = HazardReport::new();

        // ── WAW: both write the same component ────────────────────────────────
        let waw = node_a.write_overlap_with(node_b);
        if !waw.is_empty() {
            let type_ids: Vec<u32> = waw.iter().copied().collect(); // sorted (BTreeSet)
            report.waw_conflict_type_ids = waw;
            // WAW tie-break: lexicographically smaller system_id runs first (D11)
            let (first, second) = Self::lexicographic_order(node_a, node_b);
            report.edges.push(SystemEdge::write_after_write(
                first.system_id.clone(),
                second.system_id.clone(),
                type_ids,
            ));
        }

        // ── RAW: node_a writes X that node_b reads ────────────────────────────
        let raw_a_to_b = node_a.raw_hazard_with(node_b);
        if !raw_a_to_b.is_empty() {
            let type_ids: Vec<u32> = raw_a_to_b.iter().copied().collect();
            report.raw_hazard_type_ids.extend(raw_a_to_b);
            report.edges.push(SystemEdge::read_after_write(
                node_a.system_id.clone(),
                node_b.system_id.clone(),
                type_ids,
            ));
        }

        // ── RAW: node_b writes X that node_a reads ────────────────────────────
        let raw_b_to_a = node_b.raw_hazard_with(node_a);
        if !raw_b_to_a.is_empty() {
            let type_ids: Vec<u32> = raw_b_to_a.iter().copied().collect();
            report.raw_hazard_type_ids.extend(raw_b_to_a);
            report.edges.push(SystemEdge::read_after_write(
                node_b.system_id.clone(),
                node_a.system_id.clone(),
                type_ids,
            ));
        }

        report
    }

    /// Detects only WAW conflicts between two nodes.
    /// Used by the ConflictAnalyzer to build SerializationGroups.
    pub fn detect_waw(node_a: &SystemNode, node_b: &SystemNode) -> BTreeSet<u32> {
        node_a.write_overlap_with(node_b)
    }

    /// Detects only RAW hazards: what node_a writes that node_b reads.
    /// Returns the component type IDs causing the hazard.
    pub fn detect_raw_a_to_b(node_a: &SystemNode, node_b: &SystemNode) -> BTreeSet<u32> {
        node_a.raw_hazard_with(node_b)
    }

    /// Returns true if any hazard exists between node_a and node_b.
    pub fn has_any_hazard(node_a: &SystemNode, node_b: &SystemNode) -> bool {
        !node_a.write_overlap_with(node_b).is_empty()
            || !node_a.raw_hazard_with(node_b).is_empty()
            || !node_b.raw_hazard_with(node_a).is_empty()
    }

    /// Returns true if node_a and node_b can safely run in parallel.
    /// Safe = no WAW conflicts AND no RAW hazards in either direction.
    pub fn is_parallel_safe(node_a: &SystemNode, node_b: &SystemNode) -> bool {
        !Self::has_any_hazard(node_a, node_b)
    }

    // ── Internal ──────────────────────────────────────────────────────────────

    /// Returns (first, second) where first.system_id < second.system_id
    /// lexicographically. Used for deterministic WAW tie-breaking (D11).
    fn lexicographic_order<'a>(
        a: &'a SystemNode,
        b: &'a SystemNode,
    ) -> (&'a SystemNode, &'a SystemNode) {
        if a.system_id <= b.system_id { (a, b) } else { (b, a) }
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::runtime::phase_enum::PhaseEnum;
    use crate::graph_construction::system_node::SystemNode;
    use crate::compilation_error::EdgeType;

    fn sim_node(id: &str, reads: Vec<u32>, writes: Vec<u32>) -> SystemNode {
        SystemNode::new(id, PhaseEnum::Simulation)
            .with_reads(reads)
            .with_writes(writes)
    }

    // ── No Hazard ─────────────────────────────────────────────────────────────

    #[test]
    fn no_hazard_when_no_overlap() {
        // sys_input reads/writes INPUT(6), sys_health reads/writes HEALTH(100)
        let a = sim_node("sys_input",  vec![6],   vec![6]);
        let b = sim_node("sys_health", vec![100], vec![100]);
        let report = HazardDetector::detect(&a, &b);
        assert!(!report.has_hazards());
        assert!(HazardDetector::is_parallel_safe(&a, &b));
    }

    #[test]
    fn no_hazard_when_both_only_read() {
        // Two systems both reading TRANSFORM — safe to run in parallel
        let a = sim_node("sys_a", vec![1], vec![]);
        let b = sim_node("sys_b", vec![1], vec![]);
        let report = HazardDetector::detect(&a, &b);
        assert!(!report.has_hazards());
    }

    // ── RAW Hazards ───────────────────────────────────────────────────────────

    #[test]
    fn raw_detected_a_writes_b_reads() {
        // sys_ai writes VELOCITY(5), sys_movement reads VELOCITY(5)
        let ai       = sim_node("sys_ai",       vec![160, 1], vec![5]);
        let movement = sim_node("sys_movement", vec![1, 5],   vec![1]);
        let report   = HazardDetector::detect(&ai, &movement);
        assert!(report.has_raw());
        assert!(report.raw_hazard_type_ids.contains(&5));
        // Edge: sys_ai → sys_movement (ai must run before movement)
        let edge = report.edges.iter()
            .find(|e| e.edge_type == EdgeType::ReadAfterWrite)
            .expect("RAW edge must exist");
        assert_eq!(edge.from_system, "sys_ai");
        assert_eq!(edge.to_system, "sys_movement");
    }

    #[test]
    fn raw_detected_b_writes_a_reads() {
        // sys_movement reads TRANSFORM(1), sys_ai writes TRANSFORM(1)
        let movement = sim_node("sys_movement", vec![1, 5], vec![1]);
        let init     = sim_node("sys_init",     vec![],     vec![1]); // writes TRANSFORM
        let report   = HazardDetector::detect(&movement, &init);
        assert!(report.has_raw());
        // Edge: sys_init → sys_movement
        let edge = report.edges.iter()
            .find(|e| e.edge_type == EdgeType::ReadAfterWrite)
            .expect("RAW edge must exist");
        assert_eq!(edge.from_system, "sys_init");
        assert_eq!(edge.to_system, "sys_movement");
    }

    #[test]
    fn raw_involves_correct_component_ids() {
        let a = sim_node("sys_a", vec![],  vec![1, 5]); // writes TRANSFORM and VELOCITY
        let b = sim_node("sys_b", vec![5], vec![]);     // reads VELOCITY only
        let report = HazardDetector::detect(&a, &b);
        assert!(report.raw_hazard_type_ids.contains(&5));
        assert!(!report.raw_hazard_type_ids.contains(&1)); // b doesn't read TRANSFORM
    }

    // ── WAW Conflicts ─────────────────────────────────────────────────────────

    #[test]
    fn waw_detected_both_write_same_component() {
        let a = sim_node("sys_movement", vec![1, 5], vec![1]);
        let b = sim_node("sys_physics",  vec![1],    vec![1]); // both write TRANSFORM
        let report = HazardDetector::detect(&a, &b);
        assert!(report.has_waw());
        assert!(report.waw_conflict_type_ids.contains(&1));
    }

    #[test]
    fn waw_tie_break_lexicographic() {
        // "sys_movement" < "sys_physics" → sys_movement runs first
        let movement = sim_node("sys_movement", vec![], vec![1]);
        let physics  = sim_node("sys_physics",  vec![], vec![1]);
        let report   = HazardDetector::detect(&movement, &physics);
        let waw_edge = report.edges.iter()
            .find(|e| e.edge_type == EdgeType::WriteAfterWrite)
            .expect("WAW edge must exist");
        assert_eq!(waw_edge.from_system, "sys_movement"); // lex smaller = first
        assert_eq!(waw_edge.to_system,   "sys_physics");
    }

    #[test]
    fn waw_tie_break_reversed_order_same_result() {
        // Order of arguments to detect() must not change the tie-break result
        let movement = sim_node("sys_movement", vec![], vec![1]);
        let physics  = sim_node("sys_physics",  vec![], vec![1]);

        let report_ab = HazardDetector::detect(&movement, &physics);
        let report_ba = HazardDetector::detect(&physics, &movement);

        let edge_ab = report_ab.edges.iter()
            .find(|e| e.edge_type == EdgeType::WriteAfterWrite).unwrap();
        let edge_ba = report_ba.edges.iter()
            .find(|e| e.edge_type == EdgeType::WriteAfterWrite).unwrap();

        // Tie-break is deterministic regardless of argument order
        assert_eq!(edge_ab.from_system, edge_ba.from_system,
            "WAW tie-break must be argument-order independent (D11)");
        assert_eq!(edge_ab.to_system, edge_ba.to_system);
    }

    #[test]
    fn waw_multiple_components_all_reported() {
        let a = sim_node("sys_a", vec![], vec![1, 5, 100]);
        let b = sim_node("sys_b", vec![], vec![1, 5]);     // writes TRANSFORM and VELOCITY
        let report = HazardDetector::detect(&a, &b);
        assert!(report.waw_conflict_type_ids.contains(&1));
        assert!(report.waw_conflict_type_ids.contains(&5));
        assert!(!report.waw_conflict_type_ids.contains(&100)); // b doesn't write HEALTH
    }

    // ── Combined RAW + WAW ────────────────────────────────────────────────────

    #[test]
    fn both_raw_and_waw_detected() {
        // sys_a writes TRANSFORM(1) and VELOCITY(5)
        // sys_b reads VELOCITY(5) and writes TRANSFORM(1) → RAW(5) + WAW(1)
        let a = sim_node("sys_a", vec![], vec![1, 5]);
        let b = sim_node("sys_b", vec![5], vec![1]);
        let report = HazardDetector::detect(&a, &b);
        assert!(report.has_raw()); // b reads 5 written by a
        assert!(report.has_waw()); // both write 1
    }

    // ── Parallel Safety ───────────────────────────────────────────────────────

    #[test]
    fn parallel_safe_true_when_no_overlap() {
        let a = sim_node("sys_input",  vec![6],   vec![6]);
        let b = sim_node("sys_health", vec![100], vec![100]);
        assert!(HazardDetector::is_parallel_safe(&a, &b));
    }

    #[test]
    fn parallel_safe_false_when_raw_exists() {
        let a = sim_node("sys_a", vec![], vec![1]);
        let b = sim_node("sys_b", vec![1], vec![]);
        assert!(!HazardDetector::is_parallel_safe(&a, &b));
    }

    #[test]
    fn parallel_safe_false_when_waw_exists() {
        let a = sim_node("sys_a", vec![], vec![5]);
        let b = sim_node("sys_b", vec![], vec![5]);
        assert!(!HazardDetector::is_parallel_safe(&a, &b));
    }

    // ── Detect WAW / RAW isolated ─────────────────────────────────────────────

    #[test]
    fn detect_waw_isolated() {
        let a = sim_node("sys_a", vec![], vec![1, 5]);
        let b = sim_node("sys_b", vec![], vec![5, 100]);
        let waw = HazardDetector::detect_waw(&a, &b);
        assert!(waw.contains(&5));
        assert!(!waw.contains(&1));
        assert!(!waw.contains(&100));
    }

    #[test]
    fn detect_raw_isolated() {
        let writer = sim_node("sys_writer", vec![], vec![1, 5]);
        let reader = sim_node("sys_reader", vec![5], vec![]);
        let raw = HazardDetector::detect_raw_a_to_b(&writer, &reader);
        assert!(raw.contains(&5));
        assert!(!raw.contains(&1));
    }
}