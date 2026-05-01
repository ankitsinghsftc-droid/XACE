//! # Time Controller Module
//! Fixed-timestep time controller and deterministic RNG.

pub mod time_controller;
pub mod deterministic_rng;

#[cfg(test)]
mod tests;

pub use time_controller::{TimeController, TimeMode};
pub use deterministic_rng::DeterministicRng;