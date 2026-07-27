// ============================================================================
// packages/asset-runtime/src/cdn/local_cdn_adapter.rs
// ============================================================================

/*!
# local_cdn_adapter.rs — Local Filesystem CDN (Dev / CI)

Serves assets from the local filesystem for development and CI.
No network required. Used by default when `XACE_LOCAL_CDN_ROOT` is set
or when running in dev mode.

## URI Format

Local CDN URIs are relative paths under the configured root:
    `local://assets/character_knight_mesh_v1.fbx`
    → `{local_root}/assets/character_knight_mesh_v1.fbx`

The `local://` scheme prefix is stripped before joining with the root.
Plain relative paths also work without the scheme prefix.
*/

use std::path::PathBuf;

use async_trait::async_trait;
use tokio::io::AsyncReadExt;

use crate::cdn::cdn_adapter::{CdnError, CdnResult, ICdnAdapter};

pub struct LocalCdnAdapter {
    root: PathBuf,
}

impl LocalCdnAdapter {
    /// Creates a local CDN adapter rooted at `root`.
    /// Assets are served from `{root}/{relative_path}`.
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self { root: root.into() }
    }

    /// Creates a local CDN adapter using `XACE_LOCAL_CDN_ROOT` env var.
    /// Falls back to current directory if the env var is not set.
    pub fn from_env() -> Self {
        let root = std::env::var("XACE_LOCAL_CDN_ROOT").unwrap_or_else(|_| ".".to_string());
        Self::new(PathBuf::from(root))
    }

    fn resolve_path(&self, uri: &str) -> Result<PathBuf, CdnError> {
        // Strip URI scheme prefix
        let relative = uri
            .strip_prefix("local://")
            .or_else(|| uri.strip_prefix("file://"))
            .unwrap_or(uri);

        // Strip leading slash — we always join relative to the root
        let relative = relative.trim_start_matches('/');

        let path = self.root.join(relative);

        // Security: ensure resolved path stays within root (path traversal prevention)
        let canonical_root = self
            .root
            .canonicalize()
            .unwrap_or_else(|_| self.root.clone());
        let canonical_path = path.canonicalize().map_err(|_| CdnError::NotFound {
            uri: uri.to_string(),
        })?;

        if !canonical_path.starts_with(&canonical_root) {
            return Err(CdnError::InvalidUri(format!(
                "Path traversal attempt rejected for URI: {}",
                uri
            )));
        }

        Ok(canonical_path)
    }
}

#[async_trait]
impl ICdnAdapter for LocalCdnAdapter {
    async fn fetch(&self, uri: &str, byte_range: Option<(u64, u64)>) -> CdnResult<Vec<u8>> {
        let path = self.resolve_path(uri)?;

        let mut file = tokio::fs::File::open(&path)
            .await
            .map_err(|_| CdnError::NotFound {
                uri: uri.to_string(),
            })?;

        match byte_range {
            None => {
                let mut data = Vec::new();
                file.read_to_end(&mut data).await.map_err(CdnError::Io)?;
                Ok(data)
            }
            Some((start, end)) => {
                use tokio::io::AsyncSeekExt;
                file.seek(std::io::SeekFrom::Start(start))
                    .await
                    .map_err(CdnError::Io)?;
                let len = (end - start + 1) as usize;
                let mut data = vec![0u8; len];
                let read = file.read(&mut data).await.map_err(CdnError::Io)?;
                data.truncate(read);
                Ok(data)
            }
        }
    }

    async fn content_length(&self, uri: &str) -> CdnResult<Option<u64>> {
        let path = self.resolve_path(uri)?;
        let meta = tokio::fs::metadata(&path)
            .await
            .map_err(|_| CdnError::NotFound {
                uri: uri.to_string(),
            })?;
        Ok(Some(meta.len()))
    }

    fn adapter_name(&self) -> &'static str {
        "local"
    }
}
