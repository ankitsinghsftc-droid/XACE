//! # System Node
//!
//! A node in the raw system dependency graph, representing one system.
//! Carries the complete information needed by every downstream compiler stage:
//! system identity, phase assignment, component access declarations,
//! and explicit dependency list.
//!
//! ## Source
//! SystemNodes are built by the GraphConstructionLayer from SystemDefinitions
//! in the CompiledSchemaPackage. One node per registered system.
//!
//! ## Determinism (D11)
//! BTreeSet is used for all sets (reads, writes, depends_on) to guarantee
//! deterministic iteration order regardless of insertion order.
//! The graph_construction_layer builds nodes from schema definitions which
//! may arrive in any order — BTreeSet normalises them.

use std::collections::BTreeSet;
use xace_core::runtime::phase_enum::PhaseEnum;

// ── System Node ───────────────────────────────────────────────────────────────

/// A node in the raw system dependency graph.
///
/// Represents one game system. All sets use BTreeSet for deterministic
/// iteration (D11). Created by GraphConstructionLayer from SystemDefinitions.
#[derive(Debug, Clone)]
pub struct SystemNode {
    /// Unique system identifier. Matches SystemDefinition.id and ISystem::system_id().
    /// Used for RNG seeding (D6) and ExecutionPlan ordering.
    pub system_id: String,

    /// The simulation phase this system runs in.
    /// Initialization → Input → Simulation → PostSimulation → Cleanup.
    pub phase: PhaseEnum,

    /// Component type IDs this system reads.
    /// Matches SystemDefinition.reads. BTreeSet for deterministic iteration.
    pub read_set: BTreeSet<u32>,

    /// Component type IDs this system writes (via MutationGate).
    /// Matches SystemDefinition.writes. BTreeSet for deterministic iteration.
    pub write_set: BTreeSet<u32>,

    /// Explicit dependencies declared in SystemDefinition.depends_on.
    /// These are enforced regardless of read/write overlap.
    pub depends_on: BTreeSet<String>,

    /// Whether this system is declared deterministic in the schema.
    /// Non-deterministic systems cannot be part of parallel execution groups.
    pub deterministic: bool,

    /// Schema version of the system definition this node was built from.
    pub version: u32,
}

impl SystemNode {
    /// Creates a new SystemNode with the given identity and phase.
    pub fn new(system_id: impl Into<String>, phase: PhaseEnum) -> Self {
        Self {
            system_id: system_id.into(),
            phase,
            read_set: BTreeSet::new(),
            write_set: BTreeSet::new(),
            depends_on: BTreeSet::new(),
            deterministic: true,
            version: 1,
        }
    }

    /// Builder: sets the read component type IDs.
    pub fn with_reads(mut self, reads: impl IntoIterator<Item = u32>) -> Self {
        self.read_set = reads.into_iter().collect();
        self
    }

    /// Builder: sets the write component type IDs.
    pub fn with_writes(mut self, writes: impl IntoIterator<Item = u32>) -> Self {
        self.write_set = writes.into_iter().collect();
        self
    }

    /// Builder: sets explicit dependencies.
    pub fn with_depends_on(mut self, deps: impl IntoIterator<Item = String>) -> Self {
        self.depends_on = deps.into_iter().collect();
        self
    }

    /// Builder: marks the system as non-deterministic.
    pub fn non_deterministic(mut self) -> Self {
        self.deterministic = false;
        self
    }

    /// Builder: sets the schema version.
    pub fn with_version(mut self, version: u32) -> Self {
        self.version = version;
        self
    }

    // ── Queries ───────────────────────────────────────────────────────────────

    /// Returns true if this system reads the given component type.
    pub fn reads(&self, component_type_id: u32) -> bool {
        self.read_set.contains(&component_type_id)
    }

    /// Returns true if this system writes the given component type.
    pub fn writes(&self, component_type_id: u32) -> bool {
        self.write_set.contains(&component_type_id)
    }

    /// Returns the set of component type IDs that this system both reads and writes.
    pub fn read_write_overlap(&self) -> BTreeSet<u32> {
        self.read_set
            .intersection(&self.write_set)
            .copied()
            .collect()
    }

    /// Returns the component type IDs written by both this node and another.
    /// These are the WAW (write-after-write) conflict candidates.
    pub fn write_overlap_with(&self, other: &SystemNode) -> BTreeSet<u32> {
        self.write_set
            .intersection(&other.write_set)
            .copied()
            .collect()
    }

    /// Returns the component type IDs written by this node that the other reads.
    /// These are the RAW (read-after-write) hazard candidates.
    /// `self` writes → `other` reads → `other` must run after `self`.
    pub fn raw_hazard_with(&self, other: &SystemNode) -> BTreeSet<u32> {
        self.write_set
            .intersection(&other.read_set)
            .copied()
            .collect()
    }

    /// Returns true if this system has an explicit dependency on `other_id`.
    pub fn explicitly_depends_on(&self, other_id: &str) -> bool {
        self.depends_on.contains(other_id)
    }

    /// Returns true if this system can participate in parallel execution.
    /// A system is parallel-eligible if it is deterministic and has no
    /// write conflicts that force serialization (checked by scheduler).
    pub fn is_parallel_eligible(&self) -> bool {
        self.deterministic
    }
}

impl PartialEq for SystemNode {
    fn eq(&self, other: &Self) -> bool {
        self.system_id == other.system_id
    }
}

impl Eq for SystemNode {}

impl PartialOrd for SystemNode {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for SystemNode {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        // Lexicographic ordering by system_id (D11)
        self.system_id.cmp(&other.system_id)
    }
}

impl std::fmt::Display for SystemNode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "SystemNode('{}', phase={:?}, reads={:?}, writes={:?})",
            self.system_id, self.phase, self.read_set, self.write_set
        )
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn movement_node() -> SystemNode {
        SystemNode::new("sys_movement", PhaseEnum::Simulation)
            .with_reads([1, 5]) // TRANSFORM, VELOCITY
            .with_writes([1]) // TRANSFORM
    }

    fn ai_node() -> SystemNode {
        SystemNode::new("sys_ai", PhaseEnum::Simulation)
            .with_reads([160, 1]) // AI, TRANSFORM
            .with_writes([5, 101]) // VELOCITY, DAMAGE
    }

    fn velocity_node() -> SystemNode {
        SystemNode::new("sys_velocity", PhaseEnum::Simulation)
            .with_reads([5, 1])
            .with_writes([1]) // also writes TRANSFORM — WAW with movement
    }

    #[test]
    fn reads_and_writes_correct() {
        let n = movement_node();
        assert!(n.reads(1));
        assert!(n.reads(5));
        assert!(n.writes(1));
        assert!(!n.writes(5)); // reads velocity, doesn't write it
    }

    #[test]
    fn waw_overlap_detected() {
        let movement = movement_node();
        let velocity = velocity_node();
        let overlap = movement.write_overlap_with(&velocity);
        assert!(overlap.contains(&1), "Both write TRANSFORM — WAW hazard");
    }

    #[test]
    fn no_waw_when_different_writes() {
        let movement = movement_node();
        let ai = ai_node();
        let overlap = movement.write_overlap_with(&ai);
        assert!(
            overlap.is_empty(),
            "movement writes [1], ai writes [5,101] — no WAW"
        );
    }

    #[test]
    fn raw_hazard_movement_after_ai() {
        let ai = ai_node(); // writes VELOCITY (5)
        let movement = movement_node(); // reads VELOCITY (5)
        let hazard = ai.raw_hazard_with(&movement);
        assert!(
            hazard.contains(&5),
            "ai writes VELOCITY that movement reads — RAW hazard"
        );
    }

    #[test]
    fn no_raw_hazard_when_no_overlap() {
        let movement = movement_node(); // writes TRANSFORM (1)
        let ai = ai_node(); // reads AI (160), TRANSFORM (1)
                            // movement writes 1, ai reads 1 → ai must run after movement
        let hazard = movement.raw_hazard_with(&ai);
        assert!(hazard.contains(&1));
    }

    #[test]
    fn explicit_dependency() {
        let n =
            SystemNode::new("sys_b", PhaseEnum::Simulation).with_depends_on(["sys_a".to_string()]);
        assert!(n.explicitly_depends_on("sys_a"));
        assert!(!n.explicitly_depends_on("sys_c"));
    }

    #[test]
    fn ordering_is_lexicographic() {
        let a = SystemNode::new("sys_a", PhaseEnum::Simulation);
        let b = SystemNode::new("sys_b", PhaseEnum::Simulation);
        let z = SystemNode::new("sys_z", PhaseEnum::Simulation);
        assert!(a < b);
        assert!(b < z);
        assert!(a < z);
    }

    #[test]
    fn parallel_eligible_when_deterministic() {
        let n = SystemNode::new("sys_x", PhaseEnum::Simulation);
        assert!(n.is_parallel_eligible());
    }

    #[test]
    fn not_parallel_eligible_when_non_deterministic() {
        let n = SystemNode::new("sys_x", PhaseEnum::Simulation).non_deterministic();
        assert!(!n.is_parallel_eligible());
    }

    #[test]
    fn read_write_overlap_detected() {
        // A system that reads and writes the same component
        let n = SystemNode::new("sys_rw", PhaseEnum::Simulation)
            .with_reads([1, 5])
            .with_writes([1]); // reads and writes TRANSFORM
        let overlap = n.read_write_overlap();
        assert!(overlap.contains(&1));
        assert!(!overlap.contains(&5)); // only reads 5
    }
}
