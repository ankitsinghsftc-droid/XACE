//! # Wire Message
//!
//! The top-level envelope for all messages exchanged between the XACE
//! runtime and engine adapters over the TCP transport layer.
//!
//! ## What a WireMessage Is
//! Every byte that flows between XACE and an engine adapter is wrapped
//! in a WireMessage envelope. The envelope carries version information,
//! sequencing data, message type, and the typed payload. The engine
//! adapter inspects the envelope before deserializing the payload.
//!
//! ## Protocol Version
//! The protocol_version field enables forward/backward compatibility.
//! If XACE and the engine adapter have mismatched protocol versions,
//! the handshake fails and the connection is rejected. This prevents
//! silent data corruption from version mismatches.
//!
//! ## Version Triplet (D10)
//! Every WireMessage carries three version fields:
//! - protocol_version: the wire format version (frozen at v1 for now)
//! - schema_version: the CGS version active when this message was created
//! - execution_plan_version: the ExecutionPlan version active at this time
//!
//! The engine adapter validates all three before applying any payload.
//! Mismatches in schema_version or execution_plan_version cause the
//! engine adapter to request a SNAPSHOT for full resynchronization.
//!
//! ## Serialization
//! WireMessages are serialized to bytes using a deterministic format.
//! The message_serializer.rs (Phase 7) handles the actual byte encoding.
//! JSON with stable key ordering is used for cross-language compatibility.
//!
//! ## Determinism (D11)
//! Identical world state + identical tick always produces identical
//! WireMessage bytes. This is validated by test_transport.rs (Phase 7).

use serde::{Deserialize, Serialize};
use crate::wire::message_type::MessageType;
use crate::entity_metadata::Tick;

// ── Protocol Version ──────────────────────────────────────────────────────────

/// The wire protocol version.
///
/// Frozen at 1 for the initial XACE release.
/// Incremented only when the WireMessage envelope structure changes
/// in a backward-incompatible way.
/// Never incremented for payload changes — payload evolution is handled
/// by schema_version and component versioning.
pub const XACE_PROTOCOL_VERSION: u32 = 1;

// ── Wire Message ──────────────────────────────────────────────────────────────

/// The envelope for all XACE ↔ Engine communication.
///
/// Every message over the wire — SNAPSHOT, DELTA, INPUT, EVENT,
/// CONTROL, FEEDBACK — is wrapped in this envelope.
///
/// ## Byte Layout (conceptual, actual encoding by message_serializer)
/// [4 bytes] protocol_version (u32, little-endian)
/// [4 bytes] payload_length   (u32, little-endian)
/// [N bytes] JSON envelope + payload
///
/// The actual binary encoding is handled by message_serializer.rs (Phase 7).
/// This struct is the logical representation — serialization details
/// are an implementation concern of the transport layer.
///
/// ## World ID
/// world_id identifies which world session this message belongs to.
/// Used when multiple world sessions run on the same XACE instance.
/// For single-world deployments, world_id is always "default".
///
/// ## Sequence ID
/// sequence_id is the same as the inner payload's sequence_id for DELTA.
/// For SNAPSHOT, CONTROL, FEEDBACK it tracks message ordering separately.
/// The engine adapter uses this to detect dropped messages.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WireMessage {
    /// The wire protocol version.
    /// Must match XACE_PROTOCOL_VERSION on both sides.
    /// Handshake rejects mismatched versions immediately.
    pub protocol_version: u32,

    /// Identifies the world session this message belongs to.
    /// "default" for single-world deployments.
    /// UUID string for multi-world deployments.
    pub world_id: String,

    /// The CGS semantic version active when this message was created.
    /// Engine adapter validates before applying payload (D10).
    pub schema_version: String,

    /// The ExecutionPlan version active when this message was created.
    /// Engine adapter validates before applying payload (D10).
    pub execution_plan_version: u32,

    /// The simulation tick this message relates to.
    /// For DELTA and SNAPSHOT: the tick that produced the payload.
    /// For INPUT: the tick the input was generated on (I14).
    /// For FEEDBACK: the tick the engine processed feedback for.
    /// For CONTROL: 0 (not tick-related).
    pub tick: Tick,

    /// Monotonically increasing message sequence number.
    /// Used by engine adapter to detect dropped or out-of-order messages.
    /// Scoped per message type — DELTA has its own sequence, separate
    /// from FEEDBACK sequence, separate from CONTROL sequence.
    pub sequence_id: u64,

    /// What kind of message this is.
    /// Determines how the engine adapter deserializes the payload.
    pub message_type: MessageType,

    /// The message payload serialized as a JSON string.
    ///
    /// Type depends on message_type:
    /// - Snapshot  → SnapshotPayload serialized to JSON
    /// - Delta     → DeltaPayload serialized to JSON
    /// - Input     → InputPayload serialized to JSON (Phase 7)
    /// - Event     → EventPayload serialized to JSON
    /// - Control   → ControlPayload serialized to JSON (Phase 7)
    /// - Feedback  → FeedbackPayload serialized to JSON
    ///
    /// The message_deserializer.rs (Phase 7) handles type-safe
    /// deserialization from this JSON string based on message_type.
    pub payload: String,
}

impl WireMessage {
    /// Creates a new WireMessage with the current protocol version.
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

    /// Creates a SNAPSHOT message.
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

    /// Creates a DELTA message.
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

    /// Creates a FEEDBACK message.
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

    /// Creates a CONTROL message.
    /// Control messages use tick=0 and are not tick-specific.
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
            0, // control messages are not tick-specific
            sequence_id,
            MessageType::Control,
            payload_json,
        )
    }

    /// Returns true if this message's protocol version matches
    /// the current XACE protocol version.
    /// Used during handshake validation (Phase 7).
    pub fn is_protocol_compatible(&self) -> bool {
        self.protocol_version == XACE_PROTOCOL_VERSION
    }

    /// Returns true if this message's schema and plan versions match
    /// the given expected versions.
    /// Used by the engine adapter to validate before applying payload (D10).
    pub fn is_version_compatible(
        &self,
        expected_schema: &str,
        expected_plan_version: u32,
    ) -> bool {
        self.schema_version == expected_schema
            && self.execution_plan_version == expected_plan_version
    }

    /// Returns true if this is a SNAPSHOT message.
    pub fn is_snapshot(&self) -> bool {
        matches!(self.message_type, MessageType::Snapshot)
    }

    /// Returns true if this is a DELTA message.
    pub fn is_delta(&self) -> bool {
        matches!(self.message_type, MessageType::Delta)
    }

    /// Returns true if this is a FEEDBACK message.
    pub fn is_feedback(&self) -> bool {
        matches!(self.message_type, MessageType::Feedback)
    }

    /// Returns true if this is a CONTROL message.
    pub fn is_control(&self) -> bool {
        matches!(self.message_type, MessageType::Control)
    }

    /// Returns true if this message flows from XACE to the engine.
    pub fn is_outbound(&self) -> bool {
        self.message_type.is_xace_to_engine()
    }

    /// Returns true if this message flows from the engine to XACE.
    pub fn is_inbound(&self) -> bool {
        self.message_type.is_engine_to_xace()
    }

    /// Returns the payload length in bytes for bandwidth tracking.
    pub fn payload_size_bytes(&self) -> usize {
        self.payload.len()
    }

    /// Validates this message envelope for structural correctness.
    ///
    /// Checks:
    /// - protocol_version matches XACE_PROTOCOL_VERSION
    /// - world_id is not empty
    /// - schema_version is not empty
    /// - execution_plan_version >= 1
    /// - payload is not empty
    /// - INPUT messages carry a non-zero tick (I14)
    pub fn validate(&self) -> Result<(), String> {
        if self.protocol_version != XACE_PROTOCOL_VERSION {
            return Err(format!(
                "WireMessage protocol_version {} does not match \
                 expected {} — reject connection",
                self.protocol_version, XACE_PROTOCOL_VERSION
            ));
        }

        if self.world_id.is_empty() {
            return Err("WireMessage world_id must not be empty".into());
        }

        if self.schema_version.is_empty() {
            return Err("WireMessage schema_version must not be empty".into());
        }

        if self.execution_plan_version == 0 {
            return Err(
                "WireMessage execution_plan_version must be >= 1".into()
            );
        }

        if self.payload.is_empty() {
            return Err(format!(
                "WireMessage {} has empty payload — all messages \
                 must carry a payload",
                self.message_type
            ));
        }

        // INPUT messages must carry the tick they were generated on (I14)
        if matches!(self.message_type, MessageType::Input) && self.tick == 0 {
            return Err(
                "WireMessage INPUT must carry a non-zero tick — \
                 all input packets must be timestamped (I14)"
                    .into(),
            );
        }

        Ok(())
    }
}

impl std::fmt::Display for WireMessage {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "WireMessage[{}](type={}, world={}, tick={}, seq={}, \
             schema={}, plan_v={}, payload={}B)",
            self.protocol_version,
            self.message_type,
            self.world_id,
            self.tick,
            self.sequence_id,
            self.schema_version,
            self.execution_plan_version,
            self.payload.len(),
        )
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn test_message() -> WireMessage {
        WireMessage::delta(
            "default",
            "0.1.0",
            1,
            42,
            100,
            r#"{"tick":42,"sequence_id":100}"#,
        )
    }

    #[test]
    fn new_message_uses_current_protocol_version() {
        let msg = test_message();
        assert_eq!(msg.protocol_version, XACE_PROTOCOL_VERSION);
    }

    #[test]
    fn is_protocol_compatible_matches_version() {
        let msg = test_message();
        assert!(msg.is_protocol_compatible());
    }

    #[test]
    fn is_protocol_compatible_fails_wrong_version() {
        let mut msg = test_message();
        msg.protocol_version = 99;
        assert!(!msg.is_protocol_compatible());
    }

    #[test]
    fn is_version_compatible_correct() {
        let msg = test_message();
        assert!(msg.is_version_compatible("0.1.0", 1));
        assert!(!msg.is_version_compatible("0.2.0", 1));
        assert!(!msg.is_version_compatible("0.1.0", 2));
    }

    #[test]
    fn message_type_detection() {
        let delta = test_message();
        assert!(delta.is_delta());
        assert!(!delta.is_snapshot());
        assert!(!delta.is_feedback());
        assert!(!delta.is_control());
    }

    #[test]
    fn snapshot_message_created_correctly() {
        let msg = WireMessage::snapshot(
            "default",
            "0.1.0",
            1,
            0,
            1,
            r#"{"tick":0}"#,
        );
        assert!(msg.is_snapshot());
        assert!(msg.is_outbound());
    }

    #[test]
    fn feedback_message_is_inbound() {
        let msg = WireMessage::feedback(
            "default",
            "0.1.0",
            1,
            42,
            1,
            r#"{"tick":42}"#,
        );
        assert!(msg.is_feedback());
        assert!(msg.is_inbound());
        assert!(!msg.is_outbound());
    }

    #[test]
    fn control_message_has_zero_tick() {
        let msg = WireMessage::control(
            "default",
            "0.1.0",
            1,
            1,
            r#"{"type":"handshake"}"#,
        );
        assert_eq!(msg.tick, 0);
        assert!(msg.is_control());
    }

    #[test]
    fn validate_passes_for_valid_message() {
        assert!(test_message().validate().is_ok());
    }

    #[test]
    fn validate_fails_for_wrong_protocol_version() {
        let mut msg = test_message();
        msg.protocol_version = 99;
        assert!(msg.validate().is_err());
    }

    #[test]
    fn validate_fails_for_empty_world_id() {
        let mut msg = test_message();
        msg.world_id = String::new();
        assert!(msg.validate().is_err());
    }

    #[test]
    fn validate_fails_for_empty_schema_version() {
        let mut msg = test_message();
        msg.schema_version = String::new();
        assert!(msg.validate().is_err());
    }

    #[test]
    fn validate_fails_for_zero_plan_version() {
        let mut msg = test_message();
        msg.execution_plan_version = 0;
        assert!(msg.validate().is_err());
    }

    #[test]
    fn validate_fails_for_empty_payload() {
        let mut msg = test_message();
        msg.payload = String::new();
        assert!(msg.validate().is_err());
    }

    #[test]
    fn validate_fails_for_input_with_zero_tick() {
        let mut msg = WireMessage::new(
            "default",
            "0.1.0",
            1,
            0, // zero tick — invalid for INPUT (I14)
            1,
            MessageType::Input,
            r#"{"actions":[]}"#,
        );
        msg.tick = 0;
        assert!(msg.validate().is_err());
    }

    #[test]
    fn validate_passes_for_input_with_nonzero_tick() {
        let msg = WireMessage::new(
            "default",
            "0.1.0",
            1,
            5, // valid tick
            1,
            MessageType::Input,
            r#"{"actions":[]}"#,
        );
        assert!(msg.validate().is_ok());
    }

    #[test]
    fn payload_size_bytes_correct() {
        let msg = test_message();
        assert_eq!(msg.payload_size_bytes(), msg.payload.len());
    }

    #[test]
    fn display_includes_key_fields() {
        let msg = test_message();
        let display = msg.to_string();
        assert!(display.contains("DELTA"));
        assert!(display.contains("default"));
        assert!(display.contains("42"));
        assert!(display.contains("0.1.0"));
    }

    #[test]
    fn world_id_stored_correctly() {
        let msg = WireMessage::delta(
            "world-session-abc",
            "0.1.0",
            1,
            0,
            1,
            "{}",
        );
        assert_eq!(msg.world_id, "world-session-abc");
    }

    #[test]
    fn sequence_id_stored_correctly() {
        let msg = test_message();
        assert_eq!(msg.sequence_id, 100);
    }

    #[test]
    fn tick_stored_correctly() {
        let msg = test_message();
        assert_eq!(msg.tick, 42);
    }
}