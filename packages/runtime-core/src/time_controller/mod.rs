//! # Time Controller Module
//! Fixed-timestep time controller and deterministic RNG.

pub mod deterministic_rng;
pub mod time_controller;

#[cfg(test)]
mod tests;

pub use deterministic_rng::DeterministicRng;
pub use time_controller::{TimeController, TimeMode};
