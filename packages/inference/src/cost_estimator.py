"""
cost_estimator.py — CostEstimator
=====================================
Pre-flight cost estimation for inference calls.

CostEstimator runs before any model dispatch to answer:
"How much will this call cost, approximately?"

This is used for:
    - Soft budget warnings in InferenceAdapter (warn before breaching)
    - Model routing tie-breaking (when cost_pressure=HIGH in RoutingContext)
    - Builder UI cost indicator (show estimated cost per mutation)
    - Per-session cost accumulation preview

## What This Is NOT
CostEstimator is NOT the billing system. Actual billing uses token
counts from the provider response (in InferenceAdapter.call()).
Estimates here are directionally correct (±25%) but not exact.

## Estimation Chain
    text (str) or token_count (int)
        → token_estimator.py (if text given)
        → ModelDescriptor pricing fields
        → CostEstimate

## Cache Benefit Calculation
When a call has a cacheable prefix, CostEstimator calculates both
the uncached and cached cost and the projected saving.
Over a 10-call session with identical prefix, the cache saving
is a first-class output — surfaced in the builder UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .model_descriptor import ModelDescriptor, ComplexityTier
from .token_estimator import TokenEstimator, ContentType


# ── Cost Estimate ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CostEstimate:
    """
    Pre-flight cost estimate for one inference call.

    All values are USD cents. Estimates are approximate (±25%).
    Actual costs come from InferenceResponse.cost_cents.

    Attributes
    ----------
    input_cost_cents : float
        Cost of non-cached input tokens.
    output_cost_cents : float
        Cost of output tokens.
    cache_write_cost_cents : float
        Cost of writing to prompt cache (first call with this prefix).
    cache_read_cost_cents : float
        Cost of reading from prompt cache (subsequent calls).
    total_uncached_cents : float
        Full cost if cache_control is NOT used (input + output).
    total_cached_cents : float
        Full cost if cache IS used: cache_write + cache_read + output.
    cache_saving_cents : float
        total_uncached - total_cached (0.0 if provider doesn't cache).
    input_tokens : int
        Estimated non-cached input tokens.
    output_tokens : int
        Estimated output tokens.
    cache_write_tokens : int
        Tokens in the cacheable prefix (written to cache once).
    model_id : str
        The model this estimate is for.
    provider : str
        The provider this estimate is for.
    """

    input_cost_cents:     float
    output_cost_cents:    float
    cache_write_cost_cents: float
    cache_read_cost_cents:  float
    total_uncached_cents: float
    total_cached_cents:   float
    cache_saving_cents:   float
    input_tokens:         int
    output_tokens:        int
    cache_write_tokens:   int
    model_id:             str
    provider:             str

    @property
    def total_cents(self) -> float:
        """Convenience alias — total cost without cache optimisation."""
        return self.total_uncached_cents

    @property
    def cached_total_cents(self) -> float:
        """Total cost with cache optimisation applied."""
        return self.total_cached_cents

    @property
    def cache_saving_pct(self) -> float:
        """Cache saving as a percentage of uncached cost."""
        if self.total_uncached_cents == 0:
            return 0.0
        return (self.cache_saving_cents / self.total_uncached_cents) * 100.0

    @property
    def is_free(self) -> bool:
        """True for TIER_S (deterministic shortcut) or local models."""
        return self.total_uncached_cents == 0.0

    def format_cents(self, value: float) -> str:
        if value < 0.01:
            return f"{value * 1000:.3f}m¢"   # milli-cents for tiny amounts
        if value < 1.0:
            return f"{value:.3f}¢"
        return f"{value:.2f}¢"

    def __repr__(self) -> str:
        return (
            f"CostEstimate("
            f"uncached={self.format_cents(self.total_uncached_cents)}, "
            f"cached={self.format_cents(self.total_cached_cents)}, "
            f"saving={self.format_cents(self.cache_saving_cents)}, "
            f"model={self.model_id!r})"
        )


# ── Session Projection ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SessionCostProjection:
    """
    Projected total cost for a builder session.
    Built from per-call estimates accumulated during the session.
    Surfaced in the builder UI cost indicator (ARCHITECT_MODE only per manifest).
    """

    session_id:          str
    call_count:          int
    total_uncached_cents: float
    total_cached_cents:  float
    cache_saving_cents:  float
    dominant_tier:       str     # which tier drove most cost
    by_tier:             dict[str, float]  # tier → total cents

    @property
    def total_savings_pct(self) -> float:
        if self.total_uncached_cents == 0:
            return 0.0
        return (self.cache_saving_cents / self.total_uncached_cents) * 100.0

    def __repr__(self) -> str:
        return (
            f"SessionProjection(session={self.session_id!r}, "
            f"calls={self.call_count}, "
            f"total={self.total_cached_cents:.2f}¢, "
            f"saved={self.cache_saving_cents:.2f}¢)"
        )


# ── Cost Estimator ────────────────────────────────────────────────────────────

class CostEstimator:
    """
    Pre-flight cost estimation for inference calls.

    Stateless — one instance shared across InferenceAdapter calls.

    Usage
    -----
        estimator = CostEstimator()

        # From token counts
        est = estimator.estimate(
            descriptor=sonnet_descriptor,
            input_tokens=2000,
            output_tokens=500,
            cache_write_tokens=1500,  # static prefix size
        )
        print(est.cache_saving_cents)  # what caching saves

        # From text
        est = estimator.estimate_from_text(
            descriptor=haiku_descriptor,
            prompt_text=full_prompt,
            system_text=system_prompt,
            expected_output_tokens=400,
            cacheable_prefix_text=constraints_text,
        )
    """

    def __init__(self) -> None:
        self._token_est = TokenEstimator()
        # Session accumulator: session_id → list[CostEstimate]
        self._session_estimates: dict[str, list[CostEstimate]] = {}

    # ── Estimate from token counts ────────────────────────────────────────────

    def estimate(
        self,
        descriptor:          ModelDescriptor,
        input_tokens:        int,
        output_tokens:       int,
        cache_write_tokens:  int = 0,
        cache_read_tokens:   int = 0,
    ) -> CostEstimate:
        """
        Estimates cost given known token counts.

        Parameters
        ----------
        descriptor : ModelDescriptor
            The model to estimate for.
        input_tokens : int
            Non-cached input tokens.
        output_tokens : int
            Expected output tokens.
        cache_write_tokens : int
            Tokens in the static cacheable prefix (written to cache on first call).
        cache_read_tokens : int
            Tokens read from cache (for subsequent calls with same prefix).
        """
        p = descriptor  # alias for brevity

        input_cost        = (input_tokens         / 1000.0) * p.input_price_per_1k
        output_cost       = (output_tokens         / 1000.0) * p.output_price_per_1k
        cache_write_cost  = (cache_write_tokens    / 1000.0) * p.cache_write_price_per_1k
        cache_read_cost   = (cache_read_tokens     / 1000.0) * p.cache_read_price_per_1k

        # Uncached: full input + output
        uncached_input_cost = (
            ((input_tokens + cache_write_tokens) / 1000.0) * p.input_price_per_1k
        )
        total_uncached = (uncached_input_cost + output_cost) * 100.0  # → cents

        # Cached: write cost + cache read cost + output
        total_cached = (
            cache_write_cost + cache_read_cost + input_cost + output_cost
        ) * 100.0

        saving = max(0.0, total_uncached - total_cached)

        return CostEstimate(
            input_cost_cents       = input_cost    * 100.0,
            output_cost_cents      = output_cost   * 100.0,
            cache_write_cost_cents = cache_write_cost * 100.0,
            cache_read_cost_cents  = cache_read_cost  * 100.0,
            total_uncached_cents   = total_uncached,
            total_cached_cents     = total_cached,
            cache_saving_cents     = saving,
            input_tokens           = input_tokens,
            output_tokens          = output_tokens,
            cache_write_tokens     = cache_write_tokens,
            model_id               = p.model_id,
            provider               = p.provider,
        )

    # ── Estimate from text ────────────────────────────────────────────────────

    def estimate_from_text(
        self,
        descriptor:              ModelDescriptor,
        prompt_text:             str,
        system_text:             str   = "",
        expected_output_tokens:  int   = 512,
        cacheable_prefix_text:   str   = "",
    ) -> CostEstimate:
        """
        Estimates cost from raw text, using TokenEstimator internally.

        Parameters
        ----------
        descriptor : ModelDescriptor
            Target model.
        prompt_text : str
            Dynamic per-prompt text (not cached).
        system_text : str
            System instruction (usually partially cacheable).
        expected_output_tokens : int
            Conservative output token estimate.
        cacheable_prefix_text : str
            The static prefix text that would be cached (constraints,
            stable memory layers, determinism rules).
        """
        is_opus47 = "opus-4-7" in descriptor.model_id or "opus_4_7" in descriptor.model_id

        # Estimate each text segment
        dynamic_tokens  = self._token_est.estimate(
            prompt_text + system_text,
            ContentType.MIXED,
            apply_opus47_multiplier=is_opus47,
        ).estimated_tokens

        prefix_tokens = 0
        if cacheable_prefix_text and descriptor.supports_cache_control:
            prefix_tokens = self._token_est.estimate(
                cacheable_prefix_text,
                ContentType.MIXED,
                apply_opus47_multiplier=is_opus47,
            ).estimated_tokens

        return self.estimate(
            descriptor          = descriptor,
            input_tokens        = dynamic_tokens,
            output_tokens       = expected_output_tokens,
            cache_write_tokens  = prefix_tokens,
            cache_read_tokens   = 0,   # first call — write, not read
        )

    # ── 5-pass pipeline estimate ──────────────────────────────────────────────

    def estimate_five_pass_pipeline(
        self,
        descriptor_m:  ModelDescriptor,   # TIER_M (passes 3 & 4)
        descriptor_l:  ModelDescriptor,   # TIER_L (passes 1, 2, 5)
        prompt_tokens: int,
        prefix_tokens: int,
        avg_output:    int = 600,
    ) -> dict[str, Any]:
        """
        Estimates total cost of the 5-pass LLM orchestrator.

        Pass routing (per Audit 9):
            pass1_planning       → TIER_L
            pass2_dsl_draft      → TIER_L
            pass3_self_critique  → TIER_M
            pass4_determinism    → TIER_M
            pass5_final_output   → TIER_L

        Returns a dict with per-pass and total cost.
        """
        tier_l_passes = [
            ("pass1_planning",    self.estimate(descriptor_l, prompt_tokens, avg_output,
                                                cache_write_tokens=prefix_tokens)),
            ("pass2_dsl_draft",   self.estimate(descriptor_l, prompt_tokens, avg_output,
                                                cache_read_tokens=prefix_tokens)),
            ("pass5_final",       self.estimate(descriptor_l, prompt_tokens, avg_output,
                                                cache_read_tokens=prefix_tokens)),
        ]
        tier_m_passes = [
            ("pass3_critique",    self.estimate(descriptor_m, prompt_tokens, avg_output // 2,
                                                cache_read_tokens=prefix_tokens)),
            ("pass4_determinism", self.estimate(descriptor_m, prompt_tokens, avg_output // 3,
                                                cache_read_tokens=prefix_tokens)),
        ]

        all_passes   = tier_l_passes + tier_m_passes
        total_cached = sum(e.total_cached_cents for _, e in all_passes)
        total_uncached = sum(e.total_uncached_cents for _, e in all_passes)

        return {
            "passes":          {name: est for name, est in all_passes},
            "total_cached":    total_cached,
            "total_uncached":  total_uncached,
            "cache_saving":    total_uncached - total_cached,
            "per_pass_avg":    total_cached / 5,
        }

    # ── Session accumulation ──────────────────────────────────────────────────

    def record_for_session(
        self,
        session_id: str,
        estimate:   CostEstimate,
        tier:       str = ComplexityTier.L,
    ) -> None:
        """Accumulates an estimate for session projection."""
        self._session_estimates.setdefault(session_id, []).append(estimate)

    def session_projection(self, session_id: str) -> SessionCostProjection | None:
        """Builds a SessionCostProjection from accumulated estimates."""
        estimates = self._session_estimates.get(session_id)
        if not estimates:
            return None

        by_tier: dict[str, float] = {}
        total_uncached = 0.0
        total_cached   = 0.0
        total_saving   = 0.0

        for est in estimates:
            total_uncached += est.total_uncached_cents
            total_cached   += est.total_cached_cents
            total_saving   += est.cache_saving_cents

        dominant = max(by_tier, key=lambda k: by_tier[k]) if by_tier else ComplexityTier.L

        return SessionCostProjection(
            session_id           = session_id,
            call_count           = len(estimates),
            total_uncached_cents = total_uncached,
            total_cached_cents   = total_cached,
            cache_saving_cents   = total_saving,
            dominant_tier        = dominant,
            by_tier              = by_tier,
        )

    def clear_session(self, session_id: str) -> None:
        self._session_estimates.pop(session_id, None)

    # ── Free-tier check ───────────────────────────────────────────────────────

    @staticmethod
    def is_free_call(descriptor: ModelDescriptor) -> bool:
        """Returns True if the call has zero cost (local model or TIER_S)."""
        return (
            descriptor.provider == "local"
            or (
                descriptor.input_price_per_1k == 0.0
                and descriptor.output_price_per_1k == 0.0
            )
        )