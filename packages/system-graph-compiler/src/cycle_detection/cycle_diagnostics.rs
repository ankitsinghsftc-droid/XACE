//! # Cycle Diagnostics — SGC Companion to CycleDetector
//!
//! Produces human-readable diagnostic reports for detected cycles.
//! Enriches a `CycleError` with per-edge analysis and ranked resolution
//! strategies so the designer knows exactly which dependency to break and how.
//!
//! ## Usage
//! Called by the builder UI and Design Mentor after a `CompilationError::Cycle`
//! is returned by the SGC pipeline. The pipeline itself does not call this —
//! it returns the raw `CycleError`. The caller opts in to the richer report.
//!
//! ```rust
//! if let Err(CompilationError::Cycle(ref ce)) = result {
//!     let report = CycleDiagnosticReport::build(ce, &bucket);
//!     println!("{}", report.summary);
//!     for strategy in &report.strategies {
//!         println!("  [{}] {}", strategy.difficulty, strategy.description);
//!     }
//! }
//! ```
//!
//! ## Strategy Ranking
//! Strategies are ordered: lowest developer effort first.
//! Low < Medium < High difficulty. Within the same difficulty, more targeted
//! strategies (pointing at a specific edge) are listed before generic ones.
//!
//! ## Determinism (D11)
//! All per-edge iteration uses cycle_path index order, which is already
//! normalized to start from the lex-smallest system_id by CycleDetector.
//! Strategy lists are built in a fixed order — same CycleError always
//! produces an identical CycleDiagnosticReport.

use crate::compilation_error::{CycleError, EdgeType};
use crate::phase_segmentation::phase_segmentation_layer::PhaseBucket;

// ── Resolution Strategy ───────────────────────────────────────────────────────

/// A concrete, actionable suggestion for how to break a detected cycle.
///
/// Strategies are ranked: lowest difficulty first inside `strategies` vec.
#[derive(Debug, Clone)]
pub struct ResolutionStrategy {
    /// Short label — suitable for a UI button or menu item.
    /// Example: "Remove explicit dependency 'sys_a' → 'sys_b'"
    pub label: String,

    /// Full plain-English description of what the developer should do.
    pub description: String,

    /// The specific (from, to) edge this strategy targets, if any.
    /// None for generic suggestions that apply to the whole cycle.
    pub target_edge: Option<(String, String)>,

    /// Developer effort estimate: "Low" | "Medium" | "High".
    pub difficulty: &'static str,
}

impl ResolutionStrategy {
    // ── Factories (ordered roughly Low → High effort) ─────────────────────────

    fn remove_explicit_dependency(from: &str, to: &str) -> Self {
        Self {
            label: format!("Remove explicit depends_on: '{}' → '{}'", from, to),
            description: format!(
                "The explicit dependency from '{}' to '{}' may be redundant. \
                 If the read/write declarations already enforce this ordering, \
                 removing this depends_on entry breaks the cycle without \
                 changing execution behaviour.",
                from, to
            ),
            target_edge: Some((from.to_string(), to.to_string())),
            difficulty: "Low",
        }
    }

    fn move_to_earlier_phase(system_id: &str) -> Self {
        Self {
            label: format!("Move '{}' to an earlier phase", system_id),
            description: format!(
                "If '{}' only consumes data from the previous tick, consider \
                 moving it to Initialization or an earlier phase. Systems in \
                 different phases cannot form a dependency cycle.",
                system_id
            ),
            target_edge: None,
            difficulty: "Low",
        }
    }

    fn split_system(from: &str, to: &str) -> Self {
        Self {
            label: format!("Split '{}' into read-only and write-only systems", from),
            description: format!(
                "Divide '{}' into two systems: one that only reads the \
                 shared component(s), and one that only writes them. \
                 This eliminates the dependency edge to '{}' and breaks the cycle.",
                from, to
            ),
            target_edge: Some((from.to_string(), to.to_string())),
            difficulty: "Medium",
        }
    }

    fn introduce_intermediary(from: &str, to: &str) -> Self {
        Self {
            label: format!(
                "Introduce an intermediary component between '{}' and '{}'",
                from, to
            ),
            description: format!(
                "Create a new 'intent' or 'request' component. '{}' writes its \
                 desired outcome into the new component. '{}' reads from it instead \
                 of depending on '{}' directly. This decouples the cycle into a \
                 one-way data flow.",
                from, to, from
            ),
            target_edge: Some((from.to_string(), to.to_string())),
            difficulty: "High",
        }
    }

    fn generic_from_cycle_error(label: String, description: String) -> Self {
        Self {
            label,
            description,
            target_edge: None,
            difficulty: "Medium",
        }
    }

    /// Returns the numeric difficulty rank for sorting (Low=0, Medium=1, High=2).
    pub fn difficulty_rank(&self) -> u8 {
        match self.difficulty {
            "Low" => 0,
            "Medium" => 1,
            _ => 2,
        }
    }
}

// ── Cycle Edge Report ─────────────────────────────────────────────────────────

/// Detailed analysis of one directed edge in the detected cycle.
#[derive(Debug, Clone)]
pub struct CycleEdgeReport {
    /// System that must run first (the "from" side of the constraint).
    pub from_system: String,
    /// System that must run after `from_system`.
    pub to_system: String,
    /// Why this ordering constraint exists.
    pub edge_type: EdgeType,
    /// Human-readable description of the constraint source.
    pub reason: String,
    /// Whether this edge is a candidate for removal to break the cycle.
    ///
    /// ExplicitDependency and WriteAfterWrite edges are breakable —
    /// the developer can restructure to eliminate them.
    /// ReadAfterWrite edges are harder to break — they reflect real data flow.
    pub is_breakable: bool,
}

impl CycleEdgeReport {
    /// Returns a one-line description suitable for a UI diff view.
    pub fn short_label(&self) -> String {
        format!(
            "{} → {} [{}]{}",
            self.from_system,
            self.to_system,
            self.edge_type,
            if self.is_breakable {
                " ← breakable"
            } else {
                ""
            }
        )
    }
}

// ── Cycle Diagnostic Report ───────────────────────────────────────────────────

/// Full diagnostic report for a detected cycle.
///
/// Enriches `CycleError` with:
/// - Per-edge breakdown (type, reason, breakable flag)
/// - Ranked resolution strategies (lowest effort first)
/// - Plain-English summary for builder UI display
///
/// Deterministic: same `CycleError` + same `PhaseBucket` → identical report (D11).
#[derive(Debug, Clone)]
pub struct CycleDiagnosticReport {
    /// The original cycle error from the SGC pipeline.
    pub cycle_error: CycleError,

    /// Per-edge breakdown of the cycle, in cycle path order.
    /// Length == `cycle_error.cycle_path.len()`.
    /// The closing edge (last → first) is included at position `len - 1`.
    pub edge_reports: Vec<CycleEdgeReport>,

    /// Resolution strategies ranked by difficulty (lowest first).
    /// Always contains at least the generic CycleError suggestions.
    pub strategies: Vec<ResolutionStrategy>,

    /// Plain-English summary suitable for builder UI display.
    /// No ECS vocabulary — describes the cycle in game-design terms.
    pub summary: String,
}

impl CycleDiagnosticReport {
    /// Builds a full diagnostic report from a `CycleError` and the `PhaseBucket`
    /// in which the cycle was detected.
    ///
    /// `bucket` is used to look up edge types and reasons for each cycle edge.
    /// If an edge is not found in the bucket (defensive), it is reported as
    /// ExplicitDependency with `is_breakable = true`.
    pub fn build(cycle_error: &CycleError, bucket: &PhaseBucket) -> Self {
        let edge_reports = Self::build_edge_reports(cycle_error, bucket);
        let strategies = Self::build_strategies(cycle_error, &edge_reports);
        let summary = Self::build_summary(cycle_error, &edge_reports);

        Self {
            cycle_error: cycle_error.clone(),
            edge_reports,
            strategies,
            summary,
        }
    }

    // ── Edge Reports ──────────────────────────────────────────────────────────

    /// Builds one CycleEdgeReport per edge in the cycle path,
    /// including the closing edge (last → first).
    fn build_edge_reports(cycle_error: &CycleError, bucket: &PhaseBucket) -> Vec<CycleEdgeReport> {
        let n = cycle_error.cycle_path.len();
        let mut reports = Vec::with_capacity(n);

        for i in 0..n {
            let from = &cycle_error.cycle_path[i];
            let to = &cycle_error.cycle_path[(i + 1) % n];
            let key = (from.clone(), to.clone());

            let (edge_type, reason, is_breakable) = bucket
                .edges
                .get(&key)
                .map(|e| {
                    // ExplicitDependency and WriteAfterWrite can be restructured away.
                    // ReadAfterWrite reflects real data flow — harder to break.
                    let breakable = matches!(
                        e.edge_type,
                        EdgeType::ExplicitDependency | EdgeType::WriteAfterWrite
                    );
                    (e.edge_type.clone(), e.reason.clone(), breakable)
                })
                .unwrap_or_else(|| {
                    // Edge not in bucket — defensive fallback.
                    (
                        EdgeType::ExplicitDependency,
                        format!("'{}' → '{}' (constraint source not found)", from, to),
                        true,
                    )
                });

            reports.push(CycleEdgeReport {
                from_system: from.clone(),
                to_system: to.clone(),
                edge_type,
                reason,
                is_breakable,
            });
        }

        reports
    }

    // ── Strategies ────────────────────────────────────────────────────────────

    /// Builds and ranks resolution strategies for the cycle.
    ///
    /// Priority order (lowest effort first):
    /// 1. Remove explicit dependencies (Low) — zero restructuring needed
    /// 2. Move lex-smallest system to earlier phase (Low) — phase reassignment
    /// 3. Split systems with WAW edges (Medium) — requires new system
    /// 4. Introduce intermediary components for RAW edges (High) — new component
    /// 5. Generic CycleError suggestions (Medium) — fallback
    fn build_strategies(
        cycle_error: &CycleError,
        edge_reports: &[CycleEdgeReport],
    ) -> Vec<ResolutionStrategy> {
        let mut strategies: Vec<ResolutionStrategy> = Vec::new();

        // 1. Remove explicit dependencies — cheapest fix.
        for report in edge_reports {
            if report.edge_type == EdgeType::ExplicitDependency {
                strategies.push(ResolutionStrategy::remove_explicit_dependency(
                    &report.from_system,
                    &report.to_system,
                ));
            }
        }

        // 2. Move the lex-smallest (first in normalized path) to an earlier phase.
        if let Some(first) = cycle_error.cycle_path.first() {
            strategies.push(ResolutionStrategy::move_to_earlier_phase(first));
        }

        // 3. Split systems for WAW edges.
        for report in edge_reports {
            if report.edge_type == EdgeType::WriteAfterWrite {
                strategies.push(ResolutionStrategy::split_system(
                    &report.from_system,
                    &report.to_system,
                ));
            }
        }

        // 4. Introduce intermediary component for RAW edges.
        for report in edge_reports {
            if report.edge_type == EdgeType::ReadAfterWrite {
                strategies.push(ResolutionStrategy::introduce_intermediary(
                    &report.from_system,
                    &report.to_system,
                ));
            }
        }

        // 5. Append generic suggestions from CycleError (deduplicated by position).
        for (i, suggestion) in cycle_error.suggestions.iter().enumerate() {
            let short = if suggestion.len() > 60 {
                format!("{}…", &suggestion[..57])
            } else {
                suggestion.clone()
            };
            strategies.push(ResolutionStrategy::generic_from_cycle_error(
                format!("General option {}: {}", i + 1, short),
                suggestion.clone(),
            ));
        }

        // Sort: lowest difficulty_rank first; stable sort preserves insertion order
        // within equal ranks (D11).
        strategies.sort_by_key(|s| s.difficulty_rank());
        strategies
    }

    // ── Summary ───────────────────────────────────────────────────────────────

    /// Builds a plain-English summary of the cycle for builder UI display.
    fn build_summary(cycle_error: &CycleError, edge_reports: &[CycleEdgeReport]) -> String {
        let path_str = cycle_error.cycle_display();

        let explicit_count = edge_reports
            .iter()
            .filter(|r| r.edge_type == EdgeType::ExplicitDependency)
            .count();
        let raw_count = edge_reports
            .iter()
            .filter(|r| r.edge_type == EdgeType::ReadAfterWrite)
            .count();
        let waw_count = edge_reports
            .iter()
            .filter(|r| r.edge_type == EdgeType::WriteAfterWrite)
            .count();

        let breakable_count = edge_reports.iter().filter(|r| r.is_breakable).count();

        format!(
            "Dependency cycle detected: {}\n\
             The system graph cannot be compiled until this cycle is broken.\n\
             Cycle contains {} edge(s): {} explicit, {} data-flow, {} write-conflict.\n\
             {} of {} edges can be removed or restructured to fix this.",
            path_str,
            edge_reports.len(),
            explicit_count,
            raw_count,
            waw_count,
            breakable_count,
            edge_reports.len()
        )
    }

    // ── Query helpers ─────────────────────────────────────────────────────────

    /// Returns only the breakable edges — candidates for removal to fix the cycle.
    pub fn breakable_edges(&self) -> Vec<&CycleEdgeReport> {
        self.edge_reports
            .iter()
            .filter(|r| r.is_breakable)
            .collect()
    }

    /// Returns the single easiest resolution strategy (lowest difficulty rank).
    /// Returns None only if the strategy list is empty (should never happen).
    pub fn easiest_strategy(&self) -> Option<&ResolutionStrategy> {
        self.strategies.iter().min_by_key(|s| s.difficulty_rank())
    }

    /// Returns true if the cycle contains at least one breakable edge.
    /// A cycle with no breakable edges requires a full redesign.
    pub fn has_breakable_edge(&self) -> bool {
        self.edge_reports.iter().any(|r| r.is_breakable)
    }

    /// Returns all strategies at the given difficulty level.
    pub fn strategies_at_difficulty(&self, difficulty: &str) -> Vec<&ResolutionStrategy> {
        self.strategies
            .iter()
            .filter(|s| s.difficulty == difficulty)
            .collect()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::compilation_error::{CycleError, EdgeType};
    use crate::graph_construction::system_edge::SystemEdge;
    use crate::graph_construction::system_node::SystemNode;
    use crate::phase_segmentation::phase_segmentation_layer::PhaseBucket;
    use std::collections::BTreeMap;
    use xace_core::runtime::phase_enum::PhaseEnum;

    // ── Helpers ───────────────────────────────────────────────────────────────

    /// Builds a PhaseBucket with explicit-dependency edges for testing.
    fn make_bucket(nodes: &[&str], edges: &[(&str, &str, EdgeType)]) -> PhaseBucket {
        PhaseBucket {
            phase: PhaseEnum::Simulation,
            nodes: nodes
                .iter()
                .map(|&id| (id.to_string(), SystemNode::new(id, PhaseEnum::Simulation)))
                .collect(),
            edges: edges
                .iter()
                .map(|&(from, to, ref et)| {
                    let key = (from.to_string(), to.to_string());
                    let edge = match et {
                        EdgeType::ExplicitDependency => SystemEdge::explicit_dependency(from, to),
                        EdgeType::ReadAfterWrite => SystemEdge::read_after_write(from, to, vec![1]),
                        EdgeType::WriteAfterWrite => {
                            SystemEdge::write_after_write(from, to, vec![1])
                        }
                        EdgeType::PhaseOrder => SystemEdge::phase_order(from, to),
                    };
                    (key, edge)
                })
                .collect(),
        }
    }

    /// Builds a CycleError directly (normalized path already assumed correct).
    fn make_cycle_error(path: &[&str], edge_types: &[EdgeType]) -> CycleError {
        CycleError::new(
            path.iter().map(|s| s.to_string()).collect(),
            edge_types.to_vec(),
        )
    }

    // ── Report construction ───────────────────────────────────────────────────

    #[test]
    fn two_node_explicit_cycle_report() {
        let bucket = make_bucket(
            &["sys_a", "sys_b"],
            &[
                ("sys_a", "sys_b", EdgeType::ExplicitDependency),
                ("sys_b", "sys_a", EdgeType::ExplicitDependency),
            ],
        );
        let ce = make_cycle_error(&["sys_a", "sys_b"], &[EdgeType::ExplicitDependency; 2]);
        let report = CycleDiagnosticReport::build(&ce, &bucket);

        assert_eq!(
            report.edge_reports.len(),
            2,
            "Two edges in a two-node cycle"
        );
        assert!(
            report.edge_reports.iter().all(|r| r.is_breakable),
            "ExplicitDependency edges are always breakable"
        );
        assert!(!report.summary.is_empty());
        assert!(!report.strategies.is_empty());
    }

    #[test]
    fn three_node_mixed_edge_cycle_report() {
        // sys_a →(explicit) sys_b →(RAW) sys_c →(WAW) sys_a
        let bucket = make_bucket(
            &["sys_a", "sys_b", "sys_c"],
            &[
                ("sys_a", "sys_b", EdgeType::ExplicitDependency),
                ("sys_b", "sys_c", EdgeType::ReadAfterWrite),
                ("sys_c", "sys_a", EdgeType::WriteAfterWrite),
            ],
        );
        let ce = make_cycle_error(
            &["sys_a", "sys_b", "sys_c"],
            &[
                EdgeType::ExplicitDependency,
                EdgeType::ReadAfterWrite,
                EdgeType::WriteAfterWrite,
            ],
        );
        let report = CycleDiagnosticReport::build(&ce, &bucket);

        assert_eq!(report.edge_reports.len(), 3);

        // sys_a→sys_b (explicit) and sys_c→sys_a (WAW) are breakable
        let breakable = report.breakable_edges();
        assert_eq!(breakable.len(), 2, "explicit + WAW edges are breakable");

        // sys_b→sys_c (RAW) is NOT breakable
        let raw_report = report
            .edge_reports
            .iter()
            .find(|r| r.edge_type == EdgeType::ReadAfterWrite)
            .unwrap();
        assert!(!raw_report.is_breakable);
    }

    // ── Edge reports ──────────────────────────────────────────────────────────

    #[test]
    fn edge_reports_include_closing_edge() {
        // Cycle: [sys_a, sys_b] — edges are sys_a→sys_b AND sys_b→sys_a (closing).
        let bucket = make_bucket(
            &["sys_a", "sys_b"],
            &[
                ("sys_a", "sys_b", EdgeType::ExplicitDependency),
                ("sys_b", "sys_a", EdgeType::ExplicitDependency),
            ],
        );
        let ce = make_cycle_error(&["sys_a", "sys_b"], &[EdgeType::ExplicitDependency; 2]);
        let report = CycleDiagnosticReport::build(&ce, &bucket);

        // Must have the closing edge sys_b → sys_a
        let closing = report
            .edge_reports
            .iter()
            .find(|r| r.from_system == "sys_b")
            .unwrap();
        assert_eq!(closing.to_system, "sys_a");
    }

    #[test]
    fn edge_report_short_label_includes_edge_type() {
        let bucket = make_bucket(
            &["sys_a", "sys_b"],
            &[
                ("sys_a", "sys_b", EdgeType::ExplicitDependency),
                ("sys_b", "sys_a", EdgeType::ExplicitDependency),
            ],
        );
        let ce = make_cycle_error(&["sys_a", "sys_b"], &[EdgeType::ExplicitDependency; 2]);
        let report = CycleDiagnosticReport::build(&ce, &bucket);

        for er in &report.edge_reports {
            let label = er.short_label();
            assert!(label.contains("→"), "label must contain arrow");
            assert!(
                label.contains("EXPLICIT_DEPENDENCY") || label.contains("breakable"),
                "label must identify edge type or breakability"
            );
        }
    }

    #[test]
    fn missing_edge_in_bucket_uses_fallback() {
        // Bucket has no edges — CycleDiagnosticReport must handle this gracefully.
        let bucket = make_bucket(&["sys_a", "sys_b"], &[]);
        let ce = make_cycle_error(&["sys_a", "sys_b"], &[EdgeType::ExplicitDependency; 2]);
        let report = CycleDiagnosticReport::build(&ce, &bucket);
        // Should still produce edge reports (fallback path)
        assert_eq!(report.edge_reports.len(), 2);
    }

    // ── Strategy ranking ──────────────────────────────────────────────────────

    #[test]
    fn strategies_sorted_by_difficulty_rank() {
        let bucket = make_bucket(
            &["sys_a", "sys_b", "sys_c"],
            &[
                ("sys_a", "sys_b", EdgeType::ReadAfterWrite),
                ("sys_b", "sys_c", EdgeType::WriteAfterWrite),
                ("sys_c", "sys_a", EdgeType::ExplicitDependency),
            ],
        );
        let ce = make_cycle_error(
            &["sys_a", "sys_b", "sys_c"],
            &[
                EdgeType::ReadAfterWrite,
                EdgeType::WriteAfterWrite,
                EdgeType::ExplicitDependency,
            ],
        );
        let report = CycleDiagnosticReport::build(&ce, &bucket);

        // Verify non-decreasing difficulty order
        let ranks: Vec<u8> = report
            .strategies
            .iter()
            .map(|s| s.difficulty_rank())
            .collect();
        for window in ranks.windows(2) {
            assert!(
                window[0] <= window[1],
                "Strategies must be sorted Low → Medium → High: {:?}",
                ranks
            );
        }
    }

    #[test]
    fn explicit_dependency_strategy_is_low_difficulty() {
        let bucket = make_bucket(
            &["sys_a", "sys_b"],
            &[
                ("sys_a", "sys_b", EdgeType::ExplicitDependency),
                ("sys_b", "sys_a", EdgeType::ExplicitDependency),
            ],
        );
        let ce = make_cycle_error(&["sys_a", "sys_b"], &[EdgeType::ExplicitDependency; 2]);
        let report = CycleDiagnosticReport::build(&ce, &bucket);

        let low_strategies = report.strategies_at_difficulty("Low");
        assert!(
            !low_strategies.is_empty(),
            "Explicit dep cycle must have Low-difficulty strategies"
        );
        // Easiest strategy must be Low
        assert_eq!(report.easiest_strategy().unwrap().difficulty, "Low");
    }

    #[test]
    fn raw_only_cycle_has_no_breakable_edges() {
        let bucket = make_bucket(
            &["sys_a", "sys_b"],
            &[
                ("sys_a", "sys_b", EdgeType::ReadAfterWrite),
                ("sys_b", "sys_a", EdgeType::ReadAfterWrite),
            ],
        );
        let ce = make_cycle_error(&["sys_a", "sys_b"], &[EdgeType::ReadAfterWrite; 2]);
        let report = CycleDiagnosticReport::build(&ce, &bucket);
        assert!(
            !report.has_breakable_edge(),
            "RAW-only cycle has no breakable edges"
        );
    }

    // ── Summary ───────────────────────────────────────────────────────────────

    #[test]
    fn summary_contains_cycle_path() {
        let bucket = make_bucket(
            &["sys_a", "sys_b"],
            &[
                ("sys_a", "sys_b", EdgeType::ExplicitDependency),
                ("sys_b", "sys_a", EdgeType::ExplicitDependency),
            ],
        );
        let ce = make_cycle_error(&["sys_a", "sys_b"], &[EdgeType::ExplicitDependency; 2]);
        let report = CycleDiagnosticReport::build(&ce, &bucket);
        assert!(
            report.summary.contains("sys_a"),
            "Summary must name cycle systems"
        );
        assert!(report.summary.contains("sys_b"));
    }

    #[test]
    fn summary_contains_edge_counts() {
        let bucket = make_bucket(
            &["sys_a", "sys_b", "sys_c"],
            &[
                ("sys_a", "sys_b", EdgeType::ExplicitDependency),
                ("sys_b", "sys_c", EdgeType::ReadAfterWrite),
                ("sys_c", "sys_a", EdgeType::WriteAfterWrite),
            ],
        );
        let ce = make_cycle_error(
            &["sys_a", "sys_b", "sys_c"],
            &[
                EdgeType::ExplicitDependency,
                EdgeType::ReadAfterWrite,
                EdgeType::WriteAfterWrite,
            ],
        );
        let report = CycleDiagnosticReport::build(&ce, &bucket);
        // Summary must mention the total edge count
        assert!(
            report.summary.contains('3') || report.summary.contains("three"),
            "Summary must reference the number of edges"
        );
    }

    // ── easiest_strategy ──────────────────────────────────────────────────────

    #[test]
    fn easiest_strategy_returns_some_for_non_empty_cycle() {
        let bucket = make_bucket(
            &["sys_a", "sys_b"],
            &[
                ("sys_a", "sys_b", EdgeType::ExplicitDependency),
                ("sys_b", "sys_a", EdgeType::ExplicitDependency),
            ],
        );
        let ce = make_cycle_error(&["sys_a", "sys_b"], &[EdgeType::ExplicitDependency; 2]);
        let report = CycleDiagnosticReport::build(&ce, &bucket);
        assert!(report.easiest_strategy().is_some());
    }

    // ── Zombie chase — should never reach diagnostics ─────────────────────────

    #[test]
    fn zombie_chase_graph_is_acyclic_no_report_needed() {
        use crate::cycle_detection::cycle_detector::CycleDetector;
        use crate::graph_construction::graph_construction_layer::GraphConstructionLayer;
        use crate::phase_segmentation::phase_segmentation_layer::PhaseSegmentationLayer;
        use xace_core::schema::system_definition::{
            ExecutionPhase, SystemDefinition, SystemVersion,
        };

        fn def(id: &str, reads: Vec<u32>, writes: Vec<u32>) -> SystemDefinition {
            SystemDefinition {
                id: id.into(),
                display_name: id.into(),
                phase: ExecutionPhase::Simulation,
                reads,
                writes,
                depends_on: vec![],
                deterministic: true,
                version: SystemVersion::INITIAL,
                description: String::new(),
            }
        }

        let defs = vec![
            def("InputSystem", vec![6, 1], vec![5]),
            def("MovementSystem", vec![5, 1], vec![1]),
            def("AISystem", vec![160, 1], vec![5, 101]),
            def("DamageSystem", vec![101, 100], vec![100, 101]),
            def("DeathSystem", vec![100], vec![]),
        ];

        let graph = GraphConstructionLayer::build(&defs).unwrap();
        let buckets = PhaseSegmentationLayer::segment(&graph).unwrap();

        for bucket in &buckets {
            let result = CycleDetector::check(bucket);
            assert!(
                result.is_ok(),
                "Zombie chase must be acyclic — no diagnostic report needed"
            );
        }
    }
}
