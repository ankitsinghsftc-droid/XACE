use xace_core::events::{event_struct::Event, event_type::EventType};
use xace_core::runtime::phase_enum::PhaseEnum;
use xace_runtime_core::engine_protocol::presentation_events;

#[test]
fn arbitrary_events_keep_payload_and_distinct_stable_occurrences_without_mutation() {
    let event = Event::directed(
        42,
        71,
        EventType::Domain("project.docking_pulse.v1".into()),
        9,
        PhaseEnum::Simulation,
    )
    .with_payload("resource", "project.any_future_noun.v7");
    let input = vec![event.clone(), event.clone()];
    let output = presentation_events(&input);
    assert_eq!(input, vec![event.clone(), event]);
    assert_eq!(output[0].event_type, "project.docking_pulse.v1");
    assert_eq!(output[0].entity_id, 42);
    assert_eq!(output[0].data["target_entity_id"], "71");
    assert_eq!(
        output[0].data["payload"]["resource"],
        "project.any_future_noun.v7"
    );
    assert_eq!(output[0].data["occurrence_id"], "9:0");
    assert_eq!(output[1].data["occurrence_id"], "9:1");
    assert_eq!(
        serde_json::to_vec(&output).unwrap(),
        serde_json::to_vec(&presentation_events(&input)).unwrap()
    );
    assert!(presentation_events(&[]).is_empty());
}

#[test]
fn compound_world_objects_keep_all_stable_object_bindings() {
    use std::collections::BTreeMap;
    use xace_core::world::v3::WorldContractV3;
    use xace_runtime_core::geometry::WorldGeometryBindings;
    let world = WorldContractV3::from_bytes(include_bytes!(
        "../../core/tests/fixtures/world_contract_v3/world.canonical.json"
    ))
    .unwrap();
    let mut instances = BTreeMap::new();
    for object in &world.objects {
        let next = instances.len() as u64 + 1;
        instances
            .entry((object.actor_id.clone(), object.instance_index))
            .or_insert(next);
    }
    let bindings = WorldGeometryBindings::from_v3(&world, &instances)
        .unwrap()
        .object_entity_ids();
    assert_eq!(bindings.len(), world.objects.len());
    for object in &world.objects {
        assert_eq!(
            bindings[&String::from(object.id.clone())],
            instances[&(object.actor_id.clone(), object.instance_index)].to_string()
        );
    }
    assert!(bindings.len() > instances.len());
}
