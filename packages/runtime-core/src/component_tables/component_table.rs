//! # Component Table
//!
//! Single-type component storage — stores all instances of one component
//! type across all entities. Uses SortedEntityMap to guarantee EntityID
//! ascending iteration order (D3).
//!
//! ## Design
//! One ComponentTable exists per registered component type in the runtime.
//! The ComponentTableStore holds all tables keyed by component_type_id.
//!
//! Component data is stored as raw JSON strings. This keeps the
//! ComponentTable generic and cross-language compatible — the engine
//! adapter, GDE, and PIL all work with the same serialized form.
//!
//! ## Determinism (D3, D11)
//! All entity iteration is in EntityID ascending order (D3) via
//! SortedEntityMap. Serialization uses stable key ordering (D11).
//!
//! ## Global Invariant I1
//! Every EntityID in a ComponentTable must exist in the EntityStore.
//! This is enforced by the MutationGate before any add/update/remove.

use xace_core::entity_id::EntityID;
use xace_core::entity_metadata::Tick;
use xace_core::errors::xace_error::{XaceError, ErrorContext};
use super::sorted_entity_map::SortedEntityMap;

// ── Component Table ───────────────────────────────────────────────────────────

/// Storage for all instances of one component type.
///
/// Each component instance is stored as a JSON string keyed by EntityID.
/// The SortedEntityMap guarantees EntityID-ascending iteration (D3).
///
/// ## Versioning
/// `version` increments on every write operation. Used by the
/// QueryCache to detect staleness and invalidate cached results.
pub struct ComponentTable {
    /// The component type ID this table serves. Immutable after creation.
    component_type_id: u32,

    /// The canonical component type name for error messages and debugging.
    component_type_name: String,

    /// All component instances sorted by EntityID ASC (D3).
    rows: SortedEntityMap<String>,

    /// Increments on every add/update/remove operation.
    /// Used by QueryCache for cache invalidation.
    version: u64,
}

impl ComponentTable {
    /// Creates a new empty ComponentTable for the given component type.
    pub fn new(component_type_id: u32, component_type_name: impl Into<String>) -> Self {
        Self {
            component_type_id,
            component_type_name: component_type_name.into(),
            rows: SortedEntityMap::new(),
            version: 0,
        }
    }

    // ── Write Operations ───────────────────────────────────────────────────

    /// Adds a component instance for an entity.
    ///
    /// Returns ValidationFailure if the entity already has this component.
    /// The MutationGate validates entity existence before calling this.
    pub fn add(
        &mut self,
        entity_id: EntityID,
        component_json: String,
        tick: Tick,
    ) -> Result<(), XaceError> {
        if self.rows.contains(entity_id) {
            return Err(XaceError::ValidationFailure {
                message: format!(
                    "Entity {} already has component {} — \
                     use update() to modify existing components",
                    entity_id, self.component_type_name
                ),
                context: ErrorContext::new(
                    &format!("ComponentTable({})", self.component_type_name),
                    "add",
                ).with_tick(tick),
                rule_violated: "no_duplicate_components".into(),
                failed_path: format!(
                    "entity:{}.component:{}",
                    entity_id, self.component_type_name
                ),
            });
        }
        self.rows.insert(entity_id, component_json);
        self.version += 1;
        Ok(())
    }

    /// Updates the component data for an existing entity.
    ///
    /// Returns ValidationFailure if the entity does not have this component.
    pub fn update(
        &mut self,
        entity_id: EntityID,
        component_json: String,
        tick: Tick,
    ) -> Result<(), XaceError> {
        if !self.rows.contains(entity_id) {
            return Err(XaceError::ValidationFailure {
                message: format!(
                    "Entity {} does not have component {} — \
                     use add() to attach new components",
                    entity_id, self.component_type_name
                ),
                context: ErrorContext::new(
                    &format!("ComponentTable({})", self.component_type_name),
                    "update",
                ).with_tick(tick),
                rule_violated: "component_must_exist".into(),
                failed_path: format!(
                    "entity:{}.component:{}",
                    entity_id, self.component_type_name
                ),
            });
        }
        self.rows.insert(entity_id, component_json);
        self.version += 1;
        Ok(())
    }

    /// Removes the component from an entity.
    ///
    /// Returns ValidationFailure if the entity does not have this component.
    pub fn remove(
        &mut self,
        entity_id: EntityID,
        tick: Tick,
    ) -> Result<String, XaceError> {
        self.rows.remove(entity_id).ok_or_else(|| {
            XaceError::ValidationFailure {
                message: format!(
                    "Entity {} does not have component {} — cannot remove",
                    entity_id, self.component_type_name
                ),
                context: ErrorContext::new(
                    &format!("ComponentTable({})", self.component_type_name),
                    "remove",
                ).with_tick(tick),
                rule_violated: "component_must_exist".into(),
                failed_path: format!(
                    "entity:{}.component:{}",
                    entity_id, self.component_type_name
                ),
            }
        }).map(|json| {
            self.version += 1;
            json
        })
    }

    /// Removes all component data for an entity — used during entity destruction.
    ///
    /// No-op if the entity does not have this component.
    /// Does not return an error — called during bulk cleanup.
    pub fn remove_for_entity(&mut self, entity_id: EntityID) {
        if self.rows.remove(entity_id).is_some() {
            self.version += 1;
        }
    }

    // ── Read Operations ────────────────────────────────────────────────────

    /// Returns the component JSON data for an entity, if present.
    pub fn get(&self, entity_id: EntityID) -> Option<&str> {
        self.rows.get(entity_id).map(|s| s.as_str())
    }

    /// Returns true if the entity has this component.
    pub fn has(&self, entity_id: EntityID) -> bool {
        self.rows.contains(entity_id)
    }

    /// Returns all EntityIDs that have this component, sorted ASC (D3).
    /// BTreeMap iteration guarantees ascending order.
    pub fn all_entity_ids(&self) -> Vec<EntityID> {
        self.rows.entity_ids()
    }

    /// Returns the number of component instances in this table.
    pub fn count(&self) -> usize {
        self.rows.len()
    }

    /// Returns true if this table has no entries.
    pub fn is_empty(&self) -> bool {
        self.rows.is_empty()
    }

    /// Returns the component type ID this table serves.
    pub fn component_type_id(&self) -> u32 {
        self.component_type_id
    }

    /// Returns the canonical component type name.
    pub fn component_type_name(&self) -> &str {
        &self.component_type_name
    }

    /// Returns the current version counter.
    /// Increments on every write. Used by QueryCache for invalidation.
    pub fn version(&self) -> u64 {
        self.version
    }

    // ── Iteration ──────────────────────────────────────────────────────────

    /// Iterates all (EntityID, component_json) pairs in EntityID ASC order (D3).
    pub fn iter(&self) -> impl Iterator<Item = (EntityID, &str)> {
        self.rows.iter().map(|(id, json)| (id, json.as_str()))
    }

    /// Returns all EntityIDs that have this component AND are in the
    /// given set. Result is sorted by EntityID ASC (D3).
    /// Used by the QueryEngine for multi-component intersection queries.
    pub fn entity_ids_in_set(&self, set: &[EntityID]) -> Vec<EntityID> {
        // set is assumed sorted — we can merge linearly
        let mut result = Vec::new();
        let mut set_iter = set.iter().peekable();
        for id in self.rows.keys() {
            // Advance set_iter to catch up with id
            while let Some(&&s) = set_iter.peek() {
                if s < id { set_iter.next(); } else { break; }
            }
            if set_iter.peek().map(|&&s| s == id).unwrap_or(false) {
                result.push(id);
            }
        }
        result
    }

    // ── Snapshot Support ───────────────────────────────────────────────────

    /// Serializes the entire table to a snapshot-compatible JSON string.
    /// Keys are EntityID strings, values are component JSON strings.
    /// BTreeMap guarantees stable key ordering (D11).
    pub fn to_snapshot_json(&self) -> String {
        let pairs: Vec<String> = self.rows
            .iter()
            .map(|(id, json)| format!("\"{}\":{}", id, json))
            .collect();
        format!("{{{}}}", pairs.join(","))
    }

    /// Returns the SortedEntityMap for snapshot serialization.
    pub fn rows(&self) -> &SortedEntityMap<String> {
        &self.rows
    }

    /// Creates a deep copy of this table for snapshot purposes.
    pub fn deep_clone(&self) -> Self {
        Self {
            component_type_id: self.component_type_id,
            component_type_name: self.component_type_name.clone(),
            rows: self.rows.deep_clone(),
            version: self.version,
        }
    }

    /// Restores this table from snapshot data.
    /// Replaces all current data with the provided entries.
    pub fn restore_from_snapshot(
        &mut self,
        entries: Vec<(EntityID, String)>,
    ) {
        self.rows.clear();
        for (entity_id, json) in entries {
            self.rows.insert(entity_id, json);
        }
        self.version += 1;
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn table() -> ComponentTable {
        ComponentTable::new(1, "COMP_TRANSFORM_V1")
    }

    fn json(x: f32) -> String {
        format!(r#"{{"position":{{"x":{},"y":0.0,"z":0.0}}}}"#, x)
    }

    #[test]
    fn add_and_get() {
        let mut t = table();
        t.add(1, json(1.0), 0).unwrap();
        assert_eq!(t.get(1), Some(json(1.0).as_str()));
    }

    #[test]
    fn add_duplicate_fails() {
        let mut t = table();
        t.add(1, json(1.0), 0).unwrap();
        assert!(t.add(1, json(2.0), 0).is_err());
    }

    #[test]
    fn update_existing() {
        let mut t = table();
        t.add(1, json(1.0), 0).unwrap();
        t.update(1, json(5.0), 1).unwrap();
        assert_eq!(t.get(1), Some(json(5.0).as_str()));
    }

    #[test]
    fn update_nonexistent_fails() {
        let mut t = table();
        assert!(t.update(1, json(1.0), 0).is_err());
    }

    #[test]
    fn remove_existing() {
        let mut t = table();
        t.add(1, json(1.0), 0).unwrap();
        let removed = t.remove(1, 1).unwrap();
        assert_eq!(removed, json(1.0));
        assert!(!t.has(1));
    }

    #[test]
    fn remove_nonexistent_fails() {
        let mut t = table();
        assert!(t.remove(999, 0).is_err());
    }

    #[test]
    fn remove_for_entity_no_error_if_missing() {
        let mut t = table();
        t.remove_for_entity(999); // no error
    }

    #[test]
    fn has_correct() {
        let mut t = table();
        assert!(!t.has(1));
        t.add(1, json(1.0), 0).unwrap();
        assert!(t.has(1));
    }

    #[test]
    fn all_entity_ids_sorted_ascending() {
        let mut t = table();
        t.add(5, json(5.0), 0).unwrap();
        t.add(1, json(1.0), 0).unwrap();
        t.add(3, json(3.0), 0).unwrap();
        assert_eq!(t.all_entity_ids(), vec![1, 3, 5]);
    }

    #[test]
    fn iter_yields_ascending_order() {
        let mut t = table();
        t.add(3, json(3.0), 0).unwrap();
        t.add(1, json(1.0), 0).unwrap();
        t.add(2, json(2.0), 0).unwrap();
        let ids: Vec<EntityID> = t.iter().map(|(id, _)| id).collect();
        assert_eq!(ids, vec![1, 2, 3]);
    }

    #[test]
    fn version_increments_on_write() {
        let mut t = table();
        let v0 = t.version();
        t.add(1, json(1.0), 0).unwrap();
        assert_eq!(t.version(), v0 + 1);
        t.update(1, json(2.0), 1).unwrap();
        assert_eq!(t.version(), v0 + 2);
        t.remove(1, 2).unwrap();
        assert_eq!(t.version(), v0 + 3);
    }

    #[test]
    fn version_not_incremented_on_read() {
        let mut t = table();
        t.add(1, json(1.0), 0).unwrap();
        let v = t.version();
        let _ = t.get(1);
        let _ = t.has(1);
        let _ = t.all_entity_ids();
        assert_eq!(t.version(), v);
    }

    #[test]
    fn count_correct() {
        let mut t = table();
        assert_eq!(t.count(), 0);
        t.add(1, json(1.0), 0).unwrap();
        t.add(2, json(2.0), 0).unwrap();
        assert_eq!(t.count(), 2);
        t.remove(1, 1).unwrap();
        assert_eq!(t.count(), 1);
    }

    #[test]
    fn entity_ids_in_set_intersection() {
        let mut t = table();
        t.add(1, json(1.0), 0).unwrap();
        t.add(2, json(2.0), 0).unwrap();
        t.add(3, json(3.0), 0).unwrap();
        t.add(5, json(5.0), 0).unwrap();
        let set = vec![1, 3, 4, 5];
        let result = t.entity_ids_in_set(&set);
        assert_eq!(result, vec![1, 3, 5]);
    }

    #[test]
    fn entity_ids_in_set_empty_result() {
        let mut t = table();
        t.add(1, json(1.0), 0).unwrap();
        let result = t.entity_ids_in_set(&[10, 20]);
        assert!(result.is_empty());
    }

    #[test]
    fn deep_clone_is_independent() {
        let mut t = table();
        t.add(1, json(1.0), 0).unwrap();
        let mut cloned = t.deep_clone();
        cloned.update(1, json(99.0), 1).unwrap();
        assert_eq!(t.get(1), Some(json(1.0).as_str())); // original unchanged
    }

    #[test]
    fn restore_from_snapshot_replaces_data() {
        let mut t = table();
        t.add(1, json(1.0), 0).unwrap();
        t.restore_from_snapshot(vec![(5, json(5.0)), (10, json(10.0))]);
        assert!(!t.has(1));
        assert!(t.has(5));
        assert!(t.has(10));
        assert_eq!(t.count(), 2);
    }

    #[test]
    fn to_snapshot_json_stable() {
        let mut t = table();
        t.add(1, json(1.0), 0).unwrap();
        t.add(2, json(2.0), 0).unwrap();
        let json1 = t.to_snapshot_json();
        let json2 = t.to_snapshot_json();
        assert_eq!(json1, json2); // Deterministic output
    }
}