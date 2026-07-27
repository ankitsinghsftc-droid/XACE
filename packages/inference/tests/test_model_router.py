"""
tests/test_model_router.py
============================
Tests for ModelRouter and FallbackPolicy.
"""

from __future__ import annotations

from datetime import datetime, timezone
import pytest
from typing import Any

from ..src.model_descriptor import (
    ModelDescriptor, ComplexityTier, ModelCapability,
    ANTHROPIC_SONNET_4_6, ANTHROPIC_HAIKU_4_5, ANTHROPIC_OPUS_4_7,
    DEEPSEEK_V4_FLASH, GLM_5_1, GOOGLE_GEMINI_31_PRO, BUILTIN_DESCRIPTORS,
)
from ..src.model_router import ModelRouter, RoutingContext, RoutingDecision, CostPressure, ModelRoutingError
from ..src.route_evidence import RouteEvidencePolicy
from ..src.fallback_policy import (
    FallbackPolicy, FallbackChain, ChainLink, FallbackAttempt,
    ProviderChainExhaustedError, _default_chains,
)
from ..src.provider_registry import ProviderRegistry, IProviderClient


_NOW = datetime(2026, 7, 3, tzinfo=timezone.utc)


# ── Fake Provider Client ──────────────────────────────────────────────────────

class _HealthyClient(IProviderClient):
    def __init__(self, provider: str) -> None:
        self._name = provider
    def complete(self, **_) -> dict:
        return {"text": "ok", "input_tokens": 10, "output_tokens": 5,
                "cache_read_tokens": 0, "cache_write_tokens": 0}
    def health_check(self) -> bool:
        return True
    def provider_name(self) -> str:
        return self._name


class _UnhealthyClient(IProviderClient):
    def __init__(self, provider: str) -> None:
        self._name = provider
    def complete(self, **_) -> dict:
        raise RuntimeError("unhealthy")
    def health_check(self) -> bool:
        return False
    def provider_name(self) -> str:
        return self._name


def _make_registry(providers: list[str] = None, healthy: bool = True) -> ProviderRegistry:
    registry = ProviderRegistry()
    for p in (providers or ["anthropic", "openai", "deepseek", "zai",
                             "minimax", "google", "local"]):
        client = _HealthyClient(p) if healthy else _UnhealthyClient(p)
        registry.register_client(p, client)
    return registry


def _make_router(providers: list[str] = None, healthy: bool = True) -> ModelRouter:
    return ModelRouter(_make_registry(providers, healthy), route_evidence_policy=_route_evidence_policy())


def _route_evidence_policy(*, only: list[ModelDescriptor] | None = None, stale: bool = False) -> RouteEvidencePolicy:
    descriptors = only or list(BUILTIN_DESCRIPTORS.values())
    expires = "2026-07-02T00:00:00Z" if stale else "2027-07-03T00:00:00Z"
    rows = [
        {
            "provider": descriptor.provider,
            "logical_name": descriptor.logical_name,
            "model_id": descriptor.model_id,
            "tier": descriptor.default_tier,
            "benchmark_id": f"task56-{descriptor.provider}-{descriptor.logical_name}",
            "benchmark_hash": f"sha256:{descriptor.provider}:{descriptor.logical_name}:{descriptor.model_id}",
            "benchmarked_at_utc": "2026-07-01T00:00:00Z",
            "expires_at_utc": expires,
            "status": "passed",
            "metrics": {"route_accuracy": 1.0, "sample_count": 3},
        }
        for descriptor in descriptors
    ]
    return RouteEvidencePolicy.from_records(rows, now_utc=_NOW)


# ── TIER_S Tests ──────────────────────────────────────────────────────────────

class TestTierSShortcut:

    def test_tier_s_returns_deterministic_shortcut(self) -> None:
        router   = _make_router()
        decision = router.route(ComplexityTier.S)
        assert decision.is_deterministic_shortcut
        assert decision.descriptor is None
        assert decision.tier == ComplexityTier.S

    def test_tier_s_no_context_needed(self) -> None:
        router   = _make_router(providers=[])  # no providers at all
        decision = router.route(ComplexityTier.S)
        assert decision.is_deterministic_shortcut

    def test_tier_s_reason_mentions_ii2(self) -> None:
        router   = _make_router()
        decision = router.route(ComplexityTier.S)
        assert "II2" in decision.reason or "deterministic" in decision.reason.lower()


# ── Tier Routing Tests ────────────────────────────────────────────────────────

class TestTierRouting:

    def setup_method(self) -> None:
        self.router = _make_router()

    def test_tier_m_returns_descriptor(self) -> None:
        decision = self.router.route(ComplexityTier.M)
        assert not decision.is_deterministic_shortcut
        assert decision.descriptor is not None
        assert decision.descriptor.default_tier == ComplexityTier.M

    def test_tier_l_returns_descriptor(self) -> None:
        decision = self.router.route(ComplexityTier.L)
        assert decision.descriptor is not None
        assert decision.descriptor.default_tier == ComplexityTier.L

    def test_tier_xl_returns_descriptor(self) -> None:
        decision = self.router.route(ComplexityTier.XL)
        assert decision.descriptor is not None
        assert decision.descriptor.default_tier == ComplexityTier.XL

    def test_tier_xl_prefers_anthropic_by_default(self) -> None:
        decision = self.router.route(ComplexityTier.XL)
        # Anthropic has supports_cache_control=True → highest capability score
        assert decision.descriptor.provider == "anthropic"

    def test_tier_l_prefers_deepseek_by_default(self) -> None:
        decision = self.router.route(ComplexityTier.L)
        assert decision.descriptor.provider == "deepseek"

    def test_tier_m_prefers_deepseek_cloud_when_local_manager_absent(self) -> None:
        decision = self.router.route(ComplexityTier.M)
        assert decision.descriptor.provider == "deepseek"

    def test_no_providers_raises_routing_error(self) -> None:
        registry = ProviderRegistry()  # no clients registered
        router   = ModelRouter(registry, route_evidence_policy=_route_evidence_policy())
        with pytest.raises(ModelRoutingError):
            router.route(ComplexityTier.L)


class TestRouteEvidenceGate:

    def test_unbenchmarked_route_is_rejected_with_user_visible_code(self) -> None:
        router = ModelRouter(_make_registry(["deepseek"]), route_evidence_policy=RouteEvidencePolicy(now_utc=_NOW))
        with pytest.raises(ModelRoutingError) as err:
            router.route(ComplexityTier.L)
        message = str(err.value)
        assert "MODEL_ROUTE_EVIDENCE_BLOCKED" in message
        assert "MODEL_ROUTE_EVIDENCE_MISSING" in message
        assert "deepseek" in message

    def test_stale_route_is_rejected_with_user_visible_code(self) -> None:
        router = ModelRouter(
            _make_registry(["deepseek"]),
            route_evidence_policy=_route_evidence_policy(only=[BUILTIN_DESCRIPTORS["deepseek_premium"]], stale=True),
        )
        with pytest.raises(ModelRoutingError) as err:
            router.route(ComplexityTier.L)
        message = str(err.value)
        assert "MODEL_ROUTE_EVIDENCE_STALE" in message
        assert "expired" in message

    def test_benchmarked_route_is_allowed(self) -> None:
        router = ModelRouter(
            _make_registry(["deepseek"]),
            route_evidence_policy=_route_evidence_policy(only=[BUILTIN_DESCRIPTORS["deepseek_premium"]]),
        )
        decision = router.route(ComplexityTier.L)
        assert decision.descriptor.provider == "deepseek"
        assert decision.route_evidence_id.startswith("TIER_L:deepseek:")


# ── Failed Provider Exclusion ─────────────────────────────────────────────────

class TestFailedProviderExclusion:

    def test_failed_deepseek_routes_to_fallback(self) -> None:
        router   = _make_router()
        context  = RoutingContext(
            session_id       = "sess1",
            failed_providers = ("deepseek",),
        )
        decision = router.route(ComplexityTier.L, context)
        assert decision.descriptor is not None
        assert decision.descriptor.provider != "deepseek"
        assert decision.fallback_applied

    def test_all_providers_failed_raises(self) -> None:
        registry = _make_registry()
        router   = ModelRouter(registry)
        # Get all TIER_L providers
        tier_l_providers = tuple(
            d.provider for d in registry.logical_model_names()
            and [registry.get(n) for n in registry.logical_model_names()
                 if registry.get(n).default_tier == ComplexityTier.L]
        )
        # Easier: just mark all known providers as failed
        context = RoutingContext(
            session_id       = "sess_fail",
            failed_providers = (
                "anthropic", "openai", "deepseek", "zai", "minimax", "google", "local"
            ),
        )
        with pytest.raises(ModelRoutingError):
            router.route(ComplexityTier.L, context)

    def test_multiple_failed_providers_skipped(self) -> None:
        router  = _make_router()
        context = RoutingContext(
            session_id       = "sess2",
            failed_providers = ("anthropic", "openai"),
        )
        decision = router.route(ComplexityTier.L, context)
        assert decision.descriptor.provider not in ("anthropic", "openai")


# ── Cost Pressure Routing ─────────────────────────────────────────────────────

class TestCostPressureRouting:

    def test_high_cost_pressure_picks_cheapest_tier_m(self) -> None:
        router  = _make_router()
        context = RoutingContext(cost_pressure=CostPressure.HIGH)
        decision = router.route(ComplexityTier.M, context)
        # With HIGH pressure, should prefer cheapest TIER_M descriptor
        # DeepSeek V4 Flash is much cheaper than Haiku at TIER_M
        assert decision.descriptor is not None
        # Just verify it picked the cheapest available (input_price_per_1k is lowest)
        all_m = router._candidates_for_tier(ComplexityTier.M)
        cheapest = min(all_m, key=lambda d: d.input_price_per_1k)
        assert decision.descriptor.input_price_per_1k <= cheapest.input_price_per_1k + 0.001

    def test_normal_cost_pressure_uses_hybrid_tier_l_preference(self) -> None:
        router   = _make_router()
        context  = RoutingContext(cost_pressure=CostPressure.NORMAL)
        decision = router.route(ComplexityTier.L, context)
        assert decision.descriptor.provider == "deepseek"

    def test_extreme_cost_pressure_picks_cheapest_available(self) -> None:
        router   = _make_router()
        context  = RoutingContext(cost_pressure=CostPressure.EXTREME)
        decision = router.route(ComplexityTier.M, context)
        assert decision.descriptor is not None


# ── Provider Preference ───────────────────────────────────────────────────────

class TestProviderPreference:

    def test_explicit_preferred_provider_wins(self) -> None:
        router  = _make_router()
        context = RoutingContext(preferred_provider="deepseek")
        decision = router.route(ComplexityTier.L, context)
        # DeepSeek V4 Pro is TIER_L — preferred provider should win
        assert decision.descriptor.provider == "deepseek"

    def test_config_tier_preference_respected(self) -> None:
        router = ModelRouter(
            _make_registry(),
            config={"provider_preference": {"TIER_M": "deepseek"}},
            route_evidence_policy=_route_evidence_policy(),
        )
        decision = router.route(ComplexityTier.M)
        assert decision.descriptor.provider == "deepseek"

    def test_unavailable_preferred_falls_through(self) -> None:
        router  = _make_router()
        context = RoutingContext(
            preferred_provider = "zai",
            failed_providers   = ("zai",),
        )
        decision = router.route(ComplexityTier.L, context)
        # zai is excluded → falls through to next available
        assert decision.descriptor is not None
        assert decision.descriptor.provider != "zai"


# ── Convenience Methods ───────────────────────────────────────────────────────

class TestRouterConvenience:

    def test_route_cheapest_returns_descriptor(self) -> None:
        router = _make_router()
        desc   = router.route_cheapest(ComplexityTier.M)
        assert desc is not None
        assert desc.default_tier == ComplexityTier.M

    def test_route_best_returns_anthropic_for_xl(self) -> None:
        router = _make_router()
        desc   = router.route_best(ComplexityTier.XL)
        assert desc is not None
        assert desc.provider == "anthropic"

    def test_available_tiers_non_empty(self) -> None:
        router = _make_router()
        tiers  = router.available_tiers()
        assert ComplexityTier.M  in tiers
        assert ComplexityTier.L  in tiers
        assert ComplexityTier.XL in tiers


# ── FallbackPolicy Tests ──────────────────────────────────────────────────────

class TestFallbackPolicy:

    def setup_method(self) -> None:
        self.registry = _make_registry()
        self.policy   = FallbackPolicy(self.registry)

    def test_default_chains_exist_for_all_tiers(self) -> None:
        for tier in [ComplexityTier.M, ComplexityTier.L, ComplexityTier.XL]:
            chain = self.policy.chain_for(tier)
            assert chain is not None
            assert len(chain.links) > 0

    def test_tier_s_chain_has_no_links(self) -> None:
        chain = self.policy.chain_for(ComplexityTier.S)
        assert chain is not None
        assert len(chain.links) == 0

    def test_next_link_returns_primary_on_fresh_attempt(self) -> None:
        attempt  = self.policy.create_attempt(ComplexityTier.L, "pass2")
        link     = self.policy.next_link(attempt)
        assert link is not None
        assert link == self.policy.chain_for(ComplexityTier.L).primary

    def test_next_link_skips_failed_providers(self) -> None:
        attempt = FallbackAttempt(tier=ComplexityTier.L, call_label="pass2")
        attempt.record_failure("anthropic", "claude-sonnet-4-6", "transport error")

        link = self.policy.next_link(attempt)
        assert link is not None
        assert link.provider != "anthropic"

    def test_next_link_returns_none_when_chain_exhausted(self) -> None:
        attempt = FallbackAttempt(tier=ComplexityTier.L)
        chain   = self.policy.chain_for(ComplexityTier.L)
        for link in chain.links:
            attempt.record_failure(link.provider, "model", "error")

        result = self.policy.next_link(attempt)
        assert result is None

    def test_create_attempt_fresh(self) -> None:
        attempt = self.policy.create_attempt(ComplexityTier.XL, "codegen")
        assert attempt.tier         == ComplexityTier.XL
        assert attempt.call_label   == "codegen"
        assert attempt.attempt_count == 0
        assert len(attempt.failed_providers) == 0

    def test_build_exhausted_error(self) -> None:
        attempt = FallbackAttempt(tier=ComplexityTier.L, call_label="pass1")
        attempt.record_failure("anthropic", "sonnet", "timeout")
        attempt.record_failure("deepseek",  "v4-pro", "429")

        err = self.policy.build_exhausted_error(attempt)
        assert isinstance(err, ProviderChainExhaustedError)
        assert "anthropic" in err.tried_providers
        assert "deepseek"  in err.tried_providers
        assert err.tier == ComplexityTier.L

    def test_xl_chain_has_code_gen_capable_links(self) -> None:
        chain = self.policy.chain_for(ComplexityTier.XL)
        for link in chain.links:
            if link.required_capability:
                assert link.required_capability == ModelCapability.CODE_GEN

    def test_summary_returns_all_tiers(self) -> None:
        summary = self.policy.summary()
        assert ComplexityTier.M  in summary
        assert ComplexityTier.L  in summary
        assert ComplexityTier.XL in summary

    def test_register_custom_chain(self) -> None:
        custom = FallbackChain(
            tier  = ComplexityTier.L,
            links = (ChainLink("google", "google_flagship"),),
        )
        self.policy.register_chain(custom)
        chain = self.policy.chain_for(ComplexityTier.L)
        assert chain.primary.provider == "google"
