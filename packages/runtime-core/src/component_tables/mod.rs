//! # Component Tables Module
//! ComponentTable, ComponentTableStore, and SortedEntityMap.

pub mod sorted_entity_map;
pub mod component_table;
pub mod component_table_store;

#[cfg(test)]
mod tests;

pub use sorted_entity_map::SortedEntityMap;
pub use component_table::ComponentTable;
pub use component_table_store::ComponentTableStore;
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
   pub use storage_strategy::{StorageStrategy, StorageConfig, EntityId, TypeId, ArchetypeId};
   pub use storage_router::StorageRouter;
   pub use archetype_storage::ArchetypeStorage;
//
// The existing `component_table.rs` (BTreeMap implementation) remains unchanged
// and is still the default for <1000 entities.