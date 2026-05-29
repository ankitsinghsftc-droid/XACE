//! # Event Bus Integration Tests

use crate::event_bus::event_bus::{reset_event_id_counter, EventBus};
use xace_core::events::event_struct::Event;
use xace_core::events::event_type::EventType;
use xace_core::runtime::phase_enum::PhaseEnum;

fn setup() -> EventBus {
    reset_event_id_counter();
    let mut bus = EventBus::new();
    bus.register_subscription("sys_combat", vec![EventType::DamageTaken])
        .unwrap();
    bus.register_subscription("sys_death", vec![EventType::EntityDestroyed])
        .unwrap();
    bus.register_subscription("sys_spawner", vec![EventType::EntitySpawned])
        .unwrap();
    bus
}

fn event(source: u64, event_type: EventType, tick: u64, phase: PhaseEnum) -> Event {
    Event::broadcast(source, event_type, tick, phase)
}

// ── Deferred Dispatch Tests (D5) ──────────────────────────────────────────────

#[test]
fn events_not_visible_until_dispatch() {
    let mut bus = setup();
    let e = event(1, EventType::DamageTaken, 0, PhaseEnum::Simulation);
    bus.emit(e).unwrap();
    // Before dispatch — pending for systems is empty
    assert!(bus.get_events_for_system("sys_combat").is_empty());
}

#[test]
fn events_visible_after_dispatch() {
    let mut bus = setup();
    let e = event(1, EventType::DamageTaken, 0, PhaseEnum::Simulation);
    bus.emit(e).unwrap();
    bus.dispatch_phase_events(PhaseEnum::Simulation as u8)
        .unwrap();
    assert_eq!(bus.get_events_for_system("sys_combat").len(), 1);
}

// ── Ordering Tests (D5) ───────────────────────────────────────────────────────

#[test]
fn ordering_deterministic_across_two_buses() {
    reset_event_id_counter();
    let mut bus1 = EventBus::new();
    bus1.register_subscription("sys_combat", vec![EventType::DamageTaken])
        .unwrap();

    reset_event_id_counter();
    let mut bus2 = EventBus::new();
    bus2.register_subscription("sys_combat", vec![EventType::DamageTaken])
        .unwrap();

    // Same events emitted in same order
    for tick in [2u64, 0, 1] {
        let e = event(1, EventType::DamageTaken, tick, PhaseEnum::Simulation);
        bus1.emit(e.clone()).unwrap();
        bus2.emit(e).unwrap();
    }

    bus1.dispatch_phase_events(PhaseEnum::Simulation as u8)
        .unwrap();
    bus2.dispatch_phase_events(PhaseEnum::Simulation as u8)
        .unwrap();

    let e1 = bus1.get_events_for_system("sys_combat");
    let e2 = bus2.get_events_for_system("sys_combat");

    // Both buses must produce identical ordering
    let ticks1: Vec<u64> = e1.iter().map(|e| e.creation_tick).collect();
    let ticks2: Vec<u64> = e2.iter().map(|e| e.creation_tick).collect();
    assert_eq!(ticks1, ticks2);

    // Must be sorted ascending
    assert_eq!(ticks1, vec![0, 1, 2]);
}

// ── Cross-Phase Isolation Tests ───────────────────────────────────────────────

#[test]
fn input_phase_events_not_in_simulation_dispatch() {
    let mut bus = setup();
    let e_input = event(1, EventType::DamageTaken, 0, PhaseEnum::Input);
    let e_sim = event(1, EventType::DamageTaken, 0, PhaseEnum::Simulation);
    bus.emit(e_input).unwrap();
    bus.emit(e_sim).unwrap();

    // Dispatch only Simulation
    bus.dispatch_phase_events(PhaseEnum::Simulation as u8)
        .unwrap();
    let events = bus.get_events_for_system("sys_combat");
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].creation_phase, PhaseEnum::Simulation);
}

// ── Replay Compatibility Tests (D14) ─────────────────────────────────────────

#[test]
fn dispatch_log_in_emission_order() {
    let mut bus = setup();
    for i in 0u64..5 {
        let e = event(1, EventType::DamageTaken, i, PhaseEnum::Simulation);
        bus.emit(e).unwrap();
    }
    bus.dispatch_phase_events(PhaseEnum::Simulation as u8)
        .unwrap();
    let log = bus.dispatch_log();
    assert_eq!(log.len(), 5);
    // Log is in dispatch order (sorted)
    let ticks: Vec<u64> = log.iter().map(|r| r.tick).collect();
    for window in ticks.windows(2) {
        assert!(window[0] <= window[1]);
    }
}

// ── Lifecycle Tests ───────────────────────────────────────────────────────────

#[test]
fn consumed_events_survive_until_purge() {
    let mut bus = setup();
    let e = event(1, EventType::DamageTaken, 0, PhaseEnum::Simulation);
    let id = bus.emit(e).unwrap();
    bus.dispatch_phase_events(PhaseEnum::Simulation as u8)
        .unwrap();
    bus.mark_consumed(id).unwrap();

    // Still visible until purge
    let events = bus.get_events_for_system("sys_combat");
    assert_eq!(events.len(), 1);
    assert!(events[0].is_consumed);

    // After purge — gone
    bus.purge_consumed();
    assert!(bus.get_events_for_system("sys_combat").is_empty());
}

#[test]
fn unconsumed_events_persist_across_purge() {
    let mut bus = setup();
    let e1 = event(1, EventType::DamageTaken, 0, PhaseEnum::Simulation);
    let e2 = event(2, EventType::DamageTaken, 0, PhaseEnum::Simulation);
    let id1 = bus.emit(e1).unwrap();
    bus.emit(e2).unwrap();
    bus.dispatch_phase_events(PhaseEnum::Simulation as u8)
        .unwrap();

    // Consume only first
    bus.mark_consumed(id1).unwrap();
    bus.purge_consumed();

    let events = bus.get_events_for_system("sys_combat");
    assert_eq!(events.len(), 1);
    assert!(!events[0].is_consumed);
}

#[test]
fn multiple_subscribers_all_receive_event() {
    reset_event_id_counter();
    let mut bus = EventBus::new();
    bus.register_subscription("sys_a", vec![EventType::DamageTaken])
        .unwrap();
    bus.register_subscription("sys_b", vec![EventType::DamageTaken])
        .unwrap();
    bus.register_subscription("sys_c", vec![EventType::DamageTaken])
        .unwrap();

    let e = event(1, EventType::DamageTaken, 0, PhaseEnum::Simulation);
    bus.emit(e).unwrap();
    bus.dispatch_phase_events(PhaseEnum::Simulation as u8)
        .unwrap();

    assert_eq!(bus.get_events_for_system("sys_a").len(), 1);
    assert_eq!(bus.get_events_for_system("sys_b").len(), 1);
    assert_eq!(bus.get_events_for_system("sys_c").len(), 1);
}
