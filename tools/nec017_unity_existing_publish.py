"""Publish an explicitly disposed original Unity fixture through GDE/coordinator.
Static hierarchy only; this does not translate removed native gameplay.
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
import unity_authoring as reader
from native_instance_transforms import PROFILE

def sha(data):return hashlib.sha256(data).hexdigest()
def load(path):return json.loads(path.read_bytes())
def main(out,source):
 out=out.resolve();source=source.resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists();assert source.is_relative_to(ROOT/'evidence/nec017')
 root=out/'project';root.mkdir(parents=True)
 before={p.relative_to(source/'project').as_posix():sha(p.read_bytes()) for folder in ['Assets','Packages','ProjectSettings'] for p in (source/'project'/folder).rglob('*') if p.is_file()}
 for name in before:
  dest=root/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/'project'/name,dest)
 # Explicitly upgrade only the copied authoring plugin to the tested current source.
 for current in (ROOT/'adapters/unity/Authoring').rglob('*'):
  if current.is_file():
   dest=root/'Assets/XaceAuthoring'/current.relative_to(ROOT/'adapters/unity/Authoring');dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(current,dest)
 (out/'source-pins.json').write_bytes(canonical({p.relative_to(ROOT).as_posix():sha(p.read_bytes()) for p in [Path(__file__),*sorted((ROOT/'adapters/unity/Authoring').rglob('*.cs'))]}))
 pins={p.relative_to(root).as_posix():sha(p.read_bytes()) for p in (root/'Assets/XaceAuthoring').rglob('*') if p.is_file() and p.suffix in ['.cs','.asmdef']}
 exe=Path('C:/Program Files/Unity/Hub/Editor/6000.4.9f1/Editor/Unity.exe')
 gateway=NativeEditorGateway(root,engine='unity',executable=str(exe),executable_sha256=sha(exe.read_bytes()),documents=['Assets/Game/Crate.prefab','Assets/Game/World.unity','Assets/Game/Annex.unity'],source_roots=['Assets','Packages','ProjectSettings'],plugin_hashes=pins,trusted_closed_project=True)
 raw=gateway.capture();mapping=reader.prepare_identity_map(raw,project_id='nec017-existing',branch_id='b'*32)
 enrollment=load(source/'project/existing-enrollment.json')
 selected=sorted(r['id'] for r in enrollment['objects'] if r['document']=='Assets/Game/World.unity' and r['path'] in ['Warehouse']+['Warehouse/Crate'+str(n) for n in range(50)]);assert len(selected)==51
 choices=choices_for(selected)
 inventory=json.loads(raw)
 for key in selected:
  fields=inventory['objects'][key]['fields'];choice=choices['objects'][key]
  if 'presentation.asset' in fields:choice['asset_role']='project.visual.v1'
  if 'presentation.material' in fields:choice['material_role']='project.material.v1'
 cgs=inputs('unity')[2];cgs['native_instance_profile']=PROFILE;rehash(cgs);(root/'game.cgs.json').write_bytes(canonical(cgs))
 def adoption_context():
  raw=gateway.capture()
  return dict(native_inventory=raw,mapping=mapping,current_cgs=load(root/'game.cgs.json'),selection=selected,choices=choices,expected_source_digest=sha(raw),expected_cgs_digest=digest(load(root/'game.cgs.json')),trusted_project=True)
 context=adoption_context();proposal=plan(context['native_inventory'],mapping,cgs,selected,choices);report=proposal.to_dict();assert report['candidate_valid'] and report['saved_pair_eligible'],report['saved_pair_losses']
 (out/'adoption-review.json').write_bytes(proposal.payload)
 # Rejecting this preview performs no canonical/native publication.
 saved_native={p:sha((root/p).read_bytes()) for p in before if p.startswith('Assets/Game/')}
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
 assert len(load(root/'game.cgs.json')['modes'][0]['actors'])==51
 def current_context():
  m=IdentityMap.from_dict(load(root/MAP));cgs=load(root/'game.cgs.json');raw=gateway.capture()
  return dict(baseline=Snapshot((root/NATIVE).read_bytes()),baseline_cgs=load(root/CGS),mapping=m,current_mapping=copy.deepcopy(m),current_cgs=cgs,native_inventory=raw,expected_current_cgs_digest=digest(cgs),expected_source_digest=sha(raw),verify_baseline=lambda b:verify_baseline_receipts(root,b),trusted_project=True)
 reopened=NativeMaterializationHost(root,current_context,gateway).review.open('nec017-fixture-owner');assert reopened['report']['noop'] and reopened['report']['reviewable'],reopened['report']['losses']
 assert all(sha((source/'project'/p).read_bytes())==h for p,h in before.items())
 (out/'proof.json').write_bytes(canonical(dict(ok=True,objects=51,actual_native_enrollment=len(enrollment['objects']),original_enrolled_project_unchanged=True,native_documents_unchanged_by_adoption=True,real_native_capture=True,gde_coordinator_saved_pair=True,reopened_noop=True,manual_native_disposition_required=True,scope='Explicitly disposed static hierarchy; no automatic gameplay/physics conversion or Play/build certification',play_build_continuity_verified=False)))
 print((out/'proof.json').read_text(),flush=True)
 if '--edits' in sys.argv:
  chosen=next(r['id'] for r in enrollment['objects'] if r['document']=='Assets/Game/World.unity' and r['path']=='Warehouse/Crate0')
  actor=IdentityMap.from_dict(load(root/MAP)).objects[chosen].world_binding.actor_id
  cgs=load(root/'game.cgs.json');next(a for a in cgs['modes'][0]['actors'] if a['id']==actor)['components'][0]['defaults']['position']['x']=17000000;rehash(cgs);(root/'game.cgs.json').write_bytes(canonical(cgs))
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
  assert all(sha((root/p).read_bytes())==h for p,h in saved_native.items() if p!='Assets/Game/World.unity')
  (out/'editing-proof.json').write_bytes(canonical(dict(ok=True,objects=51,canonical_to_native=True,native_to_canonical=True,reopened_noop=True,original_source_preserved=True,prefab_resources_and_other_scene_preserved=True,play_build_continuity_verified=False)))
  print((out/'editing-proof.json').read_text(),flush=True)

if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]))
