//! # Message Type
//!
//! Defines the types of messages that flow between the XACE runtime
//! and the engine adapter over the wire protocol.
//!
//! ## Wire Protocol Overview
//! XACE communicates with engine adapters via a TCP socket transport
//! (Phase 7). Every message is a WireMessage envelope containing
//! a MessageType discriminant and a typed payload.
//!
//! ## Message Flow
//! XACE → Engine: SNAPSHOT, DELTA, EVENT, CONTROL
//! Engine → XACE: INPUT, FEEDBACK
//!
//! ## Determinism
//! Message type discriminants are stable u8 values.
//! They never change once assigned — changing them breaks
//! all engine adapters built against this protocol version.
//! Treat these values as a frozen public API.

use serde::{Deserialize, Serialize};

// ── Message Type ──────────────────────────────────────────────────────────────

/// The type of a WireMessage.
///
/// Determines how the engine adapter deserializes the payload.
/// Serialized as a u8 discriminant for minimal wire overhead.
///
/// ## Stability
/// These discriminant values are part of the public wire protocol.
/// They are frozen after v1 ships — never renumber or remove.
/// Add new types only at the end of the enum.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[repr(u8)]
pub enum MessageType {
    /// Full world state snapshot.
    ///
    /// Sent by XACE to engine adapter on:
    /// - Initial connection (engine needs full world state)
    /// - Desync recovery (engine sequence gap detected)
    /// - Explicit SNAPSHOT request from engine
    ///
    /// Payload: SnapshotPayload
    /// Direction: XACE → Engine
    Snapshot = 0,

    /// Minimal per-tick state change.
    ///
    /// Sent by XACE to engine adapter every tick that has changes.
    /// Contains only what changed — not the full world state.
    /// Empty ticks (no changes) produce no DELTA message.
    ///
    /// Payload: DeltaPayload
    /// Direction: XACE → Engine
    Delta = 1,

    /// Player or AI input packet.
    ///
    /// Sent by engine adapter to XACE runtime every tick.
    /// Contains all input actions for the current tick.
    /// Always includes the tick it was generated on (I14).
    /// Applied at tick boundaries only (D12).
    ///
    /// Payload: InputPayload (defined in Phase 7)
    /// Direction: Engine → XACE
    Input = 2,

    /// Discrete game event notification.
    ///
    /// Sent by XACE to engine adapter when a game event occurs
    /// that the engine needs to act on (trigger animation, play audio).
    /// Engine receives but never modifies authoritative state from events.
    ///
    /// Payload: EventPayload (wire version)
    /// Direction: XACE → Engine
    Event = 3,

    /// Control and protocol management message.
    ///
    /// Used for: handshake, version negotiation, ping/pong,
    /// SNAPSHOT request, reconnect, disconnect notification.
    ///
    /// Payload: ControlPayload (defined in Phase 7)
    /// Direction: Bidirectional
    Control = 4,

    /// Engine feedback batch.
    ///
    /// Sent by engine adapter to XACE every tick.
    /// Contains animation state updates, physics results,
    /// visibility query results, audio completion, and more.
    /// Processed by XACE at tick boundaries only (I13, Audit 6).
    ///
    /// Payload: FeedbackPayload
    /// Direction: Engine → XACE
    Feedback = 5,
}

impl MessageType {
    /// Returns the u8 wire discriminant for this message type.
    /// Used for compact serialization — one byte on the wire.
    pub fn as_u8(&self) -> u8 {
        *self as u8
    }

    /// Constructs a MessageType from its wire discriminant.
    /// Returns None if the value is not a valid message type.
    pub fn from_u8(value: u8) -> Option<Self> {
        match value {
            0 => Some(MessageType::Snapshot),
            1 => Some(MessageType::Delta),
            2 => Some(MessageType::Input),
            3 => Some(MessageType::Event),
            4 => Some(MessageType::Control),
            5 => Some(MessageType::Feedback),
            _ => None,
        }
    }

    /// Returns true if this message type flows from XACE to the engine.
    pub fn is_xace_to_engine(&self) -> bool {
        matches!(
            self,
            MessageType::Snapshot
                | MessageType::Delta
                | MessageType::Event
        )
    }

    /// Returns true if this message type flows from engine to XACE.
    pub fn is_engine_to_xace(&self) -> bool {
        matches!(self, MessageType::Input | MessageType::Feedback)
    }

    /// Returns true if this message type is bidirectional.
    pub fn is_bidirectional(&self) -> bool {
        matches!(self, MessageType::Control)
    }

    /// Returns a human-readable name for this message type.
    pub fn name(&self) -> &'static str {
        match self {
            MessageType::Snapshot => "SNAPSHOT",
            MessageType::Delta => "DELTA",
            MessageType::Input => "INPUT",
            MessageType::Event => "EVENT",
            MessageType::Control => "CONTROL",
            MessageType::Feedback => "FEEDBACK",
        }
    }
}

impl std::fmt::Display for MessageType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.name())
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn all_types_have_unique_discriminants() {
        let types = [
            MessageType::Snapshot,
            MessageType::Delta,
            MessageType::Input,
            MessageType::Event,
            MessageType::Control,
            MessageType::Feedback,
        ];
        let mut seen = std::collections::HashSet::new();
        for t in types {
            assert!(seen.insert(t.as_u8()), "Duplicate discriminant: {}", t.as_u8());
        }
    }

    #[test]
    fn roundtrip_u8_conversion() {
        let types = [
            MessageType::Snapshot,
            MessageType::Delta,
            MessageType::Input,
            MessageType::Event,
            MessageType::Control,
            MessageType::Feedback,
        ];
        for t in types {
            let byte = t.as_u8();
            let restored = MessageType::from_u8(byte).unwrap();
            assert_eq!(t, restored);
        }
    }

    #[test]
    fn invalid_discriminant_returns_none() {
        assert!(MessageType::from_u8(6).is_none());
        assert!(MessageType::from_u8(255).is_none());
    }

    #[test]
    fn direction_classifications_correct() {
        assert!(MessageType::Snapshot.is_xace_to_engine());
        assert!(MessageType::Delta.is_xace_to_engine());
        assert!(MessageType::Event.is_xace_to_engine());
        assert!(!MessageType::Input.is_xace_to_engine());
        assert!(!MessageType::Feedback.is_xace_to_engine());
    }

    #[test]
    fn engine_to_xace_correct() {
        assert!(MessageType::Input.is_engine_to_xace());
        assert!(MessageType::Feedback.is_engine_to_xace());
        assert!(!MessageType::Snapshot.is_engine_to_xace());
        assert!(!MessageType::Delta.is_engine_to_xace());
    }

    #[test]
    fn control_is_bidirectional() {
        assert!(MessageType::Control.is_bidirectional());
        assert!(!MessageType::Snapshot.is_bidirectional());
    }

    #[test]
    fn display_is_uppercase_name() {
        assert_eq!(MessageType::Snapshot.to_string(), "SNAPSHOT");
        assert_eq!(MessageType::Feedback.to_string(), "FEEDBACK");
    }

    #[test]
    fn snapshot_discriminant_is_zero() {
        assert_eq!(MessageType::Snapshot.as_u8(), 0);
    }

    #[test]
    fn feedback_discriminant_is_five() {
        assert_eq!(MessageType::Feedback.as_u8(), 5);
    }
}