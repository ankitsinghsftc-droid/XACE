#!/usr/bin/env python3
"""Generate local XACE determinism proof artifacts.

The output directory is:

    .xace/proof/determinism/<run-id>/

Each run contains:
    - manifest.json: machine-readable command results and metadata
    - summary.md: human-readable proof summary
    - commands/*.txt: captured stdout/stderr per command

This is a local proof artifact generator, not a benchmark runner. Criterion
benchmarks are defined in packages/runtime-core/benches.rs and can be run
separately with `cargo bench -p xace-runtime-core --bench determinism_overheads`.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROOF_ROOT = REPO_ROOT / ".xace" / "proof" / "determinism"


@dataclass
class CommandResult:
    name: str
    command: list[str]
    exit_code: int
    output_file: str

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate XACE determinism proof artifacts.")
    parser.add_argument("--run-id", default="", help="Optional stable proof run id.")
    parser.add_argument(
        "--include-torture",
        action="store_true",
        help="Run the Windows 10,000-tick torture test as part of this proof.",
    )
    parser.add_argument(
        "--target-dir",
        default="target-codex-determinism-proof",
        help="Cargo target directory used for proof commands.",
    )
    args = parser.parse_args()

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    proof_dir = PROOF_ROOT / run_id
    commands_dir = proof_dir / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)

    commands: list[tuple[str, list[str]]] = [
        (
            "runtime_orchestrator",
            [
                "cargo",
                "test",
                "-p",
                "xace-runtime-core",
                "runtime_orchestrator",
                "--target-dir",
                args.target_dir,
            ],
        ),
        (
            "determinism_guard",
            [
                "cargo",
                "test",
                "-p",
                "xace-runtime-core",
                "determinism_guard",
                "--target-dir",
                args.target_dir,
            ],
        ),
        (
            "code_generation_static_checks",
            [
                python_executable(),
                "packages/prompt-intelligence/src/tests/test_code_generation.py",
            ],
        ),
    ]

    if args.include_torture:
        commands.append(
            (
                "windows_10000_tick_torture",
                [
                    "cargo",
                    "test",
                    "-p",
                    "xace-runtime-core",
                    "windows_10000_tick_deterministic_torture",
                    "--target-dir",
                    args.target_dir,
                ],
            )
        )

    results = [run_command(name, command, commands_dir) for name, command in commands]
    manifest = {
        "run_id": run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(REPO_ROOT),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "python": sys.version,
        },
        "proof_scope": [
            "canonical 64-char SHA-256 world hashes",
            "runtime replay hash-log validation",
            "determinism guard failure paths",
            "generated-system static nondeterminism rejection",
        ],
        "commands": [asdict(result) | {"passed": result.passed} for result in results],
        "passed": all(result.passed for result in results),
    }

    (proof_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (proof_dir / "summary.md").write_text(render_summary(manifest), encoding="utf-8")

    print(proof_dir)
    return 0 if manifest["passed"] else 1


def python_executable() -> str:
    return sys.executable or "python"


def run_command(name: str, command: list[str], commands_dir: Path) -> CommandResult:
    output_path = commands_dir / f"{name}.txt"
    with output_path.open("w", encoding="utf-8", errors="replace") as output:
        output.write("$ " + " ".join(command) + "\n\n")
        output.flush()
        proc = subprocess.run(
            command,
            cwd=REPO_ROOT,
            stdout=output,
            stderr=subprocess.STDOUT,
            text=True,
            env=os.environ.copy(),
        )
    return CommandResult(
        name=name,
        command=command,
        exit_code=proc.returncode,
        output_file=str(output_path.relative_to(commands_dir.parent)),
    )


def render_summary(manifest: dict) -> str:
    status = "PASS" if manifest["passed"] else "FAIL"
    lines = [
        f"# XACE Determinism Proof: {status}",
        "",
        f"- Run ID: `{manifest['run_id']}`",
        f"- Created UTC: `{manifest['created_at_utc']}`",
        f"- Platform: `{manifest['platform']['system']} {manifest['platform']['release']}`",
        "",
        "## Scope",
    ]
    lines.extend(f"- {item}" for item in manifest["proof_scope"])
    lines.extend(["", "## Commands"])
    for result in manifest["commands"]:
        mark = "PASS" if result["passed"] else "FAIL"
        lines.append(
            f"- {mark}: `{result['name']}` exit={result['exit_code']} output=`{result['output_file']}`"
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
