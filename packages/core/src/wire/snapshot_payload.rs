//! Full world-state payload sent from XACE to engine adapters.
//!
//! A `SnapshotPayload` is the adapter-facing reconstruction format. It does
//! not contain runtime-only replay internals such as RNG state, mutation queues,
//! or scheduler internals. It contains enough deterministic, sorted entity and
//! component data for an engine adapter to rebuild its scene exactly.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

use crate::entity_id::{EntityID, NULL_ENTITY_ID};
use crate::entity_metadata::Tick;
use crate::entity_state::EntityState;

/// Why a snapshot was emitted.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum SnapshotReason {
    InitialConnection,
    DesyncRecovery,
    ExplicitRequest,
    PeriodicRefresh,
}

impl std::fmt::Display for SnapshotReason {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InitialConnection => f.write_str("InitialConnection"),
            Self::DesyncRecovery => f.write_str("DesyncRecovery"),
            Self::ExplicitRequest => f.write_str("ExplicitRequest"),
            Self::PeriodicRefresh => f.write_str("PeriodicRefresh"),
        }
    }
}

/// Component data attached to one entity in a snapshot.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SnapshotComponentRecord {
    pub component_type_id: u32,
    pub component_type_name: String,
    pub data_json: String,
}

impl SnapshotComponentRecord {
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

    pub fn validate(&self) -> Result<(), String> {
        if self.component_type_id == 0 {
            return Err("snapshot component_type_id must not be zero".into());
        }
        if self.component_type_name.trim().is_empty() {
            return Err(format!(
                "snapshot component {} has empty component_type_name",
                self.component_type_id
            ));
        }
        serde_json::from_str::<serde_json::Value>(&self.data_json).map_err(|err| {
            format!(
                "snapshot component {} ({}) has invalid data_json: {}",
                self.component_type_id, self.component_type_name, err
            )
        })?;
        Ok(())
    }

    pub fn payload_size_bytes(&self) -> usize {
        self.component_type_name.len() + self.data_json.len()
    }
}

/// One entity and all components required to reconstruct it engine-side.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SnapshotEntityRecord {
    pub entity_id: EntityID,
    pub state: EntityState,
    pub components: BTreeMap<u32, SnapshotComponentRecord>,
    pub tags: Vec<String>,
}

impl SnapshotEntityRecord {
    pub fn new(entity_id: EntityID, state: EntityState) -> Self {
        Self {
            entity_id,
            state,
            components: BTreeMap::new(),
            tags: Vec::new(),
        }
    }

    pub fn with_tags(mut self, tags: Vec<String>) -> Self {
        self.tags = normalize_tags(tags);
        self
    }

    /// Inserts or replaces a component record by type id.
    pub fn add_component(&mut self, component: SnapshotComponentRecord) {
        self.components
            .insert(component.component_type_id, component);
    }

    pub fn remove_component(&mut self, type_id: u32) -> Option<SnapshotComponentRecord> {
        self.components.remove(&type_id)
    }

    pub fn get_component(&self, type_id: u32) -> Option<&SnapshotComponentRecord> {
        self.components.get(&type_id)
    }

    pub fn has_component(&self, type_id: u32) -> bool {
        self.components.contains_key(&type_id)
    }

    pub fn component_count(&self) -> usize {
        self.components.len()
    }

    pub fn has_tag(&self, tag: &str) -> bool {
        self.tags
            .binary_search_by(|known| known.as_str().cmp(tag))
            .is_ok()
    }

    pub fn is_active(&self) -> bool {
        self.state == EntityState::Active
    }

    pub fn is_engine_visible_state(&self) -> bool {
        matches!(self.state, EntityState::Active | EntityState::Disabled)
    }

    pub fn total_payload_bytes(&self) -> usize {
        self.tags.iter().map(String::len).sum::<usize>()
            + self
                .components
                .values()
                .map(SnapshotComponentRecord::payload_size_bytes)
                .sum::<usize>()
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.entity_id == NULL_ENTITY_ID {
            return Err("snapshot entity_id must not be NULL_ENTITY_ID".into());
        }
        if !self.is_engine_visible_state() {
            return Err(format!(
                "snapshot entity {} has non-engine-visible state {}",
                self.entity_id, self.state
            ));
        }
        ensure_sorted_unique_strings(&self.tags, "snapshot entity tags")?;
        for (type_id, component) in &self.components {
            if *type_id != component.component_type_id {
                return Err(format!(
                    "snapshot entity {} component map key {} does not match record type {}",
                    self.entity_id, type_id, component.component_type_id
                ));
            }
            component.validate()?;
        }
        Ok(())
    }
}

/// Complete adapter-facing snapshot payload.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SnapshotPayload {
    pub tick: Tick,
    pub schema_version: String,
    pub execution_plan_version: u32,
    pub cgs_hash: String,
    pub world_hash: String,
    pub last_delta_sequence_id: u64,
    pub is_full: bool,
    pub entities: Vec<SnapshotEntityRecord>,
    pub reason: SnapshotReason,
}

impl SnapshotPayload {
    pub fn new(
        tick: Tick,
        schema_version: impl Into<String>,
        execution_plan_version: u32,
        cgs_hash: impl Into<String>,
        world_hash: impl Into<String>,
        last_delta_sequence_id: u64,
        reason: SnapshotReason,
    ) -> Self {
        Self {
            tick,
            schema_version: schema_version.into(),
            execution_plan_version,
            cgs_hash: cgs_hash.into(),
            world_hash: world_hash.into(),
            last_delta_sequence_id,
            is_full: true,
            entities: Vec::new(),
            reason,
        }
    }

    pub fn mark_partial(&mut self) {
        self.is_full = false;
    }

    pub fn with_partial(mut self) -> Self {
        self.is_full = false;
        self
    }

    /// Inserts or replaces an entity while preserving ascending entity order.
    pub fn add_entity(&mut self, entity: SnapshotEntityRecord) {
        match self
            .entities
            .binary_search_by_key(&entity.entity_id, |e| e.entity_id)
        {
            Ok(idx) => self.entities[idx] = entity,
            Err(idx) => self.entities.insert(idx, entity),
        }
    }

    /// Fallible insert that rejects duplicate entity IDs.
    pub fn try_add_entity(&mut self, entity: SnapshotEntityRecord) -> Result<(), String> {
        match self
            .entities
            .binary_search_by_key(&entity.entity_id, |e| e.entity_id)
        {
            Ok(_) => Err(format!(
                "snapshot already contains entity {}",
                entity.entity_id
            )),
            Err(idx) => {
                self.entities.insert(idx, entity);
                Ok(())
            }
        }
    }

    pub fn get_entity(&self, entity_id: EntityID) -> Option<&SnapshotEntityRecord> {
        self.entities
            .binary_search_by_key(&entity_id, |e| e.entity_id)
            .ok()
            .map(|idx| &self.entities[idx])
    }

    pub fn contains_entity(&self, entity_id: EntityID) -> bool {
        self.entities
            .binary_search_by_key(&entity_id, |e| e.entity_id)
            .is_ok()
    }

    pub fn entity_count(&self) -> usize {
        self.entities.len()
    }

    pub fn total_component_count(&self) -> usize {
        self.entities
            .iter()
            .map(SnapshotEntityRecord::component_count)
            .sum()
    }

    pub fn total_payload_bytes(&self) -> usize {
        self.schema_version.len()
            + self.cgs_hash.len()
            + self.world_hash.len()
            + self
                .entities
                .iter()
                .map(SnapshotEntityRecord::total_payload_bytes)
                .sum::<usize>()
    }

    pub fn is_empty(&self) -> bool {
        self.entities.is_empty()
    }

    pub fn active_entities(&self) -> Vec<&SnapshotEntityRecord> {
        self.entities.iter().filter(|e| e.is_active()).collect()
    }

    /// Normalizes entity order, component order, and tags. Useful after
    /// deserializing snapshots from tools that may not preserve local ordering.
    pub fn normalize(&mut self) {
        self.entities.sort_by_key(|e| e.entity_id);
        self.entities.dedup_by_key(|e| e.entity_id);
        for entity in &mut self.entities {
            entity.tags = normalize_tags(std::mem::take(&mut entity.tags));
            let components = std::mem::take(&mut entity.components);
            entity.components = components.into_iter().collect();
        }
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.schema_version.trim().is_empty() {
            return Err("SnapshotPayload schema_version must not be empty".into());
        }
        if self.execution_plan_version == 0 {
            return Err("SnapshotPayload execution_plan_version must be greater than zero".into());
        }
        if self.world_hash.trim().is_empty() {
            return Err("SnapshotPayload world_hash must not be empty".into());
        }

        let mut previous: Option<EntityID> = None;
        for entity in &self.entities {
            if let Some(prev) = previous {
                if entity.entity_id <= prev {
                    return Err(format!(
                        "SnapshotPayload entities must be sorted and unique: found {} after {}",
                        entity.entity_id, prev
                    ));
                }
            }
            previous = Some(entity.entity_id);
            entity.validate()?;
        }
        Ok(())
    }
}

fn normalize_tags(mut tags: Vec<String>) -> Vec<String> {
    tags.retain(|tag| !tag.trim().is_empty());
    tags.sort();
    tags.dedup();
    tags
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

    const TEST_CGS_HASH: &str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    const TEST_WORLD_HASH: &str =
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

    fn test_snapshot() -> SnapshotPayload {
        SnapshotPayload::new(
            100,
            "0.1.0",
            1,
            TEST_CGS_HASH,
            TEST_WORLD_HASH,
            50,
            SnapshotReason::InitialConnection,
        )
    }

    #[test]
    fn add_entity_maintains_sort_order_and_replaces_duplicates() {
        let mut snap = test_snapshot();
        snap.add_entity(SnapshotEntityRecord::new(5, EntityState::Active));
        snap.add_entity(SnapshotEntityRecord::new(1, EntityState::Active));
        snap.add_entity(SnapshotEntityRecord::new(3, EntityState::Disabled));
        snap.add_entity(
            SnapshotEntityRecord::new(3, EntityState::Active).with_tags(vec!["player".into()]),
        );

        assert_eq!(
            snap.entities
                .iter()
                .map(|e| e.entity_id)
                .collect::<Vec<_>>(),
            vec![1, 3, 5]
        );
        assert!(snap.get_entity(3).unwrap().has_tag("player"));
        assert!(snap.validate().is_ok());
    }

    #[test]
    fn try_add_entity_rejects_duplicates() {
        let mut snap = test_snapshot();
        snap.try_add_entity(SnapshotEntityRecord::new(1, EntityState::Active))
            .unwrap();
        assert!(snap
            .try_add_entity(SnapshotEntityRecord::new(1, EntityState::Disabled))
            .is_err());
    }

    #[test]
    fn component_operations_are_deterministic() {
        let mut entity = SnapshotEntityRecord::new(1, EntityState::Active);
        entity.add_component(SnapshotComponentRecord::new(5, "COMP_VELOCITY_V1", "{}"));
        entity.add_component(SnapshotComponentRecord::new(1, "COMP_TRANSFORM_V1", "{}"));

        assert_eq!(
            entity.components.keys().copied().collect::<Vec<_>>(),
            vec![1, 5]
        );
        assert!(entity.has_component(1));
        assert_eq!(entity.component_count(), 2);
        assert!(entity.validate().is_ok());
    }

    #[test]
    fn validation_catches_unsorted_entities_and_invalid_component_json() {
        let mut snap = test_snapshot();
        snap.entities
            .push(SnapshotEntityRecord::new(5, EntityState::Active));
        snap.entities
            .push(SnapshotEntityRecord::new(2, EntityState::Active));
        assert!(snap.validate().is_err());

        let mut entity = SnapshotEntityRecord::new(1, EntityState::Active);
        entity.add_component(SnapshotComponentRecord::new(
            1,
            "COMP_TRANSFORM_V1",
            "not-json",
        ));
        assert!(entity.validate().is_err());
    }

    #[test]
    fn validation_rejects_null_and_removed_entities() {
        assert!(
            SnapshotEntityRecord::new(NULL_ENTITY_ID, EntityState::Active)
                .validate()
                .is_err()
        );
        assert!(SnapshotEntityRecord::new(1, EntityState::Archived)
            .validate()
            .is_err());
    }

    #[test]
    fn tags_are_normalized() {
        let entity = SnapshotEntityRecord::new(1, EntityState::Active).with_tags(vec![
            "zombie".into(),
            "".into(),
            "enemy".into(),
            "enemy".into(),
        ]);
        assert_eq!(entity.tags, vec!["enemy", "zombie"]);
        assert!(entity.validate().is_ok());
    }

    #[test]
    fn aggregate_counts_are_correct() {
        let mut snap = test_snapshot();
        let mut entity1 = SnapshotEntityRecord::new(1, EntityState::Active);
        entity1.add_component(SnapshotComponentRecord::new(1, "COMP_TRANSFORM_V1", "{}"));
        entity1.add_component(SnapshotComponentRecord::new(2, "COMP_IDENTITY_V1", "{}"));
        let mut entity2 = SnapshotEntityRecord::new(2, EntityState::Disabled);
        entity2.add_component(SnapshotComponentRecord::new(1, "COMP_TRANSFORM_V1", "{}"));
        snap.add_entity(entity1);
        snap.add_entity(entity2);

        assert_eq!(snap.entity_count(), 2);
        assert_eq!(snap.total_component_count(), 3);
        assert_eq!(snap.active_entities().len(), 1);
        assert!(snap.total_payload_bytes() > 0);
    }

    #[test]
    fn partial_marker_and_reason_display_work() {
        let mut snap = test_snapshot();
        assert!(snap.is_full);
        snap.mark_partial();
        assert!(!snap.is_full);
        assert_eq!(SnapshotReason::DesyncRecovery.to_string(), "DesyncRecovery");
    }
}
