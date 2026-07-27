// ============================================================================
// packages/asset-runtime/src/hot_reload/reload_coordinator.rs
// ============================================================================
/*!
# reload_coordinator.rs — Hot-Reload Orchestrator

Connects FileWatcher → hash computation → TickBoundaryGate.

## Flow

```text
[Artist saves file]
        ↓
FileWatcher (notify, background thread)
        ↓ FileChangeEvent
ReloadCoordinator.handle_change()
        ↓ read file bytes + compute SHA-256
        ↓ look up entity/component that owns this asset
        ↓ build ReloadRequest
TickBoundaryGate.push(request)
        ↓ (waits until tick start)
Phase Orchestrator drains gate
        ↓ applies via Mutation Gate
AssetReference.version updated atomically in ECS
        ↓ (in multiplayer: broadcast reload event in input stream)
All peers reload → same hash → deterministic
```
*/

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use serde::{Deserialize, Serialize};

use crate::hot_reload::file_watcher::{FileChangeEvent, FileChangeKind};
use crate::hot_reload::tick_boundary_gate::{ReloadRequest, TickBoundaryGate};
use crate::hot_reload::version_hasher::VersionHasher;
use crate::AssetId;

/// An asset reload event (for telemetry and replay logging).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReloadEvent {
    pub asset_id: AssetId,
    pub old_hash: String,
    pub new_hash: String,
    pub file_path: String,
    pub tick_applied: Option<u64>,
}

/// Maps file paths to asset IDs + ECS component ownership.
/// Populated at world load from the asset manifest (Python side).
#[derive(Debug, Clone)]
pub struct AssetOwnershipMap {
    /// file_path → (asset_id, component_type_id, entity_id, current_version)
    inner: HashMap<PathBuf, (AssetId, u32, u64, u32)>,
}

impl AssetOwnershipMap {
    pub fn new() -> Self {
        Self {
            inner: HashMap::new(),
        }
    }

    pub fn register(
        &mut self,
        file_path: impl Into<PathBuf>,
        asset_id: impl Into<String>,
        component_type_id: u32,
        entity_id: u64,
        current_version: u32,
    ) {
        self.inner.insert(
            file_path.into(),
            (
                AssetId::new(asset_id),
                component_type_id,
                entity_id,
                current_version,
            ),
        );
    }

    pub fn lookup(&self, path: &Path) -> Option<(AssetId, u32, u64, u32)> {
        self.inner.get(path).cloned()
    }

    pub fn bump_version(&mut self, path: &Path) -> u32 {
        if let Some(entry) = self.inner.get_mut(path) {
            entry.3 += 1;
            entry.3
        } else {
            1
        }
    }

    pub fn tracked_paths(&self) -> Vec<PathBuf> {
        self.inner.keys().cloned().collect()
    }
}

impl Default for AssetOwnershipMap {
    fn default() -> Self {
        Self::new()
    }
}

/// Orchestrates file watching and queues reloads at tick boundaries.
pub struct ReloadCoordinator {
    gate: Arc<TickBoundaryGate>,
    ownership: Arc<Mutex<AssetOwnershipMap>>,
    history: Mutex<Vec<ReloadEvent>>,
}

impl ReloadCoordinator {
    pub fn new(gate: Arc<TickBoundaryGate>) -> Self {
        Self {
            gate,
            ownership: Arc::new(Mutex::new(AssetOwnershipMap::new())),
            history: Mutex::new(Vec::new()),
        }
    }

    pub fn with_ownership(gate: Arc<TickBoundaryGate>, ownership: AssetOwnershipMap) -> Self {
        Self {
            gate,
            ownership: Arc::new(Mutex::new(ownership)),
            history: Mutex::new(Vec::new()),
        }
    }

    /// Registers a file → asset ownership mapping.
    /// Call at world load from the Python asset manifest.
    pub fn register_asset(
        &self,
        file_path: impl Into<PathBuf>,
        asset_id: impl Into<String>,
        component_type_id: u32,
        entity_id: u64,
        current_version: u32,
    ) {
        self.ownership.lock().unwrap().register(
            file_path,
            asset_id,
            component_type_id,
            entity_id,
            current_version,
        );
    }

    /// Processes file change events from the FileWatcher.
    ///
    /// For each modified file that is tracked in `ownership`:
    ///   1. Read new file bytes
    ///   2. Compute SHA-256
    ///   3. Build ReloadRequest
    ///   4. Push to TickBoundaryGate
    ///
    /// Call this from the same thread that owns FileWatcher (background thread).
    pub fn handle_changes(&self, events: Vec<FileChangeEvent>) {
        for event in events {
            if event.kind == FileChangeKind::Deleted {
                continue; // don't reload deleted assets
            }

            // Look up ownership
            let lookup = {
                let mut map = self.ownership.lock().unwrap();
                let entry = map.lookup(&event.path);
                if entry.is_none() {
                    continue;
                }
                let (asset_id, type_id, entity_id, _) = entry.unwrap();
                let new_version = map.bump_version(&event.path);
                (asset_id, type_id, entity_id, new_version)
            };

            let (asset_id, component_type_id, entity_id, new_version) = lookup;

            // Compute content hash
            let content_hash = match VersionHasher::hash_file(&event.path) {
                Ok(h) => h,
                Err(e) => {
                    eprintln!(
                        "[xace-hot-reload] Cannot hash '{}': {}",
                        event.path.display(),
                        e
                    );
                    continue;
                }
            };

            let request = ReloadRequest::new(
                asset_id.as_str(),
                event.path.display().to_string(),
                content_hash.clone(),
                new_version,
                component_type_id,
                entity_id,
            );

            // Record for telemetry/replay
            self.history.lock().unwrap().push(ReloadEvent {
                asset_id: asset_id.clone(),
                old_hash: String::new(), // TODO: store previous hash in ownership map
                new_hash: content_hash,
                file_path: event.path.display().to_string(),
                tick_applied: None,
            });

            self.gate.push(request);
        }
    }

    /// Returns the history of all reloads (for telemetry and replay validation).
    pub fn reload_history(&self) -> Vec<ReloadEvent> {
        self.history.lock().unwrap().clone()
    }

    /// Returns how many reloads are waiting at the tick boundary gate.
    pub fn pending_count(&self) -> usize {
        self.gate.pending_count()
    }
}
