"""
asset_reference_validation_check.py - retained X10-053 asset preflight proof.

Creates a small project fixture and proves that the strict production asset
preflight validator checks references, hashes, types, statuses, missing files,
engine support, semantic binding compatibility, and documented fallbacks before
runtime/save/adapter package handoff.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
ASSET_REGISTRY_ROOT = REPO_ROOT / "packages" / "asset-registry"
sys.path.insert(0, str(ASSET_REGISTRY_ROOT))

from asset_reference_preflight import (  # noqa: E402
    ASSET_PREFLIGHT_REPORT_SCHEMA,
    AssetPreflightPhase,
    validate_all_asset_handoffs,
    validate_asset_preflight,
)


REPORT_SCHEMA = "xace.asset_reference_validation_check_report.v1"
PHASES = tuple(phase.value for phase in AssetPreflightPhase)
ENGINES = ("godot", "unity", "unreal")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "target-codex-task53-asset-validation" / "report.json",
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=REPO_ROOT / "target-codex-task53-asset-validation" / "artifacts",
    )
    parser.add_argument("--json", action="store_true", help="Print the report JSON.")
    args = parser.parse_args(argv)

    artifact_dir = args.artifact_dir.resolve()
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    fixture_root = artifact_dir / "fixture_project"
    assets_dir = fixture_root / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    hit_wav = write_asset(assets_dir / "hero_hit.wav", b"xace-test-audio-hit\n")
    mesh_glb = write_asset(assets_dir / "hero_mesh.glb", b"xace-test-mesh-glb\n")
    controller = write_asset(assets_dir / "hero_controller.controller", b"xace-test-controller\n")
    wrong_ext = write_asset(assets_dir / "hero_hit.uasset", b"xace-test-uasset-audio\n")

    valid_cgs = cgs_with_assets(
        [
            asset_ref("hero_hit_sfx_v1", "AudioClip", "Linked", hit_wav, fixture_root),
            {
                "id": "hero_theme_music_v1",
                "asset_type": "AudioMusic",
                "status": "Missing",
                "fallback_policy": {
                    "kind": "silent_audio",
                    "reason": "optional background music can fall back to silence",
                },
            },
        ],
        semantic_asset=asset_ref("hero_hit_sfx_v1", "AudioClip", "Linked", hit_wav, fixture_root),
    )
    write_json(artifact_dir / "valid_asset_preflight_fixture.cgs.json", valid_cgs)

    valid_reports = validate_all_asset_handoffs(
        valid_cgs,
        project_root=fixture_root,
        engines=ENGINES,
        phases=PHASES,
    )
    valid_matrix_ok = all(report.ok for report in valid_reports)
    valid_matrix = [
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
        for report in valid_reports
    ]

    phase_block_case = cgs_with_assets(
        [
            {
                "id": "hero_missing_ref_v1",
                "asset_type": "AudioClip",
                "status": "Unresolved",
            }
        ]
    )
    phase_block_reports = [
        validate_asset_preflight(
            phase_block_case,
            phase=phase,
            project_root=fixture_root,
            engine="godot",
        )
        for phase in PHASES
    ]
    phase_block_ok = all(
        report.blocked and has_code(report, "UNRESOLVED_ASSET_REF")
        for report in phase_block_reports
    )

    fallback_unresolved_case = cgs_with_assets(
        [
            {
                "id": "hero_optional_sfx_v1",
                "asset_type": "AudioClip",
                "status": "Unresolved",
                "fallback_policy": {
                    "kind": "silent_audio",
                    "reason": "optional audio is muted until linked",
                },
            }
        ]
    )
    fallback_unresolved_report = validate_asset_preflight(
        fallback_unresolved_case,
        phase="runtime",
        project_root=fixture_root,
        engine="godot",
    )

    blocked_cases = [
        case(
            "missing_hash",
            cgs_with_assets([asset_ref("hero_no_hash_sfx_v1", "AudioClip", "Linked", hit_wav, fixture_root, include_hash=False)]),
            "ASSET_HASH_MISSING",
        ),
        case(
            "invalid_hash",
            cgs_with_assets([asset_ref("hero_bad_hash_sfx_v1", "AudioClip", "Linked", hit_wav, fixture_root, sha256="not-a-sha")]),
            "ASSET_HASH_INVALID",
        ),
        case(
            "hash_mismatch",
            cgs_with_assets([asset_ref("hero_wrong_hash_sfx_v1", "AudioClip", "Linked", hit_wav, fixture_root, sha256=sha256_text("different"))]),
            "ASSET_HASH_MISMATCH",
        ),
        case(
            "missing_file",
            cgs_with_assets(
                [
                    {
                        "id": "hero_missing_file_sfx_v1",
                        "asset_type": "AudioClip",
                        "status": "Linked",
                        "path": "assets/does_not_exist.wav",
                        "sha256": sha256_file(hit_wav),
                    }
                ]
            ),
            "MISSING_ASSET_FILE",
        ),
        case(
            "invalid_type",
            cgs_with_assets([asset_ref("hero_video_v1", "VideoClip", "Linked", hit_wav, fixture_root)]),
            "INVALID_ASSET_TYPE",
        ),
        case(
            "invalid_status",
            cgs_with_assets([asset_ref("hero_pending_sfx_v1", "AudioClip", "Ready", hit_wav, fixture_root)]),
            "INVALID_ASSET_STATUS",
        ),
        case(
            "unsupported_engine_extension",
            cgs_with_assets([asset_ref("hero_uasset_sfx_v1", "AudioClip", "Linked", wrong_ext, fixture_root)]),
            "ASSET_ENGINE_UNSUPPORTED_EXTENSION",
        ),
        case(
            "semantic_type_mismatch",
            cgs_with_assets(
                [],
                semantic_asset=asset_ref("hero_mesh_as_audio_v1", "Mesh", "Linked", mesh_glb, fixture_root),
            ),
            "ASSET_TYPE_MISMATCH",
        ),
    ]

    blocked_matrix: list[dict[str, Any]] = []
    blocked_matrix_ok = True
    for item in blocked_cases:
        report = validate_asset_preflight(
            item["cgs"],
            phase="adapter_package_handoff",
            project_root=fixture_root,
            engine="godot",
        )
        matched = report.blocked and has_code(report, item["expected_code"])
        blocked_matrix_ok = blocked_matrix_ok and matched
        blocked_matrix.append(
            {
                "case": item["name"],
                "phase": "adapter_package_handoff",
                "engine": "godot",
                "expected_code": item["expected_code"],
                "matched": matched,
                "report": report.to_dict(),
            }
        )

    controller_cgs = cgs_with_assets(
        [asset_ref("hero_controller_anim_v1", "AnimationController", "Linked", controller, fixture_root)]
    )
    godot_controller = validate_asset_preflight(
        controller_cgs,
        phase="adapter_package_handoff",
        project_root=fixture_root,
        engine="godot",
    )
    unity_controller = validate_asset_preflight(
        controller_cgs,
        phase="adapter_package_handoff",
        project_root=fixture_root,
        engine="unity",
    )
    engine_support_ok = (
        godot_controller.blocked
        and has_code(godot_controller, "ASSET_ENGINE_UNSUPPORTED_TYPE")
        and unity_controller.ok
    )

    checks = [
        check_result(
            "production validator module",
            ASSET_PREFLIGHT_REPORT_SCHEMA == "xace.asset_reference_preflight_report.v1",
            "asset_reference_preflight exposes a stable report schema.",
        ),
        check_result(
            "valid runtime/save/adapter-package handoff matrix",
            valid_matrix_ok and len(valid_reports) == len(PHASES) * len(ENGINES),
            "Linked, hashed audio assets plus documented missing-asset fallback pass all phases/engines.",
        ),
        check_result(
            "unresolved blocked in every phase",
            phase_block_ok,
            "UNRESOLVED references without fallback block runtime, save, and adapter package handoff.",
        ),
        check_result(
            "unresolved documented fallback allowed",
            fallback_unresolved_report.ok
            and has_code(fallback_unresolved_report, "DOCUMENTED_FALLBACK_USED"),
            "UNRESOLVED optional reference with fallback policy is recorded as fallback evidence.",
        ),
        check_result(
            "blocked asset matrix",
            blocked_matrix_ok,
            "Hashes, file presence, enum values, extensions, and semantic playback type mismatch all block.",
        ),
        check_result(
            "engine support discrimination",
            engine_support_ok,
            "Godot rejects unsupported AnimationController handoff while Unity accepts the same linked .controller asset.",
        ),
    ]

    report = {
        "schema": REPORT_SCHEMA,
        "task": "X10-053",
        "x10_053_complete": all(item["ok"] for item in checks),
        "production_validator": "packages/asset-registry/asset_reference_preflight.py",
        "phases_checked": list(PHASES),
        "engines_checked": list(ENGINES),
        "valid_phase_engine_matrix": valid_matrix,
        "phase_block_matrix": [
            {
                "phase": item.phase.value,
                "engine": item.engine,
                "blocked": item.blocked,
                "issue_codes": [issue.code for issue in item.issues],
            }
            for item in phase_block_reports
        ],
        "documented_fallback_report": fallback_unresolved_report.to_dict(),
        "blocked_asset_matrix": blocked_matrix,
        "engine_support_reports": {
            "godot": godot_controller.to_dict(),
            "unity": unity_controller.to_dict(),
        },
        "checks": checks,
        "artifacts": [
            str((artifact_dir / "valid_asset_preflight_fixture.cgs.json").relative_to(REPO_ROOT)),
        ],
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        status = "PASSED" if report["x10_053_complete"] else "FAILED"
        print(f"asset reference validation check {status}: {args.output}")

    return 0 if report["x10_053_complete"] else 1


def write_asset(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def cgs_with_assets(
    assets: list[dict[str, Any]],
    *,
    semantic_asset: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cgs: dict[str, Any] = {
        "metadata": {
            "name": "X10-053 Asset Reference Validation Fixture",
            "version": "0.1.0",
            "schema_version": "0.1.0",
        },
        "assets": assets,
        "global_systems": [],
        "modes": [],
    }
    if semantic_asset is not None:
        cgs["semantic_bindings"] = {
            "bindings": [
                {
                    "binding_id": "bind_asset_validation_audio",
                    "event_name": "interaction.accepted",
                    "playback_kind": "Audio",
                    "asset": semantic_asset,
                    "semantic_action": "play",
                    "entity_selector": "SourceEntity",
                    "parameters": {},
                    "priority": 0,
                }
            ]
        }
    return cgs


def asset_ref(
    asset_id: str,
    asset_type: str,
    status: str,
    path: Path,
    project_root: Path,
    *,
    sha256: str | None = None,
    include_hash: bool = True,
) -> dict[str, Any]:
    ref: dict[str, Any] = {
        "id": asset_id,
        "asset_type": asset_type,
        "status": status,
        "path": path.relative_to(project_root).as_posix(),
    }
    if include_hash:
        ref["sha256"] = sha256 if sha256 is not None else sha256_file(path)
    return ref


def case(name: str, cgs: dict[str, Any], expected_code: str) -> dict[str, Any]:
    return {
        "name": name,
        "cgs": cgs,
        "expected_code": expected_code,
    }


def check_result(name: str, ok: bool, detail: str) -> dict[str, Any]:
    return {
        "name": name,
        "ok": bool(ok),
        "detail": detail,
    }


def has_code(report: Any, code: str) -> bool:
    return any(issue.code == code for issue in report.issues)


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
