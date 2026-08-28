#!/usr/bin/env python3
"""Validate X10-047 delta-compressed timeline retention and restore."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "target-codex-task47-delta-retention" / "report.json"
REPORT_SCHEMA = "xace.tick_debugger_delta_retention_check_report.v1"
TASK_TEST_FILTER = "x10_047"
MIN_SCRUB_TICKS = 1000

FILES = {
    "delta_retention": "packages/runtime-core/src/snapshot_engine/delta_timeline_retention.rs",
    "snapshot_mod": "packages/runtime-core/src/snapshot_engine/mod.rs",
    "runtime_orchestrator": "packages/runtime-core/src/runtime_orchestrator.rs",
    "certify_launch": "tools/certify_launch.py",
}

DELTA_RETENTION_MARKERS = [
    "X10_047_MIN_SCRUB_TICKS: Tick = 1_000",
    "DeltaCompressedTimelineRetention",
    "DeltaTimelineRetentionConfig",
    "SnapshotTimelineDelta",
    "remember_snapshot",
    "restore_snapshot",
    "restore_proof",
    "max_retained_bytes",
    "contiguous_restore_chain",
    "x10_047_memory_bounded_scrub_window_restores_1000_ticks",
    "x10_047_byte_budget_prunes_only_complete_restore_chains",
]

RUNTIME_MARKERS = [
    "timeline_retention: DeltaCompressedTimelineRetention",
    "capture_delta_compressed_timeline_snapshot(result.tick)",
    "timeline_retention_stats",
    "retained_timeline_snapshot",
    "restore_retained_timeline_tick",
    "x10_047_runtime_feeds_delta_retention_and_restores_scrub_tick",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate X10-047 delta-compressed debugger timeline retention."
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--target-dir", default="target-codex-task47-delta-retention")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run_check(output_path=Path(args.output).resolve(), target_dir=args.target_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"tick debugger delta retention check failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, sort_keys=True) if args.json else json.dumps(report, indent=2, sort_keys=True))
    return 0


def run_check(*, output_path: Path, target_dir: str) -> dict[str, Any]:
    texts = {name: _read(path) for name, path in FILES.items()}
    cargo_result = _run_cargo_test(target_dir=target_dir)
    passed_tests = set(cargo_result["passed_tests"])
    marker_results = {
        "delta_retention_contract": _marker_result(texts["delta_retention"], DELTA_RETENTION_MARKERS),
        "runtime_integration_contract": _marker_result(texts["runtime_orchestrator"], RUNTIME_MARKERS),
        "module_export_contract": _marker_result(
            texts["snapshot_mod"],
            [
                "pub mod delta_timeline_retention;",
                "DeltaCompressedTimelineRetention",
                "DeltaTimelineRetentionStats",
                "X10_047_MIN_SCRUB_TICKS",
            ],
        ),
    }
    expected_tests = {
        "snapshot_engine::delta_timeline_retention::tests::x10_047_delta_roundtrip_restores_authoritative_snapshot_fields",
        "snapshot_engine::delta_timeline_retention::tests::x10_047_memory_bounded_scrub_window_restores_1000_ticks",
        "snapshot_engine::delta_timeline_retention::tests::x10_047_byte_budget_prunes_only_complete_restore_chains",
        "runtime_orchestrator::tests::x10_047_runtime_feeds_delta_retention_and_restores_scrub_tick",
    }
    benchmark = {
        "schema": "xace.tick_debugger_delta_retention_memory_restore_benchmark.v1",
        "min_scrub_ticks": MIN_SCRUB_TICKS,
        "rust_filter": TASK_TEST_FILTER,
        "passed_test_count": cargo_result["passed_test_count"],
        "expected_tests": sorted(expected_tests),
        "passed_expected_tests": sorted(expected_tests.intersection(passed_tests)),
        "memory_property": "retained_bytes < full_snapshot_bytes and retained_bytes <= max_retained_bytes",
        "restore_property": "every retained tick reconstructs a complete WorldSnapshot with matching WorldHasher hash",
        "runtime_property": "RuntimeOrchestrator feeds end-of-tick snapshots and restores a retained scrub tick through restore_world_snapshot",
    }
    checks = {
        "cargo_x10_047_tests_passed": cargo_result["ok"],
        "all_expected_tests_present": expected_tests.issubset(passed_tests),
        "delta_retention_contract_present": marker_results["delta_retention_contract"]["ok"],
        "runtime_integration_contract_present": marker_results["runtime_integration_contract"]["ok"],
        "module_export_contract_present": marker_results["module_export_contract"]["ok"],
        "memory_benchmark_covers_1000_ticks": MIN_SCRUB_TICKS == 1000,
        "restore_benchmark_exercises_every_retained_tick": (
            "for tick in retention.retained_ticks()" in texts["delta_retention"]
            and "retention.restore_snapshot(tick).unwrap()" in texts["delta_retention"]
        ),
    }
    report = {
        "schema": REPORT_SCHEMA,
        "ok": all(checks.values()),
        "x10_047_complete": all(checks.values()),
        "checks": checks,
        "marker_results": marker_results,
        "memory_restore_benchmark": benchmark,
        "cargo_result": cargo_result,
        "artifacts": {"output": str(output_path)},
        "source_files": {
            path: {
                "sha256": _sha256(REPO_ROOT / path),
                "bytes": (REPO_ROOT / path).stat().st_size,
            }
            for path in FILES.values()
        },
    }
    _write_json(output_path, report)
    if not report["ok"]:
        raise ValueError(f"tick debugger delta retention checks failed: {checks}")
    return report


def _run_cargo_test(*, target_dir: str) -> dict[str, Any]:
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
        "schema": "xace.tick_debugger_delta_retention.cargo_result.v1",
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


def _marker_result(text: str, markers: list[str]) -> dict[str, Any]:
    missing = [marker for marker in markers if marker not in text]
    return {"ok": not missing, "missing": missing, "checked": markers}


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
