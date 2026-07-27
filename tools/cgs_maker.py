"""
Create starter XACE projects.

This CLI delegates to packages/project-system so builder UI, scripts, and tests
all use one project manifest and template contract.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_SYSTEM = REPO_ROOT / "packages" / "project-system"
DEFAULT_PROJECT = REPO_ROOT / "projects" / "zombie_chase"

sys.path.insert(0, str(PROJECT_SYSTEM))

from project_creator import CreateProjectRequest, ProjectCreator  # noqa: E402
from project_templates import (  # noqa: E402
    list_template_ids,
    make_template,
    slug_name,
    stable_cgs_hash,
)


def main() -> int:
    args = parse_args()
    project_dir = Path(args.project).resolve()
    result = ProjectCreator().create_project(CreateProjectRequest(
        project_dir=str(project_dir),
        name=args.name,
        engine_type=args.engine,
        template_id=args.template,
        force=args.force,
    ))
    print(f"Created {result.cgs_path}")
    print(f"Manifest: {result.manifest_path}")
    print(f"CGS hash: {result.cgs_hash}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a starter XACE project.")
    parser.add_argument("--project", default=str(DEFAULT_PROJECT), help="Project directory to create.")
    parser.add_argument("--template", default="horror_chase", choices=list_template_ids(include_aliases=True))
    parser.add_argument("--engine", default="godot", choices=["godot", "unity", "unreal", "headless"])
    parser.add_argument("--name", default="Zombie Chase")
    parser.add_argument("--force", action="store_true", help="Overwrite existing starter files.")
    return parser.parse_args()


def write_project(project_dir: Path, cgs: dict[str, Any], *, overwrite: bool = False) -> None:
    """Compatibility helper for older scripts that only need game.cgs.json."""
    project_dir.mkdir(parents=True, exist_ok=True)
    target = project_dir / "game.cgs.json"
    if target.exists() and not overwrite:
        raise SystemExit(f"{target} already exists. Use --force to overwrite it.")
    target.write_text(json.dumps(cgs, indent=2, sort_keys=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
