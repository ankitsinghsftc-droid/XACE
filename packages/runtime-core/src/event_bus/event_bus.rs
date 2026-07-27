//! # Event Bus
//!
//! Deterministic deferred event dispatch system.
//!
//! ## Deferred Dispatch (D5)
//! Events are NEVER dispatched mid-phase. Systems emit events during
//! execute() — these are buffered in phase_event_buffers. At phase end
//! the PhaseOrchestrator calls dispatch_phase_events() which sorts and
//! routes all buffered events to subscribed systems.
//!
//! ## Sort Order (D5)
//! All events dispatched in: (creation_tick ASC, creation_phase ASC, event_id ASC)
//! This order is unconditional regardless of emission order.
//!
//! ## Phase Isolation
//! Each phase has its own event buffer. Events emitted in phase N
//! are dispatched at the END of phase N — never mid-phase or
//! mid-previous-phase. This prevents systems from seeing events
//! that were emitted in later phases.
//!
//! ## Global Invariants
//! I9: Events never modify state directly — all mutation via MutationGate
//! D5: Events sorted by (tick, phase, event_id) before dispatch

use super::event_dispatcher::EventDispatcher;
use super::event_subscription_registry::EventSubscriptionRegistry;
use std::collections::BTreeMap;
use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::events::event_struct::Event;
use xace_core::events::event_type::EventType;

// ── Event ID Counter ──────────────────────────────────────────────────────────

/// Monotonic event ID counter for deterministic event ordering (D5).
static mut EVENT_ID_COUNTER: u64 = 0;

fn next_event_id() -> u64 {
    // Safety: single-threaded access guaranteed by PhaseOrchestrator
    unsafe {
        EVENT_ID_COUNTER += 1;
        EVENT_ID_COUNTER
    }
}

fn current_event_id_counter() -> u64 {
    // Safety: single-threaded access guaranteed by PhaseOrchestrator.
    unsafe { EVENT_ID_COUNTER }
}

fn restore_event_id_counter(value: u64) {
    // Safety: restore happens at a phase boundary with no concurrent systems.
    unsafe {
        EVENT_ID_COUNTER = value;
    }
}

/// Resets the event ID counter — used for snapshot restore and tests.
pub fn reset_event_id_counter() {
    unsafe {
        EVENT_ID_COUNTER = 0;
    }
}

// ── Dispatched Event Record ───────────────────────────────────────────────────

/// A record of one dispatched event — stored for replay (D14).
#[derive(Debug, Clone)]
pub struct DispatchedEventRecord {
    pub event_id: u64,
    pub tick: u64,
    pub phase: u8,
    pub event_type: String,
}

// ── Event Bus ─────────────────────────────────────────────────────────────────

/// Deterministic event buffering and dispatch system.
///
/// Maintains per-phase event buffers. Events emitted by systems
/// accumulate in the current phase's buffer. At phase end the buffer
/// is sorted and dispatched to subscribed systems.
pub struct EventBus {
    /// Per-phase event buffers. Key = phase discriminant (u8).
    /// Events accumulate here during phase execution.
    phase_buffers: BTreeMap<u8, Vec<Event>>,

    /// Pending events for system consumption.
    /// Populated by dispatch_phase_events(), consumed by systems.
    pending_for_systems: BTreeMap<String, Vec<Event>>,

    /// Subscription registry — which systems receive which event types.
    subscription_registry: EventSubscriptionRegistry,

    /// All events ever dispatched — for replay log (D14).
    dispatch_log: Vec<DispatchedEventRecord>,

    /// Total events emitted this session.
    total_emitted: u64,

    /// Total events dispatched this session.
    total_dispatched: u64,
}

#[derive(Clone)]
pub struct EventBusRollbackSnapshot {
    phase_buffers: BTreeMap<u8, Vec<Event>>,
    pending_for_systems: BTreeMap<String, Vec<Event>>,
    dispatch_log: Vec<DispatchedEventRecord>,
    total_emitted: u64,
    total_dispatched: u64,
    event_id_counter: u64,
}

impl EventBus {
    pub fn new() -> Self {
        Self {
            phase_buffers: BTreeMap::new(),
            pending_for_systems: BTreeMap::new(),
            subscription_registry: EventSubscriptionRegistry::new(),
            dispatch_log: Vec::new(),
            total_emitted: 0,
            total_dispatched: 0,
        }
    }

    // ── Subscription Management ────────────────────────────────────────────

    /// Registers a system's event subscriptions.
    /// Called once at runtime initialization — never during simulation (I4).
    pub fn register_subscription(
        &mut self,
        system_id: impl Into<String>,
        event_types: Vec<EventType>,
    ) -> Result<(), XaceError> {
        self.subscription_registry.register(system_id, event_types)
    }

    // ── Event Emission ─────────────────────────────────────────────────────

    /// Buffers an event for deferred dispatch at phase end (D5).
    ///
    /// Assigns a unique monotonic event_id for sort ordering.
    /// The event is stored in the phase buffer keyed by its
    /// creation_phase discriminant.
    pub fn emit(&mut self, mut event: Event) -> Result<u64, XaceError> {
        let event_id = next_event_id();
        event.event_id = event_id;

        let phase_key = event.creation_phase as u8;
        self.phase_buffers
            .entry(phase_key)
            .or_insert_with(Vec::new)
            .push(event);

        self.total_emitted += 1;
        Ok(event_id)
    }

    // ── Phase Dispatch ─────────────────────────────────────────────────────

    /// Dispatches all buffered events for the given phase.
    ///
    /// Called by PhaseOrchestrator after each phase completes (D4, D5).
    /// Sorts events by (tick, phase, event_id) then routes to subscribers.
    ///
    /// Returns the number of events dispatched.
    pub fn dispatch_phase_events(&mut self, phase: u8) -> Result<usize, XaceError> {
        let Some(mut buffer) = self.phase_buffers.remove(&phase) else {
            return Ok(0); // No events for this phase
        };

        // Sort deterministically (D5)
        EventDispatcher::sort_events(&mut buffer);

        let count = buffer.len();

        // Route each event to subscribed systems
        for event in &buffer {
            let subscribers = self
                .subscription_registry
                .subscribers_for(&event.event_type);

            for system_id in subscribers {
                self.pending_for_systems
                    .entry(system_id.to_string())
                    .or_insert_with(Vec::new)
                    .push(event.clone());
            }

            // Log for replay (D14)
            self.dispatch_log.push(DispatchedEventRecord {
                event_id: event.event_id,
                tick: event.creation_tick,
                phase,
                event_type: format!("{:?}", event.event_type),
            });
        }

        self.total_dispatched += count as u64;
        Ok(count)
    }

    // ── System Event Access ────────────────────────────────────────────────

    /// Returns all pending events for a system, sorted (D5).
    ///
    /// Called by systems during execute() to read their event queue.
    pub fn get_events_for_system(&self, system_id: &str) -> Vec<&Event> {
        self.pending_for_systems
            .get(system_id)
            .map(|events| events.iter().collect())
            .unwrap_or_default()
    }

    /// Marks an event as consumed by its receiving system.
    ///
    /// Consumed events are removed at the start of the next tick
    /// by purge_consumed().
    pub fn mark_consumed(&mut self, event_id: u64) -> Result<(), XaceError> {
        let mut found = false;
        for events in self.pending_for_systems.values_mut() {
            for event in events.iter_mut() {
                if event.event_id == event_id {
                    event.is_consumed = true;
                    found = true;
                }
            }
        }
        if !found {
            return Err(XaceError::ValidationFailure {
                message: format!(
                    "Event ID {} not found in pending events — \
                     cannot mark as consumed",
                    event_id
                ),
                context: ErrorContext::new("EventBus", "mark_consumed"),
                rule_violated: "event_must_exist".into(),
                failed_path: format!("event_id:{}", event_id),
            });
        }
        Ok(())
    }

    /// Removes all consumed events from pending system queues.
    /// Called at the start of each tick during Cleanup phase.
    pub fn purge_consumed(&mut self) {
        for events in self.pending_for_systems.values_mut() {
            events.retain(|e| !e.is_consumed);
        }
        // Remove empty system queues
        self.pending_for_systems
            .retain(|_, events| !events.is_empty());
    }

    // ── Queries ────────────────────────────────────────────────────────────

    /// Returns the total number of events in all phase buffers.
    pub fn pending_count(&self) -> usize {
        self.phase_buffers.values().map(|b| b.len()).sum()
    }

    /// Returns the total events emitted this session.
    pub fn total_emitted(&self) -> u64 {
        self.total_emitted
    }

    /// Returns the total events dispatched this session.
    pub fn total_dispatched(&self) -> u64 {
        self.total_dispatched
    }

    /// Returns the dispatch log for replay validation (D14).
    pub fn dispatch_log(&self) -> &[DispatchedEventRecord] {
        &self.dispatch_log
    }

    /// Clears all state — used for snapshot restore.
    pub fn clear_for_restore(&mut self) {
        self.phase_buffers.clear();
        self.pending_for_systems.clear();
        self.dispatch_log.clear();
        reset_event_id_counter();
    }

    /// Captures all replay-visible event state for transaction rollback.
    pub fn rollback_snapshot(&self) -> EventBusRollbackSnapshot {
        EventBusRollbackSnapshot {
            phase_buffers: self.phase_buffers.clone(),
            pending_for_systems: self.pending_for_systems.clone(),
            dispatch_log: self.dispatch_log.clone(),
            total_emitted: self.total_emitted,
            total_dispatched: self.total_dispatched,
            event_id_counter: current_event_id_counter(),
        }
    }

    /// Restores event state captured by `rollback_snapshot()`.
    pub fn restore_rollback_snapshot(&mut self, snapshot: EventBusRollbackSnapshot) {
        self.phase_buffers = snapshot.phase_buffers;
        self.pending_for_systems = snapshot.pending_for_systems;
        self.dispatch_log = snapshot.dispatch_log;
        self.total_emitted = snapshot.total_emitted;
        self.total_dispatched = snapshot.total_dispatched;
        restore_event_id_counter(snapshot.event_id_counter);
    }
}

impl Default for EventBus {
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

    fn setup() -> EventBus {
        reset_event_id_counter();
        let mut bus = EventBus::new();
        bus.register_subscription(
            "sys_combat",
            vec![EventType::DamageTaken, EventType::EntityDestroyed],
        )
        .unwrap();
        bus.register_subscription("sys_spawner", vec![EventType::EntitySpawned])
            .unwrap();
        bus
    }

    fn make_event(source: u64, event_type: EventType, tick: u64, phase: PhaseEnum) -> Event {
        Event::broadcast(source, event_type, tick, phase)
    }

    #[test]
    fn emit_buffers_event() {
        let mut bus = setup();
        let e = make_event(1, EventType::DamageTaken, 0, PhaseEnum::Simulation);
        bus.emit(e).unwrap();
        assert_eq!(bus.pending_count(), 1);
    }

    #[test]
    fn dispatch_routes_to_subscribers() {
        let mut bus = setup();
        let e = make_event(1, EventType::DamageTaken, 0, PhaseEnum::Simulation);
        bus.emit(e).unwrap();
        let dispatched = bus
            .dispatch_phase_events(PhaseEnum::Simulation as u8)
            .unwrap();
        assert_eq!(dispatched, 1);
        let combat_events = bus.get_events_for_system("sys_combat");
        assert_eq!(combat_events.len(), 1);
    }

    #[test]
    fn non_subscriber_receives_no_events() {
        let mut bus = setup();
        let e = make_event(1, EventType::DamageTaken, 0, PhaseEnum::Simulation);
        bus.emit(e).unwrap();
        bus.dispatch_phase_events(PhaseEnum::Simulation as u8)
            .unwrap();
        let spawner_events = bus.get_events_for_system("sys_spawner");
        assert!(spawner_events.is_empty());
    }

    #[test]
    fn events_dispatched_in_sorted_order() {
        let mut bus = setup();
        reset_event_id_counter();

        // Emit in reverse order of expected sort
        let e3 = make_event(1, EventType::DamageTaken, 1, PhaseEnum::Simulation);
        let e1 = make_event(1, EventType::DamageTaken, 0, PhaseEnum::Simulation);
        let e2 = make_event(1, EventType::DamageTaken, 0, PhaseEnum::Simulation);

        bus.emit(e3).unwrap(); // tick=1
        bus.emit(e1).unwrap(); // tick=0, id=2
        bus.emit(e2).unwrap(); // tick=0, id=3

        bus.dispatch_phase_events(PhaseEnum::Simulation as u8)
            .unwrap();
        let events = bus.get_events_for_system("sys_combat");

        // Should be sorted: tick=0 before tick=1
        assert_eq!(events[0].creation_tick, 0);
        assert_eq!(events[1].creation_tick, 0);
        assert_eq!(events[2].creation_tick, 1);
    }

    #[test]
    fn phase_isolation_different_phases() {
        let mut bus = setup();
        let e_sim = make_event(1, EventType::DamageTaken, 0, PhaseEnum::Simulation);
        let e_input = make_event(1, EventType::DamageTaken, 0, PhaseEnum::Input);
        bus.emit(e_sim).unwrap();
        bus.emit(e_input).unwrap();
        assert_eq!(bus.pending_count(), 2);

        // Dispatch only Simulation phase
        let dispatched = bus
            .dispatch_phase_events(PhaseEnum::Simulation as u8)
            .unwrap();
        assert_eq!(dispatched, 1);
        assert_eq!(bus.pending_count(), 1); // Input event still pending
    }

    #[test]
    fn mark_consumed_works() {
        let mut bus = setup();
        let e = make_event(1, EventType::DamageTaken, 0, PhaseEnum::Simulation);
        let event_id = bus.emit(e).unwrap();
        bus.dispatch_phase_events(PhaseEnum::Simulation as u8)
            .unwrap();
        bus.mark_consumed(event_id).unwrap();
        let events = bus.get_events_for_system("sys_combat");
        assert!(events[0].is_consumed);
    }

    #[test]
    fn purge_consumed_removes_consumed_events() {
        let mut bus = setup();
        let e = make_event(1, EventType::DamageTaken, 0, PhaseEnum::Simulation);
        let event_id = bus.emit(e).unwrap();
        bus.dispatch_phase_events(PhaseEnum::Simulation as u8)
            .unwrap();
        bus.mark_consumed(event_id).unwrap();
        bus.purge_consumed();
        assert!(bus.get_events_for_system("sys_combat").is_empty());
    }

    #[test]
    fn mark_consumed_nonexistent_fails() {
        let mut bus = setup();
        assert!(bus.mark_consumed(99999).is_err());
    }

    #[test]
    fn total_emitted_and_dispatched_tracked() {
        let mut bus = setup();
        for _ in 0..5 {
            let e = make_event(1, EventType::DamageTaken, 0, PhaseEnum::Simulation);
            bus.emit(e).unwrap();
        }
        assert_eq!(bus.total_emitted(), 5);
        bus.dispatch_phase_events(PhaseEnum::Simulation as u8)
            .unwrap();
        assert_eq!(bus.total_dispatched(), 5);
    }

    #[test]
    fn dispatch_log_records_events() {
        let mut bus = setup();
        let e = make_event(1, EventType::DamageTaken, 0, PhaseEnum::Simulation);
        bus.emit(e).unwrap();
        bus.dispatch_phase_events(PhaseEnum::Simulation as u8)
            .unwrap();
        assert_eq!(bus.dispatch_log().len(), 1);
    }

    #[test]
    fn clear_for_restore_resets_all_state() {
        let mut bus = setup();
        let e = make_event(1, EventType::DamageTaken, 0, PhaseEnum::Simulation);
        bus.emit(e).unwrap();
        bus.dispatch_phase_events(PhaseEnum::Simulation as u8)
            .unwrap();
        bus.clear_for_restore();
        assert_eq!(bus.pending_count(), 0);
        assert!(bus.dispatch_log().is_empty());
    }

    #[test]
    fn multiple_event_types_routed_correctly() {
        let mut bus = setup();
        let e1 = make_event(1, EventType::DamageTaken, 0, PhaseEnum::Simulation);
        let e2 = make_event(2, EventType::EntitySpawned, 0, PhaseEnum::Simulation);
        let e3 = make_event(3, EventType::EntityDestroyed, 0, PhaseEnum::Simulation);
        bus.emit(e1).unwrap();
        bus.emit(e2).unwrap();
        bus.emit(e3).unwrap();
        bus.dispatch_phase_events(PhaseEnum::Simulation as u8)
            .unwrap();

        let combat = bus.get_events_for_system("sys_combat");
        assert_eq!(combat.len(), 2); // DamageTaken + EntityDestroyed

        let spawner = bus.get_events_for_system("sys_spawner");
        assert_eq!(spawner.len(), 1); // EntitySpawned only
    }
}
