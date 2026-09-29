"""XP-006 no-provider catalog, typed GDE and real compiler proof."""
import asyncio
import copy
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT), str(ROOT / "packages"), str(ROOT / "packages/builder-workspace/server")]
from session_manager import SessionManager, BuilderSession, _GDEOrchestrator
from src.domain_dsl.typed_operations.gameplay_catalog import GameplayCatalog, CatalogError, digest
from src.domain_dsl.typed_operations.typed_operation_executor import TypedOperationExecutor, TypedOperationExecutionError
from typed_operations.package_authoring import package_proposal, discover_packages
from tools.cgs_schema_validate import compute_cgs_hash
from tools.xp005_reference_proof import fixture


def catalog_data():
    return json.loads((ROOT / "examples/reference-mechanic/authoring.json").read_text(encoding="utf-8"))


def empty_cgs():
    cgs = fixture()
    cgs["component_schemas"] = []
    cgs["global_systems"] = []
    mode = cgs["modes"][0]
    mode["actors"] = []
    mode["systems"] = []
    mode["world"]["contract"]["objects"] = []
    mode["world"]["contract"]["capability_declarations"] = []
    cgs["metadata"]["cgs_hash"] = compute_cgs_hash(cgs)
    return cgs


class GameplayPackageAuthoringTests(unittest.TestCase):
    def setUp(self):
        self.package = catalog_data()
        self.catalog = GameplayCatalog([self.package], supported_systems=self.package["systems"] + self.package["templates"][0]["systems"])
        self.descriptor = self.catalog.descriptors()[0]
        self.cgs = empty_cgs()

    def batch(self, **selection):
        return package_proposal(package=self.descriptor, cgs=self.cgs, mode_id="reference",
            configuration_id="default", **selection)["transaction"]["typed_operation_batch"]

    def test_golden_template_compiles_to_reference_behavior_inputs(self):
        before = copy.deepcopy(self.cgs)
        batch = self.batch(template_id="reference.test_arena.v1")
        result = TypedOperationExecutor(self.catalog).execute(batch, self.cgs).proposed_cgs
        self.assertEqual(self.cgs, before)
        expected = fixture()
        # Authoring preserves mode scope for catalog dependency systems.
        expected["modes"][0]["systems"] = expected["global_systems"] + expected["modes"][0]["systems"]
        expected["global_systems"] = []
        result["metadata"]["cgs_hash"] = compute_cgs_hash(result)
        expected["metadata"]["cgs_hash"] = compute_cgs_hash(expected)
        self.assertEqual(result, expected)
        compiled = importlib.import_module("schema-factory.src.portable_compilation").compile_portable_cgs(result)
        self.assertEqual({s["id"] for s in compiled.to_sgc_input()}, {"reference.traversal.v1", "reference.recorded_input.v1"})

    def test_discovery_reports_requirements_without_changes(self):
        before = copy.deepcopy(self.cgs)
        result = discover_packages("Add wall running", self.catalog.descriptors(), self.cgs, "reference")
        self.assertEqual(result["missing_capabilities"], ["reference.wall_runnable.v1"])
        self.assertEqual(result["templates"], ["reference.test_arena.v1"])
        self.assertEqual(self.cgs, before)

    def test_arbitrary_capability_uses_identical_path(self):
        raw = json.dumps(self.package).replace("reference.wall_runnable.v1", "project.custom_surface.v8")
        package = json.loads(raw)
        catalog = GameplayCatalog([package], supported_systems=package["systems"] + package["templates"][0]["systems"])
        batch = package_proposal(package=catalog.descriptors()[0], cgs=self.cgs, mode_id="reference",
            configuration_id="default", template_id="reference.test_arena.v1")["transaction"]["typed_operation_batch"]
        result = TypedOperationExecutor(catalog).execute(batch, self.cgs).proposed_cgs
        self.assertIn("project.custom_surface.v8", json.dumps(result))
        self.assertNotIn("reference.wall_runnable.v1", json.dumps(result))
        result["metadata"]["cgs_hash"] = compute_cgs_hash(result)
        importlib.import_module("schema-factory.src.portable_compilation").compile_portable_cgs(result)

    def test_invalid_selections_and_stale_catalog_are_atomic(self):
        batch = self.batch(template_id="reference.test_arena.v1")
        before = copy.deepcopy(self.cgs)
        for changes in ({"package_hash": "0" * 64}, {"configuration_id": "missing"},
                        {"template_id": "missing"}, {"actor_ids": ["player"]}):
            changed = copy.deepcopy(batch)
            changed["operations"][0].update(changes)
            with self.assertRaises(TypedOperationExecutionError):
                TypedOperationExecutor(self.catalog).execute(changed, self.cgs)
            self.assertEqual(before, self.cgs)

    def test_unsupported_runtime_contract_rejected(self):
        catalog = GameplayCatalog([self.package])
        with self.assertRaisesRegex(TypedOperationExecutionError, "unsupported runtime"):
            TypedOperationExecutor(catalog).execute(self.batch(template_id="reference.test_arena.v1"), self.cgs)

    def test_mark_selected_surface_and_missing_dependency(self):
        self.cgs = fixture()
        self.cgs["component_schemas"] = []
        mode = self.cgs["modes"][0]
        mode["systems"] = []
        for actor in mode["actors"]:
            actor["components"] = [c for c in actor["components"] if c["type_id"] < 10000]
        for obj in mode["world"]["contract"]["objects"]:
            obj["capabilities"] = []
        batch = self.batch(actor_ids=["player", "target"], capability_targets=[{"capability_id": "reference.wall_runnable.v1", "object_ids": ["wall"]}])
        result = TypedOperationExecutor(self.catalog).execute(batch, self.cgs).proposed_cgs
        self.assertEqual(result["modes"][0]["world"]["contract"]["objects"][1]["capabilities"], ["reference.wall_runnable.v1"])
        self.cgs["global_systems"] = []
        before = copy.deepcopy(self.cgs)
        with self.assertRaisesRegex(TypedOperationExecutionError, "missing system dependency"):
            TypedOperationExecutor(self.catalog).execute(batch, self.cgs)
        self.assertEqual(self.cgs, before)

    def test_real_router_approval_persistence_both_configurations(self):
        from tools.xp006_authoring_proof import run
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(run(Path(tmp)))
        self.assertTrue(result["ok"])
        self.assertEqual(set(result["variants"]), {"disabled", "reversal_shockwave"})

    def test_late_batch_failure_does_not_leak_package_changes(self):
        batch = self.batch(template_id="reference.test_arena.v1")
        batch["operations"].append({"operation_id": "invalid", "kind": "set_defaults", "explanation": "Invalid follow-up",
            "mode_id": "reference", "actor_id": "missing", "component_type_id": 10001, "assignments": []})
        before = copy.deepcopy(self.cgs)
        with self.assertRaises(TypedOperationExecutionError):
            TypedOperationExecutor(self.catalog).execute(batch, self.cgs)
        self.assertEqual(self.cgs, before)

    def test_catalog_is_detached_and_invalid_declarations_rejected(self):
        self.package["component_schemas"][0]["defaults"]["chain"] = 99
        descriptor = self.catalog.descriptors()[0]
        self.assertEqual(descriptor["component_schemas"][0]["defaults"]["chain"], 0)
        descriptor["systems"].clear()
        self.assertTrue(self.catalog.descriptors()[0]["systems"])
        for capability in ("bare", "world.aabb.v1", "project.surface.v0"):
            package = catalog_data()
            package["capability_declarations"][0]["id"] = capability
            with self.assertRaises(CatalogError):
                GameplayCatalog([package])

    def test_builder_preview_cancel_stale_and_gde_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.environ.get("XACE_PROVIDER_SETTINGS_PATH")
            os.environ["XACE_PROVIDER_SETTINGS_PATH"] = str(Path(tmp) / "settings.json")
            try:
                manager = SessionManager(sgc_bin_path=str(ROOT / "target/debug/xace-system-graph-compiler.exe"), gameplay_catalog=self.catalog)
                gde = _GDEOrchestrator(gameplay_catalog=self.catalog)
                manager._sessions["test"] = BuilderSession(session_id="test", pipeline=None, gde=gde)
                args = dict(package_id=self.package["id"], package_hash=self.descriptor["package_hash"],
                    mode_id="reference", configuration_id="default", template_id="reference.test_arena.v1")
                result = manager.stage_gameplay_package("test", self.cgs, **args)
                self.assertEqual(result["kind"], "mutation", result)
                self.assertTrue(result["approval_required"])
                self.assertEqual(self.cgs, empty_cgs())
                manager.clear_pending("test")
                self.assertIsNone(manager._sessions["test"].pending_txn)
                result = manager.stage_gameplay_package("test", self.cgs, **args)
                stale = copy.deepcopy(self.cgs)
                stale["metadata"]["version"] = "0.2.0"
                stale["metadata"]["cgs_hash"] = compute_cgs_hash(stale)
                self.assertFalse(manager.apply_via_gde("test", result["transaction"], stale).success)
                applied = manager.apply_via_gde("test", result["transaction"], self.cgs)
                self.assertTrue(applied.success, applied.error)
                self.assertTrue(manager.compile_sgc_plan(applied.new_cgs).ok)
                manager._executor.shutdown()
            finally:
                if previous is None:
                    os.environ.pop("XACE_PROVIDER_SETTINGS_PATH", None)
                else:
                    os.environ["XACE_PROVIDER_SETTINGS_PATH"] = previous


if __name__ == "__main__":
    unittest.main()
