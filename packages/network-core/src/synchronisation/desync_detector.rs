use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};

use crate::{NetworkError, PeerId, Tick};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DesyncDetectorConfig {
    pub interval_ticks: Tick,
    pub require_authoritative_hash: bool,
    pub max_reports: usize,
    pub consecutive_divergence_threshold: u16,
}

impl Default for DesyncDetectorConfig {
    fn default() -> Self {
        Self {
            interval_ticks: 30,
            require_authoritative_hash: true,
            max_reports: 128,
            consecutive_divergence_threshold: 1,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PeerHashObservation {
    pub peer_id: PeerId,
    pub hash: String,
    pub received_tick: Tick,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DesyncReport {
    pub tick: Tick,
    pub expected_hash: String,
    pub divergent_peers: Vec<(PeerId, String)>,
    pub matching_peers: Vec<PeerId>,
    pub missing_peers: Vec<PeerId>,
    pub majority_hash: Option<String>,
    pub consecutive_counts: BTreeMap<PeerId, u16>,
}

impl DesyncReport {
    pub fn divergent_peer_ids(&self) -> BTreeSet<PeerId> {
        self.divergent_peers
            .iter()
            .map(|(peer_id, _)| *peer_id)
            .collect()
    }

    pub fn is_confirmed(&self, threshold: u16) -> bool {
        self.divergent_peers.iter().any(|(peer_id, _)| {
            self.consecutive_counts
                .get(peer_id)
                .copied()
                .unwrap_or_default()
                >= threshold.max(1)
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DesyncSummary {
    pub report_count: usize,
    pub latest_tick: Option<Tick>,
    pub peers_with_divergence: BTreeSet<PeerId>,
}

#[derive(Debug, Clone)]
pub struct DesyncDetector {
    config: DesyncDetectorConfig,
    reports: Vec<DesyncReport>,
    last_hash_by_peer: BTreeMap<PeerId, String>,
    consecutive_divergence: BTreeMap<PeerId, u16>,
}

impl DesyncDetector {
    pub fn new(interval_ticks: Tick) -> Self {
        Self::with_config(DesyncDetectorConfig {
            interval_ticks: interval_ticks.max(1),
            ..DesyncDetectorConfig::default()
        })
    }

    pub fn with_config(config: DesyncDetectorConfig) -> Self {
        Self {
            config: DesyncDetectorConfig {
                interval_ticks: config.interval_ticks.max(1),
                max_reports: config.max_reports.max(1),
                consecutive_divergence_threshold: config.consecutive_divergence_threshold.max(1),
                ..config
            },
            reports: Vec::new(),
            last_hash_by_peer: BTreeMap::new(),
            consecutive_divergence: BTreeMap::new(),
        }
    }

    pub fn should_compare(&self, tick: Tick) -> bool {
        tick > 0 && tick % self.config.interval_ticks == 0
    }

    pub fn compare(
        &mut self,
        tick: Tick,
        authoritative_hash: &str,
        peer_hashes: BTreeMap<PeerId, String>,
    ) -> Option<DesyncReport> {
        self.compare_result(tick, authoritative_hash, peer_hashes, BTreeSet::new())
            .ok()
            .flatten()
    }

    pub fn compare_result(
        &mut self,
        tick: Tick,
        authoritative_hash: &str,
        peer_hashes: BTreeMap<PeerId, String>,
        expected_peers: BTreeSet<PeerId>,
    ) -> Result<Option<DesyncReport>, NetworkError> {
        if !self.should_compare(tick) {
            return Ok(None);
        }
        if self.config.require_authoritative_hash && authoritative_hash.trim().is_empty() {
            return Err(NetworkError::InvalidOperation(
                "authoritative hash cannot be empty".to_string(),
            ));
        }

        let mut divergent_peers = Vec::new();
        let mut matching_peers = Vec::new();
        let mut observed_peers = BTreeSet::new();
        let mut hash_counts: BTreeMap<String, usize> = BTreeMap::new();

        for (peer_id, hash) in peer_hashes {
            validate_peer_id(peer_id)?;
            if hash.trim().is_empty() {
                return Err(NetworkError::InvalidOperation(format!(
                    "peer {} submitted an empty state hash",
                    peer_id
                )));
            }
            observed_peers.insert(peer_id);
            *hash_counts.entry(hash.clone()).or_default() += 1;
            self.last_hash_by_peer.insert(peer_id, hash.clone());
            if hash == authoritative_hash {
                matching_peers.push(peer_id);
                self.consecutive_divergence.remove(&peer_id);
            } else {
                let count = self
                    .consecutive_divergence
                    .entry(peer_id)
                    .and_modify(|count| *count = count.saturating_add(1))
                    .or_insert(1);
                divergent_peers.push((peer_id, hash));
                if *count == 0 {
                    *count = 1;
                }
            }
        }

        let missing_peers = expected_peers
            .difference(&observed_peers)
            .copied()
            .collect::<Vec<_>>();
        for peer_id in &missing_peers {
            self.consecutive_divergence
                .entry(*peer_id)
                .and_modify(|count| *count = count.saturating_add(1))
                .or_insert(1);
        }

        if divergent_peers.is_empty() && missing_peers.is_empty() {
            return Ok(None);
        }

        let majority_hash = hash_counts
            .into_iter()
            .max_by(|left, right| left.1.cmp(&right.1).then_with(|| right.0.cmp(&left.0)))
            .map(|(hash, _)| hash);
        let report = DesyncReport {
            tick,
            expected_hash: authoritative_hash.to_string(),
            divergent_peers,
            matching_peers,
            missing_peers,
            majority_hash,
            consecutive_counts: self.consecutive_divergence.clone(),
        };
        self.reports.push(report.clone());
        while self.reports.len() > self.config.max_reports {
            self.reports.remove(0);
        }
        Ok(Some(report))
    }

    pub fn observe_hash(&mut self, observation: PeerHashObservation) -> Result<(), NetworkError> {
        validate_peer_id(observation.peer_id)?;
        if observation.hash.trim().is_empty() {
            return Err(NetworkError::InvalidOperation(
                "peer hash observation cannot be empty".to_string(),
            ));
        }
        self.last_hash_by_peer
            .insert(observation.peer_id, observation.hash);
        Ok(())
    }

    pub fn last_hash_for_peer(&self, peer_id: PeerId) -> Option<&str> {
        self.last_hash_by_peer.get(&peer_id).map(String::as_str)
    }

    pub fn consecutive_divergence_for(&self, peer_id: PeerId) -> u16 {
        self.consecutive_divergence
            .get(&peer_id)
            .copied()
            .unwrap_or_default()
    }

    pub fn reports(&self) -> &[DesyncReport] {
        &self.reports
    }

    pub fn latest_report(&self) -> Option<&DesyncReport> {
        self.reports.last()
    }

    pub fn summary(&self) -> DesyncSummary {
        let peers_with_divergence = self
            .reports
            .iter()
            .flat_map(DesyncReport::divergent_peer_ids)
            .collect();
        DesyncSummary {
            report_count: self.reports.len(),
            latest_tick: self.reports.last().map(|report| report.tick),
            peers_with_divergence,
        }
    }

    pub fn config(&self) -> &DesyncDetectorConfig {
        &self.config
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
