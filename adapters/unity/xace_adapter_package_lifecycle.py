#!/usr/bin/env python3
"""Lifecycle wrapper for a versioned XACE adapter package."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


MANIFEST_FILENAME = "xace_adapter_package_version_manifest.json"
LIFECYCLE_SCHEMA = "xace.adapter_package_lifecycle.v1"
COMMANDS = ("describe", "install", "uninstall", "rollback")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a XACE adapter package lifecycle command.")
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("--package-root", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--engine-project", default="")
    parser.add_argument("--destination", default="")
    parser.add_argument("--xace-repo", default=os.environ.get("XACE_REPO_ROOT", ""))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    package_root = Path(args.package_root).resolve()
    target = _target_from_package(package_root)

    if args.command == "describe":
        return _emit({
            "ok": True,
            "schema": LIFECYCLE_SCHEMA,
            "target": target,
            "package_root": str(package_root),
            "manifest": str(package_root / MANIFEST_FILENAME),
            "commands": list(COMMANDS),
            "requires_xace_repo_for_mutations": True,
        }, args.json)

    if not args.engine_project:
        return _emit({"ok": False, "schema": LIFECYCLE_SCHEMA, "error": "--engine-project is required."}, args.json, 2)

    repo_root = _find_xace_repo(args.xace_repo)
    if repo_root is None:
        return _emit({
            "ok": False,
            "schema": LIFECYCLE_SCHEMA,
            "error": "Unable to find XACE repo. Pass --xace-repo or set XACE_REPO_ROOT.",
        }, args.json, 2)

    sys.path.insert(0, str(repo_root / "packages" / "project-system"))
    from adapter_installation import (  # noqa: PLC0415
        install_or_update_adapter,
        rollback_latest_adapter_transaction,
        uninstall_adapter,
    )

    destination = args.destination or None
    if args.command == "install":
        result = install_or_update_adapter(
            source_root=package_root,
            engine_project_root=args.engine_project,
            engine_type=target,
            destination=destination,
            overwrite=True,
            metadata={"adapter_package_manifest": str(package_root / MANIFEST_FILENAME)},
        )
    elif args.command == "uninstall":
        result = uninstall_adapter(
            engine_project_root=args.engine_project,
            engine_type=target,
            destination=destination,
        )
    else:
        result = rollback_latest_adapter_transaction(
            engine_project_root=args.engine_project,
            engine_type=target,
            destination=destination,
        )
    return _emit(result, args.json, 0 if result.get("ok") else 1)


def _target_from_package(package_root: Path) -> str:
    manifest_path = package_root / MANIFEST_FILENAME
    if manifest_path.is_file():
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            target = str(payload.get("target") or "").strip().lower()
            if target:
                return target
        except Exception:
            pass
    return package_root.name.strip().lower()


def _find_xace_repo(value: str) -> Path | None:
    candidates = []
    if value:
        candidates.append(Path(value).resolve())
    script_path = Path(__file__).resolve()
    candidates.extend(script_path.parents)
    for candidate in candidates:
        if (candidate / "packages" / "project-system" / "adapter_installation.py").is_file():
            return candidate
    return None


def _emit(payload: dict[str, Any], as_json: bool, code: int = 0) -> int:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
