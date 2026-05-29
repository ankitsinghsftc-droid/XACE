//! # Zombie Chase Simulation Runner
//!
//! Wires the XACE runtime (EntityStore, ComponentTableStore, MutationGate)
//! with the five zombie chase systems and runs N ticks.
//!
//! ## The Key Test
//! ```text
//! cargo test -p xace-zombie-chase three_runs_seed_42_tick_1000_hash_identical -- --nocapture
//! ```
//! Three calls with the same seed must return byte-identical Vec<String>.
//! If that passes: ARCHITECTURE PROVEN REAL — Milestone 1 complete.
//!
//! ## API surface used (verified against actual implementations)
//! EntityStore:     create_entity(tick), get_all_alive(), is_alive()
//! ComponentTableStore: register_table(), add_component(), get_component(),
//!                      has_component(), entities_with_all_components(), all_tables()
//! MutationGate:    request_modify_component(eid, tid, json, &es, &ts, tick)
//!                  request_add_component   (eid, tid, json, &es, &ts, tick)
//!                  request_destroy         (eid, &es, tick)
//!                  apply_all               (&mut es, &mut ts, tick)
//! DeterministicRng: new(world_seed, system_id_str, tick)
//!                   next_f64(), next_f64_range(min, max)

use std::collections::BTreeMap;

use sha2::{Digest, Sha256};

use xace_core::contracts::interfaces::{ISystem, ISystemContext};
use xace_core::entity_id::EntityID;
use xace_core::entity_metadata::Tick;
use xace_core::errors::xace_error::XaceError;
use xace_core::events::event_struct::Event;

use xace_runtime_core::component_tables::component_table_store::ComponentTableStore;
use xace_runtime_core::entity_store::entity_store::EntityStore;
use xace_runtime_core::mutation_gate::mutation_gate::MutationGate;
use xace_runtime_core::time_controller::deterministic_rng::DeterministicRng;

use crate::cgs::{component_ids, player_initial_components, zombie_initial_components};
use crate::systems::{
    ai_system::AISystem, damage_system::DamageSystem, death_system::DeathSystem,
    input_system::InputSystem, movement_system::MovementSystem,
};

// ── Constants ─────────────────────────────────────────────────────────────────

/// Number of zombie entities in the vertical slice.
const NUM_ZOMBIES: u64 = 10;

/// Player entity ID — always 1 because it is created first.
const PLAYER_ENTITY_ID: EntityID = 1;

/// All component type IDs used in the zombie chase game.
/// Must be registered in ComponentTableStore before simulation starts.
const ALL_COMPONENT_TABLES: &[(u32, &str)] = &[
    (component_ids::TRANSFORM, "COMP_TRANSFORM_V1"),
    (component_ids::IDENTITY, "COMP_IDENTITY_V1"),
    (component_ids::VELOCITY, "COMP_VELOCITY_V1"),
    (component_ids::INPUT, "COMP_INPUT_V1"),
    (component_ids::HEALTH, "COMP_HEALTH_V1"),
    (component_ids::DAMAGE, "COMP_DAMAGE_V1"),
    (component_ids::AI, "COMP_AI_V1"),
];

// ── Public Entry Point ────────────────────────────────────────────────────────

/// Runs the zombie chase simulation for `num_ticks` ticks.
///
/// Returns `world_hash` at each tick (index 0 = tick 0, etc.).
///
/// ## Determinism Guarantee
/// Identical arguments → byte-identical return value, every run, every machine.
pub fn run(world_seed: u64, num_ticks: u64) -> Vec<String> {
    let mut state = WorldState::new(world_seed);
    state.spawn_initial_entities();

    // Systems in execution order (D1)
    let systems: Vec<Box<dyn ISystem>> = vec![
        Box::new(InputSystem),
        Box::new(MovementSystem),
        Box::new(AISystem),
        Box::new(DamageSystem),
        Box::new(DeathSystem),
    ];

    let mut hashes = Vec::with_capacity(num_ticks as usize);

    for tick in 0..num_ticks {
        // Execute all systems — each gets a fresh context with its own RNG stream
        for system in &systems {
            let mut ctx = ZombieChaseContext::new(
                &state.entity_store,
                &state.component_tables,
                &mut state.mutation_gate,
                tick,
                world_seed,
                system.system_id(),
            );
            system.execute(&mut ctx).expect("System must not fail");
        }

        // D4: apply all queued mutations after all systems complete
        state
            .mutation_gate
            .apply_all(&mut state.entity_store, &mut state.component_tables, tick)
            .expect("MutationGate::apply_all must not fail");

        // D9: compute deterministic world hash after each tick
        let hash = compute_tick_hash(&state.entity_store, &state.component_tables, tick);
        hashes.push(hash);
    }

    hashes
}

// ── World State ───────────────────────────────────────────────────────────────

struct WorldState {
    world_seed: u64,
    entity_store: EntityStore,
    component_tables: ComponentTableStore,
    mutation_gate: MutationGate,
}

impl WorldState {
    fn new(world_seed: u64) -> Self {
        let mut component_tables = ComponentTableStore::new();

        // Register every component type table before first use
        for &(type_id, name) in ALL_COMPONENT_TABLES {
            component_tables
                .register_table(type_id, name)
                .expect("Table registration must succeed");
        }

        Self {
            world_seed,
            entity_store: EntityStore::new(),
            component_tables,
            mutation_gate: MutationGate::new(),
        }
    }

    /// Spawns all entities with deterministic initial component state.
    /// Called ONCE before the tick loop. Uses create_entity() which
    /// generates sequential IDs starting from 1 (D2).
    fn spawn_initial_entities(&mut self) {
        // ── Player (entity ID 1 — first create_entity call) ───────────────
        let player_id = self
            .entity_store
            .create_entity(0)
            .expect("Player entity creation must succeed");
        assert_eq!(
            player_id, PLAYER_ENTITY_ID,
            "Player must receive entity ID 1"
        );

        for (type_id, json) in player_initial_components(0.0, 0.0) {
            self.component_tables
                .add_component(player_id, type_id, json, 0)
                .expect("Player component must be addable");
        }

        // ── Zombies (entity IDs 2..=11) ────────────────────────────────────
        // DeterministicRng: seed = f(world_seed, "world_init", tick=0)
        // Same world_seed → same starting positions → same simulation.
        let mut init_rng = DeterministicRng::new(self.world_seed, "world_init", 0);

        for i in 0..NUM_ZOMBIES {
            let zombie_id = self
                .entity_store
                .create_entity(0)
                .expect("Zombie entity creation must succeed");

            let expected_id = PLAYER_ENTITY_ID + 1 + i;
            assert_eq!(
                zombie_id, expected_id,
                "Zombie {} must receive entity ID {}",
                i, expected_id
            );

            // Deterministic random starting position (D6)
            let x = init_rng.next_f64_range(-20.0, 20.0) as f32;
            let z = init_rng.next_f64_range(-20.0, 20.0) as f32;

            let components = zombie_initial_components(x, z, PLAYER_ENTITY_ID);
            for (type_id, json) in components {
                self.component_tables
                    .add_component(zombie_id, type_id, json, 0)
                    .expect("Zombie component must be addable");
            }
        }
    }
}

// ── World Hash ────────────────────────────────────────────────────────────────

/// Computes a deterministic SHA-256 hash of the complete world state.
///
/// Feeds tick + alive entities (sorted ASC, D3) + all component tables
/// (type_id ASC, D11; EntityID ASC within each table, D3) into SHA-256.
///
/// Does NOT require building a WorldSnapshot — hashes EntityStore and
/// ComponentTableStore directly. Same world state → same 64-char hex string.
fn compute_tick_hash(
    entity_store: &EntityStore,
    component_tables: &ComponentTableStore,
    tick: u64,
) -> String {
    let mut h = Sha256::new();

    // ── Tick ──────────────────────────────────────────────────────────────
    h.update(tick.to_be_bytes());

    // ── Entity store: alive entities in EntityID ASC (D3) ─────────────────
    let alive = entity_store.get_all_alive(); // already sorted ASC by BTreeMap
    h.update((alive.len() as u64).to_be_bytes()); // length prefix prevents collisions
    for &eid in &alive {
        h.update(eid.to_be_bytes());
    }

    // ── Component tables: type_id ASC (D11), EntityID ASC within (D3) ─────
    // all_tables() iterates BTreeMap → ascending type_id guaranteed
    for (type_id, table) in component_tables.all_tables() {
        h.update(type_id.to_be_bytes());
        let eids = table.all_entity_ids(); // BTreeMap → ascending EntityID
        h.update((eids.len() as u64).to_be_bytes());
        for &eid in &eids {
            h.update(eid.to_be_bytes());
            if let Some(json) = table.get(eid) {
                // Length-prefix the JSON to prevent "ab"+"c" == "a"+"bc"
                h.update((json.len() as u64).to_be_bytes());
                h.update(json.as_bytes());
            }
        }
    }

    // Hex-encode 32-byte digest → 64 lowercase hex chars
    h.finalize().iter().map(|b| format!("{:02x}", b)).collect()
}

// ── ZombieChaseContext ─────────────────────────────────────────────────────────

/// Concrete `ISystemContext` for the zombie chase simulation.
///
/// Each system gets a fresh context per tick with its own
/// `DeterministicRng` stream seeded by (world_seed, system_id_str, tick). (D6)
struct ZombieChaseContext<'a> {
    entity_store: &'a EntityStore,
    component_tables: &'a ComponentTableStore,
    mutation_gate: &'a mut MutationGate,
    tick: Tick,
    rng: DeterministicRng,
}

impl<'a> ZombieChaseContext<'a> {
    fn new(
        entity_store: &'a EntityStore,
        component_tables: &'a ComponentTableStore,
        mutation_gate: &'a mut MutationGate,
        tick: Tick,
        world_seed: u64,
        system_id: &str,
    ) -> Self {
        // D6: RNG seeded by (world_seed, system_id_str, tick) — string system_id
        let rng = DeterministicRng::new(world_seed, system_id, tick);
        Self {
            entity_store,
            component_tables,
            mutation_gate,
            tick,
            rng,
        }
    }
}

impl<'a> ISystemContext for ZombieChaseContext<'a> {
    // ── Read ──────────────────────────────────────────────────────────────

    fn get_component(
        &self,
        entity_id: EntityID,
        component_type_id: u32,
    ) -> Result<Option<&str>, XaceError> {
        Ok(self
            .component_tables
            .get_component(entity_id, component_type_id))
    }

    fn query_entities(&self, component_type_ids: &[u32]) -> Result<Vec<EntityID>, XaceError> {
        if component_type_ids.is_empty() {
            // Return all alive entities sorted ASC (D3)
            return Ok(self.entity_store.get_all_alive());
        }
        // entities_with_all_components returns EntityID ASC (D3) guaranteed by BTreeMap
        let candidates = self
            .component_tables
            .entities_with_all_components(component_type_ids);
        // Filter to alive entities only (destroyed entities may still have component rows
        // until apply_all runs the destroy phase)
        let alive: Vec<EntityID> = candidates
            .into_iter()
            .filter(|&eid| self.entity_store.is_alive(eid))
            .collect();
        // Already sorted ASC — entities_with_all_components preserves BTreeMap order
        Ok(alive)
    }

    fn current_tick(&self) -> Tick {
        self.tick
    }

    fn next_random(&mut self) -> Result<f64, XaceError> {
        // D6: DeterministicRng only — seeded by (world_seed, system_id_str, tick)
        Ok(self.rng.next_f64())
    }

    // ── Write (all deferred via MutationGate — D4) ────────────────────────

    fn submit_mutation(
        &mut self,
        entity_id: EntityID,
        component_type_id: u32,
        component_json: String,
    ) -> Result<(), XaceError> {
        // Split field borrows so mutation_gate can be borrowed mutably
        // while entity_store and component_tables are borrowed immutably.
        // References are Copy — copying them out is safe and idiomatic.
        let es = self.entity_store;
        let ts = self.component_tables;
        let tick = self.tick;

        if ts.has_component(entity_id, component_type_id) {
            // Component exists → modify (D4 modify queue)
            self.mutation_gate.request_modify_component(
                entity_id,
                component_type_id,
                component_json,
                es,
                ts,
                tick,
            )
        } else {
            // Component absent → add (D4 add queue)
            self.mutation_gate.request_add_component(
                entity_id,
                component_type_id,
                component_json,
                es,
                ts,
                tick,
            )
        }
    }

    fn submit_spawn(
        &mut self,
        actor_id: String,
        initial_components: BTreeMap<u32, String>,
    ) -> Result<(), XaceError> {
        let ts = self.component_tables;
        let tick = self.tick;
        self.mutation_gate
            .request_spawn(actor_id, initial_components, ts, tick)
    }

    fn submit_destroy(&mut self, entity_id: EntityID) -> Result<(), XaceError> {
        // D4: destroy queue — applied last in apply_all()
        // I2: all structural changes through MutationGate
        let es = self.entity_store;
        let tick = self.tick;
        self.mutation_gate.request_destroy(entity_id, es, tick)
    }

    fn emit_event(&mut self, _event: Event) -> Result<(), XaceError> {
        // Phase 9: EventBus not wired — events are a no-op.
        // Full EventBus integration arrives in Phase 10.
        Ok(())
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn run_returns_correct_tick_count() {
        let hashes = run(42, 10);
        assert_eq!(hashes.len(), 10);
    }

    #[test]
    fn hashes_are_non_empty_strings() {
        let hashes = run(42, 5);
        for h in &hashes {
            assert!(!h.is_empty());
            assert_eq!(h.len(), 64, "SHA-256 hex must be 64 chars");
        }
    }

    #[test]
    fn simulation_advances_state() {
        // Hash must differ between tick 0 and tick 99 — state changes
        let hashes = run(42, 100);
        assert_ne!(
            hashes[0],
            *hashes.last().unwrap(),
            "Simulation must change world state — tick 0 and tick 99 must differ"
        );
    }

    #[test]
    fn different_seeds_produce_different_hashes() {
        let h42 = run(42, 50).pop().unwrap();
        let h43 = run(43, 50).pop().unwrap();
        assert_ne!(
            h42, h43,
            "Different seeds must produce different final hashes"
        );
    }

    // ── THE KEY TEST ──────────────────────────────────────────────────────────

    /// THE KEY TEST — 3 runs × 1000 ticks, all hashes identical.
    ///
    /// Phase 9 Milestone 1: if this passes, XACE is a proven deterministic platform.
    /// Every tick hash in all three runs must be byte-identical. A single mismatch
    /// at any tick means a D-rule violation exists in the runtime.
    #[test]
    fn three_runs_seed_42_tick_1000_hash_identical() {
        const TICKS: u64 = 1000;
        const SEED: u64 = 42;

        eprintln!("[Milestone1] Run A (seed={SEED}, ticks={TICKS})...");
        let hashes_a = run(SEED, TICKS);

        eprintln!("[Milestone1] Run B (seed={SEED}, ticks={TICKS})...");
        let hashes_b = run(SEED, TICKS);

        eprintln!("[Milestone1] Run C (seed={SEED}, ticks={TICKS})...");
        let hashes_c = run(SEED, TICKS);

        // Check ALL 1000 ticks — a late-emerging divergence is still a violation
        for tick in 0..TICKS as usize {
            assert_eq!(
                hashes_a[tick], hashes_b[tick],
                "DETERMINISM VIOLATION at tick {}: A={} B={}",
                tick, hashes_a[tick], hashes_b[tick]
            );
            assert_eq!(
                hashes_a[tick], hashes_c[tick],
                "DETERMINISM VIOLATION at tick {}: A={} C={}",
                tick, hashes_a[tick], hashes_c[tick]
            );
        }

        eprintln!(
            "[Milestone1] ✓ ARCHITECTURE PROVEN REAL — 3×{} ticks identical. hash@1000={}",
            TICKS,
            hashes_a.last().unwrap()
        );
    }
}
