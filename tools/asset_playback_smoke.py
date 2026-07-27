"""
Editor-free asset playback smoke test.

This proves the shared asset/audio/animation path without opening any engine:

    asset files -> AssetImportWorkflow -> linked manifest entries
    -> CGS semantic_bindings -> runtime CGS load

Runtime-core unit tests validate that those CGS bindings resolve semantic events
into engine playback commands. This smoke covers the Python/project side and the
runtime load side with real imported files.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
ASSET_PLAYBACK_CGS_HASH = "e" * 64
ASSET_REGISTRY = REPO_ROOT / "packages" / "asset-registry"
sys.path.insert(0, str(ASSET_REGISTRY))

from asset_import_workflow import AssetCopyPolicy, AssetImportWorkflow  # noqa: E402
from asset_manifest import AssetManifest  # noqa: E402
from asset_type_enum import AssetType  # noqa: E402


RUST_ASSET_TYPES = {
    AssetType.ANIMATION_CLIP: "AnimationClip",
    AssetType.AUDIO_CLIP: "AudioClip",
    AssetType.PARTICLE: "Particle",
}


def main() -> int:
    args = parse_args()
    runtime_bin = Path(args.runtime_bin).resolve()

    try:
        with tempfile.TemporaryDirectory(prefix="xace-asset-playback-") as tmp:
            root = Path(tmp)
            source_dir = root / "source_assets"
            project_dir = root / "project"
            project_asset_root = project_dir / "assets"
            source_dir.mkdir(parents=True)
            project_asset_root.mkdir(parents=True)

            write_sample_assets(source_dir)
            manifest = AssetManifest()
            workflow = AssetImportWorkflow(manifest)
            plan = workflow.scan_folder(
                source_dir,
                copy_policy=AssetCopyPolicy.COPY_TO_PROJECT,
                entity_type="asset",
            )
            require(len(plan.assets) == 3, f"expected 3 supported assets, got {len(plan.assets)}")
            require(len(plan.skipped) == 1, f"expected 1 skipped file, got {len(plan.skipped)}")

            result = workflow.apply_plan(plan, project_asset_root=project_asset_root)
            require(result.imported_count == 3, f"expected 3 imported assets, got {result.imported_count}")
            require(not result.warnings, f"asset import warnings: {result.warnings}")
            require(manifest.compute_metrics().linked_count == 3, "manifest did not mark all assets linked")

            imported = imported_by_type(result.imported)
            cgs_path = project_dir / "game.cgs.json"
            write_json(cgs_path, build_cgs(imported))

            if not args.skip_runtime:
                run_runtime(runtime_bin, cgs_path, timeout=args.timeout)

            print(json.dumps({
                "ok": True,
                "imported": sorted(asset.asset_id for asset in result.imported),
                "bindings": 3,
                "skipped": [item.relative_path for item in result.skipped],
                "runtime_checked": not args.skip_runtime,
            }, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"asset playback smoke failed: {exc}", file=sys.stderr)
        return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test asset import to semantic playback CGS.")
    parser.add_argument(
        "--runtime-bin",
        default=str(REPO_ROOT / "target-codex-certify" / "debug" / runtime_binary_name()),
        help="Path to xace_runtime built by certification.",
    )
    parser.add_argument(
        "--skip-runtime",
        action="store_true",
        help="Only generate/import/validate the CGS shape; do not launch xace_runtime.",
    )
    parser.add_argument("--timeout", type=float, default=8.0)
    return parser.parse_args()


def runtime_binary_name() -> str:
    return "xace_runtime.exe" if os.name == "nt" else "xace_runtime"


def write_sample_assets(source_dir: Path) -> None:
    (source_dir / "character_idle.anim").write_text(
        "xace smoke animation clip placeholder\n",
        encoding="utf-8",
    )
    (source_dir / "interaction_click.wav").write_bytes(b"XACE smoke audio clip\n")
    (source_dir / "interaction_spark.vfx").write_text(
        "xace smoke particle effect placeholder\n",
        encoding="utf-8",
    )
    (source_dir / "notes.txt").write_text("unsupported file should be skipped\n", encoding="utf-8")


def imported_by_type(imported_assets: list[Any]) -> dict[AssetType, Any]:
    by_type = {asset.asset_type: asset for asset in imported_assets}
    required = [AssetType.ANIMATION_CLIP, AssetType.AUDIO_CLIP, AssetType.PARTICLE]
    missing = [asset_type.value for asset_type in required if asset_type not in by_type]
    require(not missing, f"missing imported asset types: {missing}")
    return by_type


def build_cgs(imported: dict[AssetType, Any]) -> dict[str, Any]:
    return {
        "metadata": {
            "name": "Asset Playback Smoke",
            "version": "0.1.0",
            "schema_version": "0.1.0",
            "cgs_hash": ASSET_PLAYBACK_CGS_HASH,
        },
        "semantic_bindings": {
            "bindings": [
                binding(
                    "bind_asset_animation",
                    "Animation",
                    imported[AssetType.ANIMATION_CLIP],
                    "play",
                    "SourceEntity",
                    priority=0,
                    parameters={"blend": "0.1"},
                ),
                binding(
                    "bind_asset_audio",
                    "Audio",
                    imported[AssetType.AUDIO_CLIP],
                    "play",
                    "SourceEntity",
                    priority=1,
                ),
                binding(
                    "bind_asset_vfx",
                    "Vfx",
                    imported[AssetType.PARTICLE],
                    "spawn",
                    "TargetEntity",
                    priority=2,
                ),
            ],
        },
        "global_systems": [],
        "modes": [
            {
                "id": "default",
                "schema_version": "0.1.0",
                "is_default": True,
                "actors": [
                    actor("player", 0),
                    actor("target", 1),
                ],
                "systems": [],
                "rules": [],
            },
        ],
    }


def binding(
    binding_id: str,
    playback_kind: str,
    imported_asset: Any,
    semantic_action: str,
    entity_selector: str,
    *,
    priority: int,
    parameters: dict[str, str] | None = None,
) -> dict[str, Any]:
    rust_type = RUST_ASSET_TYPES[imported_asset.asset_type]
    return {
        "binding_id": binding_id,
        "event_name": "interaction.accepted",
        "playback_kind": playback_kind,
        "asset": {
            "id": imported_asset.asset_id,
            "asset_type": rust_type,
            "status": "Linked",
        },
        "semantic_action": semantic_action,
        "entity_selector": entity_selector,
        "parameters": parameters or {},
        "priority": priority,
    }


def actor(actor_id: str, x: int) -> dict[str, Any]:
    return {
        "id": actor_id,
        "spawn_count": 1,
        "components": [
            {
                "type_id": 1,
                "name": "COMP_TRANSFORM_V1",
                "defaults": {"position_x": x, "position_y": 0, "position_z": 0},
            },
            {
                "type_id": 2,
                "name": "COMP_IDENTITY_V1",
                "defaults": {"name": actor_id},
            },
        ],
    }


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def run_runtime(runtime_bin: Path, cgs_path: Path, *, timeout: float) -> None:
    require(runtime_bin.exists(), f"runtime binary does not exist: {runtime_bin}")
    command = [
        str(runtime_bin),
        "--cgs",
        str(cgs_path),
        "--derive-cgs-plan",
        "--no-wait",
        "--no-control",
        "--ticks",
        "1",
        "--quiet",
    ]
    completed = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"runtime returned {completed.returncode}:\n{completed.stdout[-4000:]}"
        )


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


if __name__ == "__main__":
    raise SystemExit(main())
