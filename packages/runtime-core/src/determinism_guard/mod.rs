//! # Determinism Guard Module
//!
//! Determinism guard primitives for XACE determinism rules (D1-D15).
//!
//! RuntimeOrchestrator owns the live guard/interceptor for ticking sessions and
//! PhaseOrchestrator calls the boundary/version/hash hooks during tick
//! execution. Cross-platform replay certification remains a later X10 gate.
//!
//! ## Files in this module
//!
//! - `determinism_guard` - 6 runtime hooks, 3 guard modes, D-rule enforcement
//! - `world_hasher` - SHA-256 world state hash (D9, D11)
//! - `side_channel_hash_policy` - X10-011 authoritative side-channel policy
//! - `replay_validator` - GoldenLog recording plus tick-by-tick replay comparison
//! - `rng_interceptor` - Thread-local window enforcement and D6 violation detection

pub mod determinism_guard;
pub mod replay_validator;
pub mod rng_interceptor;
pub mod side_channel_hash_policy;
pub mod world_hasher;

#[cfg(test)]
mod tests;

// Re-export the most commonly used types at module level.
pub use determinism_guard::DeterminismGuard;
pub use replay_validator::{GoldenLog, ReplayDivergenceReport, ReplayStatus, ReplayValidator};
pub use rng_interceptor::{DeterministicWindow, InterceptorMetrics, RngInterceptor};
pub use side_channel_hash_policy::{
    policy_for, side_channel_hash_policies, validate_side_channel_hash_policy, SideChannel,
    SideChannelHashDisposition, SideChannelHashPolicy, SideChannelPolicyError,
    REQUIRED_SIDE_CHANNELS,
};
pub use world_hasher::WorldHasher;
