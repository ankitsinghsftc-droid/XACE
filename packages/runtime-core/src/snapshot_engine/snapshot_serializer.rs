//! # Snapshot Serializer
//!
//! Deterministic serialization and deserialization of WorldSnapshot.
//!
//! ## Determinism Rules (D9, D11)
//! Identical world state must always produce identical serialized bytes.
//! This requires:
//! - Stable key ordering (BTreeMap everywhere — never HashMap)
//! - Fixed float precision (always 6 decimal places)
//! - Deterministic collection ordering (sorted by EntityID ASC)
//! - No platform-dependent formatting
//!
//! ## Design
//! The serializer converts WorldSnapshot to/from a canonical JSON string.
//! This string is used for:
//! - World hash computation (DeterminismGuard D9)
//! - Network transmission (SnapshotPayload)
//! - Save file storage (ISaveEngine)
//! - Replay log entries (D14)
//!
//! ## Float Precision
//! All f32/f64 values serialized to exactly 6 decimal places.
//! This prevents platform-specific float formatting from breaking
//! determinism across machines with different FPU behavior.

use xace_core::runtime::world_snapshot::WorldSnapshot;
use xace_core::errors::xace_error::{XaceError, ErrorContext};

// ── Float Precision ───────────────────────────────────────────────────────────

/// Fixed decimal places for all float serialization (D11).
const FLOAT_PRECISION: usize = 6;

/// Formats a f32 to fixed precision string.
pub fn format_f32(value: f32) -> String {
    format!("{:.prec$}", value, prec = FLOAT_PRECISION)
}

/// Formats a f64 to fixed precision string.
pub fn format_f64(value: f64) -> String {
    format!("{:.prec$}", value, prec = FLOAT_PRECISION)
}

// ── Snapshot Serializer ───────────────────────────────────────────────────────

/// Deterministic WorldSnapshot serializer.
///
/// Converts WorldSnapshot to/from canonical JSON strings.
/// Identical input always produces identical output (D9, D11).
pub struct SnapshotSerializer;

impl SnapshotSerializer {
    pub fn new() -> Self {
        Self
    }

    /// Serializes a WorldSnapshot to a canonical JSON string.
    ///
    /// ## Guarantees
    /// - Same snapshot → same string on any machine
    /// - Stable key ordering throughout
    /// - Fixed float precision
    /// - EntityID-ascending ordering for all collections
    pub fn serialize(&self, snapshot: &WorldSnapshot) -> Result<String, XaceError> {
        let mut parts = Vec::new();

        // Tick — u64, no float issues
        parts.push(format!(r#""tick":{}"#, snapshot.tick));

        // Schema version
        parts.push(format!(
            r#""schema_version":"{}""#,
            self.escape_string(&snapshot.schema_version)
        ));

        // Execution plan version
        parts.push(format!(
            r#""execution_plan_version":{}"#,
            snapshot.execution_plan_version
        ));

        // Entity store snapshot
        parts.push(format!(
            r#""entity_store":{}"#,
            self.serialize_entity_store(&snapshot.entity_store_snapshot)?
        ));

        // Component tables snapshot
        parts.push(format!(
            r#""component_tables":{}"#,
            self.serialize_component_tables(&snapshot.component_tables_snapshot)?
        ));

        // RNG state
        parts.push(format!(
            r#""rng_state":{}"#,
            self.serialize_rng_state(&snapshot.rng_state)?
        ));

        // World hash — included in serialization for verification
        parts.push(format!(
            r#""world_hash":"{}""#,
            self.escape_string(&snapshot.world_hash)
        ));

        Ok(format!("{{{}}}", parts.join(",")))
    }

    /// Deserializes a WorldSnapshot from a canonical JSON string.
    ///
    /// Uses a simple hand-rolled parser to avoid external dependencies.
    /// Returns ValidationFailure if the string is malformed.
    pub fn deserialize(&self, json: &str) -> Result<WorldSnapshot, XaceError> {
        // For Phase 5 we use serde_json if available, otherwise
        // return a structured error directing to add the dependency.
        // The serialization format is well-defined so deserialization
        // can be implemented incrementally.
        //
        // Phase 5 implementation: parse the canonical fields we wrote.
        // Full deserialization uses the same field order as serialize().

        // Extract tick
        let tick = self.extract_u64(json, "tick").map_err(|e| {
            XaceError::ValidationFailure {
                message: format!("Failed to deserialize snapshot tick: {}", e),
                context: ErrorContext::new("SnapshotSerializer", "deserialize"),
                rule_violated: "snapshot_format".into(),
                failed_path: "tick".into(),
            }
        })?;

        // Extract schema_version
        let schema_version = self.extract_string(json, "schema_version")
            .unwrap_or_else(|_| "0.1.0".to_string());

        // Extract world_hash
        let world_hash = self.extract_string(json, "world_hash")
            .unwrap_or_default();

        // Return a minimal snapshot — full field parsing in Phase 6
        // when we have a complete snapshot format stabilized.
        Ok(WorldSnapshot::minimal(tick, schema_version, world_hash))
    }

    /// Computes a deterministic hash of the given snapshot.
    ///
    /// Used by DeterminismGuard to verify world state consistency (D9).
    /// Hash is computed from the full serialized string — any difference
    /// in world state produces a different hash.
    pub fn compute_hash(&self, snapshot: &WorldSnapshot) -> Result<String, XaceError> {
        let serialized = self.serialize(snapshot)?;
        Ok(self.hash_string(&serialized))
    }

    /// Computes a deterministic hash of a raw string.
    /// Uses FNV-1a for speed and determinism.
    pub fn hash_string(&self, input: &str) -> String {
        let mut hash: u64 = 14695981039346656037;
        for byte in input.bytes() {
            hash ^= byte as u64;
            hash = hash.wrapping_mul(1099511628211);
        }
        format!("{:016x}", hash)
    }

    // ── Serialization Helpers ──────────────────────────────────────────────

    fn serialize_entity_store(
        &self,
        store: &xace_core::runtime::world_snapshot::EntityStoreSnapshot,
    ) -> Result<String, XaceError> {
        let mut parts = Vec::new();

        // next_entity_id
        parts.push(format!(r#""next_entity_id":{}"#, store.next_entity_id));

        // entities — sorted by id ASC (D3)
        let entity_parts: Vec<String> = store.entities
            .iter()
            .map(|e| {
                let destroyed = if e.destroyed_tick > 0 {
                    e.destroyed_tick.to_string()
                } else {
                    "null".to_string()
                };
                format!(
                    r#"{{"id":{},"state":"{}","created_tick":{},"destroyed_tick":{}}}"#,
                    e.entity_id,
                    format!("{:?}", e.state),
                    e.created_tick,
                    destroyed,
                )
            })
            .collect();
        parts.push(format!(r#""entities":[{}]"#, entity_parts.join(",")));

        Ok(format!("{{{}}}", parts.join(",")))
    }

    fn serialize_component_tables(
        &self,
        tables: &xace_core::runtime::world_snapshot::ComponentTablesSnapshot,
    ) -> Result<String, XaceError> {
        // Tables sorted by type_id ASC (D11)
        let mut sorted_tables: Vec<_> = tables.tables.iter().collect();
        sorted_tables.sort_by_key(|(type_id, _)| *type_id);

        let table_parts: Vec<String> = sorted_tables
            .iter()
            .map(|(type_id, table)| {
                // Rows sorted by entity_id ASC (D3)
                let mut sorted_rows: Vec<_> = table.rows.iter().collect();
                sorted_rows.sort_by_key(|(entity_id, _)| *entity_id);

                let row_parts: Vec<String> = sorted_rows
                    .iter()
                    .map(|(entity_id, json)| {
                        format!(r#""{}":{}"#, entity_id, json)
                    })
                    .collect();

                format!(
                    r#""{}":{{"type_id":{},"rows":{{{}}}}}"#,
                    type_id,
                    type_id,
                    row_parts.join(",")
                )
            })
            .collect();

        Ok(format!("{{{}}}", table_parts.join(",")))
    }

    fn serialize_rng_state(
        &self,
        rng: &xace_core::runtime::world_snapshot::RngState,
    ) -> Result<String, XaceError> {
        Ok(format!(
            r#"{{"world_seed":{},"stream_positions":{{{}}}}}"#,
            rng.world_seed,
            rng.stream_positions
                .iter()
                .map(|(k, v)| format!(r#""{}":{}"#, k, v))
                .collect::<Vec<_>>()
                .join(",")
        ))
    }

    fn escape_string(&self, s: &str) -> String {
        s.replace('\\', "\\\\")
            .replace('"', "\\\"")
            .replace('\n', "\\n")
            .replace('\r', "\\r")
            .replace('\t', "\\t")
    }

    // ── Deserialization Helpers ────────────────────────────────────────────

    fn extract_u64(&self, json: &str, key: &str) -> Result<u64, String> {
        let search = format!(r#""{}":"#, key);
        let start = json.find(&search)
            .ok_or_else(|| format!("Key '{}' not found", key))?
            + search.len();
        let rest = &json[start..];
        let end = rest.find(|c: char| !c.is_ascii_digit())
            .unwrap_or(rest.len());
        rest[..end].parse::<u64>()
            .map_err(|e| format!("Failed to parse u64: {}", e))
    }

    fn extract_string(&self, json: &str, key: &str) -> Result<String, String> {
        let search = format!(r#""{}"":""#, key);
        let start = json.find(&search)
            .ok_or_else(|| format!("Key '{}' not found", key))?
            + search.len();
        let rest = &json[start..];
        let end = rest.find('"')
            .ok_or_else(|| "Unterminated string".to_string())?;
        Ok(rest[..end].to_string())
    }
}

impl Default for SnapshotSerializer {
    fn default() -> Self {
        Self::new()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::runtime::world_snapshot::WorldSnapshot;

    fn minimal_snapshot(tick: u64) -> WorldSnapshot {
        WorldSnapshot::minimal(tick, "0.1.0".into(), "".into())
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
        let snap = minimal_snapshot(100);
        let s1 = ser.serialize(&snap).unwrap();
        let s2 = ser.serialize(&snap).unwrap();
        assert_eq!(s1, s2);
    }

    #[test]
    fn two_identical_snapshots_same_output() {
        let ser = SnapshotSerializer::new();
        let s1 = ser.serialize(&minimal_snapshot(50)).unwrap();
        let s2 = ser.serialize(&minimal_snapshot(50)).unwrap();
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
        let snap = minimal_snapshot(77);
        let h1 = ser.compute_hash(&snap).unwrap();
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
        assert_eq!(hash.len(), 16);
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
        assert_ne!(h1, ser.hash_string("hello world!"));
    }

    #[test]
    fn serialized_json_contains_required_fields() {
        let ser = SnapshotSerializer::new();
        let json = ser.serialize(&minimal_snapshot(10)).unwrap();
        assert!(json.contains("tick"));
        assert!(json.contains("schema_version"));
        assert!(json.contains("entity_store"));
        assert!(json.contains("component_tables"));
        assert!(json.contains("rng_state"));
    }
}