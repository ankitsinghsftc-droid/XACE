//! Runtime-side engine bridge.
//!
//! The bridge performs the engine handshake, emits authoritative snapshots,
//! drains inbound input packets, and keeps transport errors isolated from the
//! deterministic tick loop.

use std::collections::VecDeque;
use std::io::{BufReader, Read};
use std::net::TcpStream;
use std::time::{Duration, Instant};

use anyhow::Result;

use crate::component_tables::component_table_store::ComponentTableStore;
use crate::engine_protocol::{
    parse_inbound_message, write_message, AdapterSideEffectRollback,
    DisconnectMessage, EnginePlaybackCommand, EntityState, HandshakeAck, InboundMessage,
    InputTickRequest, TickSnapshot, DEFAULT_TICK_RATE, MAX_HANDSHAKE_BYTES, MAX_MESSAGE_BYTES,
};
use crate::entity_store::entity_store::EntityStore;
use crate::live_session::{LiveSessionController, SessionAdmission};
use xace_engine_feedback::feedback_buffer::{FeedbackBuffer, FeedbackBufferMetrics};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EngineBridgeConfig {
    pub world_bindings: std::collections::BTreeMap<String, String>,
    pub tick_rate: u32,
    pub nonblocking_read_timeout: Duration,
    pub max_queued_inputs: usize,
    pub reject_cgs_hash_mismatch: bool,
}

impl Default for EngineBridgeConfig {
    fn default() -> Self {
        Self {
            world_bindings: Default::default(),
            tick_rate: DEFAULT_TICK_RATE,
            nonblocking_read_timeout: Duration::from_millis(16),
            max_queued_inputs: 4096,
            reject_cgs_hash_mismatch: true,
        }
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct EngineBridgeStats {
    pub snapshots_sent: u64,
    pub bytes_sent: u64,
    pub input_packets_received: u64,
    pub feedback_payloads_received: u64,
    pub feedback_messages_received: u64,
    pub malformed_messages: u64,
    pub dropped_inputs: u64,
    pub queued_inputs: usize,
    pub queued_feedback: usize,
}

pub struct EngineBridge {
    writer: TcpStream,
    reader: BufReader<TcpStream>,
    config: EngineBridgeConfig,
    session_id: String,
    start: Instant,
    cgs_hash: String,
    schema_ver: String,
    adapter_type: String,
    connected: bool,
    inbound_inputs: VecDeque<xace_network_core::input::InputPacket>,
    inbound_frame_bytes: Vec<u8>,
    last_requested_tick: Option<u64>,
    feedback_buffer: FeedbackBuffer,
    stats: EngineBridgeStats,
    admission: Option<SessionAdmission>,
    projection: Option<crate::session_projection::ProjectionStamp>,
    projection_ack: bool,
    projection_ready: bool,
    projection_refresh: bool,
    projection_sent: Instant,
    projection_sequence: u64,
}

impl EngineBridge {
    pub fn handshake(
        writer: TcpStream,
        reader: BufReader<TcpStream>,
        session_id: String,
        cgs_hash: String,
        schema_ver: String,
        entity_store: &EntityStore,
        table_store: &ComponentTableStore,
        feedback_buffer: FeedbackBuffer,
    ) -> Result<Self> {
        Self::handshake_with_config(
            writer,
            reader,
            session_id,
            cgs_hash,
            schema_ver,
            entity_store,
            table_store,
            feedback_buffer,
            EngineBridgeConfig::default(),
        )
    }

    pub fn handshake_with_config(
        writer: TcpStream,
        reader: BufReader<TcpStream>,
        session_id: String,
        cgs_hash: String,
        schema_ver: String,
        entity_store: &EntityStore,
        table_store: &ComponentTableStore,
        feedback_buffer: FeedbackBuffer,
        config: EngineBridgeConfig,
    ) -> Result<Self> {
        Self::handshake_with_session(
            writer,
            reader,
            session_id,
            cgs_hash,
            schema_ver,
            entity_store,
            table_store,
            feedback_buffer,
            config,
            None,
            0,
        )
    }

    #[allow(clippy::too_many_arguments)]
    pub fn handshake_with_session(
        writer: TcpStream,
        reader: BufReader<TcpStream>,
        session_id: String,
        cgs_hash: String,
        schema_ver: String,
        entity_store: &EntityStore,
        table_store: &ComponentTableStore,
        feedback_buffer: FeedbackBuffer,
        config: EngineBridgeConfig,
        mut session: Option<&mut LiveSessionController>,
        initial_tick: u64,
    ) -> Result<Self> {
        let mut bridge = Self {
            writer,
            reader,
            config,
            session_id,
            start: Instant::now(),
            cgs_hash,
            schema_ver,
            adapter_type: String::new(),
            connected: false,
            inbound_inputs: VecDeque::new(),
            inbound_frame_bytes: Vec::new(),
            last_requested_tick: None,
            feedback_buffer,
            admission: None,
            projection: None,
            projection_ack: false,
            projection_ready: false,
            projection_refresh: false,
            projection_sent: Instant::now(),
            projection_sequence: 0,
            stats: EngineBridgeStats {
                snapshots_sent: 0,
                bytes_sent: 0,
                input_packets_received: 0,
                feedback_payloads_received: 0,
                feedback_messages_received: 0,
                malformed_messages: 0,
                dropped_inputs: 0,
                queued_inputs: 0,
                queued_feedback: 0,
            },
        };

        let raw = match read_handshake_with_deadline(&mut bridge.reader, Duration::from_millis(1500)) {
            Ok(Some(raw)) => raw,
            Ok(None) => {
                if let Some(controller)=session.as_deref_mut() {
                    controller.record_rejection("engine disconnected before handshake")?;
                }
                return Err(anyhow::anyhow!("engine disconnected before handshake"));
            }
            Err(err) => {
                if let Some(controller)=session.as_deref_mut() {
                    controller.record_rejection(&format!("handshake read failed: {}", err))?;
                }
                return Err(err.into());
            }
        };
        let handshake = match parse_inbound_message(&raw) {
            Ok(InboundMessage::Handshake(handshake)) => handshake,
            Ok(_) => {
                if let Some(controller) = session.as_deref_mut() {
                    controller.record_rejection("expected handshake as first message")?;
                }
                bridge.send_handshake_reject("expected handshake as first message")?;
                return Err(anyhow::anyhow!("expected handshake as first message"));
            }
            Err(err) => {
                if let Some(controller) = session.as_deref_mut() {
                    controller.record_rejection(&format!("invalid handshake: {}", err))?;
                }
                bridge.send_handshake_reject(format!("invalid handshake: {}", err))?;
                return Err(anyhow::anyhow!("invalid handshake: {}", err));
            }
        };

        let validation_hash = if bridge.config.reject_cgs_hash_mismatch {
            bridge.cgs_hash.as_str()
        } else {
            ""
        };
        if let Err(err) = handshake.validate(validation_hash) {
            if let Some(controller) = session.as_deref_mut() {
                controller.record_rejection(&err.to_string())?;
            }
            bridge.send_handshake_reject(err.to_string())?;
            return Err(anyhow::anyhow!("handshake rejected: {}", err));
        }

        bridge.reader.get_ref().set_nonblocking(true)?;

        if let Some(controller) = session.as_deref_mut() {
            let parsed_offer: anyhow::Result<xace_core::wire::session_contract::SessionOffer> =
                if handshake.session_offer_json.is_empty() {
                    handshake
                        .session_offer
                        .clone()
                        .ok_or_else(|| anyhow::anyhow!("live session offer missing"))
                } else {
                    serde_json::from_str(&handshake.session_offer_json).map_err(anyhow::Error::from)
                };
            let result = parsed_offer
                .as_ref()
                .map_err(|err| anyhow::anyhow!("{}", err))
                .and_then(|offer| {
                    if normalise_adapter_type(&handshake.engine_name)
                        != format!("{:?}", offer.client.adapter.engine).to_ascii_lowercase()
                        || handshake.adapter_version
                            != String::from(offer.client.adapter.adapter_version.clone())
                    {
                        anyhow::bail!("adapter claim differs from handshake");
                    }
                    controller.admit(
                        offer,
                        &handshake.session_credential,
                        handshake.session_peer_id,
                        table_store,
                    )
                });
            match result {
                Ok(admission) => {
                    bridge.session_id = admission.contract.epoch.session_id.to_string();
                    bridge.admission = Some(admission);
                }
                Err(err) => {
                    controller.record_rejection(&err.to_string())?;
                    bridge.send_handshake_reject(err.to_string())?;
                    return Err(err);
                }
            }
        }

        log::info!(
            "Handshake from {} {} (adapter {})",
            handshake.engine_name,
            handshake.engine_version,
            handshake.adapter_version
        );
        bridge.adapter_type = normalise_adapter_type(&handshake.engine_name);

        let mut ack = HandshakeAck::accepted(
            bridge.session_id.clone(),
            bridge.cgs_hash.clone(),
            bridge.schema_ver.clone(),
            build_entity_states(entity_store, table_store),
        );
        if let Some(admission) = &bridge.admission {
            ack.authority_incarnation = admission.contract.epoch.authority_incarnation.to_string();
            ack.ruleset_epoch = admission.contract.epoch.ruleset_epoch;
            ack.assigned_peer_id = admission.peer_id;
            ack.assigned_player_id = admission.player_id;
        }
        ack.tick_rate = bridge.config.tick_rate;
        ack.world_bindings = bridge.config.world_bindings.clone();
        ack.runtime_capabilities.extend([
            "xace.world_bindings.v1".into(),
            "xace.presentation_event.v1".into(),
        ]);
        let mut ack = serde_json::to_value(ack)?;
        if let Some(admission) = &bridge.admission {
            ack["reconnect_credential"] = admission.reconnect_credential.clone().into();
            bridge.attach_projection(&mut ack, initial_tick, entity_store, table_store)?;
        }
        match write_message(&mut bridge.writer, &ack) {
            Ok(bytes) => bridge.stats.bytes_sent += bytes as u64,
            Err(err) => {
                if let (Some(controller), Some(admission)) =
                    (session.as_deref_mut(), bridge.admission.as_ref())
                {
                    controller.disconnect(admission.peer_id, "ack_delivery_failed")?;
                }
                return Err(err.into());
            }
        }

        bridge.connected = true;

        log::info!("Engine bridge handshake complete");
        Ok(bridge)
    }

    pub fn send_tick(
        &mut self,
        tick: u64,
        entity_store: &EntityStore,
        table_store: &ComponentTableStore,
        spawned_ids: Vec<u64>,
        destroyed_ids: Vec<u64>,
        playback_commands: Vec<EnginePlaybackCommand>,
    ) -> bool {
        self.send_tick_with_events(
            tick,
            entity_store,
            table_store,
            spawned_ids,
            destroyed_ids,
            playback_commands,
            Vec::new(),
        )
    }

    pub fn send_tick_with_events(
        &mut self,
        tick: u64,
        entity_store: &EntityStore,
        table_store: &ComponentTableStore,
        spawned_ids: Vec<u64>,
        destroyed_ids: Vec<u64>,
        playback_commands: Vec<EnginePlaybackCommand>,
        events: Vec<crate::engine_protocol::GameEvent>,
    ) -> bool {
        if !self.connected {
            return false;
        }

        // A syncing peer retains one full baseline, never an unbounded catch-up queue.
        if self.admission.is_some() && !self.projection_ready { return true; }
        let mut snapshot = TickSnapshot::new(
            tick,
            self.start.elapsed().as_millis() as u64,
            build_entity_states(entity_store, table_store),
            spawned_ids,
            destroyed_ids,
            events,
        );
        snapshot.playback_commands = playback_commands;

        let mut snapshot = match serde_json::to_value(snapshot) { Ok(v) => v, Err(_) => return false };
        if self.admission.is_some() {
            if self.attach_projection(&mut snapshot, tick.saturating_add(1), entity_store, table_store).is_err() {
                self.connected = false; return false;
            }
        }
        match write_message(&mut self.writer, &snapshot) {
            Ok(bytes) => {
                self.stats.snapshots_sent = self.stats.snapshots_sent.saturating_add(1);
                self.stats.bytes_sent = self.stats.bytes_sent.saturating_add(bytes as u64);
                // Next input is requested only after this projection is verified.
                self.drain_inbound();
                true
            }
            Err(err) => {
                log::warn!("Engine connection lost at tick {}: {}", tick, err);
                self.connected = false;
                false
            }
        }
    }

    pub fn send_adapter_side_effect_rollback(
        &mut self,
        rollback: &AdapterSideEffectRollback,
    ) -> bool {
        if !self.connected {
            return false;
        }
        if let Err(err) = rollback.validate() {
            log::warn!(
                "Refusing to send invalid adapter side-effect rollback '{}': {}",
                rollback.rollback_id,
                err
            );
            return false;
        }
        match write_message(&mut self.writer, rollback) {
            Ok(bytes) => {
                self.stats.bytes_sent = self.stats.bytes_sent.saturating_add(bytes as u64);
                self.drain_inbound();
                true
            }
            Err(err) => {
                log::warn!(
                    "Engine connection lost during adapter side-effect rollback '{}': {}",
                    rollback.rollback_id,
                    err
                );
                self.connected = false;
                false
            }
        }
    }
    pub fn disconnect(&mut self, reason: &str) {
        if !self.connected {
            return;
        }
        match write_message(&mut self.writer, &DisconnectMessage::new(reason)) {
            Ok(bytes) => self.stats.bytes_sent = self.stats.bytes_sent.saturating_add(bytes as u64),
            Err(err) => log::debug!("Failed to send engine disconnect: {}", err),
        }
        self.connected = false;
    }

    pub fn is_connected(&self) -> bool {
        self.connected
    }

    pub fn admitted_peer_id(&self) -> Option<u64> {
        self.admission.as_ref().map(|a| a.peer_id)
    }

    pub fn admitted_player_id(&self) -> Option<u64> {
        self.admission.as_ref().map(|a| a.player_id)
    }

    pub fn adapter_type(&self) -> &str {
        if self.adapter_type.is_empty() {
            "headless"
        } else {
            &self.adapter_type
        }
    }

    pub fn take_input_packets(&mut self) -> Vec<xace_network_core::input::InputPacket> {
        let packets = self.inbound_inputs.drain(..).collect::<Vec<_>>();
        self.stats.queued_inputs = 0;
        packets
    }

    pub fn pump_inbound(&mut self) {
        if self.connected {
            self.drain_inbound();
        }
    }

    pub fn stats(&self) -> EngineBridgeStats {
        EngineBridgeStats {
            queued_inputs: self.inbound_inputs.len(),
            queued_feedback: self.feedback_buffer.pending_count(),
            ..self.stats
        }
    }

    pub fn feedback_buffer_metrics(&self) -> FeedbackBufferMetrics {
        self.feedback_buffer.metrics()
    }

    fn send_handshake_reject(&mut self, reason: impl Into<String>) -> Result<()> {
        let ack = HandshakeAck::rejected(reason.into());
        let bytes = write_message(&mut self.writer, &ack)?;
        self.stats.bytes_sent = self.stats.bytes_sent.saturating_add(bytes as u64);
        Ok(())
    }

    fn attach_projection(&mut self, message: &mut serde_json::Value, next_tick: u64,
        entities: &EntityStore, tables: &ComponentTableStore) -> Result<()> {
        self.projection_sequence = self.projection_sequence.checked_add(1)
            .ok_or_else(|| anyhow::anyhow!("projection sequence exhausted"))?;
        let (stamp, projection) = crate::session_projection::ProjectionStamp::build(
            self.admission.as_ref().expect("live admission"), self.projection_sequence,
            next_tick, &build_entity_states(entities, tables))?;
        message["sync_json"] = serde_json::to_string(&stamp)?.into();
        message["sync"] = serde_json::to_value(&stamp)?;
        message["projection_json"] = projection.into();
        self.projection = Some(stamp);
        self.projection_ack = false;
        self.projection_sent = Instant::now();
        Ok(())
    }

    fn handle_projection_control(&mut self, raw: &[u8]) {
        use crate::session_projection::ProjectionControl;
        match serde_json::from_slice::<ProjectionControl>(raw) {
            Ok(ProjectionControl::BaselineAck { stamp_json }) => {
                let stamp = serde_json::from_str::<crate::session_projection::ProjectionStamp>(&stamp_json).ok();
                if stamp.is_some() && self.projection == stamp {
                    self.projection_ack = true;
                } else {
                    self.stats.malformed_messages += 1;
                }
            }
            Ok(ProjectionControl::ResyncRequest { connection_generation }) => {
                if self.admission.as_ref().is_some_and(|a| a.generation == connection_generation) {
                    self.projection_ready = false;
                    self.projection_refresh = true;
                    self.projection_ack = false;
                    self.inbound_inputs.clear();
                    self.last_requested_tick = None;
                }
            }
            Err(_) => self.stats.malformed_messages += 1,
        }
    }

    /// Called only at the authoritative tick boundary, before input collection.
    pub fn synchronize_projection(&mut self, tick: u64, entities: &EntityStore,
        tables: &ComponentTableStore) -> Result<bool> {
        if self.admission.is_none() { return Ok(false); }
        if !self.connected { return Ok(false); }
        if self.projection_sent.elapsed() > Duration::from_secs(5) && !self.projection_ack {
            self.disconnect("baseline_ack_timeout");
            return Ok(false);
        }
        if self.projection_refresh || (self.projection_ack && self.projection.as_ref().is_some_and(|s| s.next_tick != tick)) {
            self.projection_ready = false;
            self.projection_refresh = false;
            self.last_requested_tick = None;
            let mut message = serde_json::json!({"msg_type":"session_baseline","protocol_version":1});
            self.attach_projection(&mut message, tick, entities, tables)?;
            if write_message(&mut self.writer, &message).is_err() { self.connected = false; }
        } else if self.projection_ack {
            if !self.projection_ready {
                let admission = self.admission.as_ref().unwrap();
                // Full current projection means no historical delta backlog is necessary.
                let mut catchup = xace_network_core::synchronisation::LateJoinHandler::new();
                catchup.plan_for_peer(admission.peer_id, tick, tick)?;
                catchup.mark_snapshot_queued(admission.peer_id)?;
                catchup.consume_batch(admission.peer_id)?;
                admission.log.append(&serde_json::json!({"schema":"xace.session_record.v1",
                    "kind":"baseline_verified","peer_id":admission.peer_id,"stamp":self.projection}))?;
            }
            self.projection_ready = true;
            self.send_input_request(tick);
        }
        Ok(self.connected && self.projection_ready)
    }

    pub fn send_input_request(&mut self, tick: u64) -> bool {
        if !self.connected || self.admission.is_none() { return false; }
        if self.last_requested_tick == Some(tick) { return true; }
        let request = InputTickRequest::new(tick);
        match write_message(&mut self.writer, &request) {
            Ok(bytes) => {
                self.stats.bytes_sent = self.stats.bytes_sent.saturating_add(bytes as u64);
                self.last_requested_tick = Some(tick);
                true
            }
            Err(err) => {
                log::warn!("Input request delivery failed at tick {}: {}", tick, err);
                self.connected = false;
                false
            }
        }
    }

    fn drain_inbound(&mut self) {
        // A partial frame survives a socket WouldBlock and is completed on a later pump.
        // Reading and parsing have fixed per-pump budgets so one client cannot monopolize a tick.
        let mut read_budget = 64 * 1024;
        while read_budget > 0 {
            let mut chunk = [0_u8; 4096];
            let size = chunk.len().min(read_budget);
            match self.reader.read(&mut chunk[..size]) {
                Ok(0) => { self.connected = false; break; }
                Ok(count) => {
                    read_budget -= count;
                    self.inbound_frame_bytes.extend_from_slice(&chunk[..count]);
                    if self.inbound_frame_bytes.len() > MAX_MESSAGE_BYTES + 4 {
                        log::warn!("Inbound frame buffer exceeded protocol maximum");
                        self.connected = false;
                        break;
                    }
                }
                Err(err) if err.kind() == std::io::ErrorKind::WouldBlock
                    || err.kind() == std::io::ErrorKind::TimedOut => break,
                Err(err) => {
                    log::warn!("Inbound engine read error: {}", err);
                    self.connected = false;
                    break;
                }
            }
        }
        for _ in 0..64 {
            if self.inbound_frame_bytes.len() < 4 { break; }
            let len = u32::from_le_bytes(self.inbound_frame_bytes[..4].try_into().unwrap()) as usize;
            if len == 0 || len > MAX_MESSAGE_BYTES {
                self.stats.malformed_messages = self.stats.malformed_messages.saturating_add(1);
                self.connected = false;
                break;
            }
            if self.inbound_frame_bytes.len() < len + 4 { break; }
            let raw = self.inbound_frame_bytes[4..len + 4].to_vec();
            self.inbound_frame_bytes.drain(..len + 4);
            if let Ok(value) = serde_json::from_slice::<serde_json::Value>(&raw) {
                if matches!(value["msg_type"].as_str(), Some("baseline_ack" | "resync_request")) {
                    self.handle_projection_control(&raw);
                    continue;
                }
            }
            match parse_inbound_message(&raw) {
                Ok(InboundMessage::InputPacket(packet)) => self.queue_input(packet),
                Ok(InboundMessage::FeedbackPayload(payload)) => self.queue_feedback(payload),
                Ok(InboundMessage::Handshake(_)) => {
                    self.stats.malformed_messages = self.stats.malformed_messages.saturating_add(1);
                }
                Err(err) => {
                    self.stats.malformed_messages = self.stats.malformed_messages.saturating_add(1);
                    log::warn!("Malformed inbound engine message: {}", err);
                }
            }
        }
    }

    fn queue_feedback(&mut self, payload: xace_core::wire::feedback_payload::FeedbackPayload) {
        if self.admission.is_some() {
            self.stats.malformed_messages = self.stats.malformed_messages.saturating_add(1);
            log::warn!("Rejected gameplay feedback from live presentation client");
            return;
        }
        let message_count = payload.message_count();
        match self.feedback_buffer.append_payload(payload) {
            Ok(()) => {
                self.stats.feedback_payloads_received =
                    self.stats.feedback_payloads_received.saturating_add(1);
                self.stats.feedback_messages_received = self
                    .stats
                    .feedback_messages_received
                    .saturating_add(message_count as u64);
                self.stats.queued_feedback = self.feedback_buffer.pending_count();
            }
            Err(err) => {
                self.stats.malformed_messages = self.stats.malformed_messages.saturating_add(1);
                log::warn!("Rejected inbound feedback payload: {}", err);
            }
        }
    }

    fn queue_input(&mut self, packet: crate::engine_protocol::InputPacket) {
        if self.admission.is_some() && (!self.projection_ready || !self.projection_ack) {
            self.stats.dropped_inputs += 1;
            return;
        }
        if let Some(admission) = &self.admission {
            if packet.peer_id != admission.peer_id || (packet.player_id != admission.player_id) {
                self.stats.dropped_inputs = self.stats.dropped_inputs.saturating_add(1);
                return;
            }
        }
        match xace_network_core::input::InputPacket::try_from(packet.clone()) {
            Ok(converted) => {
                if let Some(admission) = &self.admission {
                    if let Err(err) = admission.log.append(&serde_json::json!({
                        "schema":"xace.session_record.v1","kind":"input",
                        "session_id":admission.contract.epoch.session_id,
                        "authority_incarnation":admission.contract.epoch.authority_incarnation,
                        "ruleset_epoch":admission.contract.epoch.ruleset_epoch,
                        "peer_id":admission.peer_id,"player_id":admission.player_id,
                        "packet":packet
                    })) {
                        log::error!("live input log failed: {}", err);
                        self.connected = false;
                        self.stats.dropped_inputs = self.stats.dropped_inputs.saturating_add(1);
                        return;
                    }
                }
                if self.inbound_inputs.len() >= self.config.max_queued_inputs {
                    self.stats.dropped_inputs = self.stats.dropped_inputs.saturating_add(1);
                    log::warn!("Rejected input: per-connection queue full");
                    return;
                }
                self.stats.input_packets_received =
                    self.stats.input_packets_received.saturating_add(1);
                self.inbound_inputs.push_back(converted);
                self.stats.queued_inputs = self.inbound_inputs.len();
            }
            Err(err) => {
                self.stats.malformed_messages = self.stats.malformed_messages.saturating_add(1);
                log::warn!("Rejected inbound input packet: {}", err);
            }
        }
    }
}

fn normalise_adapter_type(engine_name: &str) -> String {
    let lower = engine_name.to_ascii_lowercase();
    if lower.contains("godot") {
        "godot".to_string()
    } else if lower.contains("unity") {
        "unity".to_string()
    } else if lower.contains("unreal") {
        "unreal".to_string()
    } else if lower.contains("webgl") || lower.contains("browser") {
        "webgl".to_string()
    } else if lower.trim().is_empty() {
        "headless".to_string()
    } else {
        lower
            .chars()
            .filter(|ch| ch.is_ascii_alphanumeric() || *ch == '_' || *ch == '-')
            .take(32)
            .collect::<String>()
    }
}

pub fn build_entity_states(
    entity_store: &EntityStore,
    table_store: &ComponentTableStore,
) -> Vec<EntityState> {
    let alive = entity_store.get_all_alive();
    let mut states = Vec::with_capacity(alive.len());

    for &entity_id in &alive {
        let actor_id = table_store
            .get_component(entity_id, crate::cgs_loader::type_ids::IDENTITY)
            .and_then(|json| serde_json::from_str::<serde_json::Value>(json).ok())
            .and_then(|value| {
                value
                    .get("name")
                    .and_then(|name| name.as_str())
                    .map(str::to_string)
            })
            .unwrap_or_default();

        let mut components = std::collections::BTreeMap::new();
        for (type_id, table) in table_store.all_tables() {
            if let Some(json) = table.get(entity_id) {
                components.insert(type_id, json.to_string());
            }
        }

        states.push(EntityState {
            id: entity_id,
            actor_id,
            components,
        });
    }

    states
}

fn read_handshake_with_deadline(
    reader: &mut BufReader<TcpStream>,
    limit: Duration,
) -> std::io::Result<Option<Vec<u8>>> {
    reader.get_ref().set_nonblocking(true)?;
    let deadline = Instant::now() + limit;
    let mut header = [0_u8; 4];
    let mut got = 0;
    while got < header.len() {
        if Instant::now() >= deadline {
            return Err(std::io::Error::new(std::io::ErrorKind::TimedOut, "handshake deadline exceeded"));
        }
        match reader.read(&mut header[got..]) {
            Ok(0) => return Ok(None),
            Ok(count) => got += count,
            Err(err) if err.kind() == std::io::ErrorKind::WouldBlock => std::thread::sleep(Duration::from_millis(2)),
            Err(err) => return Err(err),
        }
    }
    let len = u32::from_le_bytes(header) as usize;
    if len == 0 || len > MAX_HANDSHAKE_BYTES {
        return Err(std::io::Error::new(std::io::ErrorKind::InvalidData, "invalid handshake frame length"));
    }
    let mut body = vec![0_u8; len];
    got = 0;
    while got < len {
        if Instant::now() >= deadline {
            return Err(std::io::Error::new(std::io::ErrorKind::TimedOut, "handshake deadline exceeded"));
        }
        match reader.read(&mut body[got..]) {
            Ok(0) => return Ok(None),
            Ok(count) => got += count,
            Err(err) if err.kind() == std::io::ErrorKind::WouldBlock => std::thread::sleep(Duration::from_millis(2)),
            Err(err) => return Err(err),
        }
    }
    Ok(Some(body))
}
