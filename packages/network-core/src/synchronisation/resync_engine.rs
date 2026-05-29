use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};

use super::DesyncReport;
use crate::{NetworkError, PeerId, Tick};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ResyncMode {
    Snapshot,
    DeltaFromSnapshot,
    FullReconnect,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ResyncState {
    Pending,
    SnapshotSent,
    AwaitingAck,
    Complete,
    Failed,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ResyncConfig {
    pub max_delta_ticks: Tick,
    pub ack_timeout_ticks: Tick,
    pub max_attempts: u8,
}

impl Default for ResyncConfig {
    fn default() -> Self {
        Self {
            max_delta_ticks: 120,
            ack_timeout_ticks: 180,
            max_attempts: 3,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ResyncInstruction {
    pub peer_id: PeerId,
    pub snapshot_tick: Tick,
    pub expected_hash: String,
    pub target_tick: Tick,
    pub mode: ResyncMode,
    pub attempt: u8,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ResyncSession {
    pub peer_id: PeerId,
    pub snapshot_tick: Tick,
    pub target_tick: Tick,
    pub expected_hash: String,
    pub mode: ResyncMode,
    pub state: ResyncState,
    pub attempts: u8,
    pub requested_tick: Tick,
    pub last_sent_tick: Option<Tick>,
    pub completed_tick: Option<Tick>,
    pub failure_reason: Option<String>,
}

impl ResyncSession {
    pub fn instruction(&self) -> ResyncInstruction {
        ResyncInstruction {
            peer_id: self.peer_id,
            snapshot_tick: self.snapshot_tick,
            expected_hash: self.expected_hash.clone(),
            target_tick: self.target_tick,
            mode: self.mode,
            attempt: self.attempts,
        }
    }
}

#[derive(Debug, Clone)]
pub struct ResyncEngine {
    config: ResyncConfig,
    sessions: BTreeMap<PeerId, ResyncSession>,
}

impl Default for ResyncEngine {
    fn default() -> Self {
        Self::new()
    }
}

impl ResyncEngine {
    pub fn new() -> Self {
        Self::with_config(ResyncConfig::default())
    }

    pub fn with_config(config: ResyncConfig) -> Self {
        Self {
            config: ResyncConfig {
                max_attempts: config.max_attempts.max(1),
                ..config
            },
            sessions: BTreeMap::new(),
        }
    }

    pub fn instructions_for_report(report: &DesyncReport) -> Vec<ResyncInstruction> {
        report
            .divergent_peers
            .iter()
            .map(|(peer_id, _)| ResyncInstruction {
                peer_id: *peer_id,
                snapshot_tick: report.tick,
                expected_hash: report.expected_hash.clone(),
                target_tick: report.tick,
                mode: ResyncMode::Snapshot,
                attempt: 1,
            })
            .collect()
    }

    pub fn begin_from_report(
        &mut self,
        report: &DesyncReport,
        live_tick: Tick,
    ) -> Result<Vec<ResyncInstruction>, NetworkError> {
        let mut peers = report.divergent_peer_ids();
        peers.extend(report.missing_peers.iter().copied());
        self.begin_for_peers(
            peers,
            report.tick,
            live_tick,
            report.expected_hash.clone(),
            report.tick,
        )
    }

    pub fn begin_for_peers(
        &mut self,
        peers: BTreeSet<PeerId>,
        snapshot_tick: Tick,
        live_tick: Tick,
        expected_hash: String,
        requested_tick: Tick,
    ) -> Result<Vec<ResyncInstruction>, NetworkError> {
        if expected_hash.trim().is_empty() {
            return Err(NetworkError::InvalidOperation(
                "resync expected hash cannot be empty".to_string(),
            ));
        }
        let mode = if live_tick.saturating_sub(snapshot_tick) <= self.config.max_delta_ticks {
            ResyncMode::DeltaFromSnapshot
        } else {
            ResyncMode::Snapshot
        };
        let mut instructions = Vec::new();
        for peer_id in peers {
            validate_peer_id(peer_id)?;
            let session = ResyncSession {
                peer_id,
                snapshot_tick,
                target_tick: live_tick,
                expected_hash: expected_hash.clone(),
                mode,
                state: ResyncState::Pending,
                attempts: 1,
                requested_tick,
                last_sent_tick: None,
                completed_tick: None,
                failure_reason: None,
            };
            instructions.push(session.instruction());
            self.sessions.insert(peer_id, session);
        }
        Ok(instructions)
    }

    pub fn mark_snapshot_sent(
        &mut self,
        peer_id: PeerId,
        tick: Tick,
    ) -> Result<ResyncInstruction, NetworkError> {
        let session = self.require_session_mut(peer_id)?;
        if matches!(session.state, ResyncState::Complete | ResyncState::Failed) {
            return Err(NetworkError::InvalidOperation(format!(
                "resync for peer {} is terminal",
                peer_id
            )));
        }
        session.state = ResyncState::SnapshotSent;
        session.last_sent_tick = Some(tick);
        Ok(session.instruction())
    }

    pub fn mark_awaiting_ack(&mut self, peer_id: PeerId) -> Result<(), NetworkError> {
        let session = self.require_session_mut(peer_id)?;
        session.state = ResyncState::AwaitingAck;
        Ok(())
    }

    pub fn acknowledge(
        &mut self,
        peer_id: PeerId,
        tick: Tick,
        peer_hash: &str,
    ) -> Result<(), NetworkError> {
        let session = self.require_session_mut(peer_id)?;
        if peer_hash != session.expected_hash {
            session.state = ResyncState::Failed;
            session.completed_tick = Some(tick);
            session.failure_reason = Some(format!(
                "resync ack hash {} did not match expected {}",
                peer_hash, session.expected_hash
            ));
            return Err(NetworkError::InvalidOperation(
                session.failure_reason.clone().expect("failure reason set"),
            ));
        }
        session.state = ResyncState::Complete;
        session.completed_tick = Some(tick);
        Ok(())
    }

    pub fn retry_due(&mut self, now_tick: Tick) -> Vec<ResyncInstruction> {
        let mut due = Vec::new();
        for session in self.sessions.values_mut() {
            if matches!(session.state, ResyncState::Complete | ResyncState::Failed) {
                continue;
            }
            let last_sent = session.last_sent_tick.unwrap_or(session.requested_tick);
            if now_tick.saturating_sub(last_sent) < self.config.ack_timeout_ticks {
                continue;
            }
            if session.attempts >= self.config.max_attempts {
                session.state = ResyncState::Failed;
                session.completed_tick = Some(now_tick);
                session.failure_reason = Some("resync retry limit exceeded".to_string());
                continue;
            }
            session.attempts = session.attempts.saturating_add(1);
            session.state = ResyncState::Pending;
            session.last_sent_tick = None;
            due.push(session.instruction());
        }
        due
    }

    pub fn session(&self, peer_id: PeerId) -> Option<&ResyncSession> {
        self.sessions.get(&peer_id)
    }

    pub fn sessions(&self) -> impl Iterator<Item = &ResyncSession> {
        self.sessions.values()
    }

    pub fn active_peer_ids(&self) -> BTreeSet<PeerId> {
        self.sessions
            .iter()
            .filter_map(|(&peer_id, session)| {
                (!matches!(session.state, ResyncState::Complete | ResyncState::Failed))
                    .then_some(peer_id)
            })
            .collect()
    }

    pub fn remove_terminal(&mut self) -> usize {
        let terminal = self
            .sessions
            .iter()
            .filter_map(|(&peer_id, session)| {
                matches!(session.state, ResyncState::Complete | ResyncState::Failed)
                    .then_some(peer_id)
            })
            .collect::<Vec<_>>();
        for peer_id in &terminal {
            self.sessions.remove(peer_id);
        }
        terminal.len()
    }

    pub fn config(&self) -> &ResyncConfig {
        &self.config
    }

    fn require_session_mut(&mut self, peer_id: PeerId) -> Result<&mut ResyncSession, NetworkError> {
        validate_peer_id(peer_id)?;
        self.sessions.get_mut(&peer_id).ok_or_else(|| {
            NetworkError::InvalidOperation(format!("no resync session for peer {}", peer_id))
        })
    }
}

fn validate_peer_id(peer_id: PeerId) -> Result<(), NetworkError> {
    if peer_id == 0 {
        return Err(NetworkError::InvalidOperation(
            "peer_id 0 is reserved".to_string(),
        ));
    }
    Ok(())
}
