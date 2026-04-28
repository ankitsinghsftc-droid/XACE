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