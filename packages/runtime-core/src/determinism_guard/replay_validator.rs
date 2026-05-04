//! # Replay Validator
//!
//! Validates that a replay run produces byte-identical world state to the
//! original simulation run, tick by tick. This is the primary proof that
//! XACE's determinism guarantees hold across sessions, machines, and time.
//!
//! ## How Replay Works in XACE (D14)
//! A replay is defined by three inputs:
//!   1. An initial WorldSnapshot  — the starting world state
//!   2. A deterministic input stream — every player and AI input, tick-stamped
//!   3. An identical schema version  — same CGS, same ExecutionPlan
//!
//! Given these three inputs, the runtime must produce the exact same
//! world_hash at every tick as the original run. The ReplayValidator
//! enforces this guarantee by comparing hashes tick by tick.
//!
//! ## Roles
//! **Recording phase** — During a live session, the validator records the
//! world_hash computed by WorldHasher after every tick into a GoldenLog.
//! The GoldenLog is the authoritative record of what the original run did.
//!
//! **Validation phase** — During replay, the validator recomputes the world_hash
//! for each tick and compares it against the GoldenLog entry for that tick.
//! Any mismatch is a ReplayDivergence — a proof that determinism was broken.
//!
//! ## Divergence Reporting
//! When divergence is detected, the validator produces a ReplayDivergenceReport
//! containing the tick, both hashes, the divergence type, and recommendations
//! for diagnosis. This report feeds into the DeterminismGuard as a D14 violation.
//!
//! ## Integration with DeterminismGuard
//! The DeterminismGuard calls validate_tick() inside hook_tick_end during replay
//! mode. The ReplayValidator is not a replacement for the guard — it is a
//! specialized instrument that the guard holds and delegates to.
//!
//! ## GoldenLog Persistence
//! The GoldenLog can be serialized to disk and loaded back for offline validation.
//! This enables CI replay testing: record a session once, store the GoldenLog,
//! and assert determinism in every subsequent CI run.

use std::collections::BTreeMap;
use serde::{Deserialize, Serialize};

use xace_core::errors::determinism_error::{DeterminismRule, DeterminismViolation, GuardMode};
use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::runtime::world_snapshot::WorldSnapshot;

use crate::determinism_guard::world_hasher::WorldHasher;

// ── Replay Session Status ─────────────────────────────────────────────────────

/// The current state of a replay validation session.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ReplayStatus {
    /// No validation has started. GoldenLog may be empty or loaded.
    Idle,

    /// Recording mode — hashes are being written into the GoldenLog.
    /// The simulation is running live. No comparison is performed.
    Recording,

    /// Validation mode — replay hashes are being compared against GoldenLog.
    /// Comparison is performed on every validate_tick() call.
    Validating,

    /// All ticks in the GoldenLog have been validated and matched.
    /// The replay proved deterministic for the full recorded range.
    Passed,

    /// A hash mismatch was detected. The replay diverged from the original run.
    /// The session is halted at the divergence tick.
    Diverged,
}

impl std::fmt::Display for ReplayStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ReplayStatus::Idle       => write!(f, "IDLE"),
            ReplayStatus::Recording  => write!(f, "RECORDING"),
            ReplayStatus::Validating => write!(f, "VALIDATING"),
            ReplayStatus::Passed     => write!(f, "PASSED"),
            ReplayStatus::Diverged   => write!(f, "DIVERGED"),
        }
    }
}

// ── Divergence Type ───────────────────────────────────────────────────────────

/// The category of replay divergence detected.
///
/// Helps diagnose the root cause of determinism failure.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum DivergenceType {
    /// World hash mismatch — simulation state differed at this tick.
    /// Root cause: one of D1–D13 was violated during replay.
    WorldHashMismatch,

    /// A tick present in the GoldenLog was not validated during replay.
    /// Root cause: replay ended early, or ticks were skipped.
    MissingReplayTick,

    /// A tick was validated during replay but has no GoldenLog entry.
    /// Root cause: replay ran further than the original session recorded.
    UnrecordedTick,

    /// Schema version or execution plan version mismatch at replay start.
    /// Root cause: D10 — replay attempted against wrong CGS version.
    SchemaVersionMismatch,
}

impl std::fmt::Display for DivergenceType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            DivergenceType::WorldHashMismatch    => write!(f, "WORLD_HASH_MISMATCH"),
            DivergenceType::MissingReplayTick    => write!(f, "MISSING_REPLAY_TICK"),
            DivergenceType::UnrecordedTick       => write!(f, "UNRECORDED_TICK"),
            DivergenceType::SchemaVersionMismatch => write!(f, "SCHEMA_VERSION_MISMATCH"),
        }
    }
}

// ── Replay Divergence ─────────────────────────────────────────────────────────

/// A single divergence event detected during replay validation.
///
/// Carries everything needed to diagnose the root cause:
/// the tick, the hash values, the divergence type, and the
/// schema version that was active at the time.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReplayDivergence {
    /// The simulation tick at which divergence was detected.
    pub tick: u64,

    /// The world_hash recorded in the GoldenLog from the original run.
    /// Empty for UnrecordedTick divergences.
    pub golden_hash: String,

    /// The world_hash computed during the replay run.
    /// Empty for MissingReplayTick divergences.
    pub replay_hash: String,

    /// The category of this divergence.
    pub divergence_type: DivergenceType,

    /// The schema version active during replay at this tick.
    pub schema_version: String,

    /// Human-readable explanation of what went wrong and where to look.
    pub diagnosis: String,
}

impl ReplayDivergence {
    /// Creates a WorldHashMismatch divergence.
    fn hash_mismatch(
        tick: u64,
        golden_hash: impl Into<String>,
        replay_hash: impl Into<String>,
        schema_version: impl Into<String>,
    ) -> Self {
        let golden = golden_hash.into();
        let replay = replay_hash.into();
        Self {
            diagnosis: format!(
                "World state diverged at tick {}. Original hash='{}' Replay hash='{}'. \
                 Check D1 (system order), D3 (entity iteration), D4 (mutation gate), \
                 D5 (event ordering), D6 (RNG). Any of these rules broken during \
                 replay will cause hash divergence.",
                tick,
                &golden[..8.min(golden.len())],
                &replay[..8.min(replay.len())],
            ),
            tick,
            golden_hash: golden,
            replay_hash: replay,
            divergence_type: DivergenceType::WorldHashMismatch,
            schema_version: schema_version.into(),
        }
    }

    /// Creates an UnrecordedTick divergence — replay ran past the GoldenLog.
    fn unrecorded_tick(tick: u64, replay_hash: impl Into<String>, schema_version: impl Into<String>) -> Self {
        Self {
            diagnosis: format!(
                "Replay tick {} has no GoldenLog entry. The replay ran further than \
                 the original recorded session. Validation cannot continue past the \
                 last recorded tick.",
                tick
            ),
            tick,
            golden_hash: String::new(),
            replay_hash: replay_hash.into(),
            divergence_type: DivergenceType::UnrecordedTick,
            schema_version: schema_version.into(),
        }
    }

    /// Creates a SchemaVersionMismatch divergence.
    fn schema_mismatch(
        tick: u64,
        golden_schema: impl Into<String>,
        replay_schema: impl Into<String>,
    ) -> Self {
        let golden = golden_schema.into();
        let replay = replay_schema.into();
        Self {
            diagnosis: format!(
                "Schema version mismatch at replay start tick {}. GoldenLog was \
                 recorded on schema='{}' but replay is running schema='{}'. \
                 Replay requires identical schema version (D10, D14).",
                tick, golden, replay
            ),
            tick,
            golden_hash: String::new(),
            replay_hash: String::new(),
            divergence_type: DivergenceType::SchemaVersionMismatch,
            schema_version: replay,
        }
    }

    /// Returns a one-line summary for logging.
    pub fn summary(&self) -> String {
        format!(
            "[{}] tick={} golden='{}' replay='{}'",
            self.divergence_type,
            self.tick,
            if self.golden_hash.is_empty() {
                "N/A".to_string()
            } else {
                self.golden_hash[..8.min(self.golden_hash.len())].to_string()
            },
            if self.replay_hash.is_empty() {
                "N/A".to_string()
            } else {
                self.replay_hash[..8.min(self.replay_hash.len())].to_string()
            },
        )
    }
}

// ── Replay Divergence Report ──────────────────────────────────────────────────

/// A complete report of all divergences detected in a replay session.
///
/// Produced by ReplayValidator::finish_validation() or on the first
/// divergence in STRICT mode. Contains full context for diagnosing
/// why the replay failed to reproduce the original run exactly.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReplayDivergenceReport {
    /// The tick at which the first divergence was detected.
    pub first_divergence_tick: u64,

    /// All divergences detected during this replay session.
    /// In STRICT mode this will contain exactly one entry (halt on first).
    /// In DEV/SILENT mode this accumulates all divergences seen.
    pub divergences: Vec<ReplayDivergence>,

    /// The schema version the GoldenLog was recorded on.
    pub golden_schema_version: String,

    /// The schema version the replay was run on.
    pub replay_schema_version: String,

    /// The total number of ticks in the GoldenLog.
    pub golden_tick_count: usize,

    /// The number of ticks successfully validated before divergence.
    pub validated_tick_count: usize,

    /// The number of ticks in the GoldenLog that were never validated.
    /// > 0 means the replay ended before the GoldenLog was exhausted.
    pub unvalidated_golden_ticks: usize,

    /// Whether the replay validated every tick in the GoldenLog successfully.
    pub is_full_pass: bool,
}

impl ReplayDivergenceReport {
    /// Returns true if this report represents a clean pass.
    pub fn passed(&self) -> bool {
        self.is_full_pass && self.divergences.is_empty()
    }

    /// Returns the number of divergences detected.
    pub fn divergence_count(&self) -> usize {
        self.divergences.len()
    }

    /// Returns a multi-line human-readable summary of the report.
    pub fn summary(&self) -> String {
        let status = if self.passed() { "PASSED" } else { "FAILED" };
        let mut lines = vec![
            format!("=== Replay Validation Report: {} ===", status),
            format!(
                "Golden: schema='{}' ticks={}",
                self.golden_schema_version, self.golden_tick_count
            ),
            format!(
                "Replay: schema='{}' validated={} unvalidated={}",
                self.replay_schema_version,
                self.validated_tick_count,
                self.unvalidated_golden_ticks
            ),
        ];
        if !self.divergences.is_empty() {
            lines.push(format!(
                "First divergence at tick {}",
                self.first_divergence_tick
            ));
            for d in &self.divergences {
                lines.push(format!("  {}", d.summary()));
                lines.push(format!("  Diagnosis: {}", d.diagnosis));
            }
        } else {
            lines.push("All ticks matched. Determinism confirmed.".into());
        }
        lines.join("\n")
    }
}

// ── Golden Log ────────────────────────────────────────────────────────────────

/// The authoritative record of world_hash values from an original simulation run.
///
/// Produced during a recording session and consumed during replay validation.
/// Can be serialized to disk for CI and offline testing.
///
/// BTreeMap<tick → hash> guarantees stable ordering for deterministic
/// serialization (D11).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GoldenLog {
    /// tick → world_hash recorded from the original run.
    pub entries: BTreeMap<u64, String>,

    /// The schema version the original run was recorded on.
    pub schema_version: String,

    /// The ExecutionPlan version the original run was recorded on.
    pub execution_plan_version: u32,

    /// The tick the original session started at (usually 0 or a checkpoint tick).
    pub start_tick: u64,

    /// The last tick recorded in this log.
    pub end_tick: u64,
}

impl GoldenLog {
    /// Creates a new empty GoldenLog for the given schema contract.
    pub fn new(schema_version: impl Into<String>, execution_plan_version: u32) -> Self {
        Self {
            entries: BTreeMap::new(),
            schema_version: schema_version.into(),
            execution_plan_version,
            start_tick: 0,
            end_tick: 0,
        }
    }

    /// Records a world_hash for a given tick.
    /// Called by ReplayValidator during recording mode after every tick.
    pub fn record(&mut self, tick: u64, hash: impl Into<String>) {
        let hash = hash.into();
        if self.entries.is_empty() {
            self.start_tick = tick;
        }
        self.end_tick = tick.max(self.end_tick);
        self.entries.insert(tick, hash);
    }

    /// Returns the recorded hash for a tick, if present.
    pub fn get(&self, tick: u64) -> Option<&str> {
        self.entries.get(&tick).map(|s| s.as_str())
    }

    /// Returns the total number of recorded ticks.
    pub fn tick_count(&self) -> usize {
        self.entries.len()
    }

    /// Returns true if the log has no entries.
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    /// Returns an iterator over (tick, hash) in ascending tick order.
    /// BTreeMap guarantees this without sorting.
    pub fn iter_ordered(&self) -> impl Iterator<Item = (u64, &str)> {
        self.entries.iter().map(|(&tick, hash)| (tick, hash.as_str()))
    }

    /// Returns true if this log is compatible with the given schema contract.
    /// Compatibility is required before replay validation can start (D10, D14).
    pub fn is_compatible(&self, schema_version: &str, execution_plan_version: u32) -> bool {
        self.schema_version == schema_version
            && self.execution_plan_version == execution_plan_version
    }
}

// ── Replay Validator ──────────────────────────────────────────────────────────

/// Validates replay determinism by comparing per-tick world hashes against
/// a GoldenLog recorded from the original simulation run.
///
/// ## Two Modes of Operation
///
/// **Recording** — call begin_recording(), then record_tick() after each tick.
/// The validator builds the GoldenLog from the live session. Call finish_recording()
/// to get the completed GoldenLog for storage.
///
/// **Validation** — call begin_validation() with a GoldenLog, then validate_tick()
/// after each replay tick. Call finish_validation() to get the full report.
///
/// ## Guard Mode Integration
/// The validator respects the DeterminismGuard's mode:
/// - STRICT:  halt on first divergence, return Err immediately
/// - DEV:     log divergence, accumulate, continue replay
/// - SILENT:  record divergence, continue replay silently
pub struct ReplayValidator {
    /// The GoldenLog being built (recording) or compared against (validation).
    golden_log: GoldenLog,

    /// Current status of this validator.
    status: ReplayStatus,

    /// Guard mode — controls divergence handling behaviour.
    mode: GuardMode,

    /// Divergences accumulated during validation.
    /// In STRICT mode this will have at most one entry.
    divergences: Vec<ReplayDivergence>,

    /// Number of ticks successfully validated with matching hashes.
    validated_ticks: usize,

    /// The schema version the replay is running on.
    /// Set by begin_validation(). Compared against GoldenLog schema.
    replay_schema_version: String,

    /// The ExecutionPlan version the replay is running on.
    replay_execution_plan_version: u32,
}

impl ReplayValidator {
    // ── Construction ──────────────────────────────────────────────────────────

    /// Creates a new ReplayValidator in IDLE status.
    ///
    /// `mode` must match the DeterminismGuard's mode for consistent behaviour.
    pub fn new(mode: GuardMode) -> Self {
        Self {
            golden_log: GoldenLog::new("", 0),
            status: ReplayStatus::Idle,
            mode,
            divergences: Vec::new(),
            validated_ticks: 0,
            replay_schema_version: String::new(),
            replay_execution_plan_version: 0,
        }
    }

    // ── Recording API ─────────────────────────────────────────────────────────

    /// Begins a recording session for the given schema contract.
    ///
    /// The validator enters RECORDING mode. Subsequent record_tick() calls
    /// populate the GoldenLog. Call finish_recording() to retrieve the log.
    pub fn begin_recording(
        &mut self,
        schema_version: impl Into<String>,
        execution_plan_version: u32,
    ) {
        self.golden_log = GoldenLog::new(schema_version, execution_plan_version);
        self.status = ReplayStatus::Recording;
        self.divergences.clear();
        self.validated_ticks = 0;
    }

    /// Records the world state for a single tick during a live session.
    ///
    /// Computes the world hash via WorldHasher and stores it in the GoldenLog.
    /// Returns the computed hash so the PhaseOrchestrator can store it in the
    /// committed WorldSnapshot.
    ///
    /// Returns Err if called when not in RECORDING mode.
    pub fn record_tick(&mut self, snapshot: &WorldSnapshot) -> Result<String, XaceError> {
        if self.status != ReplayStatus::Recording {
            return Err(XaceError::ValidationFailure {
                message: format!(
                    "record_tick() called while in {} mode — begin_recording() first",
                    self.status
                ),
                context: ErrorContext::new("ReplayValidator", "record_tick")
                    .with_tick(snapshot.tick),
                rule_violated: "D15".into(),
                failed_path: String::new(),
            });
        }

        let hash = WorldHasher::compute(snapshot);
        self.golden_log.record(snapshot.tick, &hash);
        Ok(hash)
    }

    /// Finalizes the recording session and returns the completed GoldenLog.
    ///
    /// The validator returns to IDLE status. The caller is responsible for
    /// persisting the GoldenLog to disk for future replay validation.
    ///
    /// Returns Err if not currently in RECORDING mode.
    pub fn finish_recording(&mut self) -> Result<GoldenLog, XaceError> {
        if self.status != ReplayStatus::Recording {
            return Err(XaceError::ValidationFailure {
                message: format!(
                    "finish_recording() called while in {} mode",
                    self.status
                ),
                context: ErrorContext::new("ReplayValidator", "finish_recording"),
                rule_violated: "D15".into(),
                failed_path: String::new(),
            });
        }
        self.status = ReplayStatus::Idle;
        Ok(self.golden_log.clone())
    }

    // ── Validation API ────────────────────────────────────────────────────────

    /// Begins a validation session against the provided GoldenLog.
    ///
    /// Validates that the replay schema contract matches the GoldenLog.
    /// Returns Err immediately if schema versions are incompatible (D10, D14).
    pub fn begin_validation(
        &mut self,
        golden_log: GoldenLog,
        replay_schema_version: impl Into<String>,
        replay_execution_plan_version: u32,
    ) -> Result<(), XaceError> {
        let schema = replay_schema_version.into();

        // Schema contract must match — D10, D14. Always fatal regardless of mode.
        if !golden_log.is_compatible(&schema, replay_execution_plan_version) {
            let divergence = ReplayDivergence::schema_mismatch(
                golden_log.start_tick,
                &golden_log.schema_version,
                &schema,
            );
            return Err(XaceError::FatalError {
                message: divergence.diagnosis.clone(),
                context: ErrorContext::new("ReplayValidator", "begin_validation")
                    .with_tick(golden_log.start_tick),
                snapshot_recovery_possible: false,
            });
        }

        self.replay_schema_version = schema;
        self.replay_execution_plan_version = replay_execution_plan_version;
        self.golden_log = golden_log;
        self.status = ReplayStatus::Validating;
        self.divergences.clear();
        self.validated_ticks = 0;
        Ok(())
    }

    /// Validates the world state for a single replay tick.
    ///
    /// Computes the world hash via WorldHasher and compares it against the
    /// GoldenLog entry for this tick. Behaviour on mismatch is controlled by mode:
    ///
    /// - STRICT:  returns Err(FatalError), replay halts at this tick
    /// - DEV:     logs to stderr, records divergence, returns Ok — replay continues
    /// - SILENT:  records divergence silently, returns Ok — replay continues
    ///
    /// If this tick has no GoldenLog entry (replay ran past the recording),
    /// an UnrecordedTick divergence is produced and handled per mode.
    ///
    /// Returns Ok(computed_hash) on match. The hash can be stored in the
    /// snapshot for later inspection.
    pub fn validate_tick(&mut self, snapshot: &WorldSnapshot) -> Result<String, XaceError> {
        if self.status != ReplayStatus::Validating {
            return Err(XaceError::ValidationFailure {
                message: format!(
                    "validate_tick() called while in {} mode — begin_validation() first",
                    self.status
                ),
                context: ErrorContext::new("ReplayValidator", "validate_tick")
                    .with_tick(snapshot.tick),
                rule_violated: "D15".into(),
                failed_path: String::new(),
            });
        }

        let tick = snapshot.tick;
        let computed = WorldHasher::compute(snapshot);

        match self.golden_log.get(tick) {
            // ── Tick exists in GoldenLog → compare hashes ─────────────────────
            Some(golden_hash) => {
                if computed == golden_hash {
                    // Hash matches — determinism confirmed for this tick
                    self.validated_ticks += 1;
                    Ok(computed)
                } else {
                    // Hash mismatch — divergence detected
                    let divergence = ReplayDivergence::hash_mismatch(
                        tick,
                        golden_hash,
                        &computed,
                        &self.replay_schema_version,
                    );
                    self.handle_divergence(divergence, tick, computed)
                }
            }

            // ── Tick not in GoldenLog → replay ran past recording ─────────────
            None => {
                let divergence = ReplayDivergence::unrecorded_tick(
                    tick,
                    &computed,
                    &self.replay_schema_version,
                );
                self.handle_divergence(divergence, tick, computed)
            }
        }
    }

    /// Finalizes the validation session and produces a complete report.
    ///
    /// Checks that all ticks in the GoldenLog were validated. Any golden ticks
    /// that were never replayed are counted as unvalidated (possible early replay end).
    ///
    /// The validator returns to IDLE status after this call.
    pub fn finish_validation(&mut self) -> ReplayDivergenceReport {
        let golden_tick_count = self.golden_log.tick_count();
        let unvalidated = golden_tick_count.saturating_sub(self.validated_ticks);
        let is_full_pass = self.divergences.is_empty() && unvalidated == 0;

        let first_divergence_tick = self
            .divergences
            .first()
            .map(|d| d.tick)
            .unwrap_or(0);

        if is_full_pass {
            self.status = ReplayStatus::Passed;
        } else if !self.divergences.is_empty() {
            self.status = ReplayStatus::Diverged;
        }

        let report = ReplayDivergenceReport {
            first_divergence_tick,
            divergences: self.divergences.clone(),
            golden_schema_version: self.golden_log.schema_version.clone(),
            replay_schema_version: self.replay_schema_version.clone(),
            golden_tick_count,
            validated_tick_count: self.validated_ticks,
            unvalidated_golden_ticks: unvalidated,
            is_full_pass,
        };

        self.status = ReplayStatus::Idle;
        report
    }

    // ── Inspection API ────────────────────────────────────────────────────────

    /// Returns the current replay status.
    pub fn status(&self) -> ReplayStatus {
        self.status
    }

    /// Returns true if any divergences have been detected.
    pub fn has_divergences(&self) -> bool {
        !self.divergences.is_empty()
    }

    /// Returns all divergences detected so far.
    pub fn divergences(&self) -> &[ReplayDivergence] {
        &self.divergences
    }

    /// Returns the number of ticks successfully validated so far.
    pub fn validated_tick_count(&self) -> usize {
        self.validated_ticks
    }

    /// Returns the number of ticks recorded in the GoldenLog.
    pub fn golden_tick_count(&self) -> usize {
        self.golden_log.tick_count()
    }

    /// Returns a reference to the current GoldenLog.
    pub fn golden_log(&self) -> &GoldenLog {
        &self.golden_log
    }

    // ── Internal Divergence Handling ──────────────────────────────────────────

    /// Handles a detected divergence according to the current guard mode.
    ///
    /// Always records the divergence in the divergence list and updates status.
    /// Mode controls output and whether Err is returned:
    /// - STRICT: log, set status to Diverged, return Err(FatalError)
    /// - DEV:    log to stderr, accumulate, return Ok(hash)
    /// - SILENT: accumulate only, return Ok(hash)
    fn handle_divergence(
        &mut self,
        divergence: ReplayDivergence,
        tick: u64,
        computed_hash: String,
    ) -> Result<String, XaceError> {
        self.divergences.push(divergence.clone());

        match self.mode {
            GuardMode::Strict => {
                self.status = ReplayStatus::Diverged;
                eprintln!(
                    "[XACE][STRICT][D14] Replay diverged: {}",
                    divergence.summary()
                );
                eprintln!("  Diagnosis: {}", divergence.diagnosis);
                Err(self.make_divergence_error(&divergence, tick))
            }
            GuardMode::Dev => {
                eprintln!(
                    "[XACE][DEV][D14] Replay diverged at tick {}: {}",
                    tick,
                    divergence.summary()
                );
                Ok(computed_hash)
            }
            GuardMode::Silent => Ok(computed_hash),
        }
    }

    /// Builds an XaceError::FatalError from a ReplayDivergence.
    fn make_divergence_error(&self, divergence: &ReplayDivergence, tick: u64) -> XaceError {
        // Also construct the DeterminismViolation for the guard's violation_log
        let _violation = DeterminismViolation::hash_mismatch(
            DeterminismRule::D14ReplayRequiresThreeInputs,
            "ReplayValidator",
            tick,
            &divergence.golden_hash,
            &divergence.replay_hash,
            self.mode,
        );

        XaceError::FatalError {
            message: divergence.diagnosis.clone(),
            context: ErrorContext::new("ReplayValidator", "validate_tick")
                .with_tick(tick)
                .with_detail("divergence_type", divergence.divergence_type.to_string())
                .with_detail(
                    "golden_hash",
                    divergence.golden_hash[..8.min(divergence.golden_hash.len())].to_string(),
                )
                .with_detail(
                    "replay_hash",
                    divergence.replay_hash[..8.min(divergence.replay_hash.len())].to_string(),
                ),
            snapshot_recovery_possible: false,
        }
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::runtime::world_snapshot::WorldSnapshot;

    // ── Helpers ───────────────────────────────────────────────────────────────

    fn snap(tick: u64) -> WorldSnapshot {
        let mut s = WorldSnapshot::empty("0.1.0", 1, 42);
        s.tick = tick;
        s
    }

    /// Records N ticks and returns a GoldenLog ready for validation.
    fn record_n_ticks(n: u64) -> GoldenLog {
        let mut v = ReplayValidator::new(GuardMode::Strict);
        v.begin_recording("0.1.0", 1);
        for tick in 0..n {
            v.record_tick(&snap(tick)).unwrap();
        }
        v.finish_recording().unwrap()
    }

    // ── GoldenLog Tests ───────────────────────────────────────────────────────

    #[test]
    fn golden_log_records_and_retrieves() {
        let mut log = GoldenLog::new("0.1.0", 1);
        log.record(1, "hash_tick_1");
        log.record(2, "hash_tick_2");
        assert_eq!(log.get(1), Some("hash_tick_1"));
        assert_eq!(log.get(2), Some("hash_tick_2"));
        assert_eq!(log.get(99), None);
    }

    #[test]
    fn golden_log_tick_count() {
        let log = record_n_ticks(5);
        assert_eq!(log.tick_count(), 5);
    }

    #[test]
    fn golden_log_is_compatible_matching_versions() {
        let log = GoldenLog::new("0.1.0", 1);
        assert!(log.is_compatible("0.1.0", 1));
    }

    #[test]
    fn golden_log_is_incompatible_schema_mismatch() {
        let log = GoldenLog::new("0.1.0", 1);
        assert!(!log.is_compatible("0.2.0", 1));
    }

    #[test]
    fn golden_log_is_incompatible_plan_version_mismatch() {
        let log = GoldenLog::new("0.1.0", 1);
        assert!(!log.is_compatible("0.1.0", 2));
    }

    #[test]
    fn golden_log_iter_ordered_is_ascending() {
        let mut log = GoldenLog::new("0.1.0", 1);
        log.record(5, "h5");
        log.record(2, "h2");
        log.record(9, "h9");
        let ticks: Vec<u64> = log.iter_ordered().map(|(t, _)| t).collect();
        assert_eq!(ticks, vec![2, 5, 9]);
    }

    #[test]
    fn golden_log_end_tick_tracks_max() {
        let mut log = GoldenLog::new("0.1.0", 1);
        log.record(3, "h3");
        log.record(10, "h10");
        log.record(7, "h7");
        assert_eq!(log.end_tick, 10);
    }

    // ── Recording Tests ───────────────────────────────────────────────────────

    #[test]
    fn recording_produces_golden_log_with_correct_tick_count() {
        let log = record_n_ticks(10);
        assert_eq!(log.tick_count(), 10);
        assert!(!log.is_empty());
    }

    #[test]
    fn recording_hashes_are_deterministic() {
        // Same snapshots recorded twice must produce identical GoldenLogs
        let log_a = record_n_ticks(5);
        let log_b = record_n_ticks(5);
        for tick in 0..5 {
            assert_eq!(
                log_a.get(tick),
                log_b.get(tick),
                "GoldenLog hash at tick {} must be identical across recordings",
                tick
            );
        }
    }

    #[test]
    fn record_tick_fails_when_not_in_recording_mode() {
        let mut v = ReplayValidator::new(GuardMode::Strict);
        // begin_recording() not called
        let result = v.record_tick(&snap(0));
        assert!(result.is_err());
    }

    #[test]
    fn finish_recording_fails_when_not_recording() {
        let mut v = ReplayValidator::new(GuardMode::Strict);
        assert!(v.finish_recording().is_err());
    }

    #[test]
    fn status_is_idle_after_finish_recording() {
        let mut v = ReplayValidator::new(GuardMode::Strict);
        v.begin_recording("0.1.0", 1);
        v.record_tick(&snap(0)).unwrap();
        v.finish_recording().unwrap();
        assert_eq!(v.status(), ReplayStatus::Idle);
    }

    // ── Validation Tests ──────────────────────────────────────────────────────

    #[test]
    fn validation_passes_for_identical_replay() {
        let log = record_n_ticks(5);
        let mut v = ReplayValidator::new(GuardMode::Strict);
        v.begin_validation(log, "0.1.0", 1).unwrap();

        // Replay the exact same snapshots
        for tick in 0..5 {
            assert!(v.validate_tick(&snap(tick)).is_ok());
        }

        let report = v.finish_validation();
        assert!(report.passed(), "Identical replay must pass");
        assert_eq!(report.divergence_count(), 0);
        assert_eq!(report.validated_tick_count, 5);
        assert_eq!(report.unvalidated_golden_ticks, 0);
    }

    #[test]
    fn validation_fails_for_diverged_tick_in_strict_mode() {
        let log = record_n_ticks(5);
        let mut v = ReplayValidator::new(GuardMode::Strict);
        v.begin_validation(log, "0.1.0", 1).unwrap();

        // Validate tick 0 and 1 correctly
        v.validate_tick(&snap(0)).unwrap();
        v.validate_tick(&snap(1)).unwrap();

        // Inject a diverged snapshot at tick 2 — different entity count changes hash
        let mut diverged = snap(2);
        diverged.schema_version = "diverged".into(); // mutate to force hash mismatch
        let result = v.validate_tick(&diverged);

        assert!(result.is_err(), "STRICT mode must return Err on divergence");
        assert_eq!(v.status(), ReplayStatus::Diverged);
        assert_eq!(v.divergences().len(), 1);
        assert_eq!(v.divergences()[0].divergence_type, DivergenceType::WorldHashMismatch);
    }

    #[test]
    fn validation_accumulates_divergences_in_silent_mode() {
        let log = record_n_ticks(5);
        let mut v = ReplayValidator::new(GuardMode::Silent);
        v.begin_validation(log, "0.1.0", 1).unwrap();

        // Diverge on ticks 1 and 3
        v.validate_tick(&snap(0)).unwrap();
        let mut bad1 = snap(1);
        bad1.schema_version = "bad".into();
        v.validate_tick(&bad1).unwrap(); // SILENT — continues

        v.validate_tick(&snap(2)).unwrap();
        let mut bad3 = snap(3);
        bad3.schema_version = "bad".into();
        v.validate_tick(&bad3).unwrap(); // SILENT — continues

        v.validate_tick(&snap(4)).unwrap();

        let report = v.finish_validation();
        assert!(!report.passed());
        assert_eq!(report.divergence_count(), 2);
    }

    #[test]
    fn unrecorded_tick_produces_correct_divergence_type() {
        let log = record_n_ticks(3); // Records ticks 0, 1, 2
        let mut v = ReplayValidator::new(GuardMode::Silent);
        v.begin_validation(log, "0.1.0", 1).unwrap();

        for tick in 0..3 {
            v.validate_tick(&snap(tick)).unwrap();
        }
        // Tick 5 — not in GoldenLog
        v.validate_tick(&snap(5)).unwrap();

        assert_eq!(v.divergences()[0].divergence_type, DivergenceType::UnrecordedTick);
    }

    #[test]
    fn schema_mismatch_blocks_begin_validation() {
        let log = GoldenLog::new("0.1.0", 1);
        let mut v = ReplayValidator::new(GuardMode::Strict);
        let result = v.begin_validation(log, "0.9.9", 1); // Wrong schema
        assert!(result.is_err());
        assert_eq!(v.status(), ReplayStatus::Idle);
    }

    #[test]
    fn validate_tick_fails_when_not_validating() {
        let mut v = ReplayValidator::new(GuardMode::Strict);
        // begin_validation() not called
        let result = v.validate_tick(&snap(0));
        assert!(result.is_err());
    }

    #[test]
    fn unvalidated_ticks_counted_when_replay_ends_early() {
        let log = record_n_ticks(10); // 10 ticks recorded
        let mut v = ReplayValidator::new(GuardMode::Strict);
        v.begin_validation(log, "0.1.0", 1).unwrap();

        // Only replay 4 ticks out of 10
        for tick in 0..4 {
            v.validate_tick(&snap(tick)).unwrap();
        }

        let report = v.finish_validation();
        assert!(!report.is_full_pass);
        assert_eq!(report.validated_tick_count, 4);
        assert_eq!(report.unvalidated_golden_ticks, 6);
    }

    // ── Report Tests ──────────────────────────────────────────────────────────

    #[test]
    fn report_summary_not_empty() {
        let log = record_n_ticks(3);
        let mut v = ReplayValidator::new(GuardMode::Strict);
        v.begin_validation(log, "0.1.0", 1).unwrap();
        for tick in 0..3 {
            v.validate_tick(&snap(tick)).unwrap();
        }
        let report = v.finish_validation();
        let summary = report.summary();
        assert!(!summary.is_empty());
        assert!(summary.contains("PASSED"));
    }

    #[test]
    fn failed_report_summary_contains_failed() {
        let log = record_n_ticks(3);
        let mut v = ReplayValidator::new(GuardMode::Silent);
        v.begin_validation(log, "0.1.0", 1).unwrap();
        let mut bad = snap(0);
        bad.schema_version = "bad".into();
        v.validate_tick(&bad).unwrap();
        let report = v.finish_validation();
        assert!(report.summary().contains("FAILED"));
    }

    #[test]
    fn divergence_summary_contains_tick() {
        let d = ReplayDivergence::hash_mismatch(42, "golden", "replay", "0.1.0");
        assert!(d.summary().contains("42"));
    }

    #[test]
    fn status_is_passed_after_clean_validation() {
        let log = record_n_ticks(3);
        let mut v = ReplayValidator::new(GuardMode::Strict);
        v.begin_validation(log, "0.1.0", 1).unwrap();
        for tick in 0..3 {
            v.validate_tick(&snap(tick)).unwrap();
        }
        v.finish_validation();
        // After finish_validation, status is reset to Idle per spec
        assert_eq!(v.status(), ReplayStatus::Idle);
    }

    #[test]
    fn validated_tick_count_increments_only_on_match() {
        let log = record_n_ticks(5);
        let mut v = ReplayValidator::new(GuardMode::Silent);
        v.begin_validation(log, "0.1.0", 1).unwrap();

        v.validate_tick(&snap(0)).unwrap(); // match
        v.validate_tick(&snap(1)).unwrap(); // match

        let mut bad = snap(2);
        bad.schema_version = "bad".into();
        v.validate_tick(&bad).unwrap(); // mismatch — not counted

        assert_eq!(v.validated_tick_count(), 2);
    }

    #[test]
    fn replay_status_display() {
        assert_eq!(ReplayStatus::Idle.to_string(), "IDLE");
        assert_eq!(ReplayStatus::Recording.to_string(), "RECORDING");
        assert_eq!(ReplayStatus::Validating.to_string(), "VALIDATING");
        assert_eq!(ReplayStatus::Passed.to_string(), "PASSED");
        assert_eq!(ReplayStatus::Diverged.to_string(), "DIVERGED");
    }

    #[test]
    fn divergence_type_display() {
        assert_eq!(
            DivergenceType::WorldHashMismatch.to_string(),
            "WORLD_HASH_MISMATCH"
        );
        assert_eq!(
            DivergenceType::UnrecordedTick.to_string(),
            "UNRECORDED_TICK"
        );
        assert_eq!(
            DivergenceType::SchemaVersionMismatch.to_string(),
            "SCHEMA_VERSION_MISMATCH"
        );
    }
}