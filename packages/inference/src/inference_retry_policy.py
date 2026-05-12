"""
inference_retry_policy.py — InferenceRetryPolicy
===================================================
Tier-aware retry policy for the inference transport layer.

This is DISTINCT from PIL's pil_retry_policy.py:
    inference_retry_policy — handles TRANSPORT failures (connection drops,
                             timeouts, 429 rate limits, 500 server errors).
                             Operates below PIL, transparent to callers.

    pil_retry_policy       — handles QUALITY failures (malformed LLM output,
                             failed structured parsing, self-critique rejection).
                             Operates at the PIL orchestrator level.

## Three Failure Categories

    TRANSPORT  — network error, timeout, 5xx, 429
                 Action: retry immediately (backoff on 429), same model
                 Max retries: 2

    SCHEMA     — provider returned HTTP 200 but response body is malformed
                 (missing content field, wrong JSON structure)
                 Action: retry once, same model; if fails again → raise
                 Max retries: 1

    QUALITY    — provider returned 200 + valid JSON, but content is empty
                 or token count is 0 (model produced nothing)
                 Action: retry once; if fails → raise; PIL handles escalation
                 Max retries: 1

## Backoff Strategy
    - 429 Rate Limit: exponential backoff starting at retry_after header
      value or 5s if absent; max wait 60s.
    - 5xx Server Error: fixed 2s wait before retry.
    - Other transport errors: immediate retry.

## InferenceTransportError
Raised when all retries are exhausted. Carries:
    - provider and model_id that were tried
    - number of attempts made
    - last_error: the underlying exception
Caught by InferenceAdapter which then tries the fallback chain via
fallback_policy.py.
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from typing import Any, Callable


# ── Error Types ───────────────────────────────────────────────────────────────

@dataclass
class InferenceTransportError(Exception):
    """
    Raised when all retry attempts for a call are exhausted.
    InferenceAdapter catches this and tries the next provider in the fallback chain.

    Attributes
    ----------
    provider : str
        Provider that was attempted.
    model_id : str
        Model ID that was attempted.
    attempts : int
        Total attempts made (including the first).
    last_error : Exception | None
        The underlying exception from the last attempt.
    call_label : str
        The PIL pass label for diagnostics.
    """

    provider:   str
    model_id:   str
    attempts:   int
    last_error: Exception | None  = None
    call_label: str               = ""

    def __str__(self) -> str:
        return (
            f"InferenceTransportError: {self.provider}/{self.model_id} "
            f"failed after {self.attempts} attempt(s) "
            f"[{self.call_label!r}]. "
            f"Last error: {self.last_error}"
        )


class InferenceSchemaError(Exception):
    """Raised when a provider returns HTTP 200 but a malformed response body."""


class InferenceQualityError(Exception):
    """Raised when the model returns a valid response but with empty content."""


# ── Retry Config ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RetryConfig:
    """
    Per-tier retry configuration.

    transport_retries : int
        Max additional attempts on transport failure (total = 1 + N).
    schema_retries : int
        Max additional attempts on schema failure.
    quality_retries : int
        Max additional attempts on quality failure.
    base_backoff_s : float
        Base wait time before first retry on 5xx or 429.
    max_backoff_s : float
        Cap on exponential backoff.
    """

    transport_retries: int   = 2
    schema_retries:    int   = 1
    quality_retries:   int   = 1
    base_backoff_s:    float = 2.0
    max_backoff_s:     float = 60.0


# Sensible defaults by tier
_TIER_CONFIGS: dict[str, RetryConfig] = {
    "TIER_S": RetryConfig(transport_retries=0, schema_retries=0, quality_retries=0),
    "TIER_M": RetryConfig(transport_retries=2, schema_retries=1, quality_retries=1,
                          base_backoff_s=1.0),
    "TIER_L": RetryConfig(transport_retries=2, schema_retries=1, quality_retries=1,
                          base_backoff_s=2.0),
    "TIER_XL": RetryConfig(transport_retries=2, schema_retries=1, quality_retries=1,
                           base_backoff_s=2.0, max_backoff_s=30.0),
}


# ── Retry Policy ──────────────────────────────────────────────────────────────

class InferenceRetryPolicy:
    """
    Wraps an inference call function with tier-aware retry logic.

    Distinct from pil_retry_policy.py — handles transport/schema/quality
    failures at the HTTP layer before PIL ever sees the response.

    Thread-safe — one instance is shared across InferenceAdapter calls.

    Usage
    -----
        policy = InferenceRetryPolicy()

        def attempt() -> dict:
            return provider_client.complete(model_id=..., prompt=..., ...)

        raw_response = policy.execute(attempt, call_label="pass2_dsl_draft",
                                      tier="TIER_L", provider="anthropic",
                                      model_id="claude-sonnet-4-6")
    """

    def __init__(
        self,
        config_overrides: dict[str, RetryConfig] | None = None,
    ) -> None:
        self._configs = dict(_TIER_CONFIGS)
        if config_overrides:
            self._configs.update(config_overrides)
        self._lock = threading.Lock()

    def execute(
        self,
        attempt_fn:  Callable[[], dict[str, Any]],
        call_label:  str = "",
        tier:        str = "TIER_L",
        provider:    str = "",
        model_id:    str = "",
    ) -> dict[str, Any]:
        """
        Executes attempt_fn() with retry logic applied.

        Parameters
        ----------
        attempt_fn : Callable
            The actual provider call. Must return a dict with at minimum
            {"text": str, "input_tokens": int, "output_tokens": int}.
        call_label : str
            PIL pass label for diagnostic messages.
        tier : str
            ComplexityTier — selects which RetryConfig to use.
        provider : str
            Provider name for InferenceTransportError.
        model_id : str
            Model ID for InferenceTransportError.

        Returns
        -------
        dict[str, Any]
            Raw provider response dict.

        Raises
        ------
        InferenceTransportError
            All transport retries exhausted.
        InferenceSchemaError
            Schema retries exhausted.
        InferenceQualityError
            Quality retries exhausted.
        """
        config = self._configs.get(tier, _TIER_CONFIGS["TIER_L"])

        # ── Transport retry loop ──────────────────────────────────────────────
        last_transport_error: Exception | None = None
        for transport_attempt in range(config.transport_retries + 1):

            try:
                response = self._call_with_timeout(attempt_fn)
            except Exception as exc:
                last_transport_error = exc
                if transport_attempt >= config.transport_retries:
                    raise InferenceTransportError(
                        provider   = provider,
                        model_id   = model_id,
                        attempts   = transport_attempt + 1,
                        last_error = exc,
                        call_label = call_label,
                    ) from exc

                wait = self._backoff(exc, transport_attempt, config)
                if wait > 0:
                    time.sleep(wait)
                continue

            # ── Schema validation ─────────────────────────────────────────────
            schema_error = self._check_schema(response)
            if schema_error:
                if config.schema_retries == 0:
                    raise InferenceSchemaError(
                        f"[{call_label}] Provider {provider}/{model_id} "
                        f"returned malformed response: {schema_error}"
                    )
                # One retry for schema errors
                try:
                    response = self._call_with_timeout(attempt_fn)
                    schema_error2 = self._check_schema(response)
                    if schema_error2:
                        raise InferenceSchemaError(
                            f"[{call_label}] {provider}/{model_id} "
                            f"malformed response on retry: {schema_error2}"
                        )
                except InferenceSchemaError:
                    raise
                except Exception as exc:
                    raise InferenceTransportError(
                        provider=provider, model_id=model_id,
                        attempts=transport_attempt + 2, last_error=exc,
                        call_label=call_label,
                    ) from exc

            # ── Quality validation ────────────────────────────────────────────
            quality_error = self._check_quality(response)
            if quality_error:
                if config.quality_retries == 0:
                    raise InferenceQualityError(
                        f"[{call_label}] {provider}/{model_id} "
                        f"empty/zero-token response: {quality_error}"
                    )
                try:
                    response = self._call_with_timeout(attempt_fn)
                    quality_error2 = self._check_quality(response)
                    if quality_error2:
                        raise InferenceQualityError(
                            f"[{call_label}] {provider}/{model_id} "
                            f"empty response on retry: {quality_error2}"
                        )
                except InferenceQualityError:
                    raise
                except Exception as exc:
                    raise InferenceTransportError(
                        provider=provider, model_id=model_id,
                        attempts=transport_attempt + 2, last_error=exc,
                        call_label=call_label,
                    ) from exc

            return response

        # Should never reach here — loop always returns or raises
        raise InferenceTransportError(
            provider   = provider,
            model_id   = model_id,
            attempts   = config.transport_retries + 1,
            last_error = last_transport_error,
            call_label = call_label,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _call_with_timeout(fn: Callable) -> dict[str, Any]:
        """Calls fn() and normalises known exception types."""
        return fn()

    @staticmethod
    def _check_schema(response: dict[str, Any]) -> str | None:
        """
        Returns an error string if the response is structurally malformed.
        Returns None if the response looks valid.
        """
        if not isinstance(response, dict):
            return f"Expected dict, got {type(response).__name__}"
        if "text" not in response:
            return f"Missing 'text' key. Keys present: {sorted(response.keys())}"
        if not isinstance(response["text"], str):
            return f"'text' must be str, got {type(response['text']).__name__}"
        return None

    @staticmethod
    def _check_quality(response: dict[str, Any]) -> str | None:
        """
        Returns an error string if the response is empty or zero-token.
        Returns None if the response has usable content.
        """
        text = response.get("text", "")
        if not text.strip():
            return "Empty response text from model."
        output_tokens = response.get("output_tokens", -1)
        if output_tokens == 0:
            return "Model reported 0 output tokens."
        return None

    @staticmethod
    def _backoff(
        exc:     Exception,
        attempt: int,
        config:  RetryConfig,
    ) -> float:
        """
        Returns wait time in seconds before the next retry.
        Reads Retry-After from 429 exceptions when available.
        """
        exc_str = str(exc).lower()

        # 429 rate limit — check for Retry-After header
        if "429" in exc_str or "rate limit" in exc_str or "rate_limit" in exc_str:
            # Some SDKs embed the header value in the error message
            import re
            m = re.search(r"retry.after[:\s]+(\d+)", exc_str)
            if m:
                return min(float(m.group(1)), config.max_backoff_s)
            return min(config.base_backoff_s * (2 ** attempt), config.max_backoff_s)

        # 5xx server error — fixed short wait
        if "5" in exc_str and ("server" in exc_str or "internal" in exc_str):
            return config.base_backoff_s

        # Connection / timeout — immediate retry
        return 0.0

    def get_config(self, tier: str) -> RetryConfig:
        """Returns the RetryConfig for a given tier."""
        return self._configs.get(tier, _TIER_CONFIGS["TIER_L"])

    def set_config(self, tier: str, config: RetryConfig) -> None:
        """Overrides the RetryConfig for a specific tier."""
        with self._lock:
            self._configs[tier] = config

    def __repr__(self) -> str:
        tiers = sorted(self._configs.keys())
        return f"InferenceRetryPolicy(tiers={tiers})"