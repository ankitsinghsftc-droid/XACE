#!/usr/bin/env python3
"""Run the X10-043 deterministic network chaos proof."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET_DIR = "target-codex-task43-network-chaos"
DEFAULT_OUTPUT = REPO_ROOT / DEFAULT_TARGET_DIR / "report.json"
REPORT_SCHEMA = "xace.network_chaos_proof_wrapper.v1"
EXPECTED_TEST = "x10_043_network_chaos_quick_profiles_cover_required_events_without_permanent_desync"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run X10-043 network chaos proof.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--target-dir", default=DEFAULT_TARGET_DIR)
    parser.add_argument("--proof-root", default=str(REPO_ROOT / ".xace" / "proof" / "network-chaos"))
    parser.add_argument("--run-id", default="")
    parser.add_argument("--client-counts", default="4,8,16")
    parser.add_argument("--duration-minutes", type=int, default=60)
    parser.add_argument("--duration-ticks", type=int, default=0)
    parser.add_argument("--tick-rate-hz", type=int, default=60)
    parser.add_argument("--quick", action="store_true", help="Run the short 60-tick proof profile; does not complete X10-043.")
    parser.add_argument("--full", action="store_true", help="Require the configured duration to satisfy the 60-minute X10-043 gate.")
    parser.add_argument("--release", action="store_true", help="Run the Rust proof binary in release mode.")
    parser.add_argument("--skip-cargo-test", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run(args)
    except Exception as exc:  # noqa: BLE001
        print(f"network chaos proof failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, sort_keys=True) if args.json else json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_path = Path(args.output).resolve()
    run_id = args.run_id.strip() or f"x10-043-{'full' if args.full else 'quick'}-{int(time.time())}"
    proof_dir = Path(args.proof_root).resolve() / run_id
    rust_report_path = proof_dir / "network_chaos_report.json"
    proof_dir.mkdir(parents=True, exist_ok=True)

    cargo_test = None if args.skip_cargo_test else _run_cargo_test(args.target_dir)
    rust_result = _run_rust_proof(args, rust_report_path)
    rust_report = json.loads(rust_report_path.read_text(encoding="utf-8"))

    checks = {
        "cargo_quick_test_passed": True if cargo_test is None else cargo_test["ok"],
        "cargo_quick_test_present": True if cargo_test is None else EXPECTED_TEST in cargo_test["passed_tests"],
        "rust_proof_binary_passed": rust_result["ok"],
        "client_count_coverage": rust_report["summary"].get("min_client_count") <= 4 and rust_report["summary"].get("max_client_count") >= 16,
        "all_required_events_met": bool(rust_report["summary"].get("all_required_events_met")),
        "zero_permanent_desync": bool(rust_report["summary"].get("zero_permanent_desync")),
        "duration_requirement_met": bool(rust_report["summary"].get("duration_requirement_met")),
        "certification_complete_when_full": (not args.full) or bool(rust_report.get("certification_complete")),
    }
    ok = all(checks.values()) if args.full else all(
        value for key, value in checks.items() if key not in {"duration_requirement_met", "certification_complete_when_full"}
    )
    report = {
        "schema": REPORT_SCHEMA,
        "ok": ok,
        "x10_043_complete": bool(args.full and rust_report.get("certification_complete") and all(checks.values())),
        "mode": "full" if args.full else "quick",
        "run_id": run_id,
        "proof_dir": str(proof_dir),
        "rust_report": str(rust_report_path),
        "checks": checks,
        "cargo_test": cargo_test,
        "rust_result": rust_result,
        "summary": rust_report.get("summary", {}),
        "artifacts": {"output": str(output_path)},
    }
    _write_json(output_path, report)
    if args.full and not report["x10_043_complete"]:
        raise ValueError(f"full network chaos proof did not complete X10-043: {checks}")
    if not report["ok"]:
        raise ValueError(f"network chaos proof checks failed: {checks}")
    return report


def _run_cargo_test(target_dir: str) -> dict[str, Any]:
    command = ["cargo", "test", "-p", "xace-network-core", "x10_043", "--target-dir", target_dir]
    completed = subprocess.run(command, cwd=REPO_ROOT, check=False, text=True, capture_output=True)
    return {
        "schema": "xace.network_chaos.cargo_test_result.v1",
        "command": command,
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "passed_tests": sorted(_passed_test_names(completed.stdout)),
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
    }


def _run_rust_proof(args: argparse.Namespace, rust_report_path: Path) -> dict[str, Any]:
    command = ["cargo", "run"]
    if args.release:
        command.append("--release")
    command.extend([
        "-p",
        "xace-network-core",
        "--bin",
        "network_chaos_proof",
        "--target-dir",
        args.target_dir,
        "--",
        "--output",
        str(rust_report_path),
        "--client-counts",
        args.client_counts,
        "--tick-rate-hz",
        str(args.tick_rate_hz),
    ])
    if args.quick:
        command.extend(["--quick", "--duration-ticks", str(args.duration_ticks or 60)])
    elif args.duration_ticks:
        command.extend(["--duration-ticks", str(args.duration_ticks)])
    else:
        command.extend(["--duration-minutes", str(args.duration_minutes)])
    if args.full:
        command.append("--require-certification")

    started = time.perf_counter()
    completed = subprocess.run(command, cwd=REPO_ROOT, check=False, text=True, capture_output=True)
    return {
        "schema": "xace.network_chaos.rust_binary_result.v1",
        "command": command,
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
    }


def _passed_test_names(stdout: str) -> set[str]:
    passed: set[str] = set()
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("test ") and stripped.endswith(" ... ok"):
            passed.add(stripped.removeprefix("test ").removesuffix(" ... ok"))
    return passed


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
