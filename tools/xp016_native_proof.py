"""XP-016: shared marker/transcript fixture executed by installed native hosts.

Generated engine projects/logs live under ignored target/. No gameplay mechanics.
"""
from pathlib import Path
import argparse, copy, hashlib, json, shutil, socket, struct, subprocess, sys, time

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "adapters/tests/fixtures/xp016-contract-v1.json"
def encoded(value): return json.dumps(value, sort_keys=True, separators=(",", ":"))
def digest(raw): return hashlib.sha256(raw.encode()).hexdigest()

def fixture():
    def transform(x=0,y=0,z=0,parent=0,scale=(1,1,1),rotation=(0,0,0,1)):
        return {"position":dict(zip("xyz",[int(v*1e6) for v in (x,y,z)])),"scale":dict(zip("xyz",[int(v*1e6) for v in scale])),"rotation":dict(zip("xyzw",[int(v*1e6) for v in rotation])),"parent_entity_id":parent}
    geometry={"profile":"world.aabb.v1","size":{"x":2000000,"y":4000000,"z":6000000},"offset":{"x":500000,"y":0,"z":0},"is_trigger":False,"layer_mask":1}
    ts=[transform(5),transform(1,2,3,10,(2,3,4),(0,.707106,0,.707106)),transform(6,2,3)]
    objects=[]; entities=[]
    for i,(id,name) in enumerate([(10,"origin"),(42,"marker"),(77,"solid")]):
        objects.append({"id":name,"actor_id":name,"instance_index":0,"semantic_type":"project.marker.v1","properties":{"label":name},"relationships":{},"asset_bindings":{},"capabilities":["project.any_surface.v1"],"transform":ts[i],"geometry":geometry if i==2 else None})
        components={"1":encoded(ts[i]),"12345":encoded({"arbitrary_property":"opaque","position":{"x":999999,"y":0,"z":0}})}
        if i==1:components["6"]=encoded({"controller_id":7,"control_type":"HUMAN"})
        # Real CGS packages may omit layer_mask; contract v3 materializes default 1.
        if i==2:components["4"]=encoded({**{k:v for k,v in geometry.items() if k not in {"profile","layer_mask"}},"shape":"BOX"})
        entities.append({"id":id,"actor_id":name,"components":components})
    world={"schema":"xace.world_contract.v3","contract_version":3,"mode_id":"markers","geometry_profiles":[{"id":"world.aabb.v1","required":True}],"schemas":[{"id":"project.marker.v1","definition":{"type":"object","fields":{"label":{"type":"string"}}}}],"capability_declarations":[{"id":"project.any_surface.v1","allowed_types":[]}],"objects":objects}
    alias=copy.deepcopy(objects[1]);alias['id']='marker_alias';alias['properties']['label']='alias';objects.append(alias)
    world['objects'].sort(key=lambda obj:obj['id'])
    raw=encoded(world)
    contract=json.loads((ROOT/'packages/core/tests/fixtures/session_contract_v2/authority.canonical.json').read_text())
    contract['profile_id']='host_client_lockstep_4p_60hz_windows_world_v3'
    contract['gameplay']['world']['contract_version']=3
    contract['gameplay']['world']['artifact']['content_hash']=digest(raw)
    contract['required_capabilities']=['input.timed.v1','session.projection.v1','world.aabb.v1','world.semantic_bindings.v3']
    offer={"contract":contract,"client":{"adapter":{"engine":"godot","adapter_version":"0.1.0","client_version":"xace.player.v1","platform":"windows_x64"},"engine_protocol_version":1,"capabilities":contract['required_capabilities'],"presentation_manifest_hash":"1"*64}}
    ticket={"schema":"xace.session_ticket.v1","controller_id":7,"peer_id":2,"credential":"fixture-only-credential","offer_json":encoded(offer)}
    def message(kind="handshake_ack",tick=7,seq=1,gen=1):
        projection=encoded(entities)
        stamp={"schema":"xace.session_projection.v1",**contract['epoch'],"connection_generation":gen,"baseline_id":"00000000-0000-4000-8000-000000000003","sequence":seq,"next_tick":tick,"projection_digest":digest(projection)}
        m={"msg_type":kind,"sync_json":encoded(stamp),"projection_json":projection,"tick":tick-1}
        if kind=='handshake_ack':m.update(accepted=True,assigned_peer_id=2,assigned_player_id=42,reconnect_credential='fixture-only-rotated',world_bindings={"origin":"10","marker":"42","marker_alias":"42","solid":"77"},cgs_hash=contract['gameplay']['cgs']['cgs_hash'],**contract['epoch'])
        return m
    base=message(); cases=[]
    def case(name,m,expected,prefix=None):cases.append({"name":name,"messages":[base] if prefix is None else prefix,"message":m,"expected":expected})
    case('contiguous',message('tick_snapshot',8,2),'accept')
    case('sequence_gap',message('tick_snapshot',9,3),'recover')
    case('late_baseline',message('session_baseline',20,5),'accept')
    case('stale_sequence',message('tick_snapshot',7,1),'drop')
    case('reconnect_generation',message('handshake_ack',20,1,2),'accept')
    case('stale_generation',message('handshake_ack',20,1,1),'drop')
    bad=copy.deepcopy(base);stamp=json.loads(bad['sync_json']);stamp['ruleset_epoch']+=1;bad['sync_json']=encoded(stamp);case('wrong_epoch',bad,'reject',[])
    bad=copy.deepcopy(base);bad['projection_json']='[]';case('corrupt_digest',bad,'reject',[])
    bad=message('tick_snapshot',8,2);bad['projection_json']='[]';case('corrupt_update',bad,'recover')
    bad=copy.deepcopy(base);stamp=json.loads(bad['sync_json']);stamp['next_tick']=9007199254740992;bad['sync_json']=encoded(stamp);case('unsafe_integer',bad,'reject',[])
    bad=copy.deepcopy(base);bad['world_bindings']['solid']='42';case('duplicate_binding',bad,'reject',[])
    bad=copy.deepcopy(base);bad['assigned_player_id']=77;case('wrong_owner',bad,'reject',[])
    bad=copy.deepcopy(base);bad['sync_json']='null';case('null_stamp',bad,'reject',[])
    bad=copy.deepcopy(base);projection=copy.deepcopy(entities);projection.append(projection[0]);bad['projection_json']=encoded(projection);stamp=json.loads(bad['sync_json']);stamp['projection_digest']=digest(bad['projection_json']);bad['sync_json']=encoded(stamp);case('duplicate_entity',bad,'reject',[])
    bad=copy.deepcopy(base);projection=copy.deepcopy(entities);t=json.loads(projection[0]['components']['1']);t['parent_entity_id']=42;projection[0]['components']['1']=encoded(t);bad['projection_json']=encoded(projection);stamp=json.loads(bad['sync_json']);stamp['projection_digest']=digest(bad['projection_json']);bad['sync_json']=encoded(stamp);case('parent_cycle',bad,'reject',[])
    return {"schema":"xace.native_contract_fixture.v1","world_json":raw,"ticket_json":encoded(ticket),"baseline":base,"cases":cases,"canonical_position":[6,2,3],"canonical_normal":[1,0,0],"canonical_size":[2,4,6]}

def run(command, cwd, log, timeout=900):
    with log.open('w',encoding='utf8') as stream:
        result=subprocess.run(command,cwd=cwd,stdout=stream,stderr=subprocess.STDOUT,timeout=timeout,creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
    if result.returncode:raise RuntimeError(f"Host failed ({result.returncode}): {log}")

def live(engine,package,out):
    if engine not in {'godot','unreal'}:raise ValueError('Live socket proof currently supports Godot or Unreal; use --engine unity for its installed-editor contract proof')
    def free_port():
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));return sock.getsockname()[1]
    port,control=free_port(),free_port();directory=out/(engine+'-live');directory.mkdir(parents=True,exist_ok=True)
    ticket=directory/'ticket.json';journal=directory/'session.jsonl';report=directory/'proof.json'
    if ticket.exists() or journal.exists():raise ValueError('Choose a fresh output directory for the live proof')
    command=[str(package/'runtime/xace_runtime.exe')]
    for flag,name in [('cgs','game.cgs.json'),('sgc-plan','execution_plan.json'),('world','world.json'),('world-manifest','world.manifest.json'),('package-manifest','playable.manifest.json')]:command+=['--'+flag,str(package/name)]
    command+=['--session-ticket-out',str(ticket),'--session-log',str(journal),'--session-controller-id','1','--input-lockstep-peer','1','--port',str(port),'--control-port',str(control),'--no-wait','--live-engine-accept','--live-session','--quiet']
    with (directory/'authority.log').open('w') as log:
        authority=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
        try:
            deadline=time.monotonic()+10
            while not ticket.exists() and authority.poll() is None and time.monotonic()<deadline:time.sleep(.03)
            if not ticket.exists():raise RuntimeError('Authority did not issue a session ticket')
            if engine=='godot':
                exe=Path('C:/Users/ankit/Downloads/Godot_v4.6.3-stable_win64.exe/Godot_v4.6.3-stable_win64_console.exe')
                cmd=[str(exe),'--headless','--path',str(ROOT/'adapters/godot'),'--script','res://tests/native_live_proof.gd','--',f'--port={port}',f'--ticket={ticket}',f'--world={package / "world.json"}',f'--cgs={package / "game.cgs.json"}',f'--report={report}']
            else:
                exe=Path('C:/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor-Cmd.exe')
                project=out/'target-codex-task66-unreal-vertical-slice/XaceTask66.uproject'
                cmd=[str(exe),str(project),'-run=XaceNativeContractProof','-XaceLive','-unattended','-nullrhi','-nosplash',f'-XacePort={port}',f'-XaceTicket={ticket}',f'-XaceWorld={package / "world.json"}',f'-XaceCgs={package / "game.cgs.json"}',f'-XaceReport={report}',f'-abslog={directory / "editor.log"}']
            run(cmd,ROOT,directory/'host.log',90)
            result=json.loads(report.read_text(encoding='utf-8-sig'));assert result['ok'],result
            with socket.create_connection(('127.0.0.1',control),timeout=5) as sock:
                payload=encoded({'msg_type':'runtime_control','protocol_version':1,'request_id':'xp016-proof','action':'shutdown'}).encode();sock.sendall(struct.pack('<I',len(payload))+payload)
            authority.wait(timeout=8);assert authority.returncode==0
            rows=[json.loads(line) for line in journal.read_text().splitlines()]
            result['authority_clean_exit']=True;result['journal_rows']=len(rows)
            report.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8');return result
        finally:
            if authority.poll() is None:authority.terminate();authority.wait(timeout=8)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--generate',action='store_true');ap.add_argument('--engine',choices=['godot','unity','unity-compile','unreal']);ap.add_argument('--out',type=Path,default=ROOT/'target/xp016');ap.add_argument('--live',action='store_true');ap.add_argument('--package',type=Path,default=ROOT/'target/xp016/player/exported/package');a=ap.parse_args()
    if a.generate:
        FIXTURE.parent.mkdir(parents=True,exist_ok=True);FIXTURE.write_text(encoded(fixture())+'\n',encoding='utf8')
    if not a.engine:return
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=True);report=out/(a.engine+'.json')
    if a.live:
        print(json.dumps(live(a.engine,a.package.resolve(),out),indent=2));return
    if a.engine=='godot':
        exe=Path('C:/Users/ankit/Downloads/Godot_v4.6.3-stable_win64.exe/Godot_v4.6.3-stable_win64_console.exe')
        run([str(exe),'--headless','--path',str(ROOT/'adapters/godot'),'--script','res://tests/native_contract_proof.gd','--',f'--fixture={FIXTURE}',f'--report={report}'],ROOT,out/'godot.log',90)
    elif a.engine=='unity-compile':
        data=Path('C:/Program Files/Unity/Hub/Editor/6000.4.9f1/Editor/Data')
        refs=list((data/'MonoBleedingEdge/lib/mono/4.8-api').glob('*.dll'))+list((data/'MonoBleedingEdge/lib/mono/4.8-api/Facades').glob('*.dll'))+list((data/'Managed').glob('*.dll'))+list((data/'Managed/UnityEngine').glob('*.dll'))
        rsp=out/'unity-compile.rsp'
        rsp.write_text('/noconfig\n/nostdlib+\n/unsafe+\n/target:library\n/out:"'+str(out/'unity-compile.dll')+'"\n'+'\n'.join('/reference:"'+str(p)+'"' for p in refs)+'\n'+'\n'.join('"'+str(p)+'"' for p in (ROOT/'adapters/unity').rglob('*.cs'))+'\n',encoding='utf8')
        run([str(data/'NetCoreRuntime/dotnet.exe'),str(data/'DotNetSdkRoslyn/csc.dll'),'@'+str(rsp)],ROOT,out/'unity-compile.log',90)
        report.write_text(encoded({'ok':True,'engine':'unity','compilation_only':True,'native_host_verification':'not_run_in_compile_mode'}))
    elif a.engine=='unity':
        import unity_vertical_slice_certification as old
        project=out/'target-codex-task65-unity-vertical-slice';old.stage_unity_project(unity_project_dir=project,fixture_root=old.FIXTURE_ROOT,adapter_root=ROOT/'adapters/unity',validation_path=out/'legacy-unity.json',screenshot_path=out/'legacy-unity.png',unity_version='6000.4.9f1')
        shutil.copy2(ROOT/'adapters/unity/Editor/XaceNativeContractProof.cs',project/'Assets/XACE/Editor')
        exe=Path('C:/Program Files/Unity/Hub/Editor/6000.4.9f1/Editor/Unity.exe')
        run([str(exe),'-batchmode','-nographics','-quit','-projectPath',str(project),'-executeMethod','Xace.Adapter.Unity.Editor.XaceNativeContractProof.Run','-logFile',str(out/'unity-editor.log'),'-xaceFixture',str(FIXTURE),'-xaceReport',str(report)],ROOT,out/'unity.log')
    else:
        import unreal_vertical_slice_certification as old
        old.ADAPTER_SOURCE_NAMES+=('XaceNativeContractProofCommandlet.h','XaceNativeContractProofCommandlet.cpp')
        project=out/'target-codex-task66-unreal-vertical-slice';stage=old.stage_unreal_project(unreal_project_dir=project,fixture_root=old.FIXTURE_ROOT,adapter_root=ROOT/'adapters/unreal',validation_path=out/'legacy-unreal.json',screenshot_path=out/'legacy-unreal.png',engine_association='5.7')
        exe=Path('C:/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor-Cmd.exe')
        build=old.build_unreal_plugin(unreal_editor=exe,plugin_root=stage['plugin_root'],package_dir=out/'unreal-package',command_path=out/'unreal-build-command.json',stdout_path=out/'unreal-build.log',stderr_path=out/'unreal-build-errors.log',timeout_seconds=1800)
        if not build['ok']:raise RuntimeError(f"Unreal build failed: {out/'unreal-build.log'}")
        old.copy_packaged_binaries_to_project(out/'unreal-package',stage['plugin_root'])
        run([str(exe),str(stage['project_file']),'-run=XaceNativeContractProof','-unattended','-nullrhi','-nosplash',f'-XaceFixture={FIXTURE}',f'-XaceReport={report}',f'-abslog={out / "unreal-editor.log"}'],ROOT,out/'unreal.log')
    result=json.loads(report.read_text(encoding='utf-8-sig'));assert result['ok'],result
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
