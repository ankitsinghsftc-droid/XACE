//! # Event Dispatcher
//!
//! Deterministic event dispatch — sorts by (tick, phase, event_id)
//! and routes to subscribed systems in ExecutionPlan order (D5).
//!
//! ## Determinism Rule D5
//! Events are always dispatched in this sort order:
//! 1. creation_tick ASC
//! 2. creation_phase ASC
//! 3. event_id ASC
//!
//! This order is unconditional — it holds regardless of emission
//! order, thread scheduling, or system execution order.

use xace_core::events::event_struct::Event;
use super::event_subscription_registry::EventSubscriptionRegistry;

// ── Event Dispatcher ──────────────────────────────────────────────────────────

/// Deterministic event sorting and routing.
///
/// Takes a batch of events, sorts them by (tick, phase, event_id),
/// and routes each event to its subscribed systems.
pub struct EventDispatcher;

impl EventDispatcher {
    pub fn new() -> Self {
        Self
    }

    /// Sorts events in deterministic order (D5).
    ///
    /// Sort key: (creation_tick ASC, creation_phase ASC, event_id ASC)
    /// Identical to the sort_key() method on Event struct.
    pub fn sort_events(events: &mut Vec<Event>) {
        events.sort_by_key(|e| e.sort_key());
    }

    /// Returns all events relevant to the given system, sorted (D5).
    ///
    /// Filters to events the system is subscribed to.
    pub fn events_for_system<'a>(
        events: &'a [Event],
        system_id: &str,
        registry: &EventSubscriptionRegistry,
    ) -> Vec<&'a Event> {
        events
            .iter()
            .filter(|e| {
                registry.is_subscribed(system_id, &e.event_type)
            })
            .collect()
        // Events are already sorted — filter preserves order
    }

    /// Partitions events into consumed and unconsumed.
    /// Used by EventBus.purge_consumed().
    pub fn partition_consumed(events: Vec<Event>) -> (Vec<Event>, Vec<Event>) {
        events.into_iter().partition(|e| e.is_consumed)
    }
}

impl Default for EventDispatcher {
    fn default() -> Self {
        Self::new()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::events::event_type::EventType;
    use xace_core::runtime::phase_enum::PhaseEnum;

    fn make_event(
        event_id: u64,
        tick: u64,
        phase: PhaseEnum,
        event_type: EventType,
    ) -> Event {
        let mut e = Event::broadcast(1, event_type, tick, phase);
        e.event_id = event_id;
        e
    }

    #[test]
    fn sort_events_by_tick_then_phase_then_id() {
        let mut events = vec![
            make_event(3, 2, PhaseEnum::Simulation, EventType::EntitySpawned),
            make_event(1, 1, PhaseEnum::Cleanup, EventType::EntitySpawned),
            make_event(2, 2, PhaseEnum::Input, EventType::EntitySpawned),
            make_event(4, 1, PhaseEnum::Input, EventType::EntitySpawned),
        ];
        EventDispatcher::sort_events(&mut events);
        assert_eq!(events[0].event_id, 4); // tick=1, phase=Input
        assert_eq!(events[1].event_id, 1); // tick=1, phase=Cleanup
        assert_eq!(events[2].event_id, 2); // tick=2, phase=Input
        assert_eq!(events[3].event_id, 3); // tick=2, phase=Simulation
    }

    #[test]
    fn events_for_system_filters_correctly() {
        let mut reg = EventSubscriptionRegistry::new();
        reg.register("sys_combat", vec![EventType::DamageTaken]).unwrap();

        let events = vec![
            make_event(1, 0, PhaseEnum::Simulation, EventType::DamageTaken),
            make_event(2, 0, PhaseEnum::Simulation, EventType::EntitySpawned),
            make_event(3, 0, PhaseEnum::Simulation, EventType::DamageTaken),
        ];

        let for_combat = EventDispatcher::events_for_system(
            &events, "sys_combat", &reg
        );
        assert_eq!(for_combat.len(), 2);
        assert_eq!(for_combat[0].event_id, 1);
        assert_eq!(for_combat[1].event_id, 3);
    }

    #[test]
    fn partition_consumed_separates_correctly() {
        let mut e1 = make_event(1, 0, PhaseEnum::Simulation, EventType::DamageTaken);
        let e2 = make_event(2, 0, PhaseEnum::Simulation, EventType::DamageTaken);
        let mut e3 = make_event(3, 0, PhaseEnum::Simulation, EventType::DamageTaken);
        e1.is_consumed = true;
        e3.is_consumed = true;

        let (consumed, unconsumed) = EventDispatcher::partition_consumed(
            vec![e1, e2, e3]
        );
        assert_eq!(consumed.len(), 2);
        assert_eq!(unconsumed.len(), 1);
        assert_eq!(unconsumed[0].event_id, 2);
    }
}