//! # COMP_AUTHORITY_V1
//!
//! The network authority and replication component. Defines who owns
//! this entity, how its state is replicated across peers, and how
//! client-side prediction is handled for this entity.
//!
//! ## Why this is UCL Core
//! Authority is not a multiplayer-only concern. Even in singleplayer,
//! every entity needs an authority model — LOCAL authority means the
//! local runtime owns and simulates this entity. This component makes
//! the authority model explicit and consistent across all network modes.
//! When Phase 15 (Network Core) is built, this component is already
//! in place on every entity — no migration needed.
//!
//! ## Authority Types
//! LOCAL — singleplayer or host-owned entity. Full authority.
//! SERVER — dedicated server owns this entity. Clients receive state.
//! CLIENT_OWNED — a specific client owns this entity (their character).
//! SHARED — no single owner, consensus-based (rare, for shared objects).
//!
//! ## Determinism
//! Authority transitions go through the Mutation Gate (I2).
//! Replication state is written by the Network Core (Phase 15).
//! During Phases 1-14, authority_type is always LOCAL for all entities.

use serde::{Deserialize, Serialize};

/// Component type ID for COMP_AUTHORITY_V1. Frozen forever.
pub const COMP_AUTHORITY_V1_ID: u32 = 10;

// ── Authority Type ────────────────────────────────────────────────────────────

/// Who has authoritative control over this entity's simulation state.
///
/// Authority determines which runtime instance is the source of truth
/// for this entity's component data. Only the authoritative instance
/// may write to this entity's components via the Mutation Gate.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum AuthorityType {
    /// Local runtime has full authority. Used in singleplayer and
    /// for host-owned entities in peer-to-peer sessions.
    /// This is the default for all entities in Phases 1-14.
    Local,

    /// A dedicated server has authority. This client receives
    /// replicated state and applies it — cannot write directly.
    /// Used in client-server multiplayer (Phase 15).
    Server,

    /// A specific client peer owns this entity (typically their
    /// player character). That peer's input is authoritative.
    /// `owner_peer_id` identifies which peer.
    ClientOwned,

    /// No single owner — multiple peers share authority.
    /// Used for shared interactive objects (doors, switches).
    /// Conflict resolution handled by Network Core (Phase 15).
    Shared,
}

impl Default for AuthorityType {
    fn default() -> Self {
        AuthorityType::Local
    }
}

impl std::fmt::Display for AuthorityType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            AuthorityType::Local => write!(f, "LOCAL"),
            AuthorityType::Server => write!(f, "SERVER"),
            AuthorityType::ClientOwned => write!(f, "CLIENT_OWNED"),
            AuthorityType::Shared => write!(f, "SHARED"),
        }
    }
}

// ── Replication Mode ──────────────────────────────────────────────────────────

/// How this entity's state is transmitted to non-authoritative peers.
///
/// Only relevant when authority_type is not Local.
/// During Phases 1-14 this field exists but is not processed.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum ReplicationMode {
    /// State updates sent via UDP — fast, may arrive out of order or drop.
    /// Best for frequently updated state (position, velocity).
    Unreliable,

    /// State updates sent reliably and in order — slower but guaranteed.
    /// Best for important infrequent state (health, score, phase).
    Reliable,

    /// State is never sent to clients — server only.
    /// Used for server-side AI state, cheat detection data.
    ServerOnly,
}

impl Default for ReplicationMode {
    fn default() -> Self {
        ReplicationMode::Unreliable
    }
}

impl std::fmt::Display for ReplicationMode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ReplicationMode::Unreliable => write!(f, "UNRELIABLE"),
            ReplicationMode::Reliable => write!(f, "RELIABLE"),
            ReplicationMode::ServerOnly => write!(f, "SERVER_ONLY"),
        }
    }
}

// ── Reconciliation Mode ───────────────────────────────────────────────────────

/// How client-side prediction errors are corrected when the server
/// sends an authoritative state update that differs from prediction.
///
/// Only relevant for ClientOwned entities with prediction enabled.
/// During Phases 1-14 this field exists but is not processed.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum ReconciliationMode {
    /// Instantly snap to the server's authoritative position.
    /// Fast correction, visible pop. Acceptable for low-latency sessions.
    Snap,

    /// Smoothly interpolate from predicted to authoritative position.
    /// No visible pop, slight lag in correction. Better for high latency.
    Interpolate,
}

impl Default for ReconciliationMode {
    fn default() -> Self {
        ReconciliationMode::Interpolate
    }
}

impl std::fmt::Display for ReconciliationMode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ReconciliationMode::Snap => write!(f, "SNAP"),
            ReconciliationMode::Interpolate => write!(f, "INTERPOLATE"),
        }
    }
}

// ── Component ─────────────────────────────────────────────────────────────────

/// COMP_AUTHORITY_V1 — Network authority and replication settings.
///
/// UCL Core component. Present on every entity. Defines the authority
/// model for this entity across all network configurations.
///
/// ## Singleplayer Default
/// All entities: authority_type=Local, is_replicated=false.
/// Prediction and reconciliation fields are ignored entirely.
///
/// ## Multiplayer (Phase 15)
/// The Network Core reads this component to determine how to handle
/// each entity's state synchronization across peers.
///
/// ## sync_rate_divisor
/// Controls how often this entity's state is sent to peers.
/// 1 = every tick, 2 = every other tick, 3 = every third tick, etc.
/// Higher values reduce bandwidth for less critical entities.
/// AI enemies far from all players might use divisor 4 or 8.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AuthorityComponent {
    /// Who has authoritative control over this entity.
    pub authority_type: AuthorityType,

    /// The peer ID of the owning client.
    /// Only meaningful when authority_type is ClientOwned.
    /// 0 means no specific peer owner (Local, Server, or Shared).
    pub owner_peer_id: u32,

    /// How this entity's state is sent to non-authoritative peers.
    pub replication_mode: ReplicationMode,

    /// Whether client-side prediction is enabled for this entity.
    /// Only applies to ClientOwned entities on the owning client.
    /// Prediction allows immediate local response before server confirms.
    pub prediction_enabled: bool,

    /// How prediction errors are corrected when server state arrives.
    pub reconciliation_mode: ReconciliationMode,

    /// Replication frequency divisor.
    /// 1 = replicate every tick. N = replicate every Nth tick.
    /// Must be >= 1. Validated by Mutation Gate on write.
    pub sync_rate_divisor: u8,

    /// Whether this entity's state is replicated to peers at all.
    /// False = local simulation only, no network traffic for this entity.
    /// Always false during Phases 1-14.
    pub is_replicated: bool,
}

impl AuthorityComponent {
    /// Creates a local authority component — the default for all entities.
    /// Not replicated, no prediction, no network traffic.
    /// Used for every entity in singleplayer and Phases 1-14.
    pub fn local() -> Self {
        Self {
            authority_type: AuthorityType::Local,
            owner_peer_id: 0,
            replication_mode: ReplicationMode::Unreliable,
            prediction_enabled: false,
            reconciliation_mode: ReconciliationMode::Interpolate,
            sync_rate_divisor: 1,
            is_replicated: false,
        }
    }

    /// Creates a client-owned authority component for a player entity.
    /// Used in Phase 15 for player characters in multiplayer sessions.
    /// Prediction enabled by default — feels responsive for the owning client.
    pub fn client_owned(peer_id: u32) -> Self {
        Self {
            authority_type: AuthorityType::ClientOwned,
            owner_peer_id: peer_id,
            replication_mode: ReplicationMode::Unreliable,
            prediction_enabled: true,
            reconciliation_mode: ReconciliationMode::Interpolate,
            sync_rate_divisor: 1,
            is_replicated: true,
        }
    }

    /// Creates a server-authority component for server-owned entities.
    /// Used in Phase 15 for AI, environment, and game state entities.
    pub fn server_owned() -> Self {
        Self {
            authority_type: AuthorityType::Server,
            owner_peer_id: 0,
            replication_mode: ReplicationMode::Unreliable,
            prediction_enabled: false,
            reconciliation_mode: ReconciliationMode::Snap,
            sync_rate_divisor: 1,
            is_replicated: true,
        }
    }

    /// Returns true if the local runtime has authority over this entity.
    pub fn is_local_authority(&self) -> bool {
        matches!(self.authority_type, AuthorityType::Local)
    }

    /// Returns true if a specific peer owns this entity.
    pub fn is_owned_by_peer(&self, peer_id: u32) -> bool {
        matches!(self.authority_type, AuthorityType::ClientOwned)
            && self.owner_peer_id == peer_id
    }

    /// Returns true if this entity should be replicated this tick.
    /// `current_tick` is used with sync_rate_divisor to determine frequency.
    pub fn should_replicate_this_tick(&self, current_tick: u64) -> bool {
        if !self.is_replicated {
            return false;
        }
        if self.sync_rate_divisor <= 1 {
            return true;
        }
        current_tick % self.sync_rate_divisor as u64 == 0
    }
}

impl Default for AuthorityComponent {
    fn default() -> Self {
        Self::local()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn local_authority_is_default() {
        let a = AuthorityComponent::local();
        assert!(a.is_local_authority());
        assert!(!a.is_replicated);
        assert!(!a.prediction_enabled);
    }

    #[test]
    fn client_owned_has_prediction() {
        let a = AuthorityComponent::client_owned(1);
        assert!(a.prediction_enabled);
        assert!(a.is_replicated);
        assert_eq!(a.owner_peer_id, 1);
    }

    #[test]
    fn server_owned_no_prediction() {
        let a = AuthorityComponent::server_owned();
        assert!(!a.prediction_enabled);
        assert!(a.is_replicated);
        assert!(matches!(a.authority_type, AuthorityType::Server));
    }

    #[test]
    fn local_is_local_authority() {
        let a = AuthorityComponent::local();
        assert!(a.is_local_authority());
    }

    #[test]
    fn client_owned_is_not_local_authority() {
        let a = AuthorityComponent::client_owned(2);
        assert!(!a.is_local_authority());
    }

    #[test]
    fn peer_ownership_check() {
        let a = AuthorityComponent::client_owned(5);
        assert!(a.is_owned_by_peer(5));
        assert!(!a.is_owned_by_peer(3));
    }

    #[test]
    fn local_never_replicates() {
        let a = AuthorityComponent::local();
        assert!(!a.should_replicate_this_tick(0));
        assert!(!a.should_replicate_this_tick(100));
    }

    #[test]
    fn replicated_every_tick_with_divisor_one() {
        let a = AuthorityComponent::client_owned(1);
        assert!(a.should_replicate_this_tick(0));
        assert!(a.should_replicate_this_tick(1));
        assert!(a.should_replicate_this_tick(99));
    }

    #[test]
    fn sync_rate_divisor_respected() {
        let mut a = AuthorityComponent::server_owned();
        a.sync_rate_divisor = 3;
        assert!(a.should_replicate_this_tick(0));
        assert!(!a.should_replicate_this_tick(1));
        assert!(!a.should_replicate_this_tick(2));
        assert!(a.should_replicate_this_tick(3));
        assert!(a.should_replicate_this_tick(6));
    }

    #[test]
    fn authority_type_display() {
        assert_eq!(AuthorityType::Local.to_string(), "LOCAL");
        assert_eq!(AuthorityType::Server.to_string(), "SERVER");
        assert_eq!(AuthorityType::ClientOwned.to_string(), "CLIENT_OWNED");
        assert_eq!(AuthorityType::Shared.to_string(), "SHARED");
    }

    #[test]
    fn replication_mode_display() {
        assert_eq!(ReplicationMode::Unreliable.to_string(), "UNRELIABLE");
        assert_eq!(ReplicationMode::Reliable.to_string(), "RELIABLE");
        assert_eq!(ReplicationMode::ServerOnly.to_string(), "SERVER_ONLY");
    }

    #[test]
    fn reconciliation_mode_display() {
        assert_eq!(ReconciliationMode::Snap.to_string(), "SNAP");
        assert_eq!(ReconciliationMode::Interpolate.to_string(), "INTERPOLATE");
    }
}
