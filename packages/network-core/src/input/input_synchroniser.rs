use std::collections::{BTreeMap, BTreeSet};

use super::{
    InputBuffer, InputBufferConfig, InputInsertOutcome, InputLog, InputPacket, MissingInputRange,
};
use crate::{NetworkError, PeerId, Tick};

#[derive(Debug, Clone, PartialEq)]
pub enum LockstepDecision {
    Offline,
    Wait {
        tick: Tick,
        missing_peers: Vec<PeerId>,
    },
    Release {
        tick: Tick,
        packets: Vec<InputPacket>,
    },
    AlreadyReleased {
        tick: Tick,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LockstepMode {
    Offline,
    Lockstep,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TimeoutPolicy {
    WaitForever,
    ReleaseEmptyAfter { wait_ticks: Tick },
    ErrorAfter { wait_ticks: Tick },
}

#[derive(Debug, Clone)]
pub struct InputSynchroniserConfig {
    pub mode: LockstepMode,
    pub fixed_delay_ticks: u32,
    pub timeout_policy: TimeoutPolicy,
    pub buffer_config: InputBufferConfig,
    pub keep_released_tick_history: usize,
    pub auto_log_released_inputs: bool,
}

impl Default for InputSynchroniserConfig {
    fn default() -> Self {
        Self {
            mode: LockstepMode::Lockstep,
            fixed_delay_ticks: 0,
            timeout_policy: TimeoutPolicy::WaitForever,
            buffer_config: InputBufferConfig::default(),
            keep_released_tick_history: 512,
            auto_log_released_inputs: true,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PeerReadiness {
    pub peer_id: PeerId,
    pub has_input: bool,
    pub missing_ranges: Vec<MissingInputRange>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LockstepStatus {
    pub sim_tick: Tick,
    pub input_tick: Option<Tick>,
    pub required_peers: Vec<PeerId>,
    pub missing_peers: Vec<PeerId>,
    pub waited_ticks: Tick,
    pub can_release: bool,
}

#[derive(Debug, Clone)]
pub struct InputSynchroniser {
    config: InputSynchroniserConfig,
    required_peers: BTreeSet<PeerId>,
    buffer: InputBuffer,
    input_log: InputLog,
    released_ticks: BTreeSet<Tick>,
    first_wait_seen: BTreeMap<Tick, Tick>,
    last_released_tick: Option<Tick>,
}

impl InputSynchroniser {
    pub fn new(required_peers: BTreeSet<PeerId>, fixed_delay_ticks: u32) -> Self {
        Self::with_config(
            required_peers,
            InputSynchroniserConfig {
                fixed_delay_ticks,
                ..InputSynchroniserConfig::default()
            },
        )
    }

    pub fn with_config(required_peers: BTreeSet<PeerId>, config: InputSynchroniserConfig) -> Self {
        let buffer = InputBuffer::with_config(config.buffer_config.clone());
        Self {
            config,
            required_peers,
            buffer,
            input_log: InputLog::new(),
            released_ticks: BTreeSet::new(),
            first_wait_seen: BTreeMap::new(),
            last_released_tick: None,
        }
    }

    pub fn submit(&mut self, packet: InputPacket) -> Result<(), NetworkError> {
        self.submit_with_outcome(packet).map(|_| ())
    }

    pub fn submit_with_outcome(
        &mut self,
        packet: InputPacket,
    ) -> Result<InputInsertOutcome, NetworkError> {
        if self.config.mode == LockstepMode::Offline {
            return Err(NetworkError::InvalidOperation(
                "cannot submit network input while synchroniser is offline".to_string(),
            ));
        }
        if !self.required_peers.contains(&packet.peer_id) {
            return Err(NetworkError::UnknownPeer(packet.peer_id));
        }
        self.buffer.insert_with_outcome(packet)
    }

    pub fn decision_for_sim_tick(&mut self, sim_tick: Tick) -> LockstepDecision {
        match self.release_for_sim_tick(sim_tick) {
            Ok(decision) => decision,
            Err(err) => {
                log_like_error(&err);
                let target_tick = self.target_tick_for_sim_tick(sim_tick).unwrap_or(0);
                LockstepDecision::Wait {
                    tick: target_tick,
                    missing_peers: self
                        .buffer
                        .missing_for_tick(target_tick, &self.required_peers),
                }
            }
        }
    }

    pub fn release_for_sim_tick(
        &mut self,
        sim_tick: Tick,
    ) -> Result<LockstepDecision, NetworkError> {
        if self.config.mode == LockstepMode::Offline || self.required_peers.is_empty() {
            return Ok(LockstepDecision::Offline);
        }

        let Some(target_tick) = self.pending_or_target_tick_for_sim_tick(sim_tick) else {
            return Ok(LockstepDecision::Wait {
                tick: 0,
                missing_peers: self.required_peers.iter().copied().collect(),
            });
        };

        if self.released_ticks.contains(&target_tick) {
            return Ok(LockstepDecision::AlreadyReleased { tick: target_tick });
        }

        let missing = self
            .buffer
            .missing_for_tick(target_tick, &self.required_peers);
        if missing.is_empty() {
            return Ok(self.release_tick(target_tick));
        }

        let waited_ticks = self.waited_ticks(target_tick, sim_tick);
        match self.config.timeout_policy {
            TimeoutPolicy::WaitForever => Ok(LockstepDecision::Wait {
                tick: target_tick,
                missing_peers: missing,
            }),
            TimeoutPolicy::ErrorAfter { wait_ticks } if waited_ticks >= wait_ticks => {
                Err(NetworkError::LockstepWaiting {
                    tick: target_tick,
                    missing_peers: missing,
                })
            }
            TimeoutPolicy::ReleaseEmptyAfter { wait_ticks } if waited_ticks >= wait_ticks => {
                let synthetic = self.synthetic_empty_packets(target_tick, &missing);
                for packet in synthetic {
                    let _ = self.buffer.insert_with_outcome(packet);
                }
                Ok(self.release_tick(target_tick))
            }
            _ => Ok(LockstepDecision::Wait {
                tick: target_tick,
                missing_peers: missing,
            }),
        }
    }

    pub fn status_for_sim_tick(&mut self, sim_tick: Tick) -> LockstepStatus {
        let input_tick = self.pending_or_target_tick_for_sim_tick(sim_tick);
        let missing_peers = input_tick
            .map(|tick| self.buffer.missing_for_tick(tick, &self.required_peers))
            .unwrap_or_else(|| self.required_peers.iter().copied().collect());
        let waited_ticks = input_tick.map_or(0, |tick| self.waited_ticks(tick, sim_tick));

        LockstepStatus {
            sim_tick,
            input_tick,
            required_peers: self.required_peers.iter().copied().collect(),
            can_release: input_tick.is_some()
                && missing_peers.is_empty()
                && !self.released_ticks.contains(&input_tick.unwrap()),
            missing_peers,
            waited_ticks,
        }
    }

    pub fn readiness_for_tick(&self, tick: Tick) -> Vec<PeerReadiness> {
        self.required_peers
            .iter()
            .copied()
            .map(|peer_id| PeerReadiness {
                peer_id,
                has_input: self.buffer.has_input(peer_id, tick),
                missing_ranges: self.buffer.missing_ranges(peer_id),
            })
            .collect()
    }

    pub fn target_tick_for_sim_tick(&self, sim_tick: Tick) -> Option<Tick> {
        sim_tick.checked_sub(self.config.fixed_delay_ticks as u64)
    }

    pub fn pending_or_target_tick_for_sim_tick(&self, sim_tick: Tick) -> Option<Tick> {
        self.first_wait_seen
            .keys()
            .next()
            .copied()
            .or_else(|| self.target_tick_for_sim_tick(sim_tick))
    }

    pub fn required_peers(&self) -> &BTreeSet<PeerId> {
        &self.required_peers
    }

    pub fn set_required_peers(&mut self, required_peers: BTreeSet<PeerId>) {
        self.required_peers = required_peers;
    }

    pub fn add_required_peer(&mut self, peer_id: PeerId) {
        self.required_peers.insert(peer_id);
    }

    pub fn remove_required_peer(&mut self, peer_id: PeerId) {
        self.required_peers.remove(&peer_id);
    }

    pub fn fixed_delay_ticks(&self) -> u32 {
        self.config.fixed_delay_ticks
    }

    pub fn set_fixed_delay_ticks(&mut self, fixed_delay_ticks: u32) {
        self.config.fixed_delay_ticks = fixed_delay_ticks;
    }

    pub fn input_log(&self) -> &InputLog {
        &self.input_log
    }

    pub fn buffer(&self) -> &InputBuffer {
        &self.buffer
    }

    pub fn buffer_mut(&mut self) -> &mut InputBuffer {
        &mut self.buffer
    }

    pub fn last_released_tick(&self) -> Option<Tick> {
        self.last_released_tick
    }

    fn release_tick(&mut self, target_tick: Tick) -> LockstepDecision {
        let packets = self.buffer.take_for_tick(target_tick, &self.required_peers);
        if self.config.auto_log_released_inputs {
            for packet in &packets {
                let _ = self.input_log.append_result(packet.clone());
            }
        }
        self.released_ticks.insert(target_tick);
        self.last_released_tick = Some(target_tick);
        self.first_wait_seen.remove(&target_tick);
        self.prune_released_history();
        LockstepDecision::Release {
            tick: target_tick,
            packets,
        }
    }

    fn waited_ticks(&mut self, target_tick: Tick, sim_tick: Tick) -> Tick {
        let first_seen = self.first_wait_seen.entry(target_tick).or_insert(sim_tick);
        sim_tick.saturating_sub(*first_seen)
    }

    fn synthetic_empty_packets(&self, tick: Tick, missing_peers: &[PeerId]) -> Vec<InputPacket> {
        missing_peers
            .iter()
            .copied()
            .map(|peer_id| {
                let sequence_id = self
                    .buffer
                    .get(peer_id, tick.saturating_sub(1))
                    .map(|packet| packet.sequence_id + 1)
                    .unwrap_or(1);
                InputPacket::unsigned(peer_id, tick, sequence_id).with_device("synthetic-timeout")
            })
            .collect()
    }

    fn prune_released_history(&mut self) {
        while self.released_ticks.len() > self.config.keep_released_tick_history {
            if let Some(oldest) = self.released_ticks.iter().next().copied() {
                self.released_ticks.remove(&oldest);
            } else {
                break;
            }
        }
    }
}

fn log_like_error(err: &NetworkError) {
    let _ = err;
}
