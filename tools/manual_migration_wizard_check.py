#!/usr/bin/env python3
"""
Retained X10-058 proof for the manual migration wizard.

The check creates small Godot, Unity, and Unreal fixtures with scene/entity,
asset, script, plugin, and input-map references. It then uses the production
manual migration planner to produce reversible CGS-shaped mappings, materializes
a preview CGS, proves rollback back to the original CGS, and validates that the
manual-work report references real unchanged files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_SYSTEM = REPO_ROOT / "packages" / "project-system"
sys.path.insert(0, str(PROJECT_SYSTEM))

from engine_migration_wizard import (  # noqa: E402
    build_manual_migration_plan,
    materialize_manual_migration_draft,
    revert_manual_migration_draft,
)
from project_templates import make_template  # noqa: E402


REPORT_SCHEMA = "xace.manual_migration_wizard_check_report.v1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the X10-058 manual migration wizard proof.")
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "target-codex-task58-manual-migration" / "report.json"),
        help="Path to write the retained JSON report.",
    )
    parser.add_argument(
        "--artifact-dir",
        default=str(REPO_ROOT / "target-codex-task58-manual-migration" / "artifacts"),
        help="Directory for generated proof artifacts.",
    )
    parser.add_argument("--json", action="store_true", help="Print the report JSON to stdout.")
    args = parser.parse_args()

    output = Path(args.output).resolve()
    artifact_dir = Path(args.artifact_dir).resolve()
    report = run_check(artifact_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif report["ok"]:
        print(f"manual migration wizard check PASSED ({len(report['checks'])} checks)")
    else:
        print("manual migration wizard check FAILED", file=sys.stderr)
        for check in report["checks"]:
            if not check["ok"]:
                print(f"- {check['name']}: {check['detail']}", file=sys.stderr)

    return 0 if report["ok"] else 1


def run_check(artifact_dir: Path) -> dict[str, Any]:
    fixtures_dir = artifact_dir / "fixtures"
    plans_dir = artifact_dir / "plans"
    previews_dir = artifact_dir / "previews"
    _safe_clean_dir(fixtures_dir, artifact_dir)
    _safe_clean_dir(plans_dir, artifact_dir)
    _safe_clean_dir(previews_dir, artifact_dir)
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    plans_dir.mkdir(parents=True, exist_ok=True)
    previews_dir.mkdir(parents=True, exist_ok=True)

    checks: list[dict[str, Any]] = []
    engine_results: dict[str, Any] = {}
    for engine, maker in {
        "godot": _make_godot_fixture,
        "unity": _make_unity_fixture,
        "unreal": _make_unreal_fixture,
    }.items():
        engine_root = maker(fixtures_dir / engine)
        before = _tree_signature(engine_root)
        base_cgs = make_template("blank_3d", f"X10-058 {engine} Manual Migration")
        original_cgs = json.loads(json.dumps(base_cgs, sort_keys=True))
        plan = build_manual_migration_plan(engine_root, expected_engine_type=engine, base_cgs=base_cgs)
        draft = materialize_manual_migration_draft(base_cgs, plan) if plan.get("ok") else {}
        reverted = revert_manual_migration_draft(draft["cgs"], draft["rollback"]) if draft else {}
        after = _tree_signature(engine_root)

        plan_path = plans_dir / f"{engine}_manual_migration_plan.json"
        manual_work_path = plans_dir / f"{engine}_manual_work_report.json"
        preview_path = previews_dir / f"{engine}_migration_preview.cgs.json"
        rollback_path = previews_dir / f"{engine}_rollback.json"
        _write_json(plan_path, plan)
        _write_json(manual_work_path, plan.get("manual_work_report", {}))
        if draft:
            _write_json(preview_path, draft["cgs"])
            _write_json(rollback_path, draft["rollback"])

        mappings_ok = _mapping_summary_ok(plan)
        file_evidence_ok = _file_evidence_matches(engine_root, plan)
        manual_work_ok = _manual_work_matches_files(engine_root, plan)
        preview_ok = bool(draft) and _preview_contains_migrated_records(draft["cgs"])
        rollback_ok = bool(draft) and reverted == original_cgs
        unchanged_ok = before == after
        ok = (
            plan.get("ok") is True
            and mappings_ok
            and file_evidence_ok
            and manual_work_ok
            and preview_ok
            and rollback_ok
            and unchanged_ok
        )
        checks.append({
            "name": f"{engine}_manual_migration_wizard",
            "ok": ok,
            "detail": (
                f"summary={plan.get('draft_summary')} mappings_ok={mappings_ok} "
                f"file_evidence_ok={file_evidence_ok} manual_work_ok={manual_work_ok} "
                f"preview_ok={preview_ok} rollback_ok={rollback_ok} engine_files_unchanged={unchanged_ok}"
            ),
            "artifacts": {
                "plan": str(plan_path),
                "manual_work_report": str(manual_work_path),
                "preview_cgs": str(preview_path),
                "rollback": str(rollback_path),
            },
        })
        engine_results[engine] = {
            "project_root": str(engine_root),
            "summary": plan.get("draft_summary", {}),
            "manual_work_items": len(plan.get("manual_work_report", {}).get("items", [])),
            "artifacts": {
                "plan": str(plan_path),
                "manual_work_report": str(manual_work_path),
                "preview_cgs": str(preview_path),
                "rollback": str(rollback_path),
            },
        }

    return {
        "schema": REPORT_SCHEMA,
        "task": "X10-058",
        "generated_at_utc": _utc_now(),
        "ok": all(check["ok"] for check in checks),
        "x10_058_complete": all(check["ok"] for check in checks),
        "checks": checks,
        "artifact_dir": str(artifact_dir),
        "engine_results": engine_results,
    }


def _mapping_summary_ok(plan: dict[str, Any]) -> bool:
    summary = plan.get("draft_summary", {})
    return (
        int(summary.get("scene_modes", 0)) >= 1
        and int(summary.get("starter_actors", 0)) >= 1
        and int(summary.get("starter_components", 0)) >= 2
        and int(summary.get("asset_references", 0)) >= 1
        and int(summary.get("semantic_binding_candidates", 0)) >= 1
        and int(summary.get("reversible_mappings", 0)) == len(plan.get("mappings", []))
    )


def _file_evidence_matches(root: Path, plan: dict[str, Any]) -> bool:
    evidence = plan.get("file_evidence", [])
    if not evidence:
        return False
    for item in evidence:
        path = root / str(item.get("path") or "")
        if not path.is_file():
            return False
        if item.get("exists") is not True:
            return False
        if item.get("sha256") != _sha256_file(path):
            return False
    return True


def _manual_work_matches_files(root: Path, plan: dict[str, Any]) -> bool:
    items = plan.get("manual_work_report", {}).get("items", [])
    if not items:
        return False
    for item in items:
        source = item.get("source", {})
        path = root / str(source.get("path") or "")
        if not path.is_file():
            return False
        if source.get("sha256") != _sha256_file(path):
            return False
        if source.get("reference_only") is not True:
            return False
    return True


def _preview_contains_migrated_records(cgs: dict[str, Any]) -> bool:
    imported_modes = [mode for mode in cgs.get("modes", []) if mode.get("migration_source")]
    imported_actors = [
        actor
        for mode in cgs.get("modes", [])
        for actor in mode.get("actors", [])
        if actor.get("migration_source")
    ]
    assets = cgs.get("assets", [])
    bindings = cgs.get("semantic_bindings", {}).get("bindings", [])
    component_names = {
        component.get("name")
        for actor in imported_actors
        for component in actor.get("components", [])
    }
    return (
        bool(imported_modes)
        and bool(imported_actors)
        and bool(assets)
        and bool(bindings)
        and {"COMP_TRANSFORM_V1", "COMP_IDENTITY_V1"}.issubset(component_names)
        and cgs.get("metadata", {}).get("manual_migration", {}).get("applied") is False
    )


def _make_godot_fixture(root: Path) -> Path:
    (root / "scenes").mkdir(parents=True)
    (root / "assets").mkdir()
    (root / "scripts").mkdir()
    (root / "addons" / "xace_demo").mkdir(parents=True)
    (root / "project.godot").write_text(
        "[application]\nconfig/name=\"Godot Migration\"\n\n[input]\nattack={\"deadzone\":0.5}\n",
        encoding="utf-8",
    )
    (root / "scenes" / "main.tscn").write_text(
        "[gd_scene format=3]\n[node name=\"Player\" type=\"CharacterBody3D\"]\n[node name=\"Pickup\" type=\"Node3D\"]\n",
        encoding="utf-8",
    )
    (root / "assets" / "impact.wav").write_bytes(b"godot-wav-reference")
    (root / "assets" / "spark.tres").write_text("[gd_resource type=\"ParticleProcessMaterial\"]\n", encoding="utf-8")
    (root / "scripts" / "player.gd").write_text("extends CharacterBody3D\n", encoding="utf-8")
    (root / "addons" / "xace_demo" / "plugin.cfg").write_text("[plugin]\nname=\"XACE Demo\"\n", encoding="utf-8")
    return root


def _make_unity_fixture(root: Path) -> Path:
    (root / "Assets" / "Scenes").mkdir(parents=True)
    (root / "Assets" / "Scripts").mkdir()
    (root / "Assets" / "Audio").mkdir()
    (root / "Assets" / "Plugins" / "Native").mkdir(parents=True)
    (root / "ProjectSettings").mkdir()
    (root / "Packages").mkdir()
    (root / "Assets" / "Scenes" / "Main.unity").write_text(
        "%YAML 1.1\n--- !u!1 &1\nGameObject:\n  m_Name: Player\n--- !u!1 &2\nGameObject:\n  m_Name: Pickup\n",
        encoding="utf-8",
    )
    (root / "Assets" / "Audio" / "impact.wav").write_bytes(b"unity-wav-reference")
    (root / "Assets" / "Scripts" / "Player.cs").write_text("public class Player {}\n", encoding="utf-8")
    (root / "Assets" / "Plugins" / "Native" / "XaceNative.dll").write_bytes(b"dll-reference")
    (root / "Assets" / "Controls.inputactions").write_text("{}\n", encoding="utf-8")
    (root / "ProjectSettings" / "ProjectVersion.txt").write_text("m_EditorVersion: 2022.3\n", encoding="utf-8")
    (root / "ProjectSettings" / "InputManager.asset").write_text("%YAML 1.1\n", encoding="utf-8")
    (root / "Packages" / "manifest.json").write_text("{}\n", encoding="utf-8")
    return root


def _make_unreal_fixture(root: Path) -> Path:
    (root / "Content" / "Maps").mkdir(parents=True)
    (root / "Content" / "Audio").mkdir()
    (root / "Content" / "Props").mkdir()
    (root / "Source" / "UnrealGame").mkdir(parents=True)
    (root / "Plugins" / "XaceDemo").mkdir(parents=True)
    (root / "Config").mkdir()
    (root / "UnrealGame.uproject").write_text('{"FileVersion":3}\n', encoding="utf-8")
    (root / "Content" / "Maps" / "Main.umap").write_text(
        "Begin Actor Name=BP_Player_C\nBegin Actor Name=BP_Pickup_C\n",
        encoding="utf-8",
    )
    (root / "Content" / "Audio" / "impact.wav").write_bytes(b"unreal-wav-reference")
    (root / "Content" / "Props" / "Crate.uasset").write_bytes(b"uasset-reference")
    (root / "Source" / "UnrealGame" / "Player.cpp").write_text("void Player() {}\n", encoding="utf-8")
    (root / "Plugins" / "XaceDemo" / "XaceDemo.uplugin").write_text('{"FileVersion":3}\n', encoding="utf-8")
    (root / "Config" / "DefaultInput.ini").write_text("[/Script/Engine.InputSettings]\n", encoding="utf-8")
    return root


def _tree_signature(root: Path) -> dict[str, dict[str, int | str]]:
    signature: dict[str, dict[str, int | str]] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().lower()):
        if not path.is_file():
            continue
        stat = path.stat()
        signature[path.relative_to(root).as_posix()] = {
            "sha256": _sha256_file(path),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }
    return signature


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _safe_clean_dir(path: Path, artifact_dir: Path) -> None:
    path = path.resolve()
    artifact_dir = artifact_dir.resolve()
    if path == artifact_dir:
        raise ValueError("Refusing to clean the artifact directory itself.")
    if artifact_dir not in path.parents:
        raise ValueError(f"Refusing to clean path outside artifact directory: {path}")
    if path.exists():
        shutil.rmtree(path)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
