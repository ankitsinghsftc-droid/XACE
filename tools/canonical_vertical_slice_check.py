#!/usr/bin/env python3
"""Retained X10-063 proof for the canonical cross-engine vertical slice.

The proof verifies the versioned fixture consumed by installed-engine tasks:

- committed CGS export hash is valid;
- vertical-slice manifest pins the CGS artifact and required feature map;
- one CGS-owned slice covers movement, combat, health, inventory, save/load,
  rollback, replay, semantic bindings, animation, audio, VFX, and
  network-ready input;
- linked assets have matching SHA-256 values;
- runtime/save/adapter-package asset preflight passes for Godot, Unity, Unreal;
- semantic bindings are resolved or documented fallback for every engine.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
ASSET_REGISTRY_ROOT = REPO_ROOT / "packages" / "asset-registry"
sys.path.insert(0, str(REPO_ROOT / "tools"))
sys.path.insert(0, str(ASSET_REGISTRY_ROOT))

import cgs_schema_validate  # noqa: E402
from asset_reference_preflight import AssetPreflightPhase, validate_all_asset_handoffs  # noqa: E402
from semantic_binding_status import evaluate_semantic_binding_status  # noqa: E402


REPORT_SCHEMA = "xace.canonical_vertical_slice_check_report.v1"
MANIFEST_SCHEMA = "xace.canonical_vertical_slice_manifest.v1"
SLICE_SCHEMA = "xace.canonical_vertical_slice.v1"
FIXTURE_ROOT = REPO_ROOT / "projects" / "canonical_cross_engine_vertical_slice"
CGS_FILENAME = "game.cgs.json"
MANIFEST_FILENAME = "xace.vertical_slice_manifest.json"
ENGINES = ("godot", "unity", "unreal")
REQUIRED_FEATURES = (
    "movement",
    "combat",
    "health",
    "inventory",
    "save_load",
    "rollback",
    "replay",
    "semantic_bindings",
    "animation",
    "audio",
    "vfx",
    "network_ready_input",
)
ASSET_PREFLIGHT_PHASES = tuple(phase.value for phase in AssetPreflightPhase)


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    evidence: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "ok": self.ok,
            "detail": self.detail,
        }
        if self.evidence is not None:
            payload["evidence"] = dict(self.evidence)
        return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the X10-063 canonical vertical slice proof.")
    parser.add_argument("--fixture-root", type=Path, default=FIXTURE_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "target-codex-task63-canonical-vertical-slice" / "report.json",
    )
    parser.add_argument("--json", action="store_true", help="Print report JSON.")
    args = parser.parse_args(argv)

    try:
        report = run_check(fixture_root=args.fixture_root.resolve(), output_path=args.output.resolve())
    except Exception as exc:  # noqa: BLE001 - proof tools should surface one actionable failure.
        print(f"canonical vertical slice check failed: {exc}", file=sys.stderr)
        return 1

    rendered = canonical_json(report, indent=2)
    if args.json:
        print(rendered)
    else:
        status = "PASSED" if report["ok"] else "FAILED"
        print(f"canonical vertical slice check {status}: {report['checks_passed']}/{report['checks_total']} checks")
    return 0 if report["ok"] else 1


def run_check(*, fixture_root: Path, output_path: Path) -> dict[str, Any]:
    cgs_path = fixture_root / CGS_FILENAME
    manifest_path = fixture_root / MANIFEST_FILENAME
    cgs = read_json(cgs_path)
    manifest = read_json(manifest_path)

    cgs_validation = cgs_schema_validate.validate_file(cgs_path)
    indexes = build_indexes(cgs)
    asset_preflight_reports = validate_all_asset_handoffs(
        cgs,
        project_root=fixture_root,
        engines=ENGINES,
        phases=ASSET_PREFLIGHT_PHASES,
    )
    semantic_status = evaluate_semantic_binding_status(
        cgs,
        project_root=fixture_root,
        engines=ENGINES,
    ).to_dict()

    checks = [
        check_cgs_committed(cgs_validation),
        check_manifest_identity(manifest, cgs, cgs_path),
        check_required_feature_manifest(manifest),
        check_required_feature_cgs(cgs, indexes),
        check_single_slice_boundary(cgs, manifest),
        check_network_input_profile(cgs, indexes),
        check_save_rollback_replay_metadata(cgs),
        check_asset_hashes(cgs, fixture_root),
        check_asset_preflight_matrix(asset_preflight_reports),
        check_semantic_binding_matrix(semantic_status),
    ]
    ok = all(check.ok for check in checks)
    report = {
        "schema": REPORT_SCHEMA,
        "task": "X10-063",
        "ok": ok,
        "x10_063_complete": ok,
        "fixture_root": str(fixture_root.relative_to(REPO_ROOT)),
        "engines": list(ENGINES),
        "required_features": list(REQUIRED_FEATURES),
        "cgs": {
            "path": str(cgs_path.relative_to(REPO_ROOT)),
            "canonical_cgs_hash": str((cgs.get("metadata") or {}).get("cgs_hash", "")),
            "file_sha256": sha256_file(cgs_path),
            "validator": {
                "valid": cgs_validation.ok,
                "declared_hash": cgs_validation.declared_hash,
                "computed_hash": cgs_validation.computed_hash,
                "warnings": list(cgs_validation.warnings),
                "errors": list(cgs_validation.errors),
            },
        },
        "manifest": {
            "path": str(manifest_path.relative_to(REPO_ROOT)),
            "schema": manifest.get("schema"),
            "version": manifest.get("version"),
            "sha256": sha256_file(manifest_path),
        },
        "asset_preflight": summarize_asset_preflight(asset_preflight_reports),
        "semantic_binding_status": summarize_semantic_status(semantic_status),
        "indexes": {
            "actor_count": len(indexes["actors"]),
            "component_count": len(indexes["components"]),
            "system_count": len(indexes["systems"]),
            "semantic_event_count": len(indexes["semantic_events"]),
            "asset_count": len(indexes["assets"]),
            "semantic_binding_count": len(indexes["bindings"]),
        },
        "checks_passed": sum(1 for check in checks if check.ok),
        "checks_total": len(checks),
        "checks": [check.to_dict() for check in checks],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(canonical_json(report, indent=2) + "\n", encoding="utf-8")
    if not ok:
        failed = ", ".join(check.name for check in checks if not check.ok)
        raise ValueError(f"checks failed: {failed}")
    return report


def check_cgs_committed(result: cgs_schema_validate.ValidationResult) -> Check:
    return Check(
        "committed_cgs_export_hash",
        result.ok and result.declared_hash == result.computed_hash and not result.warnings,
        "CGS export validates without draft/legacy hash allowances.",
        {
            "declared_hash": result.declared_hash,
            "computed_hash": result.computed_hash,
            "warnings": list(result.warnings),
            "errors": list(result.errors),
        },
    )


def check_manifest_identity(manifest: Mapping[str, Any], cgs: Mapping[str, Any], cgs_path: Path) -> Check:
    metadata = as_mapping(cgs.get("metadata"))
    manifest_cgs = as_mapping(manifest.get("cgs"))
    required_ok = (
        manifest.get("schema") == MANIFEST_SCHEMA
        and manifest.get("slice_id") == "x10_063_canonical_cross_engine_vertical_slice"
        and manifest.get("version") == "0.1.0"
        and manifest.get("target_engines") == list(ENGINES)
        and manifest_cgs.get("path") == CGS_FILENAME
        and manifest_cgs.get("cgs_hash") == metadata.get("cgs_hash")
        and manifest_cgs.get("file_sha256") == sha256_file(cgs_path)
    )
    return Check(
        "versioned_fixture_manifest_identity",
        required_ok,
        "Manifest pins slice id, version, target engines, CGS path, CGS hash, and CGS file SHA-256.",
        {
            "schema": manifest.get("schema"),
            "slice_id": manifest.get("slice_id"),
            "version": manifest.get("version"),
            "target_engines": manifest.get("target_engines"),
            "manifest_cgs_hash": manifest_cgs.get("cgs_hash"),
            "metadata_cgs_hash": metadata.get("cgs_hash"),
        },
    )


def check_required_feature_manifest(manifest: Mapping[str, Any]) -> Check:
    required = list(REQUIRED_FEATURES)
    declared = manifest.get("required_features")
    feature_map = as_mapping(manifest.get("feature_map"))
    missing = [feature for feature in required if feature not in feature_map]
    empty = [
        feature
        for feature in required
        if feature in feature_map and not has_feature_references(as_mapping(feature_map.get(feature)))
    ]
    ok = declared == required and not missing and not empty
    return Check(
        "manifest_required_feature_map",
        ok,
        "Version manifest declares every required Task 63 feature with concrete systems/components/events/assets/bindings.",
        {"missing": missing, "empty": empty, "declared": declared},
    )


def check_required_feature_cgs(cgs: Mapping[str, Any], indexes: Mapping[str, set[str]]) -> Check:
    feature_map = as_mapping(as_mapping(cgs.get("vertical_slice")).get("feature_coverage"))
    missing_features: list[str] = []
    missing_refs: list[str] = []
    for feature in REQUIRED_FEATURES:
        feature_record = as_mapping(feature_map.get(feature))
        if not feature_record:
            missing_features.append(feature)
            continue
        missing_refs.extend(validate_feature_refs(feature, feature_record, indexes))
    return Check(
        "cgs_owned_required_feature_coverage",
        not missing_features and not missing_refs,
        "CGS vertical_slice.feature_coverage maps every Task 63 feature to existing CGS systems/components/events/assets/bindings.",
        {"missing_features": missing_features, "missing_refs": missing_refs},
    )


def check_single_slice_boundary(cgs: Mapping[str, Any], manifest: Mapping[str, Any]) -> Check:
    vertical_slice = as_mapping(cgs.get("vertical_slice"))
    ok = (
        vertical_slice.get("schema") == SLICE_SCHEMA
        and vertical_slice.get("id") == manifest.get("slice_id")
        and vertical_slice.get("version") == manifest.get("version")
        and vertical_slice.get("target_engines") == list(ENGINES)
        and vertical_slice.get("deterministic") is True
        and vertical_slice.get("tick_rate_hz") == 60
    )
    return Check(
        "single_cgs_owned_slice_boundary",
        ok,
        "One deterministic CGS-owned slice is named, versioned, and targeted at Godot/Unity/Unreal.",
        {
            "schema": vertical_slice.get("schema"),
            "id": vertical_slice.get("id"),
            "version": vertical_slice.get("version"),
            "target_engines": vertical_slice.get("target_engines"),
            "deterministic": vertical_slice.get("deterministic"),
        },
    )


def check_network_input_profile(cgs: Mapping[str, Any], indexes: Mapping[str, set[str]]) -> Check:
    vertical_slice = as_mapping(cgs.get("vertical_slice"))
    network_profile = as_mapping(vertical_slice.get("network_profile"))
    input_profiles = [item for item in cgs.get("input_profiles", []) if isinstance(item, Mapping)]
    action_ids = {
        str(action.get("id"))
        for profile in input_profiles
        for action in profile.get("actions", [])
        if isinstance(action, Mapping) and action.get("id")
    }
    expected_actions = {"move", "attack", "pickup"}
    ok = (
        network_profile.get("topology") == "host_client_lockstep"
        and network_profile.get("authority") == "host_authoritative"
        and network_profile.get("network_ready_input") is True
        and network_profile.get("requires_input_synchroniser") is True
        and "NetworkInputSyncSystem" in indexes["systems"]
        and expected_actions.issubset(action_ids)
    )
    return Check(
        "network_ready_input_contract",
        ok,
        "Slice includes lockstep input metadata, InputSynchroniser requirement, network sync system, and gameplay input actions.",
        {
            "network_profile": dict(network_profile),
            "action_ids": sorted(action_ids),
            "expected_actions": sorted(expected_actions),
        },
    )


def check_save_rollback_replay_metadata(cgs: Mapping[str, Any]) -> Check:
    vertical_slice = as_mapping(cgs.get("vertical_slice"))
    save_load = as_mapping(vertical_slice.get("save_load"))
    rollback = as_mapping(vertical_slice.get("rollback"))
    replay = as_mapping(vertical_slice.get("replay"))
    ok = (
        save_load.get("schema") == "xace.save.slot.v1"
        and save_load.get("required_roundtrip") == "save_load_restores_world_hash"
        and rollback.get("schema") == "xace.rollback.clean_boundary.v1"
        and rollback.get("strategy") == "clean_boundary_snapshot_then_resimulate"
        and replay.get("schema") == "xace.replay.input_log.v1"
        and isinstance(replay.get("world_seed"), int)
        and int(replay.get("ticks", 0)) > 0
    )
    return Check(
        "save_load_rollback_replay_contract",
        ok,
        "Slice records save/load, clean-boundary rollback, and input-log replay contracts for installed-engine tasks.",
        {"save_load": dict(save_load), "rollback": dict(rollback), "replay": dict(replay)},
    )


def check_asset_hashes(cgs: Mapping[str, Any], fixture_root: Path) -> Check:
    failures: list[dict[str, Any]] = []
    linked_count = 0
    for asset in asset_items(cgs):
        if str(asset.get("status", "")).upper() != "LINKED":
            continue
        linked_count += 1
        asset_id = str(asset.get("id", "") or asset.get("asset_id", ""))
        rel_path = str(asset.get("path", "") or asset.get("source", ""))
        expected = str(asset.get("sha256", "")).lower()
        path = (fixture_root / rel_path).resolve()
        actual = sha256_file(path) if path.exists() else ""
        if not path.exists() or expected != actual:
            failures.append(
                {
                    "asset_id": asset_id,
                    "path": rel_path,
                    "expected": expected,
                    "actual": actual,
                    "exists": path.exists(),
                }
            )
    return Check(
        "linked_asset_sha256s_match",
        linked_count >= 2 and not failures,
        "Linked animation/audio placeholder assets exist and match declared SHA-256 values.",
        {"linked_count": linked_count, "failures": failures},
    )


def check_asset_preflight_matrix(reports: Iterable[Any]) -> Check:
    rows = [
        {
            "phase": report.phase.value,
            "engine": report.engine,
            "ok": report.ok,
            "blocked": report.blocked,
            "error_count": report.error_count,
            "warning_count": report.warning_count,
            "issue_codes": [issue.code for issue in report.issues],
        }
        for report in reports
    ]
    expected_count = len(ASSET_PREFLIGHT_PHASES) * len(ENGINES)
    ok = len(rows) == expected_count and all(row["ok"] and not row["blocked"] for row in rows)
    return Check(
        "cross_engine_asset_preflight_matrix",
        ok,
        "Runtime/save/adapter-package asset preflight passes for Godot, Unity, and Unreal.",
        {"rows": rows, "expected_count": expected_count},
    )


def check_semantic_binding_matrix(status_report: Mapping[str, Any]) -> Check:
    records = [record for record in status_report.get("records", []) if isinstance(record, Mapping)]
    blocking = [record for record in records if record.get("blocks_runtime") or record.get("blocks_handoff")]
    statuses_by_binding: dict[str, set[str]] = {}
    statuses_by_engine: dict[str, set[str]] = {engine: set() for engine in ENGINES}
    for record in records:
        binding_id = str(record.get("binding_id", ""))
        status = str(record.get("status", ""))
        engine = str(record.get("engine", ""))
        statuses_by_binding.setdefault(binding_id, set()).add(status)
        statuses_by_engine.setdefault(engine, set()).add(status)
    ok = (
        status_report.get("schema") == "xace.semantic_binding_status_report.v1"
        and len(records) == len(ENGINES) * 3
        and not blocking
        and statuses_by_binding.get("binding_player_run_animation") == {"resolved"}
        and statuses_by_binding.get("binding_sword_hit_audio") == {"resolved"}
        and statuses_by_binding.get("binding_hit_spark_vfx") == {"fallback"}
        and all({"resolved", "fallback"}.issubset(statuses_by_engine.get(engine, set())) for engine in ENGINES)
    )
    return Check(
        "semantic_binding_status_matrix",
        ok,
        "Animation/audio bindings resolve and VFX uses documented fallback for each target engine without blocking runtime/handoff.",
        {
            "record_count": len(records),
            "blocking": blocking,
            "statuses_by_binding": {key: sorted(value) for key, value in statuses_by_binding.items()},
            "statuses_by_engine": {key: sorted(value) for key, value in statuses_by_engine.items()},
        },
    )


def build_indexes(cgs: Mapping[str, Any]) -> dict[str, set[str]]:
    components: set[str] = set()
    systems: set[str] = set()
    actors: set[str] = set()
    for schema in cgs.get("component_schemas", []):
        if isinstance(schema, Mapping) and isinstance(schema.get("name"), str):
            components.add(schema["name"])
    for system in cgs.get("global_systems", []):
        if isinstance(system, Mapping) and isinstance(system.get("id"), str):
            systems.add(system["id"])
    for mode in cgs.get("modes", []):
        if not isinstance(mode, Mapping):
            continue
        for system in mode.get("systems", []):
            if isinstance(system, Mapping) and isinstance(system.get("id"), str):
                systems.add(system["id"])
        for actor in mode.get("actors", []):
            if not isinstance(actor, Mapping):
                continue
            if isinstance(actor.get("id"), str):
                actors.add(actor["id"])
            for component in actor.get("components", []):
                if isinstance(component, Mapping) and isinstance(component.get("name"), str):
                    components.add(component["name"])
    semantic_events = {
        str(event.get("name"))
        for event in cgs.get("semantic_events", [])
        if isinstance(event, Mapping) and event.get("name")
    }
    assets = {
        str(asset.get("id") or asset.get("asset_id"))
        for asset in asset_items(cgs)
        if asset.get("id") or asset.get("asset_id")
    }
    bindings = {
        str(binding.get("binding_id"))
        for binding in as_mapping(cgs.get("semantic_bindings")).get("bindings", [])
        if isinstance(binding, Mapping) and binding.get("binding_id")
    }
    return {
        "actors": actors,
        "components": components,
        "systems": systems,
        "semantic_events": semantic_events,
        "assets": assets,
        "bindings": bindings,
    }


def validate_feature_refs(
    feature: str,
    feature_record: Mapping[str, Any],
    indexes: Mapping[str, set[str]],
) -> list[str]:
    failures: list[str] = []
    fields = {
        "systems": "systems",
        "components": "components",
        "semantic_events": "semantic_events",
        "assets": "assets",
        "bindings": "bindings",
    }
    for field, index_name in fields.items():
        values = feature_record.get(field, [])
        if values is None:
            continue
        if not isinstance(values, list):
            failures.append(f"{feature}.{field} is not an array")
            continue
        for value in values:
            if not isinstance(value, str) or value not in indexes[index_name]:
                failures.append(f"{feature}.{field} references missing {value!r}")
    return failures


def has_feature_references(feature_record: Mapping[str, Any]) -> bool:
    for field in ("systems", "components", "semantic_events", "assets", "bindings"):
        value = feature_record.get(field)
        if isinstance(value, list) and value:
            return True
    return False


def summarize_asset_preflight(reports: Iterable[Any]) -> list[dict[str, Any]]:
    return [
        {
            "phase": report.phase.value,
            "engine": report.engine,
            "ok": report.ok,
            "blocked": report.blocked,
            "asset_refs_checked": report.asset_refs_checked,
            "asset_files_checked": report.asset_files_checked,
            "asset_hashes_checked": report.asset_hashes_checked,
            "fallbacks_documented": report.fallbacks_documented,
            "issue_codes": [issue.code for issue in report.issues],
        }
        for report in reports
    ]


def summarize_semantic_status(status_report: Mapping[str, Any]) -> dict[str, Any]:
    records = [record for record in status_report.get("records", []) if isinstance(record, Mapping)]
    return {
        "schema": status_report.get("schema"),
        "record_count": len(records),
        "count_by_status": status_report.get("count_by_status"),
        "count_by_engine": status_report.get("count_by_engine"),
        "blocking_count": sum(1 for record in records if record.get("blocks_runtime") or record.get("blocks_handoff")),
    }


def asset_items(cgs: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    out: list[Mapping[str, Any]] = []
    for item in cgs.get("assets", []):
        if isinstance(item, Mapping):
            out.append(item)
    for binding in as_mapping(cgs.get("semantic_bindings")).get("bindings", []):
        if isinstance(binding, Mapping) and isinstance(binding.get("asset"), Mapping):
            out.append(binding["asset"])
    return out


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return value


def as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def canonical_json(value: Any, *, indent: int | None = None) -> str:
    return json.dumps(value, indent=indent, sort_keys=True, ensure_ascii=True)


if __name__ == "__main__":
    raise SystemExit(main())
