#!/usr/bin/env python3
"""Retained X10-052 proof for exportable debug reports."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "tools"

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from security_secret_scan import scan_paths  # noqa: E402


REPORT_SCHEMA = "xace.exportable_debug_report_check_report.v1"
REPORT_ID = "x10-052-debug-report"
FAKE_KEY = "sk-xace-debug-report-secret-123456"
FAKE_BEARER = "Bearer xaceDebugReportBearer123456"
FAKE_GOOGLE = "AIza" + "d" * 24
REQUIRED_SECTIONS = {
    "debugger_state",
    "replay_inputs",
    "hash_logs",
    "sgc_plan",
    "mutation_log",
    "adapter_feedback",
}


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def build_fixture(root: Path) -> Path:
    if root.exists():
        _safe_rmtree(root)
    project_dir = root / "debug-report-fixture-project"
    project_dir.mkdir(parents=True, exist_ok=True)

    cgs = {
        "schema": "xace.cgs.export.v1",
        "metadata": {
            "name": "Debug Report Fixture",
            "schema_version": "1.0.0",
            "execution_plan_version": 1,
            "adapter_protocol_version": 1,
        },
        "components": [
            {
                "id": "Health",
                "fields": [
                    {"name": "hp", "type": "int", "default": 100},
                ],
            }
        ],
        "systems": [
            {
                "id": "CombatDamageSystem",
                "phase": "simulation",
                "reads": ["Health"],
                "writes": ["Health"],
                "depends_on": [],
                "deterministic": True,
            }
        ],
        "events": [{"id": "DamageApplied", "fields": [{"name": "amount", "type": "int"}]}],
        "inputs": [{"id": "AttackPressed", "fields": [{"name": "pressed", "type": "bool"}]}],
        "assets": [{"id": "fx_hit", "kind": "vfx", "semantic": "combat.hit"}],
        "save": {"slots": ["slot_autosave"], "components": ["Health"]},
        "network": {"topology": "host_client_lockstep", "inputs": ["AttackPressed"]},
    }
    cgs_path = project_dir / "game.cgs.json"
    _write_json(cgs_path, cgs)
    cgs_hash = _file_sha256(cgs_path)

    manifest = {
        "schema_version": "0.1.0",
        "project_id": "debug_report_fixture",
        "name": "Debug Report Fixture",
        "engine_type": "godot",
        "template_id": "blank_3d",
        "cgs_path": "game.cgs.json",
        "asset_root": "assets",
    }
    _write_json(project_dir / "xace.project.json", manifest)

    hashes = [_hash_for(f"world-{tick}") for tick in range(4)]
    debugger_state = {
        "schema": "xace.builder.tick_debugger.state.v1",
        "selected_tick": 2,
        "selected_world_hash": hashes[2],
        "selected_snapshot_key": "tick-000002",
        "timeline_cursor": {"tick": 2, "world_hash": hashes[2]},
        "hash_timeline": [
            {"tick": tick, "world_hash": hashes[tick], "source": "runtime_hash_log"}
            for tick in range(4)
        ],
        "breakpoints": [
            {"id": "bp-health-low", "kind": "component_value", "armed": True, "last_hit_tick": 2}
        ],
        "causality_trace_id": "trace-combat-hit-0002",
        "rng_trace_summary": {
            "visible_call_count": 2,
            "illegal_rng_blocked": True,
            "legal_replay_hash_match": True,
        },
    }
    _write_json(project_dir / ".xace" / "debugger" / "debugger_state.json", debugger_state)

    replay_inputs = {
        "schema": "xace.replay.inputs.v1",
        "records": [
            {
                "tick": 1,
                "player_id": "host",
                "sequence": 1,
                "actions": [{"id": "AttackPressed", "pressed": True}],
            },
            {
                "tick": 2,
                "player_id": "client_01",
                "sequence": 2,
                "actions": [{"id": "AttackPressed", "pressed": False}],
            },
        ],
    }
    _write_json(project_dir / ".xace" / "replay" / "replay_inputs.json", replay_inputs)

    hash_log = {
        "schema": "xace.runtime.hash_log.v1",
        "hash_log": [
            {"tick": tick, "world_hash": hashes[tick], "schedule_fingerprint": _hash_for("schedule")[:32]}
            for tick in range(4)
        ],
    }
    _write_json(project_dir / ".xace" / "runtime" / "hash_log.json", hash_log)

    sgc_plan = {
        "schema": "xace.sgc.execution_plan.v1",
        "plan_hash": _hash_for("fixture-plan"),
        "compiled_from_cgs_hash": cgs_hash,
        "schema_version": "1.0.0",
        "plan_version": 1,
        "adapter_protocol_version": 1,
        "migration_status": "current",
        "phases": [
            {"phase": "simulation", "systems": ["CombatDamageSystem"], "parallel": False}
        ],
        "component_access_sets": {
            "schema": "xace.sgc.component_access_sets.v1",
            "systems": {
                "CombatDamageSystem": {"reads": ["Health"], "writes": ["Health"]}
            },
        },
        "system_metadata": {
            "schema": "xace.sgc.system_metadata.v1",
            "systems": [
                {
                    "id": "CombatDamageSystem",
                    "phase": "simulation",
                    "deterministic": True,
                    "version": "1.0.0",
                }
            ],
        },
        "proof_bundle": {"path": f".xace/proof/sgc/{cgs_hash}"},
    }
    _write_json(project_dir / ".xace" / "execution_plans" / f"{cgs_hash}.plan.json", sgc_plan)

    mutation_records = [
        {
            "schema": "xace.mutation.audit.v1",
            "transaction_id": "tx-debug-001",
            "tick": 1,
            "operation": "add_component_field",
            "pre_cgs_hash": _hash_for("pre"),
            "post_cgs_hash": cgs_hash,
            "proof_links": {"execution_plan": {"available": True, "path": f".xace/execution_plans/{cgs_hash}.plan.json"}},
            "note": f"redaction canary {FAKE_KEY}",
        },
        {
            "schema": "xace.mutation.audit.v1",
            "transaction_id": "tx-debug-002",
            "tick": 2,
            "operation": "tune_damage_amount",
            "rollback_available": True,
            "authorization": FAKE_BEARER,
        },
    ]
    _write_jsonl(project_dir / ".xace" / "audit" / "mutations.jsonl", mutation_records)

    adapter_feedback = [
        {
            "schema": "xace.adapter.feedback.v1",
            "tick": 2,
            "engine": "godot",
            "feedback_type": "collision_entered",
            "entity_id": 1001,
            "payload": {
                "semantic": "combat.hit",
                "component": "Health",
                "api_key": FAKE_KEY,
            },
        },
        {
            "schema": "xace.adapter.feedback.v1",
            "tick": 3,
            "engine": "godot",
            "feedback_type": "asset_binding_status",
            "payload": {"asset_id": "fx_hit", "status": "resolved", "google_key_shape": FAKE_GOOGLE},
        },
    ]
    _write_jsonl(project_dir / ".xace" / "logs" / "adapter_feedback.jsonl", adapter_feedback)

    return project_dir


def run_export_command(project_dir: Path, report_path: Path, artifact_dir: Path) -> dict[str, Any]:
    command = [
        sys.executable,
        "tools/export_debug_report.py",
        "--project",
        str(project_dir),
        "--output",
        str(report_path),
        "--artifact-dir",
        str(artifact_dir),
        "--report-id",
        REPORT_ID,
        "--overwrite",
        "--json",
    ]
    completed = run(command, ROOT)
    payload = _json_from_stdout(completed.stdout)
    return {
        "name": "export_debug_report_command",
        "ok": completed.returncode == 0 and bool(payload.get("ok")),
        "returncode": completed.returncode,
        "stdout_tail": _tail(completed.stdout),
        "stderr_tail": _tail(completed.stderr),
        "command": command,
        "payload": _export_payload_summary(payload),
    }


def run_fresh_checkout_validation(report_path: Path, fresh_checkout: Path) -> dict[str, Any]:
    if fresh_checkout.exists():
        _safe_rmtree(fresh_checkout)
    fresh_checkout.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "tools/export_debug_report.py",
        "--validate",
        "--input",
        str(report_path),
        "--fresh-checkout",
        str(fresh_checkout),
        "--json",
    ]
    completed = run(command, ROOT)
    payload = _json_from_stdout(completed.stdout)
    summary_path = fresh_checkout / "loaded_debug_report_summary.json"
    return {
        "name": "fresh_checkout_round_trip",
        "ok": completed.returncode == 0 and bool(payload.get("ok")) and summary_path.exists(),
        "returncode": completed.returncode,
        "stdout_tail": _tail(completed.stdout),
        "stderr_tail": _tail(completed.stderr),
        "command": command,
        "payload": payload,
        "summary_path": str(summary_path),
        "summary_exists": summary_path.exists(),
    }


def validate_report_contents(report_path: Path, artifact_dir: Path, export_check: dict[str, Any], round_trip: dict[str, Any]) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    sections = report.get("sections") if isinstance(report.get("sections"), dict) else {}
    section_names = set(sections)
    artifact_manifest = artifact_dir / "debug_report_artifact_manifest.json"
    artifact_sections = {
        path.stem
        for path in (artifact_dir / "sections").glob("*.json")
        if path.is_file()
    } if (artifact_dir / "sections").exists() else set()
    text = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    findings = scan_paths([report_path, artifact_dir], repo_root=ROOT) if report_path.exists() else []
    validation = round_trip.get("payload") if isinstance(round_trip.get("payload"), dict) else {}
    section_results = validation.get("section_results") if isinstance(validation.get("section_results"), dict) else {}
    required_loaded = {
        section: bool(section_results.get(section, {}).get("ok"))
        for section in REQUIRED_SECTIONS
    }
    return {
        "name": "report_contents_artifacts_and_redaction",
        "ok": (
            bool(export_check.get("ok"))
            and bool(round_trip.get("ok"))
            and report.get("schema") == "xace.exportable_debug_report.v1"
            and report.get("debug_report_id") == REPORT_ID
            and REQUIRED_SECTIONS.issubset(section_names)
            and REQUIRED_SECTIONS.issubset(artifact_sections)
            and artifact_manifest.exists()
            and all(required_loaded.values())
            and "[REDACTED_SECRET]" in text
            and FAKE_KEY not in text
            and FAKE_BEARER not in text
            and FAKE_GOOGLE not in text
            and not findings
        ),
        "report_path": str(report_path),
        "report_sha256": _file_sha256(report_path) if report_path.exists() else "",
        "artifact_manifest": str(artifact_manifest),
        "artifact_manifest_exists": artifact_manifest.exists(),
        "section_names": sorted(section_names),
        "artifact_sections": sorted(artifact_sections),
        "fresh_checkout_sections_loaded": required_loaded,
        "redaction_marker_present": "[REDACTED_SECRET]" in text,
        "raw_secret_present": any(secret in text for secret in (FAKE_KEY, FAKE_BEARER, FAKE_GOOGLE)),
        "secret_scan_findings": [
            {
                "path": finding.path,
                "line": finding.line,
                "column": finding.column,
                "kind": finding.kind,
                "preview": finding.preview,
            }
            for finding in findings[:20]
        ],
    }


def build_report(output: Path, artifact_dir: Path) -> dict[str, Any]:
    fixture_root = artifact_dir / "fixture"
    project_dir = build_fixture(fixture_root)
    report_path = artifact_dir / "debug_report.json"
    exported_artifacts = artifact_dir / "exported_artifacts"
    fresh_checkout = artifact_dir / "fresh_checkout"

    export_check = run_export_command(project_dir, report_path, exported_artifacts)
    round_trip = (
        run_fresh_checkout_validation(report_path, fresh_checkout)
        if export_check["ok"]
        else {
            "name": "fresh_checkout_round_trip",
            "ok": False,
            "error": "debug report export failed",
        }
    )
    contents = (
        validate_report_contents(report_path, exported_artifacts, export_check, round_trip)
        if export_check["ok"]
        else {
            "name": "report_contents_artifacts_and_redaction",
            "ok": False,
            "error": "debug report export failed",
        }
    )
    checks = [export_check, round_trip, contents]
    return {
        "schema": REPORT_SCHEMA,
        "task": "X10-052",
        "x10_052_complete": all(check.get("ok") for check in checks),
        "debug_report_id": REPORT_ID,
        "debug_report_path": str(report_path),
        "debug_report_sha256": _file_sha256(report_path) if report_path.exists() else "",
        "artifact_dir": str(exported_artifacts),
        "fresh_checkout_dir": str(fresh_checkout),
        "checks": checks,
    }


def _json_from_stdout(stdout: str) -> dict[str, Any]:
    try:
        loaded = json.loads(stdout)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _export_payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
    artifact_manifest = payload.get("artifact_manifest") if isinstance(payload.get("artifact_manifest"), dict) else {}
    return {
        "schema": payload.get("schema"),
        "ok": payload.get("ok"),
        "debug_report_id": payload.get("debug_report_id"),
        "required_sections_present": {
            section: section in sections
            for section in REQUIRED_SECTIONS
        },
        "section_digests": payload.get("section_digests") if isinstance(payload.get("section_digests"), dict) else {},
        "artifact_manifest_path": artifact_manifest.get("path", ""),
        "redaction": payload.get("redaction") if isinstance(payload.get("redaction"), dict) else {},
    }


def _tail(text: str, limit: int = 4000) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[-limit:]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_for(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_rmtree(path: Path) -> None:
    resolved = path.resolve()
    root = ROOT.resolve()
    if root not in resolved.parents:
        raise RuntimeError(f"refusing to remove path outside repo: {resolved}")
    shutil.rmtree(resolved)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test X10-052 exportable debug reports.")
    parser.add_argument("--output", default="target-codex-task52-debug-report/report.json")
    parser.add_argument("--artifact-dir", default="target-codex-task52-debug-report/artifacts")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    output = (ROOT / args.output).resolve()
    artifact_dir = (ROOT / args.artifact_dir).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    report = build_report(output, artifact_dir)
    _write_json(output, report)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        status = "PASS" if report["x10_052_complete"] else "FAIL"
        print(f"{status}: wrote {output}")
    return 0 if report["x10_052_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
