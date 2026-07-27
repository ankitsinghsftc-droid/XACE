"""
Validate Task 58 deterministic no-LLM routing for certified simple edits.

The benchmark exercises certified value-edit prompts through
SessionManager.run_pil() with provider readiness and PIL execution replaced by
sentinels. A passing report proves the simple edit route produced normal GDE
mutation previews without entering provider readiness, PIL, or hosted-provider
execution.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = REPO_ROOT / "packages" / "builder-workspace" / "server"
PROJECT_SYSTEM_DIR = REPO_ROOT / "packages" / "project-system"
for path in (REPO_ROOT, SERVER_DIR, PROJECT_SYSTEM_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from packages.inference.src.provider_accounting import write_accounting_artifacts  # noqa: E402
from project_templates import make_template  # noqa: E402
from session_manager import (  # noqa: E402
    DETERMINISTIC_SIMPLE_EDIT_MODEL,
    DETERMINISTIC_SIMPLE_EDIT_SCHEMA,
    SessionManager,
)


REPORT_SCHEMA = "xace.deterministic_simple_edit_benchmark.v1"
CASE_SCHEMA = "xace.deterministic_simple_edit_benchmark_case.v1"
DEFAULT_OUTPUT = REPO_ROOT / "target-deterministic-simple-edit-benchmark"
DEFAULT_PROMPTS = (
    ("set_player_speed_decimal", "Set the player movement speed to 6.5.", 6.5),
    ("change_player_speed_integer", "Change player speed to 4.", 4.0),
    ("update_player_speed_decimal", "Update the player speed to 7.25.", 7.25),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Task 58 deterministic simple-edit benchmark.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Directory for JSON/JSONL/Markdown reports.")
    parser.add_argument("--json", action="store_true", help="Print compact JSON completion output.")
    args = parser.parse_args(argv)

    try:
        report = run_benchmark(Path(args.output))
    except BenchmarkError as exc:
        if args.json:
            print(json.dumps({"schema": REPORT_SCHEMA, "ok": False, "error": str(exc)}, indent=2, sort_keys=True))
        else:
            print(f"deterministic simple edit benchmark failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({
            "schema": REPORT_SCHEMA,
            "ok": report["ok"],
            "summary_path": report["artifacts"]["summary_json"],
            "results_jsonl_path": report["artifacts"]["results_jsonl"],
            "provider_calls": report["summary"]["provider_calls"],
            "pil_calls": report["summary"]["pil_calls"],
            "provider_readiness_calls": report["summary"]["provider_readiness_calls"],
        }, indent=2, sort_keys=True))
    else:
        print("deterministic simple edit benchmark PASSED")
        print(f"summary: {report['artifacts']['summary_json']}")
        print(f"results: {report['artifacts']['results_jsonl']}")
        print(f"provider_calls: {report['summary']['provider_calls']}")
        print(f"pil_calls: {report['summary']['pil_calls']}")
    return 0 if report["ok"] else 2


def run_benchmark(output_dir: Path) -> dict[str, Any]:
    output = output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    previous_settings_path = os.environ.get("XACE_PROVIDER_SETTINGS_PATH")
    provider_tmp = tempfile.TemporaryDirectory(prefix="xace-task58-provider-")
    os.environ["XACE_PROVIDER_SETTINGS_PATH"] = str(Path(provider_tmp.name) / "provider_settings.json")

    try:
        sm = SessionManager()
        cgs = make_template("blank_3d", "Task 58 Deterministic Simple Edit Benchmark")
        cgs_hash = str(cgs["metadata"]["cgs_hash"])
        pipeline = _PILSentinel()
        readiness = _ProviderReadinessSentinel()
        session = _session(pipeline)
        sm._sessions["benchmark_session_58"] = session
        sm.provider_readiness = readiness  # type: ignore[method-assign]

        results: list[dict[str, Any]] = []
        for case_id, prompt, expected_value in DEFAULT_PROMPTS:
            started = time.perf_counter()
            result = asyncio.run(sm.run_pil("benchmark_session_58", prompt, cgs, cgs_hash))
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            results.append(_case_result(case_id, prompt, expected_value, result, elapsed_ms))
            sm.clear_pending("benchmark_session_58")

        report = _build_report(
            output=output,
            results=results,
            pipeline_calls=pipeline.calls,
            provider_readiness_calls=readiness.calls,
        )
        _write_artifacts(report, output)
        if not report["ok"]:
            raise BenchmarkError("; ".join(report["findings"]))
        return report
    finally:
        if previous_settings_path is None:
            os.environ.pop("XACE_PROVIDER_SETTINGS_PATH", None)
        else:
            os.environ["XACE_PROVIDER_SETTINGS_PATH"] = previous_settings_path
        provider_tmp.cleanup()


class BenchmarkError(RuntimeError):
    pass


class _PILSentinel:
    def __init__(self) -> None:
        self.calls = 0

    def process(self, prompt: str, cgs: dict, cgs_hash: str, mode: str = "COLLABORATIVE") -> Any:
        del prompt, cgs, cgs_hash, mode
        self.calls += 1
        raise AssertionError("PIL must not execute for deterministic simple edits.")


class _ProviderReadinessSentinel:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> dict[str, Any]:
        self.calls += 1
        raise AssertionError("Provider readiness must not execute for deterministic simple edits.")


def _session(pipeline: _PILSentinel) -> SimpleNamespace:
    return SimpleNamespace(
        session_id="benchmark_session_58",
        pipeline=pipeline,
        gde=None,
        current_mode="COLLABORATIVE",
        pending_txn=None,
        pending_clar_id=None,
        pending_prompt_clarification=None,
        prompt_clarification_log=[],
        pending_prompt_preview=None,
        pending_prompt_result=None,
        prompt_preview_approval_log=[],
        runtime_connected=False,
        runtime_adapter_type="",
        runtime_engine_version="",
        runtime_last_tick=None,
        runtime_last_hash="",
        engine_edit_log=[],
        touch=lambda: None,
    )


def _case_result(
    case_id: str,
    prompt: str,
    expected_value: float,
    result: dict[str, Any],
    elapsed_ms: float,
) -> dict[str, Any]:
    txn = result.get("transaction") if isinstance(result.get("transaction"), dict) else {}
    operations = txn.get("operations") if isinstance(txn.get("operations"), list) else []
    first_op = operations[0] if operations and isinstance(operations[0], dict) else {}
    shortcut = result.get("deterministic_simple_edit") if isinstance(result.get("deterministic_simple_edit"), dict) else {}
    preview = result.get("preview") if isinstance(result.get("preview"), dict) else {}
    cost_diff = preview.get("cost_diff") if isinstance(preview.get("cost_diff"), dict) else {}
    provider_calls = int(shortcut.get("provider_calls") or 0)
    pil_calls = int(shortcut.get("pil_calls") or 0)
    llm_calls = int(shortcut.get("llm_calls") or 0)
    actual_value = float(first_op.get("value")) if isinstance(first_op.get("value"), (int, float)) else None
    ok = (
        result.get("kind") == "mutation"
        and result.get("approval_required") is True
        and result.get("provider") == "deterministic"
        and result.get("model") == DETERMINISTIC_SIMPLE_EDIT_MODEL
        and shortcut.get("schema") == DETERMINISTIC_SIMPLE_EDIT_SCHEMA
        and provider_calls == 0
        and pil_calls == 0
        and llm_calls == 0
        and actual_value == expected_value
        and int(result.get("tokens") or 0) == 0
        and float(result.get("cost_cents") or 0.0) == 0.0
        and cost_diff.get("provider") == "deterministic"
        and cost_diff.get("source") == "deterministic_simple_edit_no_provider_call"
    )
    return {
        "schema": CASE_SCHEMA,
        "case_id": case_id,
        "prompt": prompt,
        "ok": ok,
        "kind": str(result.get("kind") or ""),
        "approval_required": bool(result.get("approval_required")),
        "provider": str(result.get("provider") or ""),
        "model": str(result.get("model") or ""),
        "expected_value": expected_value,
        "actual_value": actual_value,
        "provider_calls": provider_calls,
        "pil_calls": pil_calls,
        "llm_calls": llm_calls,
        "tokens": int(result.get("tokens") or 0),
        "cost_cents": float(result.get("cost_cents") or 0.0),
        "target_path": str(first_op.get("path") or ""),
        "preview_cost_source": str(cost_diff.get("source") or ""),
        "latency_ms": round(elapsed_ms, 3),
    }


def _build_report(
    *,
    output: Path,
    results: list[dict[str, Any]],
    pipeline_calls: int,
    provider_readiness_calls: int,
) -> dict[str, Any]:
    findings: list[str] = []
    if pipeline_calls != 0:
        findings.append(f"PIL pipeline was called {pipeline_calls} times")
    if provider_readiness_calls != 0:
        findings.append(f"provider readiness was called {provider_readiness_calls} times")
    for result in results:
        if not result["ok"]:
            findings.append(f"{result['case_id']} failed deterministic simple-edit assertions")

    summary = {
        "case_count": len(results),
        "passed": sum(1 for result in results if result["ok"]),
        "provider_calls": sum(int(result["provider_calls"]) for result in results),
        "provider_readiness_calls": provider_readiness_calls,
        "pil_calls": pipeline_calls + sum(int(result["pil_calls"]) for result in results),
        "llm_calls": sum(int(result["llm_calls"]) for result in results),
        "tokens": sum(int(result["tokens"]) for result in results),
        "cost_cents": round(sum(float(result["cost_cents"]) for result in results), 8),
        "latency_ms_avg": round(
            sum(float(result["latency_ms"]) for result in results) / len(results),
            3,
        ) if results else 0.0,
    }
    artifacts = {
        "summary_json": str((output / "summary.json").resolve()),
        "results_jsonl": str((output / "results.jsonl").resolve()),
        "markdown_report": str((output / "report.md").resolve()),
    }
    return {
        "schema": REPORT_SCHEMA,
        "ok": not findings,
        "status": "pass" if not findings else "fail",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "route": {
            "schema": DETERMINISTIC_SIMPLE_EDIT_SCHEMA,
            "provider": "deterministic",
            "model": DETERMINISTIC_SIMPLE_EDIT_MODEL,
            "gde_transaction_path": True,
            "provider_readiness_bypassed": provider_readiness_calls == 0,
            "pil_bypassed": pipeline_calls == 0,
        },
        "summary": summary,
        "results": results,
        "artifacts": artifacts,
        "findings": findings,
        "environment": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
    }


def _write_artifacts(report: dict[str, Any], output: Path) -> None:
    accounting = write_accounting_artifacts(
        [],
        output,
        benchmark_id="task58-deterministic-simple-edit",
        source="deterministic_simple_edit_benchmark",
        generated_at_utc=str(report.get("generated_at_utc") or ""),
        benchmark_case_count=int((report.get("summary") or {}).get("case_count") or 0),
        notes=[
            "Task 58 deterministic simple-edit benchmark made no hosted provider calls.",
            "Provider readiness and PIL sentinels prove the certified simple-edit branch ran locally.",
        ],
    )
    report["artifacts"].update(accounting["artifacts"])
    report["provider_accounting"] = accounting["summary"]
    Path(report["artifacts"]["summary_json"]).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    Path(report["artifacts"]["results_jsonl"]).write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in report["results"]),
        encoding="utf-8",
    )
    Path(report["artifacts"]["markdown_report"]).write_text(_markdown(report), encoding="utf-8")


def _markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Deterministic Simple Edit Benchmark",
        "",
        f"Schema: `{report['schema']}`",
        "",
        f"Generated: `{report['generated_at_utc']}`",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Cases | {summary['case_count']} |",
        f"| Passed | {summary['passed']} |",
        f"| Provider calls | {summary['provider_calls']} |",
        f"| Provider readiness calls | {summary['provider_readiness_calls']} |",
        f"| PIL calls | {summary['pil_calls']} |",
        f"| LLM calls | {summary['llm_calls']} |",
        f"| Tokens | {summary['tokens']} |",
        f"| Cost cents | {summary['cost_cents']:.8f} |",
        "",
        "## Cases",
        "",
        "| Case | Kind | Provider | Value | Provider Calls | PIL Calls | LLM Calls | Cost Source | Status |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for result in report["results"]:
        lines.append(
            "| "
            f"`{result['case_id']}` | "
            f"`{result['kind']}` | "
            f"`{result['provider']}` | "
            f"{result['actual_value']} | "
            f"{result['provider_calls']} | "
            f"{result['pil_calls']} | "
            f"{result['llm_calls']} | "
            f"`{result['preview_cost_source']}` | "
            f"`{'pass' if result['ok'] else 'fail'}` |"
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
