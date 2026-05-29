//! Integration tests for Dependency Resolution Engine.
//! Verifies topological sort correctness, stable ordering, and multi-system graphs.

#[cfg(test)]
mod tests {
    use crate::compilation_error::CompilationError;
    use crate::dependency_resolution::dependency_resolution_engine::DependencyResolutionEngine;
    use crate::graph_construction::graph_construction_layer::GraphConstructionLayer;
    use crate::phase_segmentation::phase_segmentation_layer::PhaseSegmentationLayer;
    use xace_core::runtime::phase_enum::PhaseEnum;
    use xace_core::schema::system_definition::SystemDefinition;

    fn def(
        id: &str,
        phase: PhaseEnum,
        reads: Vec<u32>,
        writes: Vec<u32>,
        deps: Vec<&str>,
    ) -> SystemDefinition {
        let mut def = SystemDefinition::with_spec(id, id, phase.into(), reads, writes);
        def.depends_on = deps.into_iter().map(String::from).collect();
        def
    }
    fn sim(id: &str, reads: Vec<u32>, writes: Vec<u32>, deps: Vec<&str>) -> SystemDefinition {
        def(id, PhaseEnum::Simulation, reads, writes, deps)
    }

    fn resolve(
        defs: &[SystemDefinition],
    ) -> crate::dependency_resolution::dependency_resolution_engine::OrderedGraph {
        let g = GraphConstructionLayer::build(defs).unwrap();
        let b = PhaseSegmentationLayer::segment(&g).unwrap();
        DependencyResolutionEngine::resolve(&b).unwrap()
    }

    // ── Ordering correctness ──────────────────────────────────────────────────

    #[test]
    fn simple_chain_ordered_root_to_leaf() {
        let defs = vec![
            sim("s_a", vec![], vec![], vec![]),
            sim("s_b", vec![], vec![], vec!["s_a"]),
            sim("s_c", vec![], vec![], vec!["s_b"]),
        ];
        let g = resolve(&defs);
        let sys = g.systems_in_phase(PhaseEnum::Simulation);
        assert_eq!(sys, &["s_a", "s_b", "s_c"]);
    }

    #[test]
    fn diamond_dep_root_first_leaf_last() {
        // s_a → s_b, s_a → s_c, s_b → s_d, s_c → s_d
        let defs = vec![
            sim("s_a", vec![], vec![], vec![]),
            sim("s_b", vec![], vec![], vec!["s_a"]),
            sim("s_c", vec![], vec![], vec!["s_a"]),
            sim("s_d", vec![], vec![], vec!["s_b", "s_c"]),
        ];
        let g = resolve(&defs);
        let sys = g.systems_in_phase(PhaseEnum::Simulation);
        assert_eq!(sys[0], "s_a", "Root must be first");
        assert_eq!(sys[3], "s_d", "Leaf must be last");
        let b = sys.iter().position(|s| s == "s_b").unwrap();
        let c = sys.iter().position(|s| s == "s_c").unwrap();
        let d = sys.iter().position(|s| s == "s_d").unwrap();
        assert!(b < d && c < d);
    }

    #[test]
    fn raw_hazard_forces_writer_before_reader() {
        let defs = vec![
            sim("reader", vec![5], vec![], vec![]),
            sim("writer", vec![], vec![5], vec![]),
        ];
        let g = resolve(&defs);
        let phase = g.phase(PhaseEnum::Simulation).unwrap();
        assert!(
            phase.is_before("writer", "reader"),
            "Writer must precede reader"
        );
    }

    #[test]
    fn waw_lex_smaller_runs_first() {
        let defs = vec![
            sim("sys_z", vec![], vec![1], vec![]),
            sim("sys_a", vec![], vec![1], vec![]),
        ];
        let g = resolve(&defs);
        let phase = g.phase(PhaseEnum::Simulation).unwrap();
        assert!(
            phase.is_before("sys_a", "sys_z"),
            "Lex-smaller runs first (D11)"
        );
    }

    // ── Multi-phase ordering ──────────────────────────────────────────────────

    #[test]
    fn multi_phase_phases_in_ordinal_order() {
        let defs = vec![
            def("s_post", PhaseEnum::PostSimulation, vec![], vec![], vec![]),
            def("s_init", PhaseEnum::Initialization, vec![], vec![], vec![]),
            def("s_sim", PhaseEnum::Simulation, vec![], vec![], vec![]),
        ];
        let g = resolve(&defs);
        let ordinals: Vec<u8> = g.phases.iter().map(|p| p.phase.as_u8()).collect();
        assert_eq!(ordinals, vec![0, 2, 3]); // Init, Sim, Post
    }

    #[test]
    fn global_position_cross_phase() {
        let defs = vec![
            def("s_init", PhaseEnum::Initialization, vec![], vec![], vec![]),
            sim("s_sim", vec![], vec![], vec![]),
        ];
        let g = resolve(&defs);
        let init_pos = g.global_position("s_init").unwrap();
        let sim_pos = g.global_position("s_sim").unwrap();
        assert!(
            init_pos < sim_pos,
            "Initialization must globally precede Simulation"
        );
    }

    // ── Stable ordering (D11) ─────────────────────────────────────────────────

    #[test]
    fn independent_systems_sorted_lexicographically() {
        let defs = vec![
            sim("s_z", vec![], vec![], vec![]),
            sim("s_a", vec![], vec![], vec![]),
            sim("s_m", vec![], vec![], vec![]),
            sim("s_b", vec![], vec![], vec![]),
        ];
        let g = resolve(&defs);
        let sys = g.systems_in_phase(PhaseEnum::Simulation);
        assert_eq!(
            sys,
            &["s_a", "s_b", "s_m", "s_z"],
            "Must be lex-sorted (D11)"
        );
    }

    #[test]
    fn ordering_identical_for_different_input_orders() {
        let make = |order: &[&str]| -> Vec<SystemDefinition> {
            order
                .iter()
                .map(|&id| sim(id, vec![], vec![], vec![]))
                .collect()
        };
        let o1 = resolve(&make(&["s_z", "s_a", "s_m"]));
        let o2 = resolve(&make(&["s_a", "s_m", "s_z"]));
        let o3 = resolve(&make(&["s_m", "s_z", "s_a"]));
        let sys1 = o1.systems_in_phase(PhaseEnum::Simulation);
        let sys2 = o2.systems_in_phase(PhaseEnum::Simulation);
        let sys3 = o3.systems_in_phase(PhaseEnum::Simulation);
        assert_eq!(sys1, sys2, "Input order must not affect output (D11)");
        assert_eq!(sys1, sys3, "Input order must not affect output (D11)");
    }

    // ── resolve_and_verify ────────────────────────────────────────────────────

    #[test]
    fn verify_succeeds_for_all_systems_present() {
        let defs = vec![
            sim("s_a", vec![], vec![], vec![]),
            sim("s_b", vec![], vec![], vec![]),
        ];
        let g = GraphConstructionLayer::build(&defs).unwrap();
        let b = PhaseSegmentationLayer::segment(&g).unwrap();
        assert!(DependencyResolutionEngine::resolve_and_verify(&b, 2).is_ok());
    }

    // ── Cycle detection via Kahn's ────────────────────────────────────────────

    #[test]
    fn cyclic_bucket_returns_cycle_error() {
        use crate::graph_construction::system_edge::SystemEdge;
        use crate::graph_construction::system_node::SystemNode;
        use crate::phase_segmentation::phase_segmentation_layer::PhaseBucket;
        use std::collections::BTreeMap;
        let bucket = PhaseBucket {
            phase: PhaseEnum::Simulation,
            nodes: {
                let mut m = BTreeMap::new();
                m.insert("s_a".into(), SystemNode::new("s_a", PhaseEnum::Simulation));
                m.insert("s_b".into(), SystemNode::new("s_b", PhaseEnum::Simulation));
                m
            },
            edges: {
                let mut m = BTreeMap::new();
                m.insert(
                    ("s_a".into(), "s_b".into()),
                    SystemEdge::explicit_dependency("s_a", "s_b"),
                );
                m.insert(
                    ("s_b".into(), "s_a".into()),
                    SystemEdge::explicit_dependency("s_b", "s_a"),
                );
                m
            },
        };
        let r = DependencyResolutionEngine::resolve(&[bucket]);
        assert!(r.is_err());
        assert!(r.unwrap_err().is_cycle());
    }

    // ── All systems accounted for ─────────────────────────────────────────────

    #[test]
    fn all_systems_present_in_resolved_graph() {
        let defs = vec![
            sim("InputSystem", vec![6, 1], vec![5], vec![]),
            sim("MovementSystem", vec![5, 1], vec![1], vec![]),
            sim("AISystem", vec![160, 1], vec![5, 101], vec![]),
            sim("DamageSystem", vec![101, 100], vec![100, 101], vec![]),
            sim("DeathSystem", vec![100], vec![], vec![]),
        ];
        let g = resolve(&defs);
        assert_eq!(g.total_system_count(), 5);
        let all = g.all_systems_in_order();
        assert!(all.contains(&"InputSystem"));
        assert!(all.contains(&"DeathSystem"));
    }
}
