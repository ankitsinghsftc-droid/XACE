"""
Run the X10-028 launch provider/runtime prompt benchmark profile.

This tool keeps the Task 47 local classifier benchmark intact and adds the
stricter launch profile proof: provider calls through InferenceAdapter, real
SGC/runtime proof execution, rollback recovery proof execution, unsupported
blocking, cost, latency, and reproducibility artifacts.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import prompt_corpus_benchmark as corpus_benchmark  # noqa: E402
from packages.inference.src.cache_key_builder import CacheKeyBuilder  # noqa: E402
from packages.inference.src.inference_adapter import InferenceAdapter, InferenceRequest, PromptPart  # noqa: E402
from packages.inference.src.inference_budget import InferenceBudget  # noqa: E402
from packages.inference.src.inference_retry_policy import InferenceRetryPolicy  # noqa: E402
from packages.inference.src.model_descriptor import ComplexityTier  # noqa: E402
from packages.inference.src.prompt_cache import PromptCache  # noqa: E402
from packages.inference.src.provider_accounting import write_accounting_artifacts  # noqa: E402
from packages.inference.src.provider_registry import IProviderClient, ProviderRegistry  # noqa: E402
from packages.inference.src.response_cache import ResponseCache  # noqa: E402
from packages.inference.src.telemetry_pipeline import InMemoryBackend, TelemetryPipeline  # noqa: E402


SCHEMA = "xace.launch_provider_runtime_benchmark.v1"
CASE_SCHEMA = "xace.launch_provider_runtime_benchmark_case.v1"
PROOF_SCHEMA = "xace.launch_provider_runtime_dimension_proofs.v1"
EXECUTION_PROFILE = "launch_provider_runtime"
DEFAULT_OUTPUT = REPO_ROOT / "target-launch-provider-runtime-prompt-benchmark"
DEFAULT_RUNTIME_BIN = REPO_ROOT / "target-codex-certify" / "debug" / ("xace_runtime.exe" if os.name == "nt" else "xace_runtime")
DEFAULT_SGC_BIN = REPO_ROOT / "target-codex-certify" / "debug" / ("xace-system-graph-compiler.exe" if os.name == "nt" else "xace-system-graph-compiler")
LAUNCH_PROVIDER = "local"
LAUNCH_MODEL = "xace-launch-provider-runtime-contract-v1"
LAUNCH_SESSION_ID = "x10-028-launch-provider-runtime"


class LaunchBenchmarkError(RuntimeError):
    pass


class _LaunchProviderClient(IProviderClient):
    """Deterministic in-process provider client used behind InferenceAdapter."""

    def complete(
        self,
        model_id: str,
        prompt: dict[str, Any],
        system_prompt: str,
        max_tokens: int,
        temperature: float,
        structured_output: Any | None = None,
    ) -> dict[str, Any]:
        del system_prompt, max_tokens, temperature, structured_output
        prompt_text = json.dumps(prompt, sort_keys=True, separators=(",", ":"), default=str)
        response = {
            "schema": "xace.launch_provider_runtime.provider_response.v1",
            "model_id": model_id,
            "prompt_hash": corpus_benchmark._stable_hash({"prompt": prompt_text}),
            "decision": "provider_contract_pass",
        }
        text = json.dumps(response, sort_keys=True, separators=(",", ":"))
        return {
            "text": text,
            "input_tokens": max(1, len(prompt_text) // 4),
            "output_tokens": max(1, len(text) // 4),
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        }

    def health_check(self) -> bool:
        return True

    def provider_name(self) -> str:
        return LAUNCH_PROVIDER


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the X10-028 launch provider/runtime prompt benchmark.")
    parser.add_argument("--corpus", default=str(corpus_benchmark.DEFAULT_CORPUS))
    parser.add_argument("--manifest", default=str(corpus_benchmark.DEFAULT_MANIFEST))
    parser.add_argument("--thresholds", default=str(corpus_benchmark.DEFAULT_THRESHOLDS))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Directory for generated reports.")
    parser.add_argument("--runtime-bin", default=str(DEFAULT_RUNTIME_BIN))
    parser.add_argument("--sgc-bin", default=str(DEFAULT_SGC_BIN))
    parser.add_argument("--provider", default=LAUNCH_PROVIDER)
    parser.add_argument("--model", default=LAUNCH_MODEL)
    parser.add_argument("--proof-timeout-s", type=int, default=240)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run_benchmark(
            corpus_path=Path(args.corpus),
            manifest_path=Path(args.manifest),
            thresholds_path=Path(args.thresholds),
            output_dir=Path(args.output),
            runtime_bin=Path(args.runtime_bin),
            sgc_bin=Path(args.sgc_bin),
            provider=str(args.provider),
            model=str(args.model),
            proof_timeout_s=int(args.proof_timeout_s),
        )
    except LaunchBenchmarkError as exc:
        if args.json:
            print(json.dumps({"schema": SCHEMA, "ok": False, "error": str(exc)}, indent=2, sort_keys=True))
        else:
            print(f"launch provider/runtime benchmark failed: {exc}", file=sys.stderr)
        return 1

    completion = {
        "schema": SCHEMA,
        "ok": bool(report.get("ok")),
        "status": str(report.get("status") or ""),
        "summary_path": report["artifacts"]["summary_json"],
        "results_jsonl_path": report["artifacts"]["results_jsonl"],
        "markdown_report_path": report["artifacts"]["markdown_report"],
        "case_count": report["summary"]["case_count"],
        "provider_call_count": report["summary"].get("provider_call_count", 0),
        "compiled": report["summary"].get("compiled", 0),
        "runtime_passed": report["summary"].get("runtime_passed", 0),
        "rollback_passed": report["summary"].get("rollback_passed", 0),
        "route_mismatches": report["summary"]["expectation_matches"].get("route_mismatches", 0),
        "threshold_status": report.get("thresholds", {}).get("status", "not_evaluated"),
        "threshold_failures": len(report.get("thresholds", {}).get("failures") or []),
        "run_signature": report["reproducibility"]["run_signature"],
    }
    if args.json:
        print(json.dumps(completion, indent=2, sort_keys=True))
    else:
        print("launch provider/runtime benchmark PASSED" if completion["ok"] else "launch provider/runtime benchmark FAILED")
        print(f"summary: {completion['summary_path']}")
        print(f"results: {completion['results_jsonl_path']}")
        print(f"markdown: {completion['markdown_report_path']}")
        print(f"threshold_status: {completion['threshold_status']}")
    return 0 if completion["ok"] else 2


def run_benchmark(
    *,
    corpus_path: Path,
    manifest_path: Path,
    thresholds_path: Path,
    output_dir: Path,
    runtime_bin: Path,
    sgc_bin: Path,
    provider: str = LAUNCH_PROVIDER,
    model: str = LAUNCH_MODEL,
    proof_timeout_s: int = 240,
) -> dict[str, Any]:
    corpus_path = corpus_benchmark._resolve_path(corpus_path)
    manifest_path = corpus_benchmark._resolve_path(manifest_path)
    thresholds_path = corpus_benchmark._resolve_path(thresholds_path)
    output_dir = corpus_benchmark._resolve_path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = corpus_benchmark._load_json(manifest_path, "manifest")
    corpus_bytes = corpus_path.read_bytes()
    corpus_sha256 = corpus_benchmark.hashlib.sha256(corpus_bytes).hexdigest()
    expected_hash = str(manifest.get("corpus_sha256") or "")
    if expected_hash and expected_hash != corpus_sha256:
        raise LaunchBenchmarkError(f"manifest corpus_sha256 does not match {corpus_benchmark._repo_relative(corpus_path)}")
    rows = corpus_benchmark._load_jsonl(corpus_path)
    expected_count = int(manifest.get("case_count") or 0)
    if expected_count and len(rows) != expected_count:
        raise LaunchBenchmarkError(f"corpus has {len(rows)} rows, manifest expects {expected_count}")

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    results = [
        corpus_benchmark._classify_case(row, provider=provider, model=model, corpus_sha256=corpus_sha256)
        for row in rows
    ]

    adapter, telemetry_backend = _build_launch_adapter()
    for row, result in zip(rows, results):
        _execute_provider_dimension(row, result, adapter)

    proofs = _run_launch_dimension_proofs(
        output_dir=output_dir,
        runtime_bin=runtime_bin,
        sgc_bin=sgc_bin,
        timeout_s=proof_timeout_s,
    )
    _apply_compile_runtime_rollback_dimensions(results, proofs)

    report = corpus_benchmark._build_report(
        manifest=manifest,
        corpus_path=corpus_path,
        output_dir=output_dir,
        provider=provider,
        model=model,
        generated_at=generated_at,
        corpus_sha256=corpus_sha256,
        results=results,
    )
    report["schema"] = SCHEMA
    report["execution_profile"] = EXECUTION_PROFILE
    report["status"] = "completed_launch_provider_runtime"
    report["launch_provider_runtime"] = proofs
    report["notes"] = [
        "X10-028 launch benchmark runs provider calls through InferenceAdapter for provider-allowed corpus rows.",
        "Real SGC/runtime proof and rollback recovery proof commands execute once per benchmark and are attached to each mutation-capable row as shared launch evidence.",
        "Unsupported, blocked, clarification, and experimental rows must remain pre-provider no-mutation routes.",
    ]
    _override_launch_summary(report, results)
    report["reproducibility"]["command_hint"] = (
        "python tools/launch_provider_runtime_benchmark.py --output "
        f"{corpus_benchmark._repo_relative(output_dir)} --runtime-bin {runtime_bin} --sgc-bin {sgc_bin}"
    )
    report["reproducibility"]["execution_profile"] = EXECUTION_PROFILE
    report["reproducibility"]["platform"] = platform.platform()
    report["reproducibility"]["python_version"] = platform.python_version()
    report["reproducibility"]["run_signature"] = corpus_benchmark._stable_hash({
        "corpus_sha256": corpus_sha256,
        "execution_profile": EXECUTION_PROFILE,
        "provider": provider,
        "model": model,
        "results": _signature_results(results),
        "proofs": _signature_proofs(proofs),
    })

    thresholds = corpus_benchmark._load_thresholds(thresholds_path)
    report["thresholds"] = corpus_benchmark.evaluate_thresholds(
        report,
        thresholds,
        EXECUTION_PROFILE,
        thresholds_path,
    )
    report["summary"]["execution_scope"]["thresholds"] = report["thresholds"]["status"]
    route_mismatches = int(report["summary"]["expectation_matches"].get("route_mismatches") or 0)
    report["ok"] = (
        bool(proofs.get("ok"))
        and report["thresholds"].get("status") == "pass"
        and route_mismatches == 0
    )
    if not report["ok"]:
        report["status"] = "failed_launch_provider_runtime"

    _write_launch_artifacts(report, output_dir, telemetry_backend.all_events())
    return report


def _build_launch_adapter() -> tuple[InferenceAdapter, InMemoryBackend]:
    registry = ProviderRegistry(clients={LAUNCH_PROVIDER: _LaunchProviderClient()})
    telemetry = TelemetryPipeline()
    backend = InMemoryBackend()
    telemetry.add_backend(backend)
    adapter = InferenceAdapter(
        provider_registry=registry,
        telemetry=telemetry,
        budget=InferenceBudget(),
        retry_policy=InferenceRetryPolicy(sleep_fn=lambda _seconds: None),
        prompt_cache=PromptCache(),
        response_cache=ResponseCache(),
        cache_key_builder=CacheKeyBuilder(),
    )
    return adapter, backend


def _execute_provider_dimension(row: dict[str, Any], result: dict[str, Any], adapter: InferenceAdapter) -> None:
    result["schema"] = CASE_SCHEMA
    result["execution_profile"] = EXECUTION_PROFILE
    if not bool(result.get("provider_call_allowed")):
        result["provider_executed"] = False
        result["provider_status"] = "not_required_pre_provider_block"
        result["cost_status"] = "no_provider_call_pre_provider_block"
        return

    payload = {
        "schema": "xace.launch_provider_runtime.provider_prompt.v1",
        "prompt_id": result.get("prompt_id"),
        "prompt": row.get("prompt"),
        "expected_category_id": row.get("category_id"),
        "actual_category_id": result.get("actual_category_id"),
        "expected_builder_route": row.get("expected_builder_route"),
        "actual_builder_route": result.get("actual_builder_route"),
    }
    started = time.perf_counter()
    try:
        response = adapter.call(InferenceRequest(
            prompt_parts=[PromptPart(text=json.dumps(payload, sort_keys=True), cacheable=False, label="launch_case")],
            system_prompt="Return the XACE launch benchmark provider contract response.",
            logical_model="local_dev",
            complexity_tier=ComplexityTier.M,
            max_tokens=128,
            temperature=0.0,
            session_id=LAUNCH_SESSION_ID,
            call_label=f"launch_provider_runtime:{result.get('prompt_id', '')}",
            request_id=f"x10-028-{result.get('prompt_id', '')}",
            intent_class="PromptLaunchBenchmark",
            bypass_response_cache=True,
        ))
        provider_payload = json.loads(response.text)
        ok = provider_payload.get("schema") == "xace.launch_provider_runtime.provider_response.v1"
        result["provider_executed"] = True
        result["provider_status"] = "success" if ok else "invalid_provider_contract"
        result["provider_response_schema"] = str(provider_payload.get("schema") or "")
        result["provider_request_id"] = response.request_id
        result["provider_tokens"] = {
            "input": response.input_tokens,
            "output": response.output_tokens,
            "cache_read": response.cache_read_tokens,
            "cache_write": response.cache_write_tokens,
        }
        result["cost_usd"] = round(response.cost_cents / 100.0, 10)
        result["cost_status"] = "provider_accounted"
        result["latency_ms"] = round(float(result.get("latency_ms") or 0.0) + float(response.latency_ms), 3)
    except Exception as exc:  # noqa: BLE001
        result["provider_executed"] = True
        result["provider_status"] = "error"
        result["provider_error"] = str(exc)[-500:]
        result["latency_ms"] = round(float(result.get("latency_ms") or 0.0) + ((time.perf_counter() - started) * 1000.0), 3)


def _run_launch_dimension_proofs(*, output_dir: Path, runtime_bin: Path, sgc_bin: Path, timeout_s: int) -> dict[str, Any]:
    runtime_bin = runtime_bin.resolve()
    sgc_bin = sgc_bin.resolve()
    if not runtime_bin.exists():
        raise LaunchBenchmarkError(f"runtime binary not found: {runtime_bin}")
    if not sgc_bin.exists():
        raise LaunchBenchmarkError(f"SGC binary not found: {sgc_bin}")

    proof_root = output_dir / "sgc-runtime-proof"
    run_id = f"x10-028-launch-provider-runtime-{int(time.time() * 1000)}"
    sgc_runtime = _run_json_command(
        [
            sys.executable,
            "tools/sgc_runtime_proof.py",
            "--runtime-bin",
            str(runtime_bin),
            "--sgc-bin",
            str(sgc_bin),
            "--proof-root",
            str(proof_root),
            "--run-id",
            run_id,
            "--ticks",
            "3",
            "--json",
        ],
        timeout_s=timeout_s,
    )
    rollback = _run_json_command(
        [sys.executable, "tools/prompt_apply_recovery_check.py", "--json"],
        timeout_s=timeout_s,
    )
    sgc_report = sgc_runtime.get("json") if isinstance(sgc_runtime.get("json"), dict) else {}
    rollback_report = rollback.get("json") if isinstance(rollback.get("json"), dict) else {}
    sgc_checks = sgc_report.get("checks") if isinstance(sgc_report.get("checks"), dict) else {}
    compile_ok = (
        bool(sgc_runtime.get("ok"))
        and bool(sgc_report.get("ok"))
        and bool(sgc_checks.get("real_sgc_binary_invoked"))
        and bool(sgc_checks.get("persisted_sgc_plan_loaded"))
    )
    runtime_ok = (
        bool(sgc_runtime.get("ok"))
        and bool(sgc_report.get("ok"))
        and bool(sgc_checks.get("real_runtime_binary_invoked"))
        and bool(sgc_checks.get("tick_hash_replay_match"))
        and bool(sgc_checks.get("schedule_replay_match"))
    )
    rollback_ok = bool(rollback.get("ok")) and bool(rollback_report.get("ok"))
    return {
        "schema": PROOF_SCHEMA,
        "ok": compile_ok and runtime_ok and rollback_ok,
        "runtime_bin": str(runtime_bin),
        "sgc_bin": str(sgc_bin),
        "proof_root": str(proof_root),
        "run_id": run_id,
        "compile_ok": compile_ok,
        "runtime_ok": runtime_ok,
        "rollback_ok": rollback_ok,
        "sgc_runtime_proof": sgc_runtime,
        "rollback_recovery_proof": rollback,
    }


def _run_json_command(command: list[str], *, timeout_s: int) -> dict[str, Any]:
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout_s,
        check=False,
    )
    stdout = completed.stdout or ""
    parsed: dict[str, Any] = {}
    try:
        parsed_raw = json.loads(stdout.strip())
        if isinstance(parsed_raw, dict):
            parsed = parsed_raw
    except Exception:
        try:
            parsed_raw = json.loads(stdout.strip().splitlines()[-1])
            if isinstance(parsed_raw, dict):
                parsed = parsed_raw
        except Exception:
            parsed = {}
    return {
        "schema": "xace.launch_provider_runtime.command_result.v1",
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "command": command,
        "stdout_tail": stdout[-4000:],
        "json": parsed,
    }


def _apply_compile_runtime_rollback_dimensions(results: list[dict[str, Any]], proofs: dict[str, Any]) -> None:
    compile_ok = bool(proofs.get("compile_ok"))
    runtime_ok = bool(proofs.get("runtime_ok"))
    rollback_ok = bool(proofs.get("rollback_ok"))
    evidence = {
        "schema": "xace.launch_provider_runtime.case_evidence.v1",
        "proof_root": str(proofs.get("proof_root") or ""),
        "compile_source": "tools/sgc_runtime_proof.py",
        "runtime_source": "tools/sgc_runtime_proof.py",
        "rollback_source": "tools/prompt_apply_recovery_check.py",
    }
    for result in results:
        requires_execution = bool(result.get("accepted")) and bool(result.get("mutation_allowed"))
        if requires_execution:
            result["compiled"] = compile_ok
            result["compile_status"] = "passed_by_sgc_runtime_proof" if compile_ok else "failed_sgc_runtime_proof"
            result["runtime_passed"] = runtime_ok
            result["runtime_status"] = "passed_by_sgc_runtime_proof" if runtime_ok else "failed_sgc_runtime_proof"
            result["rollback_passed"] = rollback_ok
            result["rollback_status"] = "passed_by_prompt_apply_recovery_proof" if rollback_ok else "failed_prompt_apply_recovery_proof"
            result["launch_execution_evidence"] = evidence
        else:
            result["compiled"] = None
            result["compile_status"] = "not_required_non_mutation_route"
            result["runtime_passed"] = None
            result["runtime_status"] = "not_required_non_mutation_route"
            result["rollback_passed"] = None
            result["rollback_status"] = "not_required_non_mutation_route"
            result["launch_execution_evidence"] = {
                **evidence,
                "status": "unsupported_or_non_mutation_blocked_before_compile",
            }


def _override_launch_summary(report: dict[str, Any], results: list[dict[str, Any]]) -> None:
    summary = report["summary"]
    latencies = [float(result.get("latency_ms") or 0.0) for result in results]
    compiled = sum(1 for result in results if result.get("compiled") is True)
    compiled_failed = sum(1 for result in results if result.get("compiled") is False)
    runtime_passed = sum(1 for result in results if result.get("runtime_passed") is True)
    runtime_failed = sum(1 for result in results if result.get("runtime_passed") is False)
    rollback_passed = sum(1 for result in results if result.get("rollback_passed") is True)
    rollback_failed = sum(1 for result in results if result.get("rollback_passed") is False)
    provider_calls = sum(1 for result in results if bool(result.get("provider_executed")))
    provider_success = sum(1 for result in results if result.get("provider_status") == "success")
    total_cost_usd = round(sum(float(result.get("cost_usd") or 0.0) for result in results), 10)
    summary.update({
        "compiled": compiled,
        "compiled_failed": compiled_failed,
        "compiled_not_run": len(results) - compiled - compiled_failed,
        "runtime_passed": runtime_passed,
        "runtime_failed": runtime_failed,
        "runtime_not_run": len(results) - runtime_passed - runtime_failed,
        "rollback_passed": rollback_passed,
        "rollback_failed": rollback_failed,
        "rollback_not_run": len(results) - rollback_passed - rollback_failed,
        "provider_call_count": provider_calls,
        "provider_success_count": provider_success,
        "provider_failure_count": provider_calls - provider_success,
        "provider_reliability_rate": corpus_benchmark._rate(provider_success, provider_calls),
        "total_cost_usd": total_cost_usd,
        "latency_ms": {
            "min": round(min(latencies), 3) if latencies else 0.0,
            "max": round(max(latencies), 3) if latencies else 0.0,
            "avg": round(corpus_benchmark.statistics.fmean(latencies), 3) if latencies else 0.0,
            "p95": round(corpus_benchmark._percentile(latencies, 95), 3) if latencies else 0.0,
        },
        "execution_scope": {
            "provider_calls": "executed" if provider_calls else "not_run",
            "compile": "executed" if compiled + compiled_failed else "not_run",
            "runtime": "executed" if runtime_passed + runtime_failed else "not_run",
            "rollback": "executed" if rollback_passed + rollback_failed else "not_run",
            "thresholds": "not_evaluated",
        },
    })


def _write_launch_artifacts(report: dict[str, Any], output_dir: Path, accounting_events: list[Any]) -> None:
    accounting = write_accounting_artifacts(
        accounting_events,
        output_dir,
        benchmark_id=str(report.get("reproducibility", {}).get("run_signature") or ""),
        source="launch_provider_runtime_benchmark",
        generated_at_utc=str(report.get("generated_at_utc") or ""),
        benchmark_case_count=int((report.get("summary") or {}).get("case_count") or 0),
        notes=[
            "X10-028 provider calls are emitted by InferenceAdapter through the launch benchmark provider client.",
            "Hosted BYOK reliability remains covered by the separate opt-in hosted-provider proof gate.",
        ],
    )
    report["artifacts"].update(accounting["artifacts"])
    report["provider_accounting"] = accounting["summary"]
    (output_dir / "summary.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "results.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in report["results"]),
        encoding="utf-8",
    )
    (output_dir / "report.md").write_text(_markdown_report(report), encoding="utf-8")


def _markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    thresholds = report.get("thresholds") or {}
    lines = [
        "# Launch Provider Runtime Prompt Benchmark",
        "",
        f"Schema: `{report['schema']}`",
        "",
        f"Generated: `{report['generated_at_utc']}`",
        "",
        f"Execution profile: `{report['execution_profile']}`",
        "",
        f"Run signature: `{report['reproducibility']['run_signature']}`",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Cases | {summary['case_count']} |",
        f"| Provider calls | {summary.get('provider_call_count', 0)} |",
        f"| Provider reliability | {summary.get('provider_reliability_rate', 0.0):.3f} |",
        f"| Compiled | {summary.get('compiled', 0)} ({summary.get('compiled_failed', 0)} failed, {summary.get('compiled_not_run', 0)} not required) |",
        f"| Runtime passed | {summary.get('runtime_passed', 0)} ({summary.get('runtime_failed', 0)} failed, {summary.get('runtime_not_run', 0)} not required) |",
        f"| Rollback passed | {summary.get('rollback_passed', 0)} ({summary.get('rollback_failed', 0)} failed, {summary.get('rollback_not_run', 0)} not required) |",
        f"| Cost USD | {float(summary.get('total_cost_usd') or 0.0):.4f} |",
        f"| Latency p95 ms | {float((summary.get('latency_ms') or {}).get('p95') or 0.0):.3f} |",
        f"| Route mismatches | {summary['expectation_matches']['route_mismatches']} |",
        f"| Threshold profile | `{thresholds.get('profile', '')}` |",
        f"| Threshold status | `{thresholds.get('status', 'not_evaluated')}` |",
        "",
        "## Threshold Checks",
        "",
    ]
    checks = thresholds.get("checks") or []
    if checks:
        lines.extend(["| Check | Observed | Rule | Status |", "| --- | ---: | --- | --- |"])
        for check in checks:
            lines.append(
                "| "
                f"{corpus_benchmark._escape_md(str(check.get('label') or check.get('metric') or ''))} | "
                f"{corpus_benchmark._format_observed(check.get('observed'))} | "
                f"`{check.get('operator')}` {corpus_benchmark._format_observed(check.get('threshold'))} | "
                f"`{check.get('status')}` |"
            )
    else:
        lines.append("Thresholds were not evaluated.")
    lines.extend(["", "## Proof Commands", ""])
    proofs = report.get("launch_provider_runtime") or {}
    for key in ("sgc_runtime_proof", "rollback_recovery_proof"):
        item = proofs.get(key) if isinstance(proofs.get(key), dict) else {}
        lines.append(f"- `{key}`: `{ 'pass' if item.get('ok') else 'fail' }` in {float(item.get('elapsed_ms') or 0.0):.3f} ms")
    lines.extend(["", "## Results", ""])
    lines.extend([
        "| Prompt | Expected Route | Actual Route | Provider | Compile | Runtime | Rollback | Cost USD | Latency ms |",
        "| --- | --- | --- | --- | --- | --- | --- | ---: | ---: |",
    ])
    for result in report["results"]:
        lines.append(
            "| "
            f"`{result['prompt_id']}` | "
            f"`{result['expected_builder_route']}` | "
            f"`{result['actual_builder_route']}` | "
            f"`{result.get('provider_status', '')}` | "
            f"`{result.get('compile_status', '')}` | "
            f"`{result.get('runtime_status', '')}` | "
            f"`{result.get('rollback_status', '')}` | "
            f"{float(result.get('cost_usd') or 0.0):.4f} | "
            f"{float(result.get('latency_ms') or 0.0):.3f} |"
        )
    lines.append("")
    return "\n".join(lines)


def _signature_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = (
        "prompt_id",
        "actual_category_id",
        "actual_builder_route",
        "actual_result_kind",
        "provider_status",
        "compile_status",
        "runtime_status",
        "rollback_status",
        "category_matched",
        "route_matched",
        "result_kind_matched",
    )
    return [{key: result.get(key) for key in keys} for result in results]


def _signature_proofs(proofs: dict[str, Any]) -> dict[str, Any]:
    return {
        "compile_ok": bool(proofs.get("compile_ok")),
        "runtime_ok": bool(proofs.get("runtime_ok")),
        "rollback_ok": bool(proofs.get("rollback_ok")),
        "runtime_bin": str(proofs.get("runtime_bin") or ""),
        "sgc_bin": str(proofs.get("sgc_bin") or ""),
    }


if __name__ == "__main__":
    raise SystemExit(main())
