//! # Protocol Handshake
//!
//! Version negotiation between the XACE runtime (server) and an engine
//! adapter (client) before any simulation messages are exchanged.
//!
//! ## Why a Dedicated Handshake
//! Every WireMessage carries three version fields (protocol, schema, plan).
//! Without an explicit handshake, a version mismatch would be discovered
//! silently mid-session — possibly after hundreds of ticks have run —
//! producing a desync that looks like a game bug. The handshake surfaces
//! mismatches immediately, before a single DELTA is sent, with a precise
//! error message naming the offending field and both versions.
//!
//! ## Handshake Sequence
//! ```text
//! Engine Adapter                    XACE Runtime
//!      │                                  │
//!      │──── CONTROL/HandshakeHello ──────▶│  (engine sends first)
//!      │                                  │  validate all 3 version fields
//!      │◀─── CONTROL/HandshakeAck  ───────│  (success)
//!      │         or                       │
//!      │◀─── CONTROL/HandshakeReject ─────│  (version mismatch)
//!      │                                  │
//! ```
//!
//! ## Three Version Fields (D10)
//! All three must match exactly for the handshake to succeed:
//! - `protocol_version`       — wire format version (XACE_PROTOCOL_VERSION)
//! - `schema_version`         — CGS semantic version (e.g. "0.1.0")
//! - `execution_plan_version` — ExecutionPlan version (monotonic u32)
//!
//! Any mismatch produces a `HandshakeReject` with the specific field that
//! failed and both the expected and received values.
//!
//! ## Transport Agnostic
//! The handshake operates on `WireMessage` values, not on raw sockets.
//! The caller (TcpTransport or ShmTransport) reads the first frame,
//! passes it to `ProtocolHandshake::receive_hello()`, and sends back
//! the frame returned by `build_ack()` or `build_reject()`.
//! This makes the handshake testable without a real socket.
//!
//! ## Timeout
//! The handshake does not implement its own timeout — the transport's
//! `accept_timeout` in `TcpTransportConfig` covers the accept phase.
//! If the engine adapter connects but never sends a Hello, the transport
//! will eventually time out at the OS socket level.

use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};

use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::wire::wire_message::{WireMessage, XACE_PROTOCOL_VERSION};
use xace_core::wire::message_type::MessageType;

use crate::transport::message_serializer::MessageSerializer;
use crate::transport::message_deserializer::MessageDeserializer;

// ── Handshake Control Message Type ────────────────────────────────────────────

/// Discriminator embedded in a CONTROL message payload.
///
/// All handshake messages use `MessageType::Control` as the WireMessage
/// envelope type. The `HandshakeControlType` field inside the JSON payload
/// tells the receiver which handshake step this is.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum HandshakeControlType {
    /// Sent by the engine adapter to initiate the handshake.
    Hello,
    /// Sent by XACE to accept the connection.
    Ack,
    /// Sent by XACE to reject the connection with a specific reason.
    Reject,
}

// ── Handshake Hello ───────────────────────────────────────────────────────────

/// The opening message sent by the engine adapter.
///
/// Contains all three version fields plus adapter metadata.
/// XACE validates every field and responds with Ack or Reject.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HandshakeHello {
    pub control_type: HandshakeControlType,

    /// Must match `XACE_PROTOCOL_VERSION` exactly.
    pub protocol_version: u32,

    /// Must match the CGS schema version active in this XACE session.
    pub schema_version: String,

    /// Must match the ExecutionPlan version active in this XACE session.
    pub execution_plan_version: u32,

    /// The world session ID the adapter wants to connect to.
    /// Must match the XACE session's world_id.
    pub world_id: String,

    /// Human-readable name of the engine adapter (e.g. "Unity-2022", "Godot-4").
    /// Informational — used for logging, not validation.
    pub engine_name: String,

    /// Semantic version of the engine adapter client library.
    /// Informational — used for debugging mismatches.
    pub adapter_version: String,
}

// ── Handshake Ack ─────────────────────────────────────────────────────────────

/// Sent by XACE on successful handshake.
///
/// Echoes back the agreed version triple so the adapter can confirm
/// it received the correct Ack and not a replay of a stale packet.
/// Also carries the initial DELTA sequence_id the adapter should
/// expect as the first DELTA message.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HandshakeAck {
    pub control_type: HandshakeControlType,

    /// Echoed protocol_version — must match what the adapter sent.
    pub protocol_version: u32,

    /// Echoed schema_version.
    pub schema_version: String,

    /// Echoed execution_plan_version.
    pub execution_plan_version: u32,

    /// Echoed world_id.
    pub world_id: String,

    /// The first DELTA message will carry this sequence_id.
    /// The adapter initialises its sequence tracker to this value.
    pub initial_delta_sequence_id: u64,

    /// Informational: the XACE server version string.
    pub xace_version: String,
}

// ── Handshake Reject ──────────────────────────────────────────────────────────

/// The reason an incoming HandshakeHello was rejected.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum RejectReason {
    /// Wire protocol version mismatch.
    ProtocolVersionMismatch,
    /// CGS schema version mismatch.
    SchemaVersionMismatch,
    /// ExecutionPlan version mismatch.
    ExecutionPlanVersionMismatch,
    /// world_id does not match the active XACE session.
    WorldIdMismatch,
    /// Message type was not HandshakeHello (wrong control_type).
    UnexpectedMessageType,
    /// JSON payload could not be parsed as a HandshakeHello.
    MalformedPayload,
}

impl std::fmt::Display for RejectReason {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            RejectReason::ProtocolVersionMismatch     => write!(f, "PROTOCOL_VERSION_MISMATCH"),
            RejectReason::SchemaVersionMismatch       => write!(f, "SCHEMA_VERSION_MISMATCH"),
            RejectReason::ExecutionPlanVersionMismatch => write!(f, "EXECUTION_PLAN_VERSION_MISMATCH"),
            RejectReason::WorldIdMismatch             => write!(f, "WORLD_ID_MISMATCH"),
            RejectReason::UnexpectedMessageType       => write!(f, "UNEXPECTED_MESSAGE_TYPE"),
            RejectReason::MalformedPayload            => write!(f, "MALFORMED_PAYLOAD"),
        }
    }
}

/// Sent by XACE when the HandshakeHello fails validation.
///
/// Contains the specific reason and both the expected and received
/// values so the adapter developer can fix the mismatch immediately.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HandshakeReject {
    pub control_type: HandshakeControlType,

    /// Why the handshake was rejected.
    pub reason: RejectReason,

    /// Human-readable explanation including both expected and received values.
    pub detail: String,

    /// The protocol_version XACE expects.
    pub expected_protocol_version: u32,

    /// The schema_version XACE expects.
    pub expected_schema_version: String,

    /// The execution_plan_version XACE expects.
    pub expected_execution_plan_version: u32,

    /// The world_id XACE is running.
    pub expected_world_id: String,
}

// ── Handshake State ───────────────────────────────────────────────────────────

/// The current state of a handshake session.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HandshakeState {
    /// Awaiting the engine adapter's Hello message.
    AwaitingHello,
    /// Hello received and validated successfully. Ack was sent.
    Completed,
    /// Hello received but validation failed. Reject was sent.
    Rejected,
}

impl std::fmt::Display for HandshakeState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            HandshakeState::AwaitingHello => write!(f, "AWAITING_HELLO"),
            HandshakeState::Completed     => write!(f, "COMPLETED"),
            HandshakeState::Rejected      => write!(f, "REJECTED"),
        }
    }
}

// ── Handshake Result ──────────────────────────────────────────────────────────

/// The outcome of a completed handshake on the XACE (server) side.
///
/// On success, contains the validated adapter metadata and the agreed
/// initial_delta_sequence_id. On failure, contains the reject detail.
#[derive(Debug, Clone)]
pub enum HandshakeResult {
    /// Handshake succeeded. Connection is ready for simulation messages.
    Accepted {
        /// The adapter's reported engine name.
        engine_name: String,
        /// The adapter's reported version string.
        adapter_version: String,
        /// The agreed initial DELTA sequence_id.
        initial_delta_sequence_id: u64,
        /// The schema version that was validated.
        schema_version: String,
        /// The execution plan version that was validated.
        execution_plan_version: u32,
        /// Round-trip time of the handshake (Hello received → Ack sent).
        handshake_duration: Duration,
    },
    /// Handshake failed. Connection was rejected.
    Rejected {
        reason: RejectReason,
        detail: String,
    },
}

impl HandshakeResult {
    /// Returns true if the handshake succeeded.
    pub fn is_accepted(&self) -> bool {
        matches!(self, HandshakeResult::Accepted { .. })
    }

    /// Returns the engine name if the handshake succeeded.
    pub fn engine_name(&self) -> Option<&str> {
        match self {
            HandshakeResult::Accepted { engine_name, .. } => Some(engine_name),
            _ => None,
        }
    }

    /// Returns the rejection reason if the handshake failed.
    pub fn reject_reason(&self) -> Option<&RejectReason> {
        match self {
            HandshakeResult::Rejected { reason, .. } => Some(reason),
            _ => None,
        }
    }
}

// ── Protocol Handshake ────────────────────────────────────────────────────────

/// Manages the version-negotiation handshake between XACE and an engine adapter.
///
/// Created once per connection attempt, used for a single handshake,
/// then discarded. The transport layer creates a new instance for each
/// incoming connection.
///
/// ## Server-side usage (XACE)
/// ```ignore
/// let mut handshake = ProtocolHandshake::new_server(
///     "0.1.0", 1, "default", 1,
/// );
/// let hello_bytes = transport.read_next_frame()?;
/// let ack_frame = handshake.process_hello_frame(&hello_bytes)?;
/// transport.send_raw(&ack_frame)?;
/// let result = handshake.result().unwrap();
/// ```
pub struct ProtocolHandshake {
    /// The schema version XACE is running. Validated against Hello.
    expected_schema_version: String,

    /// The ExecutionPlan version XACE is running. Validated against Hello.
    expected_execution_plan_version: u32,

    /// The world_id of the active XACE session. Validated against Hello.
    expected_world_id: String,

    /// The initial DELTA sequence_id to report in the Ack.
    initial_delta_sequence_id: u64,

    /// Current handshake state.
    state: HandshakeState,

    /// The final result — set by process_hello_frame().
    result: Option<HandshakeResult>,

    /// Timestamp when this handshake was created.
    started_at: Instant,

    /// Serializer for building response frames.
    serializer: MessageSerializer,
}

impl ProtocolHandshake {
    // ── Construction ──────────────────────────────────────────────────────────

    /// Creates a new server-side handshake handler.
    ///
    /// - `schema_version`              — must match what the engine adapter sends
    /// - `execution_plan_version`      — must match what the engine adapter sends
    /// - `world_id`                    — must match what the engine adapter sends
    /// - `initial_delta_sequence_id`   — echoed in the Ack so the adapter can
    ///                                   initialise its SequenceTracker
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

    // ── Primary API ───────────────────────────────────────────────────────────

    /// Processes one raw frame received from the engine adapter.
    ///
    /// Deserializes the frame, validates the HandshakeHello, and returns
    /// the complete wire frame that must be sent back to the adapter
    /// (either an Ack frame or a Reject frame).
    ///
    /// After this call:
    /// - `self.state()` reflects the outcome (Completed or Rejected)
    /// - `self.result()` contains the full HandshakeResult
    ///
    /// ## Errors
    /// Returns `Err` only for structural failures (cannot produce a response):
    /// - JSON serialization of the response failed
    ///
    /// Version mismatches are NOT errors here — they produce a Reject frame
    /// that is returned as `Ok(reject_frame)`. The caller sends the reject
    /// frame and then closes the connection.
    pub fn process_hello_frame(
        &mut self,
        frame_bytes: &[u8],
    ) -> Result<Vec<u8>, XaceError> {
        // Deserialize the frame
        let msg = self.deserialize_frame(frame_bytes)?;

        // Validate it is a CONTROL message
        if !matches!(msg.message_type, MessageType::Control) {
            return self.reject_and_build_frame(
                RejectReason::UnexpectedMessageType,
                format!(
                    "Expected CONTROL message for handshake but received {:?}",
                    msg.message_type
                ),
            );
        }

        // Parse the Hello payload
        let hello: HandshakeHello = serde_json::from_str(&msg.payload).map_err(|e| {
            XaceError::RecoverableError {
                message: format!(
                    "ProtocolHandshake: failed to parse HandshakeHello payload — {}",
                    e
                ),
                context: ErrorContext::new("ProtocolHandshake", "process_hello_frame"),
                max_retries: 0,
                retry_count: 0,
            }
        })?;

        if hello.control_type != HandshakeControlType::Hello {
            return self.reject_and_build_frame(
                RejectReason::UnexpectedMessageType,
                format!(
                    "Expected HandshakeHello control_type but got {:?}",
                    hello.control_type
                ),
            );
        }

        // ── Validate all three version fields ──────────────────────────────

        if hello.protocol_version != XACE_PROTOCOL_VERSION {
            return self.reject_and_build_frame(
                RejectReason::ProtocolVersionMismatch,
                format!(
                    "Protocol version mismatch: adapter sent {} but XACE requires {}",
                    hello.protocol_version, XACE_PROTOCOL_VERSION
                ),
            );
        }

        if hello.schema_version != self.expected_schema_version {
            return self.reject_and_build_frame(
                RejectReason::SchemaVersionMismatch,
                format!(
                    "Schema version mismatch: adapter sent '{}' but XACE is running '{}'",
                    hello.schema_version, self.expected_schema_version
                ),
            );
        }

        if hello.execution_plan_version != self.expected_execution_plan_version {
            return self.reject_and_build_frame(
                RejectReason::ExecutionPlanVersionMismatch,
                format!(
                    "ExecutionPlan version mismatch: adapter sent {} but XACE is running {}",
                    hello.execution_plan_version, self.expected_execution_plan_version
                ),
            );
        }

        if hello.world_id != self.expected_world_id {
            return self.reject_and_build_frame(
                RejectReason::WorldIdMismatch,
                format!(
                    "World ID mismatch: adapter wants '{}' but this XACE session is '{}'",
                    hello.world_id, self.expected_world_id
                ),
            );
        }

        // ── All checks passed — build Ack ──────────────────────────────────

        let duration = self.started_at.elapsed();
        self.state = HandshakeState::Completed;
        self.result = Some(HandshakeResult::Accepted {
            engine_name: hello.engine_name.clone(),
            adapter_version: hello.adapter_version.clone(),
            initial_delta_sequence_id: self.initial_delta_sequence_id,
            schema_version: hello.schema_version.clone(),
            execution_plan_version: hello.execution_plan_version,
            handshake_duration: duration,
        });

        self.build_ack_frame(&hello)
    }

    /// Builds a HandshakeHello frame for the engine adapter (client) side.
    ///
    /// Called by the engine adapter to produce the opening handshake frame.
    /// The result is sent to XACE over the transport.
    pub fn build_hello_frame(
        schema_version: impl Into<String>,
        execution_plan_version: u32,
        world_id: impl Into<String>,
        engine_name: impl Into<String>,
        adapter_version: impl Into<String>,
    ) -> Result<Vec<u8>, XaceError> {
        let hello = HandshakeHello {
            control_type: HandshakeControlType::Hello,
            protocol_version: XACE_PROTOCOL_VERSION,
            schema_version: schema_version.into(),
            execution_plan_version,
            world_id: world_id.into(),
            engine_name: engine_name.into(),
            adapter_version: adapter_version.into(),
        };

        let payload = serde_json::to_string(&hello).map_err(|e| XaceError::FatalError {
            message: format!("ProtocolHandshake: failed to serialize HandshakeHello — {}", e),
            context: ErrorContext::new("ProtocolHandshake", "build_hello_frame"),
            snapshot_recovery_possible: false,
        })?;

        let msg = WireMessage::control(
            &hello.world_id,
            &hello.schema_version,
            hello.execution_plan_version,
            0, // sequence_id = 0 for handshake messages
            payload,
        );

        let mut ser = MessageSerializer::new();
        ser.serialize(&msg)
    }

    /// Parses a raw Ack or Reject frame received from XACE.
    ///
    /// Called by the engine adapter after sending its Hello frame.
    /// Returns the HandshakeResult so the adapter knows whether to
    /// proceed or report a version mismatch to the user.
    pub fn parse_response_frame(frame_bytes: &[u8]) -> Result<HandshakeResult, XaceError> {
        let mut deser = MessageDeserializer::new();
        deser.push_bytes(frame_bytes);
        let msg = deser
            .try_extract_message()?
            .ok_or_else(|| XaceError::RecoverableError {
                message: "ProtocolHandshake: incomplete response frame from XACE".into(),
                context: ErrorContext::new("ProtocolHandshake", "parse_response_frame"),
                max_retries: 3,
                retry_count: 0,
            })?;

        if !matches!(msg.message_type, MessageType::Control) {
            return Err(XaceError::RecoverableError {
                message: format!(
                    "ProtocolHandshake: expected CONTROL response but got {:?}",
                    msg.message_type
                ),
                context: ErrorContext::new("ProtocolHandshake", "parse_response_frame"),
                max_retries: 0,
                retry_count: 0,
            });
        }

        // Try to parse as Ack first
        if let Ok(ack) = serde_json::from_str::<HandshakeAck>(&msg.payload) {
            if ack.control_type == HandshakeControlType::Ack {
                return Ok(HandshakeResult::Accepted {
                    engine_name: String::new(), // not in Ack — adapter already knows its own name
                    adapter_version: String::new(),
                    initial_delta_sequence_id: ack.initial_delta_sequence_id,
                    schema_version: ack.schema_version,
                    execution_plan_version: ack.execution_plan_version,
                    handshake_duration: Duration::from_millis(0),
                });
            }
        }

        // Try to parse as Reject
        if let Ok(reject) = serde_json::from_str::<HandshakeReject>(&msg.payload) {
            if reject.control_type == HandshakeControlType::Reject {
                return Ok(HandshakeResult::Rejected {
                    reason: reject.reason,
                    detail: reject.detail,
                });
            }
        }

        Err(XaceError::RecoverableError {
            message: format!(
                "ProtocolHandshake: response payload could not be parsed as Ack or Reject: {}",
                &msg.payload[..msg.payload.len().min(200)]
            ),
            context: ErrorContext::new("ProtocolHandshake", "parse_response_frame"),
            max_retries: 0,
            retry_count: 0,
        })
    }

    // ── Inspection ────────────────────────────────────────────────────────────

    /// Returns the current handshake state.
    pub fn state(&self) -> HandshakeState {
        self.state
    }

    /// Returns the HandshakeResult if the handshake has completed (either
    /// Accepted or Rejected). Returns None if still AwaitingHello.
    pub fn result(&self) -> Option<&HandshakeResult> {
        self.result.as_ref()
    }

    /// Returns true if the handshake completed successfully.
    pub fn is_accepted(&self) -> bool {
        matches!(self.state, HandshakeState::Completed)
    }

    /// Returns true if the handshake was rejected.
    pub fn is_rejected(&self) -> bool {
        matches!(self.state, HandshakeState::Rejected)
    }

    /// Returns how long the handshake has been in progress.
    pub fn elapsed(&self) -> Duration {
        self.started_at.elapsed()
    }

    // ── Internal Helpers ──────────────────────────────────────────────────────

    /// Deserializes a raw frame into a WireMessage using a throwaway deserializer.
    fn deserialize_frame(&self, frame_bytes: &[u8]) -> Result<WireMessage, XaceError> {
        let mut deser = MessageDeserializer::new();
        deser.push_bytes(frame_bytes);
        deser
            .try_extract_message()?
            .ok_or_else(|| XaceError::RecoverableError {
                message: "ProtocolHandshake: incomplete frame — not enough bytes".into(),
                context: ErrorContext::new("ProtocolHandshake", "deserialize_frame"),
                max_retries: 3,
                retry_count: 0,
            })
    }

    /// Records a rejection, updates state, and builds the Reject response frame.
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

        let payload = serde_json::to_string(&reject).map_err(|e| XaceError::FatalError {
            message: format!("ProtocolHandshake: failed to serialize HandshakeReject — {}", e),
            context: ErrorContext::new("ProtocolHandshake", "reject_and_build_frame"),
            snapshot_recovery_possible: false,
        })?;

        let msg = WireMessage::control(
            &self.expected_world_id,
            &self.expected_schema_version,
            self.expected_execution_plan_version,
            0,
            payload,
        );

        self.serializer.serialize_unchecked(&msg)
    }

    /// Builds the Ack response frame after a successful Hello validation.
    fn build_ack_frame(&mut self, hello: &HandshakeHello) -> Result<Vec<u8>, XaceError> {
        let ack = HandshakeAck {
            control_type: HandshakeControlType::Ack,
            protocol_version: XACE_PROTOCOL_VERSION,
            schema_version: hello.schema_version.clone(),
            execution_plan_version: hello.execution_plan_version,
            world_id: hello.world_id.clone(),
            initial_delta_sequence_id: self.initial_delta_sequence_id,
            xace_version: "0.1.0".into(),
        };

        let payload = serde_json::to_string(&ack).map_err(|e| XaceError::FatalError {
            message: format!("ProtocolHandshake: failed to serialize HandshakeAck — {}", e),
            context: ErrorContext::new("ProtocolHandshake", "build_ack_frame"),
            snapshot_recovery_possible: false,
        })?;

        let msg = WireMessage::control(
            &hello.world_id,
            &hello.schema_version,
            hello.execution_plan_version,
            0,
            payload,
        );

        self.serializer.serialize_unchecked(&msg)
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    // ── Helpers ───────────────────────────────────────────────────────────────

    fn server() -> ProtocolHandshake {
        ProtocolHandshake::new_server("0.1.0", 1, "default", 1)
    }

    fn hello_frame(
        schema: &str,
        plan: u32,
        world_id: &str,
    ) -> Vec<u8> {
        ProtocolHandshake::build_hello_frame(
            schema, plan, world_id, "Unity-2022", "1.0.0",
        )
        .expect("build_hello_frame must not fail")
    }

    fn valid_hello_frame() -> Vec<u8> {
        hello_frame("0.1.0", 1, "default")
    }

    // ── Hello Frame Construction ───────────────────────────────────────────────

    #[test]
    fn build_hello_frame_produces_non_empty_bytes() {
        let frame = valid_hello_frame();
        assert!(!frame.is_empty());
    }

    #[test]
    fn hello_frame_is_valid_wire_frame() {
        let frame = valid_hello_frame();
        // Must have at least a 4-byte header
        assert!(frame.len() > 4);
        // Header must decode to a valid payload length
        let len = u32::from_be_bytes(frame[..4].try_into().unwrap()) as usize;
        assert_eq!(frame.len(), 4 + len);
    }

    #[test]
    fn hello_frame_deserializes_to_control_message() {
        let frame = valid_hello_frame();
        let mut deser = MessageDeserializer::new();
        deser.push_bytes(&frame);
        let msg = deser.try_extract_message().unwrap().unwrap();
        assert!(msg.is_control());
    }

    // ── Successful Handshake ──────────────────────────────────────────────────

    #[test]
    fn valid_hello_produces_ack_and_completed_state() {
        let mut hs = server();
        assert_eq!(hs.state(), HandshakeState::AwaitingHello);

        let frame = valid_hello_frame();
        let ack_frame = hs.process_hello_frame(&frame).unwrap();

        assert_eq!(hs.state(), HandshakeState::Completed);
        assert!(hs.is_accepted());
        assert!(!hs.is_rejected());
        assert!(!ack_frame.is_empty());
    }

    #[test]
    fn ack_frame_is_parseable_as_handshake_result() {
        let mut hs = server();
        let hello = valid_hello_frame();
        let ack_frame = hs.process_hello_frame(&hello).unwrap();

        let result = ProtocolHandshake::parse_response_frame(&ack_frame).unwrap();
        assert!(result.is_accepted());
    }

    #[test]
    fn accepted_result_carries_engine_name() {
        let mut hs = server();
        hs.process_hello_frame(&valid_hello_frame()).unwrap();
        let result = hs.result().unwrap();
        assert_eq!(result.engine_name(), Some("Unity-2022"));
    }

    #[test]
    fn accepted_result_carries_initial_sequence_id() {
        let mut hs = ProtocolHandshake::new_server("0.1.0", 1, "default", 42);
        hs.process_hello_frame(&valid_hello_frame()).unwrap();
        if let Some(HandshakeResult::Accepted { initial_delta_sequence_id, .. }) = hs.result() {
            assert_eq!(*initial_delta_sequence_id, 42);
        } else {
            panic!("Expected Accepted result");
        }
    }

    #[test]
    fn ack_carries_correct_initial_sequence_id() {
        let mut hs = ProtocolHandshake::new_server("0.1.0", 1, "default", 99);
        let ack_frame = hs.process_hello_frame(&valid_hello_frame()).unwrap();
        let result = ProtocolHandshake::parse_response_frame(&ack_frame).unwrap();
        if let HandshakeResult::Accepted { initial_delta_sequence_id, .. } = result {
            assert_eq!(initial_delta_sequence_id, 99);
        } else {
            panic!("Expected Accepted");
        }
    }

    // ── Protocol Version Mismatch ─────────────────────────────────────────────

    #[test]
    fn wrong_protocol_version_produces_reject() {
        let mut hs = server();

        // Build a Hello with wrong protocol version by constructing raw payload
        let hello = HandshakeHello {
            control_type: HandshakeControlType::Hello,
            protocol_version: 999, // wrong
            schema_version: "0.1.0".into(),
            execution_plan_version: 1,
            world_id: "default".into(),
            engine_name: "TestEngine".into(),
            adapter_version: "1.0.0".into(),
        };
        let payload = serde_json::to_string(&hello).unwrap();
        let msg = WireMessage::control("default", "0.1.0", 1, 0, payload);
        let mut ser = MessageSerializer::new();
        let frame = ser.serialize_unchecked(&msg).unwrap();

        let reject_frame = hs.process_hello_frame(&frame).unwrap();
        assert_eq!(hs.state(), HandshakeState::Rejected);
        assert!(hs.is_rejected());

        let result = ProtocolHandshake::parse_response_frame(&reject_frame).unwrap();
        assert!(!result.is_accepted());
        assert_eq!(result.reject_reason(), Some(&RejectReason::ProtocolVersionMismatch));
    }

    // ── Schema Version Mismatch ───────────────────────────────────────────────

    #[test]
    fn wrong_schema_version_produces_reject_with_correct_reason() {
        let mut hs = server();
        let frame = hello_frame("9.9.9", 1, "default"); // wrong schema
        let reject_frame = hs.process_hello_frame(&frame).unwrap();

        assert_eq!(hs.state(), HandshakeState::Rejected);
        let result = ProtocolHandshake::parse_response_frame(&reject_frame).unwrap();
        assert_eq!(result.reject_reason(), Some(&RejectReason::SchemaVersionMismatch));
    }

    // ── Execution Plan Version Mismatch ───────────────────────────────────────

    #[test]
    fn wrong_plan_version_produces_reject_with_correct_reason() {
        let mut hs = server();
        let frame = hello_frame("0.1.0", 999, "default"); // wrong plan version
        let reject_frame = hs.process_hello_frame(&frame).unwrap();

        assert_eq!(hs.state(), HandshakeState::Rejected);
        let result = ProtocolHandshake::parse_response_frame(&reject_frame).unwrap();
        assert_eq!(result.reject_reason(), Some(&RejectReason::ExecutionPlanVersionMismatch));
    }

    // ── World ID Mismatch ─────────────────────────────────────────────────────

    #[test]
    fn wrong_world_id_produces_reject_with_correct_reason() {
        let mut hs = server();
        let frame = hello_frame("0.1.0", 1, "wrong-world"); // wrong world_id
        let reject_frame = hs.process_hello_frame(&frame).unwrap();

        let result = ProtocolHandshake::parse_response_frame(&reject_frame).unwrap();
        assert_eq!(result.reject_reason(), Some(&RejectReason::WorldIdMismatch));
    }

    // ── Wrong Message Type ────────────────────────────────────────────────────

    #[test]
    fn non_control_message_produces_reject() {
        let mut hs = server();
        // Send a DELTA message instead of CONTROL
        let msg = WireMessage::delta("default", "0.1.0", 1, 0, 0, r#"{"not":"hello"}"#);
        let mut ser = MessageSerializer::new();
        let frame = ser.serialize_unchecked(&msg).unwrap();

        let reject_frame = hs.process_hello_frame(&frame).unwrap();
        assert_eq!(hs.state(), HandshakeState::Rejected);

        let result = ProtocolHandshake::parse_response_frame(&reject_frame).unwrap();
        assert_eq!(result.reject_reason(), Some(&RejectReason::UnexpectedMessageType));
    }

    // ── Malformed Payload ─────────────────────────────────────────────────────

    #[test]
    fn malformed_hello_payload_returns_err() {
        let mut hs = server();
        // A valid CONTROL message envelope but garbage payload
        let msg = WireMessage::control("default", "0.1.0", 1, 0, r#"{"not_valid":"garbage"}"#);
        let mut ser = MessageSerializer::new();
        let frame = ser.serialize_unchecked(&msg).unwrap();

        // The payload parses as JSON but not as HandshakeHello →
        // serde_json::from_str fails → process_hello_frame returns Err
        // (not a reject frame — we can't produce a valid reject from garbage)
        let result = hs.process_hello_frame(&frame);
        assert!(result.is_err(), "Malformed payload must return Err");
    }

    // ── Incomplete Frame ──────────────────────────────────────────────────────

    #[test]
    fn incomplete_frame_bytes_return_err() {
        let mut hs = server();
        let partial = &valid_hello_frame()[..3]; // only 3 bytes — not even a header
        let result = hs.process_hello_frame(partial);
        assert!(result.is_err());
    }

    // ── Reject Detail Message ─────────────────────────────────────────────────

    #[test]
    fn reject_detail_contains_version_info() {
        let mut hs = server();
        let frame = hello_frame("0.1.0", 999, "default");
        let reject_frame = hs.process_hello_frame(&frame).unwrap();

        // Parse the raw reject payload to inspect the detail string
        let mut deser = MessageDeserializer::new();
        deser.push_bytes(&reject_frame);
        let msg = deser.try_extract_message().unwrap().unwrap();
        let reject: HandshakeReject = serde_json::from_str(&msg.payload).unwrap();

        assert!(
            reject.detail.contains("999"),
            "Reject detail must include the received plan version"
        );
        assert!(
            reject.detail.contains("1"),
            "Reject detail must include the expected plan version"
        );
    }

    #[test]
    fn reject_contains_expected_versions() {
        let mut hs = ProtocolHandshake::new_server("0.2.0", 5, "world-xyz", 1);
        let frame = hello_frame("0.1.0", 5, "world-xyz"); // schema mismatch
        let reject_frame = hs.process_hello_frame(&frame).unwrap();

        let mut deser = MessageDeserializer::new();
        deser.push_bytes(&reject_frame);
        let msg = deser.try_extract_message().unwrap().unwrap();
        let reject: HandshakeReject = serde_json::from_str(&msg.payload).unwrap();

        assert_eq!(reject.expected_schema_version, "0.2.0");
        assert_eq!(reject.expected_execution_plan_version, 5);
        assert_eq!(reject.expected_world_id, "world-xyz");
        assert_eq!(reject.expected_protocol_version, XACE_PROTOCOL_VERSION);
    }

    // ── State Guards ──────────────────────────────────────────────────────────

    #[test]
    fn initial_state_is_awaiting_hello() {
        let hs = server();
        assert_eq!(hs.state(), HandshakeState::AwaitingHello);
        assert!(hs.result().is_none());
        assert!(!hs.is_accepted());
        assert!(!hs.is_rejected());
    }

    #[test]
    fn elapsed_increases_over_time() {
        let hs = server();
        std::thread::sleep(Duration::from_millis(5));
        assert!(hs.elapsed() >= Duration::from_millis(1));
    }

    // ── Full Client-Server Round-trip ─────────────────────────────────────────

    #[test]
    fn full_round_trip_accepted() {
        // Client builds Hello
        let hello_frame = ProtocolHandshake::build_hello_frame(
            "0.1.0", 1, "default", "Godot-4", "2.0.0",
        )
        .unwrap();

        // Server processes Hello → produces Ack
        let mut server = ProtocolHandshake::new_server("0.1.0", 1, "default", 10);
        let ack_frame = server.process_hello_frame(&hello_frame).unwrap();
        assert!(server.is_accepted());

        // Client parses Ack
        let client_result = ProtocolHandshake::parse_response_frame(&ack_frame).unwrap();
        assert!(client_result.is_accepted());
        if let HandshakeResult::Accepted { initial_delta_sequence_id, schema_version, .. } =
            client_result
        {
            assert_eq!(initial_delta_sequence_id, 10);
            assert_eq!(schema_version, "0.1.0");
        }
    }

    #[test]
    fn full_round_trip_rejected_schema_mismatch() {
        // Client sends Hello with wrong schema
        let hello_frame = ProtocolHandshake::build_hello_frame(
            "0.9.0", 1, "default", "UnrealEngine-5", "3.0.0",
        )
        .unwrap();

        // Server rejects
        let mut server = ProtocolHandshake::new_server("0.1.0", 1, "default", 1);
        let reject_frame = server.process_hello_frame(&hello_frame).unwrap();
        assert!(server.is_rejected());

        // Client parses Reject
        let client_result = ProtocolHandshake::parse_response_frame(&reject_frame).unwrap();
        assert!(!client_result.is_accepted());
        assert_eq!(
            client_result.reject_reason(),
            Some(&RejectReason::SchemaVersionMismatch)
        );
    }

    // ── Display / Serde ───────────────────────────────────────────────────────

    #[test]
    fn reject_reason_display() {
        assert_eq!(
            RejectReason::SchemaVersionMismatch.to_string(),
            "SCHEMA_VERSION_MISMATCH"
        );
        assert_eq!(
            RejectReason::ProtocolVersionMismatch.to_string(),
            "PROTOCOL_VERSION_MISMATCH"
        );
        assert_eq!(
            RejectReason::WorldIdMismatch.to_string(),
            "WORLD_ID_MISMATCH"
        );
    }

    #[test]
    fn handshake_state_display() {
        assert_eq!(HandshakeState::AwaitingHello.to_string(), "AWAITING_HELLO");
        assert_eq!(HandshakeState::Completed.to_string(), "COMPLETED");
        assert_eq!(HandshakeState::Rejected.to_string(), "REJECTED");
    }

    #[test]
    fn handshake_hello_roundtrip_serde() {
        let hello = HandshakeHello {
            control_type: HandshakeControlType::Hello,
            protocol_version: XACE_PROTOCOL_VERSION,
            schema_version: "0.1.0".into(),
            execution_plan_version: 1,
            world_id: "default".into(),
            engine_name: "Unity".into(),
            adapter_version: "1.0.0".into(),
        };
        let json = serde_json::to_string(&hello).unwrap();
        let restored: HandshakeHello = serde_json::from_str(&json).unwrap();
        assert_eq!(restored.schema_version, "0.1.0");
        assert_eq!(restored.engine_name, "Unity");
    }
}