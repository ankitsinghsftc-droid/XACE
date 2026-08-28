#!/usr/bin/env python3
"""
Reversible engine-adapter installation transactions.

This module owns the safety boundary for copying XACE engine adapters into
creator-owned Godot, Unity, and Unreal project trees. The invariant is simple:
XACE may update or remove files that an earlier XACE install manifest owns, but
it must not overwrite or delete unrelated creator engine data.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


ADAPTER_INSTALL_MANIFEST_SCHEMA = "xace.adapter_engine_install_manifest.v1"
ADAPTER_TRANSACTION_SCHEMA = "xace.adapter_install_transaction.v1"
ADAPTER_UNINSTALL_REPORT_SCHEMA = "xace.adapter_uninstall_report.v1"
ADAPTER_ENGINE_INSTALL_MANIFEST = "xace_engine_install_manifest.json"
ADAPTER_BACKUP_DIR = ".xace_adapter_backups"


@dataclass(frozen=True)
class AdapterPayloadFile:
    """
    One file that should exist under the installed adapter destination.

    ``source_relative_path`` is retained for diagnostics and compatibility with
    old Builder responses. ``target_relative_path`` is the path under the engine
    adapter destination that the transaction owns.
    """

    source_relative_path: str
    target_relative_path: str
    data: bytes
    generated: bool = False

    @property
    def sha256(self) -> str:
        return _sha256_bytes(self.data)

    @property
    def size(self) -> int:
        return len(self.data)


def build_adapter_payload(
    source_root: str | Path,
    engine_type: str,
    *,
    generated_files: Mapping[str, str | bytes] | None = None,
) -> list[AdapterPayloadFile]:
    """
    Build the install payload from a prepared adapter folder plus generated files.

    The target mapping mirrors Builder's installed layout:
    - Godot skips the source ``project.godot`` file and rewrites the demo scene
      resource path for ``addons/xace``.
    - Unreal headers and source files are placed under the plugin module's
      Public/Private folders.
    """

    key = _engine_key(engine_type)
    root = Path(source_root).resolve()
    if not root.exists() or not root.is_dir():
        raise AdapterInstallationError(f"Adapter source folder not found: {root}")

    payload: list[AdapterPayloadFile] = []
    seen_targets: set[str] = set()
    for source_path in sorted(root.rglob("*"), key=lambda item: item.as_posix().lower()):
        if not source_path.is_file():
            continue
        source_relative = _normalise_relative_path(source_path.relative_to(root).as_posix())
        if source_relative == "xace_adapter_manifest.json":
            continue
        if source_relative in {"xace_adapter_package_version_manifest.json", "xace_adapter_package_handoff_manifest.json"}:
            continue
        if source_relative.endswith(".pyc") or "__pycache__" in PurePosixPath(source_relative).parts:
            continue
        if key == "godot" and source_relative == "project.godot":
            continue
        target_relative = _target_relative_for_engine(key, source_relative)
        data = source_path.read_bytes()
        if key == "godot" and source_relative == "xace_godot_main.tscn":
            data = data.decode("utf-8").replace(
                'path="res://xace_godot_main.gd"',
                'path="res://addons/xace/xace_godot_main.gd"',
            ).encode("utf-8")
        _append_payload(
            payload,
            seen_targets,
            AdapterPayloadFile(
                source_relative_path=source_relative,
                target_relative_path=target_relative,
                data=data,
                generated=False,
            ),
        )

    for target_relative, content in sorted((generated_files or {}).items()):
        normalised_target = _normalise_relative_path(target_relative)
        data = content if isinstance(content, bytes) else content.encode("utf-8")
        _append_payload(
            payload,
            seen_targets,
            AdapterPayloadFile(
                source_relative_path=f"<generated>/{normalised_target}",
                target_relative_path=normalised_target,
                data=data,
                generated=True,
            ),
        )
    return payload


def install_or_update_adapter(
    *,
    source_root: str | Path,
    engine_project_root: str | Path,
    engine_type: str,
    destination: str | Path | None = None,
    overwrite: bool = False,
    generated_files: Mapping[str, str | bytes] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Install or update an adapter using an ownership-aware transaction.

    Existing non-XACE files are never overwritten, even when ``overwrite`` is
    true. Existing XACE-owned files are only overwritten when the current bytes
    still match the previous manifest hash, so creator edits to adapter files
    are preserved and surfaced as conflicts.
    """

    key = _engine_key(engine_type)
    source = Path(source_root).resolve()
    engine_root = Path(engine_project_root).resolve()
    install_root = Path(destination).resolve() if destination is not None else _default_destination(engine_root, key)
    _validate_destination(engine_root, install_root)
    payload = build_adapter_payload(source, key, generated_files=generated_files)

    manifest_path = install_root / ADAPTER_ENGINE_INSTALL_MANIFEST
    previous_manifest = _read_manifest(manifest_path)
    previous_owned = _owned_file_map(previous_manifest, key, install_root)
    operation = "update" if previous_manifest else "install"
    transaction_id = f"{_utc_now().replace(':', '').replace('-', '').replace('.', '')}-{uuid.uuid4().hex[:12]}"
    backup_root = install_root / ADAPTER_BACKUP_DIR / transaction_id

    copied: list[str] = []
    installed_files: list[dict[str, Any]] = []
    skipped_existing: list[str] = []
    unchanged: list[str] = []
    removed_stale: list[str] = []
    conflicts: list[dict[str, Any]] = []
    file_actions: list[dict[str, Any]] = []
    payload_targets = {item.target_relative_path for item in payload}

    install_root.mkdir(parents=True, exist_ok=True)
    previous_manifest_backup: str | None = None
    if manifest_path.exists():
        previous_manifest_backup = _backup_file(manifest_path, backup_root, "__manifest__")

    for item in payload:
        target = _resolve_under(install_root, item.target_relative_path)
        before = _file_state(target)
        owned_before = previous_owned.get(item.target_relative_path)
        if before["exists"]:
            if owned_before is None:
                conflicts.append({
                    "path": item.target_relative_path,
                    "reason": "TARGET_EXISTS_NOT_XACE_OWNED",
                    "current_sha256": before["sha256"],
                })
                skipped_existing.append(item.source_relative_path)
                continue
            if owned_before.get("sha256") and before["sha256"] != owned_before.get("sha256"):
                conflicts.append({
                    "path": item.target_relative_path,
                    "reason": "XACE_OWNED_FILE_MODIFIED_BY_USER",
                    "expected_sha256": owned_before.get("sha256"),
                    "current_sha256": before["sha256"],
                })
                skipped_existing.append(item.source_relative_path)
                continue
            if before["sha256"] == item.sha256:
                unchanged.append(item.target_relative_path)
                installed_files.append(_owned_record(item, target))
                continue
            if not overwrite:
                skipped_existing.append(item.source_relative_path)
                installed_files.append(_owned_record_from_previous(item.target_relative_path, target, owned_before))
                continue

        backup_relative = _backup_file(target, backup_root, item.target_relative_path) if before["exists"] else None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(item.data)
        after = _file_state(target)
        file_actions.append({
            "action": "write",
            "target_relative_path": item.target_relative_path,
            "source_relative_path": item.source_relative_path,
            "generated": item.generated,
            "before": {**before, "backup_relative_path": backup_relative},
            "after": after,
        })
        copied.append(item.source_relative_path)
        installed_files.append(_owned_record(item, target))

    for target_relative, previous in sorted(previous_owned.items()):
        if target_relative in payload_targets:
            continue
        target = _resolve_under(install_root, target_relative)
        before = _file_state(target)
        if not before["exists"]:
            continue
        if previous.get("sha256") and before["sha256"] != previous.get("sha256"):
            conflicts.append({
                "path": target_relative,
                "reason": "STALE_XACE_FILE_MODIFIED_BY_USER",
                "expected_sha256": previous.get("sha256"),
                "current_sha256": before["sha256"],
            })
            continue
        backup_relative = _backup_file(target, backup_root, target_relative)
        target.unlink()
        removed_stale.append(target_relative)
        file_actions.append({
            "action": "remove_stale",
            "target_relative_path": target_relative,
            "before": {**before, "backup_relative_path": backup_relative},
            "after": _file_state(target),
        })

    manifest = {
        "schema": ADAPTER_INSTALL_MANIFEST_SCHEMA,
        "target": key,
        "engine_type": key,
        "source": str(source),
        "engine_project_path": str(engine_root),
        "destination_path": str(install_root),
        "installed_at_utc": _utc_now(),
        "operation": operation,
        "transaction_id": transaction_id,
        "overwrite": bool(overwrite),
        "owned_files": sorted(installed_files, key=lambda item: item["path"]),
        "copied": copied,
        "skipped": skipped_existing,
        "unchanged": unchanged,
        "removed_stale": removed_stale,
        "conflicts": conflicts,
        "metadata": dict(metadata or {}),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    after_manifest = _file_state(manifest_path)

    transaction = {
        "schema": ADAPTER_TRANSACTION_SCHEMA,
        "transaction_id": transaction_id,
        "operation": operation,
        "engine_type": key,
        "source_root": str(source),
        "engine_project_path": str(engine_root),
        "destination_path": str(install_root),
        "manifest_path": str(manifest_path),
        "manifest_relative_path": ADAPTER_ENGINE_INSTALL_MANIFEST,
        "backup_root": str(backup_root),
        "previous_manifest_backup": previous_manifest_backup,
        "after_manifest": after_manifest,
        "file_actions": file_actions,
        "created_at_utc": _utc_now(),
    }
    backup_root.mkdir(parents=True, exist_ok=True)
    transaction_path = backup_root / "transaction.json"
    transaction_path.write_text(json.dumps(transaction, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_latest_transaction_pointer(install_root, transaction_path)
    _remove_empty_dirs(install_root, install_root)

    return {
        "ok": not conflicts,
        "schema": ADAPTER_INSTALL_MANIFEST_SCHEMA,
        "target": key,
        "label": _engine_label(key),
        "operation": operation,
        "engine_project_path": str(engine_root),
        "destination_path": str(install_root),
        "source_path": str(source),
        "copied": copied,
        "installed_files": [item["path"] for item in sorted(installed_files, key=lambda value: value["path"])],
        "skipped": skipped_existing,
        "unchanged": unchanged,
        "removed_stale": removed_stale,
        "conflicts": conflicts,
        "manifest_path": str(manifest_path),
        "transaction_path": str(transaction_path),
        "transaction": transaction,
    }


def rollback_latest_adapter_transaction(
    *,
    engine_project_root: str | Path,
    engine_type: str,
    destination: str | Path | None = None,
) -> dict[str, Any]:
    key = _engine_key(engine_type)
    engine_root = Path(engine_project_root).resolve()
    install_root = Path(destination).resolve() if destination is not None else _default_destination(engine_root, key)
    _validate_destination(engine_root, install_root)
    pointer = install_root / ADAPTER_BACKUP_DIR / "latest_transaction.json"
    if not pointer.exists():
        return {
            "ok": True,
            "schema": ADAPTER_TRANSACTION_SCHEMA,
            "operation": "rollback",
            "target": key,
            "status": "noop",
            "reason": "No adapter transaction is available to roll back.",
            "rolled_back": [],
            "conflicts": [],
        }
    payload = json.loads(pointer.read_text(encoding="utf-8"))
    transaction_path = Path(str(payload.get("transaction_path") or "")).resolve()
    return rollback_adapter_transaction(transaction_path)


def rollback_adapter_transaction(transaction_or_path: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    """
    Roll back an install/update transaction while preserving user modifications.
    """

    transaction = _load_transaction(transaction_or_path)
    if transaction.get("schema") != ADAPTER_TRANSACTION_SCHEMA:
        raise AdapterInstallationError("Unsupported adapter transaction schema.")

    destination = Path(str(transaction["destination_path"])).resolve()
    manifest_path = Path(str(transaction["manifest_path"])).resolve()
    backup_root = Path(str(transaction["backup_root"])).resolve()
    rolled_back: list[str] = []
    restored: list[str] = []
    removed: list[str] = []
    conflicts: list[dict[str, Any]] = []

    for action in reversed(list(transaction.get("file_actions", []))):
        target_relative = _normalise_relative_path(str(action.get("target_relative_path") or ""))
        target = _resolve_under(destination, target_relative)
        before = action.get("before", {}) or {}
        after = action.get("after", {}) or {}
        current = _file_state(target)

        if action.get("action") == "write":
            after_hash = after.get("sha256")
            if current["exists"] and after_hash and current.get("sha256") != after_hash:
                conflicts.append({
                    "path": target_relative,
                    "reason": "CURRENT_FILE_CHANGED_AFTER_TRANSACTION",
                    "expected_sha256": after_hash,
                    "current_sha256": current.get("sha256"),
                })
                continue
            if before.get("exists"):
                backup_relative = before.get("backup_relative_path")
                backup = _resolve_under(backup_root, str(backup_relative)) if backup_relative else None
                if backup is None or not backup.exists():
                    conflicts.append({"path": target_relative, "reason": "BACKUP_FILE_MISSING"})
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, target)
                restored.append(target_relative)
            else:
                if target.exists():
                    target.unlink()
                removed.append(target_relative)
            rolled_back.append(target_relative)

        elif action.get("action") == "remove_stale":
            if target.exists():
                conflicts.append({"path": target_relative, "reason": "TARGET_RECREATED_AFTER_TRANSACTION"})
                continue
            backup_relative = before.get("backup_relative_path")
            backup = _resolve_under(backup_root, str(backup_relative)) if backup_relative else None
            if backup is None or not backup.exists():
                conflicts.append({"path": target_relative, "reason": "BACKUP_FILE_MISSING"})
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
            restored.append(target_relative)
            rolled_back.append(target_relative)

    after_manifest = transaction.get("after_manifest", {}) or {}
    manifest_current = _file_state(manifest_path)
    if manifest_current["exists"] and after_manifest.get("sha256") and manifest_current.get("sha256") != after_manifest.get("sha256"):
        conflicts.append({
            "path": ADAPTER_ENGINE_INSTALL_MANIFEST,
            "reason": "MANIFEST_CHANGED_AFTER_TRANSACTION",
            "expected_sha256": after_manifest.get("sha256"),
            "current_sha256": manifest_current.get("sha256"),
        })
    else:
        previous_manifest_backup = transaction.get("previous_manifest_backup")
        if previous_manifest_backup:
            backup = _resolve_under(backup_root, str(previous_manifest_backup))
            if backup.exists():
                manifest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, manifest_path)
            else:
                conflicts.append({"path": ADAPTER_ENGINE_INSTALL_MANIFEST, "reason": "MANIFEST_BACKUP_MISSING"})
        elif manifest_path.exists():
            manifest_path.unlink()

    _remove_empty_dirs(destination, destination)
    return {
        "ok": not conflicts,
        "schema": ADAPTER_TRANSACTION_SCHEMA,
        "operation": "rollback",
        "target": transaction.get("engine_type"),
        "transaction_id": transaction.get("transaction_id"),
        "destination_path": str(destination),
        "rolled_back": rolled_back,
        "restored": restored,
        "removed": removed,
        "conflicts": conflicts,
    }


def uninstall_adapter(
    *,
    engine_project_root: str | Path,
    engine_type: str,
    destination: str | Path | None = None,
) -> dict[str, Any]:
    """
    Remove installed adapter files that the XACE manifest still owns.

    Files not listed in the manifest, or listed files whose bytes no longer
    match the manifest hash, are preserved and reported as user-owned/conflicted.
    """

    key = _engine_key(engine_type)
    engine_root = Path(engine_project_root).resolve()
    install_root = Path(destination).resolve() if destination is not None else _default_destination(engine_root, key)
    _validate_destination(engine_root, install_root)
    manifest_path = install_root / ADAPTER_ENGINE_INSTALL_MANIFEST
    manifest = _read_manifest(manifest_path)
    if not manifest:
        return {
            "ok": True,
            "schema": ADAPTER_UNINSTALL_REPORT_SCHEMA,
            "target": key,
            "status": "noop",
            "reason": "No XACE adapter install manifest found.",
            "removed": [],
            "preserved": [],
            "conflicts": [],
        }

    owned = _owned_file_map(manifest, key, install_root)
    removed: list[str] = []
    missing: list[str] = []
    preserved: list[str] = []
    conflicts: list[dict[str, Any]] = []
    for target_relative, record in sorted(owned.items(), key=lambda item: item[0].count("/"), reverse=True):
        target = _resolve_under(install_root, target_relative)
        current = _file_state(target)
        if not current["exists"]:
            missing.append(target_relative)
            continue
        expected_hash = record.get("sha256")
        if expected_hash and current.get("sha256") != expected_hash:
            conflicts.append({
                "path": target_relative,
                "reason": "XACE_OWNED_FILE_MODIFIED_BY_USER",
                "expected_sha256": expected_hash,
                "current_sha256": current.get("sha256"),
            })
            preserved.append(target_relative)
            continue
        target.unlink()
        removed.append(target_relative)

    if conflicts:
        preserved.extend(_remaining_user_files(install_root, set(owned)))
    else:
        if manifest_path.exists():
            manifest_path.unlink()
        backups = install_root / ADAPTER_BACKUP_DIR
        if backups.exists():
            shutil.rmtree(backups)
        preserved.extend(_remaining_user_files(install_root, set(owned)))

    _remove_empty_dirs(install_root, install_root)
    return {
        "ok": not conflicts,
        "schema": ADAPTER_UNINSTALL_REPORT_SCHEMA,
        "target": key,
        "status": "uninstalled" if not conflicts else "conflicted",
        "engine_project_path": str(engine_root),
        "destination_path": str(install_root),
        "manifest_path": str(manifest_path),
        "removed": removed,
        "missing": missing,
        "preserved": sorted(set(preserved)),
        "conflicts": conflicts,
    }


class AdapterInstallationError(RuntimeError):
    """Raised when an adapter transaction would leave the safe project boundary."""


def _append_payload(payload: list[AdapterPayloadFile], seen_targets: set[str], item: AdapterPayloadFile) -> None:
    if item.target_relative_path in seen_targets:
        raise AdapterInstallationError(f"Duplicate adapter target path: {item.target_relative_path}")
    seen_targets.add(item.target_relative_path)
    payload.append(item)


def _engine_key(engine_type: str) -> str:
    key = str(engine_type or "").strip().lower()
    if key not in {"godot", "unity", "unreal"}:
        raise AdapterInstallationError(f"Unsupported adapter engine type: {engine_type}")
    return key


def _engine_label(engine_type: str) -> str:
    return {"godot": "Godot GDScript", "unity": "Unity C#", "unreal": "Unreal C++"}.get(engine_type, engine_type)


def _default_destination(engine_root: Path, engine_type: str) -> Path:
    if engine_type == "godot":
        return engine_root / "addons" / "xace"
    if engine_type == "unity":
        return engine_root / "Assets" / "XACE"
    if engine_type == "unreal":
        return engine_root / "Plugins" / "XACE"
    return engine_root / ".xace" / "adapter" / engine_type


def _target_relative_for_engine(engine_type: str, relative_path: str) -> str:
    rel = _normalise_relative_path(relative_path)
    name = PurePosixPath(rel).name
    if engine_type == "unreal":
        if rel.endswith(".h"):
            return _normalise_relative_path(f"Source/XACEAdapter/Public/{name}")
        if rel.endswith(".cpp"):
            return _normalise_relative_path(f"Source/XACEAdapter/Private/{name}")
    return rel


def _read_manifest(manifest_path: Path) -> dict[str, Any] | None:
    if not manifest_path.exists():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _owned_file_map(manifest: Mapping[str, Any] | None, engine_type: str, destination: Path) -> dict[str, dict[str, Any]]:
    if not manifest:
        return {}
    owned: dict[str, dict[str, Any]] = {}
    for item in manifest.get("owned_files", []) or []:
        if not isinstance(item, dict):
            continue
        try:
            rel = _normalise_relative_path(str(item.get("path") or ""))
        except AdapterInstallationError:
            continue
        owned[rel] = dict(item)

    # Legacy manifests written before X10-059 used a "copied" list without a
    # schema. Treat existing files from that list as XACE-owned so upgrades can
    # be safely backed up and rolled back instead of being considered user data.
    if not owned:
        for copied in manifest.get("copied", []) or []:
            try:
                rel = _target_relative_for_engine(engine_type, str(copied))
                path = _resolve_under(destination, rel)
            except AdapterInstallationError:
                continue
            if path.exists() and path.is_file():
                owned[rel] = {
                    "path": rel,
                    "sha256": _sha256_file(path),
                    "size": path.stat().st_size,
                    "legacy": True,
                }
    return owned


def _owned_record(item: AdapterPayloadFile, target: Path) -> dict[str, Any]:
    return {
        "path": item.target_relative_path,
        "source_path": item.source_relative_path,
        "sha256": item.sha256,
        "size": item.size,
        "generated": item.generated,
        "target_path": str(target),
    }


def _owned_record_from_previous(target_relative: str, target: Path, previous: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": target_relative,
        "source_path": str(previous.get("source_path") or target_relative),
        "sha256": str(previous.get("sha256") or _sha256_file(target)),
        "size": int(previous.get("size") or target.stat().st_size),
        "generated": bool(previous.get("generated", False)),
        "target_path": str(target),
    }


def _backup_file(path: Path, backup_root: Path, relative_path: str) -> str:
    rel = _normalise_relative_path(relative_path)
    backup = _resolve_under(backup_root, rel)
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup)
    return rel


def _write_latest_transaction_pointer(destination: Path, transaction_path: Path) -> None:
    pointer = destination / ADAPTER_BACKUP_DIR / "latest_transaction.json"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(
        json.dumps({
            "schema": "xace.adapter_latest_transaction.v1",
            "transaction_path": str(transaction_path),
            "updated_at_utc": _utc_now(),
        }, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_transaction(transaction_or_path: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(transaction_or_path, Mapping):
        return dict(transaction_or_path)
    path = Path(transaction_or_path).resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AdapterInstallationError(f"Adapter transaction is not an object: {path}")
    return payload


def _remaining_user_files(destination: Path, owned_paths: set[str]) -> list[str]:
    if not destination.exists():
        return []
    remaining: list[str] = []
    for path in sorted(destination.rglob("*"), key=lambda item: item.as_posix().lower()):
        if not path.is_file():
            continue
        rel = path.relative_to(destination).as_posix()
        if rel == ADAPTER_ENGINE_INSTALL_MANIFEST or rel.startswith(f"{ADAPTER_BACKUP_DIR}/"):
            continue
        if rel not in owned_paths:
            remaining.append(rel)
    return remaining


def _file_state(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {"exists": False}
    data = path.read_bytes()
    return {
        "exists": True,
        "sha256": _sha256_bytes(data),
        "size": len(data),
    }


def _normalise_relative_path(path: str) -> str:
    raw = str(path).replace("\\", "/").strip()
    if raw.startswith("/"):
        raise AdapterInstallationError(f"Absolute adapter path is not allowed: {path}")
    parts = [part for part in raw.split("/") if part not in {"", "."}]
    if not parts:
        raise AdapterInstallationError("Empty adapter path is not allowed.")
    if any(part == ".." for part in parts):
        raise AdapterInstallationError(f"Parent traversal is not allowed in adapter path: {path}")
    if any(":" in part for part in parts):
        raise AdapterInstallationError(f"Drive or stream syntax is not allowed in adapter path: {path}")
    return PurePosixPath(*parts).as_posix()


def _resolve_under(root: Path, relative_path: str) -> Path:
    rel = _normalise_relative_path(relative_path)
    target = (root / Path(*PurePosixPath(rel).parts)).resolve()
    root_resolved = root.resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise AdapterInstallationError(f"Adapter path escapes destination: {relative_path}") from exc
    return target


def _validate_destination(engine_root: Path, destination: Path) -> None:
    engine = engine_root.resolve()
    dest = destination.resolve()
    try:
        dest.relative_to(engine)
    except ValueError as exc:
        raise AdapterInstallationError(f"Adapter destination escapes engine project: {destination}") from exc


def _remove_empty_dirs(root: Path, stop_at: Path) -> None:
    if not root.exists():
        return
    stop = stop_at.resolve()
    candidates = sorted(
        [path for path in root.rglob("*") if path.is_dir()],
        key=lambda item: len(item.parts),
        reverse=True,
    )
    candidates.append(root)
    for path in candidates:
        resolved = path.resolve()
        try:
            resolved.relative_to(stop)
        except ValueError:
            continue
        if resolved == stop and any(resolved.iterdir()):
            continue
        try:
            path.rmdir()
        except OSError:
            pass


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
