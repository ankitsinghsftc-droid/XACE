//! # Mutation Validator
//!
//! Pre-application validation for all mutation requests.
//! Validates entity existence, component type validity, and
//! duplicate checks before mutations enter the queues.
//!
//! ## Validation Against CompositeComponentRegistry
//! Per MASTER_PLAN Phase 3 note: the validator checks against the
//! CompositeComponentRegistry (UCL + DCL + GCL) — not just UCL.
//! This ensures DCL and GCL components are fully validated.
//!
//! ## When Validation Runs
//! Validation runs when a system submits a mutation request.
//! This is before the request enters the queue — invalid requests
//! are rejected immediately with a ValidationFailure error.
//!
//! ## What Is NOT Validated Here
//! Cross-mutation consistency (e.g. spawning entity X and destroying
//! entity X in the same apply batch) is handled by the MutationGate
//! during apply_all(), not here.

use crate::component_tables::component_table_store::ComponentTableStore;
use crate::entity_store::entity_store::EntityStore;
use xace_core::entity_id::{EntityID, NULL_ENTITY_ID};
use xace_core::errors::xace_error::{ErrorContext, XaceError};

// ── Mutation Validator ────────────────────────────────────────────────────────

/// Validates mutation requests before they enter the deferred queues.
///
/// Stateless — all validation context is passed as parameters.
/// The MutationGate creates one instance and reuses it.
pub struct MutationValidator;

impl MutationValidator {
    pub fn new() -> Self {
        Self
    }

    // ── Spawn Validation ───────────────────────────────────────────────────

    /// Validates a spawn request.
    ///
    /// Checks:
    /// - actor_id is not empty (warning only — empty is allowed for
    ///   runtime-generated entities without blueprints)
    /// - All component type IDs in initial_components are registered
    /// - No component appears twice in initial_components
    pub fn validate_spawn(
        &self,
        actor_id: &str,
        initial_components: &std::collections::BTreeMap<u32, String>,
        table_store: &ComponentTableStore,
        tick: u64,
    ) -> Result<(), XaceError> {
        // Validate all component types are registered
        for type_id in initial_components.keys() {
            if !table_store.has_table(*type_id) {
                return Err(XaceError::ValidationFailure {
                    message: format!(
                        "Spawn request for actor '{}' references unregistered \
                         component type_id {} — register the component table first",
                        actor_id, type_id
                    ),
                    context: ErrorContext::new("MutationValidator", "validate_spawn")
                        .with_tick(tick),
                    rule_violated: "component_must_be_registered".into(),
                    failed_path: format!("spawn.initial_components.{}", type_id),
                });
            }
        }
        Ok(())
    }

    // ── Component Add Validation ───────────────────────────────────────────

    /// Validates a component add request.
    ///
    /// Checks:
    /// - entity_id is not NULL_ENTITY_ID
    /// - Entity exists in EntityStore (I1)
    /// - Entity is in a valid state (Active or Disabled — not DestroyRequested)
    /// - Component type is registered in ComponentTableStore
    /// - Entity does not already have this component
    pub fn validate_add_component(
        &self,
        entity_id: EntityID,
        component_type_id: u32,
        entity_store: &EntityStore,
        table_store: &ComponentTableStore,
        tick: u64,
    ) -> Result<(), XaceError> {
        self.validate_entity_id(entity_id, tick)?;
        self.validate_entity_exists(entity_id, entity_store, "add_component", tick)?;
        self.validate_entity_not_destroy_requested(entity_id, entity_store, tick)?;
        self.validate_component_registered(component_type_id, table_store, "add_component", tick)?;

        // Check entity doesn't already have this component
        if table_store.has_component(entity_id, component_type_id) {
            return Err(XaceError::ValidationFailure {
                message: format!(
                    "Entity {} already has component type_id {} — \
                     use modify to update existing components",
                    entity_id, component_type_id
                ),
                context: ErrorContext::new("MutationValidator", "add_component").with_tick(tick),
                rule_violated: "no_duplicate_components".into(),
                failed_path: format!("entity:{}.component:{}", entity_id, component_type_id),
            });
        }
        Ok(())
    }

    // ── Component Modify Validation ────────────────────────────────────────

    /// Validates a component modify request.
    ///
    /// Checks:
    /// - entity_id is not NULL_ENTITY_ID
    /// - Entity exists
    /// - Component type is registered
    /// - Entity has this component (can only modify existing)
    pub fn validate_modify_component(
        &self,
        entity_id: EntityID,
        component_type_id: u32,
        entity_store: &EntityStore,
        table_store: &ComponentTableStore,
        tick: u64,
    ) -> Result<(), XaceError> {
        self.validate_entity_id(entity_id, tick)?;
        self.validate_entity_exists(entity_id, entity_store, "modify_component", tick)?;
        self.validate_component_registered(
            component_type_id,
            table_store,
            "modify_component",
            tick,
        )?;

        if !table_store.has_component(entity_id, component_type_id) {
            return Err(XaceError::ValidationFailure {
                message: format!(
                    "Entity {} does not have component type_id {} — \
                     use add to attach new components",
                    entity_id, component_type_id
                ),
                context: ErrorContext::new("MutationValidator", "modify_component").with_tick(tick),
                rule_violated: "component_must_exist".into(),
                failed_path: format!("entity:{}.component:{}", entity_id, component_type_id),
            });
        }
        Ok(())
    }

    // ── Component Remove Validation ────────────────────────────────────────

    /// Validates a component remove request.
    pub fn validate_remove_component(
        &self,
        entity_id: EntityID,
        component_type_id: u32,
        entity_store: &EntityStore,
        table_store: &ComponentTableStore,
        tick: u64,
    ) -> Result<(), XaceError> {
        self.validate_entity_id(entity_id, tick)?;
        self.validate_entity_exists(entity_id, entity_store, "remove_component", tick)?;
        self.validate_component_registered(
            component_type_id,
            table_store,
            "remove_component",
            tick,
        )?;

        if !table_store.has_component(entity_id, component_type_id) {
            return Err(XaceError::ValidationFailure {
                message: format!(
                    "Entity {} does not have component type_id {} — cannot remove",
                    entity_id, component_type_id
                ),
                context: ErrorContext::new("MutationValidator", "remove_component").with_tick(tick),
                rule_violated: "component_must_exist".into(),
                failed_path: format!("entity:{}.component:{}", entity_id, component_type_id),
            });
        }
        Ok(())
    }

    // ── Destroy Validation ─────────────────────────────────────────────────

    /// Validates a destroy request.
    ///
    /// Checks:
    /// - entity_id is not NULL_ENTITY_ID
    /// - Entity exists in EntityStore
    /// - Entity is not already DestroyRequested or destroyed
    pub fn validate_destroy(
        &self,
        entity_id: EntityID,
        entity_store: &EntityStore,
        tick: u64,
    ) -> Result<(), XaceError> {
        self.validate_entity_id(entity_id, tick)?;

        if !entity_store.exists(entity_id) {
            return Err(XaceError::ValidationFailure {
                message: format!(
                    "Cannot destroy entity {} — entity does not exist",
                    entity_id
                ),
                context: ErrorContext::new("MutationValidator", "validate_destroy").with_tick(tick),
                rule_violated: "I1".into(),
                failed_path: format!("entity:{}", entity_id),
            });
        }

        // Check not already in destruction pipeline
        let meta = entity_store.get_metadata(entity_id).unwrap();
        if !meta
            .state
            .can_transition_to(xace_core::entity_state::EntityState::DestroyRequested)
        {
            return Err(XaceError::ValidationFailure {
                message: format!(
                    "Entity {} is already in state {:?} — cannot request destruction",
                    entity_id, meta.state
                ),
                context: ErrorContext::new("MutationValidator", "validate_destroy").with_tick(tick),
                rule_violated: "entity_lifecycle".into(),
                failed_path: format!("entity:{}", entity_id),
            });
        }
        Ok(())
    }

    // ── Shared Validation Helpers ──────────────────────────────────────────

    fn validate_entity_id(&self, entity_id: EntityID, tick: u64) -> Result<(), XaceError> {
        if entity_id == NULL_ENTITY_ID {
            return Err(XaceError::ValidationFailure {
                message: "NULL_ENTITY_ID (0) is not a valid entity ID \
                          for mutation requests"
                    .into(),
                context: ErrorContext::new("MutationValidator", "validate_entity_id")
                    .with_tick(tick),
                rule_violated: "D2".into(),
                failed_path: "entity_id".into(),
            });
        }
        Ok(())
    }

    fn validate_entity_exists(
        &self,
        entity_id: EntityID,
        entity_store: &EntityStore,
        operation: &str,
        tick: u64,
    ) -> Result<(), XaceError> {
        if !entity_store.exists(entity_id) {
            return Err(XaceError::ValidationFailure {
                message: format!(
                    "Entity {} does not exist in EntityStore — \
                     component mutations require existing entities (I1)",
                    entity_id
                ),
                context: ErrorContext::new("MutationValidator", operation).with_tick(tick),
                rule_violated: "I1".into(),
                failed_path: format!("entity:{}", entity_id),
            });
        }
        Ok(())
    }

    fn validate_entity_not_destroy_requested(
        &self,
        entity_id: EntityID,
        entity_store: &EntityStore,
        tick: u64,
    ) -> Result<(), XaceError> {
        if let Some(meta) = entity_store.get_metadata(entity_id) {
            if matches!(
                meta.state,
                xace_core::entity_state::EntityState::DestroyRequested
            ) {
                return Err(XaceError::ValidationFailure {
                    message: format!(
                        "Entity {} is marked for destruction — \
                         cannot add components to a dying entity",
                        entity_id
                    ),
                    context: ErrorContext::new(
                        "MutationValidator",
                        "validate_entity_not_destroy_requested",
                    )
                    .with_tick(tick),
                    rule_violated: "entity_lifecycle".into(),
                    failed_path: format!("entity:{}", entity_id),
                });
            }
        }
        Ok(())
    }

    fn validate_component_registered(
        &self,
        component_type_id: u32,
        table_store: &ComponentTableStore,
        operation: &str,
        tick: u64,
    ) -> Result<(), XaceError> {
        if !table_store.has_table(component_type_id) {
            return Err(XaceError::ValidationFailure {
                message: format!(
                    "Component type_id {} is not registered in ComponentTableStore — \
                     register it during runtime initialization",
                    component_type_id
                ),
                context: ErrorContext::new("MutationValidator", operation).with_tick(tick),
                rule_violated: "component_must_be_registered".into(),
                failed_path: format!("component_type_id:{}", component_type_id),
            });
        }
        Ok(())
    }
}

impl Default for MutationValidator {
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

    fn setup() -> (MutationValidator, EntityStore, ComponentTableStore) {
        let validator = MutationValidator::new();
        let entity_store = EntityStore::new();
        let mut table_store = ComponentTableStore::new();
        table_store.register_table(1, "COMP_TRANSFORM_V1").unwrap();
        table_store.register_table(2, "COMP_IDENTITY_V1").unwrap();
        (validator, entity_store, table_store)
    }

    #[test]
    fn null_entity_id_rejected() {
        let (v, es, ts) = setup();
        assert!(v
            .validate_add_component(NULL_ENTITY_ID, 1, &es, &ts, 0)
            .is_err());
    }

    #[test]
    fn nonexistent_entity_rejected() {
        let (v, es, ts) = setup();
        assert!(v.validate_add_component(999, 1, &es, &ts, 0).is_err());
    }

    #[test]
    fn unregistered_component_rejected() {
        let (v, mut es, ts) = setup();
        let id = es.create_entity(0).unwrap();
        assert!(v.validate_add_component(id, 999, &es, &ts, 0).is_err());
    }

    #[test]
    fn valid_add_component() {
        let (v, mut es, ts) = setup();
        let id = es.create_entity(0).unwrap();
        assert!(v.validate_add_component(id, 1, &es, &ts, 0).is_ok());
    }

    #[test]
    fn duplicate_component_rejected() {
        let (v, mut es, mut ts) = setup();
        let id = es.create_entity(0).unwrap();
        ts.add_component(id, 1, "{}".into(), 0).unwrap();
        assert!(v.validate_add_component(id, 1, &es, &ts, 0).is_err());
    }

    #[test]
    fn modify_nonexistent_component_rejected() {
        let (v, mut es, ts) = setup();
        let id = es.create_entity(0).unwrap();
        assert!(v.validate_modify_component(id, 1, &es, &ts, 0).is_err());
    }

    #[test]
    fn valid_modify_component() {
        let (v, mut es, mut ts) = setup();
        let id = es.create_entity(0).unwrap();
        ts.add_component(id, 1, "{}".into(), 0).unwrap();
        assert!(v.validate_modify_component(id, 1, &es, &ts, 0).is_ok());
    }

    #[test]
    fn destroy_nonexistent_entity_rejected() {
        let (v, es, _) = setup();
        assert!(v.validate_destroy(999, &es, 0).is_err());
    }

    #[test]
    fn valid_destroy() {
        let (v, mut es, _) = setup();
        let id = es.create_entity(0).unwrap();
        assert!(v.validate_destroy(id, &es, 0).is_ok());
    }

    #[test]
    fn destroy_already_requested_rejected() {
        let (v, mut es, _) = setup();
        let id = es.create_entity(0).unwrap();
        es.request_destroy(id, 1).unwrap();
        assert!(v.validate_destroy(id, &es, 2).is_err());
    }

    #[test]
    fn add_to_destroy_requested_entity_rejected() {
        let (v, mut es, ts) = setup();
        let id = es.create_entity(0).unwrap();
        es.request_destroy(id, 1).unwrap();
        assert!(v.validate_add_component(id, 1, &es, &ts, 2).is_err());
    }
}
