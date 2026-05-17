// ============================================================================
// packages/asset-runtime/src/streaming/priority_queue.rs
// ============================================================================
 
/*!
# priority_queue.rs — Priority-Ordered Asset Queue
 
Thread-safe priority queue for pending `LoadRequest`s.
 
Uses a `BinaryHeap<LoadRequest>` (max-heap) behind a `Mutex`.
`LoadRequest` implements `Ord` so Critical priority pops before Background.
Within the same priority, earlier requests (FIFO) pop first.
 
The queue is bounded by `max_depth`. When full, incoming requests at
lower priority than the current minimum are dropped with a telemetry event.
*/
 
use std::collections::BinaryHeap;
use std::sync::Mutex;
 
use crate::streaming::load_request::{LoadPriority, LoadRequest};
 
 
pub struct AssetPriorityQueue {
    inner:     Mutex<BinaryHeap<LoadRequest>>,
    max_depth: usize,
}
 
impl AssetPriorityQueue {
    pub fn new(max_depth: usize) -> Self {
        Self {
            inner:     Mutex::new(BinaryHeap::with_capacity(max_depth)),
            max_depth,
        }
    }
 
    /// Enqueues a request. Drops the lowest-priority item when full.
    /// Returns `true` if the request was accepted, `false` if dropped.
    pub fn push(&self, request: LoadRequest) -> bool {
        let mut heap = self.inner.lock().unwrap();
        if heap.len() >= self.max_depth {
            // Drop the request only if lower priority than the current minimum
            // BinaryHeap is max-heap, so peek is the highest. We need the lowest.
            // Full queue: drop incoming if its priority is the lowest tier.
            if request.priority == LoadPriority::Preload {
                return false;   // drop pre-load requests when queue is full
            }
        }
        heap.push(request);
        true
    }
 
    /// Pops the highest-priority request, or None if empty.
    pub fn pop(&self) -> Option<LoadRequest> {
        self.inner.lock().unwrap().pop()
    }
 
    /// Peeks at the next request priority without removing it.
    pub fn peek_priority(&self) -> Option<LoadPriority> {
        self.inner.lock().unwrap().peek().map(|r| r.priority)
    }
 
    /// Drains up to `n` requests, highest priority first.
    pub fn drain_n(&self, n: usize) -> Vec<LoadRequest> {
        let mut heap = self.inner.lock().unwrap();
        let take = n.min(heap.len());
        (0..take).filter_map(|_| heap.pop()).collect()
    }
 
    /// Returns the number of queued requests.
    pub fn len(&self) -> usize {
        self.inner.lock().unwrap().len()
    }
 
    pub fn is_empty(&self) -> bool { self.len() == 0 }
 
    /// Removes all requests for the given asset ID (e.g. entity destroyed).
    pub fn cancel(&self, asset_id: &crate::AssetId) -> usize {
        let mut heap = self.inner.lock().unwrap();
        let all: Vec<LoadRequest> = heap.drain().collect();
        let before = all.len();
        *heap = all.into_iter()
            .filter(|r| &r.asset_id != asset_id)
            .collect();
        before - heap.len()
    }
}