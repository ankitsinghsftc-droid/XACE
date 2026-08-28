#!/usr/bin/env python3
"""Retained X10-061 proof for adapter package handoff preflight validation."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_SYSTEM_DIR = REPO_ROOT / "packages" / "project-system"
BUILDER_SERVER_DIR = REPO_ROOT / "packages" / "builder-workspace" / "server"
for _path in (str(PROJECT_SYSTEM_DIR), str(BUILDER_SERVER_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from adapter_package_handoff_preflight import (  # noqa: E402
    validate_adapter_package_handoff,
    write_adapter_package_handoff_preflight_report,
)
from project_manifest import XaceProjectManifest, default_adapter_config, save_manifest  # noqa: E402


REPORT_SCHEMA = "xace.adapter_package_handoff_preflight_check_report.v1"
DEFAULT_OUTPUT = REPO_ROOT / "target-codex-task61-adapter-package-handoff-preflight" / "report.json"
DEFAULT_ARTIFACT_DIR = REPO_ROOT / "target-codex-task61-adapter-package-handoff-preflight" / "artifacts"
REQUIRED_CATEGORIES = [
    "target_engine",
    "cgs",
    "sgc_plan",
    "runtime_compatibility",
    "adapter_version",
    "assets",
    "bindings",
    "secrets",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run X10-061 adapter package handoff preflight proof.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--artifact-dir", default=str(DEFAULT_ARTIFACT_DIR))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run_check(output_path=Path(args.output).resolve(), artifact_dir=Path(args.artifact_dir).resolve())
    except Exception as exc:  # noqa: BLE001
        print(f"adapter package handoff preflight check failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"adapter package handoff preflight check PASSED ({report['checks_passed']}/{report['checks_total']} checks)")
    return 0


def run_check(*, output_path: Path, artifact_dir: Path) -> dict[str, Any]:
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    adapter_repo = artifact_dir / "adapter_repo"
    _write_adapter_repo(adapter_repo)

    valid_project = artifact_dir / "valid_project"
    valid_hash = _write_project(valid_project)
    valid_report = validate_adapter_package_handoff(valid_project, "godot", repo_root=adapter_repo)
    valid_report_path = write_adapter_package_handoff_preflight_report(valid_project, "godot", valid_report)

    blocked_cases = []
    case_mutators: dict[str, tuple[str, Callable[[Path, Path], str]]] = {
        "target_engine": ("dreamcast", lambda project, repo: "unsupported target name"),
        "cgs": ("godot", _break_cgs),
        "sgc_plan": ("godot", _break_sgc_plan),
        "runtime_compatibility": ("godot", _break_runtime_compatibility),
        "adapter_version": ("godot", _break_adapter_version),
        "assets": ("godot", _break_assets),
        "bindings": ("godot", _break_bindings),
        "secrets": ("godot", _break_secrets),
    }
    for category, (target, mutator) in case_mutators.items():
        project = artifact_dir / f"blocked_{category}"
        repo = artifact_dir / f"repo_{category}"
        _write_adapter_repo(repo)
        cgs_hash = _write_project(project)
        mutation = mutator(project, repo)
        preflight = validate_adapter_package_handoff(project, target, repo_root=repo)
        report_path = write_adapter_package_handoff_preflight_report(project, target, preflight)
        blocked_cases.append({
            "category": category,
            "target": target,
            "mutation": mutation,
            "project": str(project),
            "cgs_hash": cgs_hash,
            "report_path": str(report_path),
            "ok": preflight.get("ok") is False,
            "blocking_categories": preflight.get("blocking_categories", []),
            "matched_expected_category": category in preflight.get("blocking_categories", []),
            "preflight": _compact_preflight(preflight),
        })

    endpoint_result = _run_builder_endpoint_proof(artifact_dir)
    checks = [
        {
            "name": "valid_project_all_categories_pass",
            "ok": valid_report.get("ok") is True and valid_report.get("required_categories") == REQUIRED_CATEGORIES,
            "detail": f"valid_report_ok={valid_report.get('ok')} required_categories={valid_report.get('required_categories')}",
        },
        {
            "name": "blocked_matrix_covers_required_categories",
            "ok": all(item["ok"] and item["matched_expected_category"] for item in blocked_cases),
            "detail": f"blocked_cases={len(blocked_cases)} categories={REQUIRED_CATEGORIES}",
        },
        {
            "name": "endpoint_blocks_before_copy",
            "ok": bool(endpoint_result.get("ok")),
            "detail": endpoint_result.get("detail", ""),
        },
        {
            "name": "retained_reports_written",
            "ok": Path(valid_report_path).is_file() and all(Path(item["report_path"]).is_file() for item in blocked_cases),
            "detail": "valid and blocked preflight reports are retained under .xace/adapter_package_handoff_preflight",
        },
    ]
    report = {
        "schema": REPORT_SCHEMA,
        "task": "X10-061",
        "generated_at_utc": _utc_now(),
        "ok": all(check["ok"] for check in checks),
        "x10_061_complete": all(check["ok"] for check in checks),
        "checks_passed": sum(1 for check in checks if check["ok"]),
        "checks_total": len(checks),
        "required_categories": REQUIRED_CATEGORIES,
        "valid_project": {
            "project": str(valid_project),
            "cgs_hash": valid_hash,
            "report_path": str(valid_report_path),
            "preflight": _compact_preflight(valid_report),
        },
        "blocked_matrix": blocked_cases,
        "endpoint_result": endpoint_result,
        "checks": checks,
        "artifacts": {
            "artifact_dir": str(artifact_dir),
            "output": str(output_path),
        },
    }
    if not report["ok"]:
        raise RuntimeError(json.dumps(report, indent=2, sort_keys=True))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _run_builder_endpoint_proof(artifact_dir: Path) -> dict[str, Any]:
    try:
        from fastapi.testclient import TestClient  # noqa: PLC0415
        from builder_server import create_app  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"TestClient unavailable: {exc}"}
    project = artifact_dir / "endpoint_blocked_project"
    _write_project(project)
    _break_assets(project, artifact_dir / "unused_repo")
    app = create_app(project_path=str(project), static_dir=str(artifact_dir / "no_dist"), dev_mode=False)
    client = TestClient(app)
    response = client.post("/api/adapter-package/handoff/godot")
    payload = response.json()
    handoff_dir = project / ".xace" / "adapter_package_handoffs" / "godot"
    ok = (
        response.status_code == 200
        and payload.get("ok") is False
        and payload.get("preflight", {}).get("ok") is False
        and "assets" in payload.get("preflight", {}).get("blocking_categories", [])
        and not handoff_dir.exists()
    )
    return {
        "ok": ok,
        "status_code": response.status_code,
        "detail": "Builder endpoint returns failed preflight and does not create handoff directory",
        "handoff_dir_exists": handoff_dir.exists(),
        "blocking_categories": payload.get("preflight", {}).get("blocking_categories", []),
        "preflight_report_path": payload.get("preflight_report_path", ""),
    }


def _write_project(project: Path) -> str:
    project.mkdir(parents=True, exist_ok=True)
    asset_dir = project / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    asset_path = asset_dir / "hero_hit.wav"
    asset_path.write_bytes(b"xace-task61-hit-audio\n")
    cgs = _base_cgs(asset_path, project)
    cgs["metadata"]["cgs_hash"] = _stable_cgs_hash(cgs)
    cgs_hash = str(cgs["metadata"]["cgs_hash"])
    _write_json(project / "game.cgs.json", cgs)
    manifest = XaceProjectManifest(
        project_id="x10_061_handoff_preflight",
        name="X10 061 Handoff Preflight",
        engine_type="godot",
        template_id="x10_061_fixture",
        cgs_path="game.cgs.json",
        asset_root="assets",
        adapter_config=default_adapter_config("godot"),
    )
    save_manifest(project, manifest)
    _write_json(project / ".xace" / "execution_plans" / f"{cgs_hash}.plan.json", _persisted_plan(cgs_hash))
    _write_json(project / ".xace" / "proof" / "runtime-compatibility" / f"{cgs_hash}.json", _runtime_compatibility_proof(cgs_hash))
    return cgs_hash


def _base_cgs(asset_path: Path, project: Path) -> dict[str, Any]:
    asset_hash = hashlib.sha256(asset_path.read_bytes()).hexdigest()
    asset_record = {
        "id": "hero_hit_sfx_v1",
        "asset_type": "AudioClip",
        "status": "LINKED",
        "source": asset_path.relative_to(project).as_posix(),
        "path": asset_path.relative_to(project).as_posix(),
        "sha256": asset_hash,
    }
    return {
        "format": "xace.cgs.export",
        "format_version": "1.0.0",
        "metadata": {
            "name": "X10 061 Handoff Preflight",
            "schema_version": "0.1.0",
            "version": "0.1.0",
            "execution_plan_version": 1,
            "cgs_hash": "",
        },
        "assets": [asset_record],
        "semantic_bindings": {
            "bindings": [
                {
                    "binding_id": "hero_hit_audio",
                    "event_name": "combat.hit",
                    "playback_kind": "Audio",
                    "asset": dict(asset_record),
                    "parameters": {"xace_engine_targets": "godot,unity,unreal"},
                }
            ]
        },
        "global_systems": [
            {
                "id": "MovementSystem",
                "phase": "Simulation",
                "reads": [1, 5],
                "writes": [1],
                "depends_on": [],
                "deterministic": True,
            }
        ],
        "modes": [
            {
                "id": "default",
                "schema_version": "0.1.0",
                "is_default": True,
                "actors": [
                    {
                        "id": "player",
                        "spawn_count": 1,
                        "components": [
                            {"type_id": 1, "name": "COMP_TRANSFORM_V1", "defaults": {"position_x": 0.0}},
                            {"type_id": 5, "name": "COMP_VELOCITY_V1", "defaults": {"vx": 1.0}},
                        ],
                    }
                ],
                "systems": [],
                "rules": [],
            }
        ],
    }


def _persisted_plan(cgs_hash: str) -> dict[str, Any]:
    plan_hash = "b" * 64
    return {
        "schema_version": "0.1.0",
        "plan_version": 1,
        "adapter_protocol_version": 1,
        "migration_status": "current",
        "created_tick": 0,
        "plan_hash": plan_hash,
        "compiled_from_cgs_hash": cgs_hash,
        "all_system_ids": ["MovementSystem"],
        "phases": {
            "2": {
                "phase": "Simulation",
                "groups": [
                    {
                        "group_id": "Simulation_group_0",
                        "phase": "Simulation",
                        "parallel": False,
                        "systems": ["MovementSystem"],
                        "serialization_constraints": [],
                        "execution_index": 0,
                    }
                ],
                "total_system_count": 1,
            }
        },
        "component_access_sets": {
            "schema": "xace.sgc.component_access_sets.v1",
            "by_system": {"MovementSystem": {"reads": [1, 5], "writes": [1]}},
            "all_reads": [1, 5],
            "all_writes": [1],
            "component_ids": [1, 5],
        },
        "system_metadata": {
            "schema": "xace.sgc.system_metadata.v1",
            "systems": {
                "MovementSystem": {
                    "display_name": "Movement System",
                    "phase": "Simulation",
                    "depends_on": [],
                    "deterministic": True,
                    "version": {"major": 1, "minor": 0},
                    "description": "Task 61 runtime-compatible fixture system.",
                }
            },
        },
        "proof_bundle": {
            "schema": "xace.sgc.proof_ref.v1",
            "path": f".xace/proof/sgc/{cgs_hash}",
            "compiled_from_cgs_hash": cgs_hash,
            "plan_hash": plan_hash,
            "input_hash": "d" * 64,
            "validation_hash": "e" * 64,
        },
    }


def _runtime_compatibility_proof(cgs_hash: str) -> dict[str, Any]:
    return {
        "schema": "xace.runtime.plan_compatibility.v1",
        "ok": True,
        "source": "cgs-derived",
        "cgs_hash": cgs_hash,
        "declared_system_ids": ["MovementSystem"],
        "scheduled_system_ids": ["MovementSystem"],
        "unsupported_systems": [],
        "legacy_dropped_system_ids": [],
        "default_system_injected": False,
        "runtime_rule": "CGS-derived plans must fail before tick zero when any declared system cannot be executed; no system may be silently filtered or replaced.",
    }


def _write_adapter_repo(repo: Path) -> None:
    godot = repo / "adapters" / "godot"
    godot.mkdir(parents=True, exist_ok=True)
    (godot / "xace_protocol.gd").write_text('const PROTOCOL_VERSION := 1\nfunc make_handshake(adapter_version: String = "0.1.0") -> Dictionary:\n\treturn {}\n', encoding="utf-8")
    (godot / "xace_transport.gd").write_text('extends Node\n@export var adapter_version := "0.1.0"\n', encoding="utf-8")
    (godot / "xace_delta_applicator.gd").write_text("extends Node\n", encoding="utf-8")
    (godot / "xace_input_collector.gd").write_text("extends Node\n", encoding="utf-8")
    for target in ("unity", "unreal"):
        (repo / "adapters" / target).mkdir(parents=True, exist_ok=True)


def _break_cgs(project: Path, _repo: Path) -> str:
    cgs_path = project / "game.cgs.json"
    cgs = json.loads(cgs_path.read_text(encoding="utf-8"))
    cgs["metadata"]["cgs_hash"] = "0" * 64
    _write_json(cgs_path, cgs)
    return "metadata.cgs_hash set to stale zero digest"


def _break_sgc_plan(project: Path, _repo: Path) -> str:
    for plan_path in (project / ".xace" / "execution_plans").glob("*.plan.json"):
        plan_path.unlink()
    return "persisted SGC plan removed"


def _break_runtime_compatibility(project: Path, _repo: Path) -> str:
    proof_path = next((project / ".xace" / "proof" / "runtime-compatibility").glob("*.json"))
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["ok"] = False
    proof["unsupported_systems"] = [{"system_id": "MovementSystem", "reason": "forced X10-061 failure"}]
    proof["legacy_dropped_system_ids"] = ["MovementSystem"]
    _write_json(proof_path, proof)
    return "runtime compatibility proof marked not ok with unsupported system"


def _break_adapter_version(_project: Path, repo: Path) -> str:
    transport = repo / "adapters" / "godot" / "xace_transport.gd"
    text = transport.read_text(encoding="utf-8").replace('adapter_version := "0.1.0"', 'adapter_version := "9.9.9"')
    transport.write_text(text, encoding="utf-8")
    return "Godot adapter version marker changed to 9.9.9"


def _break_assets(project: Path, _repo: Path) -> str:
    cgs_path = project / "game.cgs.json"
    cgs = json.loads(cgs_path.read_text(encoding="utf-8"))
    cgs["assets"][0]["sha256"] = "f" * 64
    cgs["semantic_bindings"]["bindings"][0]["asset"]["sha256"] = "f" * 64
    cgs["metadata"]["cgs_hash"] = _stable_cgs_hash(cgs)
    _rewrite_project_cgs_and_hash_artifacts(project, cgs)
    return "linked asset SHA-256 changed away from file bytes"


def _break_bindings(project: Path, _repo: Path) -> str:
    cgs_path = project / "game.cgs.json"
    cgs = json.loads(cgs_path.read_text(encoding="utf-8"))
    cgs["semantic_bindings"]["bindings"][0]["parameters"]["xace_engine_targets"] = "unity,unreal"
    cgs["metadata"]["cgs_hash"] = _stable_cgs_hash(cgs)
    _rewrite_project_cgs_and_hash_artifacts(project, cgs)
    return "semantic binding target list excludes godot"


def _break_secrets(project: Path, _repo: Path) -> str:
    secret_path = project / "assets" / "handoff_notes.txt"
    secret_path.write_text("temporary provider token: sk-task61SecretExample\n", encoding="utf-8")
    return "credential-looking text file added under asset root"


def _rewrite_project_cgs_and_hash_artifacts(project: Path, cgs: dict[str, Any]) -> None:
    old_plan_dir = project / ".xace" / "execution_plans"
    old_runtime_dir = project / ".xace" / "proof" / "runtime-compatibility"
    shutil.rmtree(old_plan_dir, ignore_errors=True)
    shutil.rmtree(old_runtime_dir, ignore_errors=True)
    cgs_hash = str(cgs["metadata"]["cgs_hash"])
    _write_json(project / "game.cgs.json", cgs)
    _write_json(old_plan_dir / f"{cgs_hash}.plan.json", _persisted_plan(cgs_hash))
    _write_json(old_runtime_dir / f"{cgs_hash}.json", _runtime_compatibility_proof(cgs_hash))


def _stable_cgs_hash(cgs: dict[str, Any]) -> str:
    stripped = copy.deepcopy(cgs)
    stripped.setdefault("metadata", {}).pop("cgs_hash", None)
    canonical = json.dumps(stripped, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _compact_preflight(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": report.get("ok"),
        "blocked": report.get("blocked"),
        "target": report.get("target"),
        "cgs_hash": report.get("cgs_hash"),
        "blocking_categories": report.get("blocking_categories", []),
        "checks_passed": report.get("checks_passed"),
        "checks_total": report.get("checks_total"),
        "checks": [
            {
                "name": check.get("name"),
                "ok": check.get("ok"),
                "issue_codes": [issue.get("code") for issue in check.get("issues", [])],
            }
            for check in report.get("checks", [])
        ],
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())

