"""Compile the removable reference fixture through real Factory and SGC.
No new gameplay compiler, provider or native engine. --write-fixtures is explicit.
"""
from __future__ import annotations
import argparse, copy, hashlib, importlib, json, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/"packages")]
from tools.cgs_schema_validate import compute_cgs_hash
factory=importlib.import_module("schema-factory.src.portable_compilation")
PACKAGE=ROOT/"examples/reference-mechanic"

def fixture(third_attempt="disabled"):
    catalog=json.loads((PACKAGE/"catalog.json").read_text(encoding="utf-8"))
    catalog["component_schemas"][1]["defaults"]["third_attempt"]=third_attempt
    actors=[];objects=[]
    for name,kind,pos,size in [("floor","static_box",[0,-500000,0],[20000000,1000000,20000000]),
            ("wall","static_box",[-750000,5000000,0],[1000000,10000000,20000000]),
            ("player","kinematic_box",[0,3000000,0],[500000,1000000,500000]),
            ("target","kinematic_box",[2000000,3000000,0],[500000,1000000,500000])]:
        def vec(v):return dict(zip(("x","y","z"),v))
        comps=[{"type_id":1,"name":"COMP_TRANSFORM_V1","defaults":{"position":vec(pos),"rotation":{"x":0,"y":0,"z":0,"w":1000000},"scale":vec([1000000]*3),"parent_entity_id":0}},
            {"type_id":4,"name":"COMP_COLLIDER_V1","defaults":{"shape":"BOX","size":vec(size),"offset":vec([0]*3),"is_trigger":False}}]
        comps.append({"type_id":2,"name":"COMP_IDENTITY_V1","defaults":{"entity_name":name}})
        if name in {"player","target"}:
            comps.extend([{"type_id":5,"name":"COMP_VELOCITY_V1","defaults":{"linear":vec([0]*3),"angular":vec([0]*3),"max_linear_speed":20000000,"max_angular_speed":0}},
                {"type_id":6,"name":"COMP_INPUT_V1","defaults":{"controller_id":1 if name=="player" else 2,"control_type":"HUMAN","input_profile_id":"reference.input.v1"}}])
            comps.extend({"type_id":s["type_id"],"name":s["name"],"defaults":copy.deepcopy(s["defaults"])} for s in catalog["component_schemas"])
        actors.append({"id":name,"actor_type":"PLAYER" if name in {"player","target"} else "WORLD_OBJECT","control_type":"HUMAN" if name in {"player","target"} else "NONE","spawn_count":1,"components":comps})
        objects.append({"id":name,"actor_id":name,"kind":kind,"capabilities":["reference.wall_runnable.v1"] if name=="wall" else []})
    cgs={"metadata":{"name":"ReferenceMechanicProof","version":"0.1.0","schema_version":"0.1.0","cgs_hash":""},
        "component_schemas":catalog["component_schemas"],"global_systems":[{"id":"reference.recorded_input.v1","phase":"Input","reads":[6,10000],"writes":[6],"depends_on":[],"deterministic":True}],
        "assets":[],"modes":[{"id":"reference","is_default":True,"schema_version":"0.1.0","actors":actors,"systems":catalog["systems"],"rules":[],"ui":{},
        "world":{"size":{"width":100000000,"height":100000000,"depth":100000000},"gravity":{"x":0,"y":-9810000,"z":0},"day_length_ticks":0,
        "contract":{"contract_version":2,"id":"reference.arena","version":"1.0.0","numeric_profile":"fixed64_y_up_neg_z_v1","capability_declarations":catalog["capability_declarations"],"objects":objects}}}]}
    cgs["metadata"]["cgs_hash"]=compute_cgs_hash(cgs)
    return cgs

def compile_variant(write=False, third_attempt="disabled"):
    cgs=fixture(third_attempt);package=factory.compile_portable_cgs(cgs)
    systems=package.to_sgc_input()
    # The reference package owns the only actor transform writer.
    assert [s["id"] for s in systems if 1 in s["writes"]]==["reference.traversal.v1"]
    exe=ROOT/"target/debug"/("xace-system-graph-compiler.exe" if sys.platform=="win32" else "xace-system-graph-compiler")
    envelope={"systems":systems,"schema_version":package.schema_version,"cgs_hash":package.cgs_hash,"plan_version":1}
    proc=subprocess.run([str(exe)],input=json.dumps(envelope),capture_output=True,text=True,timeout=30)
    if proc.returncode:raise RuntimeError(proc.stderr)
    plan=json.loads(proc.stdout)
    content={"game.cgs.json":(json.dumps(cgs,indent=2)+"\n").encode(),"execution_plan.json":(json.dumps(plan,indent=2)+"\n").encode(),
             "world.json":package.world_contract.content_bytes,"world.manifest.json":package.world_contract.manifest_bytes}
    out=PACKAGE/"fixtures"
    if third_attempt!="disabled":out=out/third_attempt
    if write:out.mkdir(parents=True,exist_ok=True)
    for name,data in content.items():
        if write:(out/name).write_bytes(data)
        else:assert (out/name).read_bytes()==data,name
    return {"schema":"xace.xp005.reference_compilation.v1","ok":True,"cgs_hash":package.cgs_hash,"plan_hash":plan["plan_hash"],
        "files":{n:hashlib.sha256(b).hexdigest() for n,b in content.items()},"scope":"real Factory/SGC fixture compilation; Rust package replay tested separately"}
def run(write=False):
    return {"schema":"xace.xp005.reference_compilation.v1", "ok":True,
            "variants":{policy:compile_variant(write,policy) for policy in ("disabled","reversal_shockwave")}}

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--write-fixtures",action="store_true")
    print(json.dumps(run(parser.parse_args().write_fixtures),indent=2))
