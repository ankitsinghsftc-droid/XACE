use std::collections::BTreeSet;

use serde::{Deserialize, Serialize};

use super::{session_manager::SessionPlayerIdentity, ConnectionState};
use crate::{EntityId, NetworkError, PeerId, Tick};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PeerCapabilities {
    pub supports_prediction: bool,
    pub supports_rollback: bool,
    pub supports_delta_compression: bool,
    pub max_supported_protocol: u32,
}

impl Default for PeerCapabilities {
    fn default() -> Self {
        Self {
            supports_prediction: true,
            supports_rollback: true,
            supports_delta_compression: true,
            max_supported_protocol: 1,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Peer {
    pub peer_id: PeerId,
    pub state: ConnectionState,
    pub state_since_tick: Tick,
    pub connected_tick: Tick,
    pub last_seen_tick: Tick,
    pub latency_ms: u32,
    pub jitter_ms: u32,
    pub packet_loss_ppm: u32,
    pub last_input_tick: Tick,
    pub last_sequence_id: u64,
    pub missed_heartbeats: u32,
    #[serde(default)]
    pub player_id: Option<EntityId>,
    #[serde(default)]
    pub ready: bool,
    pub display_name: String,
    pub engine_name: String,
    pub adapter_version: String,
    pub capabilities: PeerCapabilities,
    pub authoritative_entities: BTreeSet<EntityId>,
}

impl Peer {
    pub fn new(peer_id: PeerId) -> Self {
        Self::new_at(peer_id, 0)
    }

    pub fn new_at(peer_id: PeerId, tick: Tick) -> Self {
        Self {
            peer_id,
            state: ConnectionState::Connecting,
            state_since_tick: tick,
            connected_tick: tick,
            last_seen_tick: tick,
            latency_ms: 0,
            jitter_ms: 0,
            packet_loss_ppm: 0,
            last_input_tick: 0,
            last_sequence_id: 0,
            missed_heartbeats: 0,
            player_id: None,
            ready: false,
            display_name: format!("peer_{}", peer_id),
            engine_name: String::new(),
            adapter_version: String::new(),
            capabilities: PeerCapabilities::default(),
            authoritative_entities: BTreeSet::new(),
        }
    }

    pub fn with_identity(
        mut self,
        display_name: impl Into<String>,
        engine_name: impl Into<String>,
        adapter_version: impl Into<String>,
    ) -> Self {
        self.display_name = display_name.into();
        self.engine_name = engine_name.into();
        self.adapter_version = adapter_version.into();
        self
    }

    pub fn with_player_identity(mut self, identity: &SessionPlayerIdentity) -> Self {
        self.player_id = Some(identity.player_id);
        self.display_name = identity.display_name.clone();
        self.engine_name = identity.engine_name.clone();
        self.adapter_version = identity.adapter_version.clone();
        self
    }

    pub fn set_ready(&mut self, ready: bool) {
        self.ready = ready;
    }

    pub fn transition(
        &mut self,
        next_state: ConnectionState,
        tick: Tick,
    ) -> Result<(), NetworkError> {
        if !self.state.can_transition_to(next_state) {
            return Err(NetworkError::InvalidOperation(format!(
                "peer {} cannot transition {:?} -> {:?}",
                self.peer_id, self.state, next_state
            )));
        }
        if self.state != next_state {
            self.state = next_state;
            self.state_since_tick = tick;
        }
        if next_state == ConnectionState::Disconnected {
            self.ready = false;
        }
        Ok(())
    }

    pub fn mark_live(&mut self) {
        let _ = self.transition(ConnectionState::Live, self.state_since_tick);
    }

    pub fn observe_heartbeat(&mut self, tick: Tick) {
        self.last_seen_tick = self.last_seen_tick.max(tick);
        self.missed_heartbeats = 0;
    }

    pub fn observe_input(&mut self, tick: Tick, sequence_id: u64) {
        self.last_input_tick = self.last_input_tick.max(tick);
        self.last_sequence_id = self.last_sequence_id.max(sequence_id);
        self.observe_heartbeat(tick);
    }

    pub fn observe_latency(&mut self, rtt_ms: u32, jitter_ms: u32, packet_loss_ppm: u32) {
        self.latency_ms = rtt_ms;
        self.jitter_ms = jitter_ms;
        self.packet_loss_ppm = packet_loss_ppm;
    }

    pub fn assign_authority(&mut self, entity_id: EntityId) {
        self.authoritative_entities.insert(entity_id);
    }

    pub fn revoke_authority(&mut self, entity_id: EntityId) {
        self.authoritative_entities.remove(&entity_id);
    }

    pub fn has_authority(&self, entity_id: EntityId) -> bool {
        self.authoritative_entities.contains(&entity_id)
    }

    pub fn is_timed_out(&self, now_tick: Tick, timeout_ticks: Tick) -> bool {
        now_tick.saturating_sub(self.last_seen_tick) > timeout_ticks
    }

    pub fn can_receive_reliable_messages(&self) -> bool {
        matches!(
            self.state,
            ConnectionState::Handshaking
                | ConnectionState::Syncing
                | ConnectionState::Live
                | ConnectionState::Desynced
                | ConnectionState::Reconnecting
        )
    }
}
