//! # Component Table Store
//!
//! The registry of all component tables in the runtime.
//! Holds one ComponentTable per registered component type, keyed by
//! component_type_id. Provides factory methods and bulk operations
//! for snapshot, restore, and delta production.
//!
//! ## Design
//! ComponentTableStore uses BTreeMap<u32, ComponentTable> — sorted by
//! component_type_id for deterministic iteration (D11).
//!
//! ## Global Invariant I1
//! The MutationGate ensures no EntityID enters a ComponentTable
//! without first existing in the EntityStore. ComponentTableStore
//! itself does not enforce I1 — that is the MutationGate's job.
//!
//! ## Version Metadata
//! Each table tracks its own write version. The store exposes
//! a combined version signal for the QueryCache to detect any
//! write to any table.

use std::collections::BTreeMap;
use xace_core::entity_id::EntityID;
use xace_core::entity_metadata::Tick;
use xace_core::errors::xace_error::{XaceError, ErrorContext};
use super::component_table::ComponentTable;

// ── Component Table Store ─────────────────────────────────────────────────────

/// Registry of all component tables in the XACE runtime.
///
/// One table exists per registered component type.
/// Tables are created at runtime initialization from the compiled
/// schema package and never added or removed during simulation.
///
/// ## BTreeMap for Determinism
/// Uses BTreeMap<u32, ComponentTable> sorted by component_type_id.
/// This guarantees deterministic iteration order across all tables (D11).
pub struct ComponentTableStore {
    /// component_type_id → ComponentTable
    /// BTreeMap guarantees ascending type_id iteration order (D11).
    tables: BTreeMap<u32, ComponentTable>,
}

impl ComponentTableStore {
    /// Creates a new empty ComponentTableStore.
    pub fn new() -> Self {
        Self {
            tables: BTreeMap::new(),
        }
    }

    // ── Table Registration ─────────────────────────────────────────────────

    /// Registers a new component table for the given type.
    ///
    /// Called during runtime initialization for each component type
    /// in the CompositeComponentRegistry. Never called during simulation.
    ///
    /// Returns error if a table for this type_id already exists.
    pub fn register_table(
        &mut self,
        component_type_id: u32,
        component_type_name: impl Into<String>,
    ) -> Result<(), XaceError> {
        if self.tables.contains_key(&component_type_id) {
            return Err(XaceError::ValidationFailure {
                message: format!(
                    "ComponentTable for type_id {} already registered",
                    component_type_id
                ),
                context: ErrorContext::new(
                    "ComponentTableStore", "register_table"
                ),
                rule_violated: "no_duplicate_tables".into(),
                failed_path: format!("component_type_id:{}", component_type_id),
            });
        }
        self.tables.insert(
            component_type_id,
            ComponentTable::new(component_type_id, component_type_name),
        );
        Ok(())
    }

    // ── Table Access ───────────────────────────────────────────────────────

    /// Returns a reference to the table for the given component type.
    /// Returns None if no table is registered for this type.
    pub fn get_table(&self, component_type_id: u32) -> Option<&ComponentTable> {
        self.tables.get(&component_type_id)
    }

    /// Returns a mutable reference to the table for the given component type.
    pub fn get_table_mut(
        &mut self,
        component_type_id: u32,
    ) -> Option<&mut ComponentTable> {
        self.tables.get_mut(&component_type_id)
    }

    /// Returns true if a table is registered for the given component type.
    pub fn has_table(&self, component_type_id: u32) -> bool {
        self.tables.contains_key(&component_type_id)
    }

    /// Returns the number of registered component tables.
    pub fn table_count(&self) -> usize {
        self.tables.len()
    }

    /// Returns all registered component type IDs sorted ascending (D11).
    pub fn all_type_ids(&self) -> Vec<u32> {
        self.tables.keys().copied().collect()
    }

    // ── Component Operations ───────────────────────────────────────────────

    /// Adds a component to an entity.
    ///
    /// Delegates to the correct ComponentTable.
    /// Returns ValidationFailure if no table exists for the type or
    /// if the entity already has this component.
    pub fn add_component(
        &mut self,
        entity_id: EntityID,
        component_type_id: u32,
        component_json: String,
        tick: Tick,
    ) -> Result<(), XaceError> {
        let table = self.get_table_mut_or_error(
            component_type_id, "add_component"
        )?;
        table.add(entity_id, component_json, tick)
    }

    /// Updates a component on an entity.
    pub fn update_component(
        &mut self,
        entity_id: EntityID,
        component_type_id: u32,
        component_json: String,
        tick: Tick,
    ) -> Result<(), XaceError> {
        let table = self.get_table_mut_or_error(
            component_type_id, "update_component"
        )?;
        table.update(entity_id, component_json, tick)
    }

    /// Removes a component from an entity.
    pub fn remove_component(
        &mut self,
        entity_id: EntityID,
        component_type_id: u32,
        tick: Tick,
    ) -> Result<String, XaceError> {
        let table = self.get_table_mut_or_error(
            component_type_id, "remove_component"
        )?;
        table.remove(entity_id, tick)
    }

    /// Removes all components for a destroyed entity across all tables.
    ///
    /// Called by the MutationGate during entity destruction cleanup.
    /// No-op for tables where the entity has no component.
    pub fn remove_all_for_entity(&mut self, entity_id: EntityID) {
        for table in self.tables.values_mut() {
            table.remove_for_entity(entity_id);
        }
    }

    /// Returns the component JSON for an entity, if it has this component.
    pub fn get_component(
        &self,
        entity_id: EntityID,
        component_type_id: u32,
    ) -> Option<&str> {
        self.tables
            .get(&component_type_id)
            .and_then(|t| t.get(entity_id))
    }

    /// Returns true if an entity has the given component.
    pub fn has_component(
        &self,
        entity_id: EntityID,
        component_type_id: u32,
    ) -> bool {
        self.tables
            .get(&component_type_id)
            .map(|t| t.has(entity_id))
            .unwrap_or(false)
    }

    /// Returns all component type IDs that the given entity has.
    /// Sorted ascending for determinism (D11).
    pub fn component_types_for_entity(
        &self,
        entity_id: EntityID,
    ) -> Vec<u32> {
        self.tables
            .iter()
            .filter(|(_, table)| table.has(entity_id))
            .map(|(&type_id, _)| type_id)
            .collect()
        // BTreeMap iteration already ascending
    }

    // ── Query Support ──────────────────────────────────────────────────────

    /// Returns all EntityIDs that have ALL of the given component types.
    /// Result is sorted by EntityID ASC (D3).
    ///
    /// This is the core of the QueryEngine's intersection query.
    /// Uses a progressive intersection approach — starts with the
    /// smallest table and intersects with each subsequent table.
    pub fn entities_with_all_components(
        &self,
        component_type_ids: &[u32],
    ) -> Vec<EntityID> {
        if component_type_ids.is_empty() {
            return Vec::new();
        }

        // Get the first table's entity list as starting set
        let Some(first_table) = self.tables.get(&component_type_ids[0]) else {
            return Vec::new();
        };

        let mut candidates = first_table.all_entity_ids();

        // Intersect with each subsequent table
        for &type_id in &component_type_ids[1..] {
            let Some(table) = self.tables.get(&type_id) else {
                return Vec::new(); // Missing table = no results
            };
            candidates = table.entity_ids_in_set(&candidates);
            if candidates.is_empty() {
                return Vec::new(); // Early exit on empty intersection
            }
        }

        candidates
    }

    // ── Version Tracking ───────────────────────────────────────────────────

    /// Returns the combined version signal across all tables.
    ///
    /// The sum of all table versions changes whenever any component
    /// is written anywhere. Used by QueryCache to detect staleness.
    ///
    /// Note: sum of versions is not unique but monotonically non-decreasing.
    /// Any change to any component increases this value.
    pub fn combined_version(&self) -> u64 {
        self.tables.values().map(|t| t.version()).sum()
    }

    // ── Snapshot Support ───────────────────────────────────────────────────

    /// Creates a deep copy of all component tables for snapshot purposes.
    /// Used by SnapshotEngine.take_snapshot().
    pub fn deep_clone_all(&self) -> BTreeMap<u32, ComponentTable> {
        self.tables
            .iter()
            .map(|(&type_id, table)| (type_id, table.deep_clone()))
            .collect()
    }

    /// Returns all tables sorted by type_id ascending (D11).
    pub fn all_tables(&self) -> impl Iterator<Item = (u32, &ComponentTable)> {
        self.tables.iter().map(|(&id, t)| (id, t))
    }

    // ── Internal Helpers ───────────────────────────────────────────────────

    fn get_table_mut_or_error(
        &mut self,
        component_type_id: u32,
        operation: &str,
    ) -> Result<&mut ComponentTable, XaceError> {
        self.tables.get_mut(&component_type_id).ok_or_else(|| {
            XaceError::ValidationFailure {
                message: format!(
                    "No ComponentTable registered for type_id {} — \
                     component must be registered before use",
                    component_type_id
                ),
                context: ErrorContext::new("ComponentTableStore", operation),
                rule_violated: "table_must_exist".into(),
                failed_path: format!("component_type_id:{}", component_type_id),
            }
        })
    }
}

impl Default for ComponentTableStore {
    fn default() -> Self {
        Self::new()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn store_with_tables() -> ComponentTableStore {
        let mut store = ComponentTableStore::new();
        store.register_table(1, "COMP_TRANSFORM_V1").unwrap();
        store.register_table(2, "COMP_IDENTITY_V1").unwrap();
        store.register_table(5, "COMP_VELOCITY_V1").unwrap();
        store
    }

    fn json(val: &str) -> String {
        format!(r#"{{"value":"{}"}}"#, val)
    }

    #[test]
    fn register_table_works() {
        let mut store = ComponentTableStore::new();
        store.register_table(1, "COMP_TRANSFORM_V1").unwrap();
        assert!(store.has_table(1));
        assert_eq!(store.table_count(), 1);
    }

    #[test]
    fn register_duplicate_table_fails() {
        let mut store = ComponentTableStore::new();
        store.register_table(1, "COMP_TRANSFORM_V1").unwrap();
        assert!(store.register_table(1, "COMP_TRANSFORM_V1").is_err());
    }

    #[test]
    fn add_and_get_component() {
        let mut store = store_with_tables();
        store.add_component(1, 1, json("pos"), 0).unwrap();
        assert_eq!(store.get_component(1, 1), Some(json("pos").as_str()));
    }

    #[test]
    fn update_component() {
        let mut store = store_with_tables();
        store.add_component(1, 1, json("old"), 0).unwrap();
        store.update_component(1, 1, json("new"), 1).unwrap();
        assert_eq!(store.get_component(1, 1), Some(json("new").as_str()));
    }

    #[test]
    fn remove_component() {
        let mut store = store_with_tables();
        store.add_component(1, 1, json("pos"), 0).unwrap();
        store.remove_component(1, 1, 1).unwrap();
        assert!(!store.has_component(1, 1));
    }

    #[test]
    fn remove_all_for_entity() {
        let mut store = store_with_tables();
        store.add_component(1, 1, json("t"), 0).unwrap();
        store.add_component(1, 2, json("i"), 0).unwrap();
        store.add_component(1, 5, json("v"), 0).unwrap();
        store.remove_all_for_entity(1);
        assert!(!store.has_component(1, 1));
        assert!(!store.has_component(1, 2));
        assert!(!store.has_component(1, 5));
    }

    #[test]
    fn component_types_for_entity_sorted() {
        let mut store = store_with_tables();
        store.add_component(1, 5, json("v"), 0).unwrap();
        store.add_component(1, 1, json("t"), 0).unwrap();
        store.add_component(1, 2, json("i"), 0).unwrap();
        let types = store.component_types_for_entity(1);
        assert_eq!(types, vec![1, 2, 5]);
    }

    #[test]
    fn entities_with_all_components_intersection() {
        let mut store = store_with_tables();
        // Entity 1: has transform + identity + velocity
        store.add_component(1, 1, json("t"), 0).unwrap();
        store.add_component(1, 2, json("i"), 0).unwrap();
        store.add_component(1, 5, json("v"), 0).unwrap();
        // Entity 2: has transform + identity only
        store.add_component(2, 1, json("t"), 0).unwrap();
        store.add_component(2, 2, json("i"), 0).unwrap();
        // Entity 3: has transform only
        store.add_component(3, 1, json("t"), 0).unwrap();

        // Query: entities with transform + velocity
        let result = store.entities_with_all_components(&[1, 5]);
        assert_eq!(result, vec![1]); // only entity 1

        // Query: entities with transform + identity
        let result2 = store.entities_with_all_components(&[1, 2]);
        assert_eq!(result2, vec![1, 2]);

        // Query: all three
        let result3 = store.entities_with_all_components(&[1, 2, 5]);
        assert_eq!(result3, vec![1]);
    }

    #[test]
    fn entities_with_all_components_empty_query() {
        let store = store_with_tables();
        assert!(store.entities_with_all_components(&[]).is_empty());
    }

    #[test]
    fn entities_with_all_components_missing_table() {
        let store = store_with_tables();
        // type_id 999 not registered
        let result = store.entities_with_all_components(&[1, 999]);
        assert!(result.is_empty());
    }

    #[test]
    fn combined_version_increases_on_write() {
        let mut store = store_with_tables();
        let v0 = store.combined_version();
        store.add_component(1, 1, json("t"), 0).unwrap();
        assert!(store.combined_version() > v0);
    }

    #[test]
    fn all_type_ids_sorted_ascending() {
        let store = store_with_tables();
        let ids = store.all_type_ids();
        assert_eq!(ids, vec![1, 2, 5]);
    }

    #[test]
    fn operation_on_unregistered_table_fails() {
        let mut store = ComponentTableStore::new();
        assert!(store.add_component(1, 99, json("x"), 0).is_err());
        assert!(store.update_component(1, 99, json("x"), 0).is_err());
        assert!(store.remove_component(1, 99, 0).is_err());
    }

    #[test]
    fn intersection_result_sorted_ascending() {
        let mut store = store_with_tables();
        for id in [5u64, 2, 8, 1, 3] {
            store.add_component(id, 1, json("t"), 0).unwrap();
            store.add_component(id, 2, json("i"), 0).unwrap();
        }
        let result = store.entities_with_all_components(&[1, 2]);
        assert_eq!(result, vec![1, 2, 3, 5, 8]);
    }
}