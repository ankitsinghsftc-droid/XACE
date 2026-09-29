"""Data-only cross-genre contract vectors; no new gameplay implementations."""
import copy
import json
from pathlib import Path
from tools.xp005_reference_proof import fixture, factory, compute_cgs_hash
ROOT = Path(__file__).resolve().parents[1]
NOUNS = ("spaceship", "meteor", "burning_effect", "docking_port", "vacuum_zone", "gravity_field",
         "territory", "resource_node", "formation_slot", "haunted_region", "sound_occluder")

def semantic_fixture():
    cgs = fixture()
    cgs["component_schemas"] = []
    cgs["global_systems"] = []
    mode = cgs["modes"][0]
    prototype = mode["actors"][0]
    mode["actors"] = []; mode["systems"] = []
    schemas = []; objects = []
    for i, noun in enumerate(NOUNS):
        sid = "project." + noun + ".v1"
        schemas.append({"id":sid,"definition":{"type":"object","fields":{"strength":{"type":"integer"}, "labels":{"type":"array","items":{"type":"string"}}}}})
        actor = copy.deepcopy(prototype)
        actor.update(id=noun, actor_type={"Custom":sid}, spawn_count=2)
        actor["components"] = [c for c in actor["components"] if c["type_id"] != 4]
        transform = actor["components"][0]["defaults"]
        transform["rotation"] = {"x":0,"y":1000000,"z":0,"w":0}
        transform["scale"]["x"] = 2000000
        transform["parent_entity_id"] = 42
        mode["actors"].append(actor)
        objects.append({"id":noun,"actor_id":noun,"instance_index":1,"semantic_type":sid,
            "properties":{"strength":i,"labels":[noun]}, "capabilities":["project.observable.v1"],
            "relationships":{},"asset_bindings":{},"geometry_profile":None})
    compound = copy.deepcopy(objects[0]); compound["id"]="ship_socket"; objects.append(compound)
    objects[0]["relationships"]={"project.docks_at.v1":["docking_port"]}
    schemas.append({"id":"project.volumetric_asset.v1","definition":{"type":"object","fields":{}}})
    cgs["assets"]=[{"id":"volume_asset", "asset_type":"project.volumetric_asset.v1", "status":"PLACEHOLDER"}]
    objects[0]["asset_bindings"]={role:{"id":"volume_asset","asset_type":"project.volumetric_asset.v1","status":"PLACEHOLDER"} for role in ("project.hull_effect.v1","project.engine_effect.v1")}
    mode["world"]["contract"]={"contract_version":3,"id":"project.world","version":"1.0.0", "schemas":schemas,
        "capability_declarations":[{"id":"project.observable.v1","allowed_types":[]}],"geometry_profiles":[],"objects":objects}
    rehash(cgs)
    return cgs

def rehash(cgs): cgs["metadata"]["cgs_hash"] = compute_cgs_hash(cgs)

def write_vectors():
    cgs=semantic_fixture(); world=factory.compile_portable_cgs(cgs).world_contract
    out=ROOT/"packages/core/tests/fixtures/world_contract_v3";out.mkdir(parents=True,exist_ok=True)
    (out/"source.cgs.json").write_text(json.dumps(cgs,indent=2),encoding="utf8")
    (out/"world.canonical.json").write_bytes(world.content_bytes)
    (out/"manifest.json").write_bytes(world.manifest_bytes)
    import importlib
    migrate=importlib.import_module("schema-factory.src.world_contract_v3").migrate_v2_source
    legacy=fixture(); legacy["modes"][0]["world"]["contract"]=migrate(legacy["modes"][0]["world"]["contract"])
    rehash(legacy); migrated=factory.compile_portable_cgs(legacy).world_contract
    (out/"migrated_reference.world.json").write_bytes(migrated.content_bytes)
    return {"objects":len(world.content()["objects"]),"semantic_types":len(NOUNS),"hash":world.manifest()["world"]["artifact"]["content_hash"]}

if __name__=="__main__": print(json.dumps(write_vectors(),indent=2))
