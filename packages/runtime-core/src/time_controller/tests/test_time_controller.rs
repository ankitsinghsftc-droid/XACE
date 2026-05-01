//! # Time Controller Integration Tests

use crate::time_controller::{TimeController, TimeMode, DeterministicRng};

#[test]
fn fixed_timestep_math_correct() {
    let tc = TimeController::new(120.0, 16);
    assert!((tc.fixed_timestep() - 1.0 / 120.0).abs() < 1e-12);
    assert_eq!(tc.simulation_rate() as u32, 120);
}

#[test]
fn accumulator_carries_remainder_correctly() {
    let mut tc = TimeController::new(10.0, 100); // 10 Hz
    // 0.15 seconds = 1 tick (0.1s) + 0.05s remainder
    let ticks = tc.update(0.15).unwrap();
    assert_eq!(ticks, 1);
    assert!((tc.accumulator() - 0.05).abs() < 1e-10);
}

#[test]
fn consistent_timing_over_many_frames() {
    let mut tc = TimeController::standard_60hz();
    let frame_time = 1.0 / 60.0; // perfect 60fps
    let mut total_ticks = 0u64;
    for _ in 0..60 {
        total_ticks += tc.update(frame_time).unwrap() as u64;
    }
    // 60 frames of 1/60s each = exactly 60 ticks
    assert_eq!(total_ticks, 60);
}

#[test]
fn pause_preserves_accumulator() {
    let mut tc = TimeController::standard_60hz();
    tc.update(0.5).unwrap(); // some remainder accumulated
    let acc_before = tc.accumulator();
    tc.pause();
    tc.update(10.0).unwrap(); // large time while paused
    assert!((tc.accumulator() - acc_before).abs() < 1e-10);
}

#[test]
fn replay_mode_with_2x_speed() {
    let mut tc = TimeController::standard_60hz();
    tc.set_mode(TimeMode::Replay);
    tc.set_time_scale(2.0).unwrap();
    let ticks = tc.update(0.5).unwrap(); // 0.5s real = 1s sim = 60 ticks
    assert_eq!(ticks, 60);
}

#[test]
fn rng_reproducibility_across_systems() {
    // Two systems with same parameters produce identical sequences
    let mut rng_a = DeterministicRng::new(999, "sys_ai", 42);
    let mut rng_b = DeterministicRng::new(999, "sys_ai", 42);
    for _ in 0..50 {
        assert_eq!(rng_a.next_f64(), rng_b.next_f64());
    }
}

#[test]
fn rng_different_ticks_independent() {
    let mut rng_t0 = DeterministicRng::new(1, "sys_movement", 0);
    let mut rng_t1 = DeterministicRng::new(1, "sys_movement", 1);
    // Sequences must differ
    let seq0: Vec<u64> = (0..10).map(|_| rng_t0.next_u64()).collect();
    let seq1: Vec<u64> = (0..10).map(|_| rng_t1.next_u64()).collect();
    assert_ne!(seq0, seq1);
}

#[test]
fn time_scale_001_very_slow() {
    let mut tc = TimeController::new(60.0, 100);
    tc.set_time_scale(0.01).unwrap();
    // At 0.01x scale, 1 real second = 0.01 sim seconds = 0.6 ticks
    let ticks = tc.update(1.0).unwrap();
    assert_eq!(ticks, 0); // Not enough for even 1 tick
}

#[test]
fn interpolation_alpha_zero_at_start() {
    let tc = TimeController::standard_60hz();
    // Before any update, accumulator is 0
    assert_eq!(tc.interpolation_alpha(), 0.0);
}

#[test]
fn fixed_input_delay_default_zero() {
    let tc = TimeController::standard_60hz();
    assert_eq!(tc.fixed_input_delay(), 0);
}

#[test]
fn fixed_input_delay_set_correctly() {
    let mut tc = TimeController::standard_60hz();
    tc.set_fixed_input_delay(3);
    assert_eq!(tc.fixed_input_delay(), 3);
}