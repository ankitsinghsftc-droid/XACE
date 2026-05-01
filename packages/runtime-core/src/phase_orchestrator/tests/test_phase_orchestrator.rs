//! # Phase Orchestrator Integration Tests

use crate::phase_orchestrator::{PhaseOrchestrator, SystemRegistry};
use crate::entity_store::EntityStore;
use crate::component_tables::ComponentTableStore;
use crate::mutation_gate::MutationGate;
use crate::query_engine::QueryEngine;
use crate::event_bus::event_bus::EventBus;
use xace_core::contracts::interfaces::{ISystem, ISystemContext};
use xace_core::errors::xace_error::XaceError;

struct NoopSystem { id: String }
impl ISystem for NoopSystem {
    fn system_id(&self) -> &str { &self.id }
    fn execute(&self, _: &mut dyn ISystemContext) -> Result<(), XaceError> { Ok(()) }
    fn declared_reads(&self) -> &[u32] { &[] }
    fn declared_writes(&self) -> &[u32] { &[] }
}

fn full_setup() -> (
    PhaseOrchestrator, SystemRegistry,
    EntityStore, ComponentTableStore,
    MutationGate, QueryEngine, EventBus,
) {
    let mut registry = SystemRegistry::new();
    for id in ["sys_input", "sys_movement", "sys_ai", "sys_cleanup"] {
        registry.register(Box::new(NoopSystem { id: id.into() })).unwrap();
    }
    (
        PhaseOrchestrator::new(12345, "0.1.0", 1),
        registry,
        EntityStore::new(),
        ComponentTableStore::new(),
        MutationGate::new(),
        QueryEngine::new(),
        EventBus::new(),
    )
}

#[test]
fn phase_order_enforced_tick_increments() {
    let (mut orch, reg, mut es, mut ts, mut mg, mut qe, mut eb) = full_setup();
    let phases = vec![
        ("Input", vec!["sys_input".to_string()], false),
        ("Simulation", vec!["sys_movement".to_string(), "sys_ai".to_string()], true),
        ("Cleanup", vec!["sys_cleanup".to_string()], false),
    ];
    for tick in 0u64..10 {
        let result = orch.tick(&phases, &reg, &mut es, &mut ts, &mut mg, &mut qe, &mut eb).unwrap();
        assert_eq!(result.tick, tick);
    }
    assert_eq!(orch.current_tick(), 10);
}

#[test]
fn mutation_gate_empty_after_each_tick() {
    let (mut orch, reg, mut es, mut ts, mut mg, mut qe, mut eb) = full_setup();
    let phases = vec![("Simulation", vec!["sys_movement".to_string()], false)];
    orch.tick(&phases, &reg, &mut es, &mut ts, &mut mg, &mut qe, &mut eb).unwrap();
    assert!(mg.is_empty());
}

#[test]
fn parallel_and_sequential_groups_both_work() {
    let (mut orch, reg, mut es, mut ts, mut mg, mut qe, mut eb) = full_setup();
    let phases = vec![
        ("Input", vec!["sys_input".to_string()], false),
        ("Simulation", vec!["sys_movement".to_string(), "sys_ai".to_string()], true),
    ];
    let result = orch.tick(&phases, &reg, &mut es, &mut ts, &mut mg, &mut qe, &mut eb).unwrap();
    assert_eq!(result.tick, 0);
}

#[test]
fn tick_isolation_entities_visible_next_tick() {
    let (mut orch, reg, mut es, mut ts, mut mg, mut qe, mut eb) = full_setup();
    // Manually spawn an entity outside the tick
    let id = es.create_entity(0).unwrap();
    assert!(es.is_alive(id));
    // Run tick — entity persists
    let phases = vec![("Simulation", vec!["sys_movement".to_string()], false)];
    orch.tick(&phases, &reg, &mut es, &mut ts, &mut mg, &mut qe, &mut eb).unwrap();
    assert!(es.is_alive(id));
}