//! # Snapshot Engine Module
//! Deterministic world state capture and restore.

pub mod delta_timeline_retention;
pub mod snapshot_completeness_policy;
pub mod snapshot_engine;
pub mod snapshot_serializer;
pub mod snapshot_store;

#[cfg(test)]
mod tests;

pub use delta_timeline_retention::{
    DeltaCompressedTimelineRetention, DeltaTimelineRestoreProof, DeltaTimelineRetentionConfig,
    DeltaTimelineRetentionStats, DEFAULT_DELTA_ANCHOR_INTERVAL_TICKS,
    DEFAULT_DELTA_TIMELINE_MAX_BYTES, DELTA_TIMELINE_STATS_SCHEMA, X10_047_MIN_SCRUB_TICKS,
};
pub use snapshot_completeness_policy::{
    archived_entries_for_restore, policy_for, snapshot_completeness_policies,
    validate_restorable_snapshot, validate_snapshot_completeness_policy, SnapshotChannel,
    SnapshotCompletenessPolicy, SnapshotDisposition, SnapshotPolicyError,
    SnapshotRestoreCompletenessError,
};
pub use snapshot_engine::SnapshotEngine;
pub use snapshot_serializer::SnapshotSerializer;
pub use snapshot_store::{RetentionPolicy, SnapshotStore};
