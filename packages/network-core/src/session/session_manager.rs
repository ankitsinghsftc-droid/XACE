use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};

use super::{
    ConnectionState, Peer, PeerManager, PeerManagerStats, SessionCompatibilityMismatch,
    SessionCompatibilityProfile, SessionCompatibilityReport,
};
use crate::{EntityId, NetworkError, PeerId, Tick};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum NetworkMode {
    Offline,
    Host,
    Client,
    DedicatedServer,
    PeerToPeer,
}

impl NetworkMode {
    pub const fn all() -> &'static [Self; 5] {
        &[
            Self::Offline,
            Self::Host,
            Self::Client,
            Self::DedicatedServer,
            Self::PeerToPeer,
        ]
    }

    pub const fn stable_id(self) -> &'static str {
        match self {
            Self::Offline => "offline",
            Self::Host => "host",
            Self::Client => "client",
            Self::DedicatedServer => "dedicated_server",
            Self::PeerToPeer => "peer_to_peer",
        }
    }

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

    pub fn launch_topology(self) -> super::LaunchTopologyDecision {
        super::launch_topology_for_mode(self)
    }

    pub fn require_launch_topology(self) -> Result<super::LaunchTopologyDecision, NetworkError> {
        super::require_launch_topology(self)
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
pub struct SessionPlayerIdentity {
    pub peer_id: PeerId,
    pub player_id: EntityId,
    pub display_name: String,
    pub engine_name: String,
    pub adapter_version: String,
}

impl SessionPlayerIdentity {
    pub fn new(peer_id: PeerId, player_id: EntityId, display_name: impl Into<String>) -> Self {
        Self {
            peer_id,
            player_id,
            display_name: display_name.into(),
            engine_name: String::new(),
            adapter_version: String::new(),
        }
    }

    pub fn with_adapter(
        mut self,
        engine_name: impl Into<String>,
        adapter_version: impl Into<String>,
    ) -> Self {
        self.engine_name = engine_name.into();
        self.adapter_version = adapter_version.into();
        self
    }

    pub fn validate(&self) -> Result<(), NetworkError> {
        if self.peer_id == 0 {
            return Err(NetworkError::InvalidOperation(
                "peer_id 0 is reserved".to_string(),
            ));
        }
        if self.player_id == 0 {
            return Err(NetworkError::InvalidOperation(
                "player_id 0 is reserved for unbound peers".to_string(),
            ));
        }
        let display_name = self.display_name.trim();
        if display_name.is_empty() {
            return Err(NetworkError::InvalidOperation(
                "player display_name must be non-empty".to_string(),
            ));
        }
        if display_name.chars().count() > 64 {
            return Err(NetworkError::InvalidOperation(
                "player display_name must be 64 characters or fewer".to_string(),
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub enum SessionLifecycleEventKind {
    Created,
    LobbyCreated,
    Joined,
    Ready,
    LiveStarted,
    Left,
    Reconnecting,
    Reconnected,
    LateJoined,
    CompatibilityPassed,
    CompatibilityFailed,
    TeardownStarted,
    Ended,
}

impl SessionLifecycleEventKind {
    pub const fn stable_id(self) -> &'static str {
        match self {
            Self::Created => "created",
            Self::LobbyCreated => "lobby_created",
            Self::Joined => "joined",
            Self::Ready => "ready",
            Self::LiveStarted => "live_started",
            Self::Left => "left",
            Self::Reconnecting => "reconnecting",
            Self::Reconnected => "reconnected",
            Self::LateJoined => "late_joined",
            Self::CompatibilityPassed => "compatibility_passed",
            Self::CompatibilityFailed => "compatibility_failed",
            Self::TeardownStarted => "teardown_started",
            Self::Ended => "ended",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SessionLifecycleEvent {
    pub kind: SessionLifecycleEventKind,
    pub tick: Tick,
    pub phase: SessionPhase,
    pub peer_id: Option<PeerId>,
    pub player_id: Option<EntityId>,
    pub message: String,
}

impl SessionLifecycleEvent {
    pub fn new(
        kind: SessionLifecycleEventKind,
        tick: Tick,
        phase: SessionPhase,
        peer_id: Option<PeerId>,
        player_id: Option<EntityId>,
        message: impl Into<String>,
    ) -> Self {
        Self {
            kind,
            tick,
            phase,
            peer_id,
            player_id,
            message: message.into(),
        }
    }
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
    pub ready_peers: BTreeSet<PeerId>,
    pub player_identities: Vec<SessionPlayerIdentity>,
    pub lifecycle_events: Vec<SessionLifecycleEvent>,
    pub compatibility_required: bool,
    pub compatibility_ok: bool,
    pub compatibility_profile: Option<SessionCompatibilityProfile>,
    pub compatibility_reports: Vec<SessionCompatibilityReport>,
    pub compatibility_blockers: Vec<SessionCompatibilityMismatch>,
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
    lifecycle_events: Vec<SessionLifecycleEvent>,
    compatibility_profile: Option<SessionCompatibilityProfile>,
    compatibility_reports: BTreeMap<PeerId, SessionCompatibilityReport>,
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
            lifecycle_events: vec![SessionLifecycleEvent::new(
                SessionLifecycleEventKind::Created,
                0,
                SessionPhase::Created,
                None,
                None,
                "session created",
            )],
            compatibility_profile: None,
            compatibility_reports: BTreeMap::new(),
        })
    }

    pub fn require_compatibility_profile(
        &mut self,
        profile: SessionCompatibilityProfile,
    ) -> Result<(), NetworkError> {
        profile.validate()?;
        self.compatibility_reports.insert(
            profile.peer_id,
            SessionCompatibilityReport::compatible(profile.peer_id),
        );
        self.compatibility_profile = Some(profile);
        Ok(())
    }

    pub fn clear_compatibility_profile(&mut self) {
        self.compatibility_profile = None;
        self.compatibility_reports.clear();
    }

    pub fn record_peer_compatibility(
        &mut self,
        peer_profile: SessionCompatibilityProfile,
    ) -> Result<SessionCompatibilityReport, NetworkError> {
        let Some(expected) = self.compatibility_profile.as_ref() else {
            return Err(NetworkError::InvalidOperation(
                "session compatibility profile is not configured".to_string(),
            ));
        };
        if self.peers.get(peer_profile.peer_id).is_none()
            && peer_profile.peer_id != expected.peer_id
        {
            return Err(NetworkError::UnknownPeer(peer_profile.peer_id));
        }

        let report = expected.compare_peer(&peer_profile)?;
        self.compatibility_reports
            .insert(report.peer_id, report.clone());
        let player_id = self
            .peers
            .get(report.peer_id)
            .and_then(|peer| peer.player_id);
        self.record_lifecycle(
            if report.compatible {
                SessionLifecycleEventKind::CompatibilityPassed
            } else {
                SessionLifecycleEventKind::CompatibilityFailed
            },
            self.session_tick,
            Some(report.peer_id),
            player_id,
            if report.compatible {
                "peer compatibility profile accepted"
            } else {
                "peer compatibility profile rejected"
            },
        );
        Ok(report)
    }

    pub fn join_peer_with_compatibility(
        &mut self,
        identity: SessionPlayerIdentity,
        profile: SessionCompatibilityProfile,
    ) -> Result<SessionCompatibilityReport, NetworkError> {
        if profile.peer_id != identity.peer_id {
            return Err(NetworkError::InvalidOperation(format!(
                "compatibility profile peer_id {} does not match identity peer_id {}",
                profile.peer_id, identity.peer_id
            )));
        }
        self.join_peer(identity)?;
        self.record_peer_compatibility(profile)
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
        self.record_lifecycle(
            SessionLifecycleEventKind::Joined,
            tick,
            Some(peer_id),
            None,
            "peer joined session",
        );
        Ok(())
    }

    pub fn join_peer(&mut self, identity: SessionPlayerIdentity) -> Result<(), NetworkError> {
        self.join_peer_at(identity, self.session_tick)
    }

    pub fn join_peer_at(
        &mut self,
        identity: SessionPlayerIdentity,
        tick: Tick,
    ) -> Result<(), NetworkError> {
        self.join_peer_inner(identity, tick, false)
    }

    pub fn late_join_peer(&mut self, identity: SessionPlayerIdentity) -> Result<(), NetworkError> {
        self.late_join_peer_at(identity, self.session_tick)
    }

    pub fn late_join_peer_at(
        &mut self,
        identity: SessionPlayerIdentity,
        tick: Tick,
    ) -> Result<(), NetworkError> {
        if !matches!(
            self.phase,
            SessionPhase::Live | SessionPhase::Paused | SessionPhase::Resyncing
        ) {
            return Err(NetworkError::InvalidOperation(format!(
                "late join requires a live or resyncing session, got {:?}",
                self.phase
            )));
        }
        self.join_peer_inner(identity, tick, true)
    }

    fn join_peer_inner(
        &mut self,
        identity: SessionPlayerIdentity,
        tick: Tick,
        force_late: bool,
    ) -> Result<(), NetworkError> {
        identity.validate()?;
        if self.config.mode == NetworkMode::Offline {
            return Err(NetworkError::InvalidOperation(
                "offline sessions cannot add remote peers".to_string(),
            ));
        }
        if matches!(self.phase, SessionPhase::ShuttingDown | SessionPhase::Ended) {
            return Err(NetworkError::InvalidOperation(format!(
                "session phase {:?} does not accept joins",
                self.phase
            )));
        }
        if self.peers.get(identity.peer_id).is_some() {
            return Err(NetworkError::InvalidOperation(format!(
                "peer {} already exists",
                identity.peer_id
            )));
        }
        if self.peers.len() >= self.config.max_peers {
            return Err(NetworkError::InvalidOperation(format!(
                "session peer limit reached: {}",
                self.config.max_peers
            )));
        }
        let late_join = force_late || !self.phase.accepts_membership_changes();
        if late_join && !self.config.allow_late_join {
            return Err(NetworkError::InvalidOperation(format!(
                "session phase {:?} does not accept late joins",
                self.phase
            )));
        }

        let mut peer = Peer::new_at(identity.peer_id, tick).with_player_identity(&identity);
        if late_join || matches!(self.phase, SessionPhase::Syncing | SessionPhase::Resyncing) {
            peer.transition(ConnectionState::Handshaking, tick)?;
            peer.transition(ConnectionState::Syncing, tick)?;
        }
        let peer_id = identity.peer_id;
        let player_id = identity.player_id;
        self.peers.upsert_peer(peer)?;
        self.last_membership_change_tick = tick;
        self.record_lifecycle(
            if late_join {
                SessionLifecycleEventKind::LateJoined
            } else {
                SessionLifecycleEventKind::Joined
            },
            tick,
            Some(peer_id),
            Some(player_id),
            if late_join {
                "late-joining peer accepted into session sync"
            } else {
                "peer joined session with player identity"
            },
        );
        Ok(())
    }

    pub fn mark_peer_ready(&mut self, peer_id: PeerId) -> Result<(), NetworkError> {
        self.mark_peer_ready_at(peer_id, self.session_tick)
    }

    pub fn mark_peer_ready_at(&mut self, peer_id: PeerId, tick: Tick) -> Result<(), NetworkError> {
        let player_id = {
            let peer = self.peers.require_mut(peer_id)?;
            if peer.state == ConnectionState::Disconnected {
                return Err(NetworkError::InvalidOperation(format!(
                    "peer {} is disconnected and cannot become ready",
                    peer_id
                )));
            }
            peer.set_ready(true);
            peer.player_id
        };
        self.last_membership_change_tick = tick;
        self.record_lifecycle(
            SessionLifecycleEventKind::Ready,
            tick,
            Some(peer_id),
            player_id,
            "peer marked ready",
        );
        Ok(())
    }

    pub fn clear_peer_ready(&mut self, peer_id: PeerId) -> Result<(), NetworkError> {
        self.peers.set_ready(peer_id, false)
    }

    pub fn compatibility_reports(&self) -> Vec<SessionCompatibilityReport> {
        self.compatibility_reports.values().cloned().collect()
    }

    pub fn compatibility_blockers(&self) -> Vec<SessionCompatibilityMismatch> {
        let mut blockers = Vec::new();
        if self.compatibility_profile.is_none() {
            return blockers;
        }
        for peer in self.peers.iter() {
            if peer.state == ConnectionState::Disconnected {
                continue;
            }
            match self.compatibility_reports.get(&peer.peer_id) {
                Some(report) => blockers.extend(
                    report
                        .mismatches
                        .iter()
                        .filter(|mismatch| mismatch.blocking)
                        .cloned(),
                ),
                None => blockers
                    .extend(SessionCompatibilityReport::missing_profile(peer.peer_id).mismatches),
            }
        }
        blockers
    }

    pub fn compatibility_ok(&self) -> bool {
        self.compatibility_blockers().is_empty()
    }

    fn ensure_start_compatible(&self) -> Result<(), NetworkError> {
        let blockers = self.compatibility_blockers();
        if blockers.is_empty() {
            return Ok(());
        }
        let summary = blockers
            .iter()
            .map(|mismatch| {
                format!(
                    "peer={} kind={} expected={} actual={}",
                    mismatch.peer_id,
                    mismatch.kind.stable_id(),
                    mismatch.expected,
                    mismatch.actual
                )
            })
            .collect::<Vec<_>>()
            .join("; ");
        Err(NetworkError::InvalidOperation(format!(
            "session compatibility check failed: {summary}"
        )))
    }

    pub fn all_lobby_peers_ready(&self) -> bool {
        let mut active_peer_count = 0usize;
        for peer in self.peers.iter() {
            if peer.state == ConnectionState::Disconnected {
                continue;
            }
            active_peer_count += 1;
            if !peer.ready {
                return false;
            }
        }
        active_peer_count > 0
    }

    pub fn start_live_when_ready(&mut self) -> Result<(), NetworkError> {
        if !self.all_lobby_peers_ready() {
            return Err(NetworkError::InvalidOperation(
                "cannot start live session until every active lobby peer is ready".to_string(),
            ));
        }
        self.ensure_start_compatible()?;
        if self.phase == SessionPhase::Created {
            self.enter_lobby()?;
        }
        if self.phase == SessionPhase::Lobby {
            self.start_sync()?;
        }
        if !matches!(
            self.phase,
            SessionPhase::Syncing | SessionPhase::Resyncing | SessionPhase::Live
        ) {
            return Err(NetworkError::InvalidOperation(format!(
                "session phase {:?} cannot start live from ready peers",
                self.phase
            )));
        }
        let ready_peers = self.ready_peer_ids();
        for peer_id in ready_peers {
            self.promote_peer_to_live(peer_id, self.session_tick)?;
        }
        self.start_live()
    }

    pub fn promote_ready_peer_to_live(&mut self, peer_id: PeerId) -> Result<(), NetworkError> {
        if !self.peers.require(peer_id)?.ready {
            return Err(NetworkError::InvalidOperation(format!(
                "peer {} must be ready before becoming live",
                peer_id
            )));
        }
        self.promote_peer_to_live(peer_id, self.session_tick)
    }

    pub fn leave_peer(&mut self, peer_id: PeerId) -> Result<(), NetworkError> {
        self.leave_peer_at(peer_id, self.session_tick)
    }

    pub fn leave_peer_at(&mut self, peer_id: PeerId, tick: Tick) -> Result<(), NetworkError> {
        let player_id = self.peers.require(peer_id)?.player_id;
        self.peers.set_ready(peer_id, false)?;
        self.peers.disconnect_peer(peer_id, tick)?;
        self.compatibility_reports.remove(&peer_id);
        self.last_membership_change_tick = tick;
        self.record_lifecycle(
            SessionLifecycleEventKind::Left,
            tick,
            Some(peer_id),
            player_id,
            "peer left session",
        );
        Ok(())
    }

    pub fn reconnect_peer(&mut self, peer_id: PeerId) -> Result<(), NetworkError> {
        self.reconnect_peer_at(peer_id, self.session_tick)
    }

    pub fn reconnect_peer_at(&mut self, peer_id: PeerId, tick: Tick) -> Result<(), NetworkError> {
        let old_peer = self.peers.require(peer_id)?.clone();
        self.record_lifecycle(
            SessionLifecycleEventKind::Reconnecting,
            tick,
            Some(peer_id),
            old_peer.player_id,
            "peer reconnect requested",
        );
        let mut peer = Peer::new_at(peer_id, tick).with_identity(
            old_peer.display_name.clone(),
            old_peer.engine_name.clone(),
            old_peer.adapter_version.clone(),
        );
        peer.player_id = old_peer.player_id;
        peer.capabilities = old_peer.capabilities;
        peer.authoritative_entities = old_peer.authoritative_entities;
        peer.last_input_tick = old_peer.last_input_tick;
        peer.last_sequence_id = old_peer.last_sequence_id;
        peer.transition(ConnectionState::Handshaking, tick)?;
        peer.transition(ConnectionState::Syncing, tick)?;
        self.peers.upsert_peer(peer)?;
        self.last_membership_change_tick = tick;
        self.record_lifecycle(
            SessionLifecycleEventKind::Reconnected,
            tick,
            Some(peer_id),
            old_peer.player_id,
            "peer reconnected and is syncing",
        );
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

    pub fn create_lobby(&mut self) -> Result<(), NetworkError> {
        self.enter_lobby()
    }

    pub fn enter_lobby(&mut self) -> Result<(), NetworkError> {
        let was_lobby = self.phase == SessionPhase::Lobby;
        self.transition_phase(SessionPhase::Lobby)?;
        if !was_lobby {
            self.record_lifecycle(
                SessionLifecycleEventKind::LobbyCreated,
                self.session_tick,
                None,
                None,
                "lobby created",
            );
        }
        Ok(())
    }

    pub fn start_sync(&mut self) -> Result<(), NetworkError> {
        self.transition_phase(SessionPhase::Syncing)
    }

    pub fn start_live(&mut self) -> Result<(), NetworkError> {
        let was_live = self.phase == SessionPhase::Live;
        self.transition_phase(SessionPhase::Live)?;
        if !was_live {
            self.record_lifecycle(
                SessionLifecycleEventKind::LiveStarted,
                self.session_tick,
                None,
                None,
                "session entered live phase",
            );
        }
        Ok(())
    }

    pub fn begin_shutdown(&mut self) -> Result<(), NetworkError> {
        let was_shutting_down = self.phase == SessionPhase::ShuttingDown;
        self.transition_phase(SessionPhase::ShuttingDown)?;
        if !was_shutting_down {
            self.record_lifecycle(
                SessionLifecycleEventKind::TeardownStarted,
                self.session_tick,
                None,
                None,
                "session teardown started",
            );
        }
        Ok(())
    }

    pub fn end(&mut self) -> Result<(), NetworkError> {
        if self.phase == SessionPhase::Ended {
            return Ok(());
        }
        if self.phase != SessionPhase::ShuttingDown {
            self.begin_shutdown()?;
        }
        let was_ended = self.phase == SessionPhase::Ended;
        self.transition_phase(SessionPhase::Ended)?;
        if !was_ended {
            self.record_lifecycle(
                SessionLifecycleEventKind::Ended,
                self.session_tick,
                None,
                None,
                "session ended",
            );
        }
        Ok(())
    }

    pub fn teardown(&mut self) -> Result<(), NetworkError> {
        self.teardown_at(self.session_tick)
    }

    pub fn teardown_at(&mut self, tick: Tick) -> Result<(), NetworkError> {
        if self.phase == SessionPhase::Ended {
            return Ok(());
        }
        self.begin_shutdown()?;
        let peer_ids = self.peers.all_peer_ids();
        for peer_id in peer_ids {
            self.peers.set_ready(peer_id, false)?;
            self.peers.disconnect_peer(peer_id, tick)?;
        }
        self.end()
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
            .set_state_at(peer_id, ConnectionState::Reconnecting, self.session_tick)?;
        self.peers.set_ready(peer_id, false)?;
        let player_id = self.peers.require(peer_id)?.player_id;
        self.record_lifecycle(
            SessionLifecycleEventKind::Reconnecting,
            self.session_tick,
            Some(peer_id),
            player_id,
            "peer entered reconnecting state",
        );
        Ok(())
    }

    pub fn disconnect_peer(&mut self, peer_id: PeerId) -> Result<(), NetworkError> {
        self.peers.set_ready(peer_id, false)?;
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
        for peer_id in &timed_out {
            let _ = self.peers.set_ready(*peer_id, false);
            let player_id = self
                .peers
                .require(*peer_id)
                .ok()
                .and_then(|peer| peer.player_id);
            self.record_lifecycle(
                SessionLifecycleEventKind::Reconnecting,
                self.session_tick,
                Some(*peer_id),
                player_id,
                "heartbeat timeout moved peer to reconnecting",
            );
        }
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

    pub fn ready_peer_ids(&self) -> BTreeSet<PeerId> {
        self.peers.ready_peer_ids()
    }

    pub fn player_identities(&self) -> Vec<SessionPlayerIdentity> {
        self.peers
            .iter()
            .filter_map(|peer| {
                peer.player_id.map(|player_id| SessionPlayerIdentity {
                    peer_id: peer.peer_id,
                    player_id,
                    display_name: peer.display_name.clone(),
                    engine_name: peer.engine_name.clone(),
                    adapter_version: peer.adapter_version.clone(),
                })
            })
            .collect()
    }

    pub fn lifecycle_events(&self) -> &[SessionLifecycleEvent] {
        &self.lifecycle_events
    }

    fn record_lifecycle(
        &mut self,
        kind: SessionLifecycleEventKind,
        tick: Tick,
        peer_id: Option<PeerId>,
        player_id: Option<EntityId>,
        message: impl Into<String>,
    ) {
        self.lifecycle_events.push(SessionLifecycleEvent::new(
            kind, tick, self.phase, peer_id, player_id, message,
        ));
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
            ready_peers: self.ready_peer_ids(),
            player_identities: self.player_identities(),
            lifecycle_events: self.lifecycle_events.clone(),
            compatibility_required: self.compatibility_profile.is_some(),
            compatibility_ok: self.compatibility_ok(),
            compatibility_profile: self.compatibility_profile.clone(),
            compatibility_reports: self.compatibility_reports(),
            compatibility_blockers: self.compatibility_blockers(),
            required_input_peers: self.required_input_peers(),
        }
    }
}
