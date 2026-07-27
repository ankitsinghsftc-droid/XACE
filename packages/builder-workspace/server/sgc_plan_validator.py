"""
Validation gate for SGC ExecutionPlan artifacts.

The standalone runtime can load persisted SGC plans as its authoritative
schedule when SGC authority is required. This module performs the acceptance
checks that must pass before Builder stores a compiled plan or the runtime
loader consumes it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_HASH64_RE = re.compile(r"^[0-9a-f]{64}$")
_VALID_PHASES = {"Initialization", "Input", "Simulation", "PostSimulation", "Cleanup"}
_PHASE_ORDINALS = {"0", "1", "2", "3", "4"}
_RUNTIME_ADAPTER_PROTOCOL_VERSION = 1
_LOADABLE_MIGRATION_STATUS = "current"


@dataclass
class SgcPlanValidationError(Exception):
    report: dict[str, Any]

    def __str__(self) -> str:
        issues = self.report.get("issues") or []
        if issues:
            return "; ".join(str(issue) for issue in issues[:3])
        return "SGC ExecutionPlan failed validation."


@dataclass
class SgcExecutionPlanContractError(Exception):
    report: dict[str, Any]

    def __str__(self) -> str:
        issues = self.report.get("issues") or []
        if issues:
            return "; ".join(str(issue) for issue in issues[:3])
        return "SGC persisted ExecutionPlan contract failed validation."


def validate_sgc_plan_for_runtime_load(cgs: dict[str, Any], plan_json: str) -> dict[str, Any]:
    """Validates a compiled ExecutionPlan before Builder accepts it."""
    issues: list[str] = []
    warnings: list[str] = []
    plan = _parse_plan(plan_json, issues)
    meta = cgs.get("metadata", {}) if isinstance(cgs.get("metadata"), dict) else {}
    cgs_hash = str(meta.get("cgs_hash") or "")
    schema_version = str(meta.get("schema_version") or meta.get("version") or "")
    cgs_systems = _extract_systems(cgs)
    cgs_ids = set(cgs_systems)

    scheduled_ids: list[str] = []
    parallel_group_count = 0
    sequential_group_count = 0

    if isinstance(plan, dict):
        try:
            validate_persisted_execution_plan_contract(cgs_hash, plan_json)
        except SgcExecutionPlanContractError as exc:
            issues.extend(str(issue) for issue in exc.report.get("issues", []))
        _validate_plan_header(plan, cgs_hash, schema_version, issues)
        scheduled_ids, parallel_group_count, sequential_group_count = _validate_plan_schedule(
            plan,
            cgs_systems,
            issues,
            warnings,
        )
        declared_ids = plan.get("all_system_ids")
        if not isinstance(declared_ids, list) or not all(isinstance(item, str) for item in declared_ids):
            issues.append("ExecutionPlan all_system_ids must be a string array.")
            declared_set: set[str] = set()
        else:
            declared_set = set(declared_ids)
            if declared_ids != sorted(declared_ids):
                issues.append("ExecutionPlan all_system_ids must be sorted for deterministic lookup.")
        if declared_set != cgs_ids:
            issues.append(
                "ExecutionPlan all_system_ids does not match CGS SystemDefinition IDs "
                f"(missing={sorted(cgs_ids - declared_set)}, extra={sorted(declared_set - cgs_ids)})."
            )
        scheduled_set = set(scheduled_ids)
        if scheduled_set != declared_set:
            issues.append(
                "ExecutionPlan scheduled systems do not match all_system_ids "
                f"(missing={sorted(declared_set - scheduled_set)}, extra={sorted(scheduled_set - declared_set)})."
            )

    rollback_issues = _rollback_compatibility_issues(cgs_systems)
    issues.extend(rollback_issues)

    report = {
        "schema": "xace.sgc.plan_validation.v1",
        "ok": not issues,
        "load_ready": not issues,
        "rollback_compatible": not rollback_issues,
        "mutation_safety_checked": True,
        "runtime_load_status": "strict_loader_ready",
        "cgs_hash": cgs_hash,
        "schema_version": schema_version,
        "system_count": len(cgs_systems),
        "scheduled_system_count": len(set(scheduled_ids)),
        "parallel_group_count": parallel_group_count,
        "sequential_group_count": sequential_group_count,
        "issues": issues,
        "warnings": warnings,
    }
    if issues:
        raise SgcPlanValidationError(report)
    return report


def validate_persisted_execution_plan_contract(
    cgs_hash: str,
    plan_json: str,
    *,
    storage_path: str | Path | None = None,
    require_persistence_metadata: bool = False,
) -> dict[str, Any]:
    """Validates the persisted .xace/execution_plans ExecutionPlan contract."""
    issues: list[str] = []
    plan = _parse_plan(plan_json, issues)
    expected_filename = f"{cgs_hash}.plan.json" if cgs_hash else ""

    if not _HASH64_RE.match(str(cgs_hash or "")):
        issues.append("Persisted ExecutionPlan cgs_hash must be a 64-character lowercase SHA-256 digest.")
    if storage_path is not None:
        _validate_storage_path(Path(storage_path), expected_filename, issues)

    plan_hash = ""
    schema_version = ""
    plan_version: int | None = None
    compiled_hash = ""
    scheduled_ids: list[str] = []
    component_access_system_count = 0
    system_metadata_count = 0
    proof_bundle_path = ""
    adapter_protocol_version: int | None = None
    migration_status = ""

    if isinstance(plan, dict):
        if "kind" in plan and plan.get("kind") != "ExecutionPlan":
            issues.append("ExecutionPlan kind must be 'ExecutionPlan' when the optional kind field is present.")
        schema_version = str(plan.get("schema_version") or "")
        if not schema_version:
            issues.append("ExecutionPlan schema_version is required.")
        raw_plan_version = plan.get("plan_version")
        if not _is_non_negative_int(raw_plan_version) or int(raw_plan_version) < 1:
            issues.append("ExecutionPlan plan_version must be an integer >= 1.")
        else:
            plan_version = int(raw_plan_version)
        raw_adapter_protocol = plan.get("adapter_protocol_version")
        if raw_adapter_protocol is None:
            if require_persistence_metadata:
                issues.append("Persisted ExecutionPlan adapter_protocol_version is required.")
        elif not _is_non_negative_int(raw_adapter_protocol):
            issues.append("Persisted ExecutionPlan adapter_protocol_version must be an integer >= 1.")
        else:
            adapter_protocol_version = int(raw_adapter_protocol)
            if adapter_protocol_version != _RUNTIME_ADAPTER_PROTOCOL_VERSION:
                issues.append(
                    "Persisted ExecutionPlan adapter_protocol_version must match runtime adapter "
                    f"protocol version {_RUNTIME_ADAPTER_PROTOCOL_VERSION}."
                )
        raw_migration_status = plan.get("migration_status")
        if raw_migration_status is None:
            if require_persistence_metadata:
                issues.append("Persisted ExecutionPlan migration_status is required.")
        elif not isinstance(raw_migration_status, str) or not raw_migration_status:
            issues.append("Persisted ExecutionPlan migration_status must be a non-empty string.")
        else:
            migration_status = raw_migration_status
            if migration_status != _LOADABLE_MIGRATION_STATUS:
                issues.append(
                    "Persisted ExecutionPlan migration_status must be 'current' before runtime load."
                )
        if not _is_non_negative_int(plan.get("created_tick")):
            issues.append("ExecutionPlan created_tick must be an integer >= 0.")

        plan_hash = str(plan.get("plan_hash") or "")
        if not _HASH64_RE.match(plan_hash):
            issues.append("ExecutionPlan plan_hash must be a 64-character lowercase SHA-256 digest.")

        compiled_hash = str(plan.get("compiled_from_cgs_hash") or "")
        if not _HASH64_RE.match(compiled_hash):
            issues.append("ExecutionPlan compiled_from_cgs_hash must be a 64-character lowercase SHA-256 digest.")
        elif cgs_hash and compiled_hash != cgs_hash:
            issues.append("ExecutionPlan compiled_from_cgs_hash must match the persisted filename CGS hash.")

        scheduled_ids = _validate_contract_schedule(plan, issues)
        declared_ids = plan.get("all_system_ids")
        if not isinstance(declared_ids, list) or not all(isinstance(item, str) and item for item in declared_ids):
            issues.append("ExecutionPlan all_system_ids must be a non-empty string array or an empty array.")
            declared_set: set[str] = set()
        else:
            declared_set = set(declared_ids)
            if len(declared_ids) != len(declared_set):
                issues.append("ExecutionPlan all_system_ids must not contain duplicates.")
            if declared_ids != sorted(declared_ids):
                issues.append("ExecutionPlan all_system_ids must be sorted for deterministic lookup.")
        scheduled_set = set(scheduled_ids)
        if declared_set != scheduled_set:
            issues.append(
                "ExecutionPlan scheduled systems must match all_system_ids "
                f"(missing={sorted(declared_set - scheduled_set)}, extra={sorted(scheduled_set - declared_set)})."
            )
        component_access_system_count, system_metadata_count, proof_bundle_path = _validate_persistence_metadata(
            plan,
            cgs_hash,
            issues,
            require=require_persistence_metadata,
        )

    report = {
        "schema": "xace.sgc.execution_plan_contract_validation.v1",
        "ok": not issues,
        "cgs_hash": cgs_hash,
        "expected_filename": expected_filename,
        "storage_path": str(storage_path) if storage_path is not None else "",
        "schema_version": schema_version,
        "plan_version": plan_version,
        "adapter_protocol_version": adapter_protocol_version,
        "migration_status": migration_status,
        "plan_hash": plan_hash,
        "compiled_from_cgs_hash": compiled_hash,
        "scheduled_system_count": len(set(scheduled_ids)),
        "component_access_system_count": component_access_system_count,
        "system_metadata_count": system_metadata_count,
        "proof_bundle_path": proof_bundle_path,
        "persistence_metadata_required": require_persistence_metadata,
        "runtime_load_status": "strict_loader_ready",
        "runtime_load_rule": "The strict runtime loader rejects missing, stale, or incompatible persisted SGC plans before tick zero when SGC authority is required.",
        "migration_policy": "Regenerate via SGC for CGS hash/schema/plan-version changes; do not silently migrate or downgrade plan files.",
        "issues": issues,
    }
    if issues:
        raise SgcExecutionPlanContractError(report)
    return report


def _parse_plan(plan_json: str, issues: list[str]) -> dict[str, Any] | None:
    try:
        value = json.loads(plan_json)
    except json.JSONDecodeError as exc:
        issues.append(f"ExecutionPlan is not valid JSON: {exc}")
        return None
    if not isinstance(value, dict):
        issues.append("ExecutionPlan must be a JSON object.")
        return None
    return value


def _validate_storage_path(path: Path, expected_filename: str, issues: list[str]) -> None:
    if not expected_filename:
        return
    if path.name != expected_filename:
        issues.append(f"ExecutionPlan filename must be {expected_filename!r}.")
    parts = [part.replace("\\", "/") for part in path.parts]
    expected_tail = [".xace", "execution_plans", expected_filename]
    if len(parts) < 3 or parts[-3:] != expected_tail:
        issues.append("ExecutionPlan storage path must end with .xace/execution_plans/<cgs_hash>.plan.json.")


def _validate_contract_schedule(plan: dict[str, Any], issues: list[str]) -> list[str]:
    phases = plan.get("phases")
    if not isinstance(phases, dict):
        issues.append("ExecutionPlan phases must be an object keyed by phase ordinal.")
        return []

    scheduled_ids: list[str] = []
    seen_groups: set[str] = set()
    for phase_key, schedule in phases.items():
        phase_key_str = str(phase_key)
        if phase_key_str not in _PHASE_ORDINALS:
            issues.append(f"ExecutionPlan contains invalid phase key {phase_key_str!r}.")
        if not isinstance(schedule, dict):
            issues.append(f"ExecutionPlan phase {phase_key_str} schedule must be an object.")
            continue
        phase_name = schedule.get("phase")
        if not isinstance(phase_name, str) or phase_name not in _VALID_PHASES:
            issues.append(f"ExecutionPlan phase {phase_key_str} must declare a canonical phase name.")
        if not _is_non_negative_int(schedule.get("total_system_count")):
            issues.append(f"ExecutionPlan phase {phase_key_str} total_system_count must be an integer >= 0.")
        groups = schedule.get("groups")
        if not isinstance(groups, list):
            issues.append(f"ExecutionPlan phase {phase_key_str} groups must be an array.")
            continue
        phase_system_count = 0
        for group in groups:
            if not isinstance(group, dict):
                issues.append(f"ExecutionPlan phase {phase_key_str} group must be an object.")
                continue
            group_id = str(group.get("group_id") or "")
            if not group_id:
                issues.append(f"ExecutionPlan phase {phase_key_str} group is missing group_id.")
            elif group_id in seen_groups:
                issues.append(f"ExecutionPlan group_id {group_id!r} appears more than once.")
            seen_groups.add(group_id)
            group_phase = group.get("phase")
            if not isinstance(group_phase, str) or group_phase not in _VALID_PHASES:
                issues.append(f"ExecutionPlan group {group_id or phase_key_str} must declare a canonical phase name.")
            if not isinstance(group.get("parallel"), bool):
                issues.append(f"ExecutionPlan group {group_id or phase_key_str} parallel must be boolean.")
            if not _is_non_negative_int(group.get("execution_index")):
                issues.append(f"ExecutionPlan group {group_id or phase_key_str} execution_index must be an integer >= 0.")
            systems = group.get("systems")
            if not isinstance(systems, list) or not all(isinstance(item, str) and item for item in systems):
                issues.append(f"ExecutionPlan group {group_id or phase_key_str} systems must be non-empty strings.")
                continue
            constraints = group.get("serialization_constraints")
            if not isinstance(constraints, list) or not all(isinstance(item, str) and item for item in constraints):
                issues.append(
                    f"ExecutionPlan group {group_id or phase_key_str} serialization_constraints must be a string array."
                )
            scheduled_ids.extend(systems)
            phase_system_count += len(systems)
        if _is_non_negative_int(schedule.get("total_system_count")) and int(schedule["total_system_count"]) != phase_system_count:
            issues.append(f"ExecutionPlan phase {phase_key_str} total_system_count does not match grouped systems.")

    duplicates = sorted({system_id for system_id in scheduled_ids if scheduled_ids.count(system_id) > 1})
    if duplicates:
        issues.append(f"ExecutionPlan schedules systems more than once: {duplicates}.")
    return scheduled_ids


def _validate_persistence_metadata(
    plan: dict[str, Any],
    cgs_hash: str,
    issues: list[str],
    *,
    require: bool,
) -> tuple[int, int, str]:
    component_access_system_count = 0
    system_metadata_count = 0
    proof_bundle_path = ""
    access_keys: set[str] = set()
    metadata_keys: set[str] = set()

    access_sets = plan.get("component_access_sets")
    if access_sets is None:
        if require:
            issues.append("Persisted ExecutionPlan component_access_sets is required.")
    elif not isinstance(access_sets, dict):
        issues.append("Persisted ExecutionPlan component_access_sets must be an object.")
    else:
        if access_sets.get("schema") != "xace.sgc.component_access_sets.v1":
            issues.append("Persisted ExecutionPlan component_access_sets schema is invalid.")
        _validate_sorted_unique_int_array("component_access_sets.all_reads", access_sets.get("all_reads"), issues)
        _validate_sorted_unique_int_array("component_access_sets.all_writes", access_sets.get("all_writes"), issues)
        _validate_sorted_unique_int_array("component_access_sets.component_ids", access_sets.get("component_ids"), issues)
        by_system = access_sets.get("by_system")
        if not isinstance(by_system, dict):
            issues.append("Persisted ExecutionPlan component_access_sets.by_system must be an object.")
        else:
            access_keys = {str(system_id) for system_id in by_system if str(system_id)}
            component_access_system_count = len(access_keys)
            if list(by_system) != sorted(by_system):
                issues.append("Persisted ExecutionPlan component_access_sets.by_system keys must be sorted.")
            for system_id, access in by_system.items():
                if not isinstance(system_id, str) or not system_id:
                    issues.append("Persisted ExecutionPlan component_access_sets.by_system keys must be non-empty strings.")
                    continue
                if not isinstance(access, dict):
                    issues.append(f"Persisted ExecutionPlan access set for {system_id!r} must be an object.")
                    continue
                _validate_sorted_unique_int_array(
                    f"component_access_sets.by_system.{system_id}.reads",
                    access.get("reads"),
                    issues,
                )
                _validate_sorted_unique_int_array(
                    f"component_access_sets.by_system.{system_id}.writes",
                    access.get("writes"),
                    issues,
                )

    system_metadata = plan.get("system_metadata")
    if system_metadata is None:
        if require:
            issues.append("Persisted ExecutionPlan system_metadata is required.")
    elif not isinstance(system_metadata, dict):
        issues.append("Persisted ExecutionPlan system_metadata must be an object.")
    else:
        if system_metadata.get("schema") != "xace.sgc.system_metadata.v1":
            issues.append("Persisted ExecutionPlan system_metadata schema is invalid.")
        systems = system_metadata.get("systems")
        if not isinstance(systems, dict):
            issues.append("Persisted ExecutionPlan system_metadata.systems must be an object.")
        else:
            metadata_keys = {str(system_id) for system_id in systems if str(system_id)}
            system_metadata_count = len(metadata_keys)
            if list(systems) != sorted(systems):
                issues.append("Persisted ExecutionPlan system_metadata.systems keys must be sorted.")
            for system_id, metadata in systems.items():
                if not isinstance(system_id, str) or not system_id:
                    issues.append("Persisted ExecutionPlan system_metadata.systems keys must be non-empty strings.")
                    continue
                if not isinstance(metadata, dict):
                    issues.append(f"Persisted ExecutionPlan metadata for {system_id!r} must be an object.")
                    continue
                if not isinstance(metadata.get("display_name"), str) or not metadata.get("display_name"):
                    issues.append(f"Persisted ExecutionPlan metadata for {system_id!r} must include display_name.")
                if metadata.get("phase") not in _VALID_PHASES:
                    issues.append(f"Persisted ExecutionPlan metadata for {system_id!r} must declare a canonical phase.")
                if not isinstance(metadata.get("deterministic"), bool):
                    issues.append(f"Persisted ExecutionPlan metadata for {system_id!r} deterministic must be boolean.")
                _validate_sorted_unique_str_array(
                    f"system_metadata.systems.{system_id}.depends_on",
                    metadata.get("depends_on"),
                    issues,
                )
                if not isinstance(metadata.get("description"), str):
                    issues.append(f"Persisted ExecutionPlan metadata for {system_id!r} description must be a string.")
                version = metadata.get("version")
                if not isinstance(version, dict):
                    issues.append(f"Persisted ExecutionPlan metadata for {system_id!r} version must be an object.")
                else:
                    if not _is_non_negative_int(version.get("major")) or int(version.get("major")) < 1:
                        issues.append(f"Persisted ExecutionPlan metadata for {system_id!r} version.major must be >= 1.")
                    if not _is_non_negative_int(version.get("minor")):
                        issues.append(f"Persisted ExecutionPlan metadata for {system_id!r} version.minor must be >= 0.")

    if access_keys and metadata_keys and access_keys != metadata_keys:
        issues.append(
            "Persisted ExecutionPlan component access systems must match system metadata systems "
            f"(missing={sorted(metadata_keys - access_keys)}, extra={sorted(access_keys - metadata_keys)})."
        )

    proof_bundle = plan.get("proof_bundle")
    if proof_bundle is None:
        if require:
            issues.append("Persisted ExecutionPlan proof_bundle is required.")
    elif not isinstance(proof_bundle, dict):
        issues.append("Persisted ExecutionPlan proof_bundle must be an object.")
    else:
        if proof_bundle.get("schema") != "xace.sgc.proof_ref.v1":
            issues.append("Persisted ExecutionPlan proof_bundle schema is invalid.")
        proof_bundle_path = str(proof_bundle.get("path") or "")
        expected_path = f".xace/proof/sgc/{cgs_hash}"
        if proof_bundle_path != expected_path:
            issues.append(f"Persisted ExecutionPlan proof_bundle.path must be {expected_path!r}.")
        compiled_hash = str(proof_bundle.get("compiled_from_cgs_hash") or "")
        if compiled_hash != cgs_hash:
            issues.append("Persisted ExecutionPlan proof_bundle compiled_from_cgs_hash must match the plan CGS hash.")
        proof_plan_hash = str(proof_bundle.get("plan_hash") or "")
        if not _HASH64_RE.match(proof_plan_hash):
            issues.append("Persisted ExecutionPlan proof_bundle.plan_hash must be a 64-character lowercase SHA-256 digest.")
        elif proof_plan_hash != str(plan.get("plan_hash") or ""):
            issues.append("Persisted ExecutionPlan proof_bundle.plan_hash must match plan_hash.")
        for field in ("input_hash", "validation_hash"):
            value = str(proof_bundle.get(field) or "")
            if not _HASH64_RE.match(value):
                issues.append(f"Persisted ExecutionPlan proof_bundle.{field} must be a 64-character lowercase SHA-256 digest.")

    return component_access_system_count, system_metadata_count, proof_bundle_path


def _validate_sorted_unique_int_array(name: str, value: Any, issues: list[str]) -> None:
    if not isinstance(value, list):
        issues.append(f"Persisted ExecutionPlan {name} must be an array.")
        return
    invalid = [item for item in value if not isinstance(item, int) or isinstance(item, bool) or item < 0]
    if invalid:
        issues.append(f"Persisted ExecutionPlan {name} contains invalid component IDs: {invalid!r}.")
    if len(value) != len(set(value)):
        issues.append(f"Persisted ExecutionPlan {name} must not contain duplicates.")
    if value != sorted(value):
        issues.append(f"Persisted ExecutionPlan {name} must be sorted.")


def _validate_sorted_unique_str_array(name: str, value: Any, issues: list[str]) -> None:
    if not isinstance(value, list):
        issues.append(f"Persisted ExecutionPlan {name} must be an array.")
        return
    if not all(isinstance(item, str) and item for item in value):
        issues.append(f"Persisted ExecutionPlan {name} must contain non-empty strings.")
    if len(value) != len(set(value)):
        issues.append(f"Persisted ExecutionPlan {name} must not contain duplicates.")
    if value != sorted(value):
        issues.append(f"Persisted ExecutionPlan {name} must be sorted.")


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validate_plan_header(
    plan: dict[str, Any],
    cgs_hash: str,
    schema_version: str,
    issues: list[str],
) -> None:
    plan_hash = str(plan.get("plan_hash") or "")
    if not _HASH64_RE.match(plan_hash):
        issues.append("ExecutionPlan plan_hash must be a 64-character lowercase SHA-256 digest.")
    compiled_hash = str(plan.get("compiled_from_cgs_hash") or plan.get("cgs_hash") or "")
    if not _HASH64_RE.match(compiled_hash):
        issues.append("ExecutionPlan compiled_from_cgs_hash must be a 64-character lowercase SHA-256 digest.")
    elif cgs_hash and compiled_hash != cgs_hash:
        issues.append("ExecutionPlan compiled_from_cgs_hash does not match current CGS hash.")
    if schema_version and str(plan.get("schema_version") or "") != schema_version:
        issues.append("ExecutionPlan schema_version does not match current CGS schema_version.")
    if not isinstance(plan.get("plan_version"), int) or int(plan.get("plan_version") or 0) < 1:
        issues.append("ExecutionPlan plan_version must be an integer >= 1 for adapter compatibility.")


def _validate_plan_schedule(
    plan: dict[str, Any],
    cgs_systems: dict[str, dict[str, Any]],
    issues: list[str],
    warnings: list[str],
) -> tuple[list[str], int, int]:
    phases = plan.get("phases")
    if not isinstance(phases, dict):
        issues.append("ExecutionPlan phases must be an object keyed by phase ordinal.")
        return [], 0, 0

    scheduled_ids: list[str] = []
    parallel_groups = 0
    sequential_groups = 0
    seen_groups: set[str] = set()
    for phase_key, schedule in phases.items():
        phase_key_str = str(phase_key)
        if phase_key_str not in _PHASE_ORDINALS:
            issues.append(f"ExecutionPlan contains invalid phase key {phase_key_str!r}.")
        if not isinstance(schedule, dict):
            issues.append(f"ExecutionPlan phase {phase_key_str} schedule must be an object.")
            continue
        groups = schedule.get("groups")
        if not isinstance(groups, list):
            issues.append(f"ExecutionPlan phase {phase_key_str} groups must be an array.")
            continue
        for group in groups:
            if not isinstance(group, dict):
                issues.append(f"ExecutionPlan phase {phase_key_str} group must be an object.")
                continue
            group_id = str(group.get("group_id") or "")
            if not group_id:
                issues.append(f"ExecutionPlan phase {phase_key_str} group is missing group_id.")
            elif group_id in seen_groups:
                issues.append(f"ExecutionPlan group_id {group_id!r} appears more than once.")
            seen_groups.add(group_id)
            systems = group.get("systems")
            if not isinstance(systems, list) or not all(isinstance(item, str) and item for item in systems):
                issues.append(f"ExecutionPlan group {group_id or phase_key_str} systems must be non-empty strings.")
                continue
            parallel = bool(group.get("parallel"))
            if parallel:
                parallel_groups += 1
                _validate_parallel_group(group_id, systems, cgs_systems, issues)
            else:
                sequential_groups += 1
            scheduled_ids.extend(systems)
            for system_id in systems:
                cgs_system = cgs_systems.get(system_id)
                if cgs_system is None:
                    issues.append(f"ExecutionPlan schedules unknown system {system_id!r}.")
                    continue
                declared_phase = str(cgs_system.get("phase") or "")
                if declared_phase and declared_phase not in _VALID_PHASES:
                    warnings.append(f"CGS system {system_id!r} uses non-canonical phase label {declared_phase!r}.")

    duplicates = sorted({system_id for system_id in scheduled_ids if scheduled_ids.count(system_id) > 1})
    if duplicates:
        issues.append(f"ExecutionPlan schedules systems more than once: {duplicates}.")
    return scheduled_ids, parallel_groups, sequential_groups


def _validate_parallel_group(
    group_id: str,
    systems: list[str],
    cgs_systems: dict[str, dict[str, Any]],
    issues: list[str],
) -> None:
    for system_id in systems:
        system = cgs_systems.get(system_id, {})
        if system.get("deterministic") is False:
            issues.append(f"Parallel group {group_id!r} contains non-deterministic system {system_id!r}.")
    for left_index, left_id in enumerate(systems):
        left = cgs_systems.get(left_id, {})
        left_reads = set(_int_list(left.get("reads")))
        left_writes = set(_int_list(left.get("writes")))
        for right_id in systems[left_index + 1:]:
            right = cgs_systems.get(right_id, {})
            right_reads = set(_int_list(right.get("reads")))
            right_writes = set(_int_list(right.get("writes")))
            if left_writes & right_writes:
                issues.append(f"Parallel group {group_id!r} has write/write conflict: {left_id} and {right_id}.")
            if (left_writes & right_reads) or (right_writes & left_reads):
                issues.append(f"Parallel group {group_id!r} has read-after-write conflict: {left_id} and {right_id}.")


def _rollback_compatibility_issues(cgs_systems: dict[str, dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    for system_id, system in cgs_systems.items():
        for field in ("reads", "writes"):
            values = system.get(field, [])
            if not isinstance(values, list):
                issues.append(f"CGS system {system_id!r} {field} must be a list of component type IDs.")
                continue
            invalid = [value for value in values if not isinstance(value, int) or value < 0]
            if invalid:
                issues.append(
                    f"CGS system {system_id!r} {field} contains non-integer component IDs: {invalid!r}."
                )
        if system.get("writes") is None:
            issues.append(f"CGS system {system_id!r} must declare writes for rollback compatibility.")
    return issues


def _extract_systems(cgs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    systems: dict[str, dict[str, Any]] = {}
    for system in list(cgs.get("global_systems", [])):
        if isinstance(system, dict):
            _add_system(systems, system)
    for mode in cgs.get("modes", []):
        if not isinstance(mode, dict):
            continue
        for system in mode.get("systems", []):
            if isinstance(system, dict):
                _add_system(systems, system)
    return systems


def _add_system(target: dict[str, dict[str, Any]], system: dict[str, Any]) -> None:
    system_id = str(system.get("id") or "")
    if system_id and system_id not in target:
        normalized = dict(system)
        normalized.setdefault("reads", [])
        normalized.setdefault("writes", [])
        normalized.setdefault("deterministic", True)
        target[system_id] = normalized


def _int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, int)]
