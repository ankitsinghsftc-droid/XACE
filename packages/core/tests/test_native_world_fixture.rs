use xace_core::world::v3::WorldContractV3;

#[test]
fn native_marker_fixture_is_an_admitted_generic_world() {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../../adapters/tests/fixtures/xp016-contract-v1.json"
    )).unwrap();
    let world = WorldContractV3::from_bytes(fixture["world_json"].as_str().unwrap().as_bytes()).unwrap();
    world.admit(&std::collections::BTreeSet::from(["world.aabb.v1".into()])).unwrap();
    assert_eq!(world.objects.len(), 4);
}
