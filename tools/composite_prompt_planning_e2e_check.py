#!/usr/bin/env python3
"""Retained X10-032 proof: composite prompt plan -> preview/apply/rollback.

The provider still emits only the closed typed-operation batch.  Local trusted
code derives the composite dependency graph, ordered facets, save/network
plans, and rollback plan, then Builder/GDE carry the same proof through preview,
atomic apply, real SGC, persisted-runtime replay, and exact rollback.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPT_SRC = REPO_ROOT / "packages" / "prompt-intelligence" / "src"
GDE_PACKAGE = REPO_ROOT / "packages" / "gde"
BUILDER_SERVER = REPO_ROOT / "packages" / "builder-workspace" / "server"
TOOLS_DIR = REPO_ROOT / "tools"
for location in (
    REPO_ROOT,
    PROMPT_SRC,
    PROMPT_SRC / "output_parser",
    GDE_PACKAGE,
    BUILDER_SERVER,
    TOOLS_DIR,
):
    resolved = str(location)
    if resolved not in sys.path:
        sys.path.insert(0, resolved)
for prompt_subdir in ("llm_orchestrator", "context_assembler"):
    resolved = str(PROMPT_SRC / prompt_subdir)
    if resolved not in sys.path:
        sys.path.insert(0, resolved)

from packages.dcl.gameplay_primitives import (  # noqa: E402
    PLATFORMER_KINEMATIC_MOVEMENT_V1,
    build_primitive_cgs,
    committed_cgs_hash,
)
from structured_output_parser import StructuredOutputParser  # noqa: E402
from typed_operations import (  # noqa: E402
    build_composite_prompt_plan,
    composite_plan_has_required_facets,
    normalized_typed_operation_batch,
    parse_typed_operation_batch,
    validate_composite_prompt_plan,
)
from src.domain_dsl.mutation_metadata.mutation_metadata_model import (  # noqa: E402
    MutationMetadata,
)
from src.gde_orchestrator import GDEOrchestrator  # noqa: E402
from session_manager import (  # noqa: E402
    _build_prompt_diff_preview,
    _pending_transaction_block_reason,
)
from cgs_schema_validate import ValidationResult, validate_cgs  # noqa: E402
import sgc_runtime_proof as runtime_proof  # noqa: E402


DEFAULT_RUNTIME_BIN = (
    REPO_ROOT
    / "target-codex-task29-primitives"
    / "debug"
    / "xace_runtime.exe"
)
DEFAULT_SGC_BIN = (
    REPO_ROOT
    / "target-codex-task29-primitives"
    / "debug"
    / "xace-system-graph-compiler.exe"
)
DEFAULT_ROOT = REPO_ROOT / "target-codex-task32-composite-planning"
DEFAULT_ARTIFACT_DIR = DEFAULT_ROOT / "artifacts"
DEFAULT_OUTPUT = DEFAULT_ROOT / "report.json"
SYSTEM_IDS = (
    "MovementIntentSystem",
    "PlatformerMotionSystem",
    "MovementSystem",
)
ACTOR_ID = "platformer_kinematic_movement_v1_actor"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prove composite prompt planning end to end."
    )
    parser.add_argument("--runtime-bin", default=str(DEFAULT_RUNTIME_BIN))
    parser.add_argument("--sgc-bin", default=str(DEFAULT_SGC_BIN))
    parser.add_argument("--artifact-dir", default=str(DEFAULT_ARTIFACT_DIR))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--ticks", type=int, default=4)
    parser.add_argument("--world-seed", type=int, default=32)
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
    except Exception as exc:  # noqa: BLE001 - retained proof emits actionable failure.
        print(f"composite prompt planning proof failed: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(report, sort_keys=True)
        if args.json
        else json.dumps(report, indent=2, sort_keys=True)
    )
    return 0


def run_check(
    *,
    runtime_bin: Path,
    sgc_bin: Path,
    artifact_dir: Path,
    ticks: int,
    world_seed: int,
) -> dict[str, Any]:
    runtime_proof.require(
        runtime_bin.is_file(), f"runtime binary not found: {runtime_bin}"
    )
    runtime_proof.require(sgc_bin.is_file(), f"SGC binary not found: {sgc_bin}")
    runtime_proof.require(ticks > 1, "ticks must be greater than one")
    artifact_dir.mkdir(parents=True, exist_ok=True)

    base_cgs = _base_cgs()
    base_hash = base_cgs["metadata"]["cgs_hash"]
    base_canonical = _canonical(base_cgs)
    provider_batch = _provider_batch()
    runtime_proof.write_json(artifact_dir / "base.cgs.json", base_cgs)
    runtime_proof.write_json(artifact_dir / "provider_composite_batch.json", provider_batch)

    parsed = parse_typed_operation_batch(provider_batch)
    normalized = normalized_typed_operation_batch(parsed)
    canonical = StructuredOutputParser().parse_typed(
        json.dumps(normalized, ensure_ascii=True, sort_keys=True),
        base_cgs,
    )
    runtime_proof.require(
        canonical.is_fully_valid,
        "; ".join(canonical.validation.errors),
    )
    composite = canonical.composite_plan
    runtime_proof.require(composite is not None, "parser did not derive a composite plan")
    composite_plan = composite.to_dict()
    runtime_proof.require(
        validate_composite_prompt_plan(composite_plan, canonical.batch).valid,
        "derived composite plan does not validate against its typed batch",
    )
    runtime_proof.require(
        composite_plan_has_required_facets(composite_plan),
        "derived composite plan lacks schema/system/asset/save/network facets",
    )
    runtime_proof.require(
        composite_plan["rollback_plan"]["pre_cgs_hash"] == base_hash,
        "rollback plan is not bound to the pre-apply CGS hash",
    )
    runtime_proof.write_json(artifact_dir / "normalized_composite_batch.json", normalized)
    runtime_proof.write_json(artifact_dir / "composite_prompt_plan.json", composite_plan)
    runtime_proof.write_json(artifact_dir / "prompt_proposed.cgs.json", canonical.proposed_cgs)

    transaction = _transaction(normalized, composite_plan, base_hash)
    runtime_proof.require(
        _pending_transaction_block_reason(transaction) == "",
        "Builder rejected a valid composite typed transaction",
    )
    preview = _preview(transaction, base_cgs, base_hash)
    runtime_proof.require(
        preview["composite_prompt_plan"].get("plan_hash") == composite_plan["plan_hash"],
        "Builder preview did not preserve the composite plan hash",
    )
    runtime_proof.require(
        preview["save_diff"]["operation_count"] > 0
        and preview["network_diff"]["operation_count"] > 0,
        "Builder preview did not expose save/network composite facets",
    )
    runtime_proof.write_json(artifact_dir / "builder_preview.json", preview)

    orchestrator = GDEOrchestrator(session_id="x10-032-proof")
    orchestrator.load_cgs(base_cgs)
    commit = orchestrator.process_typed_operation_batch(
        normalized,
        _metadata(orchestrator, "x10-032-proof"),
    )
    runtime_proof.require(commit.success, commit.error)
    committed = orchestrator.current_cgs
    committed_hash = orchestrator.current_hash
    runtime_proof.require(isinstance(committed, dict), "GDE returned no committed CGS")
    _assert_committed_composite(committed)
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
    runtime_proof.validate_sgc_plan(plan, committed_hash, sgc_input)
    persisted_plan, sgc_proof_metadata = runtime_proof.persist_sgc_plan(
        project_root=project_root,
        sgc_input=sgc_input,
        sgc_plan=plan,
    )
    runtime_proof.write_json(artifact_dir / "persisted_plan.json", persisted_plan)
    scheduled = runtime_proof.scheduled_system_ids_from_plan(persisted_plan)
    runtime_proof.require(
        all(system_id in scheduled for system_id in SYSTEM_IDS),
        "real SGC did not schedule every composite system",
    )

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

    tampered_plan_rejection = _prove_tampered_plan_rejection(transaction)
    mid_batch_atomicity = _prove_mid_batch_failure(base_cgs, normalized, composite_plan)

    orchestrator._cgs_manager.rollback_to_hash(base_hash, base_cgs)
    rollback_exact = (
        orchestrator.current_hash == base_hash
        and _canonical(orchestrator.current_cgs) == base_canonical
    )
    runtime_proof.require(rollback_exact, "rollback did not restore exact pre-CGS")

    checks = {
        "composite_plan_validates_against_batch": True,
        "composite_plan_has_required_facets": composite_plan_has_required_facets(composite_plan),
        "dependency_graph_is_acyclic": composite_plan["dependency_graph"]["acyclic"] is True,
        "dependency_graph_orders_all_operations": composite_plan["dependency_graph"]["topological_order"] == composite_plan["operation_order"],
        "rollback_plan_bound_to_pre_hash": composite_plan["rollback_plan"]["pre_cgs_hash"] == base_hash,
        "builder_preview_preserves_plan": preview["composite_prompt_plan"].get("plan_hash") == composite_plan["plan_hash"],
        "builder_preview_exposes_save_network": preview["save_diff"]["operation_count"] > 0 and preview["network_diff"]["operation_count"] > 0,
        "gde_atomic_commit": commit.success,
        "standalone_cgs_validation": validation.ok,
        "real_sgc_binary_invoked": sgc_result["returncode"] == 0,
        "all_composite_systems_scheduled": all(system_id in scheduled for system_id in SYSTEM_IDS),
        "real_runtime_binary_invoked_twice": first_run["returncode"] == 0 and second_run["returncode"] == 0,
        "tick_hash_replay_match": replay["tick_hash_replay_match"],
        "schedule_replay_match": replay["schedule_replay_match"],
        "tampered_plan_rejected_before_apply": tampered_plan_rejection,
        "mid_batch_failure_atomic": mid_batch_atomicity,
        "rollback_exact": rollback_exact,
    }
    complete = all(checks.values())
    runtime_proof.require(complete, "one or more X10-032 proof checks failed")

    return {
        "schema": "xace.composite_prompt_planning_e2e_report.v1",
        "ok": complete,
        "x10_032_complete": complete,
        "operation_schema": normalized["schema"],
        "operation_count": len(normalized["operations"]),
        "operation_kinds": [operation["kind"] for operation in normalized["operations"]],
        "base_cgs_hash": base_hash,
        "committed_cgs_hash": committed_hash,
        "rolled_back_cgs_hash": orchestrator.current_hash,
        "typed_operation_batch_hash": commit.typed_operation_batch_hash,
        "composite_plan_hash": composite_plan["plan_hash"],
        "composite_facets": composite_plan["facet_operations"],
        "post_commit_plan_hash": persisted_plan["plan_hash"],
        "scheduled_system_ids": scheduled,
        "latest_world_hash": first_report["latest_world_hash"],
        "checks": checks,
        "sgc_proof_metadata": sgc_proof_metadata,
        "artifacts": {
            "directory": str(artifact_dir),
            "provider_batch": str(artifact_dir / "provider_composite_batch.json"),
            "composite_plan": str(artifact_dir / "composite_prompt_plan.json"),
            "builder_preview": str(artifact_dir / "builder_preview.json"),
            "committed_cgs": str(artifact_dir / "committed.cgs.json"),
            "persisted_plan": str(artifact_dir / "persisted_plan.json"),
            "first_runtime_report": first_run["report_path"],
            "second_runtime_report": second_run["report_path"],
        },
    }


def _base_cgs() -> dict[str, Any]:
    cgs = build_primitive_cgs(PLATFORMER_KINEMATIC_MOVEMENT_V1)
    cgs["global_systems"] = []
    for schema in cgs.get("component_schemas", []):
        if isinstance(schema, dict) and isinstance(schema.get("defaults"), dict):
            schema["fields"] = _field_metadata(schema["defaults"])
    cgs["metadata"]["cgs_hash"] = committed_cgs_hash(cgs)
    return cgs


def _field_metadata(defaults: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": key,
            "field_type": _field_type(value),
            "default": copy.deepcopy(value),
            "description": f"Exact metadata for {key}.",
        }
        for key, value in sorted(defaults.items())
    ]


def _field_type(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        if all(isinstance(item, int) and not isinstance(item, bool) for item in value):
            return "int_list"
        return "string_list"
    return "object"


def _provider_batch() -> dict[str, Any]:
    return {
        "schema": "xace.typed_cgs_operation_batch.v1",
        "request_id": "request.x10-032-proof",
        "prompt_id": "prompt.x10-032-proof",
        "summary": "Add composite dash traversal with save and network policy.",
        "operations": [
            {
                "operation_id": "op.declare.dash_resource",
                "kind": "declare_component",
                "explanation": "Declare deterministic dash resource state.",
                "component_type_id": 10010,
                "component_name": "COMP_DASH_RESOURCE_V1",
                "version": "1.0.0",
                "fields": [
                    {"name": "charges", "field_type": "int", "default": 1, "description": "Available dash charges."},
                    {"name": "cooldown_ticks", "field_type": "uint", "default": 30, "description": "Dash cooldown."},
                ],
                "source": "generated",
            },
            {
                "operation_id": "op.attach.dash_resource",
                "kind": "add_component",
                "explanation": "Attach dash resource to the player.",
                "mode_id": "default",
                "actor_id": ACTOR_ID,
                "component_type_id": 10010,
                "component_name": "COMP_DASH_RESOURCE_V1",
                "defaults": [],
                "use_schema_defaults": True,
            },
            {
                "operation_id": "op.system.intent",
                "kind": "add_system",
                "explanation": "Bind movement intent execution.",
                "system_id": "MovementIntentSystem",
                "phase": "Input",
                "reads": [6, 120],
                "writes": [120],
                "depends_on": [],
                "implementation_ref": "builtin.MovementIntentSystem.v1",
                "scope": "global",
                "mode_id": "",
                "version": "1.0.0",
                "deterministic": True,
                "parallel": False,
            },
            {
                "operation_id": "op.system.platformer_motion",
                "kind": "add_system",
                "explanation": "Bind platformer motion execution.",
                "system_id": "PlatformerMotionSystem",
                "phase": "Simulation",
                "reads": [5, 120, 125],
                "writes": [5, 125],
                "depends_on": ["MovementIntentSystem"],
                "implementation_ref": "builtin.PlatformerMotionSystem.v1",
                "scope": "global",
                "mode_id": "",
                "version": "1.0.0",
                "deterministic": True,
                "parallel": False,
            },
            {
                "operation_id": "op.system.movement",
                "kind": "add_system",
                "explanation": "Bind final movement application.",
                "system_id": "MovementSystem",
                "phase": "Simulation",
                "reads": [1, 5],
                "writes": [1],
                "depends_on": ["PlatformerMotionSystem"],
                "implementation_ref": "builtin.MovementSystem.v1",
                "scope": "global",
                "mode_id": "",
                "version": "1.0.0",
                "deterministic": True,
                "parallel": False,
            },
            {
                "operation_id": "op.event.dash_started",
                "kind": "add_event",
                "explanation": "Declare dash start semantics.",
                "event_name": "movement.dash_started",
                "payload_fields": [
                    {"name": "actor_entity_id", "field_type": "entity_id", "required": True}
                ],
                "version": "1.0.0",
            },
            {
                "operation_id": "op.asset.dash_audio",
                "kind": "add_asset",
                "explanation": "Reserve deterministic dash feedback.",
                "asset_id": "x10_032_dash_audio_v1",
                "asset_type": "AUDIO_CLIP",
                "status": "PLACEHOLDER",
                "source": "",
            },
            {
                "operation_id": "op.save.persistence_layer",
                "kind": "set_defaults",
                "explanation": "Persist dash state in the session layer.",
                "mode_id": "default",
                "actor_id": ACTOR_ID,
                "component_type_id": 232,
                "assignments": [
                    {"field_name": "save_layer", "field_type": "string", "value": "Session"}
                ],
            },
            {
                "operation_id": "op.network.authority_policy",
                "kind": "set_defaults",
                "explanation": "Use owner-side prediction policy for dash.",
                "mode_id": "default",
                "actor_id": ACTOR_ID,
                "component_type_id": 10,
                "assignments": [
                    {"field_name": "authority_type", "field_type": "string", "value": "Owner"},
                    {"field_name": "replication_mode", "field_type": "string", "value": "Unreliable"},
                    {"field_name": "prediction_enabled", "field_type": "bool", "value": True},
                ],
            },
        ],
    }


def _transaction(
    normalized_batch: dict[str, Any],
    composite_plan: dict[str, Any],
    base_hash: str,
) -> dict[str, Any]:
    return {
        "operation_format": "typed_cgs_v1",
        "typed_operation_batch": normalized_batch,
        "composite_prompt_plan": composite_plan,
        "operations": [],
        "schema_delta_type": "structural_add",
        "confidence_score": 0.99,
        "risk_level": "medium",
        "required_recompile": True,
        "affected_systems": list(SYSTEM_IDS),
        "mutation_summary": normalized_batch["summary"],
        "source": "prompt",
        "parent_cgs_hash": base_hash,
        "cgs_hash": base_hash,
        "version_ids": {"cgs_hash": base_hash, "schema_version": "0.1.0"},
    }


def _preview(transaction: dict[str, Any], base_cgs: dict[str, Any], base_hash: str) -> dict[str, Any]:
    session = SimpleNamespace(
        session_id="x10-032-preview",
        runtime_connected=False,
        runtime_adapter_type="",
        runtime_last_hash=base_hash,
        runtime_last_tick=None,
    )
    result = {
        "kind": "mutation",
        "transaction": transaction,
        "confidence": 0.99,
        "cost_cents": 0.0,
        "tokens": 0,
    }
    return _build_prompt_diff_preview(
        session=session,
        prompt="add dash traversal with save and network policy",
        cgs=base_cgs,
        submitted_hash=base_hash,
        mode="ARCHITECT_MODE",
        result=result,
        readiness={"provider": "deterministic-test", "model": "x10-032"},
    )


def _metadata(orchestrator: GDEOrchestrator, session_id: str) -> MutationMetadata:
    return MutationMetadata.create(
        source="prompt",
        parent_cgs_hash=orchestrator.current_hash,
        schema_version_target="0.1.0",
        prompt_text="add dash traversal with save and network policy",
        confidence=0.99,
        description="Apply a composite prompt plan.",
        risk_level="medium",
        session_id=session_id,
    )


def _assert_committed_composite(cgs: dict[str, Any]) -> None:
    systems = {system.get("id") for system in cgs.get("global_systems", [])}
    runtime_proof.require(set(SYSTEM_IDS).issubset(systems), "committed CGS lost composite systems")
    actor = cgs["modes"][0]["actors"][0]
    components = {component.get("type_id"): component for component in actor["components"]}
    runtime_proof.require(10010 in components, "dash resource component missing")
    runtime_proof.require(
        components[232]["defaults"]["save_layer"] == "Session",
        "save policy default was not applied",
    )
    runtime_proof.require(
        components[10]["defaults"]["replication_mode"] == "Unreliable"
        and components[10]["defaults"]["prediction_enabled"] is True,
        "network policy defaults were not applied",
    )
    runtime_proof.require(
        any(asset.get("id") == "x10_032_dash_audio_v1" for asset in cgs.get("assets", [])),
        "composite asset placeholder missing",
    )


def _prove_tampered_plan_rejection(transaction: dict[str, Any]) -> bool:
    tampered = copy.deepcopy(transaction)
    tampered["composite_prompt_plan"]["operation_order"] = list(
        reversed(tampered["composite_prompt_plan"]["operation_order"])
    )
    reason = _pending_transaction_block_reason(tampered)
    return "Composite prompt plan is invalid" in reason


def _prove_mid_batch_failure(
    base_cgs: dict[str, Any],
    normalized_batch: dict[str, Any],
    composite_plan: dict[str, Any],
) -> bool:
    del composite_plan
    bad_batch = copy.deepcopy(normalized_batch)
    bad_batch["operations"][6]["asset_id"] = base_cgs["assets"][0]["id"]
    parsed = parse_typed_operation_batch(bad_batch)
    bad_plan = build_composite_prompt_plan(parsed, base_cgs).to_dict()
    bad_txn = _transaction(bad_batch, bad_plan, base_cgs["metadata"]["cgs_hash"])
    runtime_proof.require(
        _pending_transaction_block_reason(bad_txn) == "",
        "bad live-reference batch failed before GDE atomicity proof",
    )
    orchestrator = GDEOrchestrator(session_id="x10-032-atomicity")
    orchestrator.load_cgs(base_cgs)
    before_hash = orchestrator.current_hash
    before_canonical = _canonical(orchestrator.current_cgs)
    result = orchestrator.process_typed_operation_batch(
        bad_batch,
        _metadata(orchestrator, "x10-032-atomicity"),
    )
    return (
        not result.success
        and orchestrator.current_hash == before_hash
        and _canonical(orchestrator.current_cgs) == before_canonical
    )


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


if __name__ == "__main__":
    raise SystemExit(main())
