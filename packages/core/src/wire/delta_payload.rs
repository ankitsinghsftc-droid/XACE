//! # Delta Payload
//!
//! The wire-format payload for DELTA messages sent from XACE to the
//! engine adapter each tick. Contains only what changed — never the
//! full world state.
//!
//! ## Minimal Delta Principle
//! The DeltaSyncEngine (Phase 8) compares the current StateDelta
//! against the last-sent state and produces a DeltaPayload containing
//! only genuinely changed data. Unchanged components are never included.
//! This minimizes bandwidth and engine-side processing cost.
//!
//! ## Ordering (D4)
//! The engine adapter MUST apply changes in this strict order:
//! 1. spawned_entities  — create new entities
//! 2. added_components  — attach new components to existing entities
//! 3. modified_components — apply field changes to existing components
//! 4. removed_components — detach components from entities
//! 5. destroyed_entities — remove entities from scene
//!
//! This order is enforced by the DeltaBuilder (Phase 8) and validated
//! by the engine adapter's DeltaApplicator. Any other order risks
//! operating on entities or components that don't exist yet.
//!
//! ## Sequence Tracking
//! Every DeltaPayload carries a sequence_id. The engine adapter tracks
//! sequence IDs and requests a SNAPSHOT if it detects a gap — meaning
//! a DELTA message was dropped or arrived out of order.
//!
//! ## Determinism (D3, D11)
//! All entity lists are sorted by EntityID ASC (D3).
//! All component lists are sorted by component_type_id ASC (D11).
//! Identical state changes always produce identical DeltaPayload bytes.

use std::collections::BTreeMap;
use serde::{Deserialize, Serialize};
use crate::entity_id::EntityID;
use crate::entity_metadata::Tick;

// ── Wire Component Data ───────────────────────────────────────────────────────

/// A component's complete data serialized for wire transmission.
///
/// Used when adding a new component to an entity or sending a
/// full component replacement. JSON is used for cross-language
/// compatibility with Unity C#, Unreal C++, and Godot GDScript.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct WireComponentData {
    /// The component type ID from the UCL/DCL/GCL registry.
    pub component_type_id: u32,

    /// The canonical component type name for engine-side lookup.
    pub component_type_name: String,

    /// Complete component data serialized as JSON.
    /// JSON keys are sorted alphabetically for determinism (D11).
    pub data_json: String,
}

impl WireComponentData {
    pub fn new(
        component_type_id: u32,
        component_type_name: impl Into<String>,
        data_json: impl Into<String>,
    ) -> Self {
        Self {
            component_type_id,
            component_type_name: component_type_name.into(),
            data_json: data_json.into(),
        }
    }
}

// ── Wire Field Change ─────────────────────────────────────────────────────────

/// A single field-level change within a component for wire transmission.
///
/// Used for minimal delta updates — only changed fields are sent,
/// not the entire component. Reduces bandwidth significantly for
/// components with many fields where only one or two change per tick.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct WireFieldChange {
    /// The name of the field that changed.
    pub field_name: String,

    /// The new field value serialized as a JSON value string.
    pub value_json: String,
}

impl WireFieldChange {
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

// ── Wire Component Update ─────────────────────────────────────────────────────

/// Field-level updates for one component on one entity.
///
/// Contains only the fields that changed — not the full component.
/// The engine adapter applies each field change to its existing
/// engine-side component representation.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct WireComponentUpdate {
    /// The component type being updated.
    pub component_type_id: u32,

    /// The canonical component type name.
    pub component_type_name: String,

    /// Changed fields sorted by field_name for determinism (D11).
    pub field_changes: Vec<WireFieldChange>,
}

impl WireComponentUpdate {
    /// Creates a component update with sorted field changes.
    pub fn new(
        component_type_id: u32,
        component_type_name: impl Into<String>,
        mut field_changes: Vec<WireFieldChange>,
    ) -> Self {
        field_changes.sort_by(|a, b| a.field_name.cmp(&b.field_name));
        Self {
            component_type_id,
            component_type_name: component_type_name.into(),
            field_changes,
        }
    }

    /// Returns the number of changed fields.
    pub fn field_count(&self) -> usize {
        self.field_changes.len()
    }
}

// ── Wire Spawned Entity ───────────────────────────────────────────────────────

/// An entity spawned this tick with its initial component data.
///
/// The engine adapter creates the entity and attaches all
/// initial components in one operation. Components are sorted
/// by component_type_id for deterministic processing (D11).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct WireSpawnedEntity {
    /// The EntityID assigned to this new entity.
    pub entity_id: EntityID,

    /// The actor definition ID this entity was spawned from.
    /// Empty string if spawned without a blueprint.
    pub actor_id: String,

    /// Initial components sorted by component_type_id ASC (D11).
    pub initial_components: Vec<WireComponentData>,

    /// Tags for quick engine-side filtering.
    /// Sorted alphabetically (D11).
    pub tags: Vec<String>,
}

impl WireSpawnedEntity {
    pub fn new(entity_id: EntityID, actor_id: impl Into<String>) -> Self {
        Self {
            entity_id,
            actor_id: actor_id.into(),
            initial_components: Vec::new(),
            tags: Vec::new(),
        }
    }

    /// Adds a component, maintaining sorted order by type_id (D11).
    pub fn add_component(&mut self, component: WireComponentData) {
        let pos = self.initial_components
            .partition_point(|c| c.component_type_id < component.component_type_id);
        self.initial_components.insert(pos, component);
    }
}

// ── Wire Destroyed Entity ─────────────────────────────────────────────────────

/// An entity destroyed this tick.
///
/// The engine adapter removes this entity from its scene
/// and releases all associated resources.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct WireDestroyedEntity {
    /// The EntityID of the destroyed entity.
    pub entity_id: EntityID,
}

impl WireDestroyedEntity {
    pub fn new(entity_id: EntityID) -> Self {
        Self { entity_id }
    }
}

// ── Wire Component Addition ───────────────────────────────────────────────────

/// A component added to an existing entity this tick.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct WireAddedComponent {
    /// The entity receiving the new component.
    pub entity_id: EntityID,

    /// The component being added with its initial data.
    pub component: WireComponentData,
}

// ── Wire Component Removal ────────────────────────────────────────────────────

/// A component removed from an entity this tick.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct WireRemovedComponent {
    /// The entity losing the component.
    pub entity_id: EntityID,

    /// The component type being removed.
    pub component_type_id: u32,

    /// The canonical component type name.
    pub component_type_name: String,
}

// ── Wire Entity Update ────────────────────────────────────────────────────────

/// All component updates for a single entity this tick.
///
/// Groups all component field changes for one entity into one record.
/// BTreeMap<component_type_id, WireComponentUpdate> ensures
/// deterministic component processing order (D11).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct WireEntityUpdate {
    /// The entity being updated.
    pub entity_id: EntityID,

    /// Component updates keyed by component_type_id.
    /// BTreeMap guarantees ascending type_id iteration order (D11).
    pub component_updates: BTreeMap<u32, WireComponentUpdate>,
}

impl WireEntityUpdate {
    pub fn new(entity_id: EntityID) -> Self {
        Self {
            entity_id,
            component_updates: BTreeMap::new(),
        }
    }

    /// Adds a component update to this entity update.
    pub fn add_component_update(&mut self, update: WireComponentUpdate) {
        self.component_updates
            .insert(update.component_type_id, update);
    }

    /// Returns the total number of field changes across all components.
    pub fn total_field_changes(&self) -> usize {
        self.component_updates
            .values()
            .map(|u| u.field_count())
            .sum()
    }
}

// ── Delta Payload ─────────────────────────────────────────────────────────────

/// The complete wire payload for a DELTA message.
///
/// Sent by XACE to the engine adapter every tick that has changes.
/// Contains only what changed — never the full world state.
///
/// ## Application Order (D4) — ENFORCED BY ENGINE ADAPTER
/// 1. spawned_entities  → create entities with initial components
/// 2. added_components  → attach new components to existing entities
/// 3. modified_entities → apply field changes to existing components
/// 4. removed_components → detach components from entities
/// 5. destroyed_entities → remove entities from scene
///
/// The DeltaBuilder (Phase 8) always produces payloads in this order.
/// The engine adapter's DeltaApplicator must apply them in this order.
/// Any deviation is a protocol violation.
///
/// ## Sequence Tracking
/// sequence_id is monotonically increasing per world session.
/// The engine adapter detects gaps and requests SNAPSHOT recovery.
/// Sequence IDs are never reused — even after SNAPSHOT recovery.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeltaPayload {
    /// The simulation tick this delta was produced from.
    pub tick: Tick,

    /// Monotonically increasing sequence number.
    /// Engine adapter requests SNAPSHOT if it detects a gap.
    pub sequence_id: u64,

    /// The schema version active during this tick.
    /// Engine adapter validates this matches its known version.
    pub schema_version: String,

    /// Entities spawned this tick sorted by EntityID ASC (D3).
    /// Applied FIRST by the engine adapter.
    pub spawned_entities: Vec<WireSpawnedEntity>,

    /// Components added to existing entities this tick.
    /// Sorted by entity_id ASC, then component_type_id ASC (D3, D11).
    /// Applied SECOND by the engine adapter.
    pub added_components: Vec<WireAddedComponent>,

    /// Field-level updates for existing entity components this tick.
    /// BTreeMap<EntityID, WireEntityUpdate> — sorted by EntityID ASC (D3).
    /// Applied THIRD by the engine adapter.
    pub modified_entities: BTreeMap<EntityID, WireEntityUpdate>,

    /// Components removed from entities this tick.
    /// Sorted by entity_id ASC, then component_type_id ASC (D3, D11).
    /// Applied FOURTH by the engine adapter.
    pub removed_components: Vec<WireRemovedComponent>,

    /// Entities destroyed this tick sorted by EntityID ASC (D3).
    /// Applied FIFTH (last) by the engine adapter.
    pub destroyed_entities: Vec<WireDestroyedEntity>,
}

impl DeltaPayload {
    /// Creates an empty delta payload for the given tick.
    pub fn empty(tick: Tick, sequence_id: u64, schema_version: impl Into<String>) -> Self {
        Self {
            tick,
            sequence_id,
            schema_version: schema_version.into(),
            spawned_entities: Vec::new(),
            added_components: Vec::new(),
            modified_entities: BTreeMap::new(),
            removed_components: Vec::new(),
            destroyed_entities: Vec::new(),
        }
    }

    /// Returns true if this payload has no changes.
    /// Empty deltas are not sent to the engine adapter.
    pub fn is_empty(&self) -> bool {
        self.spawned_entities.is_empty()
            && self.added_components.is_empty()
            && self.modified_entities.is_empty()
            && self.removed_components.is_empty()
            && self.destroyed_entities.is_empty()
    }

    /// Returns the total number of change records in this payload.
    pub fn change_count(&self) -> usize {
        self.spawned_entities.len()
            + self.added_components.len()
            + self.modified_entities.len()
            + self.removed_components.len()
            + self.destroyed_entities.len()
    }

    /// Adds a spawned entity maintaining EntityID sort order (D3).
    pub fn add_spawn(&mut self, entity: WireSpawnedEntity) {
        let pos = self.spawned_entities
            .partition_point(|e| e.entity_id < entity.entity_id);
        self.spawned_entities.insert(pos, entity);
    }

    /// Adds a destroyed entity maintaining EntityID sort order (D3).
    pub fn add_destroy(&mut self, entity: WireDestroyedEntity) {
        let pos = self.destroyed_entities
            .partition_point(|e| e.entity_id < entity.entity_id);
        self.destroyed_entities.insert(pos, entity);
    }

    /// Adds a component addition record maintaining sort order (D3, D11).
    pub fn add_component_addition(&mut self, addition: WireAddedComponent) {
        self.added_components.push(addition);
        self.added_components.sort_by(|a, b| {
            a.entity_id.cmp(&b.entity_id)
                .then(a.component.component_type_id.cmp(&b.component.component_type_id))
        });
    }

    /// Adds a component removal record maintaining sort order (D3, D11).
    pub fn add_component_removal(&mut self, removal: WireRemovedComponent) {
        self.removed_components.push(removal);
        self.removed_components.sort_by(|a, b| {
            a.entity_id.cmp(&b.entity_id)
                .then(a.component_type_id.cmp(&b.component_type_id))
        });
    }

    /// Records a component field update for an entity.
    /// BTreeMap insertion maintains deterministic ordering (D3, D11).
    pub fn add_component_update(
        &mut self,
        entity_id: EntityID,
        update: WireComponentUpdate,
    ) {
        self.modified_entities
            .entry(entity_id)
            .or_insert_with(|| WireEntityUpdate::new(entity_id))
            .add_component_update(update);
    }

    /// Returns true if a specific entity was spawned in this delta.
    pub fn was_spawned(&self, entity_id: EntityID) -> bool {
        self.spawned_entities
            .binary_search_by(|e| e.entity_id.cmp(&entity_id))
            .is_ok()
    }

    /// Returns true if a specific entity was destroyed in this delta.
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

    fn empty_delta() -> DeltaPayload {
        DeltaPayload::empty(1, 1, "0.1.0")
    }

    #[test]
    fn empty_delta_is_empty() {
        assert!(empty_delta().is_empty());
        assert_eq!(empty_delta().change_count(), 0);
    }

    #[test]
    fn add_spawn_maintains_sort_order() {
        let mut delta = empty_delta();
        delta.add_spawn(WireSpawnedEntity::new(5, "actor_zombie"));
        delta.add_spawn(WireSpawnedEntity::new(1, "actor_player"));
        delta.add_spawn(WireSpawnedEntity::new(3, "actor_chest"));
        assert_eq!(delta.spawned_entities[0].entity_id, 1);
        assert_eq!(delta.spawned_entities[1].entity_id, 3);
        assert_eq!(delta.spawned_entities[2].entity_id, 5);
    }

    #[test]
    fn add_destroy_maintains_sort_order() {
        let mut delta = empty_delta();
        delta.add_destroy(WireDestroyedEntity::new(10));
        delta.add_destroy(WireDestroyedEntity::new(2));
        delta.add_destroy(WireDestroyedEntity::new(7));
        assert_eq!(delta.destroyed_entities[0].entity_id, 2);
        assert_eq!(delta.destroyed_entities[1].entity_id, 7);
        assert_eq!(delta.destroyed_entities[2].entity_id, 10);
    }

    #[test]
    fn add_component_update_uses_btreemap() {
        let mut delta = empty_delta();
        let update = WireComponentUpdate::new(
            1,
            "COMP_TRANSFORM_V1",
            vec![WireFieldChange::new("position", r#"{"x":1.0}"#)],
        );
        delta.add_component_update(42, update);
        assert!(delta.modified_entities.contains_key(&42));
    }

    #[test]
    fn was_spawned_correct() {
        let mut delta = empty_delta();
        delta.add_spawn(WireSpawnedEntity::new(1, "actor_player"));
        assert!(delta.was_spawned(1));
        assert!(!delta.was_spawned(2));
    }

    #[test]
    fn was_destroyed_correct() {
        let mut delta = empty_delta();
        delta.add_destroy(WireDestroyedEntity::new(5));
        assert!(delta.was_destroyed(5));
        assert!(!delta.was_destroyed(1));
    }

    #[test]
    fn change_count_sums_all() {
        let mut delta = empty_delta();
        delta.add_spawn(WireSpawnedEntity::new(1, "actor_player"));
        delta.add_destroy(WireDestroyedEntity::new(99));
        assert_eq!(delta.change_count(), 2);
    }

    #[test]
    fn non_empty_delta_not_empty() {
        let mut delta = empty_delta();
        delta.add_spawn(WireSpawnedEntity::new(1, "actor_player"));
        assert!(!delta.is_empty());
    }

    #[test]
    fn wire_component_update_sorts_fields() {
        let fields = vec![
            WireFieldChange::new("z_field", "3"),
            WireFieldChange::new("a_field", "1"),
            WireFieldChange::new("m_field", "2"),
        ];
        let update = WireComponentUpdate::new(1, "COMP_TEST", fields);
        assert_eq!(update.field_changes[0].field_name, "a_field");
        assert_eq!(update.field_changes[1].field_name, "m_field");
        assert_eq!(update.field_changes[2].field_name, "z_field");
    }

    #[test]
    fn wire_spawned_entity_add_component_sorted() {
        let mut entity = WireSpawnedEntity::new(1, "actor_player");
        entity.add_component(WireComponentData::new(5, "COMP_VELOCITY_V1", "{}"));
        entity.add_component(WireComponentData::new(1, "COMP_TRANSFORM_V1", "{}"));
        entity.add_component(WireComponentData::new(3, "COMP_RENDER_V1", "{}"));
        assert_eq!(entity.initial_components[0].component_type_id, 1);
        assert_eq!(entity.initial_components[1].component_type_id, 3);
        assert_eq!(entity.initial_components[2].component_type_id, 5);
    }

    #[test]
    fn added_components_sorted_by_entity_then_type() {
        let mut delta = empty_delta();
        delta.add_component_addition(WireAddedComponent {
            entity_id: 5,
            component: WireComponentData::new(1, "COMP_TRANSFORM_V1", "{}"),
        });
        delta.add_component_addition(WireAddedComponent {
            entity_id: 2,
            component: WireComponentData::new(3, "COMP_RENDER_V1", "{}"),
        });
        delta.add_component_addition(WireAddedComponent {
            entity_id: 2,
            component: WireComponentData::new(1, "COMP_TRANSFORM_V1", "{}"),
        });
        assert_eq!(delta.added_components[0].entity_id, 2);
        assert_eq!(delta.added_components[0].component.component_type_id, 1);
        assert_eq!(delta.added_components[1].entity_id, 2);
        assert_eq!(delta.added_components[1].component.component_type_id, 3);
        assert_eq!(delta.added_components[2].entity_id, 5);
    }

    #[test]
    fn entity_update_total_field_changes() {
        let mut update = WireEntityUpdate::new(1);
        update.add_component_update(WireComponentUpdate::new(
            1,
            "COMP_TRANSFORM_V1",
            vec![
                WireFieldChange::new("position", "{}"),
                WireFieldChange::new("rotation", "{}"),
            ],
        ));
        update.add_component_update(WireComponentUpdate::new(
            5,
            "COMP_VELOCITY_V1",
            vec![WireFieldChange::new("linear", "{}")],
        ));
        assert_eq!(update.total_field_changes(), 3);
    }

    #[test]
    fn sequence_id_stored_correctly() {
        let delta = DeltaPayload::empty(10, 42, "0.1.0");
        assert_eq!(delta.sequence_id, 42);
        assert_eq!(delta.tick, 10);
    }
}