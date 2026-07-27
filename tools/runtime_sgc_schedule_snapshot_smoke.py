"""
Runtime SGC schedule snapshot and replay smoke.

This verifies that the standalone runtime executes a persisted SGC schedule
without flattening away group metadata. It runs the real runtime binary twice
against a persisted plan containing two generated systems in one
SGC-parallel-eligible group and asserts every tick snapshot matches the loaded
plan while the runtime reports its deterministic sequential execution policy.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME_BIN = (
    REPO_ROOT
    / "target-codex-certify"
    / "debug"
    / ("xace_runtime.exe" if os.name == "nt" else "xace_runtime")
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the runtime SGC schedule snapshot smoke.")
    parser.add_argument("--runtime-bin", default=str(DEFAULT_RUNTIME_BIN))
    parser.add_argument("--ticks", type=int, default=3)
    parser.add_argument("--keep-project", action="store_true")
    args = parser.parse_args(argv)

    runtime_bin = Path(args.runtime_bin).resolve()
    _require(runtime_bin.exists(), f"runtime binary not found: {runtime_bin}")
    _require(args.ticks > 0, "--ticks must be greater than zero")

    root = Path(tempfile.mkdtemp(prefix="xace-runtime-sgc-schedule-"))
    try:
        cgs_hash = "7" * 64
        cgs_path = write_project(root / "generated-parallel", cgs_hash)
        first_report_path = root / "first.schedule.json"
        second_report_path = root / "second.schedule.json"

        first_run = run_runtime(runtime_bin, cgs_path, first_report_path, args.ticks)
        second_run = run_runtime(runtime_bin, cgs_path, second_report_path, args.ticks)
        first = read_report(first_report_path, args.ticks)
        second = read_report(second_report_path, args.ticks)

        _require(first["snapshots"] == second["snapshots"], "schedule snapshots changed across replay")
        _require(first["groups"] == second["groups"], "loaded schedule groups changed across replay")
        _require(first["system_access"] == second["system_access"], "component access sets changed across replay")
        _require(
            first["system_dependencies"] == second["system_dependencies"],
            "system dependency metadata changed across replay",
        )

        summary = {
            "runtime_bin": str(runtime_bin),
            "project": str(cgs_path.parent),
            "ticks": args.ticks,
            "first_run": first_run,
            "second_run": second_run,
            "first_report": str(first_report_path),
            "second_report": str(second_report_path),
            "plan_hash": first["plan_hash"],
            "parallel_group_execution_policy": first["parallel_group_execution_policy"],
            "parallel_group_worker_threads": first["parallel_group_worker_threads"],
            "group_count": len(first["groups"]),
            "snapshot_count": len(first["snapshots"]),
            "scheduled_system_ids": first["scheduled_system_ids"],
        }
        print(json.dumps(summary, indent=2, sort_keys=True))
        print("runtime SGC schedule snapshot smoke PASSED")
        return 0
    finally:
        if args.keep_project:
            print(f"kept project: {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)


def write_project(project_root: Path, cgs_hash: str) -> Path:
    project_root.mkdir(parents=True, exist_ok=True)
    cgs_path = project_root / "game.cgs.json"
    write_json(cgs_path, generated_parallel_cgs(cgs_hash))
    plan_dir = project_root / ".xace" / "execution_plans"
    plan_dir.mkdir(parents=True, exist_ok=True)
    write_json(plan_dir / f"{cgs_hash}.plan.json", persisted_generated_plan(cgs_hash))
    return cgs_path


def run_runtime(runtime_bin: Path, cgs_path: Path, report_path: Path, ticks: int) -> dict[str, Any]:
    completed = subprocess.run(
        [
            str(runtime_bin),
            "--cgs",
            str(cgs_path),
            "--require-sgc-plan",
            "--no-wait",
            "--no-control",
            "--ticks",
            str(ticks),
            "--quiet",
            "--schedule-snapshot-out",
            str(report_path),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    output = completed.stdout + completed.stderr
    _require(completed.returncode == 0, "runtime schedule snapshot run failed:\n" + output[-4000:])
    _require(report_path.exists(), f"runtime did not write schedule snapshot report: {report_path}")
    return {
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-1000:],
        "stderr_tail": completed.stderr[-1000:],
    }


def read_report(path: Path, ticks: int) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    _require(report.get("schema") == "xace.runtime.schedule_snapshot_report.v1", "invalid report schema")
    _require(report.get("ok") is True, f"schedule report did not pass: {path}")
    _require(report.get("tick_count") == ticks, "report tick_count mismatch")
    _require(report.get("snapshot_count") == ticks, "report snapshot_count mismatch")
    _require(report.get("plan_source") == "persisted_sgc", "runtime did not use persisted SGC plan")
    _require(report.get("plan_hash") == "8" * 64, "report plan_hash mismatch")
    _require(report.get("compiled_from_cgs_hash") == "7" * 64, "report CGS hash mismatch")
    hash_log = report.get("hash_log")
    _require(isinstance(hash_log, list) and len(hash_log) == ticks, "report hash_log mismatch")
    for index, record in enumerate(hash_log):
        _require(record.get("tick") == index, f"hash_log tick mismatch at index {index}")
        world_hash = record.get("world_hash")
        _require(isinstance(world_hash, str) and len(world_hash) == 64, "invalid world hash")
    _require(
        report.get("latest_world_hash") == hash_log[-1]["world_hash"],
        "latest_world_hash did not match hash_log tail",
    )
    _require(
        report.get("parallel_group_execution_policy") == "deterministic_sequential",
        "unexpected parallel group execution policy",
    )
    _require(
        report.get("parallel_group_worker_threads") is False,
        "parallel group worker-thread flag should be false for deterministic sequential policy",
    )

    groups = report.get("groups")
    _require(isinstance(groups, list) and len(groups) == 1, "expected one persisted schedule group")
    group = groups[0]
    _require(group.get("group_id") == "Simulation_group_0", "group_id was not preserved")
    _require(group.get("phase") == "Simulation", "group phase was not preserved")
    _require(group.get("parallel") is True, "parallel group flag was not preserved")
    _require(group.get("execution_index") == 0, "execution index was not preserved")
    _require(
        group.get("systems") == ["GeneratedCounterSystem", "GeneratedLootRollSystem"],
        "system order was not preserved",
    )
    scheduled_system_ids = report.get("scheduled_system_ids")
    _require(
        scheduled_system_ids == ["GeneratedCounterSystem", "GeneratedLootRollSystem"],
        "scheduled system identity list was not preserved",
    )
    _require(
        group.get("component_access", {}).get("GeneratedCounterSystem", {}).get("writes") == [300],
        "counter write access was not preserved",
    )
    _require(
        group.get("component_access", {}).get("GeneratedLootRollSystem", {}).get("reads") == [301],
        "loot read access was not preserved",
    )

    for index, snapshot in enumerate(report.get("snapshots", [])):
        _require(snapshot.get("tick") == index, f"snapshot tick mismatch at index {index}")
        _require(snapshot.get("plan_hash") == report.get("plan_hash"), f"snapshot plan hash mismatch at tick {index}")
        _require(
            snapshot.get("compiled_from_cgs_hash") == report.get("compiled_from_cgs_hash"),
            f"snapshot compiled CGS hash mismatch at tick {index}",
        )
        _require(snapshot.get("cgs_hash") == report.get("compiled_from_cgs_hash"), f"snapshot CGS hash mismatch at tick {index}")
        _require(
            snapshot.get("scheduled_system_ids") == scheduled_system_ids,
            f"snapshot scheduled system identity mismatch at tick {index}",
        )
        _require(snapshot.get("groups") == groups, f"snapshot group mismatch at tick {index}")
        _require(
            snapshot.get("system_access") == report.get("system_access"),
            f"snapshot component access mismatch at tick {index}",
        )
        _require(
            snapshot.get("system_dependencies") == report.get("system_dependencies"),
            f"snapshot dependencies mismatch at tick {index}",
        )
    return report


def generated_parallel_cgs(cgs_hash: str) -> dict[str, Any]:
    return {
        "metadata": {
            "name": "Runtime SGC Schedule Snapshot Smoke",
            "schema_version": "0.1.0",
            "version": "0.1.0",
            "cgs_hash": cgs_hash,
            "execution_plan_version": 1,
        },
        "global_systems": [
            {
                "id": "GeneratedCounterSystem",
                "phase": "Simulation",
                "reads": [300],
                "writes": [300],
                "depends_on": [],
                "deterministic": True,
                "runtime_executor": {
                    "kind": "generated.increment_numeric_field",
                    "component_type_id": 300,
                    "field": "count",
                    "amount": 1,
                    "abi": {
                        "schema": "xace.generated_system_abi.v1",
                        "version": 1,
                        "inputs": {
                            "query_components": [300],
                            "component_reads": [300],
                            "current_tick": False,
                        },
                        "events": {"emits": []},
                        "rng": {"allowed": False, "max_calls_per_entity": 0},
                        "errors": {"policy": "halt_and_rollback"},
                        "rollback": {
                            "mutation_hook": "mutation_gate_deferred",
                            "event_hook": "event_bus_phase_buffered",
                            "rng_hook": "rng_windowed",
                        },
                    },
                },
            },
            {
                "id": "GeneratedLootRollSystem",
                "phase": "Simulation",
                "reads": [301],
                "writes": [],
                "depends_on": [],
                "deterministic": True,
                "runtime_executor": {
                    "kind": "generated.emit_event_on_rng_threshold",
                    "component_type_id": 301,
                    "chance": 1.0,
                    "event_type": "generated.loot_roll",
                    "payload": {"source": "generated"},
                    "abi": {
                        "schema": "xace.generated_system_abi.v1",
                        "version": 1,
                        "inputs": {
                            "query_components": [301],
                            "component_reads": [301],
                            "current_tick": True,
                        },
                        "events": {
                            "emits": [
                                {
                                    "event_type": "generated.loot_roll",
                                    "broadcast": True,
                                    "payload": {"source": "generated"},
                                }
                            ]
                        },
                        "rng": {"allowed": True, "max_calls_per_entity": 1},
                        "errors": {"policy": "halt_and_rollback"},
                        "rollback": {
                            "mutation_hook": "mutation_gate_deferred",
                            "event_hook": "event_bus_phase_buffered",
                            "rng_hook": "rng_windowed",
                        },
                    },
                },
            },
        ],
        "modes": [
            {
                "id": "default",
                "schema_version": "0.1.0",
                "is_default": True,
                "actors": [
                    {
                        "id": "counter",
                        "spawn_count": 1,
                        "components": [
                            {"type_id": 300, "name": "COMP_COUNTER_V1", "defaults": {"count": 0}}
                        ],
                    },
                    {
                        "id": "loot_source",
                        "spawn_count": 1,
                        "components": [
                            {
                                "type_id": 301,
                                "name": "COMP_LOOT_ROLL_V1",
                                "defaults": {"enabled": True},
                            }
                        ],
                    },
                ],
                "systems": [],
                "rules": [],
            }
        ],
    }


def persisted_generated_plan(cgs_hash: str) -> dict[str, Any]:
    plan_hash = "8" * 64
    return {
        "schema_version": "0.1.0",
        "plan_version": 1,
        "adapter_protocol_version": 1,
        "migration_status": "current",
        "created_tick": 0,
        "plan_hash": plan_hash,
        "compiled_from_cgs_hash": cgs_hash,
        "all_system_ids": ["GeneratedCounterSystem", "GeneratedLootRollSystem"],
        "phases": {
            "2": {
                "phase": "Simulation",
                "groups": [
                    {
                        "group_id": "Simulation_group_0",
                        "phase": "Simulation",
                        "parallel": True,
                        "systems": ["GeneratedCounterSystem", "GeneratedLootRollSystem"],
                        "serialization_constraints": [],
                        "execution_index": 0,
                    }
                ],
                "total_system_count": 2,
            }
        },
        "component_access_sets": {
            "schema": "xace.sgc.component_access_sets.v1",
            "by_system": {
                "GeneratedCounterSystem": {"reads": [300], "writes": [300]},
                "GeneratedLootRollSystem": {"reads": [301], "writes": []},
            },
            "all_reads": [300, 301],
            "all_writes": [300],
            "component_ids": [300, 301],
        },
        "system_metadata": {
            "schema": "xace.sgc.system_metadata.v1",
            "systems": {
                "GeneratedCounterSystem": {
                    "display_name": "Generated Counter System",
                    "phase": "Simulation",
                    "depends_on": [],
                    "deterministic": True,
                    "version": {"major": 1, "minor": 0},
                    "description": "",
                },
                "GeneratedLootRollSystem": {
                    "display_name": "Generated Loot Roll System",
                    "phase": "Simulation",
                    "depends_on": [],
                    "deterministic": True,
                    "version": {"major": 1, "minor": 0},
                    "description": "",
                },
            },
        },
        "proof_bundle": {
            "schema": "xace.sgc.proof_ref.v1",
            "path": f".xace/proof/sgc/{cgs_hash}",
            "compiled_from_cgs_hash": cgs_hash,
            "plan_hash": plan_hash,
            "input_hash": "1" * 64,
            "validation_hash": "2" * 64,
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
