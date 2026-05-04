//! # Sequence Tracker
//!
//! Detects dropped, out-of-order, and duplicate WireMessages by tracking
//! the monotonically increasing `sequence_id` field on each message type.
//!
//! ## Why Sequence Tracking
//! TCP guarantees delivery order for a single stream, but XACE must also
//! handle the shared-memory transport (ShmTransport), UDP-based transports
//! in future multiplayer work (Phase 15), and cases where the engine adapter
//! reconnects mid-session. In all these cases, sequence gaps are possible.
//!
//! Even on TCP, sequence tracking provides a safety net: if the transport
//! layer ever delivers a message from a stale connection (reconnect race),
//! the sequence check catches it before any state is corrupted.
//!
//! ## Per-Type Sequences
//! Each `MessageType` tracks its own independent sequence counter:
//!
//! ```text
//! DELTA    — incremented every tick that produces a non-empty delta
//! SNAPSHOT — incremented every time a full snapshot is sent
//! FEEDBACK — incremented every tick the engine sends feedback
//! INPUT    — incremented every tick the engine sends input
//! CONTROL  — incremented per control message (handshake, ping, etc.)
//! EVENT    — incremented per event message
//! ```
//!
//! Mixing counters across types would produce false gap alerts when a DELTA
//! and a FEEDBACK arrive in the same delivery batch.
//!
//! ## Gap Detection → SNAPSHOT Recovery
//! When a gap is detected in the DELTA sequence (the most critical type),
//! the caller should immediately request a full SNAPSHOT from XACE.
//! `SequenceCheckResult::Gap` carries the exact expected and received IDs
//! so the recovery request can include diagnostic context.
//!
//! ## Reset After SNAPSHOT
//! `SnapshotPayload.last_delta_sequence_id` tells the adapter what sequence
//! number the next DELTA will carry. Call `reset_sequence()` after receiving
//! a SNAPSHOT to re-anchor the tracker to the correct baseline.
//!
//! ## Determinism Note
//! The SequenceTracker is a pure state machine — no I/O, no randomness.
//! It is not part of the authoritative simulation state and does not affect
//! world_hash. It lives in the engine adapter layer (Layer 6) only.

use std::collections::BTreeMap;

use xace_core::wire::message_type::MessageType;
use xace_core::wire::wire_message::WireMessage;

// ── Sequence Check Result ─────────────────────────────────────────────────────

/// The outcome of checking one message's sequence_id.
///
/// The caller uses this to decide whether to process, discard, or recover.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SequenceCheckResult {
    /// Message arrived with the expected sequence_id. Process normally.
    InOrder,

    /// One or more messages were dropped between the last seen sequence_id
    /// and this one. For DELTA gaps, the caller should request a SNAPSHOT.
    Gap {
        /// The sequence_id we expected.
        expected: u64,
        /// The sequence_id we received.
        received: u64,
        /// Number of messages that were missed: `received - expected`.
        missed_count: u64,
    },

    /// Message arrived with a sequence_id below the current expected value.
    /// This can happen when a retransmitted or delayed message arrives after
    /// we have already moved past it. Discard — do not process.
    OutOfOrder {
        /// The sequence_id we expected.
        expected: u64,
        /// The sequence_id we received.
        received: u64,
    },

    /// Exact duplicate — sequence_id matches one we already processed.
    /// Discard — do not process.
    Duplicate {
        sequence_id: u64,
    },

    /// First message of this type ever seen. Treated as in-order.
    /// The tracker anchors to this sequence_id as the new baseline.
    FirstMessage {
        sequence_id: u64,
    },
}

impl SequenceCheckResult {
    /// Returns true if the message should be processed (InOrder or FirstMessage).
    pub fn should_process(&self) -> bool {
        matches!(
            self,
            SequenceCheckResult::InOrder | SequenceCheckResult::FirstMessage { .. }
        )
    }

    /// Returns true if a gap was detected.
    pub fn is_gap(&self) -> bool {
        matches!(self, SequenceCheckResult::Gap { .. })
    }

    /// Returns true if the message should be discarded without processing.
    pub fn should_discard(&self) -> bool {
        matches!(
            self,
            SequenceCheckResult::OutOfOrder { .. } | SequenceCheckResult::Duplicate { .. }
        )
    }

    /// Returns the number of missed messages if this is a Gap, else 0.
    pub fn missed_count(&self) -> u64 {
        match self {
            SequenceCheckResult::Gap { missed_count, .. } => *missed_count,
            _ => 0,
        }
    }
}

impl std::fmt::Display for SequenceCheckResult {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            SequenceCheckResult::InOrder =>
                write!(f, "IN_ORDER"),
            SequenceCheckResult::Gap { expected, received, missed_count } =>
                write!(f, "GAP(expected={}, received={}, missed={})", expected, received, missed_count),
            SequenceCheckResult::OutOfOrder { expected, received } =>
                write!(f, "OUT_OF_ORDER(expected={}, received={})", expected, received),
            SequenceCheckResult::Duplicate { sequence_id } =>
                write!(f, "DUPLICATE(seq={})", sequence_id),
            SequenceCheckResult::FirstMessage { sequence_id } =>
                write!(f, "FIRST(seq={})", sequence_id),
        }
    }
}

// ── Per-Type State ────────────────────────────────────────────────────────────

/// Tracking state for one MessageType.
#[derive(Debug, Clone)]
struct TypeSequenceState {
    /// The next sequence_id we expect to receive.
    /// None = no message of this type has been seen yet.
    next_expected: Option<u64>,

    /// Total messages of this type received in order.
    in_order_count: u64,

    /// Total gaps detected for this type.
    gap_count: u64,

    /// Total out-of-order messages discarded.
    out_of_order_count: u64,

    /// Total duplicate messages discarded.
    duplicate_count: u64,

    /// Total messages missed due to gaps (cumulative missed_count across all Gap events).
    total_missed: u64,
}

impl TypeSequenceState {
    fn new() -> Self {
        Self {
            next_expected: None,
            in_order_count: 0,
            gap_count: 0,
            out_of_order_count: 0,
            duplicate_count: 0,
            total_missed: 0,
        }
    }

    /// Checks `sequence_id` and advances the state if in-order.
    fn check_and_advance(&mut self, sequence_id: u64) -> SequenceCheckResult {
        match self.next_expected {
            // ── First message of this type ─────────────────────────────────
            None => {
                self.next_expected = Some(sequence_id + 1);
                self.in_order_count += 1;
                SequenceCheckResult::FirstMessage { sequence_id }
            }

            Some(expected) => {
                if sequence_id == expected {
                    // ── In order ───────────────────────────────────────────
                    self.next_expected = Some(expected + 1);
                    self.in_order_count += 1;
                    SequenceCheckResult::InOrder

                } else if sequence_id > expected {
                    // ── Gap ────────────────────────────────────────────────
                    let missed = sequence_id - expected;
                    self.gap_count += 1;
                    self.total_missed += missed;
                    // Advance past the gap — we cannot recover the lost messages.
                    // The caller will request a SNAPSHOT for DELTA gaps.
                    self.next_expected = Some(sequence_id + 1);
                    SequenceCheckResult::Gap {
                        expected,
                        received: sequence_id,
                        missed_count: missed,
                    }

                } else if sequence_id == expected.saturating_sub(1) {
                    // ── Duplicate — exactly one behind ─────────────────────
                    self.duplicate_count += 1;
                    SequenceCheckResult::Duplicate { sequence_id }

                } else {
                    // ── Out of order — more than one behind ────────────────
                    self.out_of_order_count += 1;
                    SequenceCheckResult::OutOfOrder {
                        expected,
                        received: sequence_id,
                    }
                }
            }
        }
    }

    /// Resets the expected sequence to a known-good value.
    /// Called after receiving a SNAPSHOT that re-establishes the baseline.
    fn reset_to(&mut self, next_expected: u64) {
        self.next_expected = Some(next_expected);
    }
}

// ── Tracker Metrics ───────────────────────────────────────────────────────────

/// A snapshot of sequence tracking statistics for one message type.
#[derive(Debug, Clone, Default)]
pub struct TypeMetrics {
    /// Next expected sequence_id. None if no messages seen yet.
    pub next_expected: Option<u64>,
    /// Messages received in order.
    pub in_order_count: u64,
    /// Gaps detected.
    pub gap_count: u64,
    /// Out-of-order messages discarded.
    pub out_of_order_count: u64,
    /// Duplicate messages discarded.
    pub duplicate_count: u64,
    /// Total messages missed due to gaps.
    pub total_missed: u64,
}

/// Aggregated metrics across all tracked message types.
#[derive(Debug, Clone, Default)]
pub struct SequenceTrackerMetrics {
    /// Metrics broken down by MessageType discriminant (0–5).
    /// Use `MessageType::as_u8()` as the key.
    pub by_type: BTreeMap<u8, TypeMetrics>,

    /// Total DELTA gaps across all time — the most important health signal.
    pub total_delta_gaps: u64,

    /// Total messages missed due to DELTA gaps.
    pub total_delta_missed: u64,

    /// Total times the tracker was reset (one per SNAPSHOT received).
    pub reset_count: u64,
}

// ── Sequence Tracker ──────────────────────────────────────────────────────────

/// Detects dropped, out-of-order, and duplicate WireMessages by tracking
/// monotonically increasing `sequence_id` fields per `MessageType`.
///
/// ## Usage
/// ```ignore
/// let mut tracker = SequenceTracker::new();
///
/// // On every received WireMessage:
/// let result = tracker.check(&wire_message);
/// match result {
///     SequenceCheckResult::InOrder | SequenceCheckResult::FirstMessage { .. } => {
///         // process the message normally
///     }
///     SequenceCheckResult::Gap { .. } if wire_message.is_delta() => {
///         // request SNAPSHOT recovery
///     }
///     SequenceCheckResult::OutOfOrder { .. } | SequenceCheckResult::Duplicate { .. } => {
///         // discard — do not process
///     }
///     _ => {}
/// }
///
/// // After receiving a SNAPSHOT:
/// tracker.reset_after_snapshot(snapshot_payload.last_delta_sequence_id + 1);
/// ```
pub struct SequenceTracker {
    /// Per-type tracking state.
    /// Keyed by MessageType::as_u8() for O(1) lookup.
    states: [TypeSequenceState; 6],

    /// Total reset operations performed.
    reset_count: u64,
}

impl SequenceTracker {
    // ── Construction ──────────────────────────────────────────────────────────

    /// Creates a new SequenceTracker with no prior history.
    ///
    /// The tracker anchors to whatever sequence_id it sees first
    /// for each message type (FirstMessage result).
    pub fn new() -> Self {
        Self {
            states: [
                TypeSequenceState::new(), // Snapshot (0)
                TypeSequenceState::new(), // Delta    (1)
                TypeSequenceState::new(), // Input    (2)
                TypeSequenceState::new(), // Event    (3)
                TypeSequenceState::new(), // Control  (4)
                TypeSequenceState::new(), // Feedback (5)
            ],
            reset_count: 0,
        }
    }

    /// Creates a SequenceTracker pre-anchored to a known DELTA sequence_id.
    ///
    /// Call this when you receive the HandshakeAck and know the
    /// `initial_delta_sequence_id` that the first DELTA will carry.
    /// This prevents the first DELTA from appearing as a FirstMessage
    /// and allows detecting a gap even in the very first tick.
    pub fn with_initial_delta_sequence(initial_delta_sequence_id: u64) -> Self {
        let mut tracker = Self::new();
        tracker.states[MessageType::Delta.as_u8() as usize]
            .next_expected = Some(initial_delta_sequence_id);
        tracker
    }

    // ── Primary API ───────────────────────────────────────────────────────────

    /// Checks the sequence_id of a received WireMessage and advances the tracker.
    ///
    /// Returns the `SequenceCheckResult` for the caller to act on.
    /// Automatically advances the expected sequence for InOrder and FirstMessage.
    /// Does NOT advance the expected sequence for Gap, OutOfOrder, or Duplicate.
    /// (For Gap, the state is advanced to `received + 1` to skip over the lost messages.)
    pub fn check(&mut self, msg: &WireMessage) -> SequenceCheckResult {
        let type_idx = msg.message_type.as_u8() as usize;
        self.states[type_idx].check_and_advance(msg.sequence_id)
    }

    /// Checks a (MessageType, sequence_id) pair directly without a WireMessage.
    ///
    /// Useful in tests and when the transport layer needs to check
    /// a sequence without constructing a full WireMessage.
    pub fn check_raw(&mut self, msg_type: MessageType, sequence_id: u64) -> SequenceCheckResult {
        let type_idx = msg_type.as_u8() as usize;
        self.states[type_idx].check_and_advance(sequence_id)
    }

    /// Resets the DELTA sequence tracker after receiving a full SNAPSHOT.
    ///
    /// Call this with `snapshot_payload.last_delta_sequence_id + 1` —
    /// the sequence_id the next DELTA message will carry.
    /// Other type sequences are unaffected.
    ///
    /// Must be called every time a SNAPSHOT is received — including the
    /// initial connection snapshot and all desync-recovery snapshots.
    pub fn reset_after_snapshot(&mut self, next_expected_delta_sequence: u64) {
        self.states[MessageType::Delta.as_u8() as usize]
            .reset_to(next_expected_delta_sequence);
        self.reset_count += 1;
    }

    /// Resets the sequence tracker for a specific MessageType.
    ///
    /// Use when a transport reconnect resets the sequence counter for
    /// one stream independently. For DELTA resets prefer `reset_after_snapshot`.
    pub fn reset_type(&mut self, msg_type: MessageType, next_expected: u64) {
        self.states[msg_type.as_u8() as usize].reset_to(next_expected);
    }

    /// Resets all sequence counters to unanchored state.
    ///
    /// Use only on full session restart — all prior sequence history is
    /// discarded and each type will re-anchor on the next message it sees.
    pub fn reset_all(&mut self) {
        for state in &mut self.states {
            *state = TypeSequenceState::new();
        }
        self.reset_count += 1;
    }

    // ── Inspection ────────────────────────────────────────────────────────────

    /// Returns the next expected sequence_id for a given message type.
    /// Returns None if no message of this type has been seen yet.
    pub fn next_expected(&self, msg_type: MessageType) -> Option<u64> {
        self.states[msg_type.as_u8() as usize].next_expected
    }

    /// Returns the last successfully processed sequence_id for a type.
    /// Returns None if no messages have been processed yet.
    pub fn last_processed(&self, msg_type: MessageType) -> Option<u64> {
        self.states[msg_type.as_u8() as usize]
            .next_expected
            .map(|next| next.saturating_sub(1))
    }

    /// Returns true if at least one DELTA gap has been detected this session.
    pub fn has_delta_gap(&self) -> bool {
        self.states[MessageType::Delta.as_u8() as usize].gap_count > 0
    }

    /// Returns the total number of DELTA gaps detected this session.
    pub fn delta_gap_count(&self) -> u64 {
        self.states[MessageType::Delta.as_u8() as usize].gap_count
    }

    /// Returns the total number of DELTA messages missed due to gaps.
    pub fn delta_missed_count(&self) -> u64 {
        self.states[MessageType::Delta.as_u8() as usize].total_missed
    }

    /// Returns true if the tracker is in a healthy state (no gaps of any type).
    pub fn is_healthy(&self) -> bool {
        self.states.iter().all(|s| s.gap_count == 0)
    }

    /// Builds a full metrics snapshot across all tracked types.
    pub fn metrics(&self) -> SequenceTrackerMetrics {
        let mut by_type = BTreeMap::new();

        for (idx, state) in self.states.iter().enumerate() {
            by_type.insert(idx as u8, TypeMetrics {
                next_expected: state.next_expected,
                in_order_count: state.in_order_count,
                gap_count: state.gap_count,
                out_of_order_count: state.out_of_order_count,
                duplicate_count: state.duplicate_count,
                total_missed: state.total_missed,
            });
        }

        SequenceTrackerMetrics {
            by_type,
            total_delta_gaps: self.states[MessageType::Delta.as_u8() as usize].gap_count,
            total_delta_missed: self.states[MessageType::Delta.as_u8() as usize].total_missed,
            reset_count: self.reset_count,
        }
    }

    /// Returns a concise one-line health summary for logging.
    ///
    /// Example: `"SequenceTracker[DELTA:ok(1024) FEEDBACK:ok(512) gaps:0]"`
    pub fn health_summary(&self) -> String {
        let delta = &self.states[MessageType::Delta.as_u8() as usize];
        let feedback = &self.states[MessageType::Feedback.as_u8() as usize];
        let input = &self.states[MessageType::Input.as_u8() as usize];

        let total_gaps: u64 = self.states.iter().map(|s| s.gap_count).sum();

        format!(
            "SequenceTracker[DELTA:{}({}) FEEDBACK:{}({}) INPUT:{}({}) gaps:{}]",
            if delta.gap_count == 0 { "ok" } else { "GAP" },
            delta.next_expected.unwrap_or(0),
            if feedback.gap_count == 0 { "ok" } else { "GAP" },
            feedback.next_expected.unwrap_or(0),
            if input.gap_count == 0 { "ok" } else { "GAP" },
            input.next_expected.unwrap_or(0),
            total_gaps,
        )
    }
}

impl Default for SequenceTracker {
    fn default() -> Self {
        Self::new()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::wire::message_type::MessageType;
    use xace_core::wire::wire_message::WireMessage;

    // ── Helpers ───────────────────────────────────────────────────────────────

    fn delta(seq: u64) -> WireMessage {
        WireMessage::delta(
            "default", "0.1.0", 1, seq, seq,
            r#"{"tick":1,"sequence_id":1,"schema_version":"0.1.0","spawned_entities":[],"added_components":[],"modified_entities":{},"removed_components":[],"destroyed_entities":[]}"#,
        )
    }

    fn feedback(seq: u64) -> WireMessage {
        WireMessage::feedback(
            "default", "0.1.0", 1, seq, seq,
            r#"{"feedback_type":"ANIMATION_STATE_UPDATE","data":{}}"#,
        )
    }

    fn snapshot_msg(seq: u64) -> WireMessage {
        WireMessage::snapshot(
            "default", "0.1.0", 1, 0, seq,
            r#"{"tick":0,"entities":[]}"#,
        )
    }

    // ── First Message ─────────────────────────────────────────────────────────

    #[test]
    fn first_delta_is_first_message() {
        let mut t = SequenceTracker::new();
        let result = t.check(&delta(1));
        assert!(matches!(result, SequenceCheckResult::FirstMessage { sequence_id: 1 }));
        assert!(result.should_process());
    }

    #[test]
    fn first_message_anchors_expected_sequence() {
        let mut t = SequenceTracker::new();
        t.check(&delta(100));
        assert_eq!(t.next_expected(MessageType::Delta), Some(101));
    }

    #[test]
    fn first_messages_tracked_independently_per_type() {
        let mut t = SequenceTracker::new();
        t.check(&delta(10));
        t.check(&feedback(20));
        assert_eq!(t.next_expected(MessageType::Delta), Some(11));
        assert_eq!(t.next_expected(MessageType::Feedback), Some(21));
    }

    #[test]
    fn unseen_type_returns_none_for_next_expected() {
        let t = SequenceTracker::new();
        assert_eq!(t.next_expected(MessageType::Delta), None);
        assert_eq!(t.next_expected(MessageType::Feedback), None);
    }

    // ── In Order ─────────────────────────────────────────────────────────────

    #[test]
    fn consecutive_deltas_all_in_order() {
        let mut t = SequenceTracker::new();
        t.check(&delta(1)); // FirstMessage
        for seq in 2..=100 {
            let result = t.check(&delta(seq));
            assert_eq!(result, SequenceCheckResult::InOrder, "seq={}", seq);
        }
    }

    #[test]
    fn in_order_advances_expected() {
        let mut t = SequenceTracker::new();
        t.check(&delta(0));
        t.check(&delta(1));
        t.check(&delta(2));
        assert_eq!(t.next_expected(MessageType::Delta), Some(3));
    }

    #[test]
    fn in_order_result_should_process() {
        let mut t = SequenceTracker::new();
        t.check(&delta(1));
        let result = t.check(&delta(2));
        assert!(result.should_process());
        assert!(!result.should_discard());
        assert!(!result.is_gap());
    }

    #[test]
    fn different_types_do_not_interfere() {
        let mut t = SequenceTracker::new();
        // Alternate DELTA and FEEDBACK
        t.check(&delta(1));
        t.check(&feedback(1));
        t.check(&delta(2));
        t.check(&feedback(2));
        assert_eq!(t.check(&delta(3)), SequenceCheckResult::InOrder);
        assert_eq!(t.check(&feedback(3)), SequenceCheckResult::InOrder);
    }

    // ── Gap Detection ─────────────────────────────────────────────────────────

    #[test]
    fn single_missing_message_detected_as_gap() {
        let mut t = SequenceTracker::new();
        t.check(&delta(1));
        let result = t.check(&delta(3)); // seq 2 was dropped
        assert!(matches!(
            result,
            SequenceCheckResult::Gap { expected: 2, received: 3, missed_count: 1 }
        ));
        assert!(result.is_gap());
        assert!(!result.should_process());
        assert_eq!(result.missed_count(), 1);
    }

    #[test]
    fn large_gap_reports_correct_missed_count() {
        let mut t = SequenceTracker::new();
        t.check(&delta(0));
        let result = t.check(&delta(100)); // 99 messages dropped
        assert!(matches!(
            result,
            SequenceCheckResult::Gap { expected: 1, received: 100, missed_count: 99 }
        ));
        assert_eq!(result.missed_count(), 99);
    }

    #[test]
    fn gap_advances_expected_past_the_gap() {
        let mut t = SequenceTracker::new();
        t.check(&delta(1));
        t.check(&delta(5)); // gap: 2,3,4 were lost
        assert_eq!(t.next_expected(MessageType::Delta), Some(6));
        // Next in-order message after the gap should succeed
        assert_eq!(t.check(&delta(6)), SequenceCheckResult::InOrder);
    }

    #[test]
    fn multiple_gaps_accumulate_counts() {
        let mut t = SequenceTracker::new();
        t.check(&delta(0));
        t.check(&delta(2));  // gap: 1 missed
        t.check(&delta(5));  // gap: 3,4 missed
        t.check(&delta(10)); // gap: 6,7,8,9 missed
        assert_eq!(t.delta_gap_count(), 3);
        assert_eq!(t.delta_missed_count(), 1 + 2 + 4);
    }

    #[test]
    fn gap_only_in_delta_does_not_affect_feedback() {
        let mut t = SequenceTracker::new();
        t.check(&delta(0));
        t.check(&delta(5)); // gap in DELTA
        t.check(&feedback(0));
        t.check(&feedback(1));
        // DELTA has a gap but FEEDBACK is fine
        assert!(t.states[MessageType::Delta.as_u8() as usize].gap_count > 0);
        assert_eq!(t.states[MessageType::Feedback.as_u8() as usize].gap_count, 0);
    }

    // ── Out of Order ──────────────────────────────────────────────────────────

    #[test]
    fn old_message_detected_as_out_of_order() {
        let mut t = SequenceTracker::new();
        t.check(&delta(5));
        t.check(&delta(6));
        let result = t.check(&delta(3)); // very old — should be discarded
        assert!(matches!(
            result,
            SequenceCheckResult::OutOfOrder { expected: 7, received: 3 }
        ));
        assert!(result.should_discard());
        assert!(!result.should_process());
    }

    #[test]
    fn out_of_order_does_not_advance_expected() {
        let mut t = SequenceTracker::new();
        t.check(&delta(10));
        t.check(&delta(11)); // next_expected = 12
        t.check(&delta(5));  // out of order — should not change next_expected
        assert_eq!(t.next_expected(MessageType::Delta), Some(12));
    }

    // ── Duplicate Detection ───────────────────────────────────────────────────

    #[test]
    fn exact_previous_sequence_id_is_duplicate() {
        let mut t = SequenceTracker::new();
        t.check(&delta(1));
        t.check(&delta(2)); // next_expected = 3
        let result = t.check(&delta(2)); // resend of seq 2
        assert!(matches!(result, SequenceCheckResult::Duplicate { sequence_id: 2 }));
        assert!(result.should_discard());
        assert!(!result.should_process());
    }

    #[test]
    fn duplicate_does_not_change_expected() {
        let mut t = SequenceTracker::new();
        t.check(&delta(1));
        t.check(&delta(2));
        t.check(&delta(2)); // duplicate
        assert_eq!(t.next_expected(MessageType::Delta), Some(3));
        // Next in-order message still works
        assert_eq!(t.check(&delta(3)), SequenceCheckResult::InOrder);
    }

    // ── Reset After Snapshot ──────────────────────────────────────────────────

    #[test]
    fn reset_after_snapshot_re_anchors_delta_sequence() {
        let mut t = SequenceTracker::new();
        t.check(&delta(1));
        t.check(&delta(2));
        // Receive a SNAPSHOT — next DELTA will be seq 500
        t.reset_after_snapshot(500);
        assert_eq!(t.next_expected(MessageType::Delta), Some(500));
    }

    #[test]
    fn after_reset_correct_next_delta_is_in_order() {
        let mut t = SequenceTracker::new();
        t.check(&delta(1));
        t.reset_after_snapshot(50);
        assert_eq!(t.check(&delta(50)), SequenceCheckResult::InOrder);
    }

    #[test]
    fn after_reset_gap_still_detected() {
        let mut t = SequenceTracker::new();
        t.check(&delta(1));
        t.reset_after_snapshot(50);
        let result = t.check(&delta(55)); // gap: 50,51,52,53,54 missed
        assert!(result.is_gap());
        assert_eq!(result.missed_count(), 5);
    }

    #[test]
    fn reset_does_not_affect_feedback_sequence() {
        let mut t = SequenceTracker::new();
        t.check(&feedback(10));
        t.check(&feedback(11)); // next_expected = 12
        t.reset_after_snapshot(999); // only resets DELTA
        assert_eq!(t.next_expected(MessageType::Feedback), Some(12));
        assert_eq!(t.check(&feedback(12)), SequenceCheckResult::InOrder);
    }

    #[test]
    fn reset_after_snapshot_increments_reset_count() {
        let mut t = SequenceTracker::new();
        t.reset_after_snapshot(1);
        t.reset_after_snapshot(100);
        assert_eq!(t.metrics().reset_count, 2);
    }

    #[test]
    fn reset_all_clears_all_types() {
        let mut t = SequenceTracker::new();
        t.check(&delta(5));
        t.check(&feedback(10));
        t.check(&snapshot_msg(1));
        t.reset_all();
        assert_eq!(t.next_expected(MessageType::Delta), None);
        assert_eq!(t.next_expected(MessageType::Feedback), None);
        assert_eq!(t.next_expected(MessageType::Snapshot), None);
    }

    // ── Pre-anchored Constructor ──────────────────────────────────────────────

    #[test]
    fn with_initial_delta_sequence_anchors_correctly() {
        let mut t = SequenceTracker::with_initial_delta_sequence(42);
        assert_eq!(t.next_expected(MessageType::Delta), Some(42));
        // Seq 42 should be InOrder, not FirstMessage
        assert_eq!(t.check(&delta(42)), SequenceCheckResult::InOrder);
    }

    #[test]
    fn with_initial_sequence_detects_gap_on_first_message() {
        let mut t = SequenceTracker::with_initial_delta_sequence(10);
        let result = t.check(&delta(15)); // gap: 10–14 missed
        assert!(result.is_gap());
        assert_eq!(result.missed_count(), 5);
    }

    // ── Inspection API ────────────────────────────────────────────────────────

    #[test]
    fn has_delta_gap_false_initially() {
        let t = SequenceTracker::new();
        assert!(!t.has_delta_gap());
    }

    #[test]
    fn has_delta_gap_true_after_gap() {
        let mut t = SequenceTracker::new();
        t.check(&delta(0));
        t.check(&delta(5));
        assert!(t.has_delta_gap());
    }

    #[test]
    fn is_healthy_true_when_no_gaps() {
        let mut t = SequenceTracker::new();
        for seq in 0..10 {
            t.check(&delta(seq));
            t.check(&feedback(seq));
        }
        assert!(t.is_healthy());
    }

    #[test]
    fn is_healthy_false_after_any_gap() {
        let mut t = SequenceTracker::new();
        t.check(&delta(0));
        t.check(&delta(3)); // gap
        assert!(!t.is_healthy());
    }

    #[test]
    fn last_processed_returns_none_before_first_message() {
        let t = SequenceTracker::new();
        assert_eq!(t.last_processed(MessageType::Delta), None);
    }

    #[test]
    fn last_processed_returns_correct_value_after_messages() {
        let mut t = SequenceTracker::new();
        t.check(&delta(7));
        t.check(&delta(8));
        t.check(&delta(9));
        assert_eq!(t.last_processed(MessageType::Delta), Some(9));
    }

    // ── Metrics ───────────────────────────────────────────────────────────────

    #[test]
    fn metrics_count_in_order_messages() {
        let mut t = SequenceTracker::new();
        t.check(&delta(0));
        t.check(&delta(1));
        t.check(&delta(2));
        let m = t.metrics();
        let delta_metrics = &m.by_type[&MessageType::Delta.as_u8()];
        assert_eq!(delta_metrics.in_order_count, 3);
    }

    #[test]
    fn metrics_count_gaps_and_missed() {
        let mut t = SequenceTracker::new();
        t.check(&delta(0));
        t.check(&delta(3)); // 2 missed
        t.check(&delta(7)); // 3 missed
        let m = t.metrics();
        assert_eq!(m.total_delta_gaps, 2);
        assert_eq!(m.total_delta_missed, 5);
    }

    #[test]
    fn metrics_count_out_of_order_and_duplicates() {
        let mut t = SequenceTracker::new();
        t.check(&delta(0));
        t.check(&delta(1));
        t.check(&delta(1)); // duplicate
        t.check(&delta(0)); // out of order (more than 1 behind)
        let m = t.metrics();
        let dm = &m.by_type[&MessageType::Delta.as_u8()];
        assert_eq!(dm.duplicate_count, 1);
        assert_eq!(dm.out_of_order_count, 1);
    }

    // ── Health Summary ────────────────────────────────────────────────────────

    #[test]
    fn health_summary_not_empty() {
        let mut t = SequenceTracker::new();
        t.check(&delta(1));
        t.check(&feedback(1));
        let summary = t.health_summary();
        assert!(!summary.is_empty());
        assert!(summary.contains("DELTA"));
        assert!(summary.contains("FEEDBACK"));
        assert!(summary.contains("gaps:0"));
    }

    #[test]
    fn health_summary_shows_gap_when_detected() {
        let mut t = SequenceTracker::new();
        t.check(&delta(0));
        t.check(&delta(5)); // gap
        let summary = t.health_summary();
        assert!(summary.contains("GAP") || summary.contains("gaps:1"));
    }

    // ── Display ───────────────────────────────────────────────────────────────

    #[test]
    fn result_display_in_order() {
        assert_eq!(SequenceCheckResult::InOrder.to_string(), "IN_ORDER");
    }

    #[test]
    fn result_display_gap() {
        let result = SequenceCheckResult::Gap {
            expected: 5,
            received: 8,
            missed_count: 3,
        };
        let s = result.to_string();
        assert!(s.contains("GAP"));
        assert!(s.contains("expected=5"));
        assert!(s.contains("missed=3"));
    }

    #[test]
    fn result_display_out_of_order() {
        let result = SequenceCheckResult::OutOfOrder { expected: 10, received: 3 };
        assert!(result.to_string().contains("OUT_OF_ORDER"));
    }

    #[test]
    fn result_display_duplicate() {
        let result = SequenceCheckResult::Duplicate { sequence_id: 7 };
        assert!(result.to_string().contains("DUPLICATE"));
        assert!(result.to_string().contains("7"));
    }

    #[test]
    fn result_display_first_message() {
        let result = SequenceCheckResult::FirstMessage { sequence_id: 42 };
        assert!(result.to_string().contains("FIRST"));
        assert!(result.to_string().contains("42"));
    }

    // ── check_raw ─────────────────────────────────────────────────────────────

    #[test]
    fn check_raw_works_without_wire_message() {
        let mut t = SequenceTracker::new();
        let r1 = t.check_raw(MessageType::Delta, 0);
        assert!(matches!(r1, SequenceCheckResult::FirstMessage { .. }));
        let r2 = t.check_raw(MessageType::Delta, 1);
        assert_eq!(r2, SequenceCheckResult::InOrder);
        let r3 = t.check_raw(MessageType::Delta, 5); // gap
        assert!(r3.is_gap());
    }

    // ── All Six MessageTypes ──────────────────────────────────────────────────

    #[test]
    fn all_six_message_types_track_independently() {
        let mut t = SequenceTracker::new();
        let types = [
            MessageType::Snapshot,
            MessageType::Delta,
            MessageType::Input,
            MessageType::Event,
            MessageType::Control,
            MessageType::Feedback,
        ];
        // Each type gets FirstMessage on its first check
        for msg_type in types {
            let result = t.check_raw(msg_type, 100);
            assert!(
                matches!(result, SequenceCheckResult::FirstMessage { sequence_id: 100 }),
                "Expected FirstMessage for {:?}",
                msg_type
            );
        }
        // Each type's next_expected is now 101
        for msg_type in types {
            assert_eq!(t.next_expected(msg_type), Some(101), "type={:?}", msg_type);
        }
    }

    #[test]
    fn sequence_zero_handled_correctly() {
        let mut t = SequenceTracker::new();
        let r = t.check_raw(MessageType::Delta, 0);
        assert!(matches!(r, SequenceCheckResult::FirstMessage { sequence_id: 0 }));
        assert_eq!(t.next_expected(MessageType::Delta), Some(1));
    }
}