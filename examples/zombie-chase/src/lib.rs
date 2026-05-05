//! # XACE Zombie Chase — Phase 9 Minimal Example Game
//!
//! This crate is the Phase 9 vertical slice: a minimal zombie chase game
//! that proves XACE's determinism guarantee (Milestone 1).
//!
//! ## How to Run the Key Test
//! ```
//! cargo test -p xace-zombie-chase three_runs_seed_42_tick_1000_hash_identical
//! ```
//!
//! If it passes: "ARCHITECTURE PROVEN REAL." Everything after Phase 9 is expansion.
//!
//! ## Crate Structure
//! - `cgs`     — Canonical Game Schema: component IDs, actor definitions, JSON helpers
//! - `runner`  — Simulation runner: wires runtime + systems, returns world hashes
//! - `systems` — Five ISystem implementations: Input, Movement, AI, Damage, Death

pub mod cgs;
pub mod runner;
pub mod systems;

/// Runs the zombie chase simulation and returns world_hash per tick.
///
/// ## Determinism Contract
/// `run(seed, ticks)` called with identical arguments on any machine,
/// OS, or Rust version must return byte-identical results.
///
/// ## Milestone 1
/// ```
/// let run_a = xace_zombie_chase::run(42, 1000);
/// let run_b = xace_zombie_chase::run(42, 1000);
/// let run_c = xace_zombie_chase::run(42, 1000);
/// assert_eq!(run_a, run_b);  // must pass
/// assert_eq!(run_a, run_c);  // must pass
/// // If both pass: XACE architecture is proven deterministic.
/// ```
pub fn run(world_seed: u64, num_ticks: u64) -> Vec<String> {
    runner::run(world_seed, num_ticks)
}