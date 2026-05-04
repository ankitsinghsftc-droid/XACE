//! # Delta Compressor
//!
//! Removes unchanged fields from a `DeltaPayload` by comparing it against
//! the last successfully sent payload, producing a minimal wire delta.
//!
//! ## The Minimal Delta Principle
//! Without compression, every field of every changed component would be sent
//! every tick even if only one field actually changed. At 60Hz with 1000
//! entities, that is significant bandwidth waste.
//!
//! The compressor holds the last-sent component state per entity and compares
//! each field in the new payload against it. Only genuinely changed fields
//! survive into the compressed output.
//!
//! ## Example
//! An entity has `COMP_TRANSFORM_V1` with position, rotation, and scale.
//! If only position changed this tick, the compressor removes rotation and
//! scale from the `WireComponentUpdate`, leaving a 1-field update instead of 3.
//!
//! ## State Tracking
//! The compressor maintains a `BTreeMap<EntityID, BTreeMap<type_id, component_json>>`
//! of last-sent component state. After each compressed payload is produced,
//! the compressor updates its cache with the new field values.
//!
//! ## Cache Invalidation
//! On entity spawn: the initial component data is stored in the cache.
//! On entity destroy: all cache entries for that entity are removed.
//! On component removal: the specific type entry is removed.
//! On SNAPSHOT send: the cache is rebuilt from the snapshot payload.
//!
//! ## Determinism (D11)
//! All cache keys are BTreeMap — deterministic iteration order.
//! Field comparison is exact string equality — no float rounding.
//! Same input delta + same cache state → same compressed output, always.

use std::collections::BTreeMap;

use xace_core::entity_id::EntityID;
use xace_core::wire::delta_payload::{
    DeltaPayload, WireComponentUpdate, WireFieldChange,
};
use xace_core::wire::snapshot_payload::SnapshotPayload;

// ── Compressor Metrics ────────────────────────────────────────────────────────

/// Statistics accumulated across all compress() calls.
#[derive(Debug, Clone, Default)]
pub struct CompressorMetrics {
    /// Total compress() calls.
    pub compressions_performed: u64,
    /// Total field changes before compression.
    pub fields_before: u64,
    /// Total field changes after compression.
    pub fields_after: u64,
    /// Total entity updates removed entirely (all fields unchanged).
    pub entity_updates_eliminated: u64,
    /// Total times the cache was rebuilt from a SNAPSHOT.
    pub cache_rebuilds: u64,
}

impl CompressorMetrics {
    /// Fields eliminated by compression.
    pub fn fields_eliminated(&self) -> u64 {
        self.fields_before.saturating_sub(self.fields_after)
    }

    /// Compression ratio (0.0 = no compression, 1.0 = everything eliminated).
    pub fn compression_ratio(&self) -> f32 {
        if self.fields_before == 0 {
            return 0.0;
        }
        self.fields_eliminated() as f32 / self.fields_before as f32
    }
}

// ── Field Cache ───────────────────────────────────────────────────────────────

/// The last-sent field values for one component on one entity.
/// BTreeMap<field_name, value_json> — sorted for determinism (D11).
type ComponentFieldCache = BTreeMap<String, String>;

/// Full last-sent state cache.
/// BTreeMap<EntityID, BTreeMap<component_type_id, ComponentFieldCache>>
type DeltaCache = BTreeMap<EntityID, BTreeMap<u32, ComponentFieldCache>>;

// ── Delta Compressor ──────────────────────────────────────────────────────────

/// Eliminates unchanged fields from a `DeltaPayload` by comparing against
/// the last successfully transmitted component state.
///
/// ## Ownership
/// One `DeltaCompressor` per engine adapter connection. Reset on reconnect
/// via `rebuild_from_snapshot()`.
pub struct DeltaCompressor {
    /// Last-sent field values, keyed by EntityID then component_type_id then field_name.
    cache: DeltaCache,

    /// Accumulated compression metrics.
    metrics: CompressorMetrics,
}

impl DeltaCompressor {
    // ── Construction ──────────────────────────────────────────────────────────

    /// Creates a new compressor with an empty cache.
    ///
    /// The first delta sent after construction will always be sent in full
    /// (nothing is cached yet to compare against).
    pub fn new() -> Self {
        Self {
            cache: BTreeMap::new(),
            metrics: CompressorMetrics::default(),
        }
    }

    // ── Primary API ───────────────────────────────────────────────────────────

    /// Compresses a `DeltaPayload` by removing fields unchanged since last send.
    ///
    /// Mutates the payload in-place:
    /// - `modified_entities`: each `WireComponentUpdate` has unchanged fields removed.
    ///   If all fields of a component are unchanged, the update is removed.
    ///   If all component updates for an entity are removed, the entity entry is removed.
    /// - `spawned_entities` and other sections are not compressed — they always
    ///   represent new state and must be sent in full.
    ///
    /// Updates the cache with all surviving field values after compression.
    /// Also processes spawns/destroys/adds/removes to keep cache consistent.
    pub fn compress(&mut self, payload: &mut DeltaPayload) {
        self.metrics.compressions_performed += 1;

        // ── Account for spawned entities in cache ──────────────────────────
        for spawned in &payload.spawned_entities {
            let entity_cache = self.cache
                .entry(spawned.entity_id)
                .or_insert_with(BTreeMap::new);

            for component in &spawned.initial_components {
                // Parse the component JSON into field-level cache entries
                let field_cache = entity_cache
                    .entry(component.component_type_id)
                    .or_insert_with(BTreeMap::new);
                Self::parse_component_json_into_cache(&component.data_json, field_cache);
            }
        }

        // ── Compress modified_entities ─────────────────────────────────────
        let mut total_before = 0u64;
        let mut total_after = 0u64;
        let mut entities_eliminated = 0u64;

        let mut empty_entity_ids: Vec<EntityID> = Vec::new();

        for (entity_id, entity_update) in payload.modified_entities.iter_mut() {
            let entity_cache = self.cache
                .entry(*entity_id)
                .or_insert_with(BTreeMap::new);

            let mut empty_type_ids: Vec<u32> = Vec::new();

            for (type_id, component_update) in entity_update.component_updates.iter_mut() {
                let field_cache = entity_cache
                    .entry(*type_id)
                    .or_insert_with(BTreeMap::new);

                total_before += component_update.field_changes.len() as u64;

                // Keep only fields whose value differs from the cached value
                component_update.field_changes.retain(|fc| {
                    match field_cache.get(&fc.field_name) {
                        Some(cached_val) => cached_val != &fc.value_json,
                        None => true, // field not yet cached — must send
                    }
                });

                total_after += component_update.field_changes.len() as u64;

                // Update cache with surviving (genuinely changed) fields
                for fc in &component_update.field_changes {
                    field_cache.insert(fc.field_name.clone(), fc.value_json.clone());
                }

                if component_update.field_changes.is_empty() {
                    empty_type_ids.push(*type_id);
                }
            }

            // Remove fully-eliminated component updates
            for type_id in empty_type_ids {
                entity_update.component_updates.remove(&type_id);
            }

            if entity_update.component_updates.is_empty() {
                empty_entity_ids.push(*entity_id);
                entities_eliminated += 1;
            }
        }

        // Remove fully-eliminated entity updates
        for entity_id in empty_entity_ids {
            payload.modified_entities.remove(&entity_id);
        }

        // ── Account for removed components in cache ────────────────────────
        for removed in &payload.removed_components {
            if let Some(entity_cache) = self.cache.get_mut(&removed.entity_id) {
                entity_cache.remove(&removed.component_type_id);
            }
        }

        // ── Account for added components in cache ──────────────────────────
        for added in &payload.added_components {
            let entity_cache = self.cache
                .entry(added.entity_id)
                .or_insert_with(BTreeMap::new);
            let field_cache = entity_cache
                .entry(added.component.component_type_id)
                .or_insert_with(BTreeMap::new);
            Self::parse_component_json_into_cache(&added.component.data_json, field_cache);
        }

        // ── Evict destroyed entities from cache ────────────────────────────
        for destroyed in &payload.destroyed_entities {
            self.cache.remove(&destroyed.entity_id);
        }

        self.metrics.fields_before += total_before;
        self.metrics.fields_after += total_after;
        self.metrics.entity_updates_eliminated += entities_eliminated;
    }

    /// Rebuilds the field cache from a `SnapshotPayload`.
    ///
    /// Call this after sending a full SNAPSHOT to the engine adapter so the
    /// compressor's cache reflects exactly what the engine currently holds.
    /// Without this, the first DELTA after a SNAPSHOT would incorrectly
    /// eliminate fields the engine hasn't received yet.
    pub fn rebuild_from_snapshot(&mut self, snapshot: &SnapshotPayload) {
        self.cache.clear();

        for entity in &snapshot.entities {
            let entity_cache = self.cache
                .entry(entity.entity_id)
                .or_insert_with(BTreeMap::new);

            for (type_id, component) in &entity.components {
                let field_cache = entity_cache
                    .entry(*type_id)
                    .or_insert_with(BTreeMap::new);
                Self::parse_component_json_into_cache(&component.data_json, field_cache);
            }
        }

        self.metrics.cache_rebuilds += 1;
    }

    /// Clears the entire cache.
    ///
    /// Use on transport reconnect before sending the initial SNAPSHOT.
    /// After clearing, the next DELTA will send all fields in full.
    pub fn clear_cache(&mut self) {
        self.cache.clear();
    }

    // ── Inspection ────────────────────────────────────────────────────────────

    /// Returns accumulated compression metrics.
    pub fn metrics(&self) -> &CompressorMetrics {
        &self.metrics
    }

    /// Returns the number of entities currently tracked in the cache.
    pub fn cached_entity_count(&self) -> usize {
        self.cache.len()
    }

    /// Returns the total number of (entity, component_type) pairs cached.
    pub fn cached_component_count(&self) -> usize {
        self.cache.values().map(|m| m.len()).sum()
    }

    /// Returns the total number of cached field values across all entities.
    pub fn cached_field_count(&self) -> usize {
        self.cache
            .values()
            .flat_map(|m| m.values())
            .map(|fc| fc.len())
            .sum()
    }

    // ── Internal Helpers ──────────────────────────────────────────────────────

    /// Parses a JSON object string into a field-name → value-string map.
    ///
    /// Uses `serde_json` to parse. If parsing fails (malformed JSON), the
    /// field cache is left empty — the next compress() will treat all fields
    /// as new and send them in full, which is safe.
    ///
    /// This does NOT recursively flatten nested objects — it stores the
    /// top-level field values as raw JSON strings. Nested objects are compared
    /// as opaque strings; any change to a nested field changes the string value.
    fn parse_component_json_into_cache(
        component_json: &str,
        cache: &mut ComponentFieldCache,
    ) {
        if let Ok(serde_json::Value::Object(map)) =
            serde_json::from_str::<serde_json::Value>(component_json)
        {
            for (key, value) in map {
                cache.insert(key, value.to_string());
            }
        }
        // Malformed JSON → leave cache empty → field will be sent in full
    }
}

impl Default for DeltaCompressor {
    fn default() -> Self {
        Self::new()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::wire::delta_payload::{
        DeltaPayload, WireEntityUpdate, WireComponentUpdate, WireFieldChange,
        WireSpawnedEntity, WireComponentData, WireDestroyedEntity, WireAddedComponent,
        WireRemovedComponent,
    };

    fn delta_with_update(
        tick: u64,
        entity_id: u64,
        type_id: u32,
        fields: Vec<(&str, &str)>,
    ) -> DeltaPayload {
        let mut payload = DeltaPayload::empty(tick, 1, "0.1.0");
        let wire_fields: Vec<WireFieldChange> = fields
            .into_iter()
            .map(|(k, v)| WireFieldChange::new(k, v))
            .collect();
        let update = WireComponentUpdate::new(type_id, "COMP_TEST", wire_fields);
        payload.add_component_update(entity_id, update);
        payload
    }

    // ── First Transmission ────────────────────────────────────────────────────

    #[test]
    fn first_send_passes_all_fields_through() {
        let mut c = DeltaCompressor::new();
        let mut payload = delta_with_update(1, 1, 1, vec![
            ("position", r#"{"x":0}"#),
            ("rotation", r#"{"w":1}"#),
        ]);
        c.compress(&mut payload);
        // Nothing was cached — both fields should survive
        let update = &payload.modified_entities[&1].component_updates[&1];
        assert_eq!(update.field_changes.len(), 2);
    }

    // ── Identical Second Send ─────────────────────────────────────────────────

    #[test]
    fn identical_second_send_eliminates_all_fields() {
        let mut c = DeltaCompressor::new();
        let fields = vec![("x", "1.0"), ("y", "2.0")];

        let mut p1 = delta_with_update(1, 1, 1, fields.clone());
        c.compress(&mut p1); // primes the cache

        let mut p2 = delta_with_update(2, 1, 1, fields);
        c.compress(&mut p2);

        // Both fields are unchanged → entity update should be eliminated
        assert!(!payload_has_entity_update(&p2, 1));
    }

    // ── Partial Change ────────────────────────────────────────────────────────

    #[test]
    fn only_changed_fields_survive_compression() {
        let mut c = DeltaCompressor::new();

        // First send: x=1, y=2
        let mut p1 = delta_with_update(1, 1, 1, vec![("x", "1.0"), ("y", "2.0")]);
        c.compress(&mut p1);

        // Second send: x unchanged, y changed
        let mut p2 = delta_with_update(2, 1, 1, vec![("x", "1.0"), ("y", "3.0")]);
        c.compress(&mut p2);

        let update = &p2.modified_entities[&1].component_updates[&1];
        assert_eq!(update.field_changes.len(), 1);
        assert_eq!(update.field_changes[0].field_name, "y");
        assert_eq!(update.field_changes[0].value_json, "3.0");
    }

    // ── New Field After First Send ────────────────────────────────────────────

    #[test]
    fn new_field_not_in_cache_always_passes_through() {
        let mut c = DeltaCompressor::new();
        let mut p1 = delta_with_update(1, 1, 1, vec![("x", "1.0")]);
        c.compress(&mut p1);

        // Second send adds a new field "z" not seen before
        let mut p2 = delta_with_update(2, 1, 1, vec![("x", "1.0"), ("z", "5.0")]);
        c.compress(&mut p2);

        let update = &p2.modified_entities[&1].component_updates[&1];
        // x is unchanged (eliminated), z is new (kept)
        assert_eq!(update.field_changes.len(), 1);
        assert_eq!(update.field_changes[0].field_name, "z");
    }

    // ── Spawn Populates Cache ─────────────────────────────────────────────────

    #[test]
    fn spawned_entity_fields_cached_for_next_compress() {
        let mut c = DeltaCompressor::new();

        // Spawn with initial component JSON
        let mut p1 = DeltaPayload::empty(1, 1, "0.1.0");
        let mut wire_entity = WireSpawnedEntity::new(1, "actor");
        wire_entity.add_component(WireComponentData::new(
            1, "COMP_TRANSFORM", r#"{"x":0,"y":0}"#,
        ));
        p1.add_spawn(wire_entity);
        c.compress(&mut p1);

        // Next tick: update with identical values — should be eliminated
        let mut p2 = delta_with_update(2, 1, 1, vec![("x", "0"), ("y", "0")]);
        c.compress(&mut p2);
        assert!(!payload_has_entity_update(&p2, 1));
    }

    // ── Destroy Evicts Cache ──────────────────────────────────────────────────

    #[test]
    fn destroyed_entity_evicted_from_cache() {
        let mut c = DeltaCompressor::new();

        let mut p1 = delta_with_update(1, 1, 1, vec![("x", "1.0")]);
        c.compress(&mut p1);
        assert_eq!(c.cached_entity_count(), 1);

        let mut p2 = DeltaPayload::empty(2, 2, "0.1.0");
        p2.add_destroy(WireDestroyedEntity::new(1));
        c.compress(&mut p2);

        assert_eq!(c.cached_entity_count(), 0);
    }

    // ── Rebuild From Snapshot ─────────────────────────────────────────────────

    #[test]
    fn rebuild_from_snapshot_populates_cache() {
        use xace_core::wire::snapshot_payload::{
            SnapshotPayload, SnapshotEntityRecord, SnapshotComponentRecord, SnapshotReason,
        };
        use xace_core::entity_state::EntityState;

        let mut c = DeltaCompressor::new();
        assert_eq!(c.cached_entity_count(), 0);

        let mut snapshot =
            SnapshotPayload::new(0, "0.1.0", 1, "", "hash", 0, SnapshotReason::InitialConnection);
        let mut entity = SnapshotEntityRecord::new(1, EntityState::Active);
        entity.add_component(SnapshotComponentRecord::new(
            1,
            "COMP_TRANSFORM",
            r#"{"x":10,"y":20}"#,
        ));
        snapshot.add_entity(entity);

        c.rebuild_from_snapshot(&snapshot);
        assert_eq!(c.cached_entity_count(), 1);
        assert_eq!(c.cached_component_count(), 1);
        assert_eq!(c.metrics().cache_rebuilds, 1);

        // Fields from snapshot should now be treated as cached
        let mut p1 = delta_with_update(1, 1, 1, vec![("x", "10"), ("y", "20")]);
        c.compress(&mut p1);
        assert!(!payload_has_entity_update(&p1, 1));
    }

    #[test]
    fn clear_cache_resets_all_entries() {
        let mut c = DeltaCompressor::new();
        let mut p1 = delta_with_update(1, 1, 1, vec![("x", "1")]);
        c.compress(&mut p1);
        assert_eq!(c.cached_entity_count(), 1);

        c.clear_cache();
        assert_eq!(c.cached_entity_count(), 0);
        assert_eq!(c.cached_field_count(), 0);
    }

    // ── Metrics ───────────────────────────────────────────────────────────────

    #[test]
    fn metrics_track_fields_before_and_after() {
        let mut c = DeltaCompressor::new();
        let mut p1 = delta_with_update(1, 1, 1, vec![("x", "1"), ("y", "2")]);
        c.compress(&mut p1);

        // Second send: x identical, y changed
        let mut p2 = delta_with_update(2, 1, 1, vec![("x", "1"), ("y", "99")]);
        c.compress(&mut p2);

        let m = c.metrics();
        // First compress: 2 fields before, 2 after (nothing cached)
        // Second compress: 2 fields before, 1 after (x eliminated)
        assert_eq!(m.fields_before, 4); // 2+2
        assert_eq!(m.fields_after, 3);  // 2+1
        assert_eq!(m.fields_eliminated(), 1);
    }

    #[test]
    fn metrics_count_entity_updates_eliminated() {
        let mut c = DeltaCompressor::new();
        let mut p1 = delta_with_update(1, 1, 1, vec![("x", "1")]);
        c.compress(&mut p1);

        let mut p2 = delta_with_update(2, 1, 1, vec![("x", "1")]); // identical
        c.compress(&mut p2);

        assert_eq!(c.metrics().entity_updates_eliminated, 1);
    }

    #[test]
    fn compression_ratio_zero_on_first_send() {
        let c = DeltaCompressor::new();
        assert_eq!(c.metrics().compression_ratio(), 0.0);
    }

    #[test]
    fn compression_ratio_high_when_mostly_unchanged() {
        let mut c = DeltaCompressor::new();
        let fields: Vec<(&str, &str)> = (0..10).map(|i| {
            let name = Box::leak(format!("field_{}", i).into_boxed_str()) as &str;
            (name, "same_value")
        }).collect();

        let mut p1 = delta_with_update(1, 1, 1, fields.clone());
        c.compress(&mut p1);

        let mut p2 = delta_with_update(2, 1, 1, fields);
        c.compress(&mut p2); // all unchanged

        assert!(c.metrics().compression_ratio() > 0.5);
    }

    // ── Helper ────────────────────────────────────────────────────────────────

    fn payload_has_entity_update(payload: &DeltaPayload, entity_id: u64) -> bool {
        payload.modified_entities.contains_key(&entity_id)
    }
}