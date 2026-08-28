#!/usr/bin/env python3
"""Export a redacted local support diagnostics bundle.

The command is intentionally local-only. It gathers inspectable diagnostics into
a folder and optional zip file, redacts known credential shapes, and writes a
manifest that records versions, manifests, logs, proof links, config, adapter
health, provider readiness, and reproduction commands.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = REPO_ROOT / "packages" / "builder-workspace" / "server"
PROJECT_SYSTEM_DIR = REPO_ROOT / "packages" / "project-system"

for import_path in (SERVER_DIR, PROJECT_SYSTEM_DIR, REPO_ROOT / "tools"):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from project_manifest import MANIFEST_FILENAME, load_manifest  # noqa: E402
from provider_settings import DEFAULT_SETTINGS_PATH, SETTINGS_PATH_ENV, ProviderSettingsStore  # noqa: E402
from secret_redaction import REDACTED_SECRET, redact_text, redact_value  # noqa: E402
from security_secret_scan import scan_paths  # noqa: E402


SCHEMA = "xace.support_diagnostics_bundle.v1"
EXPORT_TARGETS = {
    "unity": {"source": "adapters/unity", "label": "Unity C#"},
    "unreal": {"source": "adapters/unreal", "label": "Unreal C++"},
    "godot": {"source": "adapters/godot", "label": "Godot GDScript"},
}
TEXT_SUFFIXES = {
    ".cfg",
    ".cmd",
    ".gd",
    ".ini",
    ".json",
    ".jsonl",
    ".log",
    ".md",
    ".plan",
    ".py",
    ".rs",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
MAX_LOG_FILES = 24
MAX_LOG_BYTES = 256 * 1024
MAX_PROOF_LINKS = 96
REDACTION_CANARY = "sk-xace-support-bundle-canary-123456"


def create_support_bundle(
    *,
    project: Path | None,
    output_root: Path,
    bundle_id: str,
    provider_settings_path: Path | None,
    include_logs: bool,
    make_zip: bool,
    overwrite: bool,
) -> dict[str, Any]:
    output_root = output_root.resolve()
    bundle_dir = output_root / bundle_id
    if bundle_dir.exists():
        if not overwrite:
            raise RuntimeError(f"Bundle already exists: {bundle_dir}. Pass --overwrite to replace it.")
        _safe_remove_bundle(bundle_dir, output_root)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    files: list[dict[str, Any]] = []
    project_context = _project_context(project)
    provider_context = _provider_readiness(provider_settings_path)
    adapter_context = _adapter_health(project_context)

    versions = _versions()
    _write_json(bundle_dir / "versions.json", versions, files, role="versions")

    support_config = {
        "schema": "xace.support_diagnostics_bundle.request.v1",
        "project": str(project.resolve()) if project else "",
        "output_root": str(output_root),
        "bundle_id": bundle_id,
        "include_logs": include_logs,
        "zip": make_zip,
        "privacy": "local_only_redacted_no_upload",
    }
    _write_json(bundle_dir / "config" / "support_bundle_request.json", support_config, files, role="config")
    _write_json(bundle_dir / "health" / "adapter_health.json", adapter_context, files, role="adapter_health")
    _write_json(bundle_dir / "health" / "provider_readiness.json", provider_context["readiness"], files, role="provider_readiness")

    if provider_context.get("settings_payload") is not None:
        _write_json(
            bundle_dir / "config" / "provider_settings.redacted.json",
            provider_context["settings_payload"],
            files,
            role="config",
            source=str(provider_context.get("settings_path") or ""),
        )

    _collect_manifest_files(bundle_dir, files, project_context)
    log_index = _collect_logs(bundle_dir, files, project_context, include_logs=include_logs)
    _write_json(bundle_dir / "logs" / "logs_index.json", log_index, files, role="logs_index")

    proof_links = _proof_links(project_context)
    _write_json(bundle_dir / "proof_links" / "proof_links.json", proof_links, files, role="proof_links")

    reproduction = _reproduction_commands(project_context, output_root=output_root, bundle_id=bundle_id)
    _write_json(bundle_dir / "reproduction_commands.json", reproduction, files, role="reproduction_commands")

    redaction = _redaction_report(bundle_dir)
    manifest = {
        "schema": SCHEMA,
        "bundle_id": bundle_id,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "privacy": {
            "local_only": True,
            "uploaded": False,
            "redacted": True,
            "redaction_marker": REDACTED_SECRET,
        },
        "project": project_context["summary"],
        "sections": {
            "versions": True,
            "manifests": bool(project_context.get("manifest_path") or (REPO_ROOT / "Cargo.toml").exists()),
            "logs": include_logs,
            "proof_links": True,
            "config": True,
            "adapter_health": True,
            "provider_readiness": True,
            "reproduction_commands": True,
        },
        "adapter_health": adapter_context,
        "provider_readiness": provider_context["summary"],
        "redaction": redaction,
        "files": files,
    }
    _write_json(bundle_dir / "manifest.json", manifest, files, role="bundle_manifest")
    redaction = _redaction_report(bundle_dir)
    manifest["redaction"] = redaction
    _write_json(bundle_dir / "manifest.json", manifest, files, role="bundle_manifest", replace_existing=True)

    zip_path = None
    if make_zip:
        zip_path = output_root / f"{bundle_id}.zip"
        if zip_path.exists():
            if not overwrite:
                raise RuntimeError(f"Bundle zip already exists: {zip_path}. Pass --overwrite to replace it.")
            zip_path.unlink()
        _zip_bundle(bundle_dir, zip_path)

    return {
        "ok": bool(redaction.get("ok")),
        "schema": SCHEMA,
        "bundle_id": bundle_id,
        "bundle_dir": str(bundle_dir),
        "bundle_zip": str(zip_path) if zip_path else "",
        "manifest_path": str(bundle_dir / "manifest.json"),
        "file_count": len(files),
        "sections": manifest["sections"],
        "redaction": redaction,
    }


def _safe_remove_bundle(bundle_dir: Path, output_root: Path) -> None:
    resolved_bundle = bundle_dir.resolve()
    resolved_root = output_root.resolve()
    if resolved_bundle == resolved_root or resolved_root not in resolved_bundle.parents:
        raise RuntimeError(f"Refusing to remove bundle outside output root: {resolved_bundle}")
    shutil.rmtree(resolved_bundle)


def _project_context(project: Path | None) -> dict[str, Any]:
    if not project:
        return {
            "project_dir": None,
            "manifest_path": None,
            "manifest": None,
            "cgs_path": None,
            "summary": {"available": False, "reason": "No --project path supplied."},
        }
    project_dir = project.resolve()
    manifest_path = project_dir / MANIFEST_FILENAME
    manifest_payload: dict[str, Any] | None = None
    cgs_path: Path | None = None
    errors: list[str] = []
    try:
        manifest = load_manifest(project_dir)
        manifest_payload = manifest.to_dict()
        cgs_path = (project_dir / manifest.cgs_path).resolve()
    except Exception as exc:
        errors.append(redact_text(exc))
        if manifest_path.exists():
            try:
                loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    manifest_payload = loaded
                    cgs_path = (project_dir / str(loaded.get("cgs_path") or "game.cgs.json")).resolve()
            except Exception as manifest_exc:
                errors.append(redact_text(manifest_exc))
        if cgs_path is None:
            cgs_path = (project_dir / "game.cgs.json").resolve()

    engine_type = str((manifest_payload or {}).get("engine_type") or "")
    cgs_hash = _json_file_hash(cgs_path) if cgs_path and cgs_path.exists() else ""
    return {
        "project_dir": project_dir,
        "manifest_path": manifest_path if manifest_path.exists() else None,
        "manifest": manifest_payload,
        "cgs_path": cgs_path if cgs_path and cgs_path.exists() else None,
        "summary": {
            "available": project_dir.exists(),
            "project_dir": str(project_dir),
            "manifest_available": manifest_path.exists(),
            "engine_type": engine_type,
            "cgs_path": str(cgs_path) if cgs_path else "",
            "cgs_sha256": cgs_hash,
            "errors": errors,
        },
    }


def _provider_readiness(provider_settings_path: Path | None) -> dict[str, Any]:
    previous = os.environ.get(SETTINGS_PATH_ENV)
    if provider_settings_path:
        os.environ[SETTINGS_PATH_ENV] = str(provider_settings_path.resolve())
    settings_payload: Any = None
    settings_path = provider_settings_path.resolve() if provider_settings_path else DEFAULT_SETTINGS_PATH
    try:
        if settings_path.exists():
            settings_payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception as exc:
        settings_payload = {"load_error": redact_text(exc)}
    try:
        store = ProviderSettingsStore(settings_path if provider_settings_path else None)
        readiness = redact_value(store.active_readiness(refresh_models=False))
        active_provider = str(readiness.get("provider") or "")
        summary = {
            "available": True,
            "ok": bool(readiness.get("ok")),
            "provider": active_provider,
            "model": str(readiness.get("model") or ""),
            "code": str(readiness.get("code") or ""),
            "proof_status": str(readiness.get("proof_status") or ""),
            "settings_path": str(store.path),
            "settings_present": store.path.exists(),
        }
    except Exception as exc:
        readiness = {
            "ok": False,
            "code": "PROVIDER_READINESS_UNAVAILABLE",
            "message": redact_text(exc),
        }
        summary = {
            "available": False,
            "ok": False,
            "code": "PROVIDER_READINESS_UNAVAILABLE",
            "settings_path": str(settings_path),
            "settings_present": settings_path.exists(),
        }
    finally:
        if provider_settings_path:
            if previous is None:
                os.environ.pop(SETTINGS_PATH_ENV, None)
            else:
                os.environ[SETTINGS_PATH_ENV] = previous
    return {
        "readiness": readiness,
        "summary": summary,
        "settings_path": str(settings_path),
        "settings_payload": settings_payload,
    }


def _adapter_health(project_context: dict[str, Any]) -> dict[str, Any]:
    project_dir = project_context.get("project_dir")
    manifest = project_context.get("manifest") if isinstance(project_context.get("manifest"), dict) else {}
    engine_type = str(manifest.get("engine_type") or project_context.get("summary", {}).get("engine_type") or "").lower()
    if not project_dir:
        return {
            "ok": False,
            "healthy": False,
            "installed": False,
            "target": "",
            "reason": "No project supplied.",
        }
    if engine_type == "headless":
        return {
            "ok": True,
            "healthy": True,
            "installed": False,
            "target": "headless",
            "skipped": True,
            "reason": "Headless projects do not need an engine adapter.",
        }
    if engine_type not in EXPORT_TARGETS:
        return {
            "ok": False,
            "healthy": False,
            "installed": False,
            "target": engine_type,
            "error": f"Unknown adapter target: {engine_type}",
            "targets": sorted(EXPORT_TARGETS),
        }
    source_dir = REPO_ROOT / EXPORT_TARGETS[engine_type]["source"]
    adapter_root = Path(project_dir) / ".xace" / "adapter" / engine_type
    source_files = [
        str(path.relative_to(source_dir)).replace("\\", "/")
        for path in sorted(source_dir.rglob("*"))
        if path.is_file()
    ] if source_dir.exists() else []
    expected_files = source_files + ["xace_adapter_manifest.json"]
    installed_files = [
        str(path.relative_to(adapter_root)).replace("\\", "/")
        for path in sorted(adapter_root.rglob("*"))
        if path.is_file()
    ] if adapter_root.exists() else []
    missing_files = [
        relative
        for relative in expected_files
        if not (adapter_root / relative).exists()
    ]
    return {
        "ok": source_dir.exists(),
        "target": engine_type,
        "label": EXPORT_TARGETS[engine_type]["label"],
        "healthy": adapter_root.exists() and not missing_files,
        "installed": adapter_root.exists(),
        "path": str(adapter_root),
        "file_count": len(installed_files),
        "expected_count": len(expected_files),
        "missing_files": missing_files[:64],
    }


def _versions() -> dict[str, Any]:
    git_status = _capture(["git", "status", "--short"], REPO_ROOT)
    status_lines = [line for line in git_status.get("stdout", "").splitlines() if line.strip()]
    return {
        "schema": "xace.support_diagnostics.versions.v1",
        "captured_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "python": sys.version.split()[0],
        },
        "commands": {
            "python": _capture([sys.executable, "--version"], REPO_ROOT),
            "node": _capture(["node", "--version"], REPO_ROOT),
            "npm": _capture(["npm", "--version"], REPO_ROOT),
            "cargo": _capture(["cargo", "--version"], REPO_ROOT),
            "rustc": _capture(["rustc", "--version"], REPO_ROOT),
            "git_head": _capture(["git", "rev-parse", "HEAD"], REPO_ROOT),
        },
        "worktree": {
            "dirty": bool(status_lines),
            "changed_count": len(status_lines),
            "changed_paths_sample": status_lines[:80],
        },
    }


def _collect_manifest_files(bundle_dir: Path, files: list[dict[str, Any]], project_context: dict[str, Any]) -> None:
    for source in [
        REPO_ROOT / "Cargo.toml",
        REPO_ROOT / "Cargo.lock",
        REPO_ROOT / "package.json",
        REPO_ROOT / "package-lock.json",
        REPO_ROOT / "pyproject.toml",
        REPO_ROOT / "requirements.txt",
    ]:
        if source.exists():
            _copy_redacted_text(source, bundle_dir / "manifests" / "repo" / source.name, files, role="repo_manifest")
    manifest_path = project_context.get("manifest_path")
    if isinstance(manifest_path, Path) and manifest_path.exists():
        _copy_redacted_text(manifest_path, bundle_dir / "manifests" / "project" / manifest_path.name, files, role="project_manifest")
    cgs_path = project_context.get("cgs_path")
    if isinstance(cgs_path, Path) and cgs_path.exists():
        _copy_redacted_text(cgs_path, bundle_dir / "manifests" / "project" / cgs_path.name, files, role="project_cgs")


def _collect_logs(
    bundle_dir: Path,
    files: list[dict[str, Any]],
    project_context: dict[str, Any],
    *,
    include_logs: bool,
) -> dict[str, Any]:
    if not include_logs:
        return {"included": False, "files": []}
    project_dir = project_context.get("project_dir")
    log_roots: list[Path] = []
    if isinstance(project_dir, Path):
        log_roots.extend([project_dir / ".xace" / "logs", project_dir / "logs"])
    copied: list[dict[str, Any]] = []
    for root in log_roots:
        if not root.exists():
            continue
        for source in _iter_text_files(root):
            if len(copied) >= MAX_LOG_FILES:
                break
            relative = source.relative_to(root)
            target = bundle_dir / "logs" / root.name / relative
            record = _copy_redacted_text(source, target, files, role="log", max_bytes=MAX_LOG_BYTES)
            copied.append(record)
    return {
        "included": True,
        "root_count": len([root for root in log_roots if root.exists()]),
        "files": copied,
        "limit": {"max_files": MAX_LOG_FILES, "max_bytes_per_file": MAX_LOG_BYTES},
    }


def _proof_links(project_context: dict[str, Any]) -> dict[str, Any]:
    links: list[dict[str, Any]] = []
    project_dir = project_context.get("project_dir")
    if isinstance(project_dir, Path):
        for root in [project_dir / ".xace" / "proof", project_dir / ".xace" / "execution_plans", project_dir / ".xace" / "audit"]:
            links.extend(_proof_file_links(root, base=project_dir, source="project"))
    for report_path in sorted(REPO_ROOT.glob("target-codex-task*/report.json"))[:MAX_PROOF_LINKS]:
        links.append(_proof_link(report_path, base=REPO_ROOT, source="repo_target_report"))
    return {
        "schema": "xace.support_diagnostics.proof_links.v1",
        "links": links[:MAX_PROOF_LINKS],
        "link_count": min(len(links), MAX_PROOF_LINKS),
        "truncated": len(links) > MAX_PROOF_LINKS,
    }


def _proof_file_links(root: Path, *, base: Path, source: str) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    if root.is_file():
        return [_proof_link(root, base=base, source=source)]
    links: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and _looks_text(path):
            links.append(_proof_link(path, base=base, source=source))
    return links


def _proof_link(path: Path, *, base: Path, source: str) -> dict[str, Any]:
    return {
        "source": source,
        "path": _relative_or_absolute(path, base),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def _reproduction_commands(project_context: dict[str, Any], *, output_root: Path, bundle_id: str) -> dict[str, Any]:
    project_dir = project_context.get("project_dir")
    cgs_path = project_context.get("cgs_path")
    commands: list[dict[str, Any]] = [
        {
            "id": "support_bundle",
            "label": "Recreate redacted support bundle",
            "cwd": str(REPO_ROOT),
            "command": [
                sys.executable,
                "tools/support_diagnostics_bundle.py",
                "--output-dir",
                str(output_root),
                "--bundle-id",
                bundle_id,
                "--overwrite",
            ] + (["--project", str(project_dir)] if isinstance(project_dir, Path) else []),
        },
        {
            "id": "quick_certification",
            "label": "Run editor-free quick launch certification",
            "cwd": str(REPO_ROOT),
            "command": [sys.executable, "tools/certify_launch.py", "--quick"],
        },
    ]
    if isinstance(project_dir, Path):
        commands.append({
            "id": "builder_dry_run",
            "label": "Print Builder launch plan without starting processes",
            "cwd": str(REPO_ROOT),
            "command": [
                sys.executable,
                "tools/xace_builder_launch.py",
                "--project",
                str(project_dir),
                "--dry-run",
                "--no-open-browser",
                "--no-runtime",
            ],
        })
    if isinstance(cgs_path, Path):
        commands.append({
            "id": "runtime_replay_10_ticks",
            "label": "Run deterministic runtime for 10 ticks against captured CGS",
            "cwd": str(REPO_ROOT),
            "command": [
                "cargo",
                "run",
                "-p",
                "xace-runtime-core",
                "--bin",
                "xace_runtime",
                "--",
                "--cgs",
                str(cgs_path),
                "--derive-cgs-plan",
                "--ticks",
                "10",
                "--no-control",
                "--no-wait",
            ],
        })
    return {
        "schema": "xace.support_diagnostics.reproduction_commands.v1",
        "commands": commands,
    }


def _redaction_report(bundle_dir: Path) -> dict[str, Any]:
    sample = {
        "api_key": REDACTION_CANARY,
        "authorization": "Bearer xaceSupportBundleBearer123456",
        "nested": ["AIza" + "x" * 24],
    }
    rendered = json.dumps(redact_value(sample), sort_keys=True)
    canary_ok = REDACTION_CANARY not in rendered and REDACTED_SECRET in rendered
    findings = scan_paths([bundle_dir], repo_root=REPO_ROOT)
    return {
        "schema": "xace.support_diagnostics.redaction_report.v1",
        "ok": canary_ok and not findings,
        "canary_ok": canary_ok,
        "secret_shape_count": len(findings),
        "secret_shape_findings": [
            {
                "path": finding.path,
                "line": finding.line,
                "column": finding.column,
                "kind": finding.kind,
                "preview": finding.preview,
            }
            for finding in findings[:20]
        ],
    }


def _write_json(
    path: Path,
    payload: Any,
    files: list[dict[str, Any]],
    *,
    role: str,
    source: str = "",
    replace_existing: bool = False,
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(redact_value(payload), indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    record = _file_record(path, role=role, source=source)
    if replace_existing:
        files[:] = [item for item in files if item.get("bundle_path") != record["bundle_path"]]
    files.append(record)
    return record


def _copy_redacted_text(
    source: Path,
    target: Path,
    files: list[dict[str, Any]],
    *,
    role: str,
    max_bytes: int | None = None,
) -> dict[str, Any]:
    target.parent.mkdir(parents=True, exist_ok=True)
    data = source.read_bytes()
    truncated = False
    if max_bytes is not None and len(data) > max_bytes:
        data = data[-max_bytes:]
        truncated = True
    text = data.decode("utf-8", errors="replace")
    target.write_text(redact_text(text), encoding="utf-8")
    record = _file_record(target, role=role, source=str(source))
    record["truncated"] = truncated
    files.append(record)
    return record


def _file_record(path: Path, *, role: str, source: str = "") -> dict[str, Any]:
    return {
        "role": role,
        "source": source,
        "bundle_path": _relative_or_absolute(path, path.parents[1] if len(path.parents) > 1 else path.parent),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def _zip_bundle(bundle_dir: Path, zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(bundle_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(bundle_dir.parent).as_posix())


def _capture(command: list[str], cwd: Path) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=8,
            check=False,
        )
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": redact_text(completed.stdout.strip())[:8000],
            "stderr": redact_text(completed.stderr.strip())[:4000],
        }
    except Exception as exc:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": redact_text(exc),
        }


def _iter_text_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file() and _looks_text(path):
            yield path


def _looks_text(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in {"Cargo.lock", "package-lock.json"}


def _json_file_hash(path: Path) -> str:
    return _sha256(path) if path.exists() else ""


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_or_absolute(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve())).replace("\\", "/")
    except Exception:
        return str(path.resolve())


def _default_bundle_id() -> str:
    return f"xace-support-{int(time.time())}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a redacted XACE support diagnostics bundle.")
    parser.add_argument("--project", default="", help="XACE project folder to include.")
    parser.add_argument("--output-dir", default="target-codex-support-bundles", help="Directory where the bundle folder/zip is written.")
    parser.add_argument("--bundle-id", default="", help="Stable bundle folder name. Defaults to a timestamped id.")
    parser.add_argument("--provider-settings", default="", help="Provider settings JSON to summarize. Defaults to normal local settings.")
    parser.add_argument("--no-logs", action="store_true", help="Do not include redacted project logs.")
    parser.add_argument("--no-zip", action="store_true", help="Do not create a zip next to the bundle folder.")
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing bundle with the same id under --output-dir.")
    parser.add_argument("--json", action="store_true", help="Print JSON only.")
    args = parser.parse_args(argv)

    project = Path(args.project).resolve() if args.project else None
    provider_settings = Path(args.provider_settings).resolve() if args.provider_settings else None
    result = create_support_bundle(
        project=project,
        output_root=Path(args.output_dir),
        bundle_id=args.bundle_id.strip() or _default_bundle_id(),
        provider_settings_path=provider_settings,
        include_logs=not args.no_logs,
        make_zip=not args.no_zip,
        overwrite=args.overwrite,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    if not args.json:
        status = "PASSED" if result["ok"] else "FAILED"
        print(f"support diagnostics bundle {status}: {result['bundle_dir']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

