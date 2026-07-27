//! # Resync Detector
//!
//! Detects conditions that require sending a full SNAPSHOT to the engine
//! adapter and triggers the recovery path.
//!
//! ## Detection Triggers
//! The `ResyncDetector` monitors three independent signals:
//!
//! 1. **Sequence gap** — the engine adapter's DELTA sequence tracker reports
//!    a gap (one or more DELTA messages were dropped). The engine is now out
//!    of sync with the authoritative world state. A SNAPSHOT is required.
//!
//! 2. **Schema version drift** — the engine adapter reports a schema or
//!    ExecutionPlan version that differs from the one XACE is running.
//!    The engine may be replaying an old session. A SNAPSHOT with the
//!    current versions will re-anchor it.
//!
//! 3. **Tick drift** — the engine adapter's last-acknowledged tick is more
//!    than `max_tick_drift` ticks behind the current simulation tick.
//!    This indicates the transport is severely congested or the adapter
//!    has stalled. A SNAPSHOT breaks the deadlock.
//!
//! 4. **Explicit request** — the engine adapter sent a CONTROL message
//!    requesting a SNAPSHOT (e.g. after a scene reload or manual reconnect).
//!
//! ## Cooldown
//! A SNAPSHOT is expensive — it includes the full world state.
//! The detector enforces a `cooldown_ticks` minimum between consecutive
//! SNAPSHOT sends. If a resync is needed but the cooldown has not elapsed,
//! the detector records the pending request and fires on the next eligible tick.
//!
//! ## Integration
//! The `DeltaSyncEngine` holds a `ResyncDetector` and calls
//! `check_after_delta()` after each DELTA is sent. When `needs_resync()`
//! returns true, the engine skips the DELTA and calls `SnapshotRecovery`
//! instead. After the SNAPSHOT is sent, `mark_snapshot_sent()` is called
//! to reset the detector state and start the cooldown.

use xace_core::wire::snapshot_payload::SnapshotReason;

// ── Resync Trigger ────────────────────────────────────────────────────────────

/// The specific condition that triggered a resync request.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ResyncTrigger {
    /// A gap was detected in the DELTA sequence.
    SequenceGap {
        expected_sequence: u64,
        received_sequence: u64,
    },
    /// Schema or ExecutionPlan version mismatch detected.
    SchemaVersionDrift { expected: String, received: String },
    /// Engine adapter tick is too far behind the simulation.
    TickDrift {
        current_tick: u64,
        last_ack_tick: u64,
        drift: u64,
    },
    /// Engine adapter explicitly requested a SNAPSHOT.
    ExplicitRequest,
    /// Initial connection — engine has no world state yet.
    InitialConnection,
}

impl ResyncTrigger {
    /// Returns the `SnapshotReason` to embed in the payload for this trigger.
    pub fn snapshot_reason(&self) -> SnapshotReason {
        match self {
            ResyncTrigger::InitialConnection => SnapshotReason::InitialConnection,
            ResyncTrigger::ExplicitRequest => SnapshotReason::ExplicitRequest,
            ResyncTrigger::SequenceGap { .. } => SnapshotReason::DesyncRecovery,
            ResyncTrigger::SchemaVersionDrift { .. } => SnapshotReason::DesyncRecovery,
            ResyncTrigger::TickDrift { .. } => SnapshotReason::DesyncRecovery,
        }
    }
}

impl std::fmt::Display for ResyncTrigger {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ResyncTrigger::SequenceGap {
                expected_sequence,
                received_sequence,
            } => write!(
                f,
                "SequenceGap(expected={}, received={})",
                expected_sequence, received_sequence
            ),
            ResyncTrigger::SchemaVersionDrift { expected, received } => write!(
                f,
                "SchemaVersionDrift(expected='{}', received='{}')",
                expected, received
            ),
            ResyncTrigger::TickDrift {
                current_tick,
                last_ack_tick,
                drift,
            } => write!(
                f,
                "TickDrift(current={}, last_ack={}, drift={})",
                current_tick, last_ack_tick, drift
            ),
            ResyncTrigger::ExplicitRequest => write!(f, "ExplicitRequest"),
            ResyncTrigger::InitialConnection => write!(f, "InitialConnection"),
        }
    }
}

// ── Resync Configuration ──────────────────────────────────────────────────────

/// Configuration for the `ResyncDetector`.
#[derive(Debug, Clone)]
pub struct ResyncConfig {
    /// Minimum ticks between consecutive SNAPSHOT sends.
    /// Prevents SNAPSHOT flooding on a severely congested transport.
    /// Default: 120 ticks (2 seconds at 60Hz).
    pub cooldown_ticks: u64,

    /// Maximum allowed tick drift before forcing a SNAPSHOT.
    /// Default: 300 ticks (5 seconds at 60Hz).
    pub max_tick_drift: u64,

    /// Whether tick drift detection is enabled.
    /// Disable during replay and testing to avoid false positives.
    pub tick_drift_detection: bool,
}

impl Default for ResyncConfig {
    fn default() -> Self {
        Self {
            cooldown_ticks: 120,
            max_tick_drift: 300,
            tick_drift_detection: true,
        }
    }
}

// ── Detector Metrics ──────────────────────────────────────────────────────────

/// Accumulated metrics for one `ResyncDetector` session.
#[derive(Debug, Clone, Default)]
pub struct ResyncMetrics {
    /// Total resync requests raised.
    pub resync_requests: u64,
    /// Total snapshots sent (resync requests that were not suppressed by cooldown).
    pub snapshots_sent: u64,
    /// Resync requests suppressed by cooldown.
    pub cooldown_suppressions: u64,
    /// Resync triggers broken down by type.
    pub sequence_gap_triggers: u64,
    pub schema_drift_triggers: u64,
    pub tick_drift_triggers: u64,
    pub explicit_request_triggers: u64,
    pub initial_connection_triggers: u64,
}

// ── Resync Detector ───────────────────────────────────────────────────────────

/// Monitors delta sync health and triggers SNAPSHOT recovery when needed.
///
/// ## Lifecycle
/// ```text
/// // On engine adapter connect:
/// let mut detector = ResyncDetector::new(ResyncConfig::default());
/// detector.request_resync(ResyncTrigger::InitialConnection);
///
/// // After each DELTA:
/// if let Some(trigger) = detector.check_and_consume(current_tick) {
///     // send SNAPSHOT instead of DELTA
///     let payload = recovery.build_payload(&world_snapshot, trigger.snapshot_reason())?;
///     detector.mark_snapshot_sent(current_tick);
/// }
///
/// // When engine reports a sequence gap:
/// detector.request_resync(ResyncTrigger::SequenceGap { expected, received });
/// ```
pub struct ResyncDetector {
    config: ResyncConfig,

    /// Pending resync trigger, if any.
    pending: Option<ResyncTrigger>,

    /// The simulation tick on which the last SNAPSHOT was sent.
    /// None = no SNAPSHOT has been sent yet this session.
    last_snapshot_tick: Option<u64>,

    /// The last tick acknowledged by the engine adapter.
    last_ack_tick: u64,

    /// Accumulated metrics.
    metrics: ResyncMetrics,
}

impl ResyncDetector {
    // ── Construction ──────────────────────────────────────────────────────────

    /// Creates a new detector with the given configuration.
    pub fn new(config: ResyncConfig) -> Self {
        Self {
            config,
            pending: None,
            last_snapshot_tick: None,
            last_ack_tick: 0,
            metrics: ResyncMetrics::default(),
        }
    }

    /// Creates a detector with default configuration.
    pub fn with_defaults() -> Self {
        Self::new(ResyncConfig::default())
    }

    // ── Primary API ───────────────────────────────────────────────────────────

    /// Signals that a resync is needed for the given reason.
    ///
    /// The trigger is recorded as pending. It will be returned by the next
    /// `check_and_consume()` call that is not suppressed by cooldown.
    pub fn request_resync(&mut self, trigger: ResyncTrigger) {
        self.metrics.resync_requests += 1;
        match &trigger {
            ResyncTrigger::SequenceGap { .. } => self.metrics.sequence_gap_triggers += 1,
            ResyncTrigger::SchemaVersionDrift { .. } => self.metrics.schema_drift_triggers += 1,
            ResyncTrigger::TickDrift { .. } => self.metrics.tick_drift_triggers += 1,
            ResyncTrigger::ExplicitRequest => self.metrics.explicit_request_triggers += 1,
            ResyncTrigger::InitialConnection => self.metrics.initial_connection_triggers += 1,
        }
        // New trigger always overwrites pending — the most recent trigger wins
        self.pending = Some(trigger);
    }

    /// Checks if a tick drift condition exists and raises a trigger if so.
    ///
    /// Call this every tick after updating `last_ack_tick`.
    /// Only raises a trigger if tick drift detection is enabled in config.
    pub fn check_tick_drift(&mut self, current_tick: u64) {
        if !self.config.tick_drift_detection {
            return;
        }
        if current_tick > self.last_ack_tick {
            let drift = current_tick - self.last_ack_tick;
            if drift > self.config.max_tick_drift {
                self.request_resync(ResyncTrigger::TickDrift {
                    current_tick,
                    last_ack_tick: self.last_ack_tick,
                    drift,
                });
            }
        }
    }

    /// Checks for a pending resync and returns the trigger if the cooldown
    /// has elapsed. Consumes the pending trigger on return.
    ///
    /// Returns `Some(trigger)` — the caller must send a SNAPSHOT.
    /// Returns `None` — no resync needed, or cooldown still active.
    ///
    /// After sending the SNAPSHOT, call `mark_snapshot_sent(current_tick)`.
    pub fn check_and_consume(&mut self, current_tick: u64) -> Option<ResyncTrigger> {
        let trigger = self.pending.take()?;

        // Check cooldown
        if let Some(last_tick) = self.last_snapshot_tick {
            let ticks_since = current_tick.saturating_sub(last_tick);
            if ticks_since < self.config.cooldown_ticks {
                // Still in cooldown — re-queue the trigger for next eligible tick
                self.pending = Some(trigger);
                self.metrics.cooldown_suppressions += 1;
                return None;
            }
        }

        self.metrics.snapshots_sent += 1;
        Some(trigger)
    }

    /// Records that a SNAPSHOT was successfully sent at the given tick.
    ///
    /// Resets the pending trigger and starts the cooldown window.
    /// Call this immediately after the SNAPSHOT WireMessage is sent.
    pub fn mark_snapshot_sent(&mut self, tick: u64) {
        self.last_snapshot_tick = Some(tick);
        self.pending = None; // snapshot clears any pending trigger
    }

    /// Updates the last-acknowledged tick from the engine adapter.
    ///
    /// In Phase 7 this is advanced by the tick embedded in inbound FEEDBACK
    /// or INPUT messages. In Phase 15 it is updated by the multiplayer tick
    /// barrier. Call this whenever a FEEDBACK or INPUT message arrives.
    pub fn update_last_ack_tick(&mut self, tick: u64) {
        if tick > self.last_ack_tick {
            self.last_ack_tick = tick;
        }
    }

    /// Reports a schema version mismatch received from the engine adapter.
    ///
    /// This is a hard signal — always triggers a resync regardless of cooldown.
    /// Call this when an inbound WireMessage carries a different schema_version
    /// than the current XACE session.
    pub fn report_schema_mismatch(
        &mut self,
        expected: impl Into<String>,
        received: impl Into<String>,
    ) {
        self.request_resync(ResyncTrigger::SchemaVersionDrift {
            expected: expected.into(),
            received: received.into(),
        });
    }

    /// Reports a DELTA sequence gap detected in the engine adapter's tracker.
    ///
    /// Call this when the engine sends a CONTROL message reporting that it
    /// detected a gap in the DELTA stream, or when XACE-side sequence checking
    /// detects the engine is falling behind.
    pub fn report_sequence_gap(&mut self, expected: u64, received: u64) {
        self.request_resync(ResyncTrigger::SequenceGap {
            expected_sequence: expected,
            received_sequence: received,
        });
    }

    /// Records an explicit SNAPSHOT request from the engine adapter.
    pub fn report_explicit_request(&mut self) {
        self.request_resync(ResyncTrigger::ExplicitRequest);
    }

    // ── Inspection ────────────────────────────────────────────────────────────

    /// Returns true if a resync is currently pending.
    pub fn needs_resync(&self) -> bool {
        self.pending.is_some()
    }

    /// Returns a reference to the pending trigger without consuming it.
    pub fn pending_trigger(&self) -> Option<&ResyncTrigger> {
        self.pending.as_ref()
    }

    /// Returns the tick of the last SNAPSHOT sent, if any.
    pub fn last_snapshot_tick(&self) -> Option<u64> {
        self.last_snapshot_tick
    }

    /// Returns the last-acknowledged tick from the engine adapter.
    pub fn last_ack_tick(&self) -> u64 {
        self.last_ack_tick
    }

    /// Returns true if the detector is currently in the cooldown window.
    pub fn is_in_cooldown(&self, current_tick: u64) -> bool {
        match self.last_snapshot_tick {
            Some(last) => current_tick.saturating_sub(last) < self.config.cooldown_ticks,
            None => false,
        }
    }

    /// Returns accumulated resync metrics.
    pub fn metrics(&self) -> &ResyncMetrics {
        &self.metrics
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn detector() -> ResyncDetector {
        ResyncDetector::new(ResyncConfig {
            cooldown_ticks: 10,
            max_tick_drift: 30,
            tick_drift_detection: true,
        })
    }

    // ── Request and Consume ───────────────────────────────────────────────────

    #[test]
    fn no_pending_trigger_initially() {
        let d = detector();
        assert!(!d.needs_resync());
        assert!(d.pending_trigger().is_none());
    }

    #[test]
    fn request_resync_sets_pending() {
        let mut d = detector();
        d.request_resync(ResyncTrigger::InitialConnection);
        assert!(d.needs_resync());
    }

    #[test]
    fn check_and_consume_returns_trigger_when_no_cooldown() {
        let mut d = detector();
        d.request_resync(ResyncTrigger::InitialConnection);
        let trigger = d.check_and_consume(0);
        assert!(trigger.is_some());
        assert!(!d.needs_resync());
    }

    #[test]
    fn check_and_consume_returns_none_when_no_pending() {
        let mut d = detector();
        assert!(d.check_and_consume(5).is_none());
    }

    #[test]
    fn multiple_triggers_last_one_wins() {
        let mut d = detector();
        d.request_resync(ResyncTrigger::InitialConnection);
        d.request_resync(ResyncTrigger::ExplicitRequest);
        let trigger = d.check_and_consume(0).unwrap();
        assert_eq!(trigger, ResyncTrigger::ExplicitRequest);
    }

    // ── Cooldown ──────────────────────────────────────────────────────────────

    #[test]
    fn cooldown_suppresses_trigger_within_window() {
        let mut d = detector();
        d.request_resync(ResyncTrigger::InitialConnection);
        d.check_and_consume(0).unwrap(); // first snapshot at tick 0
        d.mark_snapshot_sent(0);

        // Queue another resync immediately
        d.request_resync(ResyncTrigger::ExplicitRequest);

        // Tick 5 is within cooldown_ticks=10
        let result = d.check_and_consume(5);
        assert!(result.is_none(), "Cooldown must suppress trigger at tick 5");
        assert_eq!(d.metrics().cooldown_suppressions, 1);
        // Trigger is re-queued
        assert!(d.needs_resync());
    }

    #[test]
    fn trigger_fires_after_cooldown_expires() {
        let mut d = detector();
        d.request_resync(ResyncTrigger::InitialConnection);
        d.check_and_consume(0).unwrap();
        d.mark_snapshot_sent(0);

        d.request_resync(ResyncTrigger::ExplicitRequest);

        // Tick 11 is past cooldown_ticks=10
        let result = d.check_and_consume(11);
        assert!(
            result.is_some(),
            "Trigger must fire after cooldown at tick 11"
        );
    }

    #[test]
    fn is_in_cooldown_correct() {
        let mut d = detector();
        assert!(!d.is_in_cooldown(0));

        d.mark_snapshot_sent(0);
        assert!(d.is_in_cooldown(5));
        assert!(!d.is_in_cooldown(10)); // exactly at boundary = not in cooldown
        assert!(!d.is_in_cooldown(11));
    }

    // ── Tick Drift Detection ──────────────────────────────────────────────────

    #[test]
    fn tick_drift_below_threshold_no_trigger() {
        let mut d = detector();
        d.update_last_ack_tick(0);
        d.check_tick_drift(10); // drift=10, threshold=30
        assert!(!d.needs_resync());
    }

    #[test]
    fn tick_drift_above_threshold_triggers_resync() {
        let mut d = detector();
        d.update_last_ack_tick(0);
        d.check_tick_drift(31); // drift=31, threshold=30
        assert!(d.needs_resync());
        assert!(matches!(
            d.pending_trigger(),
            Some(ResyncTrigger::TickDrift { drift: 31, .. })
        ));
    }

    #[test]
    fn tick_drift_detection_disabled_no_trigger() {
        let mut d = ResyncDetector::new(ResyncConfig {
            tick_drift_detection: false,
            ..Default::default()
        });
        d.update_last_ack_tick(0);
        d.check_tick_drift(1000); // massive drift but detection disabled
        assert!(!d.needs_resync());
    }

    #[test]
    fn update_last_ack_tick_only_advances() {
        let mut d = detector();
        d.update_last_ack_tick(100);
        d.update_last_ack_tick(50); // should not go backwards
        assert_eq!(d.last_ack_tick(), 100);
    }

    // ── Snapshot Sent ─────────────────────────────────────────────────────────

    #[test]
    fn mark_snapshot_sent_clears_pending() {
        let mut d = detector();
        d.request_resync(ResyncTrigger::ExplicitRequest);
        d.mark_snapshot_sent(5);
        assert!(!d.needs_resync());
        assert_eq!(d.last_snapshot_tick(), Some(5));
    }

    // ── Convenience Methods ───────────────────────────────────────────────────

    #[test]
    fn report_sequence_gap_sets_correct_trigger() {
        let mut d = detector();
        d.report_sequence_gap(5, 10);
        assert!(matches!(
            d.pending_trigger(),
            Some(ResyncTrigger::SequenceGap {
                expected_sequence: 5,
                received_sequence: 10,
            })
        ));
    }

    #[test]
    fn report_schema_mismatch_sets_correct_trigger() {
        let mut d = detector();
        d.report_schema_mismatch("0.1.0", "0.2.0");
        assert!(matches!(
            d.pending_trigger(),
            Some(ResyncTrigger::SchemaVersionDrift { .. })
        ));
    }

    #[test]
    fn report_explicit_request_sets_trigger() {
        let mut d = detector();
        d.report_explicit_request();
        assert!(matches!(
            d.pending_trigger(),
            Some(ResyncTrigger::ExplicitRequest)
        ));
    }

    // ── Snapshot Reason Mapping ───────────────────────────────────────────────

    #[test]
    fn initial_connection_maps_to_correct_reason() {
        let t = ResyncTrigger::InitialConnection;
        assert_eq!(t.snapshot_reason(), SnapshotReason::InitialConnection);
    }

    #[test]
    fn explicit_request_maps_to_correct_reason() {
        let t = ResyncTrigger::ExplicitRequest;
        assert_eq!(t.snapshot_reason(), SnapshotReason::ExplicitRequest);
    }

    #[test]
    fn sequence_gap_maps_to_desync_recovery() {
        let t = ResyncTrigger::SequenceGap {
            expected_sequence: 1,
            received_sequence: 5,
        };
        assert_eq!(t.snapshot_reason(), SnapshotReason::DesyncRecovery);
    }

    // ── Metrics ───────────────────────────────────────────────────────────────

    #[test]
    fn metrics_count_requests_by_trigger_type() {
        let mut d = detector();
        d.report_sequence_gap(1, 5);
        d.report_schema_mismatch("a", "b");
        d.report_explicit_request();

        let m = d.metrics();
        assert_eq!(m.sequence_gap_triggers, 1);
        assert_eq!(m.schema_drift_triggers, 1);
        assert_eq!(m.explicit_request_triggers, 1);
        assert_eq!(m.resync_requests, 3);
    }

    #[test]
    fn metrics_count_snapshots_sent() {
        let mut d = detector();
        d.request_resync(ResyncTrigger::InitialConnection);
        d.check_and_consume(0).unwrap();
        assert_eq!(d.metrics().snapshots_sent, 1);
    }

    #[test]
    fn metrics_count_cooldown_suppressions() {
        let mut d = detector();
        d.request_resync(ResyncTrigger::InitialConnection);
        d.check_and_consume(0).unwrap();
        d.mark_snapshot_sent(0);

        d.request_resync(ResyncTrigger::ExplicitRequest);
        d.check_and_consume(3); // within cooldown
        d.check_and_consume(5); // still within cooldown

        assert_eq!(d.metrics().cooldown_suppressions, 2);
    }
}
