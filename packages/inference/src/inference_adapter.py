"""
inference_adapter.py — InferenceAdapter
=========================================
Single provider-agnostic dispatch point for every LLM call in XACE.

This is Inference Invariant II1: ALL LLM calls go through inference_adapter.
No PIL submodule speaks HTTP directly. No direct `anthropic`, `openai`, or
`requests` import lives outside `packages/inference/src/providers/`.

## Contract
Every PIL submodule that needs a model response does:
    response = adapter.call(InferenceRequest(...))

InferenceAdapter then:
    1. Routes the request to the correct provider via provider_registry
    2. Applies prompt_cache directives to static prefix blocks
    3. Enforces inference_budget (token cap)
    4. Handles retry via inference_retry_policy on transport failure
    5. Records a telemetry event via telemetry_pipeline
    6. Returns InferenceResponse with full accounting fields

## InferenceRequest
Callers supply:
    prompt_parts   — list of PromptPart (each may be marked cacheable)
    system_prompt  — optional system-level instruction string
    logical_model  — logical_name from ModelDescriptor (not a concrete model string)
    complexity_tier— ComplexityTier hint; model_router may override logical_model
    max_tokens     — maximum output tokens for this call (default: model max)
    temperature    — 0.0–1.0 (default 0.0 for deterministic-flavoured outputs)
    session_id     — for telemetry grouping
    call_label     — human-readable label for telemetry (e.g. "pass2_dsl_draft")

## InferenceResponse
Returns:
    text           — raw model output text
    input_tokens   — tokens consumed on input (non-cached)
    output_tokens  — tokens generated
    cache_read_tokens  — tokens served from cache
    cache_write_tokens — tokens written to cache this call
    cost_cents     — estimated USD cents
    model_id       — concrete model string that actually ran
    provider       — which provider handled the call
    latency_ms     — wall-clock time for the call
    call_label     — echoed from request
    cached         — True if response came from response_cache (zero cost)

## Concurrency
InferenceAdapter is thread-safe. Individual provider clients handle their
own connection pooling. Multiple PIL passes may run concurrently in the
future — this adapter is the safe bottleneck for budget enforcement.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .model_descriptor import ModelDescriptor, ComplexityTier
from .provider_registry import ProviderRegistry, ProviderNotFoundError
from .telemetry_pipeline import TelemetryPipeline, InferenceTelemetryEvent
from .inference_budget import InferenceBudget, BudgetExceededError
from .inference_retry_policy import InferenceRetryPolicy, InferenceTransportError
from .prompt_cache import PromptCache
from .response_cache import ResponseCache
from .cache_key_builder import CacheKeyBuilder


# ── Prompt Part ───────────────────────────────────────────────────────────────

@dataclass
class PromptPart:
    """
    One segment of a prompt, optionally marked as cacheable.

    cacheable=True marks this segment for Anthropic cache_control.
    Only use cacheable=True for segments that are identical across
    multiple calls (architectural constraints, stable memory layers,
    determinism rules). Dynamic per-prompt content must never be cached.
    """
    text:      str
    cacheable: bool = False
    label:     str  = ""   # for telemetry and debugging


# ── Inference Request ─────────────────────────────────────────────────────────

@dataclass
class InferenceRequest:
    """
    Describes one LLM call to be dispatched by InferenceAdapter.

    Attributes
    ----------
    prompt_parts : list[PromptPart]
        Ordered list of prompt segments. Cacheable parts are marked with
        cacheable=True and placed in the prefix block.
    system_prompt : str
        System-level instruction. Sent as system message to all providers.
    logical_model : str
        logical_name from ModelDescriptor. model_router may override this.
        Example: "standard_mutation", "cheap_validation"
    complexity_tier : str
        ComplexityTier hint. If TIER_S, adapter returns early without calling
        any model (Inference Invariant II2).
    max_tokens : int
        Maximum output tokens. 0 = use model default.
    temperature : float
        0.0 for deterministic-flavoured outputs (mutation generation).
        Up to 0.7 for creative/suggestion passes.
    session_id : str
        Builder session ID for telemetry grouping and budget attribution.
    call_label : str
        Human-readable label for telemetry: "pass1_planning", "pass2_dsl_draft", etc.
    request_id : str
        UUID for this specific call (auto-generated if empty).
    cgs_structural_hash : str
        CGS structural hash at call time, used as response cache key.
    intent_class : str
        Intent classification for response cache key.
    bypass_response_cache : bool
        Force a live call even if response_cache has a hit.
    """

    prompt_parts:          list[PromptPart]
    system_prompt:         str             = ""
    logical_model:         str             = "standard_mutation"
    complexity_tier:       str             = ComplexityTier.L
    max_tokens:            int             = 0
    temperature:           float           = 0.0
    session_id:            str             = ""
    call_label:            str             = ""
    request_id:            str             = field(default_factory=lambda: uuid.uuid4().hex)
    cgs_structural_hash:   str             = ""
    intent_class:          str             = ""
    bypass_response_cache: bool            = False

    def full_prompt_text(self) -> str:
        """Returns all prompt parts concatenated (for token estimation)."""
        return "\n".join(p.text for p in self.prompt_parts)

    def cacheable_text(self) -> str:
        """Returns only cacheable parts concatenated."""
        return "\n".join(p.text for p in self.prompt_parts if p.cacheable)

    def dynamic_text(self) -> str:
        """Returns only non-cacheable (dynamic) parts concatenated."""
        return "\n".join(p.text for p in self.prompt_parts if not p.cacheable)


# ── Inference Response ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class InferenceResponse:
    """
    Fully-accounted response from one LLM call.

    All token counts and cost are populated even if the response came
    from the response_cache (cache=True, all token counts zero, cost_cents=0).
    """

    text:               str
    input_tokens:       int
    output_tokens:      int
    cache_read_tokens:  int
    cache_write_tokens: int
    cost_cents:         float
    model_id:           str
    provider:           str
    latency_ms:         float
    call_label:         str
    request_id:         str
    session_id:         str
    cached:             bool = False   # True = came from response_cache

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __repr__(self) -> str:
        source = "cache" if self.cached else self.provider
        return (
            f"InferenceResponse({self.call_label!r}, "
            f"via={source}, "
            f"tokens={self.total_tokens}, "
            f"cost={self.cost_cents:.4f}¢)"
        )


# ── Inference Error ───────────────────────────────────────────────────────────

class InferenceError(Exception):
    """Base class for all inference-layer errors."""

class ModelNotAvailableError(InferenceError):
    """Raised when no provider can serve the requested model tier."""

class InvalidRequestError(InferenceError):
    """Raised when the InferenceRequest is malformed."""


# ── Inference Adapter ─────────────────────────────────────────────────────────

class InferenceAdapter:
    """
    Single dispatch point for all LLM calls in XACE.

    Usage (from any PIL submodule)
    -----
        response = adapter.call(InferenceRequest(
            prompt_parts=[
                PromptPart(text=constraints_text, cacheable=True, label="constraints"),
                PromptPart(text=dynamic_context,   cacheable=False, label="context"),
            ],
            system_prompt=system_instruction,
            logical_model="standard_mutation",
            complexity_tier=ComplexityTier.L,
            call_label="pass2_dsl_draft",
            session_id=session_id,
            cgs_structural_hash=cgs_hash,
            intent_class=intent_type,
        ))
        mutation_json = response.text
    """

    def __init__(
        self,
        provider_registry:  ProviderRegistry,
        telemetry:          TelemetryPipeline,
        budget:             InferenceBudget,
        retry_policy:       InferenceRetryPolicy,
        prompt_cache:       PromptCache,
        response_cache:     ResponseCache,
        cache_key_builder:  CacheKeyBuilder,
    ) -> None:
        self._registry      = provider_registry
        self._telemetry     = telemetry
        self._budget        = budget
        self._retry         = retry_policy
        self._prompt_cache  = prompt_cache
        self._resp_cache    = response_cache
        self._key_builder   = cache_key_builder

    # ── Public API ────────────────────────────────────────────────────────────

    def call(self, request: InferenceRequest) -> InferenceResponse:
        """
        Dispatches one LLM call.

        Implements II1 (only dispatch point), II2 (TIER_S shortcut),
        II8 (telemetry on every call).

        Raises
        ------
        BudgetExceededError
            If the session or daily budget is already exhausted.
        ModelNotAvailableError
            If no provider can serve the request after fallbacks.
        InvalidRequestError
            If the request is structurally invalid.
        """
        self._validate_request(request)

        # II2: TIER_S never reaches a model
        if request.complexity_tier == ComplexityTier.S:
            return self._deterministic_shortcut(request)

        # Budget pre-check
        self._budget.pre_check(request.session_id)

        # Response cache lookup
        if not request.bypass_response_cache and request.cgs_structural_hash:
            cache_key = self._key_builder.build(
                intent_class        = request.intent_class,
                structural_cgs_hash = request.cgs_structural_hash,
                logical_model       = request.logical_model,
            )
            cached_text = self._resp_cache.get(cache_key)
            if cached_text is not None:
                return self._cached_response(cached_text, request)

        # Resolve descriptor (model_router decides which model within the tier)
        descriptor = self._registry.get(request.logical_model)

        # Build prompt with cache_control directives applied
        prepared_prompt = self._prompt_cache.prepare(
            request.prompt_parts, descriptor
        )

        # Dispatch with retry
        start_ms = time.monotonic() * 1000
        raw_resp  = self._dispatch_with_retry(request, descriptor, prepared_prompt)
        latency   = time.monotonic() * 1000 - start_ms

        # Build response
        cost = descriptor.cost_estimate_cents(
            input_tokens       = raw_resp.get("input_tokens", 0),
            output_tokens      = raw_resp.get("output_tokens", 0),
            cache_read_tokens  = raw_resp.get("cache_read_tokens", 0),
            cache_write_tokens = raw_resp.get("cache_write_tokens", 0),
        )

        response = InferenceResponse(
            text               = raw_resp["text"],
            input_tokens       = raw_resp.get("input_tokens", 0),
            output_tokens      = raw_resp.get("output_tokens", 0),
            cache_read_tokens  = raw_resp.get("cache_read_tokens", 0),
            cache_write_tokens = raw_resp.get("cache_write_tokens", 0),
            cost_cents         = cost,
            model_id           = descriptor.model_id,
            provider           = descriptor.provider,
            latency_ms         = latency,
            call_label         = request.call_label,
            request_id         = request.request_id,
            session_id         = request.session_id,
        )

        # Budget update
        self._budget.record(
            session_id    = request.session_id,
            input_tokens  = response.input_tokens + response.cache_read_tokens,
            output_tokens = response.output_tokens,
            cost_cents    = response.cost_cents,
        )

        # Store in response cache if structural hash available
        if request.cgs_structural_hash and not request.bypass_response_cache:
            self._resp_cache.put(cache_key, response.text)

        # Telemetry — II8: every call emits an event
        self._telemetry.emit(InferenceTelemetryEvent(
            request_id         = request.request_id,
            session_id         = request.session_id,
            call_label         = request.call_label,
            provider           = descriptor.provider,
            model_id           = descriptor.model_id,
            complexity_tier    = request.complexity_tier,
            input_tokens       = response.input_tokens,
            output_tokens      = response.output_tokens,
            cache_read_tokens  = response.cache_read_tokens,
            cache_write_tokens = response.cache_write_tokens,
            cost_cents         = response.cost_cents,
            latency_ms         = latency,
            outcome            = "success",
            cached             = False,
        ))

        return response

    # ── Internal ──────────────────────────────────────────────────────────────

    def _dispatch_with_retry(
        self,
        request:         InferenceRequest,
        descriptor:      ModelDescriptor,
        prepared_prompt: dict[str, Any],
    ) -> dict[str, Any]:
        """Dispatches to provider with retry logic applied."""
        provider_client = self._registry.get_client(descriptor.provider)
        max_tokens      = request.max_tokens or descriptor.max_output_tokens

        def _attempt() -> dict[str, Any]:
            return provider_client.complete(
                model_id      = descriptor.model_id,
                prompt        = prepared_prompt,
                system_prompt = request.system_prompt,
                max_tokens    = max_tokens,
                temperature   = request.temperature,
            )

        return self._retry.execute(_attempt, request.call_label)

    def _deterministic_shortcut(self, request: InferenceRequest) -> InferenceResponse:
        """
        TIER_S: returns a zero-cost marker response indicating the
        deterministic Phase 12 GDE pipeline should handle this request.
        The caller (pil_pipeline) checks for TIER_S and routes accordingly.
        """
        self._telemetry.emit(InferenceTelemetryEvent(
            request_id      = request.request_id,
            session_id      = request.session_id,
            call_label      = request.call_label,
            provider        = "deterministic",
            model_id        = "phase12_gde",
            complexity_tier = ComplexityTier.S,
            outcome         = "deterministic_shortcut",
            cached          = True,
        ))
        return InferenceResponse(
            text               = "__TIER_S_DETERMINISTIC__",
            input_tokens       = 0,
            output_tokens      = 0,
            cache_read_tokens  = 0,
            cache_write_tokens = 0,
            cost_cents         = 0.0,
            model_id           = "phase12_gde",
            provider           = "deterministic",
            latency_ms         = 0.0,
            call_label         = request.call_label,
            request_id         = request.request_id,
            session_id         = request.session_id,
            cached             = True,
        )

    def _cached_response(
        self, text: str, request: InferenceRequest
    ) -> InferenceResponse:
        """Wraps a response_cache hit into a zero-cost InferenceResponse."""
        self._telemetry.emit(InferenceTelemetryEvent(
            request_id      = request.request_id,
            session_id      = request.session_id,
            call_label      = request.call_label,
            provider        = "response_cache",
            model_id        = request.logical_model,
            complexity_tier = request.complexity_tier,
            outcome         = "cache_hit",
            cached          = True,
        ))
        return InferenceResponse(
            text               = text,
            input_tokens       = 0,
            output_tokens      = 0,
            cache_read_tokens  = 0,
            cache_write_tokens = 0,
            cost_cents         = 0.0,
            model_id           = request.logical_model,
            provider           = "response_cache",
            latency_ms         = 0.0,
            call_label         = request.call_label,
            request_id         = request.request_id,
            session_id         = request.session_id,
            cached             = True,
        )

    @staticmethod
    def _validate_request(request: InferenceRequest) -> None:
        if not request.prompt_parts:
            raise InvalidRequestError(
                "InferenceRequest must have at least one PromptPart."
            )
        if not ComplexityTier.is_valid(request.complexity_tier):
            raise InvalidRequestError(
                f"Invalid complexity_tier '{request.complexity_tier}'. "
                f"Valid: {ComplexityTier.ALL}"
            )
        if not 0.0 <= request.temperature <= 1.0:
            raise InvalidRequestError(
                f"temperature must be in [0.0, 1.0], got {request.temperature}."
            )

    @property
    def is_healthy(self) -> bool:
        """Quick health check — True if at least one provider is reachable."""
        return self._registry.has_any_provider()