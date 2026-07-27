import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from project_creator import CreateProjectRequest, ProjectCreator, ProjectCreationError
from project_manifest import load_manifest, recover_manifest, save_manifest
from project_templates import canonical_template_id, list_template_ids, make_template, stable_cgs_hash


class TestProjectSystem(unittest.TestCase):

    def test_template_catalog_includes_launch_starters(self):
        ids = set(list_template_ids())
        self.assertIn("blank_3d", ids)
        self.assertIn("top_down_adventure", ids)
        self.assertIn("fps_prototype", ids)
        self.assertIn("third_person", ids)
        self.assertIn("rpg", ids)
        self.assertIn("horror_chase", ids)
        self.assertIn("action_combat", ids)
        self.assertIn("multiplayer_lobby", ids)
        self.assertEqual(canonical_template_id("zombie_chase"), "horror_chase")
        self.assertEqual(canonical_template_id("sword_combat"), "action_combat")

    def test_make_template_writes_stable_hash(self):
        cgs = make_template("rpg", "My RPG")
        self.assertEqual(cgs["metadata"]["cgs_hash"], stable_cgs_hash(cgs))
        self.assertEqual(cgs["metadata"]["template_id"], "rpg")
        systems = {system["id"] for system in cgs["modes"][0]["systems"]}
        self.assertIn("InteractionSystem", systems)
        self.assertIn("InventorySystem", systems)

    def test_create_project_writes_manifest_cgs_and_standard_dirs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "my_project"
            result = ProjectCreator().create_project(CreateProjectRequest(
                project_dir=str(root),
                name="My Game",
                engine_type="godot",
                template_id="top_down_adventure",
            ))

            self.assertTrue((root / "xace.project.json").exists())
            self.assertTrue((root / "game.cgs.json").exists())
            self.assertTrue((root / "assets").is_dir())
            self.assertTrue((root / "saves").is_dir())
            self.assertTrue((root / ".xace" / "snapshots").is_dir())
            self.assertTrue((root / ".xace" / "adapter" / "godot.json").exists())

            manifest = load_manifest(root)
            self.assertEqual(manifest.engine_type, "godot")
            self.assertEqual(manifest.template_id, "top_down_adventure")
            self.assertEqual(result.cgs_hash, json.loads((root / "game.cgs.json").read_text())["metadata"]["cgs_hash"])

    def test_create_project_refuses_existing_project_without_force(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "my_project"
            root.mkdir()
            (root / "game.cgs.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(ProjectCreationError):
                ProjectCreator().create_project(CreateProjectRequest(
                    project_dir=str(root),
                    name="My Game",
                    engine_type="godot",
                    template_id="blank_3d",
                ))

    def test_open_legacy_project_with_only_cgs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "game.cgs.json").write_text(json.dumps(make_template("blank_3d", "Legacy")), encoding="utf-8")
            opened = ProjectCreator().open_project(root)
            self.assertEqual(opened.manifest.template_id, "legacy")
            self.assertTrue(opened.warnings)

    def test_import_engine_project_can_wrap_nonempty_engine_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            engine_root = Path(temp) / "GodotGame"
            engine_root.mkdir()
            (engine_root / "project.godot").write_text("[application]\n", encoding="utf-8")

            result = ProjectCreator().import_engine_project(
                engine_project_dir=engine_root,
                xace_project_dir=engine_root,
                name="Imported Game",
                engine_type="godot",
                template_id="blank_3d",
            )

            self.assertTrue((engine_root / "xace.project.json").exists())
            self.assertEqual(result.manifest.adapter_config["engine_project_path"], str(engine_root.resolve()))

    def test_x10_016_manifest_recovery_restores_last_valid_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "my_project"
            result = ProjectCreator().create_project(CreateProjectRequest(
                project_dir=str(root),
                name="My Game",
                engine_type="godot",
                template_id="blank_3d",
            ))
            manifest = result.manifest
            manifest.name = "Renamed Game"
            save_manifest(root, manifest)
            temp_path = root / ".xace_tmp_xace.project.json.crash.tmp"
            temp_path.write_text("{partial", encoding="utf-8")
            (root / "xace.project.json").write_text("{corrupt", encoding="utf-8")

            report = recover_manifest(root)
            recovered = load_manifest(root)

            self.assertTrue(report["restored"])
            self.assertEqual(report["temp_files_removed"], 1)
            self.assertEqual(recovered.name, "My Game")
            self.assertFalse(temp_path.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
