//! Local TCP control server for builder-driven runtime lifecycle commands.

use std::io::BufReader;
use std::net::{IpAddr, Ipv4Addr, SocketAddr, TcpListener, TcpStream};
use std::sync::mpsc::{self, Receiver, Sender};
use std::thread::{self, JoinHandle};
use std::time::Duration;

use anyhow::Result;

use crate::control_protocol::{
    parse_control_request, read_control_message, write_control_message, RuntimeControlInbound,
    RuntimeControlStatus,
};

#[derive(Debug)]
pub struct RuntimeControlRequest {
    pub message: RuntimeControlInbound,
    pub response_tx: Sender<serde_json::Value>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeControlServerConfig {
    pub bind_addr: SocketAddr,
    pub response_timeout: Duration,
}

impl RuntimeControlServerConfig {
    pub fn localhost(port: u16) -> Self {
        Self {
            bind_addr: SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), port),
            response_timeout: Duration::from_secs(5),
        }
    }
}

pub fn start_runtime_control_server(
    config: RuntimeControlServerConfig,
    request_tx: Sender<RuntimeControlRequest>,
) -> Result<JoinHandle<()>> {
    let listener = TcpListener::bind(config.bind_addr).map_err(|err| {
        anyhow::anyhow!("cannot bind runtime control {}: {}", config.bind_addr, err)
    })?;
    let local_addr = listener.local_addr()?;
    log::info!("Runtime control socket listening on {}", local_addr);

    let handle = thread::Builder::new()
        .name("xace-runtime-control".to_string())
        .spawn(move || accept_loop(listener, request_tx, config.response_timeout))?;
    Ok(handle)
}

fn accept_loop(
    listener: TcpListener,
    request_tx: Sender<RuntimeControlRequest>,
    response_timeout: Duration,
) {
    for incoming in listener.incoming() {
        match incoming {
            Ok(stream) => {
                let tx = request_tx.clone();
                let _ = thread::Builder::new()
                    .name("xace-runtime-control-client".to_string())
                    .spawn(move || handle_client(stream, tx, response_timeout));
            }
            Err(err) => {
                log::warn!("Runtime control accept failed: {}", err);
            }
        }
    }
}

fn handle_client(
    stream: TcpStream,
    request_tx: Sender<RuntimeControlRequest>,
    response_timeout: Duration,
) {
    let peer = stream
        .peer_addr()
        .map(|addr| addr.to_string())
        .unwrap_or_else(|_| "<unknown>".to_string());
    let mut reader = match stream.try_clone() {
        Ok(stream) => BufReader::new(stream),
        Err(err) => {
            log::warn!("Runtime control clone failed for {}: {}", peer, err);
            return;
        }
    };
    let mut writer = stream;

    loop {
        let raw = match read_control_message(&mut reader) {
            Ok(Some(raw)) => raw,
            Ok(None) => break,
            Err(err) => {
                log::warn!("Runtime control read failed from {}: {}", peer, err);
                break;
            }
        };

        let message = match parse_control_request(&raw) {
            Ok(message) => message,
            Err(err) => {
                log::warn!("Runtime control parse failed from {}: {}", peer, err);
                continue;
            }
        };

        let (response_tx, response_rx): (Sender<serde_json::Value>, Receiver<serde_json::Value>) =
            mpsc::channel();
        if request_tx
            .send(RuntimeControlRequest {
                message,
                response_tx,
            })
            .is_err()
        {
            break;
        }

        match response_rx.recv_timeout(response_timeout) {
            Ok(ack) => {
                if let Err(err) = write_control_message(&mut writer, &ack) {
                    log::warn!("Runtime control write failed to {}: {}", peer, err);
                    break;
                }
            }
            Err(err) => {
                log::warn!("Runtime control response timed out for {}: {}", peer, err);
                break;
            }
        }
    }
}

pub fn offline_status() -> RuntimeControlStatus {
    RuntimeControlStatus {
        tick: 0,
        alive_count: 0,
        engine_connected: false,
        adapter_type: "headless".to_string(),
        engine_connections: Vec::new(),
        engine_snapshots_sent: 0,
        engine_input_packets_received: 0,
        engine_feedback_payloads_received: 0,
        engine_feedback_messages_received: 0,
        engine_malformed_messages: 0,
        engine_dropped_inputs: 0,
        engine_adapter_sequence: 0,
        pending_engine_inputs: 0,
        input_sync_mode: "direct".to_string(),
        input_sync_last_decision: "offline".to_string(),
        pending_engine_feedback: 0,
        registered_systems: 0,
        phase_count: 0,
        last_engine_feedback_processed: 0,
        last_engine_feedback_invalid: 0,
        last_engine_feedback_errors: 0,
        latest_world_hash: String::new(),
        cgs_hash: String::new(),
        schema_version: String::new(),
        execution_plan_version: String::new(),
        parallel_group_execution_policy: "deterministic_sequential".to_string(),
        parallel_group_worker_threads: false,
        hash_log: Vec::new(),
        paused: false,
        step_budget: 0,
    }
}
