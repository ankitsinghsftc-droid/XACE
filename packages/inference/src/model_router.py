"""
model_router.py — ModelRouter (Hybrid Routing v2)
===================================================
Selects the best available ModelDescriptor for a ComplexityTier + RoutingContext.

## Hybrid Routing Defaults

| Tier   | Primary          | Fallback                         |
|--------|------------------|----------------------------------|
| TIER_XL| Anthropic Opus   | OpenAI GPT-5.5-Pro → DeepSeek Pro|
| TIER_L | DeepSeek V4 Pro  | GLM-5.1 → Anthropic Sonnet       |
| TIER_M | Local (Ollama)   | DeepSeek Flash → Anthropic Haiku  |
| TIER_S | Deterministic    | (no model call)                  |

## Pass-to-Tier Override

When RoutingContext.pass_number is set, PASS_TIER_MAP overrides the tier argument:

    pass 1 → TIER_L   pass 2 → TIER_L   pass 3 → TIER_M
    pass 4 → TIER_M   pass 5 → TIER_M

## Local Model Integration

Inject a LocalModelManager instance to enable TIER_M local routing.
When local is unavailable, the router falls through to cheap cloud without any
code path change in the caller.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TYPE_CHECKING

from .model_descriptor import ModelDescriptor, ComplexityTier, BUILTIN_DESCRIPTORS
from .provider_registry import ProviderRegistry

if TYPE_CHECKING:
    from .local_model_manager import LocalModelManager


# ── Pass-to-Tier Mapping ──────────────────────────────────────────────────────

PASS_TIER_MAP: dict[int, str] = {
    1: ComplexityTier.L,
    2: ComplexityTier.L,
    3: ComplexityTier.M,
    4: ComplexityTier.M,
    5: ComplexityTier.M,
}


# ── Supporting Types ──────────────────────────────────────────────────────────

class CostPressure(str, Enum):
    NONE    = "NONE"
    NORMAL  = "NORMAL"
    HIGH    = "HIGH"
    EXTREME = "EXTREME"


@dataclass(frozen=True)
class RoutingContext:
    session_id:             str             = ""
    failed_providers:       tuple[str, ...] = ()
    budget_remaining_cents: float           = -1.0
    preferred_provider:     str             = ""
    cost_pressure:          CostPressure    = CostPressure.NORMAL
    call_label:             str             = ""
    pass_number:            int | None      = None


@dataclass(frozen=True)
class RoutingDecision:
    descriptor:                ModelDescriptor | None
    tier:                      str
    reason:                    str
    is_deterministic_shortcut: bool = False
    fallback_applied:          bool = False
    local_model_selected:      bool = False


class ModelRoutingError(Exception):
    """Raised when no suitable model is available for the tier."""


# ── Model Router ──────────────────────────────────────────────────────────────

class ModelRouter:
    """
    Hybrid model routing: local TIER_M, cheap cloud TIER_L, premium TIER_XL.

    Usage
    -----
        router = ModelRouter(registry, local_manager=LocalModelManager())
        decision = router.route(ComplexityTier.M, RoutingContext(pass_number=3))
    """

    _HYBRID_PREFS: dict[str, str] = {
        ComplexityTier.XL: "anthropic",
        ComplexityTier.L:  "deepseek",
        ComplexityTier.M:  "local",
    }

    def __init__(
        self,
        registry:      ProviderRegistry,
        config:        dict[str, Any]      | None = None,
        local_manager: "LocalModelManager" | None = None,
    ) -> None:
        self._registry      = registry
        self._config        = config or {}
        self._local_manager = local_manager
        self._prefs: dict[str, str] = {
            **self._HYBRID_PREFS,
            **self._config.get("provider_preference", {}),
        }

    # ── Public API ────────────────────────────────────────────────────────────

    def route(
        self,
        tier:    str,
        context: RoutingContext = RoutingContext(),
    ) -> RoutingDecision:
        effective = self._effective_tier(tier, context.pass_number)

        if effective == ComplexityTier.S:
            return RoutingDecision(
                descriptor=None, tier=effective,
                reason="TIER_S → deterministic Phase 12 GDE. Zero cost. (II2)",
                is_deterministic_shortcut=True,
            )

        # TIER_M: try local first
        if effective == ComplexityTier.M and self._local_manager:
            local_dec = self._try_local(effective, context)
            if local_dec is not None:
                return local_dec

        # Cloud routing
        candidates = self._candidates_for_tier(effective)
        if not candidates:
            raise ModelRoutingError(f"No descriptors for tier '{effective}'.")

        active   = [d for d in candidates if d.provider not in context.failed_providers]
        healthy  = self._healthy(active)
        pool     = healthy or active
        sorted_  = self._sort(pool, effective, context)
        ordered  = self._prefer(sorted_, effective, context)

        if not ordered:
            raise ModelRoutingError(
                f"All providers for '{effective}' are failed/unhealthy: "
                f"{context.failed_providers}."
            )

        selected = ordered[0]
        fallback = (
            self._prefs.get(effective)
            and selected.provider != self._prefs[effective]
        )
        return RoutingDecision(
            descriptor       = selected,
            tier             = effective,
            reason           = self._reason(selected, effective, context, bool(fallback)),
            fallback_applied = bool(fallback),
        )

    def route_cheapest(self, tier: str) -> ModelDescriptor | None:
        cands = self._candidates_for_tier(tier)
        if not cands:
            return None
        local = [d for d in cands if d.provider == "local"]
        return local[0] if local else min(cands, key=lambda d: d.input_price_per_1k)

    def route_best(self, tier: str) -> ModelDescriptor | None:
        cands = self._candidates_for_tier(tier)
        if not cands:
            return None
        pref = self._prefs.get(tier, "anthropic")
        pref_match = [d for d in cands if d.provider == pref]
        return pref_match[0] if pref_match else cands[0]

    def effective_tier_for_pass(self, pass_number: int) -> str:
        return PASS_TIER_MAP.get(pass_number, ComplexityTier.L)

    def available_tiers(self) -> list[str]:
        tiers: set[str] = set()
        for name in self._registry.logical_model_names():
            try:
                tiers.add(self._registry.get(name).default_tier)
            except Exception:
                pass
        return sorted(tiers)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _effective_tier(self, tier: str, pass_number: int | None) -> str:
        return PASS_TIER_MAP.get(pass_number, tier) if pass_number is not None else tier

    def _try_local(
        self, tier: str, context: RoutingContext
    ) -> RoutingDecision | None:
        if "local" in context.failed_providers:
            return None
        if not self._local_manager or not self._local_manager.has_any_available():
            return None

        # Find local descriptor
        local_desc: ModelDescriptor | None = None
        for name in self._registry.logical_model_names():
            try:
                d = self._registry.get(name)
                if d.provider == "local":
                    local_desc = d
                    break
            except Exception:
                pass

        if local_desc is None:
            return None

        model = self._local_manager.select_model()
        return RoutingDecision(
            descriptor           = local_desc,
            tier                 = tier,
            reason               = f"TIER_M local: '{model}' loaded. Zero cost.",
            local_model_selected = True,
        )

    def _candidates_for_tier(self, tier: str) -> list[ModelDescriptor]:
        result: list[ModelDescriptor] = []
        for name in self._registry.logical_model_names():
            try:
                d = self._registry.get(name)
                if d.default_tier == tier:
                    result.append(d)
            except Exception:
                pass
        if not result:
            result = [d for d in BUILTIN_DESCRIPTORS.values() if d.default_tier == tier]
        return result

    def _healthy(self, candidates: list[ModelDescriptor]) -> list[ModelDescriptor]:
        out = []
        for d in candidates:
            try:
                if self._registry.get_client(d.provider).health_check():
                    out.append(d)
            except Exception:
                pass
        return out

    def _sort(
        self, pool: list[ModelDescriptor], tier: str, context: RoutingContext
    ) -> list[ModelDescriptor]:
        if context.cost_pressure in (CostPressure.HIGH, CostPressure.EXTREME):
            return sorted(pool, key=lambda d: d.input_price_per_1k)
        if tier == ComplexityTier.XL:
            def xl_key(d: ModelDescriptor) -> tuple[int, float]:
                return (0 if d.supports_cache_control else 1, d.input_price_per_1k)
            return sorted(pool, key=xl_key)
        # TIER_L, TIER_M: cheapest first (local=free wins automatically)
        return sorted(pool, key=lambda d: d.input_price_per_1k)

    def _prefer(
        self,
        pool:    list[ModelDescriptor],
        tier:    str,
        context: RoutingContext,
    ) -> list[ModelDescriptor]:
        pref = context.preferred_provider or self._prefs.get(tier, "")
        if not pref:
            return pool
        front = [d for d in pool if d.provider == pref]
        rest  = [d for d in pool if d.provider != pref]
        return front + rest

    @staticmethod
    def _reason(
        d: ModelDescriptor, tier: str, ctx: RoutingContext, fallback: bool
    ) -> str:
        parts = [f"Selected {d.logical_name!r} ({d.model_id}) for {tier}."]
        if fallback:
            parts.append("Fallback: preferred provider skipped.")
        if ctx.failed_providers:
            parts.append(f"Excluded: {ctx.failed_providers}.")
        if ctx.pass_number is not None:
            parts.append(f"Pass {ctx.pass_number} → {tier}.")
        if ctx.cost_pressure != CostPressure.NORMAL:
            parts.append(f"Cost pressure: {ctx.cost_pressure.value}.")
        return " ".join(parts)