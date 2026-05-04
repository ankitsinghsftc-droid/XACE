//! # Determinism Guard Module
//!
//! Runtime enforcement of all 15 XACE determinism rules (D1–D15).
//!
//! ## Files in this module
//!
//! - `determinism_guard`  — 6 runtime hooks, 3 guard modes, D-rule enforcement
//! - `world_hasher`       — SHA-256 world state hash (D9, D11)
//! - `replay_validator`   — GoldenLog recording + tick-by-tick replay comparison (D14)
//! - `rng_interceptor`    — Thread-local window enforcement, D6 violation detection
//!
//! ## Integration Order
//! The PhaseOrchestrator wires these together:
//! 1. RngInterceptor::open_window() before each system
//! 2. DeterminismGuard::hook_system_execute() before running the system
//! 3. System runs — any RNG access goes through RngInterceptor::request_rng()
//! 4. DeterminismGuard::hook_phase_end() after all systems in a phase
//! 5. DeterminismGuard::hook_tick_end() with the final snapshot
//!    → calls WorldHasher::compute() internally
//!    → calls ReplayValidator::record_tick() or validate_tick() depending on mode

pub mod determinism_guard;
pub mod world_hasher;
pub mod replay_validator;
pub mod rng_interceptor;

#[cfg(test)]
mod tests;

// Re-export the most commonly used types at module level
pub use determinism_guard::DeterminismGuard;
pub use world_hasher::WorldHasher;
pub use replay_validator::{GoldenLog, ReplayDivergenceReport, ReplayStatus, ReplayValidator};
pub use rng_interceptor::{DeterministicWindow, InterceptorMetrics, RngInterceptor};