//! # Snapshot Payload
//!
//! The wire-format payload for SNAPSHOT messages sent from XACE to the
//! engine adapter. Contains the complete world state needed for the
//! engine to fully reconstruct its scene from scratch.
//!
//! ## When SNAPSHOT is Sent
//! XACE sends a SNAPSHOT message to the engine adapter in three cases:
//! 1. Initial connection — engine has no world state yet
//! 2. Desync recovery — engine detected a sequence gap in DELTA messages
//! 3. Explicit SNAPSHOT request — engine sent a CONTROL/request_snapshot
//!
//! ## Relationship to WorldSnapshot
//! WorldSnapshot (runtime/world_snapshot.rs) is the authoritative
//! internal runtime state — it includes RNG state, mutation queue,
//! event queue, and everything needed for deterministic replay.
//!
//! SnapshotPayload is the wire-format subset — it contains only what
//! the engine adapter needs to reconstruct its visual scene:
//! - All entity IDs and their states
//! - All component data for all entities
//! - The current schema and plan versions for validation
//!
//! The engine adapter never needs RNG state, event queues, or
//! mutation queues — those are internal runtime concerns only.
//!
//! ## Full vs Partial Snapshots
//! A full snapshot (is_full = true) contains ALL entities and components.
//! A partial snapshot (is_full = false) contains only a specific subset —
//! used for late-join in multiplayer where not all entities are relevant
//! to the joining peer (interest management, Phase 15).
//!
//! ## Determinism
//! Entity records are sorted by EntityID ASC (D3).
//! Components within each entity are sorted by type_id ASC (D11).
//! Identical world state always produces identical SnapshotPayload bytes.

use std::collections::BTreeMap;
use serde::{Deserialize, Serialize};
use crate::entity_id::EntityID;
use crate::entity_state::EntityState;
use crate::entity_metadata::Tick;

// ── Snapshot Entity Record ────────────────────────────────────────────────────

/// A single entity's complete state in the snapshot.
///
/// Contains the entity's lifecycle state and all its component data.
/// Components are stored as a BTreeMap for deterministic type_id
/// ascending iteration order (D11).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SnapshotEntityRecord {
    /// The entity's unique ID.
    pub entity_id: EntityID,

    /// The entity's current lifecycle state.
    /// Engine adapter only receives Active and Disabled entities —
    /// Destroyed and Archived entities are never included.
    pub state: EntityState,

    /// All component data for this entity.
    /// BTreeMap<component_type_id, component_json>
    /// Sorted by component_type_id ASC for determinism (D11).
    pub components: BTreeMap<u32, SnapshotComponentRecord>,

    /// Sorted tags from COMP_IDENTITY_V1.
    /// Included for quick engine-side entity classification.
    pub tags: Vec<String>,
}

impl SnapshotEntityRecord {
    /// Creates a new entity record with no components.
    pub fn new(entity_id: EntityID, state: EntityState) -> Self {
        Self {
            entity_id,
            state,
            components: BTreeMap::new(),
            tags: Vec::new(),
        }
    }

    /// Adds a component record to this entity.
    /// BTreeMap insertion maintains type_id ascending order (D11).
    pub fn add_component(&mut self, component: SnapshotComponentRecord) {
        self.components.insert(component.component_type_id, component);
    }

    /// Returns the component record for a specific type, if present.
    pub fn get_component(&self, type_id: u32) -> Option<&SnapshotComponentRecord> {
        self.components.get(&type_id)
    }

    /// Returns true if this entity has a component of the given type.
    pub fn has_component(&self, type_id: u32) -> bool {
        self.components.contains_key(&type_id)
    }

    /// Returns the number of components on this entity.
    pub fn component_count(&self) -> usize {
        self.components.len()
    }

    /// Returns true if this entity is currently active and visible.
    pub fn is_active(&self) -> bool {
        matches!(self.state, EntityState::Active)
    }
}

// ── Snapshot Component Record ─────────────────────────────────────────────────

/// A single component's complete data in the snapshot.
///
/// Includes the type ID, canonical name, and full JSON data.
/// The engine adapter uses the type name to look up its engine-side
/// component handler and deserialize the JSON into engine types.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SnapshotComponentRecord {
    /// The component type ID from the UCL/DCL/GCL registry.
    pub component_type_id: u32,

    /// The canonical component type name for engine-side lookup.
    /// Example: "COMP_TRANSFORM_V1", "COMP_HEALTH_V1"
    pub component_type_name: String,

    /// Complete component data serialized as JSON.
    /// JSON keys are sorted alphabetically for determinism (D11).
    /// The engine adapter deserializes this into its engine type.
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
}

// ── Snapshot Payload ──────────────────────────────────────────────────────────

/// The complete wire payload for a SNAPSHOT message.
///
/// Contains the full world state needed for the engine adapter to
/// reconstruct its scene from scratch. Sent on initial connection,
/// desync recovery, or explicit snapshot request.
///
/// ## Entity Inclusion Rules
/// Only Active and Disabled entities are included in snapshots.
/// DestroyRequested, Destroyed, and Archived entities are excluded —
/// the engine adapter has no use for entities that no longer exist.
///
/// ## Component Inclusion Rules
/// All registered components for each entity are included.
/// This includes all UCL Core components and any DCL/GCL components
/// that are registered on this entity.
///
/// ## Validation
/// The engine adapter validates schema_version and plan_version
/// match its configured versions before applying the snapshot.
/// Version mismatch causes the engine to request reconnection
/// rather than applying a potentially incompatible snapshot.
///
/// ## Sequence Reset
/// After receiving a SNAPSHOT, the engine adapter resets its
/// sequence_id tracking to last_delta_sequence_id + 1.
/// All subsequent DELTA messages use the new sequence baseline.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SnapshotPayload {
    /// The simulation tick this snapshot represents.
    pub tick: Tick,

    /// The CGS semantic version active at this tick.
    /// Engine adapter validates this before applying.
    pub schema_version: String,

    /// The ExecutionPlan version active at this tick.
    /// Engine adapter validates this before applying.
    pub execution_plan_version: u32,

    /// The CGS hash for integrity verification.
    pub cgs_hash: String,

    /// The world_hash of the snapshot for determinism validation (D9).
    /// Engine adapter cannot verify this directly but records it
    /// for debugging and desync detection.
    pub world_hash: String,

    /// The last DELTA sequence_id before this snapshot.
    /// Engine adapter uses this to reset sequence tracking.
    pub last_delta_sequence_id: u64,

    /// Whether this is a full snapshot (all entities) or partial.
    /// Partial snapshots are used for late-join interest management (Phase 15).
    pub is_full: bool,

    /// All entity records sorted by EntityID ASC (D3).
    /// Only Active and Disabled entities are included.
    pub entities: Vec<SnapshotEntityRecord>,

    /// The reason this snapshot was sent.
    /// Used for logging and debugging.
    pub reason: SnapshotReason,
}

// ── Snapshot Reason ───────────────────────────────────────────────────────────

/// Why this snapshot was sent to the engine adapter.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum SnapshotReason {
    /// Engine adapter just connected — needs full world state.
    InitialConnection,

    /// Engine adapter detected a sequence gap in DELTA messages.
    /// One or more DELTA messages were dropped or arrived out of order.
    DesyncRecovery,

    /// Engine adapter explicitly requested a snapshot via CONTROL message.
    ExplicitRequest,

    /// Periodic snapshot for network stability (Phase 15).
    /// Sent every N ticks to prevent drift in long sessions.
    PeriodicRefresh,
}

impl std::fmt::Display for SnapshotReason {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            SnapshotReason::InitialConnection => write!(f, "InitialConnection"),
            SnapshotReason::DesyncRecovery => write!(f, "DesyncRecovery"),
            SnapshotReason::ExplicitRequest => write!(f, "ExplicitRequest"),
            SnapshotReason::PeriodicRefresh => write!(f, "PeriodicRefresh"),
        }
    }
}

impl SnapshotPayload {
    /// Creates a new snapshot payload.
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

    /// Adds an entity record maintaining EntityID sort order (D3).
    /// Only Active and Disabled entities should be added.
    pub fn add_entity(&mut self, entity: SnapshotEntityRecord) {
        let pos = self.entities
            .partition_point(|e| e.entity_id < entity.entity_id);
        self.entities.insert(pos, entity);
    }

    /// Returns the entity record for a specific EntityID, if present.
    pub fn get_entity(&self, entity_id: EntityID) -> Option<&SnapshotEntityRecord> {
        self.entities
            .binary_search_by(|e| e.entity_id.cmp(&entity_id))
            .ok()
            .map(|idx| &self.entities[idx])
    }

    /// Returns true if the snapshot contains a specific entity.
    pub fn contains_entity(&self, entity_id: EntityID) -> bool {
        self.entities
            .binary_search_by(|e| e.entity_id.cmp(&entity_id))
            .is_ok()
    }

    /// Returns the total number of entities in this snapshot.
    pub fn entity_count(&self) -> usize {
        self.entities.len()
    }

    /// Returns the total number of component instances across all entities.
    pub fn total_component_count(&self) -> usize {
        self.entities.iter().map(|e| e.component_count()).sum()
    }

    /// Returns true if this snapshot contains no entities.
    pub fn is_empty(&self) -> bool {
        self.entities.is_empty()
    }

    /// Returns all active entities in this snapshot.
    pub fn active_entities(&self) -> Vec<&SnapshotEntityRecord> {
        self.entities.iter().filter(|e| e.is_active()).collect()
    }

    /// Validates this snapshot payload for structural correctness.
    ///
    /// Checks:
    /// - schema_version is not empty
    /// - execution_plan_version >= 1
    /// - world_hash is not empty
    /// - Entity IDs are sorted ascending (D3)
    /// - No duplicate entity IDs
    pub fn validate(&self) -> Result<(), String> {
        if self.schema_version.is_empty() {
            return Err(
                "SnapshotPayload schema_version must not be empty".into()
            );
        }

        if self.execution_plan_version == 0 {
            return Err(
                "SnapshotPayload execution_plan_version must be >= 1".into()
            );
        }

        if self.world_hash.is_empty() {
            return Err("SnapshotPayload world_hash must not be empty".into());
        }

        // Verify entity IDs are sorted and unique (D3)
        let mut prev_id: Option<EntityID> = None;
        for entity in &self.entities {
            if let Some(prev) = prev_id {
                if entity.entity_id <= prev {
                    return Err(format!(
                        "SnapshotPayload entities not sorted by EntityID ASC — \
                         found {} after {} (D3)",
                        entity.entity_id, prev
                    ));
                }
            }
            prev_id = Some(entity.entity_id);
        }

        Ok(())
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn test_snapshot() -> SnapshotPayload {
        SnapshotPayload::new(
            100,
            "0.1.0",
            1,
            "cgs_hash_abc",
            "world_hash_xyz",
            50,
            SnapshotReason::InitialConnection,
        )
    }

    #[test]
    fn new_snapshot_is_empty() {
        assert!(test_snapshot().is_empty());
        assert_eq!(test_snapshot().entity_count(), 0);
    }

    #[test]
    fn new_snapshot_is_full() {
        assert!(test_snapshot().is_full);
    }

    #[test]
    fn add_entity_maintains_sort_order() {
        let mut snap = test_snapshot();
        snap.add_entity(SnapshotEntityRecord::new(5, EntityState::Active));
        snap.add_entity(SnapshotEntityRecord::new(1, EntityState::Active));
        snap.add_entity(SnapshotEntityRecord::new(3, EntityState::Disabled));
        assert_eq!(snap.entities[0].entity_id, 1);
        assert_eq!(snap.entities[1].entity_id, 3);
        assert_eq!(snap.entities[2].entity_id, 5);
    }

    #[test]
    fn get_entity_finds_correct_record() {
        let mut snap = test_snapshot();
        snap.add_entity(SnapshotEntityRecord::new(1, EntityState::Active));
        snap.add_entity(SnapshotEntityRecord::new(3, EntityState::Active));
        let entity = snap.get_entity(3);
        assert!(entity.is_some());
        assert_eq!(entity.unwrap().entity_id, 3);
    }

    #[test]
    fn get_entity_returns_none_for_missing() {
        let snap = test_snapshot();
        assert!(snap.get_entity(999).is_none());
    }

    #[test]
    fn contains_entity_correct() {
        let mut snap = test_snapshot();
        snap.add_entity(SnapshotEntityRecord::new(1, EntityState::Active));
        assert!(snap.contains_entity(1));
        assert!(!snap.contains_entity(2));
    }

    #[test]
    fn total_component_count_sums_correctly() {
        let mut snap = test_snapshot();
        let mut entity1 = SnapshotEntityRecord::new(1, EntityState::Active);
        entity1.add_component(SnapshotComponentRecord::new(
            1, "COMP_TRANSFORM_V1", "{}"
        ));
        entity1.add_component(SnapshotComponentRecord::new(
            2, "COMP_IDENTITY_V1", "{}"
        ));
        let mut entity2 = SnapshotEntityRecord::new(2, EntityState::Active);
        entity2.add_component(SnapshotComponentRecord::new(
            1, "COMP_TRANSFORM_V1", "{}"
        ));
        snap.add_entity(entity1);
        snap.add_entity(entity2);
        assert_eq!(snap.total_component_count(), 3);
    }

    #[test]
    fn active_entities_filters_correctly() {
        let mut snap = test_snapshot();
        snap.add_entity(SnapshotEntityRecord::new(1, EntityState::Active));
        snap.add_entity(SnapshotEntityRecord::new(2, EntityState::Disabled));
        snap.add_entity(SnapshotEntityRecord::new(3, EntityState::Active));
        let active = snap.active_entities();
        assert_eq!(active.len(), 2);
        assert_eq!(active[0].entity_id, 1);
        assert_eq!(active[1].entity_id, 3);
    }

    #[test]
    fn validate_passes_for_valid_snapshot() {
        let snap = test_snapshot();
        assert!(snap.validate().is_ok());
    }

    #[test]
    fn validate_fails_for_empty_schema_version() {
        let mut snap = test_snapshot();
        snap.schema_version = String::new();
        assert!(snap.validate().is_err());
    }

    #[test]
    fn validate_fails_for_zero_plan_version() {
        let mut snap = test_snapshot();
        snap.execution_plan_version = 0;
        assert!(snap.validate().is_err());
    }

    #[test]
    fn validate_fails_for_empty_world_hash() {
        let mut snap = test_snapshot();
        snap.world_hash = String::new();
        assert!(snap.validate().is_err());
    }

    #[test]
    fn validate_fails_for_unsorted_entities() {
        let mut snap = test_snapshot();
        // Force unsorted insertion bypassing add_entity
        snap.entities.push(SnapshotEntityRecord::new(5, EntityState::Active));
        snap.entities.push(SnapshotEntityRecord::new(2, EntityState::Active));
        assert!(snap.validate().is_err());
    }

    #[test]
    fn entity_record_component_operations() {
        let mut entity = SnapshotEntityRecord::new(1, EntityState::Active);
        entity.add_component(SnapshotComponentRecord::new(
            1, "COMP_TRANSFORM_V1", r#"{"position":{"x":0}}"#
        ));
        assert!(entity.has_component(1));
        assert!(!entity.has_component(99));
        assert_eq!(entity.component_count(), 1);
        let comp = entity.get_component(1).unwrap();
        assert_eq!(comp.component_type_name, "COMP_TRANSFORM_V1");
    }

    #[test]
    fn entity_is_active_detection() {
        let active = SnapshotEntityRecord::new(1, EntityState::Active);
        let disabled = SnapshotEntityRecord::new(2, EntityState::Disabled);
        assert!(active.is_active());
        assert!(!disabled.is_active());
    }

    #[test]
    fn snapshot_reason_display() {
        assert_eq!(
            SnapshotReason::InitialConnection.to_string(),
            "InitialConnection"
        );
        assert_eq!(
            SnapshotReason::DesyncRecovery.to_string(),
            "DesyncRecovery"
        );
    }

    #[test]
    fn snapshot_tick_stored_correctly() {
        let snap = test_snapshot();
        assert_eq!(snap.tick, 100);
    }

    #[test]
    fn last_delta_sequence_stored_correctly() {
        let snap = test_snapshot();
        assert_eq!(snap.last_delta_sequence_id, 50);
    }

    #[test]
    fn component_record_data_preserved() {
        let comp = SnapshotComponentRecord::new(
            1,
            "COMP_TRANSFORM_V1",
            r#"{"position":{"x":1.0,"y":2.0,"z":3.0}}"#,
        );
        assert_eq!(comp.component_type_id, 1);
        assert!(comp.data_json.contains("position"));
    }
}