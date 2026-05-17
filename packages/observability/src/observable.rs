/*!
# observable.rs — Observable Trait

Provides the interface other XACE layers use to emit observability events.

## Why a trait instead of direct calls?

Layers that want to emit traces and metrics must depend on this crate.
If they called `TRACER` and `METRICS` globals directly, that would work
but would make testing harder (can't inject a mock observer).

The `Observable` trait lets you inject any observer implementation —
real tracer in production, capturing mock in tests.

## Usage

```rust
// In any layer (e.g. runtime-core system executor):
use xace_observability::observable::Observable;

struct MySystem;

impl MySystem {
    fn execute(&self, obs: &dyn Observable) {
        let _span = obs.span("my_system_execute");
        obs.counter("my_system_runs", 1);
        // ... system logic ...
    }
}
```
*/

use std::sync::Arc;

use crate::trace::{Span, SpanId, TraceId};


// ── Observable Trait ──────────────────────────────────────────────────────────

/// Interface implemented by any layer that wants to emit observability events.
///
/// In production, pass the global `TRACER` and `METRICS` implementations.
/// In tests, inject a `CapturingObserver` to assert what was emitted.
pub trait Observable: Send + Sync {
    /// Opens a named span within the current trace context.
    /// The returned `SpanId` can be used to add attributes or close the span.
    fn enter_span(&self, name: &str) -> SpanId;

    /// Closes a previously opened span.
    fn exit_span(&self, id: SpanId);

    /// Adds a key=value attribute to the current span.
    fn span_attribute(&self, key: &str, value: &str);

    /// Increments a counter by `delta`.
    fn counter(&self, name: &str, delta: u64);

    /// Records one sample in a histogram.
    fn histogram(&self, name: &str, value: f64);

    /// Sets a gauge (can go up or down).
    fn gauge(&self, name: &str, value: f64);

    /// Emits a structured log line (key=value pairs).
    fn log_event(&self, message: &str, attributes: &[(&str, &str)]);

    /// Returns the current active TraceId, if any.
    fn current_trace_id(&self) -> Option<TraceId>;
}


// ── No-op Observer ────────────────────────────────────────────────────────────

/// An `Observable` that discards all events. Use in unit tests that don't
/// care about observability output, or when observability is disabled.
pub struct NoopObserver;

impl Observable for NoopObserver {
    fn enter_span(&self, _: &str)                          -> SpanId    { SpanId::ZERO }
    fn exit_span(&self, _: SpanId)                                       {}
    fn span_attribute(&self, _: &str, _: &str)                           {}
    fn counter(&self, _: &str, _: u64)                                   {}
    fn histogram(&self, _: &str, _: f64)                                 {}
    fn gauge(&self, _: &str, _: f64)                                     {}
    fn log_event(&self, _: &str, _: &[(&str, &str)])                     {}
    fn current_trace_id(&self)                             -> Option<TraceId> { None }
}


// ── Capturing Observer (for tests) ────────────────────────────────────────────

/// An `Observable` that captures all events for later inspection.
/// Used in tests to assert what observability events were emitted.
///
/// ```rust
/// let obs = CapturingObserver::new();
/// my_system.execute(&obs);
/// assert_eq!(obs.counters["my_system_runs"], 3);
/// ```
pub struct CapturingObserver {
    pub spans:    std::sync::Mutex<Vec<(String, SpanId)>>,
    pub counters: std::sync::Mutex<std::collections::HashMap<String, u64>>,
    pub gauges:   std::sync::Mutex<std::collections::HashMap<String, f64>>,
    pub logs:     std::sync::Mutex<Vec<String>>,
}

impl CapturingObserver {
    pub fn new() -> Self {
        Self {
            spans:    std::sync::Mutex::new(Vec::new()),
            counters: std::sync::Mutex::new(std::collections::HashMap::new()),
            gauges:   std::sync::Mutex::new(std::collections::HashMap::new()),
            logs:     std::sync::Mutex::new(Vec::new()),
        }
    }

    pub fn counter_value(&self, name: &str) -> u64 {
        *self.counters.lock().unwrap().get(name).unwrap_or(&0)
    }

    pub fn gauge_value(&self, name: &str) -> f64 {
        *self.gauges.lock().unwrap().get(name).unwrap_or(&0.0)
    }

    pub fn span_count(&self) -> usize {
        self.spans.lock().unwrap().len()
    }

    pub fn log_count(&self) -> usize {
        self.logs.lock().unwrap().len()
    }

    pub fn was_logged(&self, substr: &str) -> bool {
        self.logs.lock().unwrap().iter().any(|l| l.contains(substr))
    }
}

impl Default for CapturingObserver {
    fn default() -> Self { Self::new() }
}

impl Observable for CapturingObserver {
    fn enter_span(&self, name: &str) -> SpanId {
        let id = SpanId::new_unique();
        self.spans.lock().unwrap().push((name.to_owned(), id));
        id
    }

    fn exit_span(&self, _: SpanId) {}

    fn span_attribute(&self, _: &str, _: &str) {}

    fn counter(&self, name: &str, delta: u64) {
        *self.counters.lock().unwrap().entry(name.to_owned()).or_insert(0) += delta;
    }

    fn histogram(&self, _: &str, _: f64) {}

    fn gauge(&self, name: &str, value: f64) {
        self.gauges.lock().unwrap().insert(name.to_owned(), value);
    }

    fn log_event(&self, message: &str, attributes: &[(&str, &str)]) {
        let attrs: String = attributes.iter().map(|(k, v)| format!(" {}={}", k, v)).collect();
        self.logs.lock().unwrap().push(format!("{}{}", message, attrs));
    }

    fn current_trace_id(&self) -> Option<TraceId> { None }
}


// ── ObservabilityTarget ───────────────────────────────────────────────────────

/// Dependency-injectable observability handle.
///
/// Passed into layers at construction time. Wraps an `Arc<dyn Observable>`
/// so it is cheaply cloneable across threads and systems.
///
/// ```rust
/// // In production (main.rs):
/// let obs = ObservabilityTarget::global();
///
/// // In tests:
/// let capturing = Arc::new(CapturingObserver::new());
/// let obs = ObservabilityTarget::from(capturing.clone());
/// my_system.execute(&obs);
/// assert_eq!(capturing.counter_value("tick_count"), 10);
/// ```
#[derive(Clone)]
pub struct ObservabilityTarget(Arc<dyn Observable>);

impl ObservabilityTarget {
    /// Creates a target backed by the global production tracer + metrics.
    pub fn global() -> Self {
        use crate::tracer::GlobalObservable;
        Self(Arc::new(GlobalObservable))
    }

    /// Creates a no-op target — zero overhead.
    pub fn noop() -> Self {
        Self(Arc::new(NoopObserver))
    }

    /// Creates a target from any `Observable` implementation (e.g. for tests).
    pub fn from_arc(obs: Arc<dyn Observable>) -> Self {
        Self(obs)
    }
}

impl std::ops::Deref for ObservabilityTarget {
    type Target = dyn Observable;
    fn deref(&self) -> &Self::Target { &*self.0 }
}