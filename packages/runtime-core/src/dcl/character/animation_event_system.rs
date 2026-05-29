//! # Animation Event System
//!
//! Reads pending_events from COMP_ANIMATION_V2 components each tick,
//! fires game events when the animation reaches the trigger time,
//! and marks events as consumed.
//!
//! ## Audit 3 — Animation Events
//! XACE writes pending_event with trigger_at_normalized_time →
//! engine watches → fires ANIMATION_EVENT_FIRED feedback →
//! XACE processes at tick boundary → game event fires →
//! MutationGate acts.
//!
//! ## Tick Boundary Processing (I13)
//! Animation feedback arrives via EngineFeedbackProtocol at the
//! START of each tick. This system processes those feedback results
//! and fires the appropriate game events through the EventBus.
//!
//! ## Determinism
//! Events are fired in component_type_id → entity_id → event_id order (D3, D11).
//! All mutation through MutationGate (I2, I9).

use std::collections::BTreeMap;
use xace_core::entity_id::EntityID;
use xace_core::events::event_type::EventType;

// ── Animation Event ───────────────────────────────────────────────────────────

/// A pending animation event defined in COMP_ANIMATION_V2.
///
/// XACE writes these to the component. The engine watches the
/// animation playback and fires ANIMATION_EVENT_FIRED feedback
/// when normalized_time reaches trigger_at_normalized_time.
#[derive(Debug, Clone)]
pub struct AnimationEvent {
    /// Unique ID for this event within the component.
    pub event_id: String,

    /// The animation state this event is tied to.
    pub state_name: String,

    /// Normalized playback time (0.0-1.0) at which to fire.
    pub trigger_at_normalized_time: f32,

    /// The game event type to emit when triggered.
    pub game_event_type: EventType,

    /// Additional payload data.
    pub payload: BTreeMap<String, String>,

    /// True after this event has been processed.
    pub is_consumed: bool,
}

impl AnimationEvent {
    pub fn new(
        event_id: impl Into<String>,
        state_name: impl Into<String>,
        trigger_at_normalized_time: f32,
        game_event_type: EventType,
    ) -> Self {
        Self {
            event_id: event_id.into(),
            state_name: state_name.into(),
            trigger_at_normalized_time: trigger_at_normalized_time.clamp(0.0, 1.0),
            game_event_type,
            payload: BTreeMap::new(),
            is_consumed: false,
        }
    }

    pub fn with_payload(mut self, key: impl Into<String>, value: impl Into<String>) -> Self {
        self.payload.insert(key.into(), value.into());
        self
    }
}

// ── Animation Event Fired Record ──────────────────────────────────────────────

/// Record of an animation event that was fired this tick.
/// Used to build game events for the EventBus.
#[derive(Debug, Clone)]
pub struct AnimationEventFired {
    pub entity_id: EntityID,
    pub event_id: String,
    pub state_name: String,
    pub game_event_type: EventType,
    pub payload: BTreeMap<String, String>,
    pub fired_tick: u64,
}

// ── Animation Event System ────────────────────────────────────────────────────

/// Processes animation events from COMP_ANIMATION_V2 at tick boundaries.
///
/// Called by the PhaseOrchestrator at the START of each tick after
/// engine feedback is drained (I13). Reads current_normalized_time
/// written back by the engine via ANIMATION_STATE_UPDATE feedback,
/// compares against pending_events trigger times, and fires game events.
pub struct AnimationEventSystem;

impl AnimationEventSystem {
    pub fn new() -> Self {
        Self
    }

    /// Processes pending animation events for one entity.
    ///
    /// Takes the entity's pending events and current normalized time
    /// per layer, and returns which events should fire this tick.
    ///
    /// ## Processing Order (D11)
    /// Events are processed in trigger_at_normalized_time ascending order.
    /// Within same trigger time, in event_id alphabetical order.
    pub fn process_entity_events(
        &self,
        entity_id: EntityID,
        pending_events: &mut Vec<AnimationEvent>,
        current_normalized_time: f32,
        active_state: &str,
        tick: u64,
    ) -> Vec<AnimationEventFired> {
        let mut fired = Vec::new();

        // Sort pending events deterministically before processing (D11)
        pending_events.sort_by(|a, b| {
            a.trigger_at_normalized_time
                .partial_cmp(&b.trigger_at_normalized_time)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then(a.event_id.cmp(&b.event_id))
        });

        for event in pending_events.iter_mut() {
            if event.is_consumed {
                continue;
            }

            // Only fire events for the currently active animation state
            if event.state_name != active_state {
                continue;
            }

            // Fire if playback has reached or passed the trigger time
            if current_normalized_time >= event.trigger_at_normalized_time {
                fired.push(AnimationEventFired {
                    entity_id,
                    event_id: event.event_id.clone(),
                    state_name: event.state_name.clone(),
                    game_event_type: event.game_event_type.clone(),
                    payload: event.payload.clone(),
                    fired_tick: tick,
                });
                event.is_consumed = true;
            }
        }

        fired
    }

    /// Removes all consumed events from a pending events list.
    /// Called after processing to clean up consumed events.
    pub fn purge_consumed(&self, pending_events: &mut Vec<AnimationEvent>) {
        pending_events.retain(|e| !e.is_consumed);
    }

    /// Processes animation events for multiple entities in deterministic order.
    ///
    /// Entities processed in EntityID ascending order (D3).
    /// Each entity's events processed in trigger_time ascending order (D11).
    pub fn process_batch(
        &self,
        entity_events: &mut BTreeMap<EntityID, Vec<AnimationEvent>>,
        normalized_times: &BTreeMap<EntityID, f32>,
        active_states: &BTreeMap<EntityID, String>,
        tick: u64,
    ) -> Vec<AnimationEventFired> {
        let mut all_fired = Vec::new();

        // BTreeMap iteration is EntityID ascending (D3)
        for (entity_id, events) in entity_events.iter_mut() {
            let normalized_time = normalized_times.get(entity_id).copied().unwrap_or(0.0);

            let active_state = active_states
                .get(entity_id)
                .map(|s| s.as_str())
                .unwrap_or("");

            let fired =
                self.process_entity_events(*entity_id, events, normalized_time, active_state, tick);
            all_fired.extend(fired);
        }

        all_fired
    }

    /// Resets all pending events for an entity when the animation state changes.
    ///
    /// When transitioning to a new state, unconsumed events from the
    /// previous state are no longer relevant and should be cleared.
    pub fn reset_on_state_change(&self, pending_events: &mut Vec<AnimationEvent>, new_state: &str) {
        // Mark events from non-current states as consumed
        for event in pending_events.iter_mut() {
            if event.state_name != new_state {
                event.is_consumed = true;
            }
        }
        self.purge_consumed(pending_events);
    }
}

impl Default for AnimationEventSystem {
    fn default() -> Self {
        Self::new()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn make_event(id: &str, state: &str, trigger_time: f32) -> AnimationEvent {
        AnimationEvent::new(
            id,
            state,
            trigger_time,
            EventType::Domain("animation.anim_hit".into()),
        )
    }

    #[test]
    fn fires_event_when_time_reached() {
        let sys = AnimationEventSystem::new();
        let mut events = vec![make_event("evt_01", "Attack", 0.5)];
        let fired = sys.process_entity_events(1, &mut events, 0.6, "Attack", 10);
        assert_eq!(fired.len(), 1);
        assert_eq!(fired[0].event_id, "evt_01");
        assert!(events[0].is_consumed);
    }

    #[test]
    fn does_not_fire_before_trigger_time() {
        let sys = AnimationEventSystem::new();
        let mut events = vec![make_event("evt_01", "Attack", 0.8)];
        let fired = sys.process_entity_events(1, &mut events, 0.5, "Attack", 10);
        assert!(fired.is_empty());
        assert!(!events[0].is_consumed);
    }

    #[test]
    fn does_not_fire_for_wrong_state() {
        let sys = AnimationEventSystem::new();
        let mut events = vec![make_event("evt_01", "Attack", 0.5)];
        let fired = sys.process_entity_events(
            1,
            &mut events,
            0.9,
            "Idle",
            10, // Wrong state
        );
        assert!(fired.is_empty());
    }

    #[test]
    fn fires_at_exact_trigger_time() {
        let sys = AnimationEventSystem::new();
        let mut events = vec![make_event("evt_01", "Run", 0.5)];
        let fired = sys.process_entity_events(1, &mut events, 0.5, "Run", 5);
        assert_eq!(fired.len(), 1);
    }

    #[test]
    fn multiple_events_fired_in_order() {
        let sys = AnimationEventSystem::new();
        let mut events = vec![
            make_event("evt_c", "Attack", 0.9),
            make_event("evt_a", "Attack", 0.3),
            make_event("evt_b", "Attack", 0.6),
        ];
        let fired = sys.process_entity_events(1, &mut events, 1.0, "Attack", 10);
        assert_eq!(fired.len(), 3);
        // Fired in trigger_time ascending order
        assert_eq!(fired[0].event_id, "evt_a");
        assert_eq!(fired[1].event_id, "evt_b");
        assert_eq!(fired[2].event_id, "evt_c");
    }

    #[test]
    fn consumed_events_not_refired() {
        let sys = AnimationEventSystem::new();
        let mut events = vec![make_event("evt_01", "Attack", 0.5)];
        // Fire once
        sys.process_entity_events(1, &mut events, 0.6, "Attack", 10);
        // Fire again — should not re-fire
        let fired2 = sys.process_entity_events(1, &mut events, 0.9, "Attack", 11);
        assert!(fired2.is_empty());
    }

    #[test]
    fn purge_consumed_removes_consumed() {
        let sys = AnimationEventSystem::new();
        let mut events = vec![
            make_event("evt_01", "Attack", 0.3),
            make_event("evt_02", "Attack", 0.7),
        ];
        sys.process_entity_events(1, &mut events, 0.5, "Attack", 10);
        sys.purge_consumed(&mut events);
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].event_id, "evt_02");
    }

    #[test]
    fn reset_on_state_change_clears_old_state_events() {
        let sys = AnimationEventSystem::new();
        let mut events = vec![
            make_event("evt_attack", "Attack", 0.5),
            make_event("evt_idle", "Idle", 0.2),
        ];
        sys.reset_on_state_change(&mut events, "Run");
        // All events from non-Run states removed
        assert!(events.is_empty());
    }

    #[test]
    fn reset_preserves_new_state_events() {
        let sys = AnimationEventSystem::new();
        let mut events = vec![
            make_event("evt_attack", "Attack", 0.5),
            make_event("evt_run", "Run", 0.3),
        ];
        sys.reset_on_state_change(&mut events, "Run");
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].event_id, "evt_run");
    }

    #[test]
    fn batch_processes_entities_in_id_order() {
        let sys = AnimationEventSystem::new();
        let mut entity_events: BTreeMap<EntityID, Vec<AnimationEvent>> = BTreeMap::new();
        entity_events.insert(3, vec![make_event("e", "Run", 0.5)]);
        entity_events.insert(1, vec![make_event("e", "Run", 0.5)]);
        entity_events.insert(2, vec![make_event("e", "Run", 0.5)]);

        let mut times = BTreeMap::new();
        times.insert(1u64, 1.0f32);
        times.insert(2u64, 1.0f32);
        times.insert(3u64, 1.0f32);

        let mut states = BTreeMap::new();
        states.insert(1u64, "Run".to_string());
        states.insert(2u64, "Run".to_string());
        states.insert(3u64, "Run".to_string());

        let fired = sys.process_batch(&mut entity_events, &times, &states, 0);
        assert_eq!(fired.len(), 3);
        // Entity IDs in ascending order (D3)
        assert_eq!(fired[0].entity_id, 1);
        assert_eq!(fired[1].entity_id, 2);
        assert_eq!(fired[2].entity_id, 3);
    }
}
