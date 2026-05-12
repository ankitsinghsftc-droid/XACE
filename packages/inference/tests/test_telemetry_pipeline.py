"""
tests/test_telemetry_pipeline.py
===================================
Tests for TelemetryPipeline, InferenceTelemetryEvent, and backends.
"""

from __future__ import annotations

import time
import pytest

from ..src.telemetry_pipeline import (
    TelemetryPipeline, InferenceTelemetryEvent,
    InMemoryBackend, SessionTelemetrySummary,
)
from ..src.model_descriptor import ComplexityTier


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _event(
    session_id:      str   = "sess_test",
    call_label:      str   = "pass1_planning",
    provider:        str   = "anthropic",
    model_id:        str   = "claude-sonnet-4-6",
    complexity_tier: str   = ComplexityTier.L,
    input_tokens:    int   = 1000,
    output_tokens:   int   = 400,
    cache_read:      int   = 0,
    cache_write:     int   = 0,
    cost_cents:      float = 5.0,
    latency_ms:      float = 800.0,
    outcome:         str   = "success",
    cached:          bool  = False,
) -> InferenceTelemetryEvent:
    return InferenceTelemetryEvent(
        request_id         = "req_001",
        session_id         = session_id,
        call_label         = call_label,
        provider           = provider,
        model_id           = model_id,
        complexity_tier    = complexity_tier,
        input_tokens       = input_tokens,
        output_tokens      = output_tokens,
        cache_read_tokens  = cache_read,
        cache_write_tokens = cache_write,
        cost_cents         = cost_cents,
        latency_ms         = latency_ms,
        outcome            = outcome,
        cached             = cached,
    )


def _pipeline_with_memory() -> tuple[TelemetryPipeline, InMemoryBackend]:
    pipeline = TelemetryPipeline()
    backend  = InMemoryBackend()
    pipeline.add_backend(backend)
    return pipeline, backend


# ── InferenceTelemetryEvent ───────────────────────────────────────────────────

class TestInferenceTelemetryEvent:

    def test_total_tokens(self) -> None:
        e = _event(input_tokens=1000, output_tokens=400)
        assert e.total_tokens == 1400

    def test_effective_input_tokens(self) -> None:
        # cache_read_tokens are billed (at discounted rate) — included in effective
        e = _event(input_tokens=200, cache_read=800)
        assert e.effective_input_tokens == 1000

    def test_to_dict_contains_all_fields(self) -> None:
        e = _event()
        d = e.to_dict()
        assert "request_id"      in d
        assert "session_id"      in d
        assert "provider"        in d
        assert "model_id"        in d
        assert "input_tokens"    in d
        assert "output_tokens"   in d
        assert "cost_cents"      in d
        assert "latency_ms"      in d
        assert "outcome"         in d
        assert "cached"          in d

    def test_to_json_is_valid_json(self) -> None:
        import json
        e    = _event()
        text = e.to_json()
        parsed = json.loads(text)
        assert parsed["session_id"] == "sess_test"

    def test_timestamp_is_set_automatically(self) -> None:
        before = time.time()
        e      = _event()
        after  = time.time()
        assert before <= e.timestamp <= after

    def test_repr_contains_call_label(self) -> None:
        e = _event(call_label="pass3_self_critique")
        assert "pass3_self_critique" in repr(e)


# ── InMemoryBackend ───────────────────────────────────────────────────────────

class TestInMemoryBackend:

    def test_write_stores_event(self) -> None:
        backend = InMemoryBackend()
        e       = _event()
        backend.write(e)
        assert len(backend.all_events()) == 1

    def test_events_for_session(self) -> None:
        backend = InMemoryBackend()
        backend.write(_event(session_id="s1"))
        backend.write(_event(session_id="s2"))
        backend.write(_event(session_id="s1"))
        s1_events = backend.events_for_session("s1")
        assert len(s1_events) == 2

    def test_events_by_outcome(self) -> None:
        backend = InMemoryBackend()
        backend.write(_event(outcome="success"))
        backend.write(_event(outcome="cache_hit"))
        backend.write(_event(outcome="success"))
        success = backend.events_by_outcome("success")
        assert len(success) == 2

    def test_events_by_label(self) -> None:
        backend = InMemoryBackend()
        backend.write(_event(call_label="pass1_planning"))
        backend.write(_event(call_label="pass2_dsl_draft"))
        backend.write(_event(call_label="pass1_planning"))
        pass1 = backend.events_by_label("pass1_planning")
        assert len(pass1) == 2

    def test_total_cost_for_session(self) -> None:
        backend = InMemoryBackend()
        backend.write(_event(session_id="s1", cost_cents=3.0))
        backend.write(_event(session_id="s1", cost_cents=7.0))
        backend.write(_event(session_id="s2", cost_cents=5.0))
        assert abs(backend.total_cost_cents("s1") - 10.0) < 0.01

    def test_max_events_evicts_oldest(self) -> None:
        backend = InMemoryBackend(max_events=3)
        for i in range(5):
            backend.write(_event(call_label=f"pass{i}"))
        assert len(backend.all_events()) == 3

    def test_clear_removes_all(self) -> None:
        backend = InMemoryBackend()
        for _ in range(5):
            backend.write(_event())
        backend.clear()
        assert len(backend.all_events()) == 0


# ── TelemetryPipeline ─────────────────────────────────────────────────────────

class TestTelemetryPipeline:

    def test_emit_stores_in_all_backends(self) -> None:
        pipeline  = TelemetryPipeline()
        backend1  = InMemoryBackend()
        backend2  = InMemoryBackend()
        pipeline.add_backend(backend1)
        pipeline.add_backend(backend2)
        pipeline.emit(_event())
        assert len(backend1.all_events()) == 1
        assert len(backend2.all_events()) == 1

    def test_emit_without_backends_does_not_raise(self) -> None:
        pipeline = TelemetryPipeline()
        pipeline.emit(_event())   # no backends registered — must not raise

    def test_failing_backend_does_not_crash_other_backends(self) -> None:
        class BrokenBackend:
            def write(self, _):   raise RuntimeError("broken")
            def flush(self):      raise RuntimeError("broken")

        pipeline, good_backend = _pipeline_with_memory()
        pipeline.add_backend(BrokenBackend())  # type: ignore
        pipeline.emit(_event())   # must not raise
        # Good backend still received the event
        assert len(good_backend.all_events()) == 1

    def test_session_summary_accumulates(self) -> None:
        pipeline, _ = _pipeline_with_memory()
        for _ in range(3):
            pipeline.emit(_event(session_id="s1", input_tokens=100,
                                 output_tokens=50, cost_cents=2.0))
        summary = pipeline.session_summary("s1")
        assert summary is not None
        assert summary.total_calls        == 3
        assert summary.total_input_tokens == 300
        assert summary.total_output_tokens == 150
        assert abs(summary.total_cost_cents - 6.0) < 0.01

    def test_session_summary_tracks_tiers(self) -> None:
        pipeline, _ = _pipeline_with_memory()
        pipeline.emit(_event(session_id="s1", complexity_tier=ComplexityTier.M))
        pipeline.emit(_event(session_id="s1", complexity_tier=ComplexityTier.L))
        pipeline.emit(_event(session_id="s1", complexity_tier=ComplexityTier.XL))
        summary = pipeline.session_summary("s1")
        assert summary.calls_by_tier.get(ComplexityTier.M,  0) == 1
        assert summary.calls_by_tier.get(ComplexityTier.L,  0) == 1
        assert summary.calls_by_tier.get(ComplexityTier.XL, 0) == 1

    def test_cache_hit_counted_in_summary(self) -> None:
        pipeline, _ = _pipeline_with_memory()
        pipeline.emit(_event(session_id="s1", cached=True,  outcome="cache_hit"))
        pipeline.emit(_event(session_id="s1", cached=False, outcome="success"))
        summary = pipeline.session_summary("s1")
        assert summary.cached_calls == 1
        assert summary.total_calls  == 2

    def test_deterministic_shortcut_counted(self) -> None:
        pipeline, _ = _pipeline_with_memory()
        pipeline.emit(_event(
            session_id  = "s1",
            provider    = "deterministic",
            model_id    = "phase12_gde",
            cached      = True,
            outcome     = "deterministic_shortcut",
            cost_cents  = 0.0,
            input_tokens = 0,
            output_tokens = 0,
        ))
        summary = pipeline.session_summary("s1")
        assert summary.deterministic_calls == 1
        assert summary.total_cost_cents    == 0.0

    def test_cache_hit_rate_calculation(self) -> None:
        pipeline, _ = _pipeline_with_memory()
        pipeline.emit(_event(session_id="s1", cached=True,  outcome="cache_hit"))
        pipeline.emit(_event(session_id="s1", cached=True,  outcome="cache_hit"))
        pipeline.emit(_event(session_id="s1", cached=False, outcome="success"))
        pipeline.emit(_event(session_id="s1", cached=False, outcome="success"))
        summary = pipeline.session_summary("s1")
        assert abs(summary.cache_hit_rate - 0.50) < 0.01

    def test_session_cost_cents_helper(self) -> None:
        pipeline, _ = _pipeline_with_memory()
        pipeline.emit(_event(session_id="s1", cost_cents=3.5))
        pipeline.emit(_event(session_id="s1", cost_cents=6.5))
        assert abs(pipeline.session_cost_cents("s1") - 10.0) < 0.01

    def test_session_call_count_helper(self) -> None:
        pipeline, _ = _pipeline_with_memory()
        for _ in range(7):
            pipeline.emit(_event(session_id="s1"))
        assert pipeline.session_call_count("s1") == 7

    def test_close_session_removes_summary(self) -> None:
        pipeline, _ = _pipeline_with_memory()
        pipeline.emit(_event(session_id="s1"))
        closed = pipeline.close_session("s1")
        assert closed is not None
        assert pipeline.session_summary("s1") is None

    def test_all_session_ids(self) -> None:
        pipeline, _ = _pipeline_with_memory()
        pipeline.emit(_event(session_id="s1"))
        pipeline.emit(_event(session_id="s2"))
        pipeline.emit(_event(session_id="s3"))
        ids = pipeline.all_session_ids()
        assert "s1" in ids
        assert "s2" in ids
        assert "s3" in ids

    def test_remove_backend(self) -> None:
        pipeline = TelemetryPipeline()
        backend  = InMemoryBackend()
        pipeline.add_backend(backend)
        pipeline.remove_backend(backend)
        pipeline.emit(_event())
        assert len(backend.all_events()) == 0

    def test_session_latency_tracked_in_summary(self) -> None:
        pipeline, _ = _pipeline_with_memory()
        pipeline.emit(_event(session_id="s1", cached=False, latency_ms=500.0))
        pipeline.emit(_event(session_id="s1", cached=False, latency_ms=700.0))
        summary = pipeline.session_summary("s1")
        assert summary.total_latency_ms == 1200.0
        assert abs(summary.avg_latency_ms - 600.0) < 0.01