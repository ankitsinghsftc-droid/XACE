use std::collections::{BTreeMap, BTreeSet, VecDeque};

use serde::{Deserialize, Serialize};

use super::InputPacket;
use crate::{NetworkError, PeerId, Tick};

const DEFAULT_MAX_PACKETS_PER_PEER: usize = 256;
const DEFAULT_MAX_FUTURE_TICKS: Tick = 180;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum InputInsertOutcome {
    Inserted,
    DuplicateRetransmit,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct MissingInputRange {
    pub from_tick: Tick,
    pub to_tick: Tick,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InputBufferConfig {
    pub max_packets_per_peer: usize,
    pub max_future_ticks: Tick,
    pub allow_empty_packets: bool,
}

impl Default for InputBufferConfig {
    fn default() -> Self {
        Self {
            max_packets_per_peer: DEFAULT_MAX_PACKETS_PER_PEER,
            max_future_ticks: DEFAULT_MAX_FUTURE_TICKS,
            allow_empty_packets: true,
        }
    }
}

#[derive(Debug, Clone, Default)]
struct PeerInputState {
    packets: BTreeMap<Tick, InputPacket>,
    digests_by_tick: BTreeMap<Tick, String>,
    arrival_order: VecDeque<Tick>,
    last_sequence: u64,
    highest_tick_seen: Option<Tick>,
    missing_ticks: BTreeSet<Tick>,
}

#[derive(Debug, Clone)]
pub struct InputBuffer {
    config: InputBufferConfig,
    peers: BTreeMap<PeerId, PeerInputState>,
    accepted_count: u64,
    duplicate_count: u64,
    rejected_count: u64,
}

impl Default for InputBuffer {
    fn default() -> Self {
        Self::new()
    }
}

impl InputBuffer {
    pub fn new() -> Self {
        Self::with_config(InputBufferConfig::default())
    }

    pub fn with_config(config: InputBufferConfig) -> Self {
        Self {
            config,
            peers: BTreeMap::new(),
            accepted_count: 0,
            duplicate_count: 0,
            rejected_count: 0,
        }
    }

    pub fn insert(&mut self, packet: InputPacket) -> Result<(), NetworkError> {
        self.insert_with_outcome(packet).map(|_| ())
    }

    pub fn insert_with_outcome(
        &mut self,
        packet: InputPacket,
    ) -> Result<InputInsertOutcome, NetworkError> {
        if let Err(err) = self.validate_incoming(&packet) {
            self.rejected_count += 1;
            return Err(err);
        }

        let peer_id = packet.peer_id;
        let tick = packet.tick;
        let sequence_id = packet.sequence_id;
        let digest = packet.deterministic_digest();
        let state = self.peers.entry(peer_id).or_default();

        if let Some(existing_digest) = state.digests_by_tick.get(&tick) {
            if existing_digest == &digest {
                self.duplicate_count += 1;
                return Ok(InputInsertOutcome::DuplicateRetransmit);
            }
            self.rejected_count += 1;
            return Err(NetworkError::DuplicateInput {
                peer_id,
                tick,
                sequence_id,
            });
        }

        if sequence_id <= state.last_sequence {
            self.rejected_count += 1;
            return Err(NetworkError::StaleInput {
                peer_id,
                sequence_id,
                last_sequence_id: state.last_sequence,
            });
        }

        if state.packets.len() >= self.config.max_packets_per_peer {
            self.rejected_count += 1;
            return Err(NetworkError::InputBufferOverflow {
                peer_id,
                limit: self.config.max_packets_per_peer,
            });
        }

        if let Some(highest_tick) = state.highest_tick_seen {
            if tick > highest_tick + 1 {
                for missing_tick in (highest_tick + 1)..tick {
                    state.missing_ticks.insert(missing_tick);
                }
            }
        }

        state.last_sequence = sequence_id;
        state.highest_tick_seen = Some(state.highest_tick_seen.map_or(tick, |old| old.max(tick)));
        state.missing_ticks.remove(&tick);
        state.arrival_order.push_back(tick);
        state.digests_by_tick.insert(tick, digest);
        state.packets.insert(tick, packet);
        self.accepted_count += 1;
        Ok(InputInsertOutcome::Inserted)
    }

    pub fn has_input(&self, peer_id: PeerId, tick: Tick) -> bool {
        self.peers
            .get(&peer_id)
            .is_some_and(|state| state.packets.contains_key(&tick))
    }

    pub fn get(&self, peer_id: PeerId, tick: Tick) -> Option<&InputPacket> {
        self.peers.get(&peer_id)?.packets.get(&tick)
    }

    pub fn take_for_tick(&mut self, tick: Tick, peers: &BTreeSet<PeerId>) -> Vec<InputPacket> {
        let mut out = Vec::with_capacity(peers.len());
        for peer_id in peers {
            if let Some(state) = self.peers.get_mut(peer_id) {
                if let Some(packet) = state.packets.remove(&tick) {
                    state.digests_by_tick.remove(&tick);
                    remove_arrival_tick(&mut state.arrival_order, tick);
                    out.push(packet);
                }
            }
        }
        out.sort_by_key(|packet| (packet.peer_id, packet.sequence_id, packet.tick));
        out
    }

    pub fn take_ready_ticks(
        &mut self,
        peers: &BTreeSet<PeerId>,
        up_to_tick: Tick,
    ) -> BTreeMap<Tick, Vec<InputPacket>> {
        let mut ready = BTreeMap::new();
        for tick in self.complete_ticks(peers, up_to_tick) {
            ready.insert(tick, self.take_for_tick(tick, peers));
        }
        ready
    }

    pub fn complete_ticks(&self, peers: &BTreeSet<PeerId>, up_to_tick: Tick) -> Vec<Tick> {
        if peers.is_empty() {
            return Vec::new();
        }

        let mut candidate_ticks: Option<BTreeSet<Tick>> = None;
        for peer_id in peers {
            let Some(state) = self.peers.get(peer_id) else {
                return Vec::new();
            };
            let peer_ticks: BTreeSet<Tick> = state
                .packets
                .keys()
                .copied()
                .filter(|tick| *tick <= up_to_tick)
                .collect();
            candidate_ticks = Some(match candidate_ticks {
                Some(current) => current.intersection(&peer_ticks).copied().collect(),
                None => peer_ticks,
            });
        }

        candidate_ticks.unwrap_or_default().into_iter().collect()
    }

    pub fn missing_for_tick(&self, tick: Tick, peers: &BTreeSet<PeerId>) -> Vec<PeerId> {
        peers
            .iter()
            .copied()
            .filter(|peer_id| !self.has_input(*peer_id, tick))
            .collect()
    }

    pub fn missing_ranges(&self, peer_id: PeerId) -> Vec<MissingInputRange> {
        let Some(state) = self.peers.get(&peer_id) else {
            return Vec::new();
        };
        collapse_ranges(&state.missing_ticks)
    }

    pub fn missing_ticks(&self, peer_id: PeerId) -> Vec<Tick> {
        self.peers
            .get(&peer_id)
            .map(|state| state.missing_ticks.iter().copied().collect())
            .unwrap_or_default()
    }

    pub fn prune_before(&mut self, tick: Tick) {
        for state in self.peers.values_mut() {
            let to_remove: Vec<Tick> = state.packets.range(..tick).map(|(tick, _)| *tick).collect();
            for old_tick in to_remove {
                state.packets.remove(&old_tick);
                state.digests_by_tick.remove(&old_tick);
                remove_arrival_tick(&mut state.arrival_order, old_tick);
            }
            state.missing_ticks = state.missing_ticks.split_off(&tick);
        }
    }

    pub fn packet_count_for_peer(&self, peer_id: PeerId) -> usize {
        self.peers
            .get(&peer_id)
            .map(|state| state.packets.len())
            .unwrap_or(0)
    }

    pub fn total_packet_count(&self) -> usize {
        self.peers.values().map(|state| state.packets.len()).sum()
    }

    pub fn accepted_count(&self) -> u64 {
        self.accepted_count
    }

    pub fn duplicate_count(&self) -> u64 {
        self.duplicate_count
    }

    pub fn rejected_count(&self) -> u64 {
        self.rejected_count
    }

    fn validate_incoming(&self, packet: &InputPacket) -> Result<(), NetworkError> {
        packet.validate()?;
        if !self.config.allow_empty_packets && packet.actions.is_empty() {
            return Err(NetworkError::InvalidInput(
                "empty input packets are disabled for this buffer".to_string(),
            ));
        }

        let Some(state) = self.peers.get(&packet.peer_id) else {
            return Ok(());
        };

        if let Some(highest_tick) = state.highest_tick_seen {
            if packet.tick > highest_tick + self.config.max_future_ticks {
                return Err(NetworkError::InvalidInput(format!(
                    "packet tick {} is more than {} ticks ahead of peer high-water {}",
                    packet.tick, self.config.max_future_ticks, highest_tick
                )));
            }
        }
        Ok(())
    }
}

fn remove_arrival_tick(arrival_order: &mut VecDeque<Tick>, tick: Tick) {
    if let Some(index) = arrival_order
        .iter()
        .position(|candidate| *candidate == tick)
    {
        arrival_order.remove(index);
    }
}

fn collapse_ranges(ticks: &BTreeSet<Tick>) -> Vec<MissingInputRange> {
    let mut ranges = Vec::new();
    let mut iter = ticks.iter().copied();
    let Some(mut start) = iter.next() else {
        return ranges;
    };
    let mut end = start;

    for tick in iter {
        if tick == end + 1 {
            end = tick;
        } else {
            ranges.push(MissingInputRange {
                from_tick: start,
                to_tick: end,
            });
            start = tick;
            end = tick;
        }
    }

    ranges.push(MissingInputRange {
        from_tick: start,
        to_tick: end,
    });
    ranges
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::input::InputAction;

    #[test]
    fn exact_retransmit_is_idempotent() {
        let mut buffer = InputBuffer::new();
        let packet = InputPacket::with_actions(1, 10, 1, vec![InputAction::button("jump", true)]);
        assert_eq!(
            buffer.insert_with_outcome(packet.clone()).unwrap(),
            InputInsertOutcome::Inserted
        );
        assert_eq!(
            buffer.insert_with_outcome(packet).unwrap(),
            InputInsertOutcome::DuplicateRetransmit
        );
        assert_eq!(buffer.duplicate_count(), 1);
    }

    #[test]
    fn conflicting_duplicate_tick_is_rejected() {
        let mut buffer = InputBuffer::new();
        buffer
            .insert(InputPacket::with_actions(1, 10, 1, Vec::new()))
            .unwrap();
        let conflict = InputPacket::with_actions(1, 10, 2, vec![InputAction::axis("move_x", 1.0)]);
        assert!(buffer.insert(conflict).is_err());
    }

    #[test]
    fn missing_ticks_are_collapsed_into_ranges() {
        let mut buffer = InputBuffer::new();
        buffer.insert(InputPacket::unsigned(1, 1, 1)).unwrap();
        buffer.insert(InputPacket::unsigned(1, 5, 2)).unwrap();
        assert_eq!(
            buffer.missing_ranges(1),
            vec![MissingInputRange {
                from_tick: 2,
                to_tick: 4,
            }]
        );
    }
}
