//! # Event Struct
//!
//! The concrete Event struct that flows through the XACE EventBus.
//! Every event emitted by any system is an instance of this struct.
//!
//! ## What an Event Is
//! An Event is a discrete, immutable signal that something happened
//! in the simulation this tick. Events are the only way systems
//! communicate without direct coupling — a system emits an event,
//! the EventBus routes it, subscribed systems react to it.
//!
//! ## Global Invariant I9
//! Events NEVER modify state directly.
//! An event signals that something happened.
//! The receiving system reads the event and submits mutations via
//! the Mutation Gate. Direct mutation from event handlers is forbidden.
//!
//! ## Event Lifecycle
//! System emits → Mutation Gate queues event creation →
//! Phase ends → EventBus collects all new events →
//! EventDispatcher sorts by (tick, phase, event_id) (D5) →
//! Subscribed systems receive event next phase →
//! System submits mutations via Mutation Gate →
//! Event marked consumed →
//! Cleanup system removes consumed events next tick
//!
//! ## Payload
//! Payloads use BTreeMap<String, String> for deterministic key ordering (D11).
//! Values are always strings — receiving system parses them.
//! Payloads must be serializable — no pointers, no handles (I10).
//!
//! ## Relationship to COMP_EVENT_V1
//! COMP_EVENT_V1 (ucl/event_component.rs) is the ECS component that
//! carries event data when attached to an entity.
//! Event (this file) is the standalone event struct used by the EventBus
//! and EventDispatcher — it does not require an entity carrier.
//! The two types share the same design but serve different roles.

use std::collections::BTreeMap;
use serde::{Deserialize, Serialize};
use crate::entity_id::{EntityID, NULL_ENTITY_ID};
use crate::entity_metadata::Tick;
use crate::events::event_type::EventType;
use crate::runtime::phase_enum::PhaseEnum;

// ── Event ID ──────────────────────────────────────────────────────────────────

/// Unique identifier for a single event instance.
///
/// Assigned by the EventBus at dispatch time — never set manually.
/// Used as the tiebreaker in deterministic sort ordering (D5):
/// sort by (creation_tick ASC, creation_phase ASC, event_id ASC).
///
/// Monotonically increasing within a session. Never reused.
/// Included in WorldSnapshot for replay integrity (I10).
pub type EventId = u64;

// ── Event Payload ─────────────────────────────────────────────────────────────

/// Key-value payload carried by an event.
///
/// BTreeMap guarantees deterministic key iteration order (D11).
/// All values are strings — receiving system parses to appropriate type.
/// Payload must survive snapshot roundtrip serialization (I10).
pub type EventPayload = BTreeMap<String, String>;

// ── Event ─────────────────────────────────────────────────────────────────────

/// A discrete, immutable signal that something happened in the simulation.
///
/// The fundamental communication primitive between systems in XACE.
/// Systems never call each other directly — they communicate through
/// events routed by the EventBus.
///
/// ## Immutability
/// Once created, an Event's fields are never modified except:
/// - `event_id` is assigned by the EventBus at dispatch
/// - `is_consumed` is set to true by the receiving system
///
/// All other fields are set at creation and never changed.
///
/// ## Source and Target
/// `source_entity_id` is always set — always the entity emitting the event.
/// `target_entity_id` is NULL_ENTITY_ID for broadcast events.
/// A non-null target means the event is directed at a specific entity.
/// The EventDispatcher routes directed events only to systems that
/// process the target entity.
///
/// ## Sort Key (D5)
/// Events are dispatched in strictly deterministic order:
/// sort by (creation_tick ASC, creation_phase ASC, event_id ASC).
/// Emission order never affects dispatch order.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Event {
    /// Unique ID assigned by the EventBus at dispatch time.
    /// Zero until assigned — systems must not read this before dispatch.
    pub event_id: EventId,

    /// The simulation tick on which this event was created.
    /// Set by the Mutation Gate when processing the event creation request.
    pub creation_tick: Tick,

    /// The execution phase during which this event was emitted.
    /// Used for deterministic sort ordering (D5).
    pub creation_phase: PhaseEnum,

    /// What kind of event this is.
    /// Used by the EventDispatcher to route to subscribed systems.
    pub event_type: EventType,

    /// The entity that emitted this event.
    /// Always valid — never NULL_ENTITY_ID.
    /// Validated at creation — panics if NULL_ENTITY_ID passed.
    pub source_entity_id: EntityID,

    /// The intended recipient entity, or NULL_ENTITY_ID for broadcast.
    /// Broadcast events are routed to all subscribed systems.
    /// Directed events are routed only to systems handling the target.
    pub target_entity_id: EntityID,

    /// Serializable key-value data accompanying this event.
    /// BTreeMap ensures deterministic key ordering (D11).
    /// All values are strings — type conversion is the receiver's job.
    pub payload: EventPayload,

    /// Whether this event has been processed by its target system.
    /// Set to true by the receiving system via Mutation Gate.
    /// Consumed events are removed at the start of the next tick.
    pub is_consumed: bool,
}

impl Event {
    /// Creates a broadcast event — no specific target entity.
    /// Routed to all systems subscribed to this event type.
    ///
    /// ## Panics
    /// Panics if source_entity_id is NULL_ENTITY_ID.
    /// Events must always have a valid source entity.
    pub fn broadcast(
        source_entity_id: EntityID,
        event_type: EventType,
        creation_tick: Tick,
        creation_phase: PhaseEnum,
    ) -> Self {
        assert_ne!(
            source_entity_id,
            NULL_ENTITY_ID,
            "Event source_entity_id must never be NULL_ENTITY_ID — \
             every event must have a valid source entity"
        );
        Self {
            event_id: 0, // assigned by EventBus at dispatch
            creation_tick,
            creation_phase,
            event_type,
            source_entity_id,
            target_entity_id: NULL_ENTITY_ID,
            payload: BTreeMap::new(),
            is_consumed: false,
        }
    }

    /// Creates a directed event targeting a specific entity.
    /// Routed only to systems that process the target entity.
    ///
    /// ## Panics
    /// Panics if source_entity_id or target_entity_id is NULL_ENTITY_ID.
    pub fn directed(
        source_entity_id: EntityID,
        target_entity_id: EntityID,
        event_type: EventType,
        creation_tick: Tick,
        creation_phase: PhaseEnum,
    ) -> Self {
        assert_ne!(
            source_entity_id,
            NULL_ENTITY_ID,
            "Event source_entity_id must never be NULL_ENTITY_ID"
        );
        assert_ne!(
            target_entity_id,
            NULL_ENTITY_ID,
            "Directed event target_entity_id must never be NULL_ENTITY_ID — \
             use broadcast() for untargeted events"
        );
        Self {
            event_id: 0, // assigned by EventBus at dispatch
            creation_tick,
            creation_phase,
            event_type,
            source_entity_id,
            target_entity_id,
            payload: BTreeMap::new(),
            is_consumed: false,
        }
    }

    /// Builder method — adds a key-value pair to the event payload.
    /// Returns self for chained construction.
    ///
    /// Example:
    /// ```
    /// // Event::broadcast(1, EventType::ScoreChanged, 0, PhaseEnum::Simulation)
    /// //     .with_payload("delta", "10")
    /// //     .with_payload("reason", "enemy_killed");
    /// ```
    pub fn with_payload(
        mut self,
        key: impl Into<String>,
        value: impl Into<String>,
    ) -> Self {
        self.payload.insert(key.into(), value.into());
        self
    }

    /// Returns the sort key for deterministic event ordering (D5).
    ///
    /// Sort order: (creation_tick ASC, creation_phase ASC, event_id ASC).
    /// Emission order never affects dispatch order — only these three
    /// fields determine when an event is processed relative to others.
    pub fn sort_key(&self) -> (Tick, u8, EventId) {
        (self.creation_tick, self.creation_phase.as_u8(), self.event_id)
    }

    /// Returns true if this event targets a specific entity.
    pub fn is_directed(&self) -> bool {
        self.target_entity_id != NULL_ENTITY_ID
    }

    /// Returns true if this event is a broadcast (no specific target).
    pub fn is_broadcast(&self) -> bool {
        self.target_entity_id == NULL_ENTITY_ID
    }

    /// Returns true if this event has been processed by a system.
    pub fn is_consumed(&self) -> bool {
        self.is_consumed
    }

    /// Marks this event as consumed.
    ///
    /// Called by the receiving system via the Mutation Gate — not directly.
    /// Consumed events are cleaned up at the start of the next tick.
    pub fn consume(&mut self) {
        self.is_consumed = true;
    }

    /// Retrieves a payload value by key.
    /// Returns None if the key is not present.
    pub fn get_payload(&self, key: &str) -> Option<&str> {
        self.payload.get(key).map(|s| s.as_str())
    }

    /// Retrieves a payload value and parses it as f32.
    /// Returns None if the key is missing or the value cannot be parsed.
    pub fn get_payload_f32(&self, key: &str) -> Option<f32> {
        self.payload.get(key)?.parse().ok()
    }

    /// Retrieves a payload value and parses it as i64.
    /// Returns None if the key is missing or the value cannot be parsed.
    pub fn get_payload_i64(&self, key: &str) -> Option<i64> {
        self.payload.get(key)?.parse().ok()
    }

    /// Retrieves a payload value and parses it as u64.
    /// Returns None if the key is missing or the value cannot be parsed.
    pub fn get_payload_u64(&self, key: &str) -> Option<u64> {
        self.payload.get(key)?.parse().ok()
    }

    /// Retrieves a payload value and parses it as bool.
    /// Returns None if the key is missing or the value is not "true"/"false".
    pub fn get_payload_bool(&self, key: &str) -> Option<bool> {
        match self.payload.get(key)?.as_str() {
            "true" => Some(true),
            "false" => Some(false),
            _ => None,
        }
    }

    /// Returns true if this event has all the required payload keys.
    /// Used by systems to validate events before processing.
    pub fn has_payload_keys(&self, keys: &[&str]) -> bool {
        keys.iter().all(|k| self.payload.contains_key(*k))
    }
}

impl std::fmt::Display for Event {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "Event[{}](type={}, src={}, tick={}, phase={}, consumed={})",
            self.event_id,
            self.event_type,
            self.source_entity_id,
            self.creation_tick,
            self.creation_phase,
            self.is_consumed
        )
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn test_broadcast() -> Event {
        Event::broadcast(
            1,
            EventType::EntitySpawned,
            10,
            PhaseEnum::Simulation,
        )
    }

    fn test_directed() -> Event {
        Event::directed(
            1,
            2,
            EventType::Domain("combat.damage_applied".into()),
            5,
            PhaseEnum::Simulation,
        )
    }

    #[test]
    fn broadcast_has_no_target() {
        let e = test_broadcast();
        assert!(e.is_broadcast());
        assert!(!e.is_directed());
        assert_eq!(e.target_entity_id, NULL_ENTITY_ID);
    }

    #[test]
    fn directed_has_target() {
        let e = test_directed();
        assert!(e.is_directed());
        assert!(!e.is_broadcast());
        assert_eq!(e.target_entity_id, 2);
    }

    #[test]
    #[should_panic]
    fn broadcast_panics_on_null_source() {
        Event::broadcast(
            NULL_ENTITY_ID,
            EventType::EntitySpawned,
            0,
            PhaseEnum::Simulation,
        );
    }

    #[test]
    #[should_panic]
    fn directed_panics_on_null_target() {
        Event::directed(
            1,
            NULL_ENTITY_ID,
            EventType::TriggerEntered,
            0,
            PhaseEnum::Simulation,
        );
    }

    #[test]
    fn new_event_not_consumed() {
        let e = test_broadcast();
        assert!(!e.is_consumed());
    }

    #[test]
    fn consume_marks_event() {
        let mut e = test_broadcast();
        e.consume();
        assert!(e.is_consumed());
    }

    #[test]
    fn with_payload_builder_works() {
        let e = test_broadcast()
            .with_payload("delta", "10")
            .with_payload("reason", "enemy_killed");
        assert_eq!(e.get_payload("delta"), Some("10"));
        assert_eq!(e.get_payload("reason"), Some("enemy_killed"));
        assert_eq!(e.get_payload("missing"), None);
    }

    #[test]
    fn payload_uses_btreemap_ordering() {
        let e = test_broadcast()
            .with_payload("z_key", "last")
            .with_payload("a_key", "first")
            .with_payload("m_key", "middle");
        let keys: Vec<&String> = e.payload.keys().collect();
        assert_eq!(keys[0], "a_key");
        assert_eq!(keys[1], "m_key");
        assert_eq!(keys[2], "z_key");
    }

    #[test]
    fn get_payload_f32_parses_correctly() {
        let e = test_broadcast().with_payload("speed", "3.14");
        assert!((e.get_payload_f32("speed").unwrap() - 3.14f32).abs() < 1e-5);
        assert_eq!(e.get_payload_f32("missing"), None);
    }

    #[test]
    fn get_payload_i64_parses_correctly() {
        let e = test_broadcast().with_payload("score", "-42");
        assert_eq!(e.get_payload_i64("score"), Some(-42));
    }

    #[test]
    fn get_payload_u64_parses_correctly() {
        let e = test_broadcast().with_payload("entity_id", "999");
        assert_eq!(e.get_payload_u64("entity_id"), Some(999));
    }

    #[test]
    fn get_payload_bool_parses_correctly() {
        let e = test_broadcast()
            .with_payload("is_active", "true")
            .with_payload("is_dead", "false");
        assert_eq!(e.get_payload_bool("is_active"), Some(true));
        assert_eq!(e.get_payload_bool("is_dead"), Some(false));
        assert_eq!(e.get_payload_bool("missing"), None);
    }

    #[test]
    fn has_payload_keys_all_present() {
        let e = test_broadcast()
            .with_payload("a", "1")
            .with_payload("b", "2");
        assert!(e.has_payload_keys(&["a", "b"]));
        assert!(!e.has_payload_keys(&["a", "b", "c"]));
    }

    #[test]
    fn sort_key_earlier_tick_sorts_first() {
        let e1 = Event::broadcast(1, EventType::EntitySpawned, 3, PhaseEnum::Simulation);
        let e2 = Event::broadcast(1, EventType::EntitySpawned, 7, PhaseEnum::Simulation);
        assert!(e1.sort_key() < e2.sort_key());
    }

    #[test]
    fn sort_key_earlier_phase_sorts_first() {
        let e1 = Event::broadcast(1, EventType::EntitySpawned, 5, PhaseEnum::Input);
        let e2 = Event::broadcast(1, EventType::EntitySpawned, 5, PhaseEnum::Simulation);
        assert!(e1.sort_key() < e2.sort_key());
    }

    #[test]
    fn sort_key_lower_event_id_sorts_first() {
        let mut e1 = Event::broadcast(1, EventType::EntitySpawned, 5, PhaseEnum::Simulation);
        let mut e2 = Event::broadcast(1, EventType::EntitySpawned, 5, PhaseEnum::Simulation);
        e1.event_id = 1;
        e2.event_id = 2;
        assert!(e1.sort_key() < e2.sort_key());
    }

    #[test]
    fn event_id_starts_at_zero() {
        let e = test_broadcast();
        assert_eq!(e.event_id, 0);
    }

    #[test]
    fn source_entity_id_stored_correctly() {
        let e = Event::broadcast(42, EventType::EntitySpawned, 0, PhaseEnum::Simulation);
        assert_eq!(e.source_entity_id, 42);
    }

    #[test]
    fn creation_tick_stored_correctly() {
        let e = Event::broadcast(1, EventType::ScoreChanged, 100, PhaseEnum::Simulation);
        assert_eq!(e.creation_tick, 100);
    }

    #[test]
    fn display_includes_key_fields() {
        let mut e = test_broadcast();
        e.event_id = 5;
        let display = e.to_string();
        assert!(display.contains("5"));
        assert!(display.contains("EntitySpawned"));
    }

    #[test]
    fn domain_event_in_broadcast() {
        let e = Event::broadcast(
            1,
            EventType::Domain("combat.damage_applied".into()),
            0,
            PhaseEnum::Simulation,
        );
        assert!(e.event_type.is_domain_event());
    }

    #[test]
    fn event_phase_stored_correctly() {
        let e = Event::broadcast(1, EventType::EntitySpawned, 0, PhaseEnum::Cleanup);
        assert_eq!(e.creation_phase, PhaseEnum::Cleanup);
    }
}