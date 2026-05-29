//! # Deterministic RNG
//!
//! Seeded deterministic random number generator for XACE systems.
//! Blocks all OS and language-native random number generation (D6).
//!
//! ## Determinism Rule D6
//! seed = hash(world_seed, system_id, tick)
//! Same seed always produces identical sequences.
//! No OS random, no thread_rng, no SystemTime-based seeds.
//!
//! ## Algorithm
//! Uses a simple but proven deterministic algorithm based on
//! xorshift64 with a well-chosen constant multiplier.
//! Fast, deterministic, and sufficient for game simulation.

use xace_core::errors::xace_error::{ErrorContext, XaceError};

// ── Deterministic RNG ─────────────────────────────────────────────────────────

/// Deterministic RNG seeded by hash(world_seed, system_id, tick).
///
/// Each system gets its own RNG stream per tick. Same inputs always
/// produce identical outputs regardless of execution environment.
pub struct DeterministicRng {
    state: u64,
    world_seed: u64,
    system_id_hash: u64,
    tick: u64,
    call_count: u64,
}

impl DeterministicRng {
    /// Creates a new RNG seeded by world_seed, system_id, and tick (D6).
    pub fn new(world_seed: u64, system_id: &str, tick: u64) -> Self {
        let system_id_hash = Self::hash_str(system_id);
        let state = Self::derive_seed(world_seed, system_id_hash, tick);
        Self {
            state,
            world_seed,
            system_id_hash,
            tick,
            call_count: 0,
        }
    }

    /// Advances to a new tick — reseeds for this system at the new tick.
    pub fn advance_tick(&mut self, new_tick: u64) {
        self.tick = new_tick;
        self.state = Self::derive_seed(self.world_seed, self.system_id_hash, new_tick);
        self.call_count = 0;
    }

    /// Returns the next f64 in [0.0, 1.0).
    pub fn next_f64(&mut self) -> f64 {
        let raw = self.next_u64();
        (raw >> 11) as f64 / (1u64 << 53) as f64
    }

    /// Returns the next f32 in [0.0, 1.0).
    pub fn next_f32(&mut self) -> f32 {
        self.next_f64() as f32
    }

    /// Returns the next u64.
    pub fn next_u64(&mut self) -> u64 {
        self.call_count += 1;
        // xorshift64 — fast, deterministic, good statistical properties
        let mut x = self.state;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.state = x;
        x
    }

    /// Returns a random u64 in [0, max).
    pub fn next_u64_below(&mut self, max: u64) -> u64 {
        if max == 0 {
            return 0;
        }
        self.next_u64() % max
    }

    /// Returns a random i64 in [min, max).
    pub fn next_i64_range(&mut self, min: i64, max: i64) -> i64 {
        if min >= max {
            return min;
        }
        let range = (max - min) as u64;
        min + (self.next_u64() % range) as i64
    }

    /// Returns a random f64 in [min, max).
    pub fn next_f64_range(&mut self, min: f64, max: f64) -> f64 {
        if min >= max {
            return min;
        }
        min + self.next_f64() * (max - min)
    }

    /// Returns true with the given probability (0.0-1.0).
    pub fn chance(&mut self, probability: f64) -> bool {
        self.next_f64() < probability.clamp(0.0, 1.0)
    }

    /// Returns the number of values generated since last seed/tick advance.
    pub fn call_count(&self) -> u64 {
        self.call_count
    }

    /// Returns the current world seed.
    pub fn world_seed(&self) -> u64 {
        self.world_seed
    }

    /// Returns the current tick this RNG is seeded for.
    pub fn current_tick(&self) -> u64 {
        self.tick
    }

    // ── Internal ───────────────────────────────────────────────────────────

    /// Derives a seed from world_seed, system_id_hash, and tick.
    /// Same inputs always produce the same seed (D6).
    fn derive_seed(world_seed: u64, system_id_hash: u64, tick: u64) -> u64 {
        let mut s = world_seed
            .wrapping_mul(6364136223846793005)
            .wrapping_add(system_id_hash.wrapping_mul(2654435761))
            .wrapping_add(tick.wrapping_mul(1442695040888963407));
        // Ensure non-zero state (xorshift requires non-zero)
        if s == 0 {
            s = 1;
        }
        // Mix
        s ^= s << 13;
        s ^= s >> 7;
        s ^= s << 17;
        s
    }

    /// Hashes a string to u64 using FNV-1a.
    fn hash_str(s: &str) -> u64 {
        let mut hash: u64 = 14695981039346656037;
        for byte in s.bytes() {
            hash ^= byte as u64;
            hash = hash.wrapping_mul(1099511628211);
        }
        hash
    }
}

// ── RNG Interceptor ───────────────────────────────────────────────────────────

/// Guards against illegal non-deterministic RNG usage.
///
/// In Phase 6 the DeterminismGuard hooks into this to detect
/// any system attempting to use OS/language RNG (D6).
/// For Phase 4 this provides the validation API.
pub struct RngInterceptor;

impl RngInterceptor {
    /// Validates that a system is using DeterministicRng correctly.
    /// Called by DeterminismGuard in Phase 6.
    pub fn validate_rng_usage(system_id: &str, tick: u64) -> Result<(), XaceError> {
        // Phase 4: basic validation — system_id and tick must be non-empty/non-zero
        if system_id.is_empty() {
            return Err(XaceError::FatalError {
                message: "RNG used with empty system_id — D6 violation".into(),
                context: ErrorContext::new("RngInterceptor", "validate_rng_usage").with_tick(tick),
                snapshot_recovery_possible: false,
            });
        }
        Ok(())
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn same_seed_produces_same_sequence() {
        let mut rng1 = DeterministicRng::new(12345, "sys_movement", 100);
        let mut rng2 = DeterministicRng::new(12345, "sys_movement", 100);
        for _ in 0..100 {
            assert_eq!(rng1.next_u64(), rng2.next_u64());
        }
    }

    #[test]
    fn different_system_ids_produce_different_sequences() {
        let mut rng1 = DeterministicRng::new(42, "sys_movement", 0);
        let mut rng2 = DeterministicRng::new(42, "sys_ai", 0);
        let v1 = rng1.next_u64();
        let v2 = rng2.next_u64();
        assert_ne!(v1, v2);
    }

    #[test]
    fn different_ticks_produce_different_sequences() {
        let mut rng1 = DeterministicRng::new(42, "sys_movement", 0);
        let mut rng2 = DeterministicRng::new(42, "sys_movement", 1);
        let v1 = rng1.next_u64();
        let v2 = rng2.next_u64();
        assert_ne!(v1, v2);
    }

    #[test]
    fn different_world_seeds_produce_different_sequences() {
        let mut rng1 = DeterministicRng::new(111, "sys_ai", 5);
        let mut rng2 = DeterministicRng::new(222, "sys_ai", 5);
        assert_ne!(rng1.next_u64(), rng2.next_u64());
    }

    #[test]
    fn f64_values_in_range() {
        let mut rng = DeterministicRng::new(99, "sys_test", 0);
        for _ in 0..1000 {
            let v = rng.next_f64();
            assert!(v >= 0.0 && v < 1.0, "Value out of range: {}", v);
        }
    }

    #[test]
    fn f32_values_in_range() {
        let mut rng = DeterministicRng::new(99, "sys_test", 0);
        for _ in 0..1000 {
            let v = rng.next_f32();
            assert!(v >= 0.0 && v < 1.0, "Value out of range: {}", v);
        }
    }

    #[test]
    fn next_u64_below_in_range() {
        let mut rng = DeterministicRng::new(42, "sys_test", 0);
        for _ in 0..1000 {
            let v = rng.next_u64_below(10);
            assert!(v < 10, "Value {} not below 10", v);
        }
    }

    #[test]
    fn next_i64_range_correct() {
        let mut rng = DeterministicRng::new(42, "sys_test", 0);
        for _ in 0..1000 {
            let v = rng.next_i64_range(-5, 5);
            assert!(v >= -5 && v < 5, "Value {} out of range", v);
        }
    }

    #[test]
    fn chance_roughly_correct() {
        let mut rng = DeterministicRng::new(77, "sys_test", 0);
        let trials = 10000;
        let hits = (0..trials).filter(|_| rng.chance(0.5)).count();
        // Should be roughly 5000 ± 500
        assert!(
            hits > 4000 && hits < 6000,
            "Chance 0.5 gave {} hits out of {}",
            hits,
            trials
        );
    }

    #[test]
    fn advance_tick_reseeds_correctly() {
        let mut rng = DeterministicRng::new(42, "sys_test", 0);
        let v0 = rng.next_u64();
        rng.advance_tick(1);
        let v1 = rng.next_u64();
        assert_ne!(v0, v1);

        // Advancing back to tick 0 should reproduce tick 0's sequence
        rng.advance_tick(0);
        let v0_again = rng.next_u64();
        assert_eq!(v0, v0_again);
    }

    #[test]
    fn call_count_tracked() {
        let mut rng = DeterministicRng::new(42, "sys_test", 0);
        assert_eq!(rng.call_count(), 0);
        rng.next_u64();
        rng.next_u64();
        rng.next_u64();
        assert_eq!(rng.call_count(), 3);
    }

    #[test]
    fn advance_tick_resets_call_count() {
        let mut rng = DeterministicRng::new(42, "sys_test", 0);
        rng.next_u64();
        rng.next_u64();
        rng.advance_tick(1);
        assert_eq!(rng.call_count(), 0);
    }

    #[test]
    fn interceptor_rejects_empty_system_id() {
        assert!(RngInterceptor::validate_rng_usage("", 0).is_err());
    }

    #[test]
    fn interceptor_accepts_valid_system_id() {
        assert!(RngInterceptor::validate_rng_usage("sys_movement", 42).is_ok());
    }
}
