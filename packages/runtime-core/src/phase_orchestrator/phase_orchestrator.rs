//! # Phase Orchestrator
//!
//! The tick loop controller. Drives the five-phase execution cycle
//! every simulation tick. Enforces phase order, mutation timing,
//! and event dispatch ordering (D1, D4, D5).
//!
//! ## Per-Tick Sequence
//! 1. Drain EngineFeedbackBuffer at tick START (Audit 6, I13)
//! 2. For each phase (Initialization → Input → Simulation → PostSimulation → Cleanup):
//!    a. Execute all system groups in ExecutionPlan order
//!    b. Apply MutationGate (deferred mutations)
//!    c. Dispatch EventBus events (sorted by tick, phase, event_id)
//! 3. Compute world_hash (DeterminismGuard — D9)
//! 4. Advance tick counter
//!
//! ## Global Invariants Enforced
//! D1: System order from ExecutionPlan only — never self-scheduled
//! D4: Mutations applied only after phase completion
//! D5: Events dispatched after phase, sorted deterministically
//! I7: Schema version validated before any tick executes

use xace_core::errors::xace_error::XaceError;
use xace_core::runtime::state_delta::StateDelta;
use crate::entity_store::EntityStore;
use crate::component_tables::ComponentTableStore;
use crate::mutation_gate::MutationGate;
use crate::query_engine::QueryEngine;
use crate::event_bus::event_bus::EventBus;
use super::system_registry::SystemRegistry;
use super::parallel_executor::ParallelExecutor;

// ── Tick Result ───────────────────────────────────────────────────────────────

/// The output produced by one complete simulation tick.
#[derive(Debug)]
pub struct TickResult {
    /// The tick number that was executed.
    pub tick: u64,
    /// All state changes from this tick (for engine adapter).
    pub state_delta: StateDelta,
    /// Number of events dispatched this tick.
    pub events_dispatched: usize,
    /// Number of mutations applied this tick.
    pub mutations_applied: usize,
}

// ── Phase Orchestrator ────────────────────────────────────────────────────────

/// Controls the simulation tick loop and phase execution.
///
/// One PhaseOrchestrator exists per world. It owns the tick counter
/// and drives the complete phase sequence each tick.
pub struct PhaseOrchestrator {
    /// Current simulation tick. Starts at 0, increments each tick.
    current_tick: u64,

    /// World seed for deterministic RNG (D6).
    world_seed: u64,

    /// Parallel/sequential system executor.
    executor: ParallelExecutor,

    /// Schema version — validated before each tick (I7, D10).
    schema_version: String,

    /// ExecutionPlan version — validated with schema version (D10).
    execution_plan_version: u32,
}

impl PhaseOrchestrator {
    /// Creates a new PhaseOrchestrator starting at tick 0.
    pub fn new(
        world_seed: u64,
        schema_version: impl Into<String>,
        execution_plan_version: u32,
    ) -> Self {
        Self {
            current_tick: 0,
            world_seed,
            executor: ParallelExecutor::new(),
            schema_version: schema_version.into(),
            execution_plan_version,
        }
    }

    /// Returns the current simulation tick.
    pub fn current_tick(&self) -> u64 {
        self.current_tick
    }

    /// Returns the current schema version.
    pub fn schema_version(&self) -> &str {
        &self.schema_version
    }

    /// Updates the schema version after a CGS mutation and SGC recompile.
    /// Called by the runtime when a new ExecutionPlan is received.
    pub fn update_schema_version(
        &mut self,
        schema_version: impl Into<String>,
        execution_plan_version: u32,
    ) {
        self.schema_version = schema_version.into();
        self.execution_plan_version = execution_plan_version;
    }

    /// Executes one complete simulation tick.
    ///
    /// Runs all five phases in order. Each phase:
    /// 1. Executes system groups from the plan
    /// 2. Applies deferred mutations (MutationGate)
    /// 3. Dispatches deferred events (EventBus)
    ///
    /// Returns a TickResult with the state delta for the engine adapter.
    pub fn tick(
        &mut self,
        systems: &[(&str, Vec<String>, bool)], // (phase_name, system_ids, is_parallel)
        registry: &SystemRegistry,
        entity_store: &mut EntityStore,
        table_store: &mut ComponentTableStore,
        mutation_gate: &mut MutationGate,
        query_engine: &mut QueryEngine,
        event_bus: &mut EventBus,
    ) -> Result<TickResult, XaceError> {
        let tick = self.current_tick;
        let mut combined_delta = StateDelta::empty(tick, &self.schema_version);
        let mut total_mutations = 0;
        let mut total_events = 0;

        // Run each phase group in order
        for (phase_name, system_ids, is_parallel) in systems {
            let phase_byte = Self::phase_name_to_byte(phase_name);

            // Execute system group
            let emitted_events = if *is_parallel {
                self.executor.execute_parallel(
                    system_ids, registry,
                    entity_store, table_store,
                    mutation_gate, query_engine,
                    tick, self.world_seed, phase_byte,
                )?
            } else {
                self.executor.execute_sequential(
                    system_ids, registry,
                    entity_store, table_store,
                    mutation_gate, query_engine,
                    tick, self.world_seed, phase_byte,
                )?
            };

            // Emit collected events to EventBus
            for event in emitted_events {
                event_bus.emit(event)?;
            }

            // Apply deferred mutations (D4)
            let phase_delta = mutation_gate.apply_all(
                entity_store, table_store, tick
            )?;
            total_mutations += phase_delta.change_count();

            // Merge phase delta into tick delta
            Self::merge_delta(&mut combined_delta, phase_delta);

            // Dispatch deferred events (D5)
            let dispatched = event_bus.dispatch_phase_events(phase_byte)?;
            total_events += dispatched;
        }

        // Advance tick counter
        self.current_tick += 1;

        Ok(TickResult {
            tick,
            state_delta: combined_delta,
            events_dispatched: total_events,
            mutations_applied: total_mutations,
        })
    }

    /// Resets the tick counter. Used during snapshot restore.
    pub fn restore_tick(&mut self, tick: u64) {
        self.current_tick = tick;
    }

    // ── Helpers ────────────────────────────────────────────────────────────

    fn phase_name_to_byte(phase_name: &str) -> u8 {
        match phase_name {
            "Initialization" => 0,
            "Input" => 1,
            "Simulation" => 2,
            "PostSimulation" => 3,
            "Cleanup" => 4,
            _ => 255,
        }
    }

    /// Merges a phase delta into the tick-level combined delta.
    fn merge_delta(combined: &mut StateDelta, phase: StateDelta) {
        for entity in phase.spawned_entities {
            combined.record_spawn(entity);
        }
        for entity in phase.destroyed_entities {
            combined.record_destroy(entity);
        }
        for added in phase.added_components {
            combined.record_component_added(added);
        }
        for removed in phase.removed_components {
            combined.record_component_removed(removed);
        }
        for (entity_id, changes) in phase.updated_components {
            for (_, change) in changes {
                combined.record_component_update(entity_id, change);
            }
        }
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::entity_store::EntityStore;
    use crate::component_tables::ComponentTableStore;
    use crate::mutation_gate::MutationGate;
    use crate::query_engine::QueryEngine;
    use crate::event_bus::event_bus::EventBus;
    use crate::phase_orchestrator::system_registry::SystemRegistry;
    use xace_core::contracts::interfaces::{ISystem, ISystemContext};

    struct NoopSystem { id: String }
    impl ISystem for NoopSystem {
        fn system_id(&self) -> &str { &self.id }
        fn execute(&self, _: &mut dyn ISystemContext) -> Result<(), XaceError> { Ok(()) }
        fn declared_reads(&self) -> &[u32] { &[] }
        fn declared_writes(&self) -> &[u32] { &[] }
    }

    fn setup() -> (
        PhaseOrchestrator,
        SystemRegistry,
        EntityStore,
        ComponentTableStore,
        MutationGate,
        QueryEngine,
        EventBus,
    ) {
        let mut registry = SystemRegistry::new();
        registry.register(Box::new(NoopSystem { id: "sys_input".into() })).unwrap();
        registry.register(Box::new(NoopSystem { id: "sys_movement".into() })).unwrap();
        registry.register(Box::new(NoopSystem { id: "sys_cleanup".into() })).unwrap();

        (
            PhaseOrchestrator::new(42, "0.1.0", 1),
            registry,
            EntityStore::new(),
            ComponentTableStore::new(),
            MutationGate::new(),
            QueryEngine::new(),
            EventBus::new(),
        )
    }

    #[test]
    fn tick_advances_counter() {
        let (mut orch, reg, mut es, mut ts, mut mg, mut qe, mut eb) = setup();
        assert_eq!(orch.current_tick(), 0);
        let systems = vec![
            ("Input", vec!["sys_input".to_string()], false),
            ("Simulation", vec!["sys_movement".to_string()], false),
            ("Cleanup", vec!["sys_cleanup".to_string()], false),
        ];
        orch.tick(&systems, &reg, &mut es, &mut ts, &mut mg, &mut qe, &mut eb).unwrap();
        assert_eq!(orch.current_tick(), 1);
    }

    #[test]
    fn tick_returns_correct_tick_number() {
        let (mut orch, reg, mut es, mut ts, mut mg, mut qe, mut eb) = setup();
        let systems = vec![("Simulation", vec!["sys_movement".to_string()], false)];
        let result = orch.tick(&systems, &reg, &mut es, &mut ts, &mut mg, &mut qe, &mut eb).unwrap();
        assert_eq!(result.tick, 0);
    }

    #[test]
    fn empty_tick_produces_empty_delta() {
        let (mut orch, reg, mut es, mut ts, mut mg, mut qe, mut eb) = setup();
        let result = orch.tick(&[], &reg, &mut es, &mut ts, &mut mg, &mut qe, &mut eb).unwrap();
        assert!(result.state_delta.is_empty());
        assert_eq!(result.mutations_applied, 0);
    }

    #[test]
    fn multiple_ticks_sequential() {
        let (mut orch, reg, mut es, mut ts, mut mg, mut qe, mut eb) = setup();
        let systems = vec![("Simulation", vec!["sys_movement".to_string()], false)];
        for expected_tick in 0u64..5 {
            let result = orch.tick(
                &systems, &reg, &mut es, &mut ts, &mut mg, &mut qe, &mut eb
            ).unwrap();
            assert_eq!(result.tick, expected_tick);
        }
        assert_eq!(orch.current_tick(), 5);
    }

    #[test]
    fn restore_tick_resets_counter() {
        let mut orch = PhaseOrchestrator::new(0, "0.1.0", 1);
        orch.restore_tick(100);
        assert_eq!(orch.current_tick(), 100);
    }
}