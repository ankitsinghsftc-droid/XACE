import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from authoring_identity import canonical
from native_authoring_contract import inspect_capture
from godot_authoring import (ENGINE_VERSION, READER_VERSION, WRITER_VERSION, capture, inventory,
                             policy, prepare_identity_map, write_request)


def oid(n): return f"{n:032x}"


def fixture():
    rows={}
    for n,kind in [(1,"scene"),(2,"object"),(3,"object")]:
        rows[oid(n)]=dict(metadata=dict(schema="xace.native_identity.v1",namespace_id=oid(100),
            authoring_id=oid(n),kind=kind,generation="1"),locator=dict(engine="godot",document_id="scene-guid",
            object_id=f"local_id_fixture_{n}"),scene_id=None if n==1 else oid(1),prefab_id=None,
            parent_id=None,fields={} if n==1 else {"native.name":"Ordinary Name","transform.position":dict(x="1",y="2",z="3")},
            dependencies=[],opaque=[],name="Ordinary Name",path_hint="res://World.tscn")
    return dict(schema="xace.godot_authoring_inventory.v1",namespace_id=oid(100),objects=rows,
        source=dict(engine="godot",engine_version=ENGINE_VERSION,reader_version=READER_VERSION,
            materializer_version=WRITER_VERSION,play_mode=False,documents=[dict(id="scene-guid",before="a"*64,after="a"*64,dirty=False)]))


class GodotBridgeTests(unittest.TestCase):
    def test_binary_resource_replacement_is_typed_and_preserves_identity(self):
        value = fixture()
        ref = dict(asset_id="godot_meshuid", asset_type="MESH", status="LINKED",
                   resolved_path="res://Mesh.res")
        value["objects"][oid(2)]["fields"]["presentation.asset"] = ref
        data = canonical(value)
        mapping = prepare_identity_map(data, project_id="fixture", branch_id=oid(200))
        before = canonical(mapping.to_dict())
        base = capture(data, mapping, enable_writes=True).admit()
        changed = base.to_dict()["inspection"]["capture"]
        replacement = dict(ref, asset_id="godot_replacement", resolved_path="res://Replacement.res")
        changed["objects"][oid(2)]["fields"]["presentation.asset"] = replacement
        target = inspect_capture(changed, mapping, policy(enable_writes=True)).admit()
        request = json.loads(write_request(data, base, target, mapping))
        self.assertEqual(request["edits"][0]["fields"], {"presentation.asset": replacement})
        self.assertEqual(canonical(mapping.to_dict()), before)

    def test_native_collision_behavior_is_not_invented_as_supported_geometry(self):
        value = fixture()
        value["objects"][oid(2)]["fields"]["collision.shape"] = "BOX"
        data = canonical(value)
        mapping = prepare_identity_map(data, project_id="fixture", branch_id=oid(200))
        inspected = capture(data, mapping)
        self.assertTrue(any(loss["code"] == "field_not_readable" for loss in inspected.losses))
        with self.assertRaises(ValueError): inspected.admit()

    def test_explicit_identity_candidate_and_snapshot_no_mutation(self):
        data=canonical(fixture()); mapping=prepare_identity_map(data,project_id="fixture",branch_id=oid(200))
        before=canonical(mapping.to_dict()); snapshot=capture(data,mapping).admit()
        self.assertEqual(snapshot.to_dict()["inspection"]["normalized"][oid(2)]["fields"]["transform.position"],dict(x="1000000",y="2000000",z="3000000"))
        self.assertEqual(canonical(mapping.to_dict()),before)
        self.assertNotEqual(mapping.objects[oid(2)].locator,mapping.objects[oid(3)].locator)

    def test_rename_reparent_are_proposals_not_map_overwrites(self):
        original=fixture(); mapping=prepare_identity_map(canonical(original),project_id="fixture",branch_id=oid(200))
        original["objects"][oid(3)]["name"]="new name";original["objects"][oid(3)]["fields"]["native.name"]="new name"
        original["objects"][oid(3)]["parent_id"]=oid(2)
        observed=capture(canonical(original),mapping).admit()
        self.assertEqual(observed.to_dict()["inspection"]["normalized"][oid(3)]["parent_id"],oid(2))
        self.assertIsNone(mapping.objects[oid(3)].parent_id)

    def test_collisions_foreign_metadata_stale_generation_and_missing_locator(self):
        original=fixture(); mapping=prepare_identity_map(canonical(original),project_id="fixture",branch_id=oid(200))
        for kind in ("namespace","generation","locator","kind","key"):
            value=copy.deepcopy(original); row=value["objects"][oid(2)]
            if kind=="namespace": row["metadata"]["namespace_id"]=oid(999)
            elif kind=="generation": row["metadata"]["generation"]="2"
            elif kind=="locator": row["locator"]=value["objects"][oid(3)]["locator"]
            elif kind=="kind": row["metadata"]["kind"]="prefab_definition"
            else: row["metadata"]["authoring_id"]=oid(3)
            with self.subTest(kind=kind),self.assertRaises(ValueError): capture(canonical(value),mapping)

    def test_unknown_behavior_is_reported_and_blocks_admission(self):
        value=fixture();value["objects"][oid(2)]["opaque"]=[dict(id="custom.behavior",sha256="b"*64,critical=True,reason="Native behavior retained")]
        data=canonical(value);mapping=prepare_identity_map(data,project_id="fixture",branch_id=oid(200))
        inspection=capture(data,mapping)
        self.assertEqual(inspection.losses[0]["code"],"retained_native")
        with self.assertRaises(ValueError):inspection.admit()

    def test_dirty_play_and_unknown_versions_fail_closed(self):
        value=fixture();mapping=prepare_identity_map(canonical(value),project_id="fixture",branch_id=oid(200))
        for field in ("dirty","play_mode","engine_version","reader_version","materializer_version"):
            changed=copy.deepcopy(value)
            if field=="dirty":changed["source"]["documents"][0]["dirty"]=True
            else:changed["source"][field]=True if field=="play_mode" else "unknown"
            with self.subTest(field=field),self.assertRaises(ValueError):capture(canonical(changed),mapping).admit()

    def test_write_request_is_bound_to_native_inventory_and_certified_policy(self):
        data=canonical(fixture());mapping=prepare_identity_map(data,project_id="fixture",branch_id=oid(200))
        base=capture(data,mapping,enable_writes=True).admit()
        changed=base.to_dict()["inspection"]["capture"]
        changed["objects"][oid(2)]["fields"]["transform.position"]["x"]="8"
        target=inspect_capture(changed,mapping,policy(enable_writes=True)).admit()
        request=json.loads(write_request(data,base,target,mapping))
        self.assertEqual(request["edits"],[dict(document="res://World.tscn",authoring_id=oid(2),fields={"transform.position":dict(x="8000000",y="2000000",z="3000000")})])
        changedInventory=fixture();changedInventory["source"]["documents"][0].update(before="b"*64,after="b"*64)
        with self.assertRaises(ValueError):write_request(canonical(changedInventory),base,target,mapping)

    def test_write_refuses_native_owned_structural_and_component_changes(self):
        data=canonical(fixture());mapping=prepare_identity_map(data,project_id="fixture",branch_id=oid(200))
        base=capture(data,mapping,enable_writes=True).admit()
        for kind in ("name","parent","component"):
            changed=base.to_dict()["inspection"]["capture"];row=changed["objects"][oid(2)]
            if kind=="name":row["fields"]["native.name"]="overwritten"
            elif kind=="parent":row["parent_id"]=oid(3)
            else:row["fields"]["input.action"]="Jump"
            target=inspect_capture(changed,mapping,policy(enable_writes=True)).admit()
            with self.subTest(kind=kind),self.assertRaises(ValueError):write_request(data,base,target,mapping)

    def test_read_policy_cannot_authorize_write_request(self):
        data=canonical(fixture());mapping=prepare_identity_map(data,project_id="fixture",branch_id=oid(200))
        base=capture(data,mapping).admit()
        with self.assertRaises(ValueError):write_request(data,base,base,mapping)

    def test_malformed_paths_numbers_and_unknown_envelope_fields(self):
        for path in ("../World.tscn","res://../World.tscn","C:/World.tscn","Assets\\World.tscn"):
            value=fixture();value["objects"][oid(2)]["path_hint"]=path
            with self.assertRaises(ValueError):inventory(canonical(value))
        value=fixture();value["objects"][oid(2)]["metadata"]["generation"]=1
        with self.assertRaises(ValueError):inventory(canonical(value))
        value=fixture();value["trusted"]=True
        with self.assertRaises(ValueError):inventory(canonical(value))


if __name__=="__main__":unittest.main()
