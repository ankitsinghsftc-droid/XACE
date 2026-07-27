# ============================================================================
# tests/test_hybrid_routing.py
# ============================================================================
 
"""
Tests for hybrid tier routing in ModelRouter v2:
TIER_L → DeepSeek, TIER_M → local first, TIER_XL → Anthropic.
Also tests pass_number override and provider_kind in telemetry.
"""
 
from datetime import datetime, timezone
import pytest
from unittest.mock import MagicMock
 
from ..src.model_router import (
    ModelRouter, RoutingContext, CostPressure, PASS_TIER_MAP,
)
from ..src.model_descriptor import ComplexityTier, BUILTIN_DESCRIPTORS
from ..src.provider_registry import ProviderRegistry, IProviderClient
from ..src.route_evidence import RouteEvidencePolicy
 
 
# ── Helpers ───────────────────────────────────────────────────────────────────
 
class _HealthyClient(IProviderClient):
    def __init__(self, name: str) -> None: self._n = name
    def complete(self, **_): return {"text": "ok", "input_tokens": 10, "output_tokens": 5,
                                     "cache_read_tokens": 0, "cache_write_tokens": 0}
    def health_check(self)  -> bool: return True
    def provider_name(self) -> str:  return self._n
 
 
def _registry() -> ProviderRegistry:
    reg = ProviderRegistry()
    for p in ["anthropic", "openai", "deepseek", "zai", "minimax", "google", "local"]:
        reg.register_client(p, _HealthyClient(p))
    return reg
 
 
def _local_manager_with(loaded: list[str]):
    mgr = MagicMock()
    mgr.has_any_available.return_value = bool(loaded)
    mgr.select_model.return_value      = loaded[0] if loaded else "llama3.1:70b"
    return mgr
 
 
def _router(local_loaded: list[str] | None = None) -> ModelRouter:
    local_mgr = _local_manager_with(local_loaded) if local_loaded is not None else None
    return ModelRouter(
        _registry(),
        local_manager=local_mgr,
        route_evidence_policy=_route_evidence_policy(local_loaded or []),
    )


def _route_evidence_policy(local_models: list[str]) -> RouteEvidencePolicy:
    rows = []
    for descriptor in BUILTIN_DESCRIPTORS.values():
        rows.append(_route_evidence_row(descriptor.provider, descriptor.logical_name, descriptor.model_id, descriptor.default_tier))
    for model_id in local_models:
        rows.append(_route_evidence_row("local", "local_dev", model_id, ComplexityTier.M))
    return RouteEvidencePolicy.from_records(rows, now_utc=datetime(2026, 7, 3, tzinfo=timezone.utc))


def _route_evidence_row(provider: str, logical_name: str, model_id: str, tier: str) -> dict:
    return {
        "provider": provider,
        "logical_name": logical_name,
        "model_id": model_id,
        "tier": tier,
        "benchmark_id": f"task56-{provider}-{logical_name}",
        "benchmark_hash": f"sha256:{provider}:{logical_name}:{model_id}",
        "benchmarked_at_utc": "2026-07-01T00:00:00Z",
        "expires_at_utc": "2027-07-03T00:00:00Z",
        "status": "passed",
        "metrics": {"route_accuracy": 1.0, "sample_count": 3},
    }
 
 
# ── TIER_XL remains Anthropic ─────────────────────────────────────────────────
 
class TestTierXLStillAnthropic:
 
    def test_tier_xl_routes_to_anthropic(self) -> None:
        decision = _router().route(ComplexityTier.XL)
        assert decision.descriptor.provider == "anthropic"
 
    def test_tier_xl_not_deterministic(self) -> None:
        decision = _router().route(ComplexityTier.XL)
        assert not decision.is_deterministic_shortcut
 
 
# ── TIER_L now prefers DeepSeek ───────────────────────────────────────────────
 
class TestTierLHybridRouting:
 
    def test_tier_l_prefers_deepseek_over_anthropic(self) -> None:
        decision = _router().route(ComplexityTier.L)
        assert decision.descriptor.provider == "deepseek", (
            f"Expected deepseek but got {decision.descriptor.provider}. "
            f"Reason: {decision.reason}"
        )
 
    def test_tier_l_fallback_to_anthropic_when_deepseek_failed(self) -> None:
        ctx      = RoutingContext(failed_providers=("deepseek", "zai"))
        decision = _router().route(ComplexityTier.L, ctx)
        assert decision.descriptor.provider not in ("deepseek", "zai")
        assert decision.fallback_applied
 
    def test_tier_l_pass1_routes_to_deepseek(self) -> None:
        ctx      = RoutingContext(pass_number=1)
        decision = _router().route(ComplexityTier.L, ctx)
        assert decision.descriptor.provider == "deepseek"
 
    def test_tier_l_pass2_routes_to_deepseek(self) -> None:
        ctx      = RoutingContext(pass_number=2)
        decision = _router().route(ComplexityTier.L, ctx)
        assert decision.descriptor.provider == "deepseek"
 
 
# ── TIER_M: local first ───────────────────────────────────────────────────────
 
class TestTierMLocalFirstRouting:
 
    def test_tier_m_uses_local_when_available(self) -> None:
        router   = _router(local_loaded=["llama3.1:70b"])
        decision = router.route(ComplexityTier.M)
        assert decision.local_model_selected
        assert decision.descriptor.provider == "local"
        assert "Zero cost" in decision.reason
 
    def test_tier_m_falls_to_cloud_when_local_unavailable(self) -> None:
        router   = _router(local_loaded=[])  # no local models
        decision = router.route(ComplexityTier.M)
        assert not decision.local_model_selected
        assert decision.descriptor.provider != "local"
        # Should pick cheapest cloud: DeepSeek Flash
        assert decision.descriptor.provider == "deepseek"
 
    def test_tier_m_skips_local_when_in_failed_providers(self) -> None:
        router   = _router(local_loaded=["llama3.1:70b"])
        ctx      = RoutingContext(failed_providers=("local",))
        decision = router.route(ComplexityTier.M, ctx)
        assert not decision.local_model_selected
 
    def test_tier_m_pass3_routes_through_local_when_available(self) -> None:
        router   = _router(local_loaded=["qwen2.5:72b"])
        ctx      = RoutingContext(pass_number=3)
        decision = router.route(ComplexityTier.M, ctx)
        assert decision.local_model_selected
 
    def test_tier_m_pass4_routes_through_local_when_available(self) -> None:
        router   = _router(local_loaded=["llama3.1:70b"])
        ctx      = RoutingContext(pass_number=4)
        decision = router.route(ComplexityTier.M, ctx)
        assert decision.local_model_selected
 
    def test_tier_m_pass5_routes_through_local_when_available(self) -> None:
        """Pass 5 is TIER_M per spec (overrides master plan's TIER_L)."""
        router   = _router(local_loaded=["llama3.1:70b"])
        ctx      = RoutingContext(pass_number=5)
        decision = router.route(ComplexityTier.M, ctx)
        assert decision.local_model_selected
 
 
# ── Pass-to-Tier Mapping ──────────────────────────────────────────────────────
 
class TestPassTierMapping:
 
    def test_pass_1_maps_to_tier_l(self) -> None:
        assert PASS_TIER_MAP[1] == ComplexityTier.L
 
    def test_pass_2_maps_to_tier_l(self) -> None:
        assert PASS_TIER_MAP[2] == ComplexityTier.L
 
    def test_pass_3_maps_to_tier_m(self) -> None:
        assert PASS_TIER_MAP[3] == ComplexityTier.M
 
    def test_pass_4_maps_to_tier_m(self) -> None:
        assert PASS_TIER_MAP[4] == ComplexityTier.M
 
    def test_pass_5_maps_to_tier_m(self) -> None:
        """Critical: pass 5 is TIER_M per user spec, overriding old TIER_L."""
        assert PASS_TIER_MAP[5] == ComplexityTier.M
 
    def test_pass_number_overrides_tier_argument(self) -> None:
        # Caller passes TIER_XL but pass_number=3 → effective tier = TIER_M
        router   = _router(local_loaded=["llama3.1:70b"])
        ctx      = RoutingContext(pass_number=3)
        decision = router.route(ComplexityTier.XL, ctx)
        # Should route to TIER_M (local), not XL (Anthropic)
        assert decision.tier             == ComplexityTier.M
        assert decision.local_model_selected
 
    def test_effective_tier_for_pass_helper(self) -> None:
        router = _router()
        assert router.effective_tier_for_pass(1) == ComplexityTier.L
        assert router.effective_tier_for_pass(5) == ComplexityTier.M
        assert router.effective_tier_for_pass(99) == ComplexityTier.L  # unknown → default L
 
 
# ── Telemetry provider_kind ───────────────────────────────────────────────────
 
class TestProviderKindTelemetry:
 
    def test_provider_kind_defaults_to_cloud(self) -> None:
        from ..src.telemetry_pipeline import InferenceTelemetryEvent
        from ..src.model_descriptor import ComplexityTier
        event = InferenceTelemetryEvent(
            request_id="r", session_id="s", call_label="test",
            provider="anthropic", model_id="claude-sonnet-4-6",
        )
        assert event.provider_kind == "cloud"
 
    def test_provider_kind_local(self) -> None:
        from ..src.telemetry_pipeline import InferenceTelemetryEvent
        event = InferenceTelemetryEvent(
            request_id="r", session_id="s", call_label="test",
            provider="local", model_id="llama3.1:70b",
            provider_kind="local",
        )
        assert event.provider_kind == "local"
 
    def test_session_summary_tracks_provider_kind(self) -> None:
        from ..src.telemetry_pipeline import TelemetryPipeline, InferenceTelemetryEvent, InMemoryBackend
        pipeline = TelemetryPipeline()
        pipeline.add_backend(InMemoryBackend())
 
        pipeline.emit(InferenceTelemetryEvent(
            request_id="r1", session_id="s1", call_label="pass3",
            provider="local", model_id="llama3.1:70b",
            provider_kind="local",
        ))
        pipeline.emit(InferenceTelemetryEvent(
            request_id="r2", session_id="s1", call_label="pass1",
            provider="deepseek", model_id="deepseek-v4-pro",
            provider_kind="cloud",
        ))
 
        summary = pipeline.session_summary("s1")
        assert summary.calls_by_provider_kind.get("local", 0)  == 1
        assert summary.calls_by_provider_kind.get("cloud", 0)  == 1
 
 
# ── Cost Pressure ─────────────────────────────────────────────────────────────
 
class TestHybridRoutingCostPressure:
 
    def test_high_cost_pressure_picks_cheapest_tier_m(self) -> None:
        router   = _router()   # no local manager
        ctx      = RoutingContext(cost_pressure=CostPressure.HIGH)
        decision = router.route(ComplexityTier.M, ctx)
        # Must pick cheapest: DeepSeek Flash or MiniMax
        assert decision.descriptor is not None
        all_m    = router._candidates_for_tier(ComplexityTier.M)
        cheapest = min(all_m, key=lambda d: d.input_price_per_1k)
        assert decision.descriptor.input_price_per_1k <= cheapest.input_price_per_1k + 0.00001
 
    def test_extreme_cost_pressure_tier_l_picks_cheapest(self) -> None:
        router   = _router()
        ctx      = RoutingContext(cost_pressure=CostPressure.EXTREME)
        decision = router.route(ComplexityTier.L, ctx)
        assert decision.descriptor is not None
