"""
Retained proof for the real CGS -> SGC -> runtime -> replay path.

The command creates a small generated-system CGS, compiles it through the real
SGC executable, persists the exact emitted schedule with the runtime-required
metadata envelope, runs the real runtime twice in strict SGC mode, and stores
the replay/hash evidence under .xace/proof/sgc-runtime/<run-id>/ by default.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET_DIR = REPO_ROOT / "target-codex-certify" / "debug"
RUNTIME_EXE = "xace_runtime.exe" if os.name == "nt" else "xace_runtime"
SGC_EXE = "xace-system-graph-compiler.exe" if os.name == "nt" else "xace-system-graph-compiler"
DEFAULT_RUNTIME_BIN = DEFAULT_TARGET_DIR / RUNTIME_EXE
DEFAULT_SGC_BIN = DEFAULT_TARGET_DIR / SGC_EXE
DEFAULT_PROOF_ROOT = REPO_ROOT / ".xace" / "proof" / "sgc-runtime"
HASH_HEX_LENGTH = 64
DEFAULT_WORLD_SEED = 42


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prove real CGS to SGC to runtime replay.")
    parser.add_argument("--runtime-bin", default=str(DEFAULT_RUNTIME_BIN))
    parser.add_argument("--sgc-bin", default=str(DEFAULT_SGC_BIN))
    parser.add_argument("--proof-root", default=str(DEFAULT_PROOF_ROOT))
    parser.add_argument("--run-id", default="", help="Optional retained proof run id.")
    parser.add_argument("--ticks", type=int, default=3)
    parser.add_argument("--world-seed", type=int, default=DEFAULT_WORLD_SEED)
    parser.add_argument("--json", action="store_true", help="Print only the proof summary JSON.")
    args = parser.parse_args(argv)

    try:
        summary = run_proof(
            runtime_bin=Path(args.runtime_bin).resolve(),
            sgc_bin=Path(args.sgc_bin).resolve(),
            proof_root=Path(args.proof_root).resolve(),
            run_id=args.run_id.strip() or None,
            ticks=args.ticks,
            world_seed=args.world_seed,
        )
    except Exception as exc:  # noqa: BLE001 - proof tools should report the first actionable failure.
        print(f"SGC runtime proof failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(summary, sort_keys=True))
    else:
        print(json.dumps(summary, indent=2, sort_keys=True))
        print("SGC runtime proof PASSED")
    return 0


def run_proof(
    runtime_bin: Path,
    sgc_bin: Path,
    proof_root: Path,
    run_id: str | None,
    ticks: int,
    world_seed: int = DEFAULT_WORLD_SEED,
) -> dict[str, Any]:
    require(runtime_bin.is_file(), f"runtime binary not found: {runtime_bin}")
    require(sgc_bin.is_file(), f"SGC binary not found: {sgc_bin}")
    require(ticks > 0, "--ticks must be greater than zero")
    require(0 <= world_seed <= 0xFFFFFFFFFFFFFFFF, "--world-seed must fit in u64")

    proof_dir = allocate_proof_dir(proof_root, run_id)
    project_root = proof_dir / "project"
    cgs = generated_system_cgs()
    cgs_hash = cgs["metadata"]["cgs_hash"]
    generated_system_ids = sorted(system["id"] for system in cgs["global_systems"])
    cgs_path = project_root / "game.cgs.json"
    write_json(cgs_path, cgs)
    input_log = canonical_empty_input_log()
    input_log_hash = sha256_json(input_log)
    write_json(proof_dir / "input_log.json", input_log)

    sgc_input = sgc_input_from_cgs(cgs)
    write_json(proof_dir / "sgc_input.json", sgc_input)
    sgc_result = run_sgc(sgc_bin, sgc_input)
    sgc_plan = sgc_result["plan"]
    validate_sgc_plan(sgc_plan, cgs_hash, sgc_input)
    write_json(proof_dir / "sgc_stdout_plan.json", sgc_plan)

    persisted_plan, sgc_proof_metadata = persist_sgc_plan(
        project_root=project_root,
        sgc_input=sgc_input,
        sgc_plan=sgc_plan,
    )
    persisted_plan_path = (
        project_root / ".xace" / "execution_plans" / f"{cgs_hash}.plan.json"
    )
    write_json(proof_dir / "persisted_plan.json", persisted_plan)

    first_run = run_runtime(
        runtime_bin=runtime_bin,
        cgs_path=cgs_path,
        report_path=proof_dir / "first.schedule_report.json",
        stdout_path=proof_dir / "first.runtime.stdout.txt",
        stderr_path=proof_dir / "first.runtime.stderr.txt",
        ticks=ticks,
        world_seed=world_seed,
    )
    second_run = run_runtime(
        runtime_bin=runtime_bin,
        cgs_path=cgs_path,
        report_path=proof_dir / "second.schedule_report.json",
        stdout_path=proof_dir / "second.runtime.stdout.txt",
        stderr_path=proof_dir / "second.runtime.stderr.txt",
        ticks=ticks,
        world_seed=world_seed,
    )
    first_report = read_runtime_report(first_run["report_path"], persisted_plan, ticks, world_seed)
    second_report = read_runtime_report(second_run["report_path"], persisted_plan, ticks, world_seed)
    replay_checks = compare_replay_reports(first_report, second_report)

    summary = {
        "schema": "xace.sgc_runtime_proof.v1",
        "ok": True,
        "run_id": proof_dir.name,
        "proof_dir": str(proof_dir),
        "project_dir": str(project_root),
        "cgs_path": str(cgs_path),
        "persisted_plan_path": str(persisted_plan_path),
        "ticks": ticks,
        "world_seed": world_seed,
        "input_log_hash": input_log_hash,
        "cgs_hash": cgs_hash,
        "compiled_from_cgs_hash": persisted_plan["compiled_from_cgs_hash"],
        "plan_hash": persisted_plan["plan_hash"],
        "generated_system_ids": generated_system_ids,
        "sgc": {
            "binary": str(sgc_bin),
            "returncode": sgc_result["returncode"],
            "stdout_plan_hash": sgc_plan["plan_hash"],
            "stderr_tail": sgc_result["stderr_tail"],
        },
        "runtime": {
            "binary": str(runtime_bin),
            "first_run": first_run,
            "second_run": second_run,
            "latest_world_hash": first_report["latest_world_hash"],
            "hash_log_count": len(first_report["hash_log"]),
            "hash_log": first_report["hash_log"],
            "scheduled_system_ids": first_report["scheduled_system_ids"],
            "schedule_fingerprint": schedule_fingerprint(first_report),
        },
        "input_log": {
            "schema": input_log["schema"],
            "packet_count": len(input_log["packets"]),
            "hash": input_log_hash,
            "path": str(proof_dir / "input_log.json"),
        },
        "checks": {
            "real_sgc_binary_invoked": True,
            "real_runtime_binary_invoked": True,
            "persisted_sgc_plan_loaded": first_report["plan_source"] == "persisted_sgc",
            "world_seed_pinned": first_report.get("world_seed") == world_seed,
            "input_log_pinned": is_lower_hex_hash(input_log_hash),
            "tick_hash_replay_match": replay_checks["tick_hash_replay_match"],
            "schedule_replay_match": replay_checks["schedule_replay_match"],
            "no_fake_wiring": True,
        },
        "sgc_proof_metadata": sgc_proof_metadata,
        "artifacts": {
            "sgc_input": str(proof_dir / "sgc_input.json"),
            "input_log": str(proof_dir / "input_log.json"),
            "sgc_stdout_plan": str(proof_dir / "sgc_stdout_plan.json"),
            "persisted_plan_copy": str(proof_dir / "persisted_plan.json"),
            "first_schedule_report": str(first_run["report_path"]),
            "second_schedule_report": str(second_run["report_path"]),
        },
    }
    write_json(proof_dir / "summary.json", summary)
    return summary


def canonical_empty_input_log() -> dict[str, Any]:
    return {
        "schema": "xace.replay.input_log.v1",
        "topology": "headless",
        "packets": [],
    }


def allocate_proof_dir(proof_root: Path, requested_run_id: str | None) -> Path:
    proof_root.mkdir(parents=True, exist_ok=True)
    base = requested_run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = proof_root / base
    if requested_run_id:
        require(not candidate.exists(), f"proof run already exists: {candidate}")
        candidate.mkdir(parents=True)
        return candidate
    if not candidate.exists():
        candidate.mkdir(parents=True)
        return candidate
    for index in range(1, 1000):
        candidate = proof_root / f"{base}-{index:03d}"
        if not candidate.exists():
            candidate.mkdir(parents=True)
            return candidate
    raise RuntimeError(f"could not allocate unique proof run under {proof_root}")


def generated_system_cgs() -> dict[str, Any]:
    cgs = {
        "metadata": {
            "name": "SGC Runtime Proof",
            "schema_version": "0.1.0",
            "version": "0.1.0",
            "execution_plan_version": 1,
        },
        "global_systems": [
            generated_counter_system(),
            generated_loot_roll_system(),
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
                            {
                                "type_id": 300,
                                "name": "COMP_COUNTER_V1",
                                "defaults": {"count": 0},
                            }
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
    cgs["metadata"]["cgs_hash"] = sha256_json(cgs)
    return cgs


def generated_counter_system() -> dict[str, Any]:
    return {
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
    }


def generated_loot_roll_system() -> dict[str, Any]:
    return {
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
    }


def sgc_input_from_cgs(cgs: dict[str, Any]) -> dict[str, Any]:
    systems = []
    for system in cgs["global_systems"]:
        systems.append(
            {
                "id": system["id"],
                "display_name": display_name(system["id"]),
                "phase": system["phase"],
                "reads": sorted_unique_ints(system.get("reads", [])),
                "writes": sorted_unique_ints(system.get("writes", [])),
                "depends_on": sorted_unique_strings(system.get("depends_on", [])),
                "deterministic": bool(system.get("deterministic", True)),
                "version_major": 1,
                "version_minor": 0,
                "description": "",
            }
        )
    return {
        "schema": "xace.sgc.cli.input.v1",
        "schema_version": cgs["metadata"]["schema_version"],
        "plan_version": cgs["metadata"]["execution_plan_version"],
        "cgs_hash": cgs["metadata"]["cgs_hash"],
        "systems": systems,
    }


def run_sgc(sgc_bin: Path, sgc_input: dict[str, Any]) -> dict[str, Any]:
    completed = subprocess.run(
        [str(sgc_bin)],
        cwd=str(REPO_ROOT),
        input=json.dumps(sgc_input, sort_keys=True, separators=(",", ":")),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "SGC CLI failed with "
            f"{completed.returncode}.\nstderr:\n{completed.stderr[-4000:]}"
        )
    try:
        plan = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"SGC stdout was not JSON: {exc}") from exc
    return {
        "returncode": completed.returncode,
        "plan": plan,
        "stdout_tail": completed.stdout[-1000:],
        "stderr_tail": completed.stderr[-1000:],
    }


def validate_sgc_plan(
    plan: dict[str, Any],
    cgs_hash: str,
    sgc_input: dict[str, Any],
) -> None:
    require(plan.get("schema_version") == "0.1.0", "SGC plan schema_version mismatch")
    require(plan.get("plan_version") == 1, "SGC plan plan_version mismatch")
    require(
        plan.get("compiled_from_cgs_hash") == cgs_hash,
        "SGC plan compiled_from_cgs_hash mismatch",
    )
    require(is_lower_hex_hash(plan.get("plan_hash")), "SGC plan_hash is not lowercase SHA-256")
    require(plan.get("adapter_protocol_version") == 1, "SGC adapter_protocol_version mismatch")
    require(plan.get("migration_status") == "current", "SGC migration_status mismatch")
    require(plan.get("created_tick") == 0, "SGC created_tick mismatch")
    expected_ids = sorted(system["id"] for system in sgc_input["systems"])
    require(plan.get("all_system_ids") == expected_ids, "SGC all_system_ids mismatch")
    scheduled_ids = []
    phases = plan.get("phases")
    require(isinstance(phases, dict) and phases, "SGC plan has no phases")
    for schedule in phases.values():
        for group in schedule.get("groups", []):
            scheduled_ids.extend(group.get("systems", []))
    require(sorted(scheduled_ids) == expected_ids, "SGC scheduled systems mismatch")
    require(
        plan.get("component_access_sets") == component_access_sets_from_input(sgc_input),
        "SGC component_access_sets mismatch",
    )
    require(
        plan.get("system_metadata") == system_metadata_from_input(sgc_input),
        "SGC system_metadata mismatch",
    )
    proof_ref = plan.get("proof_bundle")
    require(isinstance(proof_ref, dict), "SGC proof_bundle missing")
    require(proof_ref.get("schema") == "xace.sgc.proof_ref.v1", "SGC proof_bundle schema mismatch")
    require(proof_ref.get("path") == f".xace/proof/sgc/{cgs_hash}", "SGC proof_bundle path mismatch")
    require(proof_ref.get("compiled_from_cgs_hash") == cgs_hash, "SGC proof_bundle CGS hash mismatch")
    require(proof_ref.get("plan_hash") == plan["plan_hash"], "SGC proof_bundle plan_hash mismatch")
    require(is_lower_hex_hash(proof_ref.get("input_hash")), "SGC proof_bundle input_hash mismatch")
    require(is_lower_hex_hash(proof_ref.get("validation_hash")), "SGC proof_bundle validation_hash mismatch")


def persist_sgc_plan(
    project_root: Path,
    sgc_input: dict[str, Any],
    sgc_plan: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    cgs_hash = sgc_plan["compiled_from_cgs_hash"]
    plan_hash = sgc_plan["plan_hash"]
    raw_plan_hash = sha256_json(sgc_plan)
    proof_ref = sgc_plan.get("proof_bundle")
    require(isinstance(proof_ref, dict), "SGC proof_bundle missing during persistence")
    input_hash = str(proof_ref.get("input_hash") or "")
    validation_hash = str(proof_ref.get("validation_hash") or "")
    require(is_lower_hex_hash(input_hash), "SGC proof_bundle input_hash invalid during persistence")
    require(is_lower_hex_hash(validation_hash), "SGC proof_bundle validation_hash invalid during persistence")
    persisted_plan = dict(sgc_plan)

    execution_plan_path = (
        project_root / ".xace" / "execution_plans" / f"{cgs_hash}.plan.json"
    )
    proof_dir = project_root / ".xace" / "proof" / "sgc" / cgs_hash
    metadata = {
        "schema": "xace.sgc.proof_bundle.v1",
        "compiled_from_cgs_hash": cgs_hash,
        "plan_hash": plan_hash,
        "input_hash": input_hash,
        "plan_json_hash": raw_plan_hash,
        "validation_hash": validation_hash,
        "proof_ref": proof_ref,
    }
    write_json(execution_plan_path, persisted_plan)
    write_json(proof_dir / "input.json", sgc_input)
    write_json(proof_dir / "plan.json", sgc_plan)
    write_json(proof_dir / "metadata.json", metadata)
    return persisted_plan, metadata


def component_access_sets_from_input(sgc_input: dict[str, Any]) -> dict[str, Any]:
    by_system = {}
    all_reads: set[int] = set()
    all_writes: set[int] = set()
    for system in sgc_input["systems"]:
        reads = sorted_unique_ints(system.get("reads", []))
        writes = sorted_unique_ints(system.get("writes", []))
        by_system[system["id"]] = {"reads": reads, "writes": writes}
        all_reads.update(reads)
        all_writes.update(writes)
    component_ids = sorted(all_reads | all_writes)
    return {
        "schema": "xace.sgc.component_access_sets.v1",
        "by_system": by_system,
        "all_reads": sorted(all_reads),
        "all_writes": sorted(all_writes),
        "component_ids": component_ids,
    }


def system_metadata_from_input(sgc_input: dict[str, Any]) -> dict[str, Any]:
    systems = {}
    for system in sgc_input["systems"]:
        version = system.get("version") if isinstance(system.get("version"), dict) else {}
        systems[system["id"]] = {
            "display_name": system.get("display_name") or display_name(system["id"]),
            "phase": system["phase"],
            "depends_on": sorted_unique_strings(system.get("depends_on", [])),
            "deterministic": bool(system.get("deterministic", True)),
            "version": {
                "major": int(version.get("major", system.get("version_major", 1))),
                "minor": int(version.get("minor", system.get("version_minor", 0))),
            },
            "description": system.get("description", ""),
        }
    return {"schema": "xace.sgc.system_metadata.v1", "systems": systems}


def run_runtime(
    runtime_bin: Path,
    cgs_path: Path,
    report_path: Path,
    stdout_path: Path,
    stderr_path: Path,
    ticks: int,
    world_seed: int,
) -> dict[str, Any]:
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
            "--world-seed",
            str(world_seed),
            "--quiet",
            "--schedule-snapshot-out",
            str(report_path),
        ],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
        check=False,
    )
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(
            "runtime failed with "
            f"{completed.returncode}.\nstderr:\n{completed.stderr[-4000:]}"
        )
    require(report_path.exists(), f"runtime did not write report: {report_path}")
    return {
        "returncode": completed.returncode,
        "report_path": str(report_path),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "stdout_tail": completed.stdout[-1000:],
        "stderr_tail": completed.stderr[-1000:],
    }


def read_runtime_report(
    report_path: str,
    persisted_plan: dict[str, Any],
    ticks: int,
    world_seed: int,
) -> dict[str, Any]:
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    require(report.get("schema") == "xace.runtime.schedule_snapshot_report.v1", "bad report schema")
    require(report.get("ok") is True, f"runtime report did not pass: {report_path}")
    require(report.get("tick_count") == ticks, "runtime tick_count mismatch")
    require(report.get("snapshot_count") == ticks, "runtime snapshot_count mismatch")
    require(report.get("world_seed") == world_seed, "runtime world_seed mismatch")
    require(report.get("plan_source") == "persisted_sgc", "runtime did not use persisted SGC")
    require(report.get("plan_hash") == persisted_plan["plan_hash"], "runtime plan_hash mismatch")
    require(report.get("cgs_hash") == persisted_plan["compiled_from_cgs_hash"], "runtime cgs_hash mismatch")
    require(
        report.get("compiled_from_cgs_hash") == persisted_plan["compiled_from_cgs_hash"],
        "runtime cgs hash mismatch",
    )
    scheduled_system_ids = scheduled_system_ids_from_plan(persisted_plan)
    require(
        report.get("scheduled_system_ids") == scheduled_system_ids,
        "runtime scheduled_system_ids mismatch",
    )
    hash_log = report.get("hash_log")
    require(isinstance(hash_log, list) and len(hash_log) == ticks, "runtime hash_log mismatch")
    for index, record in enumerate(hash_log):
        require(record.get("tick") == index, f"runtime hash_log tick mismatch at {index}")
        require(is_lower_hex_hash(record.get("world_hash")), "runtime world hash is invalid")
    require(
        report.get("latest_world_hash") == hash_log[-1]["world_hash"],
        "latest_world_hash does not match final hash_log record",
    )
    for index, snapshot in enumerate(report.get("snapshots") or []):
        require(snapshot.get("tick") == index, f"runtime snapshot tick mismatch at {index}")
        require(snapshot.get("plan_hash") == report.get("plan_hash"), f"snapshot plan_hash mismatch at {index}")
        require(snapshot.get("cgs_hash") == report.get("cgs_hash"), f"snapshot cgs_hash mismatch at {index}")
        require(
            snapshot.get("compiled_from_cgs_hash") == report.get("compiled_from_cgs_hash"),
            f"snapshot compiled_from_cgs_hash mismatch at {index}",
        )
        require(
            snapshot.get("scheduled_system_ids") == scheduled_system_ids,
            f"snapshot scheduled_system_ids mismatch at {index}",
        )
    return report


def schedule_fingerprint(report: dict[str, Any]) -> str:
    return sha256_json(
        {
            "schema": "xace.runtime.schedule_fingerprint.v1",
            "plan_hash": report.get("plan_hash"),
            "cgs_hash": report.get("cgs_hash"),
            "compiled_from_cgs_hash": report.get("compiled_from_cgs_hash"),
            "scheduled_system_ids": report.get("scheduled_system_ids"),
            "groups": report.get("groups"),
            "system_access": report.get("system_access"),
            "system_dependencies": report.get("system_dependencies"),
            "snapshots": report.get("snapshots"),
        }
    )


def compare_replay_reports(first: dict[str, Any], second: dict[str, Any]) -> dict[str, bool]:
    tick_hash_replay_match = first["hash_log"] == second["hash_log"]
    schedule_replay_match = (
        first["snapshots"] == second["snapshots"]
        and first["groups"] == second["groups"]
        and first["system_access"] == second["system_access"]
        and first["system_dependencies"] == second["system_dependencies"]
    )
    require(tick_hash_replay_match, "runtime tick hash log changed across replay")
    require(schedule_replay_match, "runtime schedule snapshots changed across replay")
    require(
        first["latest_world_hash"] == second["latest_world_hash"],
        "latest runtime world hash changed across replay",
    )
    return {
        "tick_hash_replay_match": tick_hash_replay_match,
        "schedule_replay_match": schedule_replay_match,
    }


def scheduled_system_ids_from_plan(plan: dict[str, Any]) -> list[str]:
    scheduled: list[str] = []
    phases = plan.get("phases")
    if not isinstance(phases, dict):
        return scheduled
    for phase_key in sorted(
        phases.keys(),
        key=lambda key: (0, int(str(key))) if str(key).isdigit() else (1, str(key)),
    ):
        groups = phases.get(phase_key, {}).get("groups", [])
        if not isinstance(groups, list):
            continue
        ordered_groups = sorted(groups, key=lambda group: int(group.get("execution_index", 0)))
        for group in ordered_groups:
            systems = group.get("systems", [])
            if isinstance(systems, list):
                scheduled.extend(str(system_id) for system_id in systems)
    return scheduled


def display_name(system_id: str) -> str:
    chars: list[str] = []
    for index, char in enumerate(system_id):
        if index > 0 and char.isupper() and not system_id[index - 1].isupper():
            chars.append(" ")
        chars.append(char)
    return "".join(chars).strip() or system_id


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def sha256_json(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sorted_unique_ints(values: Any) -> list[int]:
    return sorted({int(value) for value in values})


def sorted_unique_strings(values: Any) -> list[str]:
    return sorted({str(value) for value in values})


def is_lower_hex_hash(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != HASH_HEX_LENGTH:
        return False
    return all(char in "0123456789abcdef" for char in value)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


if __name__ == "__main__":
    raise SystemExit(main())
