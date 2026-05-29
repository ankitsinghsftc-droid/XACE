//! # Component Tables Module
//! ComponentTable, ComponentTableStore, and SortedEntityMap.

pub mod component_table;
pub mod component_table_store;
pub mod sorted_entity_map;

#[cfg(test)]
mod tests;

pub use component_table::ComponentTable;
pub use component_table_store::ComponentTableStore;
pub use sorted_entity_map::SortedEntityMap;
// ============================================================================
// packages/runtime-core/src/component_tables/mod.rs — ADDITIVE PATCH
// ============================================================================
// Add these module declarations to your existing component_tables/mod.rs:
//
pub mod archetype;
pub mod archetype_index;
pub mod archetype_storage;
pub mod storage_router;
pub mod storage_strategy;
//
pub use archetype_storage::ArchetypeStorage;
pub use storage_router::StorageRouter;
pub use storage_strategy::{ArchetypeId, EntityId, StorageConfig, StorageStrategy, TypeId};
//
// The existing `component_table.rs` (BTreeMap implementation) remains unchanged
// and is still the default for <1000 entities.
