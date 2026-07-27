/*!
# XACE Observability — Layer 0

Tracing, metrics, health-check, and crash reporting for the XACE runtime.

## Architectural Invariant — Layer 0

This crate is Layer 0. It:
- MAY be imported by any other XACE layer
- MUST NOT import any other XACE layer (no `xace-runtime-core`, `xace-gde`, etc.)
- MUST NOT introduce circular dependencies

Enforcement: `ci/check_obs_deps.sh` fails the build if a path-dep to any
`xace-*` crate appears in this crate's `Cargo.toml`.

## Quick Start

```rust
use xace_observability::{
    tracer,
    metrics::METRICS,
    health_check::HealthWriter,
    crash_reporter,
};

// Install crash handler before anything else
crash_reporter::install();

// Start health-check HTTP server on port 9090
HealthWriter::start(9090);

// Emit a trace span
let _span = tracer::enter_span("tick", [("tick_number", "1000")]);

// Increment a counter
METRICS.counter("entity_count").add(42);
```
*/

pub mod crash_reporter;
pub mod health_check;
pub mod http_server;
pub mod metrics;
pub mod metrics_registry;
pub mod observable;
pub mod tick_ring_buffer;
pub mod trace;
pub mod tracer;

// ── Convenient top-level re-exports ──────────────────────────────────────────

pub use crash_reporter::install as install_crash_handler;
pub use metrics::METRICS;
pub use observable::{ObservabilityTarget, Observable};
pub use tick_ring_buffer::{TickRecord, TickRingBuffer, TICK_BUFFER};
pub use trace::{Span, SpanId, TraceId};
pub use tracer::{current_trace_id, enter_span, ScopedSpan, TRACER};
