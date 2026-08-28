use std::collections::{BTreeMap, VecDeque};

use serde::{Deserialize, Serialize};

use crate::authority::{AuthorityResolver, CheatGuard, CheatGuardConfig, CheatViolationKind};
use crate::{NetworkError, PeerId, Tick};

use super::{InputInsertOutcome, InputPacket, InputSynchroniser};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MaliciousInputGateConfig {
    pub cheat_guard: CheatGuardConfig,
    pub max_packets_per_peer_per_window: usize,
    pub rate_window_ticks: Tick,
    pub max_rejection_log_entries: usize,
}

impl Default for MaliciousInputGateConfig {
    fn default() -> Self {
        Self {
            cheat_guard: CheatGuardConfig::default(),
            max_packets_per_peer_per_window: 32,
            rate_window_ticks: 4,
            max_rejection_log_entries: 256,
        }
    }
}

impl MaliciousInputGateConfig {
    pub fn validate(&self) -> Result<(), NetworkError> {
        self.cheat_guard.validate()?;
        if self.max_packets_per_peer_per_window == 0 {
            return Err(NetworkError::InvalidOperation(
                "malicious input gate max_packets_per_peer_per_window must be greater than zero"
                    .to_string(),
            ));
        }
        if self.rate_window_ticks == 0 {
            return Err(NetworkError::InvalidOperation(
                "malicious input gate rate_window_ticks must be greater than zero".to_string(),
            ));
        }
        if self.max_rejection_log_entries == 0 {
            return Err(NetworkError::InvalidOperation(
                "malicious input gate max_rejection_log_entries must be greater than zero"
                    .to_string(),
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub enum MaliciousInputRejectionKind {
    RateLimitExceeded,
    UnknownPeer,
    InvalidPacket,
    SignatureMissingOrInvalid,
    SequenceReplay,
    SequenceGap,
    TickRegression,
    FutureTick,
    ActionDenied,
    ActionLimitExceeded,
    DeviceDenied,
    PlayerRequired,
    AuthorityDenied,
    DuplicateTick,
    InputBufferOverflow,
    BufferRejected,
}

impl MaliciousInputRejectionKind {
    pub fn stable_id(self) -> &'static str {
        match self {
            Self::RateLimitExceeded => "rate_limit",
            Self::UnknownPeer => "unknown_peer",
            Self::InvalidPacket => "invalid_packet",
            Self::SignatureMissingOrInvalid => "signature",
            Self::SequenceReplay => "sequence_replay",
            Self::SequenceGap => "sequence_gap",
            Self::TickRegression => "tick_regression",
            Self::FutureTick => "future_tick",
            Self::ActionDenied => "action_denied",
            Self::ActionLimitExceeded => "action_limit",
            Self::DeviceDenied => "device_denied",
            Self::PlayerRequired => "player_required",
            Self::AuthorityDenied => "authority",
            Self::DuplicateTick => "duplicate_tick",
            Self::InputBufferOverflow => "input_buffer_overflow",
            Self::BufferRejected => "buffer_rejected",
        }
    }
}

impl From<CheatViolationKind> for MaliciousInputRejectionKind {
    fn from(kind: CheatViolationKind) -> Self {
        match kind {
            CheatViolationKind::InvalidPacket => Self::InvalidPacket,
            CheatViolationKind::SignatureMissingOrInvalid => Self::SignatureMissingOrInvalid,
            CheatViolationKind::SequenceReplay => Self::SequenceReplay,
            CheatViolationKind::SequenceGap => Self::SequenceGap,
            CheatViolationKind::TickRegression => Self::TickRegression,
            CheatViolationKind::FutureTick => Self::FutureTick,
            CheatViolationKind::ActionDenied => Self::ActionDenied,
            CheatViolationKind::ActionLimitExceeded => Self::ActionLimitExceeded,
            CheatViolationKind::DeviceDenied => Self::DeviceDenied,
            CheatViolationKind::PlayerRequired => Self::PlayerRequired,
            CheatViolationKind::AuthorityDenied => Self::AuthorityDenied,
            CheatViolationKind::TransformInvalid | CheatViolationKind::TransformTooFast => {
                Self::BufferRejected
            }
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MaliciousInputRejection {
    pub kind: MaliciousInputRejectionKind,
    pub peer_id: Option<PeerId>,
    pub tick: Option<Tick>,
    pub sequence_id: Option<u64>,
    pub message: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MaliciousInputGateStats {
    pub accepted_count: u64,
    pub rejected_count: u64,
    pub rate_limited_count: u64,
    pub rejection_log_entries: usize,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct PeerRateWindow {
    start_tick: Tick,
    count: usize,
}

#[derive(Debug, Clone)]
pub struct MaliciousInputGate {
    config: MaliciousInputGateConfig,
    cheat_guard: CheatGuard,
    rate_windows: BTreeMap<PeerId, PeerRateWindow>,
    rejections: VecDeque<MaliciousInputRejection>,
    accepted_count: u64,
    rejected_count: u64,
    rate_limited_count: u64,
}

impl Default for MaliciousInputGate {
    fn default() -> Self {
        Self::new(MaliciousInputGateConfig::default())
    }
}

impl MaliciousInputGate {
    pub fn new(config: MaliciousInputGateConfig) -> Self {
        Self::with_config(config).expect("malicious input gate configuration must be valid")
    }

    pub fn with_config(config: MaliciousInputGateConfig) -> Result<Self, NetworkError> {
        config.validate()?;
        Ok(Self {
            cheat_guard: CheatGuard::new(config.cheat_guard.clone()),
            config,
            rate_windows: BTreeMap::new(),
            rejections: VecDeque::new(),
            accepted_count: 0,
            rejected_count: 0,
            rate_limited_count: 0,
        })
    }

    pub fn submit_authorized(
        &mut self,
        packet: InputPacket,
        authority: &AuthorityResolver,
        synchroniser: &mut InputSynchroniser,
        server_tick: Tick,
        ingress_tick: Tick,
    ) -> Result<InputInsertOutcome, NetworkError> {
        self.check_rate_limit(&packet, ingress_tick)?;

        if !synchroniser.required_peers().contains(&packet.peer_id) {
            let error = NetworkError::UnknownPeer(packet.peer_id);
            self.record_rejection(
                MaliciousInputRejectionKind::UnknownPeer,
                Some(packet.peer_id),
                Some(packet.tick),
                Some(packet.sequence_id),
                error.to_string(),
            );
            return Err(error);
        }

        if let Err(error) = self.cheat_guard.validate_authorized_input_preview(
            &packet,
            authority,
            Some(server_tick),
        ) {
            let kind = self
                .cheat_guard
                .violation_log()
                .last()
                .map(|violation| MaliciousInputRejectionKind::from(violation.kind.clone()))
                .unwrap_or_else(|| classify_network_error(&error));
            self.record_rejection(
                kind,
                Some(packet.peer_id),
                Some(packet.tick),
                Some(packet.sequence_id),
                error.to_string(),
            );
            return Err(error);
        }

        let accepted_packet = packet.clone();
        match synchroniser.submit_with_outcome(packet) {
            Ok(outcome) => {
                self.cheat_guard.record_validated_input(&accepted_packet);
                self.accepted_count += 1;
                Ok(outcome)
            }
            Err(error) => {
                self.record_rejection(
                    classify_network_error(&error),
                    Some(accepted_packet.peer_id),
                    Some(accepted_packet.tick),
                    Some(accepted_packet.sequence_id),
                    error.to_string(),
                );
                Err(error)
            }
        }
    }

    pub fn stats(&self) -> MaliciousInputGateStats {
        MaliciousInputGateStats {
            accepted_count: self.accepted_count,
            rejected_count: self.rejected_count,
            rate_limited_count: self.rate_limited_count,
            rejection_log_entries: self.rejections.len(),
        }
    }

    pub fn rejection_log(&self) -> impl Iterator<Item = &MaliciousInputRejection> {
        self.rejections.iter()
    }

    pub fn cheat_guard(&self) -> &CheatGuard {
        &self.cheat_guard
    }

    pub fn config(&self) -> &MaliciousInputGateConfig {
        &self.config
    }

    fn check_rate_limit(
        &mut self,
        packet: &InputPacket,
        ingress_tick: Tick,
    ) -> Result<(), NetworkError> {
        let window = self
            .rate_windows
            .entry(packet.peer_id)
            .or_insert(PeerRateWindow {
                start_tick: ingress_tick,
                count: 0,
            });
        if ingress_tick < window.start_tick
            || ingress_tick.saturating_sub(window.start_tick) >= self.config.rate_window_ticks
        {
            window.start_tick = ingress_tick;
            window.count = 0;
        }
        if window.count >= self.config.max_packets_per_peer_per_window {
            let message = format!(
                "peer {} exceeded malicious input rate limit: {} packets in {} ticks",
                packet.peer_id,
                self.config.max_packets_per_peer_per_window,
                self.config.rate_window_ticks
            );
            self.rate_limited_count += 1;
            self.record_rejection(
                MaliciousInputRejectionKind::RateLimitExceeded,
                Some(packet.peer_id),
                Some(packet.tick),
                Some(packet.sequence_id),
                message.clone(),
            );
            return Err(NetworkError::CheatRejected(message));
        }
        window.count += 1;
        Ok(())
    }

    fn record_rejection(
        &mut self,
        kind: MaliciousInputRejectionKind,
        peer_id: Option<PeerId>,
        tick: Option<Tick>,
        sequence_id: Option<u64>,
        message: String,
    ) {
        self.rejected_count += 1;
        self.rejections.push_back(MaliciousInputRejection {
            kind,
            peer_id,
            tick,
            sequence_id,
            message,
        });
        while self.rejections.len() > self.config.max_rejection_log_entries {
            self.rejections.pop_front();
        }
    }
}

fn classify_network_error(error: &NetworkError) -> MaliciousInputRejectionKind {
    match error {
        NetworkError::UnknownPeer(_) => MaliciousInputRejectionKind::UnknownPeer,
        NetworkError::DuplicateInput { .. } => MaliciousInputRejectionKind::DuplicateTick,
        NetworkError::StaleInput { .. } => MaliciousInputRejectionKind::SequenceReplay,
        NetworkError::InvalidInput(_) => MaliciousInputRejectionKind::InvalidPacket,
        NetworkError::InputBufferOverflow { .. } => {
            MaliciousInputRejectionKind::InputBufferOverflow
        }
        NetworkError::AuthorityDenied { .. } => MaliciousInputRejectionKind::AuthorityDenied,
        NetworkError::CheatRejected(_) => MaliciousInputRejectionKind::BufferRejected,
        _ => MaliciousInputRejectionKind::BufferRejected,
    }
}
