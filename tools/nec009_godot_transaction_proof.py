"""Installed Godot + GDE + recoverable coordinator proof, isolated copied fixture.

Gateway is proof-only, single-scene writes, pinned editor and closed saved scenes.
It does not install a production IPC service or certify concurrent native editors.
"""
import copy,json,os,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system')]
from authoring_identity import Baseline,WorldBinding,IdentityMap
from authoring_transaction_files import FileParticipant,sha,load_json
from authoring_transaction import AuthoringCoordinator
from authoring_native_participant import NativeParticipant
from authoring_saved_pair import SavedPair,verify_baseline_receipts,MAP
from authoring_apply import file_change,ACTIVATION,gde
from authoring_transaction_contract import TransactionRequest
from native_adoption import factory
from native_reconciliation_plan import _native_transform
from native_adoption import digest,encode
from native_reconciliation_plan import plan_reconciliation
from native_authoring_contract import Snapshot
from tools.world_extensibility_proof import rehash
import godot_authoring as reader

GODOT=Path('C:/Users/ankit/Downloads/Godot_v4.6.3-stable_win64.exe/Godot_v4.6.3-stable_win64_console.exe')


class Gateway:
    def __init__(self,out):
        self.out=Path(out);self.root=self.out/'godot-project'
        self.identity=dict(engine='godot',profile='nec009-proof-single-scene',root=str(self.root),editor_sha256=sha(GODOT.read_bytes()))
    def invoke(self,action,**kwargs):
        logs=self.out/'editor-calls';logs.mkdir(exist_ok=True);i=len(list(logs.glob('*-command.json')))
        command=dict(action=action,**kwargs);(self.root/'nec009-command.json').write_bytes(encode(command))
        previous=self.root/'nec009-result.json'
        if previous.exists():
            archive=logs/f'{i:03}-previous-result.json';assert not archive.exists();previous.rename(archive)
        argv=[str(GODOT),'--headless','--editor','--path',str(self.root),'--quit-after','600']
        (logs/f'{i:03}-command.json').write_bytes(encode(dict(argv=argv,request=command,executable_sha256=self.identity['editor_sha256'])))
        p=subprocess.run(argv,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
        (logs/f'{i:03}-editor.log').write_bytes(p.stdout)
        result=load_json(self.root/'nec009-result.json');(logs/f'{i:03}-result.json').write_bytes(encode(result))
        assert p.returncode==0 and result['ok'] and b'SCRIPT ERROR:' not in p.stdout,(action,result,p.stdout[-3000:])
        return result['result']
    def capture(self):return encode(self.invoke('capture')['inventory'])
    def prepare(self,transaction_id,request):
        prepared=self.invoke('prepare',transaction_id=sha(transaction_id.encode())[:32],request=request['write_request'])
        documents={row['document'][6:] for row in prepared['receipt']['rows']}
        prepared['dependency_hashes']={p.relative_to(self.root).as_posix():sha(p.read_bytes()) for p in [self.root/'project.godot',*sorted((self.root/'Fixture').iterdir())] if p.is_file() and p.relative_to(self.root).as_posix() not in documents}
        return prepared
    def inspect(self,prepared):
        if any(sha((self.root/p).read_bytes())!=h for p,h in prepared['dependency_hashes'].items()):return 'conflict'
        return self.invoke('inspect',prepared=prepared)['state']
    def commit(self,prepared):return self.invoke('commit',prepared=prepared)
    def recover(self,prepared):return self.invoke('recover',prepared=prepared)


def build(out):
    gateway=Gateway(out);root=gateway.root;saved=load_json(out/'context.json')
    mapping=IdentityMap.from_dict(saved['mapping']);baseline=Snapshot(encode(saved['baseline']))
    ctx=dict(baseline=baseline,baseline_cgs=saved['baseline_cgs'],mapping=mapping,current_mapping=copy.deepcopy(mapping),
             current_cgs=saved['current_cgs'],native_inventory=encode(saved['native']),expected_current_cgs_digest=digest(saved['current_cgs']),
             expected_source_digest=sha(encode(saved['native'])),verify_baseline=lambda b:b==mapping.baseline,trusted_project=True)
    proposal=plan_reconciliation(**ctx);report=proposal.to_dict()
    # Preserve the production refusal. The explicitly approved low-level fixture
    # below tests recovery after native publication, NOT permission to bypass it.
    assert not report['reviewable'] and any(r['code']=='structural_materialization_requires_coordinator' for r in report['losses'])
    (out/'blocked-reconciliation.json').write_bytes(proposal.payload)
    if (out/'prepared.json').exists():prepared=load_json(out/'prepared.json')
    else:
        committed=gde.prepare_commit(ctx['current_cgs'],report['typed_operations'],transaction_id='godot-main',validate=factory.compile_portable_cgs)
        raw=copy.deepcopy(saved['native']);key=next(k for k,r in mapping.objects.items() if r.world_binding)
        raw['objects'][key]['fields']['transform.position']=_native_transform('godot','transform.position',report['merge']['merged'][key]['fields']['transform.position'])
        before=reader.capture(encode(saved['native']),mapping,enable_writes=True).admit()
        target=reader.capture(encode(raw),mapping,enable_writes=True).admit()
        request=json.loads(reader.write_request(encode(saved['native']),before,target,mapping))
        target_map=copy.deepcopy(mapping);target_map.baseline=None
        prepared=dict(cgs=committed,target_mapping=target_map.to_dict(),expected_normalized=target.to_dict()['inspection']['normalized'],native_request=request,canonical_request=dict(files=[file_change('game.cgs.json',sha((root/'game.cgs.json').read_bytes()),encode(committed['cgs']))]))
        (out/'prepared.json').write_bytes(encode(prepared))
    pair=SavedPair(root,mapping=IdentityMap.from_dict(prepared['target_mapping']),expected_cgs=prepared['cgs']['cgs'],expected_normalized=prepared['expected_normalized'],recapture=gateway.capture)
    c=AuthoringCoordinator(root,dict(canonical=FileParticipant(root,name='canonical',allowed_paths=['game.cgs.json']),native=NativeParticipant(gateway)),verify_pair=pair.verify,baseline_participant=pair.participant,baseline_request=pair.baseline_request)
    request=TransactionRequest('godot-main',proposal.sha256,dict(canonical=prepared['canonical_request'],native=dict(write_request=prepared['native_request'])),ACTIVATION,dict(mapping=prepared['target_mapping'],cgs_digest=digest(prepared['cgs']['cgs']),normalized_digest=digest(prepared['expected_normalized'])))
    return c,prepared,request


def main(out):
    assert out.resolve().is_relative_to(ROOT/'recovery-evidence/20261016/nec009') and not out.exists();out.mkdir(parents=True)
    root=out/'godot-project';addon=root/'addons/xace_authoring';addon.mkdir(parents=True)
    source=ROOT/'recovery-evidence/20261016/nec005/native-final/godot-project/Fixture'
    shutil.copytree(source,root/'Fixture')
    for p in (ROOT/'adapters/godot/authoring').iterdir():
        if p.is_file():shutil.copyfile(p,addon/p.name)
    shutil.copyfile(ROOT/'tools/nec009_godot_gateway.gd',addon/'nec009_gateway.gd')
    (addon/'plugin.cfg').write_text((addon/'plugin.cfg').read_text().replace('script="authoring_plugin.gd"','script="nec009_gateway.gd"'))
    (root/'project.godot').write_text('config_version=5\n[application]\nconfig/name="NEC009 isolated transaction proof"\n[editor_plugins]\nenabled=PackedStringArray("res://addons/xace_authoring/plugin.cfg")\n[input]\nmove={"deadzone": 0.5, "events": []}\njump={"deadzone": 0.5, "events": []}\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n')
    gateway=Gateway(out);data=gateway.capture();mapping=reader.prepare_identity_map(data,project_id='nec009-godot',branch_id='b'*32)
    prior=load_json(ROOT/'recovery-evidence/20261016/nec007/native-runtime/godot/plan.json');cgs=prior['proposed_cgs'];key=prior['selected'][0]
    aid='native_'+mapping.namespace_id+'_'+key;mapping.objects[key].world_binding=WorldBinding(aid,aid,0)
    baseline=reader.capture(data,mapping,enable_writes=True).admit();position=baseline.to_dict()['inspection']['normalized'][key]['fields']['transform.position']
    transform=cgs['modes'][0]['actors'][0]['components'][0]['defaults'];transform['position']={k:int(v) for k,v in position.items()};rehash(cgs)
    mapping.baseline=Baseline(digest(cgs),baseline.sha256,mapping.mapping_digest(),'nec009-proof-entry-fixture','a'*64,'b'*64)
    # An explicit independent native Y edit, using the installed editor writer.
    raw=json.loads(data);value=copy.deepcopy(position);value['y']=str(int(value['y'])+2000000)
    request=dict(schema='xace.godot_authoring_write_request.v1',expected_inventory_digest=digest(raw),edits=[dict(document=raw['objects'][key]['path_hint'],authoring_id=key,fields={'transform.position':value})])
    staged=gateway.prepare('native-independent-y',dict(write_request=request));gateway.commit(staged)
    observed=gateway.capture();current=copy.deepcopy(cgs);current['modes'][0]['actors'][0]['components'][0]['defaults']['position']['x']+=1000000;rehash(current)
    (root/'game.cgs.json').write_bytes(encode(current))
    (out/'context.json').write_bytes(encode(dict(mapping=mapping.to_dict(),baseline=baseline.to_dict(),baseline_cgs=cgs,current_cgs=current,native=json.loads(observed))))
    child=subprocess.run([sys.executable,__file__,'--crash',str(out)],cwd=ROOT,capture_output=True)
    (out/'crash-child.log').write_bytes(child.stdout+child.stderr);assert child.returncode==73,child.stderr
    coordinator,prepared,_=build(out);assert coordinator.status()['play_build_blocked']
    try:coordinator.recover('godot-main')
    except ValueError as exc:assert 'saved native revision differs' in str(exc),str(exc)
    else:raise AssertionError('uncertified opaque serialization admitted')
    assert coordinator.status()['play_build_blocked'] and not (root/MAP).exists()
    state=load_json(root/'.xace/authoring-transactions/godot-main/state.json')
    assert state['state']=='recovery_conflict'
    (out/'blocked-state.json').write_bytes(encode(state))
    result=coordinator.recover('godot-main',action='rollback');assert result['state']=='rolled_back'
    assert (root/'game.cgs.json').read_bytes()==encode(current) and gateway.capture()==observed
    assert coordinator.recover('godot-main',action='rollback')==result and not coordinator.status()['play_build_blocked']
    (out/'proof.json').write_bytes(encode(dict(schema='xace.nec009.godot_transaction_proof.v1',ok=True,engine='godot',editor_sha256=gateway.identity['editor_sha256'],real_editor=True,real_native_save=True,process_exit=73,recovered='rolled_back',baseline_unadvanced=True,mixed_revision_blocked=True,opaque_serialization_refused=True,idempotent_recovery=True,runtime_activation=False,canonical_version=prepared['cgs']['cgs']['metadata']['version'],scope='Explicit low-level coordinator fault fixture; production reconciliation remains blocked by opaque serialization fingerprints; no full Godot apply admission or simultaneous native writer certification')))
    print((out/'proof.json').read_text())


if __name__=='__main__':
    if sys.argv[1]=='--crash':
        out=Path(sys.argv[2]);c,p,request=build(out)
        def crash(event):
            if event=='published_before_receipt:canonical':os._exit(73)
        c.checkpoint=crash
        c.commit(request,authorize=lambda r:True)
    else:main(Path(sys.argv[1]).resolve())
