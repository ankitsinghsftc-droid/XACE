/*!
# health_check.rs — Health Status

Exposes `GET /health` for load balancers and monitoring systems.

## HealthStatus JSON

```json
{
  "runtime_ok": true,
  "last_tick_ms": 8.3,
  "schema_version": "0.2.1",
  "determinism_guard_mode": "STRICT",
  "uptime_secs": 123,
  "entity_count": 5000,
  "last_world_hash": "0b1d495d59a76609fdd15511294f5e132c5b62b9b72fb22b0acf61fac2c3e178"
}
```

## Usage

```rust
// At startup — starts background HTTP server
HealthWriter::start(9090);

// Each tick — runtime updates health state
HealthWriter::global().update_tick(duration_ms, entity_count, &world_hash);
HealthWriter::global().set_schema_version("0.2.1");
```

## HTTP Server

The HTTP server for `/health` and `/metrics` lives in `http_server.rs`.
`HealthWriter::start(port)` spawns the background thread.
*/

use std::sync::{Arc, RwLock};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

// ── HealthStatus ──────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HealthStatus {
    pub runtime_ok: bool,
    pub last_tick_ms: f64,
    pub schema_version: String,
    pub determinism_guard_mode: String,
    pub uptime_secs: u64,
    pub entity_count: u64,
    pub last_world_hash: String,
    pub tick_number: u64,
    pub timestamp_epoch_ms: u64,
    pub errors: Vec<String>,
}

impl HealthStatus {
    fn new_starting() -> Self {
        Self {
            runtime_ok: false, // false until first tick
            last_tick_ms: 0.0,
            schema_version: "unknown".into(),
            determinism_guard_mode: "STRICT".into(),
            uptime_secs: 0,
            entity_count: 0,
            last_world_hash: "none".into(),
            tick_number: 0,
            timestamp_epoch_ms: epoch_ms(),
            errors: Vec::new(),
        }
    }

    pub fn to_json(&self) -> String {
        serde_json::to_string_pretty(self).unwrap_or_else(|_| "{}".to_string())
    }

    pub fn is_healthy(&self) -> bool {
        self.runtime_ok && self.errors.is_empty()
    }
}

// ── HealthWriter ──────────────────────────────────────────────────────────────

/// Shared mutable health state.
/// Runtime Core updates this each tick; HTTP server reads it on demand.
#[derive(Clone)]
pub struct HealthWriter {
    state: Arc<RwLock<HealthStatus>>,
    started_at: Instant,
}

impl HealthWriter {
    fn new() -> Self {
        Self {
            state: Arc::new(RwLock::new(HealthStatus::new_starting())),
            started_at: Instant::now(),
        }
    }

    /// Returns the global singleton HealthWriter.
    pub fn global() -> &'static HealthWriter {
        use std::sync::OnceLock;
        static INSTANCE: OnceLock<HealthWriter> = OnceLock::new();
        INSTANCE.get_or_init(HealthWriter::new)
    }

    /// Called by Phase Orchestrator after each successful tick.
    pub fn update_tick(
        &self,
        duration_ms: f64,
        entity_count: u64,
        world_hash: &str,
        tick_number: u64,
    ) {
        let uptime = self.started_at.elapsed().as_secs();
        if let Ok(mut state) = self.state.write() {
            state.runtime_ok = true;
            state.last_tick_ms = duration_ms;
            state.entity_count = entity_count;
            state.last_world_hash = world_hash.to_owned();
            state.tick_number = tick_number;
            state.uptime_secs = uptime;
            state.timestamp_epoch_ms = epoch_ms();
            state.errors.clear(); // clear transient errors on successful tick
        }
    }

    /// Called when a D-rule violation or fatal error occurs.
    pub fn add_error(&self, msg: impl Into<String>) {
        if let Ok(mut state) = self.state.write() {
            state.runtime_ok = false;
            state.errors.push(msg.into());
        }
    }

    pub fn set_schema_version(&self, version: impl Into<String>) {
        if let Ok(mut state) = self.state.write() {
            state.schema_version = version.into();
        }
    }

    pub fn set_determinism_guard_mode(&self, mode: impl Into<String>) {
        if let Ok(mut state) = self.state.write() {
            state.determinism_guard_mode = mode.into();
        }
    }

    /// Takes a snapshot of the current health status.
    pub fn snapshot(&self) -> HealthStatus {
        self.state
            .read()
            .map(|s| s.clone())
            .unwrap_or_else(|_| HealthStatus::new_starting())
    }

    pub fn is_healthy(&self) -> bool {
        self.state.read().map(|s| s.is_healthy()).unwrap_or(false)
    }

    /// Starts the HTTP health + metrics server on `port`.
    /// Spawns a background thread — returns immediately.
    /// Call once at program startup.
    pub fn start(port: u16) {
        crate::http_server::start_background(port, Self::global().clone());
    }
}

// ── Helper ────────────────────────────────────────────────────────────────────

fn epoch_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}
