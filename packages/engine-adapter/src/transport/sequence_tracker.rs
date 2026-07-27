//! Per-message-type sequence tracking for engine transport streams.
//!
//! The tracker is deliberately transport-agnostic. TCP, shared memory, and
//! future unreliable transports can all feed `(MessageType, sequence_id)` pairs
//! into the same deterministic state machine and receive a processing decision.

use std::collections::{BTreeMap, BTreeSet, VecDeque};

use xace_core::wire::message_type::MessageType;
use xace_core::wire::wire_message::WireMessage;

const RECENT_SEQUENCE_WINDOW: usize = 512;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SequenceCheckResult {
    InOrder,
    Gap {
        expected: u64,
        received: u64,
        missed_count: u64,
    },
    OutOfOrder {
        expected: u64,
        received: u64,
    },
    Duplicate {
        sequence_id: u64,
    },
    FirstMessage {
        sequence_id: u64,
    },
}

impl SequenceCheckResult {
    pub fn should_process(&self) -> bool {
        matches!(self, Self::InOrder | Self::FirstMessage { .. })
    }

    pub fn is_gap(&self) -> bool {
        matches!(self, Self::Gap { .. })
    }

    pub fn should_discard(&self) -> bool {
        matches!(self, Self::OutOfOrder { .. } | Self::Duplicate { .. })
    }

    pub fn missed_count(&self) -> u64 {
        match self {
            Self::Gap { missed_count, .. } => *missed_count,
            _ => 0,
        }
    }
}

impl std::fmt::Display for SequenceCheckResult {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InOrder => f.write_str("IN_ORDER"),
            Self::Gap {
                expected,
                received,
                missed_count,
            } => write!(
                f,
                "GAP(expected={}, received={}, missed={})",
                expected, received, missed_count
            ),
            Self::OutOfOrder { expected, received } => {
                write!(
                    f,
                    "OUT_OF_ORDER(expected={}, received={})",
                    expected, received
                )
            }
            Self::Duplicate { sequence_id } => write!(f, "DUPLICATE(seq={})", sequence_id),
            Self::FirstMessage { sequence_id } => write!(f, "FIRST(seq={})", sequence_id),
        }
    }
}

#[derive(Debug, Clone)]
struct TypeSequenceState {
    next_expected: Option<u64>,
    last_processed: Option<u64>,
    recent_order: VecDeque<u64>,
    recent_set: BTreeSet<u64>,
    in_order_count: u64,
    gap_count: u64,
    out_of_order_count: u64,
    duplicate_count: u64,
    total_missed: u64,
}

impl TypeSequenceState {
    fn new() -> Self {
        Self {
            next_expected: None,
            last_processed: None,
            recent_order: VecDeque::with_capacity(RECENT_SEQUENCE_WINDOW),
            recent_set: BTreeSet::new(),
            in_order_count: 0,
            gap_count: 0,
            out_of_order_count: 0,
            duplicate_count: 0,
            total_missed: 0,
        }
    }

    fn check_and_advance(&mut self, sequence_id: u64) -> SequenceCheckResult {
        match self.next_expected {
            None => {
                self.in_order_count += 1;
                self.record_processed(sequence_id);
                self.next_expected = Some(sequence_id.saturating_add(1));
                SequenceCheckResult::FirstMessage { sequence_id }
            }
            Some(expected) if sequence_id == expected => {
                self.in_order_count += 1;
                self.record_processed(sequence_id);
                self.next_expected = Some(sequence_id.saturating_add(1));
                SequenceCheckResult::InOrder
            }
            Some(expected) if sequence_id > expected => {
                let missed_count = sequence_id - expected;
                self.gap_count += 1;
                self.total_missed = self.total_missed.saturating_add(missed_count);
                self.record_processed(sequence_id);
                self.next_expected = Some(sequence_id.saturating_add(1));
                SequenceCheckResult::Gap {
                    expected,
                    received: sequence_id,
                    missed_count,
                }
            }
            Some(expected) => {
                if self.recent_set.contains(&sequence_id) {
                    self.duplicate_count += 1;
                    SequenceCheckResult::Duplicate { sequence_id }
                } else {
                    self.out_of_order_count += 1;
                    SequenceCheckResult::OutOfOrder {
                        expected,
                        received: sequence_id,
                    }
                }
            }
        }
    }

    fn reset_to(&mut self, next_expected: u64) {
        self.next_expected = Some(next_expected);
        self.last_processed = next_expected.checked_sub(1);
        self.recent_order.clear();
        self.recent_set.clear();
        if let Some(last) = self.last_processed {
            self.record_processed(last);
        }
    }

    fn clear(&mut self) {
        *self = Self::new();
    }

    fn record_processed(&mut self, sequence_id: u64) {
        self.last_processed = Some(sequence_id);
        if self.recent_set.insert(sequence_id) {
            self.recent_order.push_back(sequence_id);
            while self.recent_order.len() > RECENT_SEQUENCE_WINDOW {
                if let Some(old) = self.recent_order.pop_front() {
                    self.recent_set.remove(&old);
                }
            }
        }
    }

    fn metrics(&self) -> TypeMetrics {
        TypeMetrics {
            next_expected: self.next_expected,
            last_processed: self.last_processed,
            in_order_count: self.in_order_count,
            gap_count: self.gap_count,
            out_of_order_count: self.out_of_order_count,
            duplicate_count: self.duplicate_count,
            total_missed: self.total_missed,
        }
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct TypeMetrics {
    pub next_expected: Option<u64>,
    pub last_processed: Option<u64>,
    pub in_order_count: u64,
    pub gap_count: u64,
    pub out_of_order_count: u64,
    pub duplicate_count: u64,
    pub total_missed: u64,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct SequenceTrackerMetrics {
    pub by_type: BTreeMap<u8, TypeMetrics>,
    pub total_delta_gaps: u64,
    pub total_delta_missed: u64,
    pub reset_count: u64,
}

pub struct SequenceTracker {
    states: [TypeSequenceState; 6],
    reset_count: u64,
}

impl SequenceTracker {
    pub fn new() -> Self {
        Self {
            states: std::array::from_fn(|_| TypeSequenceState::new()),
            reset_count: 0,
        }
    }

    pub fn with_initial_delta_sequence(initial_delta_sequence_id: u64) -> Self {
        let mut tracker = Self::new();
        tracker.reset_type(MessageType::Delta, initial_delta_sequence_id);
        tracker.reset_count = 0;
        tracker
    }

    pub fn check(&mut self, msg: &WireMessage) -> SequenceCheckResult {
        self.check_raw(msg.message_type, msg.sequence_id)
    }

    pub fn check_raw(&mut self, msg_type: MessageType, sequence_id: u64) -> SequenceCheckResult {
        self.state_mut(msg_type).check_and_advance(sequence_id)
    }

    pub fn reset_after_snapshot(&mut self, next_expected_delta_sequence: u64) {
        self.reset_type(MessageType::Delta, next_expected_delta_sequence);
        self.reset_count += 1;
    }

    pub fn reset_type(&mut self, msg_type: MessageType, next_expected: u64) {
        self.state_mut(msg_type).reset_to(next_expected);
    }

    pub fn reset_all(&mut self) {
        for state in &mut self.states {
            state.clear();
        }
        self.reset_count += 1;
    }

    pub fn next_expected(&self, msg_type: MessageType) -> Option<u64> {
        self.state(msg_type).next_expected
    }

    pub fn last_processed(&self, msg_type: MessageType) -> Option<u64> {
        self.state(msg_type).last_processed
    }

    pub fn has_delta_gap(&self) -> bool {
        self.delta_gap_count() > 0
    }

    pub fn delta_gap_count(&self) -> u64 {
        self.state(MessageType::Delta).gap_count
    }

    pub fn delta_missed_count(&self) -> u64 {
        self.state(MessageType::Delta).total_missed
    }

    pub fn is_healthy(&self) -> bool {
        self.states
            .iter()
            .all(|state| state.gap_count == 0 && state.out_of_order_count == 0)
    }

    pub fn metrics(&self) -> SequenceTrackerMetrics {
        let mut by_type = BTreeMap::new();
        for ty in MessageType::ALL {
            by_type.insert(ty.as_u8(), self.state(ty).metrics());
        }

        SequenceTrackerMetrics {
            total_delta_gaps: self.delta_gap_count(),
            total_delta_missed: self.delta_missed_count(),
            reset_count: self.reset_count,
            by_type,
        }
    }

    pub fn health_summary(&self) -> String {
        let mut parts = Vec::new();
        for ty in MessageType::ALL {
            let metrics = self.state(ty).metrics();
            if metrics.in_order_count > 0
                || metrics.gap_count > 0
                || metrics.duplicate_count > 0
                || metrics.out_of_order_count > 0
                || metrics.next_expected.is_some()
            {
                parts.push(format!(
                    "{} next:{:?} last:{:?} ok:{} gaps:{} missed:{} dup:{} old:{}",
                    ty,
                    metrics.next_expected,
                    metrics.last_processed,
                    metrics.in_order_count,
                    metrics.gap_count,
                    metrics.total_missed,
                    metrics.duplicate_count,
                    metrics.out_of_order_count
                ));
            }
        }
        if parts.is_empty() {
            "SequenceTracker idle".to_string()
        } else if self.is_healthy() {
            format!("SequenceTracker healthy [{}]", parts.join("; "))
        } else {
            format!("SequenceTracker GAP [{}]", parts.join("; "))
        }
    }

    fn state(&self, msg_type: MessageType) -> &TypeSequenceState {
        &self.states[msg_type.as_u8() as usize]
    }

    fn state_mut(&mut self, msg_type: MessageType) -> &mut TypeSequenceState {
        &mut self.states[msg_type.as_u8() as usize]
    }
}

impl Default for SequenceTracker {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn delta(sequence_id: u64) -> WireMessage {
        WireMessage::delta("default", "0.1.0", 1, 10, sequence_id, "{}")
    }

    #[test]
    fn first_then_in_order_advances_expected() {
        let mut tracker = SequenceTracker::new();
        assert_eq!(
            tracker.check(&delta(0)),
            SequenceCheckResult::FirstMessage { sequence_id: 0 }
        );
        assert_eq!(tracker.check(&delta(1)), SequenceCheckResult::InOrder);
        assert_eq!(tracker.next_expected(MessageType::Delta), Some(2));
        assert_eq!(tracker.last_processed(MessageType::Delta), Some(1));
    }

    #[test]
    fn gap_records_missed_and_reanchors_stream() {
        let mut tracker = SequenceTracker::new();
        tracker.check(&delta(0));
        let result = tracker.check(&delta(5));

        assert_eq!(
            result,
            SequenceCheckResult::Gap {
                expected: 1,
                received: 5,
                missed_count: 4
            }
        );
        assert!(!result.should_process());
        assert_eq!(tracker.next_expected(MessageType::Delta), Some(6));
        assert_eq!(tracker.delta_gap_count(), 1);
        assert_eq!(tracker.delta_missed_count(), 4);
    }

    #[test]
    fn duplicate_window_catches_more_than_previous_message() {
        let mut tracker = SequenceTracker::new();
        for seq in 10..20 {
            tracker.check(&delta(seq));
        }
        assert_eq!(
            tracker.check(&delta(12)),
            SequenceCheckResult::Duplicate { sequence_id: 12 }
        );
    }

    #[test]
    fn old_unseen_message_is_out_of_order() {
        let mut tracker = SequenceTracker::new();
        tracker.check(&delta(10));
        tracker.check(&delta(11));
        assert_eq!(
            tracker.check(&delta(7)),
            SequenceCheckResult::OutOfOrder {
                expected: 12,
                received: 7
            }
        );
    }

    #[test]
    fn message_types_track_independently() {
        let mut tracker = SequenceTracker::new();
        assert!(tracker.check_raw(MessageType::Delta, 0).should_process());
        assert!(tracker
            .check_raw(MessageType::Feedback, 50)
            .should_process());
        assert_eq!(
            tracker.check_raw(MessageType::Delta, 1),
            SequenceCheckResult::InOrder
        );
        assert_eq!(
            tracker.check_raw(MessageType::Feedback, 51),
            SequenceCheckResult::InOrder
        );
    }

    #[test]
    fn reset_after_snapshot_only_reanchors_delta() {
        let mut tracker = SequenceTracker::new();
        tracker.check_raw(MessageType::Feedback, 10);
        tracker.check_raw(MessageType::Feedback, 11);
        tracker.reset_after_snapshot(100);

        assert_eq!(tracker.next_expected(MessageType::Delta), Some(100));
        assert_eq!(tracker.next_expected(MessageType::Feedback), Some(12));
        assert_eq!(tracker.metrics().reset_count, 1);
    }

    #[test]
    fn preanchored_delta_detects_first_gap() {
        let mut tracker = SequenceTracker::with_initial_delta_sequence(10);
        let result = tracker.check(&delta(12));
        assert!(result.is_gap());
        assert_eq!(result.missed_count(), 2);
    }

    #[test]
    fn metrics_include_all_protocol_types() {
        let tracker = SequenceTracker::new();
        let metrics = tracker.metrics();
        for ty in MessageType::ALL {
            assert!(metrics.by_type.contains_key(&ty.as_u8()));
        }
    }

    #[test]
    fn health_summary_reports_gap_status() {
        let mut tracker = SequenceTracker::new();
        tracker.check(&delta(0));
        tracker.check(&delta(3));
        let summary = tracker.health_summary();
        assert!(summary.contains("GAP"));
        assert!(summary.contains("DELTA"));
    }
}
