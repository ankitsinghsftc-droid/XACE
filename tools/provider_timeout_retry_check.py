"""
Validate Task 52 provider timeout, retry, backoff, and telemetry behavior.

The check is deterministic and local-only. It registers a synthetic provider
client with the real InferenceAdapter and exercises timeout, rate-limit,
server, schema, and quality failures without contacting external services.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from packages.inference.src.cache_key_builder import CacheKeyBuilder  # noqa: E402
from packages.inference.src.inference_adapter import InferenceAdapter, InferenceRequest, PromptPart  # noqa: E402
from packages.inference.src.inference_budget import InferenceBudget  # noqa: E402
from packages.inference.src.inference_retry_policy import (  # noqa: E402
    FAILURE_QUALITY,
    FAILURE_RATE_LIMIT,
    FAILURE_SCHEMA,
    FAILURE_SERVER_ERROR,
    FAILURE_TIMEOUT,
    InferenceQualityError,
    InferenceRetryPolicy,
    InferenceSchemaError,
    InferenceTransportError,
    RetryConfig,
)
from packages.inference.src.model_descriptor import ComplexityTier, ModelCapability, ModelDescriptor  # noqa: E402
from packages.inference.src.prompt_cache import PromptCache  # noqa: E402
from packages.inference.src.provider_registry import ProviderRegistry  # noqa: E402
from packages.inference.src.response_cache import ResponseCache  # noqa: E402
from packages.inference.src.telemetry_pipeline import InMemoryBackend, TelemetryPipeline  # noqa: E402


REPORT_SCHEMA = "xace.provider_timeout_retry_report.v1"
DEFAULT_OUTPUT = REPO_ROOT / "target-provider-timeout-retry" / "provider_timeout_retry_report.json"
PROVIDER = "synthetic_provider"
LOGICAL_MODEL = "task52_timeout_retry_model"
MODEL_ID = "synthetic-timeout-retry-model"


class SequenceProvider:
    def __init__(self, steps: list[Any]) -> None:
        self._steps = list(steps)
        self.calls = 0

    def complete(
        self,
        model_id: str,
        prompt: dict[str, Any],
        system_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        del model_id, prompt, system_prompt, max_tokens, temperature
        index = min(self.calls, len(self._steps) - 1)
        self.calls += 1
        step = self._steps[index]
        if isinstance(step, BaseException):
            raise step
        return dict(step)

    def health_check(self) -> bool:
        return True

    def provider_name(self) -> str:
        return PROVIDER


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate provider timeout/retry telemetry policy.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="JSON report path.")
    parser.add_argument("--json", action="store_true", help="Print the JSON report.")
    args = parser.parse_args(argv)

    report = run(Path(args.output))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif report["ok"]:
        print(f"provider timeout/retry check PASSED: {report['case_count']} deterministic cases")
    else:
        print("provider timeout/retry check failed:", file=sys.stderr)
        for finding in report["findings"]:
            print(f"- {finding}", file=sys.stderr)
    return 0 if report["ok"] else 1


def run(output: Path) -> dict[str, Any]:
    findings: list[str] = []
    cases = [
        _run_case(
            case_id="timeout_then_success",
            steps=[
                TimeoutError("timed out while waiting for provider response"),
                _success("timeout recovery"),
            ],
            expected_exception=None,
            expected_final_outcome="success",
            expected_category="",
            expected_code="",
            expected_outcome="success",
            expected_attempts=2,
            expected_retries=1,
            expected_rate_limited=False,
            expected_backoff=0.0,
            expected_sleep=[],
            findings=findings,
        ),
        _run_case(
            case_id="rate_limit_exhausted",
            steps=[
                RuntimeError("429 rate limit retry-after: 3"),
                RuntimeError("429 rate limit retry-after: 3"),
            ],
            expected_exception=InferenceTransportError,
            expected_final_outcome="failure",
            expected_category=FAILURE_RATE_LIMIT,
            expected_code="PROVIDER_RATE_LIMIT",
            expected_outcome="transport_error",
            expected_attempts=2,
            expected_retries=1,
            expected_rate_limited=True,
            expected_backoff=3.0,
            expected_sleep=[3.0],
            findings=findings,
        ),
        _run_case(
            case_id="timeout_exhausted",
            steps=[
                TimeoutError("provider timed out"),
                TimeoutError("provider timed out"),
            ],
            expected_exception=InferenceTransportError,
            expected_final_outcome="failure",
            expected_category=FAILURE_TIMEOUT,
            expected_code="PROVIDER_TIMEOUT",
            expected_outcome="transport_error",
            expected_attempts=2,
            expected_retries=1,
            expected_rate_limited=False,
            expected_backoff=0.0,
            expected_sleep=[],
            findings=findings,
        ),
        _run_case(
            case_id="server_error_exhausted",
            steps=[
                RuntimeError("500 internal server error"),
                RuntimeError("500 internal server error"),
            ],
            expected_exception=InferenceTransportError,
            expected_final_outcome="failure",
            expected_category=FAILURE_SERVER_ERROR,
            expected_code="PROVIDER_SERVER_ERROR",
            expected_outcome="transport_error",
            expected_attempts=2,
            expected_retries=1,
            expected_rate_limited=False,
            expected_backoff=2.0,
            expected_sleep=[2.0],
            findings=findings,
        ),
        _run_case(
            case_id="schema_error_exhausted",
            steps=[
                {"input_tokens": 1, "output_tokens": 1},
                {"input_tokens": 1, "output_tokens": 1},
            ],
            expected_exception=InferenceSchemaError,
            expected_final_outcome="failure",
            expected_category=FAILURE_SCHEMA,
            expected_code="PROVIDER_RESPONSE_SCHEMA",
            expected_outcome="schema_error",
            expected_attempts=2,
            expected_retries=1,
            expected_rate_limited=False,
            expected_backoff=0.0,
            expected_sleep=[],
            findings=findings,
        ),
        _run_case(
            case_id="quality_error_exhausted",
            steps=[
                {"text": "", "input_tokens": 1, "output_tokens": 0},
                {"text": "", "input_tokens": 1, "output_tokens": 0},
            ],
            expected_exception=InferenceQualityError,
            expected_final_outcome="failure",
            expected_category=FAILURE_QUALITY,
            expected_code="PROVIDER_EMPTY_RESPONSE",
            expected_outcome="quality_error",
            expected_attempts=2,
            expected_retries=1,
            expected_rate_limited=False,
            expected_backoff=0.0,
            expected_sleep=[],
            findings=findings,
        ),
    ]

    report = {
        "schema": REPORT_SCHEMA,
        "ok": not findings,
        "case_count": len(cases),
        "cases": cases,
        "findings": findings,
    }
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _run_case(
    *,
    case_id: str,
    steps: list[Any],
    expected_exception: type[BaseException] | None,
    expected_final_outcome: str,
    expected_category: str,
    expected_code: str,
    expected_outcome: str,
    expected_attempts: int,
    expected_retries: int,
    expected_rate_limited: bool,
    expected_backoff: float,
    expected_sleep: list[float],
    findings: list[str],
) -> dict[str, Any]:
    sleep_calls: list[float] = []
    provider = SequenceProvider(steps)
    adapter, backend = _build_adapter(provider, sleep_calls)
    caught: BaseException | None = None
    response_text = ""

    try:
        response = adapter.call(_request(case_id))
        response_text = response.text
        if expected_exception is not None:
            findings.append(f"{case_id}: expected {expected_exception.__name__}, call succeeded")
    except BaseException as exc:
        caught = exc
        if expected_exception is None:
            findings.append(f"{case_id}: unexpected exception {exc.__class__.__name__}: {exc}")
        elif not isinstance(exc, expected_exception):
            findings.append(f"{case_id}: expected {expected_exception.__name__}, got {exc.__class__.__name__}")

    events = backend.all_events()
    if len(events) != 1:
        findings.append(f"{case_id}: expected exactly one telemetry event, got {len(events)}")
        event = None
        report: dict[str, Any] = getattr(caught, "retry_report", None) or {}
    else:
        event = events[0]
        report = event.retry_report or getattr(caught, "retry_report", None) or {}

    _expect(case_id, "provider calls", provider.calls, expected_attempts, findings)
    _expect(case_id, "sleep calls", sleep_calls, expected_sleep, findings)

    if event is not None:
        _expect(case_id, "telemetry outcome", event.outcome, expected_outcome, findings)
        _expect(case_id, "telemetry attempt_count", event.attempt_count, expected_attempts, findings)
        _expect(case_id, "telemetry retry_count", event.retry_count, expected_retries, findings)
        _expect(case_id, "telemetry rate_limited", event.rate_limited, expected_rate_limited, findings)
        _expect(case_id, "telemetry backoff_seconds", round(event.backoff_seconds, 6), expected_backoff, findings)
        _expect(case_id, "telemetry timeout_seconds", event.timeout_seconds, 17.5, findings)
        if expected_category:
            _expect(case_id, "telemetry failure_category", event.failure_category, expected_category, findings)
            _expect(case_id, "telemetry user_error_code", event.user_error_code, expected_code, findings)

    if report:
        _expect(case_id, "report schema", report.get("schema"), "xace.inference_retry_summary.v1", findings)
        _expect(case_id, "report final_outcome", report.get("final_outcome"), expected_final_outcome, findings)
        _expect(case_id, "report attempt_count", report.get("attempt_count"), expected_attempts, findings)
        _expect(case_id, "report retry_count", report.get("retry_count"), expected_retries, findings)
        _expect(case_id, "report rate_limited", report.get("rate_limited"), expected_rate_limited, findings)
        _expect(case_id, "report timeout_seconds", report.get("timeout_seconds"), 17.5, findings)
        _expect(case_id, "report total_backoff_seconds", report.get("total_backoff_seconds"), expected_backoff, findings)
        _expect(case_id, "report final_failure_category", report.get("final_failure_category", ""), expected_category, findings)
        attempts = report.get("attempts") or []
        _expect(case_id, "report attempts length", len(attempts), expected_attempts, findings)
        if expected_code:
            user_error = report.get("user_error") or {}
            _expect(case_id, "user error schema", user_error.get("schema"), "xace.provider_call_error.v1", findings)
            _expect(case_id, "user error code", user_error.get("code"), expected_code, findings)
            _expect(case_id, "user error category", user_error.get("failure_category"), expected_category, findings)
            _expect(case_id, "user error attempts", user_error.get("attempt_count"), expected_attempts, findings)
    else:
        findings.append(f"{case_id}: missing retry report")

    return {
        "case_id": case_id,
        "ok": not any(finding.startswith(f"{case_id}:") for finding in findings),
        "provider_calls": provider.calls,
        "sleep_calls": sleep_calls,
        "response_text": response_text,
        "exception": caught.__class__.__name__ if caught else "",
        "telemetry": event.to_dict() if event is not None else {},
        "retry_report": report,
    }


def _build_adapter(
    provider: SequenceProvider,
    sleep_calls: list[float],
) -> tuple[InferenceAdapter, InMemoryBackend]:
    descriptor = ModelDescriptor(
        logical_name=LOGICAL_MODEL,
        provider=PROVIDER,
        model_id=MODEL_ID,
        context_window_tokens=4096,
        max_output_tokens=256,
        input_price_per_1k=0.001,
        output_price_per_1k=0.002,
        cache_write_price_per_1k=0.0,
        cache_read_price_per_1k=0.0,
        supports_cache_control=False,
        default_tier=ComplexityTier.L,
        capabilities=frozenset({ModelCapability.GENERATION}),
        notes="Task 52 deterministic provider retry certification model.",
    )
    registry = ProviderRegistry(clients={PROVIDER: provider})
    registry.register_descriptor(descriptor)
    telemetry = TelemetryPipeline()
    backend = InMemoryBackend()
    telemetry.add_backend(backend)
    retry = InferenceRetryPolicy(
        config_overrides={
            ComplexityTier.L: RetryConfig(
                transport_retries=1,
                schema_retries=1,
                quality_retries=1,
                base_backoff_s=2.0,
                max_backoff_s=10.0,
                timeout_s=17.5,
            )
        },
        sleep_fn=sleep_calls.append,
    )
    return (
        InferenceAdapter(
            provider_registry=registry,
            telemetry=telemetry,
            budget=InferenceBudget(),
            retry_policy=retry,
            prompt_cache=PromptCache(),
            response_cache=ResponseCache(),
            cache_key_builder=CacheKeyBuilder(),
        ),
        backend,
    )


def _request(case_id: str) -> InferenceRequest:
    return InferenceRequest(
        prompt_parts=[PromptPart(text=f"Task 52 provider retry case {case_id}")],
        system_prompt="Return a concise deterministic response.",
        logical_model=LOGICAL_MODEL,
        complexity_tier=ComplexityTier.L,
        max_tokens=64,
        temperature=0.0,
        session_id=f"task52-{case_id}",
        call_label=case_id,
        bypass_response_cache=True,
    )


def _success(text: str) -> dict[str, Any]:
    return {
        "text": text,
        "input_tokens": 11,
        "output_tokens": 7,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }


def _expect(case_id: str, field: str, actual: Any, expected: Any, findings: list[str]) -> None:
    if actual != expected:
        findings.append(f"{case_id}: {field} expected {expected!r}, got {actual!r}")


if __name__ == "__main__":
    raise SystemExit(main())
