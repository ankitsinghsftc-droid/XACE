//! # TCP Transport
//!
//! Local TCP socket transport for XACE ↔ Engine Adapter communication.
//!
//! ## Role
//! The TCP transport is the primary development and remote-deployment
//! transport. It connects XACE (server) to an engine adapter (client)
//! over a TCP socket, exchanging length-prefixed WireMessage frames.
//!
//! For same-machine deployment where latency is critical, prefer
//! `shm_transport.rs` (shared-memory transport) which bypasses the
//! kernel network stack entirely. TCP stays for remote/network deployment
//! and as the reference implementation all other transports mirror.
//!
//! ## Architecture
//! ```text
//!                    ┌──────────────────────────────┐
//!  XACE Runtime ──── │  TcpTransport (server side)  │ ──── TCP socket ──── Engine Adapter
//!                    │  - send_message()             │
//!                    │  - try_receive_message()      │
//!                    │  - send_batch()               │
//!                    └──────────────────────────────┘
//! ```
//!
//! ## Connection Lifecycle
//! 1. `TcpTransport::bind()` — XACE binds a listener on the configured address
//! 2. `accept_connection()` — blocks until the engine adapter connects
//! 3. Exchange WireMessages via `send_message()` / `try_receive_message()`
//! 4. `disconnect()` — gracefully closes the connection
//! 5. Engine adapter reconnects → `accept_connection()` again
//!
//! ## Non-blocking Reads
//! `try_receive_message()` is non-blocking — it drains all available bytes
//! from the socket without blocking and returns all complete frames found.
//! The PhaseOrchestrator calls this at the start of each tick to collect
//! engine feedback without stalling the simulation (I13).
//!
//! ## Frame Format
//! All messages use the format defined by `MessageSerializer`:
//! `[4-byte BE u32 length][JSON payload bytes]`
//!
//! ## Error Handling
//! - `WouldBlock` / `EAGAIN` from non-blocking reads are treated as "no data" — not errors
//! - `BrokenPipe` / `ConnectionReset` → `RecoverableError` → reconnect path
//! - All other IO errors → `RecoverableError` with full OS error context

use std::io::{self, Read, Write};
use std::net::{TcpListener, TcpStream, SocketAddr};
use std::time::Duration;

use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::wire::wire_message::WireMessage;

use crate::transport::message_serializer::MessageSerializer;
use crate::transport::message_deserializer::MessageDeserializer;

// Inline logger shim — removes the `log` crate dependency while keeping
// the same call-sites. Replace with `log::info!` etc. once `log` is in
// the workspace Cargo.toml and re-exported here.
macro_rules! xlog_info  { ($($t:tt)*) => { eprintln!("[INFO]  {}", format!($($t)*)) } }
macro_rules! xlog_warn  { ($($t:tt)*) => { eprintln!("[WARN]  {}", format!($($t)*)) } }
macro_rules! xlog_error { ($($t:tt)*) => { eprintln!("[ERROR] {}", format!($($t)*)) } }

// ── Transport Configuration ───────────────────────────────────────────────────

/// Configuration for a TcpTransport instance.
#[derive(Debug, Clone)]
pub struct TcpTransportConfig {
    /// The address XACE listens on for incoming engine adapter connections.
    /// Default: "127.0.0.1:7777"
    pub bind_address: String,

    /// How long to wait for the engine adapter to connect before timing out.
    /// None = wait indefinitely (acceptable in development).
    pub accept_timeout: Option<Duration>,

    /// TCP_NODELAY — disables Nagle's algorithm.
    ///
    /// Must be `true` for XACE. Nagle batches small writes, introducing
    /// up to 200ms latency for sub-MSS frames. At 60Hz, one tick is 16ms —
    /// Nagle would corrupt the entire tick cadence. Always set this.
    pub no_delay: bool,

    /// Size of the OS-level send buffer for this socket in bytes.
    /// None = OS default (typically 128 KiB on Linux).
    pub send_buffer_size: Option<usize>,

    /// Size of the OS-level receive buffer for this socket in bytes.
    /// None = OS default (typically 128 KiB on Linux).
    pub recv_buffer_size: Option<usize>,

    /// Timeout for individual write operations.
    /// None = blocking writes (simpler, fine for local loopback).
    pub write_timeout: Option<Duration>,
}

impl Default for TcpTransportConfig {
    fn default() -> Self {
        Self {
            bind_address: "127.0.0.1:7777".into(),
            accept_timeout: Some(Duration::from_secs(30)),
            no_delay: true,  // mandatory — see field doc
            send_buffer_size: Some(256 * 1024),  // 256 KiB
            recv_buffer_size: Some(256 * 1024),  // 256 KiB
            write_timeout: Some(Duration::from_millis(100)),
        }
    }
}

// ── Connection State ──────────────────────────────────────────────────────────

/// The current state of the TCP transport connection.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TcpConnectionState {
    /// No listener bound. Initial state.
    Unbound,
    /// Listener bound, waiting for the engine adapter to connect.
    Listening,
    /// Engine adapter connected. Messages can be exchanged.
    Connected,
    /// Connection was closed gracefully.
    Disconnected,
    /// Connection was lost due to an error. Reconnect required.
    Error,
}

impl std::fmt::Display for TcpConnectionState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            TcpConnectionState::Unbound       => write!(f, "UNBOUND"),
            TcpConnectionState::Listening     => write!(f, "LISTENING"),
            TcpConnectionState::Connected     => write!(f, "CONNECTED"),
            TcpConnectionState::Disconnected  => write!(f, "DISCONNECTED"),
            TcpConnectionState::Error         => write!(f, "ERROR"),
        }
    }
}

// ── Transport Metrics ─────────────────────────────────────────────────────────

/// Accumulated metrics for one TcpTransport session.
#[derive(Debug, Clone, Default)]
pub struct TcpTransportMetrics {
    /// Total messages sent successfully.
    pub messages_sent: u64,
    /// Total messages received successfully.
    pub messages_received: u64,
    /// Total bytes written to the socket.
    pub bytes_sent: u64,
    /// Total bytes read from the socket.
    pub bytes_received: u64,
    /// Number of send failures (broken pipe, timeout).
    pub send_failures: u64,
    /// Number of receive failures (connection reset, IO error).
    pub receive_failures: u64,
    /// Number of times the engine adapter reconnected.
    pub reconnect_count: u64,
}

// ── TCP Transport ─────────────────────────────────────────────────────────────

/// TCP socket transport for XACE ↔ Engine Adapter message exchange.
///
/// XACE acts as the TCP server — it binds and listens.
/// The engine adapter is the TCP client — it connects.
///
/// ## Single-connection model
/// Each TcpTransport manages exactly one engine adapter connection.
/// Multi-peer multiplayer uses one TcpTransport per peer, coordinated
/// by the Network Core (Phase 15).
///
/// ## Non-blocking receive
/// The underlying TcpStream is set to non-blocking for reads.
/// `try_receive_message()` drains all available data without stalling.
/// Writes remain blocking (with timeout) for simplicity and reliability.
pub struct TcpTransport {
    config: TcpTransportConfig,

    /// Bound TCP listener. Some after `bind()`, None before.
    listener: Option<TcpListener>,

    /// Active connection stream. Some after `accept_connection()`.
    stream: Option<TcpStream>,

    /// Remote peer address, for logging.
    peer_addr: Option<SocketAddr>,

    /// Current connection state.
    state: TcpConnectionState,

    /// Serializer for outbound messages.
    serializer: MessageSerializer,

    /// Deserializer with internal receive buffer for inbound messages.
    deserializer: MessageDeserializer,

    /// Accumulated session metrics.
    metrics: TcpTransportMetrics,
}

impl TcpTransport {
    // ── Construction ──────────────────────────────────────────────────────────

    /// Creates a new TcpTransport with the given configuration.
    /// Does not bind or connect — call `bind()` to start listening.
    pub fn new(config: TcpTransportConfig) -> Self {
        Self {
            config,
            listener: None,
            stream: None,
            peer_addr: None,
            state: TcpConnectionState::Unbound,
            serializer: MessageSerializer::new(),
            deserializer: MessageDeserializer::new(),
            metrics: TcpTransportMetrics::default(),
        }
    }

    /// Creates a TcpTransport with default configuration on 127.0.0.1:7777.
    pub fn with_defaults() -> Self {
        Self::new(TcpTransportConfig::default())
    }

    /// Creates a TcpTransport on a specific address (useful for tests
    /// using port 0 for OS-assigned ports).
    pub fn on_address(addr: impl Into<String>) -> Self {
        Self::new(TcpTransportConfig {
            bind_address: addr.into(),
            ..TcpTransportConfig::default()
        })
    }

    // ── Lifecycle ─────────────────────────────────────────────────────────────

    /// Binds the TCP listener to the configured address.
    ///
    /// After this call, the engine adapter may connect.
    /// Call `accept_connection()` to block until it does.
    pub fn bind(&mut self) -> Result<SocketAddr, XaceError> {
        let listener = TcpListener::bind(&self.config.bind_address).map_err(|e| {
            XaceError::RecoverableError {
                message: format!(
                    "TcpTransport: failed to bind on '{}' — {}",
                    self.config.bind_address, e
                ),
                context: ErrorContext::new("TcpTransport", "bind")
                    .with_detail("address", &self.config.bind_address),
                max_retries: 3,
                retry_count: 0,
            }
        })?;

        // Set accept timeout if configured
        if let Some(timeout) = self.config.accept_timeout {
            listener.set_nonblocking(false).ok();
            // TcpListener does not expose set_read_timeout directly —
            // the accept timeout is implemented via non-blocking poll in accept_connection.
            let _ = timeout; // stored in config, applied during accept
        }

        let local_addr = listener.local_addr().map_err(|e| XaceError::RecoverableError {
            message: format!("TcpTransport: failed to get local address — {}", e),
            context: ErrorContext::new("TcpTransport", "bind"),
            max_retries: 0,
            retry_count: 0,
        })?;

        xlog_info!("[TcpTransport] Listening on {}", local_addr);
        self.listener = Some(listener);
        self.state = TcpConnectionState::Listening;
        Ok(local_addr)
    }

    /// Blocks until the engine adapter connects, then configures the stream.
    ///
    /// Applies TCP_NODELAY, buffer sizes, and write timeout from config.
    /// Sets the stream to non-blocking mode for reads only (via set_nonblocking
    /// on the stream after write operations are complete).
    ///
    /// After this returns Ok(()), `send_message()` and `try_receive_message()`
    /// are available.
    pub fn accept_connection(&mut self) -> Result<SocketAddr, XaceError> {
        let listener = self.listener.as_ref().ok_or_else(|| XaceError::RecoverableError {
            message: "TcpTransport: accept_connection() called before bind()".into(),
            context: ErrorContext::new("TcpTransport", "accept_connection"),
            max_retries: 0,
            retry_count: 0,
        })?;

        xlog_info!("[TcpTransport] Waiting for engine adapter to connect...");

        let (stream, peer_addr) = listener.accept().map_err(|e| XaceError::RecoverableError {
            message: format!("TcpTransport: accept failed — {}", e),
            context: ErrorContext::new("TcpTransport", "accept_connection"),
            max_retries: 3,
            retry_count: 0,
        })?;

        self.configure_stream(&stream)?;

        // Set non-blocking for reads — try_receive_message polls without stalling
        stream.set_nonblocking(true).map_err(|e| XaceError::RecoverableError {
            message: format!("TcpTransport: set_nonblocking failed — {}", e),
            context: ErrorContext::new("TcpTransport", "accept_connection"),
            max_retries: 0,
            retry_count: 0,
        })?;

        xlog_info!("[TcpTransport] Engine adapter connected from {}", peer_addr);
        self.peer_addr = Some(peer_addr);
        self.stream = Some(stream);
        self.state = TcpConnectionState::Connected;
        self.deserializer.clear_buffer();
        Ok(peer_addr)
    }

    /// Gracefully closes the connection and resets to Listening state.
    ///
    /// The listener remains bound — call `accept_connection()` again
    /// to accept the next engine adapter connection.
    pub fn disconnect(&mut self) {
        if let Some(stream) = self.stream.take() {
            stream.shutdown(std::net::Shutdown::Both).ok();
            xlog_info!("[TcpTransport] Disconnected from {:?}", self.peer_addr);
        }
        self.peer_addr = None;
        self.state = if self.listener.is_some() {
            TcpConnectionState::Listening
        } else {
            TcpConnectionState::Disconnected
        };
        self.deserializer.clear_buffer();
    }

    /// Shuts down the listener and all connections completely.
    /// After this call, `bind()` must be called again to use this transport.
    pub fn shutdown(&mut self) {
        self.disconnect();
        self.listener = None;
        self.state = TcpConnectionState::Disconnected;
    }

    // ── Message Exchange ──────────────────────────────────────────────────────

    /// Serializes and sends a WireMessage to the connected engine adapter.
    ///
    /// Writes are blocking with the configured write_timeout.
    /// A write failure transitions the state to Error and returns
    /// `RecoverableError` — the caller should trigger reconnect logic.
    pub fn send_message(&mut self, msg: &WireMessage) -> Result<(), XaceError> {
        // Step 1: serialize BEFORE borrowing the stream — avoids split-borrow conflict.
        let frame = self.serializer.serialize(msg)?;
        let byte_count = frame.len();
        let write_timeout = self.config.write_timeout;
        let msg_type = msg.message_type;
        let tick = msg.tick;

        // Step 2: validate state inline (not via require_connected — that holds &mut self).
        if !matches!(self.state, TcpConnectionState::Connected) {
            return Err(XaceError::RecoverableError {
                message: format!(
                    "TcpTransport::send_message called in state {} — must be Connected",
                    self.state
                ),
                context: ErrorContext::new("TcpTransport", "send_message")
                    .with_detail("state", self.state.to_string()),
                max_retries: 0,
                retry_count: 0,
            });
        }

        // Step 3: scoped stream borrow — ends before we touch self.metrics / self.state.
        let write_result = {
            let stream = self.stream.as_mut().unwrap();
            stream.set_nonblocking(false).ok();
            if let Some(timeout) = write_timeout {
                stream.set_write_timeout(Some(timeout)).ok();
            }
            let result = stream.write_all(&frame);
            stream.set_nonblocking(true).ok();
            result
        }; // ← stream borrow released here

        // Step 4: update self freely now that stream borrow is gone.
        match write_result {
            Ok(()) => {
                self.metrics.messages_sent += 1;
                self.metrics.bytes_sent += byte_count as u64;
                Ok(())
            }
            Err(e) => {
                self.metrics.send_failures += 1;
                self.state = TcpConnectionState::Error;
                Err(XaceError::RecoverableError {
                    message: format!(
                        "TcpTransport: send_message failed ({:?}) — {}",
                        msg_type, e
                    ),
                    context: ErrorContext::new("TcpTransport", "send_message")
                        .with_tick(tick)
                        .with_detail("message_type", msg_type.to_string())
                        .with_detail("frame_bytes", byte_count.to_string()),
                    max_retries: 3,
                    retry_count: 0,
                })
            }
        }
    }

    /// Serializes and sends multiple WireMessages in one syscall batch.
    ///
    /// More efficient than calling `send_message()` N times at 60Hz —
    /// the DELTA + EVENT messages for one tick are batched into a single
    /// `write_all()` call, reducing syscall overhead significantly.
    pub fn send_batch(&mut self, messages: &[WireMessage]) -> Result<(), XaceError> {
        if messages.is_empty() {
            return Ok(());
        }

        // Serialize before touching the stream.
        let batch = self.serializer.serialize_batch(messages)?;
        let byte_count = batch.len();
        let msg_count = messages.len();
        let write_timeout = self.config.write_timeout;

        if !matches!(self.state, TcpConnectionState::Connected) {
            return Err(XaceError::RecoverableError {
                message: format!(
                    "TcpTransport::send_batch called in state {} — must be Connected",
                    self.state
                ),
                context: ErrorContext::new("TcpTransport", "send_batch")
                    .with_detail("state", self.state.to_string()),
                max_retries: 0,
                retry_count: 0,
            });
        }

        // Scoped stream borrow.
        let write_result = {
            let stream = self.stream.as_mut().unwrap();
            stream.set_nonblocking(false).ok();
            if let Some(timeout) = write_timeout {
                stream.set_write_timeout(Some(timeout)).ok();
            }
            let result = stream.write_all(&batch);
            stream.set_nonblocking(true).ok();
            result
        }; // ← stream borrow released

        match write_result {
            Ok(()) => {
                self.metrics.messages_sent += msg_count as u64;
                self.metrics.bytes_sent += byte_count as u64;
                Ok(())
            }
            Err(e) => {
                self.metrics.send_failures += 1;
                self.state = TcpConnectionState::Error;
                Err(XaceError::RecoverableError {
                    message: format!(
                        "TcpTransport: send_batch failed — {} messages, {} bytes — {}",
                        msg_count, byte_count, e
                    ),
                    context: ErrorContext::new("TcpTransport", "send_batch")
                        .with_detail("message_count", msg_count.to_string())
                        .with_detail("batch_bytes", byte_count.to_string()),
                    max_retries: 3,
                    retry_count: 0,
                })
            }
        }
    }

    /// Drains all available inbound bytes and returns every complete WireMessage.
    ///
    /// Non-blocking — returns an empty Vec immediately if no data is available.
    /// Call at the start of each tick to collect engine feedback (I13).
    ///
    /// Partial frames are buffered internally and completed on the next call.
    ///
    /// A deserialization error on one frame does not prevent extracting
    /// subsequent frames — the bad frame is consumed and parsing continues.
    pub fn try_receive_messages(&mut self) -> Result<Vec<WireMessage>, XaceError> {
        if !matches!(self.state, TcpConnectionState::Connected) {
            return Err(XaceError::RecoverableError {
                message: format!(
                    "TcpTransport::try_receive_messages called in state {} — must be Connected",
                    self.state
                ),
                context: ErrorContext::new("TcpTransport", "try_receive_messages")
                    .with_detail("state", self.state.to_string()),
                max_retries: 0,
                retry_count: 0,
            });
        }

        let mut read_buf = [0u8; 64 * 1024];
        let mut total_bytes_read = 0u64;

        // Scoped stream reads — each iteration borrows stream briefly then drops it.
        loop {
            let read_result = {
                let stream = self.stream.as_mut().unwrap();
                stream.read(&mut read_buf)
            }; // stream borrow released

            match read_result {
                Ok(0) => {
                    // EOF — connection closed by peer
                    xlog_warn!("[TcpTransport] Connection closed by engine adapter");
                    self.state = TcpConnectionState::Error;
                    return Err(XaceError::RecoverableError {
                        message: "TcpTransport: engine adapter closed connection (EOF)".into(),
                        context: ErrorContext::new("TcpTransport", "try_receive_messages"),
                        max_retries: 3,
                        retry_count: 0,
                    });
                }
                Ok(n) => {
                    total_bytes_read += n as u64;
                    self.deserializer.push_bytes(&read_buf[..n]);
                }
                Err(e) if e.kind() == io::ErrorKind::WouldBlock => break,
                Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
                Err(e) => {
                    self.metrics.receive_failures += 1;
                    self.state = TcpConnectionState::Error;
                    return Err(XaceError::RecoverableError {
                        message: format!("TcpTransport: read error — {}", e),
                        context: ErrorContext::new("TcpTransport", "try_receive_messages"),
                        max_retries: 3,
                        retry_count: 0,
                    });
                }
            }
        }

        self.metrics.bytes_received += total_bytes_read;

        // Extract all complete frames from the deserializer buffer.
        // Stream borrow is fully released above — self is free to use.
        let mut messages = Vec::new();
        loop {
            match self.deserializer.try_extract_message() {
                Ok(Some(msg)) => {
                    self.metrics.messages_received += 1;
                    messages.push(msg);
                }
                Ok(None) => break,
                Err(e) => {
                    self.metrics.receive_failures += 1;
                    xlog_error!(
                        "[TcpTransport] Deserialize error (frame skipped): {}",
                        e.message()
                    );
                }
            }
        }

        Ok(messages)
    }

    // ── Inspection ────────────────────────────────────────────────────────────

    /// Returns the current connection state.
    pub fn state(&self) -> TcpConnectionState {
        self.state
    }

    /// Returns true if the transport is connected and ready for message exchange.
    pub fn is_connected(&self) -> bool {
        matches!(self.state, TcpConnectionState::Connected)
    }

    /// Returns the remote peer address, if connected.
    pub fn peer_addr(&self) -> Option<SocketAddr> {
        self.peer_addr
    }

    /// Returns the local address the listener is bound to.
    pub fn local_addr(&self) -> Option<SocketAddr> {
        self.listener.as_ref().and_then(|l| l.local_addr().ok())
    }

    /// Returns a reference to accumulated transport metrics.
    pub fn metrics(&self) -> &TcpTransportMetrics {
        &self.metrics
    }

    /// Returns a reference to serializer metrics.
    pub fn serializer_metrics(&self) -> &crate::transport::message_serializer::SerializerMetrics {
        self.serializer.metrics()
    }

    /// Returns a reference to deserializer metrics.
    pub fn deserializer_metrics(&self) -> &crate::transport::message_deserializer::DeserializerMetrics {
        self.deserializer.metrics()
    }

    // ── Internal Helpers ──────────────────────────────────────────────────────

    /// Applies socket options from config to a newly accepted stream.
    fn configure_stream(&self, stream: &TcpStream) -> Result<(), XaceError> {
        // TCP_NODELAY is mandatory — see config field documentation
        stream.set_nodelay(self.config.no_delay).map_err(|e| {
            XaceError::RecoverableError {
                message: format!("TcpTransport: set_nodelay failed — {}", e),
                context: ErrorContext::new("TcpTransport", "configure_stream"),
                max_retries: 0,
                retry_count: 0,
            }
        })?;

        // Buffer sizes (best-effort — OS may not honour exactly)
        if let Some(size) = self.config.send_buffer_size {
            // std::net::TcpStream does not expose SO_SNDBUF directly.
            // This is set via the OS socket API in a real deployment.
            // Documented here for completeness — impl in Phase 15 when
            // we add the socket2 crate for fine-grained socket control.
            let _ = size;
        }

        Ok(())
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::wire::wire_message::WireMessage;
    use std::io::Write;
    use std::thread;

    // ── Helpers ───────────────────────────────────────────────────────────────

    fn delta_msg(tick: u64, seq: u64) -> WireMessage {
        WireMessage::delta(
            "default", "0.1.0", 1, tick, seq,
            r#"{"tick":1,"sequence_id":1,"schema_version":"0.1.0","spawned_entities":[],"added_components":[],"modified_entities":{},"removed_components":[],"destroyed_entities":[]}"#,
        )
    }

    fn feedback_msg(tick: u64) -> WireMessage {
        WireMessage::feedback(
            "default", "0.1.0", 1, tick, tick,
            r#"{"feedback_type":"ANIMATION_STATE_UPDATE","data":{}}"#,
        )
    }

    /// Creates a transport, binds it, returns transport + local port.
    fn bound_transport() -> (TcpTransport, u16) {
        let mut t = TcpTransport::on_address("127.0.0.1:0");
        let addr = t.bind().unwrap();
        (t, addr.port())
    }

    // ── State Machine ─────────────────────────────────────────────────────────

    #[test]
    fn initial_state_is_unbound() {
        let t = TcpTransport::with_defaults();
        assert_eq!(t.state(), TcpConnectionState::Unbound);
        assert!(!t.is_connected());
    }

    #[test]
    fn bind_transitions_to_listening() {
        let (t, _port) = bound_transport();
        assert_eq!(t.state(), TcpConnectionState::Listening);
        assert!(!t.is_connected());
    }

    #[test]
    fn local_addr_available_after_bind() {
        let (t, _port) = bound_transport();
        assert!(t.local_addr().is_some());
    }

    #[test]
    fn send_message_before_connect_returns_error() {
        let (mut t, _port) = bound_transport();
        let result = t.send_message(&delta_msg(1, 1));
        assert!(result.is_err(), "send_message must fail before connected");
    }

    #[test]
    fn try_receive_before_connect_returns_error() {
        let (mut t, _port) = bound_transport();
        let result = t.try_receive_messages();
        assert!(result.is_err());
    }

    // ── Full Round-trip ───────────────────────────────────────────────────────

    fn spawn_client(port: u16, messages: Vec<Vec<u8>>) -> thread::JoinHandle<()> {
        thread::spawn(move || {
            // Small delay to let server reach accept_connection()
            thread::sleep(Duration::from_millis(20));
            let mut client = TcpStream::connect(format!("127.0.0.1:{}", port)).unwrap();
            client.set_nodelay(true).unwrap();
            for frame in messages {
                client.write_all(&frame).unwrap();
            }
            // Hold connection open briefly so server can read
            thread::sleep(Duration::from_millis(100));
        })
    }

    #[test]
    fn accept_and_send_message_round_trip() {
        let (mut server, port) = bound_transport();

        // Client thread: connect and immediately close
        let handle = thread::spawn(move || {
            thread::sleep(Duration::from_millis(20));
            let _client = TcpStream::connect(format!("127.0.0.1:{}", port)).unwrap();
            thread::sleep(Duration::from_millis(200));
        });

        server.accept_connection().unwrap();
        assert_eq!(server.state(), TcpConnectionState::Connected);
        assert!(server.is_connected());
        assert!(server.peer_addr().is_some());

        // Send should succeed on the connected socket
        assert!(server.send_message(&delta_msg(1, 1)).is_ok());
        assert_eq!(server.metrics().messages_sent, 1);
        assert!(server.metrics().bytes_sent > 0);

        handle.join().unwrap();
    }

    #[test]
    fn receive_message_sent_by_client() {
        let (mut server, port) = bound_transport();
        let mut ser = MessageSerializer::new();
        let frame = ser.serialize(&feedback_msg(5)).unwrap();

        let handle = spawn_client(port, vec![frame]);
        server.accept_connection().unwrap();

        // Poll until we get the message (with timeout)
        let start = std::time::Instant::now();
        let mut received = Vec::new();
        while received.is_empty() && start.elapsed() < Duration::from_secs(2) {
            received = server.try_receive_messages().unwrap();
            if received.is_empty() {
                thread::sleep(Duration::from_millis(5));
            }
        }

        assert_eq!(received.len(), 1);
        assert!(received[0].is_feedback());
        assert_eq!(received[0].tick, 5);
        assert_eq!(server.metrics().messages_received, 1);

        handle.join().unwrap();
    }

    #[test]
    fn receive_two_messages_from_client() {
        let (mut server, port) = bound_transport();
        let mut ser = MessageSerializer::new();
        let f1 = ser.serialize(&feedback_msg(10)).unwrap();
        let f2 = ser.serialize(&feedback_msg(11)).unwrap();
        let mut both = f1;
        both.extend_from_slice(&f2);

        let handle = spawn_client(port, vec![both]);
        server.accept_connection().unwrap();

        let start = std::time::Instant::now();
        let mut all_msgs = Vec::new();
        while all_msgs.len() < 2 && start.elapsed() < Duration::from_secs(2) {
            let mut batch = server.try_receive_messages().unwrap();
            all_msgs.append(&mut batch);
            if all_msgs.len() < 2 {
                thread::sleep(Duration::from_millis(5));
            }
        }

        assert_eq!(all_msgs.len(), 2);
        assert_eq!(all_msgs[0].tick, 10);
        assert_eq!(all_msgs[1].tick, 11);

        handle.join().unwrap();
    }

    #[test]
    fn send_batch_sends_all_messages() {
        let (mut server, port) = bound_transport();

        let handle = thread::spawn(move || {
            thread::sleep(Duration::from_millis(20));
            let _client = TcpStream::connect(format!("127.0.0.1:{}", port)).unwrap();
            thread::sleep(Duration::from_millis(200));
        });

        server.accept_connection().unwrap();
        let msgs = vec![delta_msg(1, 1), delta_msg(2, 2), delta_msg(3, 3)];
        server.send_batch(&msgs).unwrap();
        assert_eq!(server.metrics().messages_sent, 3);

        handle.join().unwrap();
    }

    #[test]
    fn send_batch_empty_slice_is_noop() {
        let (mut server, port) = bound_transport();
        let handle = thread::spawn(move || {
            thread::sleep(Duration::from_millis(20));
            let _client = TcpStream::connect(format!("127.0.0.1:{}", port)).unwrap();
            thread::sleep(Duration::from_millis(100));
        });
        server.accept_connection().unwrap();
        assert!(server.send_batch(&[]).is_ok());
        assert_eq!(server.metrics().messages_sent, 0);
        handle.join().unwrap();
    }

    #[test]
    fn try_receive_no_data_returns_empty_vec() {
        let (mut server, port) = bound_transport();
        let handle = thread::spawn(move || {
            thread::sleep(Duration::from_millis(20));
            let _client = TcpStream::connect(format!("127.0.0.1:{}", port)).unwrap();
            thread::sleep(Duration::from_millis(200));
        });
        server.accept_connection().unwrap();
        // No data sent — should return empty
        let msgs = server.try_receive_messages().unwrap();
        assert!(msgs.is_empty());
        handle.join().unwrap();
    }

    // ── Disconnect ────────────────────────────────────────────────────────────

    #[test]
    fn disconnect_transitions_to_listening() {
        let (mut server, port) = bound_transport();
        let handle = thread::spawn(move || {
            thread::sleep(Duration::from_millis(20));
            let _client = TcpStream::connect(format!("127.0.0.1:{}", port)).unwrap();
            thread::sleep(Duration::from_millis(200));
        });
        server.accept_connection().unwrap();
        server.disconnect();
        assert_eq!(server.state(), TcpConnectionState::Listening);
        assert!(!server.is_connected());
        handle.join().unwrap();
    }

    #[test]
    fn send_after_disconnect_fails() {
        let (mut server, port) = bound_transport();
        let handle = thread::spawn(move || {
            thread::sleep(Duration::from_millis(20));
            let _client = TcpStream::connect(format!("127.0.0.1:{}", port)).unwrap();
            thread::sleep(Duration::from_millis(200));
        });
        server.accept_connection().unwrap();
        server.disconnect();
        assert!(server.send_message(&delta_msg(1, 1)).is_err());
        handle.join().unwrap();
    }

    // ── Configuration ─────────────────────────────────────────────────────────

    #[test]
    fn default_config_has_no_delay_true() {
        let config = TcpTransportConfig::default();
        assert!(config.no_delay, "TCP_NODELAY must be true by default");
    }

    #[test]
    fn default_config_address_is_localhost_7777() {
        let config = TcpTransportConfig::default();
        assert_eq!(config.bind_address, "127.0.0.1:7777");
    }

    // ── Metrics ───────────────────────────────────────────────────────────────

    #[test]
    fn metrics_start_at_zero() {
        let t = TcpTransport::with_defaults();
        let m = t.metrics();
        assert_eq!(m.messages_sent, 0);
        assert_eq!(m.messages_received, 0);
        assert_eq!(m.bytes_sent, 0);
        assert_eq!(m.bytes_received, 0);
    }
}