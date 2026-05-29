use std::collections::BTreeSet;

use serde::{Deserialize, Serialize};

use super::{ConnectionState, PeerManager, PeerManagerStats};
use crate::{NetworkError, PeerId, Tick};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum NetworkMode {
    Offline,
    Host,
    Client,
    DedicatedServer,
    PeerToPeer,
}

impl NetworkMode {
    pub fn requires_lockstep(self) -> bool {
        !matches!(self, Self::Offline)
    }

    pub fn is_server_authoritative(self) -> bool {
        matches!(self, Self::Host | Self::DedicatedServer | Self::Client)
    }

    pub fn accepts_remote_peers(self) -> bool {
        matches!(self, Self::Host | Self::DedicatedServer | Self::PeerToPeer)
    }

    pub fn is_multiplayer(self) -> bool {
        !matches!(self, Self::Offline)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum SessionPhase {
    Created,
    Lobby,
    Syncing,
    Live,
    Paused,
    Resyncing,
    ShuttingDown,
    Ended,
}

impl SessionPhase {
    pub fn can_transition_to(self, next: Self) -> bool {
        use SessionPhase::*;
        if self == next {
            return true;
        }
        matches!(
            (self, next),
            (Created, Lobby)
                | (Created, Syncing)
                | (Created, Live)
                | (Created, ShuttingDown)
                | (Lobby, Syncing)
                | (Lobby, Live)
                | (Lobby, ShuttingDown)
                | (Syncing, Live)
                | (Syncing, Resyncing)
                | (Syncing, ShuttingDown)
                | (Live, Paused)
                | (Live, Resyncing)
                | (Live, ShuttingDown)
                | (Paused, Live)
                | (Paused, Resyncing)
                | (Paused, ShuttingDown)
                | (Resyncing, Syncing)
                | (Resyncing, Live)
                | (Resyncing, ShuttingDown)
                | (ShuttingDown, Ended)
        )
    }

    pub fn can_simulate(self) -> bool {
        matches!(self, Self::Live)
    }

    pub fn accepts_membership_changes(self) -> bool {
        matches!(
            self,
            Self::Created | Self::Lobby | Self::Syncing | Self::Resyncing
        )
    }

    pub fn is_terminal(self) -> bool {
        matches!(self, Self::Ended)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum PauseReason {
    UserRequested,
    WaitingForPeer(PeerId),
    PeerTimeout(PeerId),
    Resynchronising,
    EngineBridgeDisconnected,
    Other(String),
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SessionConfig {
    pub mode: NetworkMode,
    pub max_peers: usize,
    pub local_peer_id: Option<PeerId>,
    pub server_peer_id: Option<PeerId>,
    pub heartbeat_timeout_ticks: Tick,
    pub input_delay_ticks: Tick,
    pub allow_late_join: bool,
    pub require_all_live_peers_for_input: bool,
    pub pause_on_timeout: bool,
}

impl SessionConfig {
    pub fn for_mode(mode: NetworkMode) -> Self {
        Self {
            mode,
            ..Self::default()
        }
    }

    pub fn validate(&self) -> Result<(), NetworkError> {
        if self.max_peers == 0 && self.mode.is_multiplayer() {
            return Err(NetworkError::InvalidOperation(
                "multiplayer sessions require max_peers > 0".to_string(),
            ));
        }
        if self.local_peer_id == Some(0) {
            return Err(NetworkError::InvalidOperation(
                "local_peer_id 0 is reserved".to_string(),
            ));
        }
        if self.server_peer_id == Some(0) {
            return Err(NetworkError::InvalidOperation(
                "server_peer_id 0 is reserved".to_string(),
            ));
        }
        Ok(())
    }
}

impl Default for SessionConfig {
    fn default() -> Self {
        Self {
            mode: NetworkMode::Host,
            max_peers: 64,
            local_peer_id: None,
            server_peer_id: None,
            heartbeat_timeout_ticks: 180,
            input_delay_ticks: 0,
            allow_late_join: true,
            require_all_live_peers_for_input: true,
            pause_on_timeout: true,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SessionStatus {
    pub mode: NetworkMode,
    pub phase: SessionPhase,
    pub tick: Tick,
    pub paused: bool,
    pub pause_reason: Option<PauseReason>,
    pub peer_stats: PeerManagerStats,
    pub required_input_peers: BTreeSet<PeerId>,
}

#[derive(Debug, Clone)]
pub struct SessionManager {
    config: SessionConfig,
    peers: PeerManager,
    session_tick: Tick,
    phase: SessionPhase,
    paused_before_phase: Option<SessionPhase>,
    pause_reason: Option<PauseReason>,
    created_tick: Tick,
    last_membership_change_tick: Tick,
    last_timeout_scan_tick: Tick,
}

impl SessionManager {
    pub fn new(mode: NetworkMode) -> Self {
        Self::with_config(SessionConfig::for_mode(mode))
            .expect("default session configuration must be valid")
    }

    pub fn with_config(config: SessionConfig) -> Result<Self, NetworkError> {
        config.validate()?;
        Ok(Self {
            config,
            peers: PeerManager::new(),
            session_tick: 0,
            phase: SessionPhase::Created,
            paused_before_phase: None,
            pause_reason: None,
            created_tick: 0,
            last_membership_change_tick: 0,
            last_timeout_scan_tick: 0,
        })
    }

    pub fn add_peer(&mut self, peer_id: PeerId) -> Result<(), NetworkError> {
        self.add_peer_at(peer_id, self.session_tick)
    }

    pub fn add_peer_at(&mut self, peer_id: PeerId, tick: Tick) -> Result<(), NetworkError> {
        if self.config.mode == NetworkMode::Offline {
            return Err(NetworkError::InvalidOperation(
                "offline sessions cannot add remote peers".to_string(),
            ));
        }
        if self.peers.len() >= self.config.max_peers {
            return Err(NetworkError::InvalidOperation(format!(
                "session peer limit reached: {}",
                self.config.max_peers
            )));
        }
        if !self.config.allow_late_join && !self.phase.accepts_membership_changes() {
            return Err(NetworkError::InvalidOperation(format!(
                "session phase {:?} does not accept late joins",
                self.phase
            )));
        }
        self.peers.add_peer_at(peer_id, tick)?;
        self.last_membership_change_tick = tick;
        Ok(())
    }

    pub fn remove_peer(&mut self, peer_id: PeerId) -> Result<(), NetworkError> {
        self.peers
            .remove_peer(peer_id)
            .map(|_| {
                self.last_membership_change_tick = self.session_tick;
            })
            .ok_or(NetworkError::UnknownPeer(peer_id))
    }

    pub fn transition_phase(&mut self, next: SessionPhase) -> Result<(), NetworkError> {
        if !self.phase.can_transition_to(next) {
            return Err(NetworkError::InvalidOperation(format!(
                "session cannot transition {:?} -> {:?}",
                self.phase, next
            )));
        }
        if next != SessionPhase::Paused {
            self.paused_before_phase = None;
            self.pause_reason = None;
        }
        self.phase = next;
        Ok(())
    }

    pub fn enter_lobby(&mut self) -> Result<(), NetworkError> {
        self.transition_phase(SessionPhase::Lobby)
    }

    pub fn start_sync(&mut self) -> Result<(), NetworkError> {
        self.transition_phase(SessionPhase::Syncing)
    }

    pub fn start_live(&mut self) -> Result<(), NetworkError> {
        self.transition_phase(SessionPhase::Live)
    }

    pub fn begin_shutdown(&mut self) -> Result<(), NetworkError> {
        self.transition_phase(SessionPhase::ShuttingDown)
    }

    pub fn end(&mut self) -> Result<(), NetworkError> {
        if self.phase != SessionPhase::ShuttingDown {
            self.transition_phase(SessionPhase::ShuttingDown)?;
        }
        self.transition_phase(SessionPhase::Ended)
    }

    pub fn mark_peer_live(&mut self, peer_id: PeerId) -> Result<(), NetworkError> {
        self.promote_peer_to_live(peer_id, self.session_tick)
    }

    pub fn promote_peer_to_live(
        &mut self,
        peer_id: PeerId,
        tick: Tick,
    ) -> Result<(), NetworkError> {
        let state = self.peers.require(peer_id)?.state;
        match state {
            ConnectionState::Connecting => {
                self.peers
                    .set_state_at(peer_id, ConnectionState::Handshaking, tick)?;
                self.peers
                    .set_state_at(peer_id, ConnectionState::Syncing, tick)?;
                self.peers
                    .set_state_at(peer_id, ConnectionState::Live, tick)?;
            }
            ConnectionState::Handshaking => {
                self.peers
                    .set_state_at(peer_id, ConnectionState::Syncing, tick)?;
                self.peers
                    .set_state_at(peer_id, ConnectionState::Live, tick)?;
            }
            ConnectionState::Syncing | ConnectionState::Reconnecting => {
                self.peers
                    .set_state_at(peer_id, ConnectionState::Live, tick)?;
            }
            ConnectionState::Live => {}
            ConnectionState::Desynced => {
                self.peers
                    .set_state_at(peer_id, ConnectionState::Syncing, tick)?;
                self.peers
                    .set_state_at(peer_id, ConnectionState::Live, tick)?;
            }
            ConnectionState::Disconnected => {
                return Err(NetworkError::InvalidOperation(format!(
                    "peer {} is disconnected and cannot become live",
                    peer_id
                )));
            }
        }
        Ok(())
    }

    pub fn mark_peer_desynced(&mut self, peer_id: PeerId) -> Result<(), NetworkError> {
        self.peers
            .set_state_at(peer_id, ConnectionState::Desynced, self.session_tick)?;
        if self.phase == SessionPhase::Live {
            self.transition_phase(SessionPhase::Resyncing)?;
        }
        Ok(())
    }

    pub fn mark_peer_reconnecting(&mut self, peer_id: PeerId) -> Result<(), NetworkError> {
        self.peers
            .set_state_at(peer_id, ConnectionState::Reconnecting, self.session_tick)
    }

    pub fn disconnect_peer(&mut self, peer_id: PeerId) -> Result<(), NetworkError> {
        self.peers.disconnect_peer(peer_id, self.session_tick)
    }

    pub fn observe_heartbeat(&mut self, peer_id: PeerId) -> Result<(), NetworkError> {
        self.peers.observe_heartbeat(peer_id, self.session_tick)
    }

    pub fn observe_input(
        &mut self,
        peer_id: PeerId,
        input_tick: Tick,
        sequence_id: u64,
    ) -> Result<(), NetworkError> {
        self.peers.observe_input(peer_id, input_tick, sequence_id)
    }

    pub fn advance_tick(&mut self) -> Tick {
        self.session_tick = self.session_tick.saturating_add(1);
        self.session_tick
    }

    pub fn try_advance_simulation_tick(&mut self) -> Result<Tick, NetworkError> {
        if !self.can_advance_simulation() {
            return Err(NetworkError::InvalidOperation(format!(
                "session cannot simulate in phase {:?}",
                self.phase
            )));
        }
        Ok(self.advance_tick())
    }

    pub fn apply_heartbeat_timeouts(&mut self) -> Result<Vec<PeerId>, NetworkError> {
        let timed_out = self
            .peers
            .mark_timeouts_reconnecting(self.session_tick, self.config.heartbeat_timeout_ticks)?;
        self.last_timeout_scan_tick = self.session_tick;
        if self.config.pause_on_timeout {
            if let Some(peer_id) = timed_out.first().copied() {
                self.set_pause_reason(Some(PauseReason::PeerTimeout(peer_id)))?;
            }
        }
        Ok(timed_out)
    }

    pub fn required_input_peers(&self) -> BTreeSet<PeerId> {
        if !self.config.mode.requires_lockstep() {
            return BTreeSet::new();
        }
        if self.config.require_all_live_peers_for_input {
            return self.peers.live_peer_ids();
        }
        match self.config.mode {
            NetworkMode::Client => self.config.server_peer_id.into_iter().collect(),
            NetworkMode::Host | NetworkMode::DedicatedServer | NetworkMode::PeerToPeer => {
                self.peers.live_peer_ids()
            }
            NetworkMode::Offline => BTreeSet::new(),
        }
    }

    pub fn can_advance_simulation(&self) -> bool {
        self.phase.can_simulate() && self.pause_reason.is_none()
    }

    pub fn set_paused(&mut self, paused: bool) {
        let reason = paused.then_some(PauseReason::UserRequested);
        let _ = self.set_pause_reason(reason);
    }

    pub fn set_pause_reason(&mut self, reason: Option<PauseReason>) -> Result<(), NetworkError> {
        match reason {
            Some(reason) => {
                if self.phase != SessionPhase::Paused {
                    if !self.phase.can_transition_to(SessionPhase::Paused) {
                        return Err(NetworkError::InvalidOperation(format!(
                            "session phase {:?} cannot pause",
                            self.phase
                        )));
                    }
                    self.paused_before_phase = Some(self.phase);
                    self.phase = SessionPhase::Paused;
                }
                self.pause_reason = Some(reason);
            }
            None => {
                self.pause_reason = None;
                if self.phase == SessionPhase::Paused {
                    self.phase = self
                        .paused_before_phase
                        .take()
                        .unwrap_or(SessionPhase::Live);
                }
            }
        }
        Ok(())
    }

    pub fn is_paused(&self) -> bool {
        self.pause_reason.is_some()
    }

    pub fn pause_reason(&self) -> Option<&PauseReason> {
        self.pause_reason.as_ref()
    }

    pub fn mode(&self) -> NetworkMode {
        self.config.mode
    }

    pub fn config(&self) -> &SessionConfig {
        &self.config
    }

    pub fn config_mut(&mut self) -> &mut SessionConfig {
        &mut self.config
    }

    pub fn phase(&self) -> SessionPhase {
        self.phase
    }

    pub fn tick(&self) -> Tick {
        self.session_tick
    }

    pub fn created_tick(&self) -> Tick {
        self.created_tick
    }

    pub fn last_membership_change_tick(&self) -> Tick {
        self.last_membership_change_tick
    }

    pub fn last_timeout_scan_tick(&self) -> Tick {
        self.last_timeout_scan_tick
    }

    pub fn peers(&self) -> &PeerManager {
        &self.peers
    }

    pub fn peers_mut(&mut self) -> &mut PeerManager {
        &mut self.peers
    }

    pub fn status(&self) -> SessionStatus {
        SessionStatus {
            mode: self.mode(),
            phase: self.phase,
            tick: self.session_tick,
            paused: self.is_paused(),
            pause_reason: self.pause_reason.clone(),
            peer_stats: self.peers.stats(),
            required_input_peers: self.required_input_peers(),
        }
    }
}
