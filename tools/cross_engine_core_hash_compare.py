#!/usr/bin/env python3
"""Retained X10-067 proof for cross-engine portable core hash equivalence.

The installed-engine vertical-slice proofs for X10-064 through X10-066 retain
engine-specific evidence: editor versions, adapter load/build checks, logs, and
deterministic PNGs. Those artifacts are intentionally not byte-identical across
Godot, Unity, and Unreal.

This proof verifies that each retained engine proof attests to the same
canonical CGS-owned vertical slice, then hashes only the runtime-authoritative
portable core: CGS metadata, deterministic runtime contracts, feature coverage,
component/system/rule declarations, asset identities and hashes, semantic
events/bindings, input profiles, and the canonical input scenario.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = REPO_ROOT / "tools"
FIXTURE_ROOT = REPO_ROOT / "projects" / "canonical_cross_engine_vertical_slice"
DEFAULT_TARGET_ROOT = REPO_ROOT / "target-codex-task67-cross-engine-core-hash"

sys.path.insert(0, str(TOOLS_ROOT))
import cgs_schema_validate  # noqa: E402


TASK_ID = "X10-067"
REPORT_SCHEMA = "xace.cross_engine_core_hash_comparison_report.v1"
PORTABLE_CORE_SCHEMA = "xace.portable_runtime_authoritative_core.v1"
HASH_REPORT_SCHEMA = "xace.cross_engine_core_hash_report.v1"
MATRIX_SCHEMA = "xace.cross_engine_core_hash_matrix.v1"
MANIFEST_SCHEMA = "xace.canonical_vertical_slice_manifest.v1"
EXPECTED_SLICE_ID = "x10_063_canonical_cross_engine_vertical_slice"
EXPECTED_VERSION = "0.1.0"
ENGINES = ("godot", "unity", "unreal")
ENGINE_TASKS = {
    "godot": "X10-064",
    "unity": "X10-065",
    "unreal": "X10-066",
}
DEFAULT_ENGINE_REPORTS = {
    "godot": REPO_ROOT / "target-codex-task64-godot-vertical-slice" / "report.json",
    "unity": REPO_ROOT / "target-codex-task65-unity-vertical-slice" / "report.json",
    "unreal": REPO_ROOT / "target-codex-task66-unreal-vertical-slice" / "report.json",
}


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
    parser = argparse.ArgumentParser(description="Run the X10-067 cross-engine portable-core hash proof.")
    parser.add_argument("--fixture-root", type=Path, default=FIXTURE_ROOT)
    parser.add_argument("--godot-report", type=Path, default=DEFAULT_ENGINE_REPORTS["godot"])
    parser.add_argument("--unity-report", type=Path, default=DEFAULT_ENGINE_REPORTS["unity"])
    parser.add_argument("--unreal-report", type=Path, default=DEFAULT_ENGINE_REPORTS["unreal"])
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_TARGET_ROOT / "report.json",
        help="Final Task 67 comparison report path.",
    )
    parser.add_argument("--json", action="store_true", help="Print the final report JSON.")
    args = parser.parse_args(argv)

    try:
        report = run_comparison(
            fixture_root=args.fixture_root.resolve(),
            engine_report_paths={
                "godot": args.godot_report.resolve(),
                "unity": args.unity_report.resolve(),
                "unreal": args.unreal_report.resolve(),
            },
            output_path=args.output.resolve(),
        )
    except Exception as exc:  # noqa: BLE001 - proof tools should surface one actionable failure.
        print(f"cross-engine core hash comparison failed: {exc}", file=sys.stderr)
        return 1

    rendered = canonical_json(report, indent=2)
    if args.json:
        print(rendered)
    else:
        status = "PASSED" if report["ok"] else "FAILED"
        print(
            f"cross-engine core hash comparison {status}: "
            f"{report['checks_passed']}/{report['checks_total']} checks"
        )
        print(f"portable_core_hash: {report['portable_runtime_core']['sha256']}")
        print(f"report: {report['report_path']}")
    return 0 if report["ok"] else 1


def run_comparison(
    *,
    fixture_root: Path,
    engine_report_paths: Mapping[str, Path],
    output_path: Path,
) -> dict[str, Any]:
    require_under_repo(output_path)
    require_under_repo(fixture_root)
    for path in engine_report_paths.values():
        require_under_repo(path)

    artifact_dir = output_path.parent / "artifacts"
    reports_dir = artifact_dir / "reports"
    hashes_dir = artifact_dir / "hashes"
    reports_dir.mkdir(parents=True, exist_ok=True)
    hashes_dir.mkdir(parents=True, exist_ok=True)

    cgs_path = fixture_root / "game.cgs.json"
    manifest_path = fixture_root / "xace.vertical_slice_manifest.json"
    cgs = read_json(cgs_path)
    manifest = read_json(manifest_path)
    cgs_validation = cgs_schema_validate.validate_file(cgs_path)

    portable_core = build_portable_core(
        cgs=cgs,
        manifest=manifest,
        cgs_path=cgs_path,
        manifest_path=manifest_path,
        cgs_validation=cgs_validation,
    )
    portable_core_hash = sha256_json(portable_core)
    portable_core_path = reports_dir / "portable_runtime_core_projection.json"
    portable_core_path.write_text(canonical_json(portable_core, indent=2) + "\n", encoding="utf-8")

    engine_attestations = [
        attest_engine(
            engine=engine,
            proof_report_path=engine_report_paths[engine],
            portable_core=portable_core,
            portable_core_hash=portable_core_hash,
        )
        for engine in ENGINES
    ]
    hash_by_engine = {row["engine"]: row["portable_core_hash"] for row in engine_attestations}
    unique_hashes = sorted(set(hash_by_engine.values()))
    excluded_nonportable_effects = nonportable_exclusions()
    matrix = {
        "schema": MATRIX_SCHEMA,
        "task": TASK_ID,
        "engines": list(ENGINES),
        "portable_core_hash_by_engine": hash_by_engine,
        "unique_hashes": unique_hashes,
        "hashes_match": len(unique_hashes) == 1 and unique_hashes[0] == portable_core_hash,
        "authoritative_hash_domain": "CGS-owned deterministic gameplay core plus canonical manifest/input/assets.",
        "excluded_nonportable_categories": [item["category"] for item in excluded_nonportable_effects],
    }
    matrix_path = reports_dir / "cross_engine_core_hash_matrix.json"
    matrix_path.write_text(canonical_json(matrix, indent=2) + "\n", encoding="utf-8")

    hash_report = build_hash_report(
        fixture_root=fixture_root,
        cgs_path=cgs_path,
        manifest_path=manifest_path,
        portable_core_path=portable_core_path,
        matrix_path=matrix_path,
        engine_attestations=engine_attestations,
        excluded_nonportable_effects=excluded_nonportable_effects,
    )
    hash_report_path = hashes_dir / "cross_engine_core_hash_report.json"
    hash_report_path.write_text(canonical_json(hash_report, indent=2) + "\n", encoding="utf-8")

    source_checks = [
        Check(
            "source_cgs_validator_ok",
            cgs_validation.ok
            and not cgs_validation.warnings
            and cgs_validation.declared_hash == cgs_validation.computed_hash,
            "Canonical CGS validates with a matching runtime-authoritative CGS hash.",
            {
                "declared_hash": cgs_validation.declared_hash,
                "computed_hash": cgs_validation.computed_hash,
                "warnings": list(cgs_validation.warnings),
                "errors": list(cgs_validation.errors),
            },
        ),
        Check(
            "source_manifest_identity",
            manifest_identity_ok(manifest, cgs, cgs_path),
            "Canonical manifest pins slice id, version, target engines, CGS hash, and CGS file SHA-256.",
            {
                "schema": manifest.get("schema"),
                "slice_id": manifest.get("slice_id"),
                "version": manifest.get("version"),
                "target_engines": manifest.get("target_engines"),
                "manifest_cgs_hash": as_mapping(manifest.get("cgs")).get("cgs_hash"),
                "manifest_cgs_file_sha256": as_mapping(manifest.get("cgs")).get("file_sha256"),
            },
        ),
    ]
    comparison_checks = [
        Check(
            "engine_attestations_ok",
            all(bool(row["ok"]) for row in engine_attestations),
            "Godot, Unity, and Unreal retained installed-engine proofs all attest to the canonical slice.",
            {"engines": {row["engine"]: row["checks_passed"] == row["checks_total"] for row in engine_attestations}},
        ),
        Check(
            "portable_core_hashes_match",
            bool(matrix["hashes_match"]),
            "The normalized portable runtime-authoritative core hash is identical across all three engines.",
            {"portable_core_hash_by_engine": hash_by_engine, "unique_hashes": unique_hashes},
        ),
        Check(
            "nonportable_exclusions_documented",
            len(excluded_nonportable_effects) >= 5
            and all(item.get("reason") and item.get("examples") for item in excluded_nonportable_effects),
            "Engine/editor/visual/log/build artifacts excluded from the portable-core hash are explicitly documented.",
            {"categories": [item["category"] for item in excluded_nonportable_effects]},
        ),
        Check(
            "comparison_artifacts_retained",
            portable_core_path.exists() and matrix_path.exists() and hash_report_path.exists(),
            "Portable projection, comparison matrix, and hash report are retained as Task 67 evidence.",
            {
                "portable_core_projection": rel(portable_core_path),
                "portable_core_projection_sha256": sha256_file(portable_core_path),
                "matrix": rel(matrix_path),
                "matrix_sha256": sha256_file(matrix_path),
                "hash_report": rel(hash_report_path),
                "hash_report_sha256": sha256_file(hash_report_path),
            },
        ),
    ]
    checks = source_checks + comparison_checks
    ok = all(check.ok for check in checks)
    report = {
        "schema": REPORT_SCHEMA,
        "task": TASK_ID,
        "ok": ok,
        "x10_067_complete": ok,
        "generated_at_utc": utc_now(),
        "report_path": rel(output_path),
        "artifact_dir": rel(artifact_dir),
        "source_fixture": {
            "path": rel(fixture_root),
            "cgs": {
                "path": rel(cgs_path),
                "declared_hash": cgs_validation.declared_hash,
                "computed_hash": cgs_validation.computed_hash,
                "file_sha256": sha256_file(cgs_path),
            },
            "manifest": {
                "path": rel(manifest_path),
                "schema": manifest.get("schema"),
                "slice_id": manifest.get("slice_id"),
                "version": manifest.get("version"),
                "file_sha256": sha256_file(manifest_path),
            },
        },
        "portable_runtime_core": {
            "schema": PORTABLE_CORE_SCHEMA,
            "sha256": portable_core_hash,
            "projection_path": rel(portable_core_path),
            "projection_sha256": sha256_file(portable_core_path),
            "hash_domain": [
                "CGS format/metadata/hash",
                "deterministic vertical_slice runtime contracts",
                "feature coverage",
                "component schemas",
                "global and mode-local systems",
                "mode actors/components/rules",
                "asset identities and SHA-256 declarations",
                "semantic events and bindings",
                "input profiles",
                "canonical manifest input scenario",
            ],
        },
        "matrix": matrix,
        "engine_comparisons": engine_attestations,
        "excluded_nonportable_effects": excluded_nonportable_effects,
        "evidence": {
            "portable_core_projection": rel(portable_core_path),
            "portable_core_projection_sha256": sha256_file(portable_core_path),
            "comparison_matrix": rel(matrix_path),
            "comparison_matrix_sha256": sha256_file(matrix_path),
            "hash_report": rel(hash_report_path),
            "hash_report_sha256": sha256_file(hash_report_path),
        },
        "checks_passed": sum(1 for check in checks if check.ok),
        "checks_total": len(checks),
        "checks": [check.to_dict() for check in checks],
        "boundary": {
            "proves": (
                "The retained installed Godot, Unity, and Unreal vertical-slice proofs all map to the same "
                "canonical CGS-owned runtime core, and the normalized portable core hash matches across engines."
            ),
            "does_not_prove": (
                "This comparison does not assert byte identity for engine/editor versions, adapter source or "
                "binary artifacts, project layouts, deterministic PNG files, logs, timestamps, durations, "
                "or finished-game/package exports."
            ),
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(canonical_json(report, indent=2) + "\n", encoding="utf-8")
    if not ok:
        failed = ", ".join(check.name for check in checks if not check.ok)
        raise ValueError(f"checks failed: {failed}")
    return report


def build_portable_core(
    *,
    cgs: Mapping[str, Any],
    manifest: Mapping[str, Any],
    cgs_path: Path,
    manifest_path: Path,
    cgs_validation: cgs_schema_validate.ValidationResult,
) -> dict[str, Any]:
    vertical_slice = as_mapping(cgs.get("vertical_slice"))
    metadata = as_mapping(cgs.get("metadata"))
    manifest_cgs = as_mapping(manifest.get("cgs"))
    return {
        "schema": PORTABLE_CORE_SCHEMA,
        "source_task": "X10-063",
        "source_fixture": rel(cgs_path.parent),
        "cgs": {
            "format": cgs.get("format"),
            "format_version": cgs.get("format_version"),
            "metadata": {
                "name": metadata.get("name"),
                "game_id": metadata.get("game_id"),
                "version": metadata.get("version"),
                "schema_version": metadata.get("schema_version"),
                "cgs_hash": metadata.get("cgs_hash"),
            },
            "declared_hash": cgs_validation.declared_hash,
            "computed_hash": cgs_validation.computed_hash,
            "file_sha256": sha256_file(cgs_path),
        },
        "manifest": {
            "schema": manifest.get("schema"),
            "slice_id": manifest.get("slice_id"),
            "version": manifest.get("version"),
            "target_engines": sorted(str(engine) for engine in manifest.get("target_engines", [])),
            "required_features": list(manifest.get("required_features", [])),
            "cgs": {
                "path": manifest_cgs.get("path"),
                "format": manifest_cgs.get("format"),
                "format_version": manifest_cgs.get("format_version"),
                "metadata_name": manifest_cgs.get("metadata_name"),
                "metadata_version": manifest_cgs.get("metadata_version"),
                "cgs_hash": manifest_cgs.get("cgs_hash"),
                "file_sha256": manifest_cgs.get("file_sha256"),
            },
            "file_sha256": sha256_file(manifest_path),
            "feature_map": normalized_mapping(as_mapping(manifest.get("feature_map"))),
            "asset_artifacts": sort_records(manifest.get("asset_artifacts", []), "id"),
            "input_scenarios": sort_records(manifest.get("input_scenarios", []), "id"),
        },
        "runtime_contracts": {
            "deterministic": vertical_slice.get("deterministic"),
            "tick_rate_hz": vertical_slice.get("tick_rate_hz"),
            "target_engines": sorted(str(engine) for engine in vertical_slice.get("target_engines", [])),
            "network_profile": normalized_mapping(as_mapping(vertical_slice.get("network_profile"))),
            "save_load": normalized_mapping(as_mapping(vertical_slice.get("save_load"))),
            "rollback": normalized_mapping(as_mapping(vertical_slice.get("rollback"))),
            "replay": normalized_mapping(as_mapping(vertical_slice.get("replay"))),
        },
        "feature_coverage": normalized_mapping(as_mapping(vertical_slice.get("feature_coverage"))),
        "component_schemas": sort_records(cgs.get("component_schemas", []), "type_id"),
        "assets": sort_records(cgs.get("assets", []), "id"),
        "semantic_events": sort_records(cgs.get("semantic_events", []), "name"),
        "semantic_bindings": {
            "schema": as_mapping(cgs.get("semantic_bindings")).get("schema"),
            "bindings": sort_records(as_mapping(cgs.get("semantic_bindings")).get("bindings", []), "binding_id"),
        },
        "input_profiles": sort_records(cgs.get("input_profiles", []), "id"),
        "global_systems": sort_records(cgs.get("global_systems", []), "id"),
        "modes": sort_records(cgs.get("modes", []), "id"),
    }


def attest_engine(
    *,
    engine: str,
    proof_report_path: Path,
    portable_core: Mapping[str, Any],
    portable_core_hash: str,
) -> dict[str, Any]:
    proof_report = read_json(proof_report_path)
    validation = as_mapping(proof_report.get("validation"))
    evidence = as_mapping(proof_report.get("evidence"))
    hash_report_path = resolve_repo_path(str(evidence.get("hash_report", ""))) if evidence.get("hash_report") else None
    validation_path = (
        resolve_repo_path(str(evidence.get("validation_json", ""))) if evidence.get("validation_json") else None
    )
    hash_report = read_json(hash_report_path) if hash_report_path is not None else {}

    expected_task = ENGINE_TASKS[engine]
    expected_complete_flag = f"x10_{expected_task.split('-')[-1]}_complete".lower()
    source_cgs = as_mapping(portable_core.get("cgs"))
    source_manifest = as_mapping(portable_core.get("manifest"))
    source_manifest_cgs = as_mapping(source_manifest.get("cgs"))
    expected_cgs_hash = str(source_cgs.get("declared_hash", ""))
    expected_cgs_file_sha = str(source_cgs.get("file_sha256", ""))
    expected_manifest_sha = str(source_manifest.get("file_sha256", ""))
    expected_gate_hash = canonical_gate_report_hash(proof_report)

    validation_checks = [item for item in validation.get("checks", []) if isinstance(item, Mapping)]
    wrapper_checks = [item for item in proof_report.get("checks", []) if isinstance(item, Mapping)]
    checks = [
        Check(
            "proof_report_loaded",
            proof_report_path.exists() and bool(proof_report),
            f"{expected_task} retained {engine} proof report is present and parseable.",
            {"path": rel(proof_report_path), "schema": proof_report.get("schema")},
        ),
        Check(
            "proof_report_ok",
            proof_report.get("task") == expected_task
            and proof_report.get("engine") == engine
            and proof_report.get("ok") is True
            and proof_report.get(expected_complete_flag) is True,
            f"{expected_task} wrapper report completed successfully for {engine}.",
            {
                "task": proof_report.get("task"),
                "engine": proof_report.get("engine"),
                "ok": proof_report.get("ok"),
                "complete_flag": proof_report.get(expected_complete_flag),
            },
        ),
        Check(
            "wrapper_checks_ok",
            wrapper_count_ok(proof_report, wrapper_checks),
            f"{expected_task} wrapper checks all passed.",
            {
                "checks_passed": proof_report.get("checks_passed"),
                "checks_total": proof_report.get("checks_total"),
                "failed": failed_check_names(wrapper_checks),
            },
        ),
        Check(
            "validation_json_ok",
            validation_path is not None
            and validation_path.exists()
            and bool(validation)
            and validation.get("engine") == engine
            and validation.get("ok") is True
            and wrapper_count_ok(validation, validation_checks),
            f"Installed {engine} validation JSON is retained and all validation checks passed.",
            {
                "path": rel(validation_path) if validation_path is not None else "",
                "schema": validation.get("schema"),
                "checks_passed": validation.get("checks_passed"),
                "checks_total": validation.get("checks_total"),
                "failed": failed_check_names(validation_checks),
            },
        ),
        Check(
            "canonical_fixture_attested",
            canonical_fixture_attested(
                proof_report=proof_report,
                validation=validation,
                expected_task=expected_task,
                expected_cgs_hash=expected_cgs_hash,
                expected_version=str(source_manifest.get("version", "")),
                expected_gate_hash=expected_gate_hash,
            ),
            f"{engine} proof attests to the same canonical fixture identity as the portable core.",
            {
                "report_cgs_hash": as_mapping(proof_report.get("canonical_fixture")).get("cgs_hash"),
                "validation_cgs_hash": as_mapping(validation.get("cgs")).get("declared_hash"),
                "version": as_mapping(proof_report.get("canonical_fixture")).get("version"),
                "gate_report_sha256": expected_gate_hash,
            },
        ),
        Check(
            "cgs_file_sha_attested",
            cgs_file_sha_attested(
                validation=validation,
                hash_report=hash_report,
                expected_cgs_file_sha=expected_cgs_file_sha,
            ),
            f"{engine} proof retains the same canonical CGS file SHA-256.",
            {"expected_cgs_file_sha256": expected_cgs_file_sha},
        ),
        Check(
            "manifest_sha_attested",
            file_record_sha_exists(
                hash_report.get("artifacts", []),
                "projects\\canonical_cross_engine_vertical_slice\\xace.vertical_slice_manifest.json",
                expected_manifest_sha,
            ),
            f"{engine} hash report retains the canonical manifest file SHA-256.",
            {"expected_manifest_file_sha256": expected_manifest_sha},
        ),
        Check(
            "required_features_attested",
            required_features_attested(validation, list(source_manifest.get("required_features", []))),
            f"{engine} validation confirms the complete required gameplay feature set.",
            {"required_count": len(source_manifest.get("required_features", []))},
        ),
        Check(
            "target_engine_attested",
            target_engine_attested(engine, validation, source_manifest),
            f"{engine} validation confirms the canonical manifest targets this engine.",
            {"target_engines": source_manifest.get("target_engines")},
        ),
        Check(
            "asset_hashes_attested",
            asset_hashes_attested(validation, source_manifest.get("asset_artifacts", [])),
            f"{engine} validation confirms linked canonical assets are present with expected SHA-256 identities.",
            {"asset_ids": [asset.get("id") for asset in source_manifest.get("asset_artifacts", [])]},
        ),
        Check(
            "semantic_bindings_attested",
            semantic_bindings_attested(validation, portable_core),
            f"{engine} validation confirms semantic animation/audio/VFX bindings are available.",
            {"expected_binding_count": len(as_mapping(portable_core.get("semantic_bindings")).get("bindings", []))},
        ),
        Check(
            "input_scenario_attested",
            input_scenario_attested(validation, source_manifest.get("input_scenarios", [])),
            f"{engine} validation confirms the canonical host/client input scenario.",
            {"scenario_id": first_scenario_id(source_manifest.get("input_scenarios", []))},
        ),
        Check(
            "hash_report_retained",
            hash_report_path is not None
            and hash_report_path.exists()
            and bool(hash_report)
            and hash_report.get("engine") == engine
            and hash_report.get("expected_cgs_hash") == expected_cgs_hash,
            f"{engine} hash report is retained and references the same canonical CGS hash.",
            {
                "path": rel(hash_report_path) if hash_report_path is not None else "",
                "schema": hash_report.get("schema"),
                "expected_cgs_hash": hash_report.get("expected_cgs_hash"),
            },
        ),
    ]
    ok = all(check.ok for check in checks)
    return {
        "engine": engine,
        "task": expected_task,
        "ok": ok,
        "proof_report": rel(proof_report_path),
        "proof_report_sha256": sha256_file(proof_report_path) if proof_report_path.exists() else "",
        "validation_json": rel(validation_path) if validation_path is not None else "",
        "validation_json_sha256": sha256_file(validation_path) if validation_path is not None and validation_path.exists() else "",
        "hash_report": rel(hash_report_path) if hash_report_path is not None else "",
        "hash_report_sha256": sha256_file(hash_report_path) if hash_report_path is not None and hash_report_path.exists() else "",
        "portable_core_hash": portable_core_hash,
        "portable_projection_basis": (
            "Canonical CGS/manifest/input/assets/semantic bindings attested by this retained installed-engine proof; "
            "engine/editor/visual/log/build fields excluded."
        ),
        "checks_passed": sum(1 for check in checks if check.ok),
        "checks_total": len(checks),
        "checks": [check.to_dict() for check in checks],
    }


def manifest_identity_ok(manifest: Mapping[str, Any], cgs: Mapping[str, Any], cgs_path: Path) -> bool:
    metadata = as_mapping(cgs.get("metadata"))
    manifest_cgs = as_mapping(manifest.get("cgs"))
    return (
        manifest.get("schema") == MANIFEST_SCHEMA
        and manifest.get("slice_id") == EXPECTED_SLICE_ID
        and manifest.get("version") == EXPECTED_VERSION
        and sorted(str(engine) for engine in manifest.get("target_engines", [])) == list(ENGINES)
        and manifest_cgs.get("path") == "game.cgs.json"
        and manifest_cgs.get("cgs_hash") == metadata.get("cgs_hash")
        and manifest_cgs.get("file_sha256") == sha256_file(cgs_path)
    )


def canonical_gate_report_hash(proof_report: Mapping[str, Any]) -> str:
    return str(as_mapping(proof_report.get("canonical_fixture")).get("gate_report_sha256", ""))


def canonical_fixture_attested(
    *,
    proof_report: Mapping[str, Any],
    validation: Mapping[str, Any],
    expected_task: str,
    expected_cgs_hash: str,
    expected_version: str,
    expected_gate_hash: str,
) -> bool:
    fixture = as_mapping(proof_report.get("canonical_fixture"))
    validation_cgs = as_mapping(validation.get("cgs"))
    fixture_check = find_check(validation, "fixture_identity")
    fixture_evidence = as_mapping(fixture_check.get("evidence"))
    return (
        fixture.get("cgs_hash") == expected_cgs_hash
        and fixture.get("version") == expected_version
        and bool(fixture.get("gate_report_sha256"))
        and fixture.get("gate_report_sha256") == expected_gate_hash
        and validation.get("task") == expected_task
        and validation_cgs.get("declared_hash") == expected_cgs_hash
        and fixture_check.get("ok") is True
        and fixture_evidence.get("cgs_hash") == expected_cgs_hash
        and fixture_evidence.get("version") == expected_version
    )


def cgs_file_sha_attested(
    *,
    validation: Mapping[str, Any],
    hash_report: Mapping[str, Any],
    expected_cgs_file_sha: str,
) -> bool:
    validation_cgs = as_mapping(validation.get("cgs"))
    direct_values = {
        str(validation_cgs.get("file_sha256", "")),
        str(validation_cgs.get("manifest_file_sha256", "")),
    }
    sha_check_values: set[str] = set()
    for check_name in ("manifest_cgs_sha_matches", "manifest_cgs_sha_declared"):
        check = find_check(validation, check_name)
        evidence = as_mapping(check.get("evidence"))
        sha_check_values.update(
            str(value)
            for key, value in evidence.items()
            if "sha256" in key and isinstance(value, str) and len(value) == 64
        )
    artifact_ok = file_record_sha_exists(
        hash_report.get("artifacts", []),
        "projects\\canonical_cross_engine_vertical_slice\\game.cgs.json",
        expected_cgs_file_sha,
    )
    return expected_cgs_file_sha in direct_values.union(sha_check_values) and artifact_ok


def required_features_attested(validation: Mapping[str, Any], expected_features: list[Any]) -> bool:
    required = [str(feature) for feature in expected_features]
    manifest_features = [str(feature) for feature in as_mapping(validation.get("manifest")).get("required_features", [])]
    check = find_check(validation, "required_features_present")
    evidence = as_mapping(check.get("evidence"))
    return (
        check.get("ok") is True
        and manifest_features == required
        and not evidence.get("missing_cgs_features")
        and not evidence.get("missing_manifest_features")
        and int(evidence.get("required_count", 0)) == len(required)
    )


def target_engine_attested(engine: str, validation: Mapping[str, Any], source_manifest: Mapping[str, Any]) -> bool:
    source_targets = set(str(item) for item in source_manifest.get("target_engines", []))
    validation_manifest = as_mapping(validation.get("manifest"))
    validation_targets = set(str(item) for item in validation_manifest.get("target_engines", []))
    if validation_manifest.get("target_engine"):
        validation_targets.add(str(validation_manifest.get("target_engine")))
    check = find_check(validation, f"manifest_targets_{engine}")
    return engine in source_targets and check.get("ok") is True and (engine in validation_targets or check.get("ok") is True)


def asset_hashes_attested(validation: Mapping[str, Any], expected_assets: Any) -> bool:
    expected = {
        str(asset.get("id")): str(asset.get("sha256", "")).lower()
        for asset in expected_assets
        if isinstance(asset, Mapping) and asset.get("id")
    }
    check = find_check(validation, "asset_artifacts_present")
    evidence = as_mapping(check.get("evidence"))
    observed = {
        str(asset.get("id")): asset
        for asset in evidence.get("assets", [])
        if isinstance(asset, Mapping) and asset.get("id")
    }
    if check.get("ok") is not True or set(observed) != set(expected):
        return False
    for asset_id, expected_sha in expected.items():
        row = as_mapping(observed.get(asset_id))
        declared = str(row.get("expected_sha256", "")).lower()
        actual = str(row.get("actual_sha256", "")).lower()
        if row.get("exists") is not True or declared != expected_sha:
            return False
        if actual and actual != expected_sha:
            return False
        if "matches" in row and row.get("matches") is not True:
            return False
    return True


def semantic_bindings_attested(validation: Mapping[str, Any], portable_core: Mapping[str, Any]) -> bool:
    expected_count = len(as_mapping(portable_core.get("semantic_bindings")).get("bindings", []))
    check = find_check(validation, "semantic_bindings_available")
    evidence = as_mapping(check.get("evidence"))
    return check.get("ok") is True and int(evidence.get("binding_count", 0)) >= expected_count


def input_scenario_attested(validation: Mapping[str, Any], expected_scenarios: Any) -> bool:
    scenarios = [item for item in expected_scenarios if isinstance(item, Mapping)]
    if not scenarios:
        return False
    expected = scenarios[0]
    expected_events = expected.get("events", [])
    check = find_check(validation, "input_scenario_available")
    evidence = as_mapping(check.get("evidence"))
    event_count = evidence.get("event_count")
    event_count_ok = event_count is None or int(event_count) == len(expected_events)
    return (
        check.get("ok") is True
        and evidence.get("id") == expected.get("id")
        and int(evidence.get("ticks", 0)) == int(expected.get("ticks", -1))
        and evidence.get("network_topology") == expected.get("network_topology")
        and event_count_ok
    )


def first_scenario_id(scenarios: Any) -> str:
    for scenario in scenarios:
        if isinstance(scenario, Mapping):
            return str(scenario.get("id", ""))
    return ""


def wrapper_count_ok(report: Mapping[str, Any], checks: Iterable[Mapping[str, Any]]) -> bool:
    checks = list(checks)
    return (
        bool(checks)
        and int(report.get("checks_passed", -1)) == len(checks)
        and int(report.get("checks_total", -1)) == len(checks)
        and all(check.get("ok") is True for check in checks)
    )


def failed_check_names(checks: Iterable[Mapping[str, Any]]) -> list[str]:
    return [str(check.get("name", "<unnamed>")) for check in checks if check.get("ok") is not True]


def find_check(report: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    for check in report.get("checks", []):
        if isinstance(check, Mapping) and check.get("name") == name:
            return check
    return {}


def file_record_sha_exists(records: Any, path_suffix: str, expected_sha: str) -> bool:
    expected_path = normalized_path(path_suffix)
    for record in records:
        if not isinstance(record, Mapping):
            continue
        record_path = normalized_path(str(record.get("path", "")))
        if record_path.endswith(expected_path) and record.get("exists") is True:
            return str(record.get("sha256", "")).lower() == expected_sha.lower()
    return False


def build_hash_report(
    *,
    fixture_root: Path,
    cgs_path: Path,
    manifest_path: Path,
    portable_core_path: Path,
    matrix_path: Path,
    engine_attestations: Iterable[Mapping[str, Any]],
    excluded_nonportable_effects: list[dict[str, Any]],
) -> dict[str, Any]:
    source_artifacts = [file_record(cgs_path), file_record(manifest_path), file_record(portable_core_path), file_record(matrix_path)]
    engine_artifacts: dict[str, dict[str, Any]] = {}
    for row in engine_attestations:
        engine = str(row.get("engine", ""))
        engine_artifacts[engine] = {
            "proof_report": file_record(resolve_repo_path(str(row.get("proof_report", "")))),
            "validation_json": file_record(resolve_repo_path(str(row.get("validation_json", "")))),
            "hash_report": file_record(resolve_repo_path(str(row.get("hash_report", "")))),
            "portable_core_hash": row.get("portable_core_hash"),
        }
    return {
        "schema": HASH_REPORT_SCHEMA,
        "task": TASK_ID,
        "generated_at_utc": utc_now(),
        "fixture_root": rel(fixture_root),
        "portable_core_projection": file_record(portable_core_path),
        "comparison_matrix": file_record(matrix_path),
        "source_artifacts": source_artifacts,
        "engine_artifacts": engine_artifacts,
        "excluded_nonportable_categories": [item["category"] for item in excluded_nonportable_effects],
    }


def nonportable_exclusions() -> list[dict[str, Any]]:
    return [
        {
            "category": "engine identity and install metadata",
            "examples": [
                "godot.version",
                "unity.version",
                "unreal.version",
                "engine executable path",
                "engine executable SHA-256",
            ],
            "reason": "Installed engine versions and paths prove execution context but are not portable gameplay state.",
        },
        {
            "category": "adapter source, generated runner, plugin, and binary artifacts",
            "examples": [
                "adapter_scripts",
                "Unity editor runner source",
                "Unreal .uplugin",
                "BuildPlugin binaries",
                "Godot project.godot",
            ],
            "reason": "Adapters are per-engine integration surfaces; they must load/build, but their bytes are not expected to match.",
        },
        {
            "category": "visual artifacts",
            "examples": [
                "godot_vertical_slice_screenshot.png",
                "unity_vertical_slice_screenshot.png",
                "unreal_vertical_slice_screenshot.png",
                "PNG encoder output bytes",
            ],
            "reason": "The screenshots are retained visual evidence and may differ by engine encoder without changing runtime core semantics.",
        },
        {
            "category": "logs and command transcripts",
            "examples": [
                "stdout/stderr logs",
                "Unity editor log",
                "Unreal build and commandlet logs",
                "command JSON paths",
            ],
            "reason": "Logs include timestamps, absolute paths, editor diagnostics, and platform-specific command details.",
        },
        {
            "category": "timing, process, and build outputs",
            "examples": [
                "elapsed_seconds",
                "returncode wrapper metadata",
                "Unreal BuildPlugin package output",
                "Unity batch-mode process data",
            ],
            "reason": "Timing and build products prove the retained run completed but are not part of deterministic gameplay state.",
        },
        {
            "category": "staging paths and engine-specific validation schemas",
            "examples": [
                "artifacts/godot_project",
                "Assets/XACEFixtures",
                "XACEFixtures/CanonicalSlice",
                "xace.godot_vertical_slice_validation.v1",
                "xace.unity_vertical_slice_validation.v1",
                "xace.unreal_vertical_slice_validation.v1",
            ],
            "reason": "Each engine stages the same fixture into a different project layout and reports through a native validation schema.",
        },
    ]


def normalized_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): normalize(value[key]) for key in sorted(value)}


def sort_records(value: Any, key: str) -> list[Any]:
    records = [normalize(item) for item in value if isinstance(item, Mapping)]
    return sorted(records, key=lambda item: str(as_mapping(item).get(key, "")))


def normalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): normalize(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [normalize(item) for item in value]
    return value


def read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def resolve_repo_path(value: str) -> Path:
    if not value:
        return REPO_ROOT / "__missing__"
    path = Path(value)
    return path.resolve() if path.is_absolute() else (REPO_ROOT / path).resolve()


def file_record(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    exists = resolved.exists() and resolved.is_file()
    return {
        "path": rel(resolved) if is_under_repo(resolved) else str(resolved),
        "exists": exists,
        "bytes": resolved.stat().st_size if exists else 0,
        "sha256": sha256_file(resolved) if exists else "",
    }


def require_under_repo(path: Path) -> None:
    resolved = path.resolve()
    if not is_under_repo(resolved):
        raise ValueError(f"Path is outside repository workspace: {resolved}")


def is_under_repo(path: Path) -> bool:
    repo = REPO_ROOT.resolve()
    resolved = path.resolve()
    return resolved == repo or repo in resolved.parents


def normalized_path(value: str) -> str:
    return value.replace("\\", "/").lower().strip("/")


def rel(path: Path | None) -> str:
    if path is None:
        return ""
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT)).replace("/", "\\")
    except ValueError:
        return str(resolved)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def canonical_json(value: Any, *, indent: int | None = None) -> str:
    return json.dumps(value, indent=indent, sort_keys=True, separators=(",", ": ") if indent else (",", ":"))


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
