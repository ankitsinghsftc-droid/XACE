//! # Entity ID
//!
//! Defines the core identity primitive for all entities in the XACE runtime.
//! Every entity that has ever existed — alive or destroyed — has a unique EntityID.
//!
//! ## Design Rules (from CLAUDE.md)
//! - EntityID is a u64 type alias, not a struct — zero overhead, maximum compatibility
//! - NULL_ENTITY_ID = 0 is permanently reserved and never generated
//! - IDs are monotonically increasing and never reused — destroyed entity IDs are archived
//! - Generator is thread-safe via AtomicU64 — safe for parallel system execution

use std::sync::atomic::{AtomicU64, Ordering};

// ── Type Alias ────────────────────────────────────────────────────────────────

/// The unique identifier for every entity in the XACE world.
///
/// A u64 type alias — not a newtype struct — so it carries zero runtime overhead
/// and works directly as a map key without wrapping or unwrapping.
///
/// EntityIDs are:
/// - Globally unique within a world session
/// - Monotonically increasing (never reused)
/// - Sorted ascending for deterministic iteration (D3)
/// - Archived permanently on entity destruction (D2)
pub type EntityID = u64;

// ── Constants ─────────────────────────────────────────────────────────────────

/// The null / sentinel entity ID. Permanently reserved. Never generated.
///
/// Used to represent "no entity" in optional references such as
/// `parent_entity_id` in COMP_TRANSFORM_V1. Any component field holding
/// NULL_ENTITY_ID means "this reference is intentionally empty."
///
/// The generator counter starts at 1 and never returns to 0, so this
/// value can never appear as a live entity ID.
pub const NULL_ENTITY_ID: EntityID = 0;

// ── Generator ─────────────────────────────────────────────────────────────────

/// Generates unique, monotonically increasing EntityIDs.
///
/// Thread-safe via `AtomicU64` — multiple systems running in parallel
/// during Phase 4 (parallel execution) can safely request IDs concurrently
/// without locks or races.
///
/// ## Guarantees
/// - First ID generated is always 1
/// - Each subsequent ID is exactly previous + 1
/// - Counter never wraps (u64 max ~1.8 × 10¹⁹ — effectively infinite)
/// - Never returns NULL_ENTITY_ID (0)
pub struct EntityIdGenerator {
    /// The internal atomic counter. Starts at 1.
    /// Uses `fetch_add` with `Relaxed` ordering — ID uniqueness is guaranteed
    /// by the atomic increment itself, not by memory visibility ordering.
    counter: AtomicU64,
}

impl EntityIdGenerator {
    /// Creates a new generator. Counter starts at 1.
    /// NULL_ENTITY_ID (0) is permanently skipped.
    pub fn new() -> Self {
        Self {
            counter: AtomicU64::new(1),
        }
    }

    /// Generates the next unique EntityID.
    ///
    /// Atomically increments the counter and returns the previous value.
    /// Safe to call from multiple threads simultaneously.
    ///
    /// ## Guarantees
    /// - Return value is always > 0 (never NULL_ENTITY_ID)
    /// - Return value is unique across all calls on this generator instance
    /// - Return values are strictly increasing
    pub fn next_id(&self) -> EntityID {
        self.counter.fetch_add(1, Ordering::Relaxed)
    }

    /// Returns the next ID that *would* be generated, without consuming it.
    ///
    /// Useful for tests and snapshot serialization. Does not advance the counter.
    pub fn peek_next(&self) -> EntityID {
        self.counter.load(Ordering::Relaxed)
    }

    /// Restores the generator counter to a specific value.
    ///
    /// Used exclusively during snapshot restoration (Phase 5) to ensure
    /// that after a rollback, newly generated IDs never collide with
    /// IDs that existed before the snapshot was taken.
    ///
    /// ## Safety
    /// Caller must ensure `value` is greater than any EntityID currently
    /// in the EntityStore. This is enforced by SnapshotEngine, not here.
    pub fn restore_to(&self, value: EntityID) {
        self.counter.store(value, Ordering::Relaxed);
    }
}

impl Default for EntityIdGenerator {
    fn default() -> Self {
        Self::new()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn first_id_is_never_null() {
        let gen = EntityIdGenerator::new();
        assert_ne!(gen.next_id(), NULL_ENTITY_ID);
    }

    #[test]
    fn ids_are_monotonically_increasing() {
        let gen = EntityIdGenerator::new();
        let a = gen.next_id();
        let b = gen.next_id();
        let c = gen.next_id();
        assert!(a < b && b < c);
    }

    #[test]
    fn peek_does_not_advance_counter() {
        let gen = EntityIdGenerator::new();
        let peeked = gen.peek_next();
        let generated = gen.next_id();
        assert_eq!(peeked, generated);
    }

    #[test]
    fn restore_sets_counter_correctly() {
        let gen = EntityIdGenerator::new();
        gen.next_id(); // consume 1
        gen.next_id(); // consume 2
        gen.restore_to(1000);
        assert_eq!(gen.next_id(), 1000);
    }

    #[test]
    fn null_entity_id_is_zero() {
        assert_eq!(NULL_ENTITY_ID, 0u64);
    }
}// EntityID type alias (u64), NULL_ENTITY_ID constant, EntityIdGenerator — monotonic, never reuses IDs, thread-safe
