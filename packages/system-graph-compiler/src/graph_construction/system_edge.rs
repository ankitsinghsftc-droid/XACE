//! # System Edge
//!
//! A directed edge in the raw system dependency graph.
//! Represents an ordering constraint between two systems.
//!
//! ## Edge Semantics
//! An edge (from_system → to_system) means:
//! `from_system` must complete before `to_system` begins.
//!
//! All four edge types produce the same runtime constraint —
//! the type is carried for diagnostics and cycle reporting only.
//!
//! ## Determinism (D11)
//! RawSystemGraph stores edges in BTreeMap<(from, to), SystemEdge>
//! keyed by ordered (from_system_id, to_system_id) pairs.
//! This guarantees deterministic edge iteration regardless of
//! insertion order in GraphConstructionLayer.

use crate::compilation_error::EdgeType;

// ── System Edge ───────────────────────────────────────────────────────────────

/// A directed ordering constraint between two systems.
///
/// from_system must execute before to_system.
/// Created by GraphConstructionLayer for each detected constraint.
#[derive(Debug, Clone)]
pub struct SystemEdge {
    /// The system that must execute FIRST.
    pub from_system: String,

    /// The system that must execute AFTER from_system.
    pub to_system: String,

    /// Why this constraint exists.
    pub edge_type: EdgeType,

    /// Human-readable explanation for diagnostics and cycle reporting.
    pub reason: String,

    /// Component type IDs involved in this constraint (for RAW/WAW edges).
    /// Empty for ExplicitDependency and PhaseOrder edges.
    pub involved_component_type_ids: Vec<u32>,
}

impl SystemEdge {
    // ── Factories ─────────────────────────────────────────────────────────────

    /// Creates an explicit dependency edge.
    /// `from_system` is listed in `to_system.depends_on`.
    pub fn explicit_dependency(from: impl Into<String>, to: impl Into<String>) -> Self {
        let f = from.into();
        let t = to.into();
        Self {
            reason: format!("'{}' is listed in depends_on of '{}'", f, t),
            from_system: f,
            to_system: t,
            edge_type: EdgeType::ExplicitDependency,
            involved_component_type_ids: Vec::new(),
        }
    }

    /// Creates a read-after-write hazard edge.
    /// `from_system` writes component type(s) that `to_system` reads.
    pub fn read_after_write(
        from: impl Into<String>,
        to: impl Into<String>,
        type_ids: Vec<u32>,
    ) -> Self {
        let f = from.into();
        let t = to.into();
        Self {
            reason: format!(
                "'{}' reads component(s) {:?} written by '{}' — RAW hazard",
                t, type_ids, f
            ),
            from_system: f,
            to_system: t,
            edge_type: EdgeType::ReadAfterWrite,
            involved_component_type_ids: type_ids,
        }
    }

    /// Creates a write-after-write conflict edge.
    /// Both systems write the same component type(s).
    /// Ordering is determined by lexicographic system_id tie-breaking.
    pub fn write_after_write(
        from: impl Into<String>,
        to: impl Into<String>,
        type_ids: Vec<u32>,
    ) -> Self {
        let f = from.into();
        let t = to.into();
        Self {
            reason: format!(
                "'{}' and '{}' both write component(s) {:?} — WAW conflict, \
                 serialised by lexicographic system_id",
                f, t, type_ids
            ),
            from_system: f,
            to_system: t,
            edge_type: EdgeType::WriteAfterWrite,
            involved_component_type_ids: type_ids,
        }
    }

    /// Creates a phase-order edge.
    /// `from_system` is in an earlier phase than `to_system`.
    pub fn phase_order(from: impl Into<String>, to: impl Into<String>) -> Self {
        let f = from.into();
        let t = to.into();
        Self {
            reason: format!(
                "'{}' is in an earlier phase than '{}' — global phase order enforced",
                f, t
            ),
            from_system: f,
            to_system: t,
            edge_type: EdgeType::PhaseOrder,
            involved_component_type_ids: Vec::new(),
        }
    }

    // ── Accessors ─────────────────────────────────────────────────────────────

    /// Returns the canonical deduplication key for this edge.
    /// BTreeMap<(String, String), SystemEdge> uses this as its key.
    pub fn key(&self) -> (String, String) {
        (self.from_system.clone(), self.to_system.clone())
    }

    /// Returns true if this edge creates a dependency that the topological
    /// sorter must respect (all four types do).
    pub fn is_ordering_constraint(&self) -> bool {
        true
    }

    /// Returns true if this edge involves component type access.
    pub fn involves_components(&self) -> bool {
        !self.involved_component_type_ids.is_empty()
    }

    /// Returns true if this is a cross-phase edge (PhaseOrder type).
    pub fn is_cross_phase(&self) -> bool {
        self.edge_type == EdgeType::PhaseOrder
    }
}

impl PartialEq for SystemEdge {
    fn eq(&self, other: &Self) -> bool {
        self.from_system == other.from_system
            && self.to_system == other.to_system
            && self.edge_type == other.edge_type
    }
}

impl Eq for SystemEdge {}

impl PartialOrd for SystemEdge {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for SystemEdge {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        // (from, to) lexicographic ordering (D11)
        self.from_system
            .cmp(&other.from_system)
            .then(self.to_system.cmp(&other.to_system))
    }
}

impl std::fmt::Display for SystemEdge {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "{} → {} [{}]: {}",
            self.from_system, self.to_system, self.edge_type, self.reason
        )
    }
}

// ── Raw System Graph ──────────────────────────────────────────────────────────

/// The complete raw dependency graph produced by GraphConstructionLayer.
///
/// All maps are BTreeMap for deterministic iteration (D11).
/// Consumed by downstream compiler stages in the SGC pipeline.
#[derive(Debug, Default)]
pub struct RawSystemGraph {
    /// All system nodes, keyed by system_id ascending (D11).
    pub nodes:
        std::collections::BTreeMap<String, crate::graph_construction::system_node::SystemNode>,

    /// All edges, keyed by (from_system_id, to_system_id) ascending (D11).
    /// One entry per unique (from, to) pair — deduplication prevents double-edges.
    pub edges: std::collections::BTreeMap<(String, String), SystemEdge>,
}

impl RawSystemGraph {
    pub fn new() -> Self {
        Self::default()
    }

    /// Adds a node. No-op if a node with this system_id already exists.
    pub fn add_node(&mut self, node: crate::graph_construction::system_node::SystemNode) {
        self.nodes.entry(node.system_id.clone()).or_insert(node);
    }

    /// Adds an edge. If an edge with the same (from, to) already exists,
    /// the higher-priority type wins: ExplicitDependency > RAW > WAW > PhaseOrder.
    pub fn add_edge(&mut self, edge: SystemEdge) {
        let key = edge.key();
        self.edges
            .entry(key)
            .and_modify(|existing| {
                // Higher-priority edge type takes precedence
                if edge.edge_type < existing.edge_type {
                    *existing = edge.clone();
                }
            })
            .or_insert(edge);
    }

    /// Returns all edges from the given system_id, sorted (D11).
    pub fn edges_from(&self, system_id: &str) -> Vec<&SystemEdge> {
        self.edges
            .iter()
            .filter(|((from, _), _)| from == system_id)
            .map(|(_, e)| e)
            .collect()
    }

    /// Returns all edges to the given system_id, sorted (D11).
    pub fn edges_to(&self, system_id: &str) -> Vec<&SystemEdge> {
        self.edges
            .iter()
            .filter(|((_, to), _)| to == system_id)
            .map(|(_, e)| e)
            .collect()
    }

    /// Returns all node IDs sorted ascending (D11).
    pub fn system_ids(&self) -> Vec<&str> {
        self.nodes.keys().map(|s| s.as_str()).collect()
    }

    pub fn node_count(&self) -> usize {
        self.nodes.len()
    }
    pub fn edge_count(&self) -> usize {
        self.edges.len()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::graph_construction::system_node::SystemNode;
    use xace_core::runtime::phase_enum::PhaseEnum;

    #[test]
    fn explicit_dependency_edge() {
        let e = SystemEdge::explicit_dependency("sys_a", "sys_b");
        assert_eq!(e.from_system, "sys_a");
        assert_eq!(e.to_system, "sys_b");
        assert_eq!(e.edge_type, EdgeType::ExplicitDependency);
        assert!(e.reason.contains("depends_on"));
        assert!(!e.involves_components());
    }

    #[test]
    fn raw_edge_involves_components() {
        let e = SystemEdge::read_after_write("sys_a", "sys_b", vec![1, 5]);
        assert_eq!(e.edge_type, EdgeType::ReadAfterWrite);
        assert!(e.involves_components());
        assert!(e.reason.contains("RAW"));
    }

    #[test]
    fn waw_edge_reason_contains_both_systems() {
        let e = SystemEdge::write_after_write("sys_a", "sys_b", vec![1]);
        assert_eq!(e.edge_type, EdgeType::WriteAfterWrite);
        assert!(e.reason.contains("sys_a"));
        assert!(e.reason.contains("sys_b"));
    }

    #[test]
    fn phase_order_edge_is_cross_phase() {
        let e = SystemEdge::phase_order("sys_init", "sys_sim");
        assert!(e.is_cross_phase());
        assert!(!e.involves_components());
    }

    #[test]
    fn edge_ordering_lexicographic() {
        let e1 = SystemEdge::explicit_dependency("sys_a", "sys_b");
        let e2 = SystemEdge::explicit_dependency("sys_a", "sys_c");
        let e3 = SystemEdge::explicit_dependency("sys_b", "sys_a");
        assert!(e1 < e2); // same from, b < c
        assert!(e2 < e3); // sys_a < sys_b
    }

    #[test]
    fn raw_system_graph_deduplicates_edges() {
        let mut g = RawSystemGraph::new();
        // Add same (from, to) pair twice — second should not duplicate
        g.add_edge(SystemEdge::phase_order("sys_a", "sys_b"));
        g.add_edge(SystemEdge::explicit_dependency("sys_a", "sys_b")); // higher priority
                                                                       // Should be exactly 1 edge, with ExplicitDependency winning
        assert_eq!(g.edge_count(), 1);
        let edge = g.edges.values().next().unwrap();
        assert_eq!(edge.edge_type, EdgeType::ExplicitDependency);
    }

    #[test]
    fn raw_system_graph_edges_from() {
        let mut g = RawSystemGraph::new();
        g.add_edge(SystemEdge::phase_order("sys_a", "sys_b"));
        g.add_edge(SystemEdge::phase_order("sys_a", "sys_c"));
        g.add_edge(SystemEdge::phase_order("sys_b", "sys_c"));
        let from_a = g.edges_from("sys_a");
        assert_eq!(from_a.len(), 2);
    }

    #[test]
    fn raw_system_graph_system_ids_sorted() {
        let mut g = RawSystemGraph::new();
        g.add_node(SystemNode::new("sys_z", PhaseEnum::Simulation));
        g.add_node(SystemNode::new("sys_a", PhaseEnum::Simulation));
        g.add_node(SystemNode::new("sys_m", PhaseEnum::Simulation));
        let ids = g.system_ids();
        assert_eq!(ids, vec!["sys_a", "sys_m", "sys_z"]);
    }
}
