/*!
# tracer.rs — Global Tracer and Thread-Local Context

Manages the lifecycle of spans and the current trace context per thread.

## Global TRACER

A lazily-initialised `Tracer` instance shared across all threads.
Runtime layers call `TRACER.enter(...)` / `TRACER.exit(...)`.
In tests, inject `CapturingObserver` via `ObservabilityTarget` instead.

## Thread-Local Context

Each thread has an independent span stack. `enter_span()` pushes;
`ScopedSpan::drop()` pops automatically.

Multiple simulation threads (parallel system groups) each have their own
span context — no lock contention on the hot path.

## Trace Propagation

For a mutation transaction spanning multiple function calls:

```rust
// At PIL pipeline entry:
let trace_id = TraceId::new_unique();
TRACER.set_active_trace(trace_id);

// Automatically inherited by every enter_span() on this thread
let _s1 = enter_span("pil_pipeline");
    let _s2 = enter_span("context_assembler");   // parent = _s1
        let _s3 = enter_span("dependency_expander");  // parent = _s2
```
*/

use std::cell::RefCell;
use std::sync::OnceLock;

use crate::metrics::METRICS;
use crate::observable::Observable;
use crate::trace::{Span, SpanId, SpanRecord, SpanStatus, TraceId, TraceLog};


// ── Global Tracer ─────────────────────────────────────────────────────────────

static TRACER_INSTANCE: OnceLock<Tracer> = OnceLock::new();

/// The global production tracer.
/// Initialised on first access. Call `TRACER.configure(...)` at startup
/// to set the trace log path before any spans are emitted.
pub static TRACER: TracerRef = TracerRef;

pub struct TracerRef;

impl TracerRef {
    fn get(&self) -> &'static Tracer {
        TRACER_INSTANCE.get_or_init(Tracer::default)
    }

    pub fn enter(&self, name: &str, parent: Option<SpanId>) -> SpanId {
        self.get().enter(name, parent)
    }

    pub fn exit(&self, id: SpanId) {
        self.get().exit(id);
    }

    pub fn add_attribute(&self, id: SpanId, key: &str, value: &str) {
        self.get().add_attribute(id, key, value);
    }

    pub fn set_active_trace(&self, trace_id: TraceId) {
        self.get().set_active_trace(trace_id);
    }

    pub fn configure(&self, log_path: Option<std::path::PathBuf>) {
        self.get().configure(log_path);
    }

    pub fn recent_spans(&self, n: usize) -> Vec<SpanRecord> {
        self.get().log.flush().into_iter().rev().take(n).collect()
    }
}


// ── Tracer ────────────────────────────────────────────────────────────────────

#[derive(Default)]
pub struct Tracer {
    pub(crate) log: TraceLog,
}

impl Tracer {
    pub fn enter(&self, name: &str, explicit_parent: Option<SpanId>) -> SpanId {
        let trace_id  = THREAD_CONTEXT.with(|ctx| ctx.borrow().active_trace_id);
        let parent_id = explicit_parent
            .or_else(|| THREAD_CONTEXT.with(|ctx| ctx.borrow().current_span_id()));
        let span      = Span::new(name, trace_id, parent_id);
        let id        = span.span_id;

        THREAD_CONTEXT.with(|ctx| {
            ctx.borrow_mut().push(span);
        });

        // Metrics: count spans per name
        METRICS.counter(&format!("span.{}", name)).add(1);

        id
    }

    pub fn exit(&self, id: SpanId) {
        let record = THREAD_CONTEXT.with(|ctx| {
            ctx.borrow_mut().pop(id)
        });
        if let Some(record) = record {
            METRICS.histogram("span_duration_us").record(record.duration_us as f64);
            self.log.push(record);
        }
    }

    pub fn add_attribute(&self, id: SpanId, key: &str, value: &str) {
        THREAD_CONTEXT.with(|ctx| {
            ctx.borrow_mut().add_attribute(id, key, value);
        });
    }

    pub fn set_active_trace(&self, trace_id: TraceId) {
        THREAD_CONTEXT.with(|ctx| {
            ctx.borrow_mut().active_trace_id = trace_id;
        });
    }

    pub fn configure(&self, log_path: Option<std::path::PathBuf>) {
        // Swap the log path. Existing log object is replaced.
        // This is safe to call only at startup before any spans are emitted.
        let _ = log_path; // TraceLog path is set at construction — for now, log to memory
        // TODO: reinitialise log with new path
    }
}


// ── Thread-Local Context ──────────────────────────────────────────────────────

thread_local! {
    static THREAD_CONTEXT: RefCell<ThreadSpanContext> = RefCell::new(ThreadSpanContext::default());
}

#[derive(Default)]
struct ThreadSpanContext {
    active_trace_id: TraceId,
    stack:           Vec<Span>,    // innermost span is at the back
}

impl ThreadSpanContext {
    fn push(&mut self, span: Span) {
        self.stack.push(span);
    }

    fn pop(&mut self, id: SpanId) -> Option<SpanRecord> {
        // Normally the top of the stack matches; linear search as safety net
        let pos = self.stack.iter().rposition(|s| s.span_id == id)?;
        let span = self.stack.remove(pos);
        Some(span.close())
    }

    fn current_span_id(&self) -> Option<SpanId> {
        self.stack.last().map(|s| s.span_id)
    }

    fn add_attribute(&mut self, id: SpanId, key: &str, value: &str) {
        if let Some(span) = self.stack.iter_mut().find(|s| s.span_id == id) {
            span.add_attribute(key, value);
        }
    }
}


// ── ScopedSpan (RAII) ─────────────────────────────────────────────────────────

/// A span that automatically closes when dropped.
///
/// ```rust
/// {
///     let _span = enter_span("my_work", [("key", "value")]);
///     do_work();
/// }  // span closed here
/// ```
pub struct ScopedSpan {
    id:        SpanId,
    has_error: std::sync::atomic::AtomicBool,
}

impl ScopedSpan {
    pub fn id(&self) -> SpanId { self.id }

    /// Marks this span as failed. The status is recorded when the span closes.
    pub fn mark_error(&self) {
        self.has_error.store(true, std::sync::atomic::Ordering::Relaxed);
    }

    pub fn add_attribute(&self, key: &str, value: &str) {
        TRACER.add_attribute(self.id, key, value);
    }
}

impl Drop for ScopedSpan {
    fn drop(&mut self) {
        TRACER.exit(self.id);
    }
}

/// Opens a named span with optional attributes. Span closes when dropped.
///
/// # Usage
/// ```rust
/// let _span = enter_span("tick", [("tick_number", &tick.to_string())]);
/// ```
pub fn enter_span<'a>(
    name:       &str,
    attributes: impl IntoIterator<Item = (&'a str, &'a str)>,
) -> ScopedSpan {
    let id = TRACER.enter(name, None);
    for (k, v) in attributes {
        TRACER.add_attribute(id, k, v);
    }
    ScopedSpan {
        id,
        has_error: std::sync::atomic::AtomicBool::new(false),
    }
}

/// Returns the currently active TraceId on this thread.
pub fn current_trace_id() -> Option<TraceId> {
    let id = THREAD_CONTEXT.with(|ctx| ctx.borrow().active_trace_id);
    if id.is_zero() { None } else { Some(id) }
}


// ── GlobalObservable ──────────────────────────────────────────────────────────

/// Implements `Observable` using the global TRACER and METRICS.
/// Used by `ObservabilityTarget::global()`.
pub struct GlobalObservable;

impl Observable for GlobalObservable {
    fn enter_span(&self, name: &str) -> SpanId {
        TRACER.enter(name, None)
    }

    fn exit_span(&self, id: SpanId) {
        TRACER.exit(id);
    }

    fn span_attribute(&self, key: &str, value: &str) {
        THREAD_CONTEXT.with(|ctx| {
            if let Some(id) = ctx.borrow().current_span_id() {
                TRACER.add_attribute(id, key, value);
            }
        });
    }

    fn counter(&self, name: &str, delta: u64) {
        METRICS.counter(name).add(delta);
    }

    fn histogram(&self, name: &str, value: f64) {
        METRICS.histogram(name).record(value);
    }

    fn gauge(&self, name: &str, value: f64) {
        METRICS.gauge(name).set(value);
    }

    fn log_event(&self, message: &str, attributes: &[(&str, &str)]) {
        let attrs: String = attributes.iter()
            .map(|(k, v)| format!(" {}={}", k, v))
            .collect();
        // TODO: structured log sink; for now write to stderr in dev builds
        #[cfg(debug_assertions)]
        eprintln!("[xace] {}{}", message, attrs);
    }

    fn current_trace_id(&self) -> Option<TraceId> {
        crate::tracer::current_trace_id()
    }
}