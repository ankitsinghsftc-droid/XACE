/*!
# metrics.rs — Counter, Histogram, Gauge

Lock-free metric types built on atomics. Zero allocation on the hot path.

## Types

| Type       | Behaviour                | Example               |
|------------|-------------------------|-----------------------|
| Counter    | Monotonically increases  | entity_count += 1     |
| Gauge      | Can go up or down        | memory_bytes = 4096   |
| Histogram  | Tracks value distribution| tick_duration_ms = 8.3|

## Thread Safety

- `Counter` and `Gauge` are backed by `AtomicU64` (f64 bit-cast for Gauge).
- `Histogram` uses a `Mutex<Vec<f64>>` for bucket updates — only on the recording
  path. The metrics text endpoint reads once per scrape. Not on the hot path.

## Prometheus Text Format

`MetricText::encode()` produces lines like:
```
# HELP entity_count Number of active entities
# TYPE entity_count counter
entity_count 5000
tick_duration_ms_p50 8.3
tick_duration_ms_p99 12.1
```
*/

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;


// ── Counter ───────────────────────────────────────────────────────────────────

/// A monotonically increasing counter.
pub struct Counter {
    name:  String,
    value: AtomicU64,
    help:  String,
}

impl Counter {
    pub fn new(name: impl Into<String>, help: impl Into<String>) -> Self {
        Self {
            name:  name.into(),
            value: AtomicU64::new(0),
            help:  help.into(),
        }
    }

    /// Increments the counter by `delta`.
    pub fn add(&self, delta: u64) {
        self.value.fetch_add(delta, Ordering::Relaxed);
    }

    /// Increments by 1.
    pub fn inc(&self) {
        self.add(1);
    }

    /// Returns the current value.
    pub fn get(&self) -> u64 {
        self.value.load(Ordering::Relaxed)
    }

    pub fn name(&self) -> &str { &self.name }
    pub fn help(&self) -> &str { &self.help }

    /// Encodes to Prometheus text format.
    pub fn encode(&self) -> String {
        format!(
            "# HELP {} {}\n# TYPE {} counter\n{} {}\n",
            self.name, self.help,
            self.name,
            self.name, self.get(),
        )
    }
}


// ── Gauge ─────────────────────────────────────────────────────────────────────

/// A gauge that can go up or down. Backed by an atomic f64 (bit-cast as u64).
pub struct Gauge {
    name:  String,
    value: AtomicU64,
    help:  String,
}

impl Gauge {
    pub fn new(name: impl Into<String>, help: impl Into<String>) -> Self {
        Self {
            name:  name.into(),
            value: AtomicU64::new(0),
            help:  help.into(),
        }
    }

    pub fn set(&self, v: f64) {
        self.value.store(v.to_bits(), Ordering::Relaxed);
    }

    pub fn add(&self, delta: f64) {
        // Compare-and-swap loop for atomic float add
        loop {
            let current_bits = self.value.load(Ordering::Relaxed);
            let current      = f64::from_bits(current_bits);
            let new_bits     = (current + delta).to_bits();
            if self.value.compare_exchange_weak(
                current_bits, new_bits, Ordering::Relaxed, Ordering::Relaxed,
            ).is_ok() {
                break;
            }
        }
    }

    pub fn get(&self) -> f64 {
        f64::from_bits(self.value.load(Ordering::Relaxed))
    }

    pub fn name(&self) -> &str { &self.name }
    pub fn help(&self) -> &str { &self.help }

    pub fn encode(&self) -> String {
        format!(
            "# HELP {} {}\n# TYPE {} gauge\n{} {:.6}\n",
            self.name, self.help,
            self.name,
            self.name, self.get(),
        )
    }
}


// ── Histogram ─────────────────────────────────────────────────────────────────

/// Records value distributions. Computes p50, p95, p99 on demand.
///
/// Not lock-free — uses a `Mutex<Vec<f64>>`. The mutex is only held during
/// `record()` and `encode()`. Neither happens on the simulation hot path.
pub struct Histogram {
    name:    String,
    samples: Mutex<Vec<f64>>,
    help:    String,
}

impl Histogram {
    pub fn new(name: impl Into<String>, help: impl Into<String>) -> Self {
        Self {
            name:    name.into(),
            samples: Mutex::new(Vec::with_capacity(1024)),
            help:    help.into(),
        }
    }

    pub fn record(&self, value: f64) {
        if let Ok(mut samples) = self.samples.lock() {
            // Cap at 10K samples to bound memory usage.
            // On overflow, drop the oldest 20% (sliding window).
            if samples.len() >= 10_000 {
                let keep_from = samples.len() / 5;
                samples.drain(..keep_from);
            }
            samples.push(value);
        }
    }

    pub fn count(&self) -> usize {
        self.samples.lock().map(|s| s.len()).unwrap_or(0)
    }

    pub fn percentile(&self, p: f64) -> Option<f64> {
        let mut samples = self.samples.lock().ok()?;
        if samples.is_empty() { return None; }
        samples.sort_by(|a, b| a.partial_cmp(b).unwrap());
        let idx = ((p / 100.0) * (samples.len() - 1) as f64).round() as usize;
        Some(samples[idx.min(samples.len() - 1)])
    }

    pub fn mean(&self) -> Option<f64> {
        let samples = self.samples.lock().ok()?;
        if samples.is_empty() { return None; }
        Some(samples.iter().sum::<f64>() / samples.len() as f64)
    }

    pub fn name(&self) -> &str { &self.name }
    pub fn help(&self) -> &str { &self.help }

    pub fn encode(&self) -> String {
        let p50 = self.percentile(50.0).unwrap_or(0.0);
        let p95 = self.percentile(95.0).unwrap_or(0.0);
        let p99 = self.percentile(99.0).unwrap_or(0.0);
        let count = self.count();

        format!(
            "# HELP {name} {help}\n\
             # TYPE {name} histogram\n\
             {name}_p50 {p50:.3}\n\
             {name}_p95 {p95:.3}\n\
             {name}_p99 {p99:.3}\n\
             {name}_count {count}\n",
            name  = self.name,
            help  = self.help,
            p50   = p50,
            p95   = p95,
            p99   = p99,
            count = count,
        )
    }
}


// ── Pre-defined XACE Metrics ──────────────────────────────────────────────────
// All metrics defined here are auto-registered in MetricsRegistry via METRICS.
// Names follow snake_case Prometheus convention.

use crate::metrics_registry::MetricsRegistry;
use std::sync::OnceLock;

static METRICS_INSTANCE: OnceLock<MetricsRegistry> = OnceLock::new();

/// Global metrics registry. All XACE layers access metrics through here.
pub static METRICS: MetricsRegistryRef = MetricsRegistryRef;

pub struct MetricsRegistryRef;

impl MetricsRegistryRef {
    pub fn get(&self) -> &'static MetricsRegistry {
        METRICS_INSTANCE.get_or_init(|| {
            let reg = MetricsRegistry::new();
            // ── Pre-register all standard XACE metrics ──────────────────────

            // Runtime Core
            reg.register_counter(  "entity_count",         "Total active entities");
            reg.register_counter(  "entity_created_total", "Entities created lifetime");
            reg.register_counter(  "entity_destroyed_total","Entities destroyed lifetime");
            reg.register_histogram("tick_duration_ms",     "Wall-clock time per simulation tick (ms)");
            reg.register_histogram("mutation_queue_depth", "Pending mutations at tick start");
            reg.register_counter(  "mutation_applied_total","Mutations applied lifetime");

            // System execution
            reg.register_histogram("system_execute_us",    "System execution time (microseconds)");
            reg.register_counter(  "system_runs_total",    "Total system execute() calls");

            // Memory
            reg.register_gauge(    "memory_heap_bytes",    "JVM-style heap approximation (bytes)");

            // Inference / PIL
            reg.register_counter(  "llm_tokens_input",     "Total LLM input tokens consumed");
            reg.register_counter(  "llm_tokens_output",    "Total LLM output tokens consumed");
            reg.register_counter(  "llm_cache_read_tokens","Tokens served from prompt cache");
            reg.register_histogram("llm_latency_ms",       "LLM call wall-clock latency (ms)");
            reg.register_histogram("llm_cost_cents",       "LLM call cost in USD cents");
            reg.register_counter(  "llm_calls_total",      "Total LLM calls dispatched");
            reg.register_counter(  "llm_tier_s_total",     "Calls routed to deterministic shortcut");
            reg.register_counter(  "llm_cache_hits_total", "Calls served from response cache");

            // Schema / GDE
            reg.register_histogram("schema_commit_ms",     "CGS commit wall-clock time (ms)");
            reg.register_counter(  "schema_commits_total", "Total CGS commits");

            // Engine adapter
            reg.register_counter(  "delta_bytes_sent",     "Total bytes sent via delta sync");
            reg.register_counter(  "snapshot_bytes_sent",  "Total bytes sent in snapshots");
            reg.register_histogram("adapter_round_trip_ms","Engine adapter round-trip (ms)");

            reg
        })
    }

    pub fn counter(&self, name: &str)   -> &'static Counter   { self.get().counter(name) }
    pub fn gauge(&self, name: &str)     -> &'static Gauge      { self.get().gauge(name) }
    pub fn histogram(&self, name: &str) -> &'static Histogram  { self.get().histogram(name) }

    /// Encodes all registered metrics in Prometheus text format.
    pub fn encode_text(&self) -> String { self.get().encode_all() }
}