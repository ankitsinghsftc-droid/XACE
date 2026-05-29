use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::{EntityId, NetworkError, PeerId, Tick};

pub const INPUT_PACKET_SCHEMA_VERSION: u16 = 1;
pub const MAX_ACTION_NAME_BYTES: usize = 64;
pub const MAX_DEVICE_ID_BYTES: usize = 64;
pub const MAX_PACKET_ACTIONS: usize = 64;
pub const MAX_ABS_ACTION_VALUE: f32 = 1.0;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub enum InputActionKind {
    Button,
    Axis1D,
    Axis2D,
    Pointer,
    Text,
    Custom,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub enum InputActionPhase {
    Started,
    Changed,
    Performed,
    Cancelled,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct InputAction {
    pub action: String,
    pub value: f32,
    #[serde(default = "default_action_kind")]
    pub kind: InputActionKind,
    #[serde(default = "default_action_phase")]
    pub phase: InputActionPhase,
    #[serde(default)]
    pub secondary_value: f32,
    #[serde(default)]
    pub target_entity: Option<EntityId>,
    #[serde(default)]
    pub metadata: BTreeMap<String, String>,
}

impl InputAction {
    pub fn button(action: impl Into<String>, pressed: bool) -> Self {
        Self {
            action: action.into(),
            value: if pressed { 1.0 } else { 0.0 },
            kind: InputActionKind::Button,
            phase: InputActionPhase::Performed,
            secondary_value: 0.0,
            target_entity: None,
            metadata: BTreeMap::new(),
        }
    }

    pub fn axis(action: impl Into<String>, value: f32) -> Self {
        Self {
            action: action.into(),
            value,
            kind: InputActionKind::Axis1D,
            phase: InputActionPhase::Changed,
            secondary_value: 0.0,
            target_entity: None,
            metadata: BTreeMap::new(),
        }
    }

    pub fn axis2(action: impl Into<String>, x: f32, y: f32) -> Self {
        Self {
            action: action.into(),
            value: x,
            kind: InputActionKind::Axis2D,
            phase: InputActionPhase::Changed,
            secondary_value: y,
            target_entity: None,
            metadata: BTreeMap::new(),
        }
    }

    pub fn validate(&self) -> Result<(), NetworkError> {
        if self.action.is_empty() {
            return Err(NetworkError::InvalidInput(
                "action name must not be empty".to_string(),
            ));
        }
        if self.action.len() > MAX_ACTION_NAME_BYTES {
            return Err(NetworkError::InvalidInput(format!(
                "action '{}' exceeds {} bytes",
                self.action, MAX_ACTION_NAME_BYTES
            )));
        }
        if !is_portable_token(&self.action) {
            return Err(NetworkError::InvalidInput(format!(
                "action '{}' contains non-portable characters",
                self.action
            )));
        }
        validate_finite_unit(self.value, "value")?;
        validate_finite_unit(self.secondary_value, "secondary_value")?;
        if matches!(self.kind, InputActionKind::Button) && self.value != 0.0 && self.value != 1.0 {
            return Err(NetworkError::InvalidInput(format!(
                "button action '{}' must use value 0.0 or 1.0",
                self.action
            )));
        }
        for (key, value) in &self.metadata {
            if key.len() > MAX_ACTION_NAME_BYTES || !is_portable_token(key) {
                return Err(NetworkError::InvalidInput(format!(
                    "metadata key '{}' is not portable",
                    key
                )));
            }
            if value.len() > 256 {
                return Err(NetworkError::InvalidInput(format!(
                    "metadata value for '{}' exceeds 256 bytes",
                    key
                )));
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct InputPacketSignature {
    pub algorithm: String,
    pub value: String,
}

impl InputPacketSignature {
    pub fn empty() -> Self {
        Self {
            algorithm: String::new(),
            value: String::new(),
        }
    }

    pub fn is_empty(&self) -> bool {
        self.algorithm.is_empty() && self.value.is_empty()
    }
}

impl Default for InputPacketSignature {
    fn default() -> Self {
        Self::empty()
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct InputPacket {
    #[serde(default = "default_schema_version")]
    pub schema_version: u16,
    pub peer_id: PeerId,
    pub tick: Tick,
    pub sequence_id: u64,
    #[serde(default)]
    pub player_id: Option<EntityId>,
    #[serde(default)]
    pub device_id: String,
    #[serde(default)]
    pub actions: Vec<InputAction>,
    #[serde(default)]
    pub timestamp_ms: u64,
    #[serde(default)]
    pub predicted: bool,
    #[serde(default)]
    pub signature: InputPacketSignature,
}

impl InputPacket {
    pub fn unsigned(peer_id: PeerId, tick: Tick, sequence_id: u64) -> Self {
        Self {
            schema_version: INPUT_PACKET_SCHEMA_VERSION,
            peer_id,
            tick,
            sequence_id,
            player_id: None,
            device_id: String::new(),
            actions: Vec::new(),
            timestamp_ms: 0,
            predicted: false,
            signature: InputPacketSignature::empty(),
        }
    }

    pub fn with_actions(
        peer_id: PeerId,
        tick: Tick,
        sequence_id: u64,
        actions: Vec<InputAction>,
    ) -> Self {
        Self {
            actions,
            ..Self::unsigned(peer_id, tick, sequence_id)
        }
    }

    pub fn with_player(mut self, player_id: EntityId) -> Self {
        self.player_id = Some(player_id);
        self
    }

    pub fn with_device(mut self, device_id: impl Into<String>) -> Self {
        self.device_id = device_id.into();
        self
    }

    pub fn validate(&self) -> Result<(), NetworkError> {
        if self.schema_version != INPUT_PACKET_SCHEMA_VERSION {
            return Err(NetworkError::InvalidInput(format!(
                "unsupported input packet schema_version {}",
                self.schema_version
            )));
        }
        if self.peer_id == 0 {
            return Err(NetworkError::InvalidInput(
                "peer_id 0 is reserved".to_string(),
            ));
        }
        if self.sequence_id == 0 {
            return Err(NetworkError::InvalidInput(
                "sequence_id must be >= 1".to_string(),
            ));
        }
        if self.actions.len() > MAX_PACKET_ACTIONS {
            return Err(NetworkError::InvalidInput(format!(
                "too many actions: {} > {}",
                self.actions.len(),
                MAX_PACKET_ACTIONS
            )));
        }
        if self.device_id.len() > MAX_DEVICE_ID_BYTES {
            return Err(NetworkError::InvalidInput(format!(
                "device_id exceeds {} bytes",
                MAX_DEVICE_ID_BYTES
            )));
        }
        if !self.device_id.is_empty() && !is_portable_token(&self.device_id) {
            return Err(NetworkError::InvalidInput(format!(
                "device_id '{}' contains non-portable characters",
                self.device_id
            )));
        }
        for action in &self.actions {
            action.validate()?;
        }
        Ok(())
    }

    pub fn canonical_payload_bytes(&self) -> Vec<u8> {
        let mut bytes = Vec::with_capacity(128 + self.actions.len() * 64);
        bytes.extend_from_slice(&self.schema_version.to_le_bytes());
        bytes.extend_from_slice(&self.peer_id.to_le_bytes());
        bytes.extend_from_slice(&self.tick.to_le_bytes());
        bytes.extend_from_slice(&self.sequence_id.to_le_bytes());
        bytes.extend_from_slice(&self.player_id.unwrap_or(0).to_le_bytes());
        push_string(&mut bytes, &self.device_id);
        bytes.extend_from_slice(&self.timestamp_ms.to_le_bytes());
        bytes.push(u8::from(self.predicted));
        bytes.extend_from_slice(&(self.actions.len() as u32).to_le_bytes());
        for action in &self.actions {
            push_string(&mut bytes, &action.action);
            bytes.extend_from_slice(&action.value.to_bits().to_le_bytes());
            bytes.extend_from_slice(&action.secondary_value.to_bits().to_le_bytes());
            bytes.extend_from_slice(&(action.kind as u8).to_le_bytes());
            bytes.extend_from_slice(&(action.phase as u8).to_le_bytes());
            bytes.extend_from_slice(&action.target_entity.unwrap_or(0).to_le_bytes());
            bytes.extend_from_slice(&(action.metadata.len() as u32).to_le_bytes());
            for (key, value) in &action.metadata {
                push_string(&mut bytes, key);
                push_string(&mut bytes, value);
            }
        }
        bytes
    }

    pub fn deterministic_digest(&self) -> String {
        let mut hasher = Sha256::new();
        hasher.update(self.canonical_payload_bytes());
        format!("{:x}", hasher.finalize())
    }

    pub fn signed(mut self, shared_secret: &[u8]) -> Self {
        self.signature = InputPacketSignature {
            algorithm: "sha256-shared-secret-v1".to_string(),
            value: self.compute_signature(shared_secret),
        };
        self
    }

    pub fn verify_signature(&self, shared_secret: &[u8]) -> Result<(), NetworkError> {
        if self.signature.is_empty() {
            return Err(NetworkError::InvalidInput(
                "input packet is missing signature".to_string(),
            ));
        }
        if self.signature.algorithm != "sha256-shared-secret-v1" {
            return Err(NetworkError::InvalidInput(format!(
                "unsupported signature algorithm '{}'",
                self.signature.algorithm
            )));
        }
        let expected = self.compute_signature(shared_secret);
        if constant_time_eq(expected.as_bytes(), self.signature.value.as_bytes()) {
            Ok(())
        } else {
            Err(NetworkError::InvalidInput(
                "input packet signature mismatch".to_string(),
            ))
        }
    }

    fn compute_signature(&self, shared_secret: &[u8]) -> String {
        let mut hasher = Sha256::new();
        hasher.update(shared_secret);
        hasher.update([0xff]);
        hasher.update(self.canonical_payload_bytes());
        format!("{:x}", hasher.finalize())
    }
}

fn default_schema_version() -> u16 {
    INPUT_PACKET_SCHEMA_VERSION
}

fn default_action_kind() -> InputActionKind {
    InputActionKind::Custom
}

fn default_action_phase() -> InputActionPhase {
    InputActionPhase::Performed
}

fn validate_finite_unit(value: f32, field: &str) -> Result<(), NetworkError> {
    if !value.is_finite() {
        return Err(NetworkError::InvalidInput(format!(
            "{} must be finite",
            field
        )));
    }
    if value.abs() > MAX_ABS_ACTION_VALUE {
        return Err(NetworkError::InvalidInput(format!(
            "{} {} outside +/-{}",
            field, value, MAX_ABS_ACTION_VALUE
        )));
    }
    Ok(())
}

fn is_portable_token(value: &str) -> bool {
    value
        .bytes()
        .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'-' | b'.' | b':' | b'/'))
}

fn push_string(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&(value.len() as u32).to_le_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

fn constant_time_eq(left: &[u8], right: &[u8]) -> bool {
    if left.len() != right.len() {
        return false;
    }
    let mut diff = 0u8;
    for (a, b) in left.iter().zip(right.iter()) {
        diff |= a ^ b;
    }
    diff == 0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn digest_is_stable_for_same_packet() {
        let packet = InputPacket::with_actions(1, 10, 2, vec![InputAction::axis("move_x", 0.5)])
            .with_player(99)
            .with_device("keyboard");
        assert_eq!(packet.deterministic_digest(), packet.deterministic_digest());
    }

    #[test]
    fn validation_rejects_non_portable_action_names() {
        let packet = InputPacket::with_actions(1, 1, 1, vec![InputAction::axis("move x", 0.5)]);
        assert!(packet.validate().is_err());
    }

    #[test]
    fn signature_roundtrip() {
        let packet = InputPacket::with_actions(1, 1, 1, vec![InputAction::button("jump", true)])
            .signed(b"secret");
        packet.verify_signature(b"secret").unwrap();
        assert!(packet.verify_signature(b"other").is_err());
    }
}
