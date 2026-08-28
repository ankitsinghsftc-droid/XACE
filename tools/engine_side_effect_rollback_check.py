#!/usr/bin/env python3
"""Verify X10-023 engine-side side-effect rollback bindings."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


CHECKS: list[dict[str, Any]] = [
    {
        "id": "runtime_protocol_message",
        "path": "packages/runtime-core/src/engine_protocol.rs",
        "needles": [
            "AdapterSideEffectRollback",
            "adapter_side_effect_rollback",
            "clear_feedback_queue",
            "clear_pending_edits",
            "reset_asset_bindings",
        ],
    },
    {
        "id": "runtime_bridge_send_path",
        "path": "packages/runtime-core/src/engine_bridge.rs",
        "needles": ["send_adapter_side_effect_rollback", "rollback.validate()", "write_message"],
    },
    {
        "id": "runtime_authoritative_restore_log",
        "path": "packages/runtime-core/src/runtime_orchestrator.rs",
        "needles": [
            "RuntimeAdapterSideEffectRollbackReport",
            "notify_adapter_side_effect_rollback",
            "x10_023_world_restore_records_adapter_side_effect_rollback_report",
        ],
    },
    {
        "id": "godot_protocol_and_transport",
        "path": "adapters/godot/xace_protocol.gd",
        "needles": [
            "MSG_ADAPTER_SIDE_EFFECT_ROLLBACK",
            "adapter_side_effect_rollback",
            "restored_snapshot",
        ],
    },
    {
        "id": "godot_capability",
        "path": "adapters/godot/xace_transport.gd",
        "needles": ["adapter_side_effect_rollback_v1"],
    },
    {
        "id": "godot_side_effect_cleanup",
        "path": "adapters/godot/xace_entity_manager.gd",
        "needles": [
            "rollback_side_effects",
            "_clear_playback_side_effects",
            "_asset_binding_state.clear()",
            "side_effects_rolled_back",
        ],
    },
    {
        "id": "godot_feedback_queue_cleanup",
        "path": "adapters/godot/xace_delta_applicator.gd",
        "needles": ["apply_side_effect_rollback", "_feedback_queue.clear()"],
    },
    {
        "id": "unity_transport_and_dto",
        "path": "adapters/unity/XaceTransport.cs",
        "needles": [
            "XaceAdapterSideEffectRollback",
            "OnAdapterSideEffectRollback",
            "adapter_side_effect_rollback_v1",
            "AdapterSideEffectRollback = \"adapter_side_effect_rollback\"",
        ],
    },
    {
        "id": "unity_side_effect_cleanup",
        "path": "adapters/unity/XaceDeltaApplicator.cs",
        "needles": [
            "ApplyAdapterSideEffectRollback",
            "ClearPlaybackSideEffects",
            "assetBindingState.Clear()",
            "feedbackQueue.Clear()",
            "spawnedPlaybackObjects",
        ],
    },
    {
        "id": "unity_pending_edit_cleanup",
        "path": "adapters/unity/XaceConsoleWidget.cs",
        "needles": ["XaceProtocolNames.AdapterSideEffectRollback", "adapter side effects restored"],
    },
    {
        "id": "unreal_transport_and_parser",
        "path": "adapters/unreal/XaceTransport.h",
        "needles": [
            "FXaceAdapterSideEffectRollback",
            "OnAdapterSideEffectRollback",
            "ParseAdapterSideEffectRollback",
        ],
    },
    {
        "id": "unreal_transport_dispatch",
        "path": "adapters/unreal/XaceTransport.cpp",
        "needles": [
            "adapter_side_effect_rollback_v1",
            "adapter_side_effect_rollback",
            "ParseAdapterSideEffectRollback",
        ],
    },
    {
        "id": "unreal_side_effect_cleanup",
        "path": "adapters/unreal/XaceDeltaApplicator.cpp",
        "needles": [
            "OnAdapterSideEffectRollback",
            "ClearPlaybackSideEffects",
            "PendingFeedback.Reset()",
            "AssetBindingState.Reset()",
            "PlaybackSpawnedComponents",
        ],
    },
    {
        "id": "unreal_pending_edit_cleanup",
        "path": "adapters/unreal/XaceConsoleWidget.cpp",
        "needles": ["adapter_side_effect_rollback", "adapter side effects restored"],
    },
]


def run_check() -> dict[str, Any]:
    checks = []
    ok = True
    for spec in CHECKS:
        path = ROOT / spec["path"]
        text = path.read_text(encoding="utf-8")
        missing = [needle for needle in spec["needles"] if needle not in text]
        passed = not missing
        ok = ok and passed
        checks.append(
            {
                "id": spec["id"],
                "path": spec["path"],
                "passed": passed,
                "missing": missing,
            }
        )
    return {
        "schema": "xace.x10_023.engine_side_effect_rollback_check.v1",
        "ok": ok,
        "checked_paths": sorted({spec["path"] for spec in CHECKS}),
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = run_check()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    if args.json or not report["ok"]:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("X10-023 engine-side side-effect rollback bindings: ok")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
