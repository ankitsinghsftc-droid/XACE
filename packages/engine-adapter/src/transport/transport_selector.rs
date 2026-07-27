//! Loading and validating engine-adapter transport configuration.

use std::net::{IpAddr, SocketAddr};
use std::path::{Path, PathBuf};
use std::time::Duration;

use serde::{Deserialize, Serialize};

use crate::transport::shm_transport::{ShmTransportConfig, DEFAULT_RING_SIZE};
use crate::transport::tcp_transport::TcpTransportConfig;
use crate::transport_mode::TransportMode;

pub const ENGINE_CONFIG_FILE: &str = "engine_config.yaml";
pub const ENV_TRANSPORT: &str = "XACE_TRANSPORT";
pub const ENV_TCP_HOST: &str = "XACE_TCP_HOST";
pub const ENV_TCP_PORT: &str = "XACE_TCP_PORT";
pub const ENV_SHM_NAME: &str = "XACE_SHM_NAME";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct EngineConfig {
    #[serde(default)]
    pub transport: TransportMode,
    #[serde(default)]
    pub tcp: TcpConfig,
    #[serde(default)]
    pub ffi: FfiConfig,
    #[serde(default)]
    pub shm: ShmConfig,
}

impl Default for EngineConfig {
    fn default() -> Self {
        Self {
            transport: TransportMode::Tcp,
            tcp: TcpConfig::default(),
            ffi: FfiConfig::default(),
            shm: ShmConfig::default(),
        }
    }
}

impl EngineConfig {
    pub fn validate(&self) -> Result<(), ConfigError> {
        self.tcp.validate()?;
        self.ffi.validate()?;
        self.shm.validate()?;
        Ok(())
    }

    pub fn tcp_bind_address(&self) -> String {
        format!("{}:{}", self.tcp.host, self.tcp.port)
    }

    pub fn tcp_socket_addr(&self) -> Result<SocketAddr, ConfigError> {
        self.tcp_bind_address()
            .parse()
            .map_err(|_| ConfigError::InvalidValue {
                field: "tcp.host/tcp.port",
                detail: format!(
                    "'{}' is not a valid socket address",
                    self.tcp_bind_address()
                ),
            })
    }

    pub fn to_tcp_transport_config(&self) -> TcpTransportConfig {
        TcpTransportConfig {
            bind_address: self.tcp_bind_address(),
            accept_timeout: Some(Duration::from_millis(self.tcp.accept_timeout_ms)),
            no_delay: self.tcp.no_delay,
            send_buffer_size: Some(self.tcp.send_buffer_bytes),
            recv_buffer_size: Some(self.tcp.recv_buffer_bytes),
            write_timeout: Some(Duration::from_millis(self.tcp.write_timeout_ms)),
            engine_name: self.tcp.engine_name.clone(),
            read_chunk_size: self.tcp.read_chunk_bytes,
        }
    }

    pub fn to_shm_transport_config(&self) -> ShmTransportConfig {
        ShmTransportConfig {
            world_id: self.shm.segment_name.clone(),
            ring_size: self.shm.segment_size as usize,
            shm_dir: PathBuf::from(&self.shm.directory),
            unlink_on_close: self.shm.unlink_on_close,
            engine_name: self.tcp.engine_name.clone(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct TcpConfig {
    #[serde(default = "default_tcp_host")]
    pub host: String,
    #[serde(default = "default_tcp_port")]
    pub port: u16,
    #[serde(default = "default_true")]
    pub no_delay: bool,
    #[serde(default = "default_accept_timeout_ms")]
    pub accept_timeout_ms: u64,
    #[serde(default = "default_write_timeout_ms")]
    pub write_timeout_ms: u64,
    #[serde(default = "default_socket_buffer_bytes")]
    pub send_buffer_bytes: usize,
    #[serde(default = "default_socket_buffer_bytes")]
    pub recv_buffer_bytes: usize,
    #[serde(default = "default_read_chunk_bytes")]
    pub read_chunk_bytes: usize,
    #[serde(default = "default_engine_name")]
    pub engine_name: String,
}

impl Default for TcpConfig {
    fn default() -> Self {
        Self {
            host: default_tcp_host(),
            port: default_tcp_port(),
            no_delay: true,
            accept_timeout_ms: default_accept_timeout_ms(),
            write_timeout_ms: default_write_timeout_ms(),
            send_buffer_bytes: default_socket_buffer_bytes(),
            recv_buffer_bytes: default_socket_buffer_bytes(),
            read_chunk_bytes: default_read_chunk_bytes(),
            engine_name: default_engine_name(),
        }
    }
}

impl TcpConfig {
    pub fn validate(&self) -> Result<(), ConfigError> {
        if self.host.trim().is_empty() {
            return Err(ConfigError::InvalidValue {
                field: "tcp.host",
                detail: "host must not be empty".to_string(),
            });
        }
        let _ip: IpAddr = self.host.parse().map_err(|_| ConfigError::InvalidValue {
            field: "tcp.host",
            detail: format!("'{}' is not a valid IP address", self.host),
        })?;
        if self.port == 0 {
            return Err(ConfigError::InvalidValue {
                field: "tcp.port",
                detail: "port 0 is allowed in tests but not in adapter config".to_string(),
            });
        }
        if self.read_chunk_bytes < 1024 {
            return Err(ConfigError::InvalidValue {
                field: "tcp.read_chunk_bytes",
                detail: "read chunk must be at least 1024 bytes".to_string(),
            });
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct FfiConfig {
    #[serde(default = "default_delta_buf")]
    pub delta_buffer_bytes: u32,
}

impl Default for FfiConfig {
    fn default() -> Self {
        Self {
            delta_buffer_bytes: default_delta_buf(),
        }
    }
}

impl FfiConfig {
    pub fn validate(&self) -> Result<(), ConfigError> {
        if self.delta_buffer_bytes < 64 * 1024 {
            return Err(ConfigError::InvalidValue {
                field: "ffi.delta_buffer_bytes",
                detail: "buffer must be at least 64 KiB".to_string(),
            });
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ShmConfig {
    #[serde(default = "default_shm_name")]
    pub segment_name: String,
    #[serde(default = "default_shm_size")]
    pub segment_size: u64,
    #[serde(default = "default_shm_dir")]
    pub directory: String,
    #[serde(default = "default_true")]
    pub unlink_on_close: bool,
}

impl Default for ShmConfig {
    fn default() -> Self {
        Self {
            segment_name: default_shm_name(),
            segment_size: default_shm_size(),
            directory: default_shm_dir(),
            unlink_on_close: true,
        }
    }
}

impl ShmConfig {
    pub fn validate(&self) -> Result<(), ConfigError> {
        if self.segment_name.trim().is_empty() {
            return Err(ConfigError::InvalidValue {
                field: "shm.segment_name",
                detail: "segment name must not be empty".to_string(),
            });
        }
        if self.segment_size < 64 * 1024 {
            return Err(ConfigError::InvalidValue {
                field: "shm.segment_size",
                detail: "segment size must be at least 64 KiB".to_string(),
            });
        }
        if !(self.segment_size as usize).is_power_of_two() {
            return Err(ConfigError::InvalidValue {
                field: "shm.segment_size",
                detail: "segment size must be a power of two".to_string(),
            });
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ConfigError {
    Io { path: PathBuf, detail: String },
    Parse { path: PathBuf, detail: String },
    InvalidValue { field: &'static str, detail: String },
}

impl std::fmt::Display for ConfigError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io { path, detail } => {
                write!(f, "failed to read config '{}': {}", path.display(), detail)
            }
            Self::Parse { path, detail } => {
                write!(f, "failed to parse config '{}': {}", path.display(), detail)
            }
            Self::InvalidValue { field, detail } => {
                write!(f, "invalid config value '{}': {}", field, detail)
            }
        }
    }
}

impl std::error::Error for ConfigError {}

pub struct TransportSelector;

impl TransportSelector {
    /// Legacy forgiving loader: defaults to TCP when the file is absent or invalid.
    pub fn load(config_dir: impl AsRef<Path>) -> EngineConfig {
        Self::load_result(config_dir).unwrap_or_default()
    }

    pub fn load_result(config_dir: impl AsRef<Path>) -> Result<EngineConfig, ConfigError> {
        let path = config_dir.as_ref().join(ENGINE_CONFIG_FILE);
        if !path.exists() {
            return Ok(EngineConfig::default());
        }

        let raw = std::fs::read_to_string(&path).map_err(|err| ConfigError::Io {
            path: path.clone(),
            detail: err.to_string(),
        })?;
        let config: EngineConfig =
            serde_yaml::from_str(&raw).map_err(|err| ConfigError::Parse {
                path,
                detail: err.to_string(),
            })?;
        config.validate()?;
        Ok(config)
    }

    pub fn from_env_or_config(config_dir: impl AsRef<Path>) -> EngineConfig {
        Self::from_env_or_config_result(config_dir).unwrap_or_default()
    }

    pub fn from_env_or_config_result(
        config_dir: impl AsRef<Path>,
    ) -> Result<EngineConfig, ConfigError> {
        let mut config = Self::load_result(config_dir)?;
        Self::apply_env_overrides(&mut config)?;
        config.validate()?;
        Ok(config)
    }

    pub fn apply_env_overrides(config: &mut EngineConfig) -> Result<(), ConfigError> {
        if let Ok(value) = std::env::var(ENV_TRANSPORT) {
            config.transport =
                value
                    .parse::<TransportMode>()
                    .map_err(|err| ConfigError::InvalidValue {
                        field: ENV_TRANSPORT,
                        detail: err.to_string(),
                    })?;
        }
        if let Ok(value) = std::env::var(ENV_TCP_HOST) {
            config.tcp.host = value;
        }
        if let Ok(value) = std::env::var(ENV_TCP_PORT) {
            config.tcp.port = value.parse().map_err(|_| ConfigError::InvalidValue {
                field: ENV_TCP_PORT,
                detail: format!("'{}' is not a valid TCP port", value),
            })?;
        }
        if let Ok(value) = std::env::var(ENV_SHM_NAME) {
            config.shm.segment_name = value;
        }
        Ok(())
    }
}

fn default_tcp_host() -> String {
    "127.0.0.1".to_string()
}

fn default_tcp_port() -> u16 {
    7777
}

fn default_true() -> bool {
    true
}

fn default_accept_timeout_ms() -> u64 {
    30_000
}

fn default_write_timeout_ms() -> u64 {
    100
}

fn default_socket_buffer_bytes() -> usize {
    256 * 1024
}

fn default_read_chunk_bytes() -> usize {
    64 * 1024
}

fn default_engine_name() -> String {
    "EngineAdapter".to_string()
}

fn default_delta_buf() -> u32 {
    4 * 1024 * 1024
}

fn default_shm_name() -> String {
    "default".to_string()
}

fn default_shm_size() -> u64 {
    DEFAULT_RING_SIZE as u64
}

fn default_shm_dir() -> String {
    std::env::temp_dir().to_string_lossy().to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn missing_config_defaults_to_tcp() {
        let dir = tempfile::tempdir().unwrap();
        let config = TransportSelector::load_result(dir.path()).unwrap();
        assert_eq!(config.transport, TransportMode::Tcp);
        assert_eq!(config.tcp.port, 7777);
    }

    #[test]
    fn parses_yaml_config() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(
            dir.path().join(ENGINE_CONFIG_FILE),
            "transport: shm\nshm:\n  segment_name: world_a\n  segment_size: 1048576\n",
        )
        .unwrap();

        let config = TransportSelector::load_result(dir.path()).unwrap();
        assert_eq!(config.transport, TransportMode::Shm);
        assert_eq!(config.shm.segment_name, "world_a");
    }

    #[test]
    fn validates_bad_values() {
        let mut config = EngineConfig::default();
        config.shm.segment_size = 1000;
        assert!(config.validate().is_err());
    }

    #[test]
    fn tcp_transport_config_uses_selected_endpoint() {
        let mut config = EngineConfig::default();
        config.tcp.host = "127.0.0.1".to_string();
        config.tcp.port = 7788;
        let tcp = config.to_tcp_transport_config();
        assert_eq!(tcp.bind_address, "127.0.0.1:7788");
    }
}
