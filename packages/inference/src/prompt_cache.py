"""
fallback_policy.py — FallbackPolicy
=======================================
Defines and executes provider fallback chains when inference calls fail.

When InferenceAdapter catches InferenceTransportError from the primary
provider, it consults FallbackPolicy for the next provider to try.
The chain runs until either:
    (a) a provider succeeds → return response
    (b) all providers in the chain are exhausted → raise ProviderChainExhaustedError

## Fallback Chain Structure
A FallbackChain is an ordered list of (provider_name, logical_model_name) pairs.
The first entry is always the primary. Each subsequent entry is a fallback.

    Example (TIER_L chain):
        [("anthropic", "standard_mutation"),   # primary
         ("deepseek",  "deepseek_premium"),    # fallback 1
         ("openai",    "openai_standard")]     # fallback 2

## Why Per-Tier Chains?
Different tiers have different fallback logic:
    TIER_XL: must have code_gen capability → OpenAI is a valid fallback, DeepSeek V4 Pro is
    TIER_L:  any standard model works → DeepSeek Flash is acceptable
    TIER_M:  cheapest model in any available provider
    TIER_S:  no fallback needed (deterministic, never calls a provider)

## FallbackAttempt
Per-call mutable state. InferenceAdapter creates one FallbackAttempt
per call and passes it through the retry loop. FallbackAttempt tracks
which providers have been tried so model_router excludes them.

## ProviderChainExhaustedError
Raised when all providers in the chain have failed.
InferenceAdapter catches this, emits telemetry, then returns a
ClarificationRequest to PIL ("cannot process now, please try again").
This prevents infinite retry loops.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .model_descriptor import ModelDescriptor, ComplexityTier, BUILTIN_DESCRIPTORS
from .provider_registry import ProviderRegistry


# ── Errors ────────────────────────────────────────────────────────────────────

@dataclass
class ProviderChainExhaustedError(Exception):
    """
    Raised when every provider in the fallback chain has been tried
    and all have failed.

    PIL catches this and generates a ClarificationRequest with a
    "service unavailable" message — never silently drops the prompt.

    Attributes
    ----------
    tier : str
        The ComplexityTier that was being served.
    tried_providers : tuple[str, ...]
        All providers that were attempted.
    call_label : str
        The PIL pass label for diagnostics.
    failure_reasons : tuple[str, ...]
        Per-provider failure summary.
    """

    tier:              str
    tried_providers:   tuple[str, ...]
    call_label:        str             = ""
    failure_reasons:   tuple[str, ...] = ()

    def __str__(self) -> str:
        return (
            f"ProviderChainExhaustedError: all {len(self.tried_providers)} providers "
            f"failed for tier '{self.tier}' [{self.call_label!r}]. "
            f"Tried: {self.tried_providers}."
        )


# ── Chain Link ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ChainLink:
    """
    One step in a FallbackChain.

    Attributes
    ----------
    provider : str
        Provider identifier ("anthropic", "openai", "deepseek", etc.)
    logical_model : str
        Logical model name from ModelDescriptor registry.
    max_attempts : int
        How many times to retry this specific provider before skipping.
        Usually 1 for fallbacks (the primary already retried via InferenceRetryPolicy).
    required_capability : str
        ModelCapability the model must have. Empty = no requirement.
        Example: "code_gen" ensures fallback can generate Rust.
    """

    provider:              str
    logical_model:         str
    max_attempts:          int = 1
    required_capability:   str = ""

    def __repr__(self) -> str:
        return f"ChainLink({self.provider!r} / {self.logical_model!r})"


# ── Fallback Chain ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FallbackChain:
    """
    Ordered list of ChainLinks defining the fallback sequence for one tier.
    The first link is the primary. Later links are fallbacks.

    Built by FallbackPolicy from config + capability checks.
    """

    tier:  str
    links: tuple[ChainLink, ...]

    @property
    def primary(self) -> ChainLink:
        return self.links[0]

    @property
    def fallbacks(self) -> tuple[ChainLink, ...]:
        return self.links[1:]

    def has_provider(self, provider: str) -> bool:
        return any(link.provider == provider for link in self.links)

    def next_link_after(self, failed_providers: set[str]) -> ChainLink | None:
        """Returns the first link whose provider has not failed yet."""
        for link in self.links:
            if link.provider not in failed_providers:
                return link
        return None

    def __repr__(self) -> str:
        chain = " → ".join(f"{l.provider}" for l in self.links)
        return f"FallbackChain({self.tier}: {chain})"


# ── Fallback Attempt ──────────────────────────────────────────────────────────

@dataclass
class FallbackAttempt:
    """
    Mutable per-call state tracking which providers have been tried.

    InferenceAdapter creates one per call and updates it after each failure.
    Used by model_router to exclude failed providers from routing.

    Attributes
    ----------
    tier : str
        The complexity tier for this call.
    call_label : str
        PIL pass label.
    tried: list[tuple[str, str, str]]
        List of (provider, model_id, failure_reason) tuples.
    started_at : float
        Unix timestamp when the call attempt began.
    """

    tier:       str
    call_label: str = ""
    tried:      list[tuple[str, str, str]] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)

    def record_failure(
        self, provider: str, model_id: str, reason: str
    ) -> None:
        self.tried.append((provider, model_id, reason))

    @property
    def failed_providers(self) -> set[str]:
        return {t[0] for t in self.tried}

    @property
    def failed_provider_tuple(self) -> tuple[str, ...]:
        return tuple(self.failed_providers)

    @property
    def attempt_count(self) -> int:
        return len(self.tried)

    def elapsed_ms(self) -> float:
        return (time.time() - self.started_at) * 1000.0

    def failure_summary(self) -> tuple[str, ...]:
        return tuple(
            f"{provider}/{model}: {reason}"
            for provider, model, reason in self.tried
        )

    def __repr__(self) -> str:
        return (
            f"FallbackAttempt({self.tier}, "
            f"tried={len(self.tried)}, "
            f"failed={self.failed_providers})"
        )


# ── Default Chains ────────────────────────────────────────────────────────────

def _default_chains() -> dict[str, FallbackChain]:
    """Builds the default fallback chains from BUILTIN_DESCRIPTORS."""
    from .model_descriptor import ModelCapability

    return {
        ComplexityTier.XL: FallbackChain(
            tier=ComplexityTier.XL,
            links=(
                ChainLink("anthropic", "premium_reasoning",
                          required_capability=ModelCapability.CODE_GEN),
                ChainLink("openai",    "openai_premium",
                          required_capability=ModelCapability.CODE_GEN),
                # DeepSeek V4 Pro has code_gen — acceptable XL fallback
                ChainLink("deepseek",  "deepseek_premium",
                          required_capability=ModelCapability.CODE_GEN),
            ),
        ),
        ComplexityTier.L: FallbackChain(
            tier=ComplexityTier.L,
            links=(
                ChainLink("anthropic", "standard_mutation"),
                ChainLink("deepseek",  "deepseek_premium"),
                ChainLink("zai",       "zai_standard"),
                ChainLink("openai",    "openai_standard"),
            ),
        ),
        ComplexityTier.M: FallbackChain(
            tier=ComplexityTier.M,
            links=(
                ChainLink("anthropic", "cheap_validation"),
                ChainLink("deepseek",  "deepseek_standard"),
                ChainLink("minimax",   "minimax_standard"),
                ChainLink("local",     "local_dev"),
            ),
        ),
        ComplexityTier.S: FallbackChain(
            tier=ComplexityTier.S,
            links=(),   # TIER_S never reaches a provider
        ),
    }


# ── Fallback Policy ───────────────────────────────────────────────────────────

class FallbackPolicy:
    """
    Manages fallback chains and executes provider failover for inference calls.

    One instance is shared across InferenceAdapter calls.
    Thread-safe — chains are immutable after construction.

    Usage
    -----
        policy   = FallbackPolicy(registry)
        attempt  = FallbackAttempt(tier=ComplexityTier.L, call_label="pass2")

        while True:
            next_link = policy.next_link(attempt)
            if next_link is None:
                raise ProviderChainExhaustedError(...)

            try:
                descriptor = registry.get(next_link.logical_model)
                response   = provider.complete(...)
                break
            except InferenceTransportError as exc:
                attempt.record_failure(next_link.provider, descriptor.model_id, str(exc))
    """

    def __init__(
        self,
        registry:        ProviderRegistry,
        chain_overrides: dict[str, FallbackChain] | None = None,
    ) -> None:
        self._registry = registry
        self._chains   = _default_chains()
        if chain_overrides:
            self._chains.update(chain_overrides)

    # ── Public API ────────────────────────────────────────────────────────────

    def next_link(self, attempt: FallbackAttempt) -> ChainLink | None:
        """
        Returns the next untried ChainLink for this attempt's tier,
        or None if all links are exhausted.

        Called by InferenceAdapter after each provider failure.
        When None is returned, InferenceAdapter raises ProviderChainExhaustedError.
        """
        chain = self._chains.get(attempt.tier)
        if not chain or not chain.links:
            return None

        return chain.next_link_after(attempt.failed_providers)

    def create_attempt(self, tier: str, call_label: str = "") -> FallbackAttempt:
        """Creates a fresh FallbackAttempt for a new call."""
        return FallbackAttempt(tier=tier, call_label=call_label)

    def chain_for(self, tier: str) -> FallbackChain | None:
        """Returns the FallbackChain for a tier, or None if undefined."""
        return self._chains.get(tier)

    def register_chain(self, chain: FallbackChain) -> None:
        """Registers or replaces a fallback chain for a tier."""
        self._chains[chain.tier] = chain

    def primary_link(self, tier: str) -> ChainLink | None:
        """Returns the primary (first) link for a tier."""
        chain = self._chains.get(tier)
        return chain.primary if (chain and chain.links) else None

    def all_providers_for_tier(self, tier: str) -> list[str]:
        """Returns all provider names in the chain for a tier."""
        chain = self._chains.get(tier)
        if not chain:
            return []
        return [link.provider for link in chain.links]

    def build_exhausted_error(
        self, attempt: FallbackAttempt
    ) -> ProviderChainExhaustedError:
        """Constructs a ProviderChainExhaustedError from a completed attempt."""
        return ProviderChainExhaustedError(
            tier             = attempt.tier,
            tried_providers  = attempt.failed_provider_tuple,
            call_label       = attempt.call_label,
            failure_reasons  = attempt.failure_summary(),
        )

    def validate_chains(self) -> list[str]:
        """
        Validates that all chain links reference registered logical model names.
        Returns list of validation error strings (empty = all valid).
        """
        errors: list[str] = []
        registered = set(self._registry.logical_model_names())
        for tier, chain in self._chains.items():
            for link in chain.links:
                if link.logical_model not in registered:
                    errors.append(
                        f"Chain {tier}: link {link!r} references unregistered "
                        f"logical_model '{link.logical_model}'. "
                        f"Registered names: {sorted(registered)}"
                    )
        return errors

    def summary(self) -> dict[str, list[str]]:
        """Returns human-readable chain summary keyed by tier."""
        return {
            tier: [f"{l.provider}/{l.logical_model}" for l in chain.links]
            for tier, chain in sorted(self._chains.items())
        }

    def __repr__(self) -> str:
        chain_repr = {
            tier: str(chain) for tier, chain in self._chains.items()
        }
        return f"FallbackPolicy({chain_repr})"