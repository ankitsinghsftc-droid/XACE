// xace-engine-adapter — Wire protocol, transport, delta sync
// Translates StateDelta into engine-specific commands. Build Phases 7-8.

pub mod adapter_contract;
pub mod delta_sync;
pub mod ffi;
#[cfg(test)]
mod tests;
pub mod transport;
#[path = "transport/transport_mode.rs"]
pub mod transport_mode;
#[path = "transport/transport_selector.rs"]
pub mod transport_selector;
