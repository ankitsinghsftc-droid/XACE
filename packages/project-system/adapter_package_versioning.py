"""
adapter_package_versioning.py - X10-062 adapter package manifests.

The adapter package handoff is not a game-export pipeline; it is a boundary
where XACE gives an engine-owned project a self-describing adapter package. This
module owns the package manifest, compatibility metadata, lifecycle script
declarations, rollback-support declaration, and SHA-256 file inventory for that
handoff package.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from adapter_installation import (  # noqa: E402
    ADAPTER_BACKUP_DIR,
    ADAPTER_ENGINE_INSTALL_MANIFEST,
    ADAPTER_INSTALL_MANIFEST_SCHEMA,
    ADAPTER_TRANSACTION_SCHEMA,
    ADAPTER_UNINSTALL_REPORT_SCHEMA,
)
from project_manifest import PROJECT_SCHEMA_VERSION  # noqa: E402


ADAPTER_PACKAGE_MANIFEST_SCHEMA = "xace.adapter_package_version_manifest.v1"
ADAPTER_PACKAGE_VERIFICATION_SCHEMA = "xace.adapter_package_version_verification.v1"
ADAPTER_PACKAGE_MANIFEST = "xace_adapter_package_version_manifest.json"
ADAPTER_PACKAGE_LIFECYCLE_SCRIPT = "xace_adapter_package_lifecycle.py"
HANDOFF_MANIFEST = "xace_adapter_package_handoff_manifest.json"
PACKAGE_VERSION = "0.1.0"
ADAPTER_PROTOCOL_VERSION = 1
SUPPORTED_TARGETS = ("godot", "unity", "unreal")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")

EXCLUDED_CHECKSUM_FILES = {
    ADAPTER_PACKAGE_MANIFEST,
    HANDOFF_MANIFEST,
}

SKIP_DIRS = {
    ".git",
    ".xace_adapter_backups",
    "__pycache__",
    "node_modules",
    "target",
    "dist",
    "build",
}

TARGET_REQUIRED_FILES: dict[str, tuple[str, ...]] = {
    "godot": (
        "xace_protocol.gd",
        "xace_transport.gd",
        "xace_delta_applicator.gd",
        "xace_input_collector.gd",
        ADAPTER_PACKAGE_LIFECYCLE_SCRIPT,
    ),
    "unity": (
        "XACE.Adapter.Unity.asmdef",
        "XaceTransport.cs",
        "XaceDeltaApplicator.cs",
        "XaceInputCollector.cs",
        ADAPTER_PACKAGE_LIFECYCLE_SCRIPT,
    ),
    "unreal": (
        "XaceTransport.h",
        "XaceTransport.cpp",
        "XaceDeltaApplicator.h",
        "XaceDeltaApplicator.cpp",
        ADAPTER_PACKAGE_LIFECYCLE_SCRIPT,
    ),
}

TARGET_METADATA: dict[str, dict[str, Any]] = {
    "godot": {
        "label": "Godot GDScript",
        "package_id": "xace.adapter.godot",
        "engine_id": "godot",
        "engine_version_range": ">=4.0 <5.0",
        "install_destination": "addons/xace",
        "adapter_language": "gdscript",
    },
    "unity": {
        "label": "Unity C#",
        "package_id": "xace.adapter.unity",
        "engine_id": "unity",
        "engine_version_range": ">=2021.3 <7000.0",
        "install_destination": "Assets/XACE",
        "adapter_language": "csharp",
    },
    "unreal": {
        "label": "Unreal C++",
        "package_id": "xace.adapter.unreal",
        "engine_id": "unreal",
        "engine_version_range": ">=5.0 <6.0",
        "install_destination": "Plugins/XACE",
        "adapter_language": "cpp",
    },
}


def build_adapter_package_manifest(
    package_root: str | Path,
    target: str,
    *,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic package manifest for an adapter package root."""

    key = _normalize_target(target)
    root = Path(package_root).resolve()
    metadata = TARGET_METADATA[key]
    files = _collect_file_checksums(root)
    digest_payload = {
        "schema": ADAPTER_PACKAGE_MANIFEST_SCHEMA,
        "package_id": metadata["package_id"],
        "target": key,
        "version": PACKAGE_VERSION,
        "adapter_protocol_version": ADAPTER_PROTOCOL_VERSION,
        "compatibility_matrix": _compatibility_matrix(key),
        "dependencies": _dependencies(key),
        "lifecycle_scripts": _lifecycle_scripts(key),
        "rollback_support": _rollback_support(),
        "files": files,
    }
    package_content_sha256 = _sha256_json(digest_payload)
    return {
        "schema": ADAPTER_PACKAGE_MANIFEST_SCHEMA,
        "package_id": metadata["package_id"],
        "package_name": f"XACE {metadata['label']} Adapter Package",
        "package_role": "adapter_package_handoff",
        "target": key,
        "label": metadata["label"],
        "version": PACKAGE_VERSION,
        "adapter_protocol_version": ADAPTER_PROTOCOL_VERSION,
        "shipping_boundary": "engine_project_owns_shipping_package",
        "generated_at_utc": generated_at_utc or _utc_now(),
        "compatibility_matrix": digest_payload["compatibility_matrix"],
        "dependencies": digest_payload["dependencies"],
        "lifecycle_scripts": digest_payload["lifecycle_scripts"],
        "rollback_support": digest_payload["rollback_support"],
        "checksums": {
            "algorithm": "sha256",
            "manifest_excludes": sorted(EXCLUDED_CHECKSUM_FILES),
            "package_content_sha256": package_content_sha256,
            "files": files,
        },
    }


def write_adapter_package_manifest(
    package_root: str | Path,
    target: str,
    *,
    generated_at_utc: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Write the versioned package manifest into a package root."""

    root = Path(package_root).resolve()
    manifest = build_adapter_package_manifest(root, target, generated_at_utc=generated_at_utc)
    manifest_path = root / ADAPTER_PACKAGE_MANIFEST
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path, manifest


def verify_adapter_package(
    package_root: str | Path,
    target: str,
    *,
    manifest: Mapping[str, Any] | None = None,
    require_manifest_file: bool = True,
) -> dict[str, Any]:
    """Verify package metadata, lifecycle declarations, rollback support, and checksums."""

    key = _normalize_target(target)
    root = Path(package_root).resolve()
    issues: list[dict[str, Any]] = []
    manifest_path = root / ADAPTER_PACKAGE_MANIFEST
    loaded_manifest: dict[str, Any] | None = dict(manifest) if manifest is not None else None

    if require_manifest_file:
        if not manifest_path.is_file():
            issues.append(_issue("manifest", "PACKAGE_MANIFEST_MISSING", f"Package manifest missing: {manifest_path}", manifest_path))
        else:
            try:
                loaded_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                issues.append(_issue("manifest", "PACKAGE_MANIFEST_JSON_INVALID", f"Package manifest is invalid JSON: {exc}", manifest_path))
            except OSError as exc:
                issues.append(_issue("manifest", "PACKAGE_MANIFEST_UNREADABLE", f"Package manifest is unreadable: {exc}", manifest_path))

    if loaded_manifest is None:
        loaded_manifest = build_adapter_package_manifest(root, key)

    _verify_manifest_identity(root, key, loaded_manifest, issues)
    _verify_compatibility(key, loaded_manifest, issues)
    _verify_dependencies(key, loaded_manifest, issues)
    _verify_lifecycle(root, key, loaded_manifest, issues)
    _verify_rollback(loaded_manifest, issues)
    _verify_checksums(root, loaded_manifest, issues)

    ok = not issues
    return {
        "schema": ADAPTER_PACKAGE_VERIFICATION_SCHEMA,
        "ok": ok,
        "blocked": not ok,
        "target": key,
        "package_root": str(root),
        "manifest_path": str(manifest_path),
        "require_manifest_file": require_manifest_file,
        "version": str(loaded_manifest.get("version") or ""),
        "package_id": str(loaded_manifest.get("package_id") or ""),
        "package_content_sha256": str((loaded_manifest.get("checksums") or {}).get("package_content_sha256") or ""),
        "checks_passed": max(0, 6 - len({issue["category"] for issue in issues})),
        "checks_total": 6,
        "checked_categories": [
            "manifest",
            "compatibility_matrix",
            "dependencies",
            "lifecycle_scripts",
            "rollback_support",
            "checksums",
        ],
        "issues": issues,
        "required_files": list(TARGET_REQUIRED_FILES[key]),
        "generated_at_utc": _utc_now(),
    }


def write_adapter_package_verification_report(
    project_root: str | Path,
    target: str,
    report: Mapping[str, Any],
) -> Path:
    """Persist a package verification report under a project .xace folder."""

    project_dir = Path(project_root).resolve()
    digest = str(report.get("package_content_sha256") or "")
    stem = digest if re.fullmatch(r"[0-9a-f]{64}", digest) else "package-verification"
    path = project_dir / ".xace" / "adapter_package_versions" / _safe_segment(target) / f"{stem}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _verify_manifest_identity(root: Path, target: str, manifest: Mapping[str, Any], issues: list[dict[str, Any]]) -> None:
    metadata = TARGET_METADATA[target]
    expected = {
        "schema": ADAPTER_PACKAGE_MANIFEST_SCHEMA,
        "package_id": metadata["package_id"],
        "package_role": "adapter_package_handoff",
        "target": target,
        "version": PACKAGE_VERSION,
        "adapter_protocol_version": ADAPTER_PROTOCOL_VERSION,
        "shipping_boundary": "engine_project_owns_shipping_package",
    }
    for field, value in expected.items():
        if manifest.get(field) != value:
            issues.append(_issue("manifest", "PACKAGE_FIELD_MISMATCH", f"Expected {field}={value!r}.", root / ADAPTER_PACKAGE_MANIFEST, {"field": field, "actual": manifest.get(field)}))
    version = str(manifest.get("version") or "")
    if not SEMVER_RE.fullmatch(version):
        issues.append(_issue("manifest", "PACKAGE_VERSION_INVALID", "Package version must be semantic version text.", root / ADAPTER_PACKAGE_MANIFEST, {"version": version}))


def _verify_compatibility(target: str, manifest: Mapping[str, Any], issues: list[dict[str, Any]]) -> None:
    matrix = manifest.get("compatibility_matrix")
    if not isinstance(matrix, dict):
        issues.append(_issue("compatibility_matrix", "COMPATIBILITY_MATRIX_MISSING", "Compatibility matrix is missing or not an object."))
        return
    required_sections = {"engine", "xace_runtime", "adapter_protocol", "project_manifest", "cgs", "sgc_plan"}
    missing = sorted(required_sections.difference(matrix))
    if missing:
        issues.append(_issue("compatibility_matrix", "COMPATIBILITY_SECTIONS_MISSING", "Compatibility matrix is missing required sections.", evidence={"missing": missing}))
    engine = matrix.get("engine") or {}
    metadata = TARGET_METADATA[target]
    if engine.get("id") != metadata["engine_id"] or engine.get("version_range") != metadata["engine_version_range"]:
        issues.append(_issue("compatibility_matrix", "ENGINE_COMPATIBILITY_MISMATCH", "Engine compatibility does not match the target adapter.", evidence={"expected": metadata["engine_id"], "actual": engine}))
    protocol = matrix.get("adapter_protocol") or {}
    if protocol.get("version") != ADAPTER_PROTOCOL_VERSION:
        issues.append(_issue("compatibility_matrix", "PROTOCOL_COMPATIBILITY_MISMATCH", "Adapter protocol compatibility version is wrong.", evidence={"actual": protocol}))


def _verify_dependencies(target: str, manifest: Mapping[str, Any], issues: list[dict[str, Any]]) -> None:
    dependencies = manifest.get("dependencies")
    if not isinstance(dependencies, list) or not dependencies:
        issues.append(_issue("dependencies", "DEPENDENCIES_MISSING", "Dependency declarations are missing."))
        return
    ids = {str(item.get("id") or "") for item in dependencies if isinstance(item, dict)}
    required = {TARGET_METADATA[target]["engine_id"], "xace-runtime-core", "xace-project-system"}
    missing = sorted(required.difference(ids))
    if missing:
        issues.append(_issue("dependencies", "REQUIRED_DEPENDENCIES_MISSING", "Required dependencies are missing.", evidence={"missing": missing}))
    for item in dependencies:
        if not isinstance(item, dict) or not item.get("id") or not item.get("kind") or not item.get("required"):
            issues.append(_issue("dependencies", "DEPENDENCY_DECLARATION_INVALID", "Dependency declaration must include id, kind, and required=true.", evidence={"dependency": item}))


def _verify_lifecycle(root: Path, target: str, manifest: Mapping[str, Any], issues: list[dict[str, Any]]) -> None:
    scripts = manifest.get("lifecycle_scripts")
    if not isinstance(scripts, dict):
        issues.append(_issue("lifecycle_scripts", "LIFECYCLE_SCRIPTS_MISSING", "Lifecycle script declarations are missing."))
        return
    for command in ("install", "uninstall", "rollback"):
        declaration = scripts.get(command)
        if not isinstance(declaration, dict):
            issues.append(_issue("lifecycle_scripts", "LIFECYCLE_COMMAND_MISSING", f"Lifecycle command missing: {command}.", evidence={"command": command}))
            continue
        path = root / str(declaration.get("path") or "")
        if not path.is_file():
            issues.append(_issue("lifecycle_scripts", "LIFECYCLE_SCRIPT_FILE_MISSING", f"Lifecycle script file missing for {command}.", path))
        if declaration.get("transaction_schema") != ADAPTER_TRANSACTION_SCHEMA and command in {"install", "rollback"}:
            issues.append(_issue("lifecycle_scripts", "LIFECYCLE_TRANSACTION_SCHEMA_MISSING", f"{command} must declare the rollback transaction schema.", path))
        if declaration.get("target") != target:
            issues.append(_issue("lifecycle_scripts", "LIFECYCLE_TARGET_MISMATCH", f"{command} declaration targets the wrong adapter.", path, {"command": command, "actual": declaration.get("target")}))


def _verify_rollback(manifest: Mapping[str, Any], issues: list[dict[str, Any]]) -> None:
    rollback = manifest.get("rollback_support")
    if not isinstance(rollback, dict) or rollback.get("supported") is not True:
        issues.append(_issue("rollback_support", "ROLLBACK_SUPPORT_MISSING", "Rollback support must be explicitly enabled."))
        return
    expected = {
        "transaction_schema": ADAPTER_TRANSACTION_SCHEMA,
        "install_manifest_schema": ADAPTER_INSTALL_MANIFEST_SCHEMA,
        "backup_directory": ADAPTER_BACKUP_DIR,
    }
    for field, value in expected.items():
        if rollback.get(field) != value:
            issues.append(_issue("rollback_support", "ROLLBACK_FIELD_MISMATCH", f"Rollback field {field} must be {value!r}.", evidence={"field": field, "actual": rollback.get(field)}))


def _verify_checksums(root: Path, manifest: Mapping[str, Any], issues: list[dict[str, Any]]) -> None:
    checksums = manifest.get("checksums")
    if not isinstance(checksums, dict):
        issues.append(_issue("checksums", "CHECKSUM_BLOCK_MISSING", "Checksum block is missing."))
        return
    if checksums.get("algorithm") != "sha256":
        issues.append(_issue("checksums", "CHECKSUM_ALGORITHM_UNSUPPORTED", "Checksum algorithm must be sha256.", evidence={"actual": checksums.get("algorithm")}))
    files = checksums.get("files")
    if not isinstance(files, list) or not files:
        issues.append(_issue("checksums", "FILE_CHECKSUMS_MISSING", "File checksum list is missing."))
        return
    declared = {str(item.get("path") or ""): item for item in files if isinstance(item, dict)}
    actual_files = _collect_file_checksums(root)
    actual = {item["path"]: item for item in actual_files}
    missing = sorted(set(actual).difference(declared))
    stale = sorted(set(declared).difference(actual))
    if missing:
        issues.append(_issue("checksums", "FILE_CHECKSUMS_INCOMPLETE", "Package files are missing checksum records.", evidence={"missing": missing[:20]}))
    if stale:
        issues.append(_issue("checksums", "FILE_CHECKSUMS_STALE", "Checksum records reference files no longer in the package.", evidence={"stale": stale[:20]}))
    for rel, actual_record in actual.items():
        declared_record = declared.get(rel)
        if not declared_record:
            continue
        if declared_record.get("sha256") != actual_record["sha256"] or declared_record.get("size") != actual_record["size"]:
            issues.append(_issue("checksums", "FILE_CHECKSUM_MISMATCH", f"Checksum mismatch for {rel}.", root / rel, {"expected": declared_record, "actual": actual_record}))
    digest_payload = {
        "schema": ADAPTER_PACKAGE_MANIFEST_SCHEMA,
        "package_id": manifest.get("package_id"),
        "target": manifest.get("target"),
        "version": manifest.get("version"),
        "adapter_protocol_version": manifest.get("adapter_protocol_version"),
        "compatibility_matrix": manifest.get("compatibility_matrix"),
        "dependencies": manifest.get("dependencies"),
        "lifecycle_scripts": manifest.get("lifecycle_scripts"),
        "rollback_support": manifest.get("rollback_support"),
        "files": files,
    }
    expected_digest = _sha256_json(digest_payload)
    if checksums.get("package_content_sha256") != expected_digest:
        issues.append(_issue("checksums", "PACKAGE_CONTENT_DIGEST_MISMATCH", "Package content digest does not match manifest metadata and file checksums.", evidence={"expected": expected_digest, "actual": checksums.get("package_content_sha256")}))
    manifest_target = str(manifest.get("target") or "")
    for required in TARGET_REQUIRED_FILES.get(manifest_target, ()):
        if required not in declared:
            issues.append(_issue("checksums", "REQUIRED_FILE_NOT_CHECKSUMMED", f"Required package file lacks a checksum: {required}.", root / required))


def _compatibility_matrix(target: str) -> dict[str, Any]:
    metadata = TARGET_METADATA[target]
    return {
        "engine": {
            "id": metadata["engine_id"],
            "label": metadata["label"],
            "version_range": metadata["engine_version_range"],
            "install_destination": metadata["install_destination"],
        },
        "xace_runtime": {
            "crate": "xace-runtime-core",
            "version_range": f">={PACKAGE_VERSION} <1.0.0",
            "requires_authoritative_cgs": True,
        },
        "adapter_protocol": {
            "version": ADAPTER_PROTOCOL_VERSION,
            "wire_schema": "xace.engine_protocol.v1",
            "requires_handshake_ack": True,
        },
        "project_manifest": {
            "filename": "xace.project.json",
            "schema_version": PROJECT_SCHEMA_VERSION,
        },
        "cgs": {
            "format": "xace.cgs.export",
            "format_version_range": ">=1.0.0 <2.0.0",
            "requires_hash_match": True,
        },
        "sgc_plan": {
            "schema": "xace.sgc.execution_plan.v1",
            "requires_persisted_plan": True,
            "requires_runtime_compatibility_proof": True,
        },
    }


def _dependencies(target: str) -> list[dict[str, Any]]:
    metadata = TARGET_METADATA[target]
    return [
        {
            "id": metadata["engine_id"],
            "kind": "engine",
            "version_range": metadata["engine_version_range"],
            "required": True,
        },
        {
            "id": "xace-runtime-core",
            "kind": "runtime",
            "version_range": f">={PACKAGE_VERSION} <1.0.0",
            "required": True,
        },
        {
            "id": "xace-project-system",
            "kind": "tooling",
            "version_range": f">={PROJECT_SCHEMA_VERSION} <1.0.0",
            "required": True,
            "reason": "Lifecycle scripts call the reversible adapter_installation transaction layer.",
        },
    ]


def _lifecycle_scripts(target: str) -> dict[str, dict[str, Any]]:
    return {
        "install": {
            "path": ADAPTER_PACKAGE_LIFECYCLE_SCRIPT,
            "target": target,
            "command": ["python", ADAPTER_PACKAGE_LIFECYCLE_SCRIPT, "install", "--engine-project", "<engine_project_root>"],
            "transaction_schema": ADAPTER_TRANSACTION_SCHEMA,
            "install_manifest": ADAPTER_ENGINE_INSTALL_MANIFEST,
        },
        "uninstall": {
            "path": ADAPTER_PACKAGE_LIFECYCLE_SCRIPT,
            "target": target,
            "command": ["python", ADAPTER_PACKAGE_LIFECYCLE_SCRIPT, "uninstall", "--engine-project", "<engine_project_root>"],
            "report_schema": ADAPTER_UNINSTALL_REPORT_SCHEMA,
            "install_manifest": ADAPTER_ENGINE_INSTALL_MANIFEST,
        },
        "rollback": {
            "path": ADAPTER_PACKAGE_LIFECYCLE_SCRIPT,
            "target": target,
            "command": ["python", ADAPTER_PACKAGE_LIFECYCLE_SCRIPT, "rollback", "--engine-project", "<engine_project_root>"],
            "transaction_schema": ADAPTER_TRANSACTION_SCHEMA,
            "backup_directory": ADAPTER_BACKUP_DIR,
        },
    }


def _rollback_support() -> dict[str, Any]:
    return {
        "supported": True,
        "transaction_schema": ADAPTER_TRANSACTION_SCHEMA,
        "install_manifest_schema": ADAPTER_INSTALL_MANIFEST_SCHEMA,
        "install_manifest": ADAPTER_ENGINE_INSTALL_MANIFEST,
        "backup_directory": ADAPTER_BACKUP_DIR,
        "latest_transaction_pointer": f"{ADAPTER_BACKUP_DIR}/latest_transaction.json",
        "preserves_user_modified_files": True,
    }


def _collect_file_checksums(root: Path) -> list[dict[str, Any]]:
    if not root.exists() or not root.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().lower()):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if Path(rel).name in EXCLUDED_CHECKSUM_FILES:
            continue
        if any(part in SKIP_DIRS for part in Path(rel).parts):
            continue
        data = path.read_bytes()
        records.append({
            "path": rel,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    return records


def _normalize_target(target: str) -> str:
    key = str(target or "").strip().lower()
    if key not in SUPPORTED_TARGETS:
        raise ValueError(f"Unsupported adapter package target: {target!r}")
    return key


def _issue(
    category: str,
    code: str,
    message: str,
    path: str | Path | None = None,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "category": category,
        "code": code,
        "message": message,
        "path": str(path or ""),
        "severity": "error",
        "blocks_handoff": True,
        "evidence": dict(evidence or {}),
    }


def _sha256_json(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _safe_segment(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip())
    return cleaned.strip(".-") or "unknown"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
