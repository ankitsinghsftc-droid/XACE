import json
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine_project_inventory import INVENTORY_CATEGORIES, scan_engine_project_inventory
from engine_migration_wizard import (
    build_manual_migration_plan,
    materialize_manual_migration_draft,
    revert_manual_migration_draft,
)
from adapter_installation import (
    ADAPTER_ENGINE_INSTALL_MANIFEST,
    install_or_update_adapter,
    rollback_latest_adapter_transaction,
    uninstall_adapter,
)
from project_creator import CreateProjectRequest, ProjectCreator, ProjectCreationError, ProjectImportValidationError
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
            self.assertEqual(result.engine_inventory["detected_engine_type"], "godot")
            self.assertTrue(result.manifest.adapter_config["engine_project_inventory"]["reference_only"])

    def test_engine_inventory_detects_all_supported_engines_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixtures = {
                "godot": _make_godot_fixture(root / "GodotGame"),
                "unity": _make_unity_fixture(root / "UnityGame"),
                "unreal": _make_unreal_fixture(root / "UnrealGame"),
            }

            for engine, engine_root in fixtures.items():
                before = _file_signature(engine_root)
                report = scan_engine_project_inventory(engine_root, expected_engine_type=engine)
                after = _file_signature(engine_root)

                self.assertTrue(report["ok"], report)
                self.assertFalse(report["refused"], report)
                self.assertEqual(report["detected_engine_type"], engine)
                self.assertEqual(before, after)
                for category in INVENTORY_CATEGORIES:
                    self.assertGreaterEqual(report["inventory_counts"][category], 1, (engine, category, report))
                    for reference in report["inventory"][category]["references"]:
                        self.assertTrue(reference["reference_only"], reference)

    def test_import_engine_project_refuses_ambiguous_markers_before_writing_xace_project(self):
        with tempfile.TemporaryDirectory() as temp:
            engine_root = Path(temp) / "AmbiguousGame"
            engine_root.mkdir()
            (engine_root / "project.godot").write_text("[application]\n", encoding="utf-8")
            (engine_root / "Assets").mkdir()
            (engine_root / "ProjectSettings").mkdir()
            (engine_root / "ProjectSettings" / "ProjectVersion.txt").write_text("m_EditorVersion: 2022.3\n", encoding="utf-8")
            xace_root = Path(temp) / "WrappedXace"
            before = _file_signature(engine_root)

            with self.assertRaises(ProjectImportValidationError) as raised:
                ProjectCreator().import_engine_project(
                    engine_project_dir=engine_root,
                    xace_project_dir=xace_root,
                    name="Ambiguous",
                    engine_type="godot",
                    template_id="blank_3d",
                )

            self.assertEqual(raised.exception.report["reason"], "AMBIGUOUS_ENGINE_MARKERS")
            self.assertEqual(before, _file_signature(engine_root))
            self.assertFalse((xace_root / "xace.project.json").exists())

    def test_manual_migration_wizard_builds_reversible_reference_mappings(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixtures = {
                "godot": _make_godot_fixture(root / "GodotGame"),
                "unity": _make_unity_fixture(root / "UnityGame"),
                "unreal": _make_unreal_fixture(root / "UnrealGame"),
            }

            for engine, engine_root in fixtures.items():
                base_cgs = make_template("blank_3d", f"{engine} Migration")
                original_cgs = json.loads(json.dumps(base_cgs, sort_keys=True))
                before = _file_signature(engine_root)
                plan = build_manual_migration_plan(
                    engine_root,
                    expected_engine_type=engine,
                    base_cgs=base_cgs,
                )

                self.assertTrue(plan["ok"], plan)
                self.assertEqual(before, _file_signature(engine_root))
                self.assertGreaterEqual(plan["draft_summary"]["scene_modes"], 1, plan)
                self.assertGreaterEqual(plan["draft_summary"]["starter_actors"], 1, plan)
                self.assertGreaterEqual(plan["draft_summary"]["asset_references"], 1, plan)
                self.assertGreaterEqual(plan["draft_summary"]["semantic_binding_candidates"], 1, plan)
                self.assertEqual(plan["draft_summary"]["reversible_mappings"], len(plan["mappings"]))
                self.assertTrue(plan["manual_work_report"]["items"], plan)

                for evidence in plan["file_evidence"]:
                    path = engine_root / evidence["path"]
                    self.assertTrue(path.is_file(), evidence)
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), evidence["sha256"])

                draft = materialize_manual_migration_draft(base_cgs, plan)
                cgs = draft["cgs"]
                self.assertGreater(len(cgs["modes"]), len(base_cgs["modes"]))
                self.assertTrue(cgs.get("assets"), cgs)
                self.assertTrue(cgs.get("semantic_bindings", {}).get("bindings"), cgs)
                imported_actors = [
                    actor
                    for mode in cgs["modes"]
                    for actor in mode.get("actors", [])
                    if actor.get("migration_source")
                ]
                self.assertTrue(imported_actors, cgs)
                self.assertTrue(
                    any(
                        component_record["name"] in {"COMP_TRANSFORM_V1", "COMP_IDENTITY_V1"}
                        for actor in imported_actors
                        for component_record in actor.get("components", [])
                    ),
                    imported_actors,
                )

                reverted = revert_manual_migration_draft(cgs, draft["rollback"])
                self.assertEqual(original_cgs, reverted)

    def test_adapter_install_update_rollback_uninstall_preserves_user_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_v1 = root / 'adapter_v1'
            source_v2 = root / 'adapter_v2'
            source_v1.mkdir()
            source_v2.mkdir()
            (source_v1 / 'xace_adapter.gd').write_text('extends Node\n# v1\n', encoding='utf-8')
            (source_v1 / 'xace_adapter_manifest.json').write_text('{}\n', encoding='utf-8')
            (source_v2 / 'xace_adapter.gd').write_text('extends Node\n# v2\n', encoding='utf-8')
            (source_v2 / 'xace_task59_update_marker.txt').write_text('new in v2\n', encoding='utf-8')

            engine_root = root / 'GodotGame'
            (engine_root / 'addons' / 'xace').mkdir(parents=True)
            (engine_root / 'project.godot').write_text('[application]\n', encoding='utf-8')
            user_file = engine_root / 'addons' / 'xace' / 'USER_KEEP.txt'
            user_file.write_text('creator-owned note\n', encoding='utf-8')
            user_hash = hashlib.sha256(user_file.read_bytes()).hexdigest()
            adapter_file = engine_root / 'addons' / 'xace' / 'xace_adapter.gd'
            update_marker = engine_root / 'addons' / 'xace' / 'xace_task59_update_marker.txt'
            manifest_path = engine_root / 'addons' / 'xace' / ADAPTER_ENGINE_INSTALL_MANIFEST

            install = install_or_update_adapter(
                source_root=source_v1,
                engine_project_root=engine_root,
                engine_type='godot',
                generated_files={'plugin.cfg': '[plugin]\nname="XACE"\n'},
            )
            self.assertTrue(install['ok'], install)
            v1_hash = hashlib.sha256(adapter_file.read_bytes()).hexdigest()
            self.assertTrue(manifest_path.exists())

            update = install_or_update_adapter(
                source_root=source_v2,
                engine_project_root=engine_root,
                engine_type='godot',
                overwrite=True,
                generated_files={'plugin.cfg': '[plugin]\nname="XACE"\nversion="2"\n'},
            )
            self.assertTrue(update['ok'], update)
            self.assertNotEqual(v1_hash, hashlib.sha256(adapter_file.read_bytes()).hexdigest())
            self.assertTrue(update_marker.exists())

            rollback = rollback_latest_adapter_transaction(
                engine_project_root=engine_root,
                engine_type='godot',
            )
            self.assertTrue(rollback['ok'], rollback)
            self.assertEqual(v1_hash, hashlib.sha256(adapter_file.read_bytes()).hexdigest())
            self.assertFalse(update_marker.exists())

            reinstall = install_or_update_adapter(
                source_root=source_v2,
                engine_project_root=engine_root,
                engine_type='godot',
                overwrite=True,
                generated_files={'plugin.cfg': '[plugin]\nname="XACE"\nversion="2"\n'},
            )
            self.assertTrue(reinstall['ok'], reinstall)
            uninstall = uninstall_adapter(engine_project_root=engine_root, engine_type='godot')
            self.assertTrue(uninstall['ok'], uninstall)
            self.assertFalse(adapter_file.exists())
            self.assertFalse(update_marker.exists())
            self.assertFalse(manifest_path.exists())
            self.assertTrue(user_file.exists())
            self.assertEqual(user_hash, hashlib.sha256(user_file.read_bytes()).hexdigest())

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


def _make_godot_fixture(root: Path) -> Path:
    (root / 'scenes').mkdir(parents=True)
    (root / 'assets').mkdir()
    (root / 'scripts').mkdir()
    (root / 'addons' / 'xace_demo').mkdir(parents=True)
    project_text = '[application]\nconfig/name=GodotGame\n\n[input]\njump={deadzone=0.5}\n'
    (root / 'project.godot').write_text(project_text, encoding='utf-8')
    (root / 'scenes' / 'main.tscn').write_text(
        '[gd_scene format=3]\n[node name="Player" type="CharacterBody3D"]\n[node name="Pickup" type="Node3D"]\n',
        encoding='utf-8',
    )
    (root / 'assets' / 'player.png').write_bytes(b'png-reference')
    (root / 'assets' / 'impact.wav').write_bytes(b'wav-reference')
    (root / 'scripts' / 'player.gd').write_text('extends Node\n', encoding='utf-8')
    (root / 'addons' / 'xace_demo' / 'plugin.cfg').write_text('[plugin]\nname=XACE Demo\n', encoding='utf-8')
    return root


def _make_unity_fixture(root: Path) -> Path:
    (root / 'Assets' / 'Scenes').mkdir(parents=True)
    (root / 'Assets' / 'Scripts').mkdir()
    (root / 'Assets' / 'Prefabs').mkdir()
    (root / 'Assets' / 'Plugins' / 'Native').mkdir(parents=True)
    (root / 'ProjectSettings').mkdir()
    (root / 'Packages').mkdir()
    (root / 'Assets' / 'Scenes' / 'Main.unity').write_text(
        '%YAML 1.1\n--- !u!1 &1\nGameObject:\n  m_Name: Player\n--- !u!1 &2\nGameObject:\n  m_Name: Pickup\n',
        encoding='utf-8',
    )
    (root / 'Assets' / 'Scripts' / 'Player.cs').write_text('public class Player {}\n', encoding='utf-8')
    (root / 'Assets' / 'Prefabs' / 'Player.prefab').write_text('%YAML 1.1\n', encoding='utf-8')
    (root / 'Assets' / 'Audio').mkdir()
    (root / 'Assets' / 'Audio' / 'impact.wav').write_bytes(b'wav-reference')
    (root / 'Assets' / 'Plugins' / 'Native' / 'XaceNative.dll').write_bytes(b'dll-reference')
    (root / 'Assets' / 'Controls.inputactions').write_text('{}\n', encoding='utf-8')
    (root / 'ProjectSettings' / 'ProjectVersion.txt').write_text('m_EditorVersion: 2022.3\n', encoding='utf-8')
    (root / 'ProjectSettings' / 'InputManager.asset').write_text('%YAML 1.1\n', encoding='utf-8')
    (root / 'Packages' / 'manifest.json').write_text('{}\n', encoding='utf-8')
    return root


def _make_unreal_fixture(root: Path) -> Path:
    (root / 'Content' / 'Maps').mkdir(parents=True)
    (root / 'Content' / 'Props').mkdir()
    (root / 'Source' / 'UnrealGame').mkdir(parents=True)
    (root / 'Plugins' / 'XaceDemo').mkdir(parents=True)
    (root / 'Config').mkdir()
    (root / 'UnrealGame.uproject').write_text('{FileVersion:3}\n', encoding='utf-8')
    (root / 'Content' / 'Maps' / 'Main.umap').write_text('Begin Actor Name=BP_Player_C\nBegin Actor Name=BP_Pickup_C\n', encoding='utf-8')
    (root / 'Content' / 'Props' / 'Crate.uasset').write_bytes(b'uasset-reference')
    (root / 'Content' / 'Audio').mkdir()
    (root / 'Content' / 'Audio' / 'impact.wav').write_bytes(b'wav-reference')
    (root / 'Source' / 'UnrealGame' / 'Player.cpp').write_text('void Player() {}\n', encoding='utf-8')
    (root / 'Plugins' / 'XaceDemo' / 'XaceDemo.uplugin').write_text('{FileVersion:3}\n', encoding='utf-8')
    (root / 'Config' / 'DefaultInput.ini').write_text('[/Script/Engine.InputSettings]\n', encoding='utf-8')
    return root


def _file_signature(root: Path) -> dict[str, dict[str, int | str]]:
    signature: dict[str, dict[str, int | str]] = {}
    for path in sorted(root.rglob('*'), key=lambda item: item.as_posix().lower()):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        data = path.read_bytes()
        stat = path.stat()
        signature[rel] = {
            'sha256': hashlib.sha256(data).hexdigest(),
            'size': stat.st_size,
            'mtime_ns': stat.st_mtime_ns,
        }
    return signature


if __name__ == "__main__":
    unittest.main(verbosity=2)
