"""
Scan XACE source and generated artifacts for credential-looking secrets.

The scanner is intentionally conservative about directories it walks by
default: generated build outputs and dependency folders are skipped unless a
caller passes those paths explicitly.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("anthropic_api_key", re.compile(r"sk-ant-[A-Za-z0-9][A-Za-z0-9_\-]{8,}")),
    ("generic_api_key", re.compile(r"sk-[A-Za-z0-9][A-Za-z0-9_\-]{8,}")),
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z_\-]{20,}")),
    ("bearer_token", re.compile(r"(?i)Bearer\s+[A-Za-z0-9._~+\-/=]{12,}")),
    ("api_key_header", re.compile(r"(?i)(?:x-api-key|api-key)\s*[:=]\s*[A-Za-z0-9._~+\-/=]{12,}")),
)

SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "node_modules",
    "target",
    "dist",
    "build",
    "__pycache__",
}

SKIP_PREFIXES = (
    "target-",
)

TEXT_SUFFIXES = {
    ".bat",
    ".cmd",
    ".cpp",
    ".cs",
    ".gd",
    ".h",
    ".html",
    ".json",
    ".jsonl",
    ".lock",
    ".log",
    ".md",
    ".py",
    ".rs",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}


@dataclass(frozen=True)
class SecretFinding:
    path: str
    line: int
    column: int
    kind: str
    preview: str


def scan_paths(paths: Iterable[Path], *, repo_root: Path = REPO_ROOT) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    seen: set[Path] = set()
    for path in paths:
        candidate = Path(path).resolve()
        if candidate in seen or not candidate.exists():
            continue
        seen.add(candidate)
        if candidate.is_dir():
            for file_path in _iter_files(candidate):
                findings.extend(_scan_file(file_path, repo_root=repo_root))
        else:
            findings.extend(_scan_file(candidate, repo_root=repo_root))
    return findings


def default_source_paths(repo_root: Path = REPO_ROOT) -> list[Path]:
    return [
        repo_root / "packages",
        repo_root / "tools",
        repo_root / "tests",
        repo_root / "docs",
        repo_root / "adapters",
    ]


def project_artifact_paths(
    project: Path,
    *,
    include_exports: bool = False,
    include_logs: bool = False,
    include_snapshots: bool = False,
    include_crash_reports: bool = False,
    include_telemetry: bool = False,
) -> list[Path]:
    project = project.resolve()
    paths = [project]
    xace_dir = project / ".xace"
    if include_exports:
        paths.append(xace_dir / "exports")
    if include_logs:
        paths.extend([xace_dir / "logs", project / "logs"])
    if include_snapshots:
        paths.append(xace_dir / "snapshots")
    if include_crash_reports:
        paths.extend([xace_dir / "crash_reports", project / "crash_reports"])
    if include_telemetry:
        paths.extend([xace_dir / "telemetry", project / "telemetry"])
    return paths


def write_report(findings: list[SecretFinding], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "secret_scan_report.json"
    payload = {
        "ok": not findings,
        "finding_count": len(findings),
        "findings": [asdict(finding) for finding in findings],
    }
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan XACE source/project artifacts for leaked secrets.")
    parser.add_argument("--path", action="append", default=[], help="Path to scan. Can be passed multiple times.")
    parser.add_argument("--project", default="", help="Project root to scan.")
    parser.add_argument("--source", action="store_true", help="Scan repository source/docs/adapters/tools.")
    parser.add_argument("--exports", action="store_true", help="Include <project>/.xace/exports.")
    parser.add_argument("--logs", action="store_true", help="Include project log folders.")
    parser.add_argument("--snapshots", action="store_true", help="Include <project>/.xace/snapshots.")
    parser.add_argument("--crash-reports", action="store_true", help="Include project crash report folders.")
    parser.add_argument("--telemetry", action="store_true", help="Include project telemetry folders.")
    parser.add_argument("--fixtures", action="store_true", help="Scan repository tests as fixtures.")
    parser.add_argument("--output", default="", help="Directory for secret_scan_report.json.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a short text summary.")
    args = parser.parse_args(argv)

    paths = [Path(item) for item in args.path]
    if args.source:
        paths.extend(default_source_paths(REPO_ROOT))
    if args.fixtures:
        paths.append(REPO_ROOT / "tests")
        paths.extend(REPO_ROOT.glob("packages/*/tests"))
    if args.project:
        paths.extend(project_artifact_paths(
            Path(args.project),
            include_exports=args.exports,
            include_logs=args.logs,
            include_snapshots=args.snapshots,
            include_crash_reports=args.crash_reports,
            include_telemetry=args.telemetry,
        ))
    if not paths:
        parser.error("pass --path, --source, --fixtures, or --project")

    findings = scan_paths(paths)
    payload = {
        "ok": not findings,
        "finding_count": len(findings),
        "findings": [asdict(finding) for finding in findings],
    }
    if args.output:
        payload["report_path"] = str(write_report(findings, Path(args.output)))

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif findings:
        print(f"secret scan FAILED: {len(findings)} finding(s)")
        for finding in findings[:20]:
            print(f"{finding.path}:{finding.line}:{finding.column}: {finding.kind}: {finding.preview}")
    else:
        print("secret scan PASSED")
    return 1 if findings else 0


def _iter_files(root: Path) -> Iterable[Path]:
    for current, dirs, files in os.walk(root):
        dirs[:] = [
            item
            for item in dirs
            if item not in SKIP_DIRS and not item.startswith(SKIP_PREFIXES)
        ]
        for name in files:
            path = Path(current) / name
            if _looks_text(path):
                yield path


def _scan_file(path: Path, *, repo_root: Path) -> list[SecretFinding]:
    if not _looks_text(path):
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            return []
    except OSError:
        return []

    findings: list[SecretFinding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if "[REDACTED_SECRET]" in line:
            continue
        for kind, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(line):
                findings.append(SecretFinding(
                    path=_display_path(path, repo_root),
                    line=line_number,
                    column=match.start() + 1,
                    kind=kind,
                    preview=_redacted_preview(line, match.start(), match.end()),
                ))
    return findings


def _looks_text(path: Path) -> bool:
    if path.name in {"Cargo.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"}:
        return True
    return path.suffix.lower() in TEXT_SUFFIXES


def _display_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return str(path)


def _redacted_preview(line: str, start: int, end: int) -> str:
    snippet = line[max(0, start - 36): min(len(line), end + 36)]
    token_start = start - max(0, start - 36)
    token_end = token_start + (end - start)
    return snippet[:token_start] + "[REDACTED_SECRET]" + snippet[token_end:]


if __name__ == "__main__":
    raise SystemExit(main())
