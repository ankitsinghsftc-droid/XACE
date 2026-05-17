// ============================================================================
// packages/asset-runtime/src/hot_reload/tick_boundary_gate.rs
// ============================================================================
/*!
# tick_boundary_gate.rs — Tick-Boundary Hot-Reload Gate
 
Holds hot-reload events until the next tick boundary.
 
## Determinism Invariant
 
Hot reloads MUST happen at tick boundaries via the Mutation Gate.
This ensures:
    1. No system sees a partially-loaded asset mid-tick.
    2. All peers reload at the same logical tick (synchronised via input stream).
    3. The world hash after reload is identical on all peers.
    4. Replays remain valid — reload events appear in the input stream at the
       correct tick, not at an arbitrary wall-clock time.
 
## Integration with Phase Orchestrator
 
At tick START (before input drain), Phase Orchestrator calls:
 
```rust
let requests = gate.drain();
for req in requests {
    // Apply as a mutation through the Mutation Gate
    mutation_gate.update_asset_reference(
        entity_id   = req.entity_id,
        type_id     = req.component_type_id,
        new_hash    = req.content_hash,
        new_version = req.new_version,
    );
}
```
 
The reload is then processed as part of the tick's mutation pass —
identical to any other schema mutation in terms of ordering and atomicity.
*/
 
use std::sync::{Arc, Mutex};
 
use serde::{Deserialize, Serialize};
 
use crate::AssetId;
 
 
/// A hot-reload request waiting at the tick boundary gate.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReloadRequest {
    /// The asset that changed.
    pub asset_id:           AssetId,
    /// Absolute path of the changed file.
    pub file_path:          String,
    /// SHA-256 hash of the new file content.
    pub content_hash:       String,
    /// New version number for the AssetReference.version field.
    pub new_version:        u32,
    /// Component type_id owning this AssetReference (for mutation routing).
    pub component_type_id:  u32,
    /// Entity ID owning this AssetReference (for mutation routing).
    pub entity_id:          u64,
    /// Wall-clock timestamp when the file change was detected (for telemetry).
    pub detected_at_ms:     u64,
}
 
impl ReloadRequest {
    pub fn new(
        asset_id:           impl Into<String>,
        file_path:          impl Into<String>,
        content_hash:       impl Into<String>,
        new_version:        u32,
        component_type_id:  u32,
        entity_id:          u64,
    ) -> Self {
        use std::time::{SystemTime, UNIX_EPOCH};
        Self {
            asset_id:          AssetId::new(asset_id),
            file_path:         file_path.into(),
            content_hash:      content_hash.into(),
            new_version,
            component_type_id,
            entity_id,
            detected_at_ms:    SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_millis() as u64,
        }
    }
}
 
 
/// Thread-safe gate that holds reload requests until the next tick.
///
/// Write side (background thread): `ReloadCoordinator` calls `push()`.
/// Read side (game thread):        Phase Orchestrator calls `drain()` at tick start.
pub struct TickBoundaryGate {
    pending: Mutex<Vec<ReloadRequest>>,
}
 
impl TickBoundaryGate {
    pub fn new() -> Self {
        Self { pending: Mutex::new(Vec::new()) }
    }
 
    pub fn new_shared() -> Arc<Self> {
        Arc::new(Self::new())
    }
 
    /// Enqueues a reload request. Called from the file-watcher background thread.
    pub fn push(&self, request: ReloadRequest) {
        self.pending.lock().unwrap().push(request);
    }
 
    /// Drains all pending requests. Called at tick start from the game thread.
    ///
    /// Returns all pending requests and clears the queue.
    /// The caller (Phase Orchestrator) applies them through the Mutation Gate.
    pub fn drain(&self) -> Vec<ReloadRequest> {
        let mut pending = self.pending.lock().unwrap();
        std::mem::take(&mut *pending)
    }
 
    /// Returns the number of pending reload requests without draining.
    pub fn pending_count(&self) -> usize {
        self.pending.lock().unwrap().len()
    }
 
    pub fn is_empty(&self) -> bool { self.pending_count() == 0 }
}
 
impl Default for TickBoundaryGate {
    fn default() -> Self { Self::new() }
}