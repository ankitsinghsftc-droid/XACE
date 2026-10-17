"""NEC010 Unreal planner/coordinator cycle proof using an isolated native fixture.

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
from authoring_apply import file_change,ACTIVATION,gde,prepare_apply,apply_prepared
from authoring_transaction_contract import TransactionRequest
from native_adoption import factory
from native_reconciliation_plan import _native_transform
from native_adoption import digest,encode
from native_reconciliation_plan import plan_reconciliation
from native_authoring_contract import Snapshot
from tools.world_extensibility_proof import rehash
import unreal_authoring as reader

ENGINE=Path('C:/Program Files/Epic Games/UE_5.7/Engine')
EDITOR=ENGINE/'Binaries/Win64/UnrealEditor-Cmd.exe'
class Gateway:
    def __init__(self,out):
        self.out=Path(out);self.root=self.out/'unreal-project'
        self.identity=dict(engine='unreal',profile='nec010-proof-single-map',root=str(self.root),editor_sha256=sha(EDITOR.read_bytes()))
    def invoke(self,action,**kwargs):
        logs=self.out/'editor-calls';logs.mkdir(exist_ok=True);i=len(list(logs.glob('*-command.json')))
        command=dict(action=action,**kwargs);(self.root/'.xace/nec010-command.json').write_bytes(encode(command))
        previous=self.root/'.xace/nec010-result.json'
        if previous.exists():previous.rename(logs/f'{i:03}-previous-result.json')
        argv=[str(EDITOR),str(self.root/'NEC006.uproject'),'-run=XaceAuthoringProof','-Phase=gateway','-unattended','-nop4','-nosplash','-NullRHI','-NoSound','-NoShaderCompile','-stdout','-FullStdOutLogOutput',f'-abslog={logs/f"{i:03}-editor.log"}']
        (logs/f'{i:03}-command.json').write_bytes(encode(dict(argv=argv,request=command,executable_sha256=self.identity['editor_sha256'])))
        p=subprocess.run(argv,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=240,creationflags=subprocess.CREATE_NO_WINDOW)
        (logs/f'{i:03}-process.log').write_bytes(p.stdout)
        result=load_json(previous);(logs/f'{i:03}-result.json').write_bytes(encode(result))
        assert p.returncode==0 and result['ok'],(action,result)
        return result['result']
    def capture(self):return encode(self.invoke('capture'))
    def prepare(self,transaction_id,request):
        prepared=self.invoke('prepare',transaction_id=sha(transaction_id.encode())[:32],request=request['write_request'])
        files=[p for folder in ['Content','Config','Plugins'] for p in (self.root/folder).rglob('*') if p.is_file()]
        prepared['dependency_hashes']={p.relative_to(self.root).as_posix():sha(p.read_bytes()) for p in files if p.relative_to(self.root).as_posix()!='Content/Fixture/World.umap'}
        return prepared
    def inspect(self,prepared):
        if any(not (self.root/p).is_file() or sha((self.root/p).read_bytes())!=h for p,h in prepared['dependency_hashes'].items()):return 'conflict'
        receipt=prepared['receipt'];directory=Path(prepared['directory'])
        if sha((directory/'before.umap').read_bytes())!=receipt['before'] or sha((directory/'staged.umap').read_bytes())!=receipt['after']:return 'conflict'
        value=sha((self.root/'Content/Fixture/World.umap').read_bytes())
        return 'after' if value==receipt['after'] else 'before' if value==receipt['before'] else 'conflict'
    def commit(self,prepared):return self.invoke('commit',prepared=prepared)
    def recover(self,prepared):return self.invoke('recover',prepared=prepared)


def build(out):
    gateway=Gateway(out);root=gateway.root;saved=load_json(out/'context.json')
    mapping=IdentityMap.from_dict(saved['mapping']);baseline=Snapshot(encode(saved['baseline']))
    ctx=dict(baseline=baseline,baseline_cgs=saved['baseline_cgs'],mapping=mapping,current_mapping=copy.deepcopy(mapping),
             current_cgs=saved['current_cgs'],native_inventory=encode(saved['native']),expected_current_cgs_digest=digest(saved['current_cgs']),
             expected_source_digest=sha(encode(saved['native'])),verify_baseline=lambda b:b==mapping.baseline,trusted_project=True)
    proposal=plan_reconciliation(**ctx);report=proposal.to_dict()
    # Native-only opaque refresh no longer masquerades as a CGS structural edit.
    # Publication still requires exact fresh saved readback; do not relax it.
    assert report['reviewable'],report['losses']
    (out/'reviewed-reconciliation.json').write_bytes(proposal.payload)
    if (out/'prepared.json').exists():prepared=load_json(out/'prepared.json')
    else:
        prepared=prepare_apply(proposal,context=ctx,transaction_id='unreal-main',project_root=root)
        (out/'prepared.json').write_bytes(encode(prepared))
    pair=SavedPair(root,mapping=IdentityMap.from_dict(prepared['target_mapping']),expected_cgs=prepared['cgs']['cgs'],expected_normalized=prepared['expected_normalized'],recapture=gateway.capture)
    c=AuthoringCoordinator(root,dict(canonical=FileParticipant(root,name='canonical',allowed_paths=['game.cgs.json']),native=NativeParticipant(gateway)),verify_pair=pair.verify,baseline_participant=pair.participant,baseline_request=pair.baseline_request)
    request=TransactionRequest('unreal-main',proposal.sha256,dict(canonical=prepared['canonical_request'],native=dict(write_request=prepared['native_request'])),ACTIVATION,dict(mapping=prepared['target_mapping'],cgs_digest=digest(prepared['cgs']['cgs']),normalized_digest=digest(prepared['expected_normalized'])))
    return c,prepared,request


def main(out):
    assert out.resolve().is_relative_to(ROOT/'evidence/nec010/ue') and not out.exists();out.mkdir(parents=True)
    root=out/'unreal-project';root.mkdir();(root/'.xace').mkdir()
    source=ROOT/'evidence/nec010/ue/c/unreal-project'
    for folder in ['Content','Config']:shutil.copytree(source/folder,root/folder)
    shutil.copytree(ROOT/'evidence/nec010/ue/d/unreal-project/Plugins',root/'Plugins',ignore=shutil.ignore_patterns('Intermediate'))
    shutil.copyfile(source/'NEC006.uproject',root/'NEC006.uproject')
    for marker in ['NEC006.fixture','NEC010.fixture']:(root/marker).write_text('Explicit isolated native materialization fixture')
    gateway=Gateway(out);data=gateway.capture();mapping=reader.prepare_identity_map(data,project_id='nec010-unreal',branch_id='b'*32)
    prior=load_json(ROOT/'recovery-evidence/20261016/nec007/native-runtime/unreal/plan.json');cgs=prior['proposed_cgs'];key=prior['selected'][0]
    aid='native_'+mapping.namespace_id+'_'+key;mapping.objects[key].world_binding=WorldBinding(aid,aid,0)
    baseline=reader.capture(data,mapping,enable_writes=True).admit();position=baseline.to_dict()['inspection']['normalized'][key]['fields']['transform.position']
    transform=cgs['modes'][0]['actors'][0]['components'][0]['defaults'];transform['position']={k:int(v) for k,v in position.items()};rehash(cgs)
    mapping.baseline=Baseline(digest(cgs),baseline.sha256,mapping.mapping_digest(),'nec009-proof-entry-fixture','a'*64,'b'*64)
    # An explicit independent native Y edit, using the installed editor writer.
    raw=json.loads(data);value=copy.deepcopy(position);value['y']=str(int(value['y'])+2000000)
    request=dict(schema='xace.unreal_authoring_write_request.v1',expected_inventory_digest=digest(raw),edits=[dict(document=raw['objects'][key]['path_hint'],authoring_id=key,fields={'transform.position':value})])
    staged=gateway.prepare('native-independent-y',dict(write_request=request));gateway.commit(staged)
    observed=gateway.capture();current=copy.deepcopy(cgs);current['modes'][0]['actors'][0]['components'][0]['defaults']['position']['x']+=1000000;rehash(current)
    (root/'game.cgs.json').write_bytes(encode(current))
    (out/'context.json').write_bytes(encode(dict(mapping=mapping.to_dict(),baseline=baseline.to_dict(),baseline_cgs=cgs,current_cgs=current,native=json.loads(observed))))
    child=subprocess.run([sys.executable,__file__,'--crash',str(out)],cwd=ROOT,capture_output=True)
    (out/'crash-child.log').write_bytes(child.stdout+child.stderr);assert child.returncode==73,child.stderr
    coordinator,prepared,_=build(out);assert coordinator.status()['play_build_blocked']
    result=coordinator.recover('unreal-main');assert result['state']=='committed'
    recovered_mapping=IdentityMap.from_dict(load_json(root/MAP))
    assert verify_baseline_receipts(root,recovered_mapping.baseline)
    assert coordinator.recover('unreal-main')==result
    assert not coordinator.status()['play_build_blocked']
    from authoring_saved_pair import CGS,NATIVE
    cycles=[]
    for cycle in range(2):
        mapping=IdentityMap.from_dict(load_json(root/MAP))
        current=load_json(root/'game.cgs.json')
        context=dict(baseline=Snapshot((root/NATIVE).read_bytes()),baseline_cgs=load_json(root/CGS),mapping=mapping,
            current_mapping=copy.deepcopy(mapping),current_cgs=current,native_inventory=gateway.capture(),
            expected_current_cgs_digest=digest(current),verify_baseline=lambda b:verify_baseline_receipts(root,b),trusted_project=True)
        context['expected_source_digest']=sha(context['native_inventory'])
        no_op=plan_reconciliation(**context).to_dict();assert no_op['reviewable'] and no_op['noop'],no_op['losses']
        before={p.relative_to(root).as_posix():sha(p.read_bytes()) for p in (root/'Content/Fixture').iterdir() if p.is_file()}
        assert plan_reconciliation(**context).to_dict()['noop']
        assert before=={p.relative_to(root).as_posix():sha(p.read_bytes()) for p in (root/'Content/Fixture').iterdir() if p.is_file()}
        current['modes'][0]['actors'][0]['components'][0]['defaults']['position']['x']+=1000000
        rehash(current);(root/'game.cgs.json').write_bytes(encode(current));context['expected_current_cgs_digest']=digest(current)
        proposal=plan_reconciliation(**context);assert proposal.to_dict()['reviewable']
        tx='unreal-cycle-'+str(cycle)
        prepared=prepare_apply(proposal,context=context,transaction_id=tx,project_root=root)
        pair=SavedPair(root,mapping=IdentityMap.from_dict(prepared['target_mapping']),expected_cgs=prepared['cgs']['cgs'],expected_normalized=prepared['expected_normalized'],recapture=gateway.capture)
        coordinator=AuthoringCoordinator(root,dict(canonical=FileParticipant(root,name='canonical',allowed_paths=['game.cgs.json']),native=NativeParticipant(gateway)),verify_pair=pair.verify,baseline_participant=pair.participant,baseline_request=pair.baseline_request)
        def fresh():
            context['native_inventory']=gateway.capture();context['expected_source_digest']=sha(context['native_inventory'])
            return prepare_apply(proposal,context=context,transaction_id=tx,project_root=root)
        result=apply_prepared(coordinator,prepared,transaction_id=tx,native_participant_request=dict(write_request=prepared['native_request']),authorize=lambda r:True,refresh_preparation=fresh)
        assert result['state']=='committed'
        cycles.append(dict(cycle=str(cycle),committed=True,cold_editor_reopens=True,no_op_stable=True))
    (out/'cycles.json').write_bytes(encode(dict(ok=True,cycles=cycles)))
    (out/'proof.json').write_bytes(encode(dict(schema='xace.nec010.unreal_materialization.v1',ok=True,real_editor=True,real_native_save=True,process_exit=73,recovered='committed',baseline_verified=True,idempotent_recovery=True,runtime_activation=False,scope='Bound root transform; complete NEC010 all-engine acceptance still pending')))
    print((out/'proof.json').read_text())


if __name__=='__main__':
    if sys.argv[1]=='--crash':
        out=Path(sys.argv[2]);c,p,request=build(out)
        def crash(event):
            if event=='published_before_receipt:canonical':os._exit(73)
        c.checkpoint=crash
        c.commit(request,authorize=lambda r:True)
    else:main(Path(sys.argv[1]).resolve())
