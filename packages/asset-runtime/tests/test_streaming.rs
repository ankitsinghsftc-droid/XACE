// ============================================================================
// packages/asset-runtime/tests/test_streaming.rs
// ============================================================================

/*!
# test_streaming.rs — Asset Streaming Tests

Verifies priority queue ordering, cancel semantics, stats tracking,
and end-to-end load flow using a mock CDN adapter.
*/

use std::collections::HashSet;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use async_trait::async_trait;

use xace_asset_runtime::{
    cdn::cdn_adapter::{CdnError, CdnResult, ICdnAdapter},
    streaming::{
        asset_streamer::{AssetStreamer, StreamerConfig},
        load_request::{LoadPriority, LoadRequest},
    },
    AssetId,
};

// ── Mock CDN ──────────────────────────────────────────────────────────────────

struct MockCdn {
    content: Arc<Mutex<std::collections::HashMap<String, Vec<u8>>>>,
    fail_uris: Arc<Mutex<HashSet<String>>>,
}

impl MockCdn {
    fn new() -> Self {
        Self {
            content: Arc::new(Mutex::new(std::collections::HashMap::new())),
            fail_uris: Arc::new(Mutex::new(HashSet::new())),
        }
    }

    fn add(&self, uri: &str, data: &[u8]) {
        self.content
            .lock()
            .unwrap()
            .insert(uri.to_string(), data.to_vec());
    }
}

#[async_trait]
impl ICdnAdapter for MockCdn {
    async fn fetch(&self, uri: &str, _range: Option<(u64, u64)>) -> CdnResult<Vec<u8>> {
        if self.fail_uris.lock().unwrap().contains(uri) {
            return Err(CdnError::NotFound {
                uri: uri.to_string(),
            });
        }
        self.content
            .lock()
            .unwrap()
            .get(uri)
            .cloned()
            .ok_or_else(|| CdnError::NotFound {
                uri: uri.to_string(),
            })
    }

    async fn content_length(&self, uri: &str) -> CdnResult<Option<u64>> {
        Ok(self
            .content
            .lock()
            .unwrap()
            .get(uri)
            .map(|d| d.len() as u64))
    }

    fn adapter_name(&self) -> &'static str {
        "mock"
    }
}

// ── Priority Queue Tests ──────────────────────────────────────────────────────

mod priority_queue_tests {
    use xace_asset_runtime::streaming::load_request::{LoadPriority, LoadRequest};
    use xace_asset_runtime::streaming::priority_queue::AssetPriorityQueue;

    #[test]
    fn higher_priority_pops_first() {
        let q = AssetPriorityQueue::new(100);
        let bg = LoadRequest::new("bg", "uri_bg").with_priority(LoadPriority::Background);
        let crit = LoadRequest::new("crit", "uri_c").with_priority(LoadPriority::Critical);
        let pl = LoadRequest::new("pl", "uri_p").with_priority(LoadPriority::Player);
        q.push(bg);
        q.push(pl);
        q.push(crit);
        assert_eq!(q.pop().unwrap().priority, LoadPriority::Critical);
        assert_eq!(q.pop().unwrap().priority, LoadPriority::Player);
        assert_eq!(q.pop().unwrap().priority, LoadPriority::Background);
        assert!(q.is_empty());
    }

    #[test]
    fn same_priority_fifo() {
        let q = AssetPriorityQueue::new(100);
        for i in 0..5usize {
            let req =
                LoadRequest::new(format!("a{}", i), "uri").with_priority(LoadPriority::Environment);
            q.push(req);
            std::thread::sleep(std::time::Duration::from_millis(1));
        }
        // FIFO within same priority
        let first = q.pop().unwrap();
        assert_eq!(first.asset_id.as_str(), "a0");
    }

    #[test]
    fn cancel_removes_matching_requests() {
        let q = AssetPriorityQueue::new(100);
        let id = xace_asset_runtime::AssetId::new("mesh_knight");
        q.push(LoadRequest::new("mesh_knight", "u1").with_priority(LoadPriority::Player));
        q.push(LoadRequest::new("mesh_knight", "u2").with_priority(LoadPriority::Background));
        q.push(LoadRequest::new("other", "u3").with_priority(LoadPriority::Environment));
        let cancelled = q.cancel(&id);
        assert_eq!(cancelled, 2);
        assert_eq!(q.len(), 1);
        assert_eq!(q.pop().unwrap().asset_id.as_str(), "other");
    }

    #[test]
    fn queue_len_and_empty() {
        let q = AssetPriorityQueue::new(10);
        assert!(q.is_empty());
        q.push(LoadRequest::new("x", "u").with_priority(LoadPriority::Background));
        assert_eq!(q.len(), 1);
        assert!(!q.is_empty());
        q.pop();
        assert!(q.is_empty());
    }

    #[test]
    fn drain_n_returns_highest_priority_first() {
        let q = AssetPriorityQueue::new(100);
        q.push(LoadRequest::new("a", "u1").with_priority(LoadPriority::Background));
        q.push(LoadRequest::new("b", "u2").with_priority(LoadPriority::Critical));
        q.push(LoadRequest::new("c", "u3").with_priority(LoadPriority::Player));
        let drained = q.drain_n(2);
        assert_eq!(drained[0].priority, LoadPriority::Critical);
        assert_eq!(drained[1].priority, LoadPriority::Player);
        assert_eq!(q.len(), 1);
    }
}

// ── Streamer Integration Tests ────────────────────────────────────────────────

#[test]
fn streamer_loads_asset_and_returns_result() {
    let cdn = Arc::new(MockCdn::new());
    cdn.add("mesh://knight.fbx", b"fake mesh data");

    let config = StreamerConfig {
        max_concurrent: 2,
        ..Default::default()
    };
    let streamer = AssetStreamer::new(cdn, config);

    let req =
        LoadRequest::new("mesh_knight", "mesh://knight.fbx").with_priority(LoadPriority::Player);
    assert!(streamer.submit(req));

    // Poll until result arrives (max 2s)
    let mut results = Vec::new();
    for _ in 0..20 {
        std::thread::sleep(Duration::from_millis(100));
        results = streamer.poll_results();
        if !results.is_empty() {
            break;
        }
    }

    assert_eq!(results.len(), 1);
    let result = &results[0];
    assert!(result.is_success(), "expected success");
    let bytes = result.bytes().unwrap();
    assert_eq!(bytes.data, b"fake mesh data");
    assert!(!bytes.content_hash.is_empty(), "content hash must be set");
}

#[test]
fn streamer_hash_verification_passes_on_correct_hash() {
    use xace_asset_runtime::hot_reload::version_hasher::VersionHasher;

    let cdn = Arc::new(MockCdn::new());
    let content = b"terrain chunk 001";
    let hash = VersionHasher::hash_bytes(content);
    cdn.add("cdn://terrain_001.dat", content);

    let streamer = AssetStreamer::new(cdn, StreamerConfig::default());
    let req = LoadRequest::new("terrain_001", "cdn://terrain_001.dat")
        .with_expected_hash(hash)
        .with_priority(LoadPriority::Background);
    streamer.submit(req);

    for _ in 0..20 {
        std::thread::sleep(Duration::from_millis(100));
        let r = streamer.poll_results();
        if !r.is_empty() {
            assert!(r[0].is_success());
            return;
        }
    }
    panic!("no result after 2s");
}

#[test]
fn streamer_cancel_removes_pending_request() {
    let cdn = Arc::new(MockCdn::new());
    cdn.add("cdn://large_asset.dat", &vec![0u8; 1024]);

    let config = StreamerConfig {
        max_concurrent: 0,
        ..Default::default()
    }; // no dispatch
    let streamer = AssetStreamer::new(cdn, config);

    let id = AssetId::new("large_asset");
    let req = LoadRequest::new("large_asset", "cdn://large_asset.dat")
        .with_priority(LoadPriority::Background);
    streamer.submit(req);

    let cancelled = streamer.cancel(&id);
    assert!(
        cancelled > 0 || streamer.queue_depth() == 0,
        "cancel must remove the request"
    );
}

#[test]
fn streamer_stats_track_submissions() {
    let cdn = Arc::new(MockCdn::new());
    cdn.add("a", b"data_a");
    cdn.add("b", b"data_b");

    let streamer = AssetStreamer::new(cdn, StreamerConfig::default());
    streamer.submit(LoadRequest::new("a", "a").with_priority(LoadPriority::Critical));
    streamer.submit(LoadRequest::new("b", "b").with_priority(LoadPriority::Background));

    let stats = streamer.stats();
    assert_eq!(stats.total_submitted, 2);
}
