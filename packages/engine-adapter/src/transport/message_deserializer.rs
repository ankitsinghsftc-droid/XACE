//! # Message Deserializer
//!
//! Strict deserialization of length-prefixed byte frames into WireMessage
//! envelopes received over TCP or shared-memory transport layers.
//!
//! ## Companion to MessageSerializer
//! Every frame produced by `MessageSerializer::serialize()` is consumed
//! by `MessageDeserializer::deserialize_frame()`. The two are designed
//! as a matched pair — the frame format, length encoding, and JSON schema
//! are identical on both sides.
//!
//! ## Strict Validation
//! This deserializer is the **first line of defence** against malformed,
//! out-of-version, or adversarial data arriving from the engine adapter.
//! Every deserialized message is:
//!
//! 1. **Size-checked** — payload length is validated against `MAX_MESSAGE_SIZE`
//!    before any allocation larger than the header.
//! 2. **JSON-parsed** — invalid JSON is rejected immediately.
//! 3. **Envelope-validated** — the WireMessage::validate() method checks
//!    protocol version, non-empty fields, and INPUT tick requirements.
//! 4. **Protocol-version-checked** — mismatched XACE_PROTOCOL_VERSION
//!    produces a specific error that triggers handshake renegotiation.
//!
//! ## Incremental Buffer Model
//! The deserializer maintains an internal receive buffer and an internal
//! parse cursor. TCP is a byte stream — messages arrive in arbitrary chunk
//! sizes. The caller pushes received bytes into the buffer and then polls
//! `try_extract_message()` until it returns `None` (no complete frame yet).
//!
//! ```ignore
//! // In the tick receive loop:
//! let raw_bytes = transport.read_available_bytes()?;
//! deserializer.push_bytes(&raw_bytes);
//! while let Some(msg) = deserializer.try_extract_message()? {
//!     handle_message(msg);
//! }
//! ```
//!
//! ## Determinism
//! Deserialization is fully deterministic — same bytes always produce the
//! same WireMessage. The deserializer does not introduce any ordering or
//! state that could affect determinism (D11).

use serde_json;
use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::wire::wire_message::{WireMessage, XACE_PROTOCOL_VERSION};
use crate::transport::message_serializer::{
    FRAME_HEADER_SIZE, MAX_MESSAGE_SIZE,
};

// ── Deserializer Metrics ──────────────────────────────────────────────────────

/// Accumulated metrics for one deserializer instance.
#[derive(Debug, Clone, Default)]
pub struct DeserializerMetrics {
    /// Total messages successfully deserialized.
    pub messages_deserialized: u64,
    /// Total raw bytes consumed from the receive buffer.
    pub bytes_consumed: u64,
    /// Total messages rejected due to JSON parse failure.
    pub parse_failures: u64,
    /// Total messages rejected due to envelope validation failure.
    pub validation_failures: u64,
    /// Messages rejected because payload exceeded MAX_MESSAGE_SIZE.
    pub oversized_rejections: u64,
    /// Messages rejected because protocol version did not match.
    pub protocol_version_mismatches: u64,
}

// ── Deserialize Error Context ─────────────────────────────────────────────────

/// The reason a message was rejected during deserialization.
///
/// More specific than XaceError variants — used internally to update
/// metrics before wrapping in the appropriate XaceError.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DeserializeFailureReason {
    InsufficientBytes,
    OversizedPayload { declared_size: usize },
    JsonParseFailure { detail: String },
    EnvelopeValidationFailure { detail: String },
    ProtocolVersionMismatch { found: u32, expected: u32 },
}

// ── Message Deserializer ──────────────────────────────────────────────────────

/// Deserializes length-prefixed byte frames into validated WireMessage values.
///
/// Maintains an internal receive buffer. Callers push raw bytes in and
/// poll for complete messages. Handles TCP stream fragmentation transparently.
///
/// ## Thread Safety
/// Not `Send` — own one per connection/thread. The transport layer creates
/// one deserializer per peer connection and accesses it from the connection's
/// dedicated receive task.
pub struct MessageDeserializer {
    /// Internal receive buffer. Accumulates bytes until a complete frame arrives.
    /// Bytes before `cursor` have already been processed.
    buffer: Vec<u8>,

    /// Parse cursor — the index in `buffer` where unparsed data begins.
    /// Allows us to avoid shifting the entire buffer on each extraction.
    /// Compacted periodically via `compact()`.
    cursor: usize,

    /// Accumulated metrics.
    metrics: DeserializerMetrics,

    /// Maximum number of bytes to buffer before forcing a compaction.
    /// Prevents unbounded memory growth from a slow consumer.
    compaction_threshold: usize,
}

impl MessageDeserializer {
    // ── Construction ──────────────────────────────────────────────────────────

    /// Creates a new deserializer with an empty receive buffer.
    pub fn new() -> Self {
        Self {
            buffer: Vec::with_capacity(8 * 1024), // 8 KiB initial
            cursor: 0,
            metrics: DeserializerMetrics::default(),
            compaction_threshold: 1024 * 1024, // 1 MiB before compaction
        }
    }

    /// Creates a deserializer with a specific compaction threshold.
    /// Lower threshold = more frequent compaction = less peak memory.
    /// Higher threshold = fewer copies = better throughput.
    pub fn with_compaction_threshold(threshold: usize) -> Self {
        let mut d = Self::new();
        d.compaction_threshold = threshold;
        d
    }

    // ── Primary API ───────────────────────────────────────────────────────────

    /// Appends received bytes to the internal buffer.
    ///
    /// Call this after every successful TCP/SHM read.
    /// Then poll `try_extract_message()` until it returns `None`.
    pub fn push_bytes(&mut self, bytes: &[u8]) {
        if !bytes.is_empty() {
            self.buffer.extend_from_slice(bytes);
        }
    }

    /// Attempts to extract one complete WireMessage from the internal buffer.
    ///
    /// Returns:
    /// - `Ok(Some(msg))` — a complete valid message was extracted
    /// - `Ok(None)` — not enough bytes for a complete frame yet
    /// - `Err(...)` — a complete frame was found but failed validation
    ///
    /// On `Err`, the invalid frame bytes are consumed from the buffer
    /// (they are not retried). The connection should be closed and
    /// restarted — a validation error means something is seriously wrong
    /// with the sender or the byte stream is corrupted.
    ///
    /// Poll this in a loop after `push_bytes()` to drain all buffered frames.
    pub fn try_extract_message(&mut self) -> Result<Option<WireMessage>, XaceError> {
        self.maybe_compact();
        let unprocessed = &self.buffer[self.cursor..];

        // Need at least a frame header
        if unprocessed.len() < FRAME_HEADER_SIZE {
            return Ok(None);
        }

        // Parse the payload length from the header
        let payload_len = {
            let header: [u8; 4] = unprocessed[..4].try_into().unwrap();
            u32::from_be_bytes(header) as usize
        };

        // Safety check before allocating
        if payload_len > MAX_MESSAGE_SIZE {
            let rejected_bytes = FRAME_HEADER_SIZE + payload_len.min(unprocessed.len());
            self.cursor += rejected_bytes.min(unprocessed.len());
            self.metrics.oversized_rejections += 1;
            return Err(self.make_fatal(format!(
                "MessageDeserializer: received oversized frame — \
                 declared payload {} bytes exceeds MAX_MESSAGE_SIZE {} bytes. \
                 Connection must be reset.",
                payload_len, MAX_MESSAGE_SIZE
            )));
        }

        // Not enough bytes for the full payload yet
        if unprocessed.len() < FRAME_HEADER_SIZE + payload_len {
            return Ok(None);
        }

        // Extract the complete payload slice
        let payload_start = self.cursor + FRAME_HEADER_SIZE;
        let payload_end = payload_start + payload_len;
        let payload_bytes = &self.buffer[payload_start..payload_end];

        // Attempt JSON deserialization
        let msg: WireMessage = serde_json::from_slice(payload_bytes).map_err(|e| {
            // Consume the bad frame so we can attempt recovery on the next
            self.cursor = payload_end;
            self.metrics.parse_failures += 1;
            self.metrics.bytes_consumed += (FRAME_HEADER_SIZE + payload_len) as u64;
            XaceError::RecoverableError {
                message: format!(
                    "MessageDeserializer: JSON parse failed — {}. \
                     Frame consumed, attempting to continue.",
                    e
                ),
                context: ErrorContext::new("MessageDeserializer", "try_extract_message"),
                max_retries: 0,
                retry_count: 0,
            }
        })?;

        // Advance cursor past this frame
        self.cursor = payload_end;
        self.metrics.bytes_consumed += (FRAME_HEADER_SIZE + payload_len) as u64;

        // Protocol version check — always fatal regardless of mode (D10)
        if msg.protocol_version != XACE_PROTOCOL_VERSION {
            self.metrics.protocol_version_mismatches += 1;
            return Err(XaceError::FatalError {
                message: format!(
                    "MessageDeserializer: protocol version mismatch — \
                     received {} but this runtime is version {}. \
                     Engine adapter must be updated.",
                    msg.protocol_version, XACE_PROTOCOL_VERSION
                ),
                context: ErrorContext::new("MessageDeserializer", "try_extract_message")
                    .with_detail("received_version", msg.protocol_version.to_string())
                    .with_detail("expected_version", XACE_PROTOCOL_VERSION.to_string()),
                snapshot_recovery_possible: false,
            });
        }

        // Envelope validation
        msg.validate().map_err(|reason| {
            self.metrics.validation_failures += 1;
            XaceError::RecoverableError {
                message: format!(
                    "MessageDeserializer: envelope validation failed — {}",
                    reason
                ),
                context: ErrorContext::new("MessageDeserializer", "try_extract_message")
                    .with_tick(msg.tick)
                    .with_detail("message_type", msg.message_type.to_string()),
                max_retries: 0,
                retry_count: 0,
            }
        })?;

        self.metrics.messages_deserialized += 1;
        Ok(Some(msg))
    }

    /// Deserializes a WireMessage directly from a complete byte slice.
    ///
    /// Used by the shared-memory transport where framing is handled
    /// differently (the SHM header carries the length separately).
    /// The `bytes` slice must contain exactly one serialized WireMessage
    /// with no framing header.
    pub fn deserialize_payload(
        &mut self,
        bytes: &[u8],
    ) -> Result<WireMessage, XaceError> {
        if bytes.len() > MAX_MESSAGE_SIZE {
            self.metrics.oversized_rejections += 1;
            return Err(self.make_fatal(format!(
                "deserialize_payload: {} bytes exceeds MAX_MESSAGE_SIZE",
                bytes.len()
            )));
        }

        let msg: WireMessage = serde_json::from_slice(bytes).map_err(|e| {
            self.metrics.parse_failures += 1;
            XaceError::RecoverableError {
                message: format!("deserialize_payload: JSON parse failed — {}", e),
                context: ErrorContext::new("MessageDeserializer", "deserialize_payload"),
                max_retries: 0,
                retry_count: 0,
            }
        })?;

        if msg.protocol_version != XACE_PROTOCOL_VERSION {
            self.metrics.protocol_version_mismatches += 1;
            return Err(XaceError::FatalError {
                message: format!(
                    "deserialize_payload: protocol version {} != expected {}",
                    msg.protocol_version, XACE_PROTOCOL_VERSION
                ),
                context: ErrorContext::new("MessageDeserializer", "deserialize_payload"),
                snapshot_recovery_possible: false,
            });
        }

        msg.validate().map_err(|reason| {
            self.metrics.validation_failures += 1;
            XaceError::RecoverableError {
                message: format!("deserialize_payload: validation failed — {}", reason),
                context: ErrorContext::new("MessageDeserializer", "deserialize_payload")
                    .with_tick(msg.tick),
                max_retries: 0,
                retry_count: 0,
            }
        })?;

        self.metrics.messages_deserialized += 1;
        self.metrics.bytes_consumed += bytes.len() as u64;
        Ok(msg)
    }

    // ── Buffer Management ─────────────────────────────────────────────────────

    /// Returns the number of unprocessed bytes currently buffered.
    pub fn buffered_bytes(&self) -> usize {
        self.buffer.len() - self.cursor
    }

    /// Returns true if the buffer is empty (no unprocessed bytes).
    pub fn is_buffer_empty(&self) -> bool {
        self.buffered_bytes() == 0
    }

    /// Discards all buffered bytes. Called on connection reset.
    pub fn clear_buffer(&mut self) {
        self.buffer.clear();
        self.cursor = 0;
    }

    /// Compacts the buffer by removing already-processed bytes.
    ///
    /// This copy is O(remaining bytes). Called when `cursor` exceeds
    /// the `compaction_threshold` to prevent unbounded buffer growth.
    pub fn compact(&mut self) {
        if self.cursor > 0 {
            self.buffer.drain(..self.cursor);
            self.cursor = 0;
        }
    }

    /// Compacts the buffer if the cursor has advanced past the threshold.
    fn maybe_compact(&mut self) {
        if self.cursor >= self.compaction_threshold {
            self.compact();
        }
    }

    // ── Metrics & Inspection ──────────────────────────────────────────────────

    /// Returns accumulated deserialization metrics.
    pub fn metrics(&self) -> &DeserializerMetrics {
        &self.metrics
    }

    /// Resets metrics without affecting the buffer state.
    pub fn reset_metrics(&mut self) {
        self.metrics = DeserializerMetrics::default();
    }

    // ── Internal Helpers ──────────────────────────────────────────────────────

    fn make_fatal(&self, message: String) -> XaceError {
        XaceError::FatalError {
            message,
            context: ErrorContext::new("MessageDeserializer", "try_extract_message"),
            snapshot_recovery_possible: false,
        }
    }
}

impl Default for MessageDeserializer {
    fn default() -> Self {
        Self::new()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::transport::message_serializer::MessageSerializer;

    fn valid_delta() -> WireMessage {
        WireMessage::delta(
            "default",
            "0.1.0",
            1,
            10,
            50,
            r#"{"tick":10,"sequence_id":50,"schema_version":"0.1.0","spawned_entities":[],"added_components":[],"modified_entities":{},"removed_components":[],"destroyed_entities":[]}"#,
        )
    }

    fn roundtrip(msg: &WireMessage) -> WireMessage {
        let mut ser = MessageSerializer::new();
        let frame = ser.serialize(msg).unwrap();
        let mut deser = MessageDeserializer::new();
        deser.push_bytes(&frame);
        deser.try_extract_message().unwrap().unwrap()
    }

    // ── Round-trip ────────────────────────────────────────────────────────────

    #[test]
    fn delta_message_roundtrip_preserves_all_fields() {
        let original = valid_delta();
        let restored = roundtrip(&original);
        assert_eq!(restored.tick, original.tick);
        assert_eq!(restored.sequence_id, original.sequence_id);
        assert_eq!(restored.schema_version, original.schema_version);
        assert_eq!(restored.execution_plan_version, original.execution_plan_version);
        assert_eq!(restored.world_id, original.world_id);
        assert_eq!(restored.message_type, original.message_type);
        assert_eq!(restored.payload, original.payload);
    }

    #[test]
    fn snapshot_message_roundtrip() {
        let msg = WireMessage::snapshot(
            "world-abc",
            "0.1.0",
            1,
            0,
            1,
            r#"{"tick":0,"entities":[]}"#,
        );
        let restored = roundtrip(&msg);
        assert_eq!(restored.world_id, "world-abc");
        assert!(restored.is_snapshot());
    }

    #[test]
    fn feedback_message_roundtrip() {
        let msg = WireMessage::feedback(
            "default",
            "0.1.0",
            1,
            5,
            3,
            r#"{"feedback_type":"ANIMATION_STATE_UPDATE"}"#,
        );
        let restored = roundtrip(&msg);
        assert!(restored.is_feedback());
        assert_eq!(restored.tick, 5);
    }

    // ── Incremental Receive (TCP Stream Simulation) ───────────────────────────

    #[test]
    fn partial_frame_returns_none_until_complete() {
        let mut ser = MessageSerializer::new();
        let frame = ser.serialize(&valid_delta()).unwrap();
        let mut deser = MessageDeserializer::new();

        // Feed bytes in tiny chunks
        for i in 0..frame.len() {
            deser.push_bytes(&frame[i..i + 1]);
            if i < frame.len() - 1 {
                assert!(
                    deser.try_extract_message().unwrap().is_none(),
                    "Partial frame at byte {} must return None",
                    i
                );
            }
        }
        // Now the last byte was pushed — should have a complete message
        assert!(deser.try_extract_message().unwrap().is_some());
    }

    #[test]
    fn two_concatenated_frames_both_extracted() {
        let mut ser = MessageSerializer::new();
        let msg1 = valid_delta();
        let msg2 = WireMessage::snapshot(
            "default", "0.1.0", 1, 0, 1, r#"{"tick":0}"#
        );
        let frame1 = ser.serialize(&msg1).unwrap();
        let frame2 = ser.serialize(&msg2).unwrap();

        let mut combined = frame1;
        combined.extend_from_slice(&frame2);

        let mut deser = MessageDeserializer::new();
        deser.push_bytes(&combined);

        let m1 = deser.try_extract_message().unwrap().unwrap();
        let m2 = deser.try_extract_message().unwrap().unwrap();
        assert!(m1.is_delta());
        assert!(m2.is_snapshot());
        assert!(deser.try_extract_message().unwrap().is_none());
    }

    #[test]
    fn empty_push_does_not_affect_state() {
        let mut deser = MessageDeserializer::new();
        deser.push_bytes(&[]);
        assert!(deser.is_buffer_empty());
        assert!(deser.try_extract_message().unwrap().is_none());
    }

    // ── Validation ────────────────────────────────────────────────────────────

    #[test]
    fn wrong_protocol_version_returns_fatal_error() {
        let mut msg = valid_delta();
        msg.protocol_version = 99; // wrong version

        let mut ser = MessageSerializer::new();
        // Bypass validation for test — use unchecked
        let payload = serde_json::to_vec(&msg).unwrap();
        let frame = MessageSerializer::build_frame(&payload);

        let mut deser = MessageDeserializer::new();
        deser.push_bytes(&frame);
        let result = deser.try_extract_message();
        assert!(result.is_err());
        assert_eq!(deser.metrics().protocol_version_mismatches, 1);
    }

    #[test]
    fn oversized_frame_returns_fatal_error() {
        // Craft a frame with an enormous declared size
        let mut frame = vec![0u8; 4];
        let oversized = (MAX_MESSAGE_SIZE + 1) as u32;
        frame[..4].copy_from_slice(&oversized.to_be_bytes());

        let mut deser = MessageDeserializer::new();
        deser.push_bytes(&frame);
        let result = deser.try_extract_message();
        assert!(result.is_err());
        assert_eq!(deser.metrics().oversized_rejections, 1);
    }

    #[test]
    fn invalid_json_returns_recoverable_error() {
        // Build a frame with valid length but garbage JSON
        let garbage = b"not json at all !!!";
        let frame = MessageSerializer::build_frame(garbage);

        let mut deser = MessageDeserializer::new();
        deser.push_bytes(&frame);
        let result = deser.try_extract_message();
        assert!(result.is_err());
        assert_eq!(deser.metrics().parse_failures, 1);
    }

    #[test]
    fn deserialize_payload_succeeds_for_valid_bytes() {
        let msg = valid_delta();
        let bytes = serde_json::to_vec(&msg).unwrap();
        let mut deser = MessageDeserializer::new();
        let result = deser.deserialize_payload(&bytes);
        assert!(result.is_ok());
        assert_eq!(result.unwrap().tick, 10);
    }

    // ── Buffer Management ─────────────────────────────────────────────────────

    #[test]
    fn buffered_bytes_decreases_after_extraction() {
        let mut ser = MessageSerializer::new();
        let frame = ser.serialize(&valid_delta()).unwrap();
        let frame_len = frame.len();

        let mut deser = MessageDeserializer::new();
        deser.push_bytes(&frame);
        assert_eq!(deser.buffered_bytes(), frame_len);

        deser.try_extract_message().unwrap();
        // After extraction, buffer should shrink (cursor advanced)
        // Note: buffer may not be compacted yet, but buffered_bytes() = len - cursor
        assert_eq!(deser.buffered_bytes(), 0);
    }

    #[test]
    fn clear_buffer_resets_all_state() {
        let mut ser = MessageSerializer::new();
        let frame = ser.serialize(&valid_delta()).unwrap();
        let mut deser = MessageDeserializer::new();
        deser.push_bytes(&frame);
        deser.clear_buffer();
        assert!(deser.is_buffer_empty());
        assert_eq!(deser.buffered_bytes(), 0);
    }

    #[test]
    fn compact_removes_processed_bytes() {
        let mut ser = MessageSerializer::new();
        let frame = ser.serialize(&valid_delta()).unwrap();
        let mut deser = MessageDeserializer::new();
        deser.push_bytes(&frame);
        deser.try_extract_message().unwrap();
        // Cursor has advanced but buffer may still hold old bytes
        deser.compact();
        // After compact, buffer.len() == 0 since all bytes were consumed
        assert_eq!(deser.buffer.len(), 0);
        assert_eq!(deser.cursor, 0);
    }

    // ── Metrics ───────────────────────────────────────────────────────────────

    #[test]
    fn successful_deserialization_increments_metric() {
        let mut ser = MessageSerializer::new();
        let frame = ser.serialize(&valid_delta()).unwrap();
        let mut deser = MessageDeserializer::new();
        deser.push_bytes(&frame);
        deser.try_extract_message().unwrap();
        assert_eq!(deser.metrics().messages_deserialized, 1);
        assert!(deser.metrics().bytes_consumed > 0);
    }

    #[test]
    fn reset_metrics_does_not_affect_buffer() {
        let mut ser = MessageSerializer::new();
        let frame = ser.serialize(&valid_delta()).unwrap();
        let mut deser = MessageDeserializer::new();
        deser.push_bytes(&frame);
        deser.reset_metrics();
        // Buffer still has the frame
        assert!(!deser.is_buffer_empty());
        // But metrics are zeroed
        assert_eq!(deser.metrics().messages_deserialized, 0);
    }
}