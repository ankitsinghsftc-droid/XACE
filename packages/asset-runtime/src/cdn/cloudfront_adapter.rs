// ============================================================================
// packages/asset-runtime/src/cdn/cloudfront_adapter.rs
// ============================================================================

/*!
# cloudfront_adapter.rs — AWS CloudFront CDN Adapter

Fetches assets from a CloudFront distribution using HTTPS.

CloudFront provides:
    - Edge caching: assets cached at AWS PoPs globally
    - Automatic compression: Brotli/Gzip on supported MIME types
    - Range request support: HTTP 206 Partial Content

## URI Format

CloudFront URIs must be fully-qualified HTTPS URLs:
    `https://d1234567890.cloudfront.net/assets/mesh_v1.fbx`

Or relative paths (the `cloudfront_domain` from CdnConfig is prepended):
    `assets/mesh_v1.fbx` → `https://your-domain.cloudfront.net/assets/mesh_v1.fbx`

## Signed URLs (Optional)

Set `XACE_CDN_API_KEY` to enable signed URL auth (CloudFront + Lambda@Edge).
When set, the adapter adds an `Authorization: Bearer {key}` header.
For CloudFront signed URLs with key pairs, use the full pre-signed URL as the URI.
*/

use async_trait::async_trait;

use crate::cdn::cdn_adapter::{CdnError, CdnResult, ICdnAdapter};
use crate::cdn::range_request;

pub struct CloudFrontAdapter {
    client: reqwest::Client,
    base_url: String,
    api_key: Option<String>,
}

impl CloudFrontAdapter {
    /// Creates a CloudFront adapter from environment configuration.
    ///
    /// Required env vars:
    ///     XACE_CDN_BASE_URL   — CloudFront domain: "https://d1234.cloudfront.net"
    ///
    /// Optional:
    ///     XACE_CDN_API_KEY    — auth token for signed URL verification
    pub fn from_env() -> Result<Self, CdnError> {
        let base_url = std::env::var("XACE_CDN_BASE_URL").map_err(|_| {
            CdnError::AuthError(
                "XACE_CDN_BASE_URL not set. \
                 Export: XACE_CDN_BASE_URL=https://your-distribution.cloudfront.net"
                    .to_string(),
            )
        })?;

        let api_key = std::env::var("XACE_CDN_API_KEY").ok();

        Self::new(base_url, api_key)
    }

    pub fn new(base_url: impl Into<String>, api_key: Option<String>) -> Result<Self, CdnError> {
        let client = reqwest::Client::builder()
            .user_agent("xace-asset-runtime/0.1")
            .timeout(std::time::Duration::from_secs(60))
            .build()
            .map_err(|e| CdnError::Network(e.to_string()))?;

        let base = base_url.into().trim_end_matches('/').to_string();
        Ok(Self {
            client,
            base_url: base,
            api_key,
        })
    }

    fn resolve_url(&self, uri: &str) -> String {
        if uri.starts_with("https://") || uri.starts_with("http://") {
            uri.to_string()
        } else {
            format!("{}/{}", self.base_url, uri.trim_start_matches('/'))
        }
    }

    fn build_request(&self, method: reqwest::Method, url: &str) -> reqwest::RequestBuilder {
        let mut req = self.client.request(method, url);
        if let Some(key) = &self.api_key {
            req = req.header("Authorization", format!("Bearer {}", key));
        }
        req
    }
}

#[async_trait]
impl ICdnAdapter for CloudFrontAdapter {
    async fn fetch(&self, uri: &str, byte_range: Option<(u64, u64)>) -> CdnResult<Vec<u8>> {
        let url = self.resolve_url(uri);
        let mut req = self.build_request(reqwest::Method::GET, &url);

        if let Some((start, end)) = byte_range {
            req = req.header("Range", range_request::range_header(start, end));
        }

        let response = req
            .send()
            .await
            .map_err(|e| CdnError::Network(e.to_string()))?;

        let status = response.status();
        if status == 404 {
            return Err(CdnError::NotFound {
                uri: uri.to_string(),
            });
        }
        if status == 401 || status == 403 {
            return Err(CdnError::AuthError(format!(
                "CloudFront auth error (HTTP {}). Check XACE_CDN_API_KEY.",
                status
            )));
        }
        if !status.is_success() && status != 206 {
            let body = response.text().await.unwrap_or_default();
            return Err(CdnError::Http {
                status: status.as_u16(),
                body,
            });
        }

        response
            .bytes()
            .await
            .map(|b| b.to_vec())
            .map_err(|e| CdnError::Network(e.to_string()))
    }

    async fn content_length(&self, uri: &str) -> CdnResult<Option<u64>> {
        let url = self.resolve_url(uri);
        let req = self.build_request(reqwest::Method::HEAD, &url);
        let response = req
            .send()
            .await
            .map_err(|e| CdnError::Network(e.to_string()))?;

        if response.status() == 404 {
            return Err(CdnError::NotFound {
                uri: uri.to_string(),
            });
        }

        Ok(response.content_length())
    }

    fn adapter_name(&self) -> &'static str {
        "cloudfront"
    }
}
