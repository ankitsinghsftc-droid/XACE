"""
Validate Task 53 provider token, cache, cost, latency, and request accounting.

The check is deterministic and local-only. It registers a synthetic provider
with the real InferenceAdapter, exports redacted accounting artifacts, and
verifies that success, cache, deterministic, and failure call paths keep the
required accounting ABI.
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
from packages.inference.src.inference_retry_policy import InferenceRetryPolicy, RetryConfig  # noqa: E402
from packages.inference.src.model_descriptor import ComplexityTier, ModelCapability, ModelDescriptor  # noqa: E402
from packages.inference.src.prompt_cache import PromptCache  # noqa: E402
from packages.inference.src.provider_accounting import (  # noqa: E402
    ACCOUNTING_EVENT_SCHEMA,
    ACCOUNTING_SUMMARY_SCHEMA,
    write_accounting_artifacts,
)
from packages.inference.src.provider_registry import ProviderRegistry  # noqa: E402
from packages.inference.src.response_cache import ResponseCache  # noqa: E402
from packages.inference.src.telemetry_pipeline import FileBackend, InMemoryBackend, TelemetryPipeline  # noqa: E402


REPORT_SCHEMA = "xace.provider_token_cost_accounting_report.v1"
DEFAULT_OUTPUT = REPO_ROOT / "target-provider-token-cost-accounting" / "provider_token_cost_accounting_report.json"
PROVIDER = "synthetic_accounting_provider"
LOGICAL_MODEL = "task53_accounting_model"
MODEL_ID = "synthetic-accounting-model"
EXPECTED_COST_CENTS = 0.152


class AccountingProvider:
    def __init__(self) -> None:
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
        self.calls += 1
        return {
            "text": "accounting success",
            "input_tokens": 100,
            "output_tokens": 25,
            "cache_read_tokens": 10,
            "cache_write_tokens": 5,
        }

    def health_check(self) -> bool:
        return True

    def provider_name(self) -> str:
        return PROVIDER


class FailingProvider:
    def __init__(self) -> None:
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
        self.calls += 1
        raise TimeoutError("provider timed out before accounting proof completed")

    def health_check(self) -> bool:
        return True

    def provider_name(self) -> str:
        return PROVIDER


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate provider token and cost accounting artifacts.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="JSON report path.")
    parser.add_argument("--json", action="store_true", help="Print the JSON report.")
    args = parser.parse_args(argv)

    report = run(Path(args.output))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif report["ok"]:
        print(f"provider token/cost accounting check PASSED: {report['case_count']} deterministic cases")
    else:
        print("provider token/cost accounting check failed:", file=sys.stderr)
        for finding in report["findings"]:
            print(f"- {finding}", file=sys.stderr)
    return 0 if report["ok"] else 1


def run(output: Path) -> dict[str, Any]:
    findings: list[str] = []
    output = output.resolve()
    artifact_dir = output.parent / "artifacts"
    telemetry_path = artifact_dir / "raw_inference_telemetry.jsonl"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    if telemetry_path.exists():
        telemetry_path.unlink()

    live_provider = AccountingProvider()
    adapter, backend = _build_adapter(live_provider, telemetry_path)
    marker = "sk-" + "task53secretvalue"

    live_request = _request(
        request_id="task53-live-request",
        session_id="task53-live-session",
        call_label=f"live_accounting {marker}",
        bypass_response_cache=False,
        cgs_structural_hash="a" * 64,
    )
    live_response = adapter.call(live_request)
    cache_request = _request(
        request_id="task53-cache-request",
        session_id="task53-live-session",
        call_label=f"cache_accounting {marker}",
        bypass_response_cache=False,
        cgs_structural_hash="a" * 64,
    )
    cache_response = adapter.call(cache_request)
    deterministic_response = adapter.call(InferenceRequest(
        prompt_parts=[PromptPart(text="Task 53 deterministic accounting path")],
        logical_model=LOGICAL_MODEL,
        complexity_tier=ComplexityTier.S,
        session_id="task53-deterministic-session",
        call_label=f"deterministic_accounting {marker}",
        request_id="task53-deterministic-request",
    ))

    failing_provider = FailingProvider()
    failing_adapter, failing_backend = _build_adapter(failing_provider, telemetry_path)
    failure_exception = ""
    try:
        failing_adapter.call(_request(
            request_id="task53-failure-request",
            session_id="task53-failure-session",
            call_label=f"failure_accounting {marker}",
            bypass_response_cache=True,
            cgs_structural_hash="",
        ))
    except BaseException as exc:
        failure_exception = exc.__class__.__name__
    else:
        findings.append("failure path: expected provider timeout exception, call succeeded")

    events = backend.all_events() + failing_backend.all_events()
    accounting = write_accounting_artifacts(
        events,
        artifact_dir,
        benchmark_id="task53-provider-token-cost-accounting",
        source="provider_token_cost_accounting_check",
        benchmark_case_count=4,
        notes=[
            "Deterministic local proof using real InferenceAdapter telemetry.",
            "Provider credential-shaped labels are redacted before artifact write.",
        ],
    )
    rows = _read_jsonl(Path(accounting["artifacts"]["provider_accounting_jsonl"]))
    summary = accounting["summary"]

    _expect("live provider calls", live_provider.calls, 1, findings)
    _expect("failing provider calls", failing_provider.calls, 2, findings)
    _expect("event count", len(events), 4, findings)
    _expect("accounting event count", len(rows), 4, findings)
    _expect("summary schema", summary.get("schema"), ACCOUNTING_SUMMARY_SCHEMA, findings)
    _expect("summary provider_call_count", summary.get("provider_call_count"), 2, findings)
    _expect("summary prompt tokens", summary.get("total_prompt_tokens"), 100, findings)
    _expect("summary completion tokens", summary.get("total_completion_tokens"), 25, findings)
    _expect("summary cache read tokens", summary.get("total_cache_read_tokens"), 10, findings)
    _expect("summary cache write tokens", summary.get("total_cache_write_tokens"), 5, findings)
    _expect("summary missing request ids", summary.get("missing_request_id_count"), 0, findings)
    _expect("summary unique request ids", summary.get("unique_request_id_count"), 4, findings)
    _expect("live response cost", round(live_response.cost_cents, 6), round(EXPECTED_COST_CENTS, 6), findings)
    _expect("cache response cost", cache_response.cost_cents, 0.0, findings)
    _expect("deterministic response cost", deterministic_response.cost_cents, 0.0, findings)
    _expect("failure exception", failure_exception, "InferenceTransportError", findings)

    by_request = {str(row.get("request_id")): row for row in rows}
    _validate_row(
        "live",
        by_request.get("task53-live-request") or {},
        {
            "schema": ACCOUNTING_EVENT_SCHEMA,
            "prompt_tokens": 100,
            "completion_tokens": 25,
            "cache_read_tokens": 10,
            "cache_write_tokens": 5,
            "total_tokens": 125,
            "effective_input_tokens": 110,
            "model_id": MODEL_ID,
            "provider": PROVIDER,
            "tier": ComplexityTier.L,
            "outcome": "success",
            "attempt_count": 1,
            "retry_count": 0,
            "cached": False,
        },
        findings,
    )
    _expect(
        "live row cost",
        round(float((by_request.get("task53-live-request") or {}).get("cost_cents") or 0.0), 6),
        round(EXPECTED_COST_CENTS, 6),
        findings,
    )
    _validate_row(
        "cache",
        by_request.get("task53-cache-request") or {},
        {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "model_id": LOGICAL_MODEL,
            "provider": "response_cache",
            "outcome": "cache_hit",
            "cached": True,
        },
        findings,
    )
    _validate_row(
        "deterministic",
        by_request.get("task53-deterministic-request") or {},
        {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "model_id": "phase12_gde",
            "provider": "deterministic",
            "tier": ComplexityTier.S,
            "outcome": "deterministic_shortcut",
            "cached": True,
        },
        findings,
    )
    _validate_row(
        "failure",
        by_request.get("task53-failure-request") or {},
        {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "model_id": MODEL_ID,
            "provider": PROVIDER,
            "tier": ComplexityTier.L,
            "outcome": "transport_error",
            "attempt_count": 2,
            "retry_count": 1,
            "failure_category": "timeout",
            "user_error_code": "PROVIDER_TIMEOUT",
        },
        findings,
    )

    artifact_text = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in [
            telemetry_path,
            Path(accounting["artifacts"]["provider_accounting_jsonl"]),
            Path(accounting["artifacts"]["provider_accounting_summary_json"]),
            Path(accounting["artifacts"]["provider_accounting_markdown"]),
        ]
        if Path(path).exists()
    )
    if marker in artifact_text:
        findings.append("redaction: credential-shaped marker leaked into telemetry/accounting artifacts")
    if "[REDACTED_SECRET]" not in artifact_text:
        findings.append("redaction: expected redacted marker was not present in artifacts")

    report = {
        "schema": REPORT_SCHEMA,
        "ok": not findings,
        "case_count": 4,
        "cases": [
            {
                "case_id": "live_success",
                "request_id": live_response.request_id,
                "cost_cents": live_response.cost_cents,
                "input_tokens": live_response.input_tokens,
                "output_tokens": live_response.output_tokens,
                "cache_read_tokens": live_response.cache_read_tokens,
                "cache_write_tokens": live_response.cache_write_tokens,
            },
            {
                "case_id": "response_cache_hit",
                "request_id": cache_response.request_id,
                "cached": cache_response.cached,
                "provider": cache_response.provider,
            },
            {
                "case_id": "deterministic_shortcut",
                "request_id": deterministic_response.request_id,
                "cached": deterministic_response.cached,
                "provider": deterministic_response.provider,
            },
            {
                "case_id": "provider_failure",
                "exception": failure_exception,
                "provider_calls": failing_provider.calls,
            },
        ],
        "accounting_artifacts": accounting["artifacts"],
        "telemetry_path": str(telemetry_path),
        "summary": summary,
        "findings": findings,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _build_adapter(
    provider: Any,
    telemetry_path: Path,
) -> tuple[InferenceAdapter, InMemoryBackend]:
    descriptor = ModelDescriptor(
        logical_name=LOGICAL_MODEL,
        provider=PROVIDER,
        model_id=MODEL_ID,
        context_window_tokens=4096,
        max_output_tokens=256,
        input_price_per_1k=0.010,
        output_price_per_1k=0.020,
        cache_write_price_per_1k=0.002,
        cache_read_price_per_1k=0.001,
        supports_cache_control=False,
        default_tier=ComplexityTier.L,
        capabilities=frozenset({ModelCapability.GENERATION}),
        notes="Task 53 deterministic provider accounting certification model.",
    )
    registry = ProviderRegistry(clients={PROVIDER: provider})
    registry.register_descriptor(descriptor)
    telemetry = TelemetryPipeline()
    backend = InMemoryBackend()
    telemetry.add_backend(backend)
    telemetry.add_backend(FileBackend(str(telemetry_path)))
    retry = InferenceRetryPolicy(
        config_overrides={
            ComplexityTier.L: RetryConfig(
                transport_retries=1,
                schema_retries=0,
                quality_retries=0,
                base_backoff_s=0.0,
                max_backoff_s=0.0,
                timeout_s=12.5,
            )
        },
        sleep_fn=lambda _seconds: None,
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


def _request(
    *,
    request_id: str,
    session_id: str,
    call_label: str,
    bypass_response_cache: bool,
    cgs_structural_hash: str,
) -> InferenceRequest:
    return InferenceRequest(
        prompt_parts=[PromptPart(text="Task 53 provider accounting prompt", cacheable=True)],
        system_prompt="Return a concise deterministic response.",
        logical_model=LOGICAL_MODEL,
        complexity_tier=ComplexityTier.L,
        max_tokens=64,
        temperature=0.0,
        session_id=session_id,
        call_label=call_label,
        request_id=request_id,
        cgs_structural_hash=cgs_structural_hash,
        intent_class="SetValue",
        bypass_response_cache=bypass_response_cache,
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            rows.append(value if isinstance(value, dict) else {})
    return rows


def _validate_row(
    case_id: str,
    row: dict[str, Any],
    expected: dict[str, Any],
    findings: list[str],
) -> None:
    if not row:
        findings.append(f"{case_id}: missing accounting row")
        return
    for key, value in expected.items():
        _expect(f"{case_id} row {key}", row.get(key), value, findings)
    if not row.get("request_id"):
        findings.append(f"{case_id}: missing request_id")
    if not row.get("model_id"):
        findings.append(f"{case_id}: missing model_id")
    if not row.get("tier"):
        findings.append(f"{case_id}: missing tier")
    if float(row.get("latency_ms") or 0.0) < 0.0:
        findings.append(f"{case_id}: latency_ms must be non-negative")


def _expect(label: str, actual: Any, expected: Any, findings: list[str]) -> None:
    if actual != expected:
        findings.append(f"{label}: expected {expected!r}, got {actual!r}")


if __name__ == "__main__":
    raise SystemExit(main())
