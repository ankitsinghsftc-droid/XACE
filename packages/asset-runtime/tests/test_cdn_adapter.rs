// ============================================================================
// packages/asset-runtime/tests/test_cdn_adapter.rs
// ============================================================================
 
/*!
# test_cdn_adapter.rs — CDN Adapter Tests
 
Tests LocalCdnAdapter correctness (no network required).
S3 and CloudFront adapters are tested via integration tests that require
AWS credentials — those live in `tests/integration/` and are excluded from CI.
*/
 
use std::fs;
use tempfile::TempDir;
 
use xace_asset_runtime::cdn::local_cdn_adapter::LocalCdnAdapter;
use xace_asset_runtime::cdn::cdn_adapter::ICdnAdapter;
use xace_asset_runtime::cdn::range_request;
 
fn setup_local_cdn() -> (TempDir, LocalCdnAdapter) {
    let dir = TempDir::new().unwrap();
    let cdn = LocalCdnAdapter::new(dir.path());
    (dir, cdn)
}
 
// ── LocalCdnAdapter Tests ─────────────────────────────────────────────────────
 
#[tokio::test]
async fn local_cdn_fetch_existing_file() {
    let (dir, cdn) = setup_local_cdn();
    let file_path  = dir.path().join("mesh_knight.fbx");
    fs::write(&file_path, b"fake mesh bytes").unwrap();
 
    let result = cdn.fetch("mesh_knight.fbx", None).await;
    assert!(result.is_ok(), "fetch of existing file must succeed");
    assert_eq!(result.unwrap(), b"fake mesh bytes");
}
 
#[tokio::test]
async fn local_cdn_fetch_missing_file_returns_not_found() {
    let (_, cdn)   = setup_local_cdn();
    let result     = cdn.fetch("missing.fbx", None).await;
    assert!(result.is_err());
    assert!(matches!(result.unwrap_err(),
        xace_asset_runtime::cdn::cdn_adapter::CdnError::NotFound { .. }));
}
 
#[tokio::test]
async fn local_cdn_fetch_with_byte_range() {
    let (dir, cdn) = setup_local_cdn();
    let data       = b"0123456789ABCDEF";
    fs::write(dir.path().join("ranged.dat"), data).unwrap();
 
    // Fetch bytes 4–7 (inclusive) → "4567"
    let result = cdn.fetch("ranged.dat", Some((4, 7))).await;
    assert!(result.is_ok());
    let bytes = result.unwrap();
    assert_eq!(bytes, b"4567");
}
 
#[tokio::test]
async fn local_cdn_fetch_local_scheme_prefix() {
    let (dir, cdn) = setup_local_cdn();
    fs::write(dir.path().join("audio.ogg"), b"audio data").unwrap();
 
    // local:// prefix must be stripped
    let result = cdn.fetch("local://audio.ogg", None).await;
    assert!(result.is_ok());
    assert_eq!(result.unwrap(), b"audio data");
}
 
#[tokio::test]
async fn local_cdn_content_length() {
    let (dir, cdn) = setup_local_cdn();
    let data       = b"exactly 15 bytes";
    fs::write(dir.path().join("sized.dat"), data).unwrap();
 
    let len = cdn.content_length("sized.dat").await;
    assert!(len.is_ok());
    assert_eq!(len.unwrap(), Some(data.len() as u64));
}
 
#[tokio::test]
async fn local_cdn_exists_true_for_existing() {
    let (dir, cdn) = setup_local_cdn();
    fs::write(dir.path().join("exists.dat"), b"data").unwrap();
    assert!(cdn.exists("exists.dat").await);
}
 
#[tokio::test]
async fn local_cdn_exists_false_for_missing() {
    let (_, cdn) = setup_local_cdn();
    assert!(!cdn.exists("no_such_file.dat").await);
}
 
#[tokio::test]
async fn local_cdn_path_traversal_rejected() {
    let (dir, cdn) = setup_local_cdn();
    // Create a file outside the CDN root
    let outside = dir.path().parent().unwrap().join("secret.txt");
    fs::write(&outside, b"secret").unwrap();
 
    // Attempt path traversal
    let result = cdn.fetch("../secret.txt", None).await;
    assert!(result.is_err(), "path traversal must be rejected");
}
 
// ── Range Request Helpers ─────────────────────────────────────────────────────
 
#[test]
fn range_header_format() {
    assert_eq!(range_request::range_header(0, 1023), "bytes=0-1023");
    assert_eq!(range_request::range_header(1024, 2047), "bytes=1024-2047");
}
 
#[test]
fn parse_content_length_valid() {
    assert_eq!(range_request::parse_content_length("bytes 0-1023/4096"), Some(4096));
    assert_eq!(range_request::parse_content_length("bytes 500-999/1000"), Some(1000));
}
 
#[test]
fn parse_content_length_unknown_total() {
    assert_eq!(range_request::parse_content_length("bytes 0-1023/*"), None);
}
 
#[test]
fn chunk_ranges_even_split() {
    let chunks = range_request::chunk_ranges(1000, 100);
    assert_eq!(chunks.len(), 10);
    assert_eq!(chunks[0], (0, 99));
    assert_eq!(chunks[9], (900, 999));
}
 
#[test]
fn chunk_ranges_uneven_split() {
    let chunks = range_request::chunk_ranges(150, 100);
    assert_eq!(chunks.len(), 2);
    assert_eq!(chunks[0], (0, 99));
    assert_eq!(chunks[1], (100, 149));
}
 
#[test]
fn chunk_ranges_zero_size() {
    let chunks = range_request::chunk_ranges(0, 100);
    assert!(chunks.is_empty());
}