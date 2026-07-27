//! Canonical wire envelope for runtime-to-engine communication.
//!
//! The envelope is intentionally small and stable. The `payload` field remains
//! a JSON string so Unity, Unreal, Godot, Python tooling, and Rust transports can
//! all share the same frame contract. Typed helpers are provided for Rust code
//! so callers do not need to hand-roll JSON serialization at every call site.

use serde::{de::DeserializeOwned, Deserialize, Serialize};

use crate::entity_metadata::Tick;
use crate::wire::message_type::{MessageDirection, MessageType};

/// Current incompatible wire envelope version.
pub const XACE_PROTOCOL_VERSION: u32 = 1;

/// Single-world default session identifier.
pub const DEFAULT_WORLD_ID: &str = "default";

/// Conservative limit for the JSON payload string inside a `WireMessage`.
///
/// Transports have their own framed-message limits; this envelope limit catches
/// obviously invalid messages before transport serialization.
pub const MAX_WIRE_PAYLOAD_BYTES: usize = 16 * 1024 * 1024;

/// Envelope validation failures with stable, human-readable diagnostics.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WireMessageValidationError {
    ProtocolVersionMismatch {
        found: u32,
        expected: u32,
    },
    EmptyWorldId,
    EmptySchemaVersion,
    ZeroExecutionPlanVersion,
    EmptyPayload {
        message_type: MessageType,
    },
    OversizedPayload {
        actual: usize,
        max: usize,
    },
    PayloadIsNotJson {
        detail: String,
    },
    InputTickIsZero,
    IllegalDirection {
        message_type: MessageType,
        attempted_direction: MessageDirection,
    },
}

impl std::fmt::Display for WireMessageValidationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::ProtocolVersionMismatch { found, expected } => {
                write!(
                    f,
                    "protocol version mismatch: found {}, expected {}",
                    found, expected
                )
            }
            Self::EmptyWorldId => f.write_str("world_id must not be empty"),
            Self::EmptySchemaVersion => f.write_str("schema_version must not be empty"),
            Self::ZeroExecutionPlanVersion => {
                f.write_str("execution_plan_version must be greater than zero")
            }
            Self::EmptyPayload { message_type } => {
                write!(f, "{} payload must not be empty", message_type)
            }
            Self::OversizedPayload { actual, max } => {
                write!(f, "payload is {} bytes, max is {} bytes", actual, max)
            }
            Self::PayloadIsNotJson { detail } => write!(f, "payload is not valid JSON: {}", detail),
            Self::InputTickIsZero => f.write_str("INPUT messages must carry a non-zero tick"),
            Self::IllegalDirection {
                message_type,
                attempted_direction,
            } => write!(
                f,
                "{} is not legal in {} direction",
                message_type, attempted_direction
            ),
        }
    }
}

impl std::error::Error for WireMessageValidationError {}

/// The envelope for every message crossing the runtime/engine boundary.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WireMessage {
    pub protocol_version: u32,
    pub world_id: String,
    pub schema_version: String,
    pub execution_plan_version: u32,
    pub tick: Tick,
    pub sequence_id: u64,
    pub message_type: MessageType,
    pub payload: String,
}

impl WireMessage {
    pub fn new(
        world_id: impl Into<String>,
        schema_version: impl Into<String>,
        execution_plan_version: u32,
        tick: Tick,
        sequence_id: u64,
        message_type: MessageType,
        payload: impl Into<String>,
    ) -> Self {
        Self {
            protocol_version: XACE_PROTOCOL_VERSION,
            world_id: world_id.into(),
            schema_version: schema_version.into(),
            execution_plan_version,
            tick,
            sequence_id,
            message_type,
            payload: payload.into(),
        }
    }

    /// Builds a message by serializing a typed payload into canonical JSON.
    pub fn with_typed_payload<T: Serialize>(
        world_id: impl Into<String>,
        schema_version: impl Into<String>,
        execution_plan_version: u32,
        tick: Tick,
        sequence_id: u64,
        message_type: MessageType,
        payload: &T,
    ) -> Result<Self, serde_json::Error> {
        let payload_json = serde_json::to_string(payload)?;
        Ok(Self::new(
            world_id,
            schema_version,
            execution_plan_version,
            tick,
            sequence_id,
            message_type,
            payload_json,
        ))
    }

    pub fn snapshot(
        world_id: impl Into<String>,
        schema_version: impl Into<String>,
        execution_plan_version: u32,
        tick: Tick,
        sequence_id: u64,
        payload_json: impl Into<String>,
    ) -> Self {
        Self::new(
            world_id,
            schema_version,
            execution_plan_version,
            tick,
            sequence_id,
            MessageType::Snapshot,
            payload_json,
        )
    }

    pub fn delta(
        world_id: impl Into<String>,
        schema_version: impl Into<String>,
        execution_plan_version: u32,
        tick: Tick,
        sequence_id: u64,
        payload_json: impl Into<String>,
    ) -> Self {
        Self::new(
            world_id,
            schema_version,
            execution_plan_version,
            tick,
            sequence_id,
            MessageType::Delta,
            payload_json,
        )
    }

    pub fn input(
        world_id: impl Into<String>,
        schema_version: impl Into<String>,
        execution_plan_version: u32,
        tick: Tick,
        sequence_id: u64,
        payload_json: impl Into<String>,
    ) -> Self {
        Self::new(
            world_id,
            schema_version,
            execution_plan_version,
            tick,
            sequence_id,
            MessageType::Input,
            payload_json,
        )
    }

    pub fn event(
        world_id: impl Into<String>,
        schema_version: impl Into<String>,
        execution_plan_version: u32,
        tick: Tick,
        sequence_id: u64,
        payload_json: impl Into<String>,
    ) -> Self {
        Self::new(
            world_id,
            schema_version,
            execution_plan_version,
            tick,
            sequence_id,
            MessageType::Event,
            payload_json,
        )
    }

    pub fn feedback(
        world_id: impl Into<String>,
        schema_version: impl Into<String>,
        execution_plan_version: u32,
        tick: Tick,
        sequence_id: u64,
        payload_json: impl Into<String>,
    ) -> Self {
        Self::new(
            world_id,
            schema_version,
            execution_plan_version,
            tick,
            sequence_id,
            MessageType::Feedback,
            payload_json,
        )
    }

    /// Control messages are not tied to simulation ticks.
    pub fn control(
        world_id: impl Into<String>,
        schema_version: impl Into<String>,
        execution_plan_version: u32,
        sequence_id: u64,
        payload_json: impl Into<String>,
    ) -> Self {
        Self::new(
            world_id,
            schema_version,
            execution_plan_version,
            0,
            sequence_id,
            MessageType::Control,
            payload_json,
        )
    }

    pub fn is_protocol_compatible(&self) -> bool {
        self.protocol_version == XACE_PROTOCOL_VERSION
    }

    pub fn is_version_compatible(&self, expected_schema: &str, expected_plan_version: u32) -> bool {
        self.schema_version == expected_schema
            && self.execution_plan_version == expected_plan_version
    }

    pub fn is_snapshot(&self) -> bool {
        self.message_type == MessageType::Snapshot
    }

    pub fn is_delta(&self) -> bool {
        self.message_type == MessageType::Delta
    }

    pub fn is_input(&self) -> bool {
        self.message_type == MessageType::Input
    }

    pub fn is_event(&self) -> bool {
        self.message_type == MessageType::Event
    }

    pub fn is_feedback(&self) -> bool {
        self.message_type == MessageType::Feedback
    }

    pub fn is_control(&self) -> bool {
        self.message_type == MessageType::Control
    }

    /// Runtime-to-engine only. Control is bidirectional, so this returns false
    /// for `Control` to preserve the older API's narrower meaning.
    pub fn is_outbound(&self) -> bool {
        self.message_type.is_xace_to_engine()
    }

    /// Engine-to-runtime only. Control is bidirectional, so this returns false
    /// for `Control` to preserve the older API's narrower meaning.
    pub fn is_inbound(&self) -> bool {
        self.message_type.is_engine_to_xace()
    }

    pub fn direction(&self) -> MessageDirection {
        self.message_type.direction()
    }

    pub fn payload_size_bytes(&self) -> usize {
        self.payload.len()
    }

    pub fn decode_payload<T: DeserializeOwned>(&self) -> Result<T, serde_json::Error> {
        serde_json::from_str(&self.payload)
    }

    pub fn payload_value(&self) -> Result<serde_json::Value, serde_json::Error> {
        self.decode_payload()
    }

    /// Validates envelope invariants and payload JSON shape.
    ///
    /// This preserves the historical `Result<(), String>` signature used by
    /// existing transports. Use `validate_detailed` when callers need a typed
    /// reason.
    pub fn validate(&self) -> Result<(), String> {
        self.validate_detailed().map_err(|err| err.to_string())
    }

    pub fn validate_detailed(&self) -> Result<(), WireMessageValidationError> {
        if self.protocol_version != XACE_PROTOCOL_VERSION {
            return Err(WireMessageValidationError::ProtocolVersionMismatch {
                found: self.protocol_version,
                expected: XACE_PROTOCOL_VERSION,
            });
        }
        if self.world_id.trim().is_empty() {
            return Err(WireMessageValidationError::EmptyWorldId);
        }
        if self.schema_version.trim().is_empty() {
            return Err(WireMessageValidationError::EmptySchemaVersion);
        }
        if self.execution_plan_version == 0 {
            return Err(WireMessageValidationError::ZeroExecutionPlanVersion);
        }
        if self.payload.is_empty() {
            return Err(WireMessageValidationError::EmptyPayload {
                message_type: self.message_type,
            });
        }
        if self.payload.len() > MAX_WIRE_PAYLOAD_BYTES {
            return Err(WireMessageValidationError::OversizedPayload {
                actual: self.payload.len(),
                max: MAX_WIRE_PAYLOAD_BYTES,
            });
        }
        serde_json::from_str::<serde_json::Value>(&self.payload).map_err(|err| {
            WireMessageValidationError::PayloadIsNotJson {
                detail: err.to_string(),
            }
        })?;
        if self.message_type == MessageType::Input && self.tick == 0 {
            return Err(WireMessageValidationError::InputTickIsZero);
        }
        Ok(())
    }

    pub fn validate_direction(
        &self,
        attempted_direction: MessageDirection,
    ) -> Result<(), WireMessageValidationError> {
        self.validate_detailed()?;
        if !self.message_type.can_flow(attempted_direction) {
            return Err(WireMessageValidationError::IllegalDirection {
                message_type: self.message_type,
                attempted_direction,
            });
        }
        Ok(())
    }
}

impl std::fmt::Display for WireMessage {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "WireMessage[v{} type={} world={} tick={} seq={} schema={} plan={} payload={}B]",
            self.protocol_version,
            self.message_type,
            self.world_id,
            self.tick,
            self.sequence_id,
            self.schema_version,
            self.execution_plan_version,
            self.payload.len()
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn test_message() -> WireMessage {
        WireMessage::delta(
            DEFAULT_WORLD_ID,
            "0.1.0",
            1,
            42,
            100,
            r#"{"sequence_id":100,"tick":42}"#,
        )
    }

    #[test]
    fn constructors_set_type_and_protocol() {
        let msg = test_message();
        assert_eq!(msg.protocol_version, XACE_PROTOCOL_VERSION);
        assert!(msg.is_delta());
        assert!(msg.is_outbound());
        assert!(!msg.is_inbound());

        let control = WireMessage::control(DEFAULT_WORLD_ID, "0.1.0", 1, 1, r#"{"kind":"ping"}"#);
        assert!(control.is_control());
        assert_eq!(control.tick, 0);
        assert!(!control.is_outbound());
        assert!(!control.is_inbound());
    }

    #[test]
    fn typed_payload_roundtrip_works() {
        let payload = json!({"move_x":1.0,"move_z":0.0});
        let msg = WireMessage::with_typed_payload(
            DEFAULT_WORLD_ID,
            "0.1.0",
            1,
            5,
            7,
            MessageType::Input,
            &payload,
        )
        .unwrap();
        assert!(msg.is_input());
        assert_eq!(msg.payload_value().unwrap()["move_x"], 1.0);
        assert!(msg.validate().is_ok());
    }

    #[test]
    fn validate_checks_core_invariants() {
        assert!(test_message().validate().is_ok());

        let mut bad = test_message();
        bad.protocol_version = 999;
        assert!(matches!(
            bad.validate_detailed(),
            Err(WireMessageValidationError::ProtocolVersionMismatch { .. })
        ));

        let mut bad = test_message();
        bad.payload = "not json".into();
        assert!(matches!(
            bad.validate_detailed(),
            Err(WireMessageValidationError::PayloadIsNotJson { .. })
        ));

        let bad = WireMessage::input(DEFAULT_WORLD_ID, "0.1.0", 1, 0, 1, "{}");
        assert!(matches!(
            bad.validate_detailed(),
            Err(WireMessageValidationError::InputTickIsZero)
        ));
    }

    #[test]
    fn direction_validation_allows_control_both_ways() {
        let delta = test_message();
        assert!(delta
            .validate_direction(MessageDirection::XaceToEngine)
            .is_ok());
        assert!(matches!(
            delta.validate_direction(MessageDirection::EngineToXace),
            Err(WireMessageValidationError::IllegalDirection { .. })
        ));

        let control = WireMessage::control(DEFAULT_WORLD_ID, "0.1.0", 1, 1, "{}");
        assert!(control
            .validate_direction(MessageDirection::XaceToEngine)
            .is_ok());
        assert!(control
            .validate_direction(MessageDirection::EngineToXace)
            .is_ok());
    }

    #[test]
    fn version_compatibility_is_explicit() {
        let msg = test_message();
        assert!(msg.is_protocol_compatible());
        assert!(msg.is_version_compatible("0.1.0", 1));
        assert!(!msg.is_version_compatible("0.2.0", 1));
        assert!(!msg.is_version_compatible("0.1.0", 2));
    }

    #[test]
    fn display_contains_operational_fields() {
        let rendered = test_message().to_string();
        assert!(rendered.contains("DELTA"));
        assert!(rendered.contains("default"));
        assert!(rendered.contains("tick=42"));
    }
}
