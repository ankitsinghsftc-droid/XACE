// ============================================================================
// packages/asset-runtime/src/cdn/cdn_adapter.rs
// ============================================================================
/*!
# cdn_adapter.rs — ICdnAdapter Trait

Abstract interface for all CDN backends. Implementations:
    - `LocalCdnAdapter`   — local filesystem (dev, CI)
    - `S3Adapter`         — AWS S3 (production)
    - `CloudFrontAdapter` — AWS CloudFront (CDN edge caching)

## Credentials

Never from config files. Always from environment variables:
    AWS_ACCESS_KEY_ID
    AWS_SECRET_ACCESS_KEY
    AWS_DEFAULT_REGION     (default: us-east-1)
    XACE_CDN_BASE_URL      (generic CDN override)
    XACE_CDN_API_KEY       (generic CDN auth header)
*/

use async_trait::async_trait;
use thiserror::Error;

// ── Error ─────────────────────────────────────────────────────────────────────

#[derive(Debug, Error)]
pub enum CdnError {
    #[error("Not found: {uri}")]
    NotFound { uri: String },

    #[error("Auth error (check env vars): {0}")]
    AuthError(String),

    #[error("Network error: {0}")]
    Network(String),

    #[error("Invalid URI: {0}")]
    InvalidUri(String),

    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),

    #[error("HTTP {status}: {body}")]
    Http { status: u16, body: String },
}

pub type CdnResult<T> = Result<T, CdnError>;

// ── Config ────────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Default)]
pub struct CdnConfig {
    /// S3 bucket name (for S3Adapter)
    pub s3_bucket: Option<String>,
    /// AWS region (fallback if AWS_DEFAULT_REGION not set)
    pub aws_region: Option<String>,
    /// CloudFront distribution domain (for CloudFrontAdapter)
    pub cloudfront_domain: Option<String>,
    /// Base path for local CDN (for LocalCdnAdapter)
    pub local_root: Option<std::path::PathBuf>,
    /// Whether to use path-style S3 URLs (required for some S3-compatible services)
    pub s3_path_style: bool,
}

impl CdnConfig {
    /// Reads all configuration from environment variables.
    pub fn from_env() -> Self {
        Self {
            s3_bucket: std::env::var("XACE_S3_BUCKET").ok(),
            aws_region: std::env::var("AWS_DEFAULT_REGION").ok(),
            cloudfront_domain: std::env::var("XACE_CDN_BASE_URL").ok(),
            local_root: std::env::var("XACE_LOCAL_CDN_ROOT").ok().map(Into::into),
            s3_path_style: std::env::var("XACE_S3_PATH_STYLE")
                .map(|v| v == "1")
                .unwrap_or(false),
        }
    }
}

// ── ICdnAdapter ───────────────────────────────────────────────────────────────

/// Abstract CDN interface. All streaming operations go through this.
#[async_trait]
pub trait ICdnAdapter: Send + Sync {
    /// Fetches an asset by URI, returning raw bytes.
    ///
    /// `byte_range`: `Some((start, end))` for partial content (HTTP Range).
    /// `None` = fetch the entire asset.
    async fn fetch(&self, uri: &str, byte_range: Option<(u64, u64)>) -> CdnResult<Vec<u8>>;

    /// Returns the size of an asset without fetching its content.
    /// Uses a HEAD request or equivalent. Returns None if unsupported.
    async fn content_length(&self, uri: &str) -> CdnResult<Option<u64>>;

    /// Checks if an asset exists at the given URI.
    async fn exists(&self, uri: &str) -> bool {
        self.content_length(uri).await.is_ok()
    }

    /// Returns the adapter's name (for telemetry).
    fn adapter_name(&self) -> &'static str;
}
