import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path


sys_path_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if sys_path_root not in sys.path:
    sys.path.insert(0, sys_path_root)

from asset_reference_preflight import (  # noqa: E402
    validate_asset_preflight,
    validate_before_adapter_handoff,
    validate_before_adapter_package_handoff,
    validate_before_runtime,
    validate_before_save,
)


class TestAssetReferencePreflight(unittest.TestCase):
    def test_linked_hashed_asset_passes_every_boundary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            asset_path = root / "assets" / "hit.wav"
            asset_path.parent.mkdir(parents=True)
            asset_path.write_bytes(b"xace-audio\n")
            cgs = cgs_with_asset(asset(asset_path, root))

            reports = [
                validate_before_runtime(cgs, project_root=root, engine="godot"),
                validate_before_adapter_package_handoff(cgs, project_root=root, engine="godot"),
                validate_before_save(cgs, project_root=root, engine="godot"),
                validate_before_adapter_handoff(cgs, project_root=root, engine="godot"),
            ]

            self.assertTrue(all(report.ok for report in reports))
            self.assertTrue(all(report.asset_hashes_checked == 1 for report in reports))

    def test_unresolved_ref_blocks_without_fallback(self):
        cgs = cgs_with_asset(
            {
                "id": "hero_missing_sfx_v1",
                "asset_type": "AudioClip",
                "status": "Unresolved",
            }
        )

        report = validate_asset_preflight(
            cgs,
            phase="runtime",
            project_root=Path("."),
            engine="godot",
        )

        self.assertTrue(report.blocked)
        self.assertIn("UNRESOLVED_ASSET_REF", [issue.code for issue in report.issues])

    def test_documented_fallback_allows_optional_unresolved_ref(self):
        cgs = cgs_with_asset(
            {
                "id": "hero_optional_sfx_v1",
                "asset_type": "AudioClip",
                "status": "Unresolved",
                "fallback_policy": {"kind": "silent_audio"},
            }
        )

        report = validate_asset_preflight(
            cgs,
            phase="runtime",
            project_root=Path("."),
            engine="godot",
        )

        self.assertTrue(report.ok)
        self.assertEqual(report.fallbacks_documented, 1)
        self.assertIn("DOCUMENTED_FALLBACK_USED", [issue.code for issue in report.issues])

    def test_hash_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            asset_path = root / "assets" / "hit.wav"
            asset_path.parent.mkdir(parents=True)
            asset_path.write_bytes(b"xace-audio\n")
            cgs = cgs_with_asset(
                asset(
                    asset_path,
                    root,
                    sha256=hashlib.sha256(b"different").hexdigest(),
                )
            )

            report = validate_asset_preflight(
                cgs,
                phase="adapter_handoff",
                project_root=root,
                engine="godot",
            )

            self.assertTrue(report.blocked)
            self.assertIn("ASSET_HASH_MISMATCH", [issue.code for issue in report.issues])

    def test_engine_support_matrix_rejects_godot_controller_handoff(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            controller = root / "assets" / "hero.controller"
            controller.parent.mkdir(parents=True)
            controller.write_bytes(b"xace-controller\n")
            cgs = cgs_with_asset(
                asset(
                    controller,
                    root,
                    asset_id="hero_controller_anim_v1",
                    asset_type="AnimationController",
                )
            )

            godot_report = validate_asset_preflight(
                cgs,
                phase="adapter_handoff",
                project_root=root,
                engine="godot",
            )
            unity_report = validate_asset_preflight(
                cgs,
                phase="adapter_handoff",
                project_root=root,
                engine="unity",
            )

            self.assertTrue(godot_report.blocked)
            self.assertIn(
                "ASSET_ENGINE_UNSUPPORTED_TYPE",
                [issue.code for issue in godot_report.issues],
            )
            self.assertTrue(unity_report.ok)


def cgs_with_asset(asset_entry):
    return {
        "metadata": {"name": "asset preflight unit test", "schema_version": "0.1.0"},
        "assets": [asset_entry],
        "global_systems": [],
        "modes": [],
    }


def asset(
    path: Path,
    project_root: Path,
    *,
    asset_id: str = "hero_hit_sfx_v1",
    asset_type: str = "AudioClip",
    sha256: str | None = None,
):
    return {
        "id": asset_id,
        "asset_type": asset_type,
        "status": "Linked",
        "path": path.relative_to(project_root).as_posix(),
        "sha256": sha256 or hashlib.sha256(path.read_bytes()).hexdigest(),
    }


if __name__ == "__main__":
    unittest.main()
