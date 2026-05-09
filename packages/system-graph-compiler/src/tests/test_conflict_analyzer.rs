//! Integration tests for the Conflict Analyzer.
//! Verifies known conflict patterns and serialization group correctness.

#[cfg(test)]
mod tests {
    use xace_core::runtime::phase_enum::PhaseEnum;
    use xace_core::schema::system_definition::SystemDefinition;
    use crate::conflict_analyzer::conflict_analyzer::ConflictAnalyzer;
    use crate::conflict_analyzer::serialization_group_builder::SerializationGroupBuilder;
    use crate::graph_construction::graph_construction_layer::GraphConstructionLayer;
    use crate::phase_segmentation::phase_segmentation_layer::PhaseSegmentationLayer;

    fn sim(id: &str, reads: Vec<u32>, writes: Vec<u32>) -> SystemDefinition {
        SystemDefinition { id: id.into(), phase: PhaseEnum::Simulation, reads, writes,
            depends_on: vec![], deterministic: true, version: 1 }
    }

    fn analyze(defs: &[SystemDefinition]) -> crate::conflict_analyzer::conflict_analyzer::ConflictReport {
        let g = GraphConstructionLayer::build(defs).unwrap();
        let b = PhaseSegmentationLayer::segment(&g).unwrap();
        ConflictAnalyzer::analyze(&b, &g).unwrap()
    }

    // ── Conflict-free patterns ────────────────────────────────────────────────

    #[test]
    fn no_conflicts_when_completely_independent() {
        let r = analyze(&[sim("s_a", vec![6], vec![6]), sim("s_b", vec![100], vec![100])]);
        assert!(r.is_conflict_free());
        assert!(r.can_parallelize("s_a", "s_b", PhaseEnum::Simulation));
    }

    #[test]
    fn read_only_systems_no_conflict() {
        let r = analyze(&[sim("s_a", vec![1,5], vec![]), sim("s_b", vec![1,100], vec![])]);
        assert!(r.is_conflict_free());
    }

    // ── WAW conflict patterns ─────────────────────────────────────────────────

    #[test]
    fn waw_produces_write_conflict_entry() {
        let r = analyze(&[sim("s_a", vec![], vec![1]), sim("s_b", vec![], vec![1])]);
        assert_eq!(r.write_conflicts.len(), 1);
        assert!(r.write_conflicts[0].component_type_ids.contains(&1));
    }

    #[test]
    fn multiple_waw_components_all_reported() {
        let r = analyze(&[sim("s_a", vec![], vec![1,5]), sim("s_b", vec![], vec![1,5,100])]);
        let c = &r.write_conflicts[0];
        assert!(c.component_type_ids.contains(&1));
        assert!(c.component_type_ids.contains(&5));
        assert!(!c.component_type_ids.contains(&100)); // s_a doesn't write 100
    }

    #[test]
    fn waw_forces_serialization() {
        let r = analyze(&[sim("s_a", vec![], vec![5]), sim("s_b", vec![], vec![5])]);
        assert!(r.must_serialize("s_a", "s_b", PhaseEnum::Simulation));
        assert!(!r.can_parallelize("s_a", "s_b", PhaseEnum::Simulation));
    }

    // ── RAW hazard patterns ───────────────────────────────────────────────────

    #[test]
    fn raw_hazard_detected_and_forces_serialization() {
        let r = analyze(&[sim("writer", vec![], vec![5]), sim("reader", vec![5], vec![])]);
        assert!(!r.read_write_hazards.is_empty());
        assert!(r.must_serialize("writer", "reader", PhaseEnum::Simulation));
    }

    #[test]
    fn bidirectional_raw_both_detected() {
        // s_a writes X, s_b reads X; s_b writes Y, s_a reads Y
        let r = analyze(&[sim("s_a", vec![5], vec![1]), sim("s_b", vec![1], vec![5])]);
        assert!(r.read_write_hazards.len() >= 2, "Both RAW directions must be detected");
    }

    // ── Serialization groups ──────────────────────────────────────────────────

    #[test]
    fn transitive_conflicts_same_group() {
        // s_a ↔ s_b, s_b ↔ s_c → all three in one group
        let r = analyze(&[
            sim("s_a", vec![], vec![1,5]),
            sim("s_b", vec![5], vec![1]),
            sim("s_c", vec![1], vec![]),
        ]);
        let groups = r.groups_for_phase(PhaseEnum::Simulation);
        let constrained: Vec<_> = groups.iter().filter(|g| g.is_constrained()).collect();
        assert!(constrained.iter().any(|g| g.members.len() == 3),
            "Transitively conflicting systems must share a group");
    }

    #[test]
    fn independent_pairs_in_separate_groups() {
        let r = analyze(&[
            sim("s_a", vec![], vec![1]), sim("s_b", vec![], vec![1]), // pair 1
            sim("s_c", vec![], vec![5]), sim("s_d", vec![], vec![5]), // pair 2
        ]);
        assert!(!r.must_serialize("s_a", "s_c", PhaseEnum::Simulation));
        assert!(r.must_serialize("s_a",  "s_b", PhaseEnum::Simulation));
        assert!(r.must_serialize("s_c",  "s_d", PhaseEnum::Simulation));
    }

    #[test]
    fn conflict_report_counts_total_systems() {
        let r = analyze(&[
            sim("s_a", vec![], vec![]), sim("s_b", vec![], vec![]),
            sim("s_c", vec![], vec![]), sim("s_d", vec![], vec![]),
        ]);
        assert_eq!(r.total_systems_analyzed, 4);
    }

    // ── Safe parallel groups ──────────────────────────────────────────────────

    #[test]
    fn three_way_independent_all_parallel() {
        let r = analyze(&[
            sim("s_a", vec![6],   vec![6]),
            sim("s_b", vec![100], vec![100]),
            sim("s_c", vec![160], vec![]),
        ]);
        assert!(r.can_parallelize("s_a", "s_b", PhaseEnum::Simulation));
        assert!(r.can_parallelize("s_b", "s_c", PhaseEnum::Simulation));
        assert!(r.can_parallelize("s_a", "s_c", PhaseEnum::Simulation));
    }

    // ── Zombie chase known pattern ────────────────────────────────────────────

    #[test]
    fn zombie_chase_all_expected_constraints() {
        let r = analyze(&[
            sim("InputSystem",    vec![6, 1],     vec![5]),
            sim("MovementSystem", vec![5, 1],     vec![1]),
            sim("AISystem",       vec![160, 1],   vec![5, 101]),
            sim("DamageSystem",   vec![101, 100], vec![100, 101]),
            sim("DeathSystem",    vec![100],      vec![]),
        ]);
        let ph = PhaseEnum::Simulation;
        // WAW on VELOCITY(5): InputSystem ↔ AISystem
        assert!(r.must_serialize("InputSystem", "AISystem", ph));
        // RAW on VELOCITY(5): AI/Input → MovementSystem
        assert!(r.must_serialize("AISystem", "MovementSystem", ph));
        assert!(r.must_serialize("InputSystem", "MovementSystem", ph));
        // RAW on DAMAGE(101): AISystem → DamageSystem
        assert!(r.must_serialize("AISystem", "DamageSystem", ph));
        // RAW on HEALTH(100): DamageSystem → DeathSystem
        assert!(r.must_serialize("DamageSystem", "DeathSystem", ph));
    }
}