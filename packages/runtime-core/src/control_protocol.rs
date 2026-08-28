//! Local builder-to-runtime control protocol.
//!
//! This is intentionally separate from the engine adapter protocol. Engine
//! adapters own input and snapshots; the builder control socket owns lifecycle
//! commands such as pause, step, reset, and status. Messages use the same
//! little-endian length-prefixed JSON framing as the engine bridge.

use std::fmt;
use std::io::{Read, Write};

use serde::{Deserialize, Serialize};

use crate::engine_protocol::TickSnapshot;

pub const CONTROL_PROTOCOL_VERSION: u32 = 1;
pub const MAX_CONTROL_MESSAGE_BYTES: usize = 4 * 1024 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RuntimeControlAction {
    Play,
    Pause,
    Step,
    Reset,
    ReloadCgs,
    Status,
    Snapshot,
    ReplayRecord,
    ReplayValidate,
    Shutdown,
}

impl RuntimeControlAction {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Play => "play",
            Self::Pause => "pause",
            Self::Step => "step",
            Self::Reset => "reset",
            Self::ReloadCgs => "reload_cgs",
            Self::Status => "status",
            Self::Snapshot => "snapshot",
            Self::ReplayRecord => "replay_record",
            Self::ReplayValidate => "replay_validate",
            Self::Shutdown => "shutdown",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RuntimeEngineEditKind {
    SelectEntity,
    FocusEntity,
    SetComponentField,
}

impl RuntimeEngineEditKind {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::SelectEntity => "select_entity",
            Self::FocusEntity => "focus_entity",
            Self::SetComponentField => "set_component_field",
        }
    }
}

impl fmt::Display for RuntimeEngineEditKind {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl fmt::Display for RuntimeControlAction {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RuntimeControlCommand {
    pub msg_type: String,
    pub protocol_version: u32,
    pub request_id: String,
    pub action: RuntimeControlAction,
    #[serde(default)]
    pub session_id: String,
    #[serde(default)]
    pub tick: Option<u64>,
    #[serde(default)]
    pub cgs_hash: String,
    #[serde(default)]
    pub schema_version: String,
    #[serde(default)]
    pub execution_plan_version: String,
}

impl RuntimeControlCommand {
    pub fn validate(&self) -> Result<(), ControlProtocolError> {
        if self.msg_type != "runtime_control" {
            return Err(ControlProtocolError::UnexpectedMessageType {
                expected: "runtime_control",
                actual: self.msg_type.clone(),
            });
        }
        if self.protocol_version != CONTROL_PROTOCOL_VERSION {
            return Err(ControlProtocolError::ProtocolVersionMismatch {
                client: self.protocol_version,
                runtime: CONTROL_PROTOCOL_VERSION,
            });
        }
        if self.request_id.len() > 96 {
            return Err(ControlProtocolError::InvalidField {
                field: "request_id",
                reason: "exceeds 96 bytes".to_string(),
            });
        }
        if self.session_id.len() > 128 {
            return Err(ControlProtocolError::InvalidField {
                field: "session_id",
                reason: "exceeds 128 bytes".to_string(),
            });
        }
        if self.cgs_hash.len() > 128 {
            return Err(ControlProtocolError::InvalidField {
                field: "cgs_hash",
                reason: "exceeds 128 bytes".to_string(),
            });
        }
        if self.schema_version.len() > 64 {
            return Err(ControlProtocolError::InvalidField {
                field: "schema_version",
                reason: "exceeds 64 bytes".to_string(),
            });
        }
        if self.execution_plan_version.len() > 128 {
            return Err(ControlProtocolError::InvalidField {
                field: "execution_plan_version",
                reason: "exceeds 128 bytes".to_string(),
            });
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RuntimeEngineEditCommand {
    pub msg_type: String,
    pub protocol_version: u32,
    pub request_id: String,
    pub kind: RuntimeEngineEditKind,
    pub entity_id: u64,
    #[serde(default)]
    pub component_type_id: Option<u32>,
    #[serde(default)]
    pub field_path: String,
    #[serde(default)]
    pub value: serde_json::Value,
    #[serde(default)]
    pub session_id: String,
}

impl RuntimeEngineEditCommand {
    pub fn validate(&self) -> Result<(), ControlProtocolError> {
        if self.msg_type != "runtime_engine_edit" {
            return Err(ControlProtocolError::UnexpectedMessageType {
                expected: "runtime_engine_edit",
                actual: self.msg_type.clone(),
            });
        }
        if self.protocol_version != CONTROL_PROTOCOL_VERSION {
            return Err(ControlProtocolError::ProtocolVersionMismatch {
                client: self.protocol_version,
                runtime: CONTROL_PROTOCOL_VERSION,
            });
        }
        if self.entity_id == 0 {
            return Err(ControlProtocolError::InvalidField {
                field: "entity_id",
                reason: "must be greater than zero".to_string(),
            });
        }
        if self.request_id.len() > 96 {
            return Err(ControlProtocolError::InvalidField {
                field: "request_id",
                reason: "exceeds 96 bytes".to_string(),
            });
        }
        if self.session_id.len() > 128 {
            return Err(ControlProtocolError::InvalidField {
                field: "session_id",
                reason: "exceeds 128 bytes".to_string(),
            });
        }
        match self.kind {
            RuntimeEngineEditKind::SelectEntity | RuntimeEngineEditKind::FocusEntity => {}
            RuntimeEngineEditKind::SetComponentField => {
                if self.component_type_id.is_none() {
                    return Err(ControlProtocolError::InvalidField {
                        field: "component_type_id",
                        reason: "is required for set_component_field".to_string(),
                    });
                }
                validate_engine_edit_field_path(&self.field_path)?;
                validate_engine_edit_value(&self.value)?;
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum RuntimeControlInbound {
    Control(RuntimeControlCommand),
    EngineEdit(RuntimeEngineEditCommand),
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RuntimeControlStatus {
    pub tick: u64,
    pub alive_count: usize,
    pub engine_connected: bool,
    pub adapter_type: String,
    #[serde(default)]
    pub engine_connections: Vec<RuntimeControlEngineConnection>,
    #[serde(default)]
    pub engine_snapshots_sent: u64,
    #[serde(default)]
    pub engine_input_packets_received: u64,
    #[serde(default)]
    pub engine_feedback_payloads_received: u64,
    #[serde(default)]
    pub engine_feedback_messages_received: u64,
    #[serde(default)]
    pub engine_malformed_messages: u64,
    #[serde(default)]
    pub engine_dropped_inputs: u64,
    #[serde(default)]
    pub engine_adapter_sequence: u64,
    pub pending_engine_inputs: usize,
    #[serde(default)]
    pub input_sync_mode: String,
    #[serde(default)]
    pub input_sync_last_decision: String,
    pub pending_engine_feedback: usize,
    pub registered_systems: usize,
    pub phase_count: usize,
    pub last_engine_feedback_processed: usize,
    pub last_engine_feedback_invalid: usize,
    pub last_engine_feedback_errors: usize,
    #[serde(default)]
    pub latest_world_hash: String,
    #[serde(default)]
    pub cgs_hash: String,
    #[serde(default)]
    pub schema_version: String,
    #[serde(default)]
    pub execution_plan_version: String,
    #[serde(default)]
    pub parallel_group_execution_policy: String,
    #[serde(default)]
    pub parallel_group_worker_threads: bool,
    #[serde(default)]
    pub hash_log: Vec<RuntimeControlHashRecord>,
    pub paused: bool,
    pub step_budget: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RuntimeControlHashRecord {
    pub tick: u64,
    pub world_hash: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RuntimeControlEngineConnection {
    pub adapter_type: String,
    pub connected: bool,
    pub snapshots_sent: u64,
    pub input_packets_received: u64,
    pub feedback_payloads_received: u64,
    pub feedback_messages_received: u64,
    pub malformed_messages: u64,
    pub dropped_inputs: u64,
    pub queued_inputs: usize,
    pub queued_feedback: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RuntimeControlAck {
    pub msg_type: String,
    pub protocol_version: u32,
    pub request_id: String,
    pub action: RuntimeControlAction,
    pub accepted: bool,
    pub reason: String,
    pub status: RuntimeControlStatus,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub snapshot: Option<TickSnapshot>,
}

impl RuntimeControlAck {
    pub fn accepted(
        command: &RuntimeControlCommand,
        reason: impl Into<String>,
        status: RuntimeControlStatus,
    ) -> Self {
        Self {
            msg_type: "runtime_control_ack".to_string(),
            protocol_version: CONTROL_PROTOCOL_VERSION,
            request_id: command.request_id.clone(),
            action: command.action,
            accepted: true,
            reason: reason.into(),
            status,
            snapshot: None,
        }
    }

    pub fn rejected(
        command: &RuntimeControlCommand,
        reason: impl Into<String>,
        status: RuntimeControlStatus,
    ) -> Self {
        Self {
            msg_type: "runtime_control_ack".to_string(),
            protocol_version: CONTROL_PROTOCOL_VERSION,
            request_id: command.request_id.clone(),
            action: command.action,
            accepted: false,
            reason: reason.into(),
            status,
            snapshot: None,
        }
    }

    pub fn with_snapshot(mut self, snapshot: TickSnapshot) -> Self {
        self.snapshot = Some(snapshot);
        self
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RuntimeEngineEditAck {
    pub msg_type: String,
    pub protocol_version: u32,
    pub request_id: String,
    pub kind: RuntimeEngineEditKind,
    pub accepted: bool,
    pub reason: String,
    pub affected_entity_ids: Vec<u64>,
    pub status: RuntimeControlStatus,
}

impl RuntimeEngineEditAck {
    pub fn accepted(
        command: &RuntimeEngineEditCommand,
        reason: impl Into<String>,
        affected_entity_ids: Vec<u64>,
        status: RuntimeControlStatus,
    ) -> Self {
        Self {
            msg_type: "runtime_engine_edit_ack".to_string(),
            protocol_version: CONTROL_PROTOCOL_VERSION,
            request_id: command.request_id.clone(),
            kind: command.kind,
            accepted: true,
            reason: reason.into(),
            affected_entity_ids,
            status,
        }
    }

    pub fn rejected(
        command: &RuntimeEngineEditCommand,
        reason: impl Into<String>,
        status: RuntimeControlStatus,
    ) -> Self {
        Self {
            msg_type: "runtime_engine_edit_ack".to_string(),
            protocol_version: CONTROL_PROTOCOL_VERSION,
            request_id: command.request_id.clone(),
            kind: command.kind,
            accepted: false,
            reason: reason.into(),
            affected_entity_ids: Vec::new(),
            status,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ControlProtocolError {
    EmptyFrame,
    MessageTooLarge {
        size: usize,
        max: usize,
    },
    InvalidJson(String),
    UnexpectedMessageType {
        expected: &'static str,
        actual: String,
    },
    ProtocolVersionMismatch {
        client: u32,
        runtime: u32,
    },
    InvalidField {
        field: &'static str,
        reason: String,
    },
}

impl fmt::Display for ControlProtocolError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::EmptyFrame => write!(f, "empty control frame"),
            Self::MessageTooLarge { size, max } => {
                write!(f, "control message too large: {} bytes (max {})", size, max)
            }
            Self::InvalidJson(err) => write!(f, "invalid control JSON: {}", err),
            Self::UnexpectedMessageType { expected, actual } => {
                write!(
                    f,
                    "expected control msg_type '{}', got '{}'",
                    expected, actual
                )
            }
            Self::ProtocolVersionMismatch { client, runtime } => write!(
                f,
                "control protocol version mismatch: client={} runtime={}",
                client, runtime
            ),
            Self::InvalidField { field, reason } => {
                write!(f, "invalid control field {}: {}", field, reason)
            }
        }
    }
}

impl std::error::Error for ControlProtocolError {}

fn validate_engine_edit_field_path(field_path: &str) -> Result<(), ControlProtocolError> {
    if field_path.is_empty() {
        return Err(ControlProtocolError::InvalidField {
            field: "field_path",
            reason: "must not be empty for set_component_field".to_string(),
        });
    }
    if field_path.len() > 160 {
        return Err(ControlProtocolError::InvalidField {
            field: "field_path",
            reason: "exceeds 160 bytes".to_string(),
        });
    }
    for segment in field_path.split('.') {
        if segment.is_empty() {
            return Err(ControlProtocolError::InvalidField {
                field: "field_path",
                reason: "contains an empty segment".to_string(),
            });
        }
        if !segment
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-'))
        {
            return Err(ControlProtocolError::InvalidField {
                field: "field_path",
                reason: format!("segment '{}' is not portable", segment),
            });
        }
    }
    Ok(())
}

fn validate_engine_edit_value(value: &serde_json::Value) -> Result<(), ControlProtocolError> {
    if value.is_null() {
        return Err(ControlProtocolError::InvalidField {
            field: "value",
            reason: "must be provided for set_component_field".to_string(),
        });
    }
    if matches!(
        value,
        serde_json::Value::Object(_) | serde_json::Value::Array(_)
    ) {
        return Err(ControlProtocolError::InvalidField {
            field: "value",
            reason: "must be a primitive JSON value".to_string(),
        });
    }
    Ok(())
}

pub fn parse_control_command(raw: &[u8]) -> Result<RuntimeControlCommand, ControlProtocolError> {
    if raw.is_empty() {
        return Err(ControlProtocolError::EmptyFrame);
    }
    if raw.len() > MAX_CONTROL_MESSAGE_BYTES {
        return Err(ControlProtocolError::MessageTooLarge {
            size: raw.len(),
            max: MAX_CONTROL_MESSAGE_BYTES,
        });
    }
    let command: RuntimeControlCommand = serde_json::from_slice(raw)
        .map_err(|err| ControlProtocolError::InvalidJson(err.to_string()))?;
    command.validate()?;
    Ok(command)
}

pub fn parse_control_request(raw: &[u8]) -> Result<RuntimeControlInbound, ControlProtocolError> {
    if raw.is_empty() {
        return Err(ControlProtocolError::EmptyFrame);
    }
    if raw.len() > MAX_CONTROL_MESSAGE_BYTES {
        return Err(ControlProtocolError::MessageTooLarge {
            size: raw.len(),
            max: MAX_CONTROL_MESSAGE_BYTES,
        });
    }
    let value: serde_json::Value = serde_json::from_slice(raw)
        .map_err(|err| ControlProtocolError::InvalidJson(err.to_string()))?;
    let msg_type = value
        .get("msg_type")
        .and_then(|value| value.as_str())
        .ok_or_else(|| ControlProtocolError::UnexpectedMessageType {
            expected: "runtime_control|runtime_engine_edit",
            actual: "<missing>".to_string(),
        })?;
    match msg_type {
        "runtime_control" => {
            let command: RuntimeControlCommand = serde_json::from_value(value)
                .map_err(|err| ControlProtocolError::InvalidJson(err.to_string()))?;
            command.validate()?;
            Ok(RuntimeControlInbound::Control(command))
        }
        "runtime_engine_edit" => {
            let command: RuntimeEngineEditCommand = serde_json::from_value(value)
                .map_err(|err| ControlProtocolError::InvalidJson(err.to_string()))?;
            command.validate()?;
            Ok(RuntimeControlInbound::EngineEdit(command))
        }
        other => Err(ControlProtocolError::UnexpectedMessageType {
            expected: "runtime_control|runtime_engine_edit",
            actual: other.to_string(),
        }),
    }
}

pub fn write_control_message<W: Write, T: Serialize>(
    writer: &mut W,
    msg: &T,
) -> std::io::Result<usize> {
    let json = serde_json::to_vec(msg)
        .map_err(|err| std::io::Error::new(std::io::ErrorKind::InvalidData, err))?;
    if json.len() > MAX_CONTROL_MESSAGE_BYTES {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            format!(
                "control message too large: {} bytes (max {})",
                json.len(),
                MAX_CONTROL_MESSAGE_BYTES
            ),
        ));
    }
    writer.write_all(&(json.len() as u32).to_le_bytes())?;
    writer.write_all(&json)?;
    writer.flush()?;
    Ok(json.len())
}

pub fn read_control_message<R: Read>(reader: &mut R) -> std::io::Result<Option<Vec<u8>>> {
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
            "zero-length control frame",
        ));
    }
    if len > MAX_CONTROL_MESSAGE_BYTES {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            format!(
                "control message too large: {} bytes (max {})",
                len, MAX_CONTROL_MESSAGE_BYTES
            ),
        ));
    }
    let mut buf = vec![0u8; len];
    reader.read_exact(&mut buf)?;
    Ok(Some(buf))
}

#[cfg(test)]
mod tests {
    use std::io::Cursor;

    use super::*;

    #[test]
    fn command_round_trips_through_frame() {
        let command = RuntimeControlCommand {
            msg_type: "runtime_control".to_string(),
            protocol_version: CONTROL_PROTOCOL_VERSION,
            request_id: "abc".to_string(),
            action: RuntimeControlAction::Pause,
            session_id: "s".to_string(),
            tick: Some(4),
            cgs_hash: String::new(),
            schema_version: String::new(),
            execution_plan_version: String::new(),
        };
        let mut buf = Cursor::new(Vec::new());
        write_control_message(&mut buf, &command).unwrap();
        buf.set_position(0);
        let raw = read_control_message(&mut buf).unwrap().unwrap();
        let RuntimeControlInbound::Control(decoded) = parse_control_request(&raw).unwrap() else {
            panic!("expected control command");
        };
        assert_eq!(decoded.action, RuntimeControlAction::Pause);
    }

    #[test]
    fn rejects_wrong_msg_type() {
        let raw = br#"{"msg_type":"bad","protocol_version":1,"request_id":"x","action":"play"}"#;
        assert!(parse_control_request(raw).is_err());
    }

    #[test]
    fn reload_cgs_accepts_version_id_fields() {
        let raw = br#"{"msg_type":"runtime_control","protocol_version":1,"request_id":"x","action":"reload_cgs","cgs_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","schema_version":"0.1.0","execution_plan_version":"1"}"#;
        let RuntimeControlInbound::Control(command) = parse_control_request(raw).unwrap() else {
            panic!("expected control command");
        };
        assert_eq!(command.action, RuntimeControlAction::ReloadCgs);
        assert_eq!(command.cgs_hash.len(), 64);
        assert_eq!(command.schema_version, "0.1.0");
        assert_eq!(command.execution_plan_version, "1");
    }

    #[test]
    fn engine_edit_round_trips() {
        let raw = br#"{"msg_type":"runtime_engine_edit","protocol_version":1,"request_id":"x","kind":"set_component_field","entity_id":7,"component_type_id":1,"field_path":"position.x","value":3.5}"#;
        let RuntimeControlInbound::EngineEdit(edit) = parse_control_request(raw).unwrap() else {
            panic!("expected engine edit");
        };
        assert_eq!(edit.kind, RuntimeEngineEditKind::SetComponentField);
        assert_eq!(edit.component_type_id, Some(1));
    }

    #[test]
    fn set_component_field_requires_component_field_and_primitive_value() {
        let missing_component = br#"{"msg_type":"runtime_engine_edit","protocol_version":1,"request_id":"x","kind":"set_component_field","entity_id":7,"field_path":"position.x","value":3.5}"#;
        assert!(parse_control_request(missing_component).is_err());

        let bad_path = br#"{"msg_type":"runtime_engine_edit","protocol_version":1,"request_id":"x","kind":"set_component_field","entity_id":7,"component_type_id":1,"field_path":"position..x","value":3.5}"#;
        assert!(parse_control_request(bad_path).is_err());

        let complex_value = br#"{"msg_type":"runtime_engine_edit","protocol_version":1,"request_id":"x","kind":"set_component_field","entity_id":7,"component_type_id":1,"field_path":"position.x","value":{"x":1}}"#;
        assert!(parse_control_request(complex_value).is_err());
    }
}
