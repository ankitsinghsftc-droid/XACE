import copy
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "packages"))
sys.path.insert(0, str(ROOT / "packages/builder-workspace/server"))
from tools.xp003_world_proof import arena, FIXTURES, compute_cgs_hash, factory
from session_manager import SessionManager, _GDEOrchestrator
from cgs_persistence import CGSPersistence

def rehash(cgs):
    cgs["metadata"]["cgs_hash"] = compute_cgs_hash(cgs)

class WorldContractTests(unittest.TestCase):
    def test_generic_capabilities_are_package_data(self):
        cgs = arena(); contract = cgs["modes"][0]["world"]["contract"]
        contract["capability_declarations"] = [{"id": "custom.anything.v42", "allowed_kinds": ["anchor", "kinematic_box", "spawn", "static_box", "trigger"]}]
        for obj in contract["objects"]: obj["capabilities"] = ["custom.anything.v42"]
        rehash(cgs)
        result = factory.compile_portable_cgs(cgs).world_contract.content()
        self.assertEqual(result["required_capabilities"], ["world.aabb.v1", "world.semantic_bindings.v1"])
        self.assertTrue(all(o["capabilities"] == ["custom.anything.v42"] for o in result["objects"]))
        for malformed in [[], [{"id": "custom.anything.v42", "allowed_kinds": ["anchor"]}],
                          [{"id": "input.timed.v1", "allowed_kinds": ["anchor"]}]]:
            contract["capability_declarations"] = malformed; rehash(cgs)
            with self.assertRaises(factory.SchemaFactoryError): factory.compile_portable_cgs(cgs)

    def test_golden_exact_bytes_and_package_source_binding(self):
        cgs = arena(); before = copy.deepcopy(cgs)
        package = factory.compile_portable_cgs(cgs)
        self.assertEqual(package.world_contract.content_bytes, (FIXTURES / "world.canonical.json").read_bytes())
        self.assertEqual(package.world_contract.manifest_bytes, (FIXTURES / "manifest.json").read_bytes())
        self.assertEqual(package.cgs_hash, package.world_contract.manifest()["schema_package"]["cgs_hash"])
        self.assertEqual(cgs, before)

    def test_reorder_source_preserves_content_but_rebinds_provenance(self):
        cgs = arena(); first = factory.compile_portable_cgs(cgs).world_contract
        cgs["modes"][0]["actors"].reverse()
        cgs["modes"][0]["world"]["contract"]["objects"].reverse()
        for obj in cgs["modes"][0]["world"]["contract"]["objects"]: obj["capabilities"].reverse()
        rehash(cgs); second = factory.compile_portable_cgs(cgs).world_contract
        self.assertEqual(first.content_bytes, second.content_bytes)
        self.assertNotEqual(first.manifest_bytes, second.manifest_bytes)

    def test_ids_survive_insertion_and_display_rename(self):
        cgs = arena(); first = factory.compile_portable_cgs(cgs).world_contract.content()
        mode = cgs["modes"][0]
        actor = copy.deepcopy(mode["actors"][0]); actor["id"] = "actor_extra"
        actor["components"][1]["defaults"]["entity_name"] = "Renamed visual"
        mode["actors"].insert(0, actor)
        obj = copy.deepcopy(mode["world"]["contract"]["objects"][0]); obj.update(id="aaa_extra", actor_id="actor_extra")
        mode["world"]["contract"]["objects"].insert(0, obj)
        rehash(cgs); second = factory.compile_portable_cgs(cgs).world_contract.content()
        self.assertEqual(first["objects"], [o for o in second["objects"] if o["id"] != "aaa_extra"])

    def test_immutable_result_returns_detached_views(self):
        world = factory.compile_portable_cgs(arena()).world_contract
        value = world.content(); value["objects"].clear()
        self.assertEqual(len(world.content()["objects"]), 6)

    def test_native_asset_resolution_does_not_change_world_content(self):
        cgs = arena(); first = factory.compile_portable_cgs(cgs).world_contract
        cgs["assets"][0].update(status="LINKED", source="visuals/wall.mesh")
        cgs["modes"][0]["world"]["contract"]["objects"][1]["asset_reference"]["status"] = "LINKED"
        rehash(cgs)
        self.assertEqual(first.content_bytes, factory.compile_portable_cgs(cgs).world_contract.content_bytes)

    def test_malformed_world_source_never_reaches_sgc(self):
        def obj(c): return c["modes"][0]["world"]["contract"]["objects"]
        def transform(c): return c["modes"][0]["actors"][0]["components"][0]["defaults"]
        def collider(c): return c["modes"][0]["actors"][0]["components"][2]["defaults"]
        cases = [
            lambda c: obj(c)[1].update(id="floor"),
            lambda c: obj(c)[1].update(actor_id="actor_floor"),
            lambda c: obj(c)[0].update(id="res://floor"),
            lambda c: obj(c)[0].update(target_id="missing"),
            lambda c: obj(c)[0].update(capabilities=["world.unknown.v1"]),
            lambda c: collider(c)["size"].update(x=-2),
            lambda c: collider(c)["size"].update(x=3),
            lambda c: collider(c).update(shape="SPHERE"),
            lambda c: transform(c)["rotation"].update(y=1000000),
            lambda c: transform(c)["scale"].update(x=2000000),
            lambda c: transform(c).update(parent_entity_id=1),
            lambda c: transform(c)["position"].update(x=8192000000),
            lambda c: transform(c)["position"].update(x=0.5),
            lambda c: obj(c)[1]["asset_reference"].update(status="UNRESOLVED"),
            lambda c: obj(c)[1]["asset_reference"].update(id="unregistered_mesh"),
            lambda c: obj(c).pop(0),
            lambda c: c["modes"][0]["actors"][0].update(spawn_count=2),
            lambda c: c["modes"][0]["world"]["contract"].update(contract_version=1),
        ]
        manager = object.__new__(SessionManager); manager._sgc_bin = "must-not-execute"; manager._sgc_args = []
        for index, mutate in enumerate(cases):
            with self.subTest(case=index):
                cgs = arena(); mutate(cgs); rehash(cgs); before = copy.deepcopy(cgs)
                with patch("subprocess.run") as run: result = manager.compile_sgc_plan(cgs)
                run.assert_not_called(); self.assertTrue(result.failed)
                self.assertEqual(result.error["code"], "SCHEMA_FACTORY_VALIDATION_FAILED")
                self.assertEqual(cgs, before)

    def test_stale_hash_rejected_by_strict_validator(self):
        cgs = arena(); cgs["modes"][0]["world"]["day_length_ticks"] += 1
        with self.assertRaises(factory.SchemaFactoryError): factory.compile_portable_cgs(cgs)

    def test_real_gde_rejection_restores_state_and_persisted_artifacts(self):
        cgs = arena()
        with tempfile.TemporaryDirectory() as tmp:
            persistence = CGSPersistence(Path(tmp)); persistence.save(cgs)
            compiled = factory.compile_portable_cgs(cgs).world_contract
            (Path(tmp) / "world.json").write_bytes(compiled.content_bytes)
            (Path(tmp) / "world.manifest.json").write_bytes(compiled.manifest_bytes)
            before = {str(p): p.read_bytes() for p in Path(tmp).rglob("*") if p.is_file()}
            manager = object.__new__(SessionManager)
            gde = _GDEOrchestrator(mode="COLLABORATIVE", session_id="xp003")
            manager._sessions = {"xp003": SimpleNamespace(gde=gde)}
            result = manager.apply_via_gde("xp003", {"parent_cgs_hash": cgs["metadata"]["cgs_hash"],
                "operations": [{"op": "SET", "path": "modes.mode_arena.actors.actor_floor.components.4.defaults.size.x", "value": -2, "type_hint": "int"}],
                "mutation_summary": "invalid world box"}, cgs)
            self.assertFalse(result.success); self.assertIn("Schema Factory", result.error)
            self.assertEqual(gde.current_cgs, cgs)
            self.assertEqual(before, {str(p): p.read_bytes() for p in Path(tmp).rglob("*") if p.is_file()})

    def test_no_world_contract_preserves_legacy_package_shape(self):
        cgs = arena(); del cgs["modes"][0]["world"]["contract"]; rehash(cgs)
        self.assertIsNone(factory.compile_portable_cgs(cgs).world_contract)

    def test_bounds_and_resource_limits(self):
        cgs = arena()
        cgs["modes"][0]["actors"][0]["components"][0]["defaults"]["position"]["x"] = 8191000000
        rehash(cgs)
        self.assertIsNotNone(factory.compile_portable_cgs(cgs).world_contract)
        cgs["modes"][0]["world"]["contract"]["objects"] *= 683
        rehash(cgs)
        with self.assertRaises(factory.SchemaFactoryError): factory.compile_portable_cgs(cgs)

    def test_render_unresolved_reference_also_blocks_commit(self):
        cgs = arena()
        cgs["modes"][0]["actors"][0]["components"].append({"type_id": 3, "name": "COMP_RENDER_V1", "defaults": {
            "asset_reference": {"id": "unregistered", "asset_type": "MESH", "status": "UNRESOLVED"}}})
        rehash(cgs)
        with self.assertRaises(factory.SchemaFactoryError): factory.compile_portable_cgs(cgs)

    def test_package_version_override_cannot_forge_world_provenance(self):
        cgs = arena(); package = factory.compile_portable_cgs(cgs)
        compiler = factory.SchemaFactory(package.component_registry)
        with self.assertRaises(factory.SchemaFactoryError): compiler.compile(cgs, schema_version="9.0.0")
        changed = copy.deepcopy(cgs)
        changed["modes"][0]["world"]["day_length_ticks"] += 1
        with self.assertRaises(factory.SchemaFactoryError): compiler.compile(changed, source_cgs=cgs)

    def test_capabilities_cannot_assign_solid_semantics_to_points(self):
        cgs = arena()
        cgs["modes"][0]["world"]["contract"]["objects"][4]["capabilities"].append("world.solid.v1")
        rehash(cgs)
        with self.assertRaises(factory.SchemaFactoryError): factory.compile_portable_cgs(cgs)
