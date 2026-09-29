use serde::Deserialize;
use serde_json::Value;
use std::collections::BTreeSet;
use xace_core::runtime::execution_plan::ExecutionPlan;
use xace_core::wire::session_contract::*;

#[derive(Deserialize)]
struct Vectors {
    authority: SessionContract,
    certified_adapters: BTreeSet<AdapterIdentity>,
    cases: Vec<Case>,
}
#[derive(Deserialize)]
struct Case {
    name: String,
    candidate: Value,
    expected_rejection: Option<CompatibilityRejection>,
}
fn vectors() -> Vectors {
    serde_json::from_str(include_str!(
        "fixtures/session_contract_v2/golden_vectors.json"
    ))
    .unwrap()
}

#[test]
fn all_host_readers_share_golden_acceptance_and_first_rejection_codes() {
    let v = vectors();
    assert_eq!(v.cases.len(), 50);
    for case in v.cases {
        let json = serde_json::to_string(&case.candidate).unwrap();
        let expected = case.expected_rejection.map_or(Ok(()), Err);
        for _ in 0..3 {
            assert_eq!(
                compare_session_json(&v.authority, &json, &v.certified_adapters),
                expected,
                "{}",
                case.name
            );
        }
    }
}

#[test]
fn serialization_matches_frozen_bytes_and_normalizes_set_order() {
    let v = vectors();
    let expected = include_str!("fixtures/session_contract_v2/authority.canonical.json").trim_end();
    assert_eq!(serde_json::to_string(&v.authority).unwrap(), expected);
    let mut value: Value = serde_json::from_str(expected).unwrap();
    value["required_capabilities"]
        .as_array_mut()
        .unwrap()
        .reverse();
    let reordered: SessionContract = serde_json::from_value(value).unwrap();
    assert_eq!(serde_json::to_string(&reordered).unwrap(), expected);
    assert_eq!(reordered, v.authority);
}

#[test]
fn existing_persisted_plan_and_cgs_identity_are_reused_without_migration() {
    let v = vectors();
    let plan: ExecutionPlan = serde_json::from_str(include_str!(
        "fixtures/session_contract_v2/persisted_plan.json"
    ))
    .unwrap();
    assert_eq!(
        SgcIdentity::try_from(&plan).unwrap(),
        v.authority.gameplay.sgc
    );
    let cgs: Value =
        serde_json::from_str(include_str!("fixtures/session_contract_v2/game.cgs.json")).unwrap();
    assert_eq!(
        serde_json::to_value(&v.authority.gameplay.cgs.cgs_hash).unwrap(),
        cgs["metadata"]["cgs_hash"]
    );
    assert_eq!(
        v.authority.gameplay.cgs.schema_version.to_string(),
        cgs["metadata"]["schema_version"]
    );
    let mut invalid = plan;
    invalid.migration_status = "pending".into();
    assert!(SgcIdentity::try_from(&invalid).is_err());
}

#[test]
fn certification_is_authority_supplied_and_invalid_authority_fails_closed() {
    let v = vectors();
    let json = serde_json::to_string(&v.cases[0].candidate).unwrap();
    assert_eq!(
        compare_session_json(&v.authority, &json, &BTreeSet::new()),
        Err(CompatibilityRejection::UncertifiedAdapter)
    );
    let mut authority = v.authority;
    authority
        .required_capabilities
        .insert("world.unknown.v1".to_owned().try_into().unwrap());
    assert_eq!(
        compare_session_json(&authority, &json, &v.certified_adapters),
        Err(CompatibilityRejection::UnknownRequiredCapability)
    );
}

#[test]
fn provenance_roundtrip_preserves_all_correlations_and_rejects_nil_activation() {
    let v = vectors();
    let mut p = SessionProvenance {
        schema: "xace.session_provenance.v1".into(),
        contract: v.authority,
        adapter: v.certified_adapters.first().unwrap().clone(),
        tick: 42,
        activation: Some(ActivationIdentity {
            mutation_id: "00000000-0000-4000-8000-000000000010".parse().unwrap(),
            activation_id: "00000000-0000-4000-8000-000000000011".parse().unwrap(),
        }),
    };
    p.validate().unwrap();
    let json = serde_json::to_string(&p).unwrap();
    assert_eq!(serde_json::from_str::<SessionProvenance>(&json).unwrap(), p);
    p.activation.as_mut().unwrap().activation_id = uuid::Uuid::nil();
    assert_eq!(p.validate(), Err(CompatibilityRejection::InvalidProvenance));
    p.activation = None;
    p.validate().unwrap();
}

#[test]
fn capability_vocabulary_reserves_semantics_without_engine_paths() {
    assert_eq!(KNOWN_CAPABILITIES, REQUIRED_PROFILE_CAPABILITIES);
    for semantic in ["fixture.wall_runnable.v1", "custom.anything.v42"] {
        assert!(xace_core::world::valid_semantic_capability(semantic));
        assert!(!KNOWN_CAPABILITIES.contains(&semantic));
    }
    for invalid in ["", "res://wall", "Assets/Wall", "/Game/Wall", "x y"] {
        assert!(ContractId::try_from(invalid.to_owned()).is_err());
    }
    for invalid in ["a".repeat(63), "A".repeat(64), "g".repeat(64)] {
        assert!(ContentHash::try_from(invalid).is_err());
    }
}

#[test]
fn semantic_requirements_are_generic_and_not_host_features() {
    let v = vectors();
    let mut authority = v.authority;
    authority.gameplay.world.contract_version = 2;
    authority
        .semantic_capabilities
        .insert("custom.arbitrary.v7".to_string().try_into().unwrap());
    authority.validate().unwrap();
    let mut offer: SessionOffer = serde_json::from_value(v.cases[0].candidate.clone()).unwrap();
    offer.contract = authority.clone();
    assert!(compare_session(&authority, &offer, &v.certified_adapters).is_ok());
    offer.contract.semantic_capabilities.clear();
    assert_eq!(
        compare_session(&authority, &offer, &v.certified_adapters),
        Err(CompatibilityRejection::RequiredCapabilities)
    );
    authority
        .required_capabilities
        .insert("platform.unknown.v1".to_string().try_into().unwrap());
    assert_eq!(
        authority.validate(),
        Err(CompatibilityRejection::UnknownRequiredCapability)
    );
}

#[test]
fn artifact_bound_admission_rejects_undeclared_semantics() {
    let v = vectors();
    let mut authority = v.authority;
    let world = xace_core::world::WorldContract::from_bytes(include_bytes!(
        "fixtures/world_contract_v2/world.canonical.json"
    ))
    .unwrap();
    authority.gameplay.world.contract_version = world.contract_version;
    authority.gameplay.world.mode_id = world.mode_id.clone();
    authority.gameplay.world.artifact.content_hash = world.content_hash().unwrap();
    authority.semantic_capabilities = world
        .objects
        .iter()
        .flat_map(|o| o.capabilities.iter())
        .map(|c| c.clone().try_into().unwrap())
        .collect();
    let mut offer: SessionOffer = serde_json::from_value(v.cases[0].candidate.clone()).unwrap();
    offer.contract = authority.clone();
    assert!(compare_session_with_world(&authority, &offer, &world, &v.certified_adapters).is_ok());
    authority
        .semantic_capabilities
        .insert("custom.undeclared.v1".to_string().try_into().unwrap());
    offer.contract = authority.clone();
    assert_eq!(
        compare_session_with_world(&authority, &offer, &world, &v.certified_adapters),
        Err(CompatibilityRejection::RequiredCapabilities)
    );
}
