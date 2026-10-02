"""XP-009 exported presentation proof. All gameplay remains in the reference package."""
from pathlib import Path
import json,sys,importlib,io,wave,struct,math
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/"packages"),str(ROOT/"packages/project-system")]
from tools.xp007_package_proof import compile_plan
from tools.world_extensibility_proof import rehash
from tools.xp008_player_build import prepare_player,export_player
from playable_package import RuntimeSupport,build_package,install_archive,digest
from tools.xp008_player_proof import PROOF_SCRIPT,process_alive

def resources(manifest,world,variant=0):
    files={};assets=[];objects=[];events=[]
    def add(id,kind,fmt,value,fallback="marker"):
        path="presentation/resources/"+id+(".wav" if isinstance(value,bytes) else ".json")
        files[path]=value if isinstance(value,bytes) else json.dumps(value).encode()
        assets.append({"asset":{"id":id,"asset_type":kind,"status":"Linked"},"format":fmt,"path":path,"required":False,"fallback":fallback})
        return {"id":id,"asset_type":kind}
    for obj in world["objects"]:
        geometry=obj.get("geometry")
        if not geometry:continue
        size=[geometry["size"][axis]/2000000 for axis in "xyz"]
        vertices=[[size[axis]*(1 if i&(1<<axis) else -1) for axis in range(3)] for i in range(8)]
        indices=[0,2,1,1,2,3,4,5,6,5,7,6,0,1,4,1,5,4,2,6,3,3,6,7,0,4,2,2,4,6,1,3,5,3,7,5]
        ref=add(obj["id"]+"_skin","Mesh","xace.mesh.v1",{"schema":"xace.mesh.v1","vertices":vertices,"indices":indices,"color":[0.2+0.5*variant,0.6,0.8-0.5*variant,1]},"canonical")
        objects.append({"object_id":obj["id"],"asset":ref})
    ring=add("pulse","Particle","xace.effect.ring.v1",{"schema":"xace.effect.ring.v1","radius":4,"duration_ticks":60,"color":[1,0.5,0.1,0.8]})
    camera=add("camera","project.camera_effect.v1","xace.camera.impulse.v1",{"schema":"xace.camera.impulse.v1","offset":[0.4,0.2,0],"duration_ticks":20},"silent")
    buffer=io.BytesIO()
    with wave.open(buffer,"wb") as wav:
        wav.setparams((1,2,16000,0,"NONE","not compressed"));wav.writeframes(b"".join(struct.pack("<h",int(5000*math.sin(i*0.17))) for i in range(4000)))
    sound=add("sound","AudioClip","audio.pcm_wav.v1",buffer.getvalue(),"silent")
    for ref in [ring,camera,sound]:events.append({"binding_id":ref["id"],"event_name":"reference.shockwave.v1","entity_selector":"source","asset":ref})
    catalog={"schema":"xace.player.presentation.v1","world_hash":manifest["gameplay"]["world"]["artifact"]["content_hash"],"assets":assets,"objects":objects,"events":events,"camera_offset":[12,10,14],"collision_overlay":True}
    files["presentation/player/presentation.json"]=json.dumps(catalog).encode()
    return files

def stage(out, variant=0):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
    cgs=json.loads((ROOT/"examples/reference-mechanic/fixtures/game.cgs.json").read_text())
    cgs["global_systems"]=[{"id":"EngineInputSystem","phase":"Input","reads":[],"writes":[6],"depends_on":[],"deterministic":True}]
    cgs["modes"][0]["systems"][0]["depends_on"]=["EngineInputSystem"]
    cgs["modes"][0]["world"]["contract"]=importlib.import_module("schema-factory.src.world_contract_v3").migrate_v2_source(cgs["modes"][0]["world"]["contract"])
    def enable(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key=="third_attempt":value[key]="reversal_shockwave"
                else:enable(item)
        elif isinstance(value,list):
            for item in value:enable(item)
    enable(cgs)
    rehash(cgs)
    plan,compiled=compile_plan(cgs)
    runtime=(ROOT/"target/debug/xace_reference_host.exe").read_bytes()
    support=RuntimeSupport(digest(runtime),"xace.runtime_executor.v1",tuple(compiled.to_sgc_input()))
    settings={"schema":"xace.player.controls.v1","controller_id":1,"instructions":"Move: W A S D    Jump: Space","bindings":[{"action":"move_x","positive":68,"negative":65,"kind":"axis_1d"},{"action":"move_z","positive":87,"negative":83,"kind":"axis_1d"},{"action":"Jump","positive":32,"kind":"button"}]}
    base=build_package(cgs,plan,runtime,support,package_id="reference.presentation",version="1.0.0")
    import zipfile,io
    with zipfile.ZipFile(io.BytesIO(base)) as z:
        manifest=json.loads(z.read("playable.manifest.json"));world=json.loads(z.read("world.json"))
    visuals=resources(manifest,world,variant)
    visuals["presentation/player/settings.json"]=json.dumps(settings).encode()
    archive=build_package(cgs,plan,runtime,support,package_id="reference.player",version="1.0.0",presentation_files=visuals)
    (out/"reference.xace").write_bytes(archive)
    installed,manifest=install_archive(archive,out/"installed",support)
    prepare_player(installed,support,out/"player")
    return out/"player"


PRESENTATION_PROOF = PROOF_SCRIPT + r"""
func _on_handshake(ack: Dictionary) -> void:
    if options.get("--scenario","") == "binding_mismatch":
        ack.world_bindings = {}
    super._on_handshake(ack)

func _finish_proof() -> void:
    if options.has("--screenshot"):
        await RenderingServer.frame_post_draw
        get_viewport().get_texture().get_image().save_png(str(options["--screenshot"]))
        options.erase("--screenshot")
    report["before_cleanup"] = presentation.readiness_report()
    var entity := controlled
    var snapshot := {"tick":30,"events":[{"event_type":"project.docking_pulse.v1","entity_id":entity,"data":{"schema":"xace.presentation_event.v1","occurrence_id":"30:0","tick":30,"target_entity_id":str(entity)}}]}
    # Test-only project event binding: same generic admitted ring resource.
    presentation.catalog.events.append({"binding_id":"arbitrary","event_name":"project.docking_pulse.v1","entity_selector":"target","asset":{"id":"pulse","asset_type":"Particle"}})
    presentation.apply_snapshot(snapshot)
    var count: int = presentation.applied_count
    presentation.apply_snapshot(snapshot)
    report["duplicate_suppressed"] = presentation.applied_count == count
    var nodes: Array = []
    for effect in presentation.effects.values():
        if effect.node != null:
            nodes.append(effect.node)
    # A restore baseline carrying an old event must not recreate transient effects.
    var restored := {"tick":30,"entities":[],"events":snapshot.events}
    for id in entities._components:
        var components := {}
        for type_id in entities.component_snapshot(id):
            components[str(type_id)] = JSON.stringify(entities.component_snapshot(id)[type_id].data)
        restored.entities.append({"id":id,"components":components})
    var before: Dictionary = entities.component_snapshot(entity).duplicate(true)
    entities.rollback_side_effects({"restore_tick":30,"restored_snapshot":restored})
    report["restore_state_preserved"] = before == entities.component_snapshot(entity)
    report["restore_clean"] = presentation.effects.is_empty() and presentation.camera_offset() == presentation.offset
    for node in nodes:
        report.restore_clean = report.restore_clean and node.get_parent() == null
    presentation.apply_snapshot(snapshot)
    report["replay_once"] = presentation.applied_count == count+1
    presentation.apply_snapshot({"tick":700,"events":[]})
    report["expired_clean"] = presentation.effects.is_empty()
    super._finish_proof()
"""

def run(out,godot,template):
    import os,subprocess,shutil
    out=Path(out).resolve();results={};hashes=[];identities=[]
    env=dict(os.environ);env["PATH"]=str(Path(env.get("SystemRoot","C:/Windows"))/"System32")
    for variant in [0,1]:
        base=out/str(variant);player=stage(base,variant);dist=base/"exported"
        export_player(player,dist/"xace-player.exe",godot,template)
        (player/"proof_player.gd").write_text(PRESENTATION_PROOF,encoding="utf8")
        scene=player/"player.tscn";original=scene.read_text();scene.write_text(original.replace("res://player.gd","res://proof_player.gd"))
        try:export_player(player,dist/"xace-proof.exe",godot,template)
        finally:scene.write_text(original)
        identities.append(json.loads((player/"admission.json").read_text())["gameplay_hash"])
        scenarios=["normal","missing","binding_mismatch","tamper","geometry_missing"] if variant==0 else ["normal"]
        for scenario in scenarios:
            package=dist/"package";modified=base/(scenario+"-package")
            if scenario in ["missing","tamper","geometry_missing"]:
                shutil.copytree(package,modified,dirs_exist_ok=True);package=modified
                path=package/("world.json" if scenario=="geometry_missing" else "presentation/resources/pulse.json")
                if scenario=="tamper":path.write_bytes(b"{}")
                else:path.unlink()
            report=base/(scenario+".json");schedule=base/(scenario+"-schedule.json")
            command=[str(dist/"xace-proof.exe"),"--headless","--log-file",str(base/(scenario+".log")),"--","--package="+str(package),"--scenario="+scenario,"--proof-ticks=30","--fps=60","--report="+str(report),"--schedule="+str(schedule)]
            if scenario=="normal" and variant==0:
                command.remove("--headless");command.append("--screenshot="+str(out/"player.png"))
            proc=subprocess.run(command,cwd=dist,env=env,capture_output=True,text=True,timeout=40)
            (base/(scenario+"-process.log")).write_text(proc.stdout+proc.stderr,encoding="utf8")
            assert proc.returncode==0,(scenario,proc.stdout,proc.stderr)
            data=json.loads(report.read_text())
            assert not process_alive(data.get("owned_runtime_pid",0))
            if scenario in ["normal","missing"]:
                assert data["errors"]==[],data["errors"]
                assert data["before_cleanup"]["applied_effects"]>=3,data["before_cleanup"]
                for key in ["duplicate_suppressed","restore_clean","replay_once","expired_clean","restore_state_preserved"]:assert data[key],key
                if scenario=="normal":hashes.append(json.loads(schedule.read_text())["hash_log"])
                else:assert any(r["status"]=="fallback" for r in data["presentation"]["records"])
            else:
                assert data["errors"] and not data["inputs"],data
                if scenario in ["tamper","geometry_missing"]:assert "owned_runtime_pid" not in data
            assert "SCRIPT ERROR" not in proc.stdout+proc.stderr,proc.stderr
            results[str(variant)+"-"+scenario]={"errors":data["errors"],"ticks":len(data["ticks"]),"presentation":data.get("before_cleanup",{}),"owned_runtime_stopped":True,"checks":{key:data[key] for key in ["duplicate_suppressed","restore_clean","restore_state_preserved","replay_once","expired_clean"] if key in data}}
    assert hashes[0]==hashes[1] and identities[0]==identities[1]
    result={"schema":"xace.xp009.presentation_proof.v1","ok":True,"cosmetic_variants_same_gameplay_hash":True,"cosmetic_variants_same_30_tick_hashes":True,"scenarios":results,"scope":"Exported Windows Player and native reference host on this machine; automated keyboard input. Local presentation restore tested; remote session restore remains later work."}
    (out/"proof.json").write_text(json.dumps(result,indent=2),encoding="utf8")
    return result

if __name__=="__main__":
    import argparse
    from tools.godot_vertical_slice_certification import find_godot
    parser=argparse.ArgumentParser();parser.add_argument("--out",default=str(ROOT/"tmp/xp009-final"));parser.add_argument("--template",required=True);parser.add_argument("--godot",default="")
    args=parser.parse_args();print(json.dumps(run(args.out,find_godot(args.godot),args.template),indent=2))
