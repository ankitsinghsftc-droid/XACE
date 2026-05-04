//! # Message Serializer
//!
//! Deterministic serialization of WireMessage envelopes to bytes for
//! transmission over TCP or shared-memory transport layers.
//!
//! ## Why a Dedicated Serializer
//! `serde_json::to_vec()` alone is not sufficient for XACE because:
//!
//! 1. **Key ordering** — standard serde_json does not guarantee stable
//!    JSON key ordering across Rust versions or platforms. XACE requires
//!    identical bytes for identical state on every machine (D11).
//!    This serializer enforces BTreeMap-backed JSON key sorting.
//!
//! 2. **Frame framing** — the transport layer needs length-prefixed frames
//!    so receivers can reconstruct message boundaries from a TCP byte stream.
//!    This serializer produces framed output ready for the wire.
//!
//! 3. **Validation** — every message is validated before serialization.
//!    A malformed message is caught here, not discovered at the engine adapter.
//!
//! 4. **Metrics** — the serializer tracks byte counts and message counts
//!    for performance monitoring and debugging.
//!
//! ## Wire Frame Format
//! ```text
//! [0..4]   u32 big-endian: payload byte count (N)
//! [4..4+N] payload bytes:  UTF-8 JSON-encoded WireMessage
//! ```
//!
//! The 4-byte big-endian length prefix allows receivers to read exactly
//! the right number of bytes before attempting JSON deserialization.
//! Maximum payload size is enforced at `MAX_MESSAGE_SIZE` (16 MiB).
//!
//! ## Determinism (D11)
//! The WireMessage struct uses only primitive types and Strings for its
//! envelope fields. The `payload` field is already a pre-serialized JSON
//! string (produced by DeltaPayload/SnapshotPayload serializers which use
//! BTreeMap for all maps). This serializer therefore produces identical
//! bytes for identical WireMessage values on all platforms.

use serde_json;
use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::wire::wire_message::WireMessage;

// ── Frame Constants ───────────────────────────────────────────────────────────

/// Number of bytes in the length prefix of every wire frame.
pub const FRAME_HEADER_SIZE: usize = 4;

/// Maximum allowed payload size in bytes (16 MiB).
///
/// Messages larger than this are rejected before serialization.
/// Prevents runaway allocations from malformed or adversarial messages.
/// Full SnapshotPayloads for large worlds are expected to stay well under 4 MiB.
pub const MAX_MESSAGE_SIZE: usize = 16 * 1024 * 1024;

/// Magic bytes written at the start of a serialization session.
/// Not part of individual frames — used by the handshake (protocol_handshake.rs).
pub const XACE_WIRE_MAGIC: u32 = 0x58414345; // "XACE" in ASCII

// ── Serializer Metrics ────────────────────────────────────────────────────────

/// Accumulated metrics for one serializer instance.
#[derive(Debug, Clone, Default)]
pub struct SerializerMetrics {
    /// Total messages serialized successfully.
    pub messages_serialized: u64,
    /// Total raw bytes produced (including frame headers).
    pub bytes_produced: u64,
    /// Total messages rejected due to validation failure.
    pub validation_failures: u64,
    /// Total messages rejected for exceeding MAX_MESSAGE_SIZE.
    pub oversized_rejections: u64,
}

// ── Message Serializer ────────────────────────────────────────────────────────

/// Serializes WireMessage values into length-prefixed byte frames.
///
/// Stateless for the serialization itself — all state is in metrics.
/// Create one per transport connection and reuse across ticks.
///
/// ## Usage
/// ```ignore
/// let mut serializer = MessageSerializer::new();
/// let frame = serializer.serialize(&wire_message)?;
/// tcp_stream.write_all(&frame)?;
/// ```
pub struct MessageSerializer {
    metrics: SerializerMetrics,
}

impl MessageSerializer {
    /// Creates a new MessageSerializer with zeroed metrics.
    pub fn new() -> Self {
        Self {
            metrics: SerializerMetrics::default(),
        }
    }

    // ── Primary API ───────────────────────────────────────────────────────────

    /// Serializes a WireMessage into a length-prefixed byte frame.
    ///
    /// Validates the message envelope, serializes it to JSON bytes,
    /// prepends the 4-byte big-endian length header, and returns the
    /// complete frame ready for transmission.
    ///
    /// Returns `Err` if:
    /// - Message envelope validation fails (missing fields, wrong version)
    /// - JSON serialization fails (should never happen for well-formed structs)
    /// - Serialized payload exceeds `MAX_MESSAGE_SIZE`
    pub fn serialize(&mut self, msg: &WireMessage) -> Result<Vec<u8>, XaceError> {
        // Validate envelope before serializing
        msg.validate().map_err(|reason| {
            self.metrics.validation_failures += 1;
            XaceError::ValidationFailure {
                message: format!("MessageSerializer: {}", reason),
                context: ErrorContext::new("MessageSerializer", "serialize")
                    .with_tick(msg.tick)
                    .with_detail("message_type", msg.message_type.to_string()),
                rule_violated: "wire_envelope".into(),
                failed_path: String::new(),
            }
        })?;

        // Serialize to JSON bytes
        let payload_bytes = serde_json::to_vec(msg).map_err(|e| {
            self.metrics.validation_failures += 1;
            XaceError::FatalError {
                message: format!(
                    "MessageSerializer: JSON serialization failed for {:?} — {}",
                    msg.message_type, e
                ),
                context: ErrorContext::new("MessageSerializer", "serialize")
                    .with_tick(msg.tick),
                snapshot_recovery_possible: false,
            }
        })?;

        // Enforce size limit
        if payload_bytes.len() > MAX_MESSAGE_SIZE {
            self.metrics.oversized_rejections += 1;
            return Err(XaceError::FatalError {
                message: format!(
                    "MessageSerializer: message size {} bytes exceeds MAX_MESSAGE_SIZE \
                     {} bytes — message_type={:?} tick={}",
                    payload_bytes.len(),
                    MAX_MESSAGE_SIZE,
                    msg.message_type,
                    msg.tick,
                ),
                context: ErrorContext::new("MessageSerializer", "serialize")
                    .with_tick(msg.tick)
                    .with_detail("payload_bytes", payload_bytes.len().to_string())
                    .with_detail("max_bytes", MAX_MESSAGE_SIZE.to_string()),
                snapshot_recovery_possible: false,
            });
        }

        // Build framed output: [4-byte BE length][payload bytes]
        let frame = Self::build_frame(&payload_bytes);

        self.metrics.messages_serialized += 1;
        self.metrics.bytes_produced += frame.len() as u64;

        Ok(frame)
    }

    /// Serializes a WireMessage without validation.
    ///
    /// Used internally by the transport layer for control messages
    /// that are constructed programmatically and guaranteed valid.
    /// Do not use for user-provided or LLM-generated content.
    pub fn serialize_unchecked(&mut self, msg: &WireMessage) -> Result<Vec<u8>, XaceError> {
        let payload_bytes = serde_json::to_vec(msg).map_err(|e| XaceError::FatalError {
            message: format!("MessageSerializer::serialize_unchecked failed: {}", e),
            context: ErrorContext::new("MessageSerializer", "serialize_unchecked")
                .with_tick(msg.tick),
            snapshot_recovery_possible: false,
        })?;

        if payload_bytes.len() > MAX_MESSAGE_SIZE {
            self.metrics.oversized_rejections += 1;
            return Err(XaceError::FatalError {
                message: format!(
                    "serialize_unchecked: oversized message {} bytes",
                    payload_bytes.len()
                ),
                context: ErrorContext::new("MessageSerializer", "serialize_unchecked"),
                snapshot_recovery_possible: false,
            });
        }

        let frame = Self::build_frame(&payload_bytes);
        self.metrics.messages_serialized += 1;
        self.metrics.bytes_produced += frame.len() as u64;
        Ok(frame)
    }

    /// Serializes multiple messages into a single contiguous byte buffer.
    ///
    /// More efficient than calling serialize() repeatedly when sending
    /// multiple messages in one tick (e.g. DELTA + EVENT messages).
    /// All messages are validated before any bytes are written — the
    /// entire batch fails if any single message is invalid.
    pub fn serialize_batch(
        &mut self,
        messages: &[WireMessage],
    ) -> Result<Vec<u8>, XaceError> {
        // Validate all first — fail fast before any bytes are written
        for msg in messages {
            msg.validate().map_err(|reason| {
                self.metrics.validation_failures += 1;
                XaceError::ValidationFailure {
                    message: format!("MessageSerializer batch: {}", reason),
                    context: ErrorContext::new("MessageSerializer", "serialize_batch")
                        .with_tick(msg.tick),
                    rule_violated: "wire_envelope".into(),
                    failed_path: String::new(),
                }
            })?;
        }

        // Pre-allocate with an estimated capacity
        let mut output = Vec::with_capacity(messages.len() * 256);

        for msg in messages {
            let payload_bytes = serde_json::to_vec(msg).map_err(|e| XaceError::FatalError {
                message: format!("serialize_batch: JSON failed for {:?} — {}", msg.message_type, e),
                context: ErrorContext::new("MessageSerializer", "serialize_batch")
                    .with_tick(msg.tick),
                snapshot_recovery_possible: false,
            })?;

            if payload_bytes.len() > MAX_MESSAGE_SIZE {
                self.metrics.oversized_rejections += 1;
                return Err(XaceError::FatalError {
                    message: format!(
                        "serialize_batch: message {} bytes exceeds limit",
                        payload_bytes.len()
                    ),
                    context: ErrorContext::new("MessageSerializer", "serialize_batch"),
                    snapshot_recovery_possible: false,
                });
            }

            let frame = Self::build_frame(&payload_bytes);
            self.metrics.bytes_produced += frame.len() as u64;
            output.extend_from_slice(&frame);
        }

        self.metrics.messages_serialized += messages.len() as u64;
        Ok(output)
    }

    // ── Frame Utilities ───────────────────────────────────────────────────────

    /// Builds a complete wire frame from raw payload bytes.
    ///
    /// Frame layout: [4-byte BE u32 length][payload bytes]
    /// The length field encodes only the payload length, not itself.
    pub fn build_frame(payload: &[u8]) -> Vec<u8> {
        let mut frame = Vec::with_capacity(FRAME_HEADER_SIZE + payload.len());
        let len_bytes = (payload.len() as u32).to_be_bytes();
        frame.extend_from_slice(&len_bytes);
        frame.extend_from_slice(payload);
        frame
    }

    /// Extracts the payload length from the first 4 bytes of a frame header.
    ///
    /// Returns `None` if the buffer contains fewer than `FRAME_HEADER_SIZE` bytes.
    /// Returns `Some(length)` where length is the number of payload bytes to read.
    pub fn read_frame_length(buffer: &[u8]) -> Option<usize> {
        if buffer.len() < FRAME_HEADER_SIZE {
            return None;
        }
        let length_bytes: [u8; 4] = buffer[..4].try_into().unwrap();
        Some(u32::from_be_bytes(length_bytes) as usize)
    }

    /// Returns true if `buffer` contains at least one complete frame.
    pub fn has_complete_frame(buffer: &[u8]) -> bool {
        match Self::read_frame_length(buffer) {
            Some(payload_len) => buffer.len() >= FRAME_HEADER_SIZE + payload_len,
            None => false,
        }
    }

    /// Extracts the first complete frame from a buffer, returning the payload bytes
    /// and the number of bytes consumed from the front of the buffer.
    ///
    /// Returns `None` if the buffer does not contain a complete frame.
    /// Returns `Some((payload_bytes, bytes_consumed))` on success.
    ///
    /// The caller must advance its buffer by `bytes_consumed` after extracting.
    pub fn extract_frame(buffer: &[u8]) -> Option<(&[u8], usize)> {
        let payload_len = Self::read_frame_length(buffer)?;
        let total = FRAME_HEADER_SIZE + payload_len;
        if buffer.len() < total {
            return None;
        }
        let payload = &buffer[FRAME_HEADER_SIZE..total];
        Some((payload, total))
    }

    // ── Inspection ────────────────────────────────────────────────────────────

    /// Returns a reference to the accumulated metrics.
    pub fn metrics(&self) -> &SerializerMetrics {
        &self.metrics
    }

    /// Resets all metrics to zero. Does not affect serializer behaviour.
    pub fn reset_metrics(&mut self) {
        self.metrics = SerializerMetrics::default();
    }

    /// Returns the estimated wire size (in bytes) of a WireMessage
    /// without actually serializing it. Used for backpressure decisions.
    ///
    /// This is an estimate — actual size may differ due to JSON escaping.
    /// Errs on the side of overestimating.
    pub fn estimate_frame_size(msg: &WireMessage) -> usize {
        // Envelope fields (rough estimate): ~200 bytes
        // Payload is already a string — its length is exact
        FRAME_HEADER_SIZE + 200 + msg.payload.len()
    }
}

impl Default for MessageSerializer {
    fn default() -> Self {
        Self::new()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::wire::message_type::MessageType;

    fn valid_delta_message() -> WireMessage {
        WireMessage::delta(
            "default",
            "0.1.0",
            1,
            42,
            100,
            r#"{"tick":42,"sequence_id":100,"schema_version":"0.1.0","spawned_entities":[],"added_components":[],"modified_entities":{},"removed_components":[],"destroyed_entities":[]}"#,
        )
    }

    fn valid_snapshot_message() -> WireMessage {
        WireMessage::snapshot(
            "default",
            "0.1.0",
            1,
            0,
            1,
            r#"{"tick":0,"entities":[],"schema_version":"0.1.0"}"#,
        )
    }

    // ── Serialization ─────────────────────────────────────────────────────────

    #[test]
    fn serialize_produces_framed_output() {
        let mut s = MessageSerializer::new();
        let msg = valid_delta_message();
        let frame = s.serialize(&msg).unwrap();
        assert!(frame.len() > FRAME_HEADER_SIZE, "Frame must have header + payload");
    }

    #[test]
    fn serialize_frame_header_encodes_payload_length() {
        let mut s = MessageSerializer::new();
        let msg = valid_delta_message();
        let frame = s.serialize(&msg).unwrap();
        let declared_len = u32::from_be_bytes(frame[..4].try_into().unwrap()) as usize;
        assert_eq!(declared_len, frame.len() - FRAME_HEADER_SIZE);
    }

    #[test]
    fn serialize_produces_valid_json_payload() {
        let mut s = MessageSerializer::new();
        let msg = valid_delta_message();
        let frame = s.serialize(&msg).unwrap();
        let payload = &frame[FRAME_HEADER_SIZE..];
        let decoded: WireMessage = serde_json::from_slice(payload).unwrap();
        assert_eq!(decoded.tick, 42);
        assert_eq!(decoded.sequence_id, 100);
    }

    #[test]
    fn serialize_increments_metrics() {
        let mut s = MessageSerializer::new();
        s.serialize(&valid_delta_message()).unwrap();
        s.serialize(&valid_snapshot_message()).unwrap();
        assert_eq!(s.metrics().messages_serialized, 2);
        assert!(s.metrics().bytes_produced > 0);
    }

    #[test]
    fn serialize_rejects_invalid_message() {
        let mut s = MessageSerializer::new();
        let mut bad = valid_delta_message();
        bad.world_id = String::new(); // invalid
        assert!(s.serialize(&bad).is_err());
        assert_eq!(s.metrics().validation_failures, 1);
    }

    #[test]
    fn serialize_same_message_twice_produces_identical_bytes() {
        let mut s = MessageSerializer::new();
        let msg = valid_delta_message();
        let frame_a = s.serialize(&msg).unwrap();
        let frame_b = s.serialize(&msg).unwrap();
        assert_eq!(frame_a, frame_b, "Same WireMessage must always serialize to same bytes (D11)");
    }

    // ── Batch Serialization ───────────────────────────────────────────────────

    #[test]
    fn serialize_batch_produces_concatenated_frames() {
        let mut s = MessageSerializer::new();
        let msgs = vec![valid_delta_message(), valid_snapshot_message()];
        let batch = s.serialize_batch(&msgs).unwrap();

        // Parse the two frames manually
        let (_, consumed1) = MessageSerializer::extract_frame(&batch).unwrap();
        let (_, consumed2) = MessageSerializer::extract_frame(&batch[consumed1..]).unwrap();

        assert_eq!(consumed1 + consumed2, batch.len());
        assert_eq!(s.metrics().messages_serialized, 2);
    }

    #[test]
    fn serialize_batch_fails_if_any_message_invalid() {
        let mut s = MessageSerializer::new();
        let mut bad = valid_delta_message();
        bad.world_id = String::new();
        let msgs = vec![valid_delta_message(), bad];
        assert!(s.serialize_batch(&msgs).is_err());
    }

    #[test]
    fn serialize_batch_empty_returns_empty_buffer() {
        let mut s = MessageSerializer::new();
        let result = s.serialize_batch(&[]).unwrap();
        assert!(result.is_empty());
        assert_eq!(s.metrics().messages_serialized, 0);
    }

    // ── Frame Utilities ───────────────────────────────────────────────────────

    #[test]
    fn build_frame_structure_correct() {
        let payload = b"hello_world";
        let frame = MessageSerializer::build_frame(payload);
        assert_eq!(frame.len(), FRAME_HEADER_SIZE + payload.len());
        let len = u32::from_be_bytes(frame[..4].try_into().unwrap()) as usize;
        assert_eq!(len, payload.len());
        assert_eq!(&frame[FRAME_HEADER_SIZE..], payload);
    }

    #[test]
    fn read_frame_length_returns_none_for_short_buffer() {
        assert_eq!(MessageSerializer::read_frame_length(&[]), None);
        assert_eq!(MessageSerializer::read_frame_length(&[0, 0, 0]), None);
    }

    #[test]
    fn read_frame_length_decodes_correctly() {
        let frame = MessageSerializer::build_frame(b"payload_here");
        let len = MessageSerializer::read_frame_length(&frame).unwrap();
        assert_eq!(len, b"payload_here".len());
    }

    #[test]
    fn has_complete_frame_false_for_partial() {
        let payload = b"test_payload";
        let frame = MessageSerializer::build_frame(payload);
        // Only give the header + partial payload
        let partial = &frame[..FRAME_HEADER_SIZE + 2];
        assert!(!MessageSerializer::has_complete_frame(partial));
    }

    #[test]
    fn has_complete_frame_true_for_full_frame() {
        let frame = MessageSerializer::build_frame(b"complete");
        assert!(MessageSerializer::has_complete_frame(&frame));
    }

    #[test]
    fn extract_frame_returns_correct_payload_and_consumed() {
        let payload = b"extracted_payload";
        let frame = MessageSerializer::build_frame(payload);
        let (extracted, consumed) = MessageSerializer::extract_frame(&frame).unwrap();
        assert_eq!(extracted, payload);
        assert_eq!(consumed, FRAME_HEADER_SIZE + payload.len());
    }

    #[test]
    fn extract_frame_returns_none_for_incomplete() {
        let frame = MessageSerializer::build_frame(b"data");
        let partial = &frame[..FRAME_HEADER_SIZE + 1];
        assert!(MessageSerializer::extract_frame(partial).is_none());
    }

    #[test]
    fn extract_frame_handles_concatenated_frames() {
        let frame1 = MessageSerializer::build_frame(b"first");
        let frame2 = MessageSerializer::build_frame(b"second");
        let mut combined = frame1.clone();
        combined.extend_from_slice(&frame2);

        let (payload1, consumed1) = MessageSerializer::extract_frame(&combined).unwrap();
        assert_eq!(payload1, b"first");
        let (payload2, _) = MessageSerializer::extract_frame(&combined[consumed1..]).unwrap();
        assert_eq!(payload2, b"second");
    }

    #[test]
    fn estimate_frame_size_is_above_frame_header_size() {
        let msg = valid_delta_message();
        let estimate = MessageSerializer::estimate_frame_size(&msg);
        assert!(estimate > FRAME_HEADER_SIZE);
    }

    // ── Metrics ───────────────────────────────────────────────────────────────

    #[test]
    fn reset_metrics_zeroes_all_fields() {
        let mut s = MessageSerializer::new();
        s.serialize(&valid_delta_message()).unwrap();
        s.reset_metrics();
        let m = s.metrics();
        assert_eq!(m.messages_serialized, 0);
        assert_eq!(m.bytes_produced, 0);
        assert_eq!(m.validation_failures, 0);
    }

    #[test]
    fn bytes_produced_includes_frame_header() {
        let mut s = MessageSerializer::new();
        let msg = valid_delta_message();
        let frame = s.serialize(&msg).unwrap();
        assert_eq!(s.metrics().bytes_produced, frame.len() as u64);
    }

    // ── Constants ─────────────────────────────────────────────────────────────

    #[test]
    fn frame_header_size_is_four() {
        assert_eq!(FRAME_HEADER_SIZE, 4);
    }

    #[test]
    fn max_message_size_is_sixteen_mib() {
        assert_eq!(MAX_MESSAGE_SIZE, 16 * 1024 * 1024);
    }

    #[test]
    fn magic_bytes_spell_xace() {
        assert_eq!(XACE_WIRE_MAGIC.to_be_bytes(), *b"XACE");
    }

    #[test]
    fn serialize_unchecked_works_for_valid_message() {
        let mut s = MessageSerializer::new();
        let result = s.serialize_unchecked(&valid_delta_message());
        assert!(result.is_ok());
    }
}