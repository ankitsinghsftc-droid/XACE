"""Bridge actual native-produced action records into real authority/replay.
This certifies the declared event profile, not physical-device sampling or a live
native socket connection. Cosmetic package variants use native-played resources.
"""
import json,sys,subprocess,socket,time,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system')]
from tools.xp013_socket_proof import send,receive,port,verify
import playable_package as package
import native_executor_contract as contracts

def main(out,probe):
    assert out.is_relative_to(ROOT/'evidence/nec011') and not out.exists();out.mkdir(parents=True)
    observed=json.loads((probe/'proof.json').read_bytes());assert observed['ok']
    actions=observed['sampled_actions'];assert any(a['action']=='move_x' and a['value']==0.75 for a in actions)
    (out/'native-actions.json').write_text(json.dumps(actions,indent=2))
    base=ROOT/'evidence/nec011/20261021/reference-admission-a';installed=ROOT/'evidence/nec011/20261023/structured-native-b/godot/relocated';receipt=json.loads((base/'executor-receipt.json').read_bytes());exe=installed/'runtime/xace_runtime.exe'
    cgs=json.loads((installed/'game.cgs.json').read_bytes());compiled,_=package.compiled_artifacts(cgs)
    support=contracts.admit(receipt,expected_receipt_digest=contracts.digest(receipt),executable=exe,required_capabilities=['native.structured_transform.v1'],expected_compatibility=receipt['compatibility'],package=compiled)
    resources=ROOT/'evidence/nec011/20261023/godot-event-input-b/project'
    hashes=[];gameplay=[];presentations=[]
    for label,resource in [('original','tone.tres'),('replacement','replacement.tres')]:
        dest=out/label;dest.mkdir();pkg=dest/'package';pkg.mkdir()
        archive=package.build_package(cgs,(installed/'execution_plan.json').read_bytes(),exe.read_bytes(),support,package_id='nec011.native-input',version='0.1.0',presentation_files={'presentation/player/audio.tres':(resources/resource).read_bytes()})
        for name,data in package.read_archive(archive).items():
            p=pkg/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        manifest=json.loads((pkg/'playable.manifest.json').read_bytes());gameplay.append(manifest['gameplay_hash']);presentations.append(manifest['package_content_hash'])
        ep,cp=port(),port();ticket=dest/'ticket.json'
        command=[str(pkg/'runtime/xace_runtime.exe')]
        for flag,name in [('cgs','game.cgs.json'),('sgc-plan','execution_plan.json'),('world','world.json'),('world-manifest','world.manifest.json'),('package-manifest','playable.manifest.json')]:command+=['--'+flag,str(pkg/name)]
        command+=['--session-ticket-out',str(ticket),'--session-log',str(dest/'session.jsonl'),'--session-controller-id','1','--input-lockstep-peer','1','--port',str(ep),'--control-port',str(cp),'--start-paused','--no-wait','--live-engine-accept','--live-session','--quiet','--epoch-replay-out',str(dest/'replay.json')]
        (dest/'command.json').write_text(json.dumps(command,indent=2))
        with (dest/'authority.log').open('wb') as log:
            process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                deadline=time.monotonic()+20
                while not ticket.exists() and process.poll() is None and time.monotonic()<deadline:time.sleep(.03)
                assert ticket.exists(), "Authority did not publish a ticket; inspect retained authority.log"
                grant=json.loads(ticket.read_bytes())
                offer=json.loads(grant['offer_json']);offer['client']['adapter']['engine']=observed['engine']
                def control(action):
                    with socket.create_connection(('127.0.0.1',cp),timeout=15) as conn:
                        send(conn,dict(msg_type='runtime_control',protocol_version=1,request_id='nec011',action=action));reply=receive(conn);assert reply['accepted'],reply
                with socket.create_connection(('127.0.0.1',ep),timeout=15) as conn:
                    send(conn,dict(msg_type='handshake',protocol_version=1,engine_name=observed['engine'].capitalize(),engine_version=observed['version'].split('-')[0],adapter_version='0.1.0',cgs_hash=cgs['metadata']['cgs_hash'],capabilities=[],session_offer_json=json.dumps(offer),session_peer_id=1,session_credential=grant['credential']))
                    baseline=receive(conn);assert baseline['accepted'],baseline;verify(baseline);player=baseline['assigned_player_id']
                    send(conn,dict(msg_type='baseline_ack',stamp_json=baseline['sync_json']))
                    for tick in range(4):
                        request=receive(conn);assert request['msg_type']=='input_tick_request' and request['tick']==tick,request
                        send(conn,dict(msg_type='input_packet',peer_id=1,player_id=player,tick=tick,sequence_id=tick+1,actions=actions,ruleset_epoch=0))
                        control('step');snapshot=receive(conn);assert snapshot['msg_type']=='tick_snapshot',snapshot;verify(snapshot)
                        send(conn,dict(msg_type='baseline_ack',stamp_json=snapshot['sync_json']))
                    control('shutdown')
                process.wait(timeout=15);assert process.returncode==0
            finally:
                if process.poll() is None:process.terminate();process.wait(timeout=10)
        replay=json.loads((dest/'replay.json').read_bytes())['bundle'];ticks=replay['ticks'];assert len(ticks)==4
        for tick in ticks:
            assert len(tick['inputs'])==1
            recorded=tick['inputs'][0]['actions']
            assert len(recorded)==len(actions)
            for actual,expected in zip(recorded,actions):
                assert actual['action']==expected['action'] and actual['value']==expected['value'] and actual['secondary_value']==expected['secondary_value']
                assert actual['kind']=={'button':'Button','axis_1d':'Axis1D'}[expected['kind']] and actual['phase']==expected['phase'].capitalize()
                assert actual['target_entity'] is None and actual['metadata']=={}
        first=json.loads(ticks[0]['state']['components']['tables']['1']['rows'][str(player)])
        last=json.loads(ticks[-1]['state']['components']['tables']['1']['rows'][str(player)])
        assert last['position']['x']>first['position']['x'],(first,last)
        hashes.append([t['world_hash'] for t in ticks])
        command=[str(pkg/'runtime/xace_runtime.exe'),'--epoch-replay-in',str(dest/'replay.json'),'--epoch-replay-report',str(dest/'replay-report.json')]
        with (dest/'replay.log').open('wb') as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=45)
        assert r.returncode==0 and json.loads((dest/'replay-report.json').read_bytes())['verified_ticks']==4
    assert gameplay[0]==gameplay[1] and presentations[0]!=presentations[1] and hashes[0]==hashes[1]
    proof=dict(ok=True,engine=observed['engine'],native_probe_sha256=hashlib.sha256((probe/'proof.json').read_bytes()).hexdigest(),native_actions_applied_by_authority=True,structured_position_changed=True,every_tick_replayed=True,cosmetic_package_changed=True,gameplay_hash_unchanged=True,every_world_hash_unchanged=True,world_hashes=hashes[0],physical_device_certified=False,live_native_socket_certified=False)
    (out/'proof.json').write_text(json.dumps(proof,indent=2));print(json.dumps(proof,indent=2))
if __name__=='__main__':main(Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve())
