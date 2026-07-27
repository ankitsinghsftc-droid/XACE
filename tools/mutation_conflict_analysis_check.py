#!/usr/bin/env python3
"""
Task X10-018 adversarial static mutation conflict check.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
GDE_ROOT = REPO_ROOT / "packages" / "gde"
BUILDER_SERVER = REPO_ROOT / "packages" / "builder-workspace" / "server"
for path in (str(GDE_ROOT), str(REPO_ROOT / "packages"), str(BUILDER_SERVER)):
    if path not in sys.path:
        sys.path.insert(0, path)

from src.cgs.cgs_serializer import CGSSerializer  # noqa: E402
from src.consistency_validator.static_mutation_conflict_analyzer import (  # noqa: E402
    StaticMutationConflictAnalyzer,
)
from src.domain_dsl.mutation_metadata.mutation_metadata_model import MutationMetadata  # noqa: E402
from src.domain_dsl.transaction_model.transaction_builder import TransactionBuilder  # noqa: E402
from src.gde_orchestrator import GDEOrchestrator  # noqa: E402
from ws_message_router import _static_precommit_conflict_reason  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args()

    analyzer = StaticMutationConflictAnalyzer()
    cases = [
        _case_dependency_cycle(),
        _case_read_write_hazard(),
        _case_component_migration(),
        _case_runtime_abi_mismatch(),
    ]

    results: list[dict[str, Any]] = []
    for case in cases:
        report = analyzer.validate(case["proposed"], case["original"])
        codes = sorted({finding.code for finding in report.findings})
        _require(not report.is_valid, f"{case['name']} was not blocked")
        _require(case["expected_code"] in codes, f"{case['name']} missing {case['expected_code']}: {codes}")
        results.append({
            "name": case["name"],
            "blocked": True,
            "expected_code": case["expected_code"],
            "codes": codes,
        })

    gde_result = _run_gde_precommit_case()
    builder_result = _run_builder_prepersist_case()
    report = {
        "schema": "xace.static_mutation_conflict_analysis_check.v1",
        "ok": True,
        "adversarial_cases": results,
        "gde_precommit": gde_result,
        "builder_prepersist": builder_result,
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("static mutation conflict analysis check PASSED")
    return 0


def _run_gde_precommit_case() -> dict[str, Any]:
    cgs = _base_cgs()
    orchestrator = GDEOrchestrator(session_id="x10-018")
    orchestrator.load_cgs(cgs)
    old_hash = orchestrator.current_hash
    metadata = MutationMetadata.create(
        source="manual",
        parent_cgs_hash=old_hash,
        schema_version_target="0.1.0",
        description="adversarial conflicting system",
        session_id="x10-018",
    )
    txn = (
        TransactionBuilder(metadata)
        .add_system(
            "global_systems.sys_conflict",
            {
                "id": "sys_conflict",
                "phase": "Input",
                "reads": [5],
                "writes": [5],
                "depends_on": [],
                "deterministic": True,
            },
        )
        .build()
    )

    result = orchestrator.process_transaction(txn)
    current_hash = orchestrator.current_hash
    codes = []
    if result.consistency_report is not None:
        codes = sorted({finding.code for finding in result.consistency_report.static_findings})

    _require(not result.success, "GDE accepted a conflicting system transaction")
    _require(current_hash == old_hash, "GDE changed the authoritative hash after rejection")
    _require("STATIC_READ_WRITE_HAZARD" in codes, f"GDE missing static hazard code: {codes}")
    return {
        "blocked": True,
        "hash_unchanged": current_hash == old_hash,
        "codes": codes,
        "error": result.error,
    }


def _run_builder_prepersist_case() -> dict[str, Any]:
    original = _base_cgs()
    proposed = copy.deepcopy(original)
    proposed["global_systems"].append({
        "id": "sys_conflict",
        "phase": "Input",
        "reads": [5],
        "writes": [5],
        "depends_on": [],
        "deterministic": True,
    })
    reason = _static_precommit_conflict_reason(
        original,
        proposed,
        {"operations": [{"op": "ADD_SYSTEM", "path": "global_systems.sys_conflict"}]},
    )
    _require("StaticMutationConflict" in reason, f"Builder pre-persist helper did not block: {reason}")
    return {"blocked": True, "reason": reason}


def _case_dependency_cycle() -> dict[str, Any]:
    original = _base_cgs()
    proposed = copy.deepcopy(original)
    proposed["global_systems"] = [
        _system("sys_a", reads=[100], writes=[], depends_on=["sys_b"]),
        _system("sys_b", reads=[], writes=[100], depends_on=["sys_a"]),
    ]
    return {
        "name": "dependency_cycle",
        "original": original,
        "proposed": proposed,
        "expected_code": "STATIC_DEPENDENCY_CYCLE",
    }


def _case_read_write_hazard() -> dict[str, Any]:
    original = _base_cgs()
    proposed = copy.deepcopy(original)
    proposed["global_systems"] = [
        _system("sys_damage", reads=[100], writes=[100]),
        _system("sys_regen", reads=[100], writes=[100]),
    ]
    return {
        "name": "read_write_hazard",
        "original": original,
        "proposed": proposed,
        "expected_code": "STATIC_READ_WRITE_HAZARD",
    }


def _case_component_migration() -> dict[str, Any]:
    original = _base_cgs()
    original["component_schemas"] = [
        {"type_id": 300, "name": "COMP_COUNTER_V1", "defaults": {"count": 0}},
    ]
    original["global_systems"] = [_system("sys_counter", reads=[300], writes=[300])]
    proposed = copy.deepcopy(original)
    proposed["component_schemas"][0]["defaults"]["count"] = "zero"
    return {
        "name": "component_migration_type_change",
        "original": original,
        "proposed": proposed,
        "expected_code": "STATIC_COMPONENT_FIELD_TYPE_CHANGED",
    }


def _case_runtime_abi_mismatch() -> dict[str, Any]:
    original = _base_cgs()
    proposed = copy.deepcopy(original)
    proposed["component_schemas"] = [
        {"type_id": 301, "name": "COMP_LOOT_ROLL_V1", "defaults": {"enabled": True}},
    ]
    proposed["global_systems"] = [_generated_rng_system_with_bad_abi()]
    return {
        "name": "runtime_executor_abi_mismatch",
        "original": original,
        "proposed": proposed,
        "expected_code": "STATIC_RUNTIME_EXECUTOR_ABI_RNG_MISMATCH",
    }


def _base_cgs() -> dict[str, Any]:
    cgs = {
        "metadata": {
            "name": "Task 18 Static Conflict Check",
            "version": "0.1.0",
            "schema_version": "0.1.0",
            "cgs_hash": "",
        },
        "global_systems": [
            {
                "id": "sys_input",
                "phase": "Input",
                "reads": [6],
                "writes": [5],
                "depends_on": [],
                "deterministic": True,
            }
        ],
        "modes": [
            {
                "id": "mode_default",
                "display_name": "Default",
                "is_default": True,
                "schema_version": "0.1.0",
                "actors": [
                    {
                        "id": "actor_player",
                        "actor_type": "PLAYER",
                        "components": [
                            {
                                "type_id": 100,
                                "name": "COMP_HEALTH_V1",
                                "defaults": {"current": 80, "max": 100},
                            }
                        ],
                    }
                ],
                "systems": [],
                "rules": [],
            }
        ],
    }
    cgs["metadata"]["cgs_hash"] = CGSSerializer.compute_hash(_without_hash(cgs))
    return cgs


def _system(
    system_id: str,
    *,
    reads: list[int],
    writes: list[int],
    depends_on: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": system_id,
        "phase": "Simulation",
        "reads": reads,
        "writes": writes,
        "depends_on": list(depends_on or []),
        "deterministic": True,
    }


def _generated_rng_system_with_bad_abi() -> dict[str, Any]:
    return {
        "id": "GeneratedLootRollSystem",
        "phase": "Simulation",
        "reads": [301],
        "writes": [],
        "depends_on": [],
        "deterministic": True,
        "source": "generated",
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


def _without_hash(cgs: dict[str, Any]) -> dict[str, Any]:
    stripped = copy.deepcopy(cgs)
    stripped.get("metadata", {}).pop("cgs_hash", None)
    return stripped


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


if __name__ == "__main__":
    raise SystemExit(main())
