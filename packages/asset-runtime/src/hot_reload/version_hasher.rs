// ============================================================================
// packages/asset-runtime/src/hot_reload/version_hasher.rs
// ============================================================================
/*!
# version_hasher.rs — Deterministic Content Hashing

Computes SHA-256 of asset bytes. Used as the `AssetReference.version` string.

## Determinism Contract

The same file content always produces the same hash.
All peers computing this hash for the same asset produce the same version string.
This makes hot-reload deterministic across multiplayer sessions:

- Host reloads mesh and computes SHA-256, for example `a3f2bc7d...`.
- Host broadcasts reload event with that hash.
- All peers reload the same file bytes and compute the same version string.
- All `AssetReference.version` fields update to the same value.
- World hash after reload is identical on all peers.
*/

use sha2::{Digest, Sha256};
use std::path::Path;

pub struct VersionHasher;

impl VersionHasher {
    /// Computes the SHA-256 hex string of the given byte slice.
    /// This is the canonical deterministic version ID for an asset.
    pub fn hash_bytes(data: &[u8]) -> String {
        let mut hasher = Sha256::new();
        hasher.update(data);
        hex::encode(hasher.finalize())
    }

    /// Reads a file synchronously and returns its SHA-256 hex hash.
    /// For async use, load the bytes first then call `hash_bytes`.
    pub fn hash_file(path: impl AsRef<Path>) -> std::io::Result<String> {
        let data = std::fs::read(path)?;
        Ok(Self::hash_bytes(&data))
    }

    /// Computes a stable hash over a file path alone (not its content).
    /// Used as a cache key when the content is not yet available.
    pub fn hash_path(path: impl AsRef<Path>) -> String {
        let path_str = path.as_ref().to_string_lossy();
        Self::hash_bytes(path_str.as_bytes())
    }

    /// Verifies that `data` matches the expected hash.
    pub fn verify(data: &[u8], expected_hash: &str) -> bool {
        Self::hash_bytes(data) == expected_hash
    }

    /// Returns a short prefix (first 8 chars) of a hash for display.
    pub fn short(hash: &str) -> &str {
        &hash[..8.min(hash.len())]
    }
}
