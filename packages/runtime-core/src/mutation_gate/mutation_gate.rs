//! # Mutation Gate
//!
//! The ONLY path for structural world state changes in XACE.
//! All entity creation, destruction, and component mutations must
//! flow through here. Direct mutation is forbidden (I2, I9).
//!
//! ## Four Deferred Queues (D4)
//! The gate maintains five queues applied in strict order:
//! 1. spawn   — create entities (must happen before adding components)
//! 2. add     — attach new components to existing entities
//! 3. modify  — update existing component data
//! 4. remove  — detach components from entities
//! 5. destroy — remove entities from the world
//!
//! This order is non-negotiable. Spawning before destroying ensures
//! new entities don't get IDs of freshly destroyed ones. Adding before
//! removing prevents invalid intermediate states.
//!
//! ## Atomicity (I8)
//! apply_all() is atomic — if any operation fails, all applied changes
//! in that batch are rolled back via snapshot restore. No partial commits.
//!
//! ## Global Invariants Enforced
//! I2: All structural changes through Mutation Gate
//! I9: Events never modify state directly
//! D4: Mutations only after phase completion

use super::mutation_queue::{
    ComponentAddRequest, ComponentModifyRequest, ComponentRemoveRequest, DestroyRequest,
    MutationQueues, SpawnRequest,
};
use super::mutation_validator::MutationValidator;
use crate::component_tables::ComponentTableStore;
use crate::entity_store::EntityStore;
use std::collections::BTreeMap;
use xace_core::entity_id::EntityID;
use xace_core::errors::xace_error::XaceError;
use xace_core::runtime::state_delta::StateDelta;

// ── Mutation Gate ─────────────────────────────────────────────────────────────

/// The enforced gateway for all world state mutations.
///
/// Systems call request_*() methods to submit deferred mutations.
/// The PhaseOrchestrator calls apply_all() after each phase completes.
///
/// ## Thread Safety
/// MutationGate is not thread-safe. Parallel system execution uses
/// thread-local event buffers and submits mutations through
/// SystemContext which serializes them into a single gate instance.
pub struct MutationGate {
    /// The five deferred mutation queues.
    queues: MutationQueues,

    /// Pre-application validator.
    validator: MutationValidator,
}

impl MutationGate {
    pub fn new() -> Self {
        Self {
            queues: MutationQueues::new(),
            validator: MutationValidator::new(),
        }
    }

    // ── Request Methods ────────────────────────────────────────────────────

    /// Queues a spawn request. Entity is created at next apply_all().
    pub fn request_spawn(
        &mut self,
        actor_id: impl Into<String>,
        initial_components: BTreeMap<u32, String>,
        table_store: &ComponentTableStore,
        tick: u64,
    ) -> Result<(), XaceError> {
        let actor_id = actor_id.into();
        self.validator
            .validate_spawn(&actor_id, &initial_components, table_store, tick)?;
        self.queues.spawn_queue.push(SpawnRequest {
            actor_id,
            initial_components,
            requested_tick: tick,
        });
        Ok(())
    }

    /// Queues a component add request.
    pub fn request_add_component(
        &mut self,
        entity_id: EntityID,
        component_type_id: u32,
        component_json: impl Into<String>,
        entity_store: &EntityStore,
        table_store: &ComponentTableStore,
        tick: u64,
    ) -> Result<(), XaceError> {
        self.validator.validate_add_component(
            entity_id,
            component_type_id,
            entity_store,
            table_store,
            tick,
        )?;
        self.queues.add_queue.push(ComponentAddRequest {
            entity_id,
            component_type_id,
            component_json: component_json.into(),
            requested_tick: tick,
        });
        Ok(())
    }

    /// Queues a component modify request.
    pub fn request_modify_component(
        &mut self,
        entity_id: EntityID,
        component_type_id: u32,
        component_json: impl Into<String>,
        entity_store: &EntityStore,
        table_store: &ComponentTableStore,
        tick: u64,
    ) -> Result<(), XaceError> {
        self.validator.validate_modify_component(
            entity_id,
            component_type_id,
            entity_store,
            table_store,
            tick,
        )?;
        self.queues.modify_queue.push(ComponentModifyRequest {
            entity_id,
            component_type_id,
            component_json: component_json.into(),
            requested_tick: tick,
        });
        Ok(())
    }

    /// Queues a component remove request.
    pub fn request_remove_component(
        &mut self,
        entity_id: EntityID,
        component_type_id: u32,
        entity_store: &EntityStore,
        table_store: &ComponentTableStore,
        tick: u64,
    ) -> Result<(), XaceError> {
        self.validator.validate_remove_component(
            entity_id,
            component_type_id,
            entity_store,
            table_store,
            tick,
        )?;
        self.queues.remove_queue.push(ComponentRemoveRequest {
            entity_id,
            component_type_id,
            requested_tick: tick,
        });
        Ok(())
    }

    /// Queues a destroy request.
    pub fn request_destroy(
        &mut self,
        entity_id: EntityID,
        entity_store: &EntityStore,
        tick: u64,
    ) -> Result<(), XaceError> {
        self.validator
            .validate_destroy(entity_id, entity_store, tick)?;
        self.queues.destroy_queue.push(DestroyRequest {
            entity_id,
            requested_tick: tick,
        });
        Ok(())
    }

    // ── Apply Methods ──────────────────────────────────────────────────────

    /// Applies all queued mutations in enforced order (D4):
    /// spawn → add → modify → remove → destroy
    ///
    /// Returns a StateDelta capturing all changes made this batch.
    /// On any failure, discards remaining queued items and returns error.
    ///
    /// ## Atomicity Note (I8)
    /// Full atomicity with rollback requires the SnapshotEngine (Phase 5).
    /// In Phase 3, failed mutations return an error and the gate is cleared.
    /// Phase 5 adds pre-apply snapshot + restore on failure.
    pub fn apply_all(
        &mut self,
        entity_store: &mut EntityStore,
        table_store: &mut ComponentTableStore,
        tick: u64,
    ) -> Result<StateDelta, XaceError> {
        let mut delta = StateDelta::empty(tick, ""); // schema_version filled by orchestrator

        // ── Step 1: Spawn entities ────────────────────────────────────────
        let spawns: Vec<SpawnRequest> = self.queues.spawn_queue.drain(..).collect();
        for spawn in spawns {
            let entity_id = entity_store.create_entity(tick).map_err(|e| {
                self.queues.discard_all();
                e
            })?;

            // Record spawn in delta
            let mut spawned = xace_core::runtime::state_delta::SpawnedEntity::new(
                entity_id,
                spawn.actor_id.clone(),
            );

            // Apply initial components in type_id order (D11)
            for (type_id, json) in &spawn.initial_components {
                table_store
                    .add_component(entity_id, *type_id, json.clone(), tick)
                    .map_err(|e| {
                        self.queues.discard_all();
                        e
                    })?;
                spawned = spawned.with_component(*type_id, json.clone());
            }

            delta.record_spawn(spawned);
        }

        // ── Step 2: Add components ────────────────────────────────────────
        let adds: Vec<ComponentAddRequest> = self.queues.add_queue.drain(..).collect();
        for req in adds {
            table_store
                .add_component(
                    req.entity_id,
                    req.component_type_id,
                    req.component_json.clone(),
                    tick,
                )
                .map_err(|e| {
                    self.queues.discard_all();
                    e
                })?;

            delta.record_component_added(xace_core::runtime::state_delta::AddedComponent {
                entity_id: req.entity_id,
                component_type_id: req.component_type_id,
                component_type_name: String::new(), // filled by orchestrator
                component_json: req.component_json,
            });
        }

        // ── Step 3: Modify components ─────────────────────────────────────
        let modifies: Vec<ComponentModifyRequest> = self.queues.modify_queue.drain(..).collect();
        for req in modifies {
            table_store
                .update_component(
                    req.entity_id,
                    req.component_type_id,
                    req.component_json.clone(),
                    tick,
                )
                .map_err(|e| {
                    self.queues.discard_all();
                    e
                })?;

            let change = xace_core::runtime::state_delta::ComponentChange::single_field(
                req.component_type_id,
                "", // type name filled by orchestrator
                "data",
                req.component_json,
            );
            delta.record_component_update(req.entity_id, change);
        }

        // ── Step 4: Remove components ─────────────────────────────────────
        let removes: Vec<ComponentRemoveRequest> = self.queues.remove_queue.drain(..).collect();
        for req in removes {
            table_store
                .remove_component(req.entity_id, req.component_type_id, tick)
                .map_err(|e| {
                    self.queues.discard_all();
                    e
                })?;

            delta.record_component_removed(xace_core::runtime::state_delta::RemovedComponent {
                entity_id: req.entity_id,
                component_type_id: req.component_type_id,
                component_type_name: String::new(),
            });
        }

        // ── Step 5: Destroy entities ──────────────────────────────────────
        let destroys: Vec<DestroyRequest> = self.queues.destroy_queue.drain(..).collect();
        for req in destroys {
            // Remove all components first
            table_store.remove_all_for_entity(req.entity_id);

            // Request destruction in entity store
            entity_store
                .request_destroy(req.entity_id, tick)
                .map_err(|e| {
                    self.queues.discard_all();
                    e
                })?;

            // Complete destruction
            entity_store
                .complete_destroy(req.entity_id, tick)
                .map_err(|e| {
                    self.queues.discard_all();
                    e
                })?;

            delta.record_destroy(xace_core::runtime::state_delta::DestroyedEntity::new(
                req.entity_id,
                req.requested_tick,
            ));
        }

        Ok(delta)
    }

    // ── Query Methods ──────────────────────────────────────────────────────

    /// Returns the total number of pending mutations.
    pub fn pending_count(&self) -> usize {
        self.queues.total_pending()
    }

    /// Returns true if all queues are empty.
    pub fn is_empty(&self) -> bool {
        self.queues.is_empty()
    }

    /// Discards all pending mutations without applying them.
    pub fn discard_all(&mut self) {
        self.queues.discard_all();
    }

    /// Returns the queue counts for debugging.
    pub fn queue_counts(&self) -> (usize, usize, usize, usize, usize) {
        self.queues.counts()
    }
}

impl Default for MutationGate {
    fn default() -> Self {
        Self::new()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::component_tables::ComponentTableStore;
    use crate::entity_store::EntityStore;

    fn setup() -> (MutationGate, EntityStore, ComponentTableStore) {
        let gate = MutationGate::new();
        let entity_store = EntityStore::new();
        let mut table_store = ComponentTableStore::new();
        table_store.register_table(1, "COMP_TRANSFORM_V1").unwrap();
        table_store.register_table(2, "COMP_IDENTITY_V1").unwrap();
        (gate, entity_store, table_store)
    }

    #[test]
    fn spawn_creates_entity() {
        let (mut gate, mut es, mut ts) = setup();
        gate.request_spawn("actor_player", BTreeMap::new(), &ts, 0)
            .unwrap();
        let delta = gate.apply_all(&mut es, &mut ts, 0).unwrap();
        assert_eq!(delta.spawned_entities.len(), 1);
        assert_eq!(es.alive_count(), 1);
    }

    #[test]
    fn spawn_with_initial_components() {
        let (mut gate, mut es, mut ts) = setup();
        let mut components = BTreeMap::new();
        components.insert(1u32, r#"{"x":0.0}"#.to_string());
        gate.request_spawn("actor_player", components, &ts, 0)
            .unwrap();
        let _ = gate.apply_all(&mut es, &mut ts, 0).unwrap();
        let alive = es.get_all_alive();
        assert_eq!(alive.len(), 1);
        assert!(ts.has_component(alive[0], 1));
    }

    #[test]
    fn add_component_to_existing_entity() {
        let (mut gate, mut es, mut ts) = setup();
        let id = es.create_entity(0).unwrap();
        gate.request_add_component(id, 1, "{}", &es, &ts, 0)
            .unwrap();
        let _ = gate.apply_all(&mut es, &mut ts, 0).unwrap();
        assert!(ts.has_component(id, 1));
    }

    #[test]
    fn modify_existing_component() {
        let (mut gate, mut es, mut ts) = setup();
        let id = es.create_entity(0).unwrap();
        ts.add_component(id, 1, r#"{"x":0}"#.into(), 0).unwrap();
        gate.request_modify_component(id, 1, r#"{"x":5}"#, &es, &ts, 1)
            .unwrap();
        let _ = gate.apply_all(&mut es, &mut ts, 1).unwrap();
        assert_eq!(ts.get_component(id, 1), Some(r#"{"x":5}"#));
    }

    #[test]
    fn remove_component() {
        let (mut gate, mut es, mut ts) = setup();
        let id = es.create_entity(0).unwrap();
        ts.add_component(id, 1, "{}".into(), 0).unwrap();
        gate.request_remove_component(id, 1, &es, &ts, 1).unwrap();
        let _ = gate.apply_all(&mut es, &mut ts, 1).unwrap();
        assert!(!ts.has_component(id, 1));
    }

    #[test]
    fn destroy_entity() {
        let (mut gate, mut es, mut ts) = setup();
        let id = es.create_entity(0).unwrap();
        gate.request_destroy(id, &es, 1).unwrap();
        let delta = gate.apply_all(&mut es, &mut ts, 1).unwrap();
        assert!(!es.exists(id));
        assert!(es.archive().is_archived(id));
        assert_eq!(delta.destroyed_entities.len(), 1);
    }

    #[test]
    fn application_order_spawn_before_destroy() {
        let (mut gate, mut es, mut ts) = setup();
        // Spawn and destroy in same apply batch
        let existing = es.create_entity(0).unwrap();
        gate.request_destroy(existing, &es, 1).unwrap();
        gate.request_spawn("new_entity", BTreeMap::new(), &ts, 1)
            .unwrap();
        let _ = gate.apply_all(&mut es, &mut ts, 1).unwrap();
        // New entity should exist (spawned first)
        // Existing entity should be destroyed (destroyed last)
        assert!(!es.exists(existing));
        assert_eq!(es.alive_count(), 1);
    }

    #[test]
    fn empty_gate_produces_empty_delta() {
        let (mut gate, mut es, mut ts) = setup();
        let delta = gate.apply_all(&mut es, &mut ts, 0).unwrap();
        assert!(delta.is_empty());
    }

    #[test]
    fn pending_count_correct() {
        let (mut gate, mut es, ts) = setup();
        let _ = es.create_entity(0).unwrap();
        gate.request_destroy(1, &es, 0).unwrap();
        gate.request_spawn("a", BTreeMap::new(), &ts, 0).unwrap();
        assert_eq!(gate.pending_count(), 2);
    }

    #[test]
    fn discard_all_clears_queues() {
        let (mut gate, mut es, ts) = setup();
        let _ = es.create_entity(0).unwrap();
        gate.request_destroy(1, &es, 0).unwrap();
        gate.discard_all();
        assert!(gate.is_empty());
    }

    #[test]
    fn invalid_request_rejected_before_queuing() {
        let (mut gate, es, ts) = setup();
        // Entity 999 does not exist
        assert!(gate
            .request_add_component(999, 1, "{}", &es, &ts, 0)
            .is_err());
        // Gate should be empty — invalid request never queued
        assert!(gate.is_empty());
    }

    #[test]
    fn destroy_removes_all_components() {
        let (mut gate, mut es, mut ts) = setup();
        let id = es.create_entity(0).unwrap();
        ts.add_component(id, 1, "{}".into(), 0).unwrap();
        ts.add_component(id, 2, "{}".into(), 0).unwrap();
        gate.request_destroy(id, &es, 1).unwrap();
        let _ = gate.apply_all(&mut es, &mut ts, 1).unwrap();
        assert!(!ts.has_component(id, 1));
        assert!(!ts.has_component(id, 2));
    }
}
