//! Engine-adapter transport mode selection.
//!
//! The mode is chosen at adapter startup and treated as stable for the lifetime
//! of a world connection. Runtime systems should depend on the adapter contract,
//! not on this enum directly.

use std::str::FromStr;

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum TransportMode {
    #[default]
    Tcp,
    Shm,
    Ffi,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TransportModeParseError {
    value: String,
}

impl TransportMode {
    pub const ALL: [TransportMode; 3] =
        [TransportMode::Tcp, TransportMode::Shm, TransportMode::Ffi];

    pub fn parse(value: &str) -> Result<Self, TransportModeParseError> {
        value.parse()
    }

    /// Legacy helper retained for existing call sites.
    pub fn from_str(value: &str) -> Option<Self> {
        value.parse().ok()
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Tcp => "tcp",
            Self::Shm => "shm",
            Self::Ffi => "ffi",
        }
    }

    pub fn display_name(self) -> &'static str {
        match self {
            Self::Tcp => "TCP",
            Self::Shm => "Shared Memory",
            Self::Ffi => "Embedded FFI",
        }
    }

    pub fn is_embedded(self) -> bool {
        self == Self::Ffi
    }

    pub fn is_external(self) -> bool {
        !self.is_embedded()
    }

    pub fn is_ipc(self) -> bool {
        matches!(self, Self::Tcp | Self::Shm)
    }

    pub fn supports_remote_host(self) -> bool {
        self == Self::Tcp
    }

    pub fn supports_same_machine_only(self) -> bool {
        matches!(self, Self::Shm | Self::Ffi)
    }
}

impl FromStr for TransportMode {
    type Err = TransportModeParseError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        let normalized = value
            .trim()
            .replace(['-', '_', ' '], "")
            .to_ascii_lowercase();
        match normalized.as_str() {
            "tcp" | "socket" | "sockets" => Ok(Self::Tcp),
            "shm" | "sharedmemory" | "sharedmem" => Ok(Self::Shm),
            "ffi" | "embedded" | "inprocess" | "native" => Ok(Self::Ffi),
            _ => Err(TransportModeParseError {
                value: value.to_string(),
            }),
        }
    }
}

impl std::fmt::Display for TransportMode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

impl std::fmt::Display for TransportModeParseError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "unknown transport mode '{}'; expected tcp, shm, or ffi",
            self.value
        )
    }
}

impl std::error::Error for TransportModeParseError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_canonical_and_alias_names() {
        assert_eq!("tcp".parse::<TransportMode>().unwrap(), TransportMode::Tcp);
        assert_eq!(
            "shared-memory".parse::<TransportMode>().unwrap(),
            TransportMode::Shm
        );
        assert_eq!(
            "in_process".parse::<TransportMode>().unwrap(),
            TransportMode::Ffi
        );
    }

    #[test]
    fn serde_uses_lowercase_names() {
        assert_eq!(
            serde_json::to_string(&TransportMode::Shm).unwrap(),
            "\"shm\""
        );
        assert_eq!(
            serde_json::from_str::<TransportMode>("\"ffi\"").unwrap(),
            TransportMode::Ffi
        );
    }

    #[test]
    fn capability_helpers_are_explicit() {
        assert!(TransportMode::Tcp.supports_remote_host());
        assert!(TransportMode::Shm.supports_same_machine_only());
        assert!(TransportMode::Ffi.is_embedded());
        assert!(TransportMode::Tcp.is_ipc());
    }
}
