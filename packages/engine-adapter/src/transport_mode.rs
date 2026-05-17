// ============================================================================
// packages/engine-adapter/src/transport_mode.rs
// ============================================================================
 
/*!
# transport_mode.rs — Transport Mode Enum
 
Selects the engine adapter transport: TCP, SHM, or FFI.
 
Transport is selected once at world initialization and cannot change.
Runtime Core (Phases 2–6) never sees this enum — it speaks only to
IEngineAdapter and is transport-agnostic.
*/
 
use serde::{Deserialize, Serialize};
 
/// Engine adapter transport mode.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum TransportMode {
    /// TCP socket transport. Engine adapter is a separate process.
    /// Default — works across process boundaries and machines.
    #[default]
    Tcp,
 
    /// Shared memory transport. Engine and XACE in separate processes on same host.
    /// Higher throughput than TCP; lower latency. Linux/macOS only.
    Shm,
 
    /// C FFI transport. Engine calls directly into the XACE shared library.
    /// Lowest latency — no IPC. Used when XACE is embedded in the engine process.
    /// Requires the `cdylib` build artifact (XaceEmbedded.dll / libxace.so).
    Ffi,
}
 
impl TransportMode {
    pub fn from_str(s: &str) -> Option<Self> {
        match s.to_lowercase().as_str() {
            "tcp" => Some(Self::Tcp),
            "shm" => Some(Self::Shm),
            "ffi" => Some(Self::Ffi),
            _     => None,
        }
    }
 
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Tcp => "tcp",
            Self::Shm => "shm",
            Self::Ffi => "ffi",
        }
    }
 
    /// True when XACE and the engine share the same process (FFI mode).
    pub fn is_embedded(self) -> bool { self == Self::Ffi }
 
    /// True when XACE and the engine communicate via network/IPC.
    pub fn is_external(self) -> bool { !self.is_embedded() }
}
 
impl std::fmt::Display for TransportMode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.as_str())
    }
}