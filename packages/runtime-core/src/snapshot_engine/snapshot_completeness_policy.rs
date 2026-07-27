//! Executable snapshot completeness contract for X10-012.
//!
//! WorldSnapshot restore is production-supported at clean tick boundaries. Core
//! state must be present in the snapshot. Runtime buffers that are not
//! authoritative world state must have an explicit exclusion and restore action.

use std::collections::BTreeSet;
use std::fmt;

use xace_core::entity_id::EntityID;
use xace_core::entity_metadata::Tick;
use xace_core::entity_state::EntityState;
use xace_core::runtime::world_snapshot::WorldSnapshot;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SnapshotChannel {
    EntityRecords,
    ComponentTables,
    ArchivedEntities,
    RngStreamPositions,
    EventQueue,
    MutationQueue,
    Feedback,
    NetworkSync,
    SaveState,
    AdapterSideEffects,
}

impl SnapshotChannel {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::EntityRecords => "entity_records",
            Self::ComponentTables => "component_tables",
            Self::ArchivedEntities => "archived_entities",
            Self::RngStreamPositions => "rng_stream_positions",
            Self::EventQueue => "event_queue",
            Self::MutationQueue => "mutation_queue",
            Self::Feedback => "feedback",
            Self::NetworkSync => "network_sync",
            Self::SaveState => "save_state",
            Self::AdapterSideEffects => "adapter_side_effects",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SnapshotDisposition {
    IncludedInWorldSnapshot,
    IncludedAsCleanBoundaryEmptyState,
    ExplicitlyExcludedTransientRuntimeBuffer,
    ExplicitlyExcludedPersistedEnvelope,
    ExplicitlyExcludedDerivedAdapterState,
}

impl SnapshotDisposition {
    pub const fn is_included(self) -> bool {
        matches!(
            self,
            Self::IncludedInWorldSnapshot | Self::IncludedAsCleanBoundaryEmptyState
        )
    }

    pub const fn is_explicit_exclusion(self) -> bool {
        matches!(
            self,
            Self::ExplicitlyExcludedTransientRuntimeBuffer
                | Self::ExplicitlyExcludedPersistedEnvelope
                | Self::ExplicitlyExcludedDerivedAdapterState
        )
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SnapshotCompletenessPolicy {
    pub channel: SnapshotChannel,
    pub disposition: SnapshotDisposition,
    pub world_snapshot_field: Option<&'static str>,
    pub restore_behavior: &'static str,
    pub proof: &'static str,
}

pub const REQUIRED_SNAPSHOT_CHANNELS: [SnapshotChannel; 10] = [
    SnapshotChannel::EntityRecords,
    SnapshotChannel::ComponentTables,
    SnapshotChannel::ArchivedEntities,
    SnapshotChannel::RngStreamPositions,
    SnapshotChannel::EventQueue,
    SnapshotChannel::MutationQueue,
    SnapshotChannel::Feedback,
    SnapshotChannel::NetworkSync,
    SnapshotChannel::SaveState,
    SnapshotChannel::AdapterSideEffects,
];

const SNAPSHOT_COMPLETENESS_POLICIES: [SnapshotCompletenessPolicy; 10] = [
    SnapshotCompletenessPolicy {
        channel: SnapshotChannel::EntityRecords,
        disposition: SnapshotDisposition::IncludedInWorldSnapshot,
        world_snapshot_field: Some("entity_store_snapshot.entities"),
        restore_behavior: "SnapshotEngine rebuilds EntityStore metadata and next_entity_id from entity_store_snapshot.",
        proof: "EntityRecord covers entity_id, lifecycle state, created_tick, destroyed_tick, and tags.",
    },
    SnapshotCompletenessPolicy {
        channel: SnapshotChannel::ComponentTables,
        disposition: SnapshotDisposition::IncludedInWorldSnapshot,
        world_snapshot_field: Some("component_tables_snapshot.tables"),
        restore_behavior: "SnapshotEngine clears live table rows and restores every table row present in component_tables_snapshot.",
        proof: "ComponentTablesSnapshot stores component type id, type name, and sorted EntityID to JSON rows.",
    },
    SnapshotCompletenessPolicy {
        channel: SnapshotChannel::ArchivedEntities,
        disposition: SnapshotDisposition::IncludedInWorldSnapshot,
        world_snapshot_field: Some("entity_store_snapshot.entities[state=Archived]"),
        restore_behavior: "SnapshotEngine reconstructs EntityArchive from archived EntityRecord destroyed_tick values.",
        proof: "Archived records remain in EntityStoreSnapshot and are reinserted into the permanent ID archive on restore.",
    },
    SnapshotCompletenessPolicy {
        channel: SnapshotChannel::RngStreamPositions,
        disposition: SnapshotDisposition::IncludedAsCleanBoundaryEmptyState,
        world_snapshot_field: Some("rng_state.stream_positions"),
        restore_behavior: "Production restore accepts only clean tick-boundary snapshots; per-system RNG streams are per-tick and must not cross that boundary.",
        proof: "WorldHasher includes rng_state. Non-empty stream_positions in a restorable snapshot are rejected instead of silently ignored.",
    },
    SnapshotCompletenessPolicy {
        channel: SnapshotChannel::EventQueue,
        disposition: SnapshotDisposition::IncludedAsCleanBoundaryEmptyState,
        world_snapshot_field: Some("event_queue_state"),
        restore_behavior: "PhaseOrchestrator dispatches events before end-of-tick snapshots; restore rejects pending event queues.",
        proof: "WorldHasher includes event_queue_state. Runtime restore rebuilds EventBus only for clean snapshots.",
    },
    SnapshotCompletenessPolicy {
        channel: SnapshotChannel::MutationQueue,
        disposition: SnapshotDisposition::IncludedAsCleanBoundaryEmptyState,
        world_snapshot_field: Some("mutation_queue_state"),
        restore_behavior: "MutationGate applies all deferred queues before end-of-tick snapshots; restore rejects pending mutation queues.",
        proof: "WorldHasher includes mutation_queue_state. Apply-time rollback covers in-flight mutation transactions separately.",
    },
    SnapshotCompletenessPolicy {
        channel: SnapshotChannel::Feedback,
        disposition: SnapshotDisposition::ExplicitlyExcludedTransientRuntimeBuffer,
        world_snapshot_field: None,
        restore_behavior: "RuntimeOrchestrator drains and resets FeedbackBuffer/FeedbackLog when restoring a world snapshot.",
        proof: "Feedback is engine observation input, not authoritative world state; side_channel_hash_policy covers feedback replay integrity logs.",
    },
    SnapshotCompletenessPolicy {
        channel: SnapshotChannel::NetworkSync,
        disposition: SnapshotDisposition::ExplicitlyExcludedTransientRuntimeBuffer,
        world_snapshot_field: None,
        restore_behavior: "RuntimeOrchestrator clears pending engine inputs and disconnects bridges; accepted inputs are materialized into world state before ticking.",
        proof: "Network input logs and INPUT components prove accepted input ordering; raw inbound buffers are not world state.",
    },
    SnapshotCompletenessPolicy {
        channel: SnapshotChannel::SaveState,
        disposition: SnapshotDisposition::ExplicitlyExcludedPersistedEnvelope,
        world_snapshot_field: None,
        restore_behavior: "Save engine stores WorldSnapshot plus slot metadata outside the live simulation hash.",
        proof: "Save metadata carries the snapshot world_hash/cgs_hash envelope and is verified before restore.",
    },
    SnapshotCompletenessPolicy {
        channel: SnapshotChannel::AdapterSideEffects,
        disposition: SnapshotDisposition::ExplicitlyExcludedDerivedAdapterState,
        world_snapshot_field: None,
        restore_behavior: "RuntimeOrchestrator clears playback commands and disconnects adapters; engines rebuild rendered state from subsequent tick snapshots/deltas.",
        proof: "Adapter objects, sockets, audio handles, and playback commands are derived outputs from authoritative runtime state.",
    },
];

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SnapshotPolicyError {
    MissingChannel(SnapshotChannel),
    DuplicateChannel(SnapshotChannel),
    EmptyRestoreBehavior(SnapshotChannel),
    EmptyProof(SnapshotChannel),
    IncludedChannelMissingWorldSnapshotField(SnapshotChannel),
    ExcludedChannelHasWorldSnapshotField(SnapshotChannel),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SnapshotRestoreCompletenessError {
    Policy(SnapshotPolicyError),
    Structural(String),
    NonCleanSnapshot,
    PendingEvents(usize),
    PendingMutations(usize),
    RngStreamPositionsAtCleanBoundary(usize),
    ArchivedEntityMissingDestroyedTick(EntityID),
}

impl SnapshotRestoreCompletenessError {
    pub fn failed_path(&self) -> &'static str {
        match self {
            Self::Policy(_) => "snapshot_completeness_policy",
            Self::Structural(_) => "world_snapshot",
            Self::NonCleanSnapshot => "is_clean",
            Self::PendingEvents(_) => "event_queue_state.pending_events",
            Self::PendingMutations(_) => "mutation_queue_state",
            Self::RngStreamPositionsAtCleanBoundary(_) => "rng_state.stream_positions",
            Self::ArchivedEntityMissingDestroyedTick(_) => {
                "entity_store_snapshot.entities.destroyed_tick"
            }
        }
    }
}

impl fmt::Display for SnapshotRestoreCompletenessError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Policy(err) => write!(f, "snapshot completeness policy is invalid: {err:?}"),
            Self::Structural(err) => write!(f, "snapshot structural validation failed: {err}"),
            Self::NonCleanSnapshot => {
                write!(f, "snapshot restore requires a clean tick-boundary snapshot")
            }
            Self::PendingEvents(count) => write!(
                f,
                "snapshot restore does not support {count} pending event(s) at clean boundary"
            ),
            Self::PendingMutations(count) => write!(
                f,
                "snapshot restore does not support {count} pending mutation(s) at clean boundary"
            ),
            Self::RngStreamPositionsAtCleanBoundary(count) => write!(
                f,
                "snapshot restore does not support {count} live RNG stream position(s) at clean boundary"
            ),
            Self::ArchivedEntityMissingDestroyedTick(entity_id) => write!(
                f,
                "archived entity {entity_id} is missing a destroyed_tick value"
            ),
        }
    }
}

pub fn snapshot_completeness_policies() -> &'static [SnapshotCompletenessPolicy] {
    &SNAPSHOT_COMPLETENESS_POLICIES
}

pub fn policy_for(channel: SnapshotChannel) -> Option<&'static SnapshotCompletenessPolicy> {
    snapshot_completeness_policies()
        .iter()
        .find(|policy| policy.channel == channel)
}

pub fn validate_snapshot_completeness_policy() -> Result<(), SnapshotPolicyError> {
    let mut seen = BTreeSet::new();
    for policy in snapshot_completeness_policies() {
        if !seen.insert(policy.channel) {
            return Err(SnapshotPolicyError::DuplicateChannel(policy.channel));
        }
        if policy.restore_behavior.trim().is_empty() {
            return Err(SnapshotPolicyError::EmptyRestoreBehavior(policy.channel));
        }
        if policy.proof.trim().is_empty() {
            return Err(SnapshotPolicyError::EmptyProof(policy.channel));
        }
        if policy.disposition.is_included() && policy.world_snapshot_field.is_none() {
            return Err(
                SnapshotPolicyError::IncludedChannelMissingWorldSnapshotField(policy.channel),
            );
        }
        if policy.disposition.is_explicit_exclusion() && policy.world_snapshot_field.is_some() {
            return Err(SnapshotPolicyError::ExcludedChannelHasWorldSnapshotField(
                policy.channel,
            ));
        }
    }

    for channel in REQUIRED_SNAPSHOT_CHANNELS {
        if !seen.contains(&channel) {
            return Err(SnapshotPolicyError::MissingChannel(channel));
        }
    }

    Ok(())
}

pub fn validate_restorable_snapshot(
    snapshot: &WorldSnapshot,
) -> Result<(), SnapshotRestoreCompletenessError> {
    validate_snapshot_completeness_policy().map_err(SnapshotRestoreCompletenessError::Policy)?;
    snapshot
        .validate()
        .map_err(SnapshotRestoreCompletenessError::Structural)?;

    if !snapshot.is_clean {
        return Err(SnapshotRestoreCompletenessError::NonCleanSnapshot);
    }
    if snapshot.has_pending_events() {
        return Err(SnapshotRestoreCompletenessError::PendingEvents(
            snapshot.event_queue_state.pending_count(),
        ));
    }
    if snapshot.has_pending_mutations() {
        return Err(SnapshotRestoreCompletenessError::PendingMutations(
            snapshot.mutation_queue_state.total_pending(),
        ));
    }
    if !snapshot.rng_state.stream_positions.is_empty() {
        return Err(
            SnapshotRestoreCompletenessError::RngStreamPositionsAtCleanBoundary(
                snapshot.rng_state.stream_positions.len(),
            ),
        );
    }

    for record in &snapshot.entity_store_snapshot.entities {
        if record.state == EntityState::Archived && record.destroyed_tick == u64::MAX {
            return Err(
                SnapshotRestoreCompletenessError::ArchivedEntityMissingDestroyedTick(
                    record.entity_id,
                ),
            );
        }
    }

    Ok(())
}

pub fn archived_entries_for_restore(snapshot: &WorldSnapshot) -> Vec<(EntityID, Tick)> {
    snapshot
        .entity_store_snapshot
        .entities
        .iter()
        .filter(|record| record.state == EntityState::Archived)
        .map(|record| (record.entity_id, record.destroyed_tick))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::runtime::world_snapshot::{EventQueueState, MutationQueueState};

    fn restorable_snapshot() -> WorldSnapshot {
        let mut snapshot = WorldSnapshot::empty("0.1.0", 1, 42);
        snapshot.world_hash = "a".repeat(64);
        snapshot
    }

    #[test]
    fn x10_012_policy_covers_every_required_snapshot_channel() {
        validate_snapshot_completeness_policy().unwrap();
        for channel in REQUIRED_SNAPSHOT_CHANNELS {
            let policy = policy_for(channel).unwrap();
            assert!(!policy.restore_behavior.trim().is_empty());
            assert!(!policy.proof.trim().is_empty());
        }
    }

    #[test]
    fn x10_012_non_world_snapshot_channels_are_explicitly_excluded() {
        for policy in snapshot_completeness_policies() {
            if policy.world_snapshot_field.is_none() {
                assert!(
                    policy.disposition.is_explicit_exclusion(),
                    "{} must have an explicit exclusion",
                    policy.channel.as_str()
                );
            }
        }
    }

    #[test]
    fn x10_012_restorable_snapshot_rejects_pending_events() {
        let mut snapshot = restorable_snapshot();
        snapshot.event_queue_state = EventQueueState {
            pending_events: vec![r#"{"type":"damage"}"#.to_string()],
            next_event_id: 2,
        };
        let err = validate_restorable_snapshot(&snapshot).unwrap_err();
        assert_eq!(err, SnapshotRestoreCompletenessError::PendingEvents(1));
        assert_eq!(err.failed_path(), "event_queue_state.pending_events");
    }

    #[test]
    fn x10_012_restorable_snapshot_rejects_pending_mutations() {
        let mut snapshot = restorable_snapshot();
        snapshot.mutation_queue_state = MutationQueueState {
            pending_spawns: vec![r#"{"actor_id":"actor"}"#.to_string()],
            pending_additions: Vec::new(),
            pending_modifications: Vec::new(),
            pending_removals: Vec::new(),
            pending_destroys: Vec::new(),
        };
        let err = validate_restorable_snapshot(&snapshot).unwrap_err();
        assert_eq!(err, SnapshotRestoreCompletenessError::PendingMutations(1));
        assert_eq!(err.failed_path(), "mutation_queue_state");
    }

    #[test]
    fn x10_012_restorable_snapshot_rejects_live_rng_positions() {
        let mut snapshot = restorable_snapshot();
        snapshot.rng_state.set_stream_position("sys_loot", 3);
        let err = validate_restorable_snapshot(&snapshot).unwrap_err();
        assert_eq!(
            err,
            SnapshotRestoreCompletenessError::RngStreamPositionsAtCleanBoundary(1)
        );
        assert_eq!(err.failed_path(), "rng_state.stream_positions");
    }
}
