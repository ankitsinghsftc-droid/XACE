// ============================================================================
// packages/asset-runtime/src/cdn/s3_adapter.rs
// ============================================================================
/*!
# s3_adapter.rs — AWS S3 CDN Adapter
 
Fetches assets from AWS S3 using the official `aws-sdk-s3` Rust SDK.
Credentials are read exclusively from environment variables:
 
    AWS_ACCESS_KEY_ID       — required
    AWS_SECRET_ACCESS_KEY   — required
    AWS_DEFAULT_REGION      — optional, default: us-east-1
    AWS_SESSION_TOKEN       — optional, for STS temporary credentials
    XACE_S3_BUCKET          — required for S3Adapter
 
## URI Format
 
S3 URIs must be one of:
    `s3://bucket-name/path/to/asset.fbx`       — explicit bucket+key
    `s3://path/to/asset.fbx`                   — uses configured bucket
    `path/to/asset.fbx`                        — relative key in configured bucket
 
## Range Requests
 
S3 native range requests via the `Range` header in GetObject.
Used by AssetStreamer for progressive loading of large assets.
*/
 
use async_trait::async_trait;
use aws_sdk_s3::primitives::ByteStream;
use aws_sdk_s3::Client as S3Client;
 
use crate::cdn::cdn_adapter::{CdnConfig, CdnError, CdnResult, ICdnAdapter};
use crate::cdn::range_request;
 
 
pub struct S3Adapter {
    client: S3Client,
    bucket: String,
}
 
impl S3Adapter {
    /// Creates an S3 adapter using credentials from environment variables.
    ///
    /// Credentials are loaded by the AWS SDK in standard order:
    ///     1. Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
    ///     2. ~/.aws/credentials
    ///     3. EC2/ECS instance metadata (in production)
    ///
    /// Never pass credentials as arguments — use environment variables.
    pub async fn from_env(config: &CdnConfig) -> Result<Self, CdnError> {
        let bucket = config.s3_bucket.clone().ok_or_else(|| {
            CdnError::AuthError(
                "XACE_S3_BUCKET not set. Export: XACE_S3_BUCKET=your-bucket-name".to_string()
            )
        })?;
 
        let region = config.aws_region.clone()
            .unwrap_or_else(|| "us-east-1".to_string());
 
        let sdk_config = aws_config::defaults(
            aws_config::BehaviorVersion::latest()
        )
        .region(aws_config::Region::new(region))
        .load()
        .await;
 
        let mut builder = aws_sdk_s3::config::Builder::from(&sdk_config);
        if config.s3_path_style {
            builder = builder.force_path_style(true);
        }
 
        let client = S3Client::from_conf(builder.build());
        Ok(Self { client, bucket })
    }
 
    fn parse_key<'a>(&self, uri: &'a str) -> &'a str {
        // Strip "s3://bucket/" prefix or "s3://" prefix
        if let Some(rest) = uri.strip_prefix("s3://") {
            // Could be "bucket/key" or "key"
            if rest.contains('/') {
                let slash = rest.find('/').unwrap();
                return &rest[slash + 1..];
            }
            return rest;
        }
        // Plain key
        uri
    }
}
 
#[async_trait]
impl ICdnAdapter for S3Adapter {
    async fn fetch(
        &self,
        uri:        &str,
        byte_range: Option<(u64, u64)>,
    ) -> CdnResult<Vec<u8>> {
        let key = self.parse_key(uri);
 
        let mut request = self.client
            .get_object()
            .bucket(&self.bucket)
            .key(key);
 
        if let Some((start, end)) = byte_range {
            request = request.range(range_request::range_header(start, end));
        }
 
        let response = request.send().await.map_err(|e| {
            let msg = e.to_string();
            if msg.contains("NoSuchKey") || msg.contains("404") {
                CdnError::NotFound { uri: uri.to_string() }
            } else if msg.contains("credentials") || msg.contains("401") || msg.contains("403") {
                CdnError::AuthError(
                    format!("S3 auth error for '{}'. Check AWS_ACCESS_KEY_ID and \
                             AWS_SECRET_ACCESS_KEY env vars: {}", uri, msg)
                )
            } else {
                CdnError::Network(msg)
            }
        })?;
 
        let data = response.body.collect().await
            .map_err(|e| CdnError::Network(e.to_string()))?
            .into_bytes()
            .to_vec();
 
        Ok(data)
    }
 
    async fn content_length(&self, uri: &str) -> CdnResult<Option<u64>> {
        let key = self.parse_key(uri);
 
        let response = self.client
            .head_object()
            .bucket(&self.bucket)
            .key(key)
            .send()
            .await
            .map_err(|e| {
                let msg = e.to_string();
                if msg.contains("NoSuchKey") || msg.contains("404") {
                    CdnError::NotFound { uri: uri.to_string() }
                } else {
                    CdnError::Network(msg)
                }
            })?;
 
        Ok(response.content_length().map(|l| l as u64))
    }
 
    fn adapter_name(&self) -> &'static str { "s3" }
}