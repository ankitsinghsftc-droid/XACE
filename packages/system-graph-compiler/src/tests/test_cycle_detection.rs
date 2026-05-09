use xace_core::runtime::phase_enum::PhaseEnum;
use xace_core::schema::system_definition::{ExecutionPhase, SystemDefinition, SystemVersion};

use xace_system_graph_compiler::compilation_error::CompilationError;
use xace_system_graph_compiler::cycle_detection::cycle_detector::CycleDetector;
use xace_system_graph_compiler::cycle_detection::cycle_diagnostics::CycleDiagnosticReport;
use xace_system_graph_compiler::graph_construction::graph_construction_layer::GraphConstructionLayer;
use xace_system_graph_compiler::graph_construction::system_edge::{RawSystemGraph, SystemEdge};
use xace_system_graph_compiler::graph_construction::system_node::SystemNode;
use xace_system_graph_compiler::phase_segmentation::phase_segmentation_layer::{
    PhaseBucket, PhaseSegmentationLayer,
};
use xace_system_graph_compiler::sgc_pipeline::SgcPipeline;

use std::collections::BTreeMap;

// ── Helpers ───────────────────────────────────────────────────────────────────

fn def(id: &str, phase: ExecutionPhase, reads: Vec<u32>, writes: Vec<u32>, deps: Vec<&str>) -> SystemDefinition {
    SystemDefinition {
        id: id.into(), display_name: id.into(), phase, reads, writes,
        depends_on: deps.into_iter().map(String::from).collect(),
        deterministic: true, version: SystemVersion::INITIAL, description: String::new(),
    }
}

fn sim(id: &str, reads: Vec<u32>, writes: Vec<u32>) -> SystemDefinition {
    def(id, ExecutionPhase::Simulation, reads, writes, vec![])
}

fn make_bucket(nodes: &[&str], edges: &[(&str, &str)]) -> PhaseBucket {
    PhaseBucket {
        phase: PhaseEnum::Simulation,
        nodes: nodes.iter().map(|&id| (id.to_string(), SystemNode::new(id, PhaseEnum::Simulation))).collect(),
        edges: edges.iter().map(|&(from, to)| {
            ((from.to_string(), to.to_string()), SystemEdge::explicit_dependency(from, to))
        }).collect(),
    }
}

fn check_defs(defs: &[SystemDefinition]) -> Result<(), CompilationError> {
    let graph   = GraphConstructionLayer::build(defs)?;
    let buckets = PhaseSegmentationLayer::segment(&graph)?;
    for bucket in &buckets { CycleDetector::check(bucket)?; }
    Ok(())
}

// ── Acyclic — no false positives ──────────────────────────────────────────────

#[test]
fn empty_graph_is_acyclic() { assert!(check_defs(&[]).is_ok()); }

#[test]
fn single_system_is_acyclic() {
    assert!(check_defs(&[sim("sys_a", vec![], vec![])]).is_ok());
}

#[test]
fn two_independent_systems_acyclic() {
    assert!(check_defs(&[sim("sys_a", vec![6], vec![6]), sim("sys_b", vec![100], vec![100])]).is_ok());
}

#[test]
fn linear_chain_three_systems_acyclic() {
    let defs = vec![
        sim("sys_a", vec![], vec![]),
        def("sys_b", ExecutionPhase::Simulation, vec![], vec![], vec!["sys_a"]),
        def("sys_c", ExecutionPhase::Simulation, vec![], vec![], vec!["sys_b"]),
    ];
    assert!(check_defs(&defs).is_ok());
}

#[test]
fn diamond_graph_acyclic() {
    let defs = vec![
        sim("sys_root", vec![], vec![]),
        def("sys_left",  ExecutionPhase::Simulation, vec![], vec![], vec!["sys_root"]),
        def("sys_right", ExecutionPhase::Simulation, vec![], vec![], vec!["sys_root"]),
        def("sys_sink",  ExecutionPhase::Simulation, vec![], vec![], vec!["sys_left", "sys_right"]),
    ];
    assert!(check_defs(&defs).is_ok());
}

#[test]
fn raw_chain_is_acyclic() {
    let defs = vec![sim("sys_writer", vec![], vec![5]), sim("sys_reader", vec![5], vec![])];
    assert!(check_defs(&defs).is_ok());
}

// ── Simple 2-node cycles ──────────────────────────────────────────────────────

#[test]
fn two_node_explicit_cycle_detected() {
    let bucket = make_bucket(&["sys_a", "sys_b"], &[("sys_a", "sys_b"), ("sys_b", "sys_a")]);
    assert!(CycleDetector::check(&bucket).unwrap_err().is_cycle());
}

#[test]
fn two_node_cycle_path_length_is_two() {
    let bucket = make_bucket(&["sys_a", "sys_b"], &[("sys_a", "sys_b"), ("sys_b", "sys_a")]);
    if let Err(CompilationError::Cycle(ce)) = CycleDetector::check(&bucket) {
        assert_eq!(ce.cycle_path.len(), 2);
    } else { panic!("Expected Cycle error"); }
}

#[test]
fn two_node_cycle_stage_is_cycle_detection() {
    let bucket = make_bucket(&["sys_a", "sys_b"], &[("sys_a", "sys_b"), ("sys_b", "sys_a")]);
    assert_eq!(CycleDetector::check(&bucket).unwrap_err().stage(), "CycleDetection");
}

// ── Multi-node cycles ─────────────────────────────────────────────────────────

#[test]
fn three_node_cycle_detected() {
    let bucket = make_bucket(
        &["sys_a", "sys_b", "sys_c"],
        &[("sys_a", "sys_b"), ("sys_b", "sys_c"), ("sys_c", "sys_a")],
    );
    assert!(CycleDetector::check(&bucket).unwrap_err().is_cycle());
}

#[test]
fn three_node_cycle_path_length_is_three() {
    let bucket = make_bucket(
        &["sys_a", "sys_b", "sys_c"],
        &[("sys_a", "sys_b"), ("sys_b", "sys_c"), ("sys_c", "sys_a")],
    );
    if let Err(CompilationError::Cycle(ce)) = CycleDetector::check(&bucket) {
        assert_eq!(ce.cycle_path.len(), 3);
    } else { panic!("Expected Cycle error"); }
}

#[test]
fn four_node_cycle_detected() {
    let bucket = make_bucket(
        &["sys_a", "sys_b", "sys_c", "sys_d"],
        &[("sys_a","sys_b"),("sys_b","sys_c"),("sys_c","sys_d"),("sys_d","sys_a")],
    );
    assert!(CycleDetector::check(&bucket).is_err());
}

#[test]
fn cycle_with_acyclic_tail_detected() {
    let bucket = make_bucket(
        &["sys_a", "sys_b", "sys_x"],
        &[("sys_x", "sys_a"), ("sys_a", "sys_b"), ("sys_b", "sys_a")],
    );
    assert!(CycleDetector::check(&bucket).is_err());
}

#[test]
fn disconnected_one_cyclic_one_acyclic_detected() {
    let bucket = PhaseBucket {
        phase: PhaseEnum::Simulation,
        nodes: ["sys_p","sys_q","sys_r","sys_s"].iter()
            .map(|&id| (id.to_string(), SystemNode::new(id, PhaseEnum::Simulation))).collect(),
        edges: {
            let mut m = BTreeMap::new();
            m.insert(("sys_p".into(),"sys_q".into()), SystemEdge::explicit_dependency("sys_p","sys_q"));
            m.insert(("sys_r".into(),"sys_s".into()), SystemEdge::explicit_dependency("sys_r","sys_s"));
            m.insert(("sys_s".into(),"sys_r".into()), SystemEdge::explicit_dependency("sys_s","sys_r"));
            m
        },
    };
    assert!(CycleDetector::check(&bucket).is_err());
}

// ── Cycle path normalization (D11) ────────────────────────────────────────────

#[test]
fn cycle_path_starts_at_lex_minimum() {
    let bucket = make_bucket(
        &["sys_a", "sys_b", "sys_c"],
        &[("sys_c","sys_a"),("sys_a","sys_b"),("sys_b","sys_c")],
    );
    if let Err(CompilationError::Cycle(ce)) = CycleDetector::check(&bucket) {
        assert_eq!(ce.cycle_path[0], "sys_a", "Normalized cycle must start at lex-smallest (D11)");
    } else { panic!("Expected Cycle error"); }
}

#[test]
fn normalize_cycle_standalone() {
    let cases: Vec<(Vec<&str>, Vec<&str>)> = vec![
        (vec!["sys_c","sys_a","sys_b"], vec!["sys_a","sys_b","sys_c"]),
        (vec!["sys_z","sys_a"],         vec!["sys_a","sys_z"]),
        (vec!["sys_a","sys_b","sys_c"], vec!["sys_a","sys_b","sys_c"]),
    ];
    for (input, expected) in cases {
        let inp: Vec<String> = input.iter().map(|s| s.to_string()).collect();
        let exp: Vec<String> = expected.iter().map(|s| s.to_string()).collect();
        assert_eq!(CycleDetector::normalize_cycle(inp), exp);
    }
}

// ── PhaseOrder edge exclusion ─────────────────────────────────────────────────

#[test]
fn phase_order_back_edge_not_a_cycle() {
    let bucket = PhaseBucket {
        phase: PhaseEnum::Simulation,
        nodes: {
            let mut m = BTreeMap::new();
            m.insert("sys_a".into(), SystemNode::new("sys_a", PhaseEnum::Simulation));
            m.insert("sys_b".into(), SystemNode::new("sys_b", PhaseEnum::Simulation));
            m
        },
        edges: {
            let mut m = BTreeMap::new();
            m.insert(("sys_a".into(),"sys_b".into()), SystemEdge::explicit_dependency("sys_a","sys_b"));
            m.insert(("sys_b".into(),"sys_a".into()), SystemEdge::phase_order("sys_b","sys_a"));
            m
        },
    };
    assert!(CycleDetector::check(&bucket).is_ok(), "PhaseOrder back-edge must not be treated as a cycle");
}

// ── CycleError payload ────────────────────────────────────────────────────────

#[test]
fn cycle_error_has_description_and_suggestions() {
    let bucket = make_bucket(&["sys_a","sys_b"], &[("sys_a","sys_b"),("sys_b","sys_a")]);
    if let Err(CompilationError::Cycle(ce)) = CycleDetector::check(&bucket) {
        assert!(!ce.description.is_empty());
        assert!(!ce.suggestions.is_empty());
    } else { panic!("Expected Cycle error"); }
}

#[test]
fn cycle_error_edge_types_match_path_length() {
    let bucket = make_bucket(
        &["sys_a","sys_b","sys_c"],
        &[("sys_a","sys_b"),("sys_b","sys_c"),("sys_c","sys_a")],
    );
    if let Err(CompilationError::Cycle(ce)) = CycleDetector::check(&bucket) {
        assert_eq!(ce.edge_types.len(), ce.cycle_path.len());
    } else { panic!("Expected Cycle error"); }
}

#[test]
fn cycle_display_closes_back_to_start() {
    let bucket = make_bucket(&["sys_a","sys_b"], &[("sys_a","sys_b"),("sys_b","sys_a")]);
    if let Err(CompilationError::Cycle(ce)) = CycleDetector::check(&bucket) {
        assert!(ce.cycle_display().ends_with("sys_a"));
    } else { panic!("Expected Cycle error"); }
}

// ── CycleDiagnosticReport ─────────────────────────────────────────────────────

#[test]
fn diagnostic_report_builds_for_explicit_cycle() {
    let bucket = make_bucket(&["sys_a","sys_b"], &[("sys_a","sys_b"),("sys_b","sys_a")]);
    if let Err(CompilationError::Cycle(ce)) = CycleDetector::check(&bucket) {
        let report = CycleDiagnosticReport::build(&ce, &bucket);
        assert_eq!(report.edge_reports.len(), 2);
        assert!(!report.strategies.is_empty());
        assert!(report.has_breakable_edge());
        assert!(report.easiest_strategy().is_some());
    } else { panic!("Expected Cycle error"); }
}

#[test]
fn diagnostic_strategies_sorted_by_difficulty() {
    let bucket = make_bucket(
        &["sys_a","sys_b","sys_c"],
        &[("sys_a","sys_b"),("sys_b","sys_c"),("sys_c","sys_a")],
    );
    if let Err(CompilationError::Cycle(ce)) = CycleDetector::check(&bucket) {
        let report = CycleDiagnosticReport::build(&ce, &bucket);
        let ranks: Vec<u8> = report.strategies.iter().map(|s| s.difficulty_rank()).collect();
        for w in ranks.windows(2) { assert!(w[0] <= w[1], "Strategies must be sorted Low→High"); }
    } else { panic!("Expected Cycle error"); }
}

#[test]
fn diagnostic_easiest_strategy_is_low_for_explicit_cycle() {
    let bucket = make_bucket(&["sys_a","sys_b"], &[("sys_a","sys_b"),("sys_b","sys_a")]);
    if let Err(CompilationError::Cycle(ce)) = CycleDetector::check(&bucket) {
        let report = CycleDiagnosticReport::build(&ce, &bucket);
        assert_eq!(report.easiest_strategy().unwrap().difficulty, "Low");
    } else { panic!("Expected Cycle error"); }
}

#[test]
fn diagnostic_summary_names_systems() {
    let bucket = make_bucket(&["sys_alpha","sys_beta"], &[("sys_alpha","sys_beta"),("sys_beta","sys_alpha")]);
    if let Err(CompilationError::Cycle(ce)) = CycleDetector::check(&bucket) {
        let report = CycleDiagnosticReport::build(&ce, &bucket);
        assert!(report.summary.contains("sys_alpha") && report.summary.contains("sys_beta"));
    } else { panic!("Expected Cycle error"); }
}

// ── Full pipeline ─────────────────────────────────────────────────────────────

#[test]
fn detect_in_graph_catches_cycle_before_scheduling() {
    let mut graph = RawSystemGraph::new();
    graph.add_node(SystemNode::new("sys_a", PhaseEnum::Simulation));
    graph.add_node(SystemNode::new("sys_b", PhaseEnum::Simulation));
    graph.add_edge(SystemEdge::explicit_dependency("sys_a", "sys_b"));
    graph.add_edge(SystemEdge::explicit_dependency("sys_b", "sys_a"));
    let err = CycleDetector::detect_in_graph(&graph).unwrap_err();
    assert!(err.is_cycle());
    assert_eq!(err.stage(), "CycleDetection");
}

#[test]
fn acyclic_graph_compiles_to_plan() {
    let defs = vec![sim("sys_a", vec![], vec![5]), sim("sys_b", vec![5], vec![])];
    assert!(SgcPipeline::compile(&defs, "0.1.0", 1).is_ok());
}

// ── Zombie chase — must always be acyclic ─────────────────────────────────────

#[test]
fn zombie_chase_all_buckets_acyclic() {
    let defs = vec![
        sim("InputSystem",    vec![6, 1],     vec![5]),
        sim("MovementSystem", vec![5, 1],     vec![1]),
        sim("AISystem",       vec![160, 1],   vec![5, 101]),
        sim("DamageSystem",   vec![101, 100], vec![100, 101]),
        sim("DeathSystem",    vec![100],      vec![]),
    ];
    let graph   = GraphConstructionLayer::build(&defs).unwrap();
    let buckets = PhaseSegmentationLayer::segment(&graph).unwrap();
    for bucket in &buckets {
        assert!(CycleDetector::check(bucket).is_ok());
    }
}

#[test]
fn zombie_chase_full_pipeline_succeeds() {
    let defs = vec![
        sim("InputSystem",    vec![6, 1],     vec![5]),
        sim("MovementSystem", vec![5, 1],     vec![1]),
        sim("AISystem",       vec![160, 1],   vec![5, 101]),
        sim("DamageSystem",   vec![101, 100], vec![100, 101]),
        sim("DeathSystem",    vec![100],      vec![]),
    ];
    let plan = SgcPipeline::compile_and_verify(&defs, "0.1.0", 1).unwrap();
    assert_eq!(plan.total_system_count(), 5);
    assert!(!plan.plan_hash.is_empty());
}

// ── Determinism (D11) ─────────────────────────────────────────────────────────

#[test]
fn cycle_detection_deterministic_same_error_twice() {
    let bucket = make_bucket(
        &["sys_a","sys_b","sys_c"],
        &[("sys_a","sys_b"),("sys_b","sys_c"),("sys_c","sys_a")],
    );
    let r1 = CycleDetector::check(&bucket);
    let r2 = CycleDetector::check(&bucket);
    match (r1, r2) {
        (Err(CompilationError::Cycle(ce1)), Err(CompilationError::Cycle(ce2))) => {
            assert_eq!(ce1.cycle_path, ce2.cycle_path, "Must be deterministic (D11)");
        }
        _ => panic!("Both runs must return identical Cycle errors"),
    }
}