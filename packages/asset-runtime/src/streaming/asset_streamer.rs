/*!
# asset_streamer.rs — Async Asset Streaming Orchestrator

Manages a background pool of async load tasks with priority ordering.

## Architecture

```
game thread                background Tokio runtime
───────────                ──────────────────────────
AssetStreamer::submit()    AssetPriorityQueue (max-heap)
                    →          ↓
AssetStreamer::poll_results    spawn_task() per slot
                    ←          ↓
                           ICdnAdapter::fetch()
                                ↓
                           SHA-256 verify
                                ↓
                           tx → LoadResult → rx
```

## Concurrency

`max_concurrent` (default: 4) caps simultaneous CDN fetches.
Higher-priority requests preempt slots when a slot becomes free.
Critical-priority requests are dispatched immediately even if it means
briefly exceeding `max_concurrent` — one additional slot is reserved for them.

## Game Thread Integration

The game thread (not the streaming background) calls:
1. `submit(LoadRequest)` — non-blocking, enqueues
2. `poll_results()` — non-blocking drain of completed loads
3. `process_ready(|result| { ... })` — applies results this tick

Phase Orchestrator calls `process_ready` at tick start BEFORE input drain.
*/

use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use tokio::runtime::Runtime;
use tokio::sync::mpsc;

use crate::cdn::cdn_adapter::ICdnAdapter;
use crate::hot_reload::version_hasher::VersionHasher;
use crate::streaming::load_request::{LoadPriority, LoadRequest};
use crate::streaming::load_result::{AssetBytes, LoadOutcome, LoadResult};
use crate::streaming::priority_queue::AssetPriorityQueue;
use crate::AssetId;


// ── Config ────────────────────────────────────────────────────────────────────

#[derive(Debug, Clone)]
pub struct StreamerConfig {
    /// Maximum simultaneous CDN fetches.
    pub max_concurrent:        usize,
    /// Maximum pending requests in the queue before drops.
    pub queue_depth:           usize,
    /// Maximum size of one asset in bytes. Larger assets are rejected.
    pub max_asset_size_bytes:  usize,
    /// Timeout per CDN fetch.
    pub fetch_timeout:         Duration,
    /// Whether to verify SHA-256 hashes on every load.
    pub verify_hashes:         bool,
}

impl Default for StreamerConfig {
    fn default() -> Self {
        Self {
            max_concurrent:       4,
            queue_depth:          256,
            max_asset_size_bytes: 256 * 1024 * 1024,   // 256 MB
            fetch_timeout:        Duration::from_secs(30),
            verify_hashes:        true,
        }
    }
}


// ── Streamer Stats ────────────────────────────────────────────────────────────

#[derive(Debug, Default, Clone)]
pub struct StreamerStats {
    pub total_submitted:  u64,
    pub total_completed:  u64,
    pub total_failed:     u64,
    pub total_bytes:      u64,
    pub active_fetches:   usize,
    pub queue_depth:      usize,
    pub avg_latency_ms:   f64,
}


// ── Asset Streamer ────────────────────────────────────────────────────────────

/// Async asset streaming orchestrator.
///
/// One instance per world. Owned by the Phase Orchestrator.
/// Thread-safe — `submit()` and `poll_results()` may be called from different
/// threads but are typically both called from the game thread.
pub struct AssetStreamer {
    config:      StreamerConfig,
    queue:       Arc<AssetPriorityQueue>,
    cdn:         Arc<dyn ICdnAdapter>,
    // Completed results waiting for the game thread to consume
    result_tx:   mpsc::UnboundedSender<LoadResult>,
    result_rx:   Mutex<mpsc::UnboundedReceiver<LoadResult>>,
    // Background Tokio runtime
    runtime:     Arc<Runtime>,
    // Semaphore for concurrency limiting
    active:      Arc<Mutex<usize>>,
    stats:       Arc<Mutex<StreamerStats>>,
}

impl AssetStreamer {
    /// Creates a new streamer backed by the given CDN adapter.
    pub fn new(cdn: Arc<dyn ICdnAdapter>, config: StreamerConfig) -> Self {
        let (tx, rx) = mpsc::unbounded_channel();
        let runtime  = Arc::new(
            tokio::runtime::Builder::new_multi_thread()
                .worker_threads(2)
                .thread_name("xace-asset-rt")
                .enable_all()
                .build()
                .expect("failed to build asset streaming runtime"),
        );

        Self {
            queue:     Arc::new(AssetPriorityQueue::new(config.queue_depth)),
            cdn,
            result_tx: tx,
            result_rx: Mutex::new(rx),
            runtime,
            active:    Arc::new(Mutex::new(0)),
            stats:     Arc::new(Mutex::new(StreamerStats::default())),
            config,
        }
    }

    // ── Public API ────────────────────────────────────────────────────────────

    /// Enqueues an asset load request. Non-blocking.
    ///
    /// Critical-priority requests are dispatched immediately.
    /// All other priorities are queued and dispatched as slots become free.
    pub fn submit(&self, request: LoadRequest) -> bool {
        let is_critical = request.priority == LoadPriority::Critical;
        if !self.queue.push(request.clone()) && !is_critical {
            return false;   // dropped (queue full, low priority)
        }

        {
            let mut stats = self.stats.lock().unwrap();
            stats.total_submitted += 1;
            stats.queue_depth     = self.queue.len();
        }

        self.try_dispatch_next(is_critical);
        true
    }

    /// Non-blocking drain of completed load results.
    /// Call once per tick from the game thread.
    pub fn poll_results(&self) -> Vec<LoadResult> {
        let mut rx      = self.result_rx.lock().unwrap();
        let mut results = Vec::new();
        // Drain without blocking
        loop {
            match rx.try_recv() {
                Ok(result) => results.push(result),
                Err(_)     => break,
            }
        }
        results
    }

    /// Calls `handler` for each completed result this tick.
    ///
    /// Use this in Phase Orchestrator to apply loaded assets to ECS components:
    /// ```rust
    /// streamer.process_ready(|result| {
    ///     if let Some(bytes) = result.bytes() {
    ///         mutation_gate.update_asset_ref(result.asset_id, bytes.content_hash.clone());
    ///     }
    /// });
    /// ```
    pub fn process_ready<F>(&self, mut handler: F)
    where
        F: FnMut(LoadResult),
    {
        for result in self.poll_results() {
            handler(result);
        }
    }

    /// Cancels all pending requests for an asset ID (entity destroyed, etc.).
    pub fn cancel(&self, asset_id: &AssetId) -> usize {
        self.queue.cancel(asset_id)
    }

    /// Returns a snapshot of streaming statistics.
    pub fn stats(&self) -> StreamerStats {
        let mut s = self.stats.lock().unwrap().clone();
        s.active_fetches = *self.active.lock().unwrap();
        s.queue_depth    = self.queue.len();
        s
    }

    /// Returns the number of pending requests in the queue.
    pub fn queue_depth(&self) -> usize { self.queue.len() }

    /// Returns the number of active (in-flight) CDN fetches.
    pub fn active_fetches(&self) -> usize { *self.active.lock().unwrap() }

    // ── Internal ──────────────────────────────────────────────────────────────

    fn try_dispatch_next(&self, allow_over_limit: bool) {
        let current_active = *self.active.lock().unwrap();
        let limit = if allow_over_limit {
            self.config.max_concurrent + 1   // one extra slot for Critical
        } else {
            self.config.max_concurrent
        };

        if current_active >= limit {
            return;
        }

        if let Some(request) = self.queue.pop() {
            *self.active.lock().unwrap() += 1;
            self.spawn_fetch(request);
        }
    }

    fn spawn_fetch(&self, request: LoadRequest) {
        let cdn       = Arc::clone(&self.cdn);
        let tx        = self.result_tx.clone();
        let active    = Arc::clone(&self.active);
        let stats     = Arc::clone(&self.stats);
        let queue     = Arc::clone(&self.queue);
        let verify    = self.config.verify_hashes;
        let timeout   = self.config.fetch_timeout;
        let max_size  = self.config.max_asset_size_bytes;
        let max_conc  = self.config.max_concurrent;

        self.runtime.spawn(async move {
            let start = Instant::now();

            let outcome = Self::fetch_asset(&cdn, &request, verify, timeout, max_size).await;
            let duration = start.elapsed();

            let result = match outcome {
                Ok(bytes) => LoadResult::success(&request, bytes, duration),
                Err(msg)  => LoadResult::error(&request, msg, duration),
            };

            // Update stats
            {
                let mut s = stats.lock().unwrap();
                s.total_completed += 1;
                if !result.is_success() { s.total_failed += 1; }
                if let Some(b) = result.bytes() { s.total_bytes += b.size_bytes as u64; }
                // Rolling avg latency
                let n = s.total_completed as f64;
                s.avg_latency_ms = s.avg_latency_ms * ((n - 1.0) / n)
                    + (duration.as_millis() as f64 / n);
            }

            let _ = tx.send(result);

            // Release slot and dispatch next
            *active.lock().unwrap() -= 1;
            if let Some(next) = queue.pop() {
                *active.lock().unwrap() += 1;
                // Note: this spawn happens inside the runtime, so it's fine
                let cdn2    = Arc::clone(&cdn);
                let tx2     = tx.clone();
                let active2 = Arc::clone(&active);
                let stats2  = Arc::clone(&stats);
                let queue2  = Arc::clone(&queue);
                tokio::spawn(async move {
                    let start2 = Instant::now();
                    let outcome2 = Self::fetch_asset(&cdn2, &next, verify, timeout, max_size).await;
                    let dur2 = start2.elapsed();
                    let res2 = match outcome2 {
                        Ok(b)  => LoadResult::success(&next, b, dur2),
                        Err(e) => LoadResult::error(&next, e, dur2),
                    };
                    {
                        let mut s = stats2.lock().unwrap();
                        s.total_completed += 1;
                        if !res2.is_success() { s.total_failed += 1; }
                    }
                    let _ = tx2.send(res2);
                    *active2.lock().unwrap() -= 1;
                });
            }
        });
    }

    async fn fetch_asset(
        cdn:      &Arc<dyn ICdnAdapter>,
        request:  &LoadRequest,
        verify:   bool,
        timeout:  Duration,
        max_size: usize,
    ) -> std::result::Result<AssetBytes, String> {
        let data = tokio::time::timeout(
            timeout,
            cdn.fetch(&request.source_uri, request.byte_range),
        )
        .await
        .map_err(|_| format!("Timeout fetching '{}' after {}s", request.source_uri, timeout.as_secs()))?
        .map_err(|e| format!("CDN fetch error for '{}': {}", request.source_uri, e))?;

        if data.len() > max_size {
            return Err(format!(
                "Asset '{}' too large: {} bytes (max {} bytes). \
                 Increase StreamerConfig.max_asset_size_bytes.",
                request.asset_id, data.len(), max_size
            ));
        }

        let hash = VersionHasher::hash_bytes(&data);

        // Verify hash if provided
        if verify {
            if let Some(expected) = &request.expected_hash {
                if *expected != hash {
                    return Err(format!(
                        "Hash mismatch for '{}': expected {}, got {}",
                        request.asset_id, expected, hash
                    ));
                }
            }
        }

        Ok(AssetBytes::new(data, hash))
    }
}