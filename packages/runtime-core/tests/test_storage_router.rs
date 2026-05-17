/*!
# test_storage_router.rs — StorageRouter Selection Tests

Verifies that StorageRouter selects the correct backend at world init
based on `game_config.yaml` hints and the entity threshold.

These tests confirm user decision 5 (storage chosen at world init, locked)
and user decision 7 (default threshold = 1000).
*/

use xace_runtime_core::component_tables::{
    storage_router::StorageRouter,
    storage_strategy::{StorageConfig, StorageStrategy},
};


// ── Default Config Tests ──────────────────────────────────────────────────────

#[test]
fn default_config_selects_btreemap() {
    // Default: expected_max_entities=100, threshold=1000
    let config   = StorageConfig::default();
    let strategy = StorageRouter::select(&config);
    assert_eq!(
        strategy,
        StorageStrategy::BTreeMap,
        "default config (100 expected entities) must select BTreeMap"
    );
}

#[test]
fn below_threshold_selects_btreemap() {
    let config = StorageConfig {
        entity_threshold:      1000,
        expected_max_entities: 999,
        forced_strategy:       None,
    };
    assert_eq!(StorageRouter::select(&config), StorageStrategy::BTreeMap);
}

#[test]
fn at_threshold_selects_archetype() {
    let config = StorageConfig {
        entity_threshold:      1000,
        expected_max_entities: 1000,
        forced_strategy:       None,
    };
    assert_eq!(
        StorageRouter::select(&config),
        StorageStrategy::Archetype,
        "at exactly the threshold, select Archetype"
    );
}

#[test]
fn above_threshold_selects_archetype() {
    let config = StorageConfig {
        entity_threshold:      1000,
        expected_max_entities: 5000,
        forced_strategy:       None,
    };
    assert_eq!(StorageRouter::select(&config), StorageStrategy::Archetype);
}


// ── Forced Strategy Tests ─────────────────────────────────────────────────────

#[test]
fn forced_archetype_overrides_small_entity_count() {
    let config = StorageConfig {
        entity_threshold:      1000,
        expected_max_entities: 10,   // would normally pick BTreeMap
        forced_strategy:       Some(StorageStrategy::Archetype),
    };
    assert_eq!(
        StorageRouter::select(&config),
        StorageStrategy::Archetype,
        "forced_strategy=archetype must override the threshold"
    );
}

#[test]
fn forced_btreemap_overrides_large_entity_count() {
    let config = StorageConfig {
        entity_threshold:      1000,
        expected_max_entities: 50_000,   // would normally pick Archetype
        forced_strategy:       Some(StorageStrategy::BTreeMap),
    };
    assert_eq!(
        StorageRouter::select(&config),
        StorageStrategy::BTreeMap,
        "forced_strategy=btreemap must override even large entity counts"
    );
}


// ── YAML Parsing Tests ────────────────────────────────────────────────────────

#[test]
fn yaml_with_large_entity_hint_selects_archetype() {
    let yaml = r#"
name: "Big Game"
version: "0.1.0"
runtime:
  expected_max_entities: 10000
"#;
    let (strategy, _config) = StorageRouter::select_from_yaml(yaml);
    assert_eq!(strategy, StorageStrategy::Archetype);
}

#[test]
fn yaml_with_small_entity_hint_selects_btreemap() {
    let yaml = r#"
name: "Small Game"
runtime:
  expected_max_entities: 50
"#;
    let (strategy, _config) = StorageRouter::select_from_yaml(yaml);
    assert_eq!(strategy, StorageStrategy::BTreeMap);
}

#[test]
fn yaml_with_forced_archetype_backend() {
    let yaml = r#"
name: "Benchmarked Game"
runtime:
  expected_max_entities: 10
  storage_backend: archetype
"#;
    let (strategy, config) = StorageRouter::select_from_yaml(yaml);
    assert_eq!(strategy, StorageStrategy::Archetype);
    assert_eq!(config.forced_strategy, Some(StorageStrategy::Archetype));
}

#[test]
fn yaml_with_custom_threshold() {
    let yaml = r#"
name: "Threshold Test"
runtime:
  expected_max_entities: 800
  storage_backend_threshold: 500
"#;
    let (strategy, config) = StorageRouter::select_from_yaml(yaml);
    // 800 >= 500 → Archetype
    assert_eq!(strategy, StorageStrategy::Archetype);
    assert_eq!(config.entity_threshold, 500);
}

#[test]
fn yaml_missing_runtime_section_uses_defaults() {
    let yaml = r#"
name: "Bare Minimum Game"
version: "0.1.0"
"#;
    let (strategy, config) = StorageRouter::select_from_yaml(yaml);
    // Defaults: expected=100, threshold=1000 → BTreeMap
    assert_eq!(strategy, StorageStrategy::BTreeMap);
    assert_eq!(config.entity_threshold, 1000);
}

#[test]
fn yaml_malformed_falls_back_to_btreemap() {
    let yaml = "this is not valid yaml {{{";
    let (strategy, _config) = StorageRouter::select_from_yaml(yaml);
    assert_eq!(strategy, StorageStrategy::BTreeMap);
}

#[test]
fn explain_produces_non_empty_string() {
    let config = StorageConfig::default();
    let msg    = StorageRouter::explain(&config);
    assert!(!msg.is_empty());
    assert!(msg.contains("btreemap") || msg.contains("archetype"));
}

#[test]
fn explain_mentions_threshold() {
    let config = StorageConfig {
        entity_threshold:      1000,
        expected_max_entities: 500,
        forced_strategy:       None,
    };
    let msg = StorageRouter::explain(&config);
    assert!(msg.contains("500") || msg.contains("1000"),
        "explain must mention entity counts, got: {}", msg);
}

#[test]
fn strategy_from_str_round_trips() {
    assert_eq!(StorageStrategy::from_str("archetype"), Some(StorageStrategy::Archetype));
    assert_eq!(StorageStrategy::from_str("btreemap"),  Some(StorageStrategy::BTreeMap));
    assert_eq!(StorageStrategy::from_str("soa"),       Some(StorageStrategy::Archetype));
    assert_eq!(StorageStrategy::from_str("ARCHETYPE"), Some(StorageStrategy::Archetype));
    assert_eq!(StorageStrategy::from_str("unknown"),   None);
}

#[test]
fn strategy_as_str_is_lowercase() {
    assert_eq!(StorageStrategy::Archetype.as_str(), "archetype");
    assert_eq!(StorageStrategy::BTreeMap.as_str(),  "btreemap");
}