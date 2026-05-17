// ============================================================================
// packages/runtime-core/src/component_tables/storage_strategy.rs
// ============================================================================
/*!
# storage_strategy.rs — Storage Backend Selection
 
Defines the two supported component storage strategies and the
selection contract.
 
## Strategies
 
### BTreeMap (default for <1000 entities)
- `BTreeMap<EntityId, BTreeMap<TypeId, ComponentData>>` two-level tree
- Excellent for small games (<1000 entities) where cache pressure is low
- O(log n) lookup, O(log n) insert/remove
- Natural sorted iteration (satisfies D3 trivially)
- Memory overhead: tree node pointers + key duplication
 
### Archetype (for ≥1000 entities)
- Entities grouped by component composition into archetypes
- Each archetype: column-store (SoA — Structure of Arrays)
- O(log n) lookup via ArchetypeIndex
- O(1) iteration per component column (cache-friendly)
- Higher mutation cost: adding/removing components migrates entity to a new archetype
- Iteration speedup: empirically >5x BTreeMap at 5000 entities for full-scan queries
 
## Selection Locked at World Init
 
Per user decision 5: storage strategy is chosen ONCE at world initialization
based on the `storage_backend_threshold` hint from `game_config.yaml`.
The strategy is NEVER switched at runtime — dynamic switching would create
two code paths that must both be correct, an attack surface for determinism bugs.
 
## Determinism Contract (D3 and D11 — unchanged)
 
Both storage strategies MUST satisfy:
    D3:  Entity iteration in EntityID ASC order (k-way merge for Archetype)
    D11: Stable serialization order (type_ids sorted, entities sorted)
 
The Phase Orchestrator never sees the storage strategy — it consumes an
abstract `IComponentStorage` trait that both backends implement.
*/
 
use serde::{Deserialize, Serialize};
 
 
// ── EntityId Alias ────────────────────────────────────────────────────────────
// Mirrors runtime-core's existing definition. If runtime-core defines EntityId
// elsewhere, this alias is redundant and can be removed; the archetype module
// will import it from that location.
 
pub type EntityId = u64;
pub type TypeId   = u32;
pub type ArchetypeId = u32;
 
 
// ── Storage Strategy Enum ─────────────────────────────────────────────────────
 
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum StorageStrategy {
    /// Two-level `BTreeMap<EntityId, BTreeMap<TypeId, ComponentData>>`.
    /// Default for games with fewer than `storage_backend_threshold` entities.
    BTreeMap,
 
    /// Archetype-based column storage with k-way merge for D3 preservation.
    /// Selected when entity count exceeds the threshold.
    Archetype,
}
 
impl StorageStrategy {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::BTreeMap  => "btreemap",
            Self::Archetype => "archetype",
        }
    }
 
    pub fn from_str(s: &str) -> Option<Self> {
        match s.to_lowercase().as_str() {
            "btreemap" | "btree" | "tree" => Some(Self::BTreeMap),
            "archetype" | "soa"           => Some(Self::Archetype),
            _ => None,
        }
    }
}
 
impl Default for StorageStrategy {
    fn default() -> Self { Self::BTreeMap }
}
 
 
// ── Storage Configuration ─────────────────────────────────────────────────────
 
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StorageConfig {
    /// Entity count threshold for switching to Archetype storage.
    /// Default: 1000 (per user decision 7).
    pub entity_threshold:  usize,
 
    /// Explicit override — when set, ignores the threshold and uses this strategy.
    /// Useful for benchmarks and testing both backends against the same workload.
    pub forced_strategy:   Option<StorageStrategy>,
 
    /// Estimated maximum entities the game will create. Used as the hint
    /// for selection. Reading from game_config.yaml's
    /// `runtime.expected_max_entities` field.
    pub expected_max_entities: usize,
}
 
impl Default for StorageConfig {
    fn default() -> Self {
        Self {
            entity_threshold:      1000,   // user decision 7
            forced_strategy:       None,
            expected_max_entities: 100,    // safe default for new projects
        }
    }
}
 