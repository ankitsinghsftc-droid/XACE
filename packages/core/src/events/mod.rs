//! # Events Module
//! Event types and the Event struct for the XACE EventBus.

pub mod event_struct;
pub mod event_type;

pub use event_struct::{Event, EventId, EventPayload};
pub use event_type::EventType;
