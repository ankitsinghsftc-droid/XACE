"""
Editor-free generated-system safe compile smoke.

This proves the Task 28/29 path:

    generated Rust source
    -> SystemSpec/runtime ABI validation
    -> unsupported generated-system rejection
    -> deterministic static checks
    -> cargo check sandbox
    -> real SGC compilation
    -> signed compile artifact
    -> runtime registration validation

The smoke also injects adversarial generated sources and verifies they are
blocked with exact reason codes before SGC compilation.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
CODEGEN_DIR = REPO_ROOT / "packages" / "prompt-intelligence" / "src" / "code_generation"
DEFAULT_RUNTIME_BIN = (
    REPO_ROOT
    / "target-codex-certify"
    / "debug"
    / ("xace_runtime.exe" if os.name == "nt" else "xace_runtime")
)
DEFAULT_SGC_BIN = (
    REPO_ROOT
    / "target-codex-certify"
    / "debug"
    / ("xace-system-graph-compiler.exe" if os.name == "nt" else "xace-system-graph-compiler")
)

if str(CODEGEN_DIR) not in sys.path:
    sys.path.insert(0, str(CODEGEN_DIR))

from generated_system_safe_compiler import (  # noqa: E402
    GeneratedSystemSafeCompiler,
    validate_compile_artifact_signature,
)


VALID_GENERATED_COUNTER_RUST = """\
use crate::{ISystem, SystemContext};

pub struct GeneratedCounterSystem {}

impl GeneratedCounterSystem {
    pub fn new() -> Self {
        Self {}
    }
}

impl ISystem for GeneratedCounterSystem {
    fn init(&mut self, ctx: &mut SystemContext) {
    }

    fn execute(&mut self, ctx: &mut SystemContext) {
        let mut entities = ctx.entities_with::<CompCounterV1>();
        entities.sort_by_key(|entity_id| *entity_id);
        for entity in entities {
            ctx.mutation_gate().apply_partial::<CompCounterV1, _>(entity, |counter| {
                counter.count += 1;
            }).ok();
        }
    }
}
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run generated-system safe compile smoke.")
    parser.add_argument("--runtime-bin", default=str(DEFAULT_RUNTIME_BIN))
    parser.add_argument("--sgc-bin", default=str(DEFAULT_SGC_BIN))
    parser.add_argument("--project-dir", default="")
    parser.add_argument("--keep-project", action="store_true")
    args = parser.parse_args(argv)

    runtime_bin = Path(args.runtime_bin).resolve()
    sgc_bin = Path(args.sgc_bin).resolve()
    _require(runtime_bin.exists(), f"runtime binary not found: {runtime_bin}")
    _require(sgc_bin.exists(), f"SGC binary not found: {sgc_bin}")

    cleanup = None
    if args.project_dir:
        project_root = Path(args.project_dir).resolve()
        project_root.mkdir(parents=True, exist_ok=True)
    else:
        cleanup = tempfile.TemporaryDirectory(prefix="xace-generated-safe-compile-")
        project_root = Path(cleanup.name)

    try:
        cgs = generated_counter_cgs()
        compiler = GeneratedSystemSafeCompiler(sgc_bin=sgc_bin)

        adversarial_rejections = run_adversarial_rejections(compiler, cgs)
        missing_rollback = copy.deepcopy(cgs)
        del missing_rollback["global_systems"][0]["runtime_executor"]["abi"]["rollback"]["event_hook"]
        rollback_blocked = compiler.compile(
            system_id="GeneratedCounterSystem",
            cgs=missing_rollback,
            rust_source=VALID_GENERATED_COUNTER_RUST,
        )
        _require(not rollback_blocked.succeeded, "missing rollback hook unexpectedly passed")
        _require(
            rollback_blocked.stage == "runtime_abi_validation",
            f"unexpected rollback blocked stage: {rollback_blocked.stage}",
        )
        _require("rollback.event_hook" in rollback_blocked.error, rollback_blocked.error)
        _require(rollback_blocked.sgc_result is None, "missing rollback hook reached SGC")
        adversarial_rejections["missing_rollback_hook"] = {
            "stage": rollback_blocked.stage,
            "reason": "runtime_executor.abi.rollback.event_hook",
        }

        result = compiler.compile(
            system_id="GeneratedCounterSystem",
            cgs=cgs,
            rust_source=VALID_GENERATED_COUNTER_RUST,
        )
        _require(result.succeeded, f"safe compile failed at {result.stage}: {result.error}")
        _require(result.compile_artifact, "safe compile did not produce an artifact")
        _require(
            validate_compile_artifact_signature(result.compile_artifact),
            "compile artifact signature failed local verification",
        )

        signed_cgs = copy.deepcopy(cgs)
        signed_cgs["global_systems"][0]["runtime_executor"] = result.signed_runtime_executor
        cgs_path = project_root / "game.cgs.json"
        cgs_path.write_text(json.dumps(signed_cgs, indent=2, sort_keys=True), encoding="utf-8")

        runtime = run_runtime(runtime_bin, cgs_path)
        summary = {
            "project": str(project_root),
            "cgs": str(cgs_path),
            "runtime_bin": str(runtime_bin),
            "sgc_bin": str(sgc_bin),
            "system_id": "GeneratedCounterSystem",
            "artifact_schema": result.compile_artifact["schema"],
            "source_hash": result.compile_artifact["source_hash"],
            "runtime_executor_hash": result.compile_artifact["runtime_executor_hash"],
            "abi_hash": result.compile_artifact["abi_hash"],
            "sgc_plan_hash": result.compile_artifact["sgc_plan_hash"],
            "signature": result.compile_artifact["signature"],
            "unsupported_policy_hash": result.compile_artifact["unsupported_policy_hash"],
            "adversarial_rejections": adversarial_rejections,
            "runtime": runtime,
        }
        print(json.dumps(summary, indent=2, sort_keys=True))
        print("generated system safe compile smoke PASSED")
        return 0
    finally:
        if cleanup is not None and not args.keep_project:
            cleanup.cleanup()


def run_adversarial_rejections(
    compiler: GeneratedSystemSafeCompiler,
    cgs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    cases = {
        "nondeterministic_random": (
            VALID_GENERATED_COUNTER_RUST + "\nlet roll = rand::random::<u32>();\n",
            "nondeterministic.random_source",
        ),
        "filesystem_access": (
            VALID_GENERATED_COUNTER_RUST.replace(
                "let mut entities = ctx.entities_with::<CompCounterV1>();",
                "let _secret = std::fs::read_to_string(\"secret.txt\");\n"
                "        let mut entities = ctx.entities_with::<CompCounterV1>();",
            ),
            "unsupported.filesystem_access",
        ),
        "network_access": (
            VALID_GENERATED_COUNTER_RUST.replace(
                "let mut entities = ctx.entities_with::<CompCounterV1>();",
                "let _socket = std::net::TcpStream::connect(\"127.0.0.1:1\");\n"
                "        let mut entities = ctx.entities_with::<CompCounterV1>();",
            ),
            "unsupported.network_access",
        ),
        "engine_only_api": (
            VALID_GENERATED_COUNTER_RUST.replace(
                "fn execute(&mut self, ctx: &mut SystemContext) {",
                "fn execute(&mut self, ctx: &mut SystemContext) {\n"
                "        let _node = godot::prelude::Node::new_alloc();",
            ),
            "unsupported.engine_api_godot",
        ),
    }

    rejected: dict[str, dict[str, Any]] = {}
    for name, (source, expected_code) in cases.items():
        result = compiler.compile(
            system_id="GeneratedCounterSystem",
            cgs=cgs,
            rust_source=source,
        )
        _require(not result.succeeded, f"{name} unexpectedly passed")
        _require(result.stage == "unsupported_api_rejection", f"{name} stage was {result.stage}")
        _require(result.sgc_result is None, f"{name} reached SGC")
        _require(result.unsupported_report is not None, f"{name} did not produce unsupported report")
        reason_codes = [finding.code for finding in result.unsupported_report.findings]
        _require(expected_code in reason_codes, f"{name} missing {expected_code}: {reason_codes}")
        rejected[name] = {
            "stage": result.stage,
            "reason_codes": reason_codes,
        }
    return rejected


def run_runtime(runtime_bin: Path, cgs_path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            str(runtime_bin),
            "--cgs",
            str(cgs_path),
            "--derive-cgs-plan",
            "--no-wait",
            "--no-control",
            "--ticks",
            "2",
            "--quiet",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    output = completed.stdout + completed.stderr
    _require(completed.returncode == 0, "runtime rejected signed generated system:\n" + output[-4000:])
    return {
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-1200:],
        "stderr_tail": completed.stderr[-1200:],
    }


def generated_counter_cgs() -> dict[str, Any]:
    return {
        "metadata": {
            "name": "Generated Safe Compile Smoke",
            "schema_version": "0.1.0",
            "version": "0.1.0",
            "cgs_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
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
            }
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
                    }
                ],
                "systems": [],
                "rules": [],
            }
        ],
    }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


if __name__ == "__main__":
    raise SystemExit(main())
