//! # Delta Builder
//!
//! Constructs a `DeltaPayload` from a `StateDelta` in the strictly enforced
//! application order required by the engine adapter (D4).
//!
//! ## Responsibility
//! The `DeltaBuilder` translates the runtime's canonical `StateDelta`
//! (which uses `ComponentChange` / `FieldChange` types) into the wire-format
//! `DeltaPayload` (which uses `WireSpawnedEntity` / `WireComponentUpdate`).
//!
//! ## Application Order (D4)
//! The DeltaPayload produced by this builder always has changes ordered:
//! 1. `spawned_entities`   — create new entities first
//! 2. `added_components`   — attach new components to existing entities
//! 3. `modified_entities`  — apply field-level changes
//! 4. `removed_components` — detach components
//! 5. `destroyed_entities` — remove entities last
//!
//! This order is enforced by `DeltaPayload`'s own sorted insertion methods,
//! not by the builder's iteration order — but the builder also processes
//! sections in this order to make intent explicit and auditable.
//!
//! ## Determinism (D3, D11)
//! All entity lists are produced in EntityID ASC order (inherited from
//! `StateDelta`'s BTreeMap/sorted-Vec structures).
//! All component lists are produced in component_type_id ASC order.
//! Field changes within each component are sorted by field_name ASC.
//! These orderings match what `DeltaPayload` enforces — the builder
//! never produces output that violates them.

use xace_core::runtime::state_delta::StateDelta;
use xace_core::wire::delta_payload::{
    DeltaPayload, WireAddedComponent, WireComponentData, WireComponentUpdate, WireDestroyedEntity,
    WireFieldChange, WireRemovedComponent, WireSpawnedEntity,
};

// ── Builder Metrics ───────────────────────────────────────────────────────────

/// Statistics produced by one `build()` call.
#[derive(Debug, Clone, Default)]
pub struct BuildMetrics {
    pub spawned_entities: usize,
    pub destroyed_entities: usize,
    pub added_components: usize,
    pub removed_components: usize,
    pub modified_entities: usize,
    pub total_field_changes: usize,
}

// ── Delta Builder ─────────────────────────────────────────────────────────────

/// Converts a `StateDelta` into a wire-format `DeltaPayload`.
///
/// Stateless — create one per build call or reuse across ticks.
/// All state is returned in the `DeltaPayload`; none is retained.
pub struct DeltaBuilder;

impl DeltaBuilder {
    /// Builds a `DeltaPayload` from a `StateDelta`.
    ///
    /// Returns the payload and build metrics. If the `StateDelta` is empty,
    /// returns an empty payload — callers should check `DeltaPayload::is_empty()`
    /// before sending.
    ///
    /// `sequence_id` is assigned by the caller (`EngineAdapterInterface`) and
    /// embedded into the payload for sequence tracking on the engine side.
    pub fn build(delta: &StateDelta, sequence_id: u64) -> (DeltaPayload, BuildMetrics) {
        let mut payload = DeltaPayload::empty(delta.tick, sequence_id, &delta.schema_version);
        let mut metrics = BuildMetrics::default();

        // ── 1. Spawned entities ────────────────────────────────────────────
        for spawned in &delta.spawned_entities {
            let mut wire_entity = WireSpawnedEntity::new(spawned.entity_id, &spawned.actor_id);

            // BTreeMap iteration is component_type_id ASC (D11)
            for (type_id, component_json) in &spawned.initial_components {
                wire_entity.add_component(WireComponentData::new(
                    *type_id,
                    format!("COMP_TYPE_{}", type_id), // name resolved by registry in Phase 11+
                    component_json.clone(),
                ));
            }

            for tag in &spawned.tags {
                wire_entity.tags.push(tag.clone());
            }
            wire_entity.tags.sort(); // deterministic (D11)

            payload.add_spawn(wire_entity);
            metrics.spawned_entities += 1;
        }

        // ── 2. Added components ────────────────────────────────────────────
        for added in &delta.added_components {
            payload.add_component_addition(WireAddedComponent {
                entity_id: added.entity_id,
                component: WireComponentData::new(
                    added.component_type_id,
                    &added.component_type_name,
                    &added.component_json,
                ),
            });
            metrics.added_components += 1;
        }

        // ── 3. Modified components (field-level changes) ───────────────────
        // updated_components is BTreeMap<EntityID, BTreeMap<type_id, ComponentChange>>
        // Both levels iterate in ascending order (D3, D11)
        for (entity_id, component_map) in &delta.updated_components {
            for (type_id, change) in component_map {
                let wire_fields: Vec<WireFieldChange> = change
                    .field_changes
                    .iter()
                    .map(|fc| WireFieldChange::new(&fc.field_name, &fc.value_json))
                    .collect();
                // WireComponentUpdate::new sorts fields by name (D11)
                let wire_update =
                    WireComponentUpdate::new(*type_id, &change.component_type_name, wire_fields);
                payload.add_component_update(*entity_id, wire_update);
                metrics.total_field_changes += change.field_count();
            }
            metrics.modified_entities += 1;
        }

        // ── 4. Removed components ──────────────────────────────────────────
        for removed in &delta.removed_components {
            payload.add_component_removal(WireRemovedComponent {
                entity_id: removed.entity_id,
                component_type_id: removed.component_type_id,
                component_type_name: removed.component_type_name.clone(),
            });
            metrics.removed_components += 1;
        }

        // ── 5. Destroyed entities ──────────────────────────────────────────
        for destroyed in &delta.destroyed_entities {
            payload.add_destroy(WireDestroyedEntity::new(destroyed.entity_id));
            metrics.destroyed_entities += 1;
        }

        (payload, metrics)
    }

    /// Returns true if a `StateDelta` would produce a non-empty `DeltaPayload`.
    /// Use as a fast-path check before calling `build()`.
    pub fn would_produce_content(delta: &StateDelta) -> bool {
        !delta.is_empty()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::entity_metadata::Tick;
    use xace_core::runtime::state_delta::{
        AddedComponent, ComponentChange, DestroyedEntity, FieldChange, RemovedComponent,
        SpawnedEntity, StateDelta,
    };

    fn empty_delta(tick: Tick) -> StateDelta {
        StateDelta::empty(tick, "0.1.0")
    }

    // ── Empty Delta ───────────────────────────────────────────────────────────

    #[test]
    fn empty_delta_produces_empty_payload() {
        let delta = empty_delta(1);
        let (payload, metrics) = DeltaBuilder::build(&delta, 1);
        assert!(payload.is_empty());
        assert_eq!(metrics.spawned_entities, 0);
        assert_eq!(metrics.destroyed_entities, 0);
    }

    #[test]
    fn would_produce_content_false_for_empty() {
        let delta = empty_delta(1);
        assert!(!DeltaBuilder::would_produce_content(&delta));
    }

    // ── Spawned Entities ──────────────────────────────────────────────────────

    #[test]
    fn spawned_entity_appears_in_payload() {
        let mut delta = empty_delta(1);
        delta.record_spawn(
            SpawnedEntity::new(1, "actor_player").with_component(1, r#"{"position":{"x":0}}"#),
        );

        let (payload, metrics) = DeltaBuilder::build(&delta, 1);
        assert_eq!(payload.spawned_entities.len(), 1);
        assert_eq!(payload.spawned_entities[0].entity_id, 1);
        assert_eq!(payload.spawned_entities[0].initial_components.len(), 1);
        assert_eq!(metrics.spawned_entities, 1);
    }

    #[test]
    fn multiple_spawns_sorted_by_entity_id() {
        let mut delta = empty_delta(1);
        delta.record_spawn(SpawnedEntity::new(5, "actor_zombie"));
        delta.record_spawn(SpawnedEntity::new(1, "actor_player"));
        delta.record_spawn(SpawnedEntity::new(3, "actor_npc"));

        let (payload, _) = DeltaBuilder::build(&delta, 1);
        assert_eq!(payload.spawned_entities[0].entity_id, 1);
        assert_eq!(payload.spawned_entities[1].entity_id, 3);
        assert_eq!(payload.spawned_entities[2].entity_id, 5);
    }

    #[test]
    fn spawn_components_sorted_by_type_id() {
        let mut delta = empty_delta(1);
        let mut spawned = SpawnedEntity::new(1, "actor_player");
        spawned.initial_components.insert(5, "{}".into()); // velocity
        spawned.initial_components.insert(1, "{}".into()); // transform
        spawned.initial_components.insert(3, "{}".into()); // render
        delta.record_spawn(spawned);

        let (payload, _) = DeltaBuilder::build(&delta, 1);
        let comps = &payload.spawned_entities[0].initial_components;
        assert_eq!(comps[0].component_type_id, 1);
        assert_eq!(comps[1].component_type_id, 3);
        assert_eq!(comps[2].component_type_id, 5);
    }

    // ── Destroyed Entities ────────────────────────────────────────────────────

    #[test]
    fn destroyed_entity_appears_in_payload() {
        let mut delta = empty_delta(5);
        delta.record_destroy(DestroyedEntity::new(42, 4));
        let (payload, metrics) = DeltaBuilder::build(&delta, 1);
        assert_eq!(payload.destroyed_entities.len(), 1);
        assert_eq!(payload.destroyed_entities[0].entity_id, 42);
        assert_eq!(metrics.destroyed_entities, 1);
    }

    // ── Added Components ──────────────────────────────────────────────────────

    #[test]
    fn added_component_appears_in_payload() {
        let mut delta = empty_delta(1);
        delta.record_component_added(AddedComponent {
            entity_id: 1,
            component_type_id: 7,
            component_type_name: "COMP_HEALTH_V1".into(),
            component_json: r#"{"current":100}"#.into(),
        });
        let (payload, metrics) = DeltaBuilder::build(&delta, 1);
        assert_eq!(payload.added_components.len(), 1);
        assert_eq!(payload.added_components[0].entity_id, 1);
        assert_eq!(metrics.added_components, 1);
    }

    // ── Modified Components ───────────────────────────────────────────────────

    #[test]
    fn field_change_appears_in_modified_entities() {
        let mut delta = empty_delta(1);
        delta.record_component_update(
            1,
            ComponentChange::single_field(1, "COMP_TRANSFORM_V1", "position", r#"{"x":5}"#),
        );
        let (payload, metrics) = DeltaBuilder::build(&delta, 1);
        assert!(payload.modified_entities.contains_key(&1));
        assert_eq!(metrics.modified_entities, 1);
        assert_eq!(metrics.total_field_changes, 1);
    }

    #[test]
    fn multiple_field_changes_sorted_by_field_name() {
        let mut delta = empty_delta(1);
        delta.record_component_update(
            1,
            ComponentChange::multi_field(
                1,
                "COMP_TRANSFORM_V1",
                vec![
                    FieldChange::new("z_rotation", "0.5"),
                    FieldChange::new("a_position", "1.0"),
                    FieldChange::new("m_scale", "2.0"),
                ],
            ),
        );
        let (payload, _) = DeltaBuilder::build(&delta, 1);
        let entity_update = &payload.modified_entities[&1];
        let fields = &entity_update.component_updates[&1].field_changes;
        assert_eq!(fields[0].field_name, "a_position");
        assert_eq!(fields[1].field_name, "m_scale");
        assert_eq!(fields[2].field_name, "z_rotation");
    }

    // ── Removed Components ────────────────────────────────────────────────────

    #[test]
    fn removed_component_appears_in_payload() {
        let mut delta = empty_delta(1);
        delta.record_component_removed(RemovedComponent {
            entity_id: 3,
            component_type_id: 7,
            component_type_name: "COMP_HEALTH_V1".into(),
        });
        let (payload, metrics) = DeltaBuilder::build(&delta, 1);
        assert_eq!(payload.removed_components.len(), 1);
        assert_eq!(payload.removed_components[0].entity_id, 3);
        assert_eq!(metrics.removed_components, 1);
    }

    // ── Sequence ID ───────────────────────────────────────────────────────────

    #[test]
    fn sequence_id_embedded_in_payload() {
        let mut delta = empty_delta(1);
        delta.record_spawn(SpawnedEntity::new(1, "actor"));
        let (payload, _) = DeltaBuilder::build(&delta, 99);
        assert_eq!(payload.sequence_id, 99);
    }

    // ── Tick Embedding ────────────────────────────────────────────────────────

    #[test]
    fn tick_embedded_in_payload() {
        let mut delta = empty_delta(42);
        delta.record_spawn(SpawnedEntity::new(1, "actor"));
        let (payload, _) = DeltaBuilder::build(&delta, 1);
        assert_eq!(payload.tick, 42);
    }

    // ── Schema Version ────────────────────────────────────────────────────────

    #[test]
    fn schema_version_copied_from_delta() {
        let delta = StateDelta::empty(1, "1.2.3");
        let (payload, _) = DeltaBuilder::build(&delta, 1);
        assert_eq!(payload.schema_version, "1.2.3");
    }
}
