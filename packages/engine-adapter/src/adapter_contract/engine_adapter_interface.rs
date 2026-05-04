//! # Engine Adapter Interface
//!
//! The concrete `EngineAdapterInterface` struct — the XACE-side half of the
//! engine communication bridge. Implements `IEngineAdapter` from `contracts/interfaces.rs`.
//!
//! ## Responsibility
//! This struct owns the transport layer (TCP or SHM) and the sequence tracker,
//! and exposes the five IEngineAdapter operations to the PhaseOrchestrator:
//!
//! - `apply_delta()`            — serialize and send a DeltaPayload to the engine
//! - `apply_snapshot()`         — serialize and send a SnapshotPayload to the engine
//! - `collect_local_input()`    — drain inbound INPUT messages from the engine
//! - `receive_feedback_batch()` — drain inbound FEEDBACK messages from the engine
//! - `send_visibility_queries()`— pack and send batched visibility queries
//! - `send_event()`             — serialize and send a game event notification
//!
//! ## Transport Abstraction
//! The adapter is generic over a `Transport` trait (defined below) so it can
//! work identically over TCP (`TcpTransport`) or shared-memory (`ShmTransport`).
//! The `Transport` trait is a thin facade over the two send/receive methods
//! both transports already expose.
//!
//! ## Layer 6 Contract (I5, D13)
//! This struct is the only place in XACE that touches engine I/O.
//! It NEVER modifies authoritative simulation state directly.
//! It reads `StateDelta` and `SnapshotPayload` (produced by the runtime),
//! serializes them, and sends them. On the inbound path it returns raw bytes
//! or deserialized `FeedbackPayload` / input bytes — the handlers in Phase 7
//! (engine-feedback package) are responsible for writing results to components
//! via the Mutation Gate.
//!
//! ## Sequence Tracking
//! Every outbound DELTA and SNAPSHOT message gets a monotonically increasing
//! `sequence_id`. The `SequenceTracker` also validates every inbound FEEDBACK
//! and INPUT message. Gaps in inbound sequences are logged; gaps in outbound
//! DELTA sequences trigger snapshot recovery on the engine side automatically
//! (the engine detects the gap via its own sequence tracker).

use serde_json;

use xace_core::contracts::interfaces::{IEngineAdapter, VisibilityQuery};
use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::events::event_struct::Event;
use xace_core::runtime::phase_enum::PhaseEnum;
use xace_core::wire::delta_payload::DeltaPayload;
use xace_core::wire::feedback_payload::FeedbackPayload;
use xace_core::wire::message_type::MessageType;
use xace_core::wire::snapshot_payload::SnapshotPayload;
use xace_core::wire::wire_message::WireMessage;
use xace_core::entity_metadata::Tick;

use crate::transport::sequence_tracker::{SequenceCheckResult, SequenceTracker};

// ── Transport Trait ───────────────────────────────────────────────────────────

/// Minimal transport facade shared by `TcpTransport` and `ShmTransport`.
///
/// Both concrete transports already expose `send_message`, `send_batch`,
/// and `try_receive_messages` with identical signatures. This trait lets
/// `EngineAdapterInterface` be generic over either without duplicating logic.
///
/// Implement this for any transport that wants to plug into the adapter.
pub trait Transport: Send + Sync {
    /// Sends a single WireMessage.
    fn send_message(&mut self, msg: &WireMessage) -> Result<(), XaceError>;

    /// Sends multiple WireMessages in one batch (one syscall / one ring write).
    fn send_batch(&mut self, messages: &[WireMessage]) -> Result<(), XaceError>;

    /// Non-blocking drain — returns all complete inbound WireMessages.
    /// Returns empty Vec if no data is available right now.
    fn try_receive_messages(&mut self) -> Result<Vec<WireMessage>, XaceError>;

    /// Returns true if the transport layer is connected.
    fn is_connected(&self) -> bool;

    /// Human-readable name of the engine this transport talks to.
    fn engine_name(&self) -> &str;
}

// ── Adapter Metrics ───────────────────────────────────────────────────────────

/// Accumulated metrics for one EngineAdapterInterface session.
#[derive(Debug, Clone, Default)]
pub struct AdapterMetrics {
    /// Total DELTA messages sent.
    pub deltas_sent: u64,
    /// Total SNAPSHOT messages sent.
    pub snapshots_sent: u64,
    /// Total EVENT messages sent.
    pub events_sent: u64,
    /// Total visibility query batches sent.
    pub visibility_query_batches_sent: u64,
    /// Total visibility queries sent (sum across all batches).
    pub visibility_queries_sent: u64,
    /// Total FEEDBACK payloads received.
    pub feedback_payloads_received: u64,
    /// Total FEEDBACK messages (individual) received across all payloads.
    pub feedback_messages_received: u64,
    /// Total INPUT packets received.
    pub input_packets_received: u64,
    /// Inbound sequence gaps detected (FEEDBACK or INPUT).
    pub inbound_sequence_gaps: u64,
    /// Total ticks with empty feedback (engine sent nothing).
    pub empty_feedback_ticks: u64,
}

// ── Engine Adapter Interface ──────────────────────────────────────────────────

/// The XACE-side engine adapter. Implements `IEngineAdapter`.
///
/// Owns the transport and exposes clean per-operation methods to the
/// PhaseOrchestrator. All sequence management is handled internally.
///
/// ## Outbound Sequence IDs
/// DELTA and SNAPSHOT each have independent monotonic counters.
/// Both start at 1. The `initial_delta_sequence_id` from the handshake
/// determines the engine adapter's starting expectation for DELTA messages —
/// pass it to `SequenceTracker::with_initial_delta_sequence()` on the engine side.
///
/// ## Inbound Sequence Validation
/// Incoming FEEDBACK and INPUT messages are checked against the tracker.
/// Gaps are logged but do not halt the session — feedback is non-critical
/// (one missed tick of animation state is invisible to the player).
/// INPUT gaps are more serious and are surfaced via `inbound_sequence_gaps`.
pub struct EngineAdapterInterface<T: Transport> {
    /// The underlying transport (TCP or SHM).
    transport: T,

    /// Sequence tracker for inbound messages (FEEDBACK, INPUT).
    inbound_tracker: SequenceTracker,

    /// Monotonically increasing DELTA sequence counter.
    next_delta_sequence: u64,

    /// Monotonically increasing SNAPSHOT sequence counter.
    next_snapshot_sequence: u64,

    /// Monotonically increasing EVENT sequence counter.
    next_event_sequence: u64,

    /// Accumulated session metrics.
    metrics: AdapterMetrics,

    /// The schema version for this session — embedded in every outbound message.
    schema_version: String,

    /// The ExecutionPlan version for this session.
    execution_plan_version: u32,

    /// The world session ID.
    world_id: String,
}

impl<T: Transport> EngineAdapterInterface<T> {
    // ── Construction ──────────────────────────────────────────────────────────

    /// Creates a new adapter interface wrapping the given transport.
    ///
    /// - `initial_delta_sequence_id` should come from the HandshakeAck so the
    ///   engine adapter and XACE agree on the first DELTA sequence_id.
    pub fn new(
        transport: T,
        schema_version: impl Into<String>,
        execution_plan_version: u32,
        world_id: impl Into<String>,
        initial_delta_sequence_id: u64,
    ) -> Self {
        Self {
            transport,
            inbound_tracker: SequenceTracker::new(),
            next_delta_sequence: initial_delta_sequence_id,
            next_snapshot_sequence: 1,
            next_event_sequence: 1,
            metrics: AdapterMetrics::default(),
            schema_version: schema_version.into(),
            execution_plan_version,
            world_id: world_id.into(),
        }
    }

    // ── Outbound: DELTA ───────────────────────────────────────────────────────

    /// Serializes a `DeltaPayload` and sends it to the engine adapter.
    ///
    /// Assigns the next DELTA `sequence_id` and embeds it in the WireMessage
    /// envelope. The engine adapter's `SequenceTracker` validates this on receipt.
    ///
    /// Only called when the delta is non-empty — the PhaseOrchestrator
    /// must check `StateDelta::is_empty()` before calling this.
    pub fn send_delta(&mut self, delta: &DeltaPayload) -> Result<(), XaceError> {
        let seq = self.next_delta_sequence;
        self.next_delta_sequence += 1;

        let payload_json = serde_json::to_string(delta).map_err(|e| XaceError::FatalError {
            message: format!(
                "EngineAdapterInterface: failed to serialize DeltaPayload — {}",
                e
            ),
            context: ErrorContext::new("EngineAdapterInterface", "send_delta")
                .with_tick(delta.tick),
            snapshot_recovery_possible: false,
        })?;

        let msg = WireMessage::delta(
            &self.world_id,
            &self.schema_version,
            self.execution_plan_version,
            delta.tick,
            seq,
            payload_json,
        );

        self.transport.send_message(&msg)?;
        self.metrics.deltas_sent += 1;
        Ok(())
    }

    // ── Outbound: SNAPSHOT ────────────────────────────────────────────────────

    /// Serializes a `SnapshotPayload` and sends it to the engine adapter.
    ///
    /// Called on initial connection or desync recovery.
    /// The engine adapter resets its sequence tracker on receipt using
    /// `SnapshotPayload.last_delta_sequence_id`.
    pub fn send_snapshot(&mut self, snapshot: &SnapshotPayload) -> Result<(), XaceError> {
        let seq = self.next_snapshot_sequence;
        self.next_snapshot_sequence += 1;

        let payload_json =
            serde_json::to_string(snapshot).map_err(|e| XaceError::FatalError {
                message: format!(
                    "EngineAdapterInterface: failed to serialize SnapshotPayload — {}",
                    e
                ),
                context: ErrorContext::new("EngineAdapterInterface", "send_snapshot")
                    .with_tick(snapshot.tick),
                snapshot_recovery_possible: false,
            })?;

        let msg = WireMessage::snapshot(
            &self.world_id,
            &self.schema_version,
            self.execution_plan_version,
            snapshot.tick,
            seq,
            payload_json,
        );

        self.transport.send_message(&msg)?;
        self.metrics.snapshots_sent += 1;
        Ok(())
    }

    // ── Outbound: EVENT ───────────────────────────────────────────────────────

    /// Serializes a game `Event` and sends it as a WireMessage to the engine.
    ///
    /// Events that require engine-side response (play animation, trigger audio)
    /// are forwarded here. The engine reacts and sends feedback next tick.
    pub fn send_event_msg(&mut self, event: &Event) -> Result<(), XaceError> {
        let seq = self.next_event_sequence;
        self.next_event_sequence += 1;

        let payload_json = serde_json::to_string(event).map_err(|e| XaceError::FatalError {
            message: format!(
                "EngineAdapterInterface: failed to serialize Event — {}",
                e
            ),
            context: ErrorContext::new("EngineAdapterInterface", "send_event_msg")
                .with_tick(event.creation_tick),
            snapshot_recovery_possible: false,
        })?;

        let msg = WireMessage::new(
            &self.world_id,
            &self.schema_version,
            self.execution_plan_version,
            event.creation_tick,
            seq,
            MessageType::Event,
            payload_json,
        );

        self.transport.send_message(&msg)?;
        self.metrics.events_sent += 1;
        Ok(())
    }

    // ── Outbound: VISIBILITY QUERIES ──────────────────────────────────────────

    /// Packs a batch of visibility queries into a CONTROL WireMessage and sends it.
    ///
    /// XACE collects `COMP_PERCEPTION_V1.visibility_query_pending` flags
    /// each tick, batches them here, and the engine performs raycasts.
    /// Results arrive next tick as `VisibilityQueryResult` FEEDBACK messages.
    pub fn send_visibility_query_batch(
        &mut self,
        queries: &[VisibilityQuery],
        tick: Tick,
    ) -> Result<(), XaceError> {
        if queries.is_empty() {
            return Ok(());
        }

        // Serialize as a JSON array of query objects
        let query_records: Vec<serde_json::Value> = queries
            .iter()
            .map(|q| {
                serde_json::json!({
                    "observer_entity_id": q.observer_entity_id,
                    "target_entity_id":   q.target_entity_id,
                    "max_distance":       q.max_distance,
                })
            })
            .collect();

        let payload_json =
            serde_json::to_string(&query_records).map_err(|e| XaceError::FatalError {
                message: format!(
                    "EngineAdapterInterface: failed to serialize visibility queries — {}",
                    e
                ),
                context: ErrorContext::new(
                    "EngineAdapterInterface",
                    "send_visibility_query_batch",
                )
                .with_tick(tick),
                snapshot_recovery_possible: false,
            })?;

        let msg = WireMessage::control(
            &self.world_id,
            &self.schema_version,
            self.execution_plan_version,
            tick, // reuse sequence slot — CONTROL messages share a counter in Phase 15
            payload_json,
        );

        self.transport.send_message(&msg)?;
        self.metrics.visibility_query_batches_sent += 1;
        self.metrics.visibility_queries_sent += queries.len() as u64;
        Ok(())
    }

    // ── Inbound: FEEDBACK ─────────────────────────────────────────────────────

    /// Drains all available FEEDBACK messages from the transport.
    ///
    /// Non-blocking — returns immediately if no data is available.
    /// Called at the START of each tick before any phase runs (I13).
    ///
    /// Sequence-validates every FEEDBACK message. Gaps are logged
    /// to metrics but do not halt the session.
    ///
    /// Returns a combined `FeedbackPayload` with all messages from this drain.
    /// If no FEEDBACK messages arrived, returns an empty payload for the tick.
    pub fn drain_feedback(&mut self, tick: Tick) -> Result<FeedbackPayload, XaceError> {
        let messages = self.transport.try_receive_messages()?;

        let mut combined = FeedbackPayload::empty(tick);

        for msg in &messages {
            match msg.message_type {
                MessageType::Feedback => {
                    // Sequence check
                    let check = self.inbound_tracker.check(msg);
                    if check.is_gap() {
                        self.metrics.inbound_sequence_gaps += 1;
                        eprintln!(
                            "[WARN] EngineAdapterInterface: FEEDBACK sequence gap at tick {} — {}",
                            tick,
                            check
                        );
                    }
                    if check.should_discard() {
                        continue;
                    }

                    // Deserialize the FeedbackPayload from the wire message payload
                    match serde_json::from_str::<FeedbackPayload>(&msg.payload) {
                        Ok(fb) => {
                            self.metrics.feedback_messages_received +=
                                fb.message_count() as u64;
                            for feedback_msg in fb.messages {
                                combined.add_message(feedback_msg);
                            }
                        }
                        Err(e) => {
                            eprintln!(
                                "[WARN] EngineAdapterInterface: failed to deserialize \
                                 FeedbackPayload — {}",
                                e
                            );
                        }
                    }
                }

                MessageType::Input => {
                    // Input messages are counted here but returned separately
                    // via collect_local_input — just track the sequence.
                    let check = self.inbound_tracker.check(msg);
                    if check.is_gap() {
                        self.metrics.inbound_sequence_gaps += 1;
                    }
                    self.metrics.input_packets_received += 1;
                }

                _ => {
                    // SNAPSHOT, DELTA, EVENT, CONTROL inbound are not expected
                    // from the engine adapter in normal operation.
                    eprintln!(
                        "[WARN] EngineAdapterInterface: unexpected inbound message \
                         type {:?} from engine at tick {}",
                        msg.message_type, tick
                    );
                }
            }
        }

        self.metrics.feedback_payloads_received += 1;
        if combined.is_empty() {
            self.metrics.empty_feedback_ticks += 1;
        }

        Ok(combined)
    }

    // ── Inbound: INPUT ────────────────────────────────────────────────────────

    /// Drains all available INPUT messages from the transport.
    ///
    /// Returns raw input bytes for each INPUT WireMessage received.
    /// The Phase 15 InputSynchroniser deserializes these into typed
    /// InputPackets — the adapter layer stays wire-format agnostic.
    ///
    /// Sequence-validates every INPUT message.
    pub fn drain_input(&mut self, tick: Tick) -> Result<Vec<Vec<u8>>, XaceError> {
        let messages = self.transport.try_receive_messages()?;
        let mut input_payloads = Vec::new();

        for msg in &messages {
            if !matches!(msg.message_type, MessageType::Input) {
                continue;
            }

            let check = self.inbound_tracker.check(msg);
            if check.is_gap() {
                self.metrics.inbound_sequence_gaps += 1;
                eprintln!(
                    "[WARN] EngineAdapterInterface: INPUT sequence gap at tick {} — {}",
                    tick, check
                );
            }
            if check.should_discard() {
                continue;
            }

            self.metrics.input_packets_received += 1;
            input_payloads.push(msg.payload.as_bytes().to_vec());
        }

        Ok(input_payloads)
    }

    // ── Inspection ────────────────────────────────────────────────────────────

    /// Returns the accumulated adapter metrics.
    pub fn metrics(&self) -> &AdapterMetrics {
        &self.metrics
    }

    /// Returns a reference to the inbound sequence tracker.
    pub fn inbound_tracker(&self) -> &SequenceTracker {
        &self.inbound_tracker
    }

    /// Returns the next DELTA sequence_id that will be assigned.
    pub fn next_delta_sequence(&self) -> u64 {
        self.next_delta_sequence
    }

    /// Returns the next SNAPSHOT sequence_id that will be assigned.
    pub fn next_snapshot_sequence(&self) -> u64 {
        self.next_snapshot_sequence
    }

    /// Returns a reference to the underlying transport.
    pub fn transport(&self) -> &T {
        &self.transport
    }

    /// Returns a mutable reference to the underlying transport.
    pub fn transport_mut(&mut self) -> &mut T {
        &mut self.transport
    }
}

// ── IEngineAdapter Implementation ─────────────────────────────────────────────

impl<T: Transport> IEngineAdapter for EngineAdapterInterface<T> {
    fn apply_delta(&mut self, delta: &DeltaPayload) -> Result<(), XaceError> {
        self.send_delta(delta)
    }

    fn apply_snapshot(&mut self, snapshot: &SnapshotPayload) -> Result<(), XaceError> {
        self.send_snapshot(snapshot)
    }

    fn collect_local_input(&mut self, tick: Tick) -> Result<Vec<u8>, XaceError> {
        // Drain all INPUT payloads and concatenate raw bytes.
        // Phase 15 InputSynchroniser knows how to parse them.
        let inputs = self.drain_input(tick)?;
        let combined: Vec<u8> = inputs.into_iter().flatten().collect();
        Ok(combined)
    }

    fn receive_feedback_batch(&mut self, tick: Tick) -> Result<FeedbackPayload, XaceError> {
        self.drain_feedback(tick)
    }

    fn send_visibility_queries(
        &mut self,
        queries: Vec<VisibilityQuery>,
    ) -> Result<(), XaceError> {
        // tick=0 here — visibility queries carry no specific tick,
        // results arrive in the feedback of the following tick.
        self.send_visibility_query_batch(&queries, 0)
    }

    fn send_event(&mut self, event: &Event) -> Result<(), XaceError> {
        self.send_event_msg(event)
    }

    fn is_connected(&self) -> bool {
        self.transport.is_connected()
    }

    fn engine_name(&self) -> &str {
        self.transport.engine_name()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::VecDeque;
    use xace_core::events::event_type::EventType;
    use xace_core::runtime::phase_enum::PhaseEnum;
    use xace_core::wire::delta_payload::DeltaPayload;
    use xace_core::wire::snapshot_payload::{SnapshotPayload, SnapshotReason};
    use xace_core::wire::feedback_payload::{FeedbackMessage, FeedbackType};

    // ── Mock Transport ────────────────────────────────────────────────────────

    /// A simple in-memory mock transport for tests.
    /// Captures sent messages and allows injecting inbound messages.
    struct MockTransport {
        sent: Vec<WireMessage>,
        inbound: VecDeque<WireMessage>,
        connected: bool,
    }

    impl MockTransport {
        fn new() -> Self {
            Self {
                sent: Vec::new(),
                inbound: VecDeque::new(),
                connected: true,
            }
        }

        fn inject(&mut self, msg: WireMessage) {
            self.inbound.push_back(msg);
        }

        fn last_sent(&self) -> Option<&WireMessage> {
            self.sent.last()
        }
    }

    impl Transport for MockTransport {
        fn send_message(&mut self, msg: &WireMessage) -> Result<(), XaceError> {
            self.sent.push(msg.clone());
            Ok(())
        }

        fn send_batch(&mut self, messages: &[WireMessage]) -> Result<(), XaceError> {
            for msg in messages {
                self.sent.push(msg.clone());
            }
            Ok(())
        }

        fn try_receive_messages(&mut self) -> Result<Vec<WireMessage>, XaceError> {
            Ok(self.inbound.drain(..).collect())
        }

        fn is_connected(&self) -> bool {
            self.connected
        }

        fn engine_name(&self) -> &str {
            "MockEngine"
        }
    }

    fn adapter() -> EngineAdapterInterface<MockTransport> {
        EngineAdapterInterface::new(
            MockTransport::new(),
            "0.1.0",
            1,
            "default",
            1, // initial_delta_sequence_id
        )
    }

    fn empty_delta(tick: u64) -> DeltaPayload {
        let mut d = DeltaPayload::empty(tick, 1, "0.1.0");
        // Add a spawn so it's non-empty for test purposes
        use xace_core::wire::delta_payload::WireSpawnedEntity;
        d.add_spawn(WireSpawnedEntity::new(1, "actor_player"));
        d
    }

    fn test_snapshot(tick: u64) -> SnapshotPayload {
        SnapshotPayload::new(
            tick,
            "0.1.0",
            1,
            "cgs_hash",
            "world_hash",
            0,
            SnapshotReason::InitialConnection,
        )
    }

    fn test_event() -> Event {
        Event::broadcast(1, EventType::EntitySpawned, 1, PhaseEnum::Simulation)
    }

    fn feedback_wire_msg(tick: u64, seq: u64) -> WireMessage {
        let payload = FeedbackPayload {
            tick,
            messages: vec![FeedbackMessage {
                feedback_type: FeedbackType::AnimationStateUpdate,
                entity_id: 1,
                generated_frame: tick,
                payload_json: "{}".into(),
            }],
        };
        WireMessage::feedback(
            "default",
            "0.1.0",
            1,
            tick,
            seq,
            serde_json::to_string(&payload).unwrap(),
        )
    }

    // ── send_delta ────────────────────────────────────────────────────────────

    #[test]
    fn send_delta_assigns_sequence_id_starting_at_initial() {
        let mut a = adapter();
        a.send_delta(&empty_delta(1)).unwrap();
        let sent = a.transport().sent.last().unwrap();
        assert_eq!(sent.sequence_id, 1);
        assert!(sent.is_delta());
    }

    #[test]
    fn send_delta_increments_sequence_each_call() {
        let mut a = adapter();
        a.send_delta(&empty_delta(1)).unwrap();
        a.send_delta(&empty_delta(2)).unwrap();
        a.send_delta(&empty_delta(3)).unwrap();
        assert_eq!(a.next_delta_sequence(), 4);
        assert_eq!(a.metrics().deltas_sent, 3);
    }

    #[test]
    fn send_delta_embeds_correct_tick() {
        let mut a = adapter();
        a.send_delta(&empty_delta(42)).unwrap();
        let sent = a.transport().sent.last().unwrap();
        assert_eq!(sent.tick, 42);
    }

    #[test]
    fn send_delta_payload_deserializable() {
        let mut a = adapter();
        let delta = empty_delta(5);
        a.send_delta(&delta).unwrap();
        let sent = a.transport().sent.last().unwrap();
        let decoded: DeltaPayload = serde_json::from_str(&sent.payload).unwrap();
        assert_eq!(decoded.tick, 5);
    }

    // ── send_snapshot ─────────────────────────────────────────────────────────

    #[test]
    fn send_snapshot_uses_snapshot_message_type() {
        let mut a = adapter();
        a.send_snapshot(&test_snapshot(0)).unwrap();
        assert!(a.transport().last_sent().unwrap().is_snapshot());
        assert_eq!(a.metrics().snapshots_sent, 1);
    }

    #[test]
    fn send_snapshot_sequence_independent_from_delta() {
        let mut a = adapter();
        a.send_delta(&empty_delta(1)).unwrap();
        a.send_delta(&empty_delta(2)).unwrap();
        a.send_snapshot(&test_snapshot(3)).unwrap();
        // SNAPSHOT sequence starts at 1 regardless of DELTA sequence
        let snap_msg = a.transport().sent.last().unwrap();
        assert_eq!(snap_msg.sequence_id, 1);
    }

    // ── send_event ────────────────────────────────────────────────────────────

    #[test]
    fn send_event_uses_event_message_type() {
        let mut a = adapter();
        a.send_event_msg(&test_event()).unwrap();
        let sent = a.transport().last_sent().unwrap();
        assert!(matches!(sent.message_type, MessageType::Event));
        assert_eq!(a.metrics().events_sent, 1);
    }

    #[test]
    fn send_event_payload_is_valid_json() {
        let mut a = adapter();
        a.send_event_msg(&test_event()).unwrap();
        let sent = a.transport().last_sent().unwrap();
        assert!(serde_json::from_str::<serde_json::Value>(&sent.payload).is_ok());
    }

    // ── visibility queries ────────────────────────────────────────────────────

    #[test]
    fn send_empty_visibility_batch_is_noop() {
        let mut a = adapter();
        a.send_visibility_query_batch(&[], 1).unwrap();
        assert_eq!(a.transport().sent.len(), 0);
        assert_eq!(a.metrics().visibility_query_batches_sent, 0);
    }

    #[test]
    fn send_visibility_queries_packs_all_queries() {
        let mut a = adapter();
        let queries = vec![
            VisibilityQuery { observer_entity_id: 1, target_entity_id: 2, max_distance: 10.0 },
            VisibilityQuery { observer_entity_id: 1, target_entity_id: 3, max_distance: 10.0 },
        ];
        a.send_visibility_query_batch(&queries, 5).unwrap();
        assert_eq!(a.metrics().visibility_queries_sent, 2);
        assert_eq!(a.metrics().visibility_query_batches_sent, 1);
        // Payload is a JSON array with 2 entries
        let sent = a.transport().last_sent().unwrap();
        let arr: serde_json::Value = serde_json::from_str(&sent.payload).unwrap();
        assert_eq!(arr.as_array().unwrap().len(), 2);
    }

    // ── drain_feedback ────────────────────────────────────────────────────────

    #[test]
    fn drain_feedback_empty_returns_empty_payload() {
        let mut a = adapter();
        let fb = a.drain_feedback(1).unwrap();
        assert!(fb.is_empty());
        assert_eq!(a.metrics().empty_feedback_ticks, 1);
    }

    #[test]
    fn drain_feedback_deserializes_messages() {
        let mut a = adapter();
        a.transport_mut().inject(feedback_wire_msg(1, 1));
        let fb = a.drain_feedback(1).unwrap();
        assert_eq!(fb.message_count(), 1);
        assert_eq!(a.metrics().feedback_messages_received, 1);
    }

    #[test]
    fn drain_feedback_detects_sequence_gap() {
        let mut a = adapter();
        a.transport_mut().inject(feedback_wire_msg(1, 1));
        a.transport_mut().inject(feedback_wire_msg(2, 5)); // gap: 2,3,4 missed
        a.drain_feedback(1).unwrap();
        a.drain_feedback(2).unwrap();
        assert!(a.metrics().inbound_sequence_gaps > 0);
    }

    #[test]
    fn drain_feedback_collects_multiple_messages_across_payloads() {
        let mut a = adapter();
        a.transport_mut().inject(feedback_wire_msg(1, 1));
        a.transport_mut().inject(feedback_wire_msg(1, 2));
        let fb = a.drain_feedback(1).unwrap();
        assert_eq!(fb.message_count(), 2);
    }

    // ── IEngineAdapter trait impl ─────────────────────────────────────────────

    #[test]
    fn iengineadapter_apply_delta_delegates_to_send_delta() {
        let mut a = adapter();
        a.apply_delta(&empty_delta(1)).unwrap();
        assert!(a.transport().last_sent().unwrap().is_delta());
    }

    #[test]
    fn iengineadapter_apply_snapshot_delegates_to_send_snapshot() {
        let mut a = adapter();
        a.apply_snapshot(&test_snapshot(0)).unwrap();
        assert!(a.transport().last_sent().unwrap().is_snapshot());
    }

    #[test]
    fn iengineadapter_is_connected_delegates_to_transport() {
        let a = adapter();
        assert!(a.is_connected());
    }

    #[test]
    fn iengineadapter_engine_name_delegates_to_transport() {
        let a = adapter();
        assert_eq!(a.engine_name(), "MockEngine");
    }

    #[test]
    fn iengineadapter_send_event_delegates_correctly() {
        let mut a = adapter();
        a.send_event(&test_event()).unwrap();
        assert_eq!(a.metrics().events_sent, 1);
    }

    #[test]
    fn iengineadapter_receive_feedback_batch_delegates_correctly() {
        let mut a = adapter();
        a.transport_mut().inject(feedback_wire_msg(3, 1));
        let fb = a.receive_feedback_batch(3).unwrap();
        assert!(!fb.is_empty());
    }

    // ── Metrics ───────────────────────────────────────────────────────────────

    #[test]
    fn metrics_start_at_zero() {
        let a = adapter();
        let m = a.metrics();
        assert_eq!(m.deltas_sent, 0);
        assert_eq!(m.snapshots_sent, 0);
        assert_eq!(m.events_sent, 0);
        assert_eq!(m.feedback_payloads_received, 0);
        assert_eq!(m.inbound_sequence_gaps, 0);
    }

    #[test]
    fn metrics_accumulate_across_operations() {
        let mut a = adapter();
        a.send_delta(&empty_delta(1)).unwrap();
        a.send_delta(&empty_delta(2)).unwrap();
        a.send_snapshot(&test_snapshot(3)).unwrap();
        a.send_event_msg(&test_event()).unwrap();
        let m = a.metrics();
        assert_eq!(m.deltas_sent, 2);
        assert_eq!(m.snapshots_sent, 1);
        assert_eq!(m.events_sent, 1);
    }
}