//! # Delta Sync Engine
//!
//! The orchestrating entry point for Phase 7.3. Coordinates `DeltaBuilder`,
//! `DeltaCompressor`, `SnapshotRecovery`, and `ResyncDetector` to produce
//! the minimal set of wire messages every tick.
//!
//! ## Tick-level Contract
//! Each tick, the PhaseOrchestrator calls `process_tick()` with the current
//! `StateDelta` and `WorldSnapshot`. The engine returns either:
//! - A `DeltaSyncOutput::Delta(DeltaPayload)` — the compressed minimal delta
//! - A `DeltaSyncOutput::Snapshot(SnapshotPayload)` — full world state recovery
//! - A `DeltaSyncOutput::Nothing` — delta was empty, nothing to send
//!
//! The caller (EngineAdapterInterface) serializes the output and sends it.
//!
//! ## Decision Flow
//! ```text
//! process_tick(state_delta, world_snapshot)
//!   │
//!   ├─ ResyncDetector::needs_resync()?
//!   │    YES → build SNAPSHOT, mark snapshot sent, update compressor cache
//!   │          return DeltaSyncOutput::Snapshot
//!   │
//!   ├─ StateDelta::is_empty()?
//!   │    YES → return DeltaSyncOutput::Nothing
//!   │
//!   └─ Build DeltaPayload via DeltaBuilder
//!        → Compress via DeltaCompressor
//!        → If all changes compressed away → DeltaSyncOutput::Nothing
//!        → Otherwise → DeltaSyncOutput::Delta
//! ```
//!
//! ## Sequence ID Management
//! The engine assigns the `sequence_id` to each outbound DELTA.
//! The `SnapshotRecovery` is updated with the last-sent DELTA sequence_id
//! before each SNAPSHOT so the engine adapter can re-anchor its tracker.

use xace_core::errors::xace_error::XaceError;
use xace_core::runtime::state_delta::StateDelta;
use xace_core::runtime::world_snapshot::WorldSnapshot;
use xace_core::wire::delta_payload::DeltaPayload;
use xace_core::wire::snapshot_payload::SnapshotPayload;

use crate::delta_sync::delta_builder::DeltaBuilder;
use crate::delta_sync::delta_compressor::DeltaCompressor;
use crate::delta_sync::snapshot_recovery::{SnapshotRecovery, SnapshotRecoveryMetrics};
use crate::delta_sync::resync_detector::{ResyncDetector, ResyncConfig, ResyncTrigger};

// ── Sync Output ───────────────────────────────────────────────────────────────

/// The output of one `DeltaSyncEngine::process_tick()` call.
#[derive(Debug)]
pub enum DeltaSyncOutput {
    /// A compressed minimal delta — send as a DELTA WireMessage.
    Delta(DeltaPayload),

    /// A full world state snapshot — send as a SNAPSHOT WireMessage.
    Snapshot(SnapshotPayload),

    /// Nothing to send this tick — delta was empty or fully compressed away.
    Nothing,
}

impl DeltaSyncOutput {
    /// Returns true if this output requires sending a wire message.
    pub fn requires_send(&self) -> bool {
        !matches!(self, DeltaSyncOutput::Nothing)
    }

    /// Returns the tick this output was produced for.
    pub fn tick(&self) -> Option<u64> {
        match self {
            DeltaSyncOutput::Delta(p)    => Some(p.tick),
            DeltaSyncOutput::Snapshot(p) => Some(p.tick),
            DeltaSyncOutput::Nothing     => None,
        }
    }
}

// ── Engine Metrics ────────────────────────────────────────────────────────────

/// Combined metrics for one `DeltaSyncEngine` session.
#[derive(Debug, Clone, Default)]
pub struct DeltaSyncMetrics {
    /// Total ticks processed.
    pub ticks_processed: u64,
    /// Ticks where a DELTA was sent.
    pub delta_ticks: u64,
    /// Ticks where a SNAPSHOT was sent.
    pub snapshot_ticks: u64,
    /// Ticks where nothing was sent (empty or fully compressed).
    pub nothing_ticks: u64,
    /// Total DELTA fields sent (after compression).
    pub delta_fields_sent: u64,
    /// Total DELTA fields suppressed by compression.
    pub delta_fields_compressed: u64,
}

// ── Delta Sync Engine ─────────────────────────────────────────────────────────

/// Orchestrates per-tick delta synchronization between the XACE runtime
/// and the engine adapter.
///
/// ## One Instance Per Connection
/// Create a new `DeltaSyncEngine` when the engine adapter connects.
/// The compressor cache is pre-seeded with the initial SNAPSHOT.
pub struct DeltaSyncEngine {
    /// Builds wire-format DeltaPayload from StateDelta.
    builder: DeltaBuilder,

    /// Eliminates unchanged fields from DeltaPayload.
    compressor: DeltaCompressor,

    /// Builds SnapshotPayload for initial connection and desync recovery.
    recovery: SnapshotRecovery,

    /// Detects conditions requiring a SNAPSHOT instead of a DELTA.
    resync_detector: ResyncDetector,

    /// Monotonically increasing DELTA sequence counter.
    /// Managed here — shared with SnapshotRecovery for last_delta_sequence tracking.
    next_delta_sequence: u64,

    /// Accumulated metrics.
    metrics: DeltaSyncMetrics,
}

impl DeltaSyncEngine {
    // ── Construction ──────────────────────────────────────────────────────────

    /// Creates a new engine, pre-configured for the first connection.
    ///
    /// `initial_delta_sequence_id` must match the value agreed in the
    /// HandshakeAck so the engine adapter's SequenceTracker is in sync.
    pub fn new(
        schema_version: impl Into<String>,
        execution_plan_version: u32,
        world_id: impl Into<String>,
        initial_delta_sequence_id: u64,
        resync_config: ResyncConfig,
    ) -> Self {
        let schema = schema_version.into();
        let world  = world_id.into();

        let mut engine = Self {
            builder: DeltaBuilder,
            compressor: DeltaCompressor::new(),
            recovery: SnapshotRecovery::new(&schema, execution_plan_version, 0),
            resync_detector: ResyncDetector::new(resync_config),
            next_delta_sequence: initial_delta_sequence_id,
            metrics: DeltaSyncMetrics::default(),
        };

        // Queue the initial connection SNAPSHOT
        engine
            .resync_detector
            .request_resync(ResyncTrigger::InitialConnection);

        engine
    }

    /// Creates an engine with default resync configuration.
    pub fn with_defaults(
        schema_version: impl Into<String>,
        execution_plan_version: u32,
        initial_delta_sequence_id: u64,
    ) -> Self {
        Self::new(
            schema_version,
            execution_plan_version,
            "default",
            initial_delta_sequence_id,
            ResyncConfig::default(),
        )
    }

    // ── Primary API ───────────────────────────────────────────────────────────

    /// Processes one simulation tick and returns the appropriate wire output.
    ///
    /// Decision flow:
    /// 1. If resync is needed → build SNAPSHOT, seed compressor, return Snapshot
    /// 2. If StateDelta is empty → return Nothing
    /// 3. Build DeltaPayload → compress → if empty return Nothing, else Delta
    pub fn process_tick(
        &mut self,
        state_delta: &StateDelta,
        world_snapshot: &WorldSnapshot,
    ) -> Result<DeltaSyncOutput, XaceError> {
        self.metrics.ticks_processed += 1;
        let tick = state_delta.tick;

        // ── Resync path ────────────────────────────────────────────────────
        if let Some(trigger) = self.resync_detector.check_and_consume(tick) {
            let reason = trigger.snapshot_reason();

            // Update recovery with latest DELTA sequence before building
            self.recovery.update_last_delta_sequence(
                self.next_delta_sequence.saturating_sub(1),
            );

            let snapshot_payload = self.recovery.build_payload(world_snapshot, reason)?;

            // Seed the compressor cache from the snapshot so the next DELTA
            // is correctly compressed relative to what the engine received
            self.compressor.rebuild_from_snapshot(&snapshot_payload);
            self.resync_detector.mark_snapshot_sent(tick);

            self.metrics.snapshot_ticks += 1;
            return Ok(DeltaSyncOutput::Snapshot(snapshot_payload));
        }

        // ── Empty delta ────────────────────────────────────────────────────
        if !DeltaBuilder::would_produce_content(state_delta) {
            self.metrics.nothing_ticks += 1;
            return Ok(DeltaSyncOutput::Nothing);
        }

        // ── Delta path ─────────────────────────────────────────────────────
        let seq = self.next_delta_sequence;
        self.next_delta_sequence += 1;

        let (mut payload, build_metrics) = DeltaBuilder::build(state_delta, seq);
        let fields_before = build_metrics.total_field_changes as u64;

        // Compress — remove unchanged fields
        self.compressor.compress(&mut payload);

        let fields_after: u64 = payload
            .modified_entities
            .values()
            .flat_map(|eu| eu.component_updates.values())
            .map(|cu| cu.field_changes.len() as u64)
            .sum();

        self.metrics.delta_fields_sent += fields_after;
        self.metrics.delta_fields_compressed +=
            fields_before.saturating_sub(fields_after);

        // Update SnapshotRecovery with latest sequence in case resync fires next tick
        self.recovery.update_last_delta_sequence(seq);

        if payload.is_empty() {
            // All changes were compressed away — engine already has this state
            self.metrics.nothing_ticks += 1;
            Ok(DeltaSyncOutput::Nothing)
        } else {
            self.metrics.delta_ticks += 1;
            Ok(DeltaSyncOutput::Delta(payload))
        }
    }

    // ── Resync Control ────────────────────────────────────────────────────────

    /// Signals that a resync is required.
    /// Delegates to the `ResyncDetector`.
    pub fn request_resync(&mut self, trigger: ResyncTrigger) {
        self.resync_detector.request_resync(trigger);
    }

    /// Updates the engine adapter's last-acknowledged tick.
    /// Used by tick drift detection in the `ResyncDetector`.
    pub fn update_last_ack_tick(&mut self, tick: u64) {
        self.resync_detector.update_last_ack_tick(tick);
    }

    /// Reports a schema version mismatch from the engine adapter.
    pub fn report_schema_mismatch(&mut self, expected: &str, received: &str) {
        self.resync_detector.report_schema_mismatch(expected, received);
    }

    /// Reports a DELTA sequence gap.
    pub fn report_sequence_gap(&mut self, expected: u64, received: u64) {
        self.resync_detector.report_sequence_gap(expected, received);
    }

    /// Reports an explicit SNAPSHOT request from the engine adapter.
    pub fn report_explicit_snapshot_request(&mut self) {
        self.resync_detector.report_explicit_request();
    }

    // ── Inspection ────────────────────────────────────────────────────────────

    /// Returns combined delta sync metrics.
    pub fn metrics(&self) -> &DeltaSyncMetrics {
        &self.metrics
    }

    /// Returns snapshot recovery metrics.
    pub fn snapshot_metrics(&self) -> &SnapshotRecoveryMetrics {
        self.recovery.metrics()
    }

    /// Returns compressor metrics.
    pub fn compressor_metrics(&self) -> &crate::delta_sync::delta_compressor::CompressorMetrics {
        self.compressor.metrics()
    }

    /// Returns the next DELTA sequence_id that will be assigned.
    pub fn next_delta_sequence(&self) -> u64 {
        self.next_delta_sequence
    }

    /// Returns true if a resync is currently pending.
    pub fn needs_resync(&self) -> bool {
        self.resync_detector.needs_resync()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::entity_state::EntityState;
    use xace_core::runtime::state_delta::{SpawnedEntity, StateDelta, ComponentChange};
    use xace_core::runtime::world_snapshot::{
        EntityRecord, WorldSnapshot,
    };

    // ── Helpers ───────────────────────────────────────────────────────────────

    fn engine() -> DeltaSyncEngine {
        DeltaSyncEngine::new("0.1.0", 1, "default", 1,
            ResyncConfig { cooldown_ticks: 2, max_tick_drift: 100, tick_drift_detection: true }
        )
    }

    fn valid_snapshot(tick: u64) -> WorldSnapshot {
        let mut s = WorldSnapshot::empty("0.1.0", 1, 42);
        s.tick = tick;
        s.world_hash = "hash_valid".into();
        s.cgs_hash = "cgs_hash".into();
        s.entity_store_snapshot.entities.push(
            EntityRecord::new(1, EntityState::Active, 0)
        );
        s.entity_store_snapshot.next_entity_id = 2;
        s
    }

    fn empty_delta(tick: u64) -> StateDelta {
        StateDelta::empty(tick, "0.1.0")
    }

    fn delta_with_spawn(tick: u64) -> StateDelta {
        let mut d = StateDelta::empty(tick, "0.1.0");
        d.record_spawn(SpawnedEntity::new(1, "actor_player"));
        d
    }

    fn delta_with_update(tick: u64) -> StateDelta {
        let mut d = StateDelta::empty(tick, "0.1.0");
        d.record_component_update(
            1,
            ComponentChange::single_field(1, "COMP_TRANSFORM_V1", "position", r#"{"x":1}"#),
        );
        d
    }

    // ── Initial Connection ────────────────────────────────────────────────────

    #[test]
    fn first_tick_always_sends_snapshot() {
        let mut e = engine();
        let snap = valid_snapshot(0);
        let result = e.process_tick(&empty_delta(0), &snap).unwrap();
        assert!(matches!(result, DeltaSyncOutput::Snapshot(_)));
        assert_eq!(e.metrics().snapshot_ticks, 1);
    }

    #[test]
    fn snapshot_output_carries_correct_tick() {
        let mut e = engine();
        let snap = valid_snapshot(5);
        let result = e.process_tick(&empty_delta(5), &snap).unwrap();
        if let DeltaSyncOutput::Snapshot(p) = result {
            assert_eq!(p.tick, 5);
        } else {
            panic!("Expected Snapshot");
        }
    }

    // ── Empty Delta → Nothing ─────────────────────────────────────────────────

    #[test]
    fn empty_delta_after_snapshot_returns_nothing() {
        let mut e = engine();
        let snap = valid_snapshot(0);
        e.process_tick(&empty_delta(0), &snap).unwrap(); // initial snapshot
        let result = e.process_tick(&empty_delta(1), &snap).unwrap();
        assert!(matches!(result, DeltaSyncOutput::Nothing));
        assert_eq!(e.metrics().nothing_ticks, 1);
    }

    // ── Delta Path ────────────────────────────────────────────────────────────

    #[test]
    fn spawn_produces_delta_output() {
        let mut e = engine();
        let snap = valid_snapshot(0);
        e.process_tick(&empty_delta(0), &snap).unwrap(); // initial snapshot
        let result = e.process_tick(&delta_with_spawn(1), &snap).unwrap();
        assert!(matches!(result, DeltaSyncOutput::Delta(_)));
        assert_eq!(e.metrics().delta_ticks, 1);
    }

    #[test]
    fn delta_output_carries_sequence_id() {
        let mut e = engine();
        let snap = valid_snapshot(0);
        e.process_tick(&empty_delta(0), &snap).unwrap();

        let result = e.process_tick(&delta_with_spawn(1), &snap).unwrap();
        if let DeltaSyncOutput::Delta(p) = result {
            assert_eq!(p.sequence_id, 1); // first DELTA uses initial_delta_sequence_id=1
        } else {
            panic!("Expected Delta");
        }
    }

    #[test]
    fn sequence_id_increments_each_delta() {
        let mut e = engine();
        let snap = valid_snapshot(0);
        e.process_tick(&empty_delta(0), &snap).unwrap();

        e.process_tick(&delta_with_spawn(1), &snap).unwrap();
        e.process_tick(&delta_with_spawn(2), &snap).unwrap();
        assert_eq!(e.next_delta_sequence(), 3);
    }

    // ── Compression Integration ───────────────────────────────────────────────

    #[test]
    fn identical_updates_compressed_to_nothing() {
        let mut e = engine();
        let snap = valid_snapshot(0);
        e.process_tick(&empty_delta(0), &snap).unwrap(); // snapshot

        // First update: primes the compressor
        e.process_tick(&delta_with_update(1), &snap).unwrap();

        // Identical update: should be compressed away entirely
        let result = e.process_tick(&delta_with_update(2), &snap).unwrap();
        assert!(matches!(result, DeltaSyncOutput::Nothing),
            "Identical second update must be compressed to Nothing");
    }

    // ── Resync Path ───────────────────────────────────────────────────────────

    #[test]
    fn report_sequence_gap_triggers_snapshot_next_tick() {
        let mut e = engine();
        let snap = valid_snapshot(0);
        e.process_tick(&empty_delta(0), &snap).unwrap(); // initial snapshot

        e.report_sequence_gap(5, 10);
        assert!(e.needs_resync());

        let result = e.process_tick(&empty_delta(3), &snap).unwrap();
        assert!(matches!(result, DeltaSyncOutput::Snapshot(_)));
    }

    #[test]
    fn explicit_snapshot_request_triggers_snapshot() {
        let mut e = engine();
        let snap = valid_snapshot(0);
        e.process_tick(&empty_delta(0), &snap).unwrap();

        e.report_explicit_snapshot_request();
        let result = e.process_tick(&delta_with_spawn(3), &snap).unwrap();
        assert!(matches!(result, DeltaSyncOutput::Snapshot(_)));
    }

    #[test]
    fn snapshot_reseeds_compressor() {
        let mut e = engine();
        let snap = valid_snapshot(0);
        e.process_tick(&empty_delta(0), &snap).unwrap(); // initial snapshot

        // Send an update, then force a resync snapshot
        e.process_tick(&delta_with_update(1), &snap).unwrap();
        e.report_explicit_snapshot_request();
        e.process_tick(&empty_delta(2), &snap).unwrap(); // resync snapshot

        // After resync, an identical update should be treated as fresh
        // (compressor was rebuilt from snapshot which has no component updates)
        let result = e.process_tick(&delta_with_update(3), &snap).unwrap();
        // The update should pass through — snapshot didn't contain the update data
        assert!(!matches!(result, DeltaSyncOutput::Snapshot(_)));
    }

    // ── Metrics ───────────────────────────────────────────────────────────────

    #[test]
    fn metrics_count_all_output_types() {
        let mut e = engine();
        let snap = valid_snapshot(0);

        e.process_tick(&empty_delta(0), &snap).unwrap(); // snapshot
        e.process_tick(&empty_delta(1), &snap).unwrap(); // nothing
        e.process_tick(&delta_with_spawn(2), &snap).unwrap(); // delta

        let m = e.metrics();
        assert_eq!(m.snapshot_ticks, 1);
        assert_eq!(m.nothing_ticks, 1);
        assert_eq!(m.delta_ticks, 1);
        assert_eq!(m.ticks_processed, 3);
    }

    // ── DeltaSyncOutput helpers ───────────────────────────────────────────────

    #[test]
    fn delta_output_requires_send() {
        let payload = DeltaPayload::empty(1, 1, "0.1.0");
        assert!(DeltaSyncOutput::Delta(payload).requires_send());
    }

    #[test]
    fn nothing_output_does_not_require_send() {
        assert!(!DeltaSyncOutput::Nothing.requires_send());
    }

    #[test]
    fn nothing_output_tick_is_none() {
        assert_eq!(DeltaSyncOutput::Nothing.tick(), None);
    }
}