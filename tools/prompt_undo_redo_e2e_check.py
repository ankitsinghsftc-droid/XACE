#!/usr/bin/env python3
"""Retained X10-033 proof: prompt mutation history undo/redo.

The proof builds a 50-mutation prompt history from closed typed CGS operations,
persists a snapshot, ExecutionPlan, and SGC proof bundle for every state, then
walks the history backward and forward.  Each restore must keep CGS bytes,
persisted SGC plan hash, runtime world hash, and runtime hash-log replay
signature equal to the previously observed state signature.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import time
from pathlib import Path
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
    normalized_typed_operation_batch,
    parse_typed_operation_batch,
)
from src.domain_dsl.mutation_metadata.mutation_metadata_model import (  # noqa: E402
    MutationMetadata,
)
from src.gde_orchestrator import GDEOrchestrator  # noqa: E402
from cgs_persistence import CGSPersistence, SnapshotRecord  # noqa: E402
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
DEFAULT_ROOT = REPO_ROOT / "target-codex-task33-prompt-history"
DEFAULT_ARTIFACT_DIR = DEFAULT_ROOT / "artifacts"
DEFAULT_OUTPUT = DEFAULT_ROOT / "report.json"
ACTOR_ID = "platformer_kinematic_movement_v1_actor"
MODE_ID = "default"
COMPONENT_TYPE_ID = 5
FIELD_NAME = "max_linear_speed"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prove prompt undo/redo with proof links.")
    parser.add_argument("--runtime-bin", default=str(DEFAULT_RUNTIME_BIN))
    parser.add_argument("--sgc-bin", default=str(DEFAULT_SGC_BIN))
    parser.add_argument("--artifact-dir", default=str(DEFAULT_ARTIFACT_DIR))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--mutations", type=int, default=50)
    parser.add_argument("--ticks", type=int, default=2)
    parser.add_argument("--world-seed", type=int, default=33)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run_check(
            runtime_bin=Path(args.runtime_bin).resolve(),
            sgc_bin=Path(args.sgc_bin).resolve(),
            artifact_dir=Path(args.artifact_dir).resolve(),
            mutation_count=args.mutations,
            ticks=args.ticks,
            world_seed=args.world_seed,
        )
        runtime_proof.write_json(Path(args.output).resolve(), report)
    except Exception as exc:  # noqa: BLE001 - retained proof emits the first actionable failure.
        print(f"prompt undo/redo proof failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, sort_keys=True) if args.json else json.dumps(report, indent=2, sort_keys=True))
    return 0


def run_check(
    *,
    runtime_bin: Path,
    sgc_bin: Path,
    artifact_dir: Path,
    mutation_count: int,
    ticks: int,
    world_seed: int,
) -> dict[str, Any]:
    runtime_proof.require(runtime_bin.is_file(), f"runtime binary not found: {runtime_bin}")
    runtime_proof.require(sgc_bin.is_file(), f"SGC binary not found: {sgc_bin}")
    runtime_proof.require(mutation_count >= 50, "X10-033 requires at least 50 prompt mutations")
    runtime_proof.require(ticks > 0, "ticks must be positive")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    proof_dir = runtime_proof.allocate_proof_dir(artifact_dir / "runs", None)
    project_root = proof_dir / "project"
    project_root.mkdir(parents=True, exist_ok=True)
    states_dir = proof_dir / "states"
    states_dir.mkdir(parents=True, exist_ok=True)

    persist = CGSPersistence(project_root)
    parser = StructuredOutputParser()
    orchestrator = GDEOrchestrator(session_id="x10-033-proof")

    base_cgs = _base_cgs()
    base_hash = base_cgs["metadata"]["cgs_hash"]
    state_records: list[dict[str, Any]] = []
    state_by_hash: dict[str, dict[str, Any]] = {}

    _persist_state(
        persist=persist,
        cgs=base_cgs,
        state_index=0,
        summary="X10-033 base prompt history state",
        mutation_count=0,
    )
    base_state = _state_signature(
        persist=persist,
        cgs=base_cgs,
        state_index=0,
        sgc_bin=sgc_bin,
        runtime_bin=runtime_bin,
        proof_dir=states_dir / "state_000_base",
        ticks=ticks,
        world_seed=world_seed,
    )
    state_records.append(base_state)
    state_by_hash[base_hash] = base_state

    current_cgs = copy.deepcopy(base_cgs)
    applied_entries: list[dict[str, Any]] = []
    for index in range(1, mutation_count + 1):
        pre_hash = current_cgs["metadata"]["cgs_hash"]
        batch = _typed_speed_batch(index)
        parsed = parse_typed_operation_batch(batch)
        normalized = normalized_typed_operation_batch(parsed)
        canonical = parser.parse_typed(
            json.dumps(normalized, ensure_ascii=True, sort_keys=True),
            current_cgs,
        )
        runtime_proof.require(
            canonical.is_fully_valid,
            f"typed prompt mutation {index} did not validate: {'; '.join(canonical.validation.errors)}",
        )
        orchestrator.load_cgs(current_cgs)
        commit = orchestrator.process_typed_operation_batch(
            normalized,
            _metadata(
                f"txn-{index:012d}",
                f"X10-033 typed prompt mutation {index}",
                current_cgs,
            ),
        )
        runtime_proof.require(commit.success, commit.error)
        new_cgs = copy.deepcopy(orchestrator.current_cgs)
        new_hash = str(orchestrator.current_hash or new_cgs.get("metadata", {}).get("cgs_hash") or "")
        runtime_proof.require(new_hash and new_hash != pre_hash, f"mutation {index} did not change CGS hash")
        _persist_state(
            persist=persist,
            cgs=new_cgs,
            state_index=index,
            summary=f"Prompt mutation {index}: set {FIELD_NAME}",
            mutation_count=1,
        )
        state_sig = _state_signature(
            persist=persist,
            cgs=new_cgs,
            state_index=index,
            sgc_bin=sgc_bin,
            runtime_bin=runtime_bin,
            proof_dir=states_dir / f"state_{index:03d}_apply",
            ticks=ticks,
            world_seed=world_seed,
            run_runtime=index == mutation_count,
        )
        state_records.append(state_sig)
        state_by_hash[new_hash] = state_sig
        entry = persist.record_prompt_history_apply(
            transaction_id=f"txn-{index:012d}",
            pre_cgs_hash=pre_hash,
            post_cgs_hash=new_hash,
            summary=f"Prompt mutation {index}: set {FIELD_NAME}",
            mutation_count=1,
            version_ids={
                "cgs_hash": new_hash,
                "schema_version": str(new_cgs.get("metadata", {}).get("schema_version") or ""),
                "execution_plan_version": str(new_cgs.get("metadata", {}).get("execution_plan_version") or 1),
            },
            typed_operation_provenance=_typed_provenance(normalized),
        )
        applied_entries.append(entry)
        current_cgs = new_cgs

    history_after_apply = persist.prompt_history_state()
    runtime_proof.write_json(proof_dir / "prompt_history_after_apply.json", history_after_apply)
    runtime_proof.require(history_after_apply["cursor"] == mutation_count, "history cursor did not reach the end")
    runtime_proof.require(len(history_after_apply["entries"]) == mutation_count, "history entry count mismatch")

    # State 0 and state N need runtime baselines because they appear at only one end of the restore walk.
    state_records[mutation_count] = _state_signature(
        persist=persist,
        cgs=current_cgs,
        state_index=mutation_count,
        sgc_bin=sgc_bin,
        runtime_bin=runtime_bin,
        proof_dir=states_dir / f"state_{mutation_count:03d}_final_baseline",
        ticks=ticks,
        world_seed=world_seed,
    )
    state_by_hash[current_cgs["metadata"]["cgs_hash"]] = state_records[mutation_count]

    undo_results: list[dict[str, Any]] = []
    undo_runtime_by_state: dict[int, dict[str, Any]] = {}
    current_hash = current_cgs["metadata"]["cgs_hash"]
    for step in range(mutation_count, 0, -1):
        plan = persist.plan_prompt_history_restore("undo", current_cgs_hash=current_hash, require_proof=True)
        runtime_proof.require(plan.get("accepted") is True, f"undo plan rejected at {step}: {plan}")
        target_index = step - 1
        restored = _restore_from_plan(persist, plan, transaction_id=f"undo-{step:03d}")
        target_hash = restored["target_cgs_hash"]
        target_cgs = persist.load_snapshot(target_hash)
        signature = _restored_runtime_signature(
            persist=persist,
            cgs=target_cgs,
            runtime_bin=runtime_bin,
            proof_dir=states_dir / f"undo_{step:03d}_to_{target_index:03d}",
            ticks=ticks,
            world_seed=world_seed,
        )
        expected = state_records[target_index]
        _assert_restore_matches(expected, signature, target_index, f"undo {step}")
        undo_runtime_by_state[target_index] = signature
        undo_results.append({
            "step": step,
            "target_state_index": target_index,
            "target_cgs_hash": target_hash,
            "plan_hash": signature["plan_hash"],
            "latest_world_hash": signature["latest_world_hash"],
            "hash_log_hash": signature["hash_log_hash"],
            "proof_links_available": _proof_links_available(plan.get("proof_links")),
            "history_event": restored,
        })
        current_hash = target_hash

    history_after_undo = persist.prompt_history_state()
    runtime_proof.write_json(proof_dir / "prompt_history_after_undo.json", history_after_undo)
    runtime_proof.require(history_after_undo["cursor"] == 0, "full undo did not return cursor to origin")
    runtime_proof.require(current_hash == base_hash, "full undo did not restore the base CGS hash")
    _assert_restore_matches(state_records[0], undo_runtime_by_state[0], 0, "full undo origin")

    redo_results: list[dict[str, Any]] = []
    for step in range(1, mutation_count + 1):
        plan = persist.plan_prompt_history_restore("redo", current_cgs_hash=current_hash, require_proof=True)
        runtime_proof.require(plan.get("accepted") is True, f"redo plan rejected at {step}: {plan}")
        restored = _restore_from_plan(persist, plan, transaction_id=f"redo-{step:03d}")
        target_hash = restored["target_cgs_hash"]
        target_cgs = persist.load_snapshot(target_hash)
        signature = _restored_runtime_signature(
            persist=persist,
            cgs=target_cgs,
            runtime_bin=runtime_bin,
            proof_dir=states_dir / f"redo_{step:03d}_to_{step:03d}",
            ticks=ticks,
            world_seed=world_seed,
        )
        expected = state_records[step]
        _assert_restore_matches(expected, signature, step, f"redo {step}")
        if step < mutation_count:
            _assert_restore_matches(undo_runtime_by_state[step], signature, step, f"redo/undo pair {step}")
        redo_results.append({
            "step": step,
            "target_state_index": step,
            "target_cgs_hash": target_hash,
            "plan_hash": signature["plan_hash"],
            "latest_world_hash": signature["latest_world_hash"],
            "hash_log_hash": signature["hash_log_hash"],
            "proof_links_available": _proof_links_available(plan.get("proof_links")),
            "history_event": restored,
        })
        current_hash = target_hash

    history_after_redo = persist.prompt_history_state()
    runtime_proof.write_json(proof_dir / "prompt_history_after_redo.json", history_after_redo)
    runtime_proof.write_json(proof_dir / "state_records.json", state_records)
    runtime_proof.write_json(proof_dir / "undo_results.json", undo_results)
    runtime_proof.write_json(proof_dir / "redo_results.json", redo_results)

    final_hash = state_records[-1]["cgs_hash"]
    all_restore_links = all(item["proof_links_available"] for item in undo_results + redo_results)
    unique_cgs_hashes = len({record["cgs_hash"] for record in state_records})
    checks = {
        "mutation_count_at_least_50": mutation_count >= 50,
        "history_entries_recorded": len(history_after_apply.get("entries") or []) == mutation_count,
        "all_state_hashes_unique": unique_cgs_hashes == mutation_count + 1,
        "all_states_have_snapshots": all(_snapshot_exists(project_root, record["cgs_hash"]) for record in state_records),
        "all_states_have_execution_plans": all(_plan_exists(project_root, record["cgs_hash"]) for record in state_records),
        "all_states_have_sgc_proof_bundles": all(_proof_bundle_exists(project_root, record["cgs_hash"]) for record in state_records),
        "undo_count_50": len(undo_results) == mutation_count,
        "redo_count_50": len(redo_results) == mutation_count,
        "full_undo_restores_origin_hash": history_after_undo.get("current_cgs_hash") == base_hash,
        "full_redo_restores_final_hash": history_after_redo.get("current_cgs_hash") == final_hash,
        "history_cursor_after_undo_zero": history_after_undo.get("cursor") == 0,
        "history_cursor_after_redo_end": history_after_redo.get("cursor") == mutation_count,
        "all_restore_proof_links_available": all_restore_links,
        "undo_redo_cgs_plan_runtime_replay_match": True,
    }
    report = {
        "schema": "xace.prompt_undo_redo_e2e_report.v1",
        "ok": all(checks.values()),
        "x10_033_complete": all(checks.values()),
        "mutation_count": mutation_count,
        "undo_count": len(undo_results),
        "redo_count": len(redo_results),
        "base_cgs_hash": base_hash,
        "final_cgs_hash": final_hash,
        "history_hash_after_apply": history_after_apply.get("history_hash"),
        "history_hash_after_undo": history_after_undo.get("history_hash"),
        "history_hash_after_redo": history_after_redo.get("history_hash"),
        "checks": checks,
        "state_count": len(state_records),
        "state_hashes": [record["cgs_hash"] for record in state_records],
        "sample_restore": {
            "first_undo": undo_results[0],
            "last_undo": undo_results[-1],
            "first_redo": redo_results[0],
            "last_redo": redo_results[-1],
        },
        "artifacts": {
            "proof_dir": str(proof_dir),
            "project_root": str(project_root),
            "prompt_history": str(project_root / ".xace" / "audit" / "prompt_history.json"),
            "prompt_history_events": str(project_root / ".xace" / "audit" / "prompt_history_events.jsonl"),
            "state_records": str(proof_dir / "state_records.json"),
            "undo_results": str(proof_dir / "undo_results.json"),
            "redo_results": str(proof_dir / "redo_results.json"),
        },
    }
    runtime_proof.require(report["ok"], f"prompt undo/redo checks failed: {checks}")
    runtime_proof.write_json(proof_dir / "summary.json", report)
    return report


def _base_cgs() -> dict[str, Any]:
    cgs = build_primitive_cgs(PLATFORMER_KINEMATIC_MOVEMENT_V1)
    cgs.setdefault("metadata", {})["execution_plan_version"] = 1
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
            "description": f"Exact X10-033 metadata for {key}.",
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


def _typed_speed_batch(index: int) -> dict[str, Any]:
    value = 30_000_000 + index * 10_000
    return {
        "schema": "xace.typed_cgs_operation_batch.v1",
        "request_id": f"request.x10-033.{index:03d}",
        "prompt_id": f"prompt.x10-033.{index:03d}",
        "summary": f"Prompt mutation {index}: set {FIELD_NAME} to {value}.",
        "operations": [
            {
                "operation_id": f"op.speed.{index:03d}",
                "kind": "set_defaults",
                "explanation": f"Set deterministic platformer movement speed for prompt step {index}.",
                "mode_id": MODE_ID,
                "actor_id": ACTOR_ID,
                "component_type_id": COMPONENT_TYPE_ID,
                "assignments": [
                    {
                        "field_name": FIELD_NAME,
                        "field_type": "int",
                        "value": value,
                    }
                ],
            }
        ],
    }


def _metadata(transaction_id: str, description: str, cgs: dict[str, Any]) -> MutationMetadata:
    metadata = cgs.get("metadata", {}) if isinstance(cgs.get("metadata"), dict) else {}
    return MutationMetadata.create(
        transaction_id=transaction_id,
        parent_cgs_hash=str(metadata.get("cgs_hash") or ""),
        schema_version_target=str(metadata.get("version") or metadata.get("schema_version") or "0.1.0"),
        prompt_text=description,
        confidence=0.99,
        description=description,
        risk_level="medium",
        session_id="x10-033-proof",
        source="prompt",
    )


def _persist_state(
    *,
    persist: CGSPersistence,
    cgs: dict[str, Any],
    state_index: int,
    summary: str,
    mutation_count: int,
) -> None:
    cgs_hash = str(cgs.get("metadata", {}).get("cgs_hash") or "")
    persist.save(cgs)
    persist.snapshot(
        cgs,
        SnapshotRecord(
            cgs_hash=cgs_hash,
            schema_version=str(cgs.get("metadata", {}).get("schema_version") or "0.1.0"),
            turn_index=state_index,
            mutation_count=mutation_count,
            timestamp=time.time(),
            summary=summary,
            version_bump="patch" if state_index else "minor",
            risk_level="low",
        ),
    )


def _state_signature(
    *,
    persist: CGSPersistence,
    cgs: dict[str, Any],
    state_index: int,
    sgc_bin: Path,
    runtime_bin: Path,
    proof_dir: Path,
    ticks: int,
    world_seed: int,
    run_runtime: bool = True,
) -> dict[str, Any]:
    proof_dir.mkdir(parents=True, exist_ok=True)
    cgs_hash = str(cgs.get("metadata", {}).get("cgs_hash") or "")
    validation = ValidationResult()
    validate_cgs(cgs, validation, allow_legacy_hash=False, allow_draft_hash=False)
    runtime_proof.require(validation.ok, f"CGS validation failed for {cgs_hash[:8]}: {'; '.join(validation.errors)}")
    runtime_proof.write_json(proof_dir / "state.cgs.json", cgs)
    sgc_input = runtime_proof.sgc_input_from_cgs(cgs)
    runtime_proof.write_json(proof_dir / "sgc_input.json", sgc_input)
    sgc_result = runtime_proof.run_sgc(sgc_bin, sgc_input)
    plan = sgc_result["plan"]
    runtime_proof.validate_sgc_plan(plan, cgs_hash, sgc_input)
    persisted_plan_text = persist.save_execution_plan(
        cgs_hash,
        json.dumps(plan, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
        cgs=cgs,
        validation={
            "schema": "xace.prompt_undo_redo.sgc_validation.v1",
            "ok": True,
            "load_ready": True,
            "state_cgs_hash": cgs_hash,
        },
    )
    persist.save_sgc_proof_bundle(cgs, persisted_plan_text, validation={"ok": True, "load_ready": True})
    persisted_plan = json.loads(persisted_plan_text)
    runtime_signature: dict[str, Any] = {}
    if run_runtime:
        runtime_signature = _runtime_signature(
            persist=persist,
            cgs=cgs,
            runtime_bin=runtime_bin,
            persisted_plan=persisted_plan,
            proof_dir=proof_dir,
            ticks=ticks,
            world_seed=world_seed,
            label="baseline",
        )
    return {
        "schema": "xace.prompt_history_state_signature.v1",
        "state_index": state_index,
        "cgs_hash": cgs_hash,
        "cgs_json_hash": runtime_proof.sha256_json(cgs),
        "plan_hash": persisted_plan["plan_hash"],
        "plan_json_hash": runtime_proof.sha256_json(persisted_plan),
        "scheduled_system_ids": runtime_proof.scheduled_system_ids_from_plan(persisted_plan),
        "latest_world_hash": runtime_signature.get("latest_world_hash", ""),
        "hash_log_hash": runtime_signature.get("hash_log_hash", ""),
        "schedule_fingerprint": runtime_signature.get("schedule_fingerprint", ""),
        "runtime_report": runtime_signature.get("runtime_report", ""),
    }


def _restored_runtime_signature(
    *,
    persist: CGSPersistence,
    cgs: dict[str, Any],
    runtime_bin: Path,
    proof_dir: Path,
    ticks: int,
    world_seed: int,
) -> dict[str, Any]:
    cgs_hash = str(cgs.get("metadata", {}).get("cgs_hash") or "")
    plan_text = persist.load_execution_plan(cgs_hash)
    runtime_proof.require(plan_text is not None, f"persisted plan missing for restored state {cgs_hash[:8]}")
    persisted_plan = json.loads(plan_text or "{}")
    return _runtime_signature(
        persist=persist,
        cgs=cgs,
        runtime_bin=runtime_bin,
        persisted_plan=persisted_plan,
        proof_dir=proof_dir,
        ticks=ticks,
        world_seed=world_seed,
        label="restore",
    ) | {
        "schema": "xace.prompt_history_state_signature.v1",
        "cgs_hash": cgs_hash,
        "cgs_json_hash": runtime_proof.sha256_json(cgs),
        "plan_hash": persisted_plan["plan_hash"],
        "plan_json_hash": runtime_proof.sha256_json(persisted_plan),
        "scheduled_system_ids": runtime_proof.scheduled_system_ids_from_plan(persisted_plan),
    }


def _runtime_signature(
    *,
    persist: CGSPersistence,
    cgs: dict[str, Any],
    runtime_bin: Path,
    persisted_plan: dict[str, Any],
    proof_dir: Path,
    ticks: int,
    world_seed: int,
    label: str,
) -> dict[str, Any]:
    proof_dir.mkdir(parents=True, exist_ok=True)
    persist.save(cgs)
    run = runtime_proof.run_runtime(
        runtime_bin=runtime_bin,
        cgs_path=Path(getattr(persist, "_root")) / "game.cgs.json",
        report_path=proof_dir / f"{label}.schedule_report.json",
        stdout_path=proof_dir / f"{label}.runtime.stdout.txt",
        stderr_path=proof_dir / f"{label}.runtime.stderr.txt",
        ticks=ticks,
        world_seed=world_seed,
    )
    report = runtime_proof.read_runtime_report(run["report_path"], persisted_plan, ticks, world_seed)
    return {
        "latest_world_hash": report["latest_world_hash"],
        "hash_log_hash": runtime_proof.sha256_json(report["hash_log"]),
        "schedule_fingerprint": runtime_proof.schedule_fingerprint(report),
        "runtime_report": run["report_path"],
    }


def _restore_from_plan(
    persist: CGSPersistence,
    plan: dict[str, Any],
    *,
    transaction_id: str,
) -> dict[str, Any]:
    target_hash = str(plan.get("target_cgs_hash") or "")
    cgs = persist.load_snapshot(target_hash)
    cgs.setdefault("metadata", {})["cgs_hash"] = target_hash
    persist.save(cgs)
    event = persist.complete_prompt_history_restore(plan, transaction_id=transaction_id)
    event["target_cgs_hash"] = target_hash
    return event


def _assert_restore_matches(
    expected: dict[str, Any],
    actual: dict[str, Any],
    state_index: int,
    label: str,
) -> None:
    for key in (
        "cgs_hash",
        "cgs_json_hash",
        "plan_hash",
        "plan_json_hash",
        "scheduled_system_ids",
        "latest_world_hash",
        "hash_log_hash",
        "schedule_fingerprint",
    ):
        if not expected.get(key):
            continue
        runtime_proof.require(
            actual.get(key) == expected.get(key),
            f"{label} state {state_index} {key} mismatch: {actual.get(key)} != {expected.get(key)}",
        )


def _typed_provenance(batch: dict[str, Any]) -> dict[str, Any]:
    canonical = json.dumps(batch, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    operations = batch.get("operations") if isinstance(batch.get("operations"), list) else []
    return {
        "schema": str(batch.get("schema") or ""),
        "request_id": str(batch.get("request_id") or ""),
        "prompt_id": str(batch.get("prompt_id") or ""),
        "batch_hash": _sha256_text(canonical),
        "operation_ids": [str(op.get("operation_id") or "") for op in operations if isinstance(op, dict)],
        "operation_kinds": [str(op.get("kind") or "") for op in operations if isinstance(op, dict)],
    }


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _proof_links_available(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    execution_plan = value.get("execution_plan")
    proof = value.get("sgc_proof_bundle")
    return (
        bool(value.get("snapshot"))
        and isinstance(execution_plan, dict)
        and execution_plan.get("available") is True
        and isinstance(proof, dict)
        and proof.get("available") is True
    )


def _snapshot_exists(project_root: Path, cgs_hash: str) -> bool:
    return (project_root / ".xace" / "snapshots" / f"{cgs_hash}.json").exists()


def _plan_exists(project_root: Path, cgs_hash: str) -> bool:
    return (project_root / ".xace" / "execution_plans" / f"{cgs_hash}.plan.json").exists()


def _proof_bundle_exists(project_root: Path, cgs_hash: str) -> bool:
    proof_dir = project_root / ".xace" / "proof" / "sgc" / cgs_hash
    return all((proof_dir / name).exists() for name in ("input.json", "plan.json", "metadata.json"))


if __name__ == "__main__":
    raise SystemExit(main())
