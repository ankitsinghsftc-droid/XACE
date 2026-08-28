#!/usr/bin/env python3
"""Compile and deterministic-replay every catalogued gameplay primitive."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import sgc_runtime_proof as sgc
from packages.dcl.gameplay_primitives import (
    GAMEPLAY_PRIMITIVES,
    GameplayPrimitive,
    REQUIRED_FACETS,
    TASK_REQUIRED_GENRES,
    build_primitive_cgs,
    covered_genres,
    remaining_genres,
    validate_catalog,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime-bin",
        default="target-codex-certify/debug/xace_runtime.exe",
        help="Path to the standalone runtime binary.",
    )
    parser.add_argument(
        "--sgc-bin",
        default="target-codex-certify/debug/xace-sgc.exe",
        help="Path to the real SGC CLI binary.",
    )
    parser.add_argument(
        "--output",
        default="target-codex-gameplay-primitives/gameplay_primitive_library_report.json",
    )
    parser.add_argument("--artifact-dir", default="target-codex-gameplay-primitives/artifacts")
    parser.add_argument("--ticks", type=int, default=4)
    parser.add_argument("--world-seed", type=int, default=29029)
    parser.add_argument("--require-full-catalog", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = (REPO_ROOT / args.output).resolve()
    artifact_dir = (REPO_ROOT / args.artifact_dir).resolve()
    try:
        report = run_check(args, artifact_dir)
    except Exception as exc:  # fail closed while retaining a machine-readable artifact
        report = {
            "schema": "xace.gameplay_primitive_library_check.v1",
            "ok": False,
            "error": str(exc),
            "primitives": [],
        }
    sgc.write_json(output, report)
    print(json.dumps(report, sort_keys=True if args.json else False, indent=None if args.json else 2))
    return 0 if report.get("ok") is True else 1


def run_check(args: argparse.Namespace, artifact_dir: Path) -> dict[str, Any]:
    sgc.require(args.ticks >= 2, "--ticks must be at least 2 for replay evidence")
    findings = validate_catalog()
    sgc.require(not findings, "catalog validation failed: " + "; ".join(findings))
    runtime_bin = (REPO_ROOT / args.runtime_bin).resolve()
    sgc_bin = (REPO_ROOT / args.sgc_bin).resolve()
    sgc.require(runtime_bin.is_file(), f"runtime binary does not exist: {runtime_bin}")
    sgc.require(sgc_bin.is_file(), f"SGC binary does not exist: {sgc_bin}")

    rows = [
        prove_primitive(
            primitive,
            artifact_dir / primitive.primitive_id.replace(".", "_"),
            runtime_bin,
            sgc_bin,
            args.ticks,
            args.world_seed + index,
        )
        for index, primitive in enumerate(GAMEPLAY_PRIMITIVES)
    ]
    covered = covered_genres()
    remaining = remaining_genres()
    complete = not remaining
    ok = all(row.get("ok") is True for row in rows)
    if args.require_full_catalog and not complete:
        ok = False
    return {
        "schema": "xace.gameplay_primitive_library_check.v1",
        "ok": ok,
        "x10_029_complete": complete,
        "require_full_catalog": bool(args.require_full_catalog),
        "required_facets": list(REQUIRED_FACETS),
        "required_genres": list(TASK_REQUIRED_GENRES),
        "covered_genres": list(covered),
        "remaining_genres": list(remaining),
        "primitive_count": len(rows),
        "primitives": rows,
    }


def validate_cgs_file(cgs_path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "cgs_schema_validate.py"),
            str(cgs_path),
            "--json",
        ],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "CGS schema validation failed with "
            f"{completed.returncode}: {completed.stdout[-3000:]} {completed.stderr[-1000:]}"
        )
    payload = json.loads(completed.stdout)
    sgc.require(payload.get("valid") is True, "CGS validator did not report valid=true")
    return payload


def prove_primitive(
    primitive: GameplayPrimitive,
    artifact_root: Path,
    runtime_bin: Path,
    sgc_bin: Path,
    ticks: int,
    world_seed: int,
) -> dict[str, Any]:
    project_root = artifact_root / "project"
    project_root.mkdir(parents=True, exist_ok=True)
    cgs_path = project_root / "game.cgs.json"
    cgs = build_primitive_cgs(primitive)
    sgc.write_json(cgs_path, cgs)
    schema_validation = validate_cgs_file(cgs_path)

    sgc_input = sgc.sgc_input_from_cgs(cgs)
    compiled = sgc.run_sgc(sgc_bin, sgc_input)
    plan = compiled["plan"]
    sgc.validate_sgc_plan(plan, cgs["metadata"]["cgs_hash"], sgc_input)
    persisted_plan, proof_metadata = sgc.persist_sgc_plan(project_root, sgc_input, plan)
    expected_systems = [system.system_id for system in primitive.systems]
    scheduled_systems = sgc.scheduled_system_ids_from_plan(persisted_plan)
    sgc.require(scheduled_systems == expected_systems, "SGC schedule does not match catalog order")

    first_launch = sgc.run_runtime(
        runtime_bin, cgs_path, artifact_root / "runtime_first.json",
        artifact_root / "runtime_first.stdout.txt",
        artifact_root / "runtime_first.stderr.txt", ticks, world_seed,
    )
    second_launch = sgc.run_runtime(
        runtime_bin, cgs_path, artifact_root / "runtime_second.json",
        artifact_root / "runtime_second.stdout.txt",
        artifact_root / "runtime_second.stderr.txt", ticks, world_seed,
    )
    first = sgc.read_runtime_report(
        first_launch["report_path"], persisted_plan, ticks, world_seed,
    )
    second = sgc.read_runtime_report(
        second_launch["report_path"], persisted_plan, ticks, world_seed,
    )
    replay = sgc.compare_replay_reports(first, second)
    unique_hashes = {record["world_hash"] for record in first["hash_log"]}
    sgc.require(len(unique_hashes) > 1, "runtime world did not advance across primitive ticks")

    facet_evidence = {
        "schema": {
            "component_type_ids": [component.type_id for component in primitive.components],
            "authoritative_cgs_hash": cgs["metadata"]["cgs_hash"],
        },
        "system": {
            "system_ids": expected_systems,
            "scheduled_system_ids": scheduled_systems,
        },
        "event": {
            "event_names": [event.name for event in primitive.events],
            "validated_binding_ids": [asset.binding_id for asset in primitive.assets],
        },
        "input": {"actions": [input_item.action for input_item in primitive.inputs]},
        "asset": {
            "asset_ids": [asset.asset_id for asset in primitive.assets],
            "binding_ids": [asset.binding_id for asset in primitive.assets],
        },
        "save": {
            "component_type_ids": list(primitive.save.component_type_ids),
            "strategy": primitive.save.strategy,
            "save_layer": primitive.save.save_layer,
        },
        "network": {
            "component_type_ids": list(primitive.network.component_type_ids),
            "authority": primitive.network.authority,
            "replication_mode": primitive.network.replication_mode,
            "prediction_enabled": primitive.network.prediction_enabled,
        },
    }
    return {
        "ok": True,
        "primitive_id": primitive.primitive_id,
        "version": primitive.version,
        "genres": list(primitive.genres),
        "facets": facet_evidence,
        "cgs": {
            "path": str(cgs_path),
            "hash": cgs["metadata"]["cgs_hash"],
            "schema_validation": schema_validation,
        },
        "sgc": {
            "plan_hash": persisted_plan["plan_hash"],
            "proof_metadata": proof_metadata,
            "scheduled_system_ids": scheduled_systems,
        },
        "runtime": {
            "ticks": ticks,
            "world_seed": world_seed,
            "plan_source": first["plan_source"],
            "first_latest_world_hash": first["latest_world_hash"],
            "second_latest_world_hash": second["latest_world_hash"],
            "unique_tick_hashes": len(unique_hashes),
            **replay,
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
