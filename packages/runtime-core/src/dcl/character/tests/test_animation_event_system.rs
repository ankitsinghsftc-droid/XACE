//! # Animation Event System Integration Tests

use crate::dcl::character::animation_event_system::{AnimationEvent, AnimationEventSystem};
use std::collections::BTreeMap;
use xace_core::events::event_type::EventType;

fn make_event(id: &str, state: &str, trigger: f32) -> AnimationEvent {
    AnimationEvent::new(
        id,
        state,
        trigger,
        EventType::Domain("animation.test".into()),
    )
}

#[test]
fn fires_only_events_past_trigger_time() {
    let sys = AnimationEventSystem::new();
    let mut events = vec![
        make_event("early", "Run", 0.2),
        make_event("mid", "Run", 0.5),
        make_event("late", "Run", 0.8),
    ];
    let fired = sys.process_entity_events(1, &mut events, 0.6, "Run", 0);
    assert_eq!(fired.len(), 2);
    assert!(fired.iter().any(|f| f.event_id == "early"));
    assert!(fired.iter().any(|f| f.event_id == "mid"));
    assert!(!fired.iter().any(|f| f.event_id == "late"));
}

#[test]
fn fired_events_marked_consumed() {
    let sys = AnimationEventSystem::new();
    let mut events = vec![make_event("hit", "Attack", 0.5)];
    sys.process_entity_events(1, &mut events, 1.0, "Attack", 0);
    assert!(events[0].is_consumed);
}

#[test]
fn events_with_payload_preserve_data() {
    let sys = AnimationEventSystem::new();
    let event = AnimationEvent::new("hit", "Attack", 0.5, EventType::DamageTaken)
        .with_payload("damage", "25")
        .with_payload("type", "physical");
    let mut events = vec![event];
    let fired = sys.process_entity_events(1, &mut events, 1.0, "Attack", 5);
    assert_eq!(fired[0].payload.get("damage"), Some(&"25".to_string()));
    assert_eq!(fired[0].payload.get("type"), Some(&"physical".to_string()));
}

#[test]
fn batch_entity_ordering_is_ascending() {
    let sys = AnimationEventSystem::new();
    let mut entity_events = BTreeMap::new();
    for id in [5u64, 2, 8, 1] {
        entity_events.insert(id, vec![make_event("e", "Run", 0.1)]);
    }
    let times: BTreeMap<u64, f32> = entity_events.keys().map(|&k| (k, 1.0)).collect();
    let states: BTreeMap<u64, String> = entity_events
        .keys()
        .map(|&k| (k, "Run".to_string()))
        .collect();

    let fired = sys.process_batch(&mut entity_events, &times, &states, 0);
    let ids: Vec<u64> = fired.iter().map(|f| f.entity_id).collect();
    assert_eq!(ids, vec![1, 2, 5, 8]);
}

#[test]
fn state_change_clears_irrelevant_events() {
    let sys = AnimationEventSystem::new();
    let mut events = vec![
        make_event("attack_hit", "Attack", 0.5),
        make_event("run_step", "Run", 0.3),
        make_event("run_step2", "Run", 0.7),
    ];
    sys.reset_on_state_change(&mut events, "Run");
    assert_eq!(events.len(), 2);
    assert!(events.iter().all(|e| e.state_name == "Run"));
}

#[test]
fn determinism_same_input_same_output() {
    let sys = AnimationEventSystem::new();
    let make_events = || {
        vec![
            make_event("c", "Attack", 0.9),
            make_event("a", "Attack", 0.3),
            make_event("b", "Attack", 0.6),
        ]
    };
    let mut e1 = make_events();
    let mut e2 = make_events();
    let fired1 = sys.process_entity_events(1, &mut e1, 1.0, "Attack", 10);
    let fired2 = sys.process_entity_events(1, &mut e2, 1.0, "Attack", 10);
    let ids1: Vec<&str> = fired1.iter().map(|f| f.event_id.as_str()).collect();
    let ids2: Vec<&str> = fired2.iter().map(|f| f.event_id.as_str()).collect();
    assert_eq!(ids1, ids2);
}
