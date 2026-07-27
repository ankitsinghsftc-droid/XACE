//! Incremental state-change payload sent from XACE to engine adapters.
//!
//! The adapter must apply a delta in this order:
//! spawn entities, add components, modify components, remove components, destroy
//! entities. The structs below preserve deterministic ordering and expose
//! validation so bad deltas are caught before they reach an engine scene.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

use crate::entity_id::{EntityID, NULL_ENTITY_ID};
use crate::entity_metadata::Tick;

/// Complete component JSON used for component creation or replacement.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WireComponentData {
    pub component_type_id: u32,
    pub component_type_name: String,
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

    pub fn data_value(&self) -> Result<serde_json::Value, serde_json::Error> {
        serde_json::from_str(&self.data_json)
    }

    pub fn payload_size_bytes(&self) -> usize {
        self.component_type_name.len() + self.data_json.len()
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.component_type_id == 0 {
            return Err("component_type_id must not be zero".into());
        }
        if self.component_type_name.trim().is_empty() {
            return Err(format!(
                "component {} has empty component_type_name",
                self.component_type_id
            ));
        }
        serde_json::from_str::<serde_json::Value>(&self.data_json).map_err(|err| {
            format!(
                "component {} ({}) has invalid JSON: {}",
                self.component_type_id, self.component_type_name, err
            )
        })?;
        Ok(())
    }
}

/// One field-level component change.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WireFieldChange {
    pub field_name: String,
    pub value_json: String,
}

impl WireFieldChange {
    pub fn new(field_name: impl Into<String>, value_json: impl Into<String>) -> Self {
        Self {
            field_name: field_name.into(),
            value_json: value_json.into(),
        }
    }

    pub fn value(&self) -> Result<serde_json::Value, serde_json::Error> {
        serde_json::from_str(&self.value_json)
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.field_name.trim().is_empty() {
            return Err("field change field_name must not be empty".into());
        }
        serde_json::from_str::<serde_json::Value>(&self.value_json).map_err(|err| {
            format!(
                "field '{}' has invalid value_json: {}",
                self.field_name, err
            )
        })?;
        Ok(())
    }
}

/// Field-level updates for one component on one entity.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WireComponentUpdate {
    pub component_type_id: u32,
    pub component_type_name: String,
    pub field_changes: Vec<WireFieldChange>,
}

impl WireComponentUpdate {
    pub fn new(
        component_type_id: u32,
        component_type_name: impl Into<String>,
        mut field_changes: Vec<WireFieldChange>,
    ) -> Self {
        sort_dedup_field_changes(&mut field_changes);
        Self {
            component_type_id,
            component_type_name: component_type_name.into(),
            field_changes,
        }
    }

    pub fn field_count(&self) -> usize {
        self.field_changes.len()
    }

    pub fn is_empty(&self) -> bool {
        self.field_changes.is_empty()
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.component_type_id == 0 {
            return Err("component update type id must not be zero".into());
        }
        if self.component_type_name.trim().is_empty() {
            return Err(format!(
                "component update {} has empty component_type_name",
                self.component_type_id
            ));
        }
        ensure_sorted_unique_by(
            &self.field_changes,
            |change| change.field_name.clone(),
            "component update field_changes",
        )?;
        if self.field_changes.is_empty() {
            return Err(format!(
                "component update {} must contain at least one field change",
                self.component_type_id
            ));
        }
        for change in &self.field_changes {
            change.validate()?;
        }
        Ok(())
    }
}

/// Entity spawned this tick with initial component data.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WireSpawnedEntity {
    pub entity_id: EntityID,
    pub actor_id: String,
    pub initial_components: Vec<WireComponentData>,
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

    pub fn with_tags(mut self, tags: Vec<String>) -> Self {
        self.tags = normalize_tags(tags);
        self
    }

    pub fn add_component(&mut self, component: WireComponentData) {
        match self
            .initial_components
            .binary_search_by_key(&component.component_type_id, |c| c.component_type_id)
        {
            Ok(idx) => self.initial_components[idx] = component,
            Err(idx) => self.initial_components.insert(idx, component),
        }
    }

    pub fn has_component(&self, component_type_id: u32) -> bool {
        self.initial_components
            .binary_search_by_key(&component_type_id, |c| c.component_type_id)
            .is_ok()
    }

    pub fn component_count(&self) -> usize {
        self.initial_components.len()
    }

    pub fn validate(&self) -> Result<(), String> {
        ensure_entity_id(self.entity_id, "spawned entity")?;
        ensure_sorted_unique_by(
            &self.initial_components,
            |component| component.component_type_id,
            "spawned entity initial_components",
        )?;
        ensure_sorted_unique_strings(&self.tags, "spawned entity tags")?;
        for component in &self.initial_components {
            component.validate()?;
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WireDestroyedEntity {
    pub entity_id: EntityID,
}

impl WireDestroyedEntity {
    pub fn new(entity_id: EntityID) -> Self {
        Self { entity_id }
    }

    pub fn validate(&self) -> Result<(), String> {
        ensure_entity_id(self.entity_id, "destroyed entity")
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WireAddedComponent {
    pub entity_id: EntityID,
    pub component: WireComponentData,
}

impl WireAddedComponent {
    pub fn new(entity_id: EntityID, component: WireComponentData) -> Self {
        Self {
            entity_id,
            component,
        }
    }

    pub fn validate(&self) -> Result<(), String> {
        ensure_entity_id(self.entity_id, "added component entity")?;
        self.component.validate()
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WireRemovedComponent {
    pub entity_id: EntityID,
    pub component_type_id: u32,
    pub component_type_name: String,
}

impl WireRemovedComponent {
    pub fn new(
        entity_id: EntityID,
        component_type_id: u32,
        component_type_name: impl Into<String>,
    ) -> Self {
        Self {
            entity_id,
            component_type_id,
            component_type_name: component_type_name.into(),
        }
    }

    pub fn validate(&self) -> Result<(), String> {
        ensure_entity_id(self.entity_id, "removed component entity")?;
        if self.component_type_id == 0 {
            return Err("removed component type id must not be zero".into());
        }
        if self.component_type_name.trim().is_empty() {
            return Err(format!(
                "removed component {} has empty component_type_name",
                self.component_type_id
            ));
        }
        Ok(())
    }
}

/// All component updates for one entity.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WireEntityUpdate {
    pub entity_id: EntityID,
    pub component_updates: BTreeMap<u32, WireComponentUpdate>,
}

impl WireEntityUpdate {
    pub fn new(entity_id: EntityID) -> Self {
        Self {
            entity_id,
            component_updates: BTreeMap::new(),
        }
    }

    pub fn add_component_update(&mut self, update: WireComponentUpdate) {
        self.component_updates
            .insert(update.component_type_id, update);
    }

    pub fn update_count(&self) -> usize {
        self.component_updates.len()
    }

    pub fn total_field_changes(&self) -> usize {
        self.component_updates
            .values()
            .map(WireComponentUpdate::field_count)
            .sum()
    }

    pub fn validate(&self) -> Result<(), String> {
        ensure_entity_id(self.entity_id, "modified entity")?;
        if self.component_updates.is_empty() {
            return Err(format!(
                "modified entity {} has no component updates",
                self.entity_id
            ));
        }
        for (type_id, update) in &self.component_updates {
            if *type_id != update.component_type_id {
                return Err(format!(
                    "modified entity {} map key {} does not match update type {}",
                    self.entity_id, type_id, update.component_type_id
                ));
            }
            update.validate()?;
        }
        Ok(())
    }
}

/// Complete delta payload for one simulation tick.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DeltaPayload {
    pub tick: Tick,
    pub sequence_id: u64,
    pub schema_version: String,
    pub spawned_entities: Vec<WireSpawnedEntity>,
    pub added_components: Vec<WireAddedComponent>,
    pub modified_entities: BTreeMap<EntityID, WireEntityUpdate>,
    pub removed_components: Vec<WireRemovedComponent>,
    pub destroyed_entities: Vec<WireDestroyedEntity>,
}

impl DeltaPayload {
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

    pub fn is_empty(&self) -> bool {
        self.spawned_entities.is_empty()
            && self.added_components.is_empty()
            && self.modified_entities.is_empty()
            && self.removed_components.is_empty()
            && self.destroyed_entities.is_empty()
    }

    /// Counts top-level change records. Use `operation_count` for field-level work.
    pub fn change_count(&self) -> usize {
        self.spawned_entities.len()
            + self.added_components.len()
            + self.modified_entities.len()
            + self.removed_components.len()
            + self.destroyed_entities.len()
    }

    /// Counts actual engine-side operations, including each field change.
    pub fn operation_count(&self) -> usize {
        self.spawned_entities.len()
            + self.added_components.len()
            + self
                .modified_entities
                .values()
                .map(WireEntityUpdate::total_field_changes)
                .sum::<usize>()
            + self.removed_components.len()
            + self.destroyed_entities.len()
    }

    pub fn total_payload_bytes(&self) -> usize {
        self.schema_version.len()
            + self
                .spawned_entities
                .iter()
                .map(|entity| {
                    entity.actor_id.len()
                        + entity.tags.iter().map(String::len).sum::<usize>()
                        + entity
                            .initial_components
                            .iter()
                            .map(WireComponentData::payload_size_bytes)
                            .sum::<usize>()
                })
                .sum::<usize>()
            + self
                .added_components
                .iter()
                .map(|addition| addition.component.payload_size_bytes())
                .sum::<usize>()
            + self
                .modified_entities
                .values()
                .flat_map(|entity| entity.component_updates.values())
                .flat_map(|update| update.field_changes.iter())
                .map(|change| change.field_name.len() + change.value_json.len())
                .sum::<usize>()
            + self
                .removed_components
                .iter()
                .map(|removal| removal.component_type_name.len())
                .sum::<usize>()
    }

    pub fn add_spawn(&mut self, entity: WireSpawnedEntity) {
        insert_sorted_replace_by_key(&mut self.spawned_entities, entity, |entity| {
            entity.entity_id
        });
    }

    pub fn add_destroy(&mut self, entity: WireDestroyedEntity) {
        insert_sorted_replace_by_key(&mut self.destroyed_entities, entity, |entity| {
            entity.entity_id
        });
    }

    pub fn add_component_addition(&mut self, addition: WireAddedComponent) {
        insert_sorted_replace_by_key(&mut self.added_components, addition, |addition| {
            (addition.entity_id, addition.component.component_type_id)
        });
    }

    pub fn add_component_removal(&mut self, removal: WireRemovedComponent) {
        insert_sorted_replace_by_key(&mut self.removed_components, removal, |removal| {
            (removal.entity_id, removal.component_type_id)
        });
    }

    pub fn add_component_update(&mut self, entity_id: EntityID, update: WireComponentUpdate) {
        self.modified_entities
            .entry(entity_id)
            .or_insert_with(|| WireEntityUpdate::new(entity_id))
            .add_component_update(update);
    }

    pub fn was_spawned(&self, entity_id: EntityID) -> bool {
        self.spawned_entities
            .binary_search_by_key(&entity_id, |entity| entity.entity_id)
            .is_ok()
    }

    pub fn was_destroyed(&self, entity_id: EntityID) -> bool {
        self.destroyed_entities
            .binary_search_by_key(&entity_id, |entity| entity.entity_id)
            .is_ok()
    }

    pub fn has_component_addition(&self, entity_id: EntityID, component_type_id: u32) -> bool {
        self.added_components
            .binary_search_by_key(&(entity_id, component_type_id), |addition| {
                (addition.entity_id, addition.component.component_type_id)
            })
            .is_ok()
    }

    pub fn has_component_removal(&self, entity_id: EntityID, component_type_id: u32) -> bool {
        self.removed_components
            .binary_search_by_key(&(entity_id, component_type_id), |removal| {
                (removal.entity_id, removal.component_type_id)
            })
            .is_ok()
    }

    pub fn normalize(&mut self) {
        sort_dedup_by_key(&mut self.spawned_entities, |entity| entity.entity_id);
        for entity in &mut self.spawned_entities {
            entity.tags = normalize_tags(std::mem::take(&mut entity.tags));
            sort_dedup_by_key(&mut entity.initial_components, |component| {
                component.component_type_id
            });
        }
        sort_dedup_by_key(&mut self.added_components, |addition| {
            (addition.entity_id, addition.component.component_type_id)
        });
        sort_dedup_by_key(&mut self.removed_components, |removal| {
            (removal.entity_id, removal.component_type_id)
        });
        sort_dedup_by_key(&mut self.destroyed_entities, |entity| entity.entity_id);
        for entity in self.modified_entities.values_mut() {
            for update in entity.component_updates.values_mut() {
                sort_dedup_field_changes(&mut update.field_changes);
            }
        }
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.schema_version.trim().is_empty() {
            return Err("DeltaPayload schema_version must not be empty".into());
        }
        ensure_sorted_unique_by(
            &self.spawned_entities,
            |entity| entity.entity_id,
            "delta spawned_entities",
        )?;
        ensure_sorted_unique_by(
            &self.added_components,
            |addition| (addition.entity_id, addition.component.component_type_id),
            "delta added_components",
        )?;
        ensure_sorted_unique_by(
            &self.removed_components,
            |removal| (removal.entity_id, removal.component_type_id),
            "delta removed_components",
        )?;
        ensure_sorted_unique_by(
            &self.destroyed_entities,
            |entity| entity.entity_id,
            "delta destroyed_entities",
        )?;

        for entity in &self.spawned_entities {
            entity.validate()?;
        }
        for addition in &self.added_components {
            addition.validate()?;
        }
        for (entity_id, update) in &self.modified_entities {
            if *entity_id != update.entity_id {
                return Err(format!(
                    "delta modified_entities map key {} does not match record entity {}",
                    entity_id, update.entity_id
                ));
            }
            update.validate()?;
        }
        for removal in &self.removed_components {
            removal.validate()?;
        }
        for entity in &self.destroyed_entities {
            entity.validate()?;
        }
        self.validate_conflicts()
    }

    fn validate_conflicts(&self) -> Result<(), String> {
        for spawned in &self.spawned_entities {
            if self.was_destroyed(spawned.entity_id) {
                return Err(format!(
                    "entity {} appears in both spawned_entities and destroyed_entities",
                    spawned.entity_id
                ));
            }
            if self.modified_entities.contains_key(&spawned.entity_id) {
                return Err(format!(
                    "entity {} is spawned and modified in the same delta; put initial data in spawn",
                    spawned.entity_id
                ));
            }
        }
        for destroyed in &self.destroyed_entities {
            if self.modified_entities.contains_key(&destroyed.entity_id) {
                return Err(format!(
                    "entity {} is modified and destroyed in the same delta",
                    destroyed.entity_id
                ));
            }
            if self
                .added_components
                .iter()
                .any(|addition| addition.entity_id == destroyed.entity_id)
            {
                return Err(format!(
                    "entity {} receives components and is destroyed in the same delta",
                    destroyed.entity_id
                ));
            }
        }
        Ok(())
    }
}

fn ensure_entity_id(entity_id: EntityID, label: &str) -> Result<(), String> {
    if entity_id == NULL_ENTITY_ID {
        Err(format!("{} entity_id must not be NULL_ENTITY_ID", label))
    } else {
        Ok(())
    }
}

fn normalize_tags(mut tags: Vec<String>) -> Vec<String> {
    tags.retain(|tag| !tag.trim().is_empty());
    tags.sort();
    tags.dedup();
    tags
}

fn sort_dedup_field_changes(fields: &mut Vec<WireFieldChange>) {
    fields.sort_by(|a, b| a.field_name.cmp(&b.field_name));
    fields.dedup_by(|a, b| a.field_name == b.field_name);
}

fn insert_sorted_replace_by_key<T, K: Ord, F: Fn(&T) -> K>(items: &mut Vec<T>, item: T, key: F) {
    let item_key = key(&item);
    match items.binary_search_by_key(&item_key, |existing| key(existing)) {
        Ok(idx) => items[idx] = item,
        Err(idx) => items.insert(idx, item),
    }
}

fn sort_dedup_by_key<T, K: Ord, F: Fn(&T) -> K>(items: &mut Vec<T>, key: F) {
    items.sort_by_key(|item| key(item));
    items.dedup_by(|a, b| key(a) == key(b));
}

fn ensure_sorted_unique_by<T, K: Ord, F: Fn(&T) -> K>(
    items: &[T],
    key: F,
    label: &str,
) -> Result<(), String> {
    for pair in items.windows(2) {
        if key(&pair[0]) >= key(&pair[1]) {
            return Err(format!(
                "{} must be sorted ascending with no duplicates",
                label
            ));
        }
    }
    Ok(())
}

fn ensure_sorted_unique_strings(values: &[String], label: &str) -> Result<(), String> {
    for value in values {
        if value.trim().is_empty() {
            return Err(format!("{} must not contain empty strings", label));
        }
    }
    for pair in values.windows(2) {
        if pair[0] >= pair[1] {
            return Err(format!(
                "{} must be sorted ascending with no duplicates",
                label
            ));
        }
    }
    Ok(())
}

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
        assert!(empty_delta().validate().is_ok());
    }

    #[test]
    fn add_spawn_maintains_sort_order_and_replaces_duplicates() {
        let mut delta = empty_delta();
        delta.add_spawn(WireSpawnedEntity::new(5, "actor_zombie"));
        delta.add_spawn(WireSpawnedEntity::new(1, "actor_player"));
        delta.add_spawn(WireSpawnedEntity::new(3, "actor_chest"));
        delta.add_spawn(WireSpawnedEntity::new(3, "actor_chest_v2"));

        assert_eq!(
            delta
                .spawned_entities
                .iter()
                .map(|entity| entity.entity_id)
                .collect::<Vec<_>>(),
            vec![1, 3, 5]
        );
        assert_eq!(delta.spawned_entities[1].actor_id, "actor_chest_v2");
    }

    #[test]
    fn component_and_field_validation_require_json() {
        assert!(WireComponentData::new(1, "COMP_TRANSFORM_V1", "{}")
            .validate()
            .is_ok());
        assert!(WireComponentData::new(1, "COMP_TRANSFORM_V1", "not-json")
            .validate()
            .is_err());

        let update = WireComponentUpdate::new(
            1,
            "COMP_TRANSFORM_V1",
            vec![
                WireFieldChange::new("z", "3"),
                WireFieldChange::new("a", r#"{"x":1}"#),
            ],
        );
        assert_eq!(update.field_changes[0].field_name, "a");
        assert!(update.validate().is_ok());
    }

    #[test]
    fn additions_and_removals_are_sorted_by_entity_then_type() {
        let mut delta = empty_delta();
        delta.add_component_addition(WireAddedComponent::new(
            5,
            WireComponentData::new(1, "COMP_TRANSFORM_V1", "{}"),
        ));
        delta.add_component_addition(WireAddedComponent::new(
            2,
            WireComponentData::new(3, "COMP_RENDER_V1", "{}"),
        ));
        delta.add_component_addition(WireAddedComponent::new(
            2,
            WireComponentData::new(1, "COMP_TRANSFORM_V1", "{}"),
        ));
        delta.add_component_removal(WireRemovedComponent::new(9, 2, "B"));
        delta.add_component_removal(WireRemovedComponent::new(1, 8, "A"));

        assert_eq!(delta.added_components[0].entity_id, 2);
        assert_eq!(delta.added_components[0].component.component_type_id, 1);
        assert!(delta.has_component_addition(2, 3));
        assert!(delta.has_component_removal(1, 8));
    }

    #[test]
    fn entity_update_counts_fields() {
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
        assert_eq!(update.update_count(), 2);
        assert_eq!(update.total_field_changes(), 3);
        assert!(update.validate().is_ok());
    }

    #[test]
    fn validation_catches_unsorted_and_conflicting_changes() {
        let mut delta = empty_delta();
        delta
            .spawned_entities
            .push(WireSpawnedEntity::new(10, "actor"));
        delta
            .spawned_entities
            .push(WireSpawnedEntity::new(2, "actor"));
        assert!(delta.validate().is_err());

        let mut delta = empty_delta();
        delta.add_spawn(WireSpawnedEntity::new(1, "actor"));
        delta.add_destroy(WireDestroyedEntity::new(1));
        assert!(delta.validate().is_err());
    }

    #[test]
    fn normalize_restores_deterministic_order() {
        let mut delta = empty_delta();
        delta
            .spawned_entities
            .push(WireSpawnedEntity::new(3, "actor").with_tags(vec!["z".into(), "a".into()]));
        delta
            .spawned_entities
            .push(WireSpawnedEntity::new(1, "actor"));
        delta.normalize();
        assert_eq!(delta.spawned_entities[0].entity_id, 1);
        assert_eq!(delta.spawned_entities[1].tags, vec!["a", "z"]);
        assert!(delta.validate().is_ok());
    }

    #[test]
    fn operation_count_includes_field_changes() {
        let mut delta = empty_delta();
        delta.add_spawn(WireSpawnedEntity::new(1, "actor"));
        delta.add_component_update(
            2,
            WireComponentUpdate::new(
                1,
                "COMP_TRANSFORM_V1",
                vec![
                    WireFieldChange::new("x", "1"),
                    WireFieldChange::new("y", "2"),
                ],
            ),
        );
        assert_eq!(delta.change_count(), 2);
        assert_eq!(delta.operation_count(), 3);
        assert!(delta.total_payload_bytes() > 0);
    }

    #[test]
    fn null_entity_ids_are_rejected() {
        let mut delta = empty_delta();
        delta.add_destroy(WireDestroyedEntity::new(NULL_ENTITY_ID));
        assert!(delta.validate().is_err());
    }
}
