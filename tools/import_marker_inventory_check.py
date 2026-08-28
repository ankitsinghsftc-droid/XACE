#!/usr/bin/env python3
"""
Retained X10-057 proof for read-only engine import marker inventory.

This tool creates small Godot, Unity, Unreal, and ambiguous mixed-marker
fixtures, runs the production project-system scanner/import path, and writes a
report proving that engine-owned files are inventoried as references only and
are not modified by marker detection or safe import wrapping.
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

from engine_project_inventory import INVENTORY_CATEGORIES, scan_engine_project_inventory  # noqa: E402
from project_creator import ProjectCreator, ProjectImportValidationError  # noqa: E402


REPORT_SCHEMA = "xace.import_marker_inventory_check_report.v1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the X10-057 import marker inventory proof.")
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "target-codex-task57-import-inventory" / "report.json"),
        help="Path to write the retained JSON report.",
    )
    parser.add_argument(
        "--artifact-dir",
        default=str(REPO_ROOT / "target-codex-task57-import-inventory" / "artifacts"),
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
        print(f"import marker inventory check PASSED ({len(report['checks'])} checks)")
    else:
        print("import marker inventory check FAILED", file=sys.stderr)
        for check in report["checks"]:
            if not check["ok"]:
                print(f"- {check['name']}: {check['detail']}", file=sys.stderr)

    return 0 if report["ok"] else 1


def run_check(artifact_dir: Path) -> dict[str, Any]:
    fixtures_dir = artifact_dir / "fixtures"
    xace_projects_dir = artifact_dir / "xace-projects"
    reports_dir = artifact_dir / "inventory-reports"
    _safe_clean_dir(fixtures_dir, artifact_dir)
    _safe_clean_dir(xace_projects_dir, artifact_dir)
    _safe_clean_dir(reports_dir, artifact_dir)
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    xace_projects_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    checks: list[dict[str, Any]] = []
    engine_reports: dict[str, Any] = {}
    for engine, maker in {
        "godot": _make_godot_fixture,
        "unity": _make_unity_fixture,
        "unreal": _make_unreal_fixture,
    }.items():
        engine_root = maker(fixtures_dir / engine)
        xace_root = xace_projects_dir / f"{engine}-wrapped-xace"
        before = _tree_signature(engine_root)
        scan_report = scan_engine_project_inventory(engine_root, expected_engine_type=engine)
        after_scan = _tree_signature(engine_root)
        import_result = ProjectCreator().import_engine_project(
            engine_project_dir=engine_root,
            xace_project_dir=xace_root,
            name=f"{engine.title()} Wrapped",
            engine_type=engine,
            template_id="blank_3d",
        )
        after_import = _tree_signature(engine_root)
        report_path = reports_dir / f"{engine}_inventory_report.json"
        _write_json(report_path, scan_report)

        categories_ok = all(scan_report["inventory_counts"][category] >= 1 for category in INVENTORY_CATEGORIES)
        reference_only_ok = _all_references_are_reference_only(scan_report)
        manifest_inventory = import_result.manifest.adapter_config.get("engine_project_inventory", {})
        manifest_inventory_ok = (
            manifest_inventory.get("reference_only") is True
            and manifest_inventory.get("reference_mode") == "read_only_references_no_copy_no_modify"
            and manifest_inventory.get("detected_engine_type") == engine
        )
        engine_ok = (
            scan_report.get("ok") is True
            and scan_report.get("detected_engine_type") == engine
            and before == after_scan
            and before == after_import
            and categories_ok
            and reference_only_ok
            and manifest_inventory_ok
        )
        checks.append({
            "name": f"{engine}_read_only_reference_inventory",
            "ok": engine_ok,
            "detail": (
                f"detected={scan_report.get('detected_engine_type')} counts={scan_report.get('inventory_counts')} "
                f"scan_unchanged={before == after_scan} import_unchanged={before == after_import} "
                f"reference_only={reference_only_ok} manifest_inventory={manifest_inventory_ok}"
            ),
            "artifact": str(report_path),
        })
        engine_reports[engine] = {
            "project_root": str(engine_root),
            "wrapped_xace_project": str(xace_root),
            "inventory_report": str(report_path),
            "inventory_counts": scan_report.get("inventory_counts", {}),
            "manifest_inventory_counts": manifest_inventory.get("inventory_counts", {}),
        }

    ambiguous = _run_ambiguous_refusal_check(fixtures_dir, xace_projects_dir, reports_dir)
    checks.append(ambiguous["check"])

    report = {
        "schema": REPORT_SCHEMA,
        "task": "X10-057",
        "generated_at_utc": _utc_now(),
        "ok": all(check["ok"] for check in checks),
        "x10_057_complete": all(check["ok"] for check in checks),
        "checks": checks,
        "artifact_dir": str(artifact_dir),
        "engine_reports": engine_reports,
        "ambiguous_import_refusal": ambiguous["report"],
    }
    return report


def _run_ambiguous_refusal_check(fixtures_dir: Path, xace_projects_dir: Path, reports_dir: Path) -> dict[str, Any]:
    engine_root = fixtures_dir / "ambiguous-godot-unity"
    engine_root.mkdir(parents=True, exist_ok=True)
    (engine_root / "project.godot").write_text("[application]\nconfig/name=Ambiguous\n", encoding="utf-8")
    (engine_root / "Assets").mkdir()
    (engine_root / "ProjectSettings").mkdir()
    (engine_root / "ProjectSettings" / "ProjectVersion.txt").write_text("m_EditorVersion: 2022.3\n", encoding="utf-8")
    xace_root = xace_projects_dir / "ambiguous-refused-xace"
    before = _tree_signature(engine_root)
    scan_report = scan_engine_project_inventory(engine_root, expected_engine_type="godot")
    refused_by_import = False
    import_error_report: dict[str, Any] = {}
    try:
        ProjectCreator().import_engine_project(
            engine_project_dir=engine_root,
            xace_project_dir=xace_root,
            name="Ambiguous Wrapped",
            engine_type="godot",
            template_id="blank_3d",
        )
    except ProjectImportValidationError as exc:
        refused_by_import = True
        import_error_report = exc.report
    after = _tree_signature(engine_root)
    report_path = reports_dir / "ambiguous_refusal_report.json"
    refusal_report = {
        "scan_report": scan_report,
        "import_error_report": import_error_report,
        "refused_by_import": refused_by_import,
        "engine_files_unchanged": before == after,
        "xace_project_written": (xace_root / "xace.project.json").exists(),
    }
    _write_json(report_path, refusal_report)
    ok = (
        scan_report.get("refused") is True
        and scan_report.get("reason") == "AMBIGUOUS_ENGINE_MARKERS"
        and refused_by_import
        and import_error_report.get("reason") == "AMBIGUOUS_ENGINE_MARKERS"
        and before == after
        and not (xace_root / "xace.project.json").exists()
    )
    return {
        "check": {
            "name": "ambiguous_import_refused_before_writing",
            "ok": ok,
            "detail": (
                f"scan_reason={scan_report.get('reason')} refused_by_import={refused_by_import} "
                f"engine_files_unchanged={before == after} xace_project_written={(xace_root / 'xace.project.json').exists()}"
            ),
            "artifact": str(report_path),
        },
        "report": {
            "project_root": str(engine_root),
            "refusal_report": str(report_path),
            "reason": scan_report.get("reason"),
            "markers": scan_report.get("markers", []),
        },
    }


def _make_godot_fixture(root: Path) -> Path:
    (root / "scenes").mkdir(parents=True)
    (root / "assets").mkdir()
    (root / "scripts").mkdir()
    (root / "addons" / "xace_demo").mkdir(parents=True)
    (root / "project.godot").write_text(
        "[application]\nconfig/name=\"GodotGame\"\n\n[input]\njump={\"deadzone\":0.5}\n",
        encoding="utf-8",
    )
    (root / "scenes" / "main.tscn").write_text("[gd_scene format=3]\n", encoding="utf-8")
    (root / "assets" / "player.png").write_bytes(b"png-reference")
    (root / "scripts" / "player.gd").write_text("extends Node\n", encoding="utf-8")
    (root / "addons" / "xace_demo" / "plugin.cfg").write_text("[plugin]\nname=\"XACE Demo\"\n", encoding="utf-8")
    return root


def _make_unity_fixture(root: Path) -> Path:
    (root / "Assets" / "Scenes").mkdir(parents=True)
    (root / "Assets" / "Scripts").mkdir()
    (root / "Assets" / "Prefabs").mkdir()
    (root / "Assets" / "Plugins" / "Native").mkdir(parents=True)
    (root / "ProjectSettings").mkdir()
    (root / "Packages").mkdir()
    (root / "Assets" / "Scenes" / "Main.unity").write_text("%YAML 1.1\n", encoding="utf-8")
    (root / "Assets" / "Scripts" / "Player.cs").write_text("public class Player {}\n", encoding="utf-8")
    (root / "Assets" / "Prefabs" / "Player.prefab").write_text("%YAML 1.1\n", encoding="utf-8")
    (root / "Assets" / "Plugins" / "Native" / "XaceNative.dll").write_bytes(b"dll-reference")
    (root / "Assets" / "Controls.inputactions").write_text("{}\n", encoding="utf-8")
    (root / "ProjectSettings" / "ProjectVersion.txt").write_text("m_EditorVersion: 2022.3\n", encoding="utf-8")
    (root / "ProjectSettings" / "InputManager.asset").write_text("%YAML 1.1\n", encoding="utf-8")
    (root / "Packages" / "manifest.json").write_text("{}\n", encoding="utf-8")
    return root


def _make_unreal_fixture(root: Path) -> Path:
    (root / "Content" / "Maps").mkdir(parents=True)
    (root / "Content" / "Props").mkdir()
    (root / "Source" / "UnrealGame").mkdir(parents=True)
    (root / "Plugins" / "XaceDemo").mkdir(parents=True)
    (root / "Config").mkdir()
    (root / "UnrealGame.uproject").write_text('{"FileVersion":3}\n', encoding="utf-8")
    (root / "Content" / "Maps" / "Main.umap").write_bytes(b"umap-reference")
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
        rel = path.relative_to(root).as_posix()
        data = path.read_bytes()
        stat = path.stat()
        signature[rel] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }
    return signature


def _all_references_are_reference_only(report: dict[str, Any]) -> bool:
    for category in INVENTORY_CATEGORIES:
        section = report.get("inventory", {}).get(category, {})
        for reference in section.get("references", []):
            if reference.get("reference_only") is not True:
                return False
    return True


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
