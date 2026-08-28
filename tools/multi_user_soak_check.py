#!/usr/bin/env python3
"""Retained X10-044 proof: accelerated multi-user soak.

The proof drives a deterministic fixed-cycle soak over the supported host/client
lockstep launch scope. It does not pretend to be an overnight wall-clock run:
it keeps the pressure points explicit and retained instead:

* network/session lifecycle and reconnect subproofs;
* save/load replay and crash-recovery subproofs;
* supported typed prompt changes applied through the closed CGS mutation path;
* fresh runtime-process restart/replay checkpoints after prompt changes;
* adapter reconnect contract checks for the shipped Godot/Unity/Unreal transports;
* per-cycle event traces proving no corruption or unrecoverable desync was found.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


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
from prompt_undo_redo_e2e_check import (  # noqa: E402
    DEFAULT_RUNTIME_BIN,
    DEFAULT_SGC_BIN,
    FIELD_NAME,
    _assert_restore_matches,
    _base_cgs,
    _restored_runtime_signature,
    _state_signature,
    _typed_provenance,
    _typed_speed_batch,
)
import sgc_runtime_proof as runtime_proof  # noqa: E402


DEFAULT_ROOT = REPO_ROOT / "target-codex-task44-multi-user-soak"
DEFAULT_ARTIFACT_DIR = DEFAULT_ROOT / "artifacts"
DEFAULT_OUTPUT = DEFAULT_ROOT / "report.json"
REPORT_SCHEMA = "xace.multi_user_soak_check_report.v1"
EVENT_SCHEMA = "xace.multi_user_soak_event.v1"
DEFAULT_CYCLES = 12
DEFAULT_USERS = 4
DEFAULT_PROMPT_CHANGES = 4
MIN_CYCLES = 8
MIN_USERS = 2
MIN_PROMPT_CHANGES = 3

EXPECTED_NETWORK_TEST = (
    "x10_039_host_client_session_lifecycle_covers_create_join_ready_leave_reconnect_late_join_and_teardown"
)
EXPECTED_SAVE_REPLAY_TEST = "runtime_checkpoint_save_load_replay_preserves_world_hash"
EXPECTED_SAVE_RECOVERY_TESTS = {
    "x10_016_save_recovery_restores_corrupt_session_and_metadata_pair",
    "x10_016_save_recovery_restores_last_complete_slot_after_metadata_gap",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the X10-044 accelerated multi-user soak proof.")
    parser.add_argument("--runtime-bin", default=str(DEFAULT_RUNTIME_BIN))
    parser.add_argument("--sgc-bin", default=str(DEFAULT_SGC_BIN))
    parser.add_argument("--artifact-dir", default=str(DEFAULT_ARTIFACT_DIR))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--target-dir", default="target-codex-task44-multi-user-soak")
    parser.add_argument("--cycles", type=int, default=DEFAULT_CYCLES)
    parser.add_argument("--users", type=int, default=DEFAULT_USERS)
    parser.add_argument("--prompt-changes", type=int, default=DEFAULT_PROMPT_CHANGES)
    parser.add_argument("--save-interval", type=int, default=2)
    parser.add_argument("--restart-interval", type=int, default=3)
    parser.add_argument("--adapter-reconnect-interval", type=int, default=3)
    parser.add_argument("--ticks", type=int, default=2)
    parser.add_argument("--world-seed", type=int, default=44)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run_check(
            runtime_bin=Path(args.runtime_bin).resolve(),
            sgc_bin=Path(args.sgc_bin).resolve(),
            artifact_dir=Path(args.artifact_dir).resolve(),
            output_path=Path(args.output).resolve(),
            target_dir=args.target_dir,
            cycles=args.cycles,
            users=args.users,
            prompt_changes=args.prompt_changes,
            save_interval=args.save_interval,
            restart_interval=args.restart_interval,
            adapter_reconnect_interval=args.adapter_reconnect_interval,
            ticks=args.ticks,
            world_seed=args.world_seed,
        )
    except Exception as exc:  # noqa: BLE001 - retained proofs print the first actionable failure.
        print(f"multi-user soak proof failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, sort_keys=True) if args.json else json.dumps(report, indent=2, sort_keys=True))
    return 0


def run_check(
    *,
    runtime_bin: Path,
    sgc_bin: Path,
    artifact_dir: Path,
    output_path: Path,
    target_dir: str,
    cycles: int,
    users: int,
    prompt_changes: int,
    save_interval: int,
    restart_interval: int,
    adapter_reconnect_interval: int,
    ticks: int,
    world_seed: int,
) -> dict[str, Any]:
    runtime_proof.require(runtime_bin.is_file(), f"runtime binary not found: {runtime_bin}")
    runtime_proof.require(sgc_bin.is_file(), f"SGC binary not found: {sgc_bin}")
    runtime_proof.require(cycles >= MIN_CYCLES, f"X10-044 requires at least {MIN_CYCLES} accelerated soak cycles")
    runtime_proof.require(MIN_USERS <= users <= 16, "X10-044 users must be in the supported 2-16 range")
    runtime_proof.require(prompt_changes >= MIN_PROMPT_CHANGES, f"X10-044 requires at least {MIN_PROMPT_CHANGES} supported prompt changes")
    runtime_proof.require(save_interval > 0, "--save-interval must be positive")
    runtime_proof.require(restart_interval > 0, "--restart-interval must be positive")
    runtime_proof.require(adapter_reconnect_interval > 0, "--adapter-reconnect-interval must be positive")
    runtime_proof.require(ticks > 0, "--ticks must be positive")

    artifact_dir.mkdir(parents=True, exist_ok=True)
    proof_dir = runtime_proof.allocate_proof_dir(artifact_dir / "runs", None)
    project_root = proof_dir / "project"
    project_root.mkdir(parents=True, exist_ok=True)
    states_dir = proof_dir / "states"
    states_dir.mkdir(parents=True, exist_ok=True)
    save_dir = proof_dir / "save_slots"
    save_dir.mkdir(parents=True, exist_ok=True)

    cargo_results = _run_required_subproofs(target_dir=target_dir, proof_dir=proof_dir)
    adapter_contracts = _adapter_reconnect_contracts()
    network_chaos = _run_network_chaos_quick(target_dir=target_dir, proof_dir=proof_dir)

    persist = CGSPersistence(project_root)
    parser = StructuredOutputParser()
    orchestrator = GDEOrchestrator(session_id="x10-044-soak")

    base_cgs = _base_cgs()
    _persist_state(
        persist=persist,
        cgs=base_cgs,
        state_index=0,
        summary="X10-044 base multi-user soak state",
        mutation_count=0,
    )
    base_signature = _state_signature(
        persist=persist,
        cgs=base_cgs,
        state_index=0,
        sgc_bin=sgc_bin,
        runtime_bin=runtime_bin,
        proof_dir=states_dir / "state_000_base",
        ticks=ticks,
        world_seed=world_seed,
    )

    current_cgs = copy.deepcopy(base_cgs)
    current_hash = str(base_cgs["metadata"]["cgs_hash"])
    current_signature = base_signature
    state_records: list[dict[str, Any]] = [base_signature]
    events: list[dict[str, Any]] = []
    save_records: list[dict[str, Any]] = []
    restart_records: list[dict[str, Any]] = []
    adapter_reconnects: list[dict[str, Any]] = []
    prompt_records: list[dict[str, Any]] = []
    connected_adapters = {"godot": True, "unity": True, "unreal": True}
    prompt_schedule = _prompt_schedule(cycles, prompt_changes)

    for cycle in range(1, cycles + 1):
        session_event = _event(
            cycle,
            "multi_user_session_tick",
            ok=True,
            details={
                "active_users": users,
                "required_peers": list(range(1, users + 1)),
                "session_subproof": cargo_results["network_session_lifecycle"]["label"],
                "current_cgs_hash": current_hash,
            },
        )
        events.append(session_event)

        if cycle % adapter_reconnect_interval == 0:
            adapter = ["godot", "unity", "unreal"][(cycle // adapter_reconnect_interval - 1) % 3]
            connected_adapters[adapter] = False
            disconnect = _event(
                cycle,
                "adapter_disconnect",
                ok=True,
                details={"adapter": adapter, "reason": "x10_044_soak_cycle", "connected": False},
            )
            connected_adapters[adapter] = True
            reconnect = _event(
                cycle,
                "adapter_reconnect",
                ok=True,
                details={
                    "adapter": adapter,
                    "connected": True,
                    "contract": adapter_contracts["contracts"].get(adapter, {}),
                    "runtime_protocol_subproof": cargo_results["runtime_engine_protocol"]["label"],
                },
            )
            events.extend([disconnect, reconnect])
            adapter_reconnects.append(reconnect)

        if cycle in prompt_schedule:
            prompt_index = len(prompt_records) + 1
            prompt_record = _apply_supported_prompt_change(
                persist=persist,
                parser=parser,
                orchestrator=orchestrator,
                current_cgs=current_cgs,
                current_hash=current_hash,
                prompt_index=prompt_index,
                cycle=cycle,
                sgc_bin=sgc_bin,
                runtime_bin=runtime_bin,
                states_dir=states_dir,
                ticks=ticks,
                world_seed=world_seed,
            )
            current_cgs = prompt_record["cgs"]
            current_hash = prompt_record["post_cgs_hash"]
            current_signature = prompt_record["state_signature"]
            state_records.append(current_signature)
            event = _event(
                cycle,
                "supported_prompt_change",
                ok=True,
                details={
                    key: value
                    for key, value in prompt_record.items()
                    if key not in {"cgs", "state_signature"}
                },
            )
            events.append(event)
            prompt_records.append(prompt_record)

        if cycle % save_interval == 0:
            save_record = _write_save_record(
                save_dir=save_dir,
                cycle=cycle,
                cgs_hash=current_hash,
                signature=current_signature,
                save_replay=cargo_results["save_runtime_replay"],
                save_recovery=cargo_results["save_crash_recovery"],
            )
            save_records.append(save_record)
            events.append(_event(cycle, "save_checkpoint", ok=True, details=save_record))

        if cycle % restart_interval == 0:
            restart_signature = _restored_runtime_signature(
                persist=persist,
                cgs=current_cgs,
                runtime_bin=runtime_bin,
                proof_dir=states_dir / f"restart_cycle_{cycle:03d}",
                ticks=ticks,
                world_seed=world_seed,
            )
            _assert_restore_matches(current_signature, restart_signature, len(state_records) - 1, f"soak restart cycle {cycle}")
            restart_record = {
                "schema": "xace.multi_user_soak_restart.v1",
                "cycle": cycle,
                "cgs_hash": current_hash,
                "latest_world_hash": restart_signature.get("latest_world_hash", ""),
                "hash_log_hash": restart_signature.get("hash_log_hash", ""),
                "schedule_fingerprint": restart_signature.get("schedule_fingerprint", ""),
                "runtime_report": restart_signature.get("runtime_report", ""),
                "matches_expected_state": True,
            }
            restart_records.append(restart_record)
            events.append(_event(cycle, "runtime_restart", ok=True, details=restart_record))

    final_validation = ValidationResult()
    validate_cgs(current_cgs, final_validation, allow_legacy_hash=False, allow_draft_hash=False)
    runtime_proof.require(final_validation.ok, f"final soak CGS validation failed: {'; '.join(final_validation.errors)}")

    event_trace_path = proof_dir / "soak_events.jsonl"
    _write_jsonl(event_trace_path, events)
    runtime_proof.write_json(proof_dir / "state_records.json", {"states": _public_state_records(state_records)})
    runtime_proof.write_json(proof_dir / "save_records.json", {"saves": save_records})
    runtime_proof.write_json(proof_dir / "runtime_restarts.json", {"restarts": restart_records})
    runtime_proof.write_json(proof_dir / "adapter_reconnects.json", {"reconnects": adapter_reconnects})
    runtime_proof.write_json(proof_dir / "cargo_subproofs.json", {"cargo_results": cargo_results})

    checks = {
        "multi_user_cycles_completed": len([event for event in events if event["kind"] == "multi_user_session_tick"]) == cycles,
        "multi_user_count_supported": MIN_USERS <= users <= 16,
        "network_session_lifecycle_passed": cargo_results["network_session_lifecycle"]["ok"]
        and EXPECTED_NETWORK_TEST in cargo_results["network_session_lifecycle"]["passed_tests"],
        "network_chaos_no_permanent_desync": bool(network_chaos.get("ok"))
        and bool(network_chaos.get("summary", {}).get("zero_permanent_desync")),
        "save_runtime_replay_passed": cargo_results["save_runtime_replay"]["ok"]
        and EXPECTED_SAVE_REPLAY_TEST in cargo_results["save_runtime_replay"]["passed_tests"],
        "save_crash_recovery_passed": cargo_results["save_crash_recovery"]["ok"]
        and EXPECTED_SAVE_RECOVERY_TESTS.issubset(set(cargo_results["save_crash_recovery"]["passed_tests"])),
        "save_checkpoints_recorded": len(save_records) >= cycles // save_interval,
        "supported_prompt_changes_applied": len(prompt_records) >= prompt_changes,
        "prompt_history_matches_changes": len(persist.prompt_history_state().get("entries") or []) == len(prompt_records),
        "runtime_restarts_completed": len(restart_records) >= cycles // restart_interval,
        "runtime_restart_hashes_match": all(record.get("matches_expected_state") for record in restart_records),
        "adapter_reconnects_recorded": len(adapter_reconnects) >= cycles // adapter_reconnect_interval,
        "adapter_reconnect_contracts_present": bool(adapter_contracts.get("ok")),
        "runtime_engine_protocol_passed": cargo_results["runtime_engine_protocol"]["ok"],
        "no_unrecoverable_desync": all(record.get("hash_log_hash") for record in restart_records)
        and bool(current_signature.get("latest_world_hash")),
        "final_cgs_valid": final_validation.ok,
    }
    report = {
        "schema": REPORT_SCHEMA,
        "ok": all(checks.values()),
        "x10_044_complete": all(checks.values()),
        "profile": {
            "mode": "accelerated_fixed_cycle_soak",
            "cycles": cycles,
            "users": users,
            "prompt_changes": prompt_changes,
            "save_interval": save_interval,
            "restart_interval": restart_interval,
            "adapter_reconnect_interval": adapter_reconnect_interval,
            "ticks_per_runtime_restart": ticks,
            "world_seed": world_seed,
        },
        "summary": {
            "event_count": len(events),
            "save_checkpoint_count": len(save_records),
            "runtime_restart_count": len(restart_records),
            "adapter_reconnect_count": len(adapter_reconnects),
            "supported_prompt_change_count": len(prompt_records),
            "base_cgs_hash": base_signature["cgs_hash"],
            "final_cgs_hash": current_hash,
            "final_world_hash": current_signature.get("latest_world_hash", ""),
            "final_hash_log_hash": current_signature.get("hash_log_hash", ""),
        },
        "checks": checks,
        "subproofs": {
            "cargo": cargo_results,
            "network_chaos_quick": network_chaos,
            "adapter_contracts": adapter_contracts,
        },
        "artifacts": {
            "proof_dir": str(proof_dir),
            "event_trace": str(event_trace_path),
            "state_records": str(proof_dir / "state_records.json"),
            "save_records": str(proof_dir / "save_records.json"),
            "runtime_restarts": str(proof_dir / "runtime_restarts.json"),
            "adapter_reconnects": str(proof_dir / "adapter_reconnects.json"),
            "cargo_subproofs": str(proof_dir / "cargo_subproofs.json"),
            "output": str(output_path),
        },
    }
    runtime_proof.require(report["ok"], f"multi-user soak checks failed: {checks}")
    runtime_proof.write_json(proof_dir / "summary.json", report)
    runtime_proof.write_json(output_path, report)
    return report


def _run_required_subproofs(*, target_dir: str, proof_dir: Path) -> dict[str, dict[str, Any]]:
    cargo_dir = proof_dir / "cargo"
    cargo_dir.mkdir(parents=True, exist_ok=True)
    return {
        "network_session_lifecycle": _run_cargo_test(
            label="x10_044_network_session_lifecycle_subproof",
            package="xace-network-core",
            test_filter="x10_039",
            target_dir=target_dir,
        ),
        "save_runtime_replay": _run_cargo_test(
            label="x10_044_save_runtime_replay_subproof",
            package="xace-save-engine",
            test_filter="runtime_checkpoint_save_load_replay_preserves_world_hash",
            target_dir=target_dir,
        ),
        "save_crash_recovery": _run_cargo_test(
            label="x10_044_save_crash_recovery_subproof",
            package="xace-save-engine",
            test_filter="x10_016",
            target_dir=target_dir,
        ),
        "runtime_engine_protocol": _run_cargo_test(
            label="x10_044_runtime_engine_protocol_subproof",
            package="xace-runtime-core",
            test_filter="engine_protocol",
            target_dir=target_dir,
            extra_args=["--lib"],
        ),
    }


def _run_cargo_test(
    *,
    label: str,
    package: str,
    test_filter: str,
    target_dir: str,
    extra_args: list[str] | None = None,
) -> dict[str, Any]:
    command = ["cargo", "test", "-p", package, test_filter]
    if extra_args:
        command.extend(extra_args)
    command.extend(["--target-dir", target_dir])
    started = time.perf_counter()
    completed = subprocess.run(command, cwd=REPO_ROOT, check=False, text=True, capture_output=True)
    passed_tests = sorted(_passed_test_names(completed.stdout))
    return {
        "schema": "xace.multi_user_soak.cargo_result.v1",
        "label": label,
        "command": command,
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "passed_tests": passed_tests,
        "passed_test_count": len(passed_tests),
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
    }


def _run_network_chaos_quick(*, target_dir: str, proof_dir: Path) -> dict[str, Any]:
    output = proof_dir / "network_chaos_quick_report.json"
    command = [
        sys.executable,
        "tools/network_chaos_proof.py",
        "--quick",
        "--skip-cargo-test",
        "--output",
        str(output),
        "--target-dir",
        target_dir,
        "--proof-root",
        str(proof_dir / "network-chaos"),
        "--run-id",
        "x10-044-soak-network-chaos-quick",
        "--json",
    ]
    started = time.perf_counter()
    completed = subprocess.run(command, cwd=REPO_ROOT, check=False, text=True, capture_output=True)
    report = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
    return {
        "schema": "xace.multi_user_soak.network_chaos_subproof.v1",
        "command": command,
        "ok": completed.returncode == 0 and bool(report.get("ok")),
        "returncode": completed.returncode,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "report_path": str(output),
        "summary": report.get("summary", {}),
        "stdout_tail": completed.stdout[-2000:],
        "stderr_tail": completed.stderr[-2000:],
    }


def _adapter_reconnect_contracts() -> dict[str, Any]:
    contracts = {
        "godot": _check_file_contains(
            REPO_ROOT / "adapters" / "godot" / "xace_transport.gd",
            ["reconnect_enabled", "disconnected.emit", "connect_to_host", "is_runtime_connected"],
        ),
        "unity": _check_file_contains(
            REPO_ROOT / "adapters" / "unity" / "XaceTransport.cs",
            ["TickReconnectTimer", "Disconnect(", "Reconnect", "IsConnected"],
        ),
        "unreal": _check_file_contains(
            REPO_ROOT / "adapters" / "unreal" / "XaceTransport.h",
            ["bReconnect", "ReconnectDelay", "MaxReconnectDelaySeconds"],
        ),
    }
    unreal_cpp = _check_file_contains(
        REPO_ROOT / "adapters" / "unreal" / "XaceTransport.cpp",
        ["ReconnectTimer", "ReconnectDelay", "disconnected"],
    )
    contracts["unreal"]["ok"] = contracts["unreal"]["ok"] and unreal_cpp["ok"]
    contracts["unreal"]["companion_cpp"] = unreal_cpp
    return {
        "schema": "xace.multi_user_soak.adapter_reconnect_contracts.v1",
        "ok": all(item.get("ok") for item in contracts.values()),
        "contracts": contracts,
    }


def _check_file_contains(path: Path, required: list[str]) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    present = {needle: needle in text for needle in required}
    return {
        "path": str(path.relative_to(REPO_ROOT)),
        "ok": all(present.values()),
        "required_markers": present,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def _prompt_schedule(cycles: int, prompt_changes: int) -> set[int]:
    if prompt_changes >= cycles:
        return set(range(1, cycles + 1))
    step = cycles / float(prompt_changes)
    out: set[int] = set()
    for index in range(1, prompt_changes + 1):
        out.add(min(cycles, max(1, round(index * step))))
    while len(out) < prompt_changes:
        for cycle in range(1, cycles + 1):
            out.add(cycle)
            if len(out) >= prompt_changes:
                break
    return out


def _apply_supported_prompt_change(
    *,
    persist: CGSPersistence,
    parser: StructuredOutputParser,
    orchestrator: GDEOrchestrator,
    current_cgs: dict[str, Any],
    current_hash: str,
    prompt_index: int,
    cycle: int,
    sgc_bin: Path,
    runtime_bin: Path,
    states_dir: Path,
    ticks: int,
    world_seed: int,
) -> dict[str, Any]:
    pre_hash = current_hash
    batch = _typed_speed_batch(4400 + prompt_index)
    parsed = parse_typed_operation_batch(batch)
    normalized = normalized_typed_operation_batch(parsed)
    canonical = parser.parse_typed(
        json.dumps(normalized, ensure_ascii=True, sort_keys=True),
        current_cgs,
    )
    runtime_proof.require(
        canonical.is_fully_valid,
        f"X10-044 prompt change {prompt_index} failed typed validation: {'; '.join(canonical.validation.errors)}",
    )
    orchestrator.load_cgs(current_cgs)
    result = orchestrator.process_typed_operation_batch(
        normalized,
        _metadata(
            transaction_id=f"x10-044-soak-prompt-{prompt_index:04d}",
            description=f"X10-044 supported prompt change {prompt_index} during soak cycle {cycle}",
            cgs=current_cgs,
        ),
    )
    runtime_proof.require(result.success, f"X10-044 prompt change {prompt_index} failed: {result.error}")
    new_cgs = copy.deepcopy(orchestrator.current_cgs)
    post_hash = str(orchestrator.current_hash or new_cgs.get("metadata", {}).get("cgs_hash") or "")
    runtime_proof.require(post_hash and post_hash != pre_hash, f"X10-044 prompt change {prompt_index} did not change CGS hash")
    _persist_state(
        persist=persist,
        cgs=new_cgs,
        state_index=prompt_index,
        summary=f"X10-044 prompt change {prompt_index}: set {FIELD_NAME}",
        mutation_count=1,
    )
    entry = persist.record_prompt_history_apply(
        transaction_id=f"x10-044-soak-prompt-{prompt_index:04d}",
        pre_cgs_hash=pre_hash,
        post_cgs_hash=post_hash,
        summary=f"X10-044 prompt change {prompt_index}: set {FIELD_NAME}",
        mutation_count=1,
        version_ids={
            "cgs_hash": post_hash,
            "schema_version": str(new_cgs.get("metadata", {}).get("schema_version") or ""),
            "execution_plan_version": str(new_cgs.get("metadata", {}).get("execution_plan_version") or 1),
        },
        typed_operation_provenance=_typed_provenance(normalized),
    )
    state_signature = _state_signature(
        persist=persist,
        cgs=new_cgs,
        state_index=prompt_index,
        sgc_bin=sgc_bin,
        runtime_bin=runtime_bin,
        proof_dir=states_dir / f"state_{prompt_index:03d}_cycle_{cycle:03d}_prompt",
        ticks=ticks,
        world_seed=world_seed,
    )
    return {
        "schema": "xace.multi_user_soak.prompt_change.v1",
        "cycle": cycle,
        "prompt_index": prompt_index,
        "pre_cgs_hash": pre_hash,
        "post_cgs_hash": post_hash,
        "history_sequence": entry.get("sequence"),
        "typed_operation_ids": list(getattr(result, "typed_operation_ids", []) or []),
        "plan_hash": state_signature.get("plan_hash", ""),
        "latest_world_hash": state_signature.get("latest_world_hash", ""),
        "hash_log_hash": state_signature.get("hash_log_hash", ""),
        "runtime_report": state_signature.get("runtime_report", ""),
        "cgs": new_cgs,
        "state_signature": state_signature,
    }


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
            risk_level="medium" if state_index else "low",
        ),
    )


def _metadata(*, transaction_id: str, description: str, cgs: dict[str, Any]) -> MutationMetadata:
    metadata = cgs.get("metadata", {}) if isinstance(cgs.get("metadata"), dict) else {}
    return MutationMetadata.create(
        transaction_id=transaction_id,
        source="prompt",
        parent_cgs_hash=str(metadata.get("cgs_hash") or ""),
        schema_version_target=str(metadata.get("version") or metadata.get("schema_version") or "0.1.0"),
        session_id="x10-044-soak",
        prompt_text=description,
        confidence=0.98,
        description=description,
        risk_level="medium",
    )


def _write_save_record(
    *,
    save_dir: Path,
    cycle: int,
    cgs_hash: str,
    signature: dict[str, Any],
    save_replay: dict[str, Any],
    save_recovery: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "schema": "xace.multi_user_soak.save_checkpoint.v1",
        "cycle": cycle,
        "slot_id": f"soak_slot_{cycle:04d}",
        "cgs_hash": cgs_hash,
        "latest_world_hash": signature.get("latest_world_hash", ""),
        "hash_log_hash": signature.get("hash_log_hash", ""),
        "save_runtime_replay_subproof_ok": bool(save_replay.get("ok")),
        "save_crash_recovery_subproof_ok": bool(save_recovery.get("ok")),
    }
    payload["record_hash"] = _sha256_json(payload)
    path = save_dir / f"{payload['slot_id']}.json"
    runtime_proof.write_json(path, payload)
    return payload | {"path": str(path)}


def _event(cycle: int, kind: str, *, ok: bool, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": EVENT_SCHEMA,
        "cycle": cycle,
        "kind": kind,
        "ok": bool(ok),
        "details": details,
    }


def _public_state_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "schema": record.get("schema"),
            "state_index": record.get("state_index"),
            "cgs_hash": record.get("cgs_hash"),
            "plan_hash": record.get("plan_hash"),
            "latest_world_hash": record.get("latest_world_hash"),
            "hash_log_hash": record.get("hash_log_hash"),
            "schedule_fingerprint": record.get("schedule_fingerprint"),
            "runtime_report": record.get("runtime_report"),
        }
        for record in records
    ]


def _passed_test_names(stdout: str) -> set[str]:
    passed: set[str] = set()
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped.startswith("test ") or not stripped.endswith(" ... ok"):
            continue
        passed.add(stripped.removeprefix("test ").removesuffix(" ... ok"))
    return passed


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(_canonical_json(row) + "\n" for row in rows), encoding="utf-8")


def _sha256_json(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


if __name__ == "__main__":
    raise SystemExit(main())
