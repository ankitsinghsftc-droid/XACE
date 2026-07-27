from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTER_PATH = REPO_ROOT / "docs" / "fake_skip_register.json"

ALLOWED_DISPOSITIONS = {
    "remove",
    "replace",
    "isolate",
    "document-test-only",
}

TEXT_SUFFIXES = {
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
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yml",
    ".yaml",
}

EXCLUDED_DIR_NAMES = {
    ".git",
    ".xace",
    ".VSCodeCounter",
    "__pycache__",
    "node_modules",
}

EXCLUDED_FILE_PATTERNS = {
    "docs/fake_skip_register.json",
    "docs/XACE_FAKE_AND_SKIP_REGISTER.md",
    "tools/fake_skip_register_check.py",
}

RISK_PATTERN = re.compile(
    r"\b(fake|mock|stub|stubs|skipped|smoke|placeholder|conceptual|fallback)\b"
    r"|fake[_-]"
    r"|_Mock"
    r"|--skip"
    r"|not implemented"
    r"|unimplemented!?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Finding:
    path: str
    message: str


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _load_register() -> dict[str, Any]:
    return json.loads(REGISTER_PATH.read_text(encoding="utf-8"))


def _matches(pattern: str, rel_path: str) -> bool:
    pattern = pattern.replace("\\", "/")
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        if "*" in prefix or "?" in prefix:
            return fnmatch(rel_path, pattern) or fnmatch(rel_path, prefix)
        return rel_path == prefix or rel_path.startswith(prefix + "/")
    return rel_path == pattern or fnmatch(rel_path, pattern)


def _covered(rel_path: str, covers: list[str]) -> bool:
    return any(_matches(pattern, rel_path) for pattern in covers)


def _iter_text_files() -> list[Path]:
    files: list[Path] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel_path = _rel(path)
        parts = set(Path(rel_path).parts)
        if parts & EXCLUDED_DIR_NAMES:
            continue
        if any(rel_path == item or fnmatch(rel_path, item) for item in EXCLUDED_FILE_PATTERNS):
            continue
        if path.name.startswith(".") and path.suffix not in TEXT_SUFFIXES:
            continue
        if path.suffix not in TEXT_SUFFIXES and path.name not in {"Cargo.lock", "package-lock.json"}:
            continue
        if rel_path.startswith("target"):
            continue
        if "/dist/" in rel_path or rel_path.endswith("/dist"):
            continue
        files.append(path)
    return files


def _risky_files() -> list[str]:
    risky: list[str] = []
    for path in _iter_text_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if RISK_PATTERN.search(text):
            risky.append(_rel(path))
    return sorted(set(risky))


def validate_register(data: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    if data.get("schema") != "xace.fake_skip_register.v1":
        findings.append(Finding(str(REGISTER_PATH), "schema must be xace.fake_skip_register.v1"))

    entries = data.get("entries")
    if not isinstance(entries, list):
        return findings + [Finding(str(REGISTER_PATH), "entries must be a list")]

    seen_ids: set[str] = set()
    covers: list[str] = []
    for index, entry in enumerate(entries):
        label = str(entry.get("id") or f"entry[{index}]")
        if label in seen_ids:
            findings.append(Finding(str(REGISTER_PATH), f"duplicate id {label}"))
        seen_ids.add(label)
        for field in ("id", "title", "category", "risk", "disposition", "owner_task", "notes"):
            if not str(entry.get(field, "")).strip():
                findings.append(Finding(str(REGISTER_PATH), f"{label} missing {field}"))
        disposition = str(entry.get("disposition", ""))
        if disposition not in ALLOWED_DISPOSITIONS:
            findings.append(Finding(str(REGISTER_PATH), f"{label} has invalid disposition {disposition!r}"))
        if not isinstance(entry.get("production_path"), bool):
            findings.append(Finding(str(REGISTER_PATH), f"{label} production_path must be boolean"))
        entry_covers = entry.get("covers")
        if not isinstance(entry_covers, list) or not entry_covers:
            findings.append(Finding(str(REGISTER_PATH), f"{label} covers must be a non-empty list"))
            continue
        for pattern in entry_covers:
            if not isinstance(pattern, str) or not pattern.strip():
                findings.append(Finding(str(REGISTER_PATH), f"{label} has empty cover pattern"))
                continue
            covers.append(pattern)
            if "*" not in pattern and not (REPO_ROOT / pattern).exists():
                findings.append(Finding(pattern, f"{label} covers a path that does not exist"))
        evidence = entry.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            findings.append(Finding(str(REGISTER_PATH), f"{label} evidence must be a non-empty list"))

    for rel_path in _risky_files():
        if not _covered(rel_path, covers):
            findings.append(Finding(rel_path, "suspicious fake/mock/stub/skip/smoke/placeholder/fallback marker is not registered"))
    return findings


def main() -> int:
    findings = validate_register(_load_register())
    if findings:
        print("XACE fake-and-skip register check failed:", file=sys.stderr)
        for finding in findings:
            print(f"{finding.path}: {finding.message}", file=sys.stderr)
        return 1
    print("fake-and-skip register check PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
