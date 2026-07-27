"""
Validate that production packages are covered by exactly one root workspace.
"""

from __future__ import annotations

import json
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = REPO_ROOT / "docs" / "source_inventory.json"


@dataclass(frozen=True)
class Finding:
    path: str
    message: str


def _norm(path: str) -> str:
    return path.replace("\\", "/").rstrip("/")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_toml(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _cargo_members(root: Path) -> list[str]:
    data = _load_toml(root / "Cargo.toml")
    return [_norm(member) for member in data.get("workspace", {}).get("members", [])]


def _uv_members(root: Path) -> list[str]:
    data = _load_toml(root / "pyproject.toml")
    return [_norm(member) for member in data.get("tool", {}).get("uv", {}).get("workspace", {}).get("members", [])]


def _npm_members(root: Path) -> list[str]:
    data = _load_json(root / "package.json")
    return [_norm(member) for member in data.get("workspaces", [])]


def _workspace_for_kind(kind: str) -> str | None:
    if kind == "rust-package" or kind == "rust-example" or kind == "mixed-package":
        return "cargo"
    if kind == "python-package":
        return "uv"
    if kind == "npm-python-package":
        return "npm"
    return None


def _duplicates(values: list[str]) -> set[str]:
    seen: set[str] = set()
    duplicate: set[str] = set()
    for value in values:
        if value in seen:
            duplicate.add(value)
        seen.add(value)
    return duplicate


def run(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    inventory = _load_json(root / "docs" / "source_inventory.json")
    entries = inventory.get("entries", [])

    workspaces = {
        "cargo": _cargo_members(root),
        "uv": _uv_members(root),
        "npm": _npm_members(root),
    }
    for workspace_name, members in workspaces.items():
        for duplicate in sorted(_duplicates(members)):
            findings.append(Finding(duplicate, f"listed more than once in {workspace_name} workspace"))

    for entry in entries:
        path = _norm(str(entry.get("path", "")))
        status = entry.get("status")
        kind = str(entry.get("kind", ""))
        if status == "production-source-uncovered":
            findings.append(Finding(path, "production package is still marked uncovered"))
        if status != "production-source":
            continue
        expected_workspace = _workspace_for_kind(kind)
        if expected_workspace is None:
            continue
        matches = [
            workspace_name
            for workspace_name, members in workspaces.items()
            if path in members
        ]
        if matches != [expected_workspace]:
            expected = f"{expected_workspace} workspace exactly once"
            actual = ", ".join(matches) if matches else "no workspace"
            findings.append(Finding(path, f"expected {expected}; found {actual}"))

    return findings


def main(argv: list[str] | None = None) -> int:
    root = Path(argv[0]).resolve() if argv else REPO_ROOT
    findings = run(root)
    if findings:
        print("XACE workspace membership check failed:", file=sys.stderr)
        for finding in findings:
            print(f"{finding.path}: {finding.message}", file=sys.stderr)
        return 1
    print("workspace membership check PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
