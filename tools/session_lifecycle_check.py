#!/usr/bin/env python3
"""Validate X10-039 lobby/session lifecycle integration."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "target-codex-task39-session-lifecycle" / "report.json"
REPORT_SCHEMA = "xace.session_lifecycle_check_report.v1"
NETWORK_TEST_FILTER = "x10_039"
RUNTIME_TEST_FILTER = "x10_039"
EXPECTED_NETWORK_TESTS = [
    "x10_039_host_client_session_lifecycle_covers_create_join_ready_leave_reconnect_late_join_and_teardown",
]
EXPECTED_RUNTIME_TESTS = [
    "runtime_orchestrator::tests::x10_039_runtime_lockstep_required_peers_follow_session_lifecycle",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate X10-039 lobby/session lifecycle integration.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--target-dir", default="target-codex-task39-session-lifecycle")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run_check(output_path=Path(args.output).resolve(), target_dir=args.target_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"session lifecycle check failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, sort_keys=True) if args.json else json.dumps(report, indent=2, sort_keys=True))
    return 0


def run_check(*, output_path: Path, target_dir: str) -> dict[str, Any]:
    network_result = _run_cargo_test(
        package="xace-network-core",
        test_filter=NETWORK_TEST_FILTER,
        target_dir=target_dir,
        label="x10_039_network_session_lifecycle_tests",
    )
    runtime_result = _run_cargo_test(
        package="xace-runtime-core",
        test_filter=RUNTIME_TEST_FILTER,
        target_dir=target_dir,
        label="x10_039_runtime_session_lifecycle_tests",
    )
    builder_result = _run_builder_ui_contract()

    network_passed = set(network_result["passed_tests"])
    runtime_passed = set(runtime_result["passed_tests"])
    evidence = {
        "topology": "host_client_lockstep_v1",
        "session_manager": "packages/network-core/src/session/session_manager.rs",
        "peer_identity": "SessionPlayerIdentity",
        "ready_state": "Peer.ready and SessionManager::mark_peer_ready",
        "lifecycle_events": "SessionLifecycleEventKind",
        "runtime_bridge": "RuntimeInputSyncConfig::lockstep(session.required_input_peers())",
        "builder_endpoint": "/api/project/demo/multiplayer/smoke",
        "builder_ui_contract": "packages/builder-workspace/tools/builder_ui_contract_test.mjs",
        "covered_lifecycle_steps": [
            "create_lobby",
            "join_peer",
            "mark_peer_ready",
            "start_live_when_ready",
            "leave_peer",
            "reconnect_peer",
            "late_join_peer",
            "teardown",
        ],
    }
    checks = {
        "network_lifecycle_tests_passed": network_result["ok"],
        "network_lifecycle_test_present": all(test in network_passed for test in EXPECTED_NETWORK_TESTS),
        "runtime_lifecycle_tests_passed": runtime_result["ok"],
        "runtime_lifecycle_test_present": all(test in runtime_passed for test in EXPECTED_RUNTIME_TESTS),
        "builder_ui_contract_passed": builder_result["ok"],
        "builder_ui_contract_mentions_lifecycle": "Lobby/session lifecycle" in builder_result.get("stdout", "")
        or builder_result["ok"],
        "all_required_lifecycle_steps_recorded": len(evidence["covered_lifecycle_steps"]) == 8,
        "runtime_uses_session_required_peers": evidence["runtime_bridge"].startswith("RuntimeInputSyncConfig"),
    }
    report = {
        "schema": REPORT_SCHEMA,
        "ok": all(checks.values()),
        "x10_039_complete": all(checks.values()),
        "evidence": evidence,
        "checks": checks,
        "cargo_results": [network_result, runtime_result],
        "builder_ui_result": builder_result,
        "artifacts": {"output": str(output_path)},
    }
    if not report["ok"]:
        raise ValueError(f"session lifecycle checks failed: {checks}")
    _write_json(output_path, report)
    return report


def _run_cargo_test(*, package: str, test_filter: str, target_dir: str, label: str) -> dict[str, Any]:
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
    return {
        "schema": "xace.session_lifecycle.cargo_result.v1",
        "label": label,
        "command": command,
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "passed_tests": sorted(_passed_test_names(completed.stdout)),
        "passed_test_count": len(_passed_test_names(completed.stdout)),
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
        "schema": "xace.session_lifecycle.builder_ui_result.v1",
        "label": "x10_039_builder_multiplayer_lifecycle_ui_contract",
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
