"""
Editor-free Builder onboarding smoke test.

This covers launch-ready first-run project safety without opening a browser:

    source checkout folder -> rejected as a Builder project
    source-looking folder -> rejected as a Builder project
    generated game project -> opens normally
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = REPO_ROOT / "packages" / "builder-workspace" / "server"
PROJECT_SYSTEM_DIR = REPO_ROOT / "packages" / "project-system"

for path in (SERVER_DIR, PROJECT_SYSTEM_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from builder_server import _reject_source_checkout_project  # noqa: E402
from project_creator import CreateProjectRequest, ProjectCreator  # noqa: E402


def run_builder_onboarding_smoke(workspace: Path) -> dict[str, Any]:
    workspace.mkdir(parents=True, exist_ok=True)

    repo_rejection = _reject_source_checkout_project(REPO_ROOT)
    _require(repo_rejection, "real XACE source checkout was not rejected")
    _require("source checkout" in repo_rejection.lower(), "source checkout rejection was not user-readable")

    fake_source = workspace / "fake-source-checkout"
    (fake_source / "packages" / "builder-workspace").mkdir(parents=True, exist_ok=True)
    (fake_source / "packages" / "runtime-core").mkdir(parents=True, exist_ok=True)
    (fake_source / "Cargo.toml").write_text("[workspace]\n", encoding="utf-8")
    fake_rejection = _reject_source_checkout_project(fake_source)
    _require(fake_rejection, "source-looking folder was not rejected")

    creator = ProjectCreator()
    game_project = workspace / "first-game"
    created = creator.create_project(CreateProjectRequest(
        project_dir=str(game_project),
        name="First Game",
        engine_type="godot",
        template_id="blank_3d",
    ))
    _require(not _reject_source_checkout_project(game_project), "generated game project was rejected")

    opened = creator.open_project(game_project)
    _require(opened.manifest.name == "First Game", "generated project did not open with the expected name")
    _require(Path(opened.cgs_path).exists(), "generated project CGS path does not exist")

    return {
        "ok": True,
        "workspace": str(workspace),
        "repo_rejected": True,
        "fake_source_rejected": True,
        "created_project": created.project_dir,
        "opened_project": opened.project_dir,
        "engine_type": opened.manifest.engine_type,
        "cgs_path": opened.cgs_path,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test Builder onboarding project safety.")
    parser.add_argument("--target-dir", default="")
    args = parser.parse_args(argv)

    cleanup: tempfile.TemporaryDirectory[str] | None = None
    if args.target_dir:
        target_dir = Path(args.target_dir).resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        workspace = Path(tempfile.mkdtemp(prefix="builder-onboarding-", dir=str(target_dir)))
    else:
        cleanup = tempfile.TemporaryDirectory(prefix="xace-builder-onboarding-")
        workspace = Path(cleanup.name)

    summary = run_builder_onboarding_smoke(workspace)
    print(json.dumps(summary, indent=2, sort_keys=True))
    print("builder onboarding smoke PASSED")

    if cleanup is not None:
        cleanup.cleanup()
    return 0


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


if __name__ == "__main__":
    raise SystemExit(main())
