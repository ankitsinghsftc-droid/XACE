"""Independent Godot project adoption preview and unsupported-code refusal."""
from pathlib import Path
import sys,json,hashlib,copy
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'packages/project-system'),str(ROOT/'packages/project-system/tests')]
from test_native_adoption import inputs,choices_for,plan
import godot_authoring as reader
from authoring_identity import canonical
out=Path(sys.argv[1]).resolve();source=Path(sys.argv[2]).resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists();assert source.is_relative_to(ROOT/'evidence/nec017');out.mkdir(parents=True)
raw=(source/'project/existing-native.json').read_bytes();enrollment=json.loads((source/'project/existing-enrollment.json').read_bytes());mapping=reader.prepare_identity_map(raw,project_id='nec017-existing',branch_id='b'*32)
selected=sorted(row['id'] for row in enrollment['objects'] if row['document']=='res://Game/World.tscn' and row['node_path'] in ['Crate'+str(n) for n in range(50)]);assert len(selected)==50
choices=choices_for(selected)
for key in selected:choices['objects'][key]['asset_role']='project.visual.v1'
cgs=inputs('godot')[2];before=canonical(cgs);approved=plan(raw,mapping,cgs,selected,choices).to_dict();(out/'supported-preview.json').write_bytes(canonical(approved));assert approved['candidate_valid'],approved['losses'];assert canonical(cgs)==before
critical=next(row['id'] for row in enrollment['objects'] if row['node_path']=='UnsupportedCriticalScore');blocked=plan(raw,mapping,cgs,[critical],choices_for([critical])).to_dict();(out/'unsupported-preview.json').write_bytes(canonical(blocked));assert not blocked['candidate_valid'] and not blocked['play_eligible'];assert any(row['severity']=='blocking' for row in blocked['losses'])
assert (source/'project/existing-native.json').read_bytes()==raw
result=dict(ok=True,selected_objects=50,actual_native_enrolled_objects=len(enrollment['objects']),source_inventory_sha256=hashlib.sha256(raw).hexdigest(),preview_preserves_source_and_cgs=True,supported_preview_valid=True,unsupported_critical_script_refused=True,scope='Preview only; no saved-pair commit, native Play, build or continuity certification')
(out/'proof.json').write_bytes(canonical(result));print(json.dumps(result))
