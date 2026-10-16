"""NEC-007 real capture -> GDE -> Factory -> SGC -> isolated runtime proof.

Never launches an imported native project or writes a source/CGS baseline.
Gameplay values are explicit fixture user choices, not inferred native behavior.
"""
import argparse
import copy
import hashlib
import importlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/"packages"),str(ROOT/"packages/project-system"),str(ROOT/"packages/project-system/tests")]
from native_adoption import plan_adoption,compile_execution_preview,digest,encode,actor_id,factory
from test_native_adoption import choices_for,add_damage_choices,damage_package,oid
from tools.world_extensibility_proof import semantic_fixture,rehash
from tools.xp013_socket_proof import send,receive,port


def write(path,value):path.write_text(json.dumps(value,indent=2)+"\n",encoding="utf-8")
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def runtime_proof(folder,runtime,cgs,compiled,execution):
    folder.mkdir(parents=True,exist_ok=False)
    write(folder/"game.cgs.json",cgs);write(folder/"execution_plan.json",execution)
    (folder/"world.json").write_bytes(compiled.world_contract.content_bytes)
    (folder/"world.manifest.json").write_bytes(compiled.world_contract.manifest_bytes)
    cp=port();command=[str(runtime),'--cgs',str(folder/'game.cgs.json'),'--sgc-plan',str(folder/'execution_plan.json'),'--require-sgc-plan','--world',str(folder/'world.json'),'--world-manifest',str(folder/'world.manifest.json'),'--port','0','--control-port',str(cp),'--no-wait','--start-paused','--quiet']
    write(folder/'command.json',command)
    log=(folder/'runtime.log').open('wb')
    process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,cwd=folder,creationflags=subprocess.CREATE_NO_WINDOW)
    def control(action):
        with socket.create_connection(('127.0.0.1',cp),timeout=5) as sock:
            send(sock,dict(msg_type='runtime_control',protocol_version=1,request_id='nec007',action=action));result=receive(sock)
            assert result['accepted'],result
            return result
    try:
        deadline=time.monotonic()+20
        while True:
            if process.poll() is not None:raise RuntimeError((folder/'runtime.log').read_text(errors='replace')[-2500:])
            try:before=control('snapshot');break
            except OSError:
                if time.monotonic()>deadline:raise
                time.sleep(.05)
        snapshots=[before['snapshot']]
        for _ in range(2):
            prior=snapshots[-1]['tick'];control('step')
            deadline=time.monotonic()+5
            while True:
                response=control('snapshot')
                if response['snapshot']['tick']>prior:break
                assert time.monotonic()<deadline,'tick did not advance';time.sleep(.02)
            snapshots.append(response['snapshot'])
        write(folder/"snapshots.json",snapshots)
        expected_transforms=sorted(encode(next(c["defaults"] for c in actor["components"] if c["type_id"]==1)) for actor in cgs["modes"][0]["actors"])
        for index,snapshot in enumerate(snapshots):
            assert sorted(encode(json.loads(e["components"]["1"])) for e in snapshot["entities"])==expected_transforms,"native-derived transforms changed"
            expected_health=100000000 if index==0 else 90000000
            assert snapshot['entities'],snapshot
            for entity in snapshot['entities']:
                values={int(k):json.loads(v) for k,v in entity['components'].items()}
                assert values[100]['current']==expected_health,(index,values)
                assert values[101]['amount']==(10000000 if index==0 else 0),(index,values)

        hashes=control('status')['status']['hash_log']
        control('shutdown');process.wait(timeout=10)
        assert process.returncode==0
        result=dict(ok=True,snapshots=snapshots,hash_log=hashes,health=[100000000,90000000,90000000],damage_consumed_once=True,native_transforms_preserved=True)
        write(folder/'proof.json',result);return result
    finally:
        if process.poll() is None:process.terminate();process.wait(timeout=10)
        log.close()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);args=parser.parse_args();out=args.out.resolve()
    assert out.is_relative_to(ROOT/'recovery-evidence/20261016/nec007') and not out.exists();out.mkdir(parents=True)
    fixtures=ROOT/'packages/project-system/tests/fixtures/nec007'
    provenance=json.loads((fixtures/'provenance.json').read_text())
    sgc=Path('C:/Users/ankit/XACE-Recovery/build-output/cargo/debug/xace-system-graph-compiler.exe')
    runtime=ROOT/'recovery-evidence/20261015/xp022-ingress-batch/pinned-binaries/xace_reference_host.exe'
    assert sha(runtime)=='ccbd880532321eb86c544e40260da6238b3ee3232bd68026bd9b848d54543ae1'
    results={}
    for engine,selected in [('unity',[oid(3)]),('godot',[oid(5)]),('unreal',[oid(2),oid(3)])]:
        folder=out/engine;folder.mkdir()
        source=fixtures/(engine+'.json');data=source.read_bytes();before_hash=sha(source)
        assert before_hash==provenance[engine]['sha256']==sha(ROOT/provenance[engine]['source'])
        reader=importlib.import_module(engine+'_authoring');mapping=reader.prepare_identity_map(data,project_id='nec007-'+engine,branch_id='b'*32)
        observed=json.loads(data);cgs=semantic_fixture();cgs['modes'][0]['actors']=[];cgs['modes'][0]['world'].pop('contract')
        choices=choices_for(selected)
        for key in selected:
            if 'presentation.asset' in observed['objects'][key]['fields']:choices['objects'][key]['asset_role']='project.visual.v1'
        add_damage_choices(cgs,choices);catalog,operation=damage_package(mapping,selected);choices['packages']=[operation]
        context=dict(native_inventory=data,mapping=mapping,current_cgs=cgs,selection=selected,choices=choices,expected_source_digest=before_hash,expected_cgs_digest=digest(cgs),trusted_project=True,gameplay_catalog=catalog)
        before=encode([cgs,mapping.to_dict(),choices]);plan=plan_adoption(**context);report=plan.to_dict();write(folder/'plan.json',report)
        assert report['candidate_valid'],report['losses'];assert before==encode([cgs,mapping.to_dict(),choices])
        assert plan_adoption(**context)==plan
        compilation=compile_execution_preview(plan,sgc_executable=sgc,context=context);write(folder/'compilation.json',compilation)
        candidate=report['proposed_cgs'];compiled=factory.compile_portable_cgs(candidate)
        for key in selected:
            fields=reader.capture(data,mapping,enable_writes=True).admit().to_dict()['inspection']['normalized'][key]['fields']
            actor=next(a for a in candidate['modes'][0]['actors'] if a['id']==actor_id(mapping,key))
            transform=next(c['defaults'] for c in actor['components'] if c['type_id']==1)
            assert all(transform[name]=={k:int(v) for k,v in fields['transform.'+name].items()} for name in ['position','rotation','scale'])
        again=plan_adoption(**dict(context,current_cgs=candidate,expected_cgs_digest=digest(candidate))).to_dict();assert again['noop'] and again['candidate_valid'];write(folder/'repeat.json',again)
        first=runtime_proof(folder/'runtime-first',runtime,candidate,compiled,compilation['execution_plan'])
        second=runtime_proof(folder/'runtime-repeat',runtime,candidate,compiled,compilation['execution_plan']);assert first['hash_log']==second['hash_log']
        assert sha(source)==before_hash and sha(ROOT/provenance[engine]['source'])==before_hash
        results[engine]=dict(ok=True,native_fixture=provenance[engine],captured_objects=len(observed['objects']),selected=len(selected),plan_digest=plan.sha256,idempotent=True,source_and_current_unchanged=True,actual_runtime_runs=2,deterministic_hashes=first['hash_log'],expected_health=first['health'],native_transforms_preserved=True)
    result=dict(schema='xace.nec007.native_adoption_proof.v1',ok=True,engines=results,runtime_sha256=sha(runtime),sgc_sha256=sha(sgc),runtime_free_export=False,commit_performed=False)
    write(out/'proof.json',result);print(json.dumps(result,indent=2))

if __name__=='__main__':main()
