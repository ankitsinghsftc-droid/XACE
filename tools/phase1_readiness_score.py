"""
Build the Phase 1 CGS/SGC/runtime readiness scorecard from proof artifacts.

This tool intentionally grades retained JSON proof output, not documentation
claims. It fails when required proof artifacts are missing, stale in shape, or
internally inconsistent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROOF_ROOT = REPO_ROOT / ".xace" / "proof"
DEFAULT_OUTPUT = REPO_ROOT / "target-codex-readiness" / "phase1_readiness_scorecard.json"
SCORECARD_SCHEMA = "xace.phase1_readiness_scorecard.v1"
MIN_AREA_SCORE = 9.0
HASH_HEX_LENGTH = 64


@dataclass
class Evidence:
    id: str
    label: str
    ok: bool
    path: str = ""
    detail: str = ""


@dataclass
class Area:
    id: str
    label: str
    evidence: list[Evidence] = field(default_factory=list)

    def add(self, evidence_id: str, label: str, ok: bool, path: Path | str | None = None, detail: str = "") -> None:
        self.evidence.append(
            Evidence(
                id=evidence_id,
                label=label,
                ok=bool(ok),
                path=path_for_report(path) if path else "",
                detail=detail,
            )
        )

    @property
    def passed(self) -> int:
        return sum(1 for item in self.evidence if item.ok)

    @property
    def total(self) -> int:
        return len(self.evidence)

    @property
    def score(self) -> float:
        if self.total == 0:
            return 0.0
        return round((self.passed / self.total) * 10.0, 2)

    @property
    def ok(self) -> bool:
        return self.total > 0 and self.score >= MIN_AREA_SCORE and self.passed == self.total

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "ok": self.ok,
            "score_out_of_10": self.score,
            "passed": self.passed,
            "total": self.total,
            "evidence": [item.__dict__ for item in self.evidence],
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Phase 1 readiness scorecard from proof artifacts.")
    parser.add_argument("--proof-root", default=str(DEFAULT_PROOF_ROOT))
    parser.add_argument("--sgc-runtime-root", default="")
    parser.add_argument("--cgs-e2e-root", default="")
    parser.add_argument("--sgc-runtime-summary", default="")
    parser.add_argument("--cgs-e2e-summary", default="")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--min-score", type=float, default=MIN_AREA_SCORE)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    proof_root = Path(args.proof_root).resolve()
    sgc_runtime_root = Path(args.sgc_runtime_root).resolve() if args.sgc_runtime_root else proof_root / "sgc-runtime"
    cgs_e2e_root = Path(args.cgs_e2e_root).resolve() if args.cgs_e2e_root else proof_root / "cgs-e2e"
    sgc_runtime_summary = Path(args.sgc_runtime_summary).resolve() if args.sgc_runtime_summary else None
    cgs_e2e_summary = Path(args.cgs_e2e_summary).resolve() if args.cgs_e2e_summary else None
    output_path = Path(args.output).resolve()

    report = build_scorecard(
        sgc_runtime_root=sgc_runtime_root,
        cgs_e2e_root=cgs_e2e_root,
        sgc_runtime_summary=sgc_runtime_summary,
        cgs_e2e_summary=cgs_e2e_summary,
        output_path=output_path,
        min_score=args.min_score,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print_scorecard(report, output_path)
    return 0 if report["ok"] else 1


def build_scorecard(
    *,
    sgc_runtime_root: Path,
    cgs_e2e_root: Path,
    sgc_runtime_summary: Path | None,
    cgs_e2e_summary: Path | None,
    output_path: Path,
    min_score: float,
) -> dict[str, Any]:
    sgc_summary_path, sgc_summary = load_summary(
        explicit_path=sgc_runtime_summary,
        root=sgc_runtime_root,
        expected_schema="xace.sgc_runtime_proof.v1",
    )
    e2e_summary_path, e2e_summary = load_summary(
        explicit_path=cgs_e2e_summary,
        root=cgs_e2e_root,
        expected_schema="xace.cgs_end_to_end_proof.v1",
    )

    areas = [
        score_cgs_contract(e2e_summary_path, e2e_summary),
        score_sgc_contract(sgc_summary_path, sgc_summary, e2e_summary_path, e2e_summary),
        score_runtime_contract(sgc_summary_path, sgc_summary, e2e_summary_path, e2e_summary),
    ]
    area_dicts = [area.to_dict() for area in areas]
    overall_percent = round(sum(area.score for area in areas) / (len(areas) * 10.0) * 100.0, 2)
    ok = all(area.score >= min_score and area.ok for area in areas)
    return {
        "schema": SCORECARD_SCHEMA,
        "ok": ok,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scope": "phase1_cgs_sgc_runtime_contract",
        "minimum_area_score_out_of_10": min_score,
        "overall_functional_completion_percent": overall_percent,
        "areas": area_dicts,
        "inputs": {
            "sgc_runtime_summary": path_for_report(sgc_summary_path),
            "cgs_e2e_summary": path_for_report(e2e_summary_path),
        },
        "output": path_for_report(output_path),
    }


def score_cgs_contract(summary_path: Path | None, summary: dict[str, Any] | None) -> Area:
    area = Area("cgs_contract", "Canonical CGS Contract")
    area.add("cgs_e2e_summary_present", "CGS E2E proof summary exists", summary is not None, summary_path)
    if not summary:
        return area

    area.add(
        "cgs_e2e_summary_ok",
        "CGS E2E proof summary passed",
        summary.get("schema") == "xace.cgs_end_to_end_proof.v1" and summary.get("ok") is True,
        summary_path,
    )
    cgs_path = artifact_path(summary, "generated_cgs", summary_path)
    cgs = load_json_or_none(cgs_path)
    area.add("generated_cgs_present", "Generated CGS artifact exists", cgs is not None, cgs_path)
    if isinstance(cgs, dict):
        area.add("cgs_metadata_complete", "CGS metadata has name, versions, and hash", cgs_metadata_complete(cgs), cgs_path)
        area.add("cgs_hash_matches_content", "CGS hash matches canonical artifact content", cgs_hash_matches(cgs), cgs_path)
        area.add("cgs_modes_complete", "CGS modes include actors, systems, and rules arrays", cgs_modes_complete(cgs), cgs_path)
        area.add("cgs_system_access_declared", "CGS systems declare deterministic phase/access/dependencies", cgs_systems_complete(cgs), cgs_path)
    else:
        area.add("cgs_metadata_complete", "CGS metadata has name, versions, and hash", False, cgs_path)
        area.add("cgs_hash_matches_content", "CGS hash matches canonical artifact content", False, cgs_path)
        area.add("cgs_modes_complete", "CGS modes include actors, systems, and rules arrays", False, cgs_path)
        area.add("cgs_system_access_declared", "CGS systems declare deterministic phase/access/dependencies", False, cgs_path)

    generation_path = artifact_path(summary, "cgs_generation", summary_path)
    generation = load_json_or_none(generation_path)
    area.add("cgs_generation_artifact", "CGS generation proof artifact exists", generation is not None, generation_path)
    area.add(
        "cgs_generation_matches_hash",
        "CGS generation proof matches CGS hash and has system/component IDs",
        isinstance(generation, dict)
        and generation.get("schema") == "xace.cgs_generation_proof.v1"
        and generation.get("ok") is True
        and generation.get("cgs_hash") == summary.get("cgs_hash")
        and bool(generation.get("system_ids"))
        and bool(generation.get("component_type_ids")),
        generation_path,
    )

    sgc_input_path = artifact_path(summary, "sgc_input", summary_path)
    sgc_input = load_json_or_none(sgc_input_path)
    area.add(
        "sgc_input_from_cgs",
        "SGC input artifact was derived from the CGS hash",
        isinstance(sgc_input, dict)
        and sgc_input.get("schema") == "xace.sgc.cli.input.v1"
        and sgc_input.get("cgs_hash") == summary.get("cgs_hash")
        and isinstance(sgc_input.get("systems"), list)
        and len(sgc_input.get("systems", [])) > 0,
        sgc_input_path,
    )
    return area


def score_sgc_contract(
    sgc_summary_path: Path | None,
    sgc_summary: dict[str, Any] | None,
    e2e_summary_path: Path | None,
    e2e_summary: dict[str, Any] | None,
) -> Area:
    area = Area("sgc_contract", "SGC Execution Plan Contract")
    area.add("sgc_runtime_summary_present", "SGC runtime proof summary exists", sgc_summary is not None, sgc_summary_path)
    if not sgc_summary:
        return area
    area.add(
        "sgc_runtime_summary_ok",
        "SGC runtime proof summary passed",
        sgc_summary.get("schema") == "xace.sgc_runtime_proof.v1" and sgc_summary.get("ok") is True,
        sgc_summary_path,
    )
    checks = sgc_summary.get("checks") if isinstance(sgc_summary.get("checks"), dict) else {}
    area.add("real_sgc_binary_invoked", "Proof invoked the real SGC binary", checks.get("real_sgc_binary_invoked") is True, sgc_summary_path)

    persisted_path = artifact_path(sgc_summary, "persisted_plan_copy", sgc_summary_path)
    persisted_plan = load_json_or_none(persisted_path)
    area.add("persisted_plan_artifact", "Persisted plan artifact exists", persisted_plan is not None, persisted_path)
    if isinstance(persisted_plan, dict):
        area.add("persisted_plan_identity", "Persisted plan has complete identity fields", persisted_plan_identity_ok(persisted_plan, sgc_summary), persisted_path)
        area.add("persisted_plan_metadata", "Persisted plan has access, metadata, and proof bundle", persisted_plan_metadata_ok(persisted_plan), persisted_path)
        area.add("persisted_plan_schedule_matches_ids", "Scheduled systems match all_system_ids", persisted_plan_schedule_matches_ids(persisted_plan), persisted_path)
    else:
        area.add("persisted_plan_identity", "Persisted plan has complete identity fields", False, persisted_path)
        area.add("persisted_plan_metadata", "Persisted plan has access, metadata, and proof bundle", False, persisted_path)
        area.add("persisted_plan_schedule_matches_ids", "Scheduled systems match all_system_ids", False, persisted_path)

    stdout_plan_path = artifact_path(sgc_summary, "sgc_stdout_plan", sgc_summary_path)
    stdout_plan = load_json_or_none(stdout_plan_path)
    area.add(
        "sgc_stdout_plan_matches",
        "SGC stdout plan hash matches persisted plan",
        isinstance(stdout_plan, dict)
        and isinstance(persisted_plan, dict)
        and stdout_plan.get("plan_hash") == persisted_plan.get("plan_hash") == sgc_summary.get("plan_hash"),
        stdout_plan_path,
    )

    persisted_project_path = resolve_summary_path(sgc_summary.get("persisted_plan_path"), sgc_summary_path)
    project_plan = load_json_or_none(persisted_project_path)
    area.add(
        "project_plan_matches_copy",
        "Project execution plan matches retained plan copy",
        isinstance(project_plan, dict) and isinstance(persisted_plan, dict) and project_plan == persisted_plan,
        persisted_project_path,
    )

    proof_metadata = sgc_summary.get("sgc_proof_metadata")
    area.add(
        "sgc_proof_metadata_hashes",
        "SGC proof metadata hashes match plan identity",
        isinstance(proof_metadata, dict)
        and proof_metadata.get("schema") == "xace.sgc.proof_bundle.v1"
        and isinstance(persisted_plan, dict)
        and proof_metadata.get("compiled_from_cgs_hash") == persisted_plan.get("compiled_from_cgs_hash")
        and proof_metadata.get("plan_hash") == persisted_plan.get("plan_hash"),
        sgc_summary_path,
    )

    e2e_checks = e2e_summary.get("checks") if isinstance(e2e_summary, dict) and isinstance(e2e_summary.get("checks"), dict) else {}
    area.add(
        "e2e_real_sgc_compile",
        "E2E proof confirms real SGC compile",
        e2e_checks.get("real_sgc_compile") is True,
        e2e_summary_path,
    )
    return area


def score_runtime_contract(
    sgc_summary_path: Path | None,
    sgc_summary: dict[str, Any] | None,
    e2e_summary_path: Path | None,
    e2e_summary: dict[str, Any] | None,
) -> Area:
    area = Area("runtime_contract", "Runtime Schedule And Replay Contract")
    area.add("sgc_runtime_summary_present", "SGC runtime proof summary exists", sgc_summary is not None, sgc_summary_path)
    if not sgc_summary:
        return area
    checks = sgc_summary.get("checks") if isinstance(sgc_summary.get("checks"), dict) else {}
    area.add("real_runtime_binary_invoked", "Proof invoked the real runtime binary", checks.get("real_runtime_binary_invoked") is True, sgc_summary_path)
    area.add("persisted_sgc_plan_loaded", "Runtime loaded persisted SGC plan", checks.get("persisted_sgc_plan_loaded") is True, sgc_summary_path)
    area.add("tick_hash_replay_match", "Runtime tick hash replay matched", checks.get("tick_hash_replay_match") is True, sgc_summary_path)
    area.add("schedule_replay_match", "Runtime schedule replay matched", checks.get("schedule_replay_match") is True, sgc_summary_path)

    first_path = artifact_path(sgc_summary, "first_schedule_report", sgc_summary_path)
    second_path = artifact_path(sgc_summary, "second_schedule_report", sgc_summary_path)
    first = load_json_or_none(first_path)
    second = load_json_or_none(second_path)
    area.add("first_schedule_report", "First runtime schedule report exists", first is not None, first_path)
    area.add("second_schedule_report", "Second runtime schedule report exists", second is not None, second_path)
    area.add("schedule_reports_valid", "Schedule reports pass schema and identity checks", schedule_report_ok(first, sgc_summary), first_path)
    area.add("schedule_reports_replay_equal", "Schedule reports have matching hashes and snapshots", schedule_reports_equal(first, second), second_path)

    e2e_checks = e2e_summary.get("checks") if isinstance(e2e_summary, dict) and isinstance(e2e_summary.get("checks"), dict) else {}
    control_path = artifact_path(e2e_summary, "control_replay_validation", e2e_summary_path) if e2e_summary else None
    control = load_json_or_none(control_path) if control_path else None
    area.add("e2e_strict_runtime_load", "E2E proof confirms strict persisted runtime load", e2e_checks.get("strict_runtime_load") is True, e2e_summary_path)
    area.add("control_replay_validation", "Runtime control replay validation artifact passed", control_replay_ok(control), control_path)
    return area


def load_summary(
    *,
    explicit_path: Path | None,
    root: Path,
    expected_schema: str,
) -> tuple[Path | None, dict[str, Any] | None]:
    candidates: list[Path]
    if explicit_path:
        candidates = [explicit_path]
    else:
        candidates = sorted(root.glob("*/summary.json"), key=lambda path: (path.parent.name, path.stat().st_mtime), reverse=True)
    for path in candidates:
        data = load_json_or_none(path)
        if isinstance(data, dict) and data.get("schema") == expected_schema:
            return path, data
    return (candidates[0], None) if candidates else (None, None)


def load_json_or_none(path: Path | None) -> Any:
    if path is None or not path.exists() or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def artifact_path(summary: dict[str, Any], key: str, summary_path: Path | None) -> Path | None:
    artifacts = summary.get("artifacts") if isinstance(summary.get("artifacts"), dict) else {}
    return resolve_summary_path(artifacts.get(key), summary_path)


def resolve_summary_path(raw: Any, summary_path: Path | None) -> Path | None:
    if not isinstance(raw, str) or not raw.strip() or summary_path is None:
        return None
    path = Path(raw)
    if path.exists():
        return path
    if not path.is_absolute():
        candidate = (summary_path.parent / path).resolve()
        return candidate
    run_id = summary_path.parent.name
    parts = list(path.parts)
    if run_id in parts:
        suffix = Path(*parts[parts.index(run_id) + 1 :])
        candidate = summary_path.parent / suffix
        if candidate.exists():
            return candidate
    return path


def path_for_report(path: Path | str | None) -> str:
    if not path:
        return ""
    path_obj = Path(path)
    try:
        return path_obj.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path_obj)


def cgs_metadata_complete(cgs: dict[str, Any]) -> bool:
    metadata = cgs.get("metadata")
    if not isinstance(metadata, dict):
        return False
    return (
        isinstance(metadata.get("name"), str)
        and bool(metadata["name"].strip())
        and isinstance(metadata.get("version"), str)
        and isinstance(metadata.get("schema_version"), str)
        and is_lower_hex_hash(metadata.get("cgs_hash"))
    )


def cgs_hash_matches(cgs: dict[str, Any]) -> bool:
    metadata = cgs.get("metadata")
    if not isinstance(metadata, dict) or not is_lower_hex_hash(metadata.get("cgs_hash")):
        return False
    declared = metadata["cgs_hash"]
    stripped = json.loads(json.dumps(cgs))
    stripped.get("metadata", {}).pop("cgs_hash", None)
    return sha256_json(stripped) == declared


def cgs_modes_complete(cgs: dict[str, Any]) -> bool:
    modes = cgs.get("modes")
    if not isinstance(modes, list) or not modes:
        return False
    has_default = False
    for mode in modes:
        if not isinstance(mode, dict):
            return False
        if mode.get("is_default") is True:
            has_default = True
        if not isinstance(mode.get("actors"), list):
            return False
        if not isinstance(mode.get("systems"), list):
            return False
        if not isinstance(mode.get("rules"), list):
            return False
        for actor in mode.get("actors", []):
            if not isinstance(actor, dict) or not isinstance(actor.get("components"), list):
                return False
            for component in actor.get("components", []):
                if not isinstance(component, dict):
                    return False
                if not isinstance(component.get("type_id"), int) or component["type_id"] <= 0:
                    return False
                if not isinstance(component.get("name"), str) or not component["name"].strip():
                    return False
                if not isinstance(component.get("defaults"), dict):
                    return False
    return has_default


def cgs_systems_complete(cgs: dict[str, Any]) -> bool:
    systems = cgs.get("global_systems")
    if not isinstance(systems, list) or not systems:
        return False
    for system in systems:
        if not isinstance(system, dict):
            return False
        if not isinstance(system.get("id"), str) or not system["id"].strip():
            return False
        if not isinstance(system.get("phase"), str) or not system["phase"].strip():
            return False
        if system.get("deterministic") is not True:
            return False
        for field_name in ("reads", "writes", "depends_on"):
            if not isinstance(system.get(field_name), list):
                return False
    return True


def persisted_plan_identity_ok(plan: dict[str, Any], summary: dict[str, Any]) -> bool:
    return (
        plan.get("schema_version") == "0.1.0"
        and isinstance(plan.get("plan_version"), int)
        and plan["plan_version"] >= 1
        and isinstance(plan.get("adapter_protocol_version"), int)
        and plan["adapter_protocol_version"] >= 1
        and plan.get("migration_status") == "current"
        and is_lower_hex_hash(plan.get("plan_hash"))
        and is_lower_hex_hash(plan.get("compiled_from_cgs_hash"))
        and plan.get("plan_hash") == summary.get("plan_hash")
        and plan.get("compiled_from_cgs_hash") == summary.get("cgs_hash")
    )


def persisted_plan_metadata_ok(plan: dict[str, Any]) -> bool:
    access = plan.get("component_access_sets")
    metadata = plan.get("system_metadata")
    proof = plan.get("proof_bundle")
    return (
        isinstance(access, dict)
        and access.get("schema") == "xace.sgc.component_access_sets.v1"
        and isinstance(access.get("by_system"), dict)
        and isinstance(metadata, dict)
        and metadata.get("schema") == "xace.sgc.system_metadata.v1"
        and isinstance(metadata.get("systems"), dict)
        and isinstance(proof, dict)
        and proof.get("schema") == "xace.sgc.proof_ref.v1"
        and proof.get("compiled_from_cgs_hash") == plan.get("compiled_from_cgs_hash")
        and proof.get("plan_hash") == plan.get("plan_hash")
    )


def persisted_plan_schedule_matches_ids(plan: dict[str, Any]) -> bool:
    all_ids = plan.get("all_system_ids")
    if not isinstance(all_ids, list) or sorted(all_ids) != all_ids or len(set(all_ids)) != len(all_ids):
        return False
    scheduled = scheduled_system_ids_from_plan(plan)
    return sorted(scheduled) == all_ids and len(scheduled) == len(all_ids)


def schedule_report_ok(report: Any, summary: dict[str, Any]) -> bool:
    if not isinstance(report, dict):
        return False
    if report.get("schema") != "xace.runtime.schedule_snapshot_report.v1" or report.get("ok") is not True:
        return False
    if report.get("plan_source") != "persisted_sgc":
        return False
    if report.get("plan_hash") != summary.get("plan_hash"):
        return False
    if report.get("cgs_hash") != summary.get("cgs_hash"):
        return False
    if report.get("compiled_from_cgs_hash") != summary.get("cgs_hash"):
        return False
    if not isinstance(report.get("scheduled_system_ids"), list) or not report["scheduled_system_ids"]:
        return False
    if report.get("mismatched_ticks") != []:
        return False
    hash_log = report.get("hash_log")
    if not isinstance(hash_log, list) or len(hash_log) != report.get("tick_count"):
        return False
    if report.get("latest_world_hash") != hash_log[-1].get("world_hash"):
        return False
    snapshots = report.get("snapshots")
    if not isinstance(snapshots, list) or len(snapshots) != report.get("snapshot_count"):
        return False
    for index, snapshot in enumerate(snapshots):
        if not schedule_snapshot_matches_report(snapshot, report, index):
            return False
    return True


def schedule_snapshot_matches_report(snapshot: Any, report: dict[str, Any], index: int) -> bool:
    return (
        isinstance(snapshot, dict)
        and snapshot.get("schema") == "xace.runtime.schedule_snapshot.v1"
        and snapshot.get("tick") == index
        and snapshot.get("source") == "persisted_sgc"
        and snapshot.get("schema_version") == report.get("schema_version")
        and snapshot.get("plan_version") == report.get("plan_version")
        and snapshot.get("plan_hash") == report.get("plan_hash")
        and snapshot.get("cgs_hash") == report.get("cgs_hash")
        and snapshot.get("compiled_from_cgs_hash") == report.get("compiled_from_cgs_hash")
        and snapshot.get("scheduled_system_ids") == report.get("scheduled_system_ids")
        and snapshot.get("groups") == report.get("groups")
        and snapshot.get("system_access") == report.get("system_access")
        and snapshot.get("system_dependencies") == report.get("system_dependencies")
    )


def schedule_reports_equal(first: Any, second: Any) -> bool:
    if not isinstance(first, dict) or not isinstance(second, dict):
        return False
    return (
        first.get("hash_log") == second.get("hash_log")
        and first.get("latest_world_hash") == second.get("latest_world_hash")
        and first.get("snapshots") == second.get("snapshots")
        and first.get("groups") == second.get("groups")
        and first.get("system_access") == second.get("system_access")
        and first.get("system_dependencies") == second.get("system_dependencies")
        and first.get("scheduled_system_ids") == second.get("scheduled_system_ids")
    )


def control_replay_ok(report: Any) -> bool:
    return (
        isinstance(report, dict)
        and report.get("schema") == "xace.cgs_e2e.control_replay_validation.v1"
        and report.get("ok") is True
        and isinstance(report.get("record"), dict)
        and report["record"].get("accepted") is True
        and isinstance(report.get("validate"), dict)
        and report["validate"].get("accepted") is True
        and isinstance(report.get("hash_log"), list)
        and bool(report["hash_log"])
    )


def scheduled_system_ids_from_plan(plan: dict[str, Any]) -> list[str]:
    scheduled: list[str] = []
    phases = plan.get("phases")
    if not isinstance(phases, dict):
        return scheduled
    for phase_key in sorted(phases.keys(), key=lambda key: (0, int(str(key))) if str(key).isdigit() else (1, str(key))):
        phase = phases.get(phase_key)
        if not isinstance(phase, dict) or not isinstance(phase.get("groups"), list):
            continue
        groups = sorted(phase["groups"], key=lambda group: int(group.get("execution_index", 0)))
        for group in groups:
            systems = group.get("systems")
            if isinstance(systems, list):
                scheduled.extend(str(system_id) for system_id in systems)
    return scheduled


def is_lower_hex_hash(value: Any) -> bool:
    return isinstance(value, str) and len(value) == HASH_HEX_LENGTH and all(char in "0123456789abcdef" for char in value)


def sha256_json(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def print_scorecard(report: dict[str, Any], output_path: Path) -> None:
    status = "PASS" if report["ok"] else "FAIL"
    print(
        f"Phase 1 readiness {status}: "
        f"{report['overall_functional_completion_percent']}% "
        f"(minimum area score {report['minimum_area_score_out_of_10']}/10)"
    )
    for area in report["areas"]:
        area_status = "PASS" if area["ok"] else "FAIL"
        print(f"- {area['label']}: {area_status} {area['score_out_of_10']}/10")
        for evidence in area["evidence"]:
            if evidence["path"]:
                mark = "ok" if evidence["ok"] else "fail"
                print(f"  - {mark}: {evidence['label']} -> {evidence['path']}")
    print(f"scorecard: {path_for_report(output_path)}")


if __name__ == "__main__":
    raise SystemExit(main())
