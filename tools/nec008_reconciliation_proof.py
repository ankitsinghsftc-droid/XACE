"""Real capture-derived B/X/E proposal proof; never commits/native-saves."""
import argparse,copy,hashlib,importlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system')]
from authoring_identity import Baseline,WorldBinding,canonical
from native_adoption import digest,encode
from native_reconciliation_plan import plan_reconciliation,_native_transform
from native_reconciliation_review import ReconciliationReview
from tools.world_extensibility_proof import rehash

def write(path,value):path.write_bytes(encode(value))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    out=args.out.resolve();assert out.is_relative_to(ROOT/'recovery-evidence/20261016/nec008') and not out.exists();out.mkdir(parents=True)
    provenance=json.loads((ROOT/'packages/project-system/tests/fixtures/nec007/provenance.json').read_text());results={}
    for engine in ['unity','godot','unreal']:
        folder=out/engine;folder.mkdir()
        path=ROOT/'packages/project-system/tests/fixtures/nec007'/f'{engine}.json';data=path.read_bytes();assert sha(path)==provenance[engine]['sha256']==sha(ROOT/provenance[engine]['source'])
        previous=json.loads((ROOT/f'recovery-evidence/20261016/nec007/native-runtime/{engine}/plan.json').read_text());cgs=previous['proposed_cgs'];selected=previous['selected']
        reader=importlib.import_module(engine+'_authoring');mapping=reader.prepare_identity_map(data,project_id='nec008-'+engine,branch_id='b'*32)
        for key in selected:
            aid='native_'+mapping.namespace_id+'_'+key;mapping.objects[key].world_binding=WorldBinding(aid,aid,0)
        baseline=reader.capture(data,mapping,enable_writes=True).admit()
        write(folder/'baseline-cgs.json',cgs);(folder/'baseline-native.json').write_bytes(baseline.payload)
        canonical_receipt=dict(schema='nec008.proof_fixture_receipt.v1',store='canonical',sha256=sha(folder/'baseline-cgs.json'))
        native_receipt=dict(schema='nec008.proof_fixture_receipt.v1',store='native',sha256=sha(folder/'baseline-native.json'))
        write(folder/'canonical-receipt.json',canonical_receipt);write(folder/'native-receipt.json',native_receipt)
        mapping.baseline=Baseline(digest(cgs),baseline.sha256,mapping.mapping_digest(),'nec008-proof-fixture',digest(canonical_receipt),digest(native_receipt))
        saved=copy.deepcopy(mapping.baseline)
        def verify(b):return b==saved and digest(json.loads((folder/'canonical-receipt.json').read_text()))==b.canonical_receipt and digest(json.loads((folder/'native-receipt.json').read_text()))==b.native_receipt and sha(folder/'baseline-cgs.json')==canonical_receipt['sha256'] and sha(folder/'baseline-native.json')==native_receipt['sha256']
        current=copy.deepcopy(cgs);current['modes'][0]['actors'][0]['components'][0]['defaults']['position']['x']+=1000000;rehash(current)
        observed=json.loads(data);native_position=copy.deepcopy(baseline.to_dict()['inspection']['normalized'][selected[0]]['fields']['transform.position']);native_position['y']=str(int(native_position['y'])+2000000)
        observed['objects'][selected[0]]['fields']['transform.position']=_native_transform(engine,'transform.position',native_position)
        for document in observed['source']['documents']:document['before']=document['after']='c'*64
        edited=canonical(observed)
        context=dict(baseline=baseline,baseline_cgs=cgs,mapping=mapping,current_mapping=copy.deepcopy(mapping),current_cgs=current,native_inventory=edited,expected_current_cgs_digest=digest(current),expected_source_digest=hashlib.sha256(edited).hexdigest(),verify_baseline=verify,trusted_project=True)
        immutable=encode([mapping.to_dict(),current,cgs]);result=plan_reconciliation(**context);report=result.to_dict();assert report['reviewable'],report['losses']
        assert plan_reconciliation(**context)==result and immutable==encode([mapping.to_dict(),current,cgs])
        write(folder/'disjoint-plan.json',report);write(folder/'mapping.json',mapping.to_dict());write(folder/'current-cgs.json',current);(folder/'edited-native-capture.json').write_bytes(edited)
        merged=report['proposed_cgs'];assert merged['modes'][0]['actors'][0]['components'][0]['defaults']['position']['x']==current['modes'][0]['actors'][0]['components'][0]['defaults']['position']['x']
        assert merged['modes'][0]['actors'][0]['components'][0]['defaults']['position']['y']==int(native_position['y'])
        service=ReconciliationReview(lambda:context);opened=service.open('proof-operator');approval=service.approve('proof-operator',opened['token'],opened['proposal_digest']);assert service.verify_approval('proof-operator',approval)==result
        write(folder/'approval.json',approval)
        native_position['x']=str(int(native_position['x'])+3000000);observed['objects'][selected[0]]['fields']['transform.position']=_native_transform(engine,'transform.position',native_position)
        context['native_inventory']=canonical(observed);context['expected_source_digest']=hashlib.sha256(context['native_inventory']).hexdigest()
        try:service.verify_approval('proof-operator',approval)
        except ValueError:pass
        else:raise AssertionError('stale approval accepted')
        conflicted=plan_reconciliation(**context).to_dict();assert not conflicted['reviewable'];write(folder/'conflict-plan.json',conflicted)
        resolutions={c['id']:'engine' for c in conflicted['merge']['conflicts']};resolved=plan_reconciliation(**context,resolutions=resolutions).to_dict();assert resolved['reviewable'];write(folder/'resolved-plan.json',resolved)
        assert sha(path)==provenance[engine]['sha256']==sha(ROOT/provenance[engine]['source'])
        results[engine]=dict(ok=True,capture=provenance[engine],captured_objects=len(observed['objects']),bound_objects=len(selected),disjoint_fields_preserved=True,conflict_preserves_versions=True,explicit_resolution_validated=True,stale_approval_rejected=True,source_and_baseline_unchanged=True)
    proof=dict(schema='xace.nec008.reconciliation_proof.v1',ok=True,engines=results,commit_performed=False,native_editor_launched=False,baseline_receipts='Isolated fixture receipts; not a NEC-009 durable transaction certification')
    write(out/'proof.json',proof);print(json.dumps(proof,indent=2))

if __name__=='__main__':main()
