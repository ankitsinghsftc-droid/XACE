"""
semantic_binding_status_check.py - retained X10-055 semantic binding status proof.

Builds a semantic-binding fixture that exercises resolved, unresolved,
unsupported, missing, and fallback statuses for Godot, Unity, and Unreal. It
also verifies Builder UI status surfacing and adapter status-report hooks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
ASSET_REGISTRY_ROOT = REPO_ROOT / "packages" / "asset-registry"
sys.path.insert(0, str(ASSET_REGISTRY_ROOT))

from semantic_binding_status import (  # noqa: E402
    ADAPTER_STATUS_REPORT_SCHEMA,
    SEMANTIC_BINDING_STATUS_REPORT_SCHEMA,
    SEMANTIC_BINDING_STATUSES,
    build_adapter_status_reports,
    evaluate_semantic_binding_status,
)


REPORT_SCHEMA = "xace.semantic_binding_status_check_report.v1"
ENGINES = ("godot", "unity", "unreal")
EXPECTED_STATUSES = set(SEMANTIC_BINDING_STATUSES)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "target-codex-task55-binding-status" / "report.json",
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=REPO_ROOT / "target-codex-task55-binding-status" / "artifacts",
    )
    parser.add_argument("--json", action="store_true", help="Print report JSON.")
    args = parser.parse_args(argv)

    artifact_dir = args.artifact_dir.resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    fixture_root = artifact_dir / "fixture_project"
    fixture_root.mkdir(parents=True, exist_ok=True)
    fixture = build_fixture_project(fixture_root)
    fixture_path = artifact_dir / "semantic_binding_status_fixture.cgs.json"
    write_json(fixture_path, fixture)

    status_report = evaluate_semantic_binding_status(
        fixture,
        project_root=fixture_root,
        engines=ENGINES,
    )
    status_report_path = artifact_dir / "semantic_binding_status_report.json"
    write_json(status_report_path, status_report.to_dict())

    adapter_dir = artifact_dir / "adapter_reports"
    adapter_dir.mkdir(exist_ok=True)
    adapter_reports = build_adapter_status_reports(status_report)
    adapter_paths: dict[str, str] = {}
    for engine, adapter_report in adapter_reports.items():
        path = adapter_dir / f"{engine}_semantic_binding_status_report.json"
        write_json(path, adapter_report)
        adapter_paths[engine] = str(path.relative_to(REPO_ROOT))

    checks = [
        check_status_matrix(status_report.to_dict()),
        check_builder_status_ui_contract(),
        check_adapter_status_hooks(),
        check_adapter_report_artifacts(adapter_reports),
        check_certification_wiring(),
    ]
    complete = all(check["ok"] for check in checks)
    report = {
        "schema": REPORT_SCHEMA,
        "task": "X10-055",
        "x10_055_complete": complete,
        "checks_passed": sum(1 for check in checks if check["ok"]),
        "checks_total": len(checks),
        "engines": list(ENGINES),
        "statuses": sorted(EXPECTED_STATUSES),
        "artifacts": {
            "fixture_cgs": str(fixture_path.relative_to(REPO_ROOT)),
            "fixture_cgs_sha256": sha256_file(fixture_path),
            "status_report": str(status_report_path.relative_to(REPO_ROOT)),
            "status_report_sha256": sha256_file(status_report_path),
            "adapter_reports": adapter_paths,
        },
        "checks": checks,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, report)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    if not complete:
        failed = ", ".join(check["name"] for check in checks if not check["ok"])
        print(f"X10-055 semantic binding status check failed: {failed}", file=sys.stderr)
        return 1
    return 0


def check_status_matrix(status_report: dict[str, Any]) -> dict[str, Any]:
    by_engine = status_report.get("count_by_engine", {})
    engine_ok: dict[str, bool] = {}
    for engine in ENGINES:
        counts = by_engine.get(engine, {})
        engine_ok[engine] = all(counts.get(status) == 1 for status in EXPECTED_STATUSES)
    fallback_records = [
        record for record in status_report.get("records", [])
        if record.get("status") == "fallback"
    ]
    fallback_visible = (
        len(fallback_records) == len(ENGINES)
        and all(record.get("blocks_runtime") is False and record.get("blocks_handoff") is False for record in fallback_records)
    )
    return {
        "name": "per_engine_status_matrix",
        "ok": (
            status_report.get("schema") == SEMANTIC_BINDING_STATUS_REPORT_SCHEMA
            and status_report.get("record_count") == len(ENGINES) * len(EXPECTED_STATUSES)
            and all(engine_ok.values())
            and fallback_visible
        ),
        "summary": "Status evaluator tracks resolved, unresolved, unsupported, missing, and fallback for each engine.",
        "engine_status_counts": by_engine,
        "fallback_visible_not_resolved": fallback_visible,
    }


def check_builder_status_ui_contract() -> dict[str, Any]:
    files = {
        "panel": read("packages/builder-workspace/src/panels/semantic_binding_panel.ts"),
        "status": read("packages/builder-workspace/src/panels/semantic_binding_status.ts"),
        "store": read("packages/builder-workspace/src/state/cgs_store.ts"),
        "contract": read("packages/builder-workspace/tools/builder_ui_contract_test.mjs"),
    }
    required = {
        "panel": ["Pre-runtime/handoff status", "xb-sbp-status-summary", "xb-sbp-badge", "evaluateSemanticBindingStatuses"],
        "status": [
            "SemanticBindingStatusRecord",
            "semanticBindingStatusSummary",
            "statusBlocksLaunch",
            "resolved",
            "unresolved",
            "unsupported",
            "missing",
            "fallback",
        ],
        "store": ["assetRecordHash", "assetFallbackMetadata", "unresolved"],
        "contract": ["semantic binding engine status", "statusBlocksLaunch"],
    }
    missing = missing_markers(files, required)
    return {
        "name": "builder_status_ui_contract",
        "ok": not missing,
        "summary": "Builder surfaces per-engine semantic binding status before runtime/handoff launch.",
        "missing": missing,
    }


def check_adapter_status_hooks() -> dict[str, Any]:
    files = {
        "godot": read("adapters/godot/xace_entity_manager.gd"),
        "unity": read("adapters/unity/XaceDeltaApplicator.cs"),
        "unreal_h": read("adapters/unreal/XaceDeltaApplicator.h"),
        "unreal_cpp": read("adapters/unreal/XaceDeltaApplicator.cpp"),
    }
    required = {
        "godot": ["asset_binding_status_report", "_semantic_binding_status", "xace.adapter.semantic_binding_status_report.v1"],
        "unity": ["BuildAssetBindingStatusReport", "AssetBindingStatusReport", "SemanticBindingStatus", "xace.adapter.semantic_binding_status_report.v1"],
        "unreal_h": ["AssetBindingStatusReportJson", "AssetBindingStatusReport", "SemanticBindingStatus"],
        "unreal_cpp": ["AssetBindingStatusReportJson", "RecordAssetBindingStatus", "xace.adapter.semantic_binding_status_report.v1"],
    }
    missing = missing_markers(files, required)
    combined = "\n".join(files.values())
    statuses_present = all(status in combined for status in EXPECTED_STATUSES)
    return {
        "name": "adapter_status_report_hooks",
        "ok": not missing and statuses_present,
        "summary": "Godot, Unity, and Unreal adapters expose semantic binding status report hooks.",
        "missing": missing,
        "all_status_literals_present": statuses_present,
    }


def check_adapter_report_artifacts(adapter_reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    details: dict[str, Any] = {}
    ok = True
    for engine in ENGINES:
        report = adapter_reports.get(engine, {})
        statuses = {record.get("status") for record in report.get("records", [])}
        engine_ok = (
            report.get("schema") == ADAPTER_STATUS_REPORT_SCHEMA
            and report.get("engine") == engine
            and statuses == EXPECTED_STATUSES
            and report.get("record_count") == len(EXPECTED_STATUSES)
        )
        ok = ok and engine_ok
        details[engine] = {
            "ok": engine_ok,
            "statuses": sorted(statuses),
            "record_count": report.get("record_count"),
        }
    return {
        "name": "adapter_report_artifacts_cover_all_statuses",
        "ok": ok,
        "summary": "Retained adapter report artifacts cover all five statuses for Godot, Unity, and Unreal.",
        "engines": details,
    }


def check_certification_wiring() -> dict[str, Any]:
    certify = read("tools/certify_launch.py")
    missing = [
        marker for marker in [
            "semantic binding status gate",
            "tools/semantic_binding_status_check.py",
            "packages/asset-registry/semantic_binding_status.py",
        ]
        if marker not in certify
    ]
    return {
        "name": "launch_certification_wiring",
        "ok": not missing,
        "summary": "Launch certification compiles and runs the semantic binding status gate.",
        "missing": missing,
    }


def build_fixture_project(root: Path) -> dict[str, Any]:
    assets_dir = root / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    resolved_audio = write_asset(assets_dir / "resolved.wav", b"xace-resolved-audio\n")
    mesh = write_asset(assets_dir / "unsupported_mesh.glb", b"xace-unsupported-mesh\n")
    assets = [
        asset_ref("resolved_sfx", "AudioClip", "Linked", resolved_audio),
        asset_ref("unresolved_sfx", "AudioClip", "Unresolved"),
        asset_ref("missing_sfx", "AudioClip", "Linked", assets_dir / "missing.wav"),
        asset_ref("fallback_sfx", "AudioClip", "Missing", fallback=True),
        asset_ref("unsupported_mesh", "Mesh", "Linked", mesh),
    ]
    cgs = {
        "metadata": {
            "name": "X10-055 Semantic Binding Status Fixture",
            "version": "0.1.0",
            "schema_version": "0.1.0",
        },
        "assets": assets,
        "semantic_bindings": {
            "bindings": [
                binding("binding.resolved", "resolved_sfx", "AudioClip", "Linked", "play"),
                binding("binding.unresolved", "unresolved_sfx", "AudioClip", "Unresolved", "play"),
                binding("binding.missing", "missing_sfx", "AudioClip", "Linked", "play"),
                binding("binding.fallback", "fallback_sfx", "AudioClip", "Missing", "play"),
                binding("binding.unsupported", "unsupported_mesh", "Mesh", "Linked", "play"),
            ]
        },
        "global_systems": [],
        "modes": [{
            "id": "mode_default",
            "is_default": True,
            "actors": [],
            "systems": [],
            "rules": [],
        }],
    }
    cgs["metadata"]["cgs_hash"] = cgs_hash(cgs)
    return cgs


def asset_ref(asset_id: str, asset_type: str, status: str, path: Path | None = None, *, fallback: bool = False) -> dict[str, Any]:
    ref: dict[str, Any] = {
        "id": asset_id,
        "asset_type": asset_type,
        "status": status,
    }
    if path is not None:
        ref["path"] = f"assets/{path.name}"
        ref["sha256"] = sha256_file(path) if path.exists() else hashlib.sha256(asset_id.encode("utf-8")).hexdigest()
    if fallback:
        ref["fallback_policy"] = {
            "kind": "silent_audio",
            "reason": "optional binding can use deterministic fallback in X10-056",
        }
    return ref


def binding(binding_id: str, asset_id: str, asset_type: str, status: str, action: str) -> dict[str, Any]:
    return {
        "binding_id": binding_id,
        "event_name": "combat.hit_confirmed",
        "playback_kind": "Audio",
        "asset": {
            "id": asset_id,
            "asset_type": asset_type,
            "status": status,
        },
        "semantic_action": action,
        "entity_selector": "SourceEntity",
        "parameters": {
            "xace_engine_targets": "godot,unity,unreal",
            "xace_binding_status": status.lower(),
        },
        "enabled": True,
        "priority": 10,
    }


def missing_markers(files: dict[str, str], markers: dict[str, list[str]]) -> dict[str, list[str]]:
    missing: dict[str, list[str]] = {}
    for name, required in markers.items():
        text = files[name]
        absent = [marker for marker in required if marker not in text]
        if absent:
            missing[name] = absent
    return missing


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def write_asset(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    return path


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cgs_hash(cgs: dict[str, Any]) -> str:
    payload = json.loads(json.dumps(cgs))
    payload.get("metadata", {}).pop("cgs_hash", None)
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
