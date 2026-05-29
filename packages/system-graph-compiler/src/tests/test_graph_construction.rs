//! Integration tests for Graph Construction Layer.
//! Verifies all 4 edge types, tie-breaking, validation, and output determinism.

#[cfg(test)]
mod tests {
    use crate::compilation_error::EdgeType;
    use crate::graph_construction::graph_construction_layer::GraphConstructionLayer;
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
    fn sim(id: &str, reads: Vec<u32>, writes: Vec<u32>) -> SystemDefinition {
        def(id, PhaseEnum::Simulation, reads, writes, vec![])
    }

    // ── EXPLICIT_DEPENDENCY edges ─────────────────────────────────────────────

    #[test]
    fn explicit_dep_edge_type_and_direction() {
        let defs = vec![
            sim("sys_a", vec![], vec![]),
            def(
                "sys_b",
                PhaseEnum::Simulation,
                vec![],
                vec![],
                vec!["sys_a"],
            ),
        ];
        let g = GraphConstructionLayer::build(&defs).unwrap();
        let e = g.edges.get(&("sys_a".into(), "sys_b".into())).unwrap();
        assert_eq!(e.edge_type, EdgeType::ExplicitDependency);
        assert_eq!(e.from_system, "sys_a");
        assert_eq!(e.to_system, "sys_b");
    }

    #[test]
    fn self_dependency_rejected() {
        let defs = vec![def(
            "sys_a",
            PhaseEnum::Simulation,
            vec![],
            vec![],
            vec!["sys_a"],
        )];
        assert!(GraphConstructionLayer::build(&defs).is_err());
    }

    // ── READ_AFTER_WRITE edges ────────────────────────────────────────────────

    #[test]
    fn raw_edge_generated_single_component() {
        let defs = vec![sim("sys_a", vec![], vec![5]), sim("sys_b", vec![5], vec![])];
        let g = GraphConstructionLayer::build(&defs).unwrap();
        let key = ("sys_a".into(), "sys_b".into());
        assert_eq!(g.edges[&key].edge_type, EdgeType::ReadAfterWrite);
        assert!(g.edges[&key].involved_component_type_ids.contains(&5));
    }

    #[test]
    fn raw_edge_multiple_components() {
        let defs = vec![
            sim("writer", vec![], vec![1, 5, 100]),
            sim("reader", vec![5, 100], vec![]),
        ];
        let g = GraphConstructionLayer::build(&defs).unwrap();
        let key = ("writer".into(), "reader".into());
        let ids = &g.edges[&key].involved_component_type_ids;
        assert!(ids.contains(&5));
        assert!(ids.contains(&100));
        assert!(!ids.contains(&1)); // reader doesn't read 1
    }

    // ── WRITE_AFTER_WRITE edges ───────────────────────────────────────────────

    #[test]
    fn waw_edge_lex_smaller_from() {
        let defs = vec![sim("sys_z", vec![], vec![1]), sim("sys_a", vec![], vec![1])];
        let g = GraphConstructionLayer::build(&defs).unwrap();
        let key = ("sys_a".into(), "sys_z".into());
        assert!(
            g.edges.contains_key(&key),
            "sys_a (lex smaller) must be 'from'"
        );
        assert_eq!(g.edges[&key].edge_type, EdgeType::WriteAfterWrite);
    }

    #[test]
    fn waw_tie_break_argument_order_independent() {
        let order_az = vec![sim("sys_a", vec![], vec![1]), sim("sys_z", vec![], vec![1])];
        let order_za = vec![sim("sys_z", vec![], vec![1]), sim("sys_a", vec![], vec![1])];
        let g1 = GraphConstructionLayer::build(&order_az).unwrap();
        let g2 = GraphConstructionLayer::build(&order_za).unwrap();
        let keys1: Vec<_> = g1.edges.keys().collect();
        let keys2: Vec<_> = g2.edges.keys().collect();
        assert_eq!(
            keys1, keys2,
            "WAW direction must not depend on input order (D11)"
        );
    }

    // ── PHASE_ORDER edges ─────────────────────────────────────────────────────

    #[test]
    fn phase_order_direction_is_always_earlier_to_later() {
        let defs = vec![
            def(
                "sys_post",
                PhaseEnum::PostSimulation,
                vec![],
                vec![],
                vec![],
            ),
            def("sys_cleanup", PhaseEnum::Cleanup, vec![], vec![], vec![]),
            def(
                "sys_init",
                PhaseEnum::Initialization,
                vec![],
                vec![],
                vec![],
            ),
        ];
        let g = GraphConstructionLayer::build(&defs).unwrap();
        for ((_from, _to), edge) in &g.edges {
            if edge.edge_type == EdgeType::PhaseOrder {
                let fn_node = g.nodes.get(&edge.from_system).unwrap();
                let to_node = g.nodes.get(&edge.to_system).unwrap();
                assert!(
                    fn_node.phase.as_u8() < to_node.phase.as_u8(),
                    "PHASE_ORDER must always go from earlier to later phase"
                );
            }
        }
    }

    // ── ExplicitDependency beats PhaseOrder ───────────────────────────────────

    #[test]
    fn explicit_dep_beats_phase_order_for_same_pair() {
        let defs = vec![
            def(
                "sys_init",
                PhaseEnum::Initialization,
                vec![],
                vec![],
                vec![],
            ),
            def(
                "sys_sim",
                PhaseEnum::Simulation,
                vec![],
                vec![],
                vec!["sys_init"],
            ),
        ];
        let g = GraphConstructionLayer::build(&defs).unwrap();
        let key = ("sys_init".into(), "sys_sim".into());
        assert_eq!(
            g.edges[&key].edge_type,
            EdgeType::ExplicitDependency,
            "ExplicitDependency must override PhaseOrder (D11 priority)"
        );
    }

    // ── No spurious edges ─────────────────────────────────────────────────────

    #[test]
    fn no_edges_when_completely_independent_same_phase() {
        let defs = vec![
            sim("sys_a", vec![6], vec![6]),
            sim("sys_b", vec![100], vec![100]),
        ];
        let g = GraphConstructionLayer::build(&defs).unwrap();
        assert_eq!(g.edge_count(), 0);
    }

    // ── Determinism (D11) ─────────────────────────────────────────────────────

    #[test]
    fn node_and_edge_order_deterministic() {
        let defs_1 = vec![
            sim("s_z", vec![], vec![1]),
            sim("s_a", vec![1], vec![]),
            sim("s_m", vec![], vec![]),
        ];
        let defs_2 = vec![
            sim("s_m", vec![], vec![]),
            sim("s_z", vec![], vec![1]),
            sim("s_a", vec![1], vec![]),
        ];
        let g1 = GraphConstructionLayer::build(&defs_1).unwrap();
        let g2 = GraphConstructionLayer::build(&defs_2).unwrap();
        assert_eq!(
            g1.system_ids(),
            g2.system_ids(),
            "Node order must be deterministic (D11)"
        );
        let ek1: Vec<_> = g1.edges.keys().collect();
        let ek2: Vec<_> = g2.edges.keys().collect();
        assert_eq!(ek1, ek2, "Edge key order must be deterministic (D11)");
    }
}
