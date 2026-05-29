use std::collections::{BTreeMap, BTreeSet};

use super::{ConnectionState, Peer};
use crate::{EntityId, NetworkError, PeerId, Tick};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PeerManagerStats {
    pub total: usize,
    pub live: usize,
    pub disconnected: usize,
    pub desynced: usize,
}

#[derive(Debug, Clone, Default)]
pub struct PeerManager {
    peers: BTreeMap<PeerId, Peer>,
}

impl PeerManager {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn add_peer(&mut self, peer_id: PeerId) -> Result<(), NetworkError> {
        self.add_peer_at(peer_id, 0).map(|_| ())
    }

    pub fn add_peer_at(&mut self, peer_id: PeerId, tick: Tick) -> Result<&Peer, NetworkError> {
        if peer_id == 0 {
            return Err(NetworkError::InvalidOperation(
                "peer_id 0 is reserved".to_string(),
            ));
        }
        if self.peers.contains_key(&peer_id) {
            return Err(NetworkError::InvalidOperation(format!(
                "peer {} already exists",
                peer_id
            )));
        }
        self.peers.insert(peer_id, Peer::new_at(peer_id, tick));
        Ok(self.peers.get(&peer_id).expect("peer inserted"))
    }

    pub fn upsert_peer(&mut self, peer: Peer) -> Result<(), NetworkError> {
        if peer.peer_id == 0 {
            return Err(NetworkError::InvalidOperation(
                "peer_id 0 is reserved".to_string(),
            ));
        }
        self.peers.insert(peer.peer_id, peer);
        Ok(())
    }

    pub fn remove_peer(&mut self, peer_id: PeerId) -> Option<Peer> {
        self.peers.remove(&peer_id)
    }

    pub fn disconnect_peer(&mut self, peer_id: PeerId, tick: Tick) -> Result<(), NetworkError> {
        self.require_mut(peer_id)?
            .transition(ConnectionState::Disconnected, tick)
    }

    pub fn get(&self, peer_id: PeerId) -> Option<&Peer> {
        self.peers.get(&peer_id)
    }

    pub fn get_mut(&mut self, peer_id: PeerId) -> Option<&mut Peer> {
        self.peers.get_mut(&peer_id)
    }

    pub fn require(&self, peer_id: PeerId) -> Result<&Peer, NetworkError> {
        self.peers
            .get(&peer_id)
            .ok_or(NetworkError::UnknownPeer(peer_id))
    }

    pub fn require_mut(&mut self, peer_id: PeerId) -> Result<&mut Peer, NetworkError> {
        self.peers
            .get_mut(&peer_id)
            .ok_or(NetworkError::UnknownPeer(peer_id))
    }

    pub fn set_state(
        &mut self,
        peer_id: PeerId,
        state: ConnectionState,
    ) -> Result<(), NetworkError> {
        self.set_state_at(peer_id, state, 0)
    }

    pub fn set_state_at(
        &mut self,
        peer_id: PeerId,
        state: ConnectionState,
        tick: Tick,
    ) -> Result<(), NetworkError> {
        self.require_mut(peer_id)?.transition(state, tick)
    }

    pub fn observe_input(
        &mut self,
        peer_id: PeerId,
        tick: Tick,
        sequence_id: u64,
    ) -> Result<(), NetworkError> {
        self.require_mut(peer_id)?.observe_input(tick, sequence_id);
        Ok(())
    }

    pub fn observe_heartbeat(&mut self, peer_id: PeerId, tick: Tick) -> Result<(), NetworkError> {
        self.require_mut(peer_id)?.observe_heartbeat(tick);
        Ok(())
    }

    pub fn assign_authority(
        &mut self,
        peer_id: PeerId,
        entity_id: EntityId,
    ) -> Result<(), NetworkError> {
        self.require_mut(peer_id)?.assign_authority(entity_id);
        Ok(())
    }

    pub fn revoke_authority(
        &mut self,
        peer_id: PeerId,
        entity_id: EntityId,
    ) -> Result<(), NetworkError> {
        self.require_mut(peer_id)?.revoke_authority(entity_id);
        Ok(())
    }

    pub fn authority_owner(&self, entity_id: EntityId) -> Option<PeerId> {
        self.peers
            .iter()
            .find(|(_, peer)| peer.has_authority(entity_id))
            .map(|(&peer_id, _)| peer_id)
    }

    pub fn timed_out_peers(&self, now_tick: Tick, timeout_ticks: Tick) -> Vec<PeerId> {
        self.peers
            .values()
            .filter(|peer| !peer.state.is_terminal() && peer.is_timed_out(now_tick, timeout_ticks))
            .map(|peer| peer.peer_id)
            .collect()
    }

    pub fn mark_timeouts_reconnecting(
        &mut self,
        now_tick: Tick,
        timeout_ticks: Tick,
    ) -> Result<Vec<PeerId>, NetworkError> {
        let timed_out = self.timed_out_peers(now_tick, timeout_ticks);
        for peer_id in &timed_out {
            let peer = self.require_mut(*peer_id)?;
            peer.missed_heartbeats = peer.missed_heartbeats.saturating_add(1);
            if peer.state != ConnectionState::Reconnecting {
                peer.transition(ConnectionState::Reconnecting, now_tick)?;
            }
        }
        Ok(timed_out)
    }

    pub fn live_peer_ids(&self) -> BTreeSet<PeerId> {
        self.peers
            .iter()
            .filter(|(_, peer)| peer.state.can_simulate())
            .map(|(&peer_id, _)| peer_id)
            .collect()
    }

    pub fn peers_in_state(&self, state: ConnectionState) -> Vec<PeerId> {
        self.peers
            .iter()
            .filter(|(_, peer)| peer.state == state)
            .map(|(&peer_id, _)| peer_id)
            .collect()
    }

    pub fn all_peer_ids(&self) -> BTreeSet<PeerId> {
        self.peers.keys().copied().collect()
    }

    pub fn iter(&self) -> impl Iterator<Item = &Peer> {
        self.peers.values()
    }

    pub fn len(&self) -> usize {
        self.peers.len()
    }

    pub fn is_empty(&self) -> bool {
        self.peers.is_empty()
    }

    pub fn stats(&self) -> PeerManagerStats {
        PeerManagerStats {
            total: self.peers.len(),
            live: self.peers_in_state(ConnectionState::Live).len(),
            disconnected: self.peers_in_state(ConnectionState::Disconnected).len(),
            desynced: self.peers_in_state(ConnectionState::Desynced).len(),
        }
    }
}
