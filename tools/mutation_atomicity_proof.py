#!/usr/bin/env python3
"""Generate local XACE MutationGate atomicity proof artifacts.

The output directory is:

    .xace/proof/mutation-atomicity/<run-id>/

Each run contains:
    - manifest.json: machine-readable command results and metadata
    - summary.md: human-readable proof summary
    - commands/*.txt: captured stdout/stderr per command
    - pre_state.json / post_state.json: byte-compared rollback states
    - pre_post_hash_report.json: canonical hash equality report
    - zero_diff_state_report.json: byte-for-byte state equality report
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
PROOF_ROOT = REPO_ROOT / ".xace" / "proof" / "mutation-atomicity"


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
    parser = argparse.ArgumentParser(
        description="Generate XACE MutationGate atomicity proof artifacts."
    )
    parser.add_argument("--run-id", default="", help="Optional stable proof run id.")
    parser.add_argument(
        "--target-dir",
        default="target-codex-mutation-proof",
        help="Cargo target directory used for proof commands.",
    )
    args = parser.parse_args()

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    proof_dir = PROOF_ROOT / run_id
    commands_dir = proof_dir / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)

    proof_env = os.environ.copy()
    proof_env["XACE_MUTATION_PROOF_DIR"] = str(proof_dir)

    commands: list[tuple[str, list[str], dict[str, str] | None]] = [
        (
            "mutation_atomicity_tests",
            [
                "cargo",
                "test",
                "-p",
                "xace-runtime-core",
                "mutation_atomicity",
                "--target-dir",
                args.target_dir,
            ],
            proof_env,
        ),
        (
            "mutation_atomicity_bench_compile",
            [
                "cargo",
                "bench",
                "-p",
                "xace-runtime-core",
                "--bench",
                "determinism_overheads",
                "--no-run",
                "--target-dir",
                args.target_dir,
            ],
            None,
        ),
    ]

    results = [
        run_command(name, command, commands_dir, env=env)
        for name, command, env in commands
    ]
    artifact_files = [
        "pre_state.json",
        "post_state.json",
        "pre_post_hash_report.json",
        "zero_diff_state_report.json",
    ]
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
            "nested/concurrent MutationGate transactions rejected by contract",
            "five-operation batch rolls back after op3 failure",
            "byte-for-byte pre/post state equality",
            "canonical 64-char SHA-256 pre/post hash equality",
            "stress, malformed JSON, missing entity, and component-table failure paths",
            "snapshot-per-batch benchmark target is compiled and threshold-smoked",
        ],
        "artifact_files": [
            path for path in artifact_files if (proof_dir / path).exists()
        ],
        "commands": [asdict(result) | {"passed": result.passed} for result in results],
        "passed": all(result.passed for result in results)
        and all((proof_dir / path).exists() for path in artifact_files),
    }

    (proof_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (proof_dir / "summary.md").write_text(render_summary(manifest), encoding="utf-8")

    print(proof_dir)
    return 0 if manifest["passed"] else 1


def run_command(
    name: str,
    command: list[str],
    commands_dir: Path,
    env: dict[str, str] | None = None,
) -> CommandResult:
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
            env=env if env is not None else os.environ.copy(),
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
        f"# XACE MutationGate Atomicity Proof: {status}",
        "",
        f"- Run ID: `{manifest['run_id']}`",
        f"- Created UTC: `{manifest['created_at_utc']}`",
        f"- Platform: `{manifest['platform']['system']} {manifest['platform']['release']}`",
        "",
        "## Scope",
    ]
    lines.extend(f"- {item}" for item in manifest["proof_scope"])
    lines.extend(["", "## Artifacts"])
    lines.extend(f"- `{path}`" for path in manifest["artifact_files"])
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
