// ============================================================================
// packages/asset-runtime/src/streaming/load_request.rs
// ============================================================================
/*!
# load_request.rs — Asset Load Request
 
Describes one asset load request submitted to the `AssetStreamer`.
Priority determines the order in which pending requests are dispatched.
*/
 
use std::cmp::Ordering;
use std::time::Instant;
 
use serde::{Deserialize, Serialize};
 
use crate::AssetId;
 
 
// ── Priority ──────────────────────────────────────────────────────────────────
 
/// Load priority for the streaming queue.
///
/// Higher priority = dispatched sooner. Ordering is:
///     Critical > Player > Environment > Background > Preload
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[repr(u8)]
pub enum LoadPriority {
    /// Deferred preloading of assets unlikely to be needed soon.
    Preload     = 0,
    /// Background terrain, foliage, distant objects.
    Background  = 1,
    /// Environment assets in the active scene area.
    Environment = 2,
    /// Player character, player HUD, direct gameplay assets.
    Player      = 3,
    /// Required immediately — streaming will block if not ready.
    Critical    = 4,
}
 
impl LoadPriority {
    pub fn is_blocking(self) -> bool {
        self == Self::Critical
    }
}
 
impl std::fmt::Display for LoadPriority {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let s = match self {
            Self::Critical    => "CRITICAL",
            Self::Player      => "PLAYER",
            Self::Environment => "ENVIRONMENT",
            Self::Background  => "BACKGROUND",
            Self::Preload     => "PRELOAD",
        };
        write!(f, "{}", s)
    }
}
 
 
// ── Load Request ──────────────────────────────────────────────────────────────
 
/// One asset load request submitted to the streaming queue.
#[derive(Debug, Clone)]
pub struct LoadRequest {
    /// Asset identifier (matches AssetReference.id from Python asset-registry).
    pub asset_id:       AssetId,
 
    /// Where to fetch the asset from (CDN URL, S3 key, or local path).
    pub source_uri:     String,
 
    /// Expected SHA-256 hash of the asset content.
    /// When provided, the streamer validates the downloaded bytes against this hash.
    /// None = skip hash validation (used for placeholder loads).
    pub expected_hash:  Option<String>,
 
    /// Byte range for partial loading (range requests).
    /// None = load the entire asset.
    pub byte_range:     Option<(u64, u64)>,
 
    /// Load priority in the queue.
    pub priority:       LoadPriority,
 
    /// When the request was enqueued. Used to break priority ties (FIFO within tier).
    pub enqueued_at:    Instant,
 
    /// Component type_id that needs this asset (for mutation routing after load).
    pub requester_type_id: Option<u32>,
 
    /// Entity ID that needs this asset (for mutation routing after load).
    pub requester_entity_id: Option<u64>,
}
 
impl LoadRequest {
    pub fn new(asset_id: impl Into<String>, source_uri: impl Into<String>) -> Self {
        Self {
            asset_id:             AssetId::new(asset_id),
            source_uri:           source_uri.into(),
            expected_hash:        None,
            byte_range:           None,
            priority:             LoadPriority::Background,
            enqueued_at:          Instant::now(),
            requester_type_id:    None,
            requester_entity_id:  None,
        }
    }
 
    pub fn with_priority(mut self, p: LoadPriority) -> Self {
        self.priority = p; self
    }
 
    pub fn with_expected_hash(mut self, h: impl Into<String>) -> Self {
        self.expected_hash = Some(h.into()); self
    }
 
    pub fn with_byte_range(mut self, start: u64, end: u64) -> Self {
        self.byte_range = Some((start, end)); self
    }
 
    pub fn with_requester(mut self, type_id: u32, entity_id: u64) -> Self {
        self.requester_type_id    = Some(type_id);
        self.requester_entity_id  = Some(entity_id);
        self
    }
 
    pub fn age_ms(&self) -> u128 {
        self.enqueued_at.elapsed().as_millis()
    }
}
 
// BinaryHeap uses max-heap → higher priority + earlier enqueue = pops first
impl PartialEq for LoadRequest {
    fn eq(&self, other: &Self) -> bool {
        self.priority == other.priority && self.enqueued_at == other.enqueued_at
    }
}
 
impl Eq for LoadRequest {}
 
impl PartialOrd for LoadRequest {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}
 
impl Ord for LoadRequest {
    fn cmp(&self, other: &Self) -> Ordering {
        // Higher priority wins; tie-break: earlier enqueued time (FIFO within tier)
        self.priority.cmp(&other.priority)
            .then_with(|| other.enqueued_at.cmp(&self.enqueued_at))
    }
}