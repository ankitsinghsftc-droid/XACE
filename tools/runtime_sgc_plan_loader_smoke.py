"""
Strict runtime SGC persisted-plan loader and compatibility smoke.

This writes a temporary compatible CGS plus a canonical persisted SGC plan,
verifies xace_runtime accepts it with --require-sgc-plan, then verifies missing
or incompatible required plans fail before tick zero with actionable
diagnostics. It also proves CGS-derived compatibility loading rejects
unsupported declared systems instead of silently filtering them, and records
SGC migration/invalidation proof artifacts for stale persisted plans.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME_BIN = (
    REPO_ROOT
    / "target-codex-certify"
    / "debug"
    / ("xace_runtime.exe" if os.name == "nt" else "xace_runtime")
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the strict runtime SGC plan loader smoke.")
    parser.add_argument("--runtime-bin", default=str(DEFAULT_RUNTIME_BIN))
    parser.add_argument("--keep-project", action="store_true")
    args = parser.parse_args(argv)

    runtime_bin = Path(args.runtime_bin).resolve()
    _require(runtime_bin.exists(), f"runtime binary not found: {runtime_bin}")

    root = Path(tempfile.mkdtemp(prefix="xace-runtime-sgc-plan-"))
    try:
        compatible_hash = "a" * 64
        compatible_project = root / "compatible"
        compatible_cgs = write_project(compatible_project, compatible_hash, with_plan=True)
        compatible = run_runtime(runtime_bin, compatible_cgs, expect_success=True)

        missing_hash = "c" * 64
        missing_project = root / "missing-plan"
        missing_cgs = write_project(missing_project, missing_hash, with_plan=False)
        missing = run_runtime(
            runtime_bin,
            missing_cgs,
            expect_success=False,
            expected_error="SGC execution plan required but missing",
        )

        adapter_hash = "f" * 64
        adapter_project = root / "adapter-protocol-mismatch"
        adapter_cgs = write_project(
            adapter_project,
            adapter_hash,
            with_plan=True,
            plan_mutator=lambda plan: plan.__setitem__("adapter_protocol_version", 99),
        )
        adapter_mismatch = run_runtime(
            runtime_bin,
            adapter_cgs,
            expect_success=False,
            expected_error="adapter_protocol_version",
        )
        adapter_proof_path = sgc_migration_proof_path(adapter_project, adapter_hash)
        assert_migration_proof(
            adapter_proof_path,
            "adapter_protocol_version_mismatch",
            adapter_hash,
        )

        migration_hash = "1" * 64
        migration_project = root / "migration-status-mismatch"
        migration_cgs = write_project(
            migration_project,
            migration_hash,
            with_plan=True,
            plan_mutator=lambda plan: plan.__setitem__("migration_status", "pending"),
        )
        migration_mismatch = run_runtime(
            runtime_bin,
            migration_cgs,
            expect_success=False,
            expected_error="migration_status",
        )
        migration_proof_path = sgc_migration_proof_path(migration_project, migration_hash)
        migration_proof = assert_migration_proof(
            migration_proof_path,
            "migration_status_not_current",
            migration_hash,
        )
        _require(
            migration_proof.get("plan_identity", {}).get("migration_status") == "pending",
            "migration proof did not preserve stale migration_status",
        )

        schema_hash = "3" * 64
        schema_project = root / "schema-version-mismatch"
        schema_cgs = write_project(
            schema_project,
            schema_hash,
            with_plan=True,
            plan_mutator=lambda plan: plan.__setitem__("schema_version", "0.0.9"),
        )
        schema_mismatch = run_runtime(
            runtime_bin,
            schema_cgs,
            expect_success=False,
            expected_error="schema_version",
        )
        schema_proof_path = sgc_migration_proof_path(schema_project, schema_hash)
        assert_migration_proof(schema_proof_path, "schema_version_mismatch", schema_hash)

        plan_version_hash = "4" * 64
        plan_version_project = root / "plan-version-mismatch"
        plan_version_cgs = write_project(
            plan_version_project,
            plan_version_hash,
            with_plan=True,
            plan_mutator=lambda plan: plan.__setitem__("plan_version", 2),
        )
        plan_version_mismatch = run_runtime(
            runtime_bin,
            plan_version_cgs,
            expect_success=False,
            expected_error="plan_version",
        )
        plan_version_proof_path = sgc_migration_proof_path(plan_version_project, plan_version_hash)
        assert_migration_proof(
            plan_version_proof_path,
            "plan_version_mismatch",
            plan_version_hash,
        )

        unsupported_hash = "2" * 64
        unsupported_project = root / "derived-unsupported-system"
        unsupported_cgs = write_project(
            unsupported_project,
            unsupported_hash,
            with_plan=False,
            cgs_factory=runtime_unsupported_cgs,
        )
        unsupported_derived = run_runtime(
            runtime_bin,
            unsupported_cgs,
            expect_success=False,
            expected_error="GeneratedCraftingSystem",
            require_sgc_plan=False,
        )
        proof_path = (
            unsupported_project
            / ".xace"
            / "proof"
            / "runtime-compatibility"
            / f"{unsupported_hash}.json"
        )
        _require(proof_path.exists(), f"runtime compatibility proof was not written: {proof_path}")
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        _require(proof.get("ok") is False, "runtime compatibility proof did not record failure")
        _require(
            "GeneratedCraftingSystem" in proof.get("legacy_dropped_system_ids", []),
            "runtime compatibility proof did not record the legacy dropped system",
        )

        summary = {
            "runtime_bin": str(runtime_bin),
            "compatible_project": str(compatible_project),
            "missing_project": str(missing_project),
            "adapter_project": str(adapter_project),
            "migration_project": str(migration_project),
            "unsupported_project": str(unsupported_project),
            "compatible": compatible,
            "missing_required_plan": missing,
            "adapter_protocol_mismatch": adapter_mismatch,
            "adapter_protocol_migration_proof": str(adapter_proof_path),
            "migration_status_mismatch": migration_mismatch,
            "migration_status_proof": str(migration_proof_path),
            "schema_version_mismatch": schema_mismatch,
            "schema_version_proof": str(schema_proof_path),
            "plan_version_mismatch": plan_version_mismatch,
            "plan_version_proof": str(plan_version_proof_path),
            "unsupported_derived_system": unsupported_derived,
            "unsupported_derived_system_proof": str(proof_path),
        }
        print(json.dumps(summary, indent=2, sort_keys=True))
        print("runtime SGC plan loader smoke PASSED")
        return 0
    finally:
        if args.keep_project:
            print(f"kept project: {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)


def write_project(
    project_root: Path,
    cgs_hash: str,
    *,
    with_plan: bool,
    plan_mutator: Callable[[dict[str, Any]], None] | None = None,
    cgs_factory: Callable[[str], dict[str, Any]] | None = None,
) -> Path:
    project_root.mkdir(parents=True, exist_ok=True)
    cgs_path = project_root / "game.cgs.json"
    if cgs_factory is None:
        cgs_factory = runtime_compatible_cgs
    write_json(cgs_path, cgs_factory(cgs_hash))
    if with_plan:
        plan_dir = project_root / ".xace" / "execution_plans"
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan = persisted_plan(cgs_hash)
        if plan_mutator is not None:
            plan_mutator(plan)
        write_json(plan_dir / f"{cgs_hash}.plan.json", plan)
    return cgs_path


def run_runtime(
    runtime_bin: Path,
    cgs_path: Path,
    *,
    expect_success: bool,
    expected_error: str = "",
    require_sgc_plan: bool = True,
) -> dict[str, Any]:
    plan_flag = "--require-sgc-plan" if require_sgc_plan else "--derive-cgs-plan"
    completed = subprocess.run(
        [
            str(runtime_bin),
            "--cgs",
            str(cgs_path),
            plan_flag,
            "--no-wait",
            "--no-control",
            "--ticks",
            "2",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    output = completed.stdout + completed.stderr
    if expect_success:
        _require(
            completed.returncode == 0,
            "runtime failed to load compatible persisted SGC plan:\n" + output[-4000:],
        )
        _require(
            "PersistedSgc" in output,
            "runtime did not report PersistedSgc plan source:\n" + output[-4000:],
        )
    else:
        _require(completed.returncode != 0, "runtime unexpectedly accepted an incompatible required SGC plan")
        _require(expected_error, "expected_error must be supplied for failure checks")
        _require(
            expected_error in output,
            f"runtime did not report expected error {expected_error!r}:\n" + output[-4000:],
        )
    return {
        "cgs": str(cgs_path),
        "require_sgc_plan": require_sgc_plan,
        "derive_cgs_plan": not require_sgc_plan,
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-1000:],
        "stderr_tail": completed.stderr[-1000:],
    }


def sgc_migration_proof_path(project_root: Path, cgs_hash: str) -> Path:
    return project_root / ".xace" / "proof" / "sgc-migration" / f"{cgs_hash}.json"


def assert_migration_proof(path: Path, reason_code: str, cgs_hash: str) -> dict[str, Any]:
    _require(path.exists(), f"SGC migration proof was not written: {path}")
    proof = json.loads(path.read_text(encoding="utf-8"))
    _require(proof.get("schema") == "xace.sgc.plan_migration.v1", "invalid migration proof schema")
    _require(proof.get("ok") is False, "migration proof must record a failed load")
    _require(proof.get("decision") == "reject_and_regenerate", "unexpected migration decision")
    _require(proof.get("migration_performed") is False, "runtime must not migrate stale plans in place")
    _require(proof.get("fallback_to_cgs_derived") is False, "runtime must not fall back to CGS-derived plans")
    _require(proof.get("silent_downgrade_performed") is False, "runtime must not silently downgrade plans")
    _require(proof.get("runtime_tick_started") is False, "runtime must reject stale plans before tick zero")
    _require(proof.get("reason_code") == reason_code, f"unexpected migration proof reason: {proof}")
    _require(proof.get("cgs_hash") == cgs_hash, "migration proof cgs_hash mismatch")
    return proof


def runtime_compatible_cgs(cgs_hash: str) -> dict[str, Any]:
    return {
        "metadata": {
            "name": "Runtime SGC Plan Loader Smoke",
            "schema_version": "0.1.0",
            "version": "0.1.0",
            "execution_plan_version": 1,
            "cgs_hash": cgs_hash,
        },
        "global_systems": [
            {
                "id": "MovementSystem",
                "phase": "Simulation",
                "reads": [1, 5],
                "writes": [1],
                "depends_on": [],
                "deterministic": True,
            }
        ],
        "modes": [
            {
                "id": "default",
                "schema_version": "0.1.0",
                "is_default": True,
                "actors": [
                    {
                        "id": "player",
                        "spawn_count": 1,
                        "components": [
                            {
                                "type_id": 1,
                                "name": "COMP_TRANSFORM_V1",
                                "defaults": {
                                    "position_x": 0.0,
                                    "position_y": 0.0,
                                    "position_z": 0.0,
                                },
                            },
                            {
                                "type_id": 2,
                                "name": "COMP_IDENTITY_V1",
                                "defaults": {"name": "player"},
                            },
                            {
                                "type_id": 5,
                                "name": "COMP_VELOCITY_V1",
                                "defaults": {"vx": 1.0, "vy": 0.0, "vz": 0.0},
                            },
                        ],
                    }
                ],
                "systems": [],
                "rules": [],
            }
        ],
    }


def runtime_unsupported_cgs(cgs_hash: str) -> dict[str, Any]:
    cgs = runtime_compatible_cgs(cgs_hash)
    cgs["global_systems"] = [
        {
            "id": "GeneratedCraftingSystem",
            "phase": "Simulation",
            "reads": [1, 5],
            "writes": [100],
            "depends_on": [],
            "deterministic": True,
        }
    ]
    return cgs


def persisted_plan(cgs_hash: str) -> dict[str, Any]:
    plan_hash = "b" * 64
    return {
        "schema_version": "0.1.0",
        "plan_version": 1,
        "adapter_protocol_version": 1,
        "migration_status": "current",
        "created_tick": 0,
        "plan_hash": plan_hash,
        "compiled_from_cgs_hash": cgs_hash,
        "all_system_ids": ["MovementSystem"],
        "phases": {
            "2": {
                "phase": "Simulation",
                "groups": [
                    {
                        "group_id": "Simulation_group_0",
                        "phase": "Simulation",
                        "parallel": False,
                        "systems": ["MovementSystem"],
                        "serialization_constraints": [],
                        "execution_index": 0,
                    }
                ],
                "total_system_count": 1,
            }
        },
        "component_access_sets": {
            "schema": "xace.sgc.component_access_sets.v1",
            "by_system": {"MovementSystem": {"reads": [1, 5], "writes": [1]}},
            "all_reads": [1, 5],
            "all_writes": [1],
            "component_ids": [1, 5],
        },
        "system_metadata": {
            "schema": "xace.sgc.system_metadata.v1",
            "systems": {
                "MovementSystem": {
                    "display_name": "Movement System",
                    "phase": "Simulation",
                    "depends_on": [],
                    "deterministic": True,
                    "version": {"major": 1, "minor": 0},
                    "description": "Runtime-compatible smoke system.",
                }
            },
        },
        "proof_bundle": {
            "schema": "xace.sgc.proof_ref.v1",
            "path": f".xace/proof/sgc/{cgs_hash}",
            "compiled_from_cgs_hash": cgs_hash,
            "plan_hash": plan_hash,
            "input_hash": "d" * 64,
            "validation_hash": "e" * 64,
        },
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


if __name__ == "__main__":
    raise SystemExit(main())
