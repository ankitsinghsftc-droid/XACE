use std::collections::{BTreeMap, BTreeSet};

use super::InputPacket;
use crate::{NetworkError, PeerId, Tick};

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct DeliveryKey {
    pub to_peer: PeerId,
    pub from_peer: PeerId,
    pub input_tick: Tick,
    pub sequence_id: u64,
}

impl DeliveryKey {
    pub fn new(to_peer: PeerId, packet: &InputPacket) -> Self {
        Self {
            to_peer,
            from_peer: packet.peer_id,
            input_tick: packet.tick,
            sequence_id: packet.sequence_id,
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct PendingDelivery {
    pub key: DeliveryKey,
    pub packet: InputPacket,
    pub attempts: u32,
    pub first_sent_tick: Tick,
    pub last_sent_tick: Tick,
    pub next_retry_tick: Tick,
}

impl PendingDelivery {
    pub fn to_peer(&self) -> PeerId {
        self.key.to_peer
    }

    pub fn age_ticks(&self, now_tick: Tick) -> Tick {
        now_tick.saturating_sub(self.first_sent_tick)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DeliveryAckResult {
    Acked,
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DeliveryQueueResult {
    Queued,
    AlreadyPending,
}

#[derive(Debug, Clone, PartialEq)]
pub struct DeliveryFailure {
    pub delivery: PendingDelivery,
    pub reason: DeliveryFailureReason,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DeliveryFailureReason {
    MaxAttemptsExceeded,
    Expired,
}

#[derive(Debug, Clone)]
pub struct InputBroadcasterConfig {
    pub resend_after_ticks: Tick,
    pub max_attempts: u32,
    pub expire_after_ticks: Tick,
    pub queue_self_echo: bool,
}

impl Default for InputBroadcasterConfig {
    fn default() -> Self {
        Self {
            resend_after_ticks: 3,
            max_attempts: 8,
            expire_after_ticks: 180,
            queue_self_echo: false,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct InputBroadcasterStats {
    pub pending_count: usize,
    pub queued_total: u64,
    pub acked_total: u64,
    pub retransmitted_total: u64,
    pub failed_total: u64,
}

#[derive(Debug, Clone)]
pub struct InputBroadcaster {
    config: InputBroadcasterConfig,
    pending: BTreeMap<DeliveryKey, PendingDelivery>,
    queued_total: u64,
    acked_total: u64,
    retransmitted_total: u64,
    failed_total: u64,
}

impl Default for InputBroadcaster {
    fn default() -> Self {
        Self::new()
    }
}

impl InputBroadcaster {
    pub fn new() -> Self {
        Self::with_config(InputBroadcasterConfig::default())
    }

    pub fn with_config(config: InputBroadcasterConfig) -> Self {
        Self {
            config,
            pending: BTreeMap::new(),
            queued_total: 0,
            acked_total: 0,
            retransmitted_total: 0,
            failed_total: 0,
        }
    }

    pub fn queue_for_peers(
        &mut self,
        packet: InputPacket,
        peers: &BTreeSet<PeerId>,
        now_tick: Tick,
    ) {
        let _ = self.queue_for_peers_result(packet, peers, now_tick);
    }

    pub fn queue_for_peers_result(
        &mut self,
        packet: InputPacket,
        peers: &BTreeSet<PeerId>,
        now_tick: Tick,
    ) -> Result<Vec<DeliveryQueueResult>, NetworkError> {
        packet.validate()?;
        let mut results = Vec::with_capacity(peers.len());
        for &peer_id in peers {
            if !self.config.queue_self_echo && peer_id == packet.peer_id {
                continue;
            }
            results.push(self.queue_one(peer_id, packet.clone(), now_tick)?);
        }
        Ok(results)
    }

    pub fn queue_one(
        &mut self,
        to_peer: PeerId,
        packet: InputPacket,
        now_tick: Tick,
    ) -> Result<DeliveryQueueResult, NetworkError> {
        packet.validate()?;
        if to_peer == 0 {
            return Err(NetworkError::UnknownPeer(to_peer));
        }
        let key = DeliveryKey::new(to_peer, &packet);
        if self.pending.contains_key(&key) {
            return Ok(DeliveryQueueResult::AlreadyPending);
        }

        self.pending.insert(
            key,
            PendingDelivery {
                key,
                packet,
                attempts: 1,
                first_sent_tick: now_tick,
                last_sent_tick: now_tick,
                next_retry_tick: now_tick.saturating_add(self.config.resend_after_ticks),
            },
        );
        self.queued_total += 1;
        Ok(DeliveryQueueResult::Queued)
    }

    pub fn mark_acked(&mut self, peer_id: PeerId, sequence_id: u64) {
        let keys: Vec<_> = self
            .pending
            .keys()
            .copied()
            .filter(|key| key.to_peer == peer_id && key.sequence_id == sequence_id)
            .collect();
        for key in keys {
            self.ack_key(key);
        }
    }

    pub fn ack_key(&mut self, key: DeliveryKey) -> DeliveryAckResult {
        if self.pending.remove(&key).is_some() {
            self.acked_total += 1;
            DeliveryAckResult::Acked
        } else {
            DeliveryAckResult::Unknown
        }
    }

    pub fn nack_key(&mut self, key: DeliveryKey, now_tick: Tick) -> Option<PendingDelivery> {
        let delivery = self.pending.get_mut(&key)?;
        delivery.next_retry_tick = now_tick;
        Some(delivery.clone())
    }

    pub fn due_for_retransmit(
        &mut self,
        now_tick: Tick,
        resend_after_ticks: Tick,
    ) -> Vec<PendingDelivery> {
        let previous = self.config.resend_after_ticks;
        self.config.resend_after_ticks = resend_after_ticks;
        let due = self.due_for_retransmit_with_failures(now_tick).0;
        self.config.resend_after_ticks = previous;
        due
    }

    pub fn due_for_retransmit_with_failures(
        &mut self,
        now_tick: Tick,
    ) -> (Vec<PendingDelivery>, Vec<DeliveryFailure>) {
        let mut due = Vec::new();
        let mut failures = Vec::new();
        let mut remove_keys = Vec::new();

        for (key, delivery) in self.pending.iter_mut() {
            if delivery.age_ticks(now_tick) > self.config.expire_after_ticks {
                failures.push(DeliveryFailure {
                    delivery: delivery.clone(),
                    reason: DeliveryFailureReason::Expired,
                });
                remove_keys.push(*key);
                continue;
            }

            if now_tick < delivery.next_retry_tick {
                continue;
            }

            if delivery.attempts >= self.config.max_attempts {
                failures.push(DeliveryFailure {
                    delivery: delivery.clone(),
                    reason: DeliveryFailureReason::MaxAttemptsExceeded,
                });
                remove_keys.push(*key);
                continue;
            }

            delivery.attempts += 1;
            delivery.last_sent_tick = now_tick;
            delivery.next_retry_tick = now_tick.saturating_add(backoff_ticks(
                self.config.resend_after_ticks,
                delivery.attempts,
            ));
            due.push(delivery.clone());
            self.retransmitted_total += 1;
        }

        for key in remove_keys {
            self.pending.remove(&key);
            self.failed_total += 1;
        }

        due.sort_by_key(|delivery| {
            (
                delivery.key.to_peer,
                delivery.key.input_tick,
                delivery.key.from_peer,
                delivery.key.sequence_id,
            )
        });
        failures.sort_by_key(|failure| {
            (
                failure.delivery.key.to_peer,
                failure.delivery.key.input_tick,
                failure.delivery.key.from_peer,
                failure.delivery.key.sequence_id,
            )
        });
        (due, failures)
    }

    pub fn pending_for_peer(&self, peer_id: PeerId) -> Vec<&PendingDelivery> {
        self.pending
            .values()
            .filter(|delivery| delivery.key.to_peer == peer_id)
            .collect()
    }

    pub fn pending_count(&self) -> usize {
        self.pending.len()
    }

    pub fn stats(&self) -> InputBroadcasterStats {
        InputBroadcasterStats {
            pending_count: self.pending.len(),
            queued_total: self.queued_total,
            acked_total: self.acked_total,
            retransmitted_total: self.retransmitted_total,
            failed_total: self.failed_total,
        }
    }
}

fn backoff_ticks(base: Tick, attempts: u32) -> Tick {
    let multiplier = 1_u64 << attempts.saturating_sub(1).min(4);
    base.saturating_mul(multiplier)
}
