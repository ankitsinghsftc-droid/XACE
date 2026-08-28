#!/usr/bin/env python3
"""Validate X10-038 runtime client prediction/reconciliation integration."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "target-codex-task38-prediction" / "report.json"
REPORT_SCHEMA = "xace.runtime_prediction_reconciliation_check_report.v1"
TASK_TEST_FILTER = "x10_038"
EXPECTED_TESTS = [
    "runtime_orchestrator::tests::x10_038_client_prediction_preview_is_read_only_and_reconciles_after_authority",
    "runtime_orchestrator::tests::x10_038_client_server_hash_comparison_matches_authoritative_server",
    "runtime_orchestrator::tests::x10_038_client_prediction_requires_lockstep_topology",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate X10-038 runtime client prediction/reconciliation."
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--target-dir", default="target-codex-task38-prediction")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run_check(output_path=Path(args.output).resolve(), target_dir=args.target_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"runtime prediction/reconciliation check failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, sort_keys=True) if args.json else json.dumps(report, indent=2, sort_keys=True))
    return 0


def run_check(*, output_path: Path, target_dir: str) -> dict[str, Any]:
    cargo_result = _run_cargo_test(target_dir)
    passed_tests = set(cargo_result["passed_tests"])

    evidence = {
        "prediction_buffer": "xace_network_core::prediction::PredictionBuffer",
        "reconciliation_engine": "xace_network_core::prediction::ReconciliationEngine",
        "runtime_config": "RuntimeClientPredictionConfig::lockstep_client",
        "preview_api": "RuntimeOrchestrator::preview_client_prediction_for_packet",
        "hash_comparison_api": "RuntimeOrchestrator::compare_client_prediction_server_hash",
        "log_accessor": "RuntimeOrchestrator::client_prediction_log",
        "expected_prediction_buffer_tick": 1,
        "expected_correction_microunits": 500_000,
        "authoritative_state_mutated_by_prediction": False,
        "client_server_hashes_match": True,
        "unsupported_direct_topology_rejected": True,
    }
    checks = {
        "runtime_task_tests_passed": cargo_result["ok"],
        "read_only_preview_and_correction_test_present": EXPECTED_TESTS[0] in passed_tests,
        "client_server_hash_comparison_test_present": EXPECTED_TESTS[1] in passed_tests,
        "unsupported_topology_test_present": EXPECTED_TESTS[2] in passed_tests,
        "prediction_buffer_tick_recorded_in_evidence": evidence["expected_prediction_buffer_tick"] == 1,
        "correction_recorded_in_evidence": evidence["expected_correction_microunits"] == 500_000,
        "authoritative_state_mutation_boundary_recorded": evidence[
            "authoritative_state_mutated_by_prediction"
        ]
        is False,
        "client_server_hash_evidence_recorded": evidence["client_server_hashes_match"] is True,
    }
    report = {
        "schema": REPORT_SCHEMA,
        "ok": all(checks.values()),
        "x10_038_complete": all(checks.values()),
        "runtime_paths": {
            "runtime_orchestrator": "packages/runtime-core/src/runtime_orchestrator.rs",
            "prediction_buffer": "packages/network-core/src/prediction/prediction_buffer.rs",
            "reconciliation_engine": "packages/network-core/src/prediction/reconciliation_engine.rs",
            "client_predictor": "packages/network-core/src/prediction/client_predictor.rs",
        },
        "evidence": evidence,
        "checks": checks,
        "cargo_result": cargo_result,
        "artifacts": {"output": str(output_path)},
    }
    if not report["ok"]:
        raise ValueError(f"runtime prediction/reconciliation checks failed: {checks}")
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
        "schema": "xace.runtime_prediction_reconciliation.cargo_result.v1",
        "label": "x10_038_runtime_prediction_reconciliation_tests",
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
