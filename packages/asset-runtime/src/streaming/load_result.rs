// ============================================================================
// packages/asset-runtime/src/streaming/load_result.rs
// ============================================================================

/*!
# load_result.rs — Asset Load Result

The result produced by the streamer after a load request completes.
Carries the raw bytes, the computed SHA-256 hash, and metadata needed
to route the result back to the requesting ECS component.
*/

use crate::AssetId;

/// Raw asset bytes with metadata.
#[derive(Debug, Clone)]
pub struct AssetBytes {
    /// The asset bytes.
    pub data: Vec<u8>,
    /// SHA-256 hex of `data`. Computed by the streamer, verified against expected.
    pub content_hash: String,
    /// Size in bytes.
    pub size_bytes: usize,
    /// MIME type if known from CDN response headers.
    pub mime_type: Option<String>,
}

impl AssetBytes {
    pub fn new(data: Vec<u8>, content_hash: String) -> Self {
        let size = data.len();
        Self {
            data,
            content_hash,
            size_bytes: size,
            mime_type: None,
        }
    }

    pub fn is_empty(&self) -> bool {
        self.data.is_empty()
    }
}

/// Outcome of one streaming load request.
#[derive(Debug)]
pub enum LoadOutcome {
    /// Asset loaded successfully.
    Success(AssetBytes),
    /// CDN/network error — caller may retry or substitute a placeholder.
    NetworkError(String),
    /// Hash mismatch — asset bytes do not match the expected hash.
    HashMismatch { expected: String, actual: String },
    /// Asset not found at the source URI.
    NotFound,
    /// Load was cancelled (e.g. entity was destroyed before load completed).
    Cancelled,
}

/// Complete result of a streaming load request.
#[derive(Debug)]
pub struct LoadResult {
    pub asset_id: AssetId,
    pub outcome: LoadOutcome,
    /// How long the load took (ms).
    pub duration_ms: u64,
    /// Original request priority, echoed for telemetry.
    pub priority: crate::streaming::load_request::LoadPriority,
    /// Which entity + component requested this asset (for mutation routing).
    pub requester_type_id: Option<u32>,
    pub requester_entity_id: Option<u64>,
}

impl LoadResult {
    pub fn success(
        request: &crate::streaming::load_request::LoadRequest,
        bytes: AssetBytes,
        duration: std::time::Duration,
    ) -> Self {
        Self {
            asset_id: request.asset_id.clone(),
            outcome: LoadOutcome::Success(bytes),
            duration_ms: duration.as_millis() as u64,
            priority: request.priority,
            requester_type_id: request.requester_type_id,
            requester_entity_id: request.requester_entity_id,
        }
    }

    pub fn error(
        request: &crate::streaming::load_request::LoadRequest,
        msg: String,
        duration: std::time::Duration,
    ) -> Self {
        Self {
            asset_id: request.asset_id.clone(),
            outcome: LoadOutcome::NetworkError(msg),
            duration_ms: duration.as_millis() as u64,
            priority: request.priority,
            requester_type_id: request.requester_type_id,
            requester_entity_id: request.requester_entity_id,
        }
    }

    pub fn is_success(&self) -> bool {
        matches!(self.outcome, LoadOutcome::Success(_))
    }

    pub fn bytes(&self) -> Option<&AssetBytes> {
        if let LoadOutcome::Success(ref b) = self.outcome {
            Some(b)
        } else {
            None
        }
    }
}
