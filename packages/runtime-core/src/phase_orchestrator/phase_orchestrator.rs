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
//! 3. Compute the canonical end-of-tick world hash
//! 4. Return the combined tick delta, emitted events, and hash
//! 5. Advance tick counter
//!
//! RuntimeOrchestrator owns DeterminismGuard for the session and calls the
//! guarded tick path here so tick, phase, system, and hash boundaries are
//! recorded during live execution.
//!
//! ## Global Invariants Enforced
//! D1: System order from caller-provided ExecutionPlan groups — never self-scheduled
//! D4: Mutations applied only after phase completion
//! D5: Events dispatched after phase, sorted deterministically
//! I7: Schema version is carried with tick deltas; live guard validation pending

use super::parallel_executor::{ParallelExecutor, ParallelGroupExecutionPolicy};
use super::system_registry::SystemRegistry;
use crate::component_tables::ComponentTableStore;
use crate::determinism_guard::determinism_guard::DeterminismGuard;
use crate::determinism_guard::rng_interceptor::RngInterceptor;
use crate::determinism_guard::world_hasher::WorldHasher;
use crate::entity_store::EntityStore;
use crate::event_bus::event_bus::EventBus;
use crate::mutation_gate::MutationGate;
use crate::query_engine::QueryEngine;
use crate::snapshot_engine::SnapshotEngine;
use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::events::event_struct::Event;
use xace_core::runtime::phase_enum::PhaseEnum;
use xace_core::runtime::state_delta::StateDelta;

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
    /// Events emitted by systems this tick, in deterministic phase/system order.
    pub emitted_events: Vec<Event>,
    /// Canonical 64-character SHA-256 world hash at tick end.
    pub world_hash: String,
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

    /// Sequential and SGC-parallel-eligible system executor.
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

    /// Returns the current execution plan version.
    pub fn execution_plan_version(&self) -> u32 {
        self.execution_plan_version
    }

    /// Returns how SGC groups marked `parallel=true` are executed.
    pub fn parallel_group_execution_policy(&self) -> ParallelGroupExecutionPolicy {
        self.executor.parallel_group_policy()
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
        self.tick_inner(
            systems,
            registry,
            entity_store,
            table_store,
            mutation_gate,
            query_engine,
            event_bus,
            None,
            None,
            "",
        )
    }

    /// Executes one simulation tick with live determinism hooks enabled.
    pub fn tick_with_guard(
        &mut self,
        systems: &[(&str, Vec<String>, bool)], // (phase_name, system_ids, is_parallel)
        registry: &SystemRegistry,
        entity_store: &mut EntityStore,
        table_store: &mut ComponentTableStore,
        mutation_gate: &mut MutationGate,
        query_engine: &mut QueryEngine,
        event_bus: &mut EventBus,
        guard: &mut DeterminismGuard,
        rng_interceptor: &RngInterceptor,
        cgs_hash: &str,
    ) -> Result<TickResult, XaceError> {
        self.tick_inner(
            systems,
            registry,
            entity_store,
            table_store,
            mutation_gate,
            query_engine,
            event_bus,
            Some(guard),
            Some(rng_interceptor),
            cgs_hash,
        )
    }

    fn tick_inner(
        &mut self,
        systems: &[(&str, Vec<String>, bool)], // (phase_name, system_ids, is_parallel)
        registry: &SystemRegistry,
        entity_store: &mut EntityStore,
        table_store: &mut ComponentTableStore,
        mutation_gate: &mut MutationGate,
        query_engine: &mut QueryEngine,
        event_bus: &mut EventBus,
        mut guard: Option<&mut DeterminismGuard>,
        rng_interceptor: Option<&RngInterceptor>,
        cgs_hash: &str,
    ) -> Result<TickResult, XaceError> {
        let tick = self.current_tick;
        let mut combined_delta = StateDelta::empty(tick, &self.schema_version);
        let mut total_mutations = 0;
        let mut total_events = 0;
        let mut all_emitted_events = Vec::new();

        if let Some(guard) = guard.as_deref_mut() {
            guard.hook_tick_start(tick, &self.schema_version, self.execution_plan_version)?;
        }

        // Run each phase group in order
        for (phase_name, system_ids, is_parallel) in systems {
            let phase = Self::phase_name_to_enum(phase_name)?;
            let phase_byte = phase.as_u8();

            if let Some(guard) = guard.as_deref_mut() {
                guard.hook_phase_start(tick, phase)?;
            }

            // Execute system group
            let emitted_events = if *is_parallel {
                self.executor.execute_parallel(
                    system_ids,
                    registry,
                    entity_store,
                    table_store,
                    mutation_gate,
                    query_engine,
                    tick,
                    self.world_seed,
                    phase,
                    guard.as_deref_mut(),
                    rng_interceptor,
                )?
            } else {
                self.executor.execute_sequential(
                    system_ids,
                    registry,
                    entity_store,
                    table_store,
                    mutation_gate,
                    query_engine,
                    tick,
                    self.world_seed,
                    phase,
                    guard.as_deref_mut(),
                    rng_interceptor,
                )?
            };

            // Emit collected events to EventBus
            for event in &emitted_events {
                event_bus.emit(event.clone())?;
            }
            all_emitted_events.extend(emitted_events);

            // Apply deferred mutations (D4)
            let phase_delta = mutation_gate.apply_all_with_runtime_state(
                entity_store,
                table_store,
                Some(&mut *event_bus),
                rng_interceptor,
                tick,
            )?;
            total_mutations += phase_delta.change_count();

            // Merge phase delta into tick delta
            Self::merge_delta(&mut combined_delta, phase_delta);

            // Dispatch deferred events (D5)
            let dispatched = event_bus.dispatch_phase_events(phase_byte)?;
            total_events += dispatched;

            if let Some(guard) = guard.as_deref_mut() {
                guard.hook_phase_end(tick, phase)?;
            }
        }

        let mut snapshot_engine = SnapshotEngine::standard(
            self.schema_version.clone(),
            self.execution_plan_version,
            self.world_seed,
        );
        let mut snapshot = snapshot_engine.take_snapshot(tick, entity_store, table_store)?;
        snapshot.cgs_hash = cgs_hash.to_string();
        snapshot.world_hash.clear();
        let world_hash = if let Some(guard) = guard.as_deref_mut() {
            let hash = guard.hook_tick_end(&snapshot)?;
            snapshot.world_hash = hash.clone();
            hash
        } else {
            let hash = WorldHasher::compute(&snapshot);
            snapshot.world_hash = hash.clone();
            hash
        };

        // Advance tick counter
        self.current_tick += 1;

        Ok(TickResult {
            tick,
            state_delta: combined_delta,
            events_dispatched: total_events,
            mutations_applied: total_mutations,
            emitted_events: all_emitted_events,
            world_hash,
        })
    }

    /// Resets the tick counter. Used during snapshot restore.
    pub fn restore_tick(&mut self, tick: u64) {
        self.current_tick = tick;
    }

    // ── Helpers ────────────────────────────────────────────────────────────

    fn phase_name_to_enum(phase_name: &str) -> Result<PhaseEnum, XaceError> {
        match phase_name {
            "Initialization" => Ok(PhaseEnum::Initialization),
            "Input" => Ok(PhaseEnum::Input),
            "Simulation" => Ok(PhaseEnum::Simulation),
            "PostSimulation" => Ok(PhaseEnum::PostSimulation),
            "Cleanup" => Ok(PhaseEnum::Cleanup),
            other => Err(XaceError::ValidationFailure {
                message: format!("Unknown execution phase '{}'", other),
                context: ErrorContext::new("PhaseOrchestrator", "phase_name_to_enum"),
                rule_violated: "D1".into(),
                failed_path: format!("phase:{}", other),
            }),
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
    use crate::component_tables::ComponentTableStore;
    use crate::determinism_guard::determinism_guard::DeterminismGuard;
    use crate::determinism_guard::rng_interceptor::RngInterceptor;
    use crate::entity_store::EntityStore;
    use crate::event_bus::event_bus::EventBus;
    use crate::mutation_gate::MutationGate;
    use crate::phase_orchestrator::system_registry::SystemRegistry;
    use crate::query_engine::QueryEngine;
    use xace_core::contracts::interfaces::{ISystem, ISystemContext};
    use xace_core::errors::determinism_error::GuardMode;
    use xace_core::fixed_point::Fixed64;

    struct NoopSystem {
        id: String,
    }
    impl ISystem for NoopSystem {
        fn system_id(&self) -> &str {
            &self.id
        }
        fn execute(&self, _: &mut dyn ISystemContext) -> Result<(), XaceError> {
            Ok(())
        }
        fn declared_reads(&self) -> &[u32] {
            &[]
        }
        fn declared_writes(&self) -> &[u32] {
            &[]
        }
    }

    struct EmittingSystem {
        id: String,
    }

    impl ISystem for EmittingSystem {
        fn system_id(&self) -> &str {
            &self.id
        }

        fn execute(&self, ctx: &mut dyn ISystemContext) -> Result<(), XaceError> {
            use xace_core::events::event_struct::Event;
            use xace_core::events::event_type::EventType;
            use xace_core::runtime::phase_enum::PhaseEnum;

            ctx.emit_event(Event::broadcast(
                1,
                EventType::Domain("interaction.accepted".to_string()),
                0,
                PhaseEnum::Simulation,
            ))
        }

        fn declared_reads(&self) -> &[u32] {
            &[]
        }

        fn declared_writes(&self) -> &[u32] {
            &[]
        }
    }

    struct RandomSystem {
        id: String,
    }

    impl ISystem for RandomSystem {
        fn system_id(&self) -> &str {
            &self.id
        }

        fn execute(&self, ctx: &mut dyn ISystemContext) -> Result<(), XaceError> {
            let first = ctx.next_random()?;
            let second = ctx.next_random()?;
            assert!((Fixed64::ZERO..Fixed64::ONE).contains(&first));
            assert!((Fixed64::ZERO..Fixed64::ONE).contains(&second));
            Ok(())
        }

        fn declared_reads(&self) -> &[u32] {
            &[]
        }

        fn declared_writes(&self) -> &[u32] {
            &[]
        }
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
        registry
            .register(Box::new(NoopSystem {
                id: "sys_input".into(),
            }))
            .unwrap();
        registry
            .register(Box::new(NoopSystem {
                id: "sys_movement".into(),
            }))
            .unwrap();
        registry
            .register(Box::new(NoopSystem {
                id: "sys_cleanup".into(),
            }))
            .unwrap();

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
        orch.tick(&systems, &reg, &mut es, &mut ts, &mut mg, &mut qe, &mut eb)
            .unwrap();
        assert_eq!(orch.current_tick(), 1);
    }

    #[test]
    fn tick_returns_correct_tick_number() {
        let (mut orch, reg, mut es, mut ts, mut mg, mut qe, mut eb) = setup();
        let systems = vec![("Simulation", vec!["sys_movement".to_string()], false)];
        let result = orch
            .tick(&systems, &reg, &mut es, &mut ts, &mut mg, &mut qe, &mut eb)
            .unwrap();
        assert_eq!(result.tick, 0);
    }

    #[test]
    fn empty_tick_produces_empty_delta() {
        let (mut orch, reg, mut es, mut ts, mut mg, mut qe, mut eb) = setup();
        let result = orch
            .tick(&[], &reg, &mut es, &mut ts, &mut mg, &mut qe, &mut eb)
            .unwrap();
        assert!(result.state_delta.is_empty());
        assert_eq!(result.mutations_applied, 0);
        assert_eq!(result.world_hash.len(), 64);
    }

    #[test]
    fn tick_returns_emitted_events_for_runtime_playback_resolution() {
        let (mut orch, mut reg, mut es, mut ts, mut mg, mut qe, mut eb) = setup();
        reg.register(Box::new(EmittingSystem {
            id: "sys_events".into(),
        }))
        .unwrap();
        let systems = vec![("Simulation", vec!["sys_events".to_string()], false)];

        let result = orch
            .tick(&systems, &reg, &mut es, &mut ts, &mut mg, &mut qe, &mut eb)
            .unwrap();

        assert_eq!(result.emitted_events.len(), 1);
        assert_eq!(result.events_dispatched, 1);
    }

    #[test]
    fn multiple_ticks_sequential() {
        let (mut orch, reg, mut es, mut ts, mut mg, mut qe, mut eb) = setup();
        let systems = vec![("Simulation", vec!["sys_movement".to_string()], false)];
        for expected_tick in 0u64..5 {
            let result = orch
                .tick(&systems, &reg, &mut es, &mut ts, &mut mg, &mut qe, &mut eb)
                .unwrap();
            assert_eq!(result.tick, expected_tick);
        }
        assert_eq!(orch.current_tick(), 5);
    }

    #[test]
    fn guarded_tick_records_canonical_world_hash() {
        let (mut orch, reg, mut es, mut ts, mut mg, mut qe, mut eb) = setup();
        let systems = vec![("Simulation", vec!["sys_movement".to_string()], false)];
        let mut guard = DeterminismGuard::new(
            GuardMode::Strict,
            orch.schema_version().to_string(),
            orch.execution_plan_version(),
        );
        guard.register_systems(&["sys_movement"]);
        let rng_interceptor = RngInterceptor::new(42, GuardMode::Strict);

        let result = orch
            .tick_with_guard(
                &systems,
                &reg,
                &mut es,
                &mut ts,
                &mut mg,
                &mut qe,
                &mut eb,
                &mut guard,
                &rng_interceptor,
                "aabbcc",
            )
            .unwrap();

        assert_eq!(result.world_hash.len(), 64);
        assert_eq!(
            guard.hash_at_tick(result.tick),
            Some(result.world_hash.as_str())
        );
        assert_eq!(orch.current_tick(), 1);
    }

    #[test]
    fn guarded_tick_rejects_unregistered_system_boundary() {
        let (mut orch, reg, mut es, mut ts, mut mg, mut qe, mut eb) = setup();
        let systems = vec![("Simulation", vec!["sys_movement".to_string()], false)];
        let mut guard = DeterminismGuard::new(
            GuardMode::Strict,
            orch.schema_version().to_string(),
            orch.execution_plan_version(),
        );
        let rng_interceptor = RngInterceptor::new(42, GuardMode::Strict);

        let result = orch.tick_with_guard(
            &systems,
            &reg,
            &mut es,
            &mut ts,
            &mut mg,
            &mut qe,
            &mut eb,
            &mut guard,
            &rng_interceptor,
            "aabbcc",
        );

        assert!(result.is_err());
        assert_eq!(orch.current_tick(), 0);
    }

    #[test]
    fn guarded_sequential_system_rng_uses_interceptor_window() {
        let (mut orch, mut reg, mut es, mut ts, mut mg, mut qe, mut eb) = setup();
        reg.register(Box::new(RandomSystem {
            id: "sys_random".into(),
        }))
        .unwrap();
        let systems = vec![("Simulation", vec!["sys_random".to_string()], false)];
        let mut guard = DeterminismGuard::new(
            GuardMode::Strict,
            orch.schema_version().to_string(),
            orch.execution_plan_version(),
        );
        guard.register_systems(&["sys_random"]);
        let rng_interceptor = RngInterceptor::new(42, GuardMode::Strict);

        orch.tick_with_guard(
            &systems,
            &reg,
            &mut es,
            &mut ts,
            &mut mg,
            &mut qe,
            &mut eb,
            &mut guard,
            &rng_interceptor,
            "aabbcc",
        )
        .unwrap();

        let metrics = rng_interceptor.metrics();
        assert_eq!(metrics.legal_access_count, 2);
        assert_eq!(metrics.windowless_access_count, 0);
        assert_eq!(rng_interceptor.violation_count(), 0);
    }

    #[test]
    fn guarded_parallel_system_rng_uses_interceptor_window() {
        let (mut orch, mut reg, mut es, mut ts, mut mg, mut qe, mut eb) = setup();
        reg.register(Box::new(RandomSystem {
            id: "sys_random_a".into(),
        }))
        .unwrap();
        reg.register(Box::new(RandomSystem {
            id: "sys_random_b".into(),
        }))
        .unwrap();
        let systems = vec![(
            "Simulation",
            vec!["sys_random_a".to_string(), "sys_random_b".to_string()],
            true,
        )];
        let mut guard = DeterminismGuard::new(
            GuardMode::Strict,
            orch.schema_version().to_string(),
            orch.execution_plan_version(),
        );
        guard.register_systems(&["sys_random_a", "sys_random_b"]);
        let rng_interceptor = RngInterceptor::new(42, GuardMode::Strict);

        orch.tick_with_guard(
            &systems,
            &reg,
            &mut es,
            &mut ts,
            &mut mg,
            &mut qe,
            &mut eb,
            &mut guard,
            &rng_interceptor,
            "aabbcc",
        )
        .unwrap();

        let metrics = rng_interceptor.metrics();
        assert_eq!(metrics.legal_access_count, 4);
        assert_eq!(metrics.windowless_access_count, 0);
        assert_eq!(rng_interceptor.violation_count(), 0);
    }

    #[test]
    fn restore_tick_resets_counter() {
        let mut orch = PhaseOrchestrator::new(0, "0.1.0", 1);
        orch.restore_tick(100);
        assert_eq!(orch.current_tick(), 100);
    }
}
