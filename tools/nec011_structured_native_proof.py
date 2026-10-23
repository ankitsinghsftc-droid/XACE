"""Execute retained real-native hierarchical captures with the pinned structured host.
Historical native extraction is reused read-only; runtime execution is fresh.
"""
import copy,hashlib,importlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system'),str(ROOT/'packages/project-system/tests')]
from test_native_adoption import inputs,plan,oid,actor_id
from authoring_identity import canonical
from native_instance_transforms import PROFILE
from native_executor_contract import TrustedExecutor,digest,admit
from tools.cgs_schema_validate import compute_cgs_hash
import playable_package as packages

def main(out):
    assert out.is_relative_to(ROOT/'evidence/nec011') and not out.exists();out.mkdir(parents=True)
    build=ROOT/'evidence/nec011/20261021/reference-admission-a'
    receipt=json.loads((build/'executor-receipt.json').read_bytes())
    exe=build/'relocated-game/runtime/xace_runtime.exe'
    trusted=TrustedExecutor(receipt,expected_receipt_digest=digest(receipt),executable=exe,expected_compatibility=receipt['compatibility'])
    reference=json.loads((ROOT/'examples/reference-mechanic/fixtures/player/game.cgs.json').read_bytes())
    sgc=Path('C:/Users/ankit/XACE-Recovery/build-output/cargo/debug/xace-system-graph-compiler.exe')
    cases={}
    for engine,folder in [('godot','godot-hierarchy-monitor-c'),('unity','unity-hierarchy-a'),('unreal','unreal-hierarchy-c')]:
        dest=out/engine;dest.mkdir()
        history=ROOT/'evidence/nec011/20261021'/folder/'project/.xace/native-authoring-calls'
        captures=[]
        for path in history.glob('*/result.json'):
            row=json.loads(path.read_bytes());value=row.get('result',{})
            if row.get('ok') and value.get('schema')=='xace.'+engine+'_authoring_inventory.v1' and oid(3) in value.get('objects',{}):captures.append((path.stat().st_mtime_ns,path,value))
        _,source,value=max(captures,key=lambda x:x[0]);raw=canonical(value)
        (dest/'native-inventory.json').write_bytes(raw)
        reader=importlib.import_module(engine+'_authoring');mapping=reader.prepare_identity_map(raw,project_id='nec011-combined',branch_id='b'*32)
        _,_,cgs,selection,choices=inputs(engine)
        cgs['native_instance_profile']=PROFILE;cgs['component_schemas']=copy.deepcopy(reference['component_schemas']);cgs['global_systems']=copy.deepcopy(reference['global_systems']);cgs['modes'][0]['systems']=copy.deepcopy(reference['modes'][0]['systems'])
        player=next(a for a in reference['modes'][0]['actors'] if a['id']=='player')
        choices['objects'][oid(3)].update(actor_type='PLAYER',control_type='HUMAN',components=[copy.deepcopy(c) for c in player['components'] if c['type_id']!=1])
        cgs['metadata']['cgs_hash']=compute_cgs_hash(cgs)
        result=plan(raw,mapping,cgs,selection,choices,trusted_executor=trusted).to_dict();(dest/'adoption.json').write_bytes(canonical(result));assert result['candidate_valid'],result['losses']
        candidate=result['proposed_cgs'];package,_=packages.compiled_artifacts(candidate);trusted.require_structured_transform(package)
        envelope=dict(systems=package.to_sgc_input(),schema_version=package.schema_version,cgs_hash=package.cgs_hash,plan_version=1)
        compiled=subprocess.run([str(sgc)],input=canonical(envelope),capture_output=True,check=True).stdout
        support=admit(receipt,expected_receipt_digest=digest(receipt),executable=exe,required_capabilities=['native.structured_transform.v1'],expected_compatibility=receipt['compatibility'],package=package)
        archive=packages.build_package(candidate,compiled,exe.read_bytes(),support,package_id='nec011.combined.'+engine,version='0.1.0');(dest/'game.xacepkg').write_bytes(archive)
        installed=dest/'relocated';installed.mkdir()
        for name,data in packages.read_archive(archive).items():
            p=installed/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        command=packages.runtime_command(installed,support,ticks=12)+['--port','0','--print-every','1','--epoch-replay-out',str(dest/'replay.xacer')]
        (dest/'command.json').write_bytes(canonical(command))
        with (dest/'runtime.log').open('wb') as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=60)
        assert r.returncode==0,'Combined native runtime failed: '+engine
        replay=[str(installed/'runtime/xace_runtime.exe'),'--epoch-replay-in',str(dest/'replay.xacer'),'--epoch-replay-report',str(dest/'replay-report.json')]
        with (dest/'replay.log').open('wb') as log:r=subprocess.run(replay,stdout=log,stderr=subprocess.STDOUT,timeout=60)
        assert r.returncode==0,'Combined replay failed: '+engine
        proof=json.loads((dest/'replay-report.json').read_bytes());assert proof['ok']
        bundle=json.loads((dest/'replay.xacer').read_bytes())['bundle']
        ticks=bundle['ticks'];assert len(ticks)==12 and proof['verified_ticks']==12
        first=ticks[0]['state'];last=ticks[-1]['state']
        assert first['entities']==last['entities']
        a={k:json.loads(v) for k,v in first['components']['tables']['1']['rows'].items()}
        b={k:json.loads(v) for k,v in last['components']['tables']['1']['rows'].items()}
        assert set(a)==set(b) and len(a)==2
        moving=[key for key in a if a[key]!=b[key]];assert len(moving)==1
        key=moving[0];assert b[key]['position']['y']<a[key]['position']['y']
        assert all(row['parent_entity_id']==0 for row in b.values())
        assert all(len(tick['state']['entities']['entities'])==2 for tick in ticks)
        (dest/'structured-state-proof.json').write_bytes(canonical(dict(ok=True,stable_entity_store=True,structured_transform_changed=True,moving_entity=key,first=a[key],last=b[key],replayed_ticks=12,world_hashes=[t['world_hash'] for t in ticks])))
        cases[engine]=dict(native_source=str(source),native_capture_sha256=hashlib.sha256(raw).hexdigest(),adoption_valid=True,structured_executor_admitted=True,runtime_exit=0,replay=proof,native_editor_rerun=False)
    (out/'proof.json').write_bytes(canonical(dict(ok=True,cases=cases,executor_sha256=receipt['executable_sha256'],sgc_sha256=hashlib.sha256(sgc.read_bytes()).hexdigest(),runtime_parenting=False)))
    print('Combined native structured execution and replay passed all engines')
if __name__=='__main__':main(Path(sys.argv[1]).resolve())
