//! Production TCP transport for runtime/engine adapter communication.
//!
//! The runtime owns the listener and accepts one engine adapter connection.
//! Messages use the canonical length-prefixed `WireMessage` frame format.

use std::io::{self, Read, Write};
use std::net::{Shutdown, SocketAddr, TcpListener, TcpStream};
use std::thread;
use std::time::{Duration, Instant};

use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::wire::wire_message::WireMessage;

use crate::adapter_contract::engine_adapter_interface::Transport;
use crate::transport::message_deserializer::{DeserializerMetrics, MessageDeserializer};
use crate::transport::message_serializer::{MessageSerializer, SerializerMetrics};

const DEFAULT_BIND_ADDRESS: &str = "127.0.0.1:7777";
const DEFAULT_ACCEPT_TIMEOUT: Duration = Duration::from_secs(30);
const DEFAULT_WRITE_TIMEOUT: Duration = Duration::from_millis(100);
const DEFAULT_SOCKET_BUFFER: usize = 256 * 1024;
const DEFAULT_READ_CHUNK: usize = 64 * 1024;
const ACCEPT_POLL_INTERVAL: Duration = Duration::from_millis(5);

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TcpTransportConfig {
    pub bind_address: String,
    pub accept_timeout: Option<Duration>,
    pub no_delay: bool,
    pub send_buffer_size: Option<usize>,
    pub recv_buffer_size: Option<usize>,
    pub write_timeout: Option<Duration>,
    pub engine_name: String,
    pub read_chunk_size: usize,
}

impl Default for TcpTransportConfig {
    fn default() -> Self {
        Self {
            bind_address: DEFAULT_BIND_ADDRESS.to_string(),
            accept_timeout: Some(DEFAULT_ACCEPT_TIMEOUT),
            no_delay: true,
            send_buffer_size: Some(DEFAULT_SOCKET_BUFFER),
            recv_buffer_size: Some(DEFAULT_SOCKET_BUFFER),
            write_timeout: Some(DEFAULT_WRITE_TIMEOUT),
            engine_name: "EngineAdapter".to_string(),
            read_chunk_size: DEFAULT_READ_CHUNK,
        }
    }
}

impl TcpTransportConfig {
    pub fn validate(&self) -> Result<(), String> {
        if self.bind_address.trim().is_empty() {
            return Err("bind_address must not be empty".to_string());
        }
        self.bind_address
            .parse::<SocketAddr>()
            .map_err(|err| format!("bind_address is not a socket address: {}", err))?;
        if self.read_chunk_size < 1024 {
            return Err("read_chunk_size must be at least 1024 bytes".to_string());
        }
        if self.engine_name.trim().is_empty() {
            return Err("engine_name must not be empty".to_string());
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TcpConnectionState {
    Unbound,
    Listening,
    Connected,
    Disconnected,
    Error,
}

impl std::fmt::Display for TcpConnectionState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Unbound => f.write_str("UNBOUND"),
            Self::Listening => f.write_str("LISTENING"),
            Self::Connected => f.write_str("CONNECTED"),
            Self::Disconnected => f.write_str("DISCONNECTED"),
            Self::Error => f.write_str("ERROR"),
        }
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct TcpTransportMetrics {
    pub messages_sent: u64,
    pub messages_received: u64,
    pub bytes_sent: u64,
    pub bytes_received: u64,
    pub send_failures: u64,
    pub receive_failures: u64,
    pub reconnect_count: u64,
    pub accept_timeouts: u64,
    pub disconnects: u64,
    pub deserialize_failures: u64,
}

pub struct TcpTransport {
    config: TcpTransportConfig,
    listener: Option<TcpListener>,
    stream: Option<TcpStream>,
    peer_addr: Option<SocketAddr>,
    state: TcpConnectionState,
    serializer: MessageSerializer,
    deserializer: MessageDeserializer,
    metrics: TcpTransportMetrics,
}

impl TcpTransport {
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

    pub fn with_defaults() -> Self {
        Self::new(TcpTransportConfig::default())
    }

    pub fn on_address(addr: impl Into<String>) -> Self {
        Self::new(TcpTransportConfig {
            bind_address: addr.into(),
            ..TcpTransportConfig::default()
        })
    }

    pub fn bind(&mut self) -> Result<SocketAddr, XaceError> {
        self.config
            .validate()
            .map_err(|detail| self.config_error("bind", detail))?;

        if self.stream.is_some() {
            self.disconnect();
        }

        let listener = TcpListener::bind(&self.config.bind_address).map_err(|err| {
            recoverable(
                "bind",
                format!(
                    "TcpTransport failed to bind '{}': {}",
                    self.config.bind_address, err
                ),
            )
        })?;
        listener.set_nonblocking(true).map_err(|err| {
            recoverable(
                "bind",
                format!("failed to set listener nonblocking: {}", err),
            )
        })?;

        let addr = listener
            .local_addr()
            .map_err(|err| recoverable("bind", format!("failed to read local address: {}", err)))?;
        self.listener = Some(listener);
        self.state = TcpConnectionState::Listening;
        Ok(addr)
    }

    pub fn accept_connection(&mut self) -> Result<SocketAddr, XaceError> {
        let listener = self.listener.as_ref().ok_or_else(|| {
            recoverable("accept_connection", "accept_connection called before bind")
        })?;

        let started = Instant::now();
        loop {
            match listener.accept() {
                Ok((stream, peer_addr)) => {
                    self.configure_stream(&stream)?;
                    if self.peer_addr.is_some() || self.metrics.messages_received > 0 {
                        self.metrics.reconnect_count += 1;
                    }
                    self.peer_addr = Some(peer_addr);
                    self.stream = Some(stream);
                    self.state = TcpConnectionState::Connected;
                    self.deserializer.clear_buffer();
                    return Ok(peer_addr);
                }
                Err(err) if err.kind() == io::ErrorKind::WouldBlock => {
                    if let Some(timeout) = self.config.accept_timeout {
                        if started.elapsed() >= timeout {
                            self.metrics.accept_timeouts += 1;
                            return Err(recoverable(
                                "accept_connection",
                                format!("timed out after {:?} waiting for engine adapter", timeout),
                            ));
                        }
                    }
                    thread::sleep(ACCEPT_POLL_INTERVAL);
                }
                Err(err) if err.kind() == io::ErrorKind::Interrupted => continue,
                Err(err) => {
                    self.state = TcpConnectionState::Error;
                    return Err(recoverable(
                        "accept_connection",
                        format!("listener accept failed: {}", err),
                    ));
                }
            }
        }
    }

    pub fn disconnect(&mut self) {
        if let Some(stream) = self.stream.take() {
            let _ = stream.shutdown(Shutdown::Both);
            self.metrics.disconnects += 1;
        }
        self.peer_addr = None;
        self.deserializer.clear_buffer();
        self.state = if self.listener.is_some() {
            TcpConnectionState::Listening
        } else {
            TcpConnectionState::Disconnected
        };
    }

    pub fn shutdown(&mut self) {
        self.disconnect();
        self.listener = None;
        self.state = TcpConnectionState::Disconnected;
    }

    pub fn send_message(&mut self, msg: &WireMessage) -> Result<(), XaceError> {
        self.ensure_connected("send_message")?;
        let frame = self.serializer.serialize(msg)?;
        let bytes = frame.len();

        match self.write_frame(&frame) {
            Ok(()) => {
                self.metrics.messages_sent += 1;
                self.metrics.bytes_sent += bytes as u64;
                Ok(())
            }
            Err(err) => {
                self.metrics.send_failures += 1;
                self.state = TcpConnectionState::Error;
                Err(recoverable(
                    "send_message",
                    format!(
                        "failed to send {} frame at tick {} ({} bytes): {}",
                        msg.message_type, msg.tick, bytes, err
                    ),
                ))
            }
        }
    }

    pub fn send_batch(&mut self, messages: &[WireMessage]) -> Result<(), XaceError> {
        if messages.is_empty() {
            return Ok(());
        }
        self.ensure_connected("send_batch")?;
        let frame_batch = self.serializer.serialize_batch(messages)?;
        let bytes = frame_batch.len();
        let count = messages.len();

        match self.write_frame(&frame_batch) {
            Ok(()) => {
                self.metrics.messages_sent += count as u64;
                self.metrics.bytes_sent += bytes as u64;
                Ok(())
            }
            Err(err) => {
                self.metrics.send_failures += 1;
                self.state = TcpConnectionState::Error;
                Err(recoverable(
                    "send_batch",
                    format!(
                        "failed to send {} messages ({} bytes): {}",
                        count, bytes, err
                    ),
                ))
            }
        }
    }

    pub fn try_receive_messages(&mut self) -> Result<Vec<WireMessage>, XaceError> {
        self.ensure_connected("try_receive_messages")?;
        self.read_available_bytes()?;

        let mut messages = Vec::new();
        loop {
            match self.deserializer.try_extract_message() {
                Ok(Some(message)) => {
                    self.metrics.messages_received += 1;
                    messages.push(message);
                }
                Ok(None) => break,
                Err(err) => {
                    self.metrics.receive_failures += 1;
                    self.metrics.deserialize_failures += 1;
                    if err.is_fatal() {
                        self.state = TcpConnectionState::Error;
                        return Err(err);
                    }
                }
            }
        }
        Ok(messages)
    }

    pub fn state(&self) -> TcpConnectionState {
        self.state
    }

    pub fn is_connected(&self) -> bool {
        self.state == TcpConnectionState::Connected && self.stream.is_some()
    }

    pub fn peer_addr(&self) -> Option<SocketAddr> {
        self.peer_addr
    }

    pub fn local_addr(&self) -> Option<SocketAddr> {
        self.listener
            .as_ref()
            .and_then(|listener| listener.local_addr().ok())
    }

    pub fn config(&self) -> &TcpTransportConfig {
        &self.config
    }

    pub fn metrics(&self) -> &TcpTransportMetrics {
        &self.metrics
    }

    pub fn serializer_metrics(&self) -> &SerializerMetrics {
        self.serializer.metrics()
    }

    pub fn deserializer_metrics(&self) -> &DeserializerMetrics {
        self.deserializer.metrics()
    }

    pub fn reset_metrics(&mut self) {
        self.metrics = TcpTransportMetrics::default();
        self.serializer.reset_metrics();
        self.deserializer.reset_metrics();
    }

    pub fn set_engine_name(&mut self, engine_name: impl Into<String>) -> Result<(), XaceError> {
        let engine_name = engine_name.into();
        if engine_name.trim().is_empty() {
            return Err(self.config_error("set_engine_name", "engine name must not be empty"));
        }
        self.config.engine_name = engine_name;
        Ok(())
    }

    fn configure_stream(&self, stream: &TcpStream) -> Result<(), XaceError> {
        stream.set_nodelay(self.config.no_delay).map_err(|err| {
            recoverable(
                "configure_stream",
                format!("failed to set TCP_NODELAY: {}", err),
            )
        })?;
        stream
            .set_write_timeout(self.config.write_timeout)
            .map_err(|err| {
                recoverable(
                    "configure_stream",
                    format!("failed to set write timeout: {}", err),
                )
            })?;
        stream.set_nonblocking(true).map_err(|err| {
            recoverable(
                "configure_stream",
                format!("failed to set stream nonblocking: {}", err),
            )
        })?;
        Ok(())
    }

    fn ensure_connected(&self, operation: &'static str) -> Result<(), XaceError> {
        if self.is_connected() {
            Ok(())
        } else {
            Err(recoverable(
                operation,
                format!("transport is {}, expected CONNECTED", self.state),
            ))
        }
    }

    fn write_frame(&mut self, frame: &[u8]) -> io::Result<()> {
        let stream = self
            .stream
            .as_mut()
            .ok_or_else(|| io::Error::new(io::ErrorKind::NotConnected, "no active TCP stream"))?;

        stream.set_nonblocking(false)?;
        let result = stream.write_all(frame).and_then(|_| stream.flush());
        let restore = stream.set_nonblocking(true);
        result.and(restore)
    }

    fn read_available_bytes(&mut self) -> Result<(), XaceError> {
        let mut buffer = vec![0u8; self.config.read_chunk_size];
        loop {
            let read_result = {
                let stream = self
                    .stream
                    .as_mut()
                    .ok_or_else(|| recoverable("try_receive_messages", "no active TCP stream"))?;
                stream.read(&mut buffer)
            };

            match read_result {
                Ok(0) => {
                    self.metrics.receive_failures += 1;
                    self.state = TcpConnectionState::Error;
                    return Err(recoverable(
                        "try_receive_messages",
                        "engine adapter closed the connection",
                    ));
                }
                Ok(n) => {
                    self.metrics.bytes_received += n as u64;
                    self.deserializer.push_bytes(&buffer[..n]);
                    if n < buffer.len() {
                        break;
                    }
                }
                Err(err) if err.kind() == io::ErrorKind::WouldBlock => break,
                Err(err) if err.kind() == io::ErrorKind::Interrupted => continue,
                Err(err) => {
                    self.metrics.receive_failures += 1;
                    self.state = TcpConnectionState::Error;
                    return Err(recoverable(
                        "try_receive_messages",
                        format!("read failed: {}", err),
                    ));
                }
            }
        }
        Ok(())
    }

    fn config_error(&self, operation: &'static str, detail: impl Into<String>) -> XaceError {
        XaceError::ValidationFailure {
            message: format!("TcpTransport config invalid: {}", detail.into()),
            context: ErrorContext::new("TcpTransport", operation),
            rule_violated: "transport_config".to_string(),
            failed_path: "tcp".to_string(),
        }
    }
}

impl Transport for TcpTransport {
    fn send_message(&mut self, msg: &WireMessage) -> Result<(), XaceError> {
        TcpTransport::send_message(self, msg)
    }

    fn send_batch(&mut self, messages: &[WireMessage]) -> Result<(), XaceError> {
        TcpTransport::send_batch(self, messages)
    }

    fn try_receive_messages(&mut self) -> Result<Vec<WireMessage>, XaceError> {
        TcpTransport::try_receive_messages(self)
    }

    fn is_connected(&self) -> bool {
        TcpTransport::is_connected(self)
    }

    fn engine_name(&self) -> &str {
        &self.config.engine_name
    }
}

fn recoverable(operation: &'static str, message: impl Into<String>) -> XaceError {
    XaceError::RecoverableError {
        message: format!("TcpTransport: {}", message.into()),
        context: ErrorContext::new("TcpTransport", operation),
        max_retries: 3,
        retry_count: 0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::transport::message_serializer::MessageSerializer;

    fn feedback(tick: u64, seq: u64) -> WireMessage {
        WireMessage::feedback("default", "0.1.0", 1, tick, seq, r#"{"type":"input_ack"}"#)
    }

    fn delta(tick: u64, seq: u64) -> WireMessage {
        WireMessage::delta("default", "0.1.0", 1, tick, seq, r#"{"type":"delta"}"#)
    }

    fn bound_transport() -> (TcpTransport, SocketAddr) {
        let mut transport = TcpTransport::on_address("127.0.0.1:0");
        let addr = transport.bind().unwrap();
        (transport, addr)
    }

    #[test]
    fn bind_transitions_to_listening() {
        let (transport, addr) = bound_transport();
        assert_eq!(transport.state(), TcpConnectionState::Listening);
        assert_eq!(transport.local_addr(), Some(addr));
    }

    #[test]
    fn send_before_connection_fails() {
        let (mut transport, _) = bound_transport();
        assert!(transport.send_message(&delta(1, 1)).is_err());
    }

    #[test]
    fn accept_timeout_is_enforced() {
        let mut transport = TcpTransport::new(TcpTransportConfig {
            bind_address: "127.0.0.1:0".to_string(),
            accept_timeout: Some(Duration::from_millis(20)),
            ..TcpTransportConfig::default()
        });
        transport.bind().unwrap();
        assert!(transport.accept_connection().is_err());
        assert_eq!(transport.metrics().accept_timeouts, 1);
    }

    #[test]
    fn receive_message_from_client() {
        let (mut server, addr) = bound_transport();
        let frame = MessageSerializer::new().serialize(&feedback(5, 1)).unwrap();

        let handle = thread::spawn(move || {
            let mut client = TcpStream::connect(addr).unwrap();
            client.write_all(&frame).unwrap();
            thread::sleep(Duration::from_millis(50));
        });

        server.accept_connection().unwrap();
        let start = Instant::now();
        let mut messages = Vec::new();
        while messages.is_empty() && start.elapsed() < Duration::from_secs(2) {
            messages = server.try_receive_messages().unwrap();
            if messages.is_empty() {
                thread::sleep(Duration::from_millis(5));
            }
        }

        assert_eq!(messages.len(), 1);
        assert_eq!(messages[0].tick, 5);
        assert_eq!(server.metrics().messages_received, 1);
        handle.join().unwrap();
    }

    #[test]
    fn send_batch_updates_metrics() {
        let (mut server, addr) = bound_transport();
        let handle = thread::spawn(move || {
            let mut client = TcpStream::connect(addr).unwrap();
            let mut sink = [0u8; 4096];
            let _ = client.read(&mut sink);
            thread::sleep(Duration::from_millis(50));
        });

        server.accept_connection().unwrap();
        server.send_batch(&[delta(1, 1), delta(2, 2)]).unwrap();
        assert_eq!(server.metrics().messages_sent, 2);
        assert!(server.metrics().bytes_sent > 0);
        handle.join().unwrap();
    }

    #[test]
    fn disconnect_returns_to_listening_when_listener_exists() {
        let (mut server, addr) = bound_transport();
        let handle = thread::spawn(move || {
            let _client = TcpStream::connect(addr).unwrap();
            thread::sleep(Duration::from_millis(50));
        });

        server.accept_connection().unwrap();
        server.disconnect();
        assert_eq!(server.state(), TcpConnectionState::Listening);
        assert!(!server.is_connected());
        handle.join().unwrap();
    }

    #[test]
    fn implements_transport_trait() {
        fn assert_transport<T: Transport>() {}
        assert_transport::<TcpTransport>();
    }
}
