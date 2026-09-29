use serde_json::Value;
use xace_core::world::{WorldContract, WorldManifest};
const WORLD: &[u8] = include_bytes!("fixtures/world_contract_v2/world.canonical.json");
const MANIFEST: &[u8] = include_bytes!("fixtures/world_contract_v2/manifest.json");
#[test]
fn python_golden_roundtrips_with_identical_canonical_bytes_and_hash() {
    let world = WorldContract::from_bytes(WORLD).unwrap();
    assert_eq!(world.canonical_bytes().unwrap(), WORLD);
    let manifest: WorldManifest = serde_json::from_slice(MANIFEST).unwrap();
    manifest
        .verify(
            &world,
            &manifest.schema_package.cgs_hash,
            &manifest.schema_package.schema_version,
        )
        .unwrap();
    let again = WorldContract::from_bytes(&world.canonical_bytes().unwrap()).unwrap();
    assert_eq!(again, world);
}
#[test]
fn malformed_shared_corpus_is_rejected() {
    let cases: Vec<Value> = serde_json::from_str(include_str!(
        "fixtures/world_contract_v2/malformed_vectors.json"
    ))
    .unwrap();
    for case in &cases {
        let mut value: Value = serde_json::from_slice(WORLD).unwrap();
        *value.pointer_mut(case["path"].as_str().unwrap()).unwrap() = case["value"].clone();
        assert!(
            WorldContract::from_bytes(&serde_json::to_vec(&value).unwrap()).is_err(),
            "{}",
            case["name"]
        );
    }
    assert_eq!(cases.len(), 23);
}
#[test]
fn manifest_tamper_and_unknown_nested_fields_fail_closed() {
    let world = WorldContract::from_bytes(WORLD).unwrap();
    let manifest: WorldManifest = serde_json::from_slice(MANIFEST).unwrap();
    let hash = "a".repeat(64).try_into().unwrap();
    assert!(manifest
        .verify(&world, &hash, &manifest.schema_package.schema_version)
        .is_err());
    let version = "9.0.0".to_string().try_into().unwrap();
    assert!(manifest
        .verify(&world, &manifest.schema_package.cgs_hash, &version)
        .is_err());
    let mut changed = world.clone();
    changed.day_length_ticks += 1;
    assert!(manifest
        .verify(
            &changed,
            &manifest.schema_package.cgs_hash,
            &manifest.schema_package.schema_version
        )
        .is_err());
    let mut raw: Value = serde_json::from_slice(WORLD).unwrap();
    raw["gravity"]["native_gravity"] = serde_json::json!(true);
    assert!(WorldContract::from_bytes(&serde_json::to_vec(&raw).unwrap()).is_err());
}

#[test]
fn duplicate_json_fields_and_resource_overflow_reject() {
    let duplicated = std::str::from_utf8(WORLD).unwrap().replacen(
        "\"contract_version\":2",
        "\"contract_version\":2,\"contract_version\":2",
        1,
    );
    assert!(WorldContract::from_bytes(duplicated.as_bytes()).is_err());
    let mut world = WorldContract::from_bytes(WORLD).unwrap();
    world.objects = vec![world.objects[0].clone(); 4097];
    assert!(world.validate().is_err());
}

#[test]
fn package_declares_arbitrary_semantics_and_role_constraints_as_data() {
    let mut world = WorldContract::from_bytes(WORLD).unwrap();
    world.capability_declarations = vec![xace_core::world::SemanticCapabilityDeclaration {
        id: "custom.anything.v42".to_string().try_into().unwrap(),
        allowed_kinds: vec![
            "anchor".into(),
            "kinematic_box".into(),
            "spawn".into(),
            "static_box".into(),
            "trigger".into(),
        ],
    }];
    for o in &mut world.objects {
        o.capabilities = vec!["custom.anything.v42".into()];
    }
    let bytes = world.canonical_bytes().unwrap();
    assert_eq!(WorldContract::from_bytes(&bytes).unwrap(), world);
    world.capability_declarations[0].allowed_kinds = vec!["anchor".into()];
    assert!(world.validate().is_err());
    world.capability_declarations.clear();
    assert!(world.validate().is_err());
}
#[test]
fn legacy_world_requires_explicit_recompilation() {
    assert!(WorldContract::from_bytes(include_bytes!(
        "fixtures/world_contract_v1/world.canonical.json"
    ))
    .is_err());
}
