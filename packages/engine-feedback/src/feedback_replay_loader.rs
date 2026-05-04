//! # Feedback Replay Loader
//!
//! Loads a `FeedbackLog` and injects its messages into the `FeedbackBuffer`
//! tick by tick during replay mode, producing byte-identical world state
//! to the original session (D14).
//!
//! ## Replay Context
//! During replay, the XACE runtime runs from an initial `WorldSnapshot`
//! with a deterministic input stream. Without feedback replay, any tick
//! that was influenced by engine feedback in the original session will
//! diverge — the physics position, animation state, or visibility result
//! that the engine sent back will be absent, and the world_hash will differ.
//!
//! The `FeedbackReplayLoader` solves this by:
//! 1. Loading the `FeedbackLog` recorded during the original session
//! 2. Before each replay tick, injecting that tick's feedback into the
//!    `FeedbackBuffer` exactly as if the engine had just sent it
//! 3. The PhaseOrchestrator's normal drain/route/handle pipeline then
//!    processes the injected feedback identically to the original run
//!
//! ## Compatibility Validation
//! Before any injection, the loader validates that the `FeedbackLog`'s
//! schema_version and execution_plan_version match the replay session.
//! A mismatch means the log was recorded against a different CGS version —
//! injection would produce incorrect results and is rejected (D10).
//!
//! ## Tick Range
//! The loader only injects feedback for ticks within the log's recorded
//! range. Ticks outside the range receive no injected feedback (the
//! FeedbackBuffer remains empty for those ticks).
//!
//! ## Loader State Machine
//! ```text
//! Idle → begin_replay() → Replaying → tick 0…N → finish_replay() → Idle
//!                              │                        │
//!                              └── inject_for_tick()    └── produces ReplayReport
//! ```

use xace_core::entity_metadata::Tick;
use xace_core::errors::xace_error::{ErrorContext, XaceError};

use crate::feedback_buffer::FeedbackBuffer;
use crate::feedback_log::FeedbackLog;

// ── Replay Status ─────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReplayLoaderStatus {
    /// No replay active. `begin_replay()` not yet called.
    Idle,
    /// Replay active. `inject_for_tick()` can be called.
    Replaying,
    /// Replay complete — all ticks in the log range have been injected.
    Finished,
}

impl std::fmt::Display for ReplayLoaderStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ReplayLoaderStatus::Idle      => write!(f, "IDLE"),
            ReplayLoaderStatus::Replaying => write!(f, "REPLAYING"),
            ReplayLoaderStatus::Finished  => write!(f, "FINISHED"),
        }
    }
}

// ── Replay Report ─────────────────────────────────────────────────────────────

/// Summary produced by `finish_replay()`.
#[derive(Debug, Clone)]
pub struct ReplayReport {
    /// First tick injected.
    pub start_tick: Tick,
    /// Last tick injected.
    pub end_tick: Tick,
    /// Total ticks processed.
    pub ticks_processed: u64,
    /// Ticks that had feedback injected.
    pub ticks_with_feedback: u64,
    /// Ticks with no feedback in the log (empty injection).
    pub ticks_without_feedback: u64,
    /// Total messages injected across all ticks.
    pub total_messages_injected: u64,
    /// Whether the replay covered the full log range without gaps.
    pub full_coverage: bool,
}

impl ReplayReport {
    /// Returns true if every tick in the log range was processed.
    pub fn is_complete(&self) -> bool {
        self.full_coverage
    }
}

// ── Loader Metrics ────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Default)]
pub struct LoaderMetrics {
    pub total_replays: u64,
    pub total_ticks_injected: u64,
    pub total_messages_injected: u64,
    pub compatibility_failures: u64,
}

// ── Feedback Replay Loader ────────────────────────────────────────────────────

/// Injects recorded engine feedback into `FeedbackBuffer` during replay.
///
/// One instance per replay session. Reuse across multiple replays by
/// calling `begin_replay()` / `finish_replay()` in sequence.
pub struct FeedbackReplayLoader {
    /// The loaded log. Set by `begin_replay()`.
    log: Option<FeedbackLog>,

    /// Current replay status.
    status: ReplayLoaderStatus,

    /// Expected schema version for the current replay session.
    schema_version: String,

    /// Expected execution plan version for the current replay session.
    execution_plan_version: u32,

    /// Ticks injected in the current replay run.
    ticks_injected: u64,

    /// Ticks with at least one message in the current replay run.
    ticks_with_feedback: u64,

    /// Messages injected in the current replay run.
    messages_injected: u64,

    /// The FeedbackBuffer to inject into.
    buffer: FeedbackBuffer,

    metrics: LoaderMetrics,
}

impl FeedbackReplayLoader {
    // ── Construction ──────────────────────────────────────────────────────────

    /// Creates a new loader that injects into `buffer`.
    ///
    /// `schema_version` and `execution_plan_version` are the session contract
    /// that loaded `FeedbackLog` values must match.
    pub fn new(
        buffer: FeedbackBuffer,
        schema_version: impl Into<String>,
        execution_plan_version: u32,
    ) -> Self {
        Self {
            log: None,
            status: ReplayLoaderStatus::Idle,
            schema_version: schema_version.into(),
            execution_plan_version,
            ticks_injected: 0,
            ticks_with_feedback: 0,
            messages_injected: 0,
            buffer,
            metrics: LoaderMetrics::default(),
        }
    }

    // ── Replay Lifecycle ──────────────────────────────────────────────────────

    /// Loads a `FeedbackLog` and begins a replay session.
    ///
    /// Validates schema compatibility before accepting the log.
    /// Returns `Err` if the log was recorded against a different CGS version.
    pub fn begin_replay(&mut self, log: FeedbackLog) -> Result<(), XaceError> {
        if !log.is_compatible(&self.schema_version, self.execution_plan_version) {
            self.metrics.compatibility_failures += 1;
            return Err(XaceError::FatalError {
                message: format!(
                    "FeedbackReplayLoader: log schema='{}' plan={} is incompatible \
                     with replay session schema='{}' plan={}. \
                     Feedback replay requires identical CGS version (D14).",
                    log.schema_version(),
                    log.execution_plan_version(),
                    self.schema_version,
                    self.execution_plan_version,
                ),
                context: ErrorContext::new("FeedbackReplayLoader", "begin_replay"),
                snapshot_recovery_possible: false,
            });
        }

        self.log = Some(log);
        self.status = ReplayLoaderStatus::Replaying;
        self.ticks_injected = 0;
        self.ticks_with_feedback = 0;
        self.messages_injected = 0;
        Ok(())
    }

    /// Injects the feedback for `tick` into the `FeedbackBuffer`.
    ///
    /// Must be called BEFORE the PhaseOrchestrator drains the buffer for `tick`.
    /// If the log has no entry for this tick, nothing is injected (empty tick).
    ///
    /// Returns the number of messages injected (0 if tick not in log).
    pub fn inject_for_tick(&mut self, tick: Tick) -> Result<usize, XaceError> {
        if self.status != ReplayLoaderStatus::Replaying {
            return Err(XaceError::RecoverableError {
                message: format!(
                    "FeedbackReplayLoader::inject_for_tick called in status {} — \
                     call begin_replay() first",
                    self.status
                ),
                context: ErrorContext::new("FeedbackReplayLoader", "inject_for_tick")
                    .with_tick(tick),
                max_retries: 0,
                retry_count: 0,
            });
        }

        let log = self.log.as_ref().expect("log must be Some during Replaying");
        let messages = log.messages_at(tick).to_vec();
        let count = messages.len();

        if count > 0 {
            self.buffer.append_batch(messages);
            self.ticks_with_feedback += 1;
            self.messages_injected += count as u64;
        }

        self.ticks_injected += 1;

        // Check if we have passed the end of the log
        if let Some(log) = &self.log {
            if tick >= log.end_tick() {
                self.status = ReplayLoaderStatus::Finished;
            }
        }

        Ok(count)
    }

    /// Finalises the replay and returns a `ReplayReport`.
    ///
    /// Can be called at any point — even before the log end_tick is reached.
    /// Resets the loader to `Idle` state.
    pub fn finish_replay(&mut self) -> ReplayReport {
        let (start_tick, end_tick, log_tick_count) = match &self.log {
            Some(log) => (log.start_tick(), log.end_tick(), log.tick_count() as u64),
            None => (0, 0, 0),
        };

        let full_coverage = self.ticks_injected >= log_tick_count;

        let report = ReplayReport {
            start_tick,
            end_tick,
            ticks_processed: self.ticks_injected,
            ticks_with_feedback: self.ticks_with_feedback,
            ticks_without_feedback: self.ticks_injected
                .saturating_sub(self.ticks_with_feedback),
            total_messages_injected: self.messages_injected,
            full_coverage,
        };

        self.metrics.total_replays += 1;
        self.metrics.total_ticks_injected += self.ticks_injected;
        self.metrics.total_messages_injected += self.messages_injected;

        self.log = None;
        self.status = ReplayLoaderStatus::Idle;
        report
    }

    // ── Inspection ────────────────────────────────────────────────────────────

    /// Returns the current loader status.
    pub fn status(&self) -> ReplayLoaderStatus {
        self.status
    }

    /// Returns true if a replay is currently active.
    pub fn is_replaying(&self) -> bool {
        matches!(self.status, ReplayLoaderStatus::Replaying)
    }

    /// Returns accumulated loader metrics.
    pub fn metrics(&self) -> &LoaderMetrics {
        &self.metrics
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::wire::feedback_payload::{FeedbackMessage, FeedbackType};

    fn msg(entity_id: u64, frame: u64) -> FeedbackMessage {
        FeedbackMessage {
            feedback_type: FeedbackType::PhysicsSettled,
            entity_id,
            generated_frame: frame,
            payload_json: "{}".into(),
        }
    }

    fn log_with_ticks(ticks: Vec<(u64, Vec<FeedbackMessage>)>) -> FeedbackLog {
        let mut log = FeedbackLog::new("0.1.0", 1);
        for (tick, msgs) in ticks {
            log.record_tick(tick, msgs);
        }
        log
    }

    fn loader() -> FeedbackReplayLoader {
        FeedbackReplayLoader::new(FeedbackBuffer::new(), "0.1.0", 1)
    }

    // ── begin_replay ──────────────────────────────────────────────────────────

    #[test]
    fn begin_replay_accepts_compatible_log() {
        let mut l = loader();
        let log = log_with_ticks(vec![(1, vec![msg(1, 1)])]);
        assert!(l.begin_replay(log).is_ok());
        assert_eq!(l.status(), ReplayLoaderStatus::Replaying);
    }

    #[test]
    fn begin_replay_rejects_wrong_schema() {
        let mut l = loader();
        let log = FeedbackLog::new("9.9.9", 1); // wrong schema
        let result = l.begin_replay(log);
        assert!(result.is_err());
        assert_eq!(l.metrics().compatibility_failures, 1);
        assert_eq!(l.status(), ReplayLoaderStatus::Idle);
    }

    #[test]
    fn begin_replay_rejects_wrong_plan_version() {
        let mut l = loader();
        let log = FeedbackLog::new("0.1.0", 99); // wrong plan
        assert!(l.begin_replay(log).is_err());
    }

    // ── inject_for_tick ───────────────────────────────────────────────────────

    #[test]
    fn inject_for_tick_puts_messages_in_buffer() {
        let buffer = FeedbackBuffer::new();
        let mut l = FeedbackReplayLoader::new(buffer.clone(), "0.1.0", 1);

        let log = log_with_ticks(vec![(1, vec![msg(1, 1), msg(2, 1)])]);
        l.begin_replay(log).unwrap();

        let count = l.inject_for_tick(1).unwrap();
        assert_eq!(count, 2);
        assert_eq!(buffer.pending_count(), 2);
    }

    #[test]
    fn inject_for_tick_returns_zero_for_unrecorded_tick() {
        let mut l = loader();
        let log = log_with_ticks(vec![(5, vec![msg(1, 5)])]);
        l.begin_replay(log).unwrap();

        let count = l.inject_for_tick(99).unwrap(); // tick not in log
        assert_eq!(count, 0);
    }

    #[test]
    fn inject_for_tick_fails_when_not_replaying() {
        let mut l = loader();
        // begin_replay not called
        let result = l.inject_for_tick(1);
        assert!(result.is_err());
    }

    #[test]
    fn inject_for_tick_sets_finished_after_end_tick() {
        let mut l = loader();
        let log = log_with_ticks(vec![(1, vec![msg(1, 1)]), (3, vec![msg(2, 3)])]);
        l.begin_replay(log).unwrap();

        l.inject_for_tick(1).unwrap();
        l.inject_for_tick(3).unwrap(); // end_tick = 3
        assert_eq!(l.status(), ReplayLoaderStatus::Finished);
    }

    // ── finish_replay ─────────────────────────────────────────────────────────

    #[test]
    fn finish_replay_returns_correct_report() {
        let mut l = loader();
        let log = log_with_ticks(vec![
            (1, vec![msg(1, 1)]),
            (2, vec![]),
            (3, vec![msg(2, 3), msg(3, 3)]),
        ]);
        l.begin_replay(log).unwrap();
        l.inject_for_tick(1).unwrap();
        l.inject_for_tick(2).unwrap();
        l.inject_for_tick(3).unwrap();

        let report = l.finish_replay();
        assert_eq!(report.ticks_processed, 3);
        assert_eq!(report.ticks_with_feedback, 2); // ticks 1 and 3
        assert_eq!(report.ticks_without_feedback, 1); // tick 2 was empty
        assert_eq!(report.total_messages_injected, 3); // 1+0+2
        assert!(report.full_coverage);
    }

    #[test]
    fn finish_replay_resets_to_idle() {
        let mut l = loader();
        let log = log_with_ticks(vec![(1, vec![])]);
        l.begin_replay(log).unwrap();
        l.inject_for_tick(1).unwrap();
        l.finish_replay();
        assert_eq!(l.status(), ReplayLoaderStatus::Idle);
    }

    #[test]
    fn finish_replay_without_full_coverage_marks_incomplete() {
        let mut l = loader();
        let log = log_with_ticks(vec![
            (1, vec![msg(1, 1)]),
            (2, vec![msg(2, 2)]),
            (3, vec![msg(3, 3)]),
        ]);
        l.begin_replay(log).unwrap();
        // Only inject 2 of 3 ticks
        l.inject_for_tick(1).unwrap();
        l.inject_for_tick(2).unwrap();

        let report = l.finish_replay();
        assert!(!report.full_coverage);
    }

    // ── Multiple Replays ──────────────────────────────────────────────────────

    #[test]
    fn loader_supports_multiple_replay_sessions() {
        let mut l = loader();

        for _ in 0..3 {
            let log = log_with_ticks(vec![(1, vec![msg(1, 1)])]);
            l.begin_replay(log).unwrap();
            l.inject_for_tick(1).unwrap();
            l.finish_replay();
        }

        assert_eq!(l.metrics().total_replays, 3);
        assert_eq!(l.metrics().total_messages_injected, 3);
    }

    // ── Injection Ordering ────────────────────────────────────────────────────

    #[test]
    fn injected_messages_drain_in_correct_order() {
        let buffer = FeedbackBuffer::new();
        let mut l = FeedbackReplayLoader::new(buffer.clone(), "0.1.0", 1);

        // Log has messages in deterministic order (as they were stored after drain_sorted)
        let log = log_with_ticks(vec![(1, vec![msg(1, 5), msg(3, 5), msg(5, 8)])]);
        l.begin_replay(log).unwrap();
        l.inject_for_tick(1).unwrap();

        let drained = buffer.drain_sorted();
        assert_eq!(drained.len(), 3);
        // After drain_sorted: (frame=5,entity=1), (frame=5,entity=3), (frame=8,entity=5)
        assert_eq!(drained[0].entity_id, 1);
        assert_eq!(drained[1].entity_id, 3);
        assert_eq!(drained[2].entity_id, 5);
    }

    // ── Status Display ────────────────────────────────────────────────────────

    #[test]
    fn status_display_values() {
        assert_eq!(ReplayLoaderStatus::Idle.to_string(), "IDLE");
        assert_eq!(ReplayLoaderStatus::Replaying.to_string(), "REPLAYING");
        assert_eq!(ReplayLoaderStatus::Finished.to_string(), "FINISHED");
    }
}