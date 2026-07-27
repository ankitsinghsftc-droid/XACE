"""
inference_retry_policy.py - InferenceRetryPolicy
================================================
Tier-aware retry policy for provider calls in the inference transport layer.

The policy records a deterministic ABI for every provider call attempt:
timeout policy, retry scheduling, rate-limit/backoff, failure category, final
outcome, and a stable user-facing error payload. The attempt/summary records
are consumed by InferenceAdapter telemetry and by launch certification.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable


RETRY_ATTEMPT_SCHEMA = "xace.inference_retry_attempt.v1"
RETRY_SUMMARY_SCHEMA = "xace.inference_retry_summary.v1"
USER_ERROR_SCHEMA = "xace.provider_call_error.v1"

FAILURE_TIMEOUT = "timeout"
FAILURE_RATE_LIMIT = "rate_limit"
FAILURE_SERVER_ERROR = "server_error"
FAILURE_TRANSPORT = "transport_error"
FAILURE_SCHEMA = "schema_error"
FAILURE_QUALITY = "quality_error"
FAILURE_PROVIDER = "provider_error"


@dataclass(frozen=True)
class RetryAttemptRecord:
    """Structured record for one actual provider call attempt."""

    schema: str = field(default=RETRY_ATTEMPT_SCHEMA, init=False)
    attempt_index: int = 0
    attempt_kind: str = "provider"
    provider: str = ""
    model_id: str = ""
    tier: str = "TIER_L"
    call_label: str = ""
    outcome: str = "success"
    failure_category: str = ""
    error_type: str = ""
    error_message: str = ""
    retry_scheduled: bool = False
    backoff_seconds: float = 0.0
    timeout_seconds: float = 0.0
    rate_limited: bool = False
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RetryExecutionReport:
    """Final summary for one provider call through the retry policy."""

    schema: str = field(default=RETRY_SUMMARY_SCHEMA, init=False)
    provider: str = ""
    model_id: str = ""
    tier: str = "TIER_L"
    call_label: str = ""
    timeout_seconds: float = 0.0
    attempt_count: int = 0
    retry_count: int = 0
    rate_limited: bool = False
    total_backoff_seconds: float = 0.0
    final_outcome: str = "success"
    final_failure_category: str = ""
    final_error_type: str = ""
    final_error_message: str = ""
    user_error: dict[str, Any] = field(default_factory=dict)
    attempts: list[RetryAttemptRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["attempts"] = [attempt.to_dict() for attempt in self.attempts]
        return data


@dataclass
class InferenceTransportError(Exception):
    """
    Raised when transport-oriented retry attempts are exhausted.

    retry_report carries the xace.inference_retry_summary.v1 payload when this
    error came from InferenceRetryPolicy.execute().
    """

    provider: str
    model_id: str
    attempts: int
    last_error: Exception | None = None
    call_label: str = ""
    failure_category: str = FAILURE_TRANSPORT
    retry_report: dict[str, Any] | None = None

    def __str__(self) -> str:
        code = ""
        if self.retry_report:
            user_error = self.retry_report.get("user_error") or {}
            code = f" code={user_error.get('code', '')}" if user_error.get("code") else ""
        return (
            f"InferenceTransportError: {self.provider}/{self.model_id} "
            f"failed after {self.attempts} attempt(s) "
            f"[{self.call_label!r}] category={self.failure_category}{code}. "
            f"Last error: {self.last_error}"
        )


class InferenceSchemaError(Exception):
    """Raised when a provider returns HTTP 200 but a malformed response body."""

    def __init__(
        self,
        message: str = "",
        *,
        retry_report: dict[str, Any] | None = None,
        failure_category: str = FAILURE_SCHEMA,
    ) -> None:
        super().__init__(message)
        self.retry_report = retry_report
        self.failure_category = failure_category


class InferenceQualityError(Exception):
    """Raised when the model returns a valid response with unusable content."""

    def __init__(
        self,
        message: str = "",
        *,
        retry_report: dict[str, Any] | None = None,
        failure_category: str = FAILURE_QUALITY,
    ) -> None:
        super().__init__(message)
        self.retry_report = retry_report
        self.failure_category = failure_category


@dataclass(frozen=True)
class RetryConfig:
    """
    Per-tier retry configuration.

    timeout_s records the provider-call timeout policy for this tier. The
    provider client owns protocol-specific enforcement; this layer classifies
    timeout failures and records the configured timeout in every report.
    """

    transport_retries: int = 2
    schema_retries: int = 1
    quality_retries: int = 1
    base_backoff_s: float = 2.0
    max_backoff_s: float = 60.0
    timeout_s: float = 120.0


_TIER_CONFIGS: dict[str, RetryConfig] = {
    "TIER_S": RetryConfig(
        transport_retries=0,
        schema_retries=0,
        quality_retries=0,
        timeout_s=0.0,
    ),
    "TIER_M": RetryConfig(
        transport_retries=2,
        schema_retries=1,
        quality_retries=1,
        base_backoff_s=1.0,
        timeout_s=60.0,
    ),
    "TIER_L": RetryConfig(
        transport_retries=2,
        schema_retries=1,
        quality_retries=1,
        base_backoff_s=2.0,
        timeout_s=120.0,
    ),
    "TIER_XL": RetryConfig(
        transport_retries=2,
        schema_retries=1,
        quality_retries=1,
        base_backoff_s=2.0,
        max_backoff_s=30.0,
        timeout_s=180.0,
    ),
}


ReportCallback = Callable[[dict[str, Any]], None]
SleepFn = Callable[[float], None]


class InferenceRetryPolicy:
    """
    Wraps provider calls with tier-aware retry logic and deterministic telemetry.
    """

    def __init__(
        self,
        config_overrides: dict[str, RetryConfig] | None = None,
        sleep_fn: SleepFn | None = None,
    ) -> None:
        self._configs = dict(_TIER_CONFIGS)
        if config_overrides:
            self._configs.update(config_overrides)
        self._sleep = sleep_fn or time.sleep
        self._lock = threading.Lock()

    def execute(
        self,
        attempt_fn: Callable[[], dict[str, Any]],
        call_label: str = "",
        tier: str = "TIER_L",
        provider: str = "",
        model_id: str = "",
        report_callback: ReportCallback | None = None,
    ) -> dict[str, Any]:
        """
        Executes attempt_fn() with retry logic applied.

        report_callback receives the final xace.inference_retry_summary.v1
        payload on both success and failure. The callback is best-effort and
        never changes provider-call control flow.
        """

        config = self._configs.get(tier, _TIER_CONFIGS["TIER_L"])
        attempts: list[RetryAttemptRecord] = []
        retry_budget_used = {
            FAILURE_TRANSPORT: 0,
            FAILURE_SCHEMA: 0,
            FAILURE_QUALITY: 0,
        }
        attempt_index = 0

        while True:
            attempt_index += 1
            started = time.monotonic()
            try:
                response = self._call_with_timeout(attempt_fn)
            except Exception as exc:
                category = self._categorize_exception(exc)
                can_retry = retry_budget_used[FAILURE_TRANSPORT] < config.transport_retries
                if can_retry:
                    retry_budget_used[FAILURE_TRANSPORT] += 1
                wait = self._backoff(exc, retry_budget_used[FAILURE_TRANSPORT] - 1, config) if can_retry else 0.0
                attempts.append(self._attempt_record(
                    attempt_index=attempt_index,
                    attempt_kind=FAILURE_TRANSPORT,
                    provider=provider,
                    model_id=model_id,
                    tier=tier,
                    call_label=call_label,
                    outcome="failure",
                    failure_category=category,
                    error_type=exc.__class__.__name__,
                    error_message=self._stable_error_message(exc),
                    retry_scheduled=can_retry,
                    backoff_seconds=wait,
                    timeout_seconds=config.timeout_s,
                    elapsed_ms=(time.monotonic() - started) * 1000,
                ))
                if can_retry:
                    self._sleep_if_needed(wait)
                    continue

                report = self._build_report(
                    provider=provider,
                    model_id=model_id,
                    tier=tier,
                    call_label=call_label,
                    timeout_seconds=config.timeout_s,
                    attempts=attempts,
                    final_outcome="failure",
                    final_failure_category=category,
                    final_error_type=exc.__class__.__name__,
                    final_error_message=self._stable_error_message(exc),
                )
                self._emit_report(report, report_callback)
                raise InferenceTransportError(
                    provider=provider,
                    model_id=model_id,
                    attempts=len(attempts),
                    last_error=exc,
                    call_label=call_label,
                    failure_category=category,
                    retry_report=report.to_dict(),
                ) from exc

            schema_error = self._check_schema(response)
            if schema_error:
                can_retry = retry_budget_used[FAILURE_SCHEMA] < config.schema_retries
                if can_retry:
                    retry_budget_used[FAILURE_SCHEMA] += 1
                attempts.append(self._attempt_record(
                    attempt_index=attempt_index,
                    attempt_kind=FAILURE_SCHEMA,
                    provider=provider,
                    model_id=model_id,
                    tier=tier,
                    call_label=call_label,
                    outcome="failure",
                    failure_category=FAILURE_SCHEMA,
                    error_type="InferenceSchemaError",
                    error_message=schema_error,
                    retry_scheduled=can_retry,
                    timeout_seconds=config.timeout_s,
                    elapsed_ms=(time.monotonic() - started) * 1000,
                ))
                if can_retry:
                    continue
                report = self._build_report(
                    provider=provider,
                    model_id=model_id,
                    tier=tier,
                    call_label=call_label,
                    timeout_seconds=config.timeout_s,
                    attempts=attempts,
                    final_outcome="failure",
                    final_failure_category=FAILURE_SCHEMA,
                    final_error_type="InferenceSchemaError",
                    final_error_message=schema_error,
                )
                self._emit_report(report, report_callback)
                raise InferenceSchemaError(
                    f"[{call_label}] Provider {provider}/{model_id} returned malformed response: {schema_error}",
                    retry_report=report.to_dict(),
                )

            quality_error = self._check_quality(response)
            if quality_error:
                can_retry = retry_budget_used[FAILURE_QUALITY] < config.quality_retries
                if can_retry:
                    retry_budget_used[FAILURE_QUALITY] += 1
                attempts.append(self._attempt_record(
                    attempt_index=attempt_index,
                    attempt_kind=FAILURE_QUALITY,
                    provider=provider,
                    model_id=model_id,
                    tier=tier,
                    call_label=call_label,
                    outcome="failure",
                    failure_category=FAILURE_QUALITY,
                    error_type="InferenceQualityError",
                    error_message=quality_error,
                    retry_scheduled=can_retry,
                    timeout_seconds=config.timeout_s,
                    elapsed_ms=(time.monotonic() - started) * 1000,
                ))
                if can_retry:
                    continue
                report = self._build_report(
                    provider=provider,
                    model_id=model_id,
                    tier=tier,
                    call_label=call_label,
                    timeout_seconds=config.timeout_s,
                    attempts=attempts,
                    final_outcome="failure",
                    final_failure_category=FAILURE_QUALITY,
                    final_error_type="InferenceQualityError",
                    final_error_message=quality_error,
                )
                self._emit_report(report, report_callback)
                raise InferenceQualityError(
                    f"[{call_label}] {provider}/{model_id} empty/zero-token response: {quality_error}",
                    retry_report=report.to_dict(),
                )

            attempts.append(self._attempt_record(
                attempt_index=attempt_index,
                attempt_kind="provider",
                provider=provider,
                model_id=model_id,
                tier=tier,
                call_label=call_label,
                outcome="success",
                timeout_seconds=config.timeout_s,
                elapsed_ms=(time.monotonic() - started) * 1000,
            ))
            report = self._build_report(
                provider=provider,
                model_id=model_id,
                tier=tier,
                call_label=call_label,
                timeout_seconds=config.timeout_s,
                attempts=attempts,
                final_outcome="success",
            )
            self._emit_report(report, report_callback)
            return response

    @staticmethod
    def _call_with_timeout(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        return fn()

    @staticmethod
    def _check_schema(response: dict[str, Any]) -> str | None:
        if not isinstance(response, dict):
            return f"Expected dict, got {type(response).__name__}"
        if "text" not in response:
            return f"Missing 'text' key. Keys present: {sorted(response.keys())}"
        if not isinstance(response["text"], str):
            return f"'text' must be str, got {type(response['text']).__name__}"
        return None

    @staticmethod
    def _check_quality(response: dict[str, Any]) -> str | None:
        text = response.get("text", "")
        if not text.strip():
            return "Empty response text from model."
        output_tokens = response.get("output_tokens", -1)
        if output_tokens == 0:
            return "Model reported 0 output tokens."
        return None

    @classmethod
    def _categorize_exception(cls, exc: Exception) -> str:
        if isinstance(exc, InferenceTransportError) and exc.last_error is not None:
            return cls._categorize_exception(exc.last_error)
        direct = getattr(exc, "failure_category", "")
        if direct in {
            FAILURE_TIMEOUT,
            FAILURE_RATE_LIMIT,
            FAILURE_SERVER_ERROR,
            FAILURE_TRANSPORT,
            FAILURE_SCHEMA,
            FAILURE_QUALITY,
        }:
            return direct
        if isinstance(exc, TimeoutError):
            return FAILURE_TIMEOUT
        if isinstance(exc, InferenceSchemaError):
            return FAILURE_SCHEMA
        if isinstance(exc, InferenceQualityError):
            return FAILURE_QUALITY

        message = str(exc).lower()
        if "timeout" in message or "timed out" in message:
            return FAILURE_TIMEOUT
        if "429" in message or "rate limit" in message or "rate_limit" in message or "too many requests" in message:
            return FAILURE_RATE_LIMIT
        if "5xx" in message or "500" in message or "502" in message or "503" in message or "504" in message:
            return FAILURE_SERVER_ERROR
        if "server" in message or "internal" in message or "unavailable" in message:
            return FAILURE_SERVER_ERROR
        if "connection" in message or "connect" in message or "socket" in message or "dns" in message:
            return FAILURE_TRANSPORT
        return FAILURE_PROVIDER

    @classmethod
    def _backoff(cls, exc: Exception, attempt: int, config: RetryConfig) -> float:
        category = cls._categorize_exception(exc)
        message = str(exc).lower()
        if category == FAILURE_RATE_LIMIT:
            match = re.search(r"retry[-_. ]?after[:=\s]+(\d+(?:\.\d+)?)", message)
            if match:
                return min(float(match.group(1)), config.max_backoff_s)
            return min(config.base_backoff_s * (2 ** max(attempt, 0)), config.max_backoff_s)
        if category == FAILURE_SERVER_ERROR:
            return config.base_backoff_s
        return 0.0

    @classmethod
    def _attempt_record(
        cls,
        *,
        attempt_index: int,
        attempt_kind: str,
        provider: str,
        model_id: str,
        tier: str,
        call_label: str,
        outcome: str,
        timeout_seconds: float,
        failure_category: str = "",
        error_type: str = "",
        error_message: str = "",
        retry_scheduled: bool = False,
        backoff_seconds: float = 0.0,
        elapsed_ms: float = 0.0,
    ) -> RetryAttemptRecord:
        return RetryAttemptRecord(
            attempt_index=attempt_index,
            attempt_kind=attempt_kind,
            provider=provider,
            model_id=model_id,
            tier=tier,
            call_label=call_label,
            outcome=outcome,
            failure_category=failure_category,
            error_type=error_type,
            error_message=error_message,
            retry_scheduled=retry_scheduled,
            backoff_seconds=round(backoff_seconds, 6),
            timeout_seconds=round(timeout_seconds, 6),
            rate_limited=failure_category == FAILURE_RATE_LIMIT,
            elapsed_ms=round(elapsed_ms, 3),
        )

    @classmethod
    def _build_report(
        cls,
        *,
        provider: str,
        model_id: str,
        tier: str,
        call_label: str,
        timeout_seconds: float,
        attempts: list[RetryAttemptRecord],
        final_outcome: str,
        final_failure_category: str = "",
        final_error_type: str = "",
        final_error_message: str = "",
    ) -> RetryExecutionReport:
        retry_count = sum(1 for attempt in attempts if attempt.retry_scheduled)
        total_backoff = sum(attempt.backoff_seconds for attempt in attempts)
        rate_limited = any(attempt.rate_limited for attempt in attempts)
        user_error = (
            cls.user_error_payload(
                provider=provider,
                model_id=model_id,
                call_label=call_label,
                failure_category=final_failure_category,
                attempt_count=len(attempts),
                timeout_seconds=timeout_seconds,
                rate_limited=rate_limited,
            )
            if final_outcome != "success"
            else {}
        )
        return RetryExecutionReport(
            provider=provider,
            model_id=model_id,
            tier=tier,
            call_label=call_label,
            timeout_seconds=round(timeout_seconds, 6),
            attempt_count=len(attempts),
            retry_count=retry_count,
            rate_limited=rate_limited,
            total_backoff_seconds=round(total_backoff, 6),
            final_outcome=final_outcome,
            final_failure_category=final_failure_category,
            final_error_type=final_error_type,
            final_error_message=final_error_message,
            user_error=user_error,
            attempts=list(attempts),
        )

    @staticmethod
    def _stable_error_message(exc: Exception) -> str:
        text = str(exc).strip() or exc.__class__.__name__
        return text[:300]

    @staticmethod
    def _emit_report(report: RetryExecutionReport, callback: ReportCallback | None) -> None:
        if callback is None:
            return
        try:
            callback(report.to_dict())
        except Exception:
            pass

    def _sleep_if_needed(self, wait: float) -> None:
        if wait > 0:
            self._sleep(wait)

    @staticmethod
    def user_error_payload(
        *,
        provider: str,
        model_id: str,
        call_label: str,
        failure_category: str,
        attempt_count: int,
        timeout_seconds: float,
        rate_limited: bool = False,
    ) -> dict[str, Any]:
        codes = {
            FAILURE_TIMEOUT: "PROVIDER_TIMEOUT",
            FAILURE_RATE_LIMIT: "PROVIDER_RATE_LIMIT",
            FAILURE_SERVER_ERROR: "PROVIDER_SERVER_ERROR",
            FAILURE_SCHEMA: "PROVIDER_RESPONSE_SCHEMA",
            FAILURE_QUALITY: "PROVIDER_EMPTY_RESPONSE",
            FAILURE_TRANSPORT: "PROVIDER_TRANSPORT_ERROR",
            FAILURE_PROVIDER: "PROVIDER_CALL_FAILED",
        }
        messages = {
            FAILURE_TIMEOUT: "Provider call timed out before completion.",
            FAILURE_RATE_LIMIT: "Provider rate limit blocked the request after retry policy was exhausted.",
            FAILURE_SERVER_ERROR: "Provider server error persisted after retry policy was exhausted.",
            FAILURE_SCHEMA: "Provider returned a malformed response that XACE could not use.",
            FAILURE_QUALITY: "Provider returned an empty response that XACE could not use.",
            FAILURE_TRANSPORT: "Provider transport failed after retry policy was exhausted.",
            FAILURE_PROVIDER: "Provider call failed after retry policy was exhausted.",
        }
        actions = {
            FAILURE_TIMEOUT: "Check provider connectivity or choose a faster model, then retry.",
            FAILURE_RATE_LIMIT: "Wait for quota to recover or choose another ready provider, then retry.",
            FAILURE_SERVER_ERROR: "Retry later or switch to another ready provider.",
            FAILURE_SCHEMA: "Retry with the same provider or choose another ready provider if this repeats.",
            FAILURE_QUALITY: "Retry with a clearer prompt or choose another ready provider if this repeats.",
            FAILURE_TRANSPORT: "Check provider connectivity or choose another ready provider, then retry.",
            FAILURE_PROVIDER: "Inspect provider readiness and retry with a ready provider.",
        }
        category = failure_category if failure_category in codes else FAILURE_PROVIDER
        return {
            "schema": USER_ERROR_SCHEMA,
            "code": codes[category],
            "message": messages[category],
            "action": actions[category],
            "provider": provider,
            "model_id": model_id,
            "call_label": call_label,
            "failure_category": category,
            "attempt_count": attempt_count,
            "timeout_seconds": round(timeout_seconds, 6),
            "rate_limited": bool(rate_limited or category == FAILURE_RATE_LIMIT),
        }

    def get_config(self, tier: str) -> RetryConfig:
        return self._configs.get(tier, _TIER_CONFIGS["TIER_L"])

    def set_config(self, tier: str, config: RetryConfig) -> None:
        with self._lock:
            self._configs[tier] = config

    def __repr__(self) -> str:
        tiers = sorted(self._configs.keys())
        return f"InferenceRetryPolicy(tiers={tiers})"
