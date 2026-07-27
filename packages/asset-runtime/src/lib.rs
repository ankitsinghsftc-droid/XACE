/*!
# XACE Asset Runtime

Runtime-critical asset operations: async streaming, CDN loading, hot-reload.

## Language Boundary

```text
packages/asset-registry/  (Python) — authoring time
    asset_manifest.py       — writes manifests
    asset_validator.py      — validates AssetReference status
    animation_contract.py   — generates contracts from COMP_ANIMATION_V2

packages/asset-runtime/   (Rust)  — runtime critical
    streaming/              — async priority-queue streaming
    cdn/                    — S3, CloudFront, local CDN adapters
    hot_reload/             — file watcher → tick-boundary gate → mutation
```

Python writes `asset_manifest.json`. Rust reads it at startup, then streams
and hot-reloads assets independently.

## Hot-Reload Determinism Contract

All hot-reload events flow through `tick_boundary_gate.rs`:

1. File watcher fires on change (background thread)
2. `reload_coordinator` enqueues a `ReloadRequest` with SHA-256 content hash
3. At tick START, Phase Orchestrator calls `tick_boundary_gate.drain()`
4. Each `ReloadRequest` becomes a mutation through the Mutation Gate
5. `AssetReference.version` updates atomically as part of the tick's mutation pass
6. All simulation peers receive the same reload event via the input stream
7. All peers compute the same content hash → identical `AssetReference.version`

Result: hot-reload is deterministic and replay-safe. No engine system sees
a partially-loaded asset.

## CDN Credentials

Loaded from environment variables only. Never from config files.
```text
AWS_ACCESS_KEY_ID         — S3 and CloudFront
AWS_SECRET_ACCESS_KEY     — S3 and CloudFront
AWS_DEFAULT_REGION        — S3 region (default: us-east-1)
XACE_CDN_BASE_URL         — Generic CDN base URL override
XACE_CDN_API_KEY          — Generic CDN auth header value
```
*/

pub mod cdn;
pub mod hot_reload;
pub mod streaming;

// ── Public Re-exports ─────────────────────────────────────────────────────────

pub use cdn::cdn_adapter::{CdnConfig, CdnError, ICdnAdapter};
pub use cdn::local_cdn_adapter::LocalCdnAdapter;
pub use cdn::s3_adapter::S3Adapter;
pub use hot_reload::reload_coordinator::{ReloadCoordinator, ReloadEvent};
pub use hot_reload::tick_boundary_gate::{ReloadRequest, TickBoundaryGate};
pub use hot_reload::version_hasher::VersionHasher;
pub use streaming::asset_streamer::{AssetStreamer, StreamerConfig};
pub use streaming::load_request::{LoadPriority, LoadRequest};
pub use streaming::load_result::{AssetBytes, LoadResult};

// ── Asset Error ───────────────────────────────────────────────────────────────

use thiserror::Error;

#[derive(Debug, Error)]
pub enum AssetRuntimeError {
    #[error("CDN error: {0}")]
    Cdn(#[from] CdnError),

    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),

    #[error("Asset not found: {asset_id}")]
    NotFound { asset_id: String },

    #[error("Hash mismatch: expected {expected}, got {actual}")]
    HashMismatch { expected: String, actual: String },

    #[error("Buffer too small: need {needed} bytes, capacity {capacity}")]
    BufferTooSmall { needed: usize, capacity: usize },

    #[error("Hot-reload error: {0}")]
    HotReload(String),

    #[error("Serialisation error: {0}")]
    Serde(#[from] serde_json::Error),
}

pub type Result<T> = std::result::Result<T, AssetRuntimeError>;

// ── Asset Reference ───────────────────────────────────────────────────────────
// Mirrors the Python-side AssetReference. Rust uses this to identify assets
// during streaming and hot-reload. The authoritative definition is in
// packages/asset-registry/src/asset_reference.py.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct AssetId(pub String);

impl AssetId {
    pub fn new(id: impl Into<String>) -> Self {
        Self(id.into())
    }
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl std::fmt::Display for AssetId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum AssetStatus {
    Placeholder,
    Linked,
    Missing,
    Unresolved,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AssetRef {
    pub id: AssetId,
    pub asset_type: String,
    pub status: AssetStatus,
    pub content_hash: Option<String>, // SHA-256 hex; set after load
    pub version: u32,                 // incremented on each hot-reload
}
