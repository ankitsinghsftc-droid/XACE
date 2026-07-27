"""
Check XACE docs/UI/source text for launch-blocking product overclaims.

The allowlist is intentionally narrow: governance docs may list forbidden
claims, and local docs may mention them only inside explicit "do not claim"
sections. Everything else should use the safe wording in
docs/XACE_PRODUCT_CLAIMS_MATRIX.md.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

SCAN_ROOTS = [
    "README.md",
    "docs",
    "packages",
    "adapters",
    "tools",
    "Start XACE Builder.cmd",
]

SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    "dist",
    "node_modules",
    "target",
}

SKIP_FILE_NAMES = {
    "XACE_PRODUCTION_READINESS_MASTER_PLAN.md",
    "XACE_PRODUCT_CLAIMS_MATRIX.md",
    "forbidden_claims_check.py",
}

TEXT_SUFFIXES = {
    "",
    ".cmd",
    ".cs",
    ".cpp",
    ".gd",
    ".h",
    ".html",
    ".json",
    ".md",
    ".py",
    ".rs",
    ".ts",
    ".tsx",
}

FORBIDDEN_PATTERNS = [
    ("arbitrary-gameplay-generation", r"\bgenerate\s+arbitrary\s+gameplay\s+systems\b"),
    ("any-game-from-prompt", r"\bcreate\s+any\s+game\s+from\s+a\s+prompt\b"),
    ("finished-game-portability", r"\bfull\s+finished-game\s+portability\s+between\s+engines\b"),
    (
        "automatic-engine-gameplay-import",
        r"\bimport\s+existing\s+(unity|godot|unreal)(/|,|\s+or\s+|\\)?(godot|unity|unreal)?(/|,|\s+or\s+|\\)?(unreal|unity|godot)?\s+gameplay\s+automatically\b",
    ),
    ("finished-game-export", r"\bexport\s+a\s+finished\s+game\b"),
    ("production-grade-multiplayer", r"\bproduction-grade\s+multiplayer\b"),
    ("live-determinism", r"\bdeterministic\s+runtime\s+is\s+fully\s+enforced\s+live\b"),
    ("mutationgate-atomic", r"\bmutationgate\s+transactions\s+are\s+atomic\b"),
    ("real-sgc-production", r"\breal\s+sgc\s+production\s+integration\b"),
    ("secure-secrets", r"\bsecrets\s+are\s+securely\s+stored\b"),
    ("nontechnical-public-creators", r"\bready\s+for\s+non-technical\s+public\s+creators\b"),
    ("professional-studios", r"\bready\s+for\s+professional\s+studios\b"),
]

ALLOW_CONTEXT_PATTERNS = [
    re.compile(r"\bdo\s+not\s+claim\b", re.IGNORECASE),
    re.compile(r"\bmust\s+not\s+publicly\s+make\b", re.IGNORECASE),
    re.compile(r"\bforbidden\s+public\s+claims\b", re.IGNORECASE),
    re.compile(r"\bblocked\s+wording\b", re.IGNORECASE),
    re.compile(r"\bblocked\s+claims\b", re.IGNORECASE),
    re.compile(r"\bnot\s+(a\s+)?launch\s+claim\b", re.IGNORECASE),
    re.compile(r"\bnot\s+yet\b", re.IGNORECASE),
]


@dataclass(frozen=True)
class Finding:
    path: Path
    line_number: int
    claim_id: str
    line: str


def iter_scan_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for item in SCAN_ROOTS:
        path = root / item
        if not path.exists():
            continue
        if path.is_file():
            if should_scan_file(path):
                files.append(path)
            continue
        for child in path.rglob("*"):
            if not child.is_file():
                continue
            if any(part in SKIP_DIRS or part.startswith("target-") for part in child.relative_to(root).parts):
                continue
            if should_scan_file(child):
                files.append(child)
    return sorted(set(files))


def should_scan_file(path: Path) -> bool:
    if path.name in SKIP_FILE_NAMES:
        return False
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return False
    return True


def is_allowed_context(lines: list[str], index: int) -> bool:
    start = max(0, index - 8)
    context = "\n".join(lines[start : index + 1])
    return any(pattern.search(context) for pattern in ALLOW_CONTEXT_PATTERNS)


def scan_file(path: Path, root: Path) -> list[Finding]:
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    findings: list[Finding] = []
    compiled = [(claim_id, re.compile(pattern, re.IGNORECASE)) for claim_id, pattern in FORBIDDEN_PATTERNS]
    for index, line in enumerate(lines):
        for claim_id, pattern in compiled:
            if pattern.search(line) and not is_allowed_context(lines, index):
                findings.append(
                    Finding(
                        path=path.relative_to(root),
                        line_number=index + 1,
                        claim_id=claim_id,
                        line=line.strip(),
                    )
                )
    return findings


def run(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in iter_scan_files(root):
        findings.extend(scan_file(path, root))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check XACE docs and UI text for forbidden public claims.")
    parser.add_argument("--root", default=str(REPO_ROOT), help="Repository root to scan.")
    parser.add_argument("--json", action="store_true", help="Emit findings as JSON.")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    findings = run(root)
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "path": str(finding.path),
                        "line": finding.line_number,
                        "claim_id": finding.claim_id,
                        "text": finding.line,
                    }
                    for finding in findings
                ],
                indent=2,
            )
        )
    elif findings:
        print("Forbidden XACE product claims found:", file=sys.stderr)
        for finding in findings:
            print(
                f"{finding.path}:{finding.line_number}: {finding.claim_id}: {finding.line}",
                file=sys.stderr,
            )
    else:
        print("forbidden claims check PASSED")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
