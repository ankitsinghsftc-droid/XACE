"""
Production-shaped integration checks for the real SGC CLI.

This invokes the compiled xace-system-graph-compiler executable through
stdin/stdout, not the Rust library API and not a fake wiring helper.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = REPO_ROOT / "packages" / "builder-workspace" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from sgc_plan_validator import validate_sgc_plan_for_runtime_load  # noqa: E402


CGS_HASH = "c" * 64
SCHEMA_VERSION = "0.1.0"
BENCHMARK_THRESHOLD_MS = 1000.0


def default_sgc_binary() -> Path:
    exe_name = "xace-system-graph-compiler.exe" if os.name == "nt" else "xace-system-graph-compiler"
    return REPO_ROOT / "target-codex-production-sgc-build" / "debug" / exe_name


def system(
    system_id: str,
    *,
    phase: str = "Simulation",
    reads: list[int] | None = None,
    writes: list[int] | None = None,
    depends_on: list[str] | None = None,
    deterministic: bool = True,
) -> dict[str, Any]:
    return {
        "id": system_id,
        "display_name": system_id,
        "phase": phase,
        "reads": list(reads or []),
        "writes": list(writes or []),
        "depends_on": list(depends_on or []),
        "deterministic": deterministic,
        "version": {"major": 1, "minor": 0},
        "description": "",
    }


def generated_systems(count: int) -> list[dict[str, Any]]:
    systems = []
    for index in range(count):
        systems.append(
            system(
                f"GeneratedSystem{index:03d}",
                reads=[1000 + index],
                writes=[2000 + index],
                depends_on=[f"GeneratedSystem{index - 1:03d}"] if index else [],
            )
        )
    return systems


def payload(systems: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": "xace.sgc.cli.input.v1",
        "schema_version": SCHEMA_VERSION,
        "plan_version": 1,
        "cgs_hash": CGS_HASH,
        "systems": systems,
    }


def cgs_for(systems: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "version": SCHEMA_VERSION,
            "cgs_hash": CGS_HASH,
        },
        "global_systems": [],
        "modes": [
            {
                "id": "mode_test",
                "is_default": True,
                "actors": [],
                "systems": systems,
            }
        ],
    }


def run_cli(sgc_bin: Path, systems: list[dict[str, Any]]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(sgc_bin)],
        cwd=str(REPO_ROOT),
        input=json.dumps(payload(systems), sort_keys=True),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=30,
    )


def compile_plan(sgc_bin: Path, systems: list[dict[str, Any]]) -> dict[str, Any]:
    completed = run_cli(sgc_bin, systems)
    if completed.returncode != 0:
        raise RuntimeError(
            f"SGC failed with exit {completed.returncode}:\n"
            f"stderr={completed.stderr[-2000:]}\nstdout={completed.stdout[-1000:]}"
        )
    plan = json.loads(completed.stdout)
    report = validate_sgc_plan_for_runtime_load(cgs_for(systems), completed.stdout)
    require(report["ok"] is True, "runtime-load validation did not pass")
    require(report["rollback_compatible"] is True, "rollback compatibility did not pass")
    return plan


def expect_error(
    sgc_bin: Path,
    systems: list[dict[str, Any]],
    *,
    exit_code: int,
    code: str,
) -> dict[str, Any]:
    completed = run_cli(sgc_bin, systems)
    require(completed.returncode == exit_code, f"expected exit {exit_code}, got {completed.returncode}")
    require(not completed.stdout.strip(), "error path must not write stdout")
    error = json.loads(completed.stderr)
    require(error.get("schema") == "xace.sgc.cli.error.v1", "error schema mismatch")
    require(error.get("code") == code, f"expected {code}, got {error.get('code')}")
    require(error.get("exit_code") == exit_code, "error exit_code mismatch")
    return error


def assert_compile_success(sgc_bin: Path) -> dict[str, Any]:
    systems = [
        system("InputSystem", phase="Input", reads=[1], writes=[2]),
        system("MovementSystem", reads=[2], writes=[3], depends_on=["InputSystem"]),
    ]
    plan = compile_plan(sgc_bin, systems)
    require(plan["all_system_ids"] == ["InputSystem", "MovementSystem"], "success plan system IDs mismatch")
    return {"plan_hash": plan["plan_hash"], "systems": plan["all_system_ids"]}


def assert_compile_failure(sgc_bin: Path) -> dict[str, Any]:
    return expect_error(
        sgc_bin,
        [system("BadPhaseSystem", phase="BadPhase")],
        exit_code=1,
        code="INVALID_PHASE",
    )


def assert_20_generated_systems(sgc_bin: Path) -> dict[str, Any]:
    systems = generated_systems(20)
    plan = compile_plan(sgc_bin, systems)
    require(len(plan["all_system_ids"]) == 20, "20-system plan did not contain 20 systems")
    return {"system_count": len(plan["all_system_ids"]), "plan_hash": plan["plan_hash"]}


def assert_cycle(sgc_bin: Path) -> dict[str, Any]:
    systems = [
        system("CycleA", depends_on=["CycleB"]),
        system("CycleB", depends_on=["CycleA"]),
    ]
    return expect_error(sgc_bin, systems, exit_code=2, code="CYCLE_DETECTED")


def assert_unknown_dependency(sgc_bin: Path) -> dict[str, Any]:
    systems = [system("NeedsGhost", depends_on=["GhostSystem"])]
    return expect_error(sgc_bin, systems, exit_code=1, code="INVALID_SYSTEM_DEFINITION")


def assert_conflict_serializes(sgc_bin: Path) -> dict[str, Any]:
    systems = [
        system("ConflictA", writes=[42]),
        system("ConflictB", writes=[42]),
    ]
    plan = compile_plan(sgc_bin, systems)
    parallel_groups_with_conflict = []
    for phase in plan.get("phases", {}).values():
        for group in phase.get("groups", []):
            if group.get("parallel") and {"ConflictA", "ConflictB"}.issubset(set(group.get("systems", []))):
                parallel_groups_with_conflict.append(group.get("group_id"))
    require(not parallel_groups_with_conflict, "conflicting writers were scheduled in one parallel group")
    return {"plan_hash": plan["plan_hash"], "parallel_conflict_groups": parallel_groups_with_conflict}


def assert_runtime_load_contract(sgc_bin: Path) -> dict[str, Any]:
    systems = generated_systems(5)
    plan = compile_plan(sgc_bin, systems)
    report = validate_sgc_plan_for_runtime_load(cgs_for(systems), json.dumps(plan, sort_keys=True))
    require(report["load_ready"] is True, "plan did not pass runtime-load contract")
    require(report["runtime_load_status"] == "strict_loader_ready", "runtime load status mismatch")
    return report


def assert_adapter_compat(plan: dict[str, Any]) -> dict[str, Any]:
    require(isinstance(plan.get("plan_version"), int) and plan["plan_version"] >= 1, "missing adapter plan_version")
    require(isinstance(plan.get("schema_version"), str) and plan["schema_version"], "missing adapter schema_version")
    require(plan.get("compiled_from_cgs_hash") == CGS_HASH, "adapter cgs_hash mismatch")
    require(isinstance(plan.get("plan_hash"), str) and len(plan["plan_hash"]) == 64, "adapter plan_hash mismatch")
    return {
        "schema_version": plan["schema_version"],
        "plan_version": plan["plan_version"],
        "cgs_hash": plan["compiled_from_cgs_hash"],
    }


def benchmark_100_systems(sgc_bin: Path, repeats: int, threshold_ms: float) -> dict[str, Any]:
    systems = generated_systems(100)
    compile_plan(sgc_bin, systems)
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        compile_plan(sgc_bin, systems)
        samples.append((time.perf_counter() - start) * 1000.0)
    average_ms = sum(samples) / len(samples)
    max_ms = max(samples)
    require(
        average_ms <= threshold_ms,
        f"100-system SGC compile average {average_ms:.2f}ms exceeds threshold {threshold_ms:.2f}ms",
    )
    return {
        "system_count": 100,
        "repeats": repeats,
        "threshold_ms": threshold_ms,
        "average_ms": average_ms,
        "max_ms": max_ms,
        "samples_ms": samples,
    }


def run_all(sgc_bin: Path, repeats: int, threshold_ms: float) -> dict[str, Any]:
    require(sgc_bin.exists(), f"SGC binary not found: {sgc_bin}")
    success = assert_compile_success(sgc_bin)
    return {
        "ok": True,
        "sgc_bin": str(sgc_bin),
        "compile_success": success,
        "compile_failure": {
            "code": assert_compile_failure(sgc_bin)["code"],
        },
        "generated_20_systems": assert_20_generated_systems(sgc_bin),
        "cycle": {
            "code": assert_cycle(sgc_bin)["code"],
        },
        "unknown_dependency": {
            "code": assert_unknown_dependency(sgc_bin)["code"],
        },
        "conflict": assert_conflict_serializes(sgc_bin),
        "runtime_load_contract": assert_runtime_load_contract(sgc_bin),
        "adapter_compat": assert_adapter_compat(compile_plan(sgc_bin, generated_systems(3))),
        "benchmark_100_systems": benchmark_100_systems(sgc_bin, repeats, threshold_ms),
    }


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run SGC CLI integration tests and 100-system benchmark.")
    parser.add_argument("--sgc-bin", default=str(default_sgc_binary()))
    parser.add_argument("--benchmark-repeats", type=int, default=5)
    parser.add_argument("--benchmark-threshold-ms", type=float, default=BENCHMARK_THRESHOLD_MS)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        summary = run_all(Path(args.sgc_bin).resolve(), args.benchmark_repeats, args.benchmark_threshold_ms)
    except Exception as exc:  # noqa: BLE001 - integration tool should report the first actionable failure.
        print(f"SGC CLI integration failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(summary, sort_keys=True))
    else:
        print(json.dumps(summary, indent=2, sort_keys=True))
        print("SGC CLI integration PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
