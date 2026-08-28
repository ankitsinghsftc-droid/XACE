#!/usr/bin/env python3
"""Retained X10-030 proof: typed prompt batch -> GDE -> SGC -> runtime.

The proof uses only path-free structural operations, commits the seven Task 30
families atomically through the live Builder/GDE boundary, validates the
resulting CGS, compiles and persists a real SGC plan, runs the real runtime
twice, compares replay evidence, and restores the exact pre-commit CGS.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPT_SRC = REPO_ROOT / "packages" / "prompt-intelligence" / "src"
GDE_PACKAGE = REPO_ROOT / "packages" / "gde"
BUILDER_SERVER = REPO_ROOT / "packages" / "builder-workspace" / "server"
for location in (REPO_ROOT, PROMPT_SRC, PROMPT_SRC / "output_parser", GDE_PACKAGE, BUILDER_SERVER):
    resolved = str(location)
    if resolved not in sys.path:
        sys.path.insert(0, resolved)
for prompt_subdir in ('llm_orchestrator', 'context_assembler'):
    resolved = str(PROMPT_SRC / prompt_subdir)
    if resolved not in sys.path:
        sys.path.insert(0, resolved)

from packages.dcl.gameplay_primitives import (  # noqa: E402
    SIMULATION_INTERACTIVE_ENTITY_V1,
    build_primitive_cgs,
    committed_cgs_hash,
)
from typed_operations import (  # noqa: E402
    normalized_typed_operation_batch,
    parse_typed_operation_batch,
    typed_operation_batch_json_schema,
)
from structured_output_parser import StructuredOutputParser  # noqa: E402
from src.gde_orchestrator import GDEOrchestrator  # noqa: E402
from src.domain_dsl.mutation_metadata.mutation_metadata_model import (  # noqa: E402
    MutationMetadata,
)
from session_manager import _apply_via_gde, _pending_transaction_block_reason  # noqa: E402
from cgs_schema_validate import ValidationResult, validate_cgs  # noqa: E402
import sgc_runtime_proof as runtime_proof  # noqa: E402


DEFAULT_RUNTIME_BIN = REPO_ROOT / "target-codex-task29-primitives" / "debug" / "xace_runtime.exe"
DEFAULT_SGC_BIN = REPO_ROOT / "target-codex-task29-primitives" / "debug" / "xace-system-graph-compiler.exe"
DEFAULT_ARTIFACT_DIR = REPO_ROOT / "target-codex-task30-typed-operations" / "artifacts"
DEFAULT_OUTPUT = REPO_ROOT / "target-codex-task30-typed-operations" / "report.json"
EXPECTED_KINDS = (
    "declare_component",
    "add_component",
    "set_defaults",
    "add_system",
    "add_event",
    "add_rule",
    "add_asset",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prove typed prompt CGS operations end to end.")
    parser.add_argument("--runtime-bin", default=str(DEFAULT_RUNTIME_BIN))
    parser.add_argument("--sgc-bin", default=str(DEFAULT_SGC_BIN))
    parser.add_argument("--artifact-dir", default=str(DEFAULT_ARTIFACT_DIR))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--ticks", type=int, default=4)
    parser.add_argument("--world-seed", type=int, default=30)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = run_check(
            runtime_bin=Path(args.runtime_bin).resolve(),
            sgc_bin=Path(args.sgc_bin).resolve(),
            artifact_dir=Path(args.artifact_dir).resolve(),
            ticks=args.ticks,
            world_seed=args.world_seed,
        )
        runtime_proof.write_json(Path(args.output).resolve(), report)
    except Exception as exc:  # noqa: BLE001 - emit the first actionable proof failure.
        print(f"typed CGS operation proof failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True) if args.json else json.dumps(report, indent=2, sort_keys=True))
    return 0


def run_check(
    *,
    runtime_bin: Path,
    sgc_bin: Path,
    artifact_dir: Path,
    ticks: int,
    world_seed: int,
) -> dict[str, Any]:
    runtime_proof.require(runtime_bin.is_file(), f"runtime binary not found: {runtime_bin}")
    runtime_proof.require(sgc_bin.is_file(), f"SGC binary not found: {sgc_bin}")
    runtime_proof.require(ticks > 0, "ticks must be positive")
    artifact_dir.mkdir(parents=True, exist_ok=True)

    base_cgs = _base_cgs()
    base_hash = base_cgs["metadata"]["cgs_hash"]
    base_canonical = _canonical(base_cgs)
    batch_wire = _typed_batch()
    runtime_proof.write_json(artifact_dir / "base.cgs.json", base_cgs)
    runtime_proof.write_json(artifact_dir / "provider_typed_batch.json", batch_wire)

    provider_schema = typed_operation_batch_json_schema()
    provider_schema_proof = _inspect_provider_schema(provider_schema)
    runtime_proof.require(
        provider_schema_proof["openai_strict_compatible"],
        "; ".join(provider_schema_proof["errors"]),
    )
    runtime_proof.require(
        provider_schema_proof["path_free"],
        "provider structural schema exposes path/op patch fields",
    )

    parsed_batch = parse_typed_operation_batch(batch_wire)
    normalized_batch = normalized_typed_operation_batch(parsed_batch)
    canonical = StructuredOutputParser().parse_typed(
        json.dumps(normalized_batch, sort_keys=True), base_cgs
    )
    runtime_proof.require(canonical.is_fully_valid, "; ".join(canonical.validation.errors))
    runtime_proof.require(
        tuple(operation["kind"] for operation in normalized_batch["operations"]) == EXPECTED_KINDS,
        "typed batch does not cover all seven Task 30 operation families in order",
    )
    runtime_proof.require(
        all("path" not in operation and "op" not in operation for operation in normalized_batch["operations"]),
        "typed provider operations contain legacy path/op fields",
    )
    runtime_proof.write_json(artifact_dir / "normalized_typed_batch.json", normalized_batch)
    runtime_proof.write_json(artifact_dir / "prompt_proposed.cgs.json", canonical.proposed_cgs)

    transaction = {
        "operation_format": "typed_cgs_v1",
        "typed_operation_batch": normalized_batch,
        "operations": [],
        "schema_delta_type": "structural_add",
        "confidence_score": 0.99,
        "risk_level": "medium",
        "required_recompile": True,
        "affected_systems": ["MovementSystem"],
        "mutation_summary": normalized_batch["summary"],
        "source": "prompt",
        "parent_cgs_hash": base_hash,
        "cgs_hash": base_hash,
        "version_ids": {"cgs_hash": base_hash, "schema_version": "0.1.0"},
    }
    runtime_proof.require(
        _pending_transaction_block_reason(transaction) == "",
        "Builder rejected the valid typed transaction",
    )
    orchestrator = GDEOrchestrator(session_id="x10-030-proof")
    orchestrator.load_cgs(base_cgs)
    applied = _apply_via_gde(
        orchestrator, transaction, base_cgs, "x10-030-proof"
    )
    runtime_proof.require(applied.success, applied.error)
    committed = applied.new_cgs
    runtime_proof.require(isinstance(committed, dict), "GDE returned no committed CGS")
    _assert_committed_families(committed)
    runtime_proof.require(
        applied.snapshot.get("typed_operation_kinds") == list(EXPECTED_KINDS),
        "GDE snapshot lost typed operation provenance",
    )
    runtime_proof.write_json(artifact_dir / "committed.cgs.json", committed)

    validation = ValidationResult()
    validate_cgs(
        committed,
        validation,
        allow_legacy_hash=False,
        allow_draft_hash=False,
    )
    runtime_proof.require(validation.ok, "; ".join(validation.errors))

    project_root = artifact_dir / "runtime-project"
    cgs_path = project_root / "game.cgs.json"
    runtime_proof.write_json(cgs_path, committed)
    sgc_input = runtime_proof.sgc_input_from_cgs(committed)
    runtime_proof.write_json(artifact_dir / "sgc_input.json", sgc_input)
    sgc_result = runtime_proof.run_sgc(sgc_bin, sgc_input)
    plan = sgc_result["plan"]
    runtime_proof.validate_sgc_plan(plan, committed["metadata"]["cgs_hash"], sgc_input)
    persisted_plan, proof_metadata = runtime_proof.persist_sgc_plan(
        project_root=project_root,
        sgc_input=sgc_input,
        sgc_plan=plan,
    )
    runtime_proof.write_json(artifact_dir / "persisted_plan.json", persisted_plan)
    scheduled = runtime_proof.scheduled_system_ids_from_plan(persisted_plan)
    runtime_proof.require("MovementSystem" in scheduled, "MovementSystem was not scheduled")

    first_run = runtime_proof.run_runtime(
        runtime_bin=runtime_bin,
        cgs_path=cgs_path,
        report_path=artifact_dir / "first.schedule_report.json",
        stdout_path=artifact_dir / "first.runtime.stdout.txt",
        stderr_path=artifact_dir / "first.runtime.stderr.txt",
        ticks=ticks,
        world_seed=world_seed,
    )
    second_run = runtime_proof.run_runtime(
        runtime_bin=runtime_bin,
        cgs_path=cgs_path,
        report_path=artifact_dir / "second.schedule_report.json",
        stdout_path=artifact_dir / "second.runtime.stdout.txt",
        stderr_path=artifact_dir / "second.runtime.stderr.txt",
        ticks=ticks,
        world_seed=world_seed,
    )
    first_report = runtime_proof.read_runtime_report(
        first_run["report_path"], persisted_plan, ticks, world_seed
    )
    second_report = runtime_proof.read_runtime_report(
        second_run["report_path"], persisted_plan, ticks, world_seed
    )
    replay = runtime_proof.compare_replay_reports(first_report, second_report)

    orchestrator._cgs_manager.rollback_to_hash(base_hash, base_cgs)
    rollback_exact = (
        orchestrator.current_hash == base_hash
        and _canonical(orchestrator.current_cgs) == base_canonical
    )
    runtime_proof.require(rollback_exact, "rollback did not restore the exact pre-CGS")

    atomicity = _prove_mid_batch_failure(base_cgs, normalized_batch)
    assignment_adversarial = _prove_typed_assignment_rejection(
        base_cgs, normalized_batch
    )
    checks = {
        "provider_schema_is_path_free": True,
        "provider_schema_is_openai_strict_compatible": provider_schema_proof["openai_strict_compatible"],
        "prompt_parser_validated_all_families": canonical.is_fully_valid,
        "builder_typed_boundary_accepted": True,
        "gde_atomic_commit": applied.success,
        "standalone_cgs_validation": validation.ok,
        "real_sgc_binary_invoked": sgc_result["returncode"] == 0,
        "sgc_bound_to_committed_hash": persisted_plan["compiled_from_cgs_hash"] == committed["metadata"]["cgs_hash"],
        "movement_system_scheduled": "MovementSystem" in scheduled,
        "real_runtime_binary_invoked_twice": first_run["returncode"] == 0 and second_run["returncode"] == 0,
        "persisted_sgc_plan_loaded": first_report["plan_source"] == "persisted_sgc",
        "tick_hash_replay_match": replay["tick_hash_replay_match"],
        "schedule_replay_match": replay["schedule_replay_match"],
        "rollback_exact": rollback_exact,
        "mid_batch_failure_atomic": atomicity,
        "gde_rejects_mismatched_numeric_assignment_atomically": assignment_adversarial["mismatched_numeric_type"]["passed"],
        "gde_rejects_negative_uint_assignment_atomically": assignment_adversarial["negative_uint"]["passed"],
    }
    complete = all(checks.values())
    runtime_proof.require(complete, "one or more X10-030 proof checks failed")
    report = {
        "schema": "xace.typed_cgs_operation_e2e_report.v1",
        "ok": complete,
        "x10_030_complete": complete,
        "operation_schema": normalized_batch["schema"],
        "operation_kinds": list(EXPECTED_KINDS),
        "operation_count": len(EXPECTED_KINDS),
        "base_cgs_hash": base_hash,
        "committed_cgs_hash": committed["metadata"]["cgs_hash"],
        "rolled_back_cgs_hash": orchestrator.current_hash,
        "typed_operation_batch_hash": applied.snapshot["typed_operation_batch_hash"],
        "plan_hash": persisted_plan["plan_hash"],
        "scheduled_system_ids": scheduled,
        "latest_world_hash": first_report["latest_world_hash"],
        "checks": checks,
        "provider_schema_proof": provider_schema_proof,
        "adversarial_assignment_proof": assignment_adversarial,
        "sgc_proof_metadata": proof_metadata,
        "artifacts": {
            "directory": str(artifact_dir),
            "base_cgs": str(artifact_dir / "base.cgs.json"),
            "typed_batch": str(artifact_dir / "normalized_typed_batch.json"),
            "committed_cgs": str(artifact_dir / "committed.cgs.json"),
            "persisted_plan": str(artifact_dir / "persisted_plan.json"),
            "first_runtime_report": first_run["report_path"],
            "second_runtime_report": second_run["report_path"],
        },
    }
    return report


def _base_cgs() -> dict[str, Any]:
    cgs = build_primitive_cgs(SIMULATION_INTERACTIVE_ENTITY_V1)
    cgs["global_systems"] = [
        system for system in cgs["global_systems"]
        if system.get("id") != "MovementSystem"
    ]
    cgs["metadata"]["cgs_hash"] = committed_cgs_hash(cgs)
    return cgs


def _typed_batch() -> dict[str, Any]:
    actor_id = "simulation_interactive_entity_v1_actor"
    return {
        "schema": "xace.typed_cgs_operation_batch.v1",
        "request_id": "request.x10-030-proof",
        "prompt_id": "prompt.x10-030-proof",
        "summary": "Add a typed stamina feature and registered movement system",
        "operations": [
            {
                "operation_id": "op.declare.stamina",
                "kind": "declare_component",
                "explanation": "Declare deterministic stamina state.",
                "component_type_id": 10000,
                "component_name": "COMP_STAMINA_V1",
                "version": "1.0.0",
                "fields": [
                    {"name": "current", "field_type": "int", "default": 100, "description": "Current stamina."},
                    {"name": "maximum", "field_type": "int", "default": 100, "description": "Maximum stamina."},
                ],
                "source": "generated",
            },
            {
                "operation_id": "op.attach.stamina",
                "kind": "add_component",
                "explanation": "Attach stamina to the simulation actor.",
                "mode_id": "default",
                "actor_id": actor_id,
                "component_type_id": 10000,
                "component_name": "COMP_STAMINA_V1",
                "defaults": [],
                "use_schema_defaults": True,
            },
            {
                "operation_id": "op.defaults.stamina",
                "kind": "set_defaults",
                "explanation": "Set the actor starting stamina.",
                "mode_id": "default",
                "actor_id": actor_id,
                "component_type_id": 10000,
                "assignments": [
                    {"field_name": "current", "field_type": "int", "value": 80}
                ],
            },
            {
                "operation_id": "op.system.movement",
                "kind": "add_system",
                "explanation": "Bind the registered movement executor.",
                "system_id": "MovementSystem",
                "phase": "Simulation",
                "reads": [1, 5],
                "writes": [1],
                "depends_on": ["InputSystem"],
                "implementation_ref": "builtin.MovementSystem.v1",
                "scope": "global",
                "mode_id": "",
                "version": "1.0.0",
                "deterministic": True,
                "parallel": False,
            },
            {
                "operation_id": "op.event.stamina",
                "kind": "add_event",
                "explanation": "Declare stamina depletion semantics.",
                "event_name": "stamina.depleted",
                "payload_fields": [
                    {"name": "actor_entity_id", "field_type": "entity_id", "required": True}
                ],
                "version": "1.0.0",
            },
            {
                "operation_id": "op.rule.stamina",
                "kind": "add_rule",
                "explanation": "Disable sprint at zero stamina.",
                "mode_id": "default",
                "rule_id": "rule.stamina.sprint",
                "condition": "stamina.current == 0",
                "effect": "movement.sprint = false",
                "priority": 10,
                "is_active": True,
            },
            {
                "operation_id": "op.asset.stamina",
                "kind": "add_asset",
                "explanation": "Create a placeholder stamina icon.",
                "asset_id": "asset.stamina.icon",
                "asset_type": "TEXTURE",
                "status": "PLACEHOLDER",
                "source": "",
            },
        ],
    }


def _assert_committed_families(cgs: dict[str, Any]) -> None:
    actor = cgs["modes"][0]["actors"][0]
    stamina = next(
        component for component in actor["components"]
        if component.get("type_id") == 10000
    )
    runtime_proof.require(stamina["defaults"] == {"current": 80, "maximum": 100}, "typed defaults mismatch")
    schema = next(item for item in cgs["component_schemas"] if item.get("type_id") == 10000)
    runtime_proof.require(schema.get("name") == "COMP_STAMINA_V1", "typed component schema missing")
    runtime_proof.require(isinstance(schema.get("fields"), list), "typed component fields were not retained")
    runtime_proof.require(any(item.get("id") == "MovementSystem" for item in cgs["global_systems"]), "typed system missing")
    runtime_proof.require(any(item.get("name") == "stamina.depleted" for item in cgs["semantic_events"]), "typed event missing")
    runtime_proof.require(any(item.get("id") == "rule.stamina.sprint" for item in cgs["modes"][0]["rules"]), "typed rule missing")
    runtime_proof.require(any(item.get("id") == "asset.stamina.icon" for item in cgs["assets"]), "typed asset missing")


def _prove_mid_batch_failure(base_cgs: dict[str, Any], normalized_batch: dict[str, Any]) -> bool:
    bad_batch = copy.deepcopy(normalized_batch)
    bad_batch["operations"][-1]["asset_id"] = base_cgs["assets"][0]["id"]
    before = _canonical(base_cgs)
    before_hash = base_cgs["metadata"]["cgs_hash"]
    transaction = {
        "operation_format": "typed_cgs_v1",
        "typed_operation_batch": bad_batch,
        "operations": [],
        "schema_delta_type": "structural_add",
        "confidence_score": 0.99,
        "risk_level": "medium",
        "mutation_summary": "Atomic failure proof",
        "source": "prompt",
        "parent_cgs_hash": before_hash,
        "cgs_hash": before_hash,
    }
    runtime_proof.require(_pending_transaction_block_reason(transaction) == "", "bad live-reference batch failed before GDE")
    orchestrator = GDEOrchestrator(session_id="x10-030-atomicity")
    orchestrator.load_cgs(base_cgs)
    result = _apply_via_gde(orchestrator, transaction, base_cgs, "x10-030-atomicity")
    return (
        not result.success
        and orchestrator.current_hash == before_hash
        and _canonical(orchestrator.current_cgs) == before
    )


def _inspect_provider_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Statically prove the provider schema stays in the strict subset.

    OpenAI strict structured output requires every object to be closed and to
    list every property as required. The provider subset supports ``anyOf``
    for nested typed variants, but not ``oneOf``, ``uniqueItems``, or schema
    identity keywords. This walk also rejects the legacy structural
    ``path``/``op`` vocabulary anywhere in the schema.
    """

    errors: list[str] = []
    object_schema_count = 0
    any_of_count = 0
    path_free = True

    def visit(node: Any, location: str) -> None:
        nonlocal object_schema_count, any_of_count, path_free
        if isinstance(node, list):
            for index, item in enumerate(node):
                visit(item, f"{location}[{index}]")
            return
        if not isinstance(node, dict):
            return

        if "oneOf" in node:
            errors.append(f"{location} uses unsupported oneOf")
        if "uniqueItems" in node:
            errors.append(f"{location} uses unsupported uniqueItems")
        if "$id" in node:
            errors.append(f"{location} uses unsupported $id")
        if "anyOf" in node:
            any_of_count += 1
            variants = node["anyOf"]
            if not isinstance(variants, list) or not variants:
                errors.append(f"{location}.anyOf must be a non-empty array")

        properties = node.get("properties")
        if isinstance(properties, dict) and ({"path", "op"} & set(properties)):
            path_free = False
        if node.get("type") == "object":
            object_schema_count += 1
            if not isinstance(properties, dict):
                errors.append(f"{location} object schema has no properties object")
            else:
                required = node.get("required")
                if not isinstance(required, list):
                    errors.append(f"{location} object schema has no required array")
                elif (
                    len(required) != len(set(required))
                    or set(required) != set(properties)
                ):
                    errors.append(
                        f"{location} required keys do not exactly match properties"
                    )
            if node.get("additionalProperties") is not False:
                errors.append(f"{location} object schema is not closed")

        for key, value in node.items():
            visit(value, f"{location}.{key}")

    visit(schema, "schema")
    if object_schema_count == 0:
        errors.append("provider schema contains no object schemas")
    if any_of_count == 0:
        errors.append("provider schema contains no nested anyOf variants")
    return {
        "openai_strict_compatible": not errors,
        "path_free": path_free,
        "object_schema_count": object_schema_count,
        "any_of_count": any_of_count,
        "errors": errors,
    }


def _prove_typed_assignment_rejection(
    base_cgs: dict[str, Any],
    normalized_batch: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Exercise the GDE boundary with exact-type and unsigned violations."""

    cases = {
        "mismatched_numeric_type": ("entity_id", 80),
        "negative_uint": ("uint", -1),
    }
    proof: dict[str, dict[str, Any]] = {}
    for case_name, (assignment_type, assignment_value) in cases.items():
        bad_batch = copy.deepcopy(normalized_batch)
        declaration = bad_batch["operations"][0]
        declaration["fields"][0]["field_type"] = "uint"
        assignment = bad_batch["operations"][2]["assignments"][0]
        assignment["field_type"] = assignment_type
        assignment["value"] = assignment_value

        before = _canonical(base_cgs)
        before_hash = base_cgs["metadata"]["cgs_hash"]
        orchestrator = GDEOrchestrator(session_id=f"x10-030-{case_name}")
        orchestrator.load_cgs(base_cgs)
        metadata = MutationMetadata.create(
            source="prompt",
            parent_cgs_hash=before_hash,
            schema_version_target=base_cgs["metadata"].get("version", "0.1.0"),
            session_id=f"x10-030-{case_name}",
            confidence=0.99,
            description="Reject an adversarial typed default assignment",
            risk_level="medium",
        )
        result = orchestrator.process_typed_operation_batch(bad_batch, metadata)
        rejected_at_gde = (
            not result.success
            and result.code == "GDE_TYPED_OPERATION_INVALID"
            and result.error.startswith("Typed CGS operation batch rejected:")
        )
        exact_base_unchanged = (
            orchestrator.current_hash == before_hash
            and _canonical(orchestrator.current_cgs) == before
        )
        proof[case_name] = {
            "passed": rejected_at_gde and exact_base_unchanged,
            "rejected_at_gde": rejected_at_gde,
            "exact_base_cgs_unchanged": exact_base_unchanged,
            "error": result.error,
        }
    return proof


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


if __name__ == "__main__":
    raise SystemExit(main())
