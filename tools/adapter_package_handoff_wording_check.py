#!/usr/bin/env python3
"""
Retained X10-060 proof for adapter package handoff wording.

This is a narrow source/report wording gate. It does not ban legitimate CGS
export, debug-report export, support-bundle export, TypeScript exports, or Godot
``@export`` annotations. It checks the adapter-package handoff surfaces that
could otherwise imply a finished-game export flow.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_SCHEMA = "xace.adapter_package_handoff_wording_check_report.v1"


SCANNED_FILES = [
    "README.md",
    "XACE_10_OUT_OF_10_COMPLETION_TASKLIST.md",
    "docs/LAUNCH_READINESS_MAP.md",
    "docs/XACE_PRODUCT_CLAIMS_MATRIX.md",
    "docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md",
    "docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md",
    "docs/source_inventory.json",
    "packages/builder-workspace/server/builder_server.py",
    "packages/builder-workspace/src/layout/main_layout.ts",
    "packages/builder-workspace/src/panels/semantic_binding_panel.ts",
    "packages/builder-workspace/src/panels/semantic_binding_status.ts",
    "packages/builder-workspace/tools/builder_ui_contract_test.mjs",
    "packages/asset-registry/asset_reference_preflight.py",
    "packages/asset-registry/semantic_binding_status.py",
    "packages/asset-registry/tests/test_asset_reference_preflight.py",
    "packages/asset-registry/tests/test_semantic_binding_status.py",
    "tools/asset_reference_validation_check.py",
    "tools/semantic_binding_status_check.py",
    "adapters/godot/xace_entity_manager.gd",
    "adapters/unity/XaceDeltaApplicator.cs",
    "adapters/unreal/XaceDeltaApplicator.cpp",
]


REQUIRED_MARKERS = {
    "packages/builder-workspace/server/builder_server.py": [
        "/api/adapter-package/handoff/{target}",
        ".xace\" / \"adapter_package_handoffs",
        "xace.adapter_package_handoff_manifest.v1",
        "xace_adapter_package_handoff_manifest.json",
        "shipping_boundary",
    ],
    "packages/builder-workspace/src/layout/main_layout.ts": [
        "xb-handoff-menu",
        "xb-handoff-btn",
        "_handoffAdapterPackage",
        "/api/adapter-package/handoff/",
        "xace:adapter-package-handoff-complete",
        "Adapter package handoff",
    ],
    "packages/builder-workspace/src/panels/semantic_binding_panel.ts": [
        "Pre-runtime/handoff status",
        "runtime/handoff launch",
    ],
    "packages/builder-workspace/src/panels/semantic_binding_status.ts": [
        "runtime/handoff launch",
    ],
    "packages/asset-registry/asset_reference_preflight.py": [
        "ADAPTER_PACKAGE_HANDOFF",
        "adapter_package_handoff",
        "validate_before_adapter_package_handoff",
    ],
    "packages/asset-registry/semantic_binding_status.py": [
        "blocks_handoff",
        "runtime/handoff gates",
    ],
    "adapters/godot/xace_entity_manager.gd": ["blocks_handoff"],
    "adapters/unity/XaceDeltaApplicator.cs": ["blocks_handoff"],
    "adapters/unreal/XaceDeltaApplicator.cpp": ["blocks_handoff"],
    "README.md": ["Import And Adapter Package Handoff", "Adapter package handoff means"],
    "docs/XACE_PRODUCT_CLAIMS_MATRIX.md": ["| Adapter package handoff |"],
}


FORBIDDEN_MARKERS = [
    ("/api/export", "legacy Builder adapter package API route"),
    ("xace_export_manifest", "legacy adapter package manifest name"),
    (".xace/exports", "legacy adapter package artifact path"),
    (".xace\\\\exports", "legacy adapter package artifact path"),
    ("xb-export", "legacy Builder adapter package CSS class"),
    ("_exportAdapter", "legacy Builder adapter package method name"),
    ("xace:export-complete", "legacy Builder adapter package event name"),
    ("Adapter package export", "legacy adapter package UI/report wording"),
    ("Export means", "README adapter package definition wording"),
    ("Import And Export", "README section title wording"),
    ("runtime/export", "semantic binding runtime/handoff UI wording"),
    ("Pre-runtime/export", "semantic binding status label"),
    ("pre-export", "semantic binding status report wording"),
    ("blocks_export", "adapter status report field"),
    ("validate_before_export", "asset preflight API name"),
    ("AssetPreflightPhase.EXPORT", "asset preflight enum member"),
    ("phase=\"export\"", "asset preflight report phase"),
    ("phase='export'", "asset preflight report phase"),
    ("runtime/export/save", "asset validation report wording"),
    ("valid runtime/export", "asset validation check wording"),
    ("/api/export/{target}", "legacy route in docs"),
    ("Adapter export", "product-row adapter package wording"),
    ("Export currently copies adapter", "master-plan stale adapter package wording"),
]


ALLOWED_EXPORT_CONTEXTS = [
    # Product matrix blocked wording intentionally lists claims that must not be made.
    ("docs/XACE_PRODUCT_CLAIMS_MATRIX.md", "Export a finished game"),
    ("docs/XACE_PRODUCT_CLAIMS_MATRIX.md", "Forbidden Public Claims"),
    ("docs/XACE_PRODUCT_CLAIMS_MATRIX.md", "Full finished-game portability"),
    # Master plan blocked-wording sections may retain the unsupported product-promise phrase.
    ("docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md", "Export a finished game"),
    ("docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md", "finished-game export"),
    ("docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md", "no UI/docs imply XACE alone ships a finished game"),
    # Later task title remains as backlog terminology only if it has already been renamed in X10 tasklist.
    ("XACE_COMMERCIAL_READINESS_MASTER_TASKLIST.md", "export"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the X10-060 adapter package handoff wording proof.")
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "target-codex-task60-adapter-handoff-wording" / "report.json"),
        help="Path to write the retained JSON report.",
    )
    parser.add_argument("--json", action="store_true", help="Print the report JSON to stdout.")
    args = parser.parse_args()

    output = Path(args.output).resolve()
    report = run_check()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif report["ok"]:
        print(f"adapter package handoff wording check PASSED ({len(report['checks'])} checks)")
    else:
        print("adapter package handoff wording check FAILED", file=sys.stderr)
        for check in report["checks"]:
            if not check["ok"]:
                print(f"- {check['name']}: {check['detail']}", file=sys.stderr)
    return 0 if report["ok"] else 1


def run_check() -> dict[str, Any]:
    files = {path: _read(path) for path in SCANNED_FILES}
    checks = [
        _required_marker_check(files),
        _forbidden_marker_check(files),
        _semantic_report_field_check(files),
        _builder_api_surface_check(files),
    ]
    return {
        "schema": REPORT_SCHEMA,
        "task": "X10-060",
        "generated_at_utc": _utc_now(),
        "ok": all(check["ok"] for check in checks),
        "x10_060_complete": all(check["ok"] for check in checks),
        "checks": checks,
        "scanned_files": [
            {
                "path": path,
                "sha256": hashlib.sha256(files[path].encode("utf-8")).hexdigest(),
                "bytes": len(files[path].encode("utf-8")),
            }
            for path in sorted(files)
        ],
    }


def _required_marker_check(files: dict[str, str]) -> dict[str, Any]:
    missing: list[dict[str, str]] = []
    for path, markers in REQUIRED_MARKERS.items():
        text = files.get(path, "")
        for marker in markers:
            if marker not in text:
                missing.append({"path": path, "marker": marker})
    return {
        "name": "required_handoff_markers",
        "ok": not missing,
        "detail": f"missing={len(missing)}",
        "missing": missing,
    }


def _forbidden_marker_check(files: dict[str, str]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    for path, text in files.items():
        for marker, reason in FORBIDDEN_MARKERS:
            start = 0
            while True:
                index = text.find(marker, start)
                if index < 0:
                    break
                line = text.count("\n", 0, index) + 1
                excerpt = _line_at(text, line)
                if not _allowed(path, excerpt):
                    findings.append({
                        "path": path,
                        "line": line,
                        "marker": marker,
                        "reason": reason,
                        "excerpt": excerpt.strip(),
                    })
                start = index + max(1, len(marker))
    return {
        "name": "forbidden_adapter_export_markers",
        "ok": not findings,
        "detail": f"findings={len(findings)}",
        "findings": findings,
    }


def _semantic_report_field_check(files: dict[str, str]) -> dict[str, Any]:
    report_sources = [
        "packages/asset-registry/semantic_binding_status.py",
        "tools/semantic_binding_status_check.py",
        "adapters/godot/xace_entity_manager.gd",
        "adapters/unity/XaceDeltaApplicator.cs",
        "adapters/unreal/XaceDeltaApplicator.cpp",
    ]
    missing = [path for path in report_sources if "blocks_handoff" not in files.get(path, "")]
    stale = [path for path in report_sources if "blocks_export" in files.get(path, "")]
    return {
        "name": "report_fields_use_handoff",
        "ok": not missing and not stale,
        "detail": f"missing_blocks_handoff={len(missing)} stale_blocks_export={len(stale)}",
        "missing": missing,
        "stale": stale,
    }


def _builder_api_surface_check(files: dict[str, str]) -> dict[str, Any]:
    server = files["packages/builder-workspace/server/builder_server.py"]
    ui = files["packages/builder-workspace/src/layout/main_layout.ts"]
    ok = (
        '/api/adapter-package/handoff/{target}' in server
        and '/api/export/{target}' not in server
        and '/api/adapter-package/handoff/' in ui
        and '/api/export/' not in ui
        and 'xace_adapter_package_handoff_manifest.json' in server
        and 'xace_export_manifest' not in server
    )
    return {
        "name": "builder_api_renamed",
        "ok": ok,
        "detail": "Builder API/UI/manifest names use adapter package handoff",
    }


def _read(path: str) -> str:
    file_path = REPO_ROOT / path
    if not file_path.exists():
        return ""
    return file_path.read_text(encoding="utf-8", errors="replace")


def _line_at(text: str, line: int) -> str:
    lines = text.splitlines()
    if line <= 0 or line > len(lines):
        return ""
    return lines[line - 1]


def _allowed(path: str, excerpt: str) -> bool:
    return any(path == allowed_path and token in excerpt for allowed_path, token in ALLOWED_EXPORT_CONTEXTS)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
