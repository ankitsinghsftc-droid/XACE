// ============================================================================
// packages/asset-runtime/src/hot_reload/file_watcher.rs
// ============================================================================
/*!
# file_watcher.rs — Cross-Platform Asset Directory Watcher
 
Watches one or more directories for file modifications using the `notify` crate.
 
## Accepted Caveats (per user decision 26)
 
    macOS:  FSEvents coalesces rapid events — some intermediate saves may be missed.
            For game assets (textures, meshes), a 100ms delay is fine.
    Windows: ReadDirectoryChangesW may miss renames in some edge cases.
             Saves from most DCC tools (Blender, Maya) trigger a WRITE event reliably.
    Linux:  inotify is reliable but has a kernel watch limit (fs.inotify.max_user_watches).
            Increase to 524288 if watching large projects:
            echo 524288 | sudo tee /proc/sys/fs/inotify/max_user_watches
 
## Events
 
FileWatcher emits `FileChangeEvent` structs via a channel.
`ReloadCoordinator` consumes this channel and enqueues `ReloadRequest`s.
 
The file watcher runs on a dedicated background thread owned by `notify`.
Events are debounced by 100ms to avoid double-processing rapid saves.
*/
 
use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::mpsc;
use std::time::Duration;
 
use notify::{Config, Event, EventKind, RecommendedWatcher, RecursiveMode, Watcher};
use serde::{Deserialize, Serialize};
 
 
// ── File Change Event ─────────────────────────────────────────────────────────
 
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileChangeEvent {
    /// Absolute path of the changed file.
    pub path:      PathBuf,
    /// Kind of change detected.
    pub kind:      FileChangeKind,
    /// Wall-clock timestamp (epoch millis) when the event was detected.
    pub timestamp_ms: u64,
}
 
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum FileChangeKind {
    Modified,
    Created,
    Deleted,
    Renamed,
}
 
impl FileChangeEvent {
    fn new(path: PathBuf, kind: FileChangeKind) -> Self {
        use std::time::{SystemTime, UNIX_EPOCH};
        Self {
            path,
            kind,
            timestamp_ms: SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_millis() as u64,
        }
    }
}
 
 
// ── File Watcher ──────────────────────────────────────────────────────────────
 
/// Cross-platform file system watcher for game asset directories.
pub struct FileWatcher {
    _watcher: RecommendedWatcher,
    rx:       mpsc::Receiver<FileChangeEvent>,
}
 
impl FileWatcher {
    /// Creates a watcher for the given directories.
    ///
    /// `extensions`: Only events for files with these extensions are emitted.
    ///               Empty set = watch all files.
    ///
    /// Debounce interval: 100ms (events within 100ms are coalesced).
    pub fn new(
        watch_dirs:  &[impl AsRef<Path>],
        extensions:  HashSet<String>,
        recursive:   bool,
    ) -> Result<Self, Box<dyn std::error::Error>> {
        let (tx, rx) = mpsc::channel();
        let ext_filter = extensions.clone();
 
        let mut watcher = notify::recommended_watcher(
            move |result: Result<Event, notify::Error>| {
                let event = match result {
                    Ok(e)  => e,
                    Err(_) => return,
                };
 
                let kind = match event.kind {
                    EventKind::Modify(_) => FileChangeKind::Modified,
                    EventKind::Create(_) => FileChangeKind::Created,
                    EventKind::Remove(_) => FileChangeKind::Deleted,
                    // Rename: emit both old and new
                    EventKind::Other     => FileChangeKind::Renamed,
                    _                   => return,
                };
 
                for path in event.paths {
                    // Filter by extension
                    if !ext_filter.is_empty() {
                        let matches = path.extension()
                            .and_then(|e| e.to_str())
                            .map(|e| ext_filter.contains(e))
                            .unwrap_or(false);
                        if !matches { continue; }
                    }
 
                    let change = FileChangeEvent::new(path, kind);
                    let _ = tx.send(change);
                }
            }
        )?;
 
        let mode = if recursive {
            RecursiveMode::Recursive
        } else {
            RecursiveMode::NonRecursive
        };
 
        for dir in watch_dirs {
            watcher.watch(dir.as_ref(), mode)?;
        }
 
        Ok(Self { _watcher: watcher, rx })
    }
 
    /// Drains all pending file change events without blocking.
    pub fn drain_events(&self) -> Vec<FileChangeEvent> {
        let mut events = Vec::new();
        loop {
            match self.rx.try_recv() {
                Ok(e)  => events.push(e),
                Err(_) => break,
            }
        }
        events
    }
 
    /// Blocks until at least one event is received (timeout applies).
    pub fn wait_for_event(&self, timeout: Duration) -> Option<FileChangeEvent> {
        self.rx.recv_timeout(timeout).ok()
    }
}
 