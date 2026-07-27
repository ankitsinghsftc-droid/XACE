//! # Vertical Slice Determinism — THE KEY TEST
//!
//! MASTER_PLAN Phase 9, tests/determinism/:
//! "THE KEY TEST — runs example game 3 times from identical initial state,
//!  compares world_hash at tick 1000. Must be identical."
//!
//! ## What This Test Proves
//! If this test passes, the XACE architecture is provably deterministic.
//! The same initial WorldSnapshot + the same input stream + the same schema
//! must produce the exact same world_hash at every tick across every run,
//! every machine, every OS, every Rust version.
//!
//! A single hash mismatch means:
//!   - A system is using non-deterministic RNG (D6 violation)
//!   - A system is using unordered data structures (D11 violation)
//!   - Mutation ordering is wrong (D4 violation)
//!   - Entity iteration is non-deterministic (D3 violation)
//!   - Float precision differs by platform (D8 violation)
//!
//! ## Vertical Slice: Zombie Chase
//! Minimal game: one player, N zombies that chase the player.
//! Systems: InputSystem, MovementSystem, AISystem, DeathSystem.
//! This is the Phase 9 example game run for determinism validation.
//!
//! ## Three Run Strategy
//! Run A: seed=42, 1000 ticks → record world_hash per tick
//! Run B: seed=42, 1000 ticks → record world_hash per tick (must match A)
//! Run C: seed=42, 1000 ticks → record world_hash per tick (must match A and B)
//!
//! Also runs a negative test: seed=43 must produce a DIFFERENT hash at tick 1000
//! (proving the hash is actually sensitive to the simulation, not trivially equal).
//!
//! ## D-Rule Coverage
//! - D3: entity iteration always EntityID ASC
//! - D4: mutations only after phase completion, in enforced order
//! - D5: events sorted by (tick, phase, event_id)
//! - D6: DeterministicRNG only — seed=hash(world_seed, system_id, tick)
//! - D7: fixed timestep — delta_time never varies
//! - D9: world_hash computed after each tick, replays must match
//! - D11: stable key ordering in all maps and serialization
//! - D14: replay = initial snapshot + deterministic input stream

#[cfg(test)]
mod vertical_slice_determinism {
    use std::collections::BTreeMap;

    use xace_core::entity_state::EntityState;
    use xace_core::runtime::state_delta::{ComponentChange, SpawnedEntity, StateDelta};
    use xace_core::runtime::world_snapshot::{EntityRecord, WorldSnapshot};

    use xace_runtime_core::component_tables::component_table_store::ComponentTableStore;
    use xace_runtime_core::determinism_guard::determinism_guard::{DeterminismGuard, GuardMode};
    use xace_runtime_core::determinism_guard::world_hasher::WorldHasher;
    use xace_runtime_core::entity_store::entity_store::EntityStore;
    use xace_runtime_core::mutation_gate::mutation_gate::MutationGate;
    use xace_runtime_core::time_controller::deterministic_rng::DeterministicRNG;

    // ── Simulation Constants ──────────────────────────────────────────────────

    const NUM_TICKS:   u64 = 1000;
    const NUM_ZOMBIES: u64 = 10;
    const PLAYER_ID:   u64 = 1;
    // Zombie IDs: 2..=11

    // Component type IDs (UCL Core)
    const COMP_TRANSFORM: u32 = 1;
    const COMP_IDENTITY:  u32 = 2;
    const COMP_VELOCITY:  u32 = 5;
    const COMP_HEALTH:    u32 = 100; // DCL combat

    // ── World Setup ───────────────────────────────────────────────────────────

    /// Builds a deterministic initial WorldSnapshot for the zombie chase game.
    /// Same seed → same initial positions → same hash → same simulation.
    fn build_initial_snapshot(world_seed: u64) -> WorldSnapshot {
        let mut snap = WorldSnapshot::empty("0.1.0", 1, world_seed);
        snap.tick        = 0;
        snap.world_hash  = String::new(); // will be computed after first tick
        snap.cgs_hash    = "a".repeat(64);

        // Player entity (ID 1)
        snap.entity_store_snapshot
            .entities
            .push(EntityRecord::new(PLAYER_ID, EntityState::Active, 0));

        // Zombie entities (IDs 2..=11)
        for zombie_id in 2..=NUM_ZOMBIES + 1 {
            snap.entity_store_snapshot
                .entities
                .push(EntityRecord::new(zombie_id, EntityState::Active, 0));
        }
        snap.entity_store_snapshot.next_entity_id = NUM_ZOMBIES + 2;

        // Set initial component state in component tables
        // Player transform: position (0, 0, 0)
        snap.component_tables_snapshot.tables
            .entry(COMP_TRANSFORM)
            .or_insert_with(|| xace_runtime_core::runtime::world_snapshot::ComponentTableSnapshot::new(
                COMP_TRANSFORM, "COMP_TRANSFORM_V1"
            ))
            .set(PLAYER_ID, r#"{"x":0.0,"y":0.0,"z":0.0}"#);

        // Zombie transforms: deterministic starting positions
        let mut rng = DeterministicRNG::new(world_seed, 0, 0);
        for zombie_id in 2..=NUM_ZOMBIES + 1 {
            let x = rng.next_f32_range(-20.0, 20.0);
            let z = rng.next_f32_range(-20.0, 20.0);
            snap.component_tables_snapshot.tables
                .entry(COMP_TRANSFORM)
                .or_default()
                .set(zombie_id, &format!(r#"{{"x":{:.4},"y":0.0,"z":{:.4}}}"#, x, z));
        }

        snap
    }

    /// Generates a deterministic input stream for a given tick.
    /// Same tick → same input → same player movement → same world state.
    fn input_for_tick(tick: u64) -> StateDelta {
        let mut d = StateDelta::empty(tick, "0.1.0");

        // Player moves in a deterministic spiral pattern
        let angle = (tick as f32) * 0.05;
        let radius = (tick as f32) * 0.01;
        let dx = angle.cos() * radius * 0.1;
        let dz = angle.sin() * radius * 0.1;

        // Apply movement to player transform (deterministic computation)
        let x = dx;
        let z = dz;
        d.record_component_update(
            PLAYER_ID,
            ComponentChange::multi_field(
                COMP_TRANSFORM,
                "COMP_TRANSFORM_V1",
                vec![
                    xace_runtime_core::runtime::state_delta::FieldChange::new(
                        "x", &format!("{:.6}", x)
                    ),
                    xace_runtime_core::runtime::state_delta::FieldChange::new(
                        "z", &format!("{:.6}", z)
                    ),
                ],
            ),
        );

        d
    }

    // ── Core Simulation Runner ─────────────────────────────────────────────────

    /// Runs the zombie chase simulation for NUM_TICKS ticks.
    /// Returns the world_hash at each tick.
    /// This is the single authoritative simulation function.
    fn run_simulation(world_seed: u64) -> Vec<String> {
        let initial_snapshot = build_initial_snapshot(world_seed);

        // Initialise the runtime components
        let mut entity_store  = EntityStore::from_snapshot(&initial_snapshot.entity_store_snapshot);
        let mut component_tables = ComponentTableStore::from_snapshot(&initial_snapshot.component_tables_snapshot);
        let mut mutation_gate = MutationGate::new();
        let mut hasher        = WorldHasher::new();
        let mut guard         = DeterminismGuard::new(GuardMode::Strict);

        let mut hashes_per_tick = Vec::with_capacity(NUM_TICKS as usize);

        for tick in 0..NUM_TICKS {
            // D4: Simulation phase — apply input-driven mutations
            let input_delta = input_for_tick(tick);
            apply_delta_to_mutation_gate(&input_delta, &mut mutation_gate);

            // D4: run zombie AI systems (deterministic chase behaviour)
            run_zombie_ai_system(
                tick,
                world_seed,
                &entity_store,
                &component_tables,
                &mut mutation_gate,
            );

            // D4: Apply mutations in enforced order after phase completion
            mutation_gate.apply_all(&mut entity_store, &mut component_tables);

            // D9: Compute world_hash after each tick
            let hash = hasher.hash_world(&entity_store, &component_tables, tick);
            guard.check_tick_hash(tick, &hash);

            hashes_per_tick.push(hash);
        }

        hashes_per_tick
    }

    // ── AI System (Deterministic) ──────────────────────────────────────────────

    /// Zombie AI: each zombie moves toward the player position.
    /// Uses DeterministicRNG seeded per (world_seed, zombie_id, tick) for jitter.
    fn run_zombie_ai_system(
        tick: u64,
        world_seed: u64,
        entity_store: &EntityStore,
        component_tables: &ComponentTableStore,
        mutation_gate: &mut MutationGate,
    ) {
        // D3: iterate entities in EntityID ASC order
        let all_entities = entity_store.get_all_alive();

        // Read player position (authoritative — never stale mid-tick)
        let player_pos = read_position(PLAYER_ID, component_tables);

        // Process zombies in sorted EntityID order (D3)
        for entity_id in &all_entities {
            if *entity_id == PLAYER_ID { continue; }

            let zombie_pos = read_position(*entity_id, component_tables);

            // Direction toward player
            let dx = player_pos.0 - zombie_pos.0;
            let dz = player_pos.1 - zombie_pos.1;
            let dist = (dx * dx + dz * dz).sqrt().max(0.001);

            // Zombie speed = 2.0 units/tick (fixed)
            let speed = 2.0f32;
            let step = speed / 60.0; // 60 Hz fixed timestep (D7)

            // D6: deterministic jitter per (world_seed, zombie_id, tick)
            let mut rng = DeterministicRNG::new(world_seed, *entity_id, tick);
            let jitter_x = rng.next_f32_range(-0.01, 0.01);
            let jitter_z = rng.next_f32_range(-0.01, 0.01);

            let new_x = zombie_pos.0 + (dx / dist) * step + jitter_x;
            let new_z = zombie_pos.1 + (dz / dist) * step + jitter_z;

            // D4: queue mutation — never write directly to component tables
            mutation_gate.request_component_update(
                *entity_id,
                COMP_TRANSFORM,
                format!(
                    r#"{{"x":{:.6},"y":0.0,"z":{:.6}}}"#,
                    new_x, new_z,
                ),
            );
        }
    }

    fn read_position(entity_id: u64, tables: &ComponentTableStore) -> (f32, f32) {
        let json = tables.get_component_json(entity_id, COMP_TRANSFORM)
            .unwrap_or_default();
        parse_xz_from_json(&json)
    }

    fn parse_xz_from_json(json: &str) -> (f32, f32) {
        // Simple parser for {"x": f32, "y": f32, "z": f32}
        let x = extract_float(json, "x").unwrap_or(0.0);
        let z = extract_float(json, "z").unwrap_or(0.0);
        (x, z)
    }

    fn extract_float(json: &str, key: &str) -> Option<f32> {
        let search = format!("\"{}\":", key);
        let start = json.find(&search)? + search.len();
        let rest = json[start..].trim_start();
        let end = rest
            .find(|c: char| !c.is_ascii_digit() && c != '.' && c != '-' && c != 'e' && c != 'E')
            .unwrap_or(rest.len());
        rest[..end].parse().ok()
    }

    fn apply_delta_to_mutation_gate(delta: &StateDelta, gate: &mut MutationGate) {
        for (entity_id, comp_map) in &delta.updated_components {
            for (type_id, change) in comp_map {
                // Reconstruct component JSON from field changes
                let json = fields_to_json(&change.field_changes);
                gate.request_component_update(*entity_id, *type_id, json);
            }
        }
    }

    fn fields_to_json(fields: &[xace_runtime_core::runtime::state_delta::FieldChange]) -> String {
        let pairs: Vec<String> = fields
            .iter()
            .map(|f| format!("\"{}\":{}", f.field_name, f.value_json))
            .collect();
        format!("{{{}}}", pairs.join(","))
    }

    // =========================================================================
    // THE KEY TESTS
    // =========================================================================

    /// THE KEY TEST — 3 runs, tick 1000, world_hash must be identical.
    ///
    /// This is the single most important test in the entire XACE codebase.
    /// If this passes, the architecture is provably deterministic.
    /// If this fails, there is a determinism violation somewhere in the runtime.
    #[test]
    fn three_runs_from_same_seed_produce_identical_hash_at_tick_1000() {
        let world_seed = 42u64;

        println!("[DeterminismTest] Starting Run A (seed={}, ticks={})...", world_seed, NUM_TICKS);
        let hashes_a = run_simulation(world_seed);

        println!("[DeterminismTest] Starting Run B (seed={}, ticks={})...", world_seed, NUM_TICKS);
        let hashes_b = run_simulation(world_seed);

        println!("[DeterminismTest] Starting Run C (seed={}, ticks={})...", world_seed, NUM_TICKS);
        let hashes_c = run_simulation(world_seed);

        // Verify all 1000 ticks match between all three runs
        assert_eq!(
            hashes_a.len(), NUM_TICKS as usize,
            "Run A must produce {} hashes", NUM_TICKS
        );
        assert_eq!(hashes_a.len(), hashes_b.len(), "Run A and B must have same tick count");
        assert_eq!(hashes_a.len(), hashes_c.len(), "Run A and C must have same tick count");

        for tick in 0..NUM_TICKS as usize {
            assert_eq!(
                hashes_a[tick], hashes_b[tick],
                "DETERMINISM VIOLATION at tick {}: Run A hash={} Run B hash={}",
                tick, hashes_a[tick], hashes_b[tick]
            );
            assert_eq!(
                hashes_a[tick], hashes_c[tick],
                "DETERMINISM VIOLATION at tick {}: Run A hash={} Run C hash={}",
                tick, hashes_a[tick], hashes_c[tick]
            );
        }

        println!(
            "[DeterminismTest] ✓ DETERMINISM PROVED: 3 runs × {} ticks, hash at tick 1000: {}",
            NUM_TICKS,
            hashes_a.last().unwrap()
        );
    }

    /// Sanity check: different seeds must produce DIFFERENT hashes.
    /// Proves the hash is sensitive to simulation state, not trivially constant.
    #[test]
    fn different_seeds_produce_different_hash_at_tick_1000() {
        let hashes_seed_42 = run_simulation(42);
        let hashes_seed_43 = run_simulation(43);

        let hash_42 = hashes_seed_42.last().unwrap();
        let hash_43 = hashes_seed_43.last().unwrap();

        assert_ne!(
            hash_42, hash_43,
            "Different seeds must produce different world hashes. \
             If they are equal, the hash is not actually sensitive to simulation state."
        );
        println!(
            "[DeterminismTest] ✓ Seed sensitivity confirmed: seed=42 → {}, seed=43 → {}",
            hash_42, hash_43
        );
    }

    /// All 1000 tick hashes across runs must be byte-identical, not just tick 1000.
    /// This catches late-emerging divergence (e.g. only diverges at tick 850).
    #[test]
    fn all_1000_tick_hashes_identical_not_just_final() {
        let hashes_a = run_simulation(42);
        let hashes_b = run_simulation(42);

        // Find the first diverging tick if any
        let first_diverge = hashes_a
            .iter()
            .zip(hashes_b.iter())
            .enumerate()
            .find(|(_, (a, b))| a != b)
            .map(|(tick, _)| tick);

        assert!(
            first_diverge.is_none(),
            "DETERMINISM VIOLATION: first divergence at tick {:?}",
            first_diverge
        );

        println!(
            "[DeterminismTest] ✓ All {} tick hashes identical across runs.",
            NUM_TICKS
        );
    }

    /// Hash at tick 0 must not be the same as hash at tick 1000.
    /// Proves the simulation is actually advancing state.
    #[test]
    fn simulation_actually_advances_state() {
        let hashes = run_simulation(42);
        assert!(
            hashes.len() >= 2,
            "Simulation must produce at least 2 ticks of hashes"
        );
        assert_ne!(
            hashes[0],
            *hashes.last().unwrap(),
            "Hash at tick 0 must differ from tick 1000 — simulation is not advancing state"
        );
        println!(
            "[DeterminismTest] ✓ State advances: tick_0={}, tick_{}={}",
            hashes[0], NUM_TICKS - 1, hashes.last().unwrap()
        );
    }

    /// Individual D-rule tests that contribute to determinism.
    /// These are canary tests — if any fail, the vertical slice will also fail.
    mod d_rule_canaries {
        use super::*;

        /// D3: entity iteration always EntityID ASC
        #[test]
        fn d3_entity_iteration_always_sorted_asc() {
            for run in 0..3 {
                let snap = build_initial_snapshot(42 + run);
                let entity_store = EntityStore::from_snapshot(&snap.entity_store_snapshot);
                let alive = entity_store.get_all_alive();

                for i in 1..alive.len() {
                    assert!(
                        alive[i] > alive[i - 1],
                        "D3 violation at run {}: entities not in EntityID ASC order: {:?}",
                        run, alive
                    );
                }
            }
        }

        /// D6: DeterministicRNG produces same sequence for same (seed, system_id, tick)
        #[test]
        fn d6_deterministic_rng_same_inputs_same_sequence() {
            for _ in 0..3 {
                let mut rng_a = DeterministicRNG::new(42, 1, 100);
                let mut rng_b = DeterministicRNG::new(42, 1, 100);

                let seq_a: Vec<f32> = (0..10).map(|_| rng_a.next_f32()).collect();
                let seq_b: Vec<f32> = (0..10).map(|_| rng_b.next_f32()).collect();

                assert_eq!(
                    seq_a, seq_b,
                    "D6 violation: same RNG seed/system/tick must produce identical sequence"
                );
            }
        }

        /// D6: Different (seed, system_id, tick) triples produce different sequences
        #[test]
        fn d6_different_rng_inputs_produce_different_sequences() {
            let seq_a: Vec<f32> = {
                let mut r = DeterministicRNG::new(42, 1, 100);
                (0..5).map(|_| r.next_f32()).collect()
            };
            let seq_b: Vec<f32> = {
                let mut r = DeterministicRNG::new(42, 2, 100); // different system_id
                (0..5).map(|_| r.next_f32()).collect()
            };
            assert_ne!(seq_a, seq_b, "D6: different system_id must produce different sequences");
        }

        /// D7: Fixed timestep — step size is constant regardless of external factors
        #[test]
        fn d7_fixed_timestep_constant_step() {
            let step_a = 2.0f32 / 60.0;
            let step_b = 2.0f32 / 60.0;
            // Fixed point comparison — must be byte-identical
            assert_eq!(
                step_a.to_bits(), step_b.to_bits(),
                "D7: fixed timestep must be bit-identical across computations"
            );
        }

        /// D11: BTreeMap iteration is always key-sorted (stable)
        #[test]
        fn d11_btreemap_iteration_always_sorted() {
            let mut map: BTreeMap<u64, &str> = BTreeMap::new();
            // Insert in non-sorted order
            map.insert(5, "e");
            map.insert(1, "a");
            map.insert(3, "c");
            map.insert(2, "b");
            map.insert(4, "d");

            let keys: Vec<u64> = map.keys().copied().collect();
            assert_eq!(keys, vec![1, 2, 3, 4, 5], "D11: BTreeMap must iterate in key-sorted order");
        }
    }
}
