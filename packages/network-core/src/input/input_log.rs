use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use super::InputPacket;
use crate::{NetworkError, PeerId, Tick};

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub struct InputLogKey {
    pub tick: Tick,
    pub peer_id: PeerId,
    pub sequence_id: u64,
}

impl From<&InputPacket> for InputLogKey {
    fn from(packet: &InputPacket) -> Self {
        Self {
            tick: packet.tick,
            peer_id: packet.peer_id,
            sequence_id: packet.sequence_id,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct InputLogRecord {
    pub key: InputLogKey,
    pub packet: InputPacket,
    pub packet_digest: String,
    pub previous_chain_hash: String,
    pub chain_hash: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InputLogSummary {
    pub record_count: usize,
    pub first_tick: Option<Tick>,
    pub last_tick: Option<Tick>,
    pub chain_head: String,
}

#[derive(Debug, Clone, Default)]
pub struct InputLog {
    entries: BTreeMap<InputLogKey, InputLogRecord>,
    chain_head: String,
}

impl InputLog {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn append(&mut self, packet: InputPacket) {
        self.append_result(packet)
            .expect("InputLog::append received invalid or duplicate packet");
    }

    pub fn append_result(&mut self, packet: InputPacket) -> Result<&InputLogRecord, NetworkError> {
        packet.validate()?;
        let key = InputLogKey::from(&packet);
        let packet_digest = packet.deterministic_digest();

        if let Some(existing_digest) = self
            .entries
            .get(&key)
            .map(|record| record.packet_digest.clone())
        {
            if existing_digest == packet_digest {
                return Ok(self.entries.get(&key).expect("existing record present"));
            }
            return Err(NetworkError::DuplicateInput {
                peer_id: key.peer_id,
                tick: key.tick,
                sequence_id: key.sequence_id,
            });
        }

        let previous_chain_hash = self.chain_head.clone();
        let chain_hash = compute_chain_hash(&previous_chain_hash, &packet_digest);
        let record = InputLogRecord {
            key: key.clone(),
            packet,
            packet_digest,
            previous_chain_hash,
            chain_hash: chain_hash.clone(),
        };
        self.entries.insert(key.clone(), record);
        self.chain_head = self.recompute_chain();
        Ok(self.entries.get(&key).expect("record inserted"))
    }

    pub fn entries(&self) -> Vec<&InputPacket> {
        self.entries.values().map(|record| &record.packet).collect()
    }

    pub fn records(&self) -> Vec<&InputLogRecord> {
        self.entries.values().collect()
    }

    pub fn packets_for_tick(&self, tick: Tick) -> Vec<&InputPacket> {
        self.entries
            .range(
                InputLogKey {
                    tick,
                    peer_id: 0,
                    sequence_id: 0,
                }..=InputLogKey {
                    tick,
                    peer_id: u64::MAX,
                    sequence_id: u64::MAX,
                },
            )
            .map(|(_, record)| &record.packet)
            .collect()
    }

    pub fn packets_for_peer(&self, peer_id: PeerId) -> Vec<&InputPacket> {
        self.entries
            .values()
            .filter(|record| record.key.peer_id == peer_id)
            .map(|record| &record.packet)
            .collect()
    }

    pub fn deterministic_hash(&self) -> String {
        self.chain_head.clone()
    }

    pub fn verify_chain(&self) -> bool {
        let mut previous = String::new();
        for record in self.entries.values() {
            if record.previous_chain_hash != previous {
                return false;
            }
            let expected = compute_chain_hash(&previous, &record.packet_digest);
            if record.chain_hash != expected {
                return false;
            }
            previous = record.chain_hash.clone();
        }
        previous == self.chain_head
    }

    pub fn summary(&self) -> InputLogSummary {
        InputLogSummary {
            record_count: self.entries.len(),
            first_tick: self.entries.keys().next().map(|key| key.tick),
            last_tick: self.entries.keys().next_back().map(|key| key.tick),
            chain_head: self.chain_head.clone(),
        }
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    fn recompute_chain(&mut self) -> String {
        let mut previous = String::new();
        for record in self.entries.values_mut() {
            record.previous_chain_hash = previous.clone();
            record.chain_hash = compute_chain_hash(&previous, &record.packet_digest);
            previous = record.chain_hash.clone();
        }
        previous
    }
}

fn compute_chain_hash(previous: &str, packet_digest: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(previous.as_bytes());
    hasher.update([0]);
    hasher.update(packet_digest.as_bytes());
    format!("{:x}", hasher.finalize())
}
