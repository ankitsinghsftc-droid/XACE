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
//! ## Atomic Failure Contract (I8)
//! apply_all() captures a pre-batch rollback image before applying any queued
//! operation. On any apply-time failure, it restores entity/component/queue
//! state exactly, restores optional event/RNG state when the orchestrator
//! provides it, verifies the post-rollback world hash equals the pre-batch hash,
//! and returns structured diagnostics for the failing operation.
//! Nested or concurrent apply transactions are explicitly rejected until the
//! runtime has a proven multi-transaction design.
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
use crate::determinism_guard::rng_interceptor::{RngInterceptor, RngInterceptorSnapshot};
use crate::entity_store::EntityStore;
use crate::event_bus::event_bus::{EventBus, EventBusRollbackSnapshot};
use crate::snapshot_engine::SnapshotEngine;
use std::collections::BTreeMap;
use xace_core::entity_id::EntityID;
use xace_core::errors::xace_error::{ErrorContext, XaceError};
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

    /// Most recent apply-time failure diagnostic.
    last_failure_diagnostic: Option<MutationApplyFailureDiagnostic>,

    /// True while apply_all() owns a rollback transaction.
    transaction_in_progress: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum MutationRollbackStatus {
    Restored,
    HashMismatch {
        pre_batch_hash: String,
        post_rollback_hash: String,
    },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MutationApplyFailureDiagnostic {
    pub failing_operation_index: usize,
    pub operation_type: String,
    pub entity_id: Option<EntityID>,
    pub component_type_id: Option<u32>,
    pub path: String,
    pub rollback_status: MutationRollbackStatus,
    pub source_error: String,
}

#[derive(Clone)]
struct MutationOperationInfo {
    index: usize,
    operation_type: &'static str,
    entity_id: Option<EntityID>,
    component_type_id: Option<u32>,
    path: String,
}

struct MutationGateRollbackSnapshot {
    entity_store: crate::entity_store::entity_store::EntityStoreRollbackSnapshot,
    table_store:
        crate::component_tables::component_table_store::ComponentTableStoreRollbackSnapshot,
    queues: MutationQueues,
    event_bus: Option<EventBusRollbackSnapshot>,
    rng_interceptor: Option<RngInterceptorSnapshot>,
    pre_batch_hash: String,
}

impl MutationOperationInfo {
    fn new(
        index: usize,
        operation_type: &'static str,
        entity_id: Option<EntityID>,
        component_type_id: Option<u32>,
        path: String,
    ) -> Self {
        Self {
            index,
            operation_type,
            entity_id,
            component_type_id,
            path,
        }
    }
}

impl MutationGate {
    pub fn new() -> Self {
        Self {
            queues: MutationQueues::new(),
            validator: MutationValidator::new(),
            last_failure_diagnostic: None,
            transaction_in_progress: false,
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
    /// On any failure, restores the pre-batch rollback image and returns
    /// diagnostics describing the failed operation and rollback result.
    pub fn apply_all(
        &mut self,
        entity_store: &mut EntityStore,
        table_store: &mut ComponentTableStore,
        tick: u64,
    ) -> Result<StateDelta, XaceError> {
        self.apply_all_transaction(entity_store, table_store, None, None, tick)
    }

    // ── Step 1: Spawn entities ────────────────────────────────────────
    // ── Step 2: Add components ────────────────────────────────────────
    // ── Step 3: Modify components ─────────────────────────────────────
    // ── Step 4: Remove components ─────────────────────────────────────
    // ── Step 5: Destroy entities ──────────────────────────────────────
    /// Applies queued mutations with optional runtime state included in the
    /// rollback transaction.
    pub fn apply_all_with_runtime_state(
        &mut self,
        entity_store: &mut EntityStore,
        table_store: &mut ComponentTableStore,
        event_bus: Option<&mut EventBus>,
        rng_interceptor: Option<&RngInterceptor>,
        tick: u64,
    ) -> Result<StateDelta, XaceError> {
        self.apply_all_transaction(entity_store, table_store, event_bus, rng_interceptor, tick)
    }

    fn apply_all_transaction(
        &mut self,
        entity_store: &mut EntityStore,
        table_store: &mut ComponentTableStore,
        mut event_bus: Option<&mut EventBus>,
        rng_interceptor: Option<&RngInterceptor>,
        tick: u64,
    ) -> Result<StateDelta, XaceError> {
        if self.transaction_in_progress {
            return Err(Self::nested_transaction_error(tick));
        }
        self.transaction_in_progress = true;

        let rollback_snapshot = match self.capture_rollback_snapshot(
            entity_store,
            table_store,
            event_bus.as_deref(),
            rng_interceptor,
            tick,
        ) {
            Ok(snapshot) => snapshot,
            Err(error) => {
                self.transaction_in_progress = false;
                return Err(error);
            }
        };
        let mut delta = StateDelta::empty(tick, "");
        let mut operation_index = 0usize;

        let spawns: Vec<SpawnRequest> = self.queues.spawn_queue.drain(..).collect();
        for spawn in spawns {
            let op = MutationOperationInfo::new(
                operation_index,
                "spawn",
                None,
                None,
                format!("spawn.actor:{}", spawn.actor_id),
            );
            operation_index += 1;
            let entity_id = match entity_store.create_entity(tick) {
                Ok(entity_id) => entity_id,
                Err(error) => {
                    return Err(self.rollback_after_failure(
                        rollback_snapshot,
                        entity_store,
                        table_store,
                        event_bus.as_deref_mut(),
                        rng_interceptor,
                        op,
                        error,
                        tick,
                    ));
                }
            };

            let mut spawned = xace_core::runtime::state_delta::SpawnedEntity::new(
                entity_id,
                spawn.actor_id.clone(),
            );
            for (type_id, json) in &spawn.initial_components {
                let op = MutationOperationInfo::new(
                    operation_index,
                    "spawn.initial_component",
                    Some(entity_id),
                    Some(*type_id),
                    format!("entity:{}.component:{}", entity_id, type_id),
                );
                operation_index += 1;
                if let Err(error) = Self::validate_component_json(json, &op, tick) {
                    return Err(self.rollback_after_failure(
                        rollback_snapshot,
                        entity_store,
                        table_store,
                        event_bus.as_deref_mut(),
                        rng_interceptor,
                        op,
                        error,
                        tick,
                    ));
                }
                if let Err(error) =
                    table_store.add_component(entity_id, *type_id, json.clone(), tick)
                {
                    return Err(self.rollback_after_failure(
                        rollback_snapshot,
                        entity_store,
                        table_store,
                        event_bus.as_deref_mut(),
                        rng_interceptor,
                        op,
                        error,
                        tick,
                    ));
                }
                spawned = spawned.with_component(*type_id, json.clone());
            }
            delta.record_spawn(spawned);
        }

        let adds: Vec<ComponentAddRequest> = self.queues.add_queue.drain(..).collect();
        for req in adds {
            let op = MutationOperationInfo::new(
                operation_index,
                "add_component",
                Some(req.entity_id),
                Some(req.component_type_id),
                format!(
                    "entity:{}.component:{}",
                    req.entity_id, req.component_type_id
                ),
            );
            operation_index += 1;
            if let Err(error) = Self::validate_entity_present_for_apply(
                entity_store,
                req.entity_id,
                "add_component",
                tick,
            ) {
                return Err(self.rollback_after_failure(
                    rollback_snapshot,
                    entity_store,
                    table_store,
                    event_bus.as_deref_mut(),
                    rng_interceptor,
                    op,
                    error,
                    tick,
                ));
            }
            if let Err(error) = Self::validate_component_json(&req.component_json, &op, tick) {
                return Err(self.rollback_after_failure(
                    rollback_snapshot,
                    entity_store,
                    table_store,
                    event_bus.as_deref_mut(),
                    rng_interceptor,
                    op,
                    error,
                    tick,
                ));
            }
            if let Err(error) = table_store.add_component(
                req.entity_id,
                req.component_type_id,
                req.component_json.clone(),
                tick,
            ) {
                return Err(self.rollback_after_failure(
                    rollback_snapshot,
                    entity_store,
                    table_store,
                    event_bus.as_deref_mut(),
                    rng_interceptor,
                    op,
                    error,
                    tick,
                ));
            }

            delta.record_component_added(xace_core::runtime::state_delta::AddedComponent {
                entity_id: req.entity_id,
                component_type_id: req.component_type_id,
                component_type_name: String::new(),
                component_json: req.component_json,
            });
        }

        let modifies: Vec<ComponentModifyRequest> = self.queues.modify_queue.drain(..).collect();
        for req in modifies {
            let op = MutationOperationInfo::new(
                operation_index,
                "modify_component",
                Some(req.entity_id),
                Some(req.component_type_id),
                format!(
                    "entity:{}.component:{}",
                    req.entity_id, req.component_type_id
                ),
            );
            operation_index += 1;
            if let Err(error) = Self::validate_entity_present_for_apply(
                entity_store,
                req.entity_id,
                "modify_component",
                tick,
            ) {
                return Err(self.rollback_after_failure(
                    rollback_snapshot,
                    entity_store,
                    table_store,
                    event_bus.as_deref_mut(),
                    rng_interceptor,
                    op,
                    error,
                    tick,
                ));
            }
            if let Err(error) = Self::validate_component_json(&req.component_json, &op, tick) {
                return Err(self.rollback_after_failure(
                    rollback_snapshot,
                    entity_store,
                    table_store,
                    event_bus.as_deref_mut(),
                    rng_interceptor,
                    op,
                    error,
                    tick,
                ));
            }
            if let Err(error) = table_store.update_component(
                req.entity_id,
                req.component_type_id,
                req.component_json.clone(),
                tick,
            ) {
                return Err(self.rollback_after_failure(
                    rollback_snapshot,
                    entity_store,
                    table_store,
                    event_bus.as_deref_mut(),
                    rng_interceptor,
                    op,
                    error,
                    tick,
                ));
            }

            let change = xace_core::runtime::state_delta::ComponentChange::single_field(
                req.component_type_id,
                "",
                "data",
                req.component_json,
            );
            delta.record_component_update(req.entity_id, change);
        }

        let removes: Vec<ComponentRemoveRequest> = self.queues.remove_queue.drain(..).collect();
        for req in removes {
            let op = MutationOperationInfo::new(
                operation_index,
                "remove_component",
                Some(req.entity_id),
                Some(req.component_type_id),
                format!(
                    "entity:{}.component:{}",
                    req.entity_id, req.component_type_id
                ),
            );
            operation_index += 1;
            if let Err(error) = Self::validate_entity_present_for_apply(
                entity_store,
                req.entity_id,
                "remove_component",
                tick,
            ) {
                return Err(self.rollback_after_failure(
                    rollback_snapshot,
                    entity_store,
                    table_store,
                    event_bus.as_deref_mut(),
                    rng_interceptor,
                    op,
                    error,
                    tick,
                ));
            }
            if let Err(error) =
                table_store.remove_component(req.entity_id, req.component_type_id, tick)
            {
                return Err(self.rollback_after_failure(
                    rollback_snapshot,
                    entity_store,
                    table_store,
                    event_bus.as_deref_mut(),
                    rng_interceptor,
                    op,
                    error,
                    tick,
                ));
            }

            delta.record_component_removed(xace_core::runtime::state_delta::RemovedComponent {
                entity_id: req.entity_id,
                component_type_id: req.component_type_id,
                component_type_name: String::new(),
            });
        }

        let destroys: Vec<DestroyRequest> = self.queues.destroy_queue.drain(..).collect();
        for req in destroys {
            let op = MutationOperationInfo::new(
                operation_index,
                "destroy_entity",
                Some(req.entity_id),
                None,
                format!("entity:{}", req.entity_id),
            );
            operation_index += 1;

            if let Err(error) = Self::validate_entity_present_for_apply(
                entity_store,
                req.entity_id,
                "destroy_entity",
                tick,
            ) {
                return Err(self.rollback_after_failure(
                    rollback_snapshot,
                    entity_store,
                    table_store,
                    event_bus.as_deref_mut(),
                    rng_interceptor,
                    op,
                    error,
                    tick,
                ));
            }
            table_store.remove_all_for_entity(req.entity_id);
            if let Err(error) = entity_store.request_destroy(req.entity_id, tick) {
                return Err(self.rollback_after_failure(
                    rollback_snapshot,
                    entity_store,
                    table_store,
                    event_bus.as_deref_mut(),
                    rng_interceptor,
                    op,
                    error,
                    tick,
                ));
            }
            if let Err(error) = entity_store.complete_destroy(req.entity_id, tick) {
                return Err(self.rollback_after_failure(
                    rollback_snapshot,
                    entity_store,
                    table_store,
                    event_bus.as_deref_mut(),
                    rng_interceptor,
                    op,
                    error,
                    tick,
                ));
            }

            delta.record_destroy(xace_core::runtime::state_delta::DestroyedEntity::new(
                req.entity_id,
                req.requested_tick,
            ));
        }

        self.last_failure_diagnostic = None;
        self.transaction_in_progress = false;
        Ok(delta)
    }

    fn capture_rollback_snapshot(
        &self,
        entity_store: &EntityStore,
        table_store: &ComponentTableStore,
        event_bus: Option<&EventBus>,
        rng_interceptor: Option<&RngInterceptor>,
        tick: u64,
    ) -> Result<MutationGateRollbackSnapshot, XaceError> {
        Ok(MutationGateRollbackSnapshot {
            entity_store: entity_store.rollback_snapshot(),
            table_store: table_store.rollback_snapshot(),
            queues: self.queues.clone(),
            event_bus: event_bus.map(EventBus::rollback_snapshot),
            rng_interceptor: rng_interceptor.map(RngInterceptor::rollback_snapshot),
            pre_batch_hash: Self::compute_rollback_hash(entity_store, table_store, tick)?,
        })
    }

    fn rollback_after_failure(
        &mut self,
        snapshot: MutationGateRollbackSnapshot,
        entity_store: &mut EntityStore,
        table_store: &mut ComponentTableStore,
        event_bus: Option<&mut EventBus>,
        rng_interceptor: Option<&RngInterceptor>,
        operation: MutationOperationInfo,
        source_error: XaceError,
        tick: u64,
    ) -> XaceError {
        self.transaction_in_progress = false;
        let pre_batch_hash = snapshot.pre_batch_hash.clone();

        entity_store.restore_rollback_snapshot(snapshot.entity_store);
        table_store.restore_rollback_snapshot(snapshot.table_store);
        self.queues = snapshot.queues;
        if let (Some(event_bus), Some(event_snapshot)) = (event_bus, snapshot.event_bus) {
            event_bus.restore_rollback_snapshot(event_snapshot);
        }
        if let (Some(rng_interceptor), Some(rng_snapshot)) =
            (rng_interceptor, snapshot.rng_interceptor)
        {
            rng_interceptor.restore_rollback_snapshot(rng_snapshot);
        }

        let post_rollback_hash = Self::compute_rollback_hash(entity_store, table_store, tick)
            .unwrap_or_else(|_| "<hash-unavailable>".to_string());
        let rollback_status = if post_rollback_hash == pre_batch_hash {
            MutationRollbackStatus::Restored
        } else {
            MutationRollbackStatus::HashMismatch {
                pre_batch_hash: pre_batch_hash.clone(),
                post_rollback_hash: post_rollback_hash.clone(),
            }
        };

        let diagnostic = MutationApplyFailureDiagnostic {
            failing_operation_index: operation.index,
            operation_type: operation.operation_type.to_string(),
            entity_id: operation.entity_id,
            component_type_id: operation.component_type_id,
            path: operation.path.clone(),
            rollback_status: rollback_status.clone(),
            source_error: source_error.to_string(),
        };
        self.last_failure_diagnostic = Some(diagnostic.clone());

        let context = ErrorContext::new("MutationGate", "apply_all")
            .with_tick(tick)
            .with_detail("failing_operation_index", operation.index.to_string())
            .with_detail("operation_type", operation.operation_type)
            .with_detail("path", operation.path)
            .with_detail("rollback_status", format!("{:?}", rollback_status))
            .with_detail("source_error", source_error.to_string());

        match rollback_status {
            MutationRollbackStatus::Restored => XaceError::ValidationFailure {
                message: format!(
                    "Mutation batch failed at operation {} ({}) and was rolled back",
                    diagnostic.failing_operation_index, diagnostic.operation_type
                ),
                context,
                rule_violated: "I8".into(),
                failed_path: diagnostic.path,
            },
            MutationRollbackStatus::HashMismatch { .. } => XaceError::FatalError {
                message: format!(
                    "Mutation rollback hash mismatch after operation {} ({})",
                    diagnostic.failing_operation_index, diagnostic.operation_type
                ),
                context,
                snapshot_recovery_possible: true,
            },
        }
    }

    fn compute_rollback_hash(
        entity_store: &EntityStore,
        table_store: &ComponentTableStore,
        tick: u64,
    ) -> Result<String, XaceError> {
        let mut snapshot_engine = SnapshotEngine::standard("mutation-gate-atomicity", 0, 0);
        let snapshot = snapshot_engine.take_snapshot(tick, entity_store, table_store)?;
        Ok(snapshot.world_hash)
    }

    fn nested_transaction_error(tick: u64) -> XaceError {
        XaceError::ValidationFailure {
            message:
                "Nested or concurrent MutationGate transactions are forbidden until proven safe"
                    .into(),
            context: ErrorContext::new("MutationGate", "apply_all")
                .with_tick(tick)
                .with_detail("transaction_in_progress", "true"),
            rule_violated: "I8_nested_transaction_forbidden".into(),
            failed_path: "mutation_gate.transaction".into(),
        }
    }

    fn validate_entity_present_for_apply(
        entity_store: &EntityStore,
        entity_id: EntityID,
        operation: &'static str,
        tick: u64,
    ) -> Result<(), XaceError> {
        if entity_store.exists(entity_id) {
            return Ok(());
        }
        Err(XaceError::ValidationFailure {
            message: format!(
                "Entity {} is not present at MutationGate apply-time",
                entity_id
            ),
            context: ErrorContext::new("MutationGate", operation).with_tick(tick),
            rule_violated: "I1".into(),
            failed_path: format!("entity:{}", entity_id),
        })
    }

    fn validate_component_json(
        component_json: &str,
        operation: &MutationOperationInfo,
        tick: u64,
    ) -> Result<(), XaceError> {
        serde_json::from_str::<serde_json::Value>(component_json)
            .map(|_| ())
            .map_err(|error| XaceError::ValidationFailure {
                message: format!("Component payload is not valid JSON: {}", error),
                context: ErrorContext::new("MutationGate", operation.operation_type)
                    .with_tick(tick)
                    .with_detail("path", operation.path.clone()),
                rule_violated: "component_json_must_parse".into(),
                failed_path: operation.path.clone(),
            })
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

    /// Returns the most recent apply-time failure diagnostic, if any.
    pub fn last_failure_diagnostic(&self) -> Option<&MutationApplyFailureDiagnostic> {
        self.last_failure_diagnostic.as_ref()
    }

    /// Discards all pending mutations without applying them.
    pub fn discard_all(&mut self) {
        self.queues.discard_all();
    }

    /// Returns the queue counts for debugging.
    pub fn queue_counts(&self) -> (usize, usize, usize, usize, usize) {
        self.queues.counts()
    }

    /// Returns a clone of deferred queues for proof/testing serialization.
    pub fn queue_snapshot_for_proof(&self) -> MutationQueues {
        self.queues.clone()
    }

    #[cfg(test)]
    fn force_transaction_in_progress_for_test(&mut self) {
        self.transaction_in_progress = true;
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
    use crate::snapshot_engine::SnapshotEngine;

    fn setup() -> (MutationGate, EntityStore, ComponentTableStore) {
        let gate = MutationGate::new();
        let entity_store = EntityStore::new();
        let mut table_store = ComponentTableStore::new();
        table_store.register_table(1, "COMP_TRANSFORM_V1").unwrap();
        table_store.register_table(2, "COMP_IDENTITY_V1").unwrap();
        table_store.register_table(3, "COMP_HEALTH_V1").unwrap();
        (gate, entity_store, table_store)
    }

    fn rollback_hash(es: &EntityStore, ts: &ComponentTableStore, tick: u64) -> String {
        let mut snapshots = SnapshotEngine::standard("mutation-gate-atomicity", 0, 0);
        snapshots.take_snapshot(tick, es, ts).unwrap().world_hash
    }

    fn proof_state_bytes(
        gate: &MutationGate,
        es: &EntityStore,
        ts: &ComponentTableStore,
        tick: u64,
    ) -> String {
        let mut snapshots = SnapshotEngine::standard("mutation-gate-atomicity", 0, 0);
        let world_snapshot = snapshots.take_snapshot(tick, es, ts).unwrap();
        serde_json::to_string(&serde_json::json!({
            "world_snapshot": world_snapshot,
            "mutation_queues": gate.queue_snapshot_for_proof(),
        }))
        .unwrap()
    }

    fn write_mutation_proof_artifacts(
        pre_state: &str,
        post_state: &str,
        pre_hash: &str,
        post_hash: &str,
        diagnostic: &MutationApplyFailureDiagnostic,
    ) {
        let Some(proof_dir) = std::env::var_os("XACE_MUTATION_PROOF_DIR") else {
            return;
        };
        let proof_dir = std::path::PathBuf::from(proof_dir);
        std::fs::create_dir_all(&proof_dir).unwrap();
        std::fs::write(proof_dir.join("pre_state.json"), pre_state).unwrap();
        std::fs::write(proof_dir.join("post_state.json"), post_state).unwrap();
        std::fs::write(
            proof_dir.join("pre_post_hash_report.json"),
            serde_json::to_string_pretty(&serde_json::json!({
                "pre_batch_hash": pre_hash,
                "post_rollback_hash": post_hash,
                "hashes_equal": pre_hash == post_hash,
                "canonical_hash_length": 64,
                "rollback_status": format!("{:?}", diagnostic.rollback_status),
            }))
            .unwrap(),
        )
        .unwrap();
        std::fs::write(
            proof_dir.join("zero_diff_state_report.json"),
            serde_json::to_string_pretty(&serde_json::json!({
                "pre_state_bytes": pre_state.len(),
                "post_state_bytes": post_state.len(),
                "byte_for_byte_equal": pre_state.as_bytes() == post_state.as_bytes(),
                "failing_operation_index": diagnostic.failing_operation_index,
                "operation_type": diagnostic.operation_type,
                "path": diagnostic.path,
            }))
            .unwrap(),
        )
        .unwrap();
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
        let (mut gate, mut es, _ts) = setup();
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

    #[test]
    fn apply_failure_rolls_back_world_hash_and_reports_diagnostic() {
        let (mut gate, mut es, mut ts) = setup();
        let id = es.create_entity(0).unwrap();
        ts.add_component(id, 1, r#"{"x":0}"#.into(), 0).unwrap();

        gate.request_spawn("actor_new", BTreeMap::new(), &ts, 1)
            .unwrap();
        gate.request_add_component(id, 2, r#"{"name":"queued"}"#, &es, &ts, 1)
            .unwrap();
        gate.request_modify_component(id, 1, r#"{"x":99}"#, &es, &ts, 1)
            .unwrap();

        // Force an apply-time duplicate add after validation has accepted the
        // queued operation. This simulates a stale direct mutation bug.
        ts.add_component(id, 2, r#"{"name":"preexisting"}"#.into(), 1)
            .unwrap();
        let pre_hash = rollback_hash(&es, &ts, 1);

        let err = gate.apply_all(&mut es, &mut ts, 1).unwrap_err();
        let post_hash = rollback_hash(&es, &ts, 1);

        assert_eq!(pre_hash, post_hash);
        assert_eq!(es.alive_count(), 1);
        assert_eq!(ts.get_component(id, 1), Some(r#"{"x":0}"#));
        assert_eq!(ts.get_component(id, 2), Some(r#"{"name":"preexisting"}"#));
        assert_eq!(gate.pending_count(), 3);

        let diagnostic = gate.last_failure_diagnostic().unwrap();
        assert_eq!(diagnostic.failing_operation_index, 1);
        assert_eq!(diagnostic.operation_type, "add_component");
        assert_eq!(diagnostic.entity_id, Some(id));
        assert_eq!(diagnostic.component_type_id, Some(2));
        assert_eq!(diagnostic.path, format!("entity:{}.component:2", id));
        assert_eq!(diagnostic.rollback_status, MutationRollbackStatus::Restored);
        assert!(err.context().details.contains_key("rollback_status"));
    }

    #[test]
    fn mutation_atomicity_rejects_nested_transactions_until_proven_safe() {
        let (mut gate, mut es, mut ts) = setup();
        gate.force_transaction_in_progress_for_test();

        let err = gate.apply_all(&mut es, &mut ts, 0).unwrap_err();

        assert!(err.to_string().contains("Nested or concurrent"));
        match err {
            XaceError::ValidationFailure { rule_violated, .. } => {
                assert_eq!(rule_violated, "I8_nested_transaction_forbidden")
            }
            other => panic!("expected nested transaction validation failure, got {other:?}"),
        }
    }

    #[test]
    fn mutation_atomicity_five_operation_batch_op3_failure_restores_byte_for_byte_state() {
        let (mut gate, mut es, mut ts) = setup();
        let entity_a = es.create_entity(0).unwrap();
        let entity_b = es.create_entity(0).unwrap();
        ts.add_component(entity_a, 1, r#"{"x":0}"#.into(), 0)
            .unwrap();
        ts.add_component(entity_a, 3, r#"{"hp":10}"#.into(), 0)
            .unwrap();

        gate.request_spawn("actor_new", BTreeMap::new(), &ts, 1)
            .unwrap();
        gate.request_add_component(entity_a, 2, r#"{"name":"queued"}"#, &es, &ts, 1)
            .unwrap();
        gate.request_modify_component(entity_a, 1, r#"{"x":99}"#, &es, &ts, 1)
            .unwrap();
        gate.request_remove_component(entity_a, 3, &es, &ts, 1)
            .unwrap();
        gate.request_destroy(entity_b, &es, 1).unwrap();

        ts.remove_component(entity_a, 1, 1).unwrap();
        let pre_state = proof_state_bytes(&gate, &es, &ts, 1);
        let pre_hash = rollback_hash(&es, &ts, 1);

        let err = gate.apply_all(&mut es, &mut ts, 1).unwrap_err();
        let post_state = proof_state_bytes(&gate, &es, &ts, 1);
        let post_hash = rollback_hash(&es, &ts, 1);

        assert_eq!(pre_state.as_bytes(), post_state.as_bytes());
        assert_eq!(pre_hash, post_hash);
        assert_eq!(es.alive_count(), 2);
        assert!(!ts.has_component(entity_a, 1));
        assert!(!ts.has_component(entity_a, 2));
        assert!(ts.has_component(entity_a, 3));
        assert!(es.exists(entity_b));
        assert_eq!(gate.pending_count(), 5);

        let diagnostic = gate.last_failure_diagnostic().unwrap();
        assert_eq!(diagnostic.failing_operation_index, 2);
        assert_eq!(diagnostic.operation_type, "modify_component");
        assert_eq!(diagnostic.entity_id, Some(entity_a));
        assert_eq!(diagnostic.component_type_id, Some(1));
        assert_eq!(diagnostic.rollback_status, MutationRollbackStatus::Restored);
        assert!(err.context().details.contains_key("rollback_status"));
        write_mutation_proof_artifacts(&pre_state, &post_state, &pre_hash, &post_hash, diagnostic);
    }

    #[test]
    fn mutation_atomicity_stress_failure_restores_state() {
        let (mut gate, mut es, mut ts) = setup();
        let victim = es.create_entity(0).unwrap();
        ts.add_component(victim, 1, r#"{"x":0}"#.into(), 0).unwrap();
        for index in 0..128 {
            gate.request_spawn(format!("stress_actor_{}", index), BTreeMap::new(), &ts, 1)
                .unwrap();
        }
        gate.request_add_component(victim, 2, r#"{"name":"queued"}"#, &es, &ts, 1)
            .unwrap();
        ts.add_component(victim, 2, r#"{"name":"preexisting"}"#.into(), 1)
            .unwrap();
        let pre_state = proof_state_bytes(&gate, &es, &ts, 1);

        let _ = gate.apply_all(&mut es, &mut ts, 1).unwrap_err();
        let post_state = proof_state_bytes(&gate, &es, &ts, 1);

        assert_eq!(pre_state.as_bytes(), post_state.as_bytes());
        assert_eq!(es.alive_count(), 1);
        assert_eq!(gate.pending_count(), 129);
    }

    #[test]
    fn mutation_atomicity_malformed_json_failure_restores_state() {
        let (mut gate, mut es, mut ts) = setup();
        let id = es.create_entity(0).unwrap();
        gate.request_add_component(id, 1, r#"{"x":"#, &es, &ts, 1)
            .unwrap();
        let pre_state = proof_state_bytes(&gate, &es, &ts, 1);

        let _ = gate.apply_all(&mut es, &mut ts, 1).unwrap_err();
        let post_state = proof_state_bytes(&gate, &es, &ts, 1);

        assert_eq!(pre_state.as_bytes(), post_state.as_bytes());
        let diagnostic = gate.last_failure_diagnostic().unwrap();
        assert_eq!(diagnostic.operation_type, "add_component");
        assert_eq!(diagnostic.rollback_status, MutationRollbackStatus::Restored);
        assert!(diagnostic
            .source_error
            .contains("Component payload is not valid JSON"));
    }

    #[test]
    fn mutation_atomicity_missing_entity_mid_batch_failure_restores_state() {
        let (mut gate, mut es, mut ts) = setup();
        let stale = es.create_entity(0).unwrap();
        gate.request_add_component(stale, 1, r#"{"x":1}"#, &es, &ts, 1)
            .unwrap();
        es.request_destroy(stale, 1).unwrap();
        es.complete_destroy(stale, 1).unwrap();
        let pre_state = proof_state_bytes(&gate, &es, &ts, 1);

        let _ = gate.apply_all(&mut es, &mut ts, 1).unwrap_err();
        let post_state = proof_state_bytes(&gate, &es, &ts, 1);

        assert_eq!(pre_state.as_bytes(), post_state.as_bytes());
        assert!(!ts.has_component(stale, 1));
        let diagnostic = gate.last_failure_diagnostic().unwrap();
        assert_eq!(diagnostic.operation_type, "add_component");
        assert_eq!(diagnostic.entity_id, Some(stale));
        assert_eq!(diagnostic.rollback_status, MutationRollbackStatus::Restored);
    }

    #[test]
    fn mutation_atomicity_component_table_failure_restores_state() {
        let (mut gate, mut es, mut ts) = setup();
        let id = es.create_entity(0).unwrap();
        gate.request_add_component(id, 1, r#"{"x":1}"#, &es, &ts, 1)
            .unwrap();
        ts.add_component(id, 1, r#"{"x":0}"#.into(), 1).unwrap();
        let pre_state = proof_state_bytes(&gate, &es, &ts, 1);

        let _ = gate.apply_all(&mut es, &mut ts, 1).unwrap_err();
        let post_state = proof_state_bytes(&gate, &es, &ts, 1);

        assert_eq!(pre_state.as_bytes(), post_state.as_bytes());
        assert_eq!(ts.get_component(id, 1), Some(r#"{"x":0}"#));
        let diagnostic = gate.last_failure_diagnostic().unwrap();
        assert_eq!(diagnostic.operation_type, "add_component");
        assert_eq!(diagnostic.rollback_status, MutationRollbackStatus::Restored);
    }

    #[test]
    fn mutation_atomicity_snapshot_per_batch_overhead_within_threshold() {
        const ENTITY_COUNT: u64 = 1_000;
        const ACCEPTABLE_THRESHOLD_MS: u128 = 1_000;
        let (mut gate, mut es, mut ts) = setup();
        for entity_id in 1..=ENTITY_COUNT {
            let created = es.create_entity(0).unwrap();
            assert_eq!(created, entity_id);
            ts.add_component(
                created,
                1,
                format!(r#"{{"position_x":{},"position_y":0}}"#, entity_id),
                0,
            )
            .unwrap();
        }

        let started = std::time::Instant::now();
        gate.apply_all(&mut es, &mut ts, 1).unwrap();
        let elapsed_ms = started.elapsed().as_millis();

        assert!(
            elapsed_ms <= ACCEPTABLE_THRESHOLD_MS,
            "MutationGate empty batch snapshot overhead for {} entities was {}ms, threshold {}ms",
            ENTITY_COUNT,
            elapsed_ms,
            ACCEPTABLE_THRESHOLD_MS
        );
    }
}
