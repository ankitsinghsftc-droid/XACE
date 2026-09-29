"""Operator-only AG-024 runtime lifecycle entry point; never an agent tool."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1] / "packages/builder-workspace/server"
sys.path.insert(0, str(SERVER_DIR))

from agent_host.codex_runtime_lifecycle import (  # noqa: E402
    CodexRuntimeLifecycle,
    CodexRuntimeLifecycleError,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path)
    sub = parser.add_subparsers(dest="operation", required=True)
    guide = sub.add_parser("guide")
    guide.add_argument("action", choices=("install", "update", "repair", "rollback", "remove"),
                       nargs="?", default="install")
    for operation in ("install", "update", "repair"):
        command = sub.add_parser(operation)
        command.add_argument("executable", type=Path)
        command.add_argument("--confirm-official-install", action="store_true", required=True,
                             help="Confirm this executable came from the official provider installer.")
        command.add_argument("--expected-version")
        command.add_argument("--expected-sha256")
    for operation in ("inspect", "rollback", "remove", "recover"):
        sub.add_parser(operation)
    args = parser.parse_args(argv)
    try:
        lifecycle = CodexRuntimeLifecycle(args.state_dir)
        if args.operation == "guide":
            result = lifecycle.guided_plan(args.action)
        elif args.operation in {"install", "update", "repair"}:
            result = lifecycle.verify_and_activate(
                args.executable, operation=args.operation,
                expected_version=args.expected_version, expected_sha256=args.expected_sha256,
                confirm_official_install=args.confirm_official_install,
            )
        else:
            action = {"inspect": lifecycle.inspect, "rollback": lifecycle.rollback,
                      "remove": lifecycle.deactivate, "recover": lifecycle.recover_interrupted}
            result = action[args.operation]()
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1 if result.get("state_error") else 0
    except (CodexRuntimeLifecycleError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc), "operation": args.operation}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
