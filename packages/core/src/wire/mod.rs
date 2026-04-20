//! # Wire Module
//! Wire protocol types for XACE ↔ Engine adapter communication.

pub mod message_type;
pub mod feedback_payload;
pub mod delta_payload;
pub mod snapshot_payload;
pub mod wire_message;

pub use message_type::MessageType;
pub use feedback_payload::FeedbackPayload;
pub use delta_payload::DeltaPayload;
pub use snapshot_payload::SnapshotPayload;
pub use wire_message::WireMessage;