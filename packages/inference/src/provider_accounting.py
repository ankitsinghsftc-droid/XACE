"""
Provider token and cost accounting artifact helpers.

This module turns inference telemetry into a deterministic export ABI for
prompt benchmarks, certification checks, support bundles, and launch reports.
It does not dispatch providers; it only normalizes already-emitted telemetry.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .telemetry_pipeline import redact_value


ACCOUNTING_EVENT_SCHEMA = "xace.provider_accounting_event.v1"
ACCOUNTING_SUMMARY_SCHEMA = "xace.provider_accounting_summary.v1"
ACCOUNTING_MARKDOWN_TITLE = "Provider Token And Cost Accounting"


def accounting_event_from_telemetry(
    event: Any,
    *,
    benchmark_id: str = "",
    source: str = "",
) -> dict[str, Any]:
    """Returns one redacted accounting row from a telemetry event or dict."""

    raw = _event_to_dict(event)
    input_tokens = _int(raw.get("input_tokens", raw.get("prompt_tokens", 0)))
    output_tokens = _int(raw.get("output_tokens", raw.get("completion_tokens", 0)))
    cache_read_tokens = _int(raw.get("cache_read_tokens", 0))
    cache_write_tokens = _int(raw.get("cache_write_tokens", 0))
    cost_cents = _float(raw.get("cost_cents", 0.0))
    latency_ms = _float(raw.get("latency_ms", 0.0))
    model_id = str(raw.get("model_id") or raw.get("model") or "")
    tier = str(raw.get("complexity_tier") or raw.get("tier") or "")
    request_id = str(raw.get("request_id") or "")
    call_label = str(raw.get("call_label") or "")
    provider = str(raw.get("provider") or "")
    retry_report = raw.get("retry_report") if isinstance(raw.get("retry_report"), dict) else {}

    row = {
        "schema": ACCOUNTING_EVENT_SCHEMA,
        "benchmark_id": benchmark_id,
        "source": source,
        "request_id": request_id,
        "session_id": str(raw.get("session_id") or ""),
        "call_label": call_label,
        "provider": provider,
        "model_id": model_id,
        "model": model_id,
        "complexity_tier": tier,
        "tier": tier,
        "prompt_tokens": input_tokens,
        "completion_tokens": output_tokens,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "effective_input_tokens": input_tokens + cache_read_tokens,
        "total_tokens": input_tokens + output_tokens,
        "total_billed_tokens": input_tokens + output_tokens + cache_read_tokens + cache_write_tokens,
        "cost_cents": round(cost_cents, 8),
        "cost_usd": round(cost_cents / 100.0, 10),
        "latency_ms": round(latency_ms, 3),
        "outcome": str(raw.get("outcome") or ""),
        "cached": bool(raw.get("cached")),
        "provider_kind": str(raw.get("provider_kind") or _provider_kind(provider, bool(raw.get("cached")))),
        "attempt_count": _int(raw.get("attempt_count", 0)),
        "retry_count": _int(raw.get("retry_count", 0)),
        "timeout_seconds": round(_float(raw.get("timeout_seconds", 0.0)), 6),
        "rate_limited": bool(raw.get("rate_limited")),
        "backoff_seconds": round(_float(raw.get("backoff_seconds", 0.0)), 6),
        "failure_category": str(raw.get("failure_category") or ""),
        "user_error_code": str(raw.get("user_error_code") or ""),
        "retry_report_schema": str(retry_report.get("schema") or ""),
        "timestamp": _float(raw.get("timestamp", 0.0)),
        "redacted": True,
    }
    return redact_value(row)


def accounting_summary(
    events: Iterable[Any],
    *,
    benchmark_id: str = "",
    source: str = "",
    generated_at_utc: str | None = None,
    notes: list[str] | None = None,
    benchmark_case_count: int = 0,
) -> dict[str, Any]:
    """Returns a redacted aggregate summary for accounting rows."""

    rows = [
        _canonical_event(event, benchmark_id=benchmark_id, source=source)
        for event in events
    ]
    latencies = [float(row["latency_ms"]) for row in rows]
    request_ids = [str(row.get("request_id") or "") for row in rows]
    missing_request_ids = sum(1 for request_id in request_ids if not request_id)
    live_provider_calls = sum(1 for row in rows if _is_live_provider_row(row))
    summary = {
        "schema": ACCOUNTING_SUMMARY_SCHEMA,
        "benchmark_id": benchmark_id,
        "source": source,
        "generated_at_utc": generated_at_utc or _utc_now(),
        "redacted": True,
        "benchmark_case_count": int(benchmark_case_count),
        "event_count": len(rows),
        "provider_call_count": live_provider_calls,
        "cache_event_count": sum(1 for row in rows if bool(row.get("cached"))),
        "deterministic_event_count": sum(1 for row in rows if row.get("provider_kind") == "deterministic"),
        "request_id_count": len(request_ids) - missing_request_ids,
        "unique_request_id_count": len({request_id for request_id in request_ids if request_id}),
        "missing_request_id_count": missing_request_ids,
        "total_prompt_tokens": sum(int(row["prompt_tokens"]) for row in rows),
        "total_completion_tokens": sum(int(row["completion_tokens"]) for row in rows),
        "total_cache_read_tokens": sum(int(row["cache_read_tokens"]) for row in rows),
        "total_cache_write_tokens": sum(int(row["cache_write_tokens"]) for row in rows),
        "total_effective_input_tokens": sum(int(row["effective_input_tokens"]) for row in rows),
        "total_tokens": sum(int(row["total_tokens"]) for row in rows),
        "total_billed_tokens": sum(int(row["total_billed_tokens"]) for row in rows),
        "total_cost_cents": round(sum(float(row["cost_cents"]) for row in rows), 8),
        "total_cost_usd": round(sum(float(row["cost_usd"]) for row in rows), 10),
        "latency_ms": {
            "total": round(sum(latencies), 3),
            "avg": round(statistics.fmean(latencies), 3) if latencies else 0.0,
            "p95": round(_percentile(latencies, 95), 3) if latencies else 0.0,
            "max": round(max(latencies), 3) if latencies else 0.0,
        },
        "by_provider": _counts(rows, "provider"),
        "by_model": _counts(rows, "model_id"),
        "by_tier": _counts(rows, "tier"),
        "by_outcome": _counts(rows, "outcome"),
        "by_provider_kind": _counts(rows, "provider_kind"),
        "notes": list(notes or []),
    }
    return redact_value(summary)


def write_accounting_artifacts(
    events: Iterable[Any],
    output_dir: Path | str,
    *,
    benchmark_id: str = "",
    source: str = "",
    generated_at_utc: str | None = None,
    notes: list[str] | None = None,
    benchmark_case_count: int = 0,
) -> dict[str, Any]:
    """Writes redacted provider accounting JSONL, summary JSON, and Markdown."""

    output_path = Path(output_dir).resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    rows = [
        _canonical_event(event, benchmark_id=benchmark_id, source=source)
        for event in events
    ]
    summary = accounting_summary(
        rows,
        benchmark_id=benchmark_id,
        source=source,
        generated_at_utc=generated_at_utc,
        notes=notes,
        benchmark_case_count=benchmark_case_count,
    )

    jsonl_path = output_path / "provider_accounting.jsonl"
    summary_path = output_path / "provider_accounting_summary.json"
    markdown_path = output_path / "provider_accounting.md"
    jsonl_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(_markdown(summary), encoding="utf-8")

    return {
        "schema": "xace.provider_accounting_artifacts.v1",
        "ok": True,
        "artifacts": {
            "provider_accounting_jsonl": str(jsonl_path),
            "provider_accounting_summary_json": str(summary_path),
            "provider_accounting_markdown": str(markdown_path),
        },
        "summary": summary,
    }


def _canonical_event(event: Any, *, benchmark_id: str, source: str) -> dict[str, Any]:
    if isinstance(event, dict) and event.get("schema") == ACCOUNTING_EVENT_SCHEMA:
        row = dict(event)
        if benchmark_id and not row.get("benchmark_id"):
            row["benchmark_id"] = benchmark_id
        if source and not row.get("source"):
            row["source"] = source
        return redact_value(row)
    return accounting_event_from_telemetry(event, benchmark_id=benchmark_id, source=source)


def _event_to_dict(event: Any) -> dict[str, Any]:
    if isinstance(event, dict):
        return dict(event)
    if hasattr(event, "to_dict"):
        value = event.to_dict()
        return dict(value) if isinstance(value, dict) else {}
    if is_dataclass(event) and not isinstance(event, type):
        return asdict(event)
    return {}


def _provider_kind(provider: str, cached: bool) -> str:
    if cached or provider == "response_cache":
        return "cache"
    if provider == "deterministic":
        return "deterministic"
    if provider in {"local", "local-classifier"}:
        return "local"
    return "cloud"


def _is_live_provider_row(row: dict[str, Any]) -> bool:
    provider = str(row.get("provider") or "")
    if provider in {"deterministic", "response_cache", "local-classifier"}:
        return False
    if bool(row.get("cached")):
        return False
    return str(row.get("provider_kind") or "") != "deterministic"


def _counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((percentile / 100) * (len(ordered) - 1)))
    return ordered[max(0, min(index, len(ordered) - 1))]


def _markdown(summary: dict[str, Any]) -> str:
    latency = summary.get("latency_ms") or {}
    lines = [
        f"# {ACCOUNTING_MARKDOWN_TITLE}",
        "",
        f"Schema: `{summary.get('schema', '')}`",
        "",
        f"Generated: `{summary.get('generated_at_utc', '')}`",
        "",
        f"Benchmark: `{summary.get('benchmark_id', '')}`",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Benchmark cases | {int(summary.get('benchmark_case_count') or 0)} |",
        f"| Accounting events | {int(summary.get('event_count') or 0)} |",
        f"| Live provider calls | {int(summary.get('provider_call_count') or 0)} |",
        f"| Prompt tokens | {int(summary.get('total_prompt_tokens') or 0)} |",
        f"| Completion tokens | {int(summary.get('total_completion_tokens') or 0)} |",
        f"| Cache read tokens | {int(summary.get('total_cache_read_tokens') or 0)} |",
        f"| Cache write tokens | {int(summary.get('total_cache_write_tokens') or 0)} |",
        f"| Total billed tokens | {int(summary.get('total_billed_tokens') or 0)} |",
        f"| Cost USD | {float(summary.get('total_cost_usd') or 0.0):.6f} |",
        f"| Latency avg ms | {float(latency.get('avg') or 0.0):.3f} |",
        f"| Latency p95 ms | {float(latency.get('p95') or 0.0):.3f} |",
        f"| Missing request IDs | {int(summary.get('missing_request_id_count') or 0)} |",
        "",
    ]
    notes = summary.get("notes") or []
    if notes:
        lines.extend(["## Notes", ""])
        lines.extend(f"- {note}" for note in notes)
        lines.append("")
    return "\n".join(lines)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
