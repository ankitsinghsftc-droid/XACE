//! # World Hasher
//!
//! Produces a deterministic SHA-256 hash of the entire world state
//! after every simulation tick. Same world state = same hash, always,
//! on any machine, any OS, any platform. (D9, D11)
//!
//! ## What Is Hashed
//! The hash is computed from three inputs in strict order:
//!   1. tick                   — the simulation tick number
//!   2. entity_store_snapshot  — all entity IDs and their states, sorted ASC (D3)
//!   3. component_tables_snapshot — all component rows, sorted by type_id then
//!                                  EntityID ASC (D3, D11)
//!
//! RNG state, event queue, and mutation queue are intentionally excluded:
//! - RNG stream positions are a function of (world_seed, system_id, tick) and
//!   are therefore already determinism-guaranteed by D6.
//! - Event queue and mutation queue are empty at clean tick boundaries (I10).
//!   Including transient queue state would produce different hashes for
//!   snapshots taken at identical world states but different queue positions.
//!
//! ## Why Not DefaultHasher
//! std::collections::hash_map::DefaultHasher is explicitly randomized per
//! Rust version and platform. It MUST NOT be used anywhere in XACE (D6, D11).
//! SHA-256 from the `sha2` crate produces identical bytes on every platform.
//!
//! ## Feed Order (D11)
//! All fields are fed into the hasher in a fixed, documented order.
//! BTreeMap iteration in WorldSnapshot guarantees ascending key order.
//! Floats are never hashed directly — they are serialized to fixed-precision
//! strings first to avoid platform-specific float representation differences (D8).
//!
//! ## Output Format
//! Returns a lowercase hex-encoded SHA-256 digest string (64 characters).
//! Example: "3b4c1a2d9f..." — stable, printable, log-friendly.

use sha2::{Digest, Sha256};
use xace_core::runtime::world_snapshot::WorldSnapshot;

// ── World Hasher ──────────────────────────────────────────────────────────────

/// Computes deterministic SHA-256 hashes of world state.
///
/// Stateless — all methods are associated functions.
/// The PhaseOrchestrator constructs one WorldHasher and uses it
/// every tick. The DeterminismGuard calls compute() via hook_tick_end.
pub struct WorldHasher;

impl WorldHasher {
    // ── Public API ────────────────────────────────────────────────────────────

    /// Computes the deterministic SHA-256 hash of the world state at this tick.
    ///
    /// Feeds tick + entity_store + component_tables into SHA-256 in a fixed,
    /// documented order. Returns a lowercase hex string (64 chars).
    ///
    /// This replaces `compute_world_hash_placeholder()` in determinism_guard.rs.
    /// After world_hasher.rs is integrated, update DeterminismGuard::hook_tick_end
    /// to call `WorldHasher::compute(snapshot)` instead of the placeholder.
    pub fn compute(snapshot: &WorldSnapshot) -> String {
        let mut hasher = Sha256::new();

        // Field 1: tick — unique per simulation step
        Self::feed_u64(&mut hasher, snapshot.tick);

        // Field 2: schema_version — D10: hash encodes the schema contract
        Self::feed_str(&mut hasher, &snapshot.schema_version);

        // Field 3: execution_plan_version
        Self::feed_u32(&mut hasher, snapshot.execution_plan_version);

        // Field 4: entity store — all entity records in EntityID ASC order (D3)
        Self::feed_entity_store(&mut hasher, snapshot);

        // Field 5: component tables — all rows in type_id ASC, EntityID ASC (D11)
        Self::feed_component_tables(&mut hasher, snapshot);

        // Finalize and hex-encode
        let digest = hasher.finalize();
        hex_encode(&digest)
    }

    /// Computes the hash and immediately validates it against an expected value.
    ///
    /// Returns Ok(computed_hash) if they match.
    /// Returns Err(computed_hash) if they differ — caller raises D9 violation.
    pub fn compute_and_validate(
        snapshot: &WorldSnapshot,
        expected_hash: &str,
    ) -> Result<String, String> {
        let computed = Self::compute(snapshot);
        if computed == expected_hash {
            Ok(computed)
        } else {
            Err(computed)
        }
    }

    /// Returns true if two snapshots produce the same world hash.
    ///
    /// Used by the determinism test suite to verify two independently
    /// constructed worlds are byte-identical (D9).
    pub fn are_equal(a: &WorldSnapshot, b: &WorldSnapshot) -> bool {
        Self::compute(a) == Self::compute(b)
    }

    // ── Feed Helpers ──────────────────────────────────────────────────────────

    /// Feeds a u64 as 8 big-endian bytes. Fixed width — no length ambiguity.
    fn feed_u64(hasher: &mut Sha256, value: u64) {
        hasher.update(value.to_be_bytes());
    }

    /// Feeds a u32 as 4 big-endian bytes.
    fn feed_u32(hasher: &mut Sha256, value: u32) {
        hasher.update(value.to_be_bytes());
    }

    /// Feeds a string as length-prefixed bytes.
    ///
    /// The 8-byte length prefix prevents collisions between adjacent string
    /// fields: feeding "ab" then "c" must not hash the same as "a" then "bc".
    fn feed_str(hasher: &mut Sha256, s: &str) {
        // Length prefix prevents feed("ab","c") == feed("a","bc")
        hasher.update((s.len() as u64).to_be_bytes());
        hasher.update(s.as_bytes());
    }

    /// Feeds a u8 as a single byte.
    fn feed_u8(hasher: &mut Sha256, value: u8) {
        hasher.update([value]);
    }

    /// Feeds the entity store into the hasher.
    ///
    /// EntityRecords are stored in the snapshot in EntityID ASC order (D3).
    /// We trust the snapshot ordering and feed records as-is.
    /// Per record: entity_id (u64) | state (u8) | created_tick (u64) |
    ///             destroyed_tick (u64) | tags_count (u64) | tag strings
    fn feed_entity_store(hasher: &mut Sha256, snapshot: &WorldSnapshot) {
        let store = &snapshot.entity_store_snapshot;

        // Record count prefix — prevents length-extension ambiguity
        Self::feed_u64(hasher, store.entities.len() as u64);

        for record in &store.entities {
            // entity_id
            Self::feed_u64(hasher, record.entity_id);

            // state — encode as u8 discriminant
            let state_byte: u8 = match record.state {
                xace_core::entity_state::EntityState::Active => 0,
                xace_core::entity_state::EntityState::Disabled => 1,
                xace_core::entity_state::EntityState::DestroyRequested => 2,
                xace_core::entity_state::EntityState::Destroyed => 3,
                xace_core::entity_state::EntityState::Archived => 4,
            };
            Self::feed_u8(hasher, state_byte);

            // lifecycle ticks
            Self::feed_u64(hasher, record.created_tick);
            Self::feed_u64(hasher, record.destroyed_tick);

            // tags — sorted alphabetically for determinism regardless of
            // insertion order (tags on EntityRecord are already sorted per spec)
            Self::feed_u64(hasher, record.tags.len() as u64);
            for tag in &record.tags {
                Self::feed_str(hasher, tag);
            }
        }

        // Feed next_entity_id — part of the ID reservation contract (D2)
        Self::feed_u64(hasher, store.next_entity_id);
    }

    /// Feeds all component tables into the hasher.
    ///
    /// Tables are stored in a BTreeMap<component_type_id → table> in the snapshot,
    /// guaranteeing ascending type_id iteration (D11).
    /// Within each table, rows are BTreeMap<EntityID → JSON>, guaranteeing
    /// ascending EntityID iteration (D3).
    ///
    /// Per table: type_id (u32) | row_count (u64) | per row: entity_id (u64) | json
    fn feed_component_tables(hasher: &mut Sha256, snapshot: &WorldSnapshot) {
        let tables = &snapshot.component_tables_snapshot;

        // Table count prefix
        Self::feed_u64(hasher, tables.tables.len() as u64);

        // BTreeMap iteration is ascending by key — type_id order is stable (D11)
        for (type_id, table) in &tables.tables {
            // component type identity
            Self::feed_u32(hasher, *type_id);
            Self::feed_str(hasher, &table.component_type_name);

            // row count prefix
            Self::feed_u64(hasher, table.rows.len() as u64);

            // BTreeMap<EntityID, String> — ascending EntityID order (D3)
            for (entity_id, component_json) in &table.rows {
                Self::feed_u64(hasher, *entity_id);
                // Component JSON must have stable key ordering — enforced by
                // SnapshotSerializer (Phase 5). We hash it as an opaque string.
                Self::feed_str(hasher, component_json);
            }
        }
    }
}

// ── Hex Encoding ──────────────────────────────────────────────────────────────

/// Encodes a byte slice as a lowercase hex string.
///
/// Hand-rolled to avoid pulling in another dependency.
/// Output is always 2× input length. SHA-256 → 64 chars.
fn hex_encode(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for &b in bytes {
        out.push(HEX[(b >> 4) as usize] as char);
        out.push(HEX[(b & 0x0f) as usize] as char);
    }
    out
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::entity_state::EntityState;
    use xace_core::runtime::world_snapshot::{ComponentTableSnapshot, EntityRecord, WorldSnapshot};

    // ── Helpers ───────────────────────────────────────────────────────────────

    fn empty_snap(tick: u64) -> WorldSnapshot {
        let mut s = WorldSnapshot::empty("0.1.0", 1, 42);
        s.tick = tick;
        s
    }

    fn snap_with_entity(tick: u64, entity_id: u64) -> WorldSnapshot {
        let mut s = empty_snap(tick);
        s.entity_store_snapshot
            .entities
            .push(EntityRecord::new(entity_id, EntityState::Active, 0));
        s.entity_store_snapshot.next_entity_id = entity_id + 1;
        s
    }

    fn snap_with_component(tick: u64, entity_id: u64, type_id: u32, json: &str) -> WorldSnapshot {
        let mut s = snap_with_entity(tick, entity_id);
        let mut table = ComponentTableSnapshot::new(type_id, "COMP_TEST_V1");
        table.set(entity_id, json);
        s.component_tables_snapshot.set_table(table);
        s
    }

    // ── Output Format ─────────────────────────────────────────────────────────

    #[test]
    fn hash_is_64_hex_chars() {
        let hash = WorldHasher::compute(&empty_snap(0));
        assert_eq!(hash.len(), 64, "SHA-256 hex must be 64 chars");
    }

    #[test]
    fn hash_is_lowercase_hex() {
        let hash = WorldHasher::compute(&empty_snap(0));
        assert!(hash.chars().all(|c| c.is_ascii_hexdigit()));
        assert!(hash.chars().all(|c| !c.is_uppercase()));
    }

    // ── Determinism ───────────────────────────────────────────────────────────

    #[test]
    fn same_empty_world_produces_same_hash() {
        let a = WorldHasher::compute(&empty_snap(0));
        let b = WorldHasher::compute(&empty_snap(0));
        assert_eq!(a, b, "Identical worlds must produce identical hashes (D9)");
    }

    #[test]
    fn different_ticks_produce_different_hashes() {
        let a = WorldHasher::compute(&empty_snap(1));
        let b = WorldHasher::compute(&empty_snap(2));
        assert_ne!(a, b, "Different ticks must produce different hashes");
    }

    #[test]
    fn are_equal_returns_true_for_identical_worlds() {
        let a = empty_snap(10);
        let b = empty_snap(10);
        assert!(WorldHasher::are_equal(&a, &b));
    }

    #[test]
    fn are_equal_returns_false_for_different_ticks() {
        let a = empty_snap(10);
        let b = empty_snap(11);
        assert!(!WorldHasher::are_equal(&a, &b));
    }

    // ── Entity Sensitivity ────────────────────────────────────────────────────

    #[test]
    fn adding_entity_changes_hash() {
        let base = WorldHasher::compute(&empty_snap(1));
        let with_entity = WorldHasher::compute(&snap_with_entity(1, 1));
        assert_ne!(base, with_entity, "Adding an entity must change the hash");
    }

    #[test]
    fn different_entity_ids_produce_different_hashes() {
        let a = WorldHasher::compute(&snap_with_entity(1, 1));
        let b = WorldHasher::compute(&snap_with_entity(1, 2));
        assert_ne!(a, b, "Different entity IDs must produce different hashes");
    }

    #[test]
    fn entity_state_changes_hash() {
        let mut active = snap_with_entity(1, 1);
        let mut disabled = snap_with_entity(1, 1);
        disabled.entity_store_snapshot.entities[0].state = EntityState::Disabled;
        assert_ne!(
            WorldHasher::compute(&active),
            WorldHasher::compute(&disabled),
            "Entity state change must change the hash"
        );
    }

    // ── Component Sensitivity ─────────────────────────────────────────────────

    #[test]
    fn adding_component_changes_hash() {
        let base = WorldHasher::compute(&snap_with_entity(1, 1));
        let with_comp = WorldHasher::compute(&snap_with_component(1, 1, 1, r#"{"x":0}"#));
        assert_ne!(base, with_comp, "Adding a component must change the hash");
    }

    #[test]
    fn different_component_values_produce_different_hashes() {
        let a = WorldHasher::compute(&snap_with_component(1, 1, 1, r#"{"x":1}"#));
        let b = WorldHasher::compute(&snap_with_component(1, 1, 1, r#"{"x":2}"#));
        assert_ne!(
            a, b,
            "Different component values must produce different hashes"
        );
    }

    #[test]
    fn same_component_values_produce_same_hash() {
        let a = WorldHasher::compute(&snap_with_component(1, 1, 1, r#"{"x":1}"#));
        let b = WorldHasher::compute(&snap_with_component(1, 1, 1, r#"{"x":1}"#));
        assert_eq!(
            a, b,
            "Identical component data must produce identical hash (D9)"
        );
    }

    // ── Schema Version Sensitivity ────────────────────────────────────────────

    #[test]
    fn different_schema_versions_produce_different_hashes() {
        let mut a = empty_snap(1);
        let mut b = empty_snap(1);
        b.schema_version = "0.2.0".into();
        assert_ne!(
            WorldHasher::compute(&a),
            WorldHasher::compute(&b),
            "Schema version must be part of the hash (D10)"
        );
    }

    // ── compute_and_validate ──────────────────────────────────────────────────

    #[test]
    fn validate_passes_for_correct_hash() {
        let snap = empty_snap(1);
        let hash = WorldHasher::compute(&snap);
        assert!(WorldHasher::compute_and_validate(&snap, &hash).is_ok());
    }

    #[test]
    fn validate_fails_for_wrong_hash() {
        let snap = empty_snap(1);
        let result = WorldHasher::compute_and_validate(&snap, "wrong_hash_xyz");
        assert!(result.is_err());
        // The Err value is the computed hash — caller uses it in D9 violation
        let computed = result.unwrap_err();
        assert_eq!(computed.len(), 64);
    }

    // ── Hex Encoding ──────────────────────────────────────────────────────────

    #[test]
    fn hex_encode_all_zeros() {
        assert_eq!(hex_encode(&[0u8; 4]), "00000000");
    }

    #[test]
    fn hex_encode_all_ff() {
        assert_eq!(hex_encode(&[0xffu8; 4]), "ffffffff");
    }

    #[test]
    fn hex_encode_known_bytes() {
        assert_eq!(hex_encode(&[0xde, 0xad, 0xbe, 0xef]), "deadbeef");
    }
}
