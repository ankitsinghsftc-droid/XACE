/*!
# metrics_registry.rs — MetricsRegistry

Thread-safe, name-keyed registry for all metric instances.

Metrics are registered at program start via `METRICS.get()` initialisation
and accessed by name from any thread during the simulation.

All returned references are `'static` — metrics are never removed from
the registry. This is intentional: removing a metric while another thread
holds a reference to it would be unsound.
*/

use std::collections::HashMap;
use std::sync::RwLock;

use crate::metrics::{Counter, Gauge, Histogram};


// ── Storage ───────────────────────────────────────────────────────────────────

// We store each metric type in a separate map to avoid boxing.
// The maps hold `Box<Metric>` and return `&'static Metric` via raw pointer.
// Safety: boxes are never removed (see invariant above); pointer is valid for
// the program's lifetime.

struct CounterMap(RwLock<HashMap<String, Box<Counter>>>);
struct GaugeMap(RwLock<HashMap<String, Box<Gauge>>>);
struct HistogramMap(RwLock<HashMap<String, Box<Histogram>>>);


// ── MetricsRegistry ───────────────────────────────────────────────────────────

pub struct MetricsRegistry {
    counters:   CounterMap,
    gauges:     GaugeMap,
    histograms: HistogramMap,
}

impl MetricsRegistry {
    pub fn new() -> Self {
        Self {
            counters:   CounterMap(RwLock::new(HashMap::new())),
            gauges:     GaugeMap(RwLock::new(HashMap::new())),
            histograms: HistogramMap(RwLock::new(HashMap::new())),
        }
    }

    // ── Registration (called once at startup) ─────────────────────────────────

    pub fn register_counter(&self, name: &str, help: &str) {
        let mut map = self.counters.0.write().unwrap();
        map.entry(name.to_owned())
           .or_insert_with(|| Box::new(Counter::new(name, help)));
    }

    pub fn register_gauge(&self, name: &str, help: &str) {
        let mut map = self.gauges.0.write().unwrap();
        map.entry(name.to_owned())
           .or_insert_with(|| Box::new(Gauge::new(name, help)));
    }

    pub fn register_histogram(&self, name: &str, help: &str) {
        let mut map = self.histograms.0.write().unwrap();
        map.entry(name.to_owned())
           .or_insert_with(|| Box::new(Histogram::new(name, help)));
    }

    // ── Lazy-create access (for dynamic metric names, e.g. per-system) ────────

    /// Returns a `'static` reference to a Counter by name.
    /// Creates the counter (with empty help) if it doesn't exist yet.
    pub fn counter(&self, name: &str) -> &'static Counter {
        // Fast path: read lock
        {
            let map = self.counters.0.read().unwrap();
            if let Some(counter) = map.get(name) {
                return unsafe { &*(counter.as_ref() as *const Counter) };
            }
        }
        // Slow path: write lock + insert
        let mut map = self.counters.0.write().unwrap();
        let counter = map.entry(name.to_owned())
            .or_insert_with(|| Box::new(Counter::new(name, "")));
        unsafe { &*(counter.as_ref() as *const Counter) }
    }

    pub fn gauge(&self, name: &str) -> &'static Gauge {
        {
            let map = self.gauges.0.read().unwrap();
            if let Some(g) = map.get(name) {
                return unsafe { &*(g.as_ref() as *const Gauge) };
            }
        }
        let mut map = self.gauges.0.write().unwrap();
        let g = map.entry(name.to_owned())
            .or_insert_with(|| Box::new(Gauge::new(name, "")));
        unsafe { &*(g.as_ref() as *const Gauge) }
    }

    pub fn histogram(&self, name: &str) -> &'static Histogram {
        {
            let map = self.histograms.0.read().unwrap();
            if let Some(h) = map.get(name) {
                return unsafe { &*(h.as_ref() as *const Histogram) };
            }
        }
        let mut map = self.histograms.0.write().unwrap();
        let h = map.entry(name.to_owned())
            .or_insert_with(|| Box::new(Histogram::new(name, "")));
        unsafe { &*(h.as_ref() as *const Histogram) }
    }

    // ── Prometheus Text Format ────────────────────────────────────────────────

    pub fn encode_all(&self) -> String {
        let mut out = String::with_capacity(8192);

        // Counters
        for (_, counter) in self.counters.0.read().unwrap().iter() {
            out.push_str(&counter.encode());
            out.push('\n');
        }

        // Gauges
        for (_, gauge) in self.gauges.0.read().unwrap().iter() {
            out.push_str(&gauge.encode());
            out.push('\n');
        }

        // Histograms (sorted by name for stable output)
        let histograms = self.histograms.0.read().unwrap();
        let mut names: Vec<&str> = histograms.keys().map(|s| s.as_str()).collect();
        names.sort_unstable();
        for name in names {
            if let Some(h) = histograms.get(name) {
                out.push_str(&h.encode());
                out.push('\n');
            }
        }

        out
    }

    pub fn counter_names(&self) -> Vec<String> {
        self.counters.0.read().unwrap().keys().cloned().collect()
    }

    pub fn gauge_names(&self) -> Vec<String> {
        self.gauges.0.read().unwrap().keys().cloned().collect()
    }

    pub fn histogram_names(&self) -> Vec<String> {
        self.histograms.0.read().unwrap().keys().cloned().collect()
    }
}

impl Default for MetricsRegistry {
    fn default() -> Self { Self::new() }
}