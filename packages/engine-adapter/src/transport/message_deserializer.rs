//! Strict deserialization of XACE length-prefixed wire frames.
//!
//! TCP and shared-memory transports deliver arbitrary byte chunks. This module
//! owns the receive buffer, extracts complete frames, rejects malformed input
//! with typed metrics, and returns validated `WireMessage` envelopes.

use crate::transport::message_serializer::{FRAME_HEADER_SIZE, MAX_MESSAGE_SIZE};
use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::wire::wire_message::{WireMessage, XACE_PROTOCOL_VERSION};

const DEFAULT_BUFFER_CAPACITY: usize = 8 * 1024;
const DEFAULT_COMPACTION_THRESHOLD: usize = 1024 * 1024;

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct DeserializerMetrics {
    pub messages_deserialized: u64,
    pub bytes_consumed: u64,
    pub parse_failures: u64,
    pub validation_failures: u64,
    pub oversized_rejections: u64,
    pub protocol_version_mismatches: u64,
    pub incomplete_frames_seen: u64,
    pub malformed_frames: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DeserializeFailureReason {
    InsufficientBytes,
    EmptyPayload,
    OversizedPayload {
        declared_size: usize,
        max_size: usize,
    },
    JsonParseFailure {
        detail: String,
    },
    EnvelopeValidationFailure {
        detail: String,
    },
    ProtocolVersionMismatch {
        found: u32,
        expected: u32,
    },
}

impl std::fmt::Display for DeserializeFailureReason {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InsufficientBytes => f.write_str("insufficient bytes for a complete frame"),
            Self::EmptyPayload => f.write_str("frame payload must not be empty"),
            Self::OversizedPayload {
                declared_size,
                max_size,
            } => write!(
                f,
                "declared frame payload {} bytes exceeds max {} bytes",
                declared_size, max_size
            ),
            Self::JsonParseFailure { detail } => {
                write!(
                    f,
                    "frame payload is not a WireMessage JSON object: {}",
                    detail
                )
            }
            Self::EnvelopeValidationFailure { detail } => {
                write!(f, "wire envelope validation failed: {}", detail)
            }
            Self::ProtocolVersionMismatch { found, expected } => {
                write!(
                    f,
                    "protocol version mismatch: found {}, expected {}",
                    found, expected
                )
            }
        }
    }
}

pub struct MessageDeserializer {
    buffer: Vec<u8>,
    cursor: usize,
    metrics: DeserializerMetrics,
    max_message_size: usize,
    compaction_threshold: usize,
}

impl MessageDeserializer {
    pub fn new() -> Self {
        Self::with_limits(MAX_MESSAGE_SIZE, DEFAULT_COMPACTION_THRESHOLD)
    }

    pub fn with_compaction_threshold(threshold: usize) -> Self {
        Self::with_limits(MAX_MESSAGE_SIZE, threshold)
    }

    pub fn with_max_message_size(max_message_size: usize) -> Self {
        Self::with_limits(max_message_size, DEFAULT_COMPACTION_THRESHOLD)
    }

    pub fn with_limits(max_message_size: usize, compaction_threshold: usize) -> Self {
        Self {
            buffer: Vec::with_capacity(DEFAULT_BUFFER_CAPACITY),
            cursor: 0,
            metrics: DeserializerMetrics::default(),
            max_message_size: max_message_size.max(1),
            compaction_threshold: compaction_threshold.max(FRAME_HEADER_SIZE),
        }
    }

    pub fn push_bytes(&mut self, bytes: &[u8]) {
        if !bytes.is_empty() {
            self.buffer.extend_from_slice(bytes);
        }
    }

    pub fn try_extract_message(&mut self) -> Result<Option<WireMessage>, XaceError> {
        self.maybe_compact();
        let Some(payload_len) = self.peek_payload_len()? else {
            self.metrics.incomplete_frames_seen += 1;
            return Ok(None);
        };

        let total_len = FRAME_HEADER_SIZE
            .checked_add(payload_len)
            .ok_or_else(|| self.reject_current_frame_as_fatal(payload_len))?;

        if self.unprocessed().len() < total_len {
            self.metrics.incomplete_frames_seen += 1;
            return Ok(None);
        }

        let payload_start = self.cursor + FRAME_HEADER_SIZE;
        let payload_end = payload_start + payload_len;
        let payload = self.buffer[payload_start..payload_end].to_vec();
        self.cursor += total_len;
        self.metrics.bytes_consumed += total_len as u64;

        match self.deserialize_payload(&payload) {
            Ok(message) => Ok(Some(message)),
            Err(err) => Err(err),
        }
    }

    pub fn drain_available_messages(&mut self) -> Result<Vec<WireMessage>, XaceError> {
        let mut messages = Vec::new();
        while let Some(message) = self.try_extract_message()? {
            messages.push(message);
        }
        Ok(messages)
    }

    pub fn deserialize_frame(&mut self, frame_bytes: &[u8]) -> Result<WireMessage, XaceError> {
        if frame_bytes.len() < FRAME_HEADER_SIZE {
            self.metrics.incomplete_frames_seen += 1;
            return Err(self.recoverable(
                "deserialize_frame",
                DeserializeFailureReason::InsufficientBytes,
            ));
        }

        let payload_len = Self::read_payload_len(frame_bytes);
        self.validate_declared_payload_len(payload_len, "deserialize_frame")?;
        let total_len = FRAME_HEADER_SIZE + payload_len;
        if frame_bytes.len() < total_len {
            self.metrics.incomplete_frames_seen += 1;
            return Err(self.recoverable(
                "deserialize_frame",
                DeserializeFailureReason::InsufficientBytes,
            ));
        }
        if frame_bytes.len() > total_len {
            self.metrics.malformed_frames += 1;
            return Err(self.recoverable(
                "deserialize_frame",
                DeserializeFailureReason::EnvelopeValidationFailure {
                    detail: format!(
                        "frame contains {} trailing bytes after one complete message",
                        frame_bytes.len() - total_len
                    ),
                },
            ));
        }

        self.metrics.bytes_consumed += total_len as u64;
        self.deserialize_payload(&frame_bytes[FRAME_HEADER_SIZE..])
    }

    pub fn deserialize_payload(&mut self, bytes: &[u8]) -> Result<WireMessage, XaceError> {
        if bytes.is_empty() {
            self.metrics.malformed_frames += 1;
            return Err(self.recoverable(
                "deserialize_payload",
                DeserializeFailureReason::EmptyPayload,
            ));
        }
        if bytes.len() > self.max_message_size {
            self.metrics.oversized_rejections += 1;
            return Err(self.fatal(
                "deserialize_payload",
                DeserializeFailureReason::OversizedPayload {
                    declared_size: bytes.len(),
                    max_size: self.max_message_size,
                },
            ));
        }

        let message: WireMessage = serde_json::from_slice(bytes).map_err(|err| {
            self.metrics.parse_failures += 1;
            self.recoverable(
                "deserialize_payload",
                DeserializeFailureReason::JsonParseFailure {
                    detail: err.to_string(),
                },
            )
        })?;

        if message.protocol_version != XACE_PROTOCOL_VERSION {
            self.metrics.protocol_version_mismatches += 1;
            return Err(self.fatal(
                "deserialize_payload",
                DeserializeFailureReason::ProtocolVersionMismatch {
                    found: message.protocol_version,
                    expected: XACE_PROTOCOL_VERSION,
                },
            ));
        }

        message.validate().map_err(|detail| {
            self.metrics.validation_failures += 1;
            self.recoverable(
                "deserialize_payload",
                DeserializeFailureReason::EnvelopeValidationFailure { detail },
            )
        })?;

        self.metrics.messages_deserialized += 1;
        Ok(message)
    }

    pub fn buffered_bytes(&self) -> usize {
        self.buffer.len().saturating_sub(self.cursor)
    }

    pub fn is_buffer_empty(&self) -> bool {
        self.buffered_bytes() == 0
    }

    pub fn clear_buffer(&mut self) {
        self.buffer.clear();
        self.cursor = 0;
    }

    pub fn compact(&mut self) {
        if self.cursor > 0 {
            self.buffer.drain(..self.cursor);
            self.cursor = 0;
        }
    }

    pub fn max_message_size(&self) -> usize {
        self.max_message_size
    }

    pub fn metrics(&self) -> &DeserializerMetrics {
        &self.metrics
    }

    pub fn reset_metrics(&mut self) {
        self.metrics = DeserializerMetrics::default();
    }

    fn maybe_compact(&mut self) {
        if self.cursor >= self.compaction_threshold {
            self.compact();
        }
    }

    fn unprocessed(&self) -> &[u8] {
        &self.buffer[self.cursor..]
    }

    fn peek_payload_len(&mut self) -> Result<Option<usize>, XaceError> {
        let unprocessed = self.unprocessed();
        if unprocessed.len() < FRAME_HEADER_SIZE {
            return Ok(None);
        }

        let payload_len = Self::read_payload_len(unprocessed);
        self.validate_declared_payload_len(payload_len, "try_extract_message")?;
        Ok(Some(payload_len))
    }

    fn validate_declared_payload_len(
        &mut self,
        payload_len: usize,
        operation: &'static str,
    ) -> Result<(), XaceError> {
        if payload_len == 0 {
            self.metrics.malformed_frames += 1;
            self.cursor = (self.cursor + FRAME_HEADER_SIZE).min(self.buffer.len());
            return Err(self.recoverable(operation, DeserializeFailureReason::EmptyPayload));
        }
        if payload_len > self.max_message_size {
            self.metrics.oversized_rejections += 1;
            self.clear_buffer();
            return Err(self.fatal(
                operation,
                DeserializeFailureReason::OversizedPayload {
                    declared_size: payload_len,
                    max_size: self.max_message_size,
                },
            ));
        }
        Ok(())
    }

    fn reject_current_frame_as_fatal(&mut self, payload_len: usize) -> XaceError {
        self.metrics.oversized_rejections += 1;
        self.clear_buffer();
        self.fatal(
            "try_extract_message",
            DeserializeFailureReason::OversizedPayload {
                declared_size: payload_len,
                max_size: self.max_message_size,
            },
        )
    }

    fn read_payload_len(bytes: &[u8]) -> usize {
        let header: [u8; FRAME_HEADER_SIZE] = bytes[..FRAME_HEADER_SIZE]
            .try_into()
            .expect("caller checked frame header length");
        u32::from_be_bytes(header) as usize
    }

    fn recoverable(&self, operation: &'static str, reason: DeserializeFailureReason) -> XaceError {
        XaceError::RecoverableError {
            message: format!("MessageDeserializer: {}", reason),
            context: ErrorContext::new("MessageDeserializer", operation),
            max_retries: 0,
            retry_count: 0,
        }
    }

    fn fatal(&self, operation: &'static str, reason: DeserializeFailureReason) -> XaceError {
        XaceError::FatalError {
            message: format!("MessageDeserializer: {}", reason),
            context: ErrorContext::new("MessageDeserializer", operation),
            snapshot_recovery_possible: false,
        }
    }
}

impl Default for MessageDeserializer {
    fn default() -> Self {
        Self::new()
    }
}

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

    fn framed(msg: &WireMessage) -> Vec<u8> {
        MessageSerializer::new().serialize(msg).unwrap()
    }

    #[test]
    fn round_trip_from_incremental_buffer() {
        let frame = framed(&valid_delta());
        let mut deserializer = MessageDeserializer::new();

        for byte in &frame[..frame.len() - 1] {
            deserializer.push_bytes(&[*byte]);
            assert!(deserializer.try_extract_message().unwrap().is_none());
        }
        deserializer.push_bytes(&frame[frame.len() - 1..]);

        let restored = deserializer.try_extract_message().unwrap().unwrap();
        assert_eq!(restored, valid_delta());
        assert_eq!(deserializer.metrics().messages_deserialized, 1);
    }

    #[test]
    fn concatenated_frames_drain_in_order() {
        let mut combined = framed(&valid_delta());
        combined.extend_from_slice(&framed(&WireMessage::snapshot(
            "default",
            "0.1.0",
            1,
            10,
            51,
            r#"{"tick":10,"entities":[]}"#,
        )));

        let mut deserializer = MessageDeserializer::new();
        deserializer.push_bytes(&combined);
        let messages = deserializer.drain_available_messages().unwrap();

        assert_eq!(messages.len(), 2);
        assert!(messages[0].is_delta());
        assert!(messages[1].is_snapshot());
        assert!(deserializer.is_buffer_empty());
    }

    #[test]
    fn deserialize_frame_rejects_trailing_bytes() {
        let mut frame = framed(&valid_delta());
        frame.extend_from_slice(b"tail");

        let mut deserializer = MessageDeserializer::new();
        assert!(deserializer.deserialize_frame(&frame).is_err());
        assert_eq!(deserializer.metrics().malformed_frames, 1);
    }

    #[test]
    fn invalid_json_consumes_bad_frame_and_allows_next_frame() {
        let mut combined = MessageSerializer::build_frame(b"not json");
        combined.extend_from_slice(&framed(&valid_delta()));

        let mut deserializer = MessageDeserializer::new();
        deserializer.push_bytes(&combined);

        assert!(deserializer.try_extract_message().is_err());
        let next = deserializer.try_extract_message().unwrap().unwrap();
        assert_eq!(next.sequence_id, 50);
        assert_eq!(deserializer.metrics().parse_failures, 1);
    }

    #[test]
    fn wrong_protocol_version_is_fatal() {
        let mut msg = valid_delta();
        msg.protocol_version = XACE_PROTOCOL_VERSION + 1;
        let payload = serde_json::to_vec(&msg).unwrap();
        let frame = MessageSerializer::build_frame(&payload);

        let mut deserializer = MessageDeserializer::new();
        deserializer.push_bytes(&frame);

        assert!(deserializer.try_extract_message().unwrap_err().is_fatal());
        assert_eq!(deserializer.metrics().protocol_version_mismatches, 1);
    }

    #[test]
    fn oversized_declared_frame_clears_buffer() {
        let mut frame = Vec::new();
        frame.extend_from_slice(&((MAX_MESSAGE_SIZE as u32) + 1).to_be_bytes());
        frame.extend_from_slice(b"partial");

        let mut deserializer = MessageDeserializer::new();
        deserializer.push_bytes(&frame);

        assert!(deserializer.try_extract_message().unwrap_err().is_fatal());
        assert!(deserializer.is_buffer_empty());
        assert_eq!(deserializer.metrics().oversized_rejections, 1);
    }

    #[test]
    fn compact_removes_consumed_bytes() {
        let frame = framed(&valid_delta());
        let mut deserializer = MessageDeserializer::new();
        deserializer.push_bytes(&frame);
        deserializer.try_extract_message().unwrap();
        assert!(deserializer.buffer.len() > 0);
        deserializer.compact();
        assert_eq!(deserializer.buffer.len(), 0);
        assert_eq!(deserializer.cursor, 0);
    }
}
