//! # Snapshot Serializer
//!
//! Deterministic serialization and deserialization of `WorldSnapshot`.
//!
//! ## Determinism Rules (D9, D11)
//! Identical world state must always produce identical serialized bytes. This
//! serializer relies on the `WorldSnapshot` serde schema plus `BTreeMap` fields
//! for stable key ordering. It must never deserialize into a lossy minimal
//! snapshot in production paths.
//!
//! ## Numeric Precision
//! Authoritative snapshot time uses `Fixed64`, serialized as transparent integer
//! micro-units. The legacy float formatting helpers remain for
//! non-authoritative display/tests only.

use sha2::{Digest, Sha256};
use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::runtime::world_snapshot::WorldSnapshot;

const FLOAT_PRECISION: usize = 6;

pub fn format_f32(value: f32) -> String {
    format!("{:.prec$}", value, prec = FLOAT_PRECISION)
}

pub fn format_f64(value: f64) -> String {
    format!("{:.prec$}", value, prec = FLOAT_PRECISION)
}

/// Deterministic full-schema `WorldSnapshot` serializer.
pub struct SnapshotSerializer;

impl SnapshotSerializer {
    pub fn new() -> Self {
        Self
    }

    /// Serializes a complete `WorldSnapshot` to canonical compact JSON.
    ///
    /// The output includes every authoritative snapshot field. `BTreeMap`
    /// storage inside the snapshot provides stable ordering for component
    /// tables, component rows, and RNG stream positions.
    pub fn serialize(&self, snapshot: &WorldSnapshot) -> Result<String, XaceError> {
        snapshot
            .validate()
            .map_err(|message| Self::validation_error("serialize", message, "world_snapshot"))?;
        Self::serialize_unchecked(snapshot)
    }

    /// Deserializes a complete `WorldSnapshot` from canonical JSON.
    ///
    /// Missing fields are rejected. This intentionally blocks the old
    /// `WorldSnapshot::minimal` fallback, because minimal deserialization drops
    /// entities, components, RNG, events, mutations, `cgs_hash`, `time_seconds`,
    /// and `is_clean`.
    pub fn deserialize(&self, json: &str) -> Result<WorldSnapshot, XaceError> {
        let snapshot: WorldSnapshot = serde_json::from_str(json).map_err(|err| {
            Self::validation_error("deserialize", err.to_string(), "world_snapshot")
        })?;
        snapshot
            .validate()
            .map_err(|message| Self::validation_error("deserialize", message, "world_snapshot"))?;
        Ok(snapshot)
    }

    /// Computes a deterministic serializer-level SHA-256 hash.
    ///
    /// This is separate from `WorldHasher`: it hashes the full canonical JSON
    /// image after clearing `world_hash` so a snapshot does not hash its own
    /// stored digest.
    pub fn compute_hash(&self, snapshot: &WorldSnapshot) -> Result<String, XaceError> {
        let mut canonical_snapshot = snapshot.clone();
        canonical_snapshot.world_hash.clear();
        let serialized = Self::serialize_unchecked(&canonical_snapshot)?;
        Ok(self.hash_string(&serialized))
    }

    pub fn hash_string(&self, input: &str) -> String {
        let digest = Sha256::digest(input.as_bytes());
        hex_encode(&digest)
    }

    pub fn display_hash_prefix(&self, hash: &str) -> String {
        hash.chars().take(16).collect()
    }

    fn serialize_unchecked(snapshot: &WorldSnapshot) -> Result<String, XaceError> {
        serde_json::to_string(snapshot)
            .map_err(|err| Self::validation_error("serialize", err.to_string(), "world_snapshot"))
    }

    fn validation_error(
        operation: &'static str,
        message: impl Into<String>,
        failed_path: impl Into<String>,
    ) -> XaceError {
        XaceError::ValidationFailure {
            message: message.into(),
            context: ErrorContext::new("SnapshotSerializer", operation),
            rule_violated: "X10-013".into(),
            failed_path: failed_path.into(),
        }
    }
}

impl Default for SnapshotSerializer {
    fn default() -> Self {
        Self::new()
    }
}

fn hex_encode(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for &byte in bytes {
        out.push(HEX[(byte >> 4) as usize] as char);
        out.push(HEX[(byte & 0x0f) as usize] as char);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::determinism_guard::world_hasher::WorldHasher;
    use xace_core::entity_state::EntityState;
    use xace_core::fixed_point::Fixed64;
    use xace_core::runtime::world_snapshot::{
        ComponentTableSnapshot, ComponentTablesSnapshot, EntityRecord, EntityStoreSnapshot,
        EventQueueState, MutationQueueState, RngState,
    };

    fn minimal_snapshot(tick: u64) -> WorldSnapshot {
        WorldSnapshot::minimal(tick, "0.1.0".into(), "a".repeat(64))
    }

    fn rich_snapshot(seed: u64) -> WorldSnapshot {
        let base_id = seed.saturating_mul(10).saturating_add(1);

        let mut active = EntityRecord::new(base_id, EntityState::Active, seed);
        active.tags = vec!["player".to_string(), format!("seed_{seed}")];

        let mut disabled = EntityRecord::new(base_id + 1, EntityState::Disabled, seed + 1);
        disabled.tags = vec!["npc".to_string()];

        let mut archived = EntityRecord::new(base_id + 2, EntityState::Archived, seed + 2);
        archived.destroyed_tick = seed + 9;
        archived.tags = vec!["archived".to_string()];

        let entity_store_snapshot = EntityStoreSnapshot {
            entities: vec![active.clone(), disabled.clone(), archived],
            next_entity_id: base_id + 3,
        };

        let mut transform =
            ComponentTableSnapshot::new(1, format!("COMP_TRANSFORM_V{}", seed % 3 + 1));
        transform.set(
            active.entity_id,
            format!(
                r#"{{"position_x":{},"position_y":{},"position_z":{}}}"#,
                seed as i64 * 1_000_000,
                seed as i64 * 2_000_000,
                -(seed as i64) * 1_000_000
            ),
        );
        transform.set(
            disabled.entity_id,
            format!(r#"{{"position_x":{},"position_y":0,"position_z":0}}"#, seed),
        );

        let mut identity = ComponentTableSnapshot::new(2, "COMP_IDENTITY_V1");
        identity.set(
            active.entity_id,
            format!(r#"{{"name":"hero_{seed}","class":"tester"}}"#),
        );

        let mut component_tables_snapshot = ComponentTablesSnapshot::empty();
        component_tables_snapshot.set_table(transform);
        component_tables_snapshot.set_table(identity);

        let mut rng_state = RngState::new(9_000 + seed);
        rng_state.set_stream_position("sys_loot", seed + 1);
        rng_state.set_stream_position(&format!("sys_seed_{seed}"), seed * 2 + 3);

        let event_queue_state = EventQueueState {
            pending_events: vec![
                format!(r#"{{"event_id":{},"kind":"damage"}}"#, seed + 100),
                format!(r#"{{"event_id":{},"kind":"pickup"}}"#, seed + 101),
            ],
            next_event_id: seed + 102,
        };

        let mutation_queue_state = MutationQueueState {
            pending_spawns: vec![format!(r#"{{"actor_id":"actor_{seed}"}}"#)],
            pending_additions: vec![format!(
                r#"{{"entity_id":{},"component_type_id":5}}"#,
                active.entity_id
            )],
            pending_modifications: vec![format!(
                r#"{{"entity_id":{},"component_type_id":1,"field":"position_x"}}"#,
                active.entity_id
            )],
            pending_removals: vec![format!(
                r#"{{"entity_id":{},"component_type_id":2}}"#,
                disabled.entity_id
            )],
            pending_destroys: vec![format!(r#"{{"entity_id":{}}}"#, disabled.entity_id)],
        };

        let mut snapshot = WorldSnapshot {
            tick: seed + 40,
            time_seconds: Fixed64::from_millis((seed as i64 + 1) * 16),
            schema_version: format!("0.1.{}", seed % 5),
            execution_plan_version: (seed as u32 % 7) + 1,
            cgs_hash: format!("{:064x}", seed + 1),
            entity_store_snapshot,
            component_tables_snapshot,
            rng_state,
            event_queue_state,
            mutation_queue_state,
            world_hash: String::new(),
            is_clean: false,
        };
        snapshot.world_hash = WorldHasher::compute(&snapshot);
        snapshot
    }

    fn assert_snapshot_authoritative_eq(expected: &WorldSnapshot, actual: &WorldSnapshot) {
        assert_eq!(actual.tick, expected.tick);
        assert_eq!(actual.time_seconds, expected.time_seconds);
        assert_eq!(actual.schema_version, expected.schema_version);
        assert_eq!(
            actual.execution_plan_version,
            expected.execution_plan_version
        );
        assert_eq!(actual.cgs_hash, expected.cgs_hash);
        assert_eq!(actual.entity_store_snapshot, expected.entity_store_snapshot);
        assert_eq!(
            actual.component_tables_snapshot,
            expected.component_tables_snapshot
        );
        assert_eq!(actual.rng_state, expected.rng_state);
        assert_eq!(actual.event_queue_state, expected.event_queue_state);
        assert_eq!(actual.mutation_queue_state, expected.mutation_queue_state);
        assert_eq!(actual.world_hash, expected.world_hash);
        assert_eq!(actual.is_clean, expected.is_clean);
    }

    #[test]
    fn serialize_produces_string() {
        let ser = SnapshotSerializer::new();
        let snap = minimal_snapshot(42);
        let result = ser.serialize(&snap);
        assert!(result.is_ok());
        let json = result.unwrap();
        assert!(json.contains("42"));
        assert!(json.contains("0.1.0"));
    }

    #[test]
    fn serialize_is_deterministic() {
        let ser = SnapshotSerializer::new();
        let snap = rich_snapshot(100);
        let s1 = ser.serialize(&snap).unwrap();
        let s2 = ser.serialize(&snap).unwrap();
        assert_eq!(s1, s2);
    }

    #[test]
    fn two_identical_snapshots_same_output() {
        let ser = SnapshotSerializer::new();
        let s1 = ser.serialize(&rich_snapshot(50)).unwrap();
        let s2 = ser.serialize(&rich_snapshot(50)).unwrap();
        assert_eq!(s1, s2);
    }

    #[test]
    fn different_ticks_different_output() {
        let ser = SnapshotSerializer::new();
        let s1 = ser.serialize(&minimal_snapshot(1)).unwrap();
        let s2 = ser.serialize(&minimal_snapshot(2)).unwrap();
        assert_ne!(s1, s2);
    }

    #[test]
    fn hash_deterministic() {
        let ser = SnapshotSerializer::new();
        let snap = rich_snapshot(77);
        let h1 = ser.compute_hash(&snap).unwrap();
        let h2 = ser.compute_hash(&snap).unwrap();
        assert_eq!(h1, h2);
    }

    #[test]
    fn hash_does_not_hash_its_own_world_hash_field() {
        let ser = SnapshotSerializer::new();
        let mut snap = rich_snapshot(77);
        let h1 = ser.compute_hash(&snap).unwrap();
        snap.world_hash = h1.clone();
        let h2 = ser.compute_hash(&snap).unwrap();
        assert_eq!(h1, h2);
    }

    #[test]
    fn different_snapshots_different_hash() {
        let ser = SnapshotSerializer::new();
        let h1 = ser.compute_hash(&minimal_snapshot(1)).unwrap();
        let h2 = ser.compute_hash(&minimal_snapshot(2)).unwrap();
        assert_ne!(h1, h2);
    }

    #[test]
    fn hash_is_hex_string() {
        let ser = SnapshotSerializer::new();
        let snap = minimal_snapshot(0);
        let hash = ser.compute_hash(&snap).unwrap();
        assert_eq!(hash.len(), 64);
        assert!(hash.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn format_f32_fixed_precision() {
        assert_eq!(format_f32(1.0), "1.000000");
        assert_eq!(format_f32(3.14159), "3.141590");
        assert_eq!(format_f32(0.0), "0.000000");
    }

    #[test]
    fn format_f64_fixed_precision() {
        assert_eq!(format_f64(1.0), "1.000000");
        assert_eq!(format_f64(2.718281), "2.718281");
    }

    #[test]
    fn hash_string_stable() {
        let ser = SnapshotSerializer::new();
        let h1 = ser.hash_string("hello world");
        let h2 = ser.hash_string("hello world");
        assert_eq!(h1, h2);
        assert_eq!(h1.len(), 64);
        assert_ne!(h1, ser.hash_string("hello world!"));
    }

    #[test]
    fn display_hash_prefix_is_non_authoritative() {
        let ser = SnapshotSerializer::new();
        let hash = ser.hash_string("hello world");
        let prefix = ser.display_hash_prefix(&hash);
        assert_eq!(prefix.len(), 16);
        assert_ne!(prefix, hash);
    }

    #[test]
    fn serialized_json_contains_required_fields() {
        let ser = SnapshotSerializer::new();
        let json = ser.serialize(&minimal_snapshot(10)).unwrap();
        assert!(json.contains("tick"));
        assert!(json.contains("time_seconds"));
        assert!(json.contains("schema_version"));
        assert!(json.contains("execution_plan_version"));
        assert!(json.contains("cgs_hash"));
        assert!(json.contains("entity_store_snapshot"));
        assert!(json.contains("component_tables_snapshot"));
        assert!(json.contains("rng_state"));
        assert!(json.contains("event_queue_state"));
        assert!(json.contains("mutation_queue_state"));
        assert!(json.contains("world_hash"));
        assert!(json.contains("is_clean"));
    }

    #[test]
    fn x10_013_full_snapshot_roundtrip_preserves_authoritative_fields() {
        let ser = SnapshotSerializer::new();
        let snapshot = rich_snapshot(13);
        let json = ser.serialize(&snapshot).unwrap();
        let decoded = ser.deserialize(&json).unwrap();

        assert_snapshot_authoritative_eq(&snapshot, &decoded);
        assert_eq!(ser.serialize(&decoded).unwrap(), json);
        assert_eq!(WorldHasher::compute(&decoded), snapshot.world_hash);
    }

    #[test]
    fn x10_013_snapshot_roundtrip_fuzz_preserves_all_authoritative_fields() {
        let ser = SnapshotSerializer::new();

        for seed in 0..32 {
            let snapshot = rich_snapshot(seed);
            let json = ser.serialize(&snapshot).unwrap();
            let decoded = ser.deserialize(&json).unwrap();

            assert_snapshot_authoritative_eq(&snapshot, &decoded);
            assert_eq!(ser.serialize(&decoded).unwrap(), json);
            assert_eq!(
                ser.compute_hash(&decoded).unwrap(),
                ser.compute_hash(&snapshot).unwrap()
            );
        }
    }

    #[test]
    fn x10_013_deserialize_rejects_legacy_minimal_json() {
        let ser = SnapshotSerializer::new();
        let legacy = r#"{"tick":5,"schema_version":"0.1.0","world_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}"#;
        let err = ser.deserialize(legacy).unwrap_err();
        let message = format!("{err:?}");
        assert!(message.contains("X10-013"));
        assert!(message.contains("world_snapshot"));
    }

    #[test]
    fn x10_013_deserialize_rejects_empty_world_hash() {
        let ser = SnapshotSerializer::new();
        let mut snapshot = rich_snapshot(3);
        snapshot.world_hash.clear();
        let json = serde_json::to_string(&snapshot).unwrap();

        let err = ser.deserialize(&json).unwrap_err();
        let message = format!("{err:?}");
        assert!(message.contains("X10-013"));
        assert!(message.contains("world_hash"));
    }
}
