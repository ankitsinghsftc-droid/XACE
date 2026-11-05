"""Native-capture-derived adoption gate; never publishes files to source project."""
from pathlib import Path
import json,sys,hashlib
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'packages/project-system'),str(ROOT/'packages/project-system/tests')]
from test_native_adoption import inputs,choices_for,plan
from authoring_identity import canonical
import unreal_authoring as reader
out=Path(sys.argv[1]).resolve();source=Path(sys.argv[2]).resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists();assert source.is_relative_to(ROOT/'evidence/nec017');out.mkdir(parents=True)
p=source/'project/.xace/existing-enrolled.json';raw=p.read_bytes();inventory=json.loads(raw)
mapping=reader.prepare_identity_map(raw,project_id='nec017-existing',branch_id='b'*32)
selected=sorted(k for k,r in inventory['objects'].items() if r['name'] in ['Crate'+str(i) for i in range(50)]);assert len(selected)==50
choices=choices_for(selected)
for k in selected:choices['objects'][k]['asset_role']='project.visual.v1'
cgs=inputs('unreal')[2];before=canonical(cgs);proposal=plan(raw,mapping,cgs,selected,choices);report=proposal.to_dict();(out/'adoption-review.json').write_bytes(proposal.payload)
expected='--expect-supported' in sys.argv
assert report['candidate_valid']==expected,report['losses']
assert report['saved_pair_eligible']==expected,report['saved_pair_losses']
assert canonical(cgs)==before and p.read_bytes()==raw
result=dict(ok=True,selected_objects=50,actual_native_enrolled_objects=len(inventory['objects']),candidate_valid=report['candidate_valid'],saved_pair_eligible=report['saved_pair_eligible'],source_inventory_sha256=hashlib.sha256(raw).hexdigest(),source_and_cgs_preserved=True,full_adoption_verified=False,expected_scope='Explicitly disposed static fixture copy' if expected else 'Original native collision and critical behavior must be refused',loss_codes=sorted(set(r['code'] for r in report['losses'])))
(out/'proof.json').write_bytes(canonical(result));print(json.dumps(result))
