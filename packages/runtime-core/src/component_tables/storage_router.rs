// ============================================================================
// packages/runtime-core/src/component_tables/storage_router.rs
// ============================================================================
/*!
# storage_router.rs — Storage Backend Selection (LOCKED at world init)
 
Chooses between BTreeMap and Archetype storage exactly ONCE at world init.
 
## Selection Logic (deterministic)
 
```
expected_max_entities ≥ entity_threshold (1000)  →  Archetype
expected_max_entities <  entity_threshold        →  BTreeMap
config.forced_strategy = Some(s)                 →  s   (override)
```
 
## Why Locked
 
Dynamic switching at runtime would create two code paths that must both produce
identical world hashes for the same input sequence. That's two surfaces for
determinism bugs and twice the test surface. We choose at init and never switch.
 
## game_config.yaml Integration
 
```yaml
runtime:
  expected_max_entities: 5000      # hint: switches to Archetype storage
  storage_backend_threshold: 1000  # override (optional; default 1000)
  storage_backend: archetype       # forced override (optional; for benchmarks/tests)
```
*/
 
use serde::Deserialize;
 
use crate::component_tables::storage_strategy::{StorageConfig, StorageStrategy};
 
 
pub struct StorageRouter;
 
impl StorageRouter {
    /// Selects the storage strategy from a config. Deterministic.
    pub fn select(config: &StorageConfig) -> StorageStrategy {
        if let Some(forced) = config.forced_strategy {
            return forced;
        }
        if config.expected_max_entities >= config.entity_threshold {
            StorageStrategy::Archetype
        } else {
            StorageStrategy::BTreeMap
        }
    }
 
    /// Reads selection from game_config.yaml's `runtime` section.
    /// Returns the strategy along with the StorageConfig used.
    pub fn select_from_yaml(yaml_text: &str) -> (StorageStrategy, StorageConfig) {
        #[derive(Deserialize)]
        struct GameConfig { runtime: Option<RuntimeSection> }
 
        #[derive(Deserialize)]
        struct RuntimeSection {
            #[serde(default)]                          expected_max_entities:     Option<usize>,
            #[serde(default)]                          storage_backend_threshold: Option<usize>,
            #[serde(default)]                          storage_backend:           Option<String>,
        }
 
        let parsed: GameConfig = serde_yaml::from_str(yaml_text)
            .unwrap_or(GameConfig { runtime: None });
 
        let rt   = parsed.runtime;
        let mut config = StorageConfig::default();
 
        if let Some(rs) = rt {
            if let Some(n) = rs.expected_max_entities     { config.expected_max_entities = n; }
            if let Some(n) = rs.storage_backend_threshold { config.entity_threshold      = n; }
            if let Some(s) = rs.storage_backend {
                config.forced_strategy = StorageStrategy::from_str(&s);
            }
        }
 
        let strategy = Self::select(&config);
        (strategy, config)
    }
 
    /// Explains the selection in human-readable form for logging.
    pub fn explain(config: &StorageConfig) -> String {
        let strategy = Self::select(config);
        if config.forced_strategy.is_some() {
            format!(
                "Storage strategy: {} (forced via storage_backend config).",
                strategy.as_str()
            )
        } else if config.expected_max_entities >= config.entity_threshold {
            format!(
                "Storage strategy: archetype (expected_max_entities = {} ≥ \
                 threshold = {}).",
                config.expected_max_entities, config.entity_threshold,
            )
        } else {
            format!(
                "Storage strategy: btreemap (expected_max_entities = {} < \
                 threshold = {}).",
                config.expected_max_entities, config.entity_threshold,
            )
        }
    }
}