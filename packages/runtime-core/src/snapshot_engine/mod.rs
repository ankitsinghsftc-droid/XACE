//! # Snapshot Engine Module
//! Deterministic world state capture and restore.

pub mod snapshot_completeness_policy;
pub mod snapshot_engine;
pub mod snapshot_serializer;
pub mod snapshot_store;

#[cfg(test)]
mod tests;

pub use snapshot_completeness_policy::{
    archived_entries_for_restore, policy_for, snapshot_completeness_policies,
    validate_restorable_snapshot, validate_snapshot_completeness_policy, SnapshotChannel,
    SnapshotCompletenessPolicy, SnapshotDisposition, SnapshotPolicyError,
    SnapshotRestoreCompletenessError,
};
pub use snapshot_engine::SnapshotEngine;
pub use snapshot_serializer::SnapshotSerializer;
pub use snapshot_store::{RetentionPolicy, SnapshotStore};
