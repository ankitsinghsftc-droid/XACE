"""
Validate that the frozen XACE commercial scope record exists and is referenced
from the docs, Builder UI, CI, and release certification gates.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCOPE_PATH = Path("docs/XACE_COMMERCIAL_SCOPE.md")

REQUIRED_SCOPE_TEXT = [
    "Record ID: XACE-COMMERCIAL-SCOPE-2026-06-14",
    "Scope status: Frozen for commercial-readiness execution",
    "Signed by:",
    "local-first",
    "BYOK",
    "Godot, Unity, and Unreal",
    "Paid Tiers And Entitlements",
    "License Terms",
    "Update Channels",
    "Support Workflow",
    "Privacy And Telemetry",
    "Release Gates",
]

REFERENCE_CHECKS = {
    "README.md": "docs/XACE_COMMERCIAL_SCOPE.md",
    "docs/XACE_PRODUCT_CLAIMS_MATRIX.md": "docs/XACE_COMMERCIAL_SCOPE.md",
    "docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md": "docs/XACE_COMMERCIAL_SCOPE.md",
    "packages/builder-workspace/src/layout/main_layout.ts": "Commercial scope",
    "tools/certify_launch.py": "commercial scope record",
    ".github/workflows/xace-scope.yml": "tools/commercial_scope_check.py",
}


@dataclass(frozen=True)
class Finding:
    path: str
    message: str


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def run(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    scope_file = root / SCOPE_PATH
    if not scope_file.exists():
        return [Finding(str(SCOPE_PATH), "commercial scope record is missing")]

    scope_text = _read(scope_file)
    for needle in REQUIRED_SCOPE_TEXT:
        if needle not in scope_text:
            findings.append(Finding(str(SCOPE_PATH), f"missing required scope text: {needle}"))

    for rel_path, needle in REFERENCE_CHECKS.items():
        path = root / rel_path
        if not path.exists():
            findings.append(Finding(rel_path, "required commercial scope reference file is missing"))
            continue
        text = _read(path)
        if needle not in text:
            findings.append(Finding(rel_path, f"missing commercial scope reference: {needle}"))

    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate XACE commercial scope references.")
    parser.add_argument("--root", default=str(REPO_ROOT), help="Repository root to scan.")
    parser.add_argument("--json", action="store_true", help="Emit findings as JSON.")
    args = parser.parse_args(argv)

    findings = run(Path(args.root).resolve())
    if args.json:
        print(json.dumps([finding.__dict__ for finding in findings], indent=2))
    elif findings:
        print("XACE commercial scope check failed:", file=sys.stderr)
        for finding in findings:
            print(f"{finding.path}: {finding.message}", file=sys.stderr)
    else:
        print("commercial scope check PASSED")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
