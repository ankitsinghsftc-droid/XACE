#!/usr/bin/env python3
"""
Retained X10-059 proof for reversible adapter install/update/rollback/uninstall.

The check uses the production adapter transaction module against real adapter
source folders for Godot, Unity, and Unreal. Each fixture contains user-owned
engine data inside and outside the adapter destination; the proof records
before/after signatures and fails if XACE overwrites or deletes that data.
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

from adapter_installation import (  # noqa: E402
    ADAPTER_ENGINE_INSTALL_MANIFEST,
    build_adapter_payload,
    install_or_update_adapter,
    rollback_latest_adapter_transaction,
    uninstall_adapter,
)


REPORT_SCHEMA = "xace.adapter_reversibility_check_report.v1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the X10-059 reversible adapter install proof.")
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "target-codex-task59-adapter-reversibility" / "report.json"),
        help="Path to write the retained JSON report.",
    )
    parser.add_argument(
        "--artifact-dir",
        default=str(REPO_ROOT / "target-codex-task59-adapter-reversibility" / "artifacts"),
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
        print(f"adapter reversibility check PASSED ({len(report['checks'])} checks)")
    else:
        print("adapter reversibility check FAILED", file=sys.stderr)
        for check in report["checks"]:
            if not check["ok"]:
                print(f"- {check['name']}: {check['detail']}", file=sys.stderr)
    return 0 if report["ok"] else 1


def run_check(artifact_dir: Path) -> dict[str, Any]:
    fixtures_dir = artifact_dir / "fixtures"
    sources_dir = artifact_dir / "sources"
    reports_dir = artifact_dir / "reports"
    _safe_clean_dir(fixtures_dir, artifact_dir)
    _safe_clean_dir(sources_dir, artifact_dir)
    _safe_clean_dir(reports_dir, artifact_dir)
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    sources_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    checks: list[dict[str, Any]] = []
    engine_results: dict[str, Any] = {}
    for engine in ("godot", "unity", "unreal"):
        engine_root = _make_engine_fixture(fixtures_dir / engine, engine)
        source_v1 = _copy_adapter_source(engine, sources_dir / f"{engine}_v1")
        source_v2 = _copy_adapter_source(engine, sources_dir / f"{engine}_v2")
        mutation = _mutate_source_for_update(source_v2, engine)
        before = _tree_signature(engine_root)
        user_inside_rel = _destination_label(engine) + "/USER_KEEP.txt"
        user_outside_rel = _outside_user_file(engine)
        user_inside_before = before[user_inside_rel]["sha256"]
        user_outside_before = before[user_outside_rel]["sha256"]

        install = install_or_update_adapter(
            source_root=source_v1,
            engine_project_root=engine_root,
            engine_type=engine,
            generated_files=_generated_files(engine, "v1"),
        )
        target_path = _destination(engine_root, engine) / mutation["target_relative_path"]
        update_marker_path = _destination(engine_root, engine) / "xace_task59_update_marker.txt"
        install_target_hash = _sha256_file(target_path)
        install_manifest_exists = (_destination(engine_root, engine) / ADAPTER_ENGINE_INSTALL_MANIFEST).is_file()

        update = install_or_update_adapter(
            source_root=source_v2,
            engine_project_root=engine_root,
            engine_type=engine,
            overwrite=True,
            generated_files=_generated_files(engine, "v2"),
        )
        update_target_hash = _sha256_file(target_path)
        update_marker_installed = update_marker_path.is_file()

        rollback = rollback_latest_adapter_transaction(
            engine_project_root=engine_root,
            engine_type=engine,
        )
        rollback_target_hash = _sha256_file(target_path)
        update_marker_removed = not update_marker_path.exists()

        reinstall = install_or_update_adapter(
            source_root=source_v2,
            engine_project_root=engine_root,
            engine_type=engine,
            overwrite=True,
            generated_files=_generated_files(engine, "v2"),
        )
        uninstall = uninstall_adapter(
            engine_project_root=engine_root,
            engine_type=engine,
        )
        after = _tree_signature(engine_root)
        destination = _destination(engine_root, engine)
        manifest_removed = not (destination / ADAPTER_ENGINE_INSTALL_MANIFEST).exists()
        adapter_owned_removed = all(
            not (destination / path).exists()
            for path in reinstall.get("installed_files", [])
            if path != "USER_KEEP.txt"
        )
        user_inside_preserved = after.get(user_inside_rel, {}).get("sha256") == user_inside_before
        user_outside_preserved = after.get(user_outside_rel, {}).get("sha256") == user_outside_before
        no_user_data_deleted = user_inside_preserved and user_outside_preserved
        update_changed_owned_file = update_target_hash != install_target_hash
        rollback_restored_owned_file = rollback_target_hash == install_target_hash
        ok = (
            install.get("ok") is True
            and update.get("ok") is True
            and rollback.get("ok") is True
            and reinstall.get("ok") is True
            and uninstall.get("ok") is True
            and install_manifest_exists
            and update_changed_owned_file
            and update_marker_installed
            and rollback_restored_owned_file
            and update_marker_removed
            and manifest_removed
            and adapter_owned_removed
            and no_user_data_deleted
        )

        engine_report = {
            "engine_project_root": str(engine_root),
            "source_v1": str(source_v1),
            "source_v2": str(source_v2),
            "mutation": mutation,
            "install": _compact_operation(install),
            "update": _compact_operation(update),
            "rollback": _compact_operation(rollback),
            "reinstall": _compact_operation(reinstall),
            "uninstall": _compact_operation(uninstall),
            "before_signature_path": str(reports_dir / f"{engine}_before_signature.json"),
            "after_signature_path": str(reports_dir / f"{engine}_after_signature.json"),
            "user_inside_preserved": user_inside_preserved,
            "user_outside_preserved": user_outside_preserved,
            "adapter_owned_removed": adapter_owned_removed,
        }
        _write_json(reports_dir / f"{engine}_before_signature.json", before)
        _write_json(reports_dir / f"{engine}_after_signature.json", after)
        _write_json(reports_dir / f"{engine}_operation_report.json", engine_report)
        checks.append({
            "name": f"{engine}_adapter_reversibility",
            "ok": ok,
            "detail": (
                f"install={install.get('ok')} update={update.get('ok')} rollback={rollback.get('ok')} "
                f"uninstall={uninstall.get('ok')} user_preserved={no_user_data_deleted} "
                f"rollback_restored={rollback_restored_owned_file} adapter_removed={adapter_owned_removed}"
            ),
            "artifacts": {
                "operation_report": str(reports_dir / f"{engine}_operation_report.json"),
                "before_signature": str(reports_dir / f"{engine}_before_signature.json"),
                "after_signature": str(reports_dir / f"{engine}_after_signature.json"),
            },
        })
        engine_results[engine] = engine_report

    return {
        "schema": REPORT_SCHEMA,
        "task": "X10-059",
        "generated_at_utc": _utc_now(),
        "ok": all(check["ok"] for check in checks),
        "x10_059_complete": all(check["ok"] for check in checks),
        "checks": checks,
        "artifact_dir": str(artifact_dir),
        "engine_results": engine_results,
    }


def _copy_adapter_source(engine: str, destination: Path) -> Path:
    source = REPO_ROOT / "adapters" / engine
    shutil.copytree(source, destination)
    return destination


def _mutate_source_for_update(source_root: Path, engine: str) -> dict[str, str]:
    payload = build_adapter_payload(source_root, engine, generated_files=_generated_files(engine, "v1"))
    candidates = [
        item
        for item in payload
        if not item.generated and Path(item.source_relative_path).suffix.lower() in {".gd", ".cs", ".cpp", ".h", ".md"}
    ]
    if not candidates:
        raise RuntimeError(f"No mutable adapter source file found for {engine}")
    selected = candidates[0]
    source_file = source_root / selected.source_relative_path
    source_file.write_text(source_file.read_text(encoding="utf-8") + "\n// X10-059 update marker\n", encoding="utf-8")
    (source_root / "xace_task59_update_marker.txt").write_text("installed only by update\n", encoding="utf-8")
    return {
        "source_relative_path": selected.source_relative_path,
        "target_relative_path": selected.target_relative_path,
    }


def _make_engine_fixture(root: Path, engine: str) -> Path:
    if engine == "godot":
        (root / "addons" / "xace").mkdir(parents=True)
        (root / "scenes").mkdir(parents=True)
        (root / "project.godot").write_text("[application]\nconfig/name=\"Task59\"\n", encoding="utf-8")
        (root / "addons" / "xace" / "USER_KEEP.txt").write_text("godot user adapter note\n", encoding="utf-8")
        (root / "scenes" / "user_scene.tscn").write_text("[gd_scene format=3]\n", encoding="utf-8")
    elif engine == "unity":
        (root / "Assets" / "XACE").mkdir(parents=True)
        (root / "ProjectSettings").mkdir(parents=True)
        (root / "Assets" / "Scenes").mkdir(parents=True)
        (root / "Assets" / "XACE" / "USER_KEEP.txt").write_text("unity user adapter note\n", encoding="utf-8")
        (root / "Assets" / "Scenes" / "UserScene.unity").write_text("%YAML 1.1\n", encoding="utf-8")
        (root / "ProjectSettings" / "ProjectVersion.txt").write_text("m_EditorVersion: 2022.3\n", encoding="utf-8")
    elif engine == "unreal":
        (root / "Plugins" / "XACE").mkdir(parents=True)
        (root / "Content" / "Maps").mkdir(parents=True)
        (root / "Task59.uproject").write_text("{\"FileVersion\":3}\n", encoding="utf-8")
        (root / "Plugins" / "XACE" / "USER_KEEP.txt").write_text("unreal user adapter note\n", encoding="utf-8")
        (root / "Content" / "Maps" / "UserMap.umap").write_text("Begin Map\n", encoding="utf-8")
    else:
        raise ValueError(engine)
    return root


def _generated_files(engine: str, version: str) -> dict[str, str]:
    if engine == "godot":
        return {
            "plugin.cfg": "\n".join([
                "[plugin]",
                "",
                "name=\"XACE Adapter\"",
                "description=\"Connects a Godot project to the XACE runtime.\"",
                "author=\"XACE\"",
                f"version=\"0.1.0-{version}\"",
                "script=\"xace_editor_plugin.gd\"",
                "",
            ]),
            "xace_editor_plugin.gd": "\n".join([
                "@tool",
                "extends EditorPlugin",
                "",
                f"# generated {version}",
                "func _enter_tree() -> void:",
                "\tpass",
                "",
                "func _exit_tree() -> void:",
                "\tpass",
                "",
            ]),
        }
    if engine == "unreal":
        return {
            "XACE.uplugin": json.dumps({"FileVersion": 3, "FriendlyName": f"XACE Adapter {version}"}, sort_keys=True),
            "Source/XACEAdapter/XACEAdapter.Build.cs": f"// XACE build {version}\n",
            "Source/XACEAdapter/Public/XACEAdapterModule.h": f"// XACE module h {version}\n",
            "Source/XACEAdapter/Private/XACEAdapterModule.cpp": f"// XACE module cpp {version}\n",
        }
    return {}


def _destination(engine_root: Path, engine: str) -> Path:
    if engine == "godot":
        return engine_root / "addons" / "xace"
    if engine == "unity":
        return engine_root / "Assets" / "XACE"
    if engine == "unreal":
        return engine_root / "Plugins" / "XACE"
    raise ValueError(engine)


def _destination_label(engine: str) -> str:
    return {
        "godot": "addons/xace",
        "unity": "Assets/XACE",
        "unreal": "Plugins/XACE",
    }[engine]


def _outside_user_file(engine: str) -> str:
    return {
        "godot": "scenes/user_scene.tscn",
        "unity": "Assets/Scenes/UserScene.unity",
        "unreal": "Content/Maps/UserMap.umap",
    }[engine]


def _compact_operation(operation: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": operation.get("ok"),
        "operation": operation.get("operation"),
        "status": operation.get("status"),
        "copied": operation.get("copied", []),
        "installed_files": operation.get("installed_files", []),
        "skipped": operation.get("skipped", []),
        "unchanged": operation.get("unchanged", []),
        "removed_stale": operation.get("removed_stale", []),
        "rolled_back": operation.get("rolled_back", []),
        "removed": operation.get("removed", []),
        "preserved": operation.get("preserved", []),
        "conflicts": operation.get("conflicts", []),
        "manifest_path": operation.get("manifest_path"),
        "transaction_path": operation.get("transaction_path"),
    }


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


def _safe_clean_dir(path: Path, allowed_root: Path) -> None:
    resolved = path.resolve()
    allowed = allowed_root.resolve()
    if not str(resolved).startswith(str(allowed)):
        raise RuntimeError(f"Refusing to clean path outside artifact root: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
