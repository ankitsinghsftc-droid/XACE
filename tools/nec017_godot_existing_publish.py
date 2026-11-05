"""Publish explicit 50-instance adoption through GDE and the real coordinator.
Only copies NEC017 test fixtures. Original native gameplay removal is a separate,
retained manual test disposition, never an automatic migration claim.
"""
from pathlib import Path
import sys,copy,json,shutil,hashlib
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'packages/project-system'),str(ROOT/'packages/project-system/tests')]
from test_native_adoption import inputs,choices_for,plan
from authoring_identity import canonical,IdentityMap
from authoring_apply import prepare_apply,apply_prepared
from authoring_saved_pair import SavedPair,MAP,CGS,NATIVE,verify_baseline_receipts
from native_materialization import NativeMaterializationHost
from native_editor_gateway import NativeEditorGateway
from native_authoring_contract import Snapshot
from native_adoption import digest
from tools.world_extensibility_proof import rehash
import godot_authoring as reader

def sha(data):return hashlib.sha256(data).hexdigest()
def load(path):return json.loads(path.read_bytes())
def main(out,source):
 out=out.resolve();source=source.resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists();assert source.is_relative_to(ROOT/'evidence/nec017')
 root=out/'project';root.mkdir(parents=True)
 before={p.relative_to(source/'project').as_posix():sha(p.read_bytes()) for p in (source/'project').rglob('*') if p.is_file() and '.godot' not in p.parts}
 for name in before:
  dest=root/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/'project'/name,dest)
 config=root/'addons/xace_authoring/plugin.cfg';config.write_text(config.read_text().replace('script="existing_enroll.gd"','script="authoring_plugin.gd"'))
 pins={p.relative_to(root).as_posix():sha(p.read_bytes()) for p in (root/'addons').rglob('*') if p.is_file() and p.suffix!='.uid'}
 exe=Path('C:/Users/ankit/Downloads/Godot_v4.6.3-stable_win64.exe/Godot_v4.6.3-stable_win64_console.exe')
 gateway=NativeEditorGateway(root,engine='godot',executable=str(exe),executable_sha256=sha(exe.read_bytes()),documents=['res://Game/Crate.tscn','res://Game/World.tscn','res://Game/Annex.tscn'],source_roots=['Game','addons','project.godot','xace_protocol.gd'],plugin_hashes=pins,trusted_closed_project=True)
 raw=gateway.capture();mapping=reader.prepare_identity_map(raw,project_id='nec017-existing',branch_id='b'*32)
 enrollment=load(root/'existing-enrollment.json')
 selected=sorted(r['id'] for r in enrollment['objects'] if r['document']=='res://Game/World.tscn' and r['node_path'] in ['Crate'+str(n) for n in range(50)]);assert len(selected)==50
 choices=choices_for(selected)
 for key in selected:
  choices['objects'][key]['asset_role']='project.visual.v1'
  if 'presentation.material' in json.loads(raw)['objects'][key]['fields']:
   choices['objects'][key]['material_role']='project.material.v1'
 cgs=inputs('godot')[2];(root/'game.cgs.json').write_bytes(canonical(cgs))
 def adoption_context():
  raw=gateway.capture()
  return dict(native_inventory=raw,mapping=mapping,current_cgs=load(root/'game.cgs.json'),selection=selected,choices=choices,expected_source_digest=sha(raw),expected_cgs_digest=digest(load(root/'game.cgs.json')),trusted_project=True)
 context=adoption_context();proposal=plan(context['native_inventory'],mapping,cgs,selected,choices);report=proposal.to_dict();assert report['candidate_valid'] and report['saved_pair_eligible'],report['saved_pair_losses']
 (out/'adoption-review.json').write_bytes(proposal.payload)
 # Rejecting this preview performs no canonical/native publication.
 saved_native={p:sha((root/p).read_bytes()) for p in before if p.startswith('Game/')}
 assert load(root/'game.cgs.json')==cgs
 approval=dict(principal='nec017-fixture-owner',proposal_digest=proposal.sha256,action='approve_adoption_after_explicit_native_disposition')
 (out/'explicit-approval.json').write_bytes(canonical(approval))
 def fresh():return prepare_apply(proposal,context=adoption_context(),transaction_id='existing-adoption',project_root=root)
 prepared=fresh();pair=SavedPair(root,mapping=IdentityMap.from_dict(prepared['target_mapping']),expected_cgs=prepared['cgs']['cgs'],expected_normalized=prepared['expected_normalized'],recapture=gateway.capture)
 host=NativeMaterializationHost(root,lambda:None,gateway)
 result=apply_prepared(host._coordinator(pair),prepared,transaction_id='existing-adoption',native_participant_request=dict(write_request=prepared['native_request']),authorize=lambda request:request.proposal_digest==approval['proposal_digest'],refresh_preparation=fresh)
 assert result['state']=='committed',result
 assert all(sha((root/p).read_bytes())==h for p,h in saved_native.items())
 m=IdentityMap.from_dict(load(root/MAP));assert verify_baseline_receipts(root,m.baseline)
 assert len(load(root/'game.cgs.json')['modes'][0]['actors'])==50
 def current_context():
  m=IdentityMap.from_dict(load(root/MAP));cgs=load(root/'game.cgs.json');raw=gateway.capture()
  return dict(baseline=Snapshot((root/NATIVE).read_bytes()),baseline_cgs=load(root/CGS),mapping=m,current_mapping=copy.deepcopy(m),current_cgs=cgs,native_inventory=raw,expected_current_cgs_digest=digest(cgs),expected_source_digest=sha(raw),verify_baseline=lambda b:verify_baseline_receipts(root,b),trusted_project=True)
 reopened=NativeMaterializationHost(root,current_context,gateway).review.open('nec017-fixture-owner');assert reopened['report']['noop'] and reopened['report']['reviewable'],reopened['report']['losses']
 assert all(sha((source/'project'/p).read_bytes())==h for p,h in before.items())
 (out/'proof.json').write_bytes(canonical(dict(ok=True,objects=50,actual_native_enrollment=58,original_enrolled_project_unchanged=True,native_documents_unchanged_by_adoption=True,real_native_capture=True,gde_coordinator_saved_pair=True,reopened_noop=True,manual_native_disposition_required=True,play_build_continuity_verified=False)))
 print((out/'proof.json').read_text(),flush=True)
 if '--edits' in sys.argv:
  actor=load(root/'game.cgs.json')['modes'][0]['actors'][0]['id']
  cgs=load(root/'game.cgs.json');cgs['modes'][0]['actors'][0]['components'][0]['defaults']['position']['x']=17000000;rehash(cgs);(root/'game.cgs.json').write_bytes(canonical(cgs))
  def approve_apply():
   host=NativeMaterializationHost(root,current_context,gateway);opened=host.review.open('nec017-fixture-owner');assert opened['report']['reviewable'],opened['report']['losses']
   approval=host.review.approve('nec017-fixture-owner',opened['token'],opened['proposal_digest'])
   assert host.apply('nec017-fixture-owner',approval,approval['proposal_digest'])['state']=='committed'
  approve_apply()
  m=IdentityMap.from_dict(load(root/MAP));key=next(k for k,r in m.objects.items() if r.world_binding and r.world_binding.actor_id==actor)
  raw=gateway.capture();assert json.loads(raw)['objects'][key]['fields']['transform.position']['x']=='17'
  baseline=reader.capture(raw,m,enable_writes=True).admit();target=json.loads(raw);target['objects'][key]['fields']['transform.position']['x']='18'
  desired=reader.capture(canonical(target),m,enable_writes=True).admit()
  native=gateway.prepare('existing-native-edit',dict(write_request=json.loads(reader.write_request(raw,baseline,desired,m))));gateway.commit(native)
  approve_apply()
  final=load(root/'game.cgs.json');assert next(a for a in final['modes'][0]['actors'] if a['id']==actor)['components'][0]['defaults']['position']['x']==18000000
  last=NativeMaterializationHost(root,current_context,gateway).review.open('nec017-fixture-owner');assert last['report']['noop'] and last['report']['reviewable']
  assert all(sha((source/'project'/p).read_bytes())==h for p,h in before.items())
  assert all(sha((root/p).read_bytes())==h for p,h in saved_native.items() if p!='Game/World.tscn')
  (out/'editing-proof.json').write_bytes(canonical(dict(ok=True,objects=50,canonical_to_native=True,native_to_canonical=True,reopened_noop=True,original_source_preserved=True,prefab_resources_and_other_scene_preserved=True,play_build_continuity_verified=False)))
  print((out/'editing-proof.json').read_text(),flush=True)

if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]))
