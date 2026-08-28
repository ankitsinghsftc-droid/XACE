//! Deterministic multiplayer primitives for XACE Phase 15.
//!
//! This crate owns lockstep input gating, peer/session state, authority checks,
//! desync detection, rollback bookkeeping, and interest management. It does not
//! open sockets; transports live in engine-adapter/runtime code and feed typed
//! packets into these deterministic structures.

pub mod authority;
pub mod chaos;
pub mod diagnostics;
pub mod input;
pub mod prediction;
pub mod replication;
pub mod session;
pub mod synchronisation;

use thiserror::Error;

pub type PeerId = u64;
pub type EntityId = u64;
pub type Tick = u64;

#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum NetworkError {
    #[error("peer {0} is not registered")]
    UnknownPeer(PeerId),

    #[error("duplicate input packet peer={peer_id} tick={tick} sequence={sequence_id}")]
    DuplicateInput {
        peer_id: PeerId,
        tick: Tick,
        sequence_id: u64,
    },

    #[error("stale input packet peer={peer_id} sequence={sequence_id} last={last_sequence_id}")]
    StaleInput {
        peer_id: PeerId,
        sequence_id: u64,
        last_sequence_id: u64,
    },

    #[error("missing input range peer={peer_id} from={from_tick} to={to_tick}")]
    MissingInputRange {
        peer_id: PeerId,
        from_tick: Tick,
        to_tick: Tick,
    },

    #[error("invalid input packet: {0}")]
    InvalidInput(String),

    #[error("input buffer overflow peer={peer_id} limit={limit}")]
    InputBufferOverflow { peer_id: PeerId, limit: usize },

    #[error("lockstep tick {tick} is waiting for peers {missing_peers:?}")]
    LockstepWaiting {
        tick: Tick,
        missing_peers: Vec<PeerId>,
    },

    #[error("cheat guard rejected input: {0}")]
    CheatRejected(String),

    #[error("authority denied entity={entity_id} peer={peer_id}")]
    AuthorityDenied {
        entity_id: EntityId,
        peer_id: PeerId,
    },

    #[error("rollback snapshot for tick {0} was not found")]
    RollbackSnapshotMissing(Tick),

    #[error(
        "{failure_code}: unsupported launch topology mode={mode} topology={topology_id}: {reason}"
    )]
    UnsupportedTopology {
        failure_code: String,
        mode: String,
        topology_id: String,
        reason: String,
    },

    #[error("invalid network operation: {0}")]
    InvalidOperation(String),
}
