"""
telemetry_pipeline.py — TelemetryPipeline
==========================================
Emits one InferenceTelemetryEvent per LLM call and appends it to the
session log. Enforces Inference Invariant II8: zero silent calls.

Every path through InferenceAdapter.call() — success, cache hit,
TIER_S shortcut, transport failure, budget rejection — emits an event.
The telemetry log is the canonical record of what the system spent.

## Event Schema
One InferenceTelemetryEvent per call:
    request_id         — UUID from the InferenceRequest
    session_id         — builder session
    call_label         — "pass1_planning", "pass2_dsl_draft", etc.
    provider           — "anthropic" | "openai" | "deepseek" | "zai" | "minimax"
                         | "deterministic" | "response_cache"
    model_id           — concrete model string
    complexity_tier    — TIER_S | TIER_M | TIER_L | TIER_XL
    input_tokens       — non-cached input tokens
    output_tokens      — tokens generated
    cache_read_tokens  — tokens served from cache (cost ~10% of input)
    cache_write_tokens — tokens written to cache this call
    cost_cents         — total USD cents for this call
    latency_ms         — wall-clock time including retry
    outcome            — "success" | "cache_hit" | "deterministic_shortcut"
                         | "transport_error" | "budget_exceeded" | "schema_error"
    cached             — True when response came from response_cache

## Storage Backends
TelemetryPipeline is backend-agnostic. Register a TelemetryBackend
for each destination. Default: InMemoryBackend (dev/test).
Production deployments add FileBackend or RemoteBackend.

## Thread Safety
TelemetryPipeline is thread-safe. emit() acquires a lock before
writing to all backends.
"""

from __future__ import annotations

import threading
import time
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Any


# ── Telemetry Event ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class InferenceTelemetryEvent:
    """
    Immutable record of one LLM call attempt.

    All numeric fields default to 0 so callers only set what they know.
    cost_cents is pre-calculated by InferenceAdapter using ModelDescriptor.
    """

    request_id:         str
    session_id:         str
    call_label:         str
    provider:           str
    model_id:           str
    complexity_tier:    str                = "TIER_L"
    input_tokens:       int                = 0
    output_tokens:      int                = 0
    cache_read_tokens:  int                = 0
    cache_write_tokens: int                = 0
    cost_cents:         float              = 0.0
    latency_ms:         float              = 0.0
    outcome:            str                = "success"
    cached:             bool               = False
    timestamp:          float              = field(default_factory=time.time)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def effective_input_tokens(self) -> int:
        """Total input billed: non-cached input + cache reads (at reduced rate)."""
        return self.input_tokens + self.cache_read_tokens

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))

    def __repr__(self) -> str:
        return (
            f"TelemetryEvent("
            f"{self.call_label!r}, "
            f"{self.provider}/{self.model_id}, "
            f"tokens={self.total_tokens}, "
            f"cost={self.cost_cents:.4f}¢, "
            f"outcome={self.outcome!r})"
        )


# ── Session Summary ───────────────────────────────────────────────────────────

@dataclass
class SessionTelemetrySummary:
    """Aggregated totals for one builder session."""

    session_id:         str
    total_calls:        int   = 0
    cached_calls:       int   = 0
    deterministic_calls: int  = 0
    total_input_tokens: int   = 0
    total_output_tokens: int  = 0
    total_cache_read_tokens: int = 0
    total_cache_write_tokens: int = 0
    total_cost_cents:   float = 0.0
    total_latency_ms:   float = 0.0
    calls_by_tier:      dict[str, int]   = field(default_factory=dict)
    calls_by_provider:  dict[str, int]   = field(default_factory=dict)
    calls_by_outcome:   dict[str, int]   = field(default_factory=dict)

    def absorb(self, event: InferenceTelemetryEvent) -> None:
        self.total_calls          += 1
        self.total_input_tokens   += event.input_tokens
        self.total_output_tokens  += event.output_tokens
        self.total_cache_read_tokens  += event.cache_read_tokens
        self.total_cache_write_tokens += event.cache_write_tokens
        self.total_cost_cents     += event.cost_cents
        self.total_latency_ms     += event.latency_ms

        if event.cached:
            self.cached_calls += 1
        if event.outcome == "deterministic_shortcut":
            self.deterministic_calls += 1

        self.calls_by_tier[event.complexity_tier]  = \
            self.calls_by_tier.get(event.complexity_tier, 0) + 1
        self.calls_by_provider[event.provider]     = \
            self.calls_by_provider.get(event.provider, 0) + 1
        self.calls_by_outcome[event.outcome]       = \
            self.calls_by_outcome.get(event.outcome, 0) + 1

    @property
    def cache_hit_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return (self.cached_calls + self.deterministic_calls) / self.total_calls

    @property
    def avg_cost_cents(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.total_cost_cents / self.total_calls

    @property
    def avg_latency_ms(self) -> float:
        live = self.total_calls - self.cached_calls - self.deterministic_calls
        if live == 0:
            return 0.0
        return self.total_latency_ms / live


# ── Backend Interface ─────────────────────────────────────────────────────────

class ITelemetryBackend(ABC):
    """Interface for telemetry storage. Implement for file, DB, or remote sink."""

    @abstractmethod
    def write(self, event: InferenceTelemetryEvent) -> None:
        """Writes one event. Must be non-blocking or have bounded latency."""

    @abstractmethod
    def flush(self) -> None:
        """Flushes any buffered events."""


# ── Backends ──────────────────────────────────────────────────────────────────

class InMemoryBackend(ITelemetryBackend):
    """
    Stores events in a list. Used in dev/test.
    Provides query helpers for assertions in tests.
    """

    def __init__(self, max_events: int = 10_000) -> None:
        self._events:    list[InferenceTelemetryEvent] = []
        self._max        = max_events
        self._lock       = threading.Lock()

    def write(self, event: InferenceTelemetryEvent) -> None:
        with self._lock:
            if len(self._events) >= self._max:
                self._events.pop(0)  # drop oldest on overflow
            self._events.append(event)

    def flush(self) -> None:
        pass  # already in memory

    def all_events(self) -> list[InferenceTelemetryEvent]:
        with self._lock:
            return list(self._events)

    def events_for_session(self, session_id: str) -> list[InferenceTelemetryEvent]:
        with self._lock:
            return [e for e in self._events if e.session_id == session_id]

    def events_by_outcome(self, outcome: str) -> list[InferenceTelemetryEvent]:
        with self._lock:
            return [e for e in self._events if e.outcome == outcome]

    def events_by_label(self, call_label: str) -> list[InferenceTelemetryEvent]:
        with self._lock:
            return [e for e in self._events if e.call_label == call_label]

    def total_cost_cents(self, session_id: str | None = None) -> float:
        with self._lock:
            events = (
                [e for e in self._events if e.session_id == session_id]
                if session_id else self._events
            )
            return sum(e.cost_cents for e in events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


class FileBackend(ITelemetryBackend):
    """
    Appends one JSON line per event to a log file.
    Suitable for production: events survive process restart.
    """

    def __init__(self, path: str) -> None:
        self._path  = path
        self._lock  = threading.Lock()

    def write(self, event: InferenceTelemetryEvent) -> None:
        line = event.to_json() + "\n"
        with self._lock:
            try:
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(line)
            except OSError:
                pass  # never crash the caller due to telemetry failure

    def flush(self) -> None:
        pass  # file writes are immediate


# ── Telemetry Pipeline ────────────────────────────────────────────────────────

class TelemetryPipeline:
    """
    Collects InferenceTelemetryEvents from InferenceAdapter and fans
    them out to registered backends.

    Maintains per-session summaries for the builder UI dashboard and
    budget system.

    Thread-safe — emit() can be called from concurrent PIL passes.

    Usage
    -----
        telemetry = TelemetryPipeline()
        telemetry.add_backend(InMemoryBackend())
        telemetry.add_backend(FileBackend("/var/log/xace/inference.jsonl"))

        # In InferenceAdapter:
        telemetry.emit(InferenceTelemetryEvent(
            request_id=request.request_id,
            session_id=request.session_id,
            call_label=request.call_label,
            provider=descriptor.provider,
            model_id=descriptor.model_id,
            ...
        ))
    """

    def __init__(self) -> None:
        self._backends:  list[ITelemetryBackend]             = []
        self._summaries: dict[str, SessionTelemetrySummary]  = {}
        self._lock       = threading.Lock()

    # ── Backend management ────────────────────────────────────────────────────

    def add_backend(self, backend: ITelemetryBackend) -> None:
        with self._lock:
            self._backends.append(backend)

    def remove_backend(self, backend: ITelemetryBackend) -> None:
        with self._lock:
            self._backends = [b for b in self._backends if b is not backend]

    # ── Emit ──────────────────────────────────────────────────────────────────

    def emit(self, event: InferenceTelemetryEvent) -> None:
        """
        Emits one event to all backends and updates the session summary.
        Never raises — telemetry failures must not crash the caller.
        """
        with self._lock:
            # Update session summary
            if event.session_id not in self._summaries:
                self._summaries[event.session_id] = SessionTelemetrySummary(
                    session_id=event.session_id
                )
            self._summaries[event.session_id].absorb(event)

            # Fan out to backends
            for backend in self._backends:
                try:
                    backend.write(event)
                except Exception:
                    pass  # individual backend failure must not block others

    # ── Query ─────────────────────────────────────────────────────────────────

    def session_summary(self, session_id: str) -> SessionTelemetrySummary | None:
        with self._lock:
            return self._summaries.get(session_id)

    def all_session_ids(self) -> list[str]:
        with self._lock:
            return sorted(self._summaries.keys())

    def session_cost_cents(self, session_id: str) -> float:
        with self._lock:
            s = self._summaries.get(session_id)
            return s.total_cost_cents if s else 0.0

    def session_call_count(self, session_id: str) -> int:
        with self._lock:
            s = self._summaries.get(session_id)
            return s.total_calls if s else 0

    def flush_all(self) -> None:
        with self._lock:
            for backend in self._backends:
                try:
                    backend.flush()
                except Exception:
                    pass

    def close_session(self, session_id: str) -> SessionTelemetrySummary | None:
        """
        Removes the session summary from memory and returns it.
        Call on session end to release memory.
        """
        with self._lock:
            return self._summaries.pop(session_id, None)

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"TelemetryPipeline("
                f"backends={len(self._backends)}, "
                f"active_sessions={len(self._summaries)})"
            )