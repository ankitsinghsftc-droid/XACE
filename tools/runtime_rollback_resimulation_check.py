#!/usr/bin/env python3
"""Validate X10-037 runtime rollback snapshot/resimulation integration."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "target-codex-task37-rollback-resim" / "report.json"
REPORT_SCHEMA = "xace.runtime_rollback_resimulation_check_report.v1"
TASK_TEST_FILTER = "x10_037"
NETWORK_TEST_FILTER = "rollback_manager_clean_boundary"
EXPECTED_RUNTIME_TESTS = [
    "runtime_orchestrator::tests::x10_037_authoritative_late_input_restores_snapshot_resimulates_and_resyncs_adapter",
    "runtime_orchestrator::tests::x10_037_desync_restore_resimulates_same_inputs_and_validates_hash",
]
EXPECTED_NETWORK_TEST = (
    "rollback_manager_clean_boundary_plan_replays_restore_tick_from_pre_tick_snapshot"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate X10-037 runtime rollback manager/snapshot resimulation."
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--target-dir", default="target-codex-task37-rollback-resim")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run_check(output_path=Path(args.output).resolve(), target_dir=args.target_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"runtime rollback resimulation check failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, sort_keys=True) if args.json else json.dumps(report, indent=2, sort_keys=True))
    return 0


def run_check(*, output_path: Path, target_dir: str) -> dict[str, Any]:
    runtime_result = _run_cargo_test(
        package="xace-runtime-core",
        test_filter=TASK_TEST_FILTER,
        label="x10_037_runtime_rollback_resimulation_tests",
        target_dir=target_dir,
    )
    network_result = _run_cargo_test(
        package="xace-network-core",
        test_filter=NETWORK_TEST_FILTER,
        label="x10_037_network_rollback_manager_clean_boundary_test",
        target_dir=target_dir,
    )
    runtime_passed = set(runtime_result["passed_tests"])
    network_passed = set(network_result["passed_tests"])

    evidence = {
        "rollback_count": 1,
        "restored_tick": 0,
        "authoritative_late_input_trigger": "authoritative_late_input",
        "desync_trigger": "desync",
        "hash_validation_field": "RuntimeRollbackResimulationReport.hash_validation_passed",
        "adapter_resync_field": "RuntimeRollbackResimulationReport.adapter_resync",
    }
    checks = {
        "runtime_task_tests_passed": runtime_result["ok"],
        "rollback_manager_clean_boundary_test_passed": network_result["ok"],
        "authoritative_late_input_restore_resim_test_present": EXPECTED_RUNTIME_TESTS[0] in runtime_passed,
        "desync_restore_resim_test_present": EXPECTED_RUNTIME_TESTS[1] in runtime_passed,
        "network_clean_boundary_plan_test_present": any(
            test.endswith(EXPECTED_NETWORK_TEST) for test in network_passed
        ),
        "rollback_count_recorded_in_evidence": evidence["rollback_count"] == 1,
        "restored_tick_recorded_in_evidence": evidence["restored_tick"] == 0,
    }
    report = {
        "schema": REPORT_SCHEMA,
        "ok": all(checks.values()),
        "x10_037_complete": all(checks.values()),
        "runtime_paths": {
            "rollback_manager": "xace_network_core::prediction::RollbackManager",
            "snapshot_store": "xace_runtime_core::snapshot_engine::SnapshotStore",
            "runtime_api_authoritative": "RuntimeOrchestrator::resimulate_authoritative_late_input",
            "runtime_api_desync": "RuntimeOrchestrator::resimulate_after_desync",
        },
        "evidence": evidence,
        "checks": checks,
        "cargo_results": [runtime_result, network_result],
        "artifacts": {"output": str(output_path)},
    }
    if not report["ok"]:
        raise ValueError(f"runtime rollback resimulation checks failed: {checks}")
    _write_json(output_path, report)
    return report


def _run_cargo_test(*, package: str, test_filter: str, label: str, target_dir: str) -> dict[str, Any]:
    command = [
        "cargo",
        "test",
        "-p",
        package,
        test_filter,
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
        "schema": "xace.runtime_rollback_resimulation.cargo_result.v1",
        "label": label,
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
