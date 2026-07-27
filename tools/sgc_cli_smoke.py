"""
Editor-free smoke test for the real System Graph Compiler CLI.

This deliberately exercises the compiled SGC executable through stdin/stdout,
not the Rust library API and not the fake SGC wiring helper.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SGC_SMOKE_CGS_HASH = "d" * 64


def default_sgc_binary() -> Path:
    exe_name = "xace-system-graph-compiler.exe" if os.name == "nt" else "xace-system-graph-compiler"
    return REPO_ROOT / "target-codex-certify" / "debug" / exe_name


def smoke_input() -> dict[str, Any]:
    return {
        "schema": "xace.sgc.cli.input.v1",
        "schema_version": "0.1.0",
        "plan_version": 1,
        "cgs_hash": SGC_SMOKE_CGS_HASH,
        "systems": [
            {
                "id": "InputSystem",
                "phase": "Input",
                "reads": [6],
                "writes": [5],
                "version_major": 1,
                "version_minor": 0,
            },
            {
                "id": "MovementSystem",
                "phase": "Simulation",
                "reads": [5],
                "writes": [1],
                "depends_on": ["InputSystem"],
                "version_major": 1,
                "version_minor": 0,
            },
        ],
    }


def invalid_phase_input() -> dict[str, Any]:
    return {
        "schema": "xace.sgc.cli.input.v1",
        "schema_version": "0.1.0",
        "plan_version": 1,
        "cgs_hash": SGC_SMOKE_CGS_HASH,
        "systems": [
            {
                "id": "BadPhaseSystem",
                "phase": "DefinitelyNotAPhase",
                "reads": [],
                "writes": [],
            }
        ],
    }


def run_smoke(sgc_bin: Path) -> dict[str, Any]:
    if not sgc_bin.exists():
        raise RuntimeError(f"SGC binary not found: {sgc_bin}")
    completed = subprocess.run(
        [str(sgc_bin)],
        cwd=str(REPO_ROOT),
        input=json.dumps(smoke_input(), sort_keys=True),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "SGC CLI exited with "
            f"{completed.returncode}.\nstderr:\n{completed.stderr[-4000:]}\nstdout:\n{completed.stdout[-1000:]}"
        )
    try:
        plan = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"SGC CLI stdout was not valid JSON: {exc}\n{completed.stdout[-1000:]}") from exc

    require(plan.get("schema_version") == "0.1.0", "schema_version mismatch")
    require(plan.get("plan_version") == 1, "plan_version mismatch")
    require(plan.get("compiled_from_cgs_hash") == SGC_SMOKE_CGS_HASH, "cgs hash was not stamped into plan")
    require(plan.get("adapter_protocol_version") == 1, "adapter_protocol_version mismatch")
    require(plan.get("migration_status") == "current", "migration_status mismatch")
    require(plan.get("created_tick") == 0, "created_tick mismatch")
    require(isinstance(plan.get("plan_hash"), str) and len(plan["plan_hash"]) == 64, "plan_hash is not SHA-256 hex")
    all_system_ids = plan.get("all_system_ids") or []
    require(all_system_ids == ["InputSystem", "MovementSystem"], f"unexpected all_system_ids: {all_system_ids!r}")
    require(plan.get("phases"), "plan has no phase schedules")
    access = plan.get("component_access_sets") or {}
    require(access.get("schema") == "xace.sgc.component_access_sets.v1", "component_access_sets schema mismatch")
    require(access.get("by_system", {}).get("InputSystem") == {"reads": [6], "writes": [5]}, "InputSystem access mismatch")
    metadata = plan.get("system_metadata") or {}
    require(metadata.get("schema") == "xace.sgc.system_metadata.v1", "system_metadata schema mismatch")
    require(
        metadata.get("systems", {}).get("MovementSystem", {}).get("phase") == "Simulation",
        "MovementSystem metadata phase mismatch",
    )
    proof = plan.get("proof_bundle") or {}
    require(proof.get("schema") == "xace.sgc.proof_ref.v1", "proof_bundle schema mismatch")
    require(proof.get("path") == f".xace/proof/sgc/{SGC_SMOKE_CGS_HASH}", "proof_bundle path mismatch")
    require(proof.get("compiled_from_cgs_hash") == SGC_SMOKE_CGS_HASH, "proof_bundle CGS hash mismatch")
    require(proof.get("plan_hash") == plan["plan_hash"], "proof_bundle plan_hash mismatch")
    require(isinstance(proof.get("input_hash"), str) and len(proof["input_hash"]) == 64, "proof input_hash mismatch")
    require(isinstance(proof.get("validation_hash"), str) and len(proof["validation_hash"]) == 64, "proof validation_hash mismatch")
    error_summary = run_error_contract_smoke(sgc_bin)
    return {
        "ok": True,
        "sgc_bin": str(sgc_bin),
        "plan_hash": plan["plan_hash"],
        "systems": all_system_ids,
        "phase_count": len(plan["phases"]),
        "error_contract": error_summary,
    }


def run_error_contract_smoke(sgc_bin: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [str(sgc_bin)],
        cwd=str(REPO_ROOT),
        input=json.dumps(invalid_phase_input(), sort_keys=True),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=30,
    )
    require(completed.returncode == 1, f"invalid phase returned {completed.returncode}, expected 1")
    require(not completed.stdout.strip(), f"error path wrote stdout: {completed.stdout[-1000:]}")
    try:
        error = json.loads(completed.stderr)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"SGC CLI stderr was not valid error JSON: {exc}\n{completed.stderr[-1000:]}") from exc

    require(error.get("schema") == "xace.sgc.cli.error.v1", "error schema mismatch")
    require(error.get("ok") is False, "error ok flag mismatch")
    require(error.get("code") == "INVALID_PHASE", f"unexpected error code: {error.get('code')!r}")
    require(error.get("category") == "invalid_input", "error category mismatch")
    require(error.get("exit_code") == 1, "error exit_code mismatch")
    require(error.get("system_id") == "BadPhaseSystem", "error system_id mismatch")
    return {
        "code": error["code"],
        "category": error["category"],
        "system_id": error["system_id"],
    }


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the real SGC CLI smoke test.")
    parser.add_argument("--sgc-bin", default=str(default_sgc_binary()), help="Path to xace-system-graph-compiler.")
    parser.add_argument("--json", action="store_true", help="Print the smoke summary as JSON.")
    args = parser.parse_args(argv)

    try:
        summary = run_smoke(Path(args.sgc_bin).resolve())
    except Exception as exc:  # noqa: BLE001 - smoke tools should report first actionable failure.
        print(f"SGC CLI smoke failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(summary, sort_keys=True))
    else:
        print("SGC CLI smoke PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
