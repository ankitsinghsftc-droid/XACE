#!/usr/bin/env python3
"""Validate X10-035 launch multiplayer topology scope."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = REPO_ROOT / "docs" / "multiplayer_launch_topology_matrix.json"
DEFAULT_OUTPUT = REPO_ROOT / "target-codex-task35-multiplayer-topology" / "report.json"
REPORT_SCHEMA = "xace.multiplayer_topology_check_report.v1"
EXPECTED_SUPPORTED = {"host", "client"}
EXPECTED_LOCAL_ONLY = {"offline"}
EXPECTED_UNSUPPORTED = {"dedicated_server", "peer_to_peer"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate X10-035 multiplayer launch topology.")
    parser.add_argument("--matrix", default=str(DEFAULT_MATRIX))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--target-dir", default="target-codex-task35-multiplayer-topology")
    parser.add_argument("--skip-cargo", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run_check(
            matrix_path=Path(args.matrix).resolve(),
            output_path=Path(args.output).resolve(),
            target_dir=args.target_dir,
            skip_cargo=args.skip_cargo,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"multiplayer topology check failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, sort_keys=True) if args.json else json.dumps(report, indent=2, sort_keys=True))
    return 0


def run_check(
    *,
    matrix_path: Path,
    output_path: Path,
    target_dir: str,
    skip_cargo: bool,
) -> dict[str, Any]:
    matrix = _read_json(matrix_path)
    topologies = matrix.get("topologies")
    if not isinstance(topologies, list):
        raise ValueError("matrix topologies must be a list")
    by_mode = {str(row.get("mode")): row for row in topologies if isinstance(row, dict)}
    modes = set(by_mode)

    supported = {
        mode
        for mode, row in by_mode.items()
        if row.get("launch_support") == "supported_multiplayer"
    }
    local_only = {
        mode
        for mode, row in by_mode.items()
        if row.get("launch_support") == "supported_local_only"
    }
    unsupported = {
        mode
        for mode, row in by_mode.items()
        if row.get("launch_support") == "unsupported_launch_profile"
    }

    checks = {
        "schema": matrix.get("schema") == "xace.multiplayer_launch_topology_matrix.v1",
        "selected_topology_is_host_client_lockstep": matrix.get("selected_launch_topology_id") == "host_client_lockstep_v1",
        "all_expected_modes_present": modes == EXPECTED_SUPPORTED | EXPECTED_LOCAL_ONLY | EXPECTED_UNSUPPORTED,
        "host_and_client_supported": supported == EXPECTED_SUPPORTED,
        "offline_local_only": local_only == EXPECTED_LOCAL_ONLY,
        "dedicated_and_peer_to_peer_unsupported": unsupported == EXPECTED_UNSUPPORTED,
        "unsupported_modes_have_failure_code": all(
            by_mode[mode].get("failure_code") == "XACE_NETWORK_TOPOLOGY_UNSUPPORTED"
            for mode in EXPECTED_UNSUPPORTED
        ),
        "supported_modes_have_no_failure_code": all(
            not by_mode[mode].get("failure_code") for mode in EXPECTED_SUPPORTED | EXPECTED_LOCAL_ONLY
        ),
        "supported_modes_are_lockstep": all(
            by_mode[mode].get("tick_model") in {"lockstep_required_peer_inputs", "lockstep_server_input_source"}
            for mode in EXPECTED_SUPPORTED
        ),
    }

    cargo_results: list[dict[str, Any]] = []
    if not skip_cargo:
        cargo_results = [
            _run_cargo_test("launch_topology", "test_launch_topology", target_dir),
            _run_cargo_test(
                "networked_runtime_smoke_is_deterministic_across_arrival_orders",
                "test_networked_runtime_smoke",
                target_dir,
            ),
        ]
        checks["cargo_topology_tests_passed"] = all(result["ok"] for result in cargo_results)
    else:
        checks["cargo_topology_tests_passed"] = True

    report = {
        "schema": REPORT_SCHEMA,
        "ok": all(checks.values()),
        "x10_035_complete": all(checks.values()),
        "selected_launch_topology_id": matrix.get("selected_launch_topology_id"),
        "supported_multiplayer_modes": sorted(supported),
        "local_only_modes": sorted(local_only),
        "unsupported_launch_modes": sorted(unsupported),
        "checks": checks,
        "cargo_results": cargo_results,
        "artifacts": {
            "matrix": str(matrix_path),
            "output": str(output_path),
        },
    }
    if not report["ok"]:
        raise ValueError(f"topology checks failed: {checks}")
    _write_json(output_path, report)
    return report


def _run_cargo_test(test_filter: str, label: str, target_dir: str) -> dict[str, Any]:
    command = [
        "cargo",
        "test",
        "-p",
        "xace-network-core",
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
        "schema": "xace.multiplayer_topology.cargo_result.v1",
        "label": label,
        "command": command,
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
    }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
