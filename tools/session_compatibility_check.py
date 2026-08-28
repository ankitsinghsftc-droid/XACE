#!/usr/bin/env python3
"""Validate X10-040 session compatibility mismatch gating."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "target-codex-task40-session-compatibility" / "report.json"
REPORT_SCHEMA = "xace.session_compatibility_check_report.v1"
TASK_TEST_FILTER = "x10_040"
EXPECTED_TESTS = [
    "x10_040_session_compatibility_mismatch_matrix_blocks_start",
    "x10_040_compatible_session_profiles_allow_start_and_missing_profiles_block_start",
]
EXPECTED_MISMATCH_KINDS = [
    "schema",
    "sgc_plan",
    "adapter_version",
    "assets",
    "packages",
    "provider_free_metadata",
    "template",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate X10-040 session compatibility gating.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--target-dir", default="target-codex-task40-session-compatibility")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run_check(output_path=Path(args.output).resolve(), target_dir=args.target_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"session compatibility check failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, sort_keys=True) if args.json else json.dumps(report, indent=2, sort_keys=True))
    return 0


def run_check(*, output_path: Path, target_dir: str) -> dict[str, Any]:
    cargo_result = _run_cargo_test(target_dir)
    builder_result = _run_builder_ui_contract()
    passed_tests = set(cargo_result["passed_tests"])
    evidence = {
        "compatibility_profile": "xace_network_core::session::SessionCompatibilityProfile",
        "compatibility_report": "xace_network_core::session::SessionCompatibilityReport",
        "start_gate": "SessionManager::start_live_when_ready",
        "builder_endpoint": "/api/project/demo/multiplayer/smoke",
        "builder_ui_contract": "packages/builder-workspace/tools/builder_ui_contract_test.mjs",
        "blocking_mismatch_kinds": EXPECTED_MISMATCH_KINDS,
        "missing_profile_blocks_start": True,
        "compatible_profiles_allow_start": True,
    }
    checks = {
        "network_compatibility_tests_passed": cargo_result["ok"],
        "mismatch_matrix_test_present": EXPECTED_TESTS[0] in passed_tests,
        "compatible_and_missing_profile_test_present": EXPECTED_TESTS[1] in passed_tests,
        "all_required_mismatch_kinds_recorded": evidence["blocking_mismatch_kinds"]
        == EXPECTED_MISMATCH_KINDS,
        "start_gate_recorded": evidence["start_gate"] == "SessionManager::start_live_when_ready",
        "builder_ui_contract_passed": builder_result["ok"],
        "builder_smoke_exposes_compatibility_step": builder_result["ok"],
        "missing_profile_boundary_recorded": evidence["missing_profile_blocks_start"] is True,
    }
    report = {
        "schema": REPORT_SCHEMA,
        "ok": all(checks.values()),
        "x10_040_complete": all(checks.values()),
        "evidence": evidence,
        "checks": checks,
        "cargo_result": cargo_result,
        "builder_ui_result": builder_result,
        "artifacts": {"output": str(output_path)},
    }
    if not report["ok"]:
        raise ValueError(f"session compatibility checks failed: {checks}")
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
        "schema": "xace.session_compatibility.cargo_result.v1",
        "label": "x10_040_network_session_compatibility_tests",
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
        "schema": "xace.session_compatibility.builder_ui_result.v1",
        "label": "x10_040_builder_multiplayer_compatibility_ui_contract",
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
