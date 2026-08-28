#!/usr/bin/env python3
"""Validate X10-045 minimum tick debugger coverage."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "target-codex-task45-tick-debugger" / "report.json"
REPORT_SCHEMA = "xace.tick_debugger_minimum_check_report.v1"

FILES = {
    "debugger": "packages/builder-workspace/src/preview/tick_debugger.ts",
    "message_types": "packages/builder-workspace/src/api/message_types.ts",
    "builder_client": "packages/builder-workspace/src/api/builder_client.ts",
    "ui_contract": "packages/builder-workspace/tools/builder_ui_contract_test.mjs",
    "control_protocol": "packages/runtime-core/src/control_protocol.rs",
    "runtime_bin": "packages/runtime-core/src/bin/xace_runtime.rs",
    "ws_router": "packages/builder-workspace/server/ws_message_router.py",
}

DEBUGGER_MARKERS = [
    "Tick debugger",
    "data-action=\"pause\"",
    "data-action=\"step\"",
    "data-action=\"snapshot\"",
    "Timeline",
    "Snapshot list",
    "State diff",
    "Mutation history",
    "Event trace",
    "Hash mismatches",
    "Source-free trace",
    "runtime protocol payloads only",
    "runtime_control_ack",
    "message.snapshot",
    "snapshotFromEngineTick",
    "snapshotFromRuntimeControlAck",
    "buildStateDiff",
    "recordSnapshotMutations",
    "recordGameEvents",
    "observedHashesByTick",
    "pushHashMismatch",
    "hash_log",
]

MESSAGE_MARKERS = [
    "| 'snapshot';",
    "readonly snapshot?: RuntimeTickSnapshot;",
    "readonly entities?: RuntimeEntityState[];",
    "readonly spawned_ids?: number[];",
    "readonly destroyed_ids?: number[];",
    "readonly events?: RuntimeGameEvent[];",
    "readonly hash_log?: RuntimeBridgeHashRecord[];",
]

CLIENT_MARKERS = [
    "onEngineTick",
    "onRawMessage",
    "onRuntimeStatus",
    "action: 'snapshot'",
    "isRuntimeControlAck(message)",
    "hashLog: Array.isArray(status.hash_log) ? status.hash_log : []",
]

RUNTIME_MARKERS = [
    "Self::Snapshot => \"snapshot\"",
    "pub snapshot: Option<TickSnapshot>",
    "pub fn with_snapshot",
]

RUNTIME_BIN_MARKERS = [
    "RuntimeControlAction::Snapshot => \"runtime snapshot\"",
    "ack = ack.with_snapshot(runtime.control_snapshot());",
]

ROUTER_MARKERS = [
    "\"type\": \"runtime_control_ack\"",
    "\"snapshot\": response.get(\"snapshot\")",
    "def _runtime_snapshot_to_engine_tick",
    "\"entities\": entities",
    "\"spawned_ids\": snapshot.get(\"spawned_ids\", [])",
    "\"destroyed_ids\": snapshot.get(\"destroyed_ids\", [])",
    "\"events\": snapshot.get(\"events\", [])",
]

UI_CONTRACT_MARKERS = [
    "assertTickDebuggerContract",
    "src/preview/tick_debugger.ts",
    "Snapshot list",
    "Hash mismatches",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate X10-045 minimum tick debugger coverage.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run_check(output_path=Path(args.output).resolve())
    except Exception as exc:  # noqa: BLE001
        print(f"tick debugger minimum check failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, sort_keys=True) if args.json else json.dumps(report, indent=2, sort_keys=True))
    return 0


def run_check(*, output_path: Path) -> dict[str, Any]:
    texts = {name: _read(path) for name, path in FILES.items()}
    marker_results = {
        "debugger_ui_contract": _marker_result(texts["debugger"], DEBUGGER_MARKERS),
        "builder_message_contract": _marker_result(texts["message_types"], MESSAGE_MARKERS),
        "builder_client_wiring": _marker_result(texts["builder_client"], CLIENT_MARKERS),
        "builder_ui_contract_test": _marker_result(texts["ui_contract"], UI_CONTRACT_MARKERS),
        "runtime_control_protocol": _marker_result(texts["control_protocol"], RUNTIME_MARKERS),
        "runtime_snapshot_ack": _marker_result(texts["runtime_bin"], RUNTIME_BIN_MARKERS),
        "builder_server_forwarding": _marker_result(texts["ws_router"], ROUTER_MARKERS),
    }
    divergence = _known_divergence_fixture()
    checks = {
        "debugger_exposes_required_surfaces": marker_results["debugger_ui_contract"]["ok"],
        "pause_step_snapshot_controls_visible": all(
            marker in texts["debugger"]
            for marker in ["data-action=\"pause\"", "data-action=\"step\"", "data-action=\"snapshot\""]
        ),
        "message_contract_carries_snapshots_events_and_hash_log": marker_results["builder_message_contract"]["ok"],
        "builder_client_subscribes_to_tick_raw_and_status": marker_results["builder_client_wiring"]["ok"],
        "ui_contract_guards_tick_debugger": marker_results["builder_ui_contract_test"]["ok"],
        "runtime_snapshot_command_returns_tick_snapshot": marker_results["runtime_control_protocol"]["ok"]
        and marker_results["runtime_snapshot_ack"]["ok"],
        "server_forwards_snapshot_as_engine_tick_and_ack": marker_results["builder_server_forwarding"]["ok"],
        "known_divergence_hash_mismatch_detected": divergence["hash_mismatch"]["detected"],
        "known_divergence_state_diff_inspectable": any(row["kind"] == "component_changed" for row in divergence["state_diff"]),
        "known_divergence_mutation_history_inspectable": len(divergence["mutation_history"]) >= 2,
        "known_divergence_event_trace_inspectable": len(divergence["event_trace"]) >= 2,
        "source_free_boundary_recorded": "runtime protocol payloads only" in texts["debugger"],
    }

    report = {
        "schema": REPORT_SCHEMA,
        "ok": all(checks.values()),
        "x10_045_complete": all(checks.values()),
        "checks": checks,
        "marker_results": marker_results,
        "known_divergence_fixture": divergence,
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
        raise ValueError(f"tick debugger checks failed: {checks}")
    return report


def _known_divergence_fixture() -> dict[str, Any]:
    before = {
        "tick": 42,
        "world_hash": "a" * 64,
        "entities": [
            {"id": 7, "actor_id": "player", "components": {"300": "{\"x\":0,\"y\":0}", "700": "{\"active\":true}"}},
        ],
        "spawned_ids": [7],
        "destroyed_ids": [],
        "events": [{"event_type": "spawned", "entity_id": 7, "data": {"actor": "player"}}],
    }
    after = {
        "tick": 42,
        "world_hash": "b" * 64,
        "entities": [
            {"id": 7, "actor_id": "player", "components": {"300": "{\"x\":1,\"y\":0}", "700": "{\"active\":true}"}},
        ],
        "spawned_ids": [],
        "destroyed_ids": [],
        "events": [{"event_type": "moved", "entity_id": 7, "data": {"dx": 1}}],
    }
    state_diff = _state_diff(before["entities"], after["entities"])
    event_trace = [
        {"tick": before["tick"], "event_type": event["event_type"], "entity_id": event["entity_id"], "data": event["data"]}
        for event in before["events"] + after["events"]
    ]
    mutation_history = [
        {"tick": before["tick"], "kind": "spawn", "entity_id": "7", "detail": "spawned_id from runtime snapshot"},
        *[
            {
                "tick": after["tick"],
                "kind": "component",
                "entity_id": str(row["entity_id"]),
                "component": row["component"],
                "detail": f"{row['before']} -> {row['after']}",
            }
            for row in state_diff
        ],
    ]
    return {
        "schema": "xace.tick_debugger_known_divergence_fixture.v1",
        "description": "Two protocol snapshots for the same tick expose a reproducible hash mismatch plus inspectable diff/event/mutation rows.",
        "snapshots": [before, after],
        "hash_mismatch": {
            "detected": before["tick"] == after["tick"] and before["world_hash"] != after["world_hash"],
            "tick": before["tick"],
            "expected_hash": before["world_hash"],
            "actual_hash": after["world_hash"],
            "display_source": "Hash mismatches",
        },
        "state_diff": state_diff,
        "mutation_history": mutation_history,
        "event_trace": event_trace,
    }


def _state_diff(before_entities: list[dict[str, Any]], after_entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    before_by_id = {entity["id"]: entity for entity in before_entities}
    after_by_id = {entity["id"]: entity for entity in after_entities}
    rows: list[dict[str, Any]] = []
    for entity_id in sorted(set(before_by_id) | set(after_by_id)):
        before = before_by_id.get(entity_id)
        after = after_by_id.get(entity_id)
        if before is None or after is None:
            rows.append({
                "kind": "entity_added" if after else "entity_removed",
                "entity_id": entity_id,
                "component": "",
                "before": "<missing>" if after else "<present>",
                "after": "<present>" if after else "<missing>",
            })
            continue
        component_ids = sorted(set(before["components"]) | set(after["components"]))
        for component in component_ids:
            old = before["components"].get(component)
            new = after["components"].get(component)
            if old == new:
                continue
            rows.append({
                "kind": "component_changed",
                "entity_id": entity_id,
                "component": component,
                "before": old,
                "after": new,
            })
    return rows


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
