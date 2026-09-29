import copy
import json
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
sys.path[:0]=[str(ROOT),str(ROOT/"packages"),str(ROOT/"packages/builder-workspace/server")]
from tools.world_extensibility_proof import semantic_fixture, rehash, factory
from session_manager import SessionManager
from src.domain_dsl.typed_operations.gameplay_catalog import GameplayCatalog, CatalogError
from src.domain_dsl.typed_operations.typed_operation_executor import TypedOperationExecutor
from typed_operations.package_authoring import package_proposal

class WorldExtensibilityTests(unittest.TestCase):
    def test_semantic_nouns_roundtrip_without_core_enums(self):
        cgs=semantic_fixture();before=copy.deepcopy(cgs)
        compiled=factory.compile_portable_cgs(cgs).world_contract
        self.assertEqual(cgs,before)
        self.assertEqual(len(compiled.content()["objects"]),12)
        self.assertEqual(compiled.content_bytes,(ROOT/"packages/core/tests/fixtures/world_contract_v3/world.canonical.json").read_bytes())
        self.assertEqual(len(next(o for o in compiled.content()["objects"] if o["id"]=="spaceship")["asset_bindings"]),2)
        cgs["modes"][0]["actors"].reverse()
        cgs["modes"][0]["world"]["contract"]["objects"].reverse()
        rehash(cgs)
        self.assertEqual(compiled.content_bytes,factory.compile_portable_cgs(cgs).world_contract.content_bytes)

    def test_malformed_extensions_reject_before_package(self):
        mutations=[lambda c:c["objects"][0]["properties"].update(strength=True),
            lambda c:c["objects"][0]["properties"].update(unknown=1),
            lambda c:c["objects"][0].update(semantic_type="project.missing.v1"),
            lambda c:c["objects"][0].update(instance_index=2),
            lambda c:c["objects"][0]["relationships"].update({"project.link.v1":["missing"]}),
            lambda c:c["objects"][0]["asset_bindings"]["project.hull_effect.v1"].update(status="UNRESOLVED"),
            lambda c:c["geometry_profiles"].append({"id":"project.unsupported.v1","required":True}),
            lambda c:c["schemas"][0]["definition"].update(type="native_code")]
        for mutate in mutations:
            cgs=semantic_fixture();mutate(cgs["modes"][0]["world"]["contract"]);rehash(cgs)
            with self.subTest(mutation=mutate),self.assertRaises(factory.SchemaFactoryError):factory.compile_portable_cgs(cgs)

    def package(self):
        return {"schema":"xace.gameplay_authoring_package.v2","id":"project.global.v1","version":"1.0.0","aliases":["Install observation"],
            "component_schemas":[],"systems":[],"capability_declarations":[],"requirements":{"component_type_ids":[],"system_ids":[],"capability_ids":[]},
            "templates":[],"configurations":[{"id":"default","defaults":{}}],"target_roles":[]}

    def apply(self,p,cgs,**kw):
        cat=GameplayCatalog([p],supported_systems=p["systems"])
        batch=package_proposal(package=cat.descriptors()[0],cgs=cgs,mode_id="reference",configuration_id="default",**kw)["transaction"]["typed_operation_batch"]
        out=TypedOperationExecutor(cat).execute(batch,cgs).proposed_cgs
        rehash(out);factory.compile_portable_cgs(out)
        return out

    def test_global_package_needs_no_actor_or_world(self):
        cgs=semantic_fixture();cgs["modes"][0]["world"].pop("contract");cgs["modes"][0]["actors"]=[];rehash(cgs)
        out=self.apply(self.package(),cgs)
        self.assertNotIn("contract",out["modes"][0]["world"])

    def test_additive_template_and_collision_atomicity(self):
        cgs=semantic_fixture();p=self.package();new=copy.deepcopy(cgs["modes"][0]["world"]["contract"]["objects"][0]);new["id"]="extra_socket"
        p["templates"]=[{"id":"project.extra.v1","policy":"additive","actors":[],"systems":[],"actor_ids":[],"world":{"contract":{"objects":[new]}}}]
        out=self.apply(p,cgs,template_id="project.extra.v1")
        self.assertEqual(len(out["modes"][0]["world"]["contract"]["objects"]),13)
        before=copy.deepcopy(out)
        with self.assertRaises(Exception):self.apply(p,out,template_id="project.extra.v1")
        self.assertEqual(before,out)

    def test_package_roles_attach_only_their_components(self):
        cgs=semantic_fixture();p=self.package()
        p["component_schemas"]=[{"type_id":10020,"name":"PROJECT_OBSERVATION_V1","source":"gcl","defaults":{"count":0}}]
        p["target_roles"]=[{"id":"project.observer.v1","component_type_ids":[10020],"requires_component_type_ids":[1],"actor_types":["project.spaceship.v1"],"min_count":1}]
        out=self.apply(p,cgs,actor_ids=["spaceship"])
        self.assertIn(10020,{c["type_id"] for c in next(a for a in out["modes"][0]["actors"] if a["id"]=="spaceship")["components"]})
        self.assertNotIn(10020,{c["type_id"] for c in next(a for a in out["modes"][0]["actors"] if a["id"]=="meteor")["components"]})

    def test_explicit_migration_preserves_reference_geometry(self):
        import importlib
        from tools.xp005_reference_proof import fixture
        cgs=fixture();old=copy.deepcopy(cgs["modes"][0]["world"]["contract"])
        migrate=importlib.import_module("schema-factory.src.world_contract_v3").migrate_v2_source
        cgs["modes"][0]["world"]["contract"]=migrate(old);rehash(cgs)
        compiled=factory.compile_portable_cgs(cgs).world_contract.content()
        self.assertTrue(all(o["geometry"]["profile"]=="world.aabb.v1" for o in compiled["objects"]))
        self.assertEqual(old["contract_version"],2)
        # A schema-backed semantic attachment need not adopt its actor's collider shape.
        cgs["modes"][0]["actors"][0]["components"][1]["defaults"]["layer_mask"]=2
        rehash(cgs)
        self.assertEqual(factory.compile_portable_cgs(cgs).world_contract.content()["objects"][0]["geometry"]["layer_mask"],2)

    def test_v3_package_binds_arbitrary_semantic_capability(self):
        cgs=semantic_fixture();p=self.package()
        p["capability_declarations"]=[{"id":"project.dockable.v4","allowed_types":["project.spaceship.v1"]}]
        p["requirements"]["capability_ids"]=["project.dockable.v4"]
        out=self.apply(p,cgs,capability_targets=[{"capability_id":"project.dockable.v4","object_ids":["spaceship"]}])
        obj=next(o for o in out["modes"][0]["world"]["contract"]["objects"] if o["id"]=="spaceship")
        self.assertIn("project.dockable.v4",obj["capabilities"])
        with self.assertRaises(Exception):self.apply(p,cgs,capability_targets=[{"capability_id":"project.dockable.v4","object_ids":["meteor"]}])

    def test_builder_global_flow_skips_actor_question_and_stages_for_approval(self):
        import asyncio
        import os
        import tempfile
        from unittest.mock import patch
        from session_manager import BuilderSession, _GDEOrchestrator
        cgs=semantic_fixture();cgs["modes"][0]["world"].pop("contract");cgs["modes"][0]["actors"]=[];rehash(cgs)
        package=self.package()
        package["systems"]=[{"id":"project.observation.v1","phase":"Simulation","reads":[],"writes":[],"depends_on":[],"deterministic":True}]
        cat=GameplayCatalog([package],supported_systems=package["systems"])
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{"XACE_PROVIDER_SETTINGS_PATH":str(Path(tmp)/"settings.json")}):
            manager=SessionManager(sgc_bin_path=str(ROOT/"target/debug/xace-system-graph-compiler.exe"),gameplay_catalog=cat)
            manager._sessions["test"]=BuilderSession(session_id="test",pipeline=None,gde=_GDEOrchestrator(gameplay_catalog=cat))
            try:
                first=asyncio.run(manager.run_pil("test","Install observation",cgs,cgs["metadata"]["cgs_hash"]))
                answer=manager.answer_gameplay_package("test",first["clarification_session_id"],"Use package",cgs)
                self.assertEqual(answer["questions"][0]["parameter_key"],"configuration")
                staged=manager.answer_gameplay_package("test",answer["clarification_session_id"],"default",cgs)
                self.assertEqual(staged["kind"],"mutation",staged)
                self.assertTrue(staged["approval_required"])
            finally:manager._executor.shutdown()

if __name__=="__main__":unittest.main()
