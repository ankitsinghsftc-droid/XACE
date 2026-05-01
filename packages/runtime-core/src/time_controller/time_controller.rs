//! # Time Controller
//!
//! Fixed-timestep accumulation loop for the XACE runtime.
//! Converts real elapsed time into discrete simulation ticks.
//!
//! ## Determinism Rule D7
//! Fixed timestep only. delta_time = 1.0 / simulation_rate.
//! Frame rate and rendering performance NEVER affect simulation.
//! The simulation runs at exactly simulation_rate ticks per second
//! regardless of how fast or slow the engine renders.
//!
//! ## Spiral of Death Prevention
//! If real time advances faster than the simulation can process,
//! max_catchup_ticks limits how many ticks run per frame.
//! This prevents the simulation from getting stuck in an infinite
//! catch-up loop when the machine is too slow.
//!
//! ## Operating Modes
//! NORMAL     — standard real-time simulation
//! REPLAY     — playback from recorded input stream at defined speed
//! SCRUB      — manual tick advancement for debugging/timeline scrubbing
//! SERVER_AUTH — server-authoritative mode for multiplayer (Phase 15)

use xace_core::errors::xace_error::{XaceError, ErrorContext};

// ── Time Mode ─────────────────────────────────────────────────────────────────

/// The operating mode of the TimeController.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TimeMode {
    /// Standard real-time simulation. Ticks driven by wall clock.
    Normal,

    /// Replay mode. Ticks driven by input stream playback.
    /// time_scale controls replay speed (2.0 = 2x fast forward).
    Replay,

    /// Manual scrubbing. Ticks advanced only by advance_tick() calls.
    /// Used by the builder UI timeline scrubber (Phase 14).
    Scrub,

    /// Server-authoritative mode. Tick advancement controlled by
    /// network input synchronizer (Phase 15).
    ServerAuth,
}

impl std::fmt::Display for TimeMode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            TimeMode::Normal => write!(f, "NORMAL"),
            TimeMode::Replay => write!(f, "REPLAY"),
            TimeMode::Scrub => write!(f, "SCRUB"),
            TimeMode::ServerAuth => write!(f, "SERVER_AUTH"),
        }
    }
}

// ── Time Controller ───────────────────────────────────────────────────────────

/// Fixed-timestep time controller for XACE simulation.
///
/// Converts real elapsed time into discrete simulation tick counts.
/// Enforces D7 — simulation always uses fixed timestep, never
/// frame-rate-dependent delta_time.
///
/// ## Usage
/// Each frame, call update(real_elapsed_seconds) to get the number
/// of ticks to simulate this frame. Then run the PhaseOrchestrator
/// that many times.
///
/// ```ignore
/// let ticks = time_controller.update(frame_delta_seconds)?;
/// for _ in 0..ticks {
///     orchestrator.tick(...)?;
/// }
/// ```
pub struct TimeController {
    /// Simulation rate in ticks per second. Default 60.
    simulation_rate: f64,

    /// Fixed timestep duration in seconds. = 1.0 / simulation_rate.
    fixed_timestep: f64,

    /// Accumulated real time not yet converted to ticks.
    accumulator: f64,

    /// Maximum ticks to simulate per update() call.
    /// Prevents spiral of death on slow machines.
    max_catchup_ticks: u32,

    /// Current operating mode.
    mode: TimeMode,

    /// Playback speed multiplier.
    /// 1.0 = normal, 2.0 = 2x fast, 0.5 = half speed.
    /// Only applied in Normal and Replay modes.
    time_scale: f64,

    /// Whether simulation is currently paused.
    /// Paused = update() always returns 0 ticks.
    is_paused: bool,

    /// Total real time elapsed since controller creation (seconds).
    total_real_time: f64,

    /// Total simulation ticks executed.
    total_ticks: u64,

    /// Fixed input delay in ticks for multiplayer (Phase 15).
    fixed_input_delay: u32,
}

impl TimeController {
    /// Creates a TimeController with the given simulation rate.
    ///
    /// `simulation_rate`: ticks per second (e.g. 60.0 for 60 Hz simulation)
    /// `max_catchup_ticks`: max ticks per update() to prevent spiral of death
    pub fn new(simulation_rate: f64, max_catchup_ticks: u32) -> Self {
        assert!(simulation_rate > 0.0, "simulation_rate must be > 0");
        assert!(max_catchup_ticks > 0, "max_catchup_ticks must be > 0");
        Self {
            simulation_rate,
            fixed_timestep: 1.0 / simulation_rate,
            accumulator: 0.0,
            max_catchup_ticks,
            mode: TimeMode::Normal,
            time_scale: 1.0,
            is_paused: false,
            total_real_time: 0.0,
            total_ticks: 0,
            fixed_input_delay: 0,
        }
    }

    /// Creates a standard 60 Hz TimeController.
    pub fn standard_60hz() -> Self {
        Self::new(60.0, 8)
    }

    /// Creates a standard 20 Hz TimeController for server-authoritative mode.
    pub fn server_20hz() -> Self {
        Self::new(20.0, 4)
    }

    // ── Core Update ────────────────────────────────────────────────────────

    /// Advances the accumulator by real_elapsed_seconds and returns
    /// the number of simulation ticks to execute this frame.
    ///
    /// ## Fixed Timestep (D7)
    /// This method converts real time to discrete ticks using the
    /// fixed_timestep value. The accumulator carries over any remainder
    /// to the next frame — never loses time, never drifts.
    ///
    /// ## Spiral of Death Prevention
    /// If ticks_to_run exceeds max_catchup_ticks, the excess is capped.
    /// Real time continues accumulating — simulation may fall behind
    /// temporarily but will not enter an infinite catch-up loop.
    pub fn update(&mut self, real_elapsed_seconds: f64) -> Result<u32, XaceError> {
        if real_elapsed_seconds < 0.0 {
            return Err(XaceError::ValidationFailure {
                message: format!(
                    "real_elapsed_seconds cannot be negative: {}",
                    real_elapsed_seconds
                ),
                context: ErrorContext::new("TimeController", "update"),
                rule_violated: "D7".into(),
                failed_path: "real_elapsed_seconds".into(),
            });
        }

        if self.is_paused {
            return Ok(0);
        }

        if matches!(self.mode, TimeMode::Scrub | TimeMode::ServerAuth) {
            return Ok(0); // Ticks advanced manually in these modes
        }

        // Apply time scale (D7 — scale is deterministic, not frame-dependent)
        let scaled_elapsed = real_elapsed_seconds * self.time_scale;
        self.accumulator += scaled_elapsed;
        self.total_real_time += real_elapsed_seconds;

        // Convert accumulated time to discrete ticks
        let mut ticks_to_run: u32 = 0;
        while self.accumulator >= self.fixed_timestep {
            self.accumulator -= self.fixed_timestep;
            ticks_to_run += 1;

            // Spiral of death prevention
            if ticks_to_run >= self.max_catchup_ticks {
                // Cap the accumulator to prevent runaway catch-up
                if self.accumulator > self.fixed_timestep {
                    self.accumulator = self.fixed_timestep;
                }
                break;
            }
        }

        self.total_ticks += ticks_to_run as u64;
        Ok(ticks_to_run)
    }

    /// Manually advances one tick (Scrub and ServerAuth modes).
    ///
    /// Returns error if called in Normal or Replay mode.
    pub fn advance_one_tick(&mut self) -> Result<(), XaceError> {
        if !matches!(self.mode, TimeMode::Scrub | TimeMode::ServerAuth) {
            return Err(XaceError::ValidationFailure {
                message: format!(
                    "advance_one_tick() called in {} mode — \
                     only valid in SCRUB and SERVER_AUTH modes",
                    self.mode
                ),
                context: ErrorContext::new("TimeController", "advance_one_tick"),
                rule_violated: "D7".into(),
                failed_path: "time_mode".into(),
            });
        }
        self.total_ticks += 1;
        Ok(())
    }

    // ── Pause / Resume ─────────────────────────────────────────────────────

    /// Pauses the simulation. update() returns 0 ticks while paused.
    /// Accumulator is preserved — time resumes correctly on unpause.
    pub fn pause(&mut self) {
        self.is_paused = true;
    }

    /// Resumes the simulation.
    pub fn resume(&mut self) {
        self.is_paused = false;
    }

    /// Returns true if the simulation is currently paused.
    pub fn is_paused(&self) -> bool {
        self.is_paused
    }

    // ── Mode Control ───────────────────────────────────────────────────────

    /// Switches to the given operating mode.
    ///
    /// Switching modes resets the accumulator to prevent
    /// time accumulated in one mode affecting another.
    pub fn set_mode(&mut self, mode: TimeMode) {
        self.mode = mode;
        self.accumulator = 0.0; // Clear accumulator on mode switch
    }

    /// Returns the current operating mode.
    pub fn mode(&self) -> TimeMode {
        self.mode
    }

    // ── Time Scale ─────────────────────────────────────────────────────────

    /// Sets the time scale multiplier.
    ///
    /// 1.0 = normal speed
    /// 2.0 = 2x fast forward (replay)
    /// 0.5 = slow motion
    ///
    /// Returns error if scale <= 0.
    pub fn set_time_scale(&mut self, scale: f64) -> Result<(), XaceError> {
        if scale <= 0.0 {
            return Err(XaceError::ValidationFailure {
                message: format!("time_scale must be > 0, got {}", scale),
                context: ErrorContext::new("TimeController", "set_time_scale"),
                rule_violated: "D7".into(),
                failed_path: "time_scale".into(),
            });
        }
        self.time_scale = scale;
        Ok(())
    }

    /// Returns the current time scale.
    pub fn time_scale(&self) -> f64 {
        self.time_scale
    }

    // ── Queries ────────────────────────────────────────────────────────────

    /// Returns the fixed timestep in seconds (1.0 / simulation_rate).
    /// This is delta_time for all system calculations (D7).
    pub fn fixed_timestep(&self) -> f64 {
        self.fixed_timestep
    }

    /// Returns the simulation rate in ticks per second.
    pub fn simulation_rate(&self) -> f64 {
        self.simulation_rate
    }

    /// Returns total real time elapsed since controller creation.
    pub fn total_real_time(&self) -> f64 {
        self.total_real_time
    }

    /// Returns total simulation ticks executed.
    pub fn total_ticks(&self) -> u64 {
        self.total_ticks
    }

    /// Returns the current accumulator value (seconds carried over).
    /// Used for render interpolation — not for simulation logic.
    pub fn accumulator(&self) -> f64 {
        self.accumulator
    }

    /// Returns the interpolation alpha for render smoothing.
    /// alpha = accumulator / fixed_timestep (0.0 to 1.0).
    /// The engine adapter uses this for interpolated rendering.
    pub fn interpolation_alpha(&self) -> f64 {
        (self.accumulator / self.fixed_timestep).clamp(0.0, 1.0)
    }

    /// Returns the fixed input delay in ticks.
    pub fn fixed_input_delay(&self) -> u32 {
        self.fixed_input_delay
    }

    /// Sets the fixed input delay (Phase 15 multiplayer).
    pub fn set_fixed_input_delay(&mut self, delay_ticks: u32) {
        self.fixed_input_delay = delay_ticks;
    }

    // ── Snapshot Support ───────────────────────────────────────────────────

    /// Resets the accumulator for snapshot restore.
    /// Called by SnapshotEngine when restoring to a previous tick.
    pub fn reset_accumulator(&mut self) {
        self.accumulator = 0.0;
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn one_second_at_60hz_produces_60_ticks() {
        let mut tc = TimeController::standard_60hz();
        let ticks = tc.update(1.0).unwrap();
        assert_eq!(ticks, 60);
    }

    #[test]
    fn fractional_second_accumulates() {
        let mut tc = TimeController::standard_60hz();
        let t1 = tc.update(0.5).unwrap(); // 30 ticks
        let t2 = tc.update(0.5).unwrap(); // 30 ticks
        assert_eq!(t1, 30);
        assert_eq!(t2, 30);
    }

    #[test]
    fn fixed_timestep_correct() {
        let tc = TimeController::new(60.0, 8);
        assert!((tc.fixed_timestep() - 1.0 / 60.0).abs() < 1e-10);
    }

    #[test]
    fn paused_returns_zero_ticks() {
        let mut tc = TimeController::standard_60hz();
        tc.pause();
        assert_eq!(tc.update(1.0).unwrap(), 0);
        assert_eq!(tc.update(10.0).unwrap(), 0);
    }

    #[test]
    fn resume_after_pause_works() {
        let mut tc = TimeController::standard_60hz();
        tc.pause();
        tc.update(1.0).unwrap();
        tc.resume();
        let ticks = tc.update(1.0 / 60.0).unwrap();
        assert_eq!(ticks, 1);
    }

    #[test]
    fn spiral_of_death_prevention() {
        let mut tc = TimeController::new(60.0, 5); // max 5 catchup ticks
        // 10 seconds of real time — would be 600 ticks without cap
        let ticks = tc.update(10.0).unwrap();
        assert!(ticks <= 5, "Should cap at max_catchup_ticks=5, got {}", ticks);
    }

    #[test]
    fn negative_elapsed_returns_error() {
        let mut tc = TimeController::standard_60hz();
        assert!(tc.update(-1.0).is_err());
    }

    #[test]
    fn time_scale_doubles_tick_rate() {
        let mut tc = TimeController::standard_60hz();
        tc.set_time_scale(2.0).unwrap();
        let ticks = tc.update(1.0).unwrap();
        // 2x time scale = 120 ticks per second, capped at max_catchup=8
        assert!(ticks > 1);
    }

    #[test]
    fn zero_time_scale_rejected() {
        let mut tc = TimeController::standard_60hz();
        assert!(tc.set_time_scale(0.0).is_err());
    }

    #[test]
    fn negative_time_scale_rejected() {
        let mut tc = TimeController::standard_60hz();
        assert!(tc.set_time_scale(-1.0).is_err());
    }

    #[test]
    fn scrub_mode_advance_one_tick() {
        let mut tc = TimeController::standard_60hz();
        tc.set_mode(TimeMode::Scrub);
        assert_eq!(tc.update(1.0).unwrap(), 0); // update does nothing
        tc.advance_one_tick().unwrap();
        assert_eq!(tc.total_ticks(), 1);
    }

    #[test]
    fn advance_one_tick_fails_in_normal_mode() {
        let mut tc = TimeController::standard_60hz();
        assert!(tc.advance_one_tick().is_err());
    }

    #[test]
    fn interpolation_alpha_in_range() {
        let mut tc = TimeController::standard_60hz();
        tc.update(0.5).unwrap(); // accumulate some remainder
        let alpha = tc.interpolation_alpha();
        assert!(alpha >= 0.0 && alpha <= 1.0);
    }

    #[test]
    fn total_ticks_accumulates_across_updates() {
        let mut tc = TimeController::standard_60hz();
        tc.update(1.0).unwrap(); // 60 ticks
        tc.update(1.0).unwrap(); // 60 more
        assert_eq!(tc.total_ticks(), 120);
    }

    #[test]
    fn mode_switch_resets_accumulator() {
        let mut tc = TimeController::standard_60hz();
        tc.update(0.5).unwrap(); // accumulate 0.5s
        assert!(tc.accumulator() > 0.0);
        tc.set_mode(TimeMode::Replay);
        assert_eq!(tc.accumulator(), 0.0);
    }

    #[test]
    fn determinism_same_inputs_same_ticks() {
        let mut tc1 = TimeController::standard_60hz();
        let mut tc2 = TimeController::standard_60hz();
        for elapsed in [0.016, 0.017, 0.033, 0.016] {
            assert_eq!(
                tc1.update(elapsed).unwrap(),
                tc2.update(elapsed).unwrap()
            );
        }
    }

    #[test]
    fn server_20hz_rate_correct() {
        let mut tc = TimeController::server_20hz();
        let ticks = tc.update(1.0).unwrap();
        assert_eq!(ticks, 4); // capped at max_catchup=4
    }

    #[test]
    fn reset_accumulator_clears_state() {
        let mut tc = TimeController::standard_60hz();
        tc.update(0.5).unwrap();
        tc.reset_accumulator();
        assert_eq!(tc.accumulator(), 0.0);
    }
}