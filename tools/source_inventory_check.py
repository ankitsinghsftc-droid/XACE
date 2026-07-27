"""
Validate docs/source_inventory.json against the repository tree.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = Path("docs/source_inventory.json")
ALLOWED_STATUSES = {
    "production-source",
    "production-source-uncovered",
    "test-only",
    "archived",
    "generated",
    "external",
}


@dataclass(frozen=True)
class Finding:
    path: str
    message: str


def _load_inventory(root: Path) -> tuple[dict[str, Any] | None, list[Finding]]:
    path = root / INVENTORY_PATH
    if not path.exists():
        return None, [Finding(str(INVENTORY_PATH), "inventory file is missing")]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, [Finding(str(INVENTORY_PATH), f"invalid JSON: {exc}")]
    return data, []


def _entry_maps(entries: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    exact: dict[str, dict[str, Any]] = {}
    patterns: list[str] = []
    for entry in entries:
        path = str(entry.get("path", "")).replace("\\", "/").rstrip("/")
        if entry.get("glob"):
            patterns.append(path)
        else:
            exact[path] = entry
    return exact, patterns


def _covered(rel_path: str, exact: dict[str, dict[str, Any]], patterns: list[str]) -> bool:
    norm = rel_path.replace("\\", "/").rstrip("/")
    return norm in exact or any(fnmatch.fnmatch(norm, pattern) for pattern in patterns)


def _existing_children(root: Path, rel: str) -> list[str]:
    base = root / rel
    if not base.exists() or not base.is_dir():
        return []
    return sorted(str(child.relative_to(root)).replace("\\", "/") for child in base.iterdir())


def _existing_files(root: Path, rel: str, pattern: str = "*") -> list[str]:
    base = root / rel
    if not base.exists() or not base.is_dir():
        return []
    return sorted(str(child.relative_to(root)).replace("\\", "/") for child in base.rglob(pattern) if child.is_file())


def run(root: Path) -> list[Finding]:
    data, findings = _load_inventory(root)
    if data is None:
        return findings

    if data.get("schema") != "xace.source_inventory.v1":
        findings.append(Finding(str(INVENTORY_PATH), "schema must be xace.source_inventory.v1"))

    entries = data.get("entries")
    if not isinstance(entries, list):
        return findings + [Finding(str(INVENTORY_PATH), "entries must be a list")]

    seen: set[str] = set()
    for index, entry in enumerate(entries):
        path = str(entry.get("path", "")).replace("\\", "/").rstrip("/")
        status = entry.get("status")
        if not path:
            findings.append(Finding(str(INVENTORY_PATH), f"entry {index} is missing path"))
            continue
        if path in seen:
            findings.append(Finding(path, "duplicate inventory entry"))
        seen.add(path)
        if status not in ALLOWED_STATUSES:
            findings.append(Finding(path, f"invalid status: {status}"))
        if not str(entry.get("kind", "")).strip():
            findings.append(Finding(path, "missing kind"))
        if not str(entry.get("notes", "")).strip():
            findings.append(Finding(path, "missing notes"))

    exact, patterns = _entry_maps(entries)

    required_paths: set[str] = set()
    required_paths.update(_existing_children(root, "."))
    required_paths.update(_existing_children(root, "packages"))
    required_paths.update(_existing_children(root, "adapters"))
    required_paths.update(_existing_children(root, "examples"))
    required_paths.update(_existing_children(root, "projects"))
    required_paths.update(_existing_children(root, "tests"))
    required_paths.update(_existing_files(root, "docs"))
    required_paths.update(_existing_files(root, "tools", "*.py"))
    required_paths.update(_existing_files(root, ".github", "*.yml"))
    required_paths.update(_existing_files(root, ".github", "*.yaml"))

    for rel_path in sorted(required_paths):
        if rel_path == ".":
            continue
        if not _covered(rel_path, exact, patterns):
            findings.append(Finding(rel_path, "path exists but is not classified in source inventory"))

    for path, entry in exact.items():
        status = entry.get("status")
        if status == "external":
            continue
        if not (root / path).exists():
            findings.append(Finding(path, "inventory entry path does not exist"))

    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate XACE source-of-truth inventory.")
    parser.add_argument("--root", default=str(REPO_ROOT), help="Repository root to scan.")
    parser.add_argument("--json", action="store_true", help="Emit findings as JSON.")
    args = parser.parse_args(argv)

    findings = run(Path(args.root).resolve())
    if args.json:
        print(json.dumps([finding.__dict__ for finding in findings], indent=2))
    elif findings:
        print("XACE source inventory check failed:", file=sys.stderr)
        for finding in findings:
            print(f"{finding.path}: {finding.message}", file=sys.stderr)
    else:
        print("source inventory check PASSED")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
