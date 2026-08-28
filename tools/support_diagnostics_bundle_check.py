#!/usr/bin/env python3
"""Retained X10-051 proof for redacted support diagnostics bundles."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROJECT_SYSTEM_DIR = ROOT / "packages" / "project-system"
SERVER_DIR = ROOT / "packages" / "builder-workspace" / "server"

for import_path in (PROJECT_SYSTEM_DIR, SERVER_DIR, ROOT / "tools"):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from credential_store import BACKEND_ENV, UNSAFE_FALLBACK_ENV, UNSAFE_STORE_PATH_ENV  # noqa: E402
from project_creator import CreateProjectRequest, ProjectCreator  # noqa: E402
from security_secret_scan import scan_paths  # noqa: E402


REPORT_SCHEMA = "xace.support_diagnostics_bundle_check_report.v1"
BUNDLE_ID = "x10-051-support-bundle"
FAKE_KEY = "sk-xace-support-bundle-secret-123456"
FAKE_BEARER = "Bearer xaceSupportBundleBearer123456"
FAKE_GOOGLE = "AIza" + "x" * 24


def run(command: list[str], cwd: Path, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def build_fixture(root: Path) -> tuple[Path, Path]:
    if root.exists():
        _safe_rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    project_dir = root / "support-fixture-project"
    ProjectCreator().create_project(CreateProjectRequest(
        project_dir=str(project_dir),
        name="Support Bundle Fixture",
        engine_type="godot",
        template_id="blank_3d",
        force=True,
    ))

    log_dir = project_dir / ".xace" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "builder.log").write_text(
        "\n".join([
            "INFO support bundle fixture started",
            f"provider api key leaked in source log: {FAKE_KEY}",
            f"authorization header: {FAKE_BEARER}",
            f"google key shape: {FAKE_GOOGLE}",
        ]) + "\n",
        encoding="utf-8",
    )

    cgs_hash = "a" * 64
    proof_dir = project_dir / ".xace" / "proof" / "sgc" / cgs_hash
    proof_dir.mkdir(parents=True, exist_ok=True)
    (proof_dir / "validation.json").write_text(json.dumps({
        "schema": "xace.sgc.proof_bundle.v1",
        "ok": True,
        "compiled_from_cgs_hash": cgs_hash,
    }, indent=2) + "\n", encoding="utf-8")

    plan_dir = project_dir / ".xace" / "execution_plans"
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / f"{cgs_hash}.plan.json").write_text(json.dumps({
        "schema": "xace.sgc.execution_plan.v1",
        "cgs_hash": cgs_hash,
        "proof_bundle": {"path": f".xace/proof/sgc/{cgs_hash}"},
    }, indent=2) + "\n", encoding="utf-8")

    provider_settings = root / "provider_settings.json"
    provider_settings.write_text(json.dumps({
        "version": 1,
        "active_provider": "openai",
        "providers": {
            "openai": {
                "model": "xace-support-model",
                "base_url": "https://api.openai.com/v1",
                "api_key": FAKE_KEY,
                "last_test": {
                    "message": f"provider health log mentioned {FAKE_BEARER}",
                    "ok": False,
                },
            },
        },
    }, indent=2) + "\n", encoding="utf-8")

    return project_dir, provider_settings


def run_bundle_command(project_dir: Path, provider_settings: Path, bundle_root: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env[BACKEND_ENV] = "unsafe-file"
    env[UNSAFE_FALLBACK_ENV] = "1"
    env[UNSAFE_STORE_PATH_ENV] = str(bundle_root / "fixture_unsafe_credentials.json")
    command = [
        sys.executable,
        "tools/support_diagnostics_bundle.py",
        "--project",
        str(project_dir),
        "--provider-settings",
        str(provider_settings),
        "--output-dir",
        str(bundle_root),
        "--bundle-id",
        BUNDLE_ID,
        "--overwrite",
        "--json",
    ]
    completed = run(command, ROOT, env=env)
    payload: dict[str, Any] = {}
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {}
    return {
        "name": "support_bundle_command",
        "ok": completed.returncode == 0 and bool(payload.get("ok")),
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "command": command,
        "payload": payload,
    }


def validate_bundle(bundle_root: Path, command_check: dict[str, Any]) -> dict[str, Any]:
    payload = command_check.get("payload", {})
    bundle_dir = Path(str(payload.get("bundle_dir") or bundle_root / BUNDLE_ID))
    manifest_path = bundle_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    required_paths = [
        "versions.json",
        "manifest.json",
        "reproduction_commands.json",
        "manifests/project/xace.project.json",
        "manifests/project/game.cgs.json",
        "logs/logs_index.json",
        "logs/logs/builder.log",
        "proof_links/proof_links.json",
        "health/adapter_health.json",
        "health/provider_readiness.json",
        "config/provider_settings.redacted.json",
        "config/support_bundle_request.json",
    ]
    missing = [relative for relative in required_paths if not (bundle_dir / relative).exists()]
    text = _bundle_text(bundle_dir)
    findings = scan_paths([bundle_dir], repo_root=ROOT)
    proof_links = json.loads((bundle_dir / "proof_links" / "proof_links.json").read_text(encoding="utf-8"))
    reproduction = json.loads((bundle_dir / "reproduction_commands.json").read_text(encoding="utf-8"))
    adapter_health = json.loads((bundle_dir / "health" / "adapter_health.json").read_text(encoding="utf-8"))
    provider_readiness = json.loads((bundle_dir / "health" / "provider_readiness.json").read_text(encoding="utf-8"))
    command_ids = {item.get("id") for item in reproduction.get("commands", []) if isinstance(item, dict)}
    sections = manifest.get("sections") if isinstance(manifest.get("sections"), dict) else {}
    required_sections = [
        "versions",
        "manifests",
        "logs",
        "proof_links",
        "config",
        "adapter_health",
        "provider_readiness",
        "reproduction_commands",
    ]
    return {
        "name": "bundle_contents_and_redaction",
        "ok": (
            not missing
            and all(sections.get(section) is True for section in required_sections)
            and "[REDACTED_SECRET]" in text
            and FAKE_KEY not in text
            and FAKE_BEARER not in text
            and FAKE_GOOGLE not in text
            and not findings
            and proof_links.get("link_count", 0) >= 2
            and {"support_bundle", "quick_certification", "builder_dry_run", "runtime_replay_10_ticks"}.issubset(command_ids)
            and adapter_health.get("target") == "godot"
            and "ok" in provider_readiness
            and Path(str(payload.get("bundle_zip") or "")).exists()
        ),
        "bundle_dir": str(bundle_dir),
        "bundle_zip": str(payload.get("bundle_zip") or ""),
        "missing": missing,
        "sections": sections,
        "redaction_marker_present": "[REDACTED_SECRET]" in text,
        "raw_secret_present": any(secret in text for secret in (FAKE_KEY, FAKE_BEARER, FAKE_GOOGLE)),
        "secret_scan_findings": [
            {
                "path": finding.path,
                "line": finding.line,
                "column": finding.column,
                "kind": finding.kind,
                "preview": finding.preview,
            }
            for finding in findings[:20]
        ],
        "proof_link_count": proof_links.get("link_count", 0),
        "command_ids": sorted(command_ids),
        "adapter_health": adapter_health,
        "provider_readiness_code": provider_readiness.get("code", ""),
    }


def build_report(bundle_root: Path) -> dict[str, Any]:
    fixture_root = bundle_root / "fixture"
    project_dir, provider_settings = build_fixture(fixture_root)
    command_check = run_bundle_command(project_dir, provider_settings, bundle_root)
    checks: list[dict[str, Any]] = [command_check]
    if command_check["ok"]:
        checks.append(validate_bundle(bundle_root, command_check))
    else:
        checks.append({
            "name": "bundle_contents_and_redaction",
            "ok": False,
            "error": "support bundle command failed",
        })
    return {
        "schema": REPORT_SCHEMA,
        "task": "X10-051",
        "x10_051_complete": all(check.get("ok") for check in checks),
        "bundle_id": BUNDLE_ID,
        "checks": checks,
    }


def _bundle_text(bundle_dir: Path) -> str:
    chunks: list[str] = []
    for path in sorted(bundle_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() != ".zip":
            try:
                chunks.append(path.read_text(encoding="utf-8"))
            except UnicodeDecodeError:
                continue
    return "\n".join(chunks)


def _safe_rmtree(path: Path) -> None:
    resolved = path.resolve()
    root = ROOT.resolve()
    if root not in resolved.parents:
        raise RuntimeError(f"refusing to remove path outside repo: {resolved}")
    shutil.rmtree(resolved)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test X10-051 support diagnostics bundle export.")
    parser.add_argument("--output", default="target-codex-task51-support-bundle/report.json")
    parser.add_argument("--bundle-root", default="target-codex-task51-support-bundle/bundle")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    output = (ROOT / args.output).resolve()
    bundle_root = (ROOT / args.bundle_root).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    bundle_root.mkdir(parents=True, exist_ok=True)
    report = build_report(bundle_root)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        status = "PASS" if report["x10_051_complete"] else "FAIL"
        print(f"{status}: wrote {output}")
    return 0 if report["x10_051_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

