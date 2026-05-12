"""
model_router.py — ModelRouter
================================
Given a ComplexityTier and a RoutingContext, selects the best available
ModelDescriptor for the current call.

## Responsibility
ModelRouter sits between ComplexityClassifier and InferenceAdapter.
ComplexityClassifier says "this is TIER_L." ModelRouter says "for TIER_L,
given that Sonnet is healthy and DeepSeek V4 Pro is cheaper today, use X."

## Routing Logic (evaluated in order)
    1. TIER_S → return None (no model call)
    2. Filter available descriptors for the tier from provider_registry
    3. Remove providers that have failed in this call attempt
    4. Remove providers that are unhealthy (health check)
    5. Apply budget pressure: if cost_pressure=HIGH, prefer cheapest in tier
    6. Apply provider preference from config (e.g. "always_anthropic_for_xl")
    7. Return the best remaining descriptor

## RoutingContext
Passed by InferenceAdapter per call:
    session_id         — for telemetry
    failed_providers   — providers that failed earlier in this call attempt
                         (populated by InferenceAdapter after each retry)
    budget_remaining_cents — remaining session budget (may influence cheapest routing)
    preferred_provider — explicit preference from BYOK or config override

## Provider Preference Config
provider_preference in registry config controls tier routing:
    {
      "TIER_XL": "anthropic",   # always use Anthropic for XL unless failed
      "TIER_L":  "anthropic",   # default Anthropic for L
      "TIER_M":  "deepseek",    # use DeepSeek for cheap validation
    }

## Cost Pressure Levels
    NONE    — ignore cost, use best capability
    NORMAL  — balance cost and capability (default)
    HIGH    — prefer cheapest option within tier
    EXTREME — prefer cheapest across ANY tier (rare; budget emergency)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .model_descriptor import ModelDescriptor, ComplexityTier, BUILTIN_DESCRIPTORS
from .provider_registry import ProviderRegistry


# ── Cost Pressure ─────────────────────────────────────────────────────────────

class CostPressure(str, Enum):
    NONE    = "NONE"
    NORMAL  = "NORMAL"
    HIGH    = "HIGH"
    EXTREME = "EXTREME"


# ── Routing Context ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RoutingContext:
    """
    Per-call context that influences model selection.

    Attributes
    ----------
    session_id : str
        Current builder session.
    failed_providers : tuple[str, ...]
        Providers that have already failed for this call attempt.
        ModelRouter will not select any provider in this set.
    budget_remaining_cents : float
        Remaining session budget in USD cents.
        -1.0 = unlimited (default).
    preferred_provider : str
        Explicit provider preference (from BYOK or config override).
        Empty string = no preference.
    cost_pressure : CostPressure
        How aggressively to optimise for cost.
    call_label : str
        PIL pass label for telemetry.
    """

    session_id:              str             = ""
    failed_providers:        tuple[str, ...] = ()
    budget_remaining_cents:  float           = -1.0
    preferred_provider:      str             = ""
    cost_pressure:           CostPressure    = CostPressure.NORMAL
    call_label:              str             = ""


# ── Routing Decision ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RoutingDecision:
    """
    Result of ModelRouter.route().

    Attributes
    ----------
    descriptor : ModelDescriptor | None
        The selected model, or None for TIER_S (deterministic shortcut).
    tier : str
        The tier this decision was made for.
    reason : str
        Why this descriptor was selected (for telemetry and debugging).
    is_deterministic_shortcut : bool
        True when tier is TIER_S — caller should route to Phase 12 GDE.
    fallback_applied : bool
        True when the preferred provider was skipped and a fallback used.
    """

    descriptor:               ModelDescriptor | None
    tier:                     str
    reason:                   str
    is_deterministic_shortcut: bool = False
    fallback_applied:          bool = False

    def __repr__(self) -> str:
        if self.is_deterministic_shortcut:
            return "RoutingDecision(TIER_S → deterministic)"
        if self.descriptor:
            return (
                f"RoutingDecision("
                f"{self.descriptor.logical_name!r} → {self.descriptor.model_id!r}, "
                f"tier={self.tier})"
            )
        return "RoutingDecision(no model available)"


# ── Routing Error ─────────────────────────────────────────────────────────────

class ModelRoutingError(Exception):
    """Raised when no suitable model can be found for the request."""


# ── Model Router ──────────────────────────────────────────────────────────────

class ModelRouter:
    """
    Selects the best ModelDescriptor for a tier + routing context.

    Stateless routing logic — the registry holds mutable provider state.
    One instance shared across all InferenceAdapter calls.

    Usage
    -----
        router = ModelRouter(registry, config={
            "provider_preference": {
                "TIER_XL": "anthropic",
                "TIER_L":  "anthropic",
                "TIER_M":  "deepseek",
            }
        })

        decision = router.route(
            tier=ComplexityTier.L,
            context=RoutingContext(session_id="s1", failed_providers=("anthropic",)),
        )
        if decision.is_deterministic_shortcut:
            return gde_orchestrator.handle(intent)  # no LLM
        descriptor = decision.descriptor
    """

    def __init__(
        self,
        registry: ProviderRegistry,
        config:   dict[str, Any] | None = None,
    ) -> None:
        self._registry  = registry
        self._config    = config or {}
        self._prefs:    dict[str, str] = self._config.get("provider_preference", {})

    # ── Public API ────────────────────────────────────────────────────────────

    def route(
        self,
        tier:    str,
        context: RoutingContext = RoutingContext(),
    ) -> RoutingDecision:
        """
        Selects the best model for a ComplexityTier + RoutingContext.

        Raises
        ------
        ModelRoutingError
            If no available model can serve the tier after all filters.
        """
        # ── TIER_S: always deterministic, no model call ───────────────────────
        if tier == ComplexityTier.S:
            return RoutingDecision(
                descriptor=None,
                tier=tier,
                reason="TIER_S → Phase 12 deterministic GDE (Inference Invariant II2).",
                is_deterministic_shortcut=True,
            )

        # ── Gather candidates for this tier ───────────────────────────────────
        candidates = self._candidates_for_tier(tier)
        if not candidates:
            raise ModelRoutingError(
                f"No descriptors registered for tier '{tier}'. "
                f"Registered logical names: {self._registry.logical_model_names()}"
            )

        # ── Filter: remove failed providers ───────────────────────────────────
        active = [
            d for d in candidates
            if d.provider not in context.failed_providers
        ]
        if not active:
            raise ModelRoutingError(
                f"All providers for tier '{tier}' have failed in this call attempt: "
                f"{context.failed_providers}. No fallback available."
            )

        # ── Filter: remove unhealthy providers ────────────────────────────────
        healthy = [
            d for d in active
            if self._is_healthy(d.provider)
        ]
        if not healthy:
            # Fall back to active (unhealthy providers might recover)
            healthy = active

        # ── Apply cost pressure ───────────────────────────────────────────────
        sorted_candidates = self._sort_by_policy(healthy, context)

        # ── Apply provider preference ─────────────────────────────────────────
        preferred = self._apply_preference(sorted_candidates, tier, context)

        selected        = preferred[0]
        fallback_applied = (
            selected.provider != self._prefs.get(tier)
            and self._prefs.get(tier) is not None
            and len(preferred) > 0
        )

        reason = self._build_reason(selected, tier, context, fallback_applied)
        return RoutingDecision(
            descriptor       = selected,
            tier             = tier,
            reason           = reason,
            fallback_applied = fallback_applied,
        )

    def route_cheapest(self, tier: str) -> ModelDescriptor | None:
        """
        Returns the cheapest descriptor for a tier, ignoring routing context.
        Used by cost_estimator for conservative cost calculations.
        """
        candidates = self._candidates_for_tier(tier)
        if not candidates:
            return None
        return min(candidates, key=lambda d: d.input_price_per_1k)

    def route_best(self, tier: str) -> ModelDescriptor | None:
        """
        Returns the highest-capability descriptor for a tier.
        Used when cost is not a concern.
        """
        candidates = self._candidates_for_tier(tier)
        if not candidates:
            return None
        # Prefer Anthropic for XL (best code gen + cache control)
        anthropic = [d for d in candidates if d.provider == "anthropic"]
        return anthropic[0] if anthropic else candidates[0]

    def available_tiers(self) -> list[str]:
        """Returns all tiers that have at least one registered descriptor."""
        seen: set[str] = set()
        for desc in self._registry.logical_model_names():
            try:
                d = self._registry.get(desc)
                seen.add(d.default_tier)
            except Exception:
                pass
        return sorted(seen)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _candidates_for_tier(self, tier: str) -> list[ModelDescriptor]:
        """Returns all registered descriptors whose default_tier matches."""
        result: list[ModelDescriptor] = []
        for logical_name in self._registry.logical_model_names():
            try:
                desc = self._registry.get(logical_name)
                if desc.default_tier == tier:
                    result.append(desc)
            except Exception:
                pass
        # Fallback to BUILTIN_DESCRIPTORS if registry is sparse
        if not result:
            result = [d for d in BUILTIN_DESCRIPTORS.values() if d.default_tier == tier]
        return result

    def _is_healthy(self, provider: str) -> bool:
        """Returns True if the provider client passes health_check."""
        try:
            client = self._registry.get_client(provider)
            return client.health_check()
        except Exception:
            return False

    def _sort_by_policy(
        self,
        candidates: list[ModelDescriptor],
        context:    RoutingContext,
    ) -> list[ModelDescriptor]:
        """
        Sorts candidates by cost pressure:
        NONE/NORMAL → prefer best capability (Anthropic first, then by capability score)
        HIGH        → prefer cheapest (sort by input_price_per_1k ASC)
        EXTREME     → cheapest in ANY tier (sorted by input_price_per_1k ASC)
        """
        if context.cost_pressure in (CostPressure.HIGH, CostPressure.EXTREME):
            return sorted(candidates, key=lambda d: d.input_price_per_1k)

        # NONE/NORMAL: capability-first — Anthropic with cache_control first
        def capability_score(d: ModelDescriptor) -> tuple[int, float]:
            cache_bonus   = 0 if d.supports_cache_control else 1
            provider_rank = {"anthropic": 0, "openai": 1, "deepseek": 2,
                             "zai": 3, "minimax": 4, "local": 99}.get(d.provider, 50)
            return (cache_bonus + provider_rank, d.input_price_per_1k)

        return sorted(candidates, key=capability_score)

    def _apply_preference(
        self,
        sorted_candidates: list[ModelDescriptor],
        tier:              str,
        context:           RoutingContext,
    ) -> list[ModelDescriptor]:
        """
        Moves preferred provider to front when available and healthy.
        Preference order: explicit context.preferred_provider > config tier preference.
        """
        preferred_provider = (
            context.preferred_provider
            or self._prefs.get(tier)
            or ""
        )
        if not preferred_provider:
            return sorted_candidates

        # Split: preferred first, then rest
        preferred = [d for d in sorted_candidates if d.provider == preferred_provider]
        rest      = [d for d in sorted_candidates if d.provider != preferred_provider]
        return preferred + rest

    @staticmethod
    def _build_reason(
        selected:         ModelDescriptor,
        tier:             str,
        context:          RoutingContext,
        fallback_applied: bool,
    ) -> str:
        parts = [
            f"Selected {selected.logical_name!r} ({selected.model_id}) "
            f"for {tier}."
        ]
        if fallback_applied:
            parts.append(
                f"Fallback applied: preferred provider skipped "
                f"(failed or unhealthy)."
            )
        if context.failed_providers:
            parts.append(f"Excluded: {context.failed_providers}.")
        if context.cost_pressure != CostPressure.NORMAL:
            parts.append(f"Cost pressure: {context.cost_pressure.value}.")
        return " ".join(parts)