use serde_json::{json, Value};
use std::collections::BTreeSet;
use xace_core::world::{v3::WorldContractV3, WorldManifest};
const WORLD: &[u8] = include_bytes!("fixtures/world_contract_v3/world.canonical.json");
#[test]
fn python_world_roundtrip_preserves_schema_and_provenance() {
    let w = WorldContractV3::from_bytes(WORLD).unwrap();
    assert_eq!(w.canonical_bytes().unwrap(), WORLD);
    let m: WorldManifest =
        serde_json::from_slice(include_bytes!("fixtures/world_contract_v3/manifest.json")).unwrap();
    w.verify_manifest(
        &m,
        &m.schema_package.cgs_hash,
        &m.schema_package.schema_version,
    )
    .unwrap();
    assert_eq!(w.objects.len(), 12);
    w.admit(&BTreeSet::new()).unwrap();
    let mut changed = w.clone();
    changed.objects[0].properties["strength"] = json!(123);
    assert!(changed
        .verify_manifest(
            &m,
            &m.schema_package.cgs_hash,
            &m.schema_package.schema_version
        )
        .is_err());
}
#[test]
fn unknown_schemas_wrong_payloads_and_dangling_links_reject() {
    for (path, value) in [
        ("/objects/0/properties/strength", json!(true)),
        ("/objects/0/semantic_type", json!("new.undeclared.v1")),
        (
            "/objects/0/relationships",
            json!({"project.link.v1":["missing"]}),
        ),
        ("/objects/0/unknown", json!(1)),
        ("/schemas/0/definition/type", json!("code")),
    ] {
        let mut v: Value = serde_json::from_slice(WORLD).unwrap();
        if path.ends_with("/unknown") {
            v["objects"][0]["unknown"] = value;
        } else {
            *v.pointer_mut(path).unwrap() = value;
        }
        assert!(
            WorldContractV3::from_bytes(&serde_json::to_vec(&v).unwrap()).is_err(),
            "{path}"
        );
    }
}
#[test]
fn unknown_required_profiles_fail_host_admission() {
    let mut w = WorldContractV3::from_bytes(WORLD).unwrap();
    w.geometry_profiles
        .push(xace_core::world::v3::GeometryProfile {
            id: "project.future_backend.v1".to_string().try_into().unwrap(),
            required: true,
        });
    assert!(w.admit(&BTreeSet::new()).is_err());
}

#[test]
fn v3_session_uses_artifact_requirements_without_mandatory_boxes() {
    use xace_core::wire::session_contract::*;
    use xace_core::world::v3::compare_session_with_world_v3;
    let v: Value = serde_json::from_str(include_str!(
        "fixtures/session_contract_v2/golden_vectors.json"
    ))
    .unwrap();
    let mut authority: SessionContract = serde_json::from_value(v["authority"].clone()).unwrap();
    let adapters: BTreeSet<AdapterIdentity> =
        serde_json::from_value(v["certified_adapters"].clone()).unwrap();
    let w = WorldContractV3::from_bytes(WORLD).unwrap();
    authority.profile_id = SESSION_PROFILE_V3_ID.into();
    authority.gameplay.world.contract_version = 3;
    authority.gameplay.world.mode_id = w.mode_id.clone();
    authority.gameplay.world.artifact.content_hash = w.content_hash().unwrap();
    authority.required_capabilities = ["input.timed.v1", "world.semantic_bindings.v3"]
        .into_iter()
        .map(|s| s.to_string().try_into().unwrap())
        .collect();
    authority.semantic_capabilities = w
        .objects
        .iter()
        .flat_map(|o| o.capabilities.iter().cloned())
        .collect();
    let mut candidate: SessionOffer =
        serde_json::from_value(v["cases"][0]["candidate"].clone()).unwrap();
    candidate.contract = authority.clone();
    candidate.client.capabilities = authority.required_capabilities.clone();
    compare_session_with_world_v3(&authority, &candidate, &w, &adapters, &BTreeSet::new()).unwrap();
    candidate.contract.semantic_capabilities.clear();
    assert!(
        compare_session_with_world_v3(&authority, &candidate, &w, &adapters, &BTreeSet::new())
            .is_err()
    );
}
