//! Runtime <-> engine adapter protocol.
//!
//! Messages are JSON payloads framed as:
//! `[u32 little-endian payload_len][payload bytes]`.
//! The runtime keeps this module intentionally transport-agnostic so the same
//! contract can back TCP, shared memory, embedded adapters, and tests.

use std::collections::BTreeMap;
use std::fmt;
use std::io::{Read, Write};

use serde::{Deserialize, Serialize};
use xace_core::assets::{AssetReference, PlaybackCommandRequest, SemanticPlaybackKind};
use xace_core::wire::feedback_payload::{FeedbackMessage, FeedbackPayload};

pub const PROTOCOL_VERSION: u32 = 1;
pub const MAX_MESSAGE_BYTES: usize = 4 * 1024 * 1024;
pub const MAX_HANDSHAKE_BYTES: usize = 64 * 1024;
pub const MAX_ENGINE_NAME_BYTES: usize = 96;
pub const MAX_VERSION_BYTES: usize = 64;
pub const MAX_CGS_HASH_BYTES: usize = 128;
pub const DEFAULT_TICK_RATE: u32 = 60;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum EngineMessageType {
    Handshake,
    HandshakeAck,
    TickSnapshot,
    InputPacket,
    FeedbackPayload,
    PlaybackCommands,
    Disconnect,
    Error,
}

impl EngineMessageType {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Handshake => "handshake",
            Self::HandshakeAck => "handshake_ack",
            Self::TickSnapshot => "tick_snapshot",
            Self::InputPacket => "input_packet",
            Self::FeedbackPayload => "feedback_payload",
            Self::PlaybackCommands => "playback_commands",
            Self::Disconnect => "disconnect",
            Self::Error => "error",
        }
    }

    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "handshake" => Some(Self::Handshake),
            "handshake_ack" => Some(Self::HandshakeAck),
            "tick_snapshot" => Some(Self::TickSnapshot),
            "input_packet" => Some(Self::InputPacket),
            "feedback_payload" => Some(Self::FeedbackPayload),
            "playback_commands" => Some(Self::PlaybackCommands),
            "disconnect" => Some(Self::Disconnect),
            "error" => Some(Self::Error),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EntityState {
    pub id: u64,
    #[serde(default)]
    pub actor_id: String,
    #[serde(default)]
    pub components: BTreeMap<u32, String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Handshake {
    pub msg_type: String,
    pub protocol_version: u32,
    pub engine_name: String,
    pub engine_version: String,
    pub adapter_version: String,
    #[serde(default)]
    pub cgs_hash: String,
    #[serde(default)]
    pub capabilities: Vec<String>,
}

impl Handshake {
    pub fn new(engine_name: &str, cgs_hash: &str) -> Self {
        Self {
            msg_type: EngineMessageType::Handshake.as_str().to_string(),
            protocol_version: PROTOCOL_VERSION,
            engine_name: engine_name.to_string(),
            engine_version: "unknown".to_string(),
            adapter_version: "0.1.0".to_string(),
            cgs_hash: cgs_hash.to_string(),
            capabilities: Vec::new(),
        }
    }

    pub fn validate(&self, runtime_cgs_hash: &str) -> Result<(), ProtocolError> {
        validate_msg_type(&self.msg_type, EngineMessageType::Handshake)?;
        if self.protocol_version != PROTOCOL_VERSION {
            return Err(ProtocolError::ProtocolVersionMismatch {
                engine: self.protocol_version,
                runtime: PROTOCOL_VERSION,
            });
        }
        validate_portable_field(
            "engine_name",
            &self.engine_name,
            MAX_ENGINE_NAME_BYTES,
            true,
        )?;
        validate_portable_field(
            "engine_version",
            &self.engine_version,
            MAX_VERSION_BYTES,
            true,
        )?;
        validate_portable_field(
            "adapter_version",
            &self.adapter_version,
            MAX_VERSION_BYTES,
            true,
        )?;
        validate_portable_field("cgs_hash", &self.cgs_hash, MAX_CGS_HASH_BYTES, false)?;
        for capability in &self.capabilities {
            validate_portable_field("capability", capability, MAX_VERSION_BYTES, true)?;
        }
        if !self.cgs_hash.is_empty()
            && !runtime_cgs_hash.is_empty()
            && self.cgs_hash != runtime_cgs_hash
        {
            return Err(ProtocolError::CgsHashMismatch {
                engine: self.cgs_hash.clone(),
                runtime: runtime_cgs_hash.to_string(),
            });
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HandshakeAck {
    pub msg_type: String,
    pub protocol_version: u32,
    pub accepted: bool,
    pub reject_reason: String,
    pub session_id: String,
    pub tick_rate: u32,
    pub cgs_hash: String,
    pub schema_version: String,
    pub initial_entities: Vec<EntityState>,
    #[serde(default)]
    pub runtime_capabilities: Vec<String>,
}

impl HandshakeAck {
    pub fn accepted(
        session_id: impl Into<String>,
        cgs_hash: impl Into<String>,
        schema_version: impl Into<String>,
        initial_entities: Vec<EntityState>,
    ) -> Self {
        Self {
            msg_type: EngineMessageType::HandshakeAck.as_str().to_string(),
            protocol_version: PROTOCOL_VERSION,
            accepted: true,
            reject_reason: String::new(),
            session_id: session_id.into(),
            tick_rate: DEFAULT_TICK_RATE,
            cgs_hash: cgs_hash.into(),
            schema_version: schema_version.into(),
            initial_entities,
            runtime_capabilities: vec![
                "full_snapshot".to_string(),
                "input_packet_v1".to_string(),
                "length_prefixed_json".to_string(),
                "multi_engine_clients".to_string(),
            ],
        }
    }

    pub fn rejected(reason: impl Into<String>) -> Self {
        Self {
            msg_type: EngineMessageType::HandshakeAck.as_str().to_string(),
            protocol_version: PROTOCOL_VERSION,
            accepted: false,
            reject_reason: reason.into(),
            session_id: String::new(),
            tick_rate: DEFAULT_TICK_RATE,
            cgs_hash: String::new(),
            schema_version: String::new(),
            initial_entities: Vec::new(),
            runtime_capabilities: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TickSnapshot {
    pub msg_type: String,
    pub tick: u64,
    pub timestamp_ms: u64,
    pub entities: Vec<EntityState>,
    #[serde(default)]
    pub spawned_ids: Vec<u64>,
    #[serde(default)]
    pub destroyed_ids: Vec<u64>,
    #[serde(default)]
    pub events: Vec<GameEvent>,
    #[serde(default)]
    pub playback_commands: Vec<EnginePlaybackCommand>,
}

impl TickSnapshot {
    pub fn new(
        tick: u64,
        timestamp_ms: u64,
        entities: Vec<EntityState>,
        spawned_ids: Vec<u64>,
        destroyed_ids: Vec<u64>,
        events: Vec<GameEvent>,
    ) -> Self {
        Self {
            msg_type: EngineMessageType::TickSnapshot.as_str().to_string(),
            tick,
            timestamp_ms,
            entities,
            spawned_ids,
            destroyed_ids,
            events,
            playback_commands: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DisconnectMessage {
    pub msg_type: String,
    pub reason: String,
}

impl DisconnectMessage {
    pub fn new(reason: impl Into<String>) -> Self {
        Self {
            msg_type: EngineMessageType::Disconnect.as_str().to_string(),
            reason: reason.into(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ErrorMessage {
    pub msg_type: String,
    pub code: String,
    pub message: String,
}

impl ErrorMessage {
    pub fn new(code: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            msg_type: EngineMessageType::Error.as_str().to_string(),
            code: code.into(),
            message: message.into(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InputPacket {
    pub msg_type: String,
    #[serde(default = "default_peer_id")]
    pub peer_id: u64,
    pub tick: u64,
    #[serde(default)]
    pub player_id: u64,
    pub sequence_id: u64,
    #[serde(default)]
    pub actions: Vec<InputAction>,
    #[serde(default)]
    pub timestamp_ms: u64,
    #[serde(default)]
    pub device_id: String,
    #[serde(default)]
    pub predicted: bool,
}

impl InputPacket {
    pub fn validate(&self) -> Result<(), ProtocolError> {
        validate_msg_type(&self.msg_type, EngineMessageType::InputPacket)?;
        if self.peer_id == 0 {
            return Err(ProtocolError::InvalidField {
                field: "peer_id",
                reason: "must be greater than zero".to_string(),
            });
        }
        if self.sequence_id == 0 {
            return Err(ProtocolError::InvalidField {
                field: "sequence_id",
                reason: "must be greater than zero".to_string(),
            });
        }
        validate_portable_field("device_id", &self.device_id, 64, false)?;
        for action in &self.actions {
            action.validate()?;
        }
        Ok(())
    }
}

fn default_peer_id() -> u64 {
    1
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InputAction {
    pub action: String,
    pub value: f32,
    #[serde(default)]
    pub secondary_value: f32,
    #[serde(default)]
    pub kind: String,
    #[serde(default)]
    pub phase: String,
}

impl InputAction {
    pub fn validate(&self) -> Result<(), ProtocolError> {
        validate_portable_field("action", &self.action, 64, true)?;
        if !self.value.is_finite() || !self.secondary_value.is_finite() {
            return Err(ProtocolError::InvalidField {
                field: "action.value",
                reason: "values must be finite".to_string(),
            });
        }
        if self.value.abs() > 1.0 || self.secondary_value.abs() > 1.0 {
            return Err(ProtocolError::InvalidField {
                field: "action.value",
                reason: "values must be inside [-1, 1]".to_string(),
            });
        }
        validate_portable_field("action.kind", &self.kind, 32, false)?;
        validate_portable_field("action.phase", &self.phase, 32, false)?;
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GameEvent {
    pub event_type: String,
    pub entity_id: u64,
    #[serde(default)]
    pub data: BTreeMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EngineFeedbackPacket {
    pub msg_type: String,
    pub tick: u64,
    #[serde(default)]
    pub messages: Vec<FeedbackMessage>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EnginePlaybackCommand {
    pub binding_id: String,
    pub event_name: String,
    pub playback_kind: SemanticPlaybackKind,
    pub entity_id: u64,
    pub asset: AssetReference,
    #[serde(default)]
    pub semantic_action: String,
    #[serde(default)]
    pub parameters: BTreeMap<String, String>,
    #[serde(default)]
    pub priority: i32,
}

impl EnginePlaybackCommand {
    pub fn validate(&self) -> Result<(), ProtocolError> {
        validate_portable_field("binding_id", &self.binding_id, 128, true)?;
        validate_portable_field("event_name", &self.event_name, 128, true)?;
        validate_portable_field("asset.id", &self.asset.id, 256, true)?;
        validate_portable_field("semantic_action", &self.semantic_action, 128, false)?;
        if self.entity_id == 0 {
            return Err(ProtocolError::InvalidField {
                field: "entity_id",
                reason: "must be greater than zero".to_string(),
            });
        }
        if !self
            .playback_kind
            .accepts_asset_type(&self.asset.asset_type)
        {
            return Err(ProtocolError::InvalidField {
                field: "asset.asset_type",
                reason: format!(
                    "{:?} command cannot use {:?}",
                    self.playback_kind, self.asset.asset_type
                ),
            });
        }
        for key in self.parameters.keys() {
            validate_portable_field("parameter.key", key, 64, true)?;
        }
        Ok(())
    }
}

impl From<PlaybackCommandRequest> for EnginePlaybackCommand {
    fn from(request: PlaybackCommandRequest) -> Self {
        Self {
            binding_id: request.binding_id,
            event_name: request.event_name,
            playback_kind: request.playback_kind,
            entity_id: request.entity_id,
            asset: request.asset,
            semantic_action: request.semantic_action,
            parameters: request.parameters,
            priority: request.priority,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EnginePlaybackCommandBatch {
    pub msg_type: String,
    pub tick: u64,
    #[serde(default)]
    pub commands: Vec<EnginePlaybackCommand>,
}

impl EnginePlaybackCommandBatch {
    pub fn new(tick: u64, commands: Vec<EnginePlaybackCommand>) -> Self {
        Self {
            msg_type: EngineMessageType::PlaybackCommands.as_str().to_string(),
            tick,
            commands,
        }
    }

    pub fn validate(&self) -> Result<(), ProtocolError> {
        validate_msg_type(&self.msg_type, EngineMessageType::PlaybackCommands)?;
        if self.commands.len() > 4096 {
            return Err(ProtocolError::InvalidField {
                field: "commands",
                reason: "playback command batch contains more than 4096 commands".to_string(),
            });
        }
        for command in &self.commands {
            command.validate()?;
        }
        Ok(())
    }
}

impl EngineFeedbackPacket {
    pub fn validate(&self) -> Result<(), ProtocolError> {
        validate_msg_type(&self.msg_type, EngineMessageType::FeedbackPayload)?;
        if self.messages.len() > 4096 {
            return Err(ProtocolError::InvalidField {
                field: "messages",
                reason: "feedback payload contains more than 4096 messages".to_string(),
            });
        }
        Ok(())
    }
}

impl From<EngineFeedbackPacket> for FeedbackPayload {
    fn from(packet: EngineFeedbackPacket) -> Self {
        let mut payload = FeedbackPayload {
            tick: packet.tick,
            messages: packet.messages,
        };
        payload.sort_in_place();
        payload
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum InboundMessage {
    Handshake(Handshake),
    InputPacket(InputPacket),
    FeedbackPayload(FeedbackPayload),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum OutboundMessage {
    HandshakeAck(HandshakeAck),
    TickSnapshot(TickSnapshot),
    PlaybackCommands(EnginePlaybackCommandBatch),
    Disconnect(DisconnectMessage),
    Error(ErrorMessage),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ProtocolError {
    EmptyFrame,
    MessageTooLarge {
        size: usize,
        max: usize,
    },
    InvalidJson(String),
    MissingMessageType,
    UnexpectedMessageType {
        expected: &'static str,
        actual: String,
    },
    UnknownMessageType(String),
    ProtocolVersionMismatch {
        engine: u32,
        runtime: u32,
    },
    CgsHashMismatch {
        engine: String,
        runtime: String,
    },
    InvalidField {
        field: &'static str,
        reason: String,
    },
}

impl fmt::Display for ProtocolError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::EmptyFrame => write!(f, "empty protocol frame"),
            Self::MessageTooLarge { size, max } => {
                write!(f, "message too large: {} bytes (max {})", size, max)
            }
            Self::InvalidJson(err) => write!(f, "invalid JSON: {}", err),
            Self::MissingMessageType => write!(f, "missing msg_type field"),
            Self::UnexpectedMessageType { expected, actual } => {
                write!(f, "expected msg_type '{}', got '{}'", expected, actual)
            }
            Self::UnknownMessageType(msg_type) => write!(f, "unknown msg_type '{}'", msg_type),
            Self::ProtocolVersionMismatch { engine, runtime } => write!(
                f,
                "protocol version mismatch: engine={} runtime={}",
                engine, runtime
            ),
            Self::CgsHashMismatch { engine, runtime } => {
                write!(
                    f,
                    "CGS hash mismatch: engine='{}' runtime='{}'",
                    engine, runtime
                )
            }
            Self::InvalidField { field, reason } => write!(f, "invalid {}: {}", field, reason),
        }
    }
}

impl std::error::Error for ProtocolError {}

pub fn parse_inbound_message(raw: &[u8]) -> Result<InboundMessage, ProtocolError> {
    if raw.is_empty() {
        return Err(ProtocolError::EmptyFrame);
    }
    if raw.len() > MAX_MESSAGE_BYTES {
        return Err(ProtocolError::MessageTooLarge {
            size: raw.len(),
            max: MAX_MESSAGE_BYTES,
        });
    }

    let raw_value: serde_json::Value =
        serde_json::from_slice(raw).map_err(|err| ProtocolError::InvalidJson(err.to_string()))?;
    let msg_type = raw_value
        .get("msg_type")
        .and_then(|value| value.as_str())
        .ok_or(ProtocolError::MissingMessageType)?;

    match EngineMessageType::parse(msg_type) {
        Some(EngineMessageType::Handshake) => {
            if raw.len() > MAX_HANDSHAKE_BYTES {
                return Err(ProtocolError::MessageTooLarge {
                    size: raw.len(),
                    max: MAX_HANDSHAKE_BYTES,
                });
            }
            let handshake = serde_json::from_value(raw_value)
                .map_err(|err| ProtocolError::InvalidJson(err.to_string()))?;
            Ok(InboundMessage::Handshake(handshake))
        }
        Some(EngineMessageType::InputPacket) => {
            let packet: InputPacket = serde_json::from_value(raw_value)
                .map_err(|err| ProtocolError::InvalidJson(err.to_string()))?;
            packet.validate()?;
            Ok(InboundMessage::InputPacket(packet))
        }
        Some(EngineMessageType::FeedbackPayload) => {
            let packet: EngineFeedbackPacket = serde_json::from_value(raw_value)
                .map_err(|err| ProtocolError::InvalidJson(err.to_string()))?;
            packet.validate()?;
            Ok(InboundMessage::FeedbackPayload(packet.into()))
        }
        Some(other) => Err(ProtocolError::UnexpectedMessageType {
            expected: "handshake|input_packet|feedback_payload",
            actual: other.as_str().to_string(),
        }),
        None => Err(ProtocolError::UnknownMessageType(msg_type.to_string())),
    }
}

impl TryFrom<InputPacket> for xace_network_core::input::InputPacket {
    type Error = xace_network_core::NetworkError;

    fn try_from(packet: InputPacket) -> Result<Self, Self::Error> {
        let mut converted = xace_network_core::input::InputPacket::with_actions(
            packet.peer_id,
            packet.tick,
            packet.sequence_id,
            packet
                .actions
                .into_iter()
                .map(convert_input_action)
                .collect::<Result<Vec<_>, _>>()?,
        )
        .with_device(packet.device_id);
        if packet.player_id != 0 {
            converted = converted.with_player(packet.player_id);
        }
        converted.timestamp_ms = packet.timestamp_ms;
        converted.predicted = packet.predicted;
        converted.validate()?;
        Ok(converted)
    }
}

fn convert_input_action(
    action: InputAction,
) -> Result<xace_network_core::input::InputAction, xace_network_core::NetworkError> {
    let kind = match action.kind.as_str() {
        "" | "custom" | "Custom" => xace_network_core::input::InputActionKind::Custom,
        "button" | "Button" => xace_network_core::input::InputActionKind::Button,
        "axis_1d" | "Axis1D" => xace_network_core::input::InputActionKind::Axis1D,
        "axis_2d" | "Axis2D" => xace_network_core::input::InputActionKind::Axis2D,
        "pointer" | "Pointer" => xace_network_core::input::InputActionKind::Pointer,
        "text" | "Text" => xace_network_core::input::InputActionKind::Text,
        other => {
            return Err(xace_network_core::NetworkError::InvalidInput(format!(
                "unsupported action kind '{}'",
                other
            )))
        }
    };
    let phase = match action.phase.as_str() {
        "" | "performed" | "Performed" => xace_network_core::input::InputActionPhase::Performed,
        "started" | "Started" => xace_network_core::input::InputActionPhase::Started,
        "changed" | "Changed" => xace_network_core::input::InputActionPhase::Changed,
        "cancelled" | "Cancelled" => xace_network_core::input::InputActionPhase::Cancelled,
        other => {
            return Err(xace_network_core::NetworkError::InvalidInput(format!(
                "unsupported action phase '{}'",
                other
            )))
        }
    };

    let converted = xace_network_core::input::InputAction {
        action: action.action,
        value: action.value,
        kind,
        phase,
        secondary_value: action.secondary_value,
        target_entity: None,
        metadata: BTreeMap::new(),
    };
    converted.validate()?;
    Ok(converted)
}

pub fn write_message<W: Write, T: Serialize>(writer: &mut W, msg: &T) -> std::io::Result<usize> {
    let json = serde_json::to_vec(msg)
        .map_err(|err| std::io::Error::new(std::io::ErrorKind::InvalidData, err))?;
    if json.len() > MAX_MESSAGE_BYTES {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            format!(
                "message too large: {} bytes (max {})",
                json.len(),
                MAX_MESSAGE_BYTES
            ),
        ));
    }
    writer.write_all(&(json.len() as u32).to_le_bytes())?;
    writer.write_all(&json)?;
    writer.flush()?;
    Ok(json.len())
}

pub fn read_message<R: Read>(reader: &mut R) -> std::io::Result<Option<Vec<u8>>> {
    let mut len_buf = [0u8; 4];
    match reader.read_exact(&mut len_buf) {
        Ok(()) => {}
        Err(err) if err.kind() == std::io::ErrorKind::UnexpectedEof => return Ok(None),
        Err(err) => return Err(err),
    }

    let len = u32::from_le_bytes(len_buf) as usize;
    if len == 0 {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            "zero-length protocol frame",
        ));
    }
    if len > MAX_MESSAGE_BYTES {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            format!(
                "message too large: {} bytes (max {})",
                len, MAX_MESSAGE_BYTES
            ),
        ));
    }

    let mut buf = vec![0u8; len];
    reader.read_exact(&mut buf)?;
    Ok(Some(buf))
}

fn validate_msg_type(actual: &str, expected: EngineMessageType) -> Result<(), ProtocolError> {
    if actual == expected.as_str() {
        Ok(())
    } else {
        Err(ProtocolError::UnexpectedMessageType {
            expected: expected.as_str(),
            actual: actual.to_string(),
        })
    }
}

fn validate_portable_field(
    field: &'static str,
    value: &str,
    max_bytes: usize,
    required: bool,
) -> Result<(), ProtocolError> {
    if required && value.is_empty() {
        return Err(ProtocolError::InvalidField {
            field,
            reason: "must not be empty".to_string(),
        });
    }
    if value.len() > max_bytes {
        return Err(ProtocolError::InvalidField {
            field,
            reason: format!("exceeds {} bytes", max_bytes),
        });
    }
    if !value.is_empty()
        && !value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'-' | b'.' | b'/' | b' '))
    {
        return Err(ProtocolError::InvalidField {
            field,
            reason: "contains non-portable characters".to_string(),
        });
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::io::Cursor;

    use super::*;

    #[test]
    fn parse_legacy_input_packet_defaults_peer_id() {
        let raw =
            br#"{"msg_type":"input_packet","tick":7,"player_id":1,"sequence_id":2,"actions":[]}"#;
        let msg = parse_inbound_message(raw).unwrap();
        let InboundMessage::InputPacket(packet) = msg else {
            panic!("expected input packet");
        };
        assert_eq!(packet.peer_id, 1);
        assert_eq!(packet.tick, 7);
    }

    #[test]
    fn input_packet_converts_to_network_core_packet() {
        let raw = br#"{"msg_type":"input_packet","peer_id":4,"tick":7,"player_id":9,"sequence_id":2,"device_id":"keyboard","actions":[{"action":"move_x","value":1.0,"kind":"axis_1d","phase":"changed"}]}"#;
        let InboundMessage::InputPacket(packet) = parse_inbound_message(raw).unwrap() else {
            panic!("expected input packet");
        };
        let converted = xace_network_core::input::InputPacket::try_from(packet).unwrap();
        assert_eq!(converted.peer_id, 4);
        assert_eq!(converted.player_id, Some(9));
        assert_eq!(converted.actions.len(), 1);
    }

    #[test]
    fn feedback_payload_parses_and_sorts_messages() {
        let raw = serde_json::json!({
            "msg_type": "feedback_payload",
            "tick": 12,
            "messages": [
                {
                    "feedback_type": "PerformanceMetrics",
                    "entity_id": 0,
                    "generated_frame": 22,
                    "payload_json": "{\"frame_ms\":16.0}"
                },
                {
                    "feedback_type": "InputDeviceUpdate",
                    "entity_id": 7,
                    "generated_frame": 20,
                    "payload_json": "{\"device_id\":\"keyboard\"}"
                }
            ]
        });
        let raw = serde_json::to_vec(&raw).unwrap();
        let InboundMessage::FeedbackPayload(payload) = parse_inbound_message(&raw).unwrap() else {
            panic!("expected feedback payload");
        };
        assert_eq!(payload.tick, 12);
        assert_eq!(payload.messages.len(), 2);
        assert_eq!(payload.messages[0].generated_frame, 20);
        assert_eq!(payload.messages[1].generated_frame, 22);
    }

    #[test]
    fn handshake_validation_rejects_hash_mismatch() {
        let hs = Handshake::new("Godot4", "abc");
        assert!(matches!(
            hs.validate("def"),
            Err(ProtocolError::CgsHashMismatch { .. })
        ));
    }

    #[test]
    fn framed_io_round_trips_json_payload() {
        let mut buffer = Cursor::new(Vec::new());
        let msg = DisconnectMessage::new("done");
        let written = write_message(&mut buffer, &msg).unwrap();
        assert!(written > 0);

        buffer.set_position(0);
        let raw = read_message(&mut buffer).unwrap().unwrap();
        let decoded: DisconnectMessage = serde_json::from_slice(&raw).unwrap();
        assert_eq!(decoded.reason, "done");
    }

    #[test]
    fn playback_command_batch_validates_typed_assets() {
        let command = EnginePlaybackCommand {
            binding_id: "bind_interaction_sfx".to_string(),
            event_name: "interaction.accepted".to_string(),
            playback_kind: SemanticPlaybackKind::Audio,
            entity_id: 7,
            asset: AssetReference::placeholder(
                "interaction_accept_sfx_v1",
                xace_core::assets::AssetType::AudioClip,
            ),
            semantic_action: "play".to_string(),
            parameters: BTreeMap::new(),
            priority: 0,
        };
        let batch = EnginePlaybackCommandBatch::new(42, vec![command]);

        assert_eq!(batch.msg_type, "playback_commands");
        assert!(batch.validate().is_ok());
    }

    #[test]
    fn playback_command_rejects_wrong_asset_type() {
        let command = EnginePlaybackCommand {
            binding_id: "bind_bad".to_string(),
            event_name: "inventory.equipped".to_string(),
            playback_kind: SemanticPlaybackKind::Audio,
            entity_id: 7,
            asset: AssetReference::placeholder("bad_mesh_v1", xace_core::assets::AssetType::Mesh),
            semantic_action: String::new(),
            parameters: BTreeMap::new(),
            priority: 0,
        };

        assert!(matches!(
            command.validate(),
            Err(ProtocolError::InvalidField {
                field: "asset.asset_type",
                ..
            })
        ));
    }
}
