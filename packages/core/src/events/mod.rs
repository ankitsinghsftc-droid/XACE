//! # Events Module
//! Event types and the Event struct for the XACE EventBus.

pub mod event_type;
pub mod event_struct;

pub use event_type::EventType;
pub use event_struct::{Event, EventId, EventPayload};