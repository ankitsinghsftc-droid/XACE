/*!
# tick_ring_buffer.rs — Tick History Ring Buffer

Stores the last N `TickRecord`s for crash reporting and diagnostics.

## Design

SPSC (Single Producer, Single Consumer):
- Producer: Phase Orchestrator writes one record per tick.
- Consumer: crash_reporter reads all records on panic (rare path).

The write path is lock-free (atomic index + fixed-size array).
The read path is only called during crashes — performance there is irrelevant.

## Configuration

Default size: 100 ticks. Configurable via `runtime_config.yaml`:
```yaml
observability:
  tick_history_size: 100
```

## Invariants

- Old records are overwritten when the buffer is full (oldest evicted).
- Iteration from `recent()` returns records newest-first.
- Thread safety: one writer (Phase Orchestrator thread), one reader
  (crash reporter, only during panic — never concurrent with writer).
*/

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Mutex, OnceLock};

use serde::{Deserialize, Serialize};

use crate::trace::TraceId;


// ── TickRecord ────────────────────────────────────────────────────────────────

/// One tick's worth of observability data.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TickRecord {
    pub tick_number:        u64,
    pub world_hash:         String,    // hex-encoded u256/u64 hash
    pub duration_ms:        f64,
    pub entity_count:       u64,
    pub mutation_count:     u64,
    pub active_trace_id:    Option<TraceId>,
    pub determinism_violations: u32,   // count of D-rule fires this tick
    pub timestamp_ms:       u64,       // milliseconds since UNIX epoch
}

impl TickRecord {
    pub fn new(
        tick_number:    u64,
        world_hash:     impl Into<String>,
        duration_ms:    f64,
        entity_count:   u64,
        mutation_count: u64,
    ) -> Self {
        use std::time::{SystemTime, UNIX_EPOCH};
        Self {
            tick_number,
            world_hash:         world_hash.into(),
            duration_ms,
            entity_count,
            mutation_count,
            active_trace_id:    crate::tracer::current_trace_id(),
            determinism_violations: 0,
            timestamp_ms: SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_millis() as u64,
        }
    }

    pub fn with_violations(mut self, count: u32) -> Self {
        self.determinism_violations = count;
        self
    }
}


// ── Ring Buffer ───────────────────────────────────────────────────────────────

/// Fixed-size ring buffer for `TickRecord`s.
///
/// Write: O(1) lock-free (atomic CAS on head index).
/// Read: O(n) under a Mutex — only called during crash reporting.
pub struct TickRingBuffer {
    capacity: usize,
    slots:    Mutex<Vec<Option<TickRecord>>>,
    head:     AtomicUsize,   // next write position (wraps around)
    count:    AtomicUsize,   // number of valid records (caps at capacity)
}

impl TickRingBuffer {
    pub fn new(capacity: usize) -> Self {
        assert!(capacity > 0, "TickRingBuffer capacity must be > 0");
        let slots = (0..capacity).map(|_| None).collect();
        Self {
            capacity,
            slots: Mutex::new(slots),
            head:  AtomicUsize::new(0),
            count: AtomicUsize::new(0),
        }
    }

    /// Writes one tick record. Overwrites the oldest if the buffer is full.
    pub fn push(&self, record: TickRecord) {
        // Acquire the write slot
        let head = self.head.fetch_add(1, Ordering::Relaxed) % self.capacity;
        if let Ok(mut slots) = self.slots.lock() {
            slots[head] = Some(record);
        }
        self.count.fetch_min(self.capacity, Ordering::Relaxed);
        let new_count = self.count.load(Ordering::Relaxed);
        if new_count < self.capacity {
            self.count.fetch_add(1, Ordering::Relaxed);
        }
    }

    /// Returns up to `n` most recent records, newest-first.
    /// Should only be called from crash_reporter — holds the Mutex.
    pub fn recent(&self, n: usize) -> Vec<TickRecord> {
        let slots   = self.slots.lock().unwrap();
        let count   = self.count.load(Ordering::Relaxed);
        let head    = self.head.load(Ordering::Relaxed);
        let take    = n.min(count);

        let mut result = Vec::with_capacity(take);
        for i in 0..take {
            // Walk backwards from head
            let idx = (head + self.capacity - 1 - i) % self.capacity;
            if let Some(record) = &slots[idx] {
                result.push(record.clone());
            }
        }
        result
    }

    /// Returns all records that had determinism violations.
    pub fn determinism_violations(&self) -> Vec<TickRecord> {
        let slots = self.slots.lock().unwrap();
        slots.iter()
             .flatten()
             .filter(|r| r.determinism_violations > 0)
             .cloned()
             .collect()
    }

    pub fn capacity(&self) -> usize { self.capacity }

    pub fn len(&self) -> usize { self.count.load(Ordering::Relaxed) }

    pub fn is_empty(&self) -> bool { self.len() == 0 }
}


// ── Global Tick Buffer ────────────────────────────────────────────────────────

static TICK_BUFFER_INSTANCE: OnceLock<TickRingBuffer> = OnceLock::new();

/// The global tick history ring buffer.
///
/// Runtime Core's Phase Orchestrator calls `TICK_BUFFER.push(...)` after each tick.
/// Crash reporter calls `TICK_BUFFER.recent(100)` on panic.
pub static TICK_BUFFER: TickBufferRef = TickBufferRef;

pub struct TickBufferRef;

impl TickBufferRef {
    pub fn get(&self) -> &'static TickRingBuffer {
        TICK_BUFFER_INSTANCE.get_or_init(|| TickRingBuffer::new(100))
    }

    pub fn push(&self, record: TickRecord) {
        self.get().push(record);
    }

    pub fn recent(&self, n: usize) -> Vec<TickRecord> {
        self.get().recent(n)
    }

    pub fn configure(&self, capacity: usize) {
        // One-time init — must be called before any push() or the default (100) is used.
        let _ = TICK_BUFFER_INSTANCE.get_or_init(|| TickRingBuffer::new(capacity));
    }
}