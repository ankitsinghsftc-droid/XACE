//! Version and session negotiation for runtime/engine adapter connections.
//!
//! The handshake runs before simulation traffic. It verifies the wire protocol,
//! CGS schema version, execution plan version, and world id while returning a
//! precise accept/reject frame the adapter can surface to engine tooling.

use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::wire::message_type::MessageType;
use xace_core::wire::wire_message::{WireMessage, XACE_PROTOCOL_VERSION};

use crate::transport::message_deserializer::MessageDeserializer;
use crate::transport::message_serializer::MessageSerializer;

const XACE_VERSION: &str = env!("CARGO_PKG_VERSION");

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum HandshakeControlType {
    Hello,
    Ack,
    Reject,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct HandshakeHello {
    pub control_type: HandshakeControlType,
    pub protocol_version: u32,
    pub schema_version: String,
    pub execution_plan_version: u32,
    pub world_id: String,
    pub engine_name: String,
    pub adapter_version: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct HandshakeAck {
    pub control_type: HandshakeControlType,
    pub protocol_version: u32,
    pub schema_version: String,
    pub execution_plan_version: u32,
    pub world_id: String,
    pub initial_delta_sequence_id: u64,
    pub xace_version: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum RejectReason {
    ProtocolVersionMismatch,
    SchemaVersionMismatch,
    ExecutionPlanVersionMismatch,
    WorldIdMismatch,
    UnexpectedMessageType,
    MalformedPayload,
}

impl std::fmt::Display for RejectReason {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::ProtocolVersionMismatch => f.write_str("PROTOCOL_VERSION_MISMATCH"),
            Self::SchemaVersionMismatch => f.write_str("SCHEMA_VERSION_MISMATCH"),
            Self::ExecutionPlanVersionMismatch => f.write_str("EXECUTION_PLAN_VERSION_MISMATCH"),
            Self::WorldIdMismatch => f.write_str("WORLD_ID_MISMATCH"),
            Self::UnexpectedMessageType => f.write_str("UNEXPECTED_MESSAGE_TYPE"),
            Self::MalformedPayload => f.write_str("MALFORMED_PAYLOAD"),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct HandshakeReject {
    pub control_type: HandshakeControlType,
    pub reason: RejectReason,
    pub detail: String,
    pub expected_protocol_version: u32,
    pub expected_schema_version: String,
    pub expected_execution_plan_version: u32,
    pub expected_world_id: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HandshakeState {
    AwaitingHello,
    Completed,
    Rejected,
}

impl std::fmt::Display for HandshakeState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::AwaitingHello => f.write_str("AWAITING_HELLO"),
            Self::Completed => f.write_str("COMPLETED"),
            Self::Rejected => f.write_str("REJECTED"),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HandshakeResult {
    Accepted {
        engine_name: String,
        adapter_version: String,
        initial_delta_sequence_id: u64,
        schema_version: String,
        execution_plan_version: u32,
        world_id: String,
        handshake_duration: Duration,
    },
    Rejected {
        reason: RejectReason,
        detail: String,
    },
}

impl HandshakeResult {
    pub fn is_accepted(&self) -> bool {
        matches!(self, Self::Accepted { .. })
    }

    pub fn engine_name(&self) -> Option<&str> {
        match self {
            Self::Accepted { engine_name, .. } => Some(engine_name),
            Self::Rejected { .. } => None,
        }
    }

    pub fn reject_reason(&self) -> Option<&RejectReason> {
        match self {
            Self::Rejected { reason, .. } => Some(reason),
            Self::Accepted { .. } => None,
        }
    }
}

pub struct ProtocolHandshake {
    expected_schema_version: String,
    expected_execution_plan_version: u32,
    expected_world_id: String,
    initial_delta_sequence_id: u64,
    state: HandshakeState,
    result: Option<HandshakeResult>,
    started_at: Instant,
    serializer: MessageSerializer,
}

impl ProtocolHandshake {
    pub fn new_server(
        schema_version: impl Into<String>,
        execution_plan_version: u32,
        world_id: impl Into<String>,
        initial_delta_sequence_id: u64,
    ) -> Self {
        Self {
            expected_schema_version: schema_version.into(),
            expected_execution_plan_version: execution_plan_version,
            expected_world_id: world_id.into(),
            initial_delta_sequence_id,
            state: HandshakeState::AwaitingHello,
            result: None,
            started_at: Instant::now(),
            serializer: MessageSerializer::new(),
        }
    }

    pub fn process_hello_frame(&mut self, frame_bytes: &[u8]) -> Result<Vec<u8>, XaceError> {
        if self.state != HandshakeState::AwaitingHello {
            return self.reject_and_build_frame(
                RejectReason::UnexpectedMessageType,
                format!("handshake already finished with state {}", self.state),
            );
        }

        let msg = self.deserialize_frame(frame_bytes)?;
        if msg.message_type != MessageType::Control {
            return self.reject_and_build_frame(
                RejectReason::UnexpectedMessageType,
                format!(
                    "expected CONTROL message for handshake, received {}",
                    msg.message_type
                ),
            );
        }

        let hello = match serde_json::from_str::<HandshakeHello>(&msg.payload) {
            Ok(hello) => hello,
            Err(err) => {
                return self.reject_and_build_frame(
                    RejectReason::MalformedPayload,
                    format!("handshake payload is not a valid Hello: {}", err),
                );
            }
        };

        if hello.control_type != HandshakeControlType::Hello {
            return self.reject_and_build_frame(
                RejectReason::UnexpectedMessageType,
                format!(
                    "expected Hello control_type, received {:?}",
                    hello.control_type
                ),
            );
        }

        if hello.protocol_version != XACE_PROTOCOL_VERSION {
            return self.reject_and_build_frame(
                RejectReason::ProtocolVersionMismatch,
                format!(
                    "protocol version mismatch: expected {}, received {}",
                    XACE_PROTOCOL_VERSION, hello.protocol_version
                ),
            );
        }
        if hello.schema_version != self.expected_schema_version {
            return self.reject_and_build_frame(
                RejectReason::SchemaVersionMismatch,
                format!(
                    "schema version mismatch: expected {}, received {}",
                    self.expected_schema_version, hello.schema_version
                ),
            );
        }
        if hello.execution_plan_version != self.expected_execution_plan_version {
            return self.reject_and_build_frame(
                RejectReason::ExecutionPlanVersionMismatch,
                format!(
                    "execution plan version mismatch: expected {}, received {}",
                    self.expected_execution_plan_version, hello.execution_plan_version
                ),
            );
        }
        if hello.world_id != self.expected_world_id {
            return self.reject_and_build_frame(
                RejectReason::WorldIdMismatch,
                format!(
                    "world id mismatch: expected {}, received {}",
                    self.expected_world_id, hello.world_id
                ),
            );
        }
        if hello.engine_name.trim().is_empty() || hello.adapter_version.trim().is_empty() {
            return self.reject_and_build_frame(
                RejectReason::MalformedPayload,
                "engine_name and adapter_version must not be empty".to_string(),
            );
        }

        let duration = self.started_at.elapsed();
        self.state = HandshakeState::Completed;
        self.result = Some(HandshakeResult::Accepted {
            engine_name: hello.engine_name.clone(),
            adapter_version: hello.adapter_version.clone(),
            initial_delta_sequence_id: self.initial_delta_sequence_id,
            schema_version: hello.schema_version.clone(),
            execution_plan_version: hello.execution_plan_version,
            world_id: hello.world_id.clone(),
            handshake_duration: duration,
        });
        self.build_ack_frame(&hello)
    }

    pub fn build_hello_frame(
        schema_version: impl Into<String>,
        execution_plan_version: u32,
        world_id: impl Into<String>,
        engine_name: impl Into<String>,
        adapter_version: impl Into<String>,
    ) -> Result<Vec<u8>, XaceError> {
        Self::build_hello_frame_with_protocol(
            XACE_PROTOCOL_VERSION,
            schema_version,
            execution_plan_version,
            world_id,
            engine_name,
            adapter_version,
        )
    }

    pub fn build_hello_frame_with_protocol(
        protocol_version: u32,
        schema_version: impl Into<String>,
        execution_plan_version: u32,
        world_id: impl Into<String>,
        engine_name: impl Into<String>,
        adapter_version: impl Into<String>,
    ) -> Result<Vec<u8>, XaceError> {
        let schema_version = schema_version.into();
        let world_id = world_id.into();
        let hello = HandshakeHello {
            control_type: HandshakeControlType::Hello,
            protocol_version,
            schema_version: schema_version.clone(),
            execution_plan_version,
            world_id: world_id.clone(),
            engine_name: engine_name.into(),
            adapter_version: adapter_version.into(),
        };
        let payload = serde_json::to_string(&hello).map_err(|err| {
            Self::fatal(
                "build_hello_frame",
                format!("failed to serialize HandshakeHello: {}", err),
            )
        })?;
        let msg =
            WireMessage::control(world_id, schema_version, execution_plan_version, 0, payload);
        MessageSerializer::new().serialize(&msg)
    }

    pub fn parse_response_frame(frame_bytes: &[u8]) -> Result<HandshakeResult, XaceError> {
        let mut deserializer = MessageDeserializer::new();
        let msg = deserializer.deserialize_frame(frame_bytes)?;
        if msg.message_type != MessageType::Control {
            return Err(Self::recoverable(
                "parse_response_frame",
                format!(
                    "expected CONTROL handshake response, received {}",
                    msg.message_type
                ),
            ));
        }

        let control_type = control_type_from_payload(&msg.payload).map_err(|err| {
            Self::recoverable(
                "parse_response_frame",
                format!("handshake response payload missing control_type: {}", err),
            )
        })?;

        match control_type {
            HandshakeControlType::Ack => {
                let ack: HandshakeAck = serde_json::from_str(&msg.payload).map_err(|err| {
                    Self::recoverable(
                        "parse_response_frame",
                        format!("failed to parse HandshakeAck: {}", err),
                    )
                })?;
                Ok(HandshakeResult::Accepted {
                    engine_name: "xace-runtime".to_string(),
                    adapter_version: ack.xace_version,
                    initial_delta_sequence_id: ack.initial_delta_sequence_id,
                    schema_version: ack.schema_version,
                    execution_plan_version: ack.execution_plan_version,
                    world_id: ack.world_id,
                    handshake_duration: Duration::ZERO,
                })
            }
            HandshakeControlType::Reject => {
                let reject: HandshakeReject =
                    serde_json::from_str(&msg.payload).map_err(|err| {
                        Self::recoverable(
                            "parse_response_frame",
                            format!("failed to parse HandshakeReject: {}", err),
                        )
                    })?;
                Ok(HandshakeResult::Rejected {
                    reason: reject.reason,
                    detail: reject.detail,
                })
            }
            HandshakeControlType::Hello => Err(Self::recoverable(
                "parse_response_frame",
                "received Hello where Ack or Reject was expected",
            )),
        }
    }

    pub fn state(&self) -> HandshakeState {
        self.state
    }

    pub fn result(&self) -> Option<&HandshakeResult> {
        self.result.as_ref()
    }

    pub fn is_accepted(&self) -> bool {
        self.state == HandshakeState::Completed
    }

    pub fn is_rejected(&self) -> bool {
        self.state == HandshakeState::Rejected
    }

    pub fn elapsed(&self) -> Duration {
        self.started_at.elapsed()
    }

    fn deserialize_frame(&self, frame_bytes: &[u8]) -> Result<WireMessage, XaceError> {
        MessageDeserializer::new().deserialize_frame(frame_bytes)
    }

    fn reject_and_build_frame(
        &mut self,
        reason: RejectReason,
        detail: String,
    ) -> Result<Vec<u8>, XaceError> {
        self.state = HandshakeState::Rejected;
        self.result = Some(HandshakeResult::Rejected {
            reason: reason.clone(),
            detail: detail.clone(),
        });

        let reject = HandshakeReject {
            control_type: HandshakeControlType::Reject,
            reason,
            detail,
            expected_protocol_version: XACE_PROTOCOL_VERSION,
            expected_schema_version: self.expected_schema_version.clone(),
            expected_execution_plan_version: self.expected_execution_plan_version,
            expected_world_id: self.expected_world_id.clone(),
        };
        let payload = serde_json::to_string(&reject).map_err(|err| {
            Self::fatal(
                "reject_and_build_frame",
                format!("failed to serialize HandshakeReject: {}", err),
            )
        })?;
        let msg = WireMessage::control(
            self.expected_world_id.clone(),
            self.expected_schema_version.clone(),
            self.expected_execution_plan_version,
            1,
            payload,
        );
        self.serializer.serialize(&msg)
    }

    fn build_ack_frame(&mut self, hello: &HandshakeHello) -> Result<Vec<u8>, XaceError> {
        let ack = HandshakeAck {
            control_type: HandshakeControlType::Ack,
            protocol_version: XACE_PROTOCOL_VERSION,
            schema_version: hello.schema_version.clone(),
            execution_plan_version: hello.execution_plan_version,
            world_id: hello.world_id.clone(),
            initial_delta_sequence_id: self.initial_delta_sequence_id,
            xace_version: XACE_VERSION.to_string(),
        };
        let payload = serde_json::to_string(&ack).map_err(|err| {
            Self::fatal(
                "build_ack_frame",
                format!("failed to serialize HandshakeAck: {}", err),
            )
        })?;
        let msg = WireMessage::control(
            hello.world_id.clone(),
            hello.schema_version.clone(),
            hello.execution_plan_version,
            1,
            payload,
        );
        self.serializer.serialize(&msg)
    }

    fn recoverable(operation: &'static str, message: impl Into<String>) -> XaceError {
        XaceError::RecoverableError {
            message: format!("ProtocolHandshake: {}", message.into()),
            context: ErrorContext::new("ProtocolHandshake", operation),
            max_retries: 0,
            retry_count: 0,
        }
    }

    fn fatal(operation: &'static str, message: impl Into<String>) -> XaceError {
        XaceError::FatalError {
            message: format!("ProtocolHandshake: {}", message.into()),
            context: ErrorContext::new("ProtocolHandshake", operation),
            snapshot_recovery_possible: false,
        }
    }
}

fn control_type_from_payload(payload: &str) -> Result<HandshakeControlType, serde_json::Error> {
    #[derive(Deserialize)]
    struct ControlProbe {
        control_type: HandshakeControlType,
    }

    serde_json::from_str::<ControlProbe>(payload).map(|probe| probe.control_type)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn server() -> ProtocolHandshake {
        ProtocolHandshake::new_server("0.1.0", 1, "default", 7)
    }

    fn hello_frame(schema: &str, plan: u32, world_id: &str) -> Vec<u8> {
        ProtocolHandshake::build_hello_frame(schema, plan, world_id, "Godot-4", "1.0.0").unwrap()
    }

    #[test]
    fn valid_hello_completes_and_returns_ack() {
        let mut server = server();
        let ack = server
            .process_hello_frame(&hello_frame("0.1.0", 1, "default"))
            .unwrap();

        assert_eq!(server.state(), HandshakeState::Completed);
        assert!(server.is_accepted());
        assert!(!ack.is_empty());

        let parsed = ProtocolHandshake::parse_response_frame(&ack).unwrap();
        assert!(parsed.is_accepted());
        assert!(matches!(
            parsed,
            HandshakeResult::Accepted {
                initial_delta_sequence_id: 7,
                ..
            }
        ));
    }

    #[test]
    fn accepted_result_keeps_adapter_metadata() {
        let mut server = server();
        server
            .process_hello_frame(&hello_frame("0.1.0", 1, "default"))
            .unwrap();

        assert_eq!(server.result().unwrap().engine_name(), Some("Godot-4"));
    }

    #[test]
    fn schema_mismatch_rejects_with_specific_reason() {
        let mut server = server();
        let reject = server
            .process_hello_frame(&hello_frame("9.9.9", 1, "default"))
            .unwrap();

        assert_eq!(server.state(), HandshakeState::Rejected);
        let parsed = ProtocolHandshake::parse_response_frame(&reject).unwrap();
        assert_eq!(
            parsed.reject_reason(),
            Some(&RejectReason::SchemaVersionMismatch)
        );
    }

    #[test]
    fn plan_mismatch_rejects_with_specific_reason() {
        let mut server = server();
        let reject = server
            .process_hello_frame(&hello_frame("0.1.0", 2, "default"))
            .unwrap();

        let parsed = ProtocolHandshake::parse_response_frame(&reject).unwrap();
        assert_eq!(
            parsed.reject_reason(),
            Some(&RejectReason::ExecutionPlanVersionMismatch)
        );
    }

    #[test]
    fn world_mismatch_rejects_with_specific_reason() {
        let mut server = server();
        let reject = server
            .process_hello_frame(&hello_frame("0.1.0", 1, "wrong"))
            .unwrap();

        let parsed = ProtocolHandshake::parse_response_frame(&reject).unwrap();
        assert_eq!(parsed.reject_reason(), Some(&RejectReason::WorldIdMismatch));
    }

    #[test]
    fn payload_protocol_mismatch_rejects() {
        let mut server = server();
        let hello = ProtocolHandshake::build_hello_frame_with_protocol(
            XACE_PROTOCOL_VERSION + 1,
            "0.1.0",
            1,
            "default",
            "Unity",
            "1.0.0",
        )
        .unwrap();

        let reject = server.process_hello_frame(&hello).unwrap();
        let parsed = ProtocolHandshake::parse_response_frame(&reject).unwrap();
        assert_eq!(
            parsed.reject_reason(),
            Some(&RejectReason::ProtocolVersionMismatch)
        );
    }

    #[test]
    fn malformed_payload_gets_reject_frame() {
        let msg = WireMessage::control("default", "0.1.0", 1, 0, r#"{"not":"hello"}"#);
        let frame = MessageSerializer::new().serialize(&msg).unwrap();

        let mut server = server();
        let reject = server.process_hello_frame(&frame).unwrap();
        let parsed = ProtocolHandshake::parse_response_frame(&reject).unwrap();

        assert_eq!(
            parsed.reject_reason(),
            Some(&RejectReason::MalformedPayload)
        );
    }

    #[test]
    fn non_control_message_gets_reject_frame() {
        let msg = WireMessage::delta("default", "0.1.0", 1, 1, 1, "{}");
        let frame = MessageSerializer::new().serialize(&msg).unwrap();

        let mut server = server();
        let reject = server.process_hello_frame(&frame).unwrap();
        let parsed = ProtocolHandshake::parse_response_frame(&reject).unwrap();

        assert_eq!(
            parsed.reject_reason(),
            Some(&RejectReason::UnexpectedMessageType)
        );
    }

    #[test]
    fn truncated_frame_returns_error_not_reject() {
        let mut server = server();
        assert!(server.process_hello_frame(&[0, 0, 0]).is_err());
        assert_eq!(server.state(), HandshakeState::AwaitingHello);
    }

    #[test]
    fn reject_frame_carries_expected_versions() {
        let mut server = ProtocolHandshake::new_server("0.2.0", 5, "world", 1);
        let reject_frame = server
            .process_hello_frame(&hello_frame("0.1.0", 5, "world"))
            .unwrap();

        let mut deserializer = MessageDeserializer::new();
        let msg = deserializer.deserialize_frame(&reject_frame).unwrap();
        let reject: HandshakeReject = serde_json::from_str(&msg.payload).unwrap();

        assert_eq!(reject.expected_protocol_version, XACE_PROTOCOL_VERSION);
        assert_eq!(reject.expected_schema_version, "0.2.0");
        assert_eq!(reject.expected_execution_plan_version, 5);
        assert_eq!(reject.expected_world_id, "world");
    }

    #[test]
    fn elapsed_reports_duration() {
        let server = server();
        std::thread::sleep(Duration::from_millis(2));
        assert!(server.elapsed() >= Duration::from_millis(1));
    }
}
