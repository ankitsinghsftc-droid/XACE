use std::collections::{BTreeMap, BTreeSet, VecDeque};

use serde::{Deserialize, Serialize};

use super::AuthorityResolver;
use crate::input::{InputActionKind, InputPacket};
use crate::{EntityId, NetworkError, PeerId, Tick};

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct ActionLimit {
    pub max_abs_value: f32,
    pub max_abs_secondary_value: f32,
    pub max_per_tick: usize,
}

impl Default for ActionLimit {
    fn default() -> Self {
        Self {
            max_abs_value: 1.0,
            max_abs_secondary_value: 1.0,
            max_per_tick: 8,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CheatGuardConfig {
    pub max_actions_per_packet: usize,
    pub max_abs_action_value: f32,
    pub max_transform_units_per_tick: f32,
    pub allowed_actions: BTreeSet<String>,
    pub per_action_limits: BTreeMap<String, ActionLimit>,
    pub allowed_devices: BTreeSet<String>,
    pub require_player_id: bool,
    pub allow_predicted_input: bool,
    pub require_signature: bool,
    pub signature_secret: Option<Vec<u8>>,
    pub max_sequence_gap: u64,
    pub max_tick_regression: Tick,
    pub max_future_ticks: Tick,
    pub max_repeated_action_per_tick: usize,
    pub max_abs_position: f32,
    pub max_violation_log_entries: usize,
}

impl Default for CheatGuardConfig {
    fn default() -> Self {
        Self {
            max_actions_per_packet: 16,
            max_abs_action_value: 1.0,
            max_transform_units_per_tick: 0.5,
            allowed_actions: BTreeSet::new(),
            per_action_limits: BTreeMap::new(),
            allowed_devices: BTreeSet::new(),
            require_player_id: false,
            allow_predicted_input: true,
            require_signature: false,
            signature_secret: None,
            max_sequence_gap: 4096,
            max_tick_regression: 2,
            max_future_ticks: 12,
            max_repeated_action_per_tick: 8,
            max_abs_position: 1_000_000.0,
            max_violation_log_entries: 256,
        }
    }
}

impl CheatGuardConfig {
    pub fn validate(&self) -> Result<(), NetworkError> {
        if self.max_actions_per_packet == 0 {
            return Err(NetworkError::InvalidOperation(
                "cheat guard max_actions_per_packet must be greater than zero".to_string(),
            ));
        }
        if !self.max_abs_action_value.is_finite() || self.max_abs_action_value < 0.0 {
            return Err(NetworkError::InvalidOperation(
                "cheat guard max_abs_action_value must be finite and non-negative".to_string(),
            ));
        }
        if !self.max_transform_units_per_tick.is_finite() || self.max_transform_units_per_tick < 0.0
        {
            return Err(NetworkError::InvalidOperation(
                "cheat guard max_transform_units_per_tick must be finite and non-negative"
                    .to_string(),
            ));
        }
        if !self.max_abs_position.is_finite() || self.max_abs_position < 0.0 {
            return Err(NetworkError::InvalidOperation(
                "cheat guard max_abs_position must be finite and non-negative".to_string(),
            ));
        }
        if self.require_signature
            && self
                .signature_secret
                .as_deref()
                .unwrap_or_default()
                .is_empty()
        {
            return Err(NetworkError::InvalidOperation(
                "cheat guard signature enforcement requires a non-empty secret".to_string(),
            ));
        }
        for action in &self.allowed_actions {
            validate_policy_token(action, "allowed action")?;
        }
        for device in &self.allowed_devices {
            validate_policy_token(device, "allowed device")?;
        }
        for (action, limit) in &self.per_action_limits {
            validate_policy_token(action, "per-action limit")?;
            if !limit.max_abs_value.is_finite()
                || limit.max_abs_value < 0.0
                || !limit.max_abs_secondary_value.is_finite()
                || limit.max_abs_secondary_value < 0.0
                || limit.max_per_tick == 0
            {
                return Err(NetworkError::InvalidOperation(format!(
                    "invalid cheat guard limit for action {}",
                    action
                )));
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct TransformSample {
    pub tick: Tick,
    pub x: f32,
    pub y: f32,
    pub z: f32,
}

impl TransformSample {
    pub fn position_tuple(self) -> (f32, f32, f32) {
        (self.x, self.y, self.z)
    }

    pub fn is_finite(self) -> bool {
        self.x.is_finite() && self.y.is_finite() && self.z.is_finite()
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TransformDeltaReport {
    pub entity_id: EntityId,
    pub from_tick: Tick,
    pub to_tick: Tick,
    pub distance: f32,
    pub max_distance: f32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum CheatViolationKind {
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
    TransformInvalid,
    TransformTooFast,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CheatViolation {
    pub kind: CheatViolationKind,
    pub peer_id: Option<PeerId>,
    pub entity_id: Option<EntityId>,
    pub tick: Option<Tick>,
    pub message: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CheatGuardStats {
    pub tracked_peers: usize,
    pub tracked_entities: usize,
    pub violation_count: usize,
}

#[derive(Debug, Clone)]
pub struct CheatGuard {
    config: CheatGuardConfig,
    last_sequence: BTreeMap<PeerId, u64>,
    last_tick_by_peer: BTreeMap<PeerId, Tick>,
    last_transform: BTreeMap<EntityId, TransformSample>,
    action_counts: BTreeMap<(PeerId, Tick, String), usize>,
    violations: VecDeque<CheatViolation>,
}

impl CheatGuard {
    pub fn new(config: CheatGuardConfig) -> Self {
        config
            .validate()
            .expect("cheat guard configuration must be valid");
        Self {
            config,
            last_sequence: BTreeMap::new(),
            last_tick_by_peer: BTreeMap::new(),
            last_transform: BTreeMap::new(),
            action_counts: BTreeMap::new(),
            violations: VecDeque::new(),
        }
    }

    pub fn validate_input(&mut self, packet: &InputPacket) -> Result<(), NetworkError> {
        self.validate_input_at(packet, None)
    }

    pub fn validate_input_at(
        &mut self,
        packet: &InputPacket,
        server_tick: Option<Tick>,
    ) -> Result<(), NetworkError> {
        self.validate_packet_structure(packet)?;
        self.validate_packet_signature(packet)?;
        self.validate_packet_policy(packet, server_tick)?;
        self.record_packet(packet);
        Ok(())
    }

    pub fn validate_authorized_input(
        &mut self,
        packet: &InputPacket,
        authority: &AuthorityResolver,
        server_tick: Option<Tick>,
    ) -> Result<(), NetworkError> {
        self.validate_packet_structure(packet)?;
        self.validate_packet_signature(packet)?;
        self.validate_packet_policy(packet, server_tick)?;
        for action in &packet.actions {
            if let Some(entity_id) = action.target_entity {
                if let Err(error) = authority.require_authority(entity_id, packet.peer_id) {
                    return self.reject(CheatViolation {
                        kind: CheatViolationKind::AuthorityDenied,
                        peer_id: Some(packet.peer_id),
                        entity_id: Some(entity_id),
                        tick: Some(packet.tick),
                        message: error.to_string(),
                    });
                }
            }
        }
        self.record_packet(packet);
        Ok(())
    }

    pub fn validate_transform_delta(
        &mut self,
        entity_id: EntityId,
        sample: TransformSample,
    ) -> Result<(), NetworkError> {
        self.validate_transform_delta_result(entity_id, sample)
            .map(|_| ())
    }

    pub fn validate_transform_delta_result(
        &mut self,
        entity_id: EntityId,
        sample: TransformSample,
    ) -> Result<Option<TransformDeltaReport>, NetworkError> {
        if entity_id == 0 {
            return self.reject(CheatViolation {
                kind: CheatViolationKind::TransformInvalid,
                peer_id: None,
                entity_id: Some(entity_id),
                tick: Some(sample.tick),
                message: "entity_id 0 is reserved".to_string(),
            });
        }
        if !sample.is_finite()
            || sample.x.abs() > self.config.max_abs_position
            || sample.y.abs() > self.config.max_abs_position
            || sample.z.abs() > self.config.max_abs_position
        {
            return self.reject(CheatViolation {
                kind: CheatViolationKind::TransformInvalid,
                peer_id: None,
                entity_id: Some(entity_id),
                tick: Some(sample.tick),
                message: format!("entity {} submitted invalid transform", entity_id),
            });
        }

        let report = if let Some(prev) = self.last_transform.get(&entity_id).copied() {
            let elapsed_ticks = sample.tick.saturating_sub(prev.tick).max(1);
            let dx = sample.x - prev.x;
            let dy = sample.y - prev.y;
            let dz = sample.z - prev.z;
            let distance = dx.mul_add(dx, dy.mul_add(dy, dz * dz)).sqrt();
            let max_distance = self.config.max_transform_units_per_tick * elapsed_ticks as f32;
            let report = TransformDeltaReport {
                entity_id,
                from_tick: prev.tick,
                to_tick: sample.tick,
                distance,
                max_distance,
            };
            if distance > max_distance {
                return self.reject(CheatViolation {
                    kind: CheatViolationKind::TransformTooFast,
                    peer_id: None,
                    entity_id: Some(entity_id),
                    tick: Some(sample.tick),
                    message: format!(
                        "entity {} moved {} in {} ticks, max {}",
                        entity_id, distance, elapsed_ticks, max_distance
                    ),
                });
            }
            Some(report)
        } else {
            None
        };

        self.last_transform.insert(entity_id, sample);
        Ok(report)
    }

    pub fn reset_peer(&mut self, peer_id: PeerId) {
        self.last_sequence.remove(&peer_id);
        self.last_tick_by_peer.remove(&peer_id);
        self.action_counts
            .retain(|(count_peer_id, _, _), _| *count_peer_id != peer_id);
    }

    pub fn reset_entity(&mut self, entity_id: EntityId) {
        self.last_transform.remove(&entity_id);
    }

    pub fn prune_before_tick(&mut self, tick: Tick) -> usize {
        let before = self.action_counts.len();
        self.action_counts
            .retain(|(_, action_tick, _), _| *action_tick >= tick);
        before.saturating_sub(self.action_counts.len())
    }

    pub fn violation_log(&self) -> impl Iterator<Item = &CheatViolation> {
        self.violations.iter()
    }

    pub fn clear_violations(&mut self) {
        self.violations.clear();
    }

    pub fn last_sequence_for_peer(&self, peer_id: PeerId) -> Option<u64> {
        self.last_sequence.get(&peer_id).copied()
    }

    pub fn last_transform_for_entity(&self, entity_id: EntityId) -> Option<TransformSample> {
        self.last_transform.get(&entity_id).copied()
    }

    pub fn stats(&self) -> CheatGuardStats {
        CheatGuardStats {
            tracked_peers: self.last_sequence.len(),
            tracked_entities: self.last_transform.len(),
            violation_count: self.violations.len(),
        }
    }

    pub fn config(&self) -> &CheatGuardConfig {
        &self.config
    }

    pub fn config_mut(&mut self) -> &mut CheatGuardConfig {
        &mut self.config
    }

    fn validate_packet_structure(&mut self, packet: &InputPacket) -> Result<(), NetworkError> {
        if let Err(error) = packet.validate() {
            return self.reject(CheatViolation {
                kind: CheatViolationKind::InvalidPacket,
                peer_id: Some(packet.peer_id),
                entity_id: packet.player_id,
                tick: Some(packet.tick),
                message: error.to_string(),
            });
        }
        Ok(())
    }

    fn validate_packet_signature(&mut self, packet: &InputPacket) -> Result<(), NetworkError> {
        if !self.config.require_signature {
            return Ok(());
        }
        let Some(secret) = self.config.signature_secret.clone() else {
            return self.reject(CheatViolation {
                kind: CheatViolationKind::SignatureMissingOrInvalid,
                peer_id: Some(packet.peer_id),
                entity_id: packet.player_id,
                tick: Some(packet.tick),
                message: "signature required but no secret configured".to_string(),
            });
        };
        if let Err(error) = packet.verify_signature(&secret) {
            return self.reject(CheatViolation {
                kind: CheatViolationKind::SignatureMissingOrInvalid,
                peer_id: Some(packet.peer_id),
                entity_id: packet.player_id,
                tick: Some(packet.tick),
                message: error.to_string(),
            });
        }
        Ok(())
    }

    fn validate_packet_policy(
        &mut self,
        packet: &InputPacket,
        server_tick: Option<Tick>,
    ) -> Result<(), NetworkError> {
        if self.config.require_player_id && packet.player_id.is_none() {
            return self.reject(CheatViolation {
                kind: CheatViolationKind::PlayerRequired,
                peer_id: Some(packet.peer_id),
                entity_id: None,
                tick: Some(packet.tick),
                message: "player_id is required".to_string(),
            });
        }
        if !self.config.allow_predicted_input && packet.predicted {
            return self.reject(CheatViolation {
                kind: CheatViolationKind::InvalidPacket,
                peer_id: Some(packet.peer_id),
                entity_id: packet.player_id,
                tick: Some(packet.tick),
                message: "predicted input is not accepted by this authority".to_string(),
            });
        }
        if !self.config.allowed_devices.is_empty()
            && !self.config.allowed_devices.contains(&packet.device_id)
        {
            return self.reject(CheatViolation {
                kind: CheatViolationKind::DeviceDenied,
                peer_id: Some(packet.peer_id),
                entity_id: packet.player_id,
                tick: Some(packet.tick),
                message: format!("device '{}' is not allowed", packet.device_id),
            });
        }
        if packet.actions.len() > self.config.max_actions_per_packet {
            return self.reject(CheatViolation {
                kind: CheatViolationKind::ActionLimitExceeded,
                peer_id: Some(packet.peer_id),
                entity_id: packet.player_id,
                tick: Some(packet.tick),
                message: format!(
                    "too many actions: {} > {}",
                    packet.actions.len(),
                    self.config.max_actions_per_packet
                ),
            });
        }
        self.validate_sequence(packet)?;
        self.validate_tick_window(packet, server_tick)?;
        self.validate_actions(packet)?;
        Ok(())
    }

    fn validate_sequence(&mut self, packet: &InputPacket) -> Result<(), NetworkError> {
        if let Some(last) = self.last_sequence.get(&packet.peer_id).copied() {
            if packet.sequence_id <= last {
                return self.reject(CheatViolation {
                    kind: CheatViolationKind::SequenceReplay,
                    peer_id: Some(packet.peer_id),
                    entity_id: packet.player_id,
                    tick: Some(packet.tick),
                    message: format!("non-monotonic sequence {} <= {}", packet.sequence_id, last),
                });
            }
            let gap = packet.sequence_id.saturating_sub(last);
            if self.config.max_sequence_gap > 0 && gap > self.config.max_sequence_gap {
                return self.reject(CheatViolation {
                    kind: CheatViolationKind::SequenceGap,
                    peer_id: Some(packet.peer_id),
                    entity_id: packet.player_id,
                    tick: Some(packet.tick),
                    message: format!(
                        "sequence gap {} exceeds limit {}",
                        gap, self.config.max_sequence_gap
                    ),
                });
            }
        }
        Ok(())
    }

    fn validate_tick_window(
        &mut self,
        packet: &InputPacket,
        server_tick: Option<Tick>,
    ) -> Result<(), NetworkError> {
        if let Some(last_tick) = self.last_tick_by_peer.get(&packet.peer_id).copied() {
            if packet.tick.saturating_add(self.config.max_tick_regression) < last_tick {
                return self.reject(CheatViolation {
                    kind: CheatViolationKind::TickRegression,
                    peer_id: Some(packet.peer_id),
                    entity_id: packet.player_id,
                    tick: Some(packet.tick),
                    message: format!(
                        "input tick {} regressed behind last tick {}",
                        packet.tick, last_tick
                    ),
                });
            }
        }
        if let Some(server_tick) = server_tick {
            if packet.tick > server_tick.saturating_add(self.config.max_future_ticks) {
                return self.reject(CheatViolation {
                    kind: CheatViolationKind::FutureTick,
                    peer_id: Some(packet.peer_id),
                    entity_id: packet.player_id,
                    tick: Some(packet.tick),
                    message: format!(
                        "input tick {} is too far ahead of server tick {}",
                        packet.tick, server_tick
                    ),
                });
            }
        }
        Ok(())
    }

    fn validate_actions(&mut self, packet: &InputPacket) -> Result<(), NetworkError> {
        let mut packet_action_counts: BTreeMap<&str, usize> = BTreeMap::new();
        for action in &packet.actions {
            *packet_action_counts.entry(&action.action).or_default() += 1;
            if !self.config.allowed_actions.is_empty()
                && !self.config.allowed_actions.contains(&action.action)
            {
                return self.reject(CheatViolation {
                    kind: CheatViolationKind::ActionDenied,
                    peer_id: Some(packet.peer_id),
                    entity_id: action.target_entity.or(packet.player_id),
                    tick: Some(packet.tick),
                    message: format!("action {} is not allowed", action.action),
                });
            }
            let limit = self
                .config
                .per_action_limits
                .get(&action.action)
                .copied()
                .unwrap_or(ActionLimit {
                    max_abs_value: self.config.max_abs_action_value,
                    max_abs_secondary_value: self.config.max_abs_action_value,
                    max_per_tick: self.config.max_repeated_action_per_tick,
                });
            if !action.value.is_finite()
                || !action.secondary_value.is_finite()
                || action.value.abs() > limit.max_abs_value
                || action.secondary_value.abs() > limit.max_abs_secondary_value
            {
                return self.reject(CheatViolation {
                    kind: CheatViolationKind::ActionLimitExceeded,
                    peer_id: Some(packet.peer_id),
                    entity_id: action.target_entity.or(packet.player_id),
                    tick: Some(packet.tick),
                    message: format!(
                        "action {} value outside +/-{}",
                        action.action, limit.max_abs_value
                    ),
                });
            }
            if matches!(action.kind, InputActionKind::Button)
                && action.value != 0.0
                && action.value != 1.0
            {
                return self.reject(CheatViolation {
                    kind: CheatViolationKind::ActionLimitExceeded,
                    peer_id: Some(packet.peer_id),
                    entity_id: action.target_entity.or(packet.player_id),
                    tick: Some(packet.tick),
                    message: format!("button action {} must be 0.0 or 1.0", action.action),
                });
            }
        }

        for (action_name, packet_count) in packet_action_counts {
            let limit = self
                .config
                .per_action_limits
                .get(action_name)
                .map(|limit| limit.max_per_tick)
                .unwrap_or(self.config.max_repeated_action_per_tick);
            let already_seen = self
                .action_counts
                .get(&(packet.peer_id, packet.tick, action_name.to_string()))
                .copied()
                .unwrap_or_default();
            if already_seen.saturating_add(packet_count) > limit {
                return self.reject(CheatViolation {
                    kind: CheatViolationKind::ActionLimitExceeded,
                    peer_id: Some(packet.peer_id),
                    entity_id: packet.player_id,
                    tick: Some(packet.tick),
                    message: format!(
                        "action {} repeated {} times at tick {}, limit {}",
                        action_name,
                        already_seen.saturating_add(packet_count),
                        packet.tick,
                        limit
                    ),
                });
            }
        }
        Ok(())
    }

    fn record_packet(&mut self, packet: &InputPacket) {
        self.last_sequence
            .insert(packet.peer_id, packet.sequence_id);
        self.last_tick_by_peer
            .entry(packet.peer_id)
            .and_modify(|tick| *tick = (*tick).max(packet.tick))
            .or_insert(packet.tick);
        for action in &packet.actions {
            *self
                .action_counts
                .entry((packet.peer_id, packet.tick, action.action.clone()))
                .or_default() += 1;
        }
    }

    fn reject<T>(&mut self, violation: CheatViolation) -> Result<T, NetworkError> {
        let message = violation.message.clone();
        self.push_violation(violation);
        Err(NetworkError::CheatRejected(message))
    }

    fn push_violation(&mut self, violation: CheatViolation) {
        self.violations.push_back(violation);
        while self.violations.len() > self.config.max_violation_log_entries.max(1) {
            self.violations.pop_front();
        }
    }
}

fn validate_policy_token(value: &str, label: &str) -> Result<(), NetworkError> {
    if value.is_empty()
        || !value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'-' | b'.' | b':' | b'/'))
    {
        return Err(NetworkError::InvalidOperation(format!(
            "{} '{}' is not a portable token",
            label, value
        )));
    }
    Ok(())
}
