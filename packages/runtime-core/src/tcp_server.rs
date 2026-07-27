//! TCP acceptor for local engine adapters.
//!
//! This module only owns socket lifecycle. Protocol validation and message
//! handling live in `engine_protocol` and `engine_bridge`.

use std::io::BufReader;
use std::net::{IpAddr, Ipv4Addr, SocketAddr, TcpListener, TcpStream};
use std::thread;
use std::time::{Duration, Instant};

use anyhow::Result;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TcpServerConfig {
    pub bind_addr: SocketAddr,
    pub accept_poll_interval: Duration,
    pub write_timeout: Duration,
    pub read_timeout: Option<Duration>,
    pub nodelay: bool,
}

impl TcpServerConfig {
    pub fn localhost(port: u16) -> Self {
        Self {
            bind_addr: SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), port),
            accept_poll_interval: Duration::from_millis(25),
            write_timeout: Duration::from_secs(5),
            read_timeout: None,
            nodelay: true,
        }
    }
}

#[derive(Debug)]
pub struct EngineConnection {
    pub stream: TcpStream,
    pub peer_addr: String,
    pub accepted_at: Instant,
}

impl EngineConnection {
    pub fn buf_reader(&self) -> Result<BufReader<TcpStream>> {
        Ok(BufReader::new(self.stream.try_clone()?))
    }

    pub fn writer(&self) -> Result<TcpStream> {
        Ok(self.stream.try_clone()?)
    }
}

#[derive(Debug)]
pub struct TcpEngineServer {
    listener: TcpListener,
    config: TcpServerConfig,
}

impl TcpEngineServer {
    pub fn bind(config: TcpServerConfig) -> Result<Self> {
        let listener = TcpListener::bind(config.bind_addr)
            .map_err(|err| anyhow::anyhow!("cannot bind TCP {}: {}", config.bind_addr, err))?;
        listener.set_nonblocking(true)?;
        Ok(Self { listener, config })
    }

    pub fn local_addr(&self) -> Result<SocketAddr> {
        Ok(self.listener.local_addr()?)
    }

    pub fn accept_blocking(&self) -> Result<EngineConnection> {
        self.accept_until(None)?
            .ok_or_else(|| anyhow::anyhow!("accept returned without timeout or connection"))
    }

    pub fn accept_timeout(&self, timeout: Duration) -> Result<Option<EngineConnection>> {
        self.accept_until(Some(Instant::now() + timeout))
    }

    fn accept_until(&self, deadline: Option<Instant>) -> Result<Option<EngineConnection>> {
        loop {
            match self.listener.accept() {
                Ok((stream, peer_addr)) => {
                    return Ok(Some(tune_stream(stream, peer_addr, &self.config)?))
                }
                Err(err) if err.kind() == std::io::ErrorKind::WouldBlock => {
                    if deadline.is_some_and(|deadline| Instant::now() >= deadline) {
                        return Ok(None);
                    }
                    thread::sleep(self.config.accept_poll_interval);
                }
                Err(err) => return Err(anyhow::anyhow!("accept failed: {}", err)),
            }
        }
    }
}

pub fn wait_for_connection(port: u16) -> Result<EngineConnection> {
    wait_for_connections(port, 1)?
        .pop()
        .ok_or_else(|| anyhow::anyhow!("no engine connection accepted"))
}

pub fn wait_for_connections(
    port: u16,
    expected_connections: usize,
) -> Result<Vec<EngineConnection>> {
    if expected_connections == 0 {
        return Ok(Vec::new());
    }

    let config = TcpServerConfig::localhost(port);
    let server = TcpEngineServer::bind(config)?;
    log_accept_banner(server.local_addr()?);
    let mut connections = Vec::with_capacity(expected_connections);
    while connections.len() < expected_connections {
        let connection = server.accept_blocking()?;
        log::info!("Engine adapter connected from {}", connection.peer_addr);
        connections.push(connection);
    }
    Ok(connections)
}

pub fn try_connect(port: u16, timeout_secs: u64) -> Result<Option<EngineConnection>> {
    Ok(try_connect_connections(port, 1, timeout_secs)?.pop())
}

pub fn try_connect_connections(
    port: u16,
    expected_connections: usize,
    timeout_secs: u64,
) -> Result<Vec<EngineConnection>> {
    if expected_connections == 0 {
        return Ok(Vec::new());
    }

    let config = TcpServerConfig::localhost(port);
    let server = TcpEngineServer::bind(config)?;
    log_accept_banner(server.local_addr()?);

    let deadline = Instant::now() + Duration::from_secs(timeout_secs);
    let mut connections = Vec::with_capacity(expected_connections);
    while connections.len() < expected_connections {
        let Some(remaining) = deadline.checked_duration_since(Instant::now()) else {
            break;
        };
        if remaining.is_zero() {
            break;
        }
        let Some(connection) = server.accept_timeout(remaining)? else {
            break;
        };
        log::info!("Engine adapter connected from {}", connection.peer_addr);
        connections.push(connection);
    }

    if connections.is_empty() {
        log::info!(
            "No engine connected after {}s; running headless",
            timeout_secs
        );
    } else if connections.len() < expected_connections {
        log::info!(
            "Accepted {}/{} engine adapters after {}s",
            connections.len(),
            expected_connections,
            timeout_secs
        );
    }
    Ok(connections)
}

fn tune_stream(
    stream: TcpStream,
    peer_addr: SocketAddr,
    config: &TcpServerConfig,
) -> Result<EngineConnection> {
    stream.set_nonblocking(false)?;
    stream.set_nodelay(config.nodelay)?;
    stream.set_write_timeout(Some(config.write_timeout))?;
    stream.set_read_timeout(config.read_timeout)?;
    Ok(EngineConnection {
        stream,
        peer_addr: peer_addr.to_string(),
        accepted_at: Instant::now(),
    })
}

fn log_accept_banner(addr: SocketAddr) {
    log::info!("Waiting for engine adapter on {} ...", addr);
    log::info!(
        "  Configure engine adapter host=127.0.0.1 port={}",
        addr.port()
    );
}
