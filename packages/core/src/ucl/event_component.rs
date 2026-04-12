//! # COMP_EVENT_V1
//!
//! The in-world event carrier component. Allows entities to emit and
//! carry discrete game events as part of the ECS data model.
//!
//! ## Why this is UCL Core
//! Events are how systems communicate without direct coupling. Combat,
//! interaction, world state changes, AI reactions — all genres need a
//! way for one system to signal something happened without calling
//! another system directly. This is the ECS-safe way to do it.
//!
//! ## Critical Design Rule (I9)
//! Events NEVER modify state directly. An event component signals that
//! something happened. The receiving system reads the event and submits
//! mutations via the Mutation Gate. Direct state modification from an
//! event handler is a Global Invariant violation.
//!
//! ## Event Lifecycle
//! System A writes COMP_EVENT_V1 via Mutation Gate →
//! EventBus collects at phase end (D5) →
//! EventDispatcher sorts by (tick, phase, event_id) →
//! System B reads event, submits mutations via Mutation Gate →
//! Event marked is_consumed = true →
//! Cleanup system removes consumed events next tick.
//!
//! ## Determinism (D5)
//! Events are always sorted by (creation_tick ASC, creation_phase ASC,
//! event_id ASC) before dispatch. Emission order never affects
//! processing order — only these three fields matter.

use std::collections::BTreeMap;
use serde::{Deserialize, Serialize};
use crate::entity_id::{EntityID, NULL_ENTITY_ID};
use crate::entity_metadata::Tick;

/// Component type ID for COMP_EVENT_V1. Frozen forever.
pub const COMP_EVENT_V1_ID: u32 = 7;

// ── Event Type ────────────────────────────────────────────────────────────────

/// Categorizes what kind of event this component carries.
///
/// The EventDispatcher routes events to subscribed systems based on
/// this type. Systems declare which event types they subscribe to
/// in their SystemDefinition — no dynamic subscription allowed (I4).
///
/// This enum covers UCL-level events. Domain-specific events
/// (combat damage, animation triggers, audio completion) are
/// defined in their respective DCL domain packages.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum EventType {
    // ── Entity Lifecycle Events ───────────────────────────────────────────
    /// An entity was spawned into the world this tick.
    EntitySpawned,
    /// An entity was destroyed this tick.
    EntityDestroyed,
    /// An entity's state changed (Active↔Disabled).
    EntityStateChanged,

    // ── Input Events ──────────────────────────────────────────────────────
    /// A player action was triggered (jump, attack, interact).
    /// Payload contains action name and intensity.
    PlayerActionTriggered,
    /// Input was enabled or disabled on a controlled entity.
    InputStateChanged,

    // ── World Events ──────────────────────────────────────────────────────
    /// A trigger zone was entered by an entity.
    TriggerEntered,
    /// A trigger zone was exited by an entity.
    TriggerExited,
    /// A spawner produced a new entity.
    EntitySpawnedBySpawner,

    // ── Game State Events ─────────────────────────────────────────────────
    /// The game phase changed (e.g. menu → gameplay → gameover).
    GamePhaseChanged,
    /// A score or objective value changed.
    ScoreChanged,
    /// A match or round ended.
    MatchEnded,

    // ── System Events ─────────────────────────────────────────────────────
    /// A schema mutation was applied to the runtime.
    SchemaMutationApplied,
    /// A snapshot was taken or restored.
    SnapshotEvent,

    // ── Custom / Domain Events ────────────────────────────────────────────
    /// A domain-specific event from a DCL or GCL system.
    /// The string payload identifies the specific domain event type.
    /// Examples: "combat.damage_applied", "animation.event_fired"
    Domain(String),
}

impl std::fmt::Display for EventType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            EventType::EntitySpawned => write!(f, "EntitySpawned"),
            EventType::EntityDestroyed => write!(f, "EntityDestroyed"),
            EventType::EntityStateChanged => write!(f, "EntityStateChanged"),
            EventType::PlayerActionTriggered => write!(f, "PlayerActionTriggered"),
            EventType::InputStateChanged => write!(f, "InputStateChanged"),
            EventType::TriggerEntered => write!(f, "TriggerEntered"),
            EventType::TriggerExited => write!(f, "TriggerExited"),
            EventType::EntitySpawnedBySpawner => write!(f, "EntitySpawnedBySpawner"),
            EventType::GamePhaseChanged => write!(f, "GamePhaseChanged"),
            EventType::ScoreChanged => write!(f, "ScoreChanged"),
            EventType::MatchEnded => write!(f, "MatchEnded"),
            EventType::SchemaMutationApplied => write!(f, "SchemaMutationApplied"),
            EventType::SnapshotEvent => write!(f, "SnapshotEvent"),
            EventType::Domain(name) => write!(f, "Domain({})", name),
        }
    }
}

// ── Event Payload ─────────────────────────────────────────────────────────────

/// A serializable key-value payload carried by an event.
///
/// Uses BTreeMap for deterministic key ordering (D11).
/// Values are strings — type conversion is the receiving system's
/// responsibility. Keeps the payload simple and serialization-safe.
///
/// Payload must be serializable — no pointers, no handles, no
/// engine-specific types. Only data that can survive a snapshot
/// roundtrip (I10).
pub type EventPayload = BTreeMap<String, String>;

// ── Event ID ──────────────────────────────────────────────────────────────────

/// Unique identifier for a single event instance.
///
/// Used as the tiebreaker in event ordering (D5):
/// sort by (creation_tick ASC, creation_phase ASC, event_id ASC).
/// Generated by the EventBus — never set manually by systems.
pub type EventId = u64;

// ── Component ─────────────────────────────────────────────────────────────────

/// COMP_EVENT_V1 — An in-world event carrier attached to an entity.
///
/// UCL Core component. Entities that emit events receive this component
/// via the Mutation Gate. The EventBus collects all event components
/// at the end of each phase, sorts them deterministically (D5), and
/// dispatches them to subscribed systems.
///
/// ## Consumed Events
/// Once a system has processed an event, it marks `is_consumed = true`
/// via the Mutation Gate. A cleanup system removes all consumed event
/// components at the start of the next tick. This prevents events from
/// being processed multiple times across ticks.
///
/// ## Source and Target
/// `source_entity_id` is always set — it is the entity emitting the event.
/// `target_entity_id` is optional — NULL_ENTITY_ID means the event is
/// broadcast (any subscribed system may process it). A non-null target
/// means the event is directed at a specific entity.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EventComponent {
    /// Unique ID assigned by the EventBus. Used for deterministic ordering.
    /// Systems must not set this — it is assigned at dispatch time.
    pub event_id: EventId,

    /// The tick on which this event was created.
    /// Set when the Mutation Gate processes the event creation request.
    pub creation_tick: Tick,

    /// The execution phase during which this event was emitted.
    /// Stored as a u8 matching PhaseEnum discriminant values.
    /// Used for deterministic sort ordering (D5).
    pub creation_phase: u8,

    /// What kind of event this is. Used for subscription routing.
    pub event_type: EventType,

    /// The entity that emitted this event.
    /// Always valid — never NULL_ENTITY_ID.
    pub source_entity_id: EntityID,

    /// The intended recipient entity, or NULL_ENTITY_ID for broadcast.
    pub target_entity_id: EntityID,

    /// Serializable key-value data accompanying this event.
    /// BTreeMap ensures deterministic key ordering (D11).
    pub payload: EventPayload,

    /// Whether this event has been processed by its target system.
    /// Set to true by the receiving system via Mutation Gate.
    /// Consumed events are removed at the start of the next tick.
    pub is_consumed: bool,
}

impl EventComponent {
    /// Creates a broadcast event emitted by the given source entity.
    /// No specific target — any subscribed system may handle it.
    pub fn broadcast(
        source_entity_id: EntityID,
        event_type: EventType,
        creation_tick: Tick,
        creation_phase: u8,
    ) -> Self {
        assert_ne!(
            source_entity_id, NULL_ENTITY_ID,
            "Event source must never be NULL_ENTITY_ID"
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
    pub fn directed(
        source_entity_id: EntityID,
        target_entity_id: EntityID,
        event_type: EventType,
        creation_tick: Tick,
        creation_phase: u8,
    ) -> Self {
        assert_ne!(
            source_entity_id, NULL_ENTITY_ID,
            "Event source must never be NULL_ENTITY_ID"
        );
        assert_ne!(
            target_entity_id, NULL_ENTITY_ID,
            "Directed event target must never be NULL_ENTITY_ID — \
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

    /// Adds a key-value pair to the event payload.
    /// Returns self for builder-style chaining.
    pub fn with_payload(mut self, key: impl Into<String>, value: impl Into<String>) -> Self {
        self.payload.insert(key.into(), value.into());
        self
    }

    /// Returns true if this event targets a specific entity.
    pub fn is_directed(&self) -> bool {
        self.target_entity_id != NULL_ENTITY_ID
    }

    /// Returns true if this event is a broadcast (no specific target).
    pub fn is_broadcast(&self) -> bool {
        self.target_entity_id == NULL_ENTITY_ID
    }

    /// Marks this event as consumed.
    /// Called by the receiving system via Mutation Gate — not directly.
    /// Consumed events are cleaned up at the start of the next tick.
    pub fn consume(&mut self) {
        self.is_consumed = true;
    }

    /// Returns the sort key for deterministic event ordering (D5).
    /// Sort by (creation_tick ASC, creation_phase ASC, event_id ASC).
    pub fn sort_key(&self) -> (Tick, u8, EventId) {
        (self.creation_tick, self.creation_phase, self.event_id)
    }

    /// Retrieves a payload value by key.
    pub fn get_payload(&self, key: &str) -> Option<&str> {
        self.payload.get(key).map(|s| s.as_str())
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn broadcast_event_has_no_target() {
        let e = EventComponent::broadcast(1, EventType::EntitySpawned, 10, 0);
        assert!(e.is_broadcast());
        assert!(!e.is_directed());
        assert_eq!(e.target_entity_id, NULL_ENTITY_ID);
    }

    #[test]
    fn directed_event_has_target() {
        let e = EventComponent::directed(1, 2, EventType::TriggerEntered, 5, 1);
        assert!(e.is_directed());
        assert!(!e.is_broadcast());
        assert_eq!(e.target_entity_id, 2);
    }

    #[test]
    #[should_panic]
    fn broadcast_panics_on_null_source() {
        EventComponent::broadcast(NULL_ENTITY_ID, EventType::EntitySpawned, 0, 0);
    }

    #[test]
    #[should_panic]
    fn directed_panics_on_null_target() {
        EventComponent::directed(1, NULL_ENTITY_ID, EventType::TriggerEntered, 0, 0);
    }

    #[test]
    fn payload_stored_and_retrieved() {
        let e = EventComponent::broadcast(1, EventType::ScoreChanged, 0, 0)
            .with_payload("delta", "10")
            .with_payload("reason", "kill");
        assert_eq!(e.get_payload("delta"), Some("10"));
        assert_eq!(e.get_payload("reason"), Some("kill"));
        assert_eq!(e.get_payload("missing"), None);
    }

    #[test]
    fn consume_marks_event() {
        let mut e = EventComponent::broadcast(1, EventType::EntitySpawned, 0, 0);
        assert!(!e.is_consumed);
        e.consume();
        assert!(e.is_consumed);
    }

    #[test]
    fn sort_key_order_is_correct() {
        let mut e1 = EventComponent::broadcast(1, EventType::EntitySpawned, 5, 1);
        let mut e2 = EventComponent::broadcast(1, EventType::EntitySpawned, 5, 1);
        e1.event_id = 1;
        e2.event_id = 2;
        assert!(e1.sort_key() < e2.sort_key());
    }

    #[test]
    fn earlier_tick_sorts_first() {
        let e1 = EventComponent::broadcast(1, EventType::EntitySpawned, 3, 0);
        let e2 = EventComponent::broadcast(1, EventType::EntitySpawned, 7, 0);
        assert!(e1.sort_key() < e2.sort_key());
    }

    #[test]
    fn domain_event_type_display() {
        let t = EventType::Domain("combat.damage_applied".into());
        assert_eq!(t.to_string(), "Domain(combat.damage_applied)");
    }

    #[test]
    fn payload_uses_btreemap_ordering() {
        let e = EventComponent::broadcast(1, EventType::ScoreChanged, 0, 0)
            .with_payload("z_key", "last")
            .with_payload("a_key", "first");
        let keys: Vec<&String> = e.payload.keys().collect();
        assert_eq!(keys[0], "a_key");
        assert_eq!(keys[1], "z_key");
    }
}