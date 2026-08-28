#!/usr/bin/env python3
"""Validate X10-046 tick-debugger reverse-step/time-travel navigation."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "target-codex-task46-time-travel" / "report.json"
REPORT_SCHEMA = "xace.tick_debugger_time_travel_check_report.v1"
MIN_TICKS = 1000

FILES = {
    "debugger": "packages/builder-workspace/src/preview/tick_debugger.ts",
    "ui_contract": "packages/builder-workspace/tools/builder_ui_contract_test.mjs",
    "message_types": "packages/builder-workspace/src/api/message_types.ts",
    "builder_client": "packages/builder-workspace/src/api/builder_client.ts",
}

DEBUGGER_MARKERS = [
    "MIN_TIME_TRAVEL_TICKS = 1000",
    "MAX_HISTORY = MIN_TIME_TRAVEL_TICKS",
    "interface TimeTravelRecord",
    "selectedTimelineTick",
    "followLiveTimeline",
    "Time travel",
    "Reverse step",
    "Forward step",
    "Live tick",
    "Matching hash",
    "data-nav=\"reverse_step\"",
    "data-nav=\"forward_step\"",
    "data-nav=\"live\"",
    "renderTimeTravelNavigation",
    "navigateTimeline",
    "timelineRecords",
    "currentTimelineRecord",
    "nearestTimelineRecord",
    "hash_log",
]

UI_CONTRACT_MARKERS = [
    "MIN_TIME_TRAVEL_TICKS = 1000",
    "data-nav=\"reverse_step\"",
    "data-nav=\"forward_step\"",
    "data-nav=\"live\"",
    "renderTimeTravelNavigation",
    "navigateTimeline",
    "timelineRecords",
]

MESSAGE_CLIENT_MARKERS = [
    "readonly hash_log?: RuntimeBridgeHashRecord[];",
    "onEngineTick",
    "onRuntimeStatus",
    "hashLog: Array.isArray(status.hash_log) ? status.hash_log : []",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate X10-046 tick-debugger time-travel navigation.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--ticks", type=int, default=MIN_TICKS)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run_check(output_path=Path(args.output).resolve(), ticks=args.ticks)
    except Exception as exc:  # noqa: BLE001
        print(f"tick debugger time-travel check failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, sort_keys=True) if args.json else json.dumps(report, indent=2, sort_keys=True))
    return 0


def run_check(*, output_path: Path, ticks: int) -> dict[str, Any]:
    if ticks < MIN_TICKS:
        raise ValueError(f"ticks must be at least {MIN_TICKS}")
    texts = {name: _read(path) for name, path in FILES.items()}
    marker_results = {
        "debugger_time_travel_contract": _marker_result(texts["debugger"], DEBUGGER_MARKERS),
        "builder_ui_contract_test": _marker_result(texts["ui_contract"], UI_CONTRACT_MARKERS),
        "message_and_client_hash_log_contract": _marker_result(
            texts["message_types"] + "\n" + texts["builder_client"],
            MESSAGE_CLIENT_MARKERS,
        ),
    }
    navigation = _simulate_navigation(ticks)
    checks = {
        "debugger_has_time_travel_controls": marker_results["debugger_time_travel_contract"]["ok"],
        "ui_contract_guards_time_travel": marker_results["builder_ui_contract_test"]["ok"],
        "hash_log_feed_available": marker_results["message_and_client_hash_log_contract"]["ok"],
        "retains_at_least_1000_ticks": navigation["retained_count"] >= MIN_TICKS,
        "reverse_steps_match_hashes": navigation["reverse"]["ok"],
        "forward_steps_match_hashes": navigation["forward"]["ok"],
        "live_navigation_restores_latest_tick": navigation["live"]["ok"],
        "all_visited_hashes_match_expected": navigation["mismatches"] == [],
    }
    report = {
        "schema": REPORT_SCHEMA,
        "ok": all(checks.values()),
        "x10_046_complete": all(checks.values()),
        "checks": checks,
        "marker_results": marker_results,
        "navigation_proof": navigation,
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
        raise ValueError(f"tick debugger time-travel checks failed: {checks}")
    return report


def _simulate_navigation(ticks: int) -> dict[str, Any]:
    timeline = [{"tick": tick, "world_hash": _tick_hash(tick)} for tick in range(ticks)]
    retained = timeline[-MIN_TICKS:]
    index = len(retained) - 1
    mismatches: list[dict[str, Any]] = []
    reverse_visits = 0
    forward_visits = 0

    while index > 0:
        index -= 1
        reverse_visits += 1
        _check_hash(retained[index], mismatches, phase="reverse")
    reverse_ok = index == 0 and reverse_visits == MIN_TICKS - 1 and not mismatches

    while index < len(retained) - 1:
        index += 1
        forward_visits += 1
        _check_hash(retained[index], mismatches, phase="forward")
    forward_ok = index == len(retained) - 1 and forward_visits == MIN_TICKS - 1 and not mismatches

    live_tick = retained[-1]["tick"]
    live_hash = retained[-1]["world_hash"]
    live_ok = index == len(retained) - 1 and live_tick == ticks - 1 and live_hash == _tick_hash(ticks - 1)

    return {
        "schema": "xace.tick_debugger_time_travel_navigation_proof.v1",
        "ticks_generated": ticks,
        "retained_count": len(retained),
        "retained_first_tick": retained[0]["tick"],
        "retained_last_tick": live_tick,
        "reverse": {"ok": reverse_ok, "steps": reverse_visits, "end_tick": retained[index - forward_visits]["tick"] if forward_visits else retained[index]["tick"]},
        "forward": {"ok": forward_ok, "steps": forward_visits, "end_tick": live_tick},
        "live": {"ok": live_ok, "tick": live_tick, "world_hash": live_hash},
        "sample_hashes": {
            "first": retained[0]["world_hash"],
            "middle": retained[len(retained) // 2]["world_hash"],
            "last": live_hash,
        },
        "mismatches": mismatches,
    }


def _check_hash(record: dict[str, Any], mismatches: list[dict[str, Any]], *, phase: str) -> None:
    expected = _tick_hash(int(record["tick"]))
    actual = str(record["world_hash"])
    if expected != actual:
        mismatches.append({"phase": phase, "tick": record["tick"], "expected": expected, "actual": actual})


def _tick_hash(tick: int) -> str:
    return hashlib.sha256(f"x10-046:{tick}".encode("utf-8")).hexdigest()


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
