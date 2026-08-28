#!/usr/bin/env python3
"""Retained X10-062 proof for versioned adapter packages."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_SYSTEM_DIR = REPO_ROOT / "packages" / "project-system"
if str(PROJECT_SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_SYSTEM_DIR))

from adapter_package_versioning import (  # noqa: E402
    ADAPTER_PACKAGE_LIFECYCLE_SCRIPT,
    ADAPTER_PACKAGE_MANIFEST,
    SUPPORTED_TARGETS,
    build_adapter_package_manifest,
    verify_adapter_package,
    write_adapter_package_manifest,
)


REPORT_SCHEMA = "xace.adapter_package_version_check_report.v1"
DEFAULT_OUTPUT = REPO_ROOT / "target-codex-task62-adapter-package-version" / "report.json"
DEFAULT_ARTIFACT_DIR = REPO_ROOT / "target-codex-task62-adapter-package-version" / "artifacts"
STATIC_TIME = "2026-08-23T00:00:00Z"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run X10-062 adapter package version verification.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--artifact-dir", default=str(DEFAULT_ARTIFACT_DIR))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run_check(output_path=Path(args.output).resolve(), artifact_dir=Path(args.artifact_dir).resolve())
    except Exception as exc:  # noqa: BLE001
        print(f"adapter package version check failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"adapter package version check PASSED ({report['checks_passed']}/{report['checks_total']} checks)")
    return 0


def run_check(*, output_path: Path, artifact_dir: Path) -> dict[str, Any]:
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    package_results = []
    checks = []
    for target in SUPPORTED_TARGETS:
        result = _verify_target_package(target, artifact_dir)
        package_results.append(result)
        checks.extend([
            {
                "name": f"{target}_source_virtual_manifest",
                "ok": bool(result["source_verification"]["ok"]),
                "detail": f"source package can build a valid {target} manifest without mutating source",
            },
            {
                "name": f"{target}_staged_manifest",
                "ok": bool(result["staged_verification"]["ok"]) and Path(result["manifest_path"]).is_file(),
                "detail": f"staged package includes {ADAPTER_PACKAGE_MANIFEST}",
            },
            {
                "name": f"{target}_lifecycle_script_describe",
                "ok": bool(result["lifecycle_describe"]["ok"]),
                "detail": "lifecycle script reports install/uninstall/rollback commands",
            },
            {
                "name": f"{target}_checksum_tamper_blocked",
                "ok": bool(result["tamper_verification"]["blocked"]),
                "detail": "post-manifest file mutation is rejected by checksum verification",
            },
        ])

    endpoint_result = _run_builder_handoff_version_proof(artifact_dir)
    checks.append({
        "name": "builder_endpoint_writes_versioned_packages",
        "ok": bool(endpoint_result.get("ok")),
        "detail": "Builder handoff writes a package version manifest and verification report for every adapter target",
    })

    acceptance = {
        "version": all(item["staged_manifest"].get("version") for item in package_results),
        "compatibility_matrix": all(bool(item["staged_manifest"].get("compatibility_matrix")) for item in package_results),
        "dependency_declarations": all(bool(item["staged_manifest"].get("dependencies")) for item in package_results),
        "install_uninstall_scripts": all(bool(item["lifecycle_describe"].get("has_install_uninstall")) for item in package_results),
        "rollback_support": all(bool(item["staged_manifest"].get("rollback_support", {}).get("supported")) for item in package_results),
        "checksums": all(bool(item["staged_manifest"].get("checksums", {}).get("package_content_sha256")) for item in package_results),
    }
    checks.append({
        "name": "acceptance_fields_present_for_all_targets",
        "ok": all(acceptance.values()),
        "detail": f"acceptance={acceptance}",
    })

    report = {
        "schema": REPORT_SCHEMA,
        "task": "X10-062",
        "generated_at_utc": _utc_now(),
        "ok": all(check["ok"] for check in checks),
        "x10_062_complete": all(check["ok"] for check in checks),
        "checks_passed": sum(1 for check in checks if check["ok"]),
        "checks_total": len(checks),
        "targets": list(SUPPORTED_TARGETS),
        "acceptance": acceptance,
        "packages": package_results,
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


def _verify_target_package(target: str, artifact_dir: Path) -> dict[str, Any]:
    source = REPO_ROOT / "adapters" / target
    source_manifest = build_adapter_package_manifest(source, target, generated_at_utc=STATIC_TIME)
    source_verification = verify_adapter_package(
        source,
        target,
        manifest=source_manifest,
        require_manifest_file=False,
    )

    staged_root = artifact_dir / "staged_packages" / target
    shutil.copytree(source, staged_root)
    manifest_path, staged_manifest = write_adapter_package_manifest(staged_root, target, generated_at_utc=STATIC_TIME)
    staged_verification = verify_adapter_package(staged_root, target)
    lifecycle_describe = _run_lifecycle_describe(staged_root)

    tamper_root = artifact_dir / "tampered_packages" / target
    shutil.copytree(source, tamper_root)
    write_adapter_package_manifest(tamper_root, target, generated_at_utc=STATIC_TIME)
    tampered_file = _tamper_first_package_file(tamper_root, staged_manifest)
    tamper_verification = verify_adapter_package(tamper_root, target)
    tamper_verification["tampered_file"] = str(tampered_file)

    return {
        "target": target,
        "source_root": str(source),
        "staged_root": str(staged_root),
        "manifest_path": str(manifest_path),
        "source_verification": _compact_verification(source_verification),
        "staged_verification": _compact_verification(staged_verification),
        "lifecycle_describe": lifecycle_describe,
        "tamper_verification": _compact_verification(tamper_verification),
        "staged_manifest": {
            "schema": staged_manifest.get("schema"),
            "package_id": staged_manifest.get("package_id"),
            "version": staged_manifest.get("version"),
            "adapter_protocol_version": staged_manifest.get("adapter_protocol_version"),
            "compatibility_matrix": staged_manifest.get("compatibility_matrix"),
            "dependencies": staged_manifest.get("dependencies"),
            "lifecycle_scripts": staged_manifest.get("lifecycle_scripts"),
            "rollback_support": staged_manifest.get("rollback_support"),
            "checksums": {
                "algorithm": staged_manifest.get("checksums", {}).get("algorithm"),
                "package_content_sha256": staged_manifest.get("checksums", {}).get("package_content_sha256"),
                "file_count": len(staged_manifest.get("checksums", {}).get("files", [])),
            },
        },
    }


def _run_builder_handoff_version_proof(artifact_dir: Path) -> dict[str, Any]:
    try:
        from fastapi.testclient import TestClient  # noqa: PLC0415
        from adapter_package_handoff_preflight_check import _write_project  # noqa: PLC0415
        from builder_server import create_app  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"Builder TestClient unavailable: {exc}"}

    project = artifact_dir / "builder_handoff_project"
    _write_project(project)
    app = create_app(project_path=str(project), static_dir=str(artifact_dir / "no_dist"), dev_mode=False)
    client = TestClient(app)
    results = []
    for target in SUPPORTED_TARGETS:
        response = client.post(f"/api/adapter-package/handoff/{target}")
        try:
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            payload = {"ok": False, "error": f"Non-JSON response: {exc}"}
        handoff_root = project / ".xace" / "adapter_package_handoffs" / target
        manifest_path = handoff_root / ADAPTER_PACKAGE_MANIFEST
        version_report = verify_adapter_package(handoff_root, target) if handoff_root.exists() else {"ok": False, "issues": []}
        result_ok = (
            response.status_code == 200
            and payload.get("ok") is True
            and manifest_path.is_file()
            and version_report.get("ok") is True
            and payload.get("manifest", {}).get("adapter_package_version") == "0.1.0"
            and payload.get("package_version_report", {}).get("ok") is True
        )
        results.append({
            "target": target,
            "ok": result_ok,
            "status_code": response.status_code,
            "handoff_root": str(handoff_root),
            "manifest_path": str(manifest_path),
            "package_version_report_path": payload.get("package_version_report_path", ""),
            "payload_ok": payload.get("ok"),
            "verification": _compact_verification(version_report),
        })
    return {
        "ok": all(item["ok"] for item in results),
        "targets": results,
    }


def _run_lifecycle_describe(package_root: Path) -> dict[str, Any]:
    script = package_root / ADAPTER_PACKAGE_LIFECYCLE_SCRIPT
    proc = subprocess.run(
        [sys.executable, str(script), "describe", "--package-root", str(package_root), "--json"],
        cwd=str(package_root),
        text=True,
        capture_output=True,
        timeout=30,
    )
    payload: dict[str, Any] = {}
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        payload = {"ok": False, "error": "describe output was not JSON"}
    commands = set(payload.get("commands", []) or [])
    return {
        "ok": proc.returncode == 0 and payload.get("ok") is True and {"install", "uninstall", "rollback"}.issubset(commands),
        "returncode": proc.returncode,
        "target": payload.get("target"),
        "commands": sorted(commands),
        "has_install_uninstall": {"install", "uninstall"}.issubset(commands),
        "has_rollback": "rollback" in commands,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def _tamper_first_package_file(package_root: Path, manifest: dict[str, Any]) -> Path:
    files = manifest.get("checksums", {}).get("files", []) or []
    if not files:
        raise RuntimeError(f"No checksummed files found for tamper test: {package_root}")
    rel = str(files[0]["path"])
    path = package_root / rel
    path.write_bytes(path.read_bytes() + b"\n# x10-062 checksum tamper\n")
    return path


def _compact_verification(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": bool(report.get("ok")),
        "blocked": bool(report.get("blocked")),
        "version": report.get("version"),
        "package_id": report.get("package_id"),
        "package_content_sha256": report.get("package_content_sha256"),
        "checks_passed": report.get("checks_passed"),
        "checks_total": report.get("checks_total"),
        "issue_codes": [issue.get("code") for issue in report.get("issues", [])],
        "issues": report.get("issues", [])[:8],
        "tampered_file": report.get("tampered_file", ""),
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
