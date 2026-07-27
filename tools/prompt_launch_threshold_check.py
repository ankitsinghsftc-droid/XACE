"""
Validate Task 48 prompt launch thresholds and benchmark failure behavior.
"""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
THRESHOLDS_PATH = REPO_ROOT / "docs" / "prompt_launch_thresholds.json"
THRESHOLDS_DOC = REPO_ROOT / "docs" / "PROMPT_LAUNCH_THRESHOLDS.md"
BENCHMARK_TOOL = REPO_ROOT / "tools" / "prompt_corpus_benchmark.py"
DEFAULT_TARGET_DIR = REPO_ROOT / "target-codex-prompt-launch-threshold-check"
REQUIRED_LOCAL_KEYS = (
    "case_count_min",
    "classification_accuracy_min",
    "route_accuracy_min",
    "result_kind_accuracy_min",
    "unsupported_no_mutation_rate_min",
    "unsupported_block_or_unsupported_rate_min",
    "cost_total_usd_max",
    "latency_p95_ms_max",
    "reproducibility_required",
)
REQUIRED_LAUNCH_KEYS = (
    "classification_accuracy_min",
    "compilation_success_rate_min",
    "runtime_success_rate_min",
    "rollback_success_rate_min",
    "unsupported_no_mutation_rate_min",
    "cost_per_case_usd_max",
    "latency_p95_ms_max",
    "provider_reliability_min",
    "reproducibility_required",
    "requires_executed_provider_compile_runtime_rollback",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Task 48 prompt launch thresholds.")
    parser.add_argument("--target-dir", default=str(DEFAULT_TARGET_DIR), help="Directory for generated check artifacts.")
    parser.add_argument("--json", action="store_true", help="Emit a JSON report.")
    args = parser.parse_args(argv)

    findings = run(Path(args.target_dir))
    report = {
        "schema": "xace.prompt_launch_threshold_check.v1",
        "ok": not findings,
        "findings": findings,
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif findings:
        print("prompt launch threshold check failed:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
    else:
        print("prompt launch threshold check PASSED")
    return 1 if findings else 0


def run(target_dir: Path) -> list[str]:
    target_dir = _resolve(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    findings: list[str] = []
    thresholds = _load_json(THRESHOLDS_PATH, findings, "thresholds")
    if thresholds is None:
        return findings
    findings.extend(_validate_thresholds(thresholds))
    findings.extend(_validate_docs())
    findings.extend(_validate_benchmark_pass(target_dir))
    findings.extend(_validate_benchmark_failure(target_dir, thresholds))
    return findings


def _validate_thresholds(thresholds: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    if thresholds.get("schema") != "xace.prompt_launch_thresholds.v1":
        findings.append("docs/prompt_launch_thresholds.json schema mismatch")
    profiles = thresholds.get("profiles")
    if not isinstance(profiles, dict):
        return findings + ["threshold profiles must be an object"]
    local = profiles.get("local_classifier")
    launch = profiles.get("launch_provider_runtime")
    if not isinstance(local, dict):
        findings.append("missing local_classifier threshold profile")
    else:
        for key in REQUIRED_LOCAL_KEYS:
            if key not in local:
                findings.append(f"local_classifier profile missing {key}")
    if not isinstance(launch, dict):
        findings.append("missing launch_provider_runtime threshold profile")
    else:
        for key in REQUIRED_LAUNCH_KEYS:
            if key not in launch:
                findings.append(f"launch_provider_runtime profile missing {key}")
    return findings


def _validate_docs() -> list[str]:
    if not THRESHOLDS_DOC.exists():
        return ["missing docs/PROMPT_LAUNCH_THRESHOLDS.md"]
    text = THRESHOLDS_DOC.read_text(encoding="utf-8")
    findings: list[str] = []
    for needle in (
        "xace.prompt_launch_thresholds.v1",
        "local_classifier",
        "launch_provider_runtime",
        "python tools/prompt_corpus_benchmark.py",
        "python tools/prompt_launch_threshold_check.py",
    ):
        if needle not in text:
            findings.append(f"threshold docs missing {needle}")
    return findings


def _validate_benchmark_pass(target_dir: Path) -> list[str]:
    output_dir = target_dir / "local-pass"
    completed = _run_benchmark(["--output", str(output_dir), "--json"])
    findings: list[str] = []
    if completed.returncode != 0:
        findings.append(f"local threshold benchmark should pass, exit {completed.returncode}: {completed.stdout[-1200:]}")
        return findings
    summary = _load_json(output_dir / "summary.json", findings, "local pass summary")
    if not summary:
        return findings
    threshold_report = summary.get("thresholds") or {}
    if threshold_report.get("status") != "pass":
        findings.append("local threshold benchmark summary did not record threshold pass")
    if threshold_report.get("profile") != "local_classifier":
        findings.append("local threshold benchmark used unexpected threshold profile")
    if not threshold_report.get("checks"):
        findings.append("local threshold benchmark did not record threshold checks")
    return findings


def _validate_benchmark_failure(target_dir: Path, thresholds: dict[str, Any]) -> list[str]:
    stricter = copy.deepcopy(thresholds)
    stricter["profiles"]["local_classifier"]["route_accuracy_min"] = 0.99
    stricter_path = target_dir / "intentionally_failing_thresholds.json"
    stricter_path.write_text(json.dumps(stricter, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_dir = target_dir / "local-fail"
    completed = _run_benchmark(
        [
            "--thresholds",
            str(stricter_path),
            "--output",
            str(output_dir),
            "--json",
        ]
    )
    findings: list[str] = []
    if completed.returncode == 0:
        findings.append("benchmark should fail when route_accuracy_min is raised above measured result")
        return findings
    summary = _load_json(output_dir / "summary.json", findings, "intentional fail summary")
    if not summary:
        return findings
    threshold_report = summary.get("thresholds") or {}
    if threshold_report.get("status") != "fail":
        findings.append("intentional fail summary did not record threshold failure")
    failure_metrics = {failure.get("metric") for failure in threshold_report.get("failures", [])}
    if "route_accuracy" not in failure_metrics:
        findings.append("intentional fail summary did not include route_accuracy failure")
    return findings


def _run_benchmark(extra_args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(BENCHMARK_TOOL.relative_to(REPO_ROOT)), *extra_args],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
        check=False,
    )


def _load_json(path: Path, findings: list[str], label: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        findings.append(f"cannot load {label}: {exc}")
        return None
    if not isinstance(payload, dict):
        findings.append(f"{label} must be a JSON object")
        return None
    return payload


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


if __name__ == "__main__":
    raise SystemExit(main())
