//! # Parallel Executor
//!
//! Executes SGC system groups with deterministic output merging.
//! SGC groups marked `parallel=true` are parallel-eligible schedule groups, not
//! a promise that this runtime currently uses worker threads.
//!
//! ## Deterministic Parallel-Eligible Execution
//! SGC-parallel-eligible execution is safe because the SGC guarantees:
//! - No shared writes between systems in the same group
//! - No RAW hazards between systems in the same group
//!
//! Event buffers from SGC-parallel-eligible groups are merged in system_id
//! alphabetical order, ensuring identical merge results if a future policy
//! enables true worker-thread execution (D11).
//!
//! ## Current Execution Policy
//! The standalone runtime uses `deterministic_sequential`: systems in a
//! SGC-parallel-eligible group are invoked one at a time in the persisted SGC
//! order. This keeps replay behavior explicit and avoids claiming concurrency
//! until a thread-pool policy is implemented, tested, and benchmarked.

use crate::component_tables::ComponentTableStore;
use crate::determinism_guard::determinism_guard::DeterminismGuard;
use crate::determinism_guard::rng_interceptor::RngInterceptor;
use crate::entity_store::EntityStore;
use crate::mutation_gate::MutationGate;
use crate::phase_orchestrator::system_registry::SystemRegistry;
use crate::query_engine::QueryEngine;
use std::collections::BTreeMap;
use std::fmt;
use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::events::event_struct::Event;
use xace_core::runtime::phase_enum::PhaseEnum;

/// The collected output from one system's execute() call.
///
/// Contains the events emitted and any errors encountered.
/// Mutations are already queued in the MutationGate via SystemContext.
#[derive(Debug)]
pub struct SystemExecutionResult {
    pub system_id: String,
    pub emitted_events: Vec<Event>,
    pub error: Option<XaceError>,
}

/// Runtime policy for SGC groups marked `parallel=true`.
///
/// The SGC flag means a group is dependency-safe for parallel execution. This
/// policy records how the standalone runtime actually invokes those systems.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ParallelGroupExecutionPolicy {
    /// Invoke systems one at a time in persisted SGC order, with deterministic
    /// event merge ordering and no worker threads.
    DeterministicSequential,
}

impl ParallelGroupExecutionPolicy {
    /// Stable machine-readable policy identifier for reports and tests.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::DeterministicSequential => "deterministic_sequential",
        }
    }

    /// Whether this policy currently schedules systems on worker threads.
    pub fn uses_worker_threads(self) -> bool {
        match self {
            Self::DeterministicSequential => false,
        }
    }
}

impl fmt::Display for ParallelGroupExecutionPolicy {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

/// Executes system groups with deterministic output merging.
///
/// For sequential groups: systems run one-by-one in declaration order.
/// For SGC-parallel-eligible groups: systems run according to
/// [`ParallelGroupExecutionPolicy`]. The current default is deterministic
/// sequential execution with no worker threads.
///
/// ## Event Merge Order (D11)
/// Events from SGC-parallel-eligible systems are merged in system_id
/// alphabetical order. This preserves replay order now and is the required
/// merge order for any future worker-thread policy.
pub struct ParallelExecutor {
    parallel_group_policy: ParallelGroupExecutionPolicy,
}

impl ParallelExecutor {
    pub fn new() -> Self {
        Self::with_policy(ParallelGroupExecutionPolicy::DeterministicSequential)
    }

    pub fn with_policy(parallel_group_policy: ParallelGroupExecutionPolicy) -> Self {
        Self {
            parallel_group_policy,
        }
    }

    pub fn parallel_group_policy(&self) -> ParallelGroupExecutionPolicy {
        self.parallel_group_policy
    }

    /// Executes a sequential group of systems in declaration order.
    ///
    /// Systems run one after another. Each system's mutations are visible to
    /// subsequent systems via the ComponentTableStore only after apply_all() is
    /// called, not mid-phase.
    pub fn execute_sequential(
        &self,
        system_ids: &[String],
        registry: &SystemRegistry,
        entity_store: &EntityStore,
        table_store: &ComponentTableStore,
        mutation_gate: &mut MutationGate,
        query_engine: &mut QueryEngine,
        tick: u64,
        world_seed: u64,
        phase: PhaseEnum,
        mut guard: Option<&mut DeterminismGuard>,
        rng_interceptor: Option<&RngInterceptor>,
    ) -> Result<Vec<Event>, XaceError> {
        let mut all_events: Vec<Event> = Vec::new();

        for system_id in system_ids {
            let system = registry
                .get(system_id)
                .ok_or_else(|| XaceError::ValidationFailure {
                    message: format!(
                        "System '{}' not found in SystemRegistry during execution",
                        system_id
                    ),
                    context: ErrorContext::new("ParallelExecutor", "execute_sequential")
                        .with_tick(tick),
                    rule_violated: "D1".into(),
                    failed_path: format!("system:{}", system_id),
                })?;

            let mut ctx = super::system_context::SystemContext::new(
                system.system_id(),
                system.declared_reads(),
                system.declared_writes(),
                entity_store,
                table_store,
                mutation_gate,
                query_engine,
                tick,
                world_seed,
            );
            if let Some(interceptor) = rng_interceptor {
                ctx = ctx.with_rng_interceptor(interceptor);
            }

            if let Some(guard) = guard.as_deref_mut() {
                guard.hook_system_execute(tick, phase, system.system_id())?;
                ctx = ctx.with_determinism_guard(guard);
            }

            let _rng_window = rng_interceptor
                .map(|interceptor| interceptor.open_window(system.system_id(), tick));
            system
                .execute(&mut ctx)
                .map_err(|e| XaceError::FatalError {
                    message: format!(
                        "System '{}' failed during phase {} tick {}: {}",
                        system_id,
                        phase.as_u8(),
                        tick,
                        e.message()
                    ),
                    context: ErrorContext::new("ParallelExecutor", "execute_sequential")
                        .with_tick(tick),
                    snapshot_recovery_possible: true,
                })?;

            all_events.extend(ctx.emitted_events);
        }

        Ok(all_events)
    }

    /// Executes a SGC-parallel-eligible group of systems.
    ///
    /// Current policy: `deterministic_sequential`. The runtime invokes each
    /// system one at a time in the persisted SGC order and then merges events
    /// by system_id. This method name is retained for the existing scheduler
    /// surface, but it does not imply worker-thread execution.
    pub fn execute_parallel(
        &self,
        system_ids: &[String],
        registry: &SystemRegistry,
        entity_store: &EntityStore,
        table_store: &ComponentTableStore,
        mutation_gate: &mut MutationGate,
        query_engine: &mut QueryEngine,
        tick: u64,
        world_seed: u64,
        phase: PhaseEnum,
        mut guard: Option<&mut DeterminismGuard>,
        rng_interceptor: Option<&RngInterceptor>,
    ) -> Result<Vec<Event>, XaceError> {
        match self.parallel_group_policy {
            ParallelGroupExecutionPolicy::DeterministicSequential => {}
        }

        let mut results: BTreeMap<String, Vec<Event>> = BTreeMap::new();

        // Current policy executes each SGC-parallel-eligible system one at a
        // time. system_ids from persisted parallel groups are already sorted
        // alphabetically for deterministic event merge order (D11).
        for system_id in system_ids {
            let system = registry
                .get(system_id)
                .ok_or_else(|| XaceError::ValidationFailure {
                    message: format!("System '{}' not found in SystemRegistry", system_id),
                    context: ErrorContext::new("ParallelExecutor", "execute_parallel")
                        .with_tick(tick),
                    rule_violated: "D1".into(),
                    failed_path: format!("system:{}", system_id),
                })?;

            let mut ctx = super::system_context::SystemContext::new(
                system.system_id(),
                system.declared_reads(),
                system.declared_writes(),
                entity_store,
                table_store,
                mutation_gate,
                query_engine,
                tick,
                world_seed,
            );
            if let Some(interceptor) = rng_interceptor {
                ctx = ctx.with_rng_interceptor(interceptor);
            }

            if let Some(guard) = guard.as_deref_mut() {
                guard.hook_system_execute(tick, phase, system.system_id())?;
                ctx = ctx.with_determinism_guard(guard);
            }

            let _rng_window = rng_interceptor
                .map(|interceptor| interceptor.open_window(system.system_id(), tick));
            system
                .execute(&mut ctx)
                .map_err(|e| XaceError::FatalError {
                    message: format!(
                        "System '{}' failed in SGC-parallel group phase {} tick {}: {}",
                        system_id,
                        phase.as_u8(),
                        tick,
                        e.message()
                    ),
                    context: ErrorContext::new("ParallelExecutor", "execute_parallel")
                        .with_tick(tick),
                    snapshot_recovery_possible: true,
                })?;

            results.insert(system_id.clone(), ctx.emitted_events);
        }

        let merged: Vec<Event> = results.into_values().flatten().collect();
        Ok(merged)
    }
}

impl Default for ParallelExecutor {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::phase_orchestrator::system_registry::SystemRegistry;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;
    use std::time::Duration;
    use xace_core::contracts::interfaces::{ISystem, ISystemContext};

    struct CountingSystem {
        id: String,
    }

    impl ISystem for CountingSystem {
        fn system_id(&self) -> &str {
            &self.id
        }

        fn execute(&self, _ctx: &mut dyn ISystemContext) -> Result<(), XaceError> {
            Ok(())
        }

        fn declared_reads(&self) -> &[u32] {
            &[]
        }

        fn declared_writes(&self) -> &[u32] {
            &[]
        }
    }

    struct ConcurrencyProbeSystem {
        id: String,
        active: Arc<AtomicUsize>,
        max_active: Arc<AtomicUsize>,
    }

    impl ISystem for ConcurrencyProbeSystem {
        fn system_id(&self) -> &str {
            &self.id
        }

        fn execute(&self, _ctx: &mut dyn ISystemContext) -> Result<(), XaceError> {
            let active_now = self.active.fetch_add(1, Ordering::SeqCst) + 1;
            self.max_active.fetch_max(active_now, Ordering::SeqCst);
            std::thread::sleep(Duration::from_millis(5));
            self.active.fetch_sub(1, Ordering::SeqCst);
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
        SystemRegistry,
        EntityStore,
        ComponentTableStore,
        MutationGate,
        QueryEngine,
    ) {
        let mut registry = SystemRegistry::new();
        registry
            .register(Box::new(CountingSystem { id: "sys_a".into() }))
            .unwrap();
        registry
            .register(Box::new(CountingSystem { id: "sys_b".into() }))
            .unwrap();
        registry
            .register(Box::new(CountingSystem { id: "sys_c".into() }))
            .unwrap();

        (
            registry,
            EntityStore::new(),
            ComponentTableStore::new(),
            MutationGate::new(),
            QueryEngine::new(),
        )
    }

    #[test]
    fn default_policy_is_deterministic_sequential() {
        let executor = ParallelExecutor::new();

        assert_eq!(
            executor.parallel_group_policy(),
            ParallelGroupExecutionPolicy::DeterministicSequential
        );
        assert_eq!(
            executor.parallel_group_policy().as_str(),
            "deterministic_sequential"
        );
        assert_eq!(
            executor.parallel_group_policy().to_string(),
            "deterministic_sequential"
        );
        assert!(!executor.parallel_group_policy().uses_worker_threads());
    }

    #[test]
    fn sequential_execution_succeeds() {
        let (reg, es, ts, mut mg, mut qe) = setup();
        let executor = ParallelExecutor::new();
        let ids = vec!["sys_a".into(), "sys_b".into(), "sys_c".into()];
        let result = executor.execute_sequential(
            &ids,
            &reg,
            &es,
            &ts,
            &mut mg,
            &mut qe,
            0,
            42,
            PhaseEnum::Simulation,
            None,
            None,
        );
        assert!(result.is_ok());
    }

    #[test]
    fn sgc_parallel_eligible_execution_succeeds() {
        let (reg, es, ts, mut mg, mut qe) = setup();
        let executor = ParallelExecutor::new();
        let ids = vec!["sys_a".into(), "sys_b".into()];
        let result = executor.execute_parallel(
            &ids,
            &reg,
            &es,
            &ts,
            &mut mg,
            &mut qe,
            0,
            42,
            PhaseEnum::Simulation,
            None,
            None,
        );
        assert!(result.is_ok());
    }

    #[test]
    fn sgc_parallel_group_policy_is_sequential_not_concurrent() {
        let active = Arc::new(AtomicUsize::new(0));
        let max_active = Arc::new(AtomicUsize::new(0));
        let mut registry = SystemRegistry::new();
        let ids = vec![
            "probe_a".to_string(),
            "probe_b".to_string(),
            "probe_c".to_string(),
        ];

        for id in &ids {
            registry
                .register(Box::new(ConcurrencyProbeSystem {
                    id: id.clone(),
                    active: Arc::clone(&active),
                    max_active: Arc::clone(&max_active),
                }))
                .unwrap();
        }

        let entity_store = EntityStore::new();
        let table_store = ComponentTableStore::new();
        let mut mutation_gate = MutationGate::new();
        let mut query_engine = QueryEngine::new();
        let executor = ParallelExecutor::new();
        let result = executor.execute_parallel(
            &ids,
            &registry,
            &entity_store,
            &table_store,
            &mut mutation_gate,
            &mut query_engine,
            0,
            42,
            PhaseEnum::Simulation,
            None,
            None,
        );

        assert!(result.is_ok());
        assert_eq!(active.load(Ordering::SeqCst), 0);
        assert_eq!(max_active.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn missing_system_returns_error() {
        let (reg, es, ts, mut mg, mut qe) = setup();
        let executor = ParallelExecutor::new();
        let ids = vec!["sys_missing".into()];
        let result = executor.execute_sequential(
            &ids,
            &reg,
            &es,
            &ts,
            &mut mg,
            &mut qe,
            0,
            42,
            PhaseEnum::Simulation,
            None,
            None,
        );
        assert!(result.is_err());
    }
}
