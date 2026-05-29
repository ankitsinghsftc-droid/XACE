//! # System Context
//!
//! The controlled interface passed to each system during execute().
//! Provides read access to component data, mutation submission,
//! event emission, and deterministic RNG — all through controlled
//! boundaries that enforce declared read/write contracts.
//!
//! ## Access Control
//! Systems may only read components they declared in SystemDefinition.reads.
//! Systems may only write components they declared in SystemDefinition.writes.
//! Undeclared access returns a ValidationFailure error.
//!
//! ## Deferred Mutation (D4, I2)
//! submit_mutation() and submit_spawn() do not modify world state directly.
//! They queue requests in the MutationGate for application after the phase.

use crate::component_tables::ComponentTableStore;
use crate::entity_store::EntityStore;
use crate::mutation_gate::MutationGate;
use crate::query_engine::QueryEngine;
use std::collections::BTreeMap;
use xace_core::contracts::interfaces::ISystemContext;
use xace_core::entity_id::EntityID;
use xace_core::entity_metadata::Tick;
use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::events::event_struct::Event;

// ── System Context ────────────────────────────────────────────────────────────

/// Controlled world access for one system's execute() call.
///
/// Enforces declared read/write contracts. All mutations are deferred
/// to the MutationGate. Events are buffered for phase-end dispatch.
pub struct SystemContext<'a> {
    /// The system ID — used for access control error messages.
    system_id: &'a str,

    /// Component type IDs this system declared it reads.
    declared_reads: &'a [u32],

    /// Component type IDs this system declared it writes.
    declared_writes: &'a [u32],

    /// Read-only access to entity store.
    entity_store: &'a EntityStore,

    /// Read-only access to component tables.
    table_store: &'a ComponentTableStore,

    /// Mutable access to mutation gate for deferred mutations.
    mutation_gate: &'a mut MutationGate,

    /// Mutable access to query engine for entity queries.
    query_engine: &'a mut QueryEngine,

    /// Events emitted this execute() call — collected for EventBus.
    pub emitted_events: Vec<Event>,

    /// The current simulation tick.
    current_tick: Tick,

    /// Next deterministic random value index for this system this tick.
    rng_index: u64,

    /// World seed for deterministic RNG (D6).
    world_seed: u64,
}

impl<'a> SystemContext<'a> {
    /// Creates a new SystemContext for one system's execute() call.
    pub fn new(
        system_id: &'a str,
        declared_reads: &'a [u32],
        declared_writes: &'a [u32],
        entity_store: &'a EntityStore,
        table_store: &'a ComponentTableStore,
        mutation_gate: &'a mut MutationGate,
        query_engine: &'a mut QueryEngine,
        current_tick: Tick,
        world_seed: u64,
    ) -> Self {
        Self {
            system_id,
            declared_reads,
            declared_writes,
            entity_store,
            table_store,
            mutation_gate,
            query_engine,
            emitted_events: Vec::new(),
            current_tick,
            rng_index: 0,
            world_seed,
        }
    }

    /// Returns true if this system declared it reads the given component.
    fn can_read(&self, component_type_id: u32) -> bool {
        self.declared_reads.contains(&component_type_id)
            || self.declared_writes.contains(&component_type_id)
        // Writers can also read their own components
    }

    /// Returns true if this system declared it writes the given component.
    fn can_write(&self, component_type_id: u32) -> bool {
        self.declared_writes.contains(&component_type_id)
    }
}

impl<'a> ISystemContext for SystemContext<'a> {
    fn get_component(
        &self,
        entity_id: EntityID,
        component_type_id: u32,
    ) -> Result<Option<&str>, XaceError> {
        if !self.can_read(component_type_id) {
            return Err(XaceError::ValidationFailure {
                message: format!(
                    "System '{}' attempted to read component type_id {} \
                     which is not in its declared reads — add it to \
                     SystemDefinition.reads",
                    self.system_id, component_type_id
                ),
                context: ErrorContext::new(self.system_id, "get_component")
                    .with_tick(self.current_tick),
                rule_violated: "undeclared_read".into(),
                failed_path: format!("system:{}.reads.{}", self.system_id, component_type_id),
            });
        }
        Ok(self.table_store.get_component(entity_id, component_type_id))
    }

    fn query_entities(&self, component_type_ids: &[u32]) -> Result<Vec<EntityID>, XaceError> {
        // Validate all queried components are readable
        for &type_id in component_type_ids {
            if !self.can_read(type_id) {
                return Err(XaceError::ValidationFailure {
                    message: format!(
                        "System '{}' queried component type_id {} \
                         which is not declared — add to SystemDefinition.reads",
                        self.system_id, type_id
                    ),
                    context: ErrorContext::new(self.system_id, "query_entities")
                        .with_tick(self.current_tick),
                    rule_violated: "undeclared_read".into(),
                    failed_path: format!("system:{}", self.system_id),
                });
            }
        }
        // We need mutable access to query engine but have &self
        // In production this would use interior mutability or a different design.
        // For Phase 4 we return the store's direct intersection result.
        Ok(self
            .table_store
            .entities_with_all_components(component_type_ids))
    }

    fn submit_mutation(
        &mut self,
        entity_id: EntityID,
        component_type_id: u32,
        component_json: String,
    ) -> Result<(), XaceError> {
        if !self.can_write(component_type_id) {
            return Err(XaceError::ValidationFailure {
                message: format!(
                    "System '{}' attempted to write component type_id {} \
                     which is not in its declared writes — add it to \
                     SystemDefinition.writes",
                    self.system_id, component_type_id
                ),
                context: ErrorContext::new(self.system_id, "submit_mutation")
                    .with_tick(self.current_tick),
                rule_violated: "undeclared_write".into(),
                failed_path: format!("system:{}.writes.{}", self.system_id, component_type_id),
            });
        }

        // Determine if this is an add or modify
        if self.table_store.has_component(entity_id, component_type_id) {
            self.mutation_gate.request_modify_component(
                entity_id,
                component_type_id,
                component_json,
                self.entity_store,
                self.table_store,
                self.current_tick,
            )
        } else {
            self.mutation_gate.request_add_component(
                entity_id,
                component_type_id,
                component_json,
                self.entity_store,
                self.table_store,
                self.current_tick,
            )
        }
    }

    fn submit_spawn(
        &mut self,
        actor_id: String,
        initial_components: BTreeMap<u32, String>,
    ) -> Result<(), XaceError> {
        self.mutation_gate.request_spawn(
            actor_id,
            initial_components,
            self.table_store,
            self.current_tick,
        )
    }

    fn submit_destroy(&mut self, entity_id: EntityID) -> Result<(), XaceError> {
        self.mutation_gate
            .request_destroy(entity_id, self.entity_store, self.current_tick)
    }

    fn emit_event(&mut self, event: Event) -> Result<(), XaceError> {
        self.emitted_events.push(event);
        Ok(())
    }

    fn current_tick(&self) -> Tick {
        self.current_tick
    }

    fn next_random(&mut self) -> Result<f64, XaceError> {
        // Deterministic RNG: seed = hash(world_seed, system_id, tick, index)
        // Simple deterministic hash for Phase 4 — full DeterministicRNG in Phase 6
        let seed = self
            .world_seed
            .wrapping_mul(6364136223846793005)
            .wrapping_add(self.system_id.len() as u64)
            .wrapping_add(self.current_tick.wrapping_mul(2654435761))
            .wrapping_add(self.rng_index.wrapping_mul(1442695040888963407));

        self.rng_index += 1;

        // Convert to f64 in [0.0, 1.0)
        let value = (seed >> 11) as f64 / (1u64 << 53) as f64;
        Ok(value)
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::component_tables::ComponentTableStore;
    use crate::entity_store::EntityStore;
    use crate::mutation_gate::MutationGate;
    use crate::query_engine::QueryEngine;

    fn setup() -> (EntityStore, ComponentTableStore, MutationGate, QueryEngine) {
        let entity_store = EntityStore::new();
        let mut table_store = ComponentTableStore::new();
        table_store.register_table(1, "COMP_TRANSFORM_V1").unwrap();
        table_store.register_table(2, "COMP_IDENTITY_V1").unwrap();
        let mutation_gate = MutationGate::new();
        let query_engine = QueryEngine::new();
        (entity_store, table_store, mutation_gate, query_engine)
    }

    #[test]
    fn get_component_declared_read_succeeds() {
        let (mut es, mut ts, mut mg, mut qe) = setup();
        let id = es.create_entity(0).unwrap();
        ts.add_component(id, 1, r#"{"x":1.0}"#.into(), 0).unwrap();

        let mut ctx = SystemContext::new("sys_test", &[1], &[], &es, &ts, &mut mg, &mut qe, 0, 42);
        let result = ctx.get_component(id, 1).unwrap();
        assert_eq!(result, Some(r#"{"x":1.0}"#));
    }

    #[test]
    fn get_component_undeclared_read_fails() {
        let (es, ts, mut mg, mut qe) = setup();
        let mut ctx = SystemContext::new("sys_test", &[], &[], &es, &ts, &mut mg, &mut qe, 0, 42);
        assert!(ctx.get_component(1, 1).is_err());
    }

    #[test]
    fn submit_mutation_undeclared_write_fails() {
        let (mut es, ts, mut mg, mut qe) = setup();
        let _ = es.create_entity(0).unwrap();
        let mut ctx = SystemContext::new(
            "sys_test",
            &[1],
            &[], // reads 1 but does not write 1
            &es,
            &ts,
            &mut mg,
            &mut qe,
            0,
            42,
        );
        assert!(ctx.submit_mutation(1, 1, "{}".into()).is_err());
    }

    #[test]
    fn submit_mutation_declared_write_succeeds() {
        let (mut es, mut ts, mut mg, mut qe) = setup();
        let id = es.create_entity(0).unwrap();
        ts.add_component(id, 1, "{}".into(), 0).unwrap();
        let mut ctx = SystemContext::new("sys_test", &[1], &[1], &es, &ts, &mut mg, &mut qe, 0, 42);
        assert!(ctx.submit_mutation(id, 1, r#"{"x":5}"#.into()).is_ok());
        assert_eq!(mg.pending_count(), 1);
    }

    #[test]
    fn writers_can_also_read() {
        let (mut es, mut ts, mut mg, mut qe) = setup();
        let id = es.create_entity(0).unwrap();
        ts.add_component(id, 1, "{}".into(), 0).unwrap();
        let mut ctx = SystemContext::new(
            "sys_test",
            &[],
            &[1], // only writes, no explicit reads
            &es,
            &ts,
            &mut mg,
            &mut qe,
            0,
            42,
        );
        // Should succeed because writers can read their own components
        assert!(ctx.get_component(id, 1).is_ok());
    }

    #[test]
    fn current_tick_correct() {
        let (es, ts, mut mg, mut qe) = setup();
        let ctx = SystemContext::new("sys_test", &[], &[], &es, &ts, &mut mg, &mut qe, 42, 0);
        assert_eq!(ctx.current_tick(), 42);
    }

    #[test]
    fn next_random_deterministic() {
        let (es, ts, mut mg1, mut qe1) = setup();
        let (_, _, mut mg2, mut qe2) = setup();
        let mut ctx1 = SystemContext::new(
            "sys_test",
            &[],
            &[],
            &es,
            &ts,
            &mut mg1,
            &mut qe1,
            10,
            12345,
        );
        let mut ctx2 = SystemContext::new(
            "sys_test",
            &[],
            &[],
            &es,
            &ts,
            &mut mg2,
            &mut qe2,
            10,
            12345,
        );
        for _ in 0..10 {
            assert_eq!(ctx1.next_random().unwrap(), ctx2.next_random().unwrap());
        }
    }

    #[test]
    fn next_random_in_range() {
        let (es, ts, mut mg, mut qe) = setup();
        let mut ctx =
            SystemContext::new("sys_test", &[], &[], &es, &ts, &mut mg, &mut qe, 0, 99999);
        for _ in 0..100 {
            let v = ctx.next_random().unwrap();
            assert!(v >= 0.0 && v < 1.0);
        }
    }

    #[test]
    fn emit_event_stored_in_context() {
        use xace_core::events::event_struct::Event;
        use xace_core::events::event_type::EventType;
        use xace_core::runtime::phase_enum::PhaseEnum;

        let (es, ts, mut mg, mut qe) = setup();
        let mut ctx = SystemContext::new("sys_test", &[], &[], &es, &ts, &mut mg, &mut qe, 0, 0);
        let event = Event::broadcast(1, EventType::EntitySpawned, 0, PhaseEnum::Simulation);
        ctx.emit_event(event).unwrap();
        assert_eq!(ctx.emitted_events.len(), 1);
    }
}
