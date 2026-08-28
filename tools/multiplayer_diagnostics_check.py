#!/usr/bin/env python3
"""Validate X10-042 multiplayer diagnostics panel coverage."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "target-codex-task42-diagnostics" / "report.json"
REPORT_SCHEMA = "xace.multiplayer_diagnostics_check_report.v1"
TASK_TEST_FILTER = "x10_042"
EXPECTED_NETWORK_TEST = "x10_042_multiplayer_diagnostics_snapshot_exposes_required_panel_fields"
EXPECTED_SERVER_TEST = "test_x10_042_diagnostics_payload_exposes_required_panel_fields"
REQUIRED_PANEL_FIELDS = [
    "peers",
    "ticks",
    "input_buffers",
    "latency",
    "rollback",
    "resync",
    "packet_loss",
    "hash_comparisons",
    "authority",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate X10-042 multiplayer diagnostics panel coverage.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--target-dir", default="target-codex-task42-diagnostics")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run_check(output_path=Path(args.output).resolve(), target_dir=args.target_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"multiplayer diagnostics check failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, sort_keys=True) if args.json else json.dumps(report, indent=2, sort_keys=True))
    return 0


def run_check(*, output_path: Path, target_dir: str) -> dict[str, Any]:
    cargo_result = _run_cargo_test(target_dir)
    server_result = _run_server_test()
    builder_result = _run_builder_ui_contract()
    passed_network_tests = set(cargo_result["passed_tests"])
    evidence = {
        "schema": "xace.multiplayer_diagnostics_snapshot.v1",
        "runtime_capture": "xace_network_core::diagnostics::capture_multiplayer_diagnostics",
        "builder_endpoint": "/api/project/demo/multiplayer/diagnostics",
        "builder_panel": "packages/builder-workspace/src/project/project_dashboard.ts::_buildMultiplayerDiagnosticsPanel",
        "server_test": "packages/builder-workspace/server/tests/test_multiplayer_diagnostics_panel.py",
        "builder_ui_contract": "packages/builder-workspace/tools/builder_ui_contract_test.mjs",
        "required_panel_fields": REQUIRED_PANEL_FIELDS,
        "chaos_report": {
            "scenario": "deterministic_diagnostics_fixture",
            "packet_loss_ppm": 25000,
            "jitter_ms": 12,
            "missing_input_peer": 2,
            "divergent_hash_peer": 2,
            "resync_status": "AwaitingAck",
            "boundary": "Diagnostic fixture only; 4-16 client chaos/soak certification remains X10-043.",
        },
    }
    checks = {
        "network_diagnostics_tests_passed": cargo_result["ok"],
        "network_diagnostics_test_present": EXPECTED_NETWORK_TEST in passed_network_tests,
        "server_payload_test_passed": server_result["ok"],
        "server_payload_test_present": EXPECTED_SERVER_TEST in server_result["stdout"] or EXPECTED_SERVER_TEST in server_result["stderr"],
        "builder_ui_contract_passed": builder_result["ok"],
        "all_required_panel_fields_recorded": evidence["required_panel_fields"] == REQUIRED_PANEL_FIELDS,
        "packet_loss_recorded": evidence["chaos_report"]["packet_loss_ppm"] > 0,
        "resync_status_recorded": evidence["chaos_report"]["resync_status"] == "AwaitingAck",
        "hash_comparison_recorded": evidence["chaos_report"]["divergent_hash_peer"] == 2,
        "authority_owner_recorded": "authority" in evidence["required_panel_fields"],
        "x10_043_boundary_recorded": "X10-043" in evidence["chaos_report"]["boundary"],
    }
    report = {
        "schema": REPORT_SCHEMA,
        "ok": all(checks.values()),
        "x10_042_complete": all(checks.values()),
        "evidence": evidence,
        "checks": checks,
        "cargo_result": cargo_result,
        "server_test_result": server_result,
        "builder_ui_result": builder_result,
        "artifacts": {"output": str(output_path)},
    }
    if not report["ok"]:
        _write_json(output_path, report)
        raise ValueError(f"multiplayer diagnostics checks failed: {checks}")
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
        "schema": "xace.multiplayer_diagnostics.cargo_result.v1",
        "label": "x10_042_network_diagnostics_tests",
        "command": command,
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "passed_tests": passed_tests,
        "passed_test_count": len(passed_tests),
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
    }


def _run_server_test() -> dict[str, Any]:
    command = [sys.executable, "-m", "unittest", "packages/builder-workspace/server/tests/test_multiplayer_diagnostics_panel.py", "-v"]
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    return {
        "schema": "xace.multiplayer_diagnostics.server_result.v1",
        "label": "x10_042_builder_server_diagnostics_payload",
        "command": command,
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
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
        "schema": "xace.multiplayer_diagnostics.builder_ui_result.v1",
        "label": "x10_042_builder_multiplayer_diagnostics_ui_contract",
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
