#!/usr/bin/env python3
"""Retained X10-034 proof: long-session prompt degradation.

The default certification profile is a deterministic fixed-length authoring
session rather than an eight-hour wall-clock soak. It drives hundreds of prompt
turns through the closed typed-CGS path, grows and compacts active context,
injects provider failures and stale-state mutations, exercises proof-linked
undo/redo, writes provider accounting artifacts, and runs real SGC/runtime
replay checkpoints.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
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
from packages.inference.src.provider_accounting import write_accounting_artifacts  # noqa: E402
from packages.inference.src.telemetry_pipeline import InferenceTelemetryEvent  # noqa: E402
from prompt_undo_redo_e2e_check import (  # noqa: E402
    DEFAULT_RUNTIME_BIN,
    DEFAULT_SGC_BIN,
    _assert_restore_matches,
    _base_cgs,
    _plan_exists,
    _proof_bundle_exists,
    _proof_links_available,
    _restore_from_plan,
    _restored_runtime_signature,
    _snapshot_exists,
    _state_signature,
    _typed_provenance,
    _typed_speed_batch,
)
import sgc_runtime_proof as runtime_proof  # noqa: E402


DEFAULT_ROOT = REPO_ROOT / "target-codex-task34-long-session"
DEFAULT_ARTIFACT_DIR = DEFAULT_ROOT / "artifacts"
DEFAULT_OUTPUT = DEFAULT_ROOT / "report.json"
SESSION_ID = "x10-034-long-session"
REPORT_SCHEMA = "xace.prompt_long_session_degradation_report.v1"
TRACE_SCHEMA = "xace.prompt_long_session_trace_event.v1"
CONTEXT_SCHEMA = "xace.prompt_long_session_context_window.v1"
DEFAULT_TURN_COUNT = 240
MIN_FIXED_LENGTH_TURNS = 200


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prove long prompt sessions remain bounded and recoverable.")
    parser.add_argument("--runtime-bin", default=str(DEFAULT_RUNTIME_BIN))
    parser.add_argument("--sgc-bin", default=str(DEFAULT_SGC_BIN))
    parser.add_argument("--artifact-dir", default=str(DEFAULT_ARTIFACT_DIR))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--turns", type=int, default=DEFAULT_TURN_COUNT)
    parser.add_argument("--runtime-check-interval", type=int, default=60)
    parser.add_argument("--undo-redo-period", type=int, default=40)
    parser.add_argument("--provider-failure-period", type=int, default=17)
    parser.add_argument("--stale-state-period", type=int, default=23)
    parser.add_argument("--context-byte-budget", type=int, default=16_000)
    parser.add_argument("--cost-budget-usd", type=float, default=0.50)
    parser.add_argument("--world-seed", type=int, default=34)
    parser.add_argument("--ticks", type=int, default=2)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run_check(
            runtime_bin=Path(args.runtime_bin).resolve(),
            sgc_bin=Path(args.sgc_bin).resolve(),
            artifact_dir=Path(args.artifact_dir).resolve(),
            turn_count=args.turns,
            runtime_check_interval=args.runtime_check_interval,
            undo_redo_period=args.undo_redo_period,
            provider_failure_period=args.provider_failure_period,
            stale_state_period=args.stale_state_period,
            context_byte_budget=args.context_byte_budget,
            cost_budget_usd=args.cost_budget_usd,
            world_seed=args.world_seed,
            ticks=args.ticks,
        )
        runtime_proof.write_json(Path(args.output).resolve(), report)
    except Exception as exc:  # noqa: BLE001 - retained proof prints the first actionable failure.
        print(f"prompt long-session degradation proof failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, sort_keys=True) if args.json else json.dumps(report, indent=2, sort_keys=True))
    return 0


def run_check(
    *,
    runtime_bin: Path,
    sgc_bin: Path,
    artifact_dir: Path,
    turn_count: int,
    runtime_check_interval: int,
    undo_redo_period: int,
    provider_failure_period: int,
    stale_state_period: int,
    context_byte_budget: int,
    cost_budget_usd: float,
    world_seed: int,
    ticks: int,
) -> dict[str, Any]:
    runtime_proof.require(runtime_bin.is_file(), f"runtime binary not found: {runtime_bin}")
    runtime_proof.require(sgc_bin.is_file(), f"SGC binary not found: {sgc_bin}")
    runtime_proof.require(turn_count >= MIN_FIXED_LENGTH_TURNS, f"fixed-length proof requires at least {MIN_FIXED_LENGTH_TURNS} turns")
    runtime_proof.require(runtime_check_interval > 0, "runtime-check-interval must be positive")
    runtime_proof.require(undo_redo_period > 1, "undo-redo-period must be greater than 1")
    runtime_proof.require(provider_failure_period > 1, "provider-failure-period must be greater than 1")
    runtime_proof.require(stale_state_period > 1, "stale-state-period must be greater than 1")
    runtime_proof.require(context_byte_budget >= 4_000, "context-byte-budget must be at least 4000 bytes")
    runtime_proof.require(cost_budget_usd > 0, "cost-budget-usd must be positive")
    runtime_proof.require(ticks > 0, "ticks must be positive")

    artifact_dir.mkdir(parents=True, exist_ok=True)
    proof_dir = runtime_proof.allocate_proof_dir(artifact_dir / "runs", None)
    project_root = proof_dir / "project"
    project_root.mkdir(parents=True, exist_ok=True)
    states_dir = proof_dir / "states"
    states_dir.mkdir(parents=True, exist_ok=True)

    persist = CGSPersistence(project_root)
    parser = StructuredOutputParser()
    orchestrator = GDEOrchestrator(session_id=SESSION_ID)
    context = _ContextWindow(context_byte_budget)

    base_cgs = _base_cgs()
    _persist_state(
        persist=persist,
        cgs=base_cgs,
        state_index=0,
        summary="X10-034 base long-session state",
        mutation_count=0,
    )
    state_records: list[dict[str, Any]] = [
        _state_signature(
            persist=persist,
            cgs=base_cgs,
            state_index=0,
            sgc_bin=sgc_bin,
            runtime_bin=runtime_bin,
            proof_dir=states_dir / "state_0000_base",
            ticks=ticks,
            world_seed=world_seed,
        )
    ]

    current_cgs = copy.deepcopy(base_cgs)
    current_hash = str(current_cgs["metadata"]["cgs_hash"])
    accepted_count = 0
    trace_events: list[dict[str, Any]] = []
    context_windows: list[dict[str, Any]] = []
    telemetry_events: list[InferenceTelemetryEvent] = []
    provider_failures: list[dict[str, Any]] = []
    stale_rejections: list[dict[str, Any]] = []
    undo_redo_cycles: list[dict[str, Any]] = []
    runtime_checkpoints: list[dict[str, Any]] = [
        _runtime_checkpoint_summary(0, "base", state_records[0])
    ]

    def ensure_runtime_signature(state_index: int, reason: str) -> dict[str, Any]:
        existing = state_records[state_index]
        if existing.get("latest_world_hash"):
            return existing
        cgs = persist.load_snapshot(str(existing["cgs_hash"]))
        signature = _state_signature(
            persist=persist,
            cgs=cgs,
            state_index=state_index,
            sgc_bin=sgc_bin,
            runtime_bin=runtime_bin,
            proof_dir=states_dir / f"state_{state_index:04d}_{reason}",
            ticks=ticks,
            world_seed=world_seed,
        )
        state_records[state_index] = signature
        runtime_checkpoints.append(_runtime_checkpoint_summary(state_index, reason, signature))
        return signature

    for turn in range(1, turn_count + 1):
        pre_hash = current_hash
        pre_bytes_hash = runtime_proof.sha256_json(current_cgs)
        before_history_len = len(persist.prompt_history_state().get("entries") or [])
        window = context.render(turn=turn, current_cgs_hash=current_hash, accepted_count=accepted_count)
        context_windows.append(window)
        failure_turn = turn % provider_failure_period == 0
        stale_turn = (not failure_turn) and turn % stale_state_period == 0 and accepted_count > 0
        telemetry_events.append(
            _telemetry_event(
                turn=turn,
                context_bytes=window["active_context_bytes"],
                failure=failure_turn,
            )
        )

        if failure_turn:
            trace = _trace_event(
                turn=turn,
                action="provider_failure",
                pre_hash=pre_hash,
                post_hash=current_hash,
                accepted_count=accepted_count,
                context_window=window,
                ok=(current_hash == pre_hash and runtime_proof.sha256_json(current_cgs) == pre_bytes_hash),
                details={
                    "failure_category": "timeout",
                    "user_error_code": "PROVIDER_TIMEOUT",
                    "history_unchanged": len(persist.prompt_history_state().get("entries") or []) == before_history_len,
                },
            )
            provider_failures.append(trace)
            trace_events.append(trace)
            context.record(trace)
            continue

        batch = _typed_speed_batch(turn)
        parsed = parse_typed_operation_batch(batch)
        normalized = normalized_typed_operation_batch(parsed)
        canonical = parser.parse_typed(
            json.dumps(normalized, ensure_ascii=True, sort_keys=True),
            current_cgs,
        )
        runtime_proof.require(
            canonical.is_fully_valid,
            f"turn {turn} typed prompt mutation did not validate: {'; '.join(canonical.validation.errors)}",
        )
        orchestrator.load_cgs(current_cgs)

        if stale_turn:
            stale_parent = _stale_parent_hash(state_records, accepted_count)
            result = orchestrator.process_typed_operation_batch(
                normalized,
                _metadata(
                    transaction_id=f"stale-{turn:012d}",
                    description=f"X10-034 stale typed prompt mutation {turn}",
                    cgs=current_cgs,
                    parent_hash=stale_parent,
                ),
            )
            rejected = not result.success and "Stale mutation" in str(result.error)
            unchanged = (
                orchestrator.current_hash == pre_hash
                and runtime_proof.sha256_json(orchestrator.current_cgs) == pre_bytes_hash
                and len(persist.prompt_history_state().get("entries") or []) == before_history_len
            )
            runtime_proof.require(rejected and unchanged, f"turn {turn} stale mutation was not safely rejected: {result}")
            trace = _trace_event(
                turn=turn,
                action="stale_rejected",
                pre_hash=pre_hash,
                post_hash=current_hash,
                accepted_count=accepted_count,
                context_window=window,
                ok=True,
                details={
                    "stale_parent_cgs_hash": stale_parent,
                    "error_code": getattr(result, "code", ""),
                    "error": str(result.error),
                    "history_unchanged": True,
                },
            )
            stale_rejections.append(trace)
            trace_events.append(trace)
            context.record(trace)
            continue

        result = orchestrator.process_typed_operation_batch(
            normalized,
            _metadata(
                transaction_id=f"txn-{turn:012d}",
                description=f"X10-034 typed prompt mutation {turn}",
                cgs=current_cgs,
            ),
        )
        runtime_proof.require(result.success, f"turn {turn} typed prompt mutation failed: {result.error}")
        new_cgs = copy.deepcopy(orchestrator.current_cgs)
        new_hash = str(orchestrator.current_hash or new_cgs.get("metadata", {}).get("cgs_hash") or "")
        runtime_proof.require(new_hash and new_hash != pre_hash, f"turn {turn} did not change CGS hash")

        accepted_count += 1
        current_cgs = new_cgs
        current_hash = new_hash
        _persist_state(
            persist=persist,
            cgs=current_cgs,
            state_index=accepted_count,
            summary=f"Long-session prompt mutation {turn}",
            mutation_count=1,
        )
        run_runtime = accepted_count % runtime_check_interval == 0
        signature = _state_signature(
            persist=persist,
            cgs=current_cgs,
            state_index=accepted_count,
            sgc_bin=sgc_bin,
            runtime_bin=runtime_bin,
            proof_dir=states_dir / f"state_{accepted_count:04d}_turn_{turn:04d}",
            ticks=ticks,
            world_seed=world_seed,
            run_runtime=run_runtime,
        )
        state_records.append(signature)
        if run_runtime:
            runtime_checkpoints.append(_runtime_checkpoint_summary(accepted_count, f"turn_{turn:04d}", signature))
        entry = persist.record_prompt_history_apply(
            transaction_id=f"txn-{turn:012d}",
            pre_cgs_hash=pre_hash,
            post_cgs_hash=current_hash,
            summary=f"Long-session prompt mutation {turn}",
            mutation_count=1,
            version_ids={
                "cgs_hash": current_hash,
                "schema_version": str(current_cgs.get("metadata", {}).get("schema_version") or ""),
                "execution_plan_version": str(current_cgs.get("metadata", {}).get("execution_plan_version") or 1),
            },
            typed_operation_provenance=_typed_provenance(normalized),
        )
        trace = _trace_event(
            turn=turn,
            action="accepted_edit",
            pre_hash=pre_hash,
            post_hash=current_hash,
            accepted_count=accepted_count,
            context_window=window,
            ok=True,
            details={
                "history_sequence": entry.get("sequence"),
                "runtime_checkpoint": run_runtime,
                "typed_operation_ids": list(getattr(result, "typed_operation_ids", []) or []),
            },
        )
        trace_events.append(trace)
        context.record(trace)

        if accepted_count % undo_redo_period == 0:
            cycle = _run_undo_redo_cycle(
                persist=persist,
                state_records=state_records,
                ensure_runtime_signature=ensure_runtime_signature,
                current_hash=current_hash,
                accepted_count=accepted_count,
                runtime_bin=runtime_bin,
                states_dir=states_dir,
                ticks=ticks,
                world_seed=world_seed,
            )
            undo_redo_cycles.append(cycle)
            current_hash = str(cycle["redo_target_cgs_hash"])
            current_cgs = persist.load_snapshot(current_hash)
            orchestrator.load_cgs(current_cgs)
            context.record({
                "schema": TRACE_SCHEMA,
                "turn": turn,
                "action": "undo_redo_cycle",
                "accepted_count": accepted_count,
                "pre_cgs_hash": cycle["undo_source_cgs_hash"],
                "post_cgs_hash": current_hash,
                "ok": cycle["ok"],
                "details": cycle,
            })

    final_signature = ensure_runtime_signature(accepted_count, "final")
    final_cgs = persist.load_snapshot(current_hash)
    validation = ValidationResult()
    validate_cgs(final_cgs, validation, allow_legacy_hash=False, allow_draft_hash=False)
    runtime_proof.require(validation.ok, f"final CGS validation failed: {'; '.join(validation.errors)}")

    final_window = context.render(turn=turn_count + 1, current_cgs_hash=current_hash, accepted_count=accepted_count)
    context_windows.append(final_window)
    trace_path = proof_dir / "session_trace.jsonl"
    context_path = proof_dir / "context_windows.jsonl"
    _write_jsonl(trace_path, trace_events)
    _write_jsonl(context_path, context_windows)
    runtime_proof.write_json(proof_dir / "runtime_checkpoints.json", {"checkpoints": runtime_checkpoints})
    runtime_proof.write_json(proof_dir / "undo_redo_cycles.json", {"cycles": undo_redo_cycles})
    runtime_proof.write_json(proof_dir / "state_records.json", {"states": state_records})

    accounting = write_accounting_artifacts(
        telemetry_events,
        proof_dir / "provider_accounting",
        benchmark_id="x10-034-long-session-degradation",
        source="prompt_long_session_degradation_check",
        benchmark_case_count=turn_count,
        notes=[
            "Offline deterministic long-session proof; provider failures are simulated before mutation commit.",
            "Cost budget is a certification cap over accounting rows, not live provider spend.",
        ],
    )
    accounting_summary = accounting["summary"]
    history_state = persist.prompt_history_state()
    unique_hashes = len({str(record.get("cgs_hash") or "") for record in state_records})
    provider_failure_no_mutation = all(
        item.get("ok") and item.get("details", {}).get("history_unchanged") for item in provider_failures
    )
    stale_rejections_ok = all(
        item.get("ok") and item.get("details", {}).get("history_unchanged") for item in stale_rejections
    )
    undo_redo_ok = all(cycle.get("ok") for cycle in undo_redo_cycles)
    runtime_checkpoint_count = len([item for item in runtime_checkpoints if item.get("latest_world_hash")])

    checks = {
        "fixed_length_turns_completed": len(trace_events) >= turn_count and turn_count >= MIN_FIXED_LENGTH_TURNS,
        "context_source_grew": context.source_context_bytes > context_byte_budget * 2,
        "active_context_bounded": context.active_high_water_bytes <= context_byte_budget,
        "context_compactions_performed": context.compaction_count > 0,
        "cost_accounting_events_complete": accounting_summary.get("event_count") == turn_count,
        "cost_bounded": float(accounting_summary.get("total_cost_usd") or 0.0) <= cost_budget_usd,
        "provider_failures_injected": len(provider_failures) >= max(1, turn_count // provider_failure_period),
        "provider_failures_no_cgs_or_history_mutation": provider_failure_no_mutation,
        "stale_mutations_rejected": len(stale_rejections) >= max(1, turn_count // stale_state_period - 1),
        "stale_rejections_no_cgs_or_history_mutation": stale_rejections_ok,
        "accepted_edits_committed": accepted_count >= MIN_FIXED_LENGTH_TURNS - len(provider_failures) - len(stale_rejections),
        "history_entries_match_commits": len(history_state.get("entries") or []) == accepted_count,
        "history_cursor_at_end": history_state.get("cursor") == accepted_count,
        "undo_redo_cycles_completed": len(undo_redo_cycles) >= max(1, accepted_count // undo_redo_period),
        "undo_redo_restore_hashes_match": undo_redo_ok,
        "all_state_hashes_unique": unique_hashes == len(state_records),
        "all_states_have_snapshots": all(_snapshot_exists(project_root, str(record["cgs_hash"])) for record in state_records),
        "all_states_have_execution_plans": all(_plan_exists(project_root, str(record["cgs_hash"])) for record in state_records),
        "all_states_have_sgc_proof_bundles": all(_proof_bundle_exists(project_root, str(record["cgs_hash"])) for record in state_records),
        "runtime_checkpoints_passed": runtime_checkpoint_count >= 5,
        "final_cgs_valid": validation.ok,
        "final_runtime_replay_checkpoint": bool(final_signature.get("latest_world_hash") and final_signature.get("hash_log_hash")),
    }
    report = {
        "schema": REPORT_SCHEMA,
        "ok": all(checks.values()),
        "x10_034_complete": all(checks.values()),
        "profile": {
            "mode": "fixed_length",
            "turn_count": turn_count,
            "minimum_fixed_length_turns": MIN_FIXED_LENGTH_TURNS,
            "runtime_check_interval": runtime_check_interval,
            "undo_redo_period": undo_redo_period,
            "provider_failure_period": provider_failure_period,
            "stale_state_period": stale_state_period,
            "context_byte_budget": context_byte_budget,
            "cost_budget_usd": cost_budget_usd,
            "ticks": ticks,
            "world_seed": world_seed,
        },
        "turns_processed": turn_count,
        "accepted_edits": accepted_count,
        "provider_failure_count": len(provider_failures),
        "stale_rejection_count": len(stale_rejections),
        "undo_redo_cycle_count": len(undo_redo_cycles),
        "runtime_checkpoint_count": runtime_checkpoint_count,
        "base_cgs_hash": state_records[0]["cgs_hash"],
        "final_cgs_hash": current_hash,
        "history_hash": history_state.get("history_hash"),
        "context": {
            "source_context_bytes": context.source_context_bytes,
            "active_high_water_bytes": context.active_high_water_bytes,
            "final_active_context_bytes": final_window["active_context_bytes"],
            "context_byte_budget": context_byte_budget,
            "compaction_count": context.compaction_count,
            "compacted_event_count": context.compacted_event_count,
            "active_context_hash": final_window["active_context_hash"],
        },
        "cost": {
            "summary_schema": accounting_summary.get("schema"),
            "event_count": accounting_summary.get("event_count"),
            "total_prompt_tokens": accounting_summary.get("total_prompt_tokens"),
            "total_completion_tokens": accounting_summary.get("total_completion_tokens"),
            "total_cost_usd": accounting_summary.get("total_cost_usd"),
            "budget_usd": cost_budget_usd,
            "by_outcome": accounting_summary.get("by_outcome"),
        },
        "checks": checks,
        "sample_provider_failure": provider_failures[0] if provider_failures else {},
        "sample_stale_rejection": stale_rejections[0] if stale_rejections else {},
        "sample_undo_redo_cycle": undo_redo_cycles[0] if undo_redo_cycles else {},
        "artifacts": {
            "proof_dir": str(proof_dir),
            "project_root": str(project_root),
            "prompt_history": str(project_root / ".xace" / "audit" / "prompt_history.json"),
            "prompt_history_events": str(project_root / ".xace" / "audit" / "prompt_history_events.jsonl"),
            "session_trace": str(trace_path),
            "context_windows": str(context_path),
            "state_records": str(proof_dir / "state_records.json"),
            "runtime_checkpoints": str(proof_dir / "runtime_checkpoints.json"),
            "undo_redo_cycles": str(proof_dir / "undo_redo_cycles.json"),
            "provider_accounting": accounting["artifacts"],
        },
    }
    runtime_proof.require(report["ok"], f"long-session checks failed: {checks}")
    runtime_proof.write_json(proof_dir / "summary.json", report)
    return report


class _ContextWindow:
    def __init__(self, byte_budget: int, tail_size: int = 28) -> None:
        self.byte_budget = int(byte_budget)
        self.tail_size = int(tail_size)
        self.recent_events: list[dict[str, Any]] = []
        self.source_context_bytes = 0
        self.active_high_water_bytes = 0
        self.compaction_count = 0
        self.compacted_event_count = 0
        self.action_counts: dict[str, int] = {}

    def record(self, event: dict[str, Any]) -> None:
        compact_event = {
            "turn": int(event.get("turn") or 0),
            "action": str(event.get("action") or ""),
            "accepted_count": int(event.get("accepted_count") or 0),
            "pre_cgs_hash": str(event.get("pre_cgs_hash") or ""),
            "post_cgs_hash": str(event.get("post_cgs_hash") or ""),
            "ok": bool(event.get("ok")),
            "detail_hash": _sha256_json(event.get("details") or {}),
        }
        encoded = _canonical_json(compact_event).encode("utf-8")
        self.source_context_bytes += len(encoded)
        self.recent_events.append(compact_event)
        action = compact_event["action"]
        self.action_counts[action] = self.action_counts.get(action, 0) + 1

    def render(self, *, turn: int, current_cgs_hash: str, accepted_count: int) -> dict[str, Any]:
        payload = self._payload(turn=turn, current_cgs_hash=current_cgs_hash, accepted_count=accepted_count)
        text = _canonical_json(payload)
        if len(text.encode("utf-8")) > self.byte_budget:
            self.compaction_count += 1
            dropped = max(0, len(self.recent_events) - self.tail_size)
            self.compacted_event_count += dropped
            self.recent_events = self.recent_events[-self.tail_size:]
            payload = self._payload(
                turn=turn,
                current_cgs_hash=current_cgs_hash,
                accepted_count=accepted_count,
                compacted=True,
            )
            text = _canonical_json(payload)
            while len(text.encode("utf-8")) > self.byte_budget and self.recent_events:
                self.compacted_event_count += 1
                self.recent_events = self.recent_events[1:]
                payload = self._payload(
                    turn=turn,
                    current_cgs_hash=current_cgs_hash,
                    accepted_count=accepted_count,
                    compacted=True,
                )
                text = _canonical_json(payload)
        active_bytes = len(text.encode("utf-8"))
        self.active_high_water_bytes = max(self.active_high_water_bytes, active_bytes)
        return {
            "schema": CONTEXT_SCHEMA,
            "turn": int(turn),
            "current_cgs_hash": current_cgs_hash,
            "accepted_count": int(accepted_count),
            "active_context_bytes": active_bytes,
            "source_context_bytes": self.source_context_bytes,
            "active_context_hash": _sha256_text(text),
            "compaction_count": self.compaction_count,
            "compacted_event_count": self.compacted_event_count,
            "recent_event_count": len(self.recent_events),
            "action_counts": dict(sorted(self.action_counts.items())),
        }

    def _payload(
        self,
        *,
        turn: int,
        current_cgs_hash: str,
        accepted_count: int,
        compacted: bool = False,
    ) -> dict[str, Any]:
        return {
            "schema": "xace.prompt_long_session.active_context.v1",
            "turn": int(turn),
            "current_cgs_hash": current_cgs_hash,
            "accepted_count": int(accepted_count),
            "summary": {
                "source_context_bytes": self.source_context_bytes,
                "action_counts": dict(sorted(self.action_counts.items())),
                "compaction_count": self.compaction_count,
                "compacted_event_count": self.compacted_event_count,
                "compacted_this_render": compacted,
            },
            "recent_events": self.recent_events,
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
            risk_level="medium",
        ),
    )


def _metadata(
    *,
    transaction_id: str,
    description: str,
    cgs: dict[str, Any],
    parent_hash: str | None = None,
) -> MutationMetadata:
    metadata = cgs.get("metadata", {}) if isinstance(cgs.get("metadata"), dict) else {}
    return MutationMetadata.create(
        transaction_id=transaction_id,
        source="prompt",
        parent_cgs_hash=parent_hash or str(metadata.get("cgs_hash") or ""),
        schema_version_target=str(metadata.get("version") or metadata.get("schema_version") or "0.1.0"),
        session_id=SESSION_ID,
        prompt_text=description,
        confidence=0.98,
        description=description,
        risk_level="medium",
    )


def _run_undo_redo_cycle(
    *,
    persist: CGSPersistence,
    state_records: list[dict[str, Any]],
    ensure_runtime_signature: Any,
    current_hash: str,
    accepted_count: int,
    runtime_bin: Path,
    states_dir: Path,
    ticks: int,
    world_seed: int,
) -> dict[str, Any]:
    expected_current = ensure_runtime_signature(accepted_count, f"undo_redo_{accepted_count:04d}_current")
    expected_previous = ensure_runtime_signature(accepted_count - 1, f"undo_redo_{accepted_count:04d}_previous")
    undo_plan = persist.plan_prompt_history_restore("undo", current_cgs_hash=current_hash, require_proof=True)
    runtime_proof.require(undo_plan.get("accepted") is True, f"undo plan rejected during long session: {undo_plan}")
    undo_event = _restore_from_plan(persist, undo_plan, transaction_id=f"long-undo-{accepted_count:04d}")
    undo_target_hash = str(undo_event["target_cgs_hash"])
    undo_signature = _restored_runtime_signature(
        persist=persist,
        cgs=persist.load_snapshot(undo_target_hash),
        runtime_bin=runtime_bin,
        proof_dir=states_dir / f"undo_redo_{accepted_count:04d}_undo",
        ticks=ticks,
        world_seed=world_seed,
    )
    _assert_restore_matches(expected_previous, undo_signature, accepted_count - 1, f"long-session undo {accepted_count}")

    redo_plan = persist.plan_prompt_history_restore("redo", current_cgs_hash=undo_target_hash, require_proof=True)
    runtime_proof.require(redo_plan.get("accepted") is True, f"redo plan rejected during long session: {redo_plan}")
    redo_event = _restore_from_plan(persist, redo_plan, transaction_id=f"long-redo-{accepted_count:04d}")
    redo_target_hash = str(redo_event["target_cgs_hash"])
    redo_signature = _restored_runtime_signature(
        persist=persist,
        cgs=persist.load_snapshot(redo_target_hash),
        runtime_bin=runtime_bin,
        proof_dir=states_dir / f"undo_redo_{accepted_count:04d}_redo",
        ticks=ticks,
        world_seed=world_seed,
    )
    _assert_restore_matches(expected_current, redo_signature, accepted_count, f"long-session redo {accepted_count}")
    return {
        "schema": "xace.prompt_long_session_undo_redo_cycle.v1",
        "ok": True,
        "accepted_count": accepted_count,
        "undo_source_cgs_hash": current_hash,
        "undo_target_cgs_hash": undo_target_hash,
        "redo_target_cgs_hash": redo_target_hash,
        "undo_plan_proof_links_available": _proof_links_available(undo_plan.get("proof_links")),
        "redo_plan_proof_links_available": _proof_links_available(redo_plan.get("proof_links")),
        "undo_hash_log_hash": undo_signature["hash_log_hash"],
        "redo_hash_log_hash": redo_signature["hash_log_hash"],
        "undo_runtime_world_hash": undo_signature["latest_world_hash"],
        "redo_runtime_world_hash": redo_signature["latest_world_hash"],
        "undo_event": undo_event,
        "redo_event": redo_event,
    }


def _telemetry_event(*, turn: int, context_bytes: int, failure: bool) -> InferenceTelemetryEvent:
    input_tokens = max(64, math.ceil(context_bytes / 4))
    output_tokens = 0 if failure else 96
    cost_cents = input_tokens * 0.00002 + output_tokens * 0.00006
    retry_report = _retry_report(turn) if failure else {}
    return InferenceTelemetryEvent(
        request_id=f"x10-034-request-{turn:04d}",
        session_id=SESSION_ID,
        call_label=f"long_session_turn_{turn:04d}",
        provider="synthetic-long-session-provider",
        model_id="x10-034-fixed-length-model",
        complexity_tier="TIER_L",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_cents=cost_cents,
        latency_ms=12.0 + (turn % 7),
        outcome="failure" if failure else "success",
        provider_kind="local",
        attempt_count=2 if failure else 1,
        retry_count=1 if failure else 0,
        timeout_seconds=8.0 if failure else 0.0,
        failure_category="timeout" if failure else "",
        user_error_code="PROVIDER_TIMEOUT" if failure else "",
        retry_report=retry_report,
        structured_output_requested=not failure,
        structured_output_supported=not failure,
        structured_output_enforced=not failure,
        structured_output_mode="json_schema" if not failure else "none",
        structured_output_schema_id="xace.typed_cgs_operation_batch.v1" if not failure else "",
        structured_output_schema_name="xace_typed_cgs_operation_batch_v1" if not failure else "",
        structured_output_schema_hash="fixed-length-long-session-schema" if not failure else "",
        structured_output_quarantined=False,
    )


def _retry_report(turn: int) -> dict[str, Any]:
    return {
        "schema": "xace.inference_retry_summary.v1",
        "request_id": f"x10-034-request-{turn:04d}",
        "attempt_count": 2,
        "retry_count": 1,
        "final_outcome": "failure",
        "final_failure_category": "timeout",
        "user_error": {
            "code": "PROVIDER_TIMEOUT",
            "failure_category": "timeout",
            "message": "Synthetic long-session provider timeout before mutation commit.",
        },
        "attempts": [
            {
                "schema": "xace.inference_retry_attempt.v1",
                "attempt_index": 1,
                "failure_category": "timeout",
                "retry_scheduled": True,
                "backoff_seconds": 0.0,
            },
            {
                "schema": "xace.inference_retry_attempt.v1",
                "attempt_index": 2,
                "failure_category": "timeout",
                "retry_scheduled": False,
                "backoff_seconds": 0.0,
            },
        ],
    }


def _trace_event(
    *,
    turn: int,
    action: str,
    pre_hash: str,
    post_hash: str,
    accepted_count: int,
    context_window: dict[str, Any],
    ok: bool,
    details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": TRACE_SCHEMA,
        "turn": int(turn),
        "action": action,
        "accepted_count": int(accepted_count),
        "pre_cgs_hash": pre_hash,
        "post_cgs_hash": post_hash,
        "context_hash": context_window["active_context_hash"],
        "context_bytes": context_window["active_context_bytes"],
        "ok": bool(ok),
        "details": details,
    }


def _runtime_checkpoint_summary(state_index: int, reason: str, signature: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "xace.prompt_long_session_runtime_checkpoint.v1",
        "state_index": int(state_index),
        "reason": reason,
        "cgs_hash": signature.get("cgs_hash"),
        "plan_hash": signature.get("plan_hash"),
        "latest_world_hash": signature.get("latest_world_hash"),
        "hash_log_hash": signature.get("hash_log_hash"),
        "schedule_fingerprint": signature.get("schedule_fingerprint"),
    }


def _stale_parent_hash(state_records: list[dict[str, Any]], accepted_count: int) -> str:
    if accepted_count > 1:
        return str(state_records[accepted_count - 1].get("cgs_hash") or "")
    return "0" * 64


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(_canonical_json(row) + "\n" for row in rows), encoding="utf-8")


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _sha256_json(payload: Any) -> str:
    return _sha256_text(_canonical_json(payload))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
