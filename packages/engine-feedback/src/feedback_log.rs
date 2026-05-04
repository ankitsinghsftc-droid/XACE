//! # Feedback Log
//!
//! Append-only log of all `FeedbackMessage` values received from the engine
//! adapter, keyed by simulation tick. Required for exact replay fidelity (D14).
//!
//! ## Why Replay Needs Feedback
//! CLAUDE.md states: *"Replays must replay the same feedback sequence to
//! produce identical world state."* Consider a physics ragdoll: the engine
//! sends `PhysicsSettled` feedback at tick 150 with a final position.
//! The `PhysicsFeedbackHandler` writes that position to `COMP_TRANSFORM_V1`
//! via the Mutation Gate. If replay does not inject the same feedback at
//! tick 150, `COMP_TRANSFORM_V1` will have a different value, the world_hash
//! will diverge, and the replay fails.
//!
//! ## Structure
//! `BTreeMap<tick, Vec<FeedbackMessage>>` — tick-keyed, insertion-ordered
//! within each tick. The sort order within a tick matches the drain sort
//! order from `FeedbackBuffer` (`generated_frame ASC, entity_id ASC`) because
//! messages are logged after the buffer sorts them.
//!
//! ## Append-Only Guarantee
//! Once written, a log entry is never modified or deleted.
//! This mirrors the WorldSnapshot append-only snapshot chain contract.
//! Replay tools read the log forward — never backward.
//!
//! ## Serialization
//! The log can be serialized to JSON for offline storage and CI replay tests.
//! Same determinism rules apply: `BTreeMap` keys ensure stable JSON output.
//!
//! ## Memory Management
//! The log is unbounded by default. For long sessions, use `trim_before()`
//! to release feedback older than the oldest retained WorldSnapshot tick.
//! Feedback older than the earliest rollback point is never needed.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

use xace_core::entity_metadata::Tick;
use xace_core::wire::feedback_payload::FeedbackMessage;

// ── Log Entry ─────────────────────────────────────────────────────────────────

/// All feedback messages received during one simulation tick.
///
/// Messages are stored in the order they were drained from the
/// `FeedbackBuffer` — `(generated_frame ASC, entity_id ASC)` (I13).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FeedbackLogEntry {
    /// The simulation tick this entry belongs to.
    pub tick: Tick,

    /// All feedback messages for this tick, in drain order.
    pub messages: Vec<FeedbackMessage>,

    /// Total message count cached for fast access.
    pub message_count: usize,
}

impl FeedbackLogEntry {
    fn new(tick: Tick, messages: Vec<FeedbackMessage>) -> Self {
        let count = messages.len();
        Self {
            tick,
            messages,
            message_count: count,
        }
    }

    /// Returns true if there were no feedback messages at this tick.
    pub fn is_empty(&self) -> bool {
        self.messages.is_empty()
    }
}

// ── Log Metrics ───────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Default)]
pub struct FeedbackLogMetrics {
    /// Total messages ever appended.
    pub total_messages_logged: u64,
    /// Total ticks recorded.
    pub ticks_recorded: u64,
    /// Ticks with zero messages (still recorded for tick completeness).
    pub empty_ticks: u64,
    /// Total messages removed by `trim_before()` calls.
    pub messages_trimmed: u64,
    /// Times `trim_before()` was called.
    pub trim_count: u64,
}

// ── Feedback Log ──────────────────────────────────────────────────────────────

/// Append-only, tick-keyed record of all engine feedback for replay fidelity.
///
/// Written by the PhaseOrchestrator at tick START, immediately after
/// `FeedbackBuffer::drain_sorted()` and before handlers process messages.
/// Read by `FeedbackReplayLoader` during replay.
#[derive(Debug, Serialize, Deserialize)]
pub struct FeedbackLog {
    /// BTreeMap<tick, FeedbackLogEntry> — stable ordering for serialization (D11).
    entries: BTreeMap<Tick, FeedbackLogEntry>,

    /// Session schema version — validated by the replay loader before use.
    schema_version: String,

    /// ExecutionPlan version — validated by the replay loader.
    execution_plan_version: u32,

    /// The first tick recorded in this log.
    start_tick: Tick,

    /// The most recently recorded tick.
    end_tick: Tick,

    #[serde(skip)]
    metrics: FeedbackLogMetrics,
}

impl FeedbackLog {
    // ── Construction ──────────────────────────────────────────────────────────

    /// Creates a new empty log for the given session contract.
    pub fn new(schema_version: impl Into<String>, execution_plan_version: u32) -> Self {
        Self {
            entries: BTreeMap::new(),
            schema_version: schema_version.into(),
            execution_plan_version,
            start_tick: 0,
            end_tick: 0,
            metrics: FeedbackLogMetrics::default(),
        }
    }

    // ── Primary API ───────────────────────────────────────────────────────────

    /// Records all feedback messages for a simulation tick.
    ///
    /// Must be called once per tick, immediately after `FeedbackBuffer::drain_sorted()`.
    /// Messages must already be in drain sort order (`generated_frame ASC, entity_id ASC`).
    /// An empty `messages` vec is still recorded — absence of feedback is meaningful
    /// for replay (the replay loader will inject no feedback at that tick).
    ///
    /// Calling `record_tick()` for a tick that already has an entry overwrites it.
    /// This should never happen in normal operation (one drain per tick).
    pub fn record_tick(&mut self, tick: Tick, messages: Vec<FeedbackMessage>) {
        let msg_count = messages.len();
        let is_empty = messages.is_empty();

        if self.entries.is_empty() {
            self.start_tick = tick;
        }
        self.end_tick = tick.max(self.end_tick);

        self.entries.insert(tick, FeedbackLogEntry::new(tick, messages));

        self.metrics.ticks_recorded += 1;
        self.metrics.total_messages_logged += msg_count as u64;
        if is_empty {
            self.metrics.empty_ticks += 1;
        }
    }

    /// Returns the log entry for a specific tick, if present.
    pub fn get(&self, tick: Tick) -> Option<&FeedbackLogEntry> {
        self.entries.get(&tick)
    }

    /// Returns the messages for a specific tick, or an empty slice if none.
    pub fn messages_at(&self, tick: Tick) -> &[FeedbackMessage] {
        self.entries
            .get(&tick)
            .map(|e| e.messages.as_slice())
            .unwrap_or(&[])
    }

    // ── Memory Management ─────────────────────────────────────────────────────

    /// Removes all entries for ticks before `cutoff_tick`.
    ///
    /// Call when old WorldSnapshots are purged — feedback older than the
    /// earliest rollback point is never needed and wastes memory.
    /// Returns the number of messages removed.
    pub fn trim_before(&mut self, cutoff_tick: Tick) -> u64 {
        let to_remove: Vec<Tick> = self
            .entries
            .keys()
            .copied()
            .filter(|&t| t < cutoff_tick)
            .collect();

        let mut removed_msgs = 0u64;
        for tick in to_remove {
            if let Some(entry) = self.entries.remove(&tick) {
                removed_msgs += entry.message_count as u64;
            }
        }

        if removed_msgs > 0 {
            self.metrics.messages_trimmed += removed_msgs;
            self.metrics.trim_count += 1;
            // Update start_tick to reflect what remains
            if let Some(&new_start) = self.entries.keys().next() {
                self.start_tick = new_start;
            }
        }

        removed_msgs
    }

    // ── Inspection ────────────────────────────────────────────────────────────

    /// Returns the number of ticks currently recorded.
    pub fn tick_count(&self) -> usize {
        self.entries.len()
    }

    /// Returns true if the log has no entries.
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    /// Returns the first recorded tick.
    pub fn start_tick(&self) -> Tick {
        self.start_tick
    }

    /// Returns the last recorded tick.
    pub fn end_tick(&self) -> Tick {
        self.end_tick
    }

    /// Returns the schema version this log was recorded against.
    pub fn schema_version(&self) -> &str {
        &self.schema_version
    }

    /// Returns the execution plan version this log was recorded against.
    pub fn execution_plan_version(&self) -> u32 {
        self.execution_plan_version
    }

    /// Returns true if this log is compatible with the given session contract.
    /// Used by `FeedbackReplayLoader` before loading.
    pub fn is_compatible(&self, schema_version: &str, execution_plan_version: u32) -> bool {
        self.schema_version == schema_version
            && self.execution_plan_version == execution_plan_version
    }

    /// Returns accumulated log metrics.
    pub fn metrics(&self) -> &FeedbackLogMetrics {
        &self.metrics
    }

    /// Returns an iterator over all entries in tick ascending order.
    pub fn iter_ordered(&self) -> impl Iterator<Item = (Tick, &FeedbackLogEntry)> {
        self.entries.iter().map(|(&tick, entry)| (tick, entry))
    }

    /// Returns total message count across all recorded ticks.
    pub fn total_message_count(&self) -> usize {
        self.entries.values().map(|e| e.message_count).sum()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::wire::feedback_payload::FeedbackType;

    fn msg(entity_id: u64, frame: u64) -> FeedbackMessage {
        FeedbackMessage {
            feedback_type: FeedbackType::PhysicsSettled,
            entity_id,
            generated_frame: frame,
            payload_json: "{}".into(),
        }
    }

    fn log() -> FeedbackLog {
        FeedbackLog::new("0.1.0", 1)
    }

    // ── Record and Retrieve ───────────────────────────────────────────────────

    #[test]
    fn empty_log_has_no_entries() {
        let l = log();
        assert!(l.is_empty());
        assert_eq!(l.tick_count(), 0);
    }

    #[test]
    fn record_tick_stores_messages() {
        let mut l = log();
        l.record_tick(1, vec![msg(1, 1), msg(2, 1)]);
        assert_eq!(l.tick_count(), 1);
        assert_eq!(l.messages_at(1).len(), 2);
    }

    #[test]
    fn record_empty_tick_still_creates_entry() {
        let mut l = log();
        l.record_tick(5, vec![]);
        assert!(l.get(5).is_some());
        assert!(l.get(5).unwrap().is_empty());
        assert_eq!(l.metrics().empty_ticks, 1);
    }

    #[test]
    fn get_returns_none_for_unrecorded_tick() {
        let l = log();
        assert!(l.get(999).is_none());
    }

    #[test]
    fn messages_at_returns_empty_slice_for_unrecorded_tick() {
        let l = log();
        assert_eq!(l.messages_at(42).len(), 0);
    }

    #[test]
    fn start_and_end_tick_tracked() {
        let mut l = log();
        l.record_tick(5, vec![msg(1, 5)]);
        l.record_tick(10, vec![msg(1, 10)]);
        l.record_tick(3, vec![msg(1, 3)]);
        assert_eq!(l.start_tick(), 5); // first recorded
        assert_eq!(l.end_tick(), 10);  // max
    }

    #[test]
    fn total_message_count_sums_across_ticks() {
        let mut l = log();
        l.record_tick(1, vec![msg(1, 1), msg(2, 1)]);
        l.record_tick(2, vec![msg(3, 2)]);
        assert_eq!(l.total_message_count(), 3);
    }

    // ── Trim ──────────────────────────────────────────────────────────────────

    #[test]
    fn trim_before_removes_old_ticks() {
        let mut l = log();
        for tick in 0..10 {
            l.record_tick(tick, vec![msg(1, tick)]);
        }
        let removed = l.trim_before(5);
        assert_eq!(l.tick_count(), 5); // ticks 5–9 remain
        assert_eq!(removed, 5);        // 5 messages removed (one per tick)
        assert_eq!(l.metrics().messages_trimmed, 5);
    }

    #[test]
    fn trim_before_updates_start_tick() {
        let mut l = log();
        for tick in 0..5 {
            l.record_tick(tick, vec![msg(1, tick)]);
        }
        l.trim_before(3);
        assert_eq!(l.start_tick(), 3);
    }

    #[test]
    fn trim_before_zero_removes_nothing() {
        let mut l = log();
        l.record_tick(5, vec![msg(1, 5)]);
        let removed = l.trim_before(0);
        assert_eq!(removed, 0);
        assert_eq!(l.tick_count(), 1);
    }

    // ── Compatibility ─────────────────────────────────────────────────────────

    #[test]
    fn is_compatible_matching_versions() {
        let l = FeedbackLog::new("0.1.0", 1);
        assert!(l.is_compatible("0.1.0", 1));
    }

    #[test]
    fn is_compatible_wrong_schema() {
        let l = FeedbackLog::new("0.1.0", 1);
        assert!(!l.is_compatible("0.2.0", 1));
    }

    #[test]
    fn is_compatible_wrong_plan_version() {
        let l = FeedbackLog::new("0.1.0", 1);
        assert!(!l.is_compatible("0.1.0", 2));
    }

    // ── Iteration ─────────────────────────────────────────────────────────────

    #[test]
    fn iter_ordered_yields_ticks_ascending() {
        let mut l = log();
        l.record_tick(5, vec![msg(1, 5)]);
        l.record_tick(1, vec![msg(1, 1)]);
        l.record_tick(3, vec![msg(1, 3)]);
        let ticks: Vec<Tick> = l.iter_ordered().map(|(t, _)| t).collect();
        assert_eq!(ticks, vec![1, 3, 5]);
    }

    // ── Serialization ─────────────────────────────────────────────────────────

    #[test]
    fn log_serializes_and_deserializes() {
        let mut l = FeedbackLog::new("0.1.0", 1);
        l.record_tick(1, vec![msg(1, 1), msg(2, 1)]);
        l.record_tick(2, vec![msg(3, 2)]);

        let json = serde_json::to_string(&l).unwrap();
        let restored: FeedbackLog = serde_json::from_str(&json).unwrap();

        assert_eq!(restored.tick_count(), 2);
        assert_eq!(restored.messages_at(1).len(), 2);
        assert_eq!(restored.messages_at(2).len(), 1);
        assert_eq!(restored.schema_version(), "0.1.0");
    }

    // ── Metrics ───────────────────────────────────────────────────────────────

    #[test]
    fn metrics_count_ticks_and_messages() {
        let mut l = log();
        l.record_tick(1, vec![msg(1, 1), msg(2, 1)]);
        l.record_tick(2, vec![]);
        l.record_tick(3, vec![msg(3, 3)]);

        let m = l.metrics();
        assert_eq!(m.ticks_recorded, 3);
        assert_eq!(m.total_messages_logged, 3);
        assert_eq!(m.empty_ticks, 1);
    }
}