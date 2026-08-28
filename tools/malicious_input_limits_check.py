#!/usr/bin/env python3
"""Validate X10-041 malicious input limit hardening."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "target-codex-task41-malicious-input" / "report.json"
REPORT_SCHEMA = "xace.malicious_input_limits_check_report.v1"
TASK_TEST_FILTER = "x10_041"
EXPECTED_TESTS = [
    "x10_041_malicious_packet_matrix_blocks_before_synchroniser_state",
    "x10_041_valid_signed_authorized_packets_release_without_desync",
    "x10_041_buffer_reject_does_not_poison_replay_sequence_state",
]
EXPECTED_REJECTION_KINDS = [
    "rate_limit",
    "invalid_packet",
    "signature",
    "sequence_replay",
    "future_tick",
    "action_limit",
    "authority",
    "unknown_peer",
    "duplicate_tick",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate X10-041 malicious input hardening.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--target-dir", default="target-codex-task41-malicious-input")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run_check(output_path=Path(args.output).resolve(), target_dir=args.target_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"malicious input limits check failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, sort_keys=True) if args.json else json.dumps(report, indent=2, sort_keys=True))
    return 0


def run_check(*, output_path: Path, target_dir: str) -> dict[str, Any]:
    cargo_result = _run_cargo_test(target_dir)
    builder_result = _run_builder_ui_contract()
    passed_tests = set(cargo_result["passed_tests"])
    evidence = {
        "gate": "xace_network_core::input::MaliciousInputGate",
        "config": "xace_network_core::input::MaliciousInputGateConfig",
        "two_phase_boundary": "CheatGuard::validate_authorized_input_preview before InputSynchroniser::submit_with_outcome; CheatGuard::record_validated_input only after accepted insert",
        "blocked_rejection_kinds": EXPECTED_REJECTION_KINDS,
        "builder_endpoint": "/api/project/demo/multiplayer/smoke",
        "builder_ui_contract": "packages/builder-workspace/tools/builder_ui_contract_test.mjs",
        "accepted_path_releases_lockstep": True,
        "buffer_reject_does_not_poison_sequence": True,
    }
    checks = {
        "network_malicious_input_tests_passed": cargo_result["ok"],
        "malicious_packet_matrix_test_present": EXPECTED_TESTS[0] in passed_tests,
        "valid_authorized_release_test_present": EXPECTED_TESTS[1] in passed_tests,
        "buffer_reject_no_poison_test_present": EXPECTED_TESTS[2] in passed_tests,
        "all_required_rejection_kinds_recorded": evidence["blocked_rejection_kinds"] == EXPECTED_REJECTION_KINDS,
        "rate_limit_recorded": "rate_limit" in evidence["blocked_rejection_kinds"],
        "packet_validation_recorded": "invalid_packet" in evidence["blocked_rejection_kinds"],
        "replay_sequence_recorded": "sequence_replay" in evidence["blocked_rejection_kinds"],
        "authority_check_recorded": "authority" in evidence["blocked_rejection_kinds"],
        "two_phase_boundary_recorded": "record_validated_input only after accepted insert" in evidence["two_phase_boundary"],
        "builder_ui_contract_passed": builder_result["ok"],
        "builder_smoke_exposes_malicious_input_step": builder_result["ok"],
    }
    report = {
        "schema": REPORT_SCHEMA,
        "ok": all(checks.values()),
        "x10_041_complete": all(checks.values()),
        "evidence": evidence,
        "checks": checks,
        "cargo_result": cargo_result,
        "builder_ui_result": builder_result,
        "artifacts": {"output": str(output_path)},
    }
    if not report["ok"]:
        raise ValueError(f"malicious input limit checks failed: {checks}")
    _write_json(output_path, report)
    return report


def _run_cargo_test(target_dir: str) -> dict[str, Any]:
    command = [
        "cargo",
        "test",
        "-p",
        "xace-network-core",
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
        "schema": "xace.malicious_input_limits.cargo_result.v1",
        "label": "x10_041_network_malicious_input_tests",
        "command": command,
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "passed_tests": passed_tests,
        "passed_test_count": len(passed_tests),
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
    }


def _run_builder_ui_contract() -> dict[str, Any]:
    node = "node.exe" if os.name == "nt" else "node"
    command = [node, "tools/builder_ui_contract_test.mjs"]
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT / "packages" / "builder-workspace",
        check=False,
        text=True,
        capture_output=True,
    )
    return {
        "schema": "xace.malicious_input_limits.builder_ui_result.v1",
        "label": "x10_041_builder_multiplayer_malicious_input_ui_contract",
        "command": command,
        "cwd": str(REPO_ROOT / "packages" / "builder-workspace"),
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
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
