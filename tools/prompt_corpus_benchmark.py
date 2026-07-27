"""
Generate Task 47/48 prompt corpus benchmark reports.

This benchmark is intentionally local and deterministic by default. It runs the
reviewed prompt corpus through the Builder prompt classifier/matrix gate,
records every required benchmark column, and writes JSONL plus Markdown
artifacts. Task 48 threshold profiles are evaluated from
docs/prompt_launch_thresholds.json. Hosted-provider, compile, runtime, and
rollback execution remain future benchmark dimensions and are marked as not run
in the local classifier-only profile.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SERVER_DIR = REPO_ROOT / "packages" / "builder-workspace" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from packages.inference.src.provider_accounting import write_accounting_artifacts  # noqa: E402
from prompt_classifier_gate import classify_prompt  # noqa: E402


TOOL_SCHEMA = "xace.prompt_corpus_benchmark.v1"
TOOL_VERSION = 1
DEFAULT_CORPUS = REPO_ROOT / "docs" / "prompt_corpus_100.jsonl"
DEFAULT_MANIFEST = REPO_ROOT / "docs" / "prompt_corpus_manifest.json"
DEFAULT_THRESHOLDS = REPO_ROOT / "docs" / "prompt_launch_thresholds.json"
DEFAULT_OUTPUT = REPO_ROOT / "target-production-prompt-corpus"
LOCAL_NOT_RUN = "not_run_local_classifier_only"
THRESHOLD_SCHEMA = "xace.prompt_launch_thresholds.v1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Task 47 prompt corpus benchmark.")
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS), help="Path to the prompt corpus JSONL file.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="Path to the prompt corpus manifest.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Directory for generated reports.")
    parser.add_argument("--provider", default="local-classifier", help="Provider label recorded in each row.")
    parser.add_argument("--model", default="prompt-classifier-gate-v1", help="Model label recorded in each row.")
    parser.add_argument("--thresholds", default=str(DEFAULT_THRESHOLDS), help="Path to prompt launch thresholds JSON.")
    parser.add_argument("--threshold-profile", default="local_classifier", help="Threshold profile to evaluate.")
    parser.add_argument("--no-thresholds", action="store_true", help="Generate reports without threshold evaluation.")
    parser.add_argument(
        "--fail-on-route-mismatch",
        action="store_true",
        help="Return non-zero after writing reports when any corpus expectation does not match the classifier route.",
    )
    parser.add_argument("--json", action="store_true", help="Print a compact JSON completion report.")
    args = parser.parse_args(argv)

    try:
        report = run_benchmark(
            corpus_path=Path(args.corpus),
            manifest_path=Path(args.manifest),
            output_dir=Path(args.output),
            provider=str(args.provider),
            model=str(args.model),
            thresholds_path=None if args.no_thresholds else Path(args.thresholds),
            threshold_profile=str(args.threshold_profile),
        )
    except BenchmarkError as exc:
        if args.json:
            print(json.dumps({"schema": TOOL_SCHEMA, "ok": False, "error": str(exc)}, indent=2, sort_keys=True))
        else:
            print(f"prompt corpus benchmark failed: {exc}", file=sys.stderr)
        return 1

    route_mismatches = int(report["summary"]["expectation_matches"]["route_mismatches"])
    threshold_status = str(report.get("thresholds", {}).get("status") or "not_evaluated")
    threshold_failures = len(report.get("thresholds", {}).get("failures") or [])
    thresholds_ok = threshold_status in {"pass", "not_evaluated"}
    route_ok = route_mismatches == 0 or not args.fail_on_route_mismatch
    ok = thresholds_ok and route_ok
    completion = {
        "schema": TOOL_SCHEMA,
        "ok": ok,
        "status": "completed" if ok else "failed_thresholds_or_route_mismatches",
        "summary_path": report["artifacts"]["summary_json"],
        "results_jsonl_path": report["artifacts"]["results_jsonl"],
        "markdown_report_path": report["artifacts"]["markdown_report"],
        "case_count": report["summary"]["case_count"],
        "route_mismatches": route_mismatches,
        "threshold_status": threshold_status,
        "threshold_failures": threshold_failures,
        "run_signature": report["reproducibility"]["run_signature"],
    }
    if args.json:
        print(json.dumps(completion, indent=2, sort_keys=True))
    else:
        print("prompt corpus benchmark PASSED" if ok else "prompt corpus benchmark FAILED")
        print(f"summary: {completion['summary_path']}")
        print(f"results: {completion['results_jsonl_path']}")
        print(f"markdown: {completion['markdown_report_path']}")
        print(f"route_mismatches: {route_mismatches}")
        print(f"threshold_status: {threshold_status}")
        print(f"threshold_failures: {threshold_failures}")
    return 0 if ok else 2


def run_benchmark(
    *,
    corpus_path: Path,
    manifest_path: Path,
    output_dir: Path,
    provider: str,
    model: str,
    thresholds_path: Path | None = DEFAULT_THRESHOLDS,
    threshold_profile: str = "local_classifier",
) -> dict[str, Any]:
    corpus_path = _resolve_path(corpus_path)
    manifest_path = _resolve_path(manifest_path)
    output_dir = _resolve_path(output_dir)

    manifest = _load_json(manifest_path, "manifest")
    corpus_bytes = corpus_path.read_bytes()
    corpus_sha256 = hashlib.sha256(corpus_bytes).hexdigest()
    expected_hash = str(manifest.get("corpus_sha256") or "")
    if expected_hash and expected_hash != corpus_sha256:
        raise BenchmarkError(
            f"manifest corpus_sha256 does not match {corpus_path.relative_to(REPO_ROOT)}"
        )
    rows = _load_jsonl(corpus_path)
    expected_count = int(manifest.get("case_count") or 0)
    if expected_count and len(rows) != expected_count:
        raise BenchmarkError(f"corpus has {len(rows)} rows, manifest expects {expected_count}")

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    results: list[dict[str, Any]] = []
    for row in rows:
        results.append(_classify_case(row, provider=provider, model=model, corpus_sha256=corpus_sha256))

    report = _build_report(
        manifest=manifest,
        corpus_path=corpus_path,
        output_dir=output_dir,
        provider=provider,
        model=model,
        generated_at=generated_at,
        corpus_sha256=corpus_sha256,
        results=results,
    )
    if thresholds_path is None:
        threshold_report = _thresholds_not_evaluated()
    else:
        thresholds_path = _resolve_path(thresholds_path)
        thresholds = _load_thresholds(thresholds_path)
        threshold_report = evaluate_thresholds(report, thresholds, threshold_profile, thresholds_path)
    report["thresholds"] = threshold_report
    report["summary"]["execution_scope"]["thresholds"] = threshold_report["status"]
    _write_artifacts(report, output_dir)
    return report


class BenchmarkError(RuntimeError):
    pass


class ThresholdError(BenchmarkError):
    pass


def _resolve_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BenchmarkError(f"{label} not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BenchmarkError(f"{label} is invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise BenchmarkError(f"{label} must be a JSON object")
    return payload


def _load_thresholds(path: Path) -> dict[str, Any]:
    thresholds = _load_json(path, "thresholds")
    if thresholds.get("schema") != THRESHOLD_SCHEMA:
        raise ThresholdError(f"thresholds schema must be {THRESHOLD_SCHEMA}")
    profiles = thresholds.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise ThresholdError("thresholds profiles must be a non-empty object")
    return thresholds


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise BenchmarkError(f"corpus not found: {path}") from exc
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise BenchmarkError(f"corpus line {line_number} is blank")
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BenchmarkError(f"corpus line {line_number} is invalid JSON: {exc}") from exc
        if not isinstance(row, dict):
            raise BenchmarkError(f"corpus line {line_number} must be a JSON object")
        rows.append(row)
    return rows


def _classify_case(
    row: dict[str, Any],
    *,
    provider: str,
    model: str,
    corpus_sha256: str,
) -> dict[str, Any]:
    prompt = str(row.get("prompt") or "")
    started = time.perf_counter()
    classifier = classify_prompt(prompt)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    payload = classifier.to_dict()

    accepted = bool(classifier.may_continue_to_pil)
    clarified = classifier.category_id == "clarification_required"
    blocked = not accepted and not clarified
    expected_category = str(row.get("category_id") or "")
    expected_route = str(row.get("expected_builder_route") or "")
    expected_result_kind = str(row.get("expected_result_kind") or "")
    actual_result_kind = str(payload.get("builder_result_kind") or "")
    route_matched = classifier.route == expected_route
    category_matched = classifier.category_id == expected_category
    result_kind_matched = actual_result_kind == expected_result_kind
    case_hash = _stable_hash(
        {
            "prompt_id": row.get("prompt_id"),
            "prompt": prompt,
            "corpus_sha256": corpus_sha256,
            "matrix_hash": payload.get("matrix_hash"),
            "provider": provider,
            "model": model,
            "tool_version": TOOL_VERSION,
        }
    )

    return {
        "schema": "xace.prompt_corpus_benchmark_case.v1",
        "prompt_id": str(row.get("prompt_id") or ""),
        "genre": str(row.get("genre") or ""),
        "difficulty_band": str(row.get("difficulty_band") or ""),
        "prompt": prompt,
        "expected_category_id": expected_category,
        "actual_category_id": classifier.category_id,
        "expected_builder_route": expected_route,
        "actual_builder_route": classifier.route,
        "expected_result_kind": expected_result_kind,
        "actual_result_kind": actual_result_kind,
        "accepted": accepted,
        "blocked": blocked,
        "clarified": clarified,
        "compiled": None,
        "compile_status": LOCAL_NOT_RUN,
        "runtime_passed": None,
        "runtime_status": LOCAL_NOT_RUN,
        "rollback_passed": None,
        "rollback_status": LOCAL_NOT_RUN,
        "cost_usd": 0.0,
        "cost_status": "no_provider_call_local_classifier_only",
        "latency_ms": round(elapsed_ms, 3),
        "provider": provider,
        "model": model,
        "category_matched": category_matched,
        "route_matched": route_matched,
        "result_kind_matched": result_kind_matched,
        "provider_call_allowed": bool(payload.get("provider_call_allowed")),
        "mutation_allowed": bool(payload.get("mutation_allowed")),
        "classifier_confidence": float(payload.get("confidence") or 0.0),
        "classifier_reason": str(payload.get("reason") or ""),
        "classifier_signals": list(payload.get("signals") or []),
        "reproducibility": {
            "case_hash": case_hash,
            "corpus_sha256": corpus_sha256,
            "matrix_hash": str(payload.get("matrix_hash") or ""),
            "matrix_version": int(payload.get("matrix_version") or 0),
            "tool_schema": TOOL_SCHEMA,
            "tool_version": TOOL_VERSION,
        },
    }


def _build_report(
    *,
    manifest: dict[str, Any],
    corpus_path: Path,
    output_dir: Path,
    provider: str,
    model: str,
    generated_at: str,
    corpus_sha256: str,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    latencies = [float(result["latency_ms"]) for result in results]
    category_counts = _count_by(results, "actual_category_id")
    expected_category_counts = _count_by(results, "expected_category_id")
    genre_counts = _count_by(results, "genre")
    band_counts = _count_by(results, "difficulty_band")
    route_mismatches = [result for result in results if not result["route_matched"]]
    category_mismatches = [result for result in results if not result["category_matched"]]
    result_kind_mismatches = [result for result in results if not result["result_kind_matched"]]
    run_signature = _stable_hash(
        {
            "corpus_sha256": corpus_sha256,
            "provider": provider,
            "model": model,
            "tool_version": TOOL_VERSION,
            "results": [
                {
                    "prompt_id": result["prompt_id"],
                    "actual_category_id": result["actual_category_id"],
                    "actual_builder_route": result["actual_builder_route"],
                    "actual_result_kind": result["actual_result_kind"],
                    "category_matched": result["category_matched"],
                    "route_matched": result["route_matched"],
                    "result_kind_matched": result["result_kind_matched"],
                }
                for result in results
            ],
        }
    )
    summary = {
        "case_count": len(results),
        "accepted": sum(1 for result in results if result["accepted"]),
        "blocked": sum(1 for result in results if result["blocked"]),
        "clarified": sum(1 for result in results if result["clarified"]),
        "compiled": 0,
        "compiled_not_run": len(results),
        "runtime_passed": 0,
        "runtime_not_run": len(results),
        "rollback_passed": 0,
        "rollback_not_run": len(results),
        "total_cost_usd": 0.0,
        "latency_ms": {
            "min": round(min(latencies), 3) if latencies else 0.0,
            "max": round(max(latencies), 3) if latencies else 0.0,
            "avg": round(statistics.fmean(latencies), 3) if latencies else 0.0,
            "p95": round(_percentile(latencies, 95), 3) if latencies else 0.0,
        },
        "expected_category_counts": expected_category_counts,
        "actual_category_counts": category_counts,
        "genre_counts": genre_counts,
        "difficulty_band_counts": band_counts,
        "expectation_matches": {
            "category_matches": len(results) - len(category_mismatches),
            "category_mismatches": len(category_mismatches),
            "route_matches": len(results) - len(route_mismatches),
            "route_mismatches": len(route_mismatches),
            "result_kind_matches": len(results) - len(result_kind_mismatches),
            "result_kind_mismatches": len(result_kind_mismatches),
        },
        "execution_scope": {
            "provider_calls": "not_run",
            "compile": LOCAL_NOT_RUN,
            "runtime": LOCAL_NOT_RUN,
            "rollback": LOCAL_NOT_RUN,
            "thresholds": "not_evaluated",
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "summary_json": str((output_dir / "summary.json").resolve()),
        "results_jsonl": str((output_dir / "results.jsonl").resolve()),
        "markdown_report": str((output_dir / "report.md").resolve()),
    }
    return {
        "schema": TOOL_SCHEMA,
        "tool_version": TOOL_VERSION,
        "generated_at_utc": generated_at,
        "ok": True,
        "status": "completed_local_classifier_only",
        "corpus": {
            "path": _repo_relative(corpus_path),
            "corpus_id": str(manifest.get("corpus_id") or ""),
            "version": int(manifest.get("version") or 0),
            "sha256": corpus_sha256,
        },
        "provider": provider,
        "model": model,
        "summary": summary,
        "results": results,
        "artifacts": artifacts,
        "reproducibility": {
            "run_signature": run_signature,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "command_hint": (
                "python tools/prompt_corpus_benchmark.py --corpus "
                f"{_repo_relative(corpus_path)} --output {_repo_relative(output_dir)}"
            ),
        },
        "notes": [
            "Local Task 47 benchmark records classifier/matrix outcomes for the reviewed corpus.",
            "Task 48 threshold evaluation records whether measured local metrics pass the selected profile.",
            "Hosted provider, SGC compile, runtime execution, and rollback execution are not run in local classifier-only mode.",
        ],
    }


def evaluate_thresholds(
    report: dict[str, Any],
    thresholds: dict[str, Any],
    profile_id: str,
    thresholds_path: Path | None = None,
) -> dict[str, Any]:
    profiles = thresholds.get("profiles")
    if not isinstance(profiles, dict) or profile_id not in profiles:
        raise ThresholdError(f"unknown threshold profile: {profile_id}")
    profile = profiles[profile_id]
    if not isinstance(profile, dict):
        raise ThresholdError(f"threshold profile {profile_id} must be an object")

    metrics = _threshold_metrics(report)
    checks: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []

    def add_min(metric: str, threshold_key: str, label: str) -> None:
        if threshold_key not in profile:
            return
        observed = float(metrics.get(metric) or 0.0)
        threshold = float(profile[threshold_key])
        checks.append(
            _threshold_check(
                label=label,
                metric=metric,
                operator=">=",
                observed=observed,
                threshold=threshold,
                passed=observed >= threshold,
            )
        )

    def add_max(metric: str, threshold_key: str, label: str) -> None:
        if threshold_key not in profile:
            return
        observed = float(metrics.get(metric) or 0.0)
        threshold = float(profile[threshold_key])
        checks.append(
            _threshold_check(
                label=label,
                metric=metric,
                operator="<=",
                observed=observed,
                threshold=threshold,
                passed=observed <= threshold,
            )
        )

    def add_equal(metric: str, threshold_key: str, label: str) -> None:
        if threshold_key not in profile:
            return
        observed = metrics.get(metric)
        threshold = profile[threshold_key]
        checks.append(
            _threshold_check(
                label=label,
                metric=metric,
                operator="==",
                observed=observed,
                threshold=threshold,
                passed=observed == threshold,
            )
        )

    def add_required_bool(metric: str, threshold_key: str, label: str) -> None:
        if not profile.get(threshold_key):
            return
        observed = bool(metrics.get(metric))
        checks.append(
            _threshold_check(
                label=label,
                metric=metric,
                operator="is",
                observed=observed,
                threshold=True,
                passed=observed is True,
            )
        )

    add_min("case_count", "case_count_min", "Corpus case count")
    add_min("classification_accuracy", "classification_accuracy_min", "Classification accuracy")
    add_min("route_accuracy", "route_accuracy_min", "Builder route accuracy")
    add_min("result_kind_accuracy", "result_kind_accuracy_min", "Result-kind accuracy")
    add_min("unsupported_no_mutation_rate", "unsupported_no_mutation_rate_min", "Unsupported no-mutation rate")
    add_min(
        "unsupported_block_or_unsupported_rate",
        "unsupported_block_or_unsupported_rate_min",
        "Unsupported exact block/unsupported rate",
    )
    add_max("total_cost_usd", "cost_total_usd_max", "Total provider cost")
    add_max("cost_per_case_usd", "cost_per_case_usd_max", "Provider cost per case")
    add_max("latency_avg_ms", "latency_avg_ms_max", "Average latency")
    add_max("latency_p95_ms", "latency_p95_ms_max", "P95 latency")
    add_min("compilation_success_rate", "compilation_success_rate_min", "Compilation success rate")
    add_min("runtime_success_rate", "runtime_success_rate_min", "Runtime success rate")
    add_min("rollback_success_rate", "rollback_success_rate_min", "Rollback success rate")
    add_min("provider_reliability_rate", "provider_reliability_min", "Provider reliability")
    add_required_bool("reproducibility_complete", "reproducibility_required", "Reproducibility metadata")
    add_equal("provider_calls_status", "provider_calls_status", "Provider call scope")
    add_equal("compile_status", "compile_status", "Compile scope")
    add_equal("runtime_status", "runtime_status", "Runtime scope")
    add_equal("rollback_status", "rollback_status", "Rollback scope")

    if profile.get("requires_executed_provider_compile_runtime_rollback"):
        for metric, label in (
            ("provider_executed", "Provider calls executed"),
            ("compile_executed", "Compilation executed"),
            ("runtime_executed", "Runtime executed"),
            ("rollback_executed", "Rollback executed"),
        ):
            observed = bool(metrics.get(metric))
            checks.append(
                _threshold_check(
                    label=label,
                    metric=metric,
                    operator="is",
                    observed=observed,
                    threshold=True,
                    passed=observed is True,
                )
            )
    else:
        for metric, label in (
            ("compilation_success_rate", "Compilation success rate"),
            ("runtime_success_rate", "Runtime success rate"),
            ("rollback_success_rate", "Rollback success rate"),
            ("provider_reliability_rate", "Provider reliability"),
        ):
            if metrics.get(metric) is None:
                deferred.append(
                    {
                        "metric": metric,
                        "label": label,
                        "status": "deferred_not_run_in_profile",
                    }
                )

    failures = [check for check in checks if check["status"] == "fail"]
    return {
        "schema": "xace.prompt_launch_threshold_evaluation.v1",
        "profile": profile_id,
        "profile_description": str(profile.get("description") or ""),
        "thresholds_path": _repo_relative(thresholds_path) if thresholds_path else "",
        "thresholds_hash": _stable_hash(thresholds),
        "status": "fail" if failures else "pass",
        "checks": checks,
        "failures": failures,
        "deferred": deferred,
        "metrics": metrics,
    }


def _thresholds_not_evaluated() -> dict[str, Any]:
    return {
        "schema": "xace.prompt_launch_threshold_evaluation.v1",
        "profile": "",
        "status": "not_evaluated",
        "checks": [],
        "failures": [],
        "deferred": [],
        "metrics": {},
    }


def _threshold_metrics(report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("summary") or {}
    results = report.get("results") or []
    case_count = int(summary.get("case_count") or len(results) or 0)
    expectation = summary.get("expectation_matches") or {}
    category_matches = int(expectation.get("category_matches") or 0)
    route_matches = int(expectation.get("route_matches") or 0)
    result_kind_matches = int(expectation.get("result_kind_matches") or 0)
    unsupported_rows = [
        result for result in results if result.get("expected_category_id") in {"blocked", "unsupported"}
    ]
    unsupported_total = len(unsupported_rows)
    unsupported_no_mutation = [
        result
        for result in unsupported_rows
        if not bool(result.get("accepted")) and not bool(result.get("mutation_allowed"))
    ]
    unsupported_block_or_unsupported = [
        result
        for result in unsupported_rows
        if result.get("actual_category_id") in {"blocked", "unsupported"}
    ]
    latency = summary.get("latency_ms") or {}
    execution_scope = summary.get("execution_scope") or {}
    compiled_not_run = int(summary.get("compiled_not_run") or 0)
    runtime_not_run = int(summary.get("runtime_not_run") or 0)
    rollback_not_run = int(summary.get("rollback_not_run") or 0)
    compile_executed = case_count > 0 and compiled_not_run < case_count
    runtime_executed = case_count > 0 and runtime_not_run < case_count
    rollback_executed = case_count > 0 and rollback_not_run < case_count
    provider_status = str(execution_scope.get("provider_calls") or "")
    provider_executed = provider_status not in {"not_run", ""}
    case_hashes = [
        str((result.get("reproducibility") or {}).get("case_hash") or "")
        for result in results
    ]
    run_signature = str((report.get("reproducibility") or {}).get("run_signature") or "")
    return {
        "case_count": case_count,
        "classification_accuracy": _rate(category_matches, case_count),
        "route_accuracy": _rate(route_matches, case_count),
        "result_kind_accuracy": _rate(result_kind_matches, case_count),
        "unsupported_no_mutation_rate": _rate(len(unsupported_no_mutation), unsupported_total),
        "unsupported_block_or_unsupported_rate": _rate(len(unsupported_block_or_unsupported), unsupported_total),
        "total_cost_usd": float(summary.get("total_cost_usd") or 0.0),
        "cost_per_case_usd": _rate(float(summary.get("total_cost_usd") or 0.0), case_count),
        "latency_avg_ms": float(latency.get("avg") or 0.0),
        "latency_p95_ms": float(latency.get("p95") or 0.0),
        "compilation_success_rate": _rate(int(summary.get("compiled") or 0), case_count) if compile_executed else None,
        "runtime_success_rate": _rate(int(summary.get("runtime_passed") or 0), case_count) if runtime_executed else None,
        "rollback_success_rate": _rate(int(summary.get("rollback_passed") or 0), case_count) if rollback_executed else None,
        "provider_reliability_rate": None if not provider_executed else float(summary.get("provider_reliability_rate") or 0.0),
        "reproducibility_complete": (
            bool(run_signature)
            and len(run_signature) == 64
            and len(case_hashes) == case_count
            and all(len(case_hash) == 64 for case_hash in case_hashes)
            and len(set(case_hashes)) == case_count
        ),
        "provider_calls_status": provider_status,
        "compile_status": str(execution_scope.get("compile") or ""),
        "runtime_status": str(execution_scope.get("runtime") or ""),
        "rollback_status": str(execution_scope.get("rollback") or ""),
        "provider_executed": provider_executed,
        "compile_executed": compile_executed,
        "runtime_executed": runtime_executed,
        "rollback_executed": rollback_executed,
    }


def _threshold_check(
    *,
    label: str,
    metric: str,
    operator: str,
    observed: Any,
    threshold: Any,
    passed: bool,
) -> dict[str, Any]:
    return {
        "label": label,
        "metric": metric,
        "operator": operator,
        "observed": observed,
        "threshold": threshold,
        "status": "pass" if passed else "fail",
    }


def _write_artifacts(report: dict[str, Any], output_dir: Path) -> None:
    accounting = write_accounting_artifacts(
        [],
        output_dir,
        benchmark_id=str(report.get("reproducibility", {}).get("run_signature") or ""),
        source="prompt_corpus_benchmark.local_classifier",
        generated_at_utc=str(report.get("generated_at_utc") or ""),
        benchmark_case_count=int((report.get("summary") or {}).get("case_count") or 0),
        notes=[
            "Local classifier-only prompt benchmark made no hosted provider calls.",
            "This artifact is still emitted so provider-token/cost accounting is present for every benchmark run.",
        ],
    )
    report["artifacts"].update(accounting["artifacts"])
    report["provider_accounting"] = accounting["summary"]

    summary_path = output_dir / "summary.json"
    results_path = output_dir / "results.jsonl"
    markdown_path = output_dir / "report.md"
    summary_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    results_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in report["results"]),
        encoding="utf-8",
    )
    markdown_path.write_text(_markdown_report(report), encoding="utf-8")


def _markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    latency = summary["latency_ms"]
    threshold_report = report.get("thresholds") or _thresholds_not_evaluated()
    lines = [
        "# Prompt Corpus Benchmark Report",
        "",
        f"Schema: `{report['schema']}`",
        "",
        f"Generated: `{report['generated_at_utc']}`",
        "",
        f"Corpus: `{report['corpus']['path']}`",
        "",
        f"Corpus SHA-256: `{report['corpus']['sha256']}`",
        "",
        f"Provider: `{report['provider']}`",
        "",
        f"Model: `{report['model']}`",
        "",
        f"Run signature: `{report['reproducibility']['run_signature']}`",
        "",
        "This Task 47/48 report is local classifier-only evidence unless a broader threshold profile is selected. Hosted provider calls, SGC compile, runtime execution, and rollback execution are not run in local mode.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Cases | {summary['case_count']} |",
        f"| Accepted | {summary['accepted']} |",
        f"| Blocked | {summary['blocked']} |",
        f"| Clarified | {summary['clarified']} |",
        f"| Compiled | {summary['compiled']} ({summary['compiled_not_run']} not run) |",
        f"| Runtime passed | {summary['runtime_passed']} ({summary['runtime_not_run']} not run) |",
        f"| Rollback passed | {summary['rollback_passed']} ({summary['rollback_not_run']} not run) |",
        f"| Cost USD | {summary['total_cost_usd']:.4f} |",
        f"| Latency avg ms | {latency['avg']:.3f} |",
        f"| Latency p95 ms | {latency['p95']:.3f} |",
        f"| Category mismatches | {summary['expectation_matches']['category_mismatches']} |",
        f"| Route mismatches | {summary['expectation_matches']['route_mismatches']} |",
        f"| Result-kind mismatches | {summary['expectation_matches']['result_kind_mismatches']} |",
        f"| Threshold profile | `{threshold_report.get('profile', '')}` |",
        f"| Threshold status | `{threshold_report.get('status', 'not_evaluated')}` |",
        "",
        "## Threshold Checks",
        "",
    ]
    checks = threshold_report.get("checks") or []
    if checks:
        lines.extend(["| Check | Observed | Rule | Status |", "| --- | ---: | --- | --- |"])
        for check in checks:
            lines.append(
                "| "
                f"{_escape_md(str(check.get('label') or check.get('metric') or ''))} | "
                f"{_format_observed(check.get('observed'))} | "
                f"`{check.get('operator')}` {_format_observed(check.get('threshold'))} | "
                f"`{check.get('status')}` |"
            )
    else:
        lines.append("Thresholds were not evaluated.")
    deferred = threshold_report.get("deferred") or []
    if deferred:
        lines.extend(["", "Deferred threshold dimensions in this profile:"])
        for item in deferred:
            lines.append(f"- `{item.get('metric')}`: {item.get('status')}")
    lines.extend(
        [
        "",
        "## Category Counts",
        "",
        "| Category | Expected | Actual |",
        "| --- | ---: | ---: |",
        ]
    )
    categories = sorted(set(summary["expected_category_counts"]) | set(summary["actual_category_counts"]))
    for category in categories:
        expected = summary["expected_category_counts"].get(category, 0)
        actual = summary["actual_category_counts"].get(category, 0)
        lines.append(f"| `{category}` | {expected} | {actual} |")

    mismatches = [result for result in report["results"] if not result["route_matched"]]
    lines.extend(["", "## Route Mismatches", ""])
    if mismatches:
        lines.extend(["| Prompt | Expected | Actual | Signals |", "| --- | --- | --- | --- |"])
        for result in mismatches:
            signals = ", ".join(result["classifier_signals"])
            lines.append(
                "| "
                f"`{result['prompt_id']}` | "
                f"`{result['expected_builder_route']}` | "
                f"`{result['actual_builder_route']}` | "
                f"{_escape_md(signals)} |"
            )
    else:
        lines.append("No route mismatches.")

    lines.extend(
        [
            "",
            "## Results",
            "",
            "| Prompt | Genre | Band | Expected | Actual | Accepted | Blocked | Clarified | Compiled | Runtime Passed | Rollback Passed | Cost USD | Latency ms | Provider | Model | Reproducibility |",
            "| --- | --- | --- | --- | --- | ---: | ---: | ---: | --- | --- | --- | ---: | ---: | --- | --- | --- |",
        ]
    )
    for result in report["results"]:
        lines.append(
            "| "
            f"`{result['prompt_id']}` | "
            f"`{result['genre']}` | "
            f"`{result['difficulty_band']}` | "
            f"`{result['expected_builder_route']}` | "
            f"`{result['actual_builder_route']}` | "
            f"{_bool_cell(result['accepted'])} | "
            f"{_bool_cell(result['blocked'])} | "
            f"{_bool_cell(result['clarified'])} | "
            f"{_none_cell(result['compiled'], result['compile_status'])} | "
            f"{_none_cell(result['runtime_passed'], result['runtime_status'])} | "
            f"{_none_cell(result['rollback_passed'], result['rollback_status'])} | "
            f"{float(result['cost_usd']):.4f} | "
            f"{float(result['latency_ms']):.3f} | "
            f"`{_escape_md(result['provider'])}` | "
            f"`{_escape_md(result['model'])}` | "
            f"`{result['reproducibility']['case_hash'][:16]}` |"
        )
    lines.append("")
    return "\n".join(lines)


def _stable_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _count_by(results: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        value = str(result.get(key) or "")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _rate(numerator: float | int, denominator: float | int) -> float:
    denominator = float(denominator)
    if denominator == 0:
        return 0.0
    return float(numerator) / denominator


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((percentile / 100) * (len(ordered) - 1)))
    return ordered[max(0, min(index, len(ordered) - 1))]


def _repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _bool_cell(value: bool) -> str:
    return "true" if value else "false"


def _none_cell(value: Any, status: str) -> str:
    if value is None:
        return f"`{status}`"
    return _bool_cell(bool(value))


def _escape_md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _format_observed(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "`not_run`"
    if isinstance(value, str):
        return f"`{_escape_md(value)}`"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
