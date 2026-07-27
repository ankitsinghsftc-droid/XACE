//! Runtime-side engine bridge.
//!
//! The bridge performs the engine handshake, emits authoritative snapshots,
//! drains inbound input packets, and keeps transport errors isolated from the
//! deterministic tick loop.

use std::collections::VecDeque;
use std::io::BufReader;
use std::net::TcpStream;
use std::time::{Duration, Instant};

use anyhow::Result;

use crate::component_tables::component_table_store::ComponentTableStore;
use crate::engine_protocol::{
    parse_inbound_message, read_message, write_message, DisconnectMessage, EnginePlaybackCommand,
    EntityState, HandshakeAck, InboundMessage, TickSnapshot, DEFAULT_TICK_RATE,
};
use crate::entity_store::entity_store::EntityStore;
use xace_engine_feedback::feedback_buffer::{FeedbackBuffer, FeedbackBufferMetrics};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EngineBridgeConfig {
    pub tick_rate: u32,
    pub nonblocking_read_timeout: Duration,
    pub max_queued_inputs: usize,
    pub reject_cgs_hash_mismatch: bool,
}

impl Default for EngineBridgeConfig {
    fn default() -> Self {
        Self {
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
    feedback_buffer: FeedbackBuffer,
    stats: EngineBridgeStats,
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
            feedback_buffer,
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

        let raw = read_message(&mut bridge.reader)?
            .ok_or_else(|| anyhow::anyhow!("engine disconnected before handshake"))?;
        let handshake = match parse_inbound_message(&raw) {
            Ok(InboundMessage::Handshake(handshake)) => handshake,
            Ok(_) => {
                bridge.send_handshake_reject("expected handshake as first message")?;
                return Err(anyhow::anyhow!("expected handshake as first message"));
            }
            Err(err) => {
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
            bridge.send_handshake_reject(err.to_string())?;
            return Err(anyhow::anyhow!("handshake rejected: {}", err));
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
        ack.tick_rate = bridge.config.tick_rate;
        bridge.stats.bytes_sent += write_message(&mut bridge.writer, &ack)? as u64;

        bridge.connected = true;
        bridge
            .reader
            .get_ref()
            .set_read_timeout(Some(bridge.config.nonblocking_read_timeout))?;
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
        if !self.connected {
            return false;
        }

        let mut snapshot = TickSnapshot::new(
            tick,
            self.start.elapsed().as_millis() as u64,
            build_entity_states(entity_store, table_store),
            spawned_ids,
            destroyed_ids,
            Vec::new(),
        );
        snapshot.playback_commands = playback_commands;

        match write_message(&mut self.writer, &snapshot) {
            Ok(bytes) => {
                self.stats.snapshots_sent = self.stats.snapshots_sent.saturating_add(1);
                self.stats.bytes_sent = self.stats.bytes_sent.saturating_add(bytes as u64);
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

    fn drain_inbound(&mut self) {
        loop {
            match read_message(&mut self.reader) {
                Ok(Some(raw)) => match parse_inbound_message(&raw) {
                    Ok(InboundMessage::InputPacket(packet)) => self.queue_input(packet),
                    Ok(InboundMessage::FeedbackPayload(payload)) => self.queue_feedback(payload),
                    Ok(InboundMessage::Handshake(_)) => {
                        log::debug!("Ignoring duplicate engine handshake after connection is live");
                    }
                    Err(err) => {
                        self.stats.malformed_messages =
                            self.stats.malformed_messages.saturating_add(1);
                        log::warn!("Malformed inbound engine message: {}", err);
                    }
                },
                Ok(None) => {
                    log::info!("Engine disconnected cleanly");
                    self.connected = false;
                    break;
                }
                Err(err)
                    if err.kind() == std::io::ErrorKind::WouldBlock
                        || err.kind() == std::io::ErrorKind::TimedOut =>
                {
                    break;
                }
                Err(err) => {
                    log::warn!("Inbound engine read error: {}", err);
                    self.connected = false;
                    break;
                }
            }
        }
    }

    fn queue_feedback(&mut self, payload: xace_core::wire::feedback_payload::FeedbackPayload) {
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
        match xace_network_core::input::InputPacket::try_from(packet) {
            Ok(packet) => {
                if self.inbound_inputs.len() >= self.config.max_queued_inputs {
                    self.inbound_inputs.pop_front();
                    self.stats.dropped_inputs = self.stats.dropped_inputs.saturating_add(1);
                }
                self.stats.input_packets_received =
                    self.stats.input_packets_received.saturating_add(1);
                self.inbound_inputs.push_back(packet);
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
