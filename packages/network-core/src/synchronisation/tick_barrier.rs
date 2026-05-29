use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};

use crate::{NetworkError, PeerId, Tick};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum BarrierState {
    Open(Tick),
    Waiting {
        tick: Tick,
        missing_peers: Vec<PeerId>,
    },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BarrierReadiness {
    pub tick: Tick,
    pub required_peers: BTreeSet<PeerId>,
    pub ready_peers: BTreeSet<PeerId>,
    pub missing_peers: BTreeSet<PeerId>,
    pub late_peers: BTreeSet<PeerId>,
}

impl BarrierReadiness {
    pub fn is_open(&self) -> bool {
        self.missing_peers.is_empty()
    }
}

#[derive(Debug, Clone)]
pub struct TickBarrier {
    required_peers: BTreeSet<PeerId>,
    ready: BTreeMap<Tick, BTreeSet<PeerId>>,
    tick: Tick,
    opened_ticks: BTreeSet<Tick>,
    max_tracked_ticks: usize,
}

impl TickBarrier {
    pub fn new(required_peers: BTreeSet<PeerId>) -> Self {
        Self::with_capacity(required_peers, 64)
    }

    pub fn with_capacity(required_peers: BTreeSet<PeerId>, max_tracked_ticks: usize) -> Self {
        Self {
            required_peers: required_peers
                .into_iter()
                .filter(|peer_id| *peer_id != 0)
                .collect(),
            ready: BTreeMap::new(),
            tick: 0,
            opened_ticks: BTreeSet::new(),
            max_tracked_ticks: max_tracked_ticks.max(1),
        }
    }

    pub fn mark_ready(&mut self, peer_id: PeerId, tick: Tick) {
        let _ = self.mark_ready_result(peer_id, tick);
    }

    pub fn mark_ready_result(&mut self, peer_id: PeerId, tick: Tick) -> Result<bool, NetworkError> {
        validate_peer_id(peer_id)?;
        if !self.required_peers.contains(&peer_id) {
            return Ok(false);
        }
        if self.opened_ticks.contains(&tick) {
            return Ok(false);
        }
        let inserted = self.ready.entry(tick).or_default().insert(peer_id);
        self.prune_ready_windows();
        if self.readiness_for_tick(tick).is_open() {
            self.opened_ticks.insert(tick);
        }
        Ok(inserted)
    }

    pub fn state(&self) -> BarrierState {
        let readiness = self.readiness();
        if readiness.is_open() {
            BarrierState::Open(self.tick)
        } else {
            BarrierState::Waiting {
                tick: self.tick,
                missing_peers: readiness.missing_peers.into_iter().collect(),
            }
        }
    }

    pub fn readiness(&self) -> BarrierReadiness {
        self.readiness_for_tick(self.tick)
    }

    pub fn readiness_for_tick(&self, tick: Tick) -> BarrierReadiness {
        let ready_peers = self.ready.get(&tick).cloned().unwrap_or_default();
        let missing_peers = self
            .required_peers
            .difference(&ready_peers)
            .copied()
            .collect();
        let late_peers = self
            .ready
            .range(..tick)
            .flat_map(|(_, peers)| peers.iter().copied())
            .filter(|peer_id| self.required_peers.contains(peer_id))
            .collect();
        BarrierReadiness {
            tick,
            required_peers: self.required_peers.clone(),
            ready_peers,
            missing_peers,
            late_peers,
        }
    }

    pub fn advance(&mut self) {
        self.advance_to(self.tick.saturating_add(1));
    }

    pub fn advance_to(&mut self, tick: Tick) {
        self.tick = tick;
        self.prune_ready_windows();
    }

    pub fn set_required_peers(&mut self, peers: BTreeSet<PeerId>) {
        self.required_peers = peers.into_iter().filter(|peer_id| *peer_id != 0).collect();
        self.ready
            .values_mut()
            .for_each(|ready| ready.retain(|peer_id| self.required_peers.contains(peer_id)));
    }

    pub fn add_required_peer(&mut self, peer_id: PeerId) -> Result<bool, NetworkError> {
        validate_peer_id(peer_id)?;
        Ok(self.required_peers.insert(peer_id))
    }

    pub fn remove_required_peer(&mut self, peer_id: PeerId) -> bool {
        let removed = self.required_peers.remove(&peer_id);
        if removed {
            for peers in self.ready.values_mut() {
                peers.remove(&peer_id);
            }
        }
        removed
    }

    pub fn required_peers(&self) -> &BTreeSet<PeerId> {
        &self.required_peers
    }

    pub fn current_tick(&self) -> Tick {
        self.tick
    }

    pub fn opened_ticks(&self) -> &BTreeSet<Tick> {
        &self.opened_ticks
    }

    fn prune_ready_windows(&mut self) {
        while self.ready.len() > self.max_tracked_ticks {
            let Some(oldest) = self.ready.keys().next().copied() else {
                break;
            };
            self.ready.remove(&oldest);
        }
        let min_tick = self
            .tick
            .saturating_sub(self.max_tracked_ticks.saturating_sub(1) as u64);
        let stale_ticks = self
            .ready
            .range(..min_tick)
            .map(|(&tick, _)| tick)
            .collect::<Vec<_>>();
        for tick in stale_ticks {
            self.ready.remove(&tick);
        }
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
