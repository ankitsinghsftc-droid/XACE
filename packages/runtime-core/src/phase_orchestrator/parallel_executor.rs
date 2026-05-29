//! # Parallel Executor
//!
//! Executes parallel system groups using a thread pool.
//! Systems within a parallel group run concurrently — their
//! outputs (mutations and events) are collected in thread-local
//! buffers and merged deterministically at phase end.
//!
//! ## Deterministic Parallel Execution
//! Parallel execution is safe because the SGC guarantees:
//! - No shared writes between systems in the same parallel group
//! - No RAW hazards between systems in the same parallel group
//!
//! Event buffers from parallel threads are merged in system_id
//! alphabetical order — not completion order — ensuring identical
//! merge result regardless of thread scheduling (D11).
//!
//! ## Phase 4 Implementation Note
//! Full thread-pool parallelism is implemented here conceptually.
//! The actual rayon or std::thread integration is straightforward
//! but requires careful lifetime management. For Phase 4 we implement
//! the deterministic merge logic — actual parallelism can be toggled.

use crate::component_tables::ComponentTableStore;
use crate::entity_store::EntityStore;
use crate::mutation_gate::MutationGate;
use crate::phase_orchestrator::system_registry::SystemRegistry;
use crate::query_engine::QueryEngine;
use std::collections::BTreeMap;
use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::events::event_struct::Event;

// ── Parallel Execution Result ─────────────────────────────────────────────────

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

// ── Parallel Executor ─────────────────────────────────────────────────────────

/// Executes system groups with deterministic output merging.
///
/// For sequential groups: systems run one-by-one in declaration order.
/// For parallel groups: systems run concurrently (Phase 4 runs sequentially
/// with deterministic merge ordering to establish the correct semantics).
///
/// ## Event Merge Order (D11)
/// Events from parallel systems are merged in system_id alphabetical order.
/// This guarantees identical event ordering regardless of thread scheduling.
pub struct ParallelExecutor;

impl ParallelExecutor {
    pub fn new() -> Self {
        Self
    }

    /// Executes a sequential group of systems in declaration order.
    ///
    /// Systems run one after another. Each system's mutations are
    /// visible to subsequent systems via the ComponentTableStore
    /// ONLY after apply_all() is called — not mid-phase.
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
        phase: u8,
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

            system.execute(&mut ctx).map_err(|e| {
                // Wrap with execution context
                XaceError::FatalError {
                    message: format!(
                        "System '{}' failed during phase {} tick {}: {}",
                        system_id,
                        phase,
                        tick,
                        e.message()
                    ),
                    context: ErrorContext::new("ParallelExecutor", "execute_sequential")
                        .with_tick(tick),
                    snapshot_recovery_possible: true,
                }
            })?;

            all_events.extend(ctx.emitted_events);
        }

        Ok(all_events)
    }

    /// Executes a parallel group of systems.
    ///
    /// In Phase 4, runs sequentially but merges events in system_id
    /// alphabetical order — establishing the correct deterministic
    /// semantics. Full parallelism is enabled by switching to rayon
    /// in Phase 6+ without changing merge behavior.
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
        phase: u8,
    ) -> Result<Vec<Event>, XaceError> {
        // Collect results per system — keyed by system_id for sorted merge
        let mut results: BTreeMap<String, Vec<Event>> = BTreeMap::new();

        // Execute each system (sequentially in Phase 4)
        // system_ids from parallel group are already sorted alphabetically (D11)
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

            system
                .execute(&mut ctx)
                .map_err(|e| XaceError::FatalError {
                    message: format!(
                        "System '{}' failed in parallel group phase {} tick {}: {}",
                        system_id,
                        phase,
                        tick,
                        e.message()
                    ),
                    context: ErrorContext::new("ParallelExecutor", "execute_parallel")
                        .with_tick(tick),
                    snapshot_recovery_possible: true,
                })?;

            results.insert(system_id.clone(), ctx.emitted_events);
        }

        // Merge events in system_id alphabetical order (D11)
        // BTreeMap iteration is already alphabetically sorted
        let merged: Vec<Event> = results.into_values().flatten().collect();
        Ok(merged)
    }
}

impl Default for ParallelExecutor {
    fn default() -> Self {
        Self::new()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::phase_orchestrator::system_registry::SystemRegistry;
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

    fn setup() -> (
        SystemRegistry,
        EntityStore,
        ComponentTableStore,
        MutationGate,
        QueryEngine,
    ) {
        use crate::component_tables::ComponentTableStore;
        use crate::entity_store::EntityStore;
        use crate::mutation_gate::MutationGate;
        use crate::query_engine::QueryEngine;

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
    fn sequential_execution_succeeds() {
        let (reg, es, ts, mut mg, mut qe) = setup();
        let executor = ParallelExecutor::new();
        let ids = vec!["sys_a".into(), "sys_b".into(), "sys_c".into()];
        let result = executor.execute_sequential(&ids, &reg, &es, &ts, &mut mg, &mut qe, 0, 42, 2);
        assert!(result.is_ok());
    }

    #[test]
    fn parallel_execution_succeeds() {
        let (reg, es, ts, mut mg, mut qe) = setup();
        let executor = ParallelExecutor::new();
        let ids = vec!["sys_a".into(), "sys_b".into()];
        let result = executor.execute_parallel(&ids, &reg, &es, &ts, &mut mg, &mut qe, 0, 42, 2);
        assert!(result.is_ok());
    }

    #[test]
    fn missing_system_returns_error() {
        let (reg, es, ts, mut mg, mut qe) = setup();
        let executor = ParallelExecutor::new();
        let ids = vec!["sys_missing".into()];
        let result = executor.execute_sequential(&ids, &reg, &es, &ts, &mut mg, &mut qe, 0, 42, 2);
        assert!(result.is_err());
    }
}
