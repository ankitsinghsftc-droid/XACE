"""XP-017 actual installed hosts under one authority; generated output stays ignored.

Input recordings and reference-mechanic assertions belong here, never in adapters.
No Internet/multi-machine claim: all sockets in this proof use loopback.
"""
from pathlib import Path
import argparse, copy, hashlib, importlib, json, shutil, socket, subprocess, sys, time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system')]
from tools.xp013_socket_proof import send, receive, port
from tools.xp009_player_proof import stage as reference_stage, resources
from tools.xp007_package_proof import compile_plan
from tools.world_extensibility_proof import rehash
from tools.xp008_player_build import prepare_player, export_player
from playable_package import RuntimeSupport, build_package, install_archive, digest
GODOT=Path('C:/Users/ankit/Downloads/Godot_v4.6.3-stable_win64.exe/Godot_v4.6.3-stable_win64_console.exe')
UNITY=Path('C:/Program Files/Unity/Hub/Editor/6000.4.9f1/Editor/Unity.exe')
UNREAL=Path('C:/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor-Cmd.exe')
TEMPLATE=Path('C:/Users/ankit/Downloads/xace/tmp/xp008-export/windows_release_x86_64.exe')
def load(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def write(p,v):Path(p).write_text(json.dumps(v,indent=2)+'\n',encoding='utf8')
def rows(p):
    if not p.exists():return []
    lines=p.read_text(encoding='utf-8-sig').splitlines();result=[]
    for line in lines:
        try:result.append(json.loads(line))
        except json.JSONDecodeError:break # writer may be appending final row
    return result
def wait_for(predicate,seconds=90):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        value=predicate()
        if value:return value
        time.sleep(.03)
    raise TimeoutError('Proof condition timed out')
def stage(out):
    if out.exists():raise FileExistsError('Refusing to replace an existing proof build: '+str(out))
    source=reference_stage(out/'reference')
    cgs=load(source/'package/game.cgs.json');mode=cgs['modes'][0]
    for controller in [3,4]:
        actor=copy.deepcopy(mode['actors'][-1]);actor['id']='peer_'+str(controller)
        for c in actor['components']:
            if c['type_id']==6:c['defaults']['controller_id']=controller
            if c['type_id']==1:c['defaults']['position']['z']=(controller-2)*1000000
            if c['type_id']==2:c['defaults']['entity_name']=actor['id']
        mode['actors'].append(actor)
        obj=copy.deepcopy(mode['world']['contract']['objects'][-1]);obj['id']=obj['actor_id']=actor['id'];mode['world']['contract']['objects'].append(obj)
    rehash(cgs);plan,compiled=compile_plan(cgs)
    runtime=(ROOT/'target/debug/xace_reference_host.exe').read_bytes()
    support=RuntimeSupport(digest(runtime),'xace.runtime_executor.v1',tuple(compiled.to_sgc_input()))
    import zipfile,io
    initial=build_package(cgs,plan,runtime,support,package_id='reference.mixed',version='1.0.0')
    with zipfile.ZipFile(io.BytesIO(initial)) as z:manifest=json.loads(z.read('playable.manifest.json'));world=json.loads(z.read('world.json'))
    visuals=resources(manifest,world)
    visuals['presentation/player/settings.json']=(source/'package/presentation/player/settings.json').read_bytes()
    archive=build_package(cgs,plan,runtime,support,package_id='reference.mixed',version='1.0.0',presentation_files=visuals)
    installed,_=install_archive(archive,out/'installed',support)
    player=out/'player';prepare_player(installed,support,player)
    shutil.copy2(ROOT/'tools/xp017_player_proof.gd',player/'mixed_player.gd')
    scene=player/'player.tscn';scene.write_text(scene.read_text().replace('res://player.gd','res://mixed_player.gd'))
    export_player(player,out/'exported/xace-mixed-proof.exe',GODOT,TEMPLATE)
    import tools.unity_vertical_slice_certification as unity
    project=out/'target-codex-task65-unity-vertical-slice'
    unity.stage_unity_project(unity_project_dir=project,fixture_root=unity.FIXTURE_ROOT,adapter_root=ROOT/'adapters/unity',validation_path=out/'legacy.json',screenshot_path=out/'legacy.png',unity_version='6000.4.9f1')
    shutil.copy2(ROOT/'adapters/unity/Editor/XaceMixedSessionProof.cs',project/'Assets/XACE/Editor')
    return out/'exported/package'
def recording(controller):
    result=[];previous={}
    for tick in range(42):
        values={'move_x':-1 if controller==1 and tick<12 else (0.25 if controller==2 and tick>=15 else 0),'move_z':1 if controller==1 and tick<12 else 0,'Jump':1 if controller==1 and tick in [1,3,7,9] else 0}
        actions=[]
        for name,value in values.items():
            kind='button' if name=='Jump' else 'axis_1d'
            phase='cancelled' if value==0 else ('started' if previous.get(name,0)==0 else 'performed') if kind=='button' else 'changed'
            actions.append(dict(action=name,kind=kind,phase=phase,value=value,secondary_value=0))
        result.append(actions);previous=values
    return result
def scenario(out,engines,build,unreal_project):
    out.mkdir(parents=True,exist_ok=False);pkg=build/'exported/package';ep,cp=port(),port()
    ticket=out/'ticket.json';journal=out/'session.jsonl';n=len(engines)
    args=[str(pkg/'runtime/xace_runtime.exe')]
    for flag,name in [('cgs','game.cgs.json'),('sgc-plan','execution_plan.json'),('world','world.json'),('world-manifest','world.manifest.json'),('package-manifest','playable.manifest.json')]:args+=['--'+flag,str(pkg/name)]
    args+=['--session-ticket-out',str(ticket),'--session-log',str(journal),'--session-controller-id',','.join(map(str,range(1,n+1))),'--input-lockstep-peer',','.join(map(str,range(1,n+1))),'--port',str(ep),'--control-port',str(cp),'--start-paused','--no-wait','--live-engine-accept','--live-session','--quiet','--schedule-snapshot-out',str(out/'authority-schedule.json')]
    processes=[];streams=[]
    def spawn(cmd,log):
        f=log.open('w');streams.append(f);p=subprocess.Popen(cmd,stdout=f,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW);processes.append(p);return p
    authority=spawn(args,out/'authority.log')
    def control(action):
        with socket.create_connection(('127.0.0.1',cp),timeout=5) as s:send(s,dict(msg_type='runtime_control',protocol_version=1,request_id='xp017',action=action));r=receive(s);assert r['accepted'],r
    try:
        tickets=[ticket if i==1 else out/f'ticket.peer{i}.json' for i in range(1,n+1)]
        wait_for(lambda:all(p.exists() for p in tickets),15)
        cgs=load(pkg/'game.cgs.json')['metadata']['cgs_hash']
        grant=load(ticket);offer=json.loads(grant['offer_json']);offer['contract']['gameplay']['world']['artifact']['content_hash']='0'*64
        with socket.create_connection(('127.0.0.1',ep),timeout=5) as s:
            send(s,dict(msg_type='handshake',protocol_version=1,engine_name='Godot',engine_version='4.6.3',adapter_version='0.1.0',cgs_hash=cgs,capabilities=[],session_offer_json=json.dumps(offer),session_peer_id=1,session_credential=grant['credential']));refusal=receive(s);assert refusal['accepted'] is False
            write(out/'wrong-world-refusal.json',{'accepted':False,'reason':refusal.get('reject_reason','')})
        transcripts=[];clients=[]
        for i,engine in enumerate(engines,1):
            # Player's production liveness timeout remains enabled. Wait for
            # slower editor startup before admitting it to a paused proof host.
            if engine=='player' and transcripts:
                wait_for(lambda:all(any(r['kind']=='input' and r['tick']==0 for r in rows(p)) for p in transcripts),120)
            transcript=out/f'{engine}.jsonl';transcripts.append(transcript)
            config=out/f'{engine}-config.json';write(config,dict(schema='xace.mixed_host_proof.v1',ticket=str(tickets[i-1]),world=str(pkg/'world.json'),port=ep,cgs_hash=cgs,inputs=recording(i),stop_tick=19 if i==n else 39,transcript=str(transcript)))
            if engine=='player':
                frames=out/'frames';frames.mkdir();data=load(config);data['frames']=str(frames);write(config,data)
            if engine=='godot':cmd=[str(GODOT),'--headless','--path',str(ROOT/'adapters/godot'),'--script','res://tests/mixed_session_proof.gd','--','--config='+str(config)]
            elif engine=='player':cmd=[str(build/'exported/xace-mixed-proof.exe'),'--','--config='+str(config),'--session-ticket='+str(tickets[i-1]),'--port='+str(ep),'--package='+str(pkg)]
            elif engine=='unity':cmd=[str(UNITY),'-batchmode','-nographics','-quit','-projectPath',str(build/'target-codex-task65-unity-vertical-slice'),'-executeMethod','Xace.Adapter.Unity.Editor.XaceMixedSessionProof.Run','-xaceConfig',str(config),'-logFile',str(out/'unity-editor.log')]
            else:cmd=[str(UNREAL),str(unreal_project),'-run=XaceNativeContractProof','-XaceMixed='+str(config),'-unattended','-nullrhi','-nosplash','-abslog='+str(out/'unreal-editor.log')]
            clients.append(spawn(cmd,out/f'{engine}.log'))
        def check_alive():
            for p in clients:
                if p.poll() not in (None,0):raise RuntimeError('Native client failed; inspect '+str(out))
        def ready():
            check_alive();return all(any(r['kind']=='input' and r['tick']==0 for r in rows(p)) for p in transcripts)
        wait_for(ready,120)
        for tick in range(40):
            active=transcripts if tick<20 else transcripts[:-1]
            wait_for(lambda:all(any(r['kind']=='input' and r['tick']==tick for r in rows(p)) for p in active),12)
            if tick==20:
                clients[-1].wait(timeout=15)
                wait_for(lambda:any(r.get('kind')=='membership' and r.get('peer_id')==n and r.get('action') in ['transport_closed','disconnected'] for r in rows(journal)),8)
            control('step')
            wait_for(lambda:all(any(r['kind']=='tick' and r['tick']==tick for r in rows(p)) for p in active),12)
        for p in clients:assert p.wait(timeout=15)==0
        control('shutdown');assert authority.wait(timeout=10)==0
        logs=[rows(p) for p in transcripts];identities=[next(r for r in log if r['kind']=='ready') for log in logs]
        assert len({r['player'] for r in identities})==n
        epoch=lambda r:tuple(r['epoch'][key] for key in ['session_id','authority_incarnation','ruleset_epoch'])
        assert len({epoch(r) for r in identities})==1
        for i,log in enumerate(logs):
            assert not any(r['kind']=='error' for r in log),log
            assert any(r['kind']=='done' and r['ok'] for r in log)
            for r in log:
                if r['kind']=='input':assert r['actions']==recording(i+1)[r['tick']]
                if r['kind']=='tick':assert r['applied'] and digest(r['projection_json'].encode())==r['sync']['projection_digest']
        ticks=[{r['tick']:r for r in log if r['kind']=='tick'} for log in logs]
        for tick in range(40):
            active=ticks if tick<20 else ticks[:-1]
            assert len({r[tick]['sync']['projection_digest'] for r in active})==1
            assert all(r[tick]['events']==active[0][tick]['events'] for r in active)
        # Package-specific assertion kept exclusively in this reference harness.
        events=[event for row in ticks[0].values() for event in row['events']]
        assert any(e['event_type']=='reference.shockwave.v1' for e in events),events
        hit=next(e for e in events if e['event_type']=='reference.shockwave_hit.v1' and int(e['data']['target_entity_id'])==identities[1]['player'])
        hit_tick=int(hit['data']['tick']);target=identities[1]['player']
        def velocity(tick):
            entity=next(e for e in json.loads(ticks[0][tick]['projection_json']) if e['id']==target)
            return json.loads(entity['components']['5'])['linear']
        assert velocity(hit_tick)!=velocity(hit_tick-1),'Shared event did not change other owner state'
        authority_inputs={(r['peer_id'],r['packet']['tick']):r['packet'] for r in rows(journal) if r['kind']=='input'}
        for peer in range(1,n+1):
            for tick in range(20 if peer==n else 40):
                actual=authority_inputs[(peer,tick)];assert actual['player_id']==identities[peer-1]['player']
                stripped=[{k:a[k] for k in ['action','kind','phase','value','secondary_value']} for a in actual['actions']]
                assert sorted(stripped,key=lambda x:x['action'])==sorted(recording(peer)[tick],key=lambda x:x['action'])
        schedule=load(out/'authority-schedule.json');assert len(schedule['hash_log'])==40
        if 'player' in engines:
            ffmpeg=shutil.which('ffmpeg')
            if not ffmpeg:raise RuntimeError('ffmpeg is required to retain the captured gameplay recording')
            subprocess.run([ffmpeg,'-y','-loglevel','error','-framerate','20','-i',str(out/'frames/%04d.png'),'-c:v','libx264','-pix_fmt','yuv420p',str(out/'gameplay.mp4')],check=True,creationflags=subprocess.CREATE_NO_WINDOW)
        result=dict(schema='xace.xp017.mixed_session_proof.v1',ok=True,engines=engines,owners=[r['player'] for r in identities],versions=[r['version'] for r in identities],same_epoch=True,matching_applied_projections=True,matching_events=True,reference_shared_event=True,other_owner_velocity_changed_at=hit_tick,authority_inputs_match_recording=True,wrong_world_rejected=True,departed_engine=engines[-1],departed_after_tick=19,survivors_final_tick=39,authority_hashes=40,scope='Actual installed native hosts and exported Player; loopback, one Windows computer.')
        result['recording']='gameplay.mp4' if 'player' in engines else 'per-host applied projection/event transcripts'
        result['recording_timing']='One actual rendered Player frame per authority tick, encoded at 20 FPS for inspection; not a latency measurement.' if 'player' in engines else 'Authority tick indexed'
        write(out/'proof.json',result);return result
    finally:
        for p in reversed(processes):
            if p.poll() is None:p.terminate();p.wait(timeout=10)
        for f in streams:f.close()
def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=ROOT/'recovery-evidence/xp017/run');p.add_argument('--build',type=Path,default=ROOT/'recovery-evidence/xp017/build');p.add_argument('--unreal-project',type=Path,default=ROOT/'recovery-evidence/xp017/native/target-codex-task66-unreal-vertical-slice/XaceTask66.uproject');p.add_argument('--stage',action='store_true');p.add_argument('--scenario',choices=['pair','three','four','all'],default='all');a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True);build=a.build.resolve()
    if a.stage:stage(build)
    choices={'pair':['player','godot'],'three':['unity','godot','unreal'],'four':['unity','godot','unreal','player']}
    result={name:scenario(out/name,engines,build,a.unreal_project.resolve()) for name,engines in choices.items() if a.scenario in ['all',name]}
    write(out/'proof.json',result);print(json.dumps(result,indent=2))
if __name__=='__main__':main()
