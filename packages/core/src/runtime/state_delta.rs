//! # State Delta
//!
//! Represents the minimal set of changes that occurred during one
//! simulation tick. The engine adapter reads StateDelta each tick
//! and applies only what changed — not the full world state.
//!
//! ## What a StateDelta Is
//! A StateDelta is the diff between world state at tick N-1 and tick N.
//! It records which entities were created, destroyed, and which
//! component fields changed. The engine adapter applies this diff
//! to its scene without needing to re-sync the entire world state.
//!
//! ## Minimal Delta Principle
//! The DeltaSyncEngine (Phase 8) compares the current StateDelta
//! against the last-sent state to produce a WireMessage containing
//! only genuinely changed data. Unchanged components are never
//! included in the wire payload — this minimizes network bandwidth
//! and engine-side processing cost.
//!
//! ## Ordering (D4)
//! Operations in a StateDelta are always applied in this order:
//! 1. Spawn new entities
//! 2. Add components to entities
//! 3. Modify existing component fields
//! 4. Remove components from entities
//! 5. Destroy entities
//!
//! This order is enforced by the Mutation Gate and mirrored in the
//! engine adapter's DeltaApplicator. Any other order risks applying
//! mutations to entities that don't exist yet or have already been removed.
//!
//! ## Determinism
//! All collections in StateDelta use sorted structures.
//! Entity IDs are always processed in ascending order (D3).
//! Component type IDs are always processed in ascending order (D11).

use std::collections::BTreeMap;
use serde::{Deserialize, Serialize};
use crate::entity_id::EntityID;
use crate::entity_metadata::Tick;

// ── Component Field Change ────────────────────────────────────────────────────

/// A single field-level change within a component.
///
/// Records the field name and its new serialized value.
/// The engine adapter uses this to update specific component
/// fields without replacing the entire component.
///
/// Value is serialized as a JSON string for cross-language
/// compatibility — the engine adapter deserializes it into
/// the appropriate engine-side type.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct FieldChange {
    /// The name of the field that changed.
    /// Matches the field name in the component's UCL/DCL definition.
    pub field_name: String,

    /// The new value serialized as a JSON string.
    /// Engine adapter deserializes this into the engine-side type.
    pub value_json: String,
}

impl FieldChange {
    pub fn new(
        field_name: impl Into<String>,
        value_json: impl Into<String>,
    ) -> Self {
        Self {
            field_name: field_name.into(),
            value_json: value_json.into(),
        }
    }
}

// ── Component Change ──────────────────────────────────────────────────────────

/// All field-level changes for one component on one entity this tick.
///
/// Groups field changes by component type ID. The engine adapter
/// looks up the component type and applies each field change
/// to its engine-side representation.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ComponentChange {
    /// The component type ID from UCL/DCL/GCL registry.
    pub component_type_id: u32,

    /// The canonical component type name for engine adapter lookup.
    /// Example: "COMP_TRANSFORM_V1", "COMP_HEALTH_V1"
    pub component_type_name: String,

    /// Field-level changes within this component this tick.
    /// Sorted by field_name for deterministic processing (D11).
    pub field_changes: Vec<FieldChange>,
}

impl ComponentChange {
    /// Creates a component change with a single field change.
    pub fn single_field(
        component_type_id: u32,
        component_type_name: impl Into<String>,
        field_name: impl Into<String>,
        value_json: impl Into<String>,
    ) -> Self {
        Self {
            component_type_id,
            component_type_name: component_type_name.into(),
            field_changes: vec![FieldChange::new(field_name, value_json)],
        }
    }

    /// Creates a component change with multiple field changes.
    /// Sorts field changes by name for deterministic ordering (D11).
    pub fn multi_field(
        component_type_id: u32,
        component_type_name: impl Into<String>,
        mut field_changes: Vec<FieldChange>,
    ) -> Self {
        field_changes.sort_by(|a, b| a.field_name.cmp(&b.field_name));
        Self {
            component_type_id,
            component_type_name: component_type_name.into(),
            field_changes,
        }
    }

    /// Returns the number of field changes in this component change.
    pub fn field_count(&self) -> usize {
        self.field_changes.len()
    }
}

// ── Spawned Entity ────────────────────────────────────────────────────────────

/// Record of an entity spawned this tick.
///
/// Includes the entity's initial component data so the engine adapter
/// can create the entity and attach all components in one operation.
/// Components are sorted by type ID for deterministic processing (D11).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SpawnedEntity {
    /// The EntityID assigned to this new entity.
    pub entity_id: EntityID,

    /// The actor definition ID this entity was spawned from.
    /// Empty string if spawned without a blueprint (runtime-generated).
    pub actor_id: String,

    /// Initial component data for this entity.
    /// BTreeMap<component_type_id, serialized_component_json>
    /// Sorted by component_type_id for deterministic processing (D11).
    pub initial_components: BTreeMap<u32, String>,

    /// Tags from COMP_IDENTITY_V1 for quick engine-side filtering.
    pub tags: Vec<String>,
}

impl SpawnedEntity {
    /// Creates a spawned entity record with no initial components.
    pub fn new(entity_id: EntityID, actor_id: impl Into<String>) -> Self {
        Self {
            entity_id,
            actor_id: actor_id.into(),
            initial_components: BTreeMap::new(),
            tags: Vec::new(),
        }
    }

    /// Adds an initial component to this spawned entity.
    pub fn with_component(
        mut self,
        type_id: u32,
        component_json: impl Into<String>,
    ) -> Self {
        self.initial_components.insert(type_id, component_json.into());
        self
    }
}

// ── Destroyed Entity ──────────────────────────────────────────────────────────

/// Record of an entity destroyed this tick.
///
/// The engine adapter removes this entity from its scene
/// and releases all associated resources.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DestroyedEntity {
    /// The EntityID of the destroyed entity.
    pub entity_id: EntityID,

    /// The tick on which destruction was requested.
    /// May differ from the tick of destruction due to deferred processing.
    pub destroy_requested_tick: Tick,
}

impl DestroyedEntity {
    pub fn new(entity_id: EntityID, destroy_requested_tick: Tick) -> Self {
        Self {
            entity_id,
            destroy_requested_tick,
        }
    }
}

// ── Component Addition ────────────────────────────────────────────────────────

/// Record of a component added to an existing entity this tick.
///
/// Different from SpawnedEntity initial components — this records
/// components added to entities that already existed before this tick.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AddedComponent {
    /// The entity that received the new component.
    pub entity_id: EntityID,

    /// The component type that was added.
    pub component_type_id: u32,

    /// The canonical component type name.
    pub component_type_name: String,

    /// The initial component data serialized as JSON.
    pub component_json: String,
}

// ── Removed Component ─────────────────────────────────────────────────────────

/// Record of a component removed from an entity this tick.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RemovedComponent {
    /// The entity that lost the component.
    pub entity_id: EntityID,

    /// The component type that was removed.
    pub component_type_id: u32,

    /// The canonical component type name.
    pub component_type_name: String,
}

// ── State Delta ───────────────────────────────────────────────────────────────

/// The complete set of changes that occurred during one simulation tick.
///
/// Produced by the PhaseOrchestrator at the end of each tick.
/// Consumed by the DeltaSyncEngine to produce minimal WireMessages
/// for the engine adapter.
///
/// ## Application Order (D4)
/// The engine adapter MUST apply changes in this order:
/// 1. spawned_entities  — create new entities with initial components
/// 2. added_components  — attach new components to existing entities
/// 3. updated_components — apply field-level changes to existing components
/// 4. removed_components — detach components from entities
/// 5. destroyed_entities — remove entities from the scene
///
/// Any other order risks operating on entities/components that
/// don't exist yet or have already been removed.
///
/// ## Determinism
/// All collections are sorted by EntityID ASC (D3).
/// Within each entity, components are sorted by type_id ASC (D11).
/// This ensures identical StateDelta produces identical engine state
/// regardless of the order mutations were submitted during the tick.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StateDelta {
    /// The tick this delta was produced from.
    pub tick: Tick,

    /// The schema version active during this tick.
    /// Engine adapter validates this matches its known version.
    pub schema_version: String,

    /// Entities spawned this tick.
    /// Sorted by EntityID ASC (D3).
    pub spawned_entities: Vec<SpawnedEntity>,

    /// Entities destroyed this tick.
    /// Sorted by EntityID ASC (D3).
    pub destroyed_entities: Vec<DestroyedEntity>,

    /// Components added to existing entities this tick.
    /// Sorted by EntityID ASC, then component_type_id ASC (D3, D11).
    pub added_components: Vec<AddedComponent>,

    /// Components removed from entities this tick.
    /// Sorted by EntityID ASC, then component_type_id ASC (D3, D11).
    pub removed_components: Vec<RemovedComponent>,

    /// Field-level component changes for existing entities this tick.
    /// BTreeMap<EntityID, BTreeMap<component_type_id, ComponentChange>>
    /// BTreeMap guarantees deterministic iteration order (D3, D11).
    pub updated_components: BTreeMap<EntityID, BTreeMap<u32, ComponentChange>>,
}

impl StateDelta {
    /// Creates an empty StateDelta for the given tick.
    pub fn empty(tick: Tick, schema_version: impl Into<String>) -> Self {
        Self {
            tick,
            schema_version: schema_version.into(),
            spawned_entities: Vec::new(),
            destroyed_entities: Vec::new(),
            added_components: Vec::new(),
            removed_components: Vec::new(),
            updated_components: BTreeMap::new(),
        }
    }

    /// Returns true if this delta contains no changes.
    /// Empty deltas are not sent to the engine adapter.
    pub fn is_empty(&self) -> bool {
        self.spawned_entities.is_empty()
            && self.destroyed_entities.is_empty()
            && self.added_components.is_empty()
            && self.removed_components.is_empty()
            && self.updated_components.is_empty()
    }

    /// Returns the total number of change events in this delta.
    pub fn change_count(&self) -> usize {
        self.spawned_entities.len()
            + self.destroyed_entities.len()
            + self.added_components.len()
            + self.removed_components.len()
            + self.updated_components.values()
                .map(|m| m.len())
                .sum::<usize>()
    }

    /// Records an entity spawned this tick.
    /// Maintains EntityID ascending sort order (D3).
    pub fn record_spawn(&mut self, entity: SpawnedEntity) {
        let pos = self.spawned_entities
            .partition_point(|e| e.entity_id < entity.entity_id);
        self.spawned_entities.insert(pos, entity);
    }

    /// Records an entity destroyed this tick.
    /// Maintains EntityID ascending sort order (D3).
    pub fn record_destroy(&mut self, entity: DestroyedEntity) {
        let pos = self.destroyed_entities
            .partition_point(|e| e.entity_id < entity.entity_id);
        self.destroyed_entities.insert(pos, entity);
    }

    /// Records a component added to an entity this tick.
    pub fn record_component_added(&mut self, added: AddedComponent) {
        self.added_components.push(added);
        // Sort by entity_id ASC, then component_type_id ASC (D3, D11)
        self.added_components.sort_by(|a, b| {
            a.entity_id.cmp(&b.entity_id)
                .then(a.component_type_id.cmp(&b.component_type_id))
        });
    }

    /// Records a component removed from an entity this tick.
    pub fn record_component_removed(&mut self, removed: RemovedComponent) {
        self.removed_components.push(removed);
        self.removed_components.sort_by(|a, b| {
            a.entity_id.cmp(&b.entity_id)
                .then(a.component_type_id.cmp(&b.component_type_id))
        });
    }

    /// Records a component field change for an entity this tick.
    /// BTreeMap insertion maintains deterministic ordering (D3, D11).
    pub fn record_component_update(
        &mut self,
        entity_id: EntityID,
        change: ComponentChange,
    ) {
        self.updated_components
            .entry(entity_id)
            .or_insert_with(BTreeMap::new)
            .insert(change.component_type_id, change);
    }

    /// Returns all component changes for a specific entity this tick.
    pub fn get_entity_changes(
        &self,
        entity_id: EntityID,
    ) -> Option<&BTreeMap<u32, ComponentChange>> {
        self.updated_components.get(&entity_id)
    }

    /// Returns true if the given entity was spawned this tick.
    pub fn was_spawned(&self, entity_id: EntityID) -> bool {
        self.spawned_entities
            .binary_search_by(|e| e.entity_id.cmp(&entity_id))
            .is_ok()
    }

    /// Returns true if the given entity was destroyed this tick.
    pub fn was_destroyed(&self, entity_id: EntityID) -> bool {
        self.destroyed_entities
            .binary_search_by(|e| e.entity_id.cmp(&entity_id))
            .is_ok()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_delta_is_empty() {
        let delta = StateDelta::empty(0, "0.1.0");
        assert!(delta.is_empty());
        assert_eq!(delta.change_count(), 0);
    }

    #[test]
    fn record_spawn_maintains_sort_order() {
        let mut delta = StateDelta::empty(1, "0.1.0");
        delta.record_spawn(SpawnedEntity::new(5, "actor_zombie"));
        delta.record_spawn(SpawnedEntity::new(1, "actor_player"));
        delta.record_spawn(SpawnedEntity::new(3, "actor_chest"));
        assert_eq!(delta.spawned_entities[0].entity_id, 1);
        assert_eq!(delta.spawned_entities[1].entity_id, 3);
        assert_eq!(delta.spawned_entities[2].entity_id, 5);
    }

    #[test]
    fn record_destroy_maintains_sort_order() {
        let mut delta = StateDelta::empty(1, "0.1.0");
        delta.record_destroy(DestroyedEntity::new(10, 0));
        delta.record_destroy(DestroyedEntity::new(2, 0));
        delta.record_destroy(DestroyedEntity::new(7, 0));
        assert_eq!(delta.destroyed_entities[0].entity_id, 2);
        assert_eq!(delta.destroyed_entities[1].entity_id, 7);
        assert_eq!(delta.destroyed_entities[2].entity_id, 10);
    }

    #[test]
    fn record_component_update_uses_btreemap() {
        let mut delta = StateDelta::empty(1, "0.1.0");
        let change = ComponentChange::single_field(
            1,
            "COMP_TRANSFORM_V1",
            "position",
            r#"{"x":1.0,"y":0.0,"z":0.0}"#,
        );
        delta.record_component_update(42, change);
        assert!(delta.get_entity_changes(42).is_some());
        assert!(delta.get_entity_changes(99).is_none());
    }

    #[test]
    fn was_spawned_detects_correctly() {
        let mut delta = StateDelta::empty(1, "0.1.0");
        delta.record_spawn(SpawnedEntity::new(1, "actor_player"));
        assert!(delta.was_spawned(1));
        assert!(!delta.was_spawned(2));
    }

    #[test]
    fn was_destroyed_detects_correctly() {
        let mut delta = StateDelta::empty(1, "0.1.0");
        delta.record_destroy(DestroyedEntity::new(5, 0));
        assert!(delta.was_destroyed(5));
        assert!(!delta.was_destroyed(1));
    }

    #[test]
    fn change_count_sums_all_types() {
        let mut delta = StateDelta::empty(1, "0.1.0");
        delta.record_spawn(SpawnedEntity::new(1, "actor_player"));
        delta.record_destroy(DestroyedEntity::new(99, 0));
        delta.record_component_update(
            1,
            ComponentChange::single_field(1, "COMP_TRANSFORM_V1", "position", "{}"),
        );
        assert_eq!(delta.change_count(), 3);
    }

    #[test]
    fn non_empty_delta_not_empty() {
        let mut delta = StateDelta::empty(0, "0.1.0");
        delta.record_spawn(SpawnedEntity::new(1, "actor_player"));
        assert!(!delta.is_empty());
    }

    #[test]
    fn spawned_entity_with_component() {
        let entity = SpawnedEntity::new(1, "actor_player")
            .with_component(1, r#"{"position":{"x":0,"y":0,"z":0}}"#);
        assert!(entity.initial_components.contains_key(&1));
    }

    #[test]
    fn component_change_sorts_fields() {
        let fields = vec![
            FieldChange::new("z_field", "1"),
            FieldChange::new("a_field", "2"),
            FieldChange::new("m_field", "3"),
        ];
        let change = ComponentChange::multi_field(1, "COMP_TEST", fields);
        assert_eq!(change.field_changes[0].field_name, "a_field");
        assert_eq!(change.field_changes[1].field_name, "m_field");
        assert_eq!(change.field_changes[2].field_name, "z_field");
    }

    #[test]
    fn added_components_sorted_by_entity_then_type() {
        let mut delta = StateDelta::empty(1, "0.1.0");
        delta.record_component_added(AddedComponent {
            entity_id: 5,
            component_type_id: 1,
            component_type_name: "COMP_TRANSFORM_V1".into(),
            component_json: "{}".into(),
        });
        delta.record_component_added(AddedComponent {
            entity_id: 2,
            component_type_id: 3,
            component_type_name: "COMP_RENDER_V1".into(),
            component_json: "{}".into(),
        });
        delta.record_component_added(AddedComponent {
            entity_id: 2,
            component_type_id: 1,
            component_type_name: "COMP_TRANSFORM_V1".into(),
            component_json: "{}".into(),
        });
        assert_eq!(delta.added_components[0].entity_id, 2);
        assert_eq!(delta.added_components[0].component_type_id, 1);
        assert_eq!(delta.added_components[1].entity_id, 2);
        assert_eq!(delta.added_components[1].component_type_id, 3);
        assert_eq!(delta.added_components[2].entity_id, 5);
    }

    #[test]
    fn tick_stored_correctly() {
        let delta = StateDelta::empty(42, "0.1.0");
        assert_eq!(delta.tick, 42);
    }

    #[test]
    fn schema_version_stored_correctly() {
        let delta = StateDelta::empty(0, "1.2.3");
        assert_eq!(delta.schema_version, "1.2.3");
    }
}