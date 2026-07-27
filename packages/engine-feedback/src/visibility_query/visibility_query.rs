//! # Visibility Query
//!
//! Defines the `VisibilityQuery` struct and its result type used in the
//! XACE ↔ Engine visibility raycast pipeline (Audit 6).
//!
//! ## Visibility Query Lifecycle
//! ```text
//! Tick N:
//!   AISystem sets COMP_PERCEPTION_V1.visibility_query_pending = true
//!   VisibilityQueryBatcher collects all pending flags → Vec<VisibilityQuery>
//!   IEngineAdapter::send_visibility_queries() sends batch to engine
//!
//! Tick N+1:
//!   Engine returns VisibilityQueryResultFeedback per query
//!   VisibilityFeedbackHandler writes result to COMP_PERCEPTION_V1
//!   AISystem reads can_see and distance from COMP_PERCEPTION_V1
//! ```
//!
//! ## One-Tick Delay (I13)
//! The one-tick delay is intentional and confirmed correct (CLAUDE.md).
//! Real raycasting is inherently asynchronous — the engine processes it
//! in its render/physics frame. Results arrive as feedback next tick.
//!
//! ## Query Deduplication
//! The same (observer, target) pair should not be queried more than once
//! per tick. The `VisibilityQueryBatcher` deduplicates before sending.
//! This file defines the canonical query struct used throughout the pipeline.

use serde::{Deserialize, Serialize};
use xace_core::entity_id::EntityID;

// ── Visibility Query ──────────────────────────────────────────────────────────

/// A single visibility raycast query from XACE to the engine.
///
/// Sent by `IEngineAdapter::send_visibility_queries()` as a batch.
/// The engine performs a raycast from observer to target and returns
/// a `VisibilityQueryResultFeedback` on the next tick.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct VisibilityQuery {
    /// The entity performing the visibility check (the observer).
    /// Must be non-zero — always a valid active entity.
    pub observer_entity_id: EntityID,

    /// The entity being checked for visibility (the target).
    /// Must be non-zero — always a valid active entity.
    pub target_entity_id: EntityID,

    /// Maximum raycast distance in world units.
    /// 0.0 means use the observer's detection_radius from COMP_PERCEPTION_V1.
    /// Negative values are invalid and rejected by the batcher.
    pub max_distance: f32,
}

impl VisibilityQuery {
    /// Creates a new visibility query with an explicit max distance.
    pub fn new(observer: EntityID, target: EntityID, max_distance: f32) -> Self {
        Self {
            observer_entity_id: observer,
            target_entity_id: target,
            max_distance,
        }
    }

    /// Creates a visibility query using the observer's configured detection radius.
    /// The engine uses COMP_PERCEPTION_V1.detection_radius for the raycast distance.
    pub fn with_default_range(observer: EntityID, target: EntityID) -> Self {
        Self {
            observer_entity_id: observer,
            target_entity_id: target,
            max_distance: 0.0,
        }
    }

    /// Returns true if this query has an explicit max distance (not using default).
    pub fn has_explicit_range(&self) -> bool {
        self.max_distance > 0.0
    }

    /// Returns the deduplication key for this query.
    /// The batcher uses this to eliminate duplicate (observer, target) pairs.
    /// Sorted so (A→B) and (B→A) are distinct — visibility is not symmetric.
    pub fn dedup_key(&self) -> (EntityID, EntityID) {
        (self.observer_entity_id, self.target_entity_id)
    }

    /// Validates this query is structurally sound.
    /// Returns Err with a description if invalid.
    pub fn validate(&self) -> Result<(), String> {
        if self.observer_entity_id == 0 {
            return Err("VisibilityQuery: observer_entity_id must not be NULL (0)".into());
        }
        if self.target_entity_id == 0 {
            return Err("VisibilityQuery: target_entity_id must not be NULL (0)".into());
        }
        if self.observer_entity_id == self.target_entity_id {
            return Err(format!(
                "VisibilityQuery: observer and target are the same entity ({})",
                self.observer_entity_id
            ));
        }
        if self.max_distance < 0.0 {
            return Err(format!(
                "VisibilityQuery: max_distance {} is negative",
                self.max_distance
            ));
        }
        Ok(())
    }
}

// ── Visibility Query Result ───────────────────────────────────────────────────

/// The result of one visibility raycast query.
///
/// Produced by `VisibilityResultStore` after the engine's
/// `VisibilityQueryResultFeedback` is processed by the handler.
/// Available for one tick — expires after the tick it was written.
#[derive(Debug, Clone, PartialEq)]
pub struct VisibilityQueryResult {
    /// The observer entity that submitted the query.
    pub observer_entity_id: EntityID,

    /// The target entity that was raycasted against.
    pub target_entity_id: EntityID,

    /// Whether the observer has line of sight to the target.
    pub can_see: bool,

    /// Distance between observer and target in world units.
    /// 0.0 if `can_see` is false and distance could not be measured.
    pub distance: f32,

    /// The tick this result was generated for.
    pub tick: u64,

    /// Whether this result has expired (older than one tick).
    pub is_expired: bool,
}

impl VisibilityQueryResult {
    pub fn new(
        observer: EntityID,
        target: EntityID,
        can_see: bool,
        distance: f32,
        tick: u64,
    ) -> Self {
        Self {
            observer_entity_id: observer,
            target_entity_id: target,
            can_see,
            distance,
            tick,
            is_expired: false,
        }
    }

    /// Returns true if this result can still be used at the given tick.
    /// Results expire after exactly one tick.
    pub fn is_valid_at(&self, current_tick: u64) -> bool {
        !self.is_expired && current_tick <= self.tick + 1
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn new_query_stores_fields() {
        let q = VisibilityQuery::new(1, 2, 50.0);
        assert_eq!(q.observer_entity_id, 1);
        assert_eq!(q.target_entity_id, 2);
        assert!((q.max_distance - 50.0).abs() < 1e-5);
    }

    #[test]
    fn default_range_query_has_zero_distance() {
        let q = VisibilityQuery::with_default_range(1, 2);
        assert_eq!(q.max_distance, 0.0);
        assert!(!q.has_explicit_range());
    }

    #[test]
    fn explicit_range_query_has_positive_distance() {
        let q = VisibilityQuery::new(1, 2, 30.0);
        assert!(q.has_explicit_range());
    }

    #[test]
    fn dedup_key_is_ordered_pair() {
        let q = VisibilityQuery::new(3, 7, 10.0);
        assert_eq!(q.dedup_key(), (3, 7));
        // Reverse direction is a different key
        let q2 = VisibilityQuery::new(7, 3, 10.0);
        assert_ne!(q.dedup_key(), q2.dedup_key());
    }

    #[test]
    fn validate_null_observer_fails() {
        let q = VisibilityQuery::new(0, 2, 10.0);
        assert!(q.validate().is_err());
    }

    #[test]
    fn validate_null_target_fails() {
        let q = VisibilityQuery::new(1, 0, 10.0);
        assert!(q.validate().is_err());
    }

    #[test]
    fn validate_self_query_fails() {
        let q = VisibilityQuery::new(5, 5, 10.0);
        assert!(q.validate().is_err());
    }

    #[test]
    fn validate_negative_distance_fails() {
        let q = VisibilityQuery::new(1, 2, -1.0);
        assert!(q.validate().is_err());
    }

    #[test]
    fn validate_zero_distance_passes() {
        let q = VisibilityQuery::new(1, 2, 0.0);
        assert!(q.validate().is_ok());
    }

    #[test]
    fn validate_valid_query_passes() {
        let q = VisibilityQuery::new(1, 2, 50.0);
        assert!(q.validate().is_ok());
    }

    #[test]
    fn result_valid_at_same_tick() {
        let r = VisibilityQueryResult::new(1, 2, true, 10.0, 5);
        assert!(r.is_valid_at(5));
    }

    #[test]
    fn result_valid_at_next_tick() {
        let r = VisibilityQueryResult::new(1, 2, true, 10.0, 5);
        assert!(r.is_valid_at(6)); // one tick later — still valid
    }

    #[test]
    fn result_expired_two_ticks_later() {
        let r = VisibilityQueryResult::new(1, 2, true, 10.0, 5);
        assert!(!r.is_valid_at(7)); // two ticks later — expired
    }

    #[test]
    fn result_marked_expired_is_invalid() {
        let mut r = VisibilityQueryResult::new(1, 2, true, 10.0, 5);
        r.is_expired = true;
        assert!(!r.is_valid_at(5));
    }
}
