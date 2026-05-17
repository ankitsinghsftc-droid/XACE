// ============================================================================
// packages/asset-runtime/src/cdn/range_request.rs
// ============================================================================
 
/*!
# range_request.rs — Byte-Range Request Helpers
 
Utilities for building HTTP Range headers and parsing Content-Range responses.
Used by S3Adapter and CloudFrontAdapter for partial asset loading.
 
## Why Range Requests?
 
Large assets (terrain chunks, animation clips) are slow to fully download
before playback can begin. Range requests allow:
    - Streaming the header / metadata portion first
    - Progressive loading of LOD levels
    - Resuming interrupted downloads
*/
 
/// Builds an HTTP Range header value from a byte range.
///
/// ```
/// assert_eq!(range_header(0, 1023), "bytes=0-1023");
/// ```
pub fn range_header(start: u64, end: u64) -> String {
    format!("bytes={}-{}", start, end)
}
 
/// Parses a Content-Range response header to extract the full content length.
///
/// Format: `bytes start-end/total`
///
/// ```
/// assert_eq!(parse_content_length("bytes 0-1023/4096"), Some(4096));
/// ```
pub fn parse_content_length(content_range: &str) -> Option<u64> {
    // "bytes 0-1023/4096" → "4096"
    let total = content_range.split('/').last()?;
    let total = total.trim();
    if total == "*" { return None; }   // unknown length
    total.parse().ok()
}
 
/// Splits a large asset URI into chunks for parallel range loading.
///
/// Returns a list of `(start, end)` byte ranges each of `chunk_size` bytes.
pub fn chunk_ranges(total_size: u64, chunk_size: u64) -> Vec<(u64, u64)> {
    if total_size == 0 || chunk_size == 0 {
        return Vec::new();
    }
    let mut ranges = Vec::new();
    let mut start = 0u64;
    while start < total_size {
        let end = (start + chunk_size - 1).min(total_size - 1);
        ranges.push((start, end));
        start = end + 1;
    }
    ranges
}