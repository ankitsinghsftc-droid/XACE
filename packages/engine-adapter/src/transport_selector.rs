// ============================================================================
// packages/engine-adapter/src/transport_selector.rs
// ============================================================================
 
/*!
# transport_selector.rs — Transport Selection from Config
 
Reads `engine_config.yaml` and selects the appropriate transport mode.
 
## engine_config.yaml Format
 
```yaml
transport: ffi       # tcp | shm | ffi
tcp:
  host: "127.0.0.1"
  port: 7878
ffi:
  delta_buffer_bytes: 4194304   # 4 MB
shm:
  segment_name: "xace_shm"
  segment_size: 8388608         # 8 MB
```
*/
 
use std::path::Path;
 
use serde::{Deserialize, Serialize};
 
use crate::transport_mode::TransportMode;
 
 
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EngineConfig {
    #[serde(default)]
    pub transport: TransportMode,
    #[serde(default)]
    pub tcp:       TcpConfig,
    #[serde(default)]
    pub ffi:       FfiConfig,
    #[serde(default)]
    pub shm:       ShmConfig,
}
 
impl Default for EngineConfig {
    fn default() -> Self {
        Self {
            transport: TransportMode::Tcp,
            tcp:       TcpConfig::default(),
            ffi:       FfiConfig::default(),
            shm:       ShmConfig::default(),
        }
    }
}
 
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TcpConfig {
    #[serde(default = "default_tcp_host")]
    pub host: String,
    #[serde(default = "default_tcp_port")]
    pub port: u16,
}
 
impl Default for TcpConfig {
    fn default() -> Self {
        Self { host: "127.0.0.1".to_string(), port: 7878 }
    }
}
 
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FfiConfig {
    #[serde(default = "default_delta_buf")]
    pub delta_buffer_bytes: u32,
}
 
impl Default for FfiConfig {
    fn default() -> Self {
        Self { delta_buffer_bytes: 4 * 1024 * 1024 }   // 4 MB
    }
}
 
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ShmConfig {
    #[serde(default = "default_shm_name")]
    pub segment_name: String,
    #[serde(default = "default_shm_size")]
    pub segment_size: u64,
}
 
impl Default for ShmConfig {
    fn default() -> Self {
        Self { segment_name: "xace_shm".to_string(), segment_size: 8 * 1024 * 1024 }
    }
}
 
fn default_tcp_host() -> String { "127.0.0.1".to_string() }
fn default_tcp_port() -> u16    { 7878 }
fn default_delta_buf() -> u32   { 4 * 1024 * 1024 }
fn default_shm_name() -> String { "xace_shm".to_string() }
fn default_shm_size() -> u64    { 8 * 1024 * 1024 }
 
 
pub struct TransportSelector;
 
impl TransportSelector {
    /// Loads engine_config.yaml from `config_dir` and returns the config.
    /// Falls back to default (TCP) if the file is missing or malformed.
    pub fn load(config_dir: impl AsRef<Path>) -> EngineConfig {
        let path = config_dir.as_ref().join("engine_config.yaml");
        if !path.exists() {
            return EngineConfig::default();
        }
        std::fs::read_to_string(&path)
            .ok()
            .and_then(|s| serde_yaml::from_str(&s).ok())
            .unwrap_or_default()
    }
 
    /// Selects transport mode from an environment variable override.
    /// `XACE_TRANSPORT=ffi|tcp|shm` takes precedence over the config file.
    pub fn from_env_or_config(config_dir: impl AsRef<Path>) -> EngineConfig {
        let mut config = Self::load(config_dir);
        if let Ok(val) = std::env::var("XACE_TRANSPORT") {
            if let Some(mode) = TransportMode::from_str(&val) {
                config.transport = mode;
            }
        }
        config
    }
}