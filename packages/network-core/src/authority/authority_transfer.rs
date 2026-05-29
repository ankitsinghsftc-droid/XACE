use serde::{Deserialize, Serialize};

use crate::{EntityId, NetworkError, PeerId, Tick};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum AuthorityTransferState {
    Pending,
    Accepted,
    Rejected,
    Committed,
    Expired,
    RolledBack,
}

impl AuthorityTransferState {
    pub fn is_terminal(self) -> bool {
        matches!(
            self,
            Self::Rejected | Self::Committed | Self::Expired | Self::RolledBack
        )
    }

    pub fn can_transition_to(self, next: Self) -> bool {
        use AuthorityTransferState::*;
        if self == next {
            return true;
        }
        matches!(
            (self, next),
            (Pending, Accepted)
                | (Pending, Rejected)
                | (Pending, Expired)
                | (Accepted, Committed)
                | (Accepted, Rejected)
                | (Accepted, Expired)
                | (Accepted, RolledBack)
                | (Committed, RolledBack)
        )
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum AuthorityTransferReason {
    SpawnOwnership,
    PlayerPossession,
    HostMigration,
    InterestMigration,
    EngineEdit,
    ReconnectRecovery,
    Manual,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum AuthorityTransferDecision {
    Accepted,
    Rejected(String),
    Expired,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AuthorityTransfer {
    pub transfer_id: u64,
    pub entity_id: EntityId,
    pub from_peer: PeerId,
    pub to_peer: PeerId,
    pub requested_tick: Tick,
    pub expires_tick: Option<Tick>,
    pub accepted_tick: Option<Tick>,
    pub completed_tick: Option<Tick>,
    pub accepted_by: Option<PeerId>,
    pub state: AuthorityTransferState,
    pub reason: AuthorityTransferReason,
    pub rejection_reason: Option<String>,
    pub rollback_reason: Option<String>,
    pub pre_transfer_version: Option<u64>,
    pub post_transfer_version: Option<u64>,
}

impl AuthorityTransfer {
    pub fn new(
        entity_id: EntityId,
        from_peer: PeerId,
        to_peer: PeerId,
        requested_tick: Tick,
    ) -> Self {
        Self::request(
            entity_id,
            from_peer,
            to_peer,
            requested_tick,
            AuthorityTransferReason::Manual,
        )
    }

    pub fn request(
        entity_id: EntityId,
        from_peer: PeerId,
        to_peer: PeerId,
        requested_tick: Tick,
        reason: AuthorityTransferReason,
    ) -> Self {
        Self {
            transfer_id: stable_transfer_id(entity_id, from_peer, to_peer, requested_tick),
            entity_id,
            from_peer,
            to_peer,
            requested_tick,
            expires_tick: None,
            accepted_tick: None,
            completed_tick: None,
            accepted_by: None,
            state: AuthorityTransferState::Pending,
            reason,
            rejection_reason: None,
            rollback_reason: None,
            pre_transfer_version: None,
            post_transfer_version: None,
        }
    }

    pub fn with_expiry(mut self, expires_tick: Tick) -> Self {
        self.expires_tick = Some(expires_tick);
        self
    }

    pub fn with_pre_transfer_version(mut self, version: u64) -> Self {
        self.pre_transfer_version = Some(version);
        self
    }

    pub fn validate_request(&self) -> Result<(), NetworkError> {
        if self.entity_id == 0 {
            return Err(NetworkError::InvalidOperation(
                "authority transfer entity_id 0 is reserved".to_string(),
            ));
        }
        if self.from_peer == 0 || self.to_peer == 0 {
            return Err(NetworkError::InvalidOperation(
                "authority transfer peer_id 0 is reserved".to_string(),
            ));
        }
        if self.from_peer == self.to_peer {
            return Err(NetworkError::InvalidOperation(format!(
                "authority transfer for entity {} has identical peers",
                self.entity_id
            )));
        }
        if self
            .expires_tick
            .is_some_and(|expires_tick| expires_tick < self.requested_tick)
        {
            return Err(NetworkError::InvalidOperation(format!(
                "authority transfer {} expires before it is requested",
                self.transfer_id
            )));
        }
        Ok(())
    }

    pub fn accept(&mut self, accepted_by: PeerId, tick: Tick) -> Result<(), NetworkError> {
        self.validate_request()?;
        self.ensure_transition(AuthorityTransferState::Accepted)?;
        if accepted_by == 0 {
            return Err(NetworkError::InvalidOperation(
                "accepted_by peer_id 0 is reserved".to_string(),
            ));
        }
        if self.should_expire(tick) {
            return self.expire(tick);
        }
        self.state = AuthorityTransferState::Accepted;
        self.accepted_tick = Some(tick);
        self.accepted_by = Some(accepted_by);
        Ok(())
    }

    pub fn reject(&mut self, reason: impl Into<String>, tick: Tick) -> Result<(), NetworkError> {
        self.ensure_transition(AuthorityTransferState::Rejected)?;
        self.state = AuthorityTransferState::Rejected;
        self.completed_tick = Some(tick);
        self.rejection_reason = Some(reason.into());
        Ok(())
    }

    pub fn decide(
        &mut self,
        decision: AuthorityTransferDecision,
        decided_by: PeerId,
        tick: Tick,
    ) -> Result<(), NetworkError> {
        match decision {
            AuthorityTransferDecision::Accepted => self.accept(decided_by, tick),
            AuthorityTransferDecision::Rejected(reason) => self.reject(reason, tick),
            AuthorityTransferDecision::Expired => self.expire(tick),
        }
    }

    pub fn commit(&mut self, tick: Tick, post_transfer_version: u64) -> Result<(), NetworkError> {
        self.ensure_transition(AuthorityTransferState::Committed)?;
        if self.should_expire(tick) {
            return self.expire(tick);
        }
        self.state = AuthorityTransferState::Committed;
        self.completed_tick = Some(tick);
        self.post_transfer_version = Some(post_transfer_version);
        Ok(())
    }

    pub fn rollback(&mut self, tick: Tick, reason: impl Into<String>) -> Result<(), NetworkError> {
        self.ensure_transition(AuthorityTransferState::RolledBack)?;
        self.state = AuthorityTransferState::RolledBack;
        self.completed_tick = Some(tick);
        self.rollback_reason = Some(reason.into());
        Ok(())
    }

    pub fn expire(&mut self, tick: Tick) -> Result<(), NetworkError> {
        self.ensure_transition(AuthorityTransferState::Expired)?;
        self.state = AuthorityTransferState::Expired;
        self.completed_tick = Some(tick);
        Ok(())
    }

    pub fn should_expire(&self, tick: Tick) -> bool {
        self.expires_tick
            .is_some_and(|expires_tick| tick > expires_tick)
            && !self.state.is_terminal()
    }

    pub fn is_terminal(&self) -> bool {
        self.state.is_terminal()
    }

    pub fn is_pending(&self) -> bool {
        self.state == AuthorityTransferState::Pending
    }

    pub fn is_committed(&self) -> bool {
        self.state == AuthorityTransferState::Committed
    }

    pub fn duration_ticks(&self) -> Option<Tick> {
        self.completed_tick
            .map(|completed_tick| completed_tick.saturating_sub(self.requested_tick))
    }

    pub fn key_tuple(&self) -> (EntityId, PeerId, PeerId, Tick) {
        (
            self.entity_id,
            self.from_peer,
            self.to_peer,
            self.requested_tick,
        )
    }

    fn ensure_transition(&self, next: AuthorityTransferState) -> Result<(), NetworkError> {
        if self.state.can_transition_to(next) {
            Ok(())
        } else {
            Err(NetworkError::InvalidOperation(format!(
                "authority transfer {} cannot transition {:?} -> {:?}",
                self.transfer_id, self.state, next
            )))
        }
    }
}

fn stable_transfer_id(
    entity_id: EntityId,
    from_peer: PeerId,
    to_peer: PeerId,
    requested_tick: Tick,
) -> u64 {
    let mut hash = 0xcbf29ce484222325_u64;
    for value in [entity_id, from_peer, to_peer, requested_tick] {
        for byte in value.to_le_bytes() {
            hash ^= u64::from(byte);
            hash = hash.wrapping_mul(0x100000001b3);
        }
    }
    hash
}
