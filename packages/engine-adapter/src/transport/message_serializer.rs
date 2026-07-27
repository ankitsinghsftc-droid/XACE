//! Length-prefixed serialization for `WireMessage` frames.
//!
//! The transport frame is intentionally simple and language-neutral:
//! four big-endian bytes containing the JSON payload length, followed by a
//! UTF-8 JSON encoded `WireMessage`. TCP and shared-memory transports both use
//! this format so every adapter can share one parser.

use serde::Serialize;
use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::wire::wire_message::WireMessage;

pub const FRAME_HEADER_SIZE: usize = 4;
pub const MAX_MESSAGE_SIZE: usize = 16 * 1024 * 1024;
pub const XACE_WIRE_MAGIC: u32 = 0x5841_4345; // XACE

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct SerializerMetrics {
    pub messages_serialized: u64,
    pub bytes_produced: u64,
    pub validation_failures: u64,
    pub oversized_rejections: u64,
    pub batch_failures: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FrameReadError {
    HeaderIncomplete { available: usize },
    PayloadIncomplete { declared: usize, available: usize },
    OversizedPayload { declared: usize, max: usize },
    EmptyPayload,
}

impl std::fmt::Display for FrameReadError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::HeaderIncomplete { available } => {
                write!(f, "frame header incomplete: {} bytes available", available)
            }
            Self::PayloadIncomplete {
                declared,
                available,
            } => write!(
                f,
                "frame payload incomplete: declared {} bytes, {} bytes available",
                declared, available
            ),
            Self::OversizedPayload { declared, max } => {
                write!(f, "frame payload {} bytes exceeds max {}", declared, max)
            }
            Self::EmptyPayload => f.write_str("frame payload must not be empty"),
        }
    }
}

impl std::error::Error for FrameReadError {}

pub struct MessageSerializer {
    metrics: SerializerMetrics,
    max_message_size: usize,
}

impl MessageSerializer {
    pub fn new() -> Self {
        Self::with_max_message_size(MAX_MESSAGE_SIZE)
    }

    pub fn with_max_message_size(max_message_size: usize) -> Self {
        Self {
            metrics: SerializerMetrics::default(),
            max_message_size,
        }
    }

    pub fn serialize(&mut self, msg: &WireMessage) -> Result<Vec<u8>, XaceError> {
        msg.validate().map_err(|reason| {
            self.metrics.validation_failures += 1;
            validation_error(
                "serialize",
                msg,
                format!("MessageSerializer envelope validation failed: {}", reason),
            )
        })?;

        self.serialize_validated(msg)
    }

    /// Serializes a trusted programmatic message without envelope validation.
    pub fn serialize_unchecked(&mut self, msg: &WireMessage) -> Result<Vec<u8>, XaceError> {
        self.serialize_validated(msg)
    }

    pub fn serialize_typed_payload<T: Serialize>(
        &mut self,
        msg: &WireMessage,
        payload: &T,
    ) -> Result<Vec<u8>, XaceError> {
        let mut msg = msg.clone();
        msg.payload = serde_json::to_string(payload).map_err(|err| {
            fatal_error(
                "serialize_typed_payload",
                msg.tick,
                format!("typed payload JSON serialization failed: {}", err),
            )
        })?;
        self.serialize(&msg)
    }

    pub fn serialize_batch(&mut self, messages: &[WireMessage]) -> Result<Vec<u8>, XaceError> {
        if messages.is_empty() {
            return Ok(Vec::new());
        }

        let mut frames = Vec::with_capacity(messages.len());
        let mut total_len = 0usize;
        for msg in messages {
            if let Err(err) = msg.validate() {
                self.metrics.validation_failures += 1;
                self.metrics.batch_failures += 1;
                return Err(validation_error(
                    "serialize_batch",
                    msg,
                    format!("MessageSerializer batch validation failed: {}", err),
                ));
            }
            let payload = self.encode_payload(msg)?;
            let frame_len = FRAME_HEADER_SIZE + payload.len();
            total_len = total_len.checked_add(frame_len).ok_or_else(|| {
                self.metrics.batch_failures += 1;
                fatal_error(
                    "serialize_batch",
                    msg.tick,
                    "serialized batch size overflowed usize",
                )
            })?;
            frames.push(payload);
        }

        let mut output = Vec::with_capacity(total_len);
        for payload in frames {
            output.extend_from_slice(&Self::build_frame(&payload));
        }

        self.metrics.messages_serialized += messages.len() as u64;
        self.metrics.bytes_produced += output.len() as u64;
        Ok(output)
    }

    fn serialize_validated(&mut self, msg: &WireMessage) -> Result<Vec<u8>, XaceError> {
        let payload = self.encode_payload(msg)?;
        let frame = Self::build_frame(&payload);
        self.metrics.messages_serialized += 1;
        self.metrics.bytes_produced += frame.len() as u64;
        Ok(frame)
    }

    fn encode_payload(&mut self, msg: &WireMessage) -> Result<Vec<u8>, XaceError> {
        let payload = serde_json::to_vec(msg).map_err(|err| {
            self.metrics.validation_failures += 1;
            fatal_error(
                "encode_payload",
                msg.tick,
                format!("WireMessage JSON serialization failed: {}", err),
            )
        })?;

        self.ensure_payload_size(payload.len(), msg.tick)?;
        Ok(payload)
    }

    fn ensure_payload_size(&mut self, len: usize, tick: u64) -> Result<(), XaceError> {
        if len == 0 {
            self.metrics.validation_failures += 1;
            return Err(fatal_error(
                "ensure_payload_size",
                tick,
                "serialized WireMessage payload was empty",
            ));
        }
        if len > self.max_message_size {
            self.metrics.oversized_rejections += 1;
            return Err(fatal_error(
                "ensure_payload_size",
                tick,
                format!(
                    "serialized WireMessage payload is {} bytes, max is {} bytes",
                    len, self.max_message_size
                ),
            ));
        }
        Ok(())
    }

    pub fn build_frame(payload: &[u8]) -> Vec<u8> {
        assert!(
            payload.len() <= u32::MAX as usize,
            "wire frame payload exceeds u32 length prefix"
        );
        let mut frame = Vec::with_capacity(FRAME_HEADER_SIZE + payload.len());
        frame.extend_from_slice(&(payload.len() as u32).to_be_bytes());
        frame.extend_from_slice(payload);
        frame
    }

    pub fn read_frame_length(buffer: &[u8]) -> Option<usize> {
        Self::read_frame_length_checked(buffer).ok()
    }

    pub fn read_frame_length_checked(buffer: &[u8]) -> Result<usize, FrameReadError> {
        if buffer.len() < FRAME_HEADER_SIZE {
            return Err(FrameReadError::HeaderIncomplete {
                available: buffer.len(),
            });
        }
        let header: [u8; FRAME_HEADER_SIZE] = buffer[..FRAME_HEADER_SIZE]
            .try_into()
            .expect("slice length checked above");
        let len = u32::from_be_bytes(header) as usize;
        if len == 0 {
            return Err(FrameReadError::EmptyPayload);
        }
        if len > MAX_MESSAGE_SIZE {
            return Err(FrameReadError::OversizedPayload {
                declared: len,
                max: MAX_MESSAGE_SIZE,
            });
        }
        Ok(len)
    }

    pub fn has_complete_frame(buffer: &[u8]) -> bool {
        Self::extract_frame(buffer).is_some()
    }

    pub fn extract_frame(buffer: &[u8]) -> Option<(&[u8], usize)> {
        Self::extract_frame_checked(buffer).ok()
    }

    pub fn extract_frame_checked(buffer: &[u8]) -> Result<(&[u8], usize), FrameReadError> {
        let payload_len = Self::read_frame_length_checked(buffer)?;
        let total =
            FRAME_HEADER_SIZE
                .checked_add(payload_len)
                .ok_or(FrameReadError::OversizedPayload {
                    declared: payload_len,
                    max: MAX_MESSAGE_SIZE,
                })?;
        if buffer.len() < total {
            return Err(FrameReadError::PayloadIncomplete {
                declared: payload_len,
                available: buffer.len().saturating_sub(FRAME_HEADER_SIZE),
            });
        }
        Ok((&buffer[FRAME_HEADER_SIZE..total], total))
    }

    pub fn max_message_size(&self) -> usize {
        self.max_message_size
    }

    pub fn metrics(&self) -> &SerializerMetrics {
        &self.metrics
    }

    pub fn reset_metrics(&mut self) {
        self.metrics = SerializerMetrics::default();
    }

    pub fn estimate_frame_size(msg: &WireMessage) -> usize {
        FRAME_HEADER_SIZE
            + 192
            + msg.world_id.len()
            + msg.schema_version.len()
            + msg.message_type.name().len()
            + msg.payload.len()
    }
}

impl Default for MessageSerializer {
    fn default() -> Self {
        Self::new()
    }
}

fn validation_error(operation: &str, msg: &WireMessage, message: String) -> XaceError {
    XaceError::ValidationFailure {
        message,
        context: ErrorContext::new("MessageSerializer", operation)
            .with_tick(msg.tick)
            .with_detail("message_type", msg.message_type.to_string())
            .with_detail("sequence_id", msg.sequence_id.to_string()),
        rule_violated: "wire_frame".into(),
        failed_path: String::new(),
    }
}

fn fatal_error(operation: &str, tick: u64, message: impl Into<String>) -> XaceError {
    XaceError::FatalError {
        message: message.into(),
        context: ErrorContext::new("MessageSerializer", operation).with_tick(tick),
        snapshot_recovery_possible: false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn valid_delta_message() -> WireMessage {
        WireMessage::delta(
            "default",
            "0.1.0",
            1,
            42,
            100,
            r#"{"added_components":[],"destroyed_entities":[],"modified_entities":{},"removed_components":[],"schema_version":"0.1.0","sequence_id":100,"spawned_entities":[],"tick":42}"#,
        )
    }

    fn valid_snapshot_message() -> WireMessage {
        WireMessage::snapshot(
            "default",
            "0.1.0",
            1,
            0,
            1,
            r#"{"entities":[],"schema_version":"0.1.0","tick":0}"#,
        )
    }

    #[test]
    fn serialize_produces_framed_json() {
        let mut serializer = MessageSerializer::new();
        let frame = serializer.serialize(&valid_delta_message()).unwrap();
        let (payload, consumed) = MessageSerializer::extract_frame_checked(&frame).unwrap();
        let decoded: WireMessage = serde_json::from_slice(payload).unwrap();

        assert_eq!(consumed, frame.len());
        assert_eq!(decoded.tick, 42);
        assert_eq!(decoded.sequence_id, 100);
        assert_eq!(serializer.metrics().messages_serialized, 1);
        assert_eq!(serializer.metrics().bytes_produced, frame.len() as u64);
    }

    #[test]
    fn serialize_rejects_invalid_envelope() {
        let mut serializer = MessageSerializer::new();
        let mut bad = valid_delta_message();
        bad.world_id.clear();
        assert!(serializer.serialize(&bad).is_err());
        assert_eq!(serializer.metrics().validation_failures, 1);
    }

    #[test]
    fn serialize_rejects_oversized_payload() {
        let mut serializer = MessageSerializer::with_max_message_size(64);
        let err = serializer.serialize_unchecked(&valid_delta_message());
        assert!(err.is_err());
        assert_eq!(serializer.metrics().oversized_rejections, 1);
    }

    #[test]
    fn serialize_same_message_is_deterministic() {
        let mut serializer = MessageSerializer::new();
        let msg = valid_delta_message();
        let a = serializer.serialize(&msg).unwrap();
        let b = serializer.serialize(&msg).unwrap();
        assert_eq!(a, b);
    }

    #[test]
    fn serialize_batch_is_atomic_for_invalid_messages() {
        let mut serializer = MessageSerializer::new();
        let mut bad = valid_delta_message();
        bad.schema_version.clear();
        let result = serializer.serialize_batch(&[valid_delta_message(), bad]);
        assert!(result.is_err());
        assert_eq!(serializer.metrics().messages_serialized, 0);
        assert_eq!(serializer.metrics().bytes_produced, 0);
        assert_eq!(serializer.metrics().batch_failures, 1);
    }

    #[test]
    fn serialize_batch_concatenates_frames() {
        let mut serializer = MessageSerializer::new();
        let batch = serializer
            .serialize_batch(&[valid_delta_message(), valid_snapshot_message()])
            .unwrap();
        let (_, first_consumed) = MessageSerializer::extract_frame_checked(&batch).unwrap();
        let (_, second_consumed) =
            MessageSerializer::extract_frame_checked(&batch[first_consumed..]).unwrap();

        assert_eq!(first_consumed + second_consumed, batch.len());
        assert_eq!(serializer.metrics().messages_serialized, 2);
    }

    #[test]
    fn frame_helpers_distinguish_partial_and_invalid_frames() {
        assert!(matches!(
            MessageSerializer::read_frame_length_checked(&[0, 0, 0]),
            Err(FrameReadError::HeaderIncomplete { available: 3 })
        ));

        let zero = [0, 0, 0, 0];
        assert!(matches!(
            MessageSerializer::read_frame_length_checked(&zero),
            Err(FrameReadError::EmptyPayload)
        ));

        let frame = MessageSerializer::build_frame(b"payload");
        assert!(MessageSerializer::has_complete_frame(&frame));
        assert!(matches!(
            MessageSerializer::extract_frame_checked(&frame[..FRAME_HEADER_SIZE + 2]),
            Err(FrameReadError::PayloadIncomplete { .. })
        ));
    }

    #[test]
    fn extract_frame_handles_concatenated_frames() {
        let frame1 = MessageSerializer::build_frame(b"first");
        let frame2 = MessageSerializer::build_frame(b"second");
        let mut combined = frame1;
        combined.extend_from_slice(&frame2);

        let (payload1, consumed1) = MessageSerializer::extract_frame_checked(&combined).unwrap();
        let (payload2, _) =
            MessageSerializer::extract_frame_checked(&combined[consumed1..]).unwrap();
        assert_eq!(payload1, b"first");
        assert_eq!(payload2, b"second");
    }

    #[test]
    fn metrics_reset_cleanly() {
        let mut serializer = MessageSerializer::new();
        serializer.serialize(&valid_delta_message()).unwrap();
        serializer.reset_metrics();
        assert_eq!(serializer.metrics(), &SerializerMetrics::default());
    }

    #[test]
    fn constants_are_stable() {
        assert_eq!(FRAME_HEADER_SIZE, 4);
        assert_eq!(MAX_MESSAGE_SIZE, 16 * 1024 * 1024);
        assert_eq!(XACE_WIRE_MAGIC.to_be_bytes(), *b"XACE");
    }

    #[test]
    fn estimate_includes_payload_size() {
        let msg = valid_delta_message();
        assert!(MessageSerializer::estimate_frame_size(&msg) > msg.payload.len());
    }
}
