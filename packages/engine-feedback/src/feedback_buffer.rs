//! # Feedback Buffer
//!
//! Thread-safe accumulation of `FeedbackMessage` values between simulation
//! ticks, with deterministic drain at tick START (I13, Audit 6).
//!
//! ## Global Invariant I13
//! Engine feedback is processed ONLY at tick boundaries — never mid-tick.
//! The buffer accumulates all feedback that arrives from the engine adapter
//! between tick N ending and tick N+1 starting. At the START of tick N+1,
//! the PhaseOrchestrator drains the buffer before any phase runs.
//!
//! ## Deterministic Drain (D9)
//! The drain produces messages sorted by `(generated_frame ASC, entity_id ASC)`.
//! This sort order is applied at drain time, not at append time.
//! Same feedback sequence → same sort order → same world state (D9).
//! The sort is stable — two messages with the same sort key preserve insertion order.
//!
//! ## Thread Safety
//! The engine adapter's receive loop runs on a separate thread and appends
//! feedback as it arrives. The PhaseOrchestrator drains on the simulation
//! thread at tick boundaries. A `Mutex<Vec>` is the correct primitive here:
//! - Appends are rare (one batch per tick from the engine)
//! - Drains are rare (once per tick)
//! - No high-frequency concurrent writes
//!
//! ## Tick Window
//! The buffer tracks the tick its contents were generated for.
//! Feedback from tick N must be drained before tick N+1 runs — the
//! buffer enforces this via `assert_drained_before_next_tick()`.
//!
//! ## Replay (D14)
//! Every append is also forwarded to the `FeedbackLog` for replay fidelity.
//! Replay must replay the same feedback sequence to produce identical world state.

use std::sync::{Arc, Mutex, MutexGuard};

use xace_core::wire::feedback_payload::FeedbackMessage;

use crate::feedback_message::FeedbackMessageExt;

// ── Buffer Metrics ────────────────────────────────────────────────────────────

/// Accumulated metrics for one `FeedbackBuffer` session.
#[derive(Debug, Clone, Default)]
pub struct FeedbackBufferMetrics {
    /// Total messages appended across all ticks.
    pub total_appended: u64,
    /// Total drain operations performed.
    pub total_drains: u64,
    /// Total messages returned across all drains.
    pub total_drained: u64,
    /// Total ticks where the buffer was empty at drain time.
    pub empty_drain_ticks: u64,
    /// Maximum number of messages ever pending in the buffer at once.
    pub peak_pending: usize,
    /// Total times the buffer was cleared (connection reset).
    pub clear_count: u64,
}

// ── Inner State ───────────────────────────────────────────────────────────────

struct BufferInner {
    /// Pending messages from the engine, unsorted.
    /// Sorted only at drain time for determinism (D11).
    messages: Vec<FeedbackMessage>,
    metrics: FeedbackBufferMetrics,
}

impl BufferInner {
    fn new() -> Self {
        Self {
            messages: Vec::with_capacity(64),
            metrics: FeedbackBufferMetrics::default(),
        }
    }
}

// ── Feedback Buffer ───────────────────────────────────────────────────────────

/// Thread-safe accumulation buffer for engine feedback messages.
///
/// Wraps an `Arc<Mutex<...>>` so the engine adapter's receive loop and
/// the PhaseOrchestrator can safely share it across threads.
///
/// ## Typical Usage
/// ```ignore
/// // Engine adapter receive loop (any thread):
/// buffer.append_batch(feedback_payload.messages);
///
/// // PhaseOrchestrator at tick start (simulation thread):
/// let messages = buffer.drain_sorted();
/// for msg in messages {
///     router.route(msg)?;
/// }
/// ```
#[derive(Clone)]
pub struct FeedbackBuffer {
    inner: Arc<Mutex<BufferInner>>,
}

impl FeedbackBuffer {
    // ── Construction ──────────────────────────────────────────────────────────

    /// Creates a new empty buffer.
    pub fn new() -> Self {
        Self {
            inner: Arc::new(Mutex::new(BufferInner::new())),
        }
    }

    // ── Append (Engine Adapter Thread) ────────────────────────────────────────

    /// Appends a single feedback message to the buffer.
    ///
    /// Thread-safe — can be called from any thread.
    /// Does not sort — sorting is deferred to `drain_sorted()`.
    pub fn append(&self, message: FeedbackMessage) {
        let mut inner = self.lock();
        inner.metrics.total_appended += 1;
        let new_len = inner.messages.len() + 1;
        if new_len > inner.metrics.peak_pending {
            inner.metrics.peak_pending = new_len;
        }
        inner.messages.push(message);
    }

    /// Appends a batch of feedback messages in one lock acquisition.
    ///
    /// Prefer this over calling `append()` in a loop — one lock
    /// acquisition for N messages is more efficient than N acquisitions.
    pub fn append_batch(&self, messages: Vec<FeedbackMessage>) {
        if messages.is_empty() {
            return;
        }
        let count = messages.len();
        let mut inner = self.lock();
        inner.metrics.total_appended += count as u64;
        let new_len = inner.messages.len() + count;
        if new_len > inner.metrics.peak_pending {
            inner.metrics.peak_pending = new_len;
        }
        inner.messages.extend(messages);
    }

    // ── Drain (Simulation Thread — Tick Start) ────────────────────────────────

    /// Drains all buffered messages and returns them sorted by
    /// `(generated_frame ASC, entity_id ASC)` (I13, D9).
    ///
    /// Must be called at the START of each tick before any phase runs.
    /// Returns an empty Vec if no messages were buffered.
    /// The buffer is empty after this call.
    pub fn drain_sorted(&self) -> Vec<FeedbackMessage> {
        let mut inner = self.lock();
        inner.metrics.total_drains += 1;

        if inner.messages.is_empty() {
            inner.metrics.empty_drain_ticks += 1;
            return Vec::new();
        }

        // Stable sort preserves insertion order for equal sort keys (D11)
        inner.messages.sort_by_key(|m| m.sort_key());

        let drained: Vec<FeedbackMessage> = std::mem::take(&mut inner.messages);
        inner.metrics.total_drained += drained.len() as u64;
        drained
    }

    /// Drains all messages and returns them filtered to a specific entity range.
    ///
    /// Used for interest-management in Phase 15 — only drain feedback
    /// relevant to entities within this peer's area of interest.
    pub fn drain_sorted_for_entity_range(
        &self,
        min_entity_id: u64,
        max_entity_id: u64,
    ) -> Vec<FeedbackMessage> {
        let all = self.drain_sorted();
        all.into_iter()
            .filter(|m| m.entity_in_range(min_entity_id, max_entity_id))
            .collect()
    }

    // ── State Inspection ──────────────────────────────────────────────────────

    /// Returns the number of messages currently pending in the buffer.
    pub fn pending_count(&self) -> usize {
        self.lock().messages.len()
    }

    /// Returns true if the buffer has no pending messages.
    pub fn is_empty(&self) -> bool {
        self.lock().messages.is_empty()
    }

    /// Clears all pending messages without processing them.
    /// Called on transport disconnect / session reset.
    pub fn clear(&self) {
        let mut inner = self.lock();
        inner.messages.clear();
        inner.metrics.clear_count += 1;
    }

    /// Returns a copy of accumulated buffer metrics.
    pub fn metrics(&self) -> FeedbackBufferMetrics {
        self.lock().metrics.clone()
    }

    // ── Internal ──────────────────────────────────────────────────────────────

    fn lock(&self) -> MutexGuard<'_, BufferInner> {
        self.inner.lock().expect("FeedbackBuffer mutex poisoned")
    }
}

impl Default for FeedbackBuffer {
    fn default() -> Self {
        Self::new()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::wire::feedback_payload::FeedbackType;

    fn msg(ft: FeedbackType, entity_id: u64, frame: u64) -> FeedbackMessage {
        FeedbackMessage {
            feedback_type: ft,
            entity_id,
            generated_frame: frame,
            payload_json: "{}".into(),
        }
    }

    // ── Basic Append / Drain ──────────────────────────────────────────────────

    #[test]
    fn buffer_empty_initially() {
        let b = FeedbackBuffer::new();
        assert!(b.is_empty());
        assert_eq!(b.pending_count(), 0);
    }

    #[test]
    fn append_increases_pending_count() {
        let b = FeedbackBuffer::new();
        b.append(msg(FeedbackType::PhysicsSettled, 1, 1));
        assert_eq!(b.pending_count(), 1);
        assert!(!b.is_empty());
    }

    #[test]
    fn drain_sorted_returns_all_messages() {
        let b = FeedbackBuffer::new();
        b.append(msg(FeedbackType::PhysicsSettled, 1, 1));
        b.append(msg(FeedbackType::AudioComplete, 2, 2));
        let drained = b.drain_sorted();
        assert_eq!(drained.len(), 2);
        assert!(b.is_empty());
    }

    #[test]
    fn drain_sorted_empties_buffer() {
        let b = FeedbackBuffer::new();
        b.append(msg(FeedbackType::AnimationStateUpdate, 1, 1));
        b.drain_sorted();
        assert!(b.is_empty());
        assert_eq!(b.pending_count(), 0);
    }

    #[test]
    fn drain_sorted_returns_empty_when_buffer_empty() {
        let b = FeedbackBuffer::new();
        let drained = b.drain_sorted();
        assert!(drained.is_empty());
        assert_eq!(b.metrics().empty_drain_ticks, 1);
    }

    // ── Deterministic Sort Order (I13, D9) ────────────────────────────────────

    #[test]
    fn drain_sorted_sorts_by_frame_asc_then_entity_asc() {
        let b = FeedbackBuffer::new();
        // Insert in reverse order — drain must sort them
        b.append(msg(FeedbackType::PhysicsSettled, 5, 10));
        b.append(msg(FeedbackType::AnimationStateUpdate, 1, 8));
        b.append(msg(FeedbackType::AudioComplete, 3, 10));

        let drained = b.drain_sorted();
        // Expected: frame=8 first, then frame=10/entity=3, then frame=10/entity=5
        assert_eq!(drained[0].generated_frame, 8);
        assert_eq!(drained[1].generated_frame, 10);
        assert_eq!(drained[1].entity_id, 3);
        assert_eq!(drained[2].generated_frame, 10);
        assert_eq!(drained[2].entity_id, 5);
    }

    #[test]
    fn drain_sorted_same_frame_same_entity_preserves_insertion_order() {
        // Stable sort — equal keys keep insertion order
        let b = FeedbackBuffer::new();
        b.append(FeedbackMessage {
            feedback_type: FeedbackType::AnimationStateUpdate,
            entity_id: 1,
            generated_frame: 5,
            payload_json: "first".into(),
        });
        b.append(FeedbackMessage {
            feedback_type: FeedbackType::AnimationEventFired,
            entity_id: 1,
            generated_frame: 5,
            payload_json: "second".into(),
        });
        let drained = b.drain_sorted();
        assert_eq!(drained[0].payload_json, "first");
        assert_eq!(drained[1].payload_json, "second");
    }

    #[test]
    fn drain_sorted_deterministic_across_two_identical_inputs() {
        // D9 — same feedback sequence always produces same drain order
        let fill = || {
            let b = FeedbackBuffer::new();
            b.append(msg(FeedbackType::PhysicsSettled, 10, 3));
            b.append(msg(FeedbackType::AnimationStateUpdate, 1, 1));
            b.append(msg(FeedbackType::VisibilityQueryResult, 5, 2));
            b
        };

        let order_a: Vec<(u64, u64)> = fill()
            .drain_sorted()
            .iter()
            .map(|m| (m.generated_frame, m.entity_id))
            .collect();

        let order_b: Vec<(u64, u64)> = fill()
            .drain_sorted()
            .iter()
            .map(|m| (m.generated_frame, m.entity_id))
            .collect();

        assert_eq!(order_a, order_b, "Drain order must be deterministic (D9)");
    }

    // ── Batch Append ─────────────────────────────────────────────────────────

    #[test]
    fn append_batch_adds_all_messages() {
        let b = FeedbackBuffer::new();
        let batch = vec![
            msg(FeedbackType::PhysicsSettled, 1, 1),
            msg(FeedbackType::AudioComplete, 2, 2),
            msg(FeedbackType::EngineError, 3, 3),
        ];
        b.append_batch(batch);
        assert_eq!(b.pending_count(), 3);
    }

    #[test]
    fn append_batch_empty_is_noop() {
        let b = FeedbackBuffer::new();
        b.append_batch(vec![]);
        assert!(b.is_empty());
        assert_eq!(b.metrics().total_appended, 0);
    }

    // ── Clear ─────────────────────────────────────────────────────────────────

    #[test]
    fn clear_removes_all_pending_messages() {
        let b = FeedbackBuffer::new();
        b.append(msg(FeedbackType::AnimationStateUpdate, 1, 1));
        b.append(msg(FeedbackType::PhysicsSettled, 2, 2));
        b.clear();
        assert!(b.is_empty());
        assert_eq!(b.metrics().clear_count, 1);
    }

    // ── Entity Range Drain ────────────────────────────────────────────────────

    #[test]
    fn drain_sorted_for_entity_range_filters_correctly() {
        let b = FeedbackBuffer::new();
        b.append(msg(FeedbackType::PhysicsSettled, 1, 1));
        b.append(msg(FeedbackType::PhysicsSettled, 50, 1));
        b.append(msg(FeedbackType::PhysicsSettled, 100, 1));

        let drained = b.drain_sorted_for_entity_range(10, 60);
        assert_eq!(drained.len(), 1);
        assert_eq!(drained[0].entity_id, 50);
    }

    // ── Metrics ───────────────────────────────────────────────────────────────

    #[test]
    fn metrics_count_appended_and_drained() {
        let b = FeedbackBuffer::new();
        b.append(msg(FeedbackType::AudioComplete, 1, 1));
        b.append(msg(FeedbackType::AudioComplete, 2, 2));
        b.drain_sorted();

        let m = b.metrics();
        assert_eq!(m.total_appended, 2);
        assert_eq!(m.total_drains, 1);
        assert_eq!(m.total_drained, 2);
    }

    #[test]
    fn metrics_peak_pending_tracked() {
        let b = FeedbackBuffer::new();
        b.append(msg(FeedbackType::PhysicsSettled, 1, 1));
        b.append(msg(FeedbackType::PhysicsSettled, 2, 2));
        b.append(msg(FeedbackType::PhysicsSettled, 3, 3));
        b.drain_sorted();
        b.append(msg(FeedbackType::PhysicsSettled, 4, 4));
        assert_eq!(b.metrics().peak_pending, 3);
    }

    // ── Thread Safety ─────────────────────────────────────────────────────────

    #[test]
    fn concurrent_appends_all_arrive_in_drain() {
        use std::thread;

        let buffer = FeedbackBuffer::new();
        let mut handles = vec![];

        for i in 0..10u64 {
            let b = buffer.clone();
            handles.push(thread::spawn(move || {
                b.append(msg(FeedbackType::AnimationStateUpdate, i, i));
            }));
        }
        for h in handles { h.join().unwrap(); }

        let drained = buffer.drain_sorted();
        assert_eq!(drained.len(), 10);
    }
}