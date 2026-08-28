#!/usr/bin/env python3
"""Validate X10-036 runtime input synchronisation integration."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "target-codex-task36-input-sync" / "report.json"
REPORT_SCHEMA = "xace.runtime_input_sync_check_report.v1"
TASK_TEST_FILTER = "x10_036"
EXPECTED_TESTS = [
    "runtime_orchestrator::tests::x10_036_runtime_waits_for_missing_lockstep_input_before_tick_advance",
    "runtime_orchestrator::tests::x10_036_delayed_lockstep_input_releases_same_runtime_tick_deterministically",
    "runtime_orchestrator::tests::x10_036_synthetic_timeout_release_advances_with_empty_missing_peer_input",
    "runtime_orchestrator::tests::x10_036_late_released_input_is_not_applied_to_future_tick",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate X10-036 runtime InputSynchroniser integration.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--target-dir", default="target-codex-task36-input-sync")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run_check(output_path=Path(args.output).resolve(), target_dir=args.target_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"runtime input sync check failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, sort_keys=True) if args.json else json.dumps(report, indent=2, sort_keys=True))
    return 0


def run_check(*, output_path: Path, target_dir: str) -> dict[str, Any]:
    cargo_result = _run_cargo_test(target_dir)
    passed_tests = set(cargo_result["passed_tests"])

    checks = {
        "runtime_task_tests_passed": cargo_result["ok"],
        "missing_input_wait_test_present": EXPECTED_TESTS[0] in passed_tests,
        "delayed_input_release_test_present": EXPECTED_TESTS[1] in passed_tests,
        "synthetic_timeout_release_test_present": EXPECTED_TESTS[2] in passed_tests,
        "late_released_input_test_present": EXPECTED_TESTS[3] in passed_tests,
    }
    report = {
        "schema": REPORT_SCHEMA,
        "ok": all(checks.values()),
        "x10_036_complete": all(checks.values()),
        "lockstep_source": "xace_network_core::input::InputSynchroniser",
        "runtime_gate": "RuntimeOrchestrator::synchronise_and_apply_engine_inputs",
        "decisions_covered": ["wait", "release", "synthetic_timeout_release", "late_after_release"],
        "checks": checks,
        "cargo_result": cargo_result,
        "artifacts": {"output": str(output_path)},
    }
    if not report["ok"]:
        raise ValueError(f"runtime input sync checks failed: {checks}")
    _write_json(output_path, report)
    return report


def _run_cargo_test(target_dir: str) -> dict[str, Any]:
    command = [
        "cargo",
        "test",
        "-p",
        "xace-runtime-core",
        TASK_TEST_FILTER,
        "--target-dir",
        target_dir,
    ]
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    passed_tests = sorted(_passed_test_names(completed.stdout))
    return {
        "schema": "xace.runtime_input_sync.cargo_result.v1",
        "label": "x10_036_runtime_input_sync_tests",
        "command": command,
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "passed_tests": passed_tests,
        "passed_test_count": len(passed_tests),
    }


def _passed_test_names(stdout: str) -> set[str]:
    passed: set[str] = set()
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped.startswith("test ") or not stripped.endswith(" ... ok"):
            continue
        passed.add(stripped.removeprefix("test ").removesuffix(" ... ok"))
    return passed


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
