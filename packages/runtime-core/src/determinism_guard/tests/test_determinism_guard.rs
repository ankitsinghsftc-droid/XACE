//! # Determinism Guard Integration Tests
//!
//! Tests every D-rule violation path, every guard mode, and the full
//! multi-module pipeline (DeterminismGuard + WorldHasher + ReplayValidator
//! + RngInterceptor) working together.
//!
//! ## Coverage Map
//! D1  — hook_system_execute rejects unregistered system
//! D2  — validated by entity_store tests (Phase 2); guard enforces via world_hash
//! D3  — validated by entity_store sorted iteration; guard detects via hash mismatch
//! D4  — validated by mutation_gate tests (Phase 3); guard enforces via world_hash
//! D5  — validated by event_bus tests (Phase 4); guard detects via hash mismatch
//! D6  — RngInterceptor::report_illegal_rng + hook_rng_access
//! D7  — TimeController tests (Phase 4); guard detects via hash drift over ticks
//! D8  — SnapshotSerializer fixed precision; guard detects via hash mismatch
//! D9  — hook_tick_end hash computation and mismatch detection
//! D10 — hook_tick_start schema/plan version mismatch (always fatal)
//! D11 — WorldHasher BTreeMap ordering; SnapshotSerializer stable keys
//! D12 — PhaseOrchestrator input boundary; guard detects via hash mismatch
//! D13 — AdapterAuthorityEnforcer (Phase 7); guard detects via hash mismatch
//! D14 — ReplayValidator full recording → validation pipeline
//! D15 — hook ordering enforcement: phase without tick, system without phase

#[cfg(test)]
mod tests {
    use xace_core::entity_state::EntityState;
    use xace_core::errors::determinism_error::{DeterminismRule, GuardMode};
    use xace_core::runtime::phase_enum::PhaseEnum;
    use xace_core::runtime::world_snapshot::{ComponentTableSnapshot, EntityRecord, WorldSnapshot};

    use crate::determinism_guard::determinism_guard::DeterminismGuard;
    use crate::determinism_guard::replay_validator::{GoldenLog, ReplayStatus, ReplayValidator};
    use crate::determinism_guard::rng_interceptor::RngInterceptor;
    use crate::determinism_guard::world_hasher::WorldHasher;

    // ── Snapshot Factories ────────────────────────────────────────────────────

    fn empty_snap(tick: u64) -> WorldSnapshot {
        let mut s = WorldSnapshot::empty("0.1.0", 1, 42);
        s.tick = tick;
        s
    }

    fn snap_with_entity(tick: u64, entity_id: u64, state: EntityState) -> WorldSnapshot {
        let mut s = empty_snap(tick);
        s.entity_store_snapshot
            .entities
            .push(EntityRecord::new(entity_id, state, 0));
        s.entity_store_snapshot.next_entity_id = entity_id + 1;
        s
    }

    fn snap_with_component(tick: u64, entity_id: u64, type_id: u32, json: &str) -> WorldSnapshot {
        let mut s = snap_with_entity(tick, entity_id, EntityState::Active);
        let mut table = ComponentTableSnapshot::new(type_id, "COMP_TEST_V1");
        table.set(entity_id, json);
        s.component_tables_snapshot.set_table(table);
        s
    }

    // ── Guard Factories ───────────────────────────────────────────────────────

    fn strict_guard() -> DeterminismGuard {
        let mut g = DeterminismGuard::new(GuardMode::Strict, "0.1.0", 1);
        g.register_systems(&[
            "sys_movement",
            "sys_ai",
            "sys_health",
            "sys_combat",
            "sys_cleanup",
        ]);
        g
    }

    fn silent_guard() -> DeterminismGuard {
        let mut g = DeterminismGuard::new(GuardMode::Silent, "0.1.0", 1);
        g.register_systems(&["sys_movement", "sys_ai", "sys_health"]);
        g
    }

    fn dev_guard() -> DeterminismGuard {
        let mut g = DeterminismGuard::new(GuardMode::Dev, "0.1.0", 1);
        g.register_systems(&["sys_movement", "sys_ai"]);
        g
    }

    /// Runs a complete valid tick lifecycle through the guard.
    /// Returns the world hash computed at tick end.
    fn run_clean_tick(guard: &mut DeterminismGuard, tick: u64, snapshot: &WorldSnapshot) -> String {
        guard.hook_tick_start(tick, "0.1.0", 1).unwrap();
        for phase in PhaseEnum::ALL {
            guard.hook_phase_start(tick, phase).unwrap();
            guard.hook_phase_end(tick, phase).unwrap();
        }
        guard.hook_tick_end(snapshot).unwrap()
    }

    // =========================================================================
    // D1 — System order from ExecutionPlan only
    // =========================================================================

    #[test]
    fn d1_unregistered_system_causes_violation_in_strict() {
        let mut g = strict_guard();
        g.hook_tick_start(1, "0.1.0", 1).unwrap();
        g.hook_phase_start(1, PhaseEnum::Simulation).unwrap();

        let result = g.hook_system_execute(1, PhaseEnum::Simulation, "sys_unregistered");
        assert!(result.is_err(), "Unregistered system must be rejected (D1)");
        assert_eq!(
            g.violations()[0].rule,
            DeterminismRule::D1SystemOrderFromPlanOnly
        );
    }

    #[test]
    fn d1_registered_system_passes_in_all_phases() {
        let mut g = strict_guard();
        g.hook_tick_start(1, "0.1.0", 1).unwrap();
        for phase in PhaseEnum::ALL {
            g.hook_phase_start(1, phase).unwrap();
            // All registered systems must be accepted in any phase
            assert!(
                g.hook_system_execute(1, phase, "sys_movement").is_ok(),
                "Registered system must be accepted in phase {:?}",
                phase
            );
            g.hook_phase_end(1, phase).unwrap();
        }
    }

    #[test]
    fn d1_silent_mode_records_but_continues_on_unregistered_system() {
        let mut g = silent_guard();
        g.hook_tick_start(1, "0.1.0", 1).unwrap();
        g.hook_phase_start(1, PhaseEnum::Simulation).unwrap();
        let result = g.hook_system_execute(1, PhaseEnum::Simulation, "sys_ghost");
        assert!(result.is_ok(), "SILENT mode must continue on D1 violation");
        assert_eq!(g.violation_count(), 1);
    }

    // =========================================================================
    // D6 — DeterministicRNG only
    // =========================================================================

    #[test]
    fn d6_illegal_rng_report_causes_violation_in_strict() {
        let mut g = strict_guard();
        let result = g.hook_rng_access(5, "sys_ai", false);
        assert!(
            result.is_err(),
            "Illegal RNG must be rejected in STRICT (D6)"
        );
        assert_eq!(
            g.violations()[0].rule,
            DeterminismRule::D6DeterministicRngOnly
        );
        assert_eq!(g.violations()[0].tick, 5);
        assert_eq!(g.violations()[0].system_context, "sys_ai");
    }

    #[test]
    fn d6_legal_rng_access_produces_no_violation() {
        let mut g = strict_guard();
        assert!(g.hook_rng_access(1, "sys_movement", true).is_ok());
        assert_eq!(g.violation_count(), 0);
    }

    #[test]
    fn d6_multiple_illegal_accesses_accumulate_in_silent() {
        let mut g = silent_guard();
        for tick in 0..5 {
            g.hook_rng_access(tick, "sys_ai", false).ok();
        }
        assert_eq!(g.violation_count(), 5);
        assert_eq!(
            g.violations_for_rule(DeterminismRule::D6DeterministicRngOnly)
                .len(),
            5
        );
    }

    #[test]
    fn d6_interceptor_integrates_with_guard() {
        // RngInterceptor detects illegal RNG → report_illegal_rng() → guard records D6
        let interceptor = RngInterceptor::new(42, GuardMode::Silent);
        interceptor.report_illegal_rng("sys_combat", 10).ok();

        // Guard receives the same signal via its hook
        let mut g = silent_guard();
        g.hook_rng_access(10, "sys_combat", false).ok();

        // Both should record a D6 violation
        assert_eq!(interceptor.violation_count(), 1);
        assert_eq!(g.violation_count(), 1);
    }

    // =========================================================================
    // D9 — world_hash computed and validated per tick
    // =========================================================================

    #[test]
    fn d9_hook_tick_end_computes_and_records_hash() {
        let mut g = strict_guard();
        let snap = empty_snap(1);
        g.hook_tick_start(1, "0.1.0", 1).unwrap();
        for phase in PhaseEnum::ALL {
            g.hook_phase_start(1, phase).unwrap();
            g.hook_phase_end(1, phase).unwrap();
        }
        g.hook_tick_end(&snap).unwrap();
        let recorded = g.hash_at_tick(1);
        assert!(recorded.is_some(), "Guard must record world_hash at tick 1");
        assert_eq!(
            recorded.unwrap().len(),
            64,
            "Hash must be 64-char SHA-256 hex"
        );
    }

    #[test]
    fn d9_precomputed_hash_that_matches_passes() {
        let mut g = strict_guard();
        let mut snap = empty_snap(1);
        // Pre-compute what WorldHasher will produce for this snapshot
        let correct_hash = WorldHasher::compute(&snap);
        snap.world_hash = correct_hash.clone();

        g.hook_tick_start(1, "0.1.0", 1).unwrap();
        for phase in PhaseEnum::ALL {
            g.hook_phase_start(1, phase).unwrap();
            g.hook_phase_end(1, phase).unwrap();
        }
        assert!(g.hook_tick_end(&snap).is_ok());
        assert_eq!(g.violation_count(), 0);
    }

    #[test]
    fn d9_wrong_precomputed_hash_triggers_violation_in_strict() {
        let mut g = strict_guard();
        let mut snap = empty_snap(1);
        snap.world_hash = "this_is_completely_wrong_and_will_not_match".into();

        g.hook_tick_start(1, "0.1.0", 1).unwrap();
        for phase in PhaseEnum::ALL {
            g.hook_phase_start(1, phase).unwrap();
            g.hook_phase_end(1, phase).unwrap();
        }
        let result = g.hook_tick_end(&snap);
        assert!(
            result.is_err(),
            "Hash mismatch must be a D9 violation in STRICT"
        );
        assert_eq!(g.violations()[0].rule, DeterminismRule::D9WorldHashPerTick);
        assert!(g.violations()[0].is_hash_mismatch());
    }

    #[test]
    fn d9_hashes_differ_across_different_world_states() {
        let mut g = silent_guard();

        let snap_a = empty_snap(1);
        let snap_b = snap_with_entity(1, 42, EntityState::Active);

        g.hook_tick_start(1, "0.1.0", 1).unwrap();
        for phase in PhaseEnum::ALL {
            g.hook_phase_start(1, phase).unwrap();
            g.hook_phase_end(1, phase).unwrap();
        }
        let hash_a = g.hook_tick_end(&snap_a).unwrap();

        // Reset guard state to allow a second tick_start
        let mut g2 = silent_guard();
        g2.hook_tick_start(1, "0.1.0", 1).unwrap();
        for phase in PhaseEnum::ALL {
            g2.hook_phase_start(1, phase).unwrap();
            g2.hook_phase_end(1, phase).unwrap();
        }
        let hash_b = g2.hook_tick_end(&snap_b).unwrap();

        assert_ne!(
            hash_a, hash_b,
            "Different world states must produce different hashes (D9)"
        );
    }

    #[test]
    fn d9_same_world_state_produces_identical_hash_across_ticks() {
        // Two guards, same snapshot, same tick → same hash
        let snap = empty_snap(7);
        let hash_a = {
            let mut g = silent_guard();
            run_clean_tick(&mut g, 7, &snap)
        };
        let hash_b = {
            let mut g = silent_guard();
            run_clean_tick(&mut g, 7, &snap)
        };
        assert_eq!(
            hash_a, hash_b,
            "Same world must produce same hash always (D9)"
        );
    }

    // =========================================================================
    // D10 — Schema version must match ExecutionPlan version (always fatal)
    // =========================================================================

    #[test]
    fn d10_schema_mismatch_is_fatal_in_strict() {
        let mut g = strict_guard();
        let result = g.hook_tick_start(1, "9.9.9", 1);
        assert!(result.is_err());
        assert_eq!(
            g.violations()[0].rule,
            DeterminismRule::D10SchemaVersionMatch
        );
    }

    #[test]
    fn d10_plan_version_mismatch_is_fatal_in_strict() {
        let mut g = strict_guard();
        let result = g.hook_tick_start(1, "0.1.0", 999);
        assert!(result.is_err());
        assert_eq!(
            g.violations()[0].rule,
            DeterminismRule::D10SchemaVersionMatch
        );
    }

    #[test]
    fn d10_schema_mismatch_is_fatal_even_in_silent_mode() {
        // D10 bypasses mode — it is ALWAYS fatal
        let mut g = silent_guard();
        let result = g.hook_tick_start(1, "wrong_schema", 1);
        assert!(
            result.is_err(),
            "D10 must be fatal in ALL modes including SILENT"
        );
        assert_eq!(g.violation_count(), 1);
    }

    #[test]
    fn d10_schema_mismatch_is_fatal_even_in_dev_mode() {
        let mut g = dev_guard();
        let result = g.hook_tick_start(1, "0.1.0", 99);
        assert!(result.is_err(), "D10 must be fatal in DEV mode");
    }

    #[test]
    fn d10_matching_versions_pass_across_multiple_ticks() {
        let mut g = strict_guard();
        for tick in 0..10 {
            assert!(
                g.hook_tick_start(tick, "0.1.0", 1).is_ok(),
                "Matching versions must pass on every tick"
            );
            for phase in PhaseEnum::ALL {
                g.hook_phase_start(tick, phase).unwrap();
                g.hook_phase_end(tick, phase).unwrap();
            }
            g.hook_tick_end(&empty_snap(tick)).unwrap();
        }
        assert_eq!(g.violation_count(), 0);
    }

    // =========================================================================
    // D14 — Replay = initial snapshot + input stream + identical schema
    // =========================================================================

    #[test]
    fn d14_identical_replay_passes_all_ticks() {
        // Record 10 ticks
        let mut recorder = ReplayValidator::new(GuardMode::Strict);
        recorder.begin_recording("0.1.0", 1);
        for tick in 0..10 {
            recorder.record_tick(&empty_snap(tick)).unwrap();
        }
        let golden = recorder.finish_recording().unwrap();

        // Validate with identical snapshots
        let mut validator = ReplayValidator::new(GuardMode::Strict);
        validator.begin_validation(golden, "0.1.0", 1).unwrap();
        for tick in 0..10 {
            assert!(
                validator.validate_tick(&empty_snap(tick)).is_ok(),
                "Identical replay must pass at tick {}",
                tick
            );
        }
        let report = validator.finish_validation();
        assert!(report.passed(), "10-tick identical replay must pass");
        assert_eq!(report.divergence_count(), 0);
        assert_eq!(report.validated_tick_count, 10);
    }

    #[test]
    fn d14_state_change_at_single_tick_causes_divergence() {
        let mut recorder = ReplayValidator::new(GuardMode::Strict);
        recorder.begin_recording("0.1.0", 1);
        for tick in 0..5 {
            recorder.record_tick(&empty_snap(tick)).unwrap();
        }
        let golden = recorder.finish_recording().unwrap();

        let mut validator = ReplayValidator::new(GuardMode::Silent);
        validator.begin_validation(golden, "0.1.0", 1).unwrap();

        // Ticks 0–2 identical
        for tick in 0..3 {
            validator.validate_tick(&empty_snap(tick)).unwrap();
        }
        // Tick 3: different state (entity added — changes hash)
        validator
            .validate_tick(&snap_with_entity(3, 100, EntityState::Active))
            .unwrap();
        // Tick 4: back to identical
        validator.validate_tick(&empty_snap(4)).unwrap();

        let report = validator.finish_validation();
        assert!(!report.passed());
        assert_eq!(report.divergence_count(), 1);
        assert_eq!(report.first_divergence_tick, 3);
    }

    #[test]
    fn d14_wrong_schema_version_blocks_validation_start() {
        let golden = GoldenLog::new("0.1.0", 1);
        let mut validator = ReplayValidator::new(GuardMode::Strict);
        let result = validator.begin_validation(golden, "0.99.0", 1);
        assert!(
            result.is_err(),
            "Schema mismatch must block begin_validation (D14)"
        );
        assert_eq!(validator.status(), ReplayStatus::Idle);
    }

    #[test]
    fn d14_replay_ending_early_is_reported_as_unvalidated_ticks() {
        let mut recorder = ReplayValidator::new(GuardMode::Strict);
        recorder.begin_recording("0.1.0", 1);
        for tick in 0..10 {
            recorder.record_tick(&empty_snap(tick)).unwrap();
        }
        let golden = recorder.finish_recording().unwrap();

        let mut validator = ReplayValidator::new(GuardMode::Strict);
        validator.begin_validation(golden, "0.1.0", 1).unwrap();
        // Only replay 4 of 10
        for tick in 0..4 {
            validator.validate_tick(&empty_snap(tick)).unwrap();
        }
        let report = validator.finish_validation();
        assert!(!report.is_full_pass);
        assert_eq!(report.validated_tick_count, 4);
        assert_eq!(report.unvalidated_golden_ticks, 6);
    }

    // =========================================================================
    // D15 — Guard hooks active at every execution boundary
    // =========================================================================

    #[test]
    fn d15_phase_start_without_tick_start_is_violation() {
        let mut g = strict_guard();
        // Deliberately skip hook_tick_start
        let result = g.hook_phase_start(1, PhaseEnum::Simulation);
        assert!(
            result.is_err(),
            "Phase without tick window must be a D15 violation"
        );
        assert_eq!(
            g.violations()[0].rule,
            DeterminismRule::D15GuardAtEveryBoundary
        );
    }

    #[test]
    fn d15_system_execute_without_phase_start_is_violation() {
        let mut g = strict_guard();
        g.hook_tick_start(1, "0.1.0", 1).unwrap();
        // No hook_phase_start — phase window is not open
        let result = g.hook_system_execute(1, PhaseEnum::Simulation, "sys_movement");
        assert!(
            result.is_err(),
            "System without phase window must be a D15 violation"
        );
        assert_eq!(
            g.violations()[0].rule,
            DeterminismRule::D15GuardAtEveryBoundary
        );
    }

    #[test]
    fn d15_system_execute_after_phase_end_is_violation() {
        let mut g = strict_guard();
        g.hook_tick_start(1, "0.1.0", 1).unwrap();
        g.hook_phase_start(1, PhaseEnum::Simulation).unwrap();
        g.hook_phase_end(1, PhaseEnum::Simulation).unwrap();
        // Phase window is now closed
        let result = g.hook_system_execute(1, PhaseEnum::Simulation, "sys_movement");
        assert!(
            result.is_err(),
            "System after phase_end must be a D15 violation"
        );
        assert_eq!(
            g.violations()[0].rule,
            DeterminismRule::D15GuardAtEveryBoundary
        );
    }

    #[test]
    fn d15_all_hooks_in_correct_order_produce_no_violations() {
        let mut g = strict_guard();
        let snap = empty_snap(1);

        g.hook_tick_start(1, "0.1.0", 1).unwrap();
        for phase in PhaseEnum::ALL {
            g.hook_phase_start(1, phase).unwrap();
            // Execute a couple of systems per phase
            g.hook_system_execute(1, phase, "sys_movement").unwrap();
            g.hook_system_execute(1, phase, "sys_ai").unwrap();
            g.hook_phase_end(1, phase).unwrap();
        }
        g.hook_tick_end(&snap).unwrap();

        assert_eq!(
            g.violation_count(),
            0,
            "Correct hook order must produce zero violations"
        );
    }

    // =========================================================================
    // Guard Mode Behaviour
    // =========================================================================

    #[test]
    fn strict_mode_returns_err_on_first_violation_and_halts() {
        let mut g = strict_guard();
        // D6 violation in STRICT
        let result = g.hook_rng_access(1, "sys_bad", false);
        assert!(result.is_err(), "STRICT mode must return Err immediately");
        assert_eq!(g.violation_count(), 1);
    }

    #[test]
    fn dev_mode_returns_ok_and_logs_violation() {
        let mut g = dev_guard();
        let result = g.hook_rng_access(1, "sys_bad", false);
        assert!(result.is_ok(), "DEV mode must return Ok and continue");
        assert_eq!(g.violation_count(), 1);
        assert!(g.has_violations());
    }

    #[test]
    fn silent_mode_returns_ok_and_accumulates_all_violations() {
        let mut g = silent_guard();
        for tick in 0..10 {
            g.hook_rng_access(tick, "sys_bad", false).ok();
        }
        assert_eq!(g.violation_count(), 10);
        assert!(g.has_violations());
    }

    #[test]
    fn silent_mode_allows_inspection_of_all_violation_rules() {
        let mut g = silent_guard();

        // D6 violation
        g.hook_rng_access(1, "sys_bad", false).ok();

        // D1 violation
        g.hook_tick_start(2, "0.1.0", 1).unwrap();
        g.hook_phase_start(2, PhaseEnum::Simulation).unwrap();
        g.hook_system_execute(2, PhaseEnum::Simulation, "sys_unregistered")
            .ok();

        let d6_violations = g.violations_for_rule(DeterminismRule::D6DeterministicRngOnly);
        let d1_violations = g.violations_for_rule(DeterminismRule::D1SystemOrderFromPlanOnly);

        assert_eq!(d6_violations.len(), 1);
        assert_eq!(d1_violations.len(), 1);
    }

    // =========================================================================
    // WorldHasher Integration
    // =========================================================================

    #[test]
    fn world_hasher_same_state_same_hash_always() {
        let snap = snap_with_component(5, 1, 1, r#"{"x":10,"y":20}"#);
        let h1 = WorldHasher::compute(&snap);
        let h2 = WorldHasher::compute(&snap);
        assert_eq!(h1, h2, "WorldHasher must be deterministic (D9, D11)");
    }

    #[test]
    fn world_hasher_entity_state_change_changes_hash() {
        let active = snap_with_entity(1, 1, EntityState::Active);
        let disabled = snap_with_entity(1, 1, EntityState::Disabled);
        assert_ne!(
            WorldHasher::compute(&active),
            WorldHasher::compute(&disabled),
            "Entity state change must change world hash"
        );
    }

    #[test]
    fn world_hasher_component_value_change_changes_hash() {
        let a = snap_with_component(1, 1, 1, r#"{"speed":5}"#);
        let b = snap_with_component(1, 1, 1, r#"{"speed":6}"#);
        assert_ne!(
            WorldHasher::compute(&a),
            WorldHasher::compute(&b),
            "Component value change must change world hash (D9)"
        );
    }

    #[test]
    fn world_hasher_schema_version_change_changes_hash() {
        let mut a = empty_snap(1);
        let mut b = empty_snap(1);
        b.schema_version = "0.2.0".into();
        assert_ne!(
            WorldHasher::compute(&a),
            WorldHasher::compute(&b),
            "Schema version must be part of world hash (D10)"
        );
    }

    #[test]
    fn world_hasher_are_equal_returns_true_for_identical_worlds() {
        let a = snap_with_component(3, 5, 2, r#"{"hp":100}"#);
        let b = snap_with_component(3, 5, 2, r#"{"hp":100}"#);
        assert!(WorldHasher::are_equal(&a, &b));
    }

    // =========================================================================
    // RngInterceptor Integration
    // =========================================================================

    #[test]
    fn rng_interceptor_seed_is_deterministic_across_instances() {
        let seed_a = RngInterceptor::derive_seed(12345, "sys_movement", 99);
        let seed_b = RngInterceptor::derive_seed(12345, "sys_movement", 99);
        assert_eq!(seed_a, seed_b, "Seed derivation must be deterministic (D6)");
    }

    #[test]
    fn rng_interceptor_different_systems_get_different_seeds() {
        let a = RngInterceptor::derive_seed(1, "sys_movement", 1);
        let b = RngInterceptor::derive_seed(1, "sys_ai", 1);
        let c = RngInterceptor::derive_seed(1, "sys_health", 1);
        assert_ne!(a, b);
        assert_ne!(b, c);
        assert_ne!(a, c);
    }

    #[test]
    fn rng_interceptor_window_prevents_cross_system_seed_theft() {
        let interceptor = RngInterceptor::new(42, GuardMode::Strict);
        // Open window for sys_movement
        let _win = interceptor.open_window("sys_movement", 1);
        // sys_ai tries to request RNG under sys_movement's window — must fail
        let result = interceptor.request_rng("sys_ai", 1);
        assert!(result.is_err(), "Cross-system RNG request must fail");
        assert_eq!(interceptor.violation_count(), 1);
    }

    #[test]
    fn rng_interceptor_strict_illegal_report_fails_simulation() {
        let interceptor = RngInterceptor::new(42, GuardMode::Strict);
        let result = interceptor.report_illegal_rng("sys_rogue", 50);
        assert!(
            result.is_err(),
            "Illegal RNG report must fail in STRICT (D6)"
        );
        assert!(interceptor.has_violations());
    }

    #[test]
    fn rng_interceptor_metrics_track_legal_and_illegal_separately() {
        let interceptor = RngInterceptor::new(1, GuardMode::Silent);

        // 3 legal accesses
        for tick in 1..=3 {
            let _win = interceptor.open_window("sys_movement", tick);
            interceptor.request_rng("sys_movement", tick).unwrap();
        }

        // 2 illegal accesses
        interceptor.report_illegal_rng("sys_bad", 10).ok();
        interceptor.report_illegal_rng("sys_bad", 11).ok();

        let m = interceptor.metrics();
        assert_eq!(m.legal_access_count, 3);
        assert_eq!(m.illegal_access_count, 2);
        assert_eq!(m.violations_raised, 2);
        assert_eq!(m.windowless_access_count, 0);
    }

    // =========================================================================
    // Multi-tick Pipeline — Full Lifecycle
    // =========================================================================

    #[test]
    fn full_10_tick_lifecycle_with_no_violations() {
        let mut g = strict_guard();
        let interceptor = RngInterceptor::new(42, GuardMode::Strict);

        for tick in 0..10 {
            let snap = empty_snap(tick);

            // Tick start
            g.hook_tick_start(tick, "0.1.0", 1).unwrap();

            for phase in PhaseEnum::ALL {
                g.hook_phase_start(tick, phase).unwrap();

                // Open RNG window for sys_movement, make a legal access
                let _win = interceptor.open_window("sys_movement", tick);
                interceptor.request_rng("sys_movement", tick).unwrap();
                drop(_win);

                g.hook_system_execute(tick, phase, "sys_movement").unwrap();
                g.hook_system_execute(tick, phase, "sys_ai").unwrap();
                g.hook_phase_end(tick, phase).unwrap();
            }

            g.hook_tick_end(&snap).unwrap();
        }

        assert_eq!(
            g.violation_count(),
            0,
            "10-tick clean run must have zero violations"
        );
        assert_eq!(interceptor.violation_count(), 0);
        assert_eq!(interceptor.metrics().legal_access_count, 50); // once per phase
    }

    #[test]
    fn hash_log_grows_one_entry_per_tick() {
        let mut g = silent_guard();
        for tick in 0..5 {
            let snap = empty_snap(tick);
            run_clean_tick(&mut g, tick, &snap);
        }
        for tick in 0..5 {
            assert!(
                g.hash_at_tick(tick).is_some(),
                "Guard must have recorded hash at tick {}",
                tick
            );
        }
    }

    #[test]
    fn violation_carries_correct_tick_and_system_context() {
        let mut g = silent_guard();
        g.hook_rng_access(42, "sys_damage", false).ok();
        let v = &g.violations()[0];
        assert_eq!(v.tick, 42);
        assert_eq!(v.system_context, "sys_damage");
        assert_eq!(v.rule, DeterminismRule::D6DeterministicRngOnly);
    }

    #[test]
    fn violations_for_rule_filters_across_mixed_violations() {
        let mut g = silent_guard();

        // Cause D6
        g.hook_rng_access(1, "sys_bad", false).ok();

        // Cause D10
        g.hook_tick_start(2, "wrong", 1).ok();

        // Cause D15
        g.hook_phase_start(5, PhaseEnum::Cleanup).ok(); // no tick open

        let d6 = g.violations_for_rule(DeterminismRule::D6DeterministicRngOnly);
        let d10 = g.violations_for_rule(DeterminismRule::D10SchemaVersionMatch);
        let d15 = g.violations_for_rule(DeterminismRule::D15GuardAtEveryBoundary);

        assert_eq!(d6.len(), 1);
        assert_eq!(d10.len(), 1);
        assert_eq!(d15.len(), 1);
        assert_eq!(g.violation_count(), 3);
    }

    // =========================================================================
    // Replay Validator — GoldenLog Serialization Round-trip
    // =========================================================================

    #[test]
    fn golden_log_round_trip_via_json_preserves_all_entries() {
        let mut log = GoldenLog::new("0.1.0", 1);
        for tick in 0..5 {
            log.record(tick, format!("hash_{}", tick));
        }

        // Serialize and deserialize via serde_json
        let json = serde_json::to_string(&log).expect("GoldenLog must be serializable");
        let restored: GoldenLog =
            serde_json::from_str(&json).expect("GoldenLog must be deserializable");

        assert_eq!(restored.tick_count(), 5);
        for tick in 0..5 {
            assert_eq!(restored.get(tick), Some(format!("hash_{}", tick).as_str()));
        }
    }

    #[test]
    fn replay_divergence_report_round_trip_via_json() {
        // Build a report with one divergence
        let mut recorder = ReplayValidator::new(GuardMode::Strict);
        recorder.begin_recording("0.1.0", 1);
        recorder.record_tick(&empty_snap(0)).unwrap();
        let golden = recorder.finish_recording().unwrap();

        let mut validator = ReplayValidator::new(GuardMode::Silent);
        validator.begin_validation(golden, "0.1.0", 1).unwrap();
        let mut bad = empty_snap(0);
        bad.schema_version = "diverged".into();
        validator.validate_tick(&bad).unwrap();
        let report = validator.finish_validation();

        let json = serde_json::to_string(&report).expect("Report must be serializable");
        let restored: crate::determinism_guard::replay_validator::ReplayDivergenceReport =
            serde_json::from_str(&json).expect("Report must be deserializable");

        assert_eq!(restored.divergence_count(), 1);
        assert!(!restored.passed());
    }
}
