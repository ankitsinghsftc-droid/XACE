"""
test_asset_import_workflow.py - scan/import/repair tests for asset workflow.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asset_import_workflow import (
    AssetCopyPolicy,
    AssetImportWorkflow,
    infer_asset_type,
    sha256_file,
)
from asset_manifest import AssetManifest
from asset_reference import AssetReference
from asset_status_enum import AssetStatus
from asset_type_enum import AssetType
from placeholder_registry import PlaceholderRegistry


class TestAssetImportWorkflow(unittest.TestCase):

    def _write(self, root: Path, relative: str, data: bytes = b"xace") -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_infer_asset_type_general_extensions(self):
        self.assertEqual(infer_asset_type("hero.glb"), AssetType.MESH)
        self.assertEqual(infer_asset_type("hero_walk.anim"), AssetType.ANIMATION_CLIP)
        self.assertEqual(infer_asset_type("hero.controller"), AssetType.ANIMATION_CONTROLLER)
        self.assertEqual(infer_asset_type("footstep.wav"), AssetType.AUDIO_CLIP)
        self.assertEqual(infer_asset_type("main_theme.ogg"), AssetType.AUDIO_MUSIC)
        self.assertEqual(infer_asset_type("ui_button.png"), AssetType.SPRITE)
        self.assertEqual(infer_asset_type("albedo.png"), AssetType.TEXTURE)
        self.assertEqual(infer_asset_type("spark.vfx"), AssetType.PARTICLE)
        self.assertEqual(infer_asset_type("room.tscn"), AssetType.PREFAB)

    def test_scan_folder_is_deterministic_and_hashes_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mesh = self._write(root, "b/hero.glb", b"mesh")
            self._write(root, "a/readme.txt", b"ignore")
            audio = self._write(root, "a/footstep.wav", b"sound")

            manifest = AssetManifest()
            workflow = AssetImportWorkflow(manifest)
            plan = workflow.scan_folder(root)

            self.assertEqual([a.relative_path for a in plan.assets], ["a/footstep.wav", "b/hero.glb"])
            self.assertEqual(plan.assets[0].sha256, sha256_file(audio))
            self.assertEqual(plan.assets[1].sha256, sha256_file(mesh))
            self.assertEqual(len(plan.skipped), 1)
            self.assertIn("Unsupported extension", plan.skipped[0].reason)

    def test_import_folder_links_assets_in_place(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mesh = self._write(root, "hero.glb")

            manifest = AssetManifest()
            placeholders = PlaceholderRegistry()
            workflow = AssetImportWorkflow(manifest, placeholders)
            result = workflow.import_folder(root)

            self.assertEqual(result.imported_count, 1)
            imported = result.imported[0]
            self.assertEqual(imported.asset_id, "asset_hero_mesh_v1")
            self.assertEqual(imported.resolved_path, str(mesh.resolve()))

            ref = manifest.get("asset_hero_mesh_v1")
            self.assertIsNotNone(ref)
            self.assertEqual(ref.status, AssetStatus.LINKED)
            self.assertFalse(placeholders.is_tracked("asset_hero_mesh_v1"))

    def test_import_folder_can_copy_to_project_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "source"
            asset_root = Path(temp) / "project_assets"
            source = self._write(root, "hero.glb", b"mesh")

            manifest = AssetManifest()
            workflow = AssetImportWorkflow(manifest)
            result = workflow.import_folder(
                root,
                copy_policy=AssetCopyPolicy.COPY_TO_PROJECT,
                project_asset_root=asset_root,
            )

            imported = result.imported[0]
            copied = Path(imported.resolved_path)
            self.assertTrue(copied.exists())
            self.assertNotEqual(copied, source.resolve())
            self.assertEqual(copied.read_bytes(), b"mesh")
            self.assertIn("mesh", copied.as_posix().lower())

    def test_import_versions_duplicate_asset_ids_deterministically(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._write(root, "one/hero.glb")
            self._write(root, "two/hero.glb")

            manifest = AssetManifest()
            workflow = AssetImportWorkflow(manifest)
            result = workflow.import_folder(root)

            self.assertEqual(
                [asset.asset_id for asset in result.imported],
                ["asset_hero_mesh_v1", "asset_hero_mesh_v2"],
            )

    def test_suggest_repairs_for_missing_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._write(root, "recovered/hero.glb")

            manifest = AssetManifest()
            ref = AssetReference.make_placeholder("asset_hero_mesh_v1", AssetType.MESH)
            ref.link(str(root / "old" / "hero.glb"))
            manifest.register(ref)
            manifest.mark_missing("asset_hero_mesh_v1")

            workflow = AssetImportWorkflow(manifest)
            suggestions = workflow.suggest_repairs(root)

            self.assertEqual(len(suggestions), 1)
            self.assertEqual(suggestions[0].asset_id, "asset_hero_mesh_v1")
            self.assertGreater(suggestions[0].confidence, 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
