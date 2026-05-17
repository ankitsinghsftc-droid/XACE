/*!
# trace.rs — Span and Trace Types

Core types for distributed tracing within XACE.

## Trace Model

XACE uses a subset of the OpenTelemetry data model — compatible enough to
export to OTLP-compliant backends later, but with zero external dependencies.

```
TraceId (u128)          — One mutation transaction or one simulation tick
  └── Span (SpanId)     — Top-level work unit (e.g. "tick", "llm_call")
        └── Span (SpanId) — Child work (e.g. "system_execute", "mutation_apply")
              └── Span   — Grandchild work (e.g. "btree_query", "hash_compute")
```

## Span Lifecycle

```
let id = TRACER.enter("tick", parent=None);
// ... do work ...
TRACER.add_attribute(id, "entity_count", "5000");
TRACER.exit(id);
```

Or use the RAII `ScopedSpan` via `tracer::enter_span()`:

```
let _span = enter_span("tick", [("entity_count", &count.to_string())]);
// span auto-closes when _span is dropped
```
*/

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};


// ── ID Types ──────────────────────────────────────────────────────────────────

/// Identifies one end-to-end trace (e.g. one mutation transaction).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct TraceId(pub u128);

impl TraceId {
    pub const ZERO: Self = Self(0);

    /// Generates a new unique TraceId using the OS entropy source.
    pub fn new_unique() -> Self {
        let id = uuid::Uuid::new_v4();
        Self(id.as_u128())
    }

    pub fn is_zero(&self) -> bool { self.0 == 0 }

    pub fn to_hex(&self) -> String { format!("{:032x}", self.0) }
}

impl std::fmt::Display for TraceId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", &self.to_hex()[..16])   // first 16 hex chars for readability
    }
}


/// Identifies one span within a trace.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct SpanId(pub u64);

impl SpanId {
    pub const ZERO: Self = Self(0);

    pub fn new_unique() -> Self {
        static COUNTER: AtomicU64 = AtomicU64::new(1);
        Self(COUNTER.fetch_add(1, Ordering::Relaxed))
    }

    pub fn is_zero(&self) -> bool { self.0 == 0 }
}

impl std::fmt::Display for SpanId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{:016x}", self.0)
    }
}


// ── Span Status ───────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SpanStatus {
    Ok,
    Error,
    Unset,
}


// ── Span (in-flight) ─────────────────────────────────────────────────────────

/// A span that is currently open (has not been closed yet).
/// Do not store these long-term — use `SpanRecord` for storage.
#[derive(Debug)]
pub struct Span {
    pub trace_id:       TraceId,
    pub span_id:        SpanId,
    pub parent_span_id: Option<SpanId>,
    pub name:           String,
    pub start_ns:       u64,    // nanoseconds since UNIX epoch
    pub attributes:     HashMap<String, String>,
    pub status:         SpanStatus,
}

impl Span {
    pub fn new(name: impl Into<String>, trace_id: TraceId, parent: Option<SpanId>) -> Self {
        Self {
            trace_id,
            span_id:        SpanId::new_unique(),
            parent_span_id: parent,
            name:           name.into(),
            start_ns:       epoch_nanos(),
            attributes:     HashMap::new(),
            status:         SpanStatus::Unset,
        }
    }

    pub fn add_attribute(&mut self, key: impl Into<String>, value: impl Into<String>) {
        self.attributes.insert(key.into(), value.into());
    }

    pub fn set_status(&mut self, status: SpanStatus) {
        self.status = status;
    }

    /// Closes this span and produces a `SpanRecord` (serialisable, storable).
    pub fn close(self) -> SpanRecord {
        let end_ns  = epoch_nanos();
        let duration = Duration::from_nanos(end_ns.saturating_sub(self.start_ns));
        SpanRecord {
            trace_id:       self.trace_id,
            span_id:        self.span_id,
            parent_span_id: self.parent_span_id,
            name:           self.name,
            start_ns:       self.start_ns,
            duration_us:    duration.as_micros() as u64,
            attributes:     self.attributes,
            status:         self.status,
        }
    }
}


// ── SpanRecord (closed span, serialisable) ────────────────────────────────────

/// A span that has been closed and is ready for storage or export.
/// This is what gets written to crash reports and trace logs.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SpanRecord {
    pub trace_id:       TraceId,
    pub span_id:        SpanId,
    pub parent_span_id: Option<SpanId>,
    pub name:           String,
    pub start_ns:       u64,
    pub duration_us:    u64,       // microseconds — avoids float in JSON
    pub attributes:     HashMap<String, String>,
    pub status:         SpanStatus,
}

impl SpanRecord {
    pub fn duration_ms(&self) -> f64 {
        self.duration_us as f64 / 1_000.0
    }

    /// Formats as a single JSON line for JSONL log files.
    pub fn to_jsonl(&self) -> String {
        serde_json::to_string(self).unwrap_or_else(|_| "{}".to_string())
    }
}


// ── Trace Log ─────────────────────────────────────────────────────────────────

/// An append-only log of closed spans.
/// Written to disk as `traces/{date}.jsonl` when flush is called.
#[derive(Default)]
pub struct TraceLog {
    records: std::sync::Mutex<Vec<SpanRecord>>,
    path:    Option<std::path::PathBuf>,
}

impl TraceLog {
    pub fn new(path: Option<std::path::PathBuf>) -> Self {
        Self { records: Default::default(), path }
    }

    /// Appends a closed span to the log.
    pub fn push(&self, record: SpanRecord) {
        if let Ok(mut records) = self.records.lock() {
            records.push(record);
        }
    }

    /// Drains all records to the log file (if configured) and returns them.
    pub fn flush(&self) -> Vec<SpanRecord> {
        let records = std::mem::take(&mut *self.records.lock().unwrap());
        if let Some(path) = &self.path {
            let _ = flush_jsonl(path, &records);
        }
        records
    }

    pub fn len(&self) -> usize {
        self.records.lock().map(|r| r.len()).unwrap_or(0)
    }

    pub fn is_empty(&self) -> bool { self.len() == 0 }
}

fn flush_jsonl(path: &std::path::Path, records: &[SpanRecord]) -> std::io::Result<()> {
    use std::io::Write;
    let mut file = std::fs::OpenOptions::new().create(true).append(true).open(path)?;
    for record in records {
        writeln!(file, "{}", record.to_jsonl())?;
    }
    Ok(())
}


// ── Helpers ───────────────────────────────────────────────────────────────────

fn epoch_nanos() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos() as u64
}