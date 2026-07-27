//! XACE-side engine adapter facade.
//!
//! This module is the runtime-facing surface for live engine integration. It
//! converts canonical payloads into `WireMessage`s, enforces the adapter
//! authority boundary on inbound traffic, preserves sequence ordering, and
//! buffers messages so input and feedback drains cannot accidentally discard
//! each other.

use std::collections::VecDeque;

use serde_json::json;
use xace_core::contracts::interfaces::{IEngineAdapter, VisibilityQuery};
use xace_core::entity_metadata::Tick;
use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::events::event_struct::Event;
use xace_core::wire::delta_payload::DeltaPayload;
use xace_core::wire::feedback_payload::FeedbackPayload;
use xace_core::wire::message_type::MessageType;
use xace_core::wire::snapshot_payload::SnapshotPayload;
use xace_core::wire::wire_message::WireMessage;

use crate::adapter_contract::adapter_authority_enforcer::{
    AdapterAuthorityEnforcer, AuthorityClassification, AuthorityPolicy, EnforcerMetrics,
};
use crate::transport::sequence_tracker::SequenceTracker;

pub trait Transport: Send + Sync {
    fn send_message(&mut self, msg: &WireMessage) -> Result<(), XaceError>;
    fn send_batch(&mut self, messages: &[WireMessage]) -> Result<(), XaceError>;
    fn try_receive_messages(&mut self) -> Result<Vec<WireMessage>, XaceError>;
    fn is_connected(&self) -> bool;
    fn engine_name(&self) -> &str;
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct AdapterMetrics {
    pub deltas_sent: u64,
    pub snapshots_sent: u64,
    pub events_sent: u64,
    pub visibility_query_batches_sent: u64,
    pub visibility_queries_sent: u64,
    pub feedback_payloads_received: u64,
    pub feedback_messages_received: u64,
    pub input_packets_received: u64,
    pub inbound_sequence_gaps: u64,
    pub inbound_duplicates_or_old: u64,
    pub unexpected_messages_dropped: u64,
    pub malformed_inbound_payloads: u64,
    pub empty_feedback_ticks: u64,
}

pub struct EngineAdapterInterface<T: Transport> {
    transport: T,
    inbound_tracker: SequenceTracker,
    authority: AdapterAuthorityEnforcer,
    pending_inbound: VecDeque<WireMessage>,
    next_delta_sequence: u64,
    next_snapshot_sequence: u64,
    next_event_sequence: u64,
    next_control_sequence: u64,
    metrics: AdapterMetrics,
    schema_version: String,
    execution_plan_version: u32,
    world_id: String,
}

impl<T: Transport> EngineAdapterInterface<T> {
    pub fn new(
        transport: T,
        schema_version: impl Into<String>,
        execution_plan_version: u32,
        world_id: impl Into<String>,
        initial_delta_sequence_id: u64,
    ) -> Self {
        let schema_version = schema_version.into();
        let world_id = world_id.into();
        let policy = AuthorityPolicy::strict().with_expected_session(
            world_id.clone(),
            schema_version.clone(),
            execution_plan_version,
        );
        let mut authority = AdapterAuthorityEnforcer::with_policy(policy);
        authority.mark_handshake_complete();

        Self {
            transport,
            inbound_tracker: SequenceTracker::new(),
            authority,
            pending_inbound: VecDeque::new(),
            next_delta_sequence: initial_delta_sequence_id,
            next_snapshot_sequence: 1,
            next_event_sequence: 1,
            next_control_sequence: 1,
            metrics: AdapterMetrics::default(),
            schema_version,
            execution_plan_version,
            world_id,
        }
    }

    pub fn with_authority_policy(
        transport: T,
        schema_version: impl Into<String>,
        execution_plan_version: u32,
        world_id: impl Into<String>,
        initial_delta_sequence_id: u64,
        policy: AuthorityPolicy,
    ) -> Self {
        let mut adapter = Self::new(
            transport,
            schema_version,
            execution_plan_version,
            world_id,
            initial_delta_sequence_id,
        );
        adapter.authority = AdapterAuthorityEnforcer::with_policy(policy);
        adapter.authority.mark_handshake_complete();
        adapter
    }

    pub fn send_delta(&mut self, delta: &DeltaPayload) -> Result<(), XaceError> {
        delta
            .validate()
            .map_err(|detail| validation("send_delta", delta.tick, detail))?;
        let seq = self.next_delta_sequence;
        let msg = WireMessage::with_typed_payload(
            &self.world_id,
            &self.schema_version,
            self.execution_plan_version,
            delta.tick,
            seq,
            MessageType::Delta,
            delta,
        )
        .map_err(|err| fatal("send_delta", delta.tick, err.to_string()))?;

        self.transport.send_message(&msg)?;
        self.next_delta_sequence = self.next_delta_sequence.saturating_add(1);
        self.metrics.deltas_sent += 1;
        Ok(())
    }

    pub fn send_snapshot(&mut self, snapshot: &SnapshotPayload) -> Result<(), XaceError> {
        snapshot
            .validate()
            .map_err(|detail| validation("send_snapshot", snapshot.tick, detail))?;
        let seq = self.next_snapshot_sequence;
        let msg = WireMessage::with_typed_payload(
            &self.world_id,
            &self.schema_version,
            self.execution_plan_version,
            snapshot.tick,
            seq,
            MessageType::Snapshot,
            snapshot,
        )
        .map_err(|err| fatal("send_snapshot", snapshot.tick, err.to_string()))?;

        self.transport.send_message(&msg)?;
        self.next_snapshot_sequence = self.next_snapshot_sequence.saturating_add(1);
        self.metrics.snapshots_sent += 1;
        Ok(())
    }

    pub fn send_event_msg(&mut self, event: &Event) -> Result<(), XaceError> {
        let seq = self.next_event_sequence;
        let msg = WireMessage::with_typed_payload(
            &self.world_id,
            &self.schema_version,
            self.execution_plan_version,
            event.creation_tick,
            seq,
            MessageType::Event,
            event,
        )
        .map_err(|err| fatal("send_event_msg", event.creation_tick, err.to_string()))?;

        self.transport.send_message(&msg)?;
        self.next_event_sequence = self.next_event_sequence.saturating_add(1);
        self.metrics.events_sent += 1;
        Ok(())
    }

    pub fn send_visibility_query_batch(
        &mut self,
        queries: &[VisibilityQuery],
        tick: Tick,
    ) -> Result<(), XaceError> {
        if queries.is_empty() {
            return Ok(());
        }

        let payload = json!({
            "control_type": "VisibilityQueryBatch",
            "tick": tick,
            "queries": queries.iter().map(|query| {
                json!({
                    "observer_entity_id": query.observer_entity_id,
                    "target_entity_id": query.target_entity_id,
                    "max_distance": query.max_distance,
                })
            }).collect::<Vec<_>>()
        });
        let seq = self.next_control_sequence;
        let msg = WireMessage::with_typed_payload(
            &self.world_id,
            &self.schema_version,
            self.execution_plan_version,
            tick,
            seq,
            MessageType::Control,
            &payload,
        )
        .map_err(|err| fatal("send_visibility_query_batch", tick, err.to_string()))?;

        self.transport.send_message(&msg)?;
        self.next_control_sequence = self.next_control_sequence.saturating_add(1);
        self.metrics.visibility_query_batches_sent += 1;
        self.metrics.visibility_queries_sent += queries.len() as u64;
        Ok(())
    }

    pub fn drain_feedback(&mut self, tick: Tick) -> Result<FeedbackPayload, XaceError> {
        self.poll_transport()?;
        let mut combined = FeedbackPayload::empty(tick);
        let feedback_messages = self.take_pending_of_type(MessageType::Feedback);

        for msg in feedback_messages {
            if !self.sequence_allows_processing(&msg) {
                continue;
            }
            let mut payload: FeedbackPayload =
                serde_json::from_str(&msg.payload).map_err(|err| {
                    self.metrics.malformed_inbound_payloads += 1;
                    validation("drain_feedback", msg.tick, err.to_string())
                })?;
            payload.validate().map_err(|detail| {
                self.metrics.malformed_inbound_payloads += 1;
                validation("drain_feedback", msg.tick, detail)
            })?;
            payload.sort_in_place();
            self.metrics.feedback_payloads_received += 1;
            self.metrics.feedback_messages_received += payload.message_count() as u64;
            for feedback in payload.messages {
                combined.add_message(feedback);
            }
        }

        combined.sort_in_place();
        if combined.is_empty() {
            self.metrics.empty_feedback_ticks += 1;
        }
        Ok(combined)
    }

    pub fn drain_input(&mut self, _tick: Tick) -> Result<Vec<Vec<u8>>, XaceError> {
        self.poll_transport()?;
        let input_messages = self.take_pending_of_type(MessageType::Input);
        let mut payloads = Vec::with_capacity(input_messages.len());

        for msg in input_messages {
            if !self.sequence_allows_processing(&msg) {
                continue;
            }
            self.metrics.input_packets_received += 1;
            payloads.push(msg.payload.into_bytes());
        }
        Ok(payloads)
    }

    pub fn metrics(&self) -> &AdapterMetrics {
        &self.metrics
    }

    pub fn authority_metrics(&self) -> &EnforcerMetrics {
        self.authority.metrics()
    }

    pub fn inbound_tracker(&self) -> &SequenceTracker {
        &self.inbound_tracker
    }

    pub fn next_delta_sequence(&self) -> u64 {
        self.next_delta_sequence
    }

    pub fn next_snapshot_sequence(&self) -> u64 {
        self.next_snapshot_sequence
    }

    pub fn pending_inbound_count(&self) -> usize {
        self.pending_inbound.len()
    }

    pub fn transport(&self) -> &T {
        &self.transport
    }

    pub fn transport_mut(&mut self) -> &mut T {
        &mut self.transport
    }

    fn poll_transport(&mut self) -> Result<(), XaceError> {
        let messages = self.transport.try_receive_messages()?;
        for msg in messages {
            match self.authority.check(&msg)? {
                AuthorityClassification::Permitted => self.pending_inbound.push_back(msg),
                classification if classification.should_drop() => {
                    self.metrics.unexpected_messages_dropped += 1;
                }
                _ => {}
            }
        }
        Ok(())
    }

    fn take_pending_of_type(&mut self, message_type: MessageType) -> Vec<WireMessage> {
        let mut selected = Vec::new();
        let mut retained = VecDeque::with_capacity(self.pending_inbound.len());

        while let Some(msg) = self.pending_inbound.pop_front() {
            if msg.message_type == message_type {
                selected.push(msg);
            } else {
                retained.push_back(msg);
            }
        }
        self.pending_inbound = retained;
        selected
    }

    fn sequence_allows_processing(&mut self, msg: &WireMessage) -> bool {
        let result = self.inbound_tracker.check(msg);
        if result.is_gap() {
            self.metrics.inbound_sequence_gaps += 1;
        }
        if result.should_discard() {
            self.metrics.inbound_duplicates_or_old += 1;
            return false;
        }
        result.should_process()
    }
}

impl<T: Transport> IEngineAdapter for EngineAdapterInterface<T> {
    fn apply_delta(&mut self, delta: &DeltaPayload) -> Result<(), XaceError> {
        self.send_delta(delta)
    }

    fn apply_snapshot(&mut self, snapshot: &SnapshotPayload) -> Result<(), XaceError> {
        self.send_snapshot(snapshot)
    }

    fn collect_local_input(&mut self, tick: Tick) -> Result<Vec<u8>, XaceError> {
        Ok(self.drain_input(tick)?.into_iter().flatten().collect())
    }

    fn receive_feedback_batch(&mut self, tick: Tick) -> Result<FeedbackPayload, XaceError> {
        self.drain_feedback(tick)
    }

    fn send_visibility_queries(&mut self, queries: Vec<VisibilityQuery>) -> Result<(), XaceError> {
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

fn validation(operation: &'static str, tick: Tick, message: impl Into<String>) -> XaceError {
    XaceError::ValidationFailure {
        message: format!("EngineAdapterInterface: {}", message.into()),
        context: ErrorContext::new("EngineAdapterInterface", operation).with_tick(tick),
        rule_violated: "engine_adapter_contract".to_string(),
        failed_path: String::new(),
    }
}

fn fatal(operation: &'static str, tick: Tick, message: impl Into<String>) -> XaceError {
    XaceError::FatalError {
        message: format!("EngineAdapterInterface: {}", message.into()),
        context: ErrorContext::new("EngineAdapterInterface", operation).with_tick(tick),
        snapshot_recovery_possible: false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::VecDeque;
    use xace_core::events::event_type::EventType;
    use xace_core::runtime::phase_enum::PhaseEnum;
    use xace_core::wire::delta_payload::WireSpawnedEntity;
    use xace_core::wire::feedback_payload::{FeedbackMessage, FeedbackType};
    use xace_core::wire::snapshot_payload::SnapshotReason;

    struct MockTransport {
        sent: Vec<WireMessage>,
        inbound: VecDeque<WireMessage>,
    }

    impl MockTransport {
        fn new() -> Self {
            Self {
                sent: Vec::new(),
                inbound: VecDeque::new(),
            }
        }

        fn inject(&mut self, msg: WireMessage) {
            self.inbound.push_back(msg);
        }
    }

    impl Transport for MockTransport {
        fn send_message(&mut self, msg: &WireMessage) -> Result<(), XaceError> {
            self.sent.push(msg.clone());
            Ok(())
        }

        fn send_batch(&mut self, messages: &[WireMessage]) -> Result<(), XaceError> {
            self.sent.extend(messages.iter().cloned());
            Ok(())
        }

        fn try_receive_messages(&mut self) -> Result<Vec<WireMessage>, XaceError> {
            Ok(self.inbound.drain(..).collect())
        }

        fn is_connected(&self) -> bool {
            true
        }

        fn engine_name(&self) -> &str {
            "MockEngine"
        }
    }

    fn adapter() -> EngineAdapterInterface<MockTransport> {
        EngineAdapterInterface::new(MockTransport::new(), "0.1.0", 1, "default", 10)
    }

    fn delta(tick: u64) -> DeltaPayload {
        let mut delta = DeltaPayload::empty(tick, 1, "0.1.0");
        delta.add_spawn(WireSpawnedEntity::new(1, "actor_player"));
        delta
    }

    fn feedback_wire(tick: u64, seq: u64) -> WireMessage {
        let mut payload = FeedbackPayload::empty(tick);
        payload.add_message(FeedbackMessage::new(
            FeedbackType::AnimationStateUpdate,
            1,
            tick,
            "{}",
        ));
        WireMessage::feedback(
            "default",
            "0.1.0",
            1,
            tick,
            seq,
            serde_json::to_string(&payload).unwrap(),
        )
    }

    #[test]
    fn send_delta_uses_initial_sequence_and_increments_after_success() {
        let mut adapter = adapter();
        adapter.send_delta(&delta(1)).unwrap();
        assert_eq!(adapter.transport().sent[0].sequence_id, 10);
        assert_eq!(adapter.next_delta_sequence(), 11);
    }

    #[test]
    fn input_and_feedback_do_not_discard_each_other() {
        let mut adapter = adapter();
        adapter.transport_mut().inject(WireMessage::input(
            "default",
            "0.1.0",
            1,
            1,
            1,
            r#"{"a":1}"#,
        ));
        adapter.transport_mut().inject(feedback_wire(1, 1));

        let feedback = adapter.drain_feedback(1).unwrap();
        assert_eq!(feedback.message_count(), 1);
        assert_eq!(adapter.pending_inbound_count(), 1);

        let input = adapter.drain_input(1).unwrap();
        assert_eq!(input.len(), 1);
    }

    #[test]
    fn authority_violation_is_fatal() {
        let mut adapter = adapter();
        adapter
            .transport_mut()
            .inject(WireMessage::delta("default", "0.1.0", 1, 1, 1, "{}"));
        assert!(adapter.drain_feedback(1).is_err());
        assert_eq!(adapter.authority_metrics().violation_count, 1);
    }

    #[test]
    fn visibility_query_uses_control_message() {
        let mut adapter = adapter();
        adapter
            .send_visibility_query_batch(
                &[VisibilityQuery {
                    observer_entity_id: 1,
                    target_entity_id: 2,
                    max_distance: 10.0,
                }],
                5,
            )
            .unwrap();
        assert!(adapter.transport().sent[0].is_control());
    }

    #[test]
    fn trait_methods_delegate() {
        let mut adapter = adapter();
        adapter.apply_delta(&delta(1)).unwrap();
        let snapshot = SnapshotPayload::new(
            1,
            "0.1.0",
            1,
            "cgs",
            "world",
            0,
            SnapshotReason::InitialConnection,
        );
        adapter.apply_snapshot(&snapshot).unwrap();
        adapter
            .send_event(&Event::broadcast(
                1,
                EventType::EntitySpawned,
                1,
                PhaseEnum::Simulation,
            ))
            .unwrap();
        assert_eq!(adapter.metrics().deltas_sent, 1);
        assert_eq!(adapter.metrics().snapshots_sent, 1);
        assert_eq!(adapter.metrics().events_sent, 1);
    }
}
