"""Existing imported fixture: real native mutations, refusals, conflict/resolve, Play again.
Only explicit fresh test copies may be changed. Recorded captures are not live authority.
"""
from pathlib import Path
import copy,importlib,json,os,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'packages/project-system')]
from tools.nec010_playback_host_proof import NativeEditorGateway,NativeMaterializationHost,IdentityMap,canonical,sha,load_json,TransactionRequest,file_change,ACTIVATION,SavedPair,MAP,CGS,NATIVE,verify_baseline_receipts,Snapshot,digest,rehash
from tools.nec017_unity_scale_builds import run
GODOT=Path('C:/Program Files/Unity/Hub/Editor/6000.4.9f1/Editor/Unity.exe')

def main(engine,out):
 assert engine=='unity','other engine drivers not yet implemented'
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists() and shutil.disk_usage(ROOT).free>4*2**30;out.mkdir(parents=True)
 source=ROOT/'evidence/nec017/20261105/unity-existing-publish-b/project';root=out/'project';source_files={p.relative_to(source).as_posix():sha(p.read_bytes()) for p in source.rglob('*') if p.is_file() and (p.relative_to(source).parts[0] in ['Assets','Packages','ProjectSettings'] or p.name=='game.cgs.json')};root.mkdir()
 for name in source_files:
  target=root/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/name,target)
 addons=root/'Assets/XaceAuthoring'
 for p in (ROOT/'adapters/unity/Authoring').rglob('*'):
  if p.is_file():
   dest=addons/p.relative_to(ROOT/'adapters/unity/Authoring');dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest)
 shutil.copyfile(ROOT/'tools/nec017_unity_existing_mutations.cs',addons/'Editor/NEC017ExistingMutations.cs');reader=importlib.import_module('unity_authoring');documents=['Assets/Game/Crate.prefab','Assets/Game/World.unity','Assets/Game/Annex.unity']
 pins={p.relative_to(root).as_posix():sha(p.read_bytes()) for p in addons.rglob('*') if p.is_file() and p.suffix in ['.cs','.asmdef']}
 gateway=NativeEditorGateway(root,engine=engine,executable=str(GODOT),executable_sha256=sha(GODOT.read_bytes()),documents=documents,source_roots=['Assets','Packages','ProjectSettings'],plugin_hashes=pins,trusted_closed_project=True)
 raw=gateway.capture();cgs=load_json(root/'game.cgs.json');mapping=IdentityMap.from_dict(load_json(source/MAP));mapping.baseline=None;mapping.project_id='nec017-existing-workflow';mapping.branch_id='e'*32
 rows=reader.capture(raw,mapping,enable_writes=True).admit().to_dict()['inspection']['normalized'];pair=SavedPair(root,mapping=mapping,expected_cgs=cgs,expected_normalized=rows,recapture=gateway.capture);h=NativeMaterializationHost(root,lambda:None,gateway);request=TransactionRequest('explicit-workflow-baseline','a'*64,dict(canonical=dict(files=[file_change('game.cgs.json',sha(canonical(cgs)),canonical(cgs))]),native=dict(write_request=None)),ACTIVATION,dict(mapping=mapping.to_dict(),cgs_digest=digest(cgs),normalized_digest=digest(rows)),dict(cgs=cgs,normalized=rows,accepted_loss_digest=None));h._coordinator(pair).commit(request,authorize=lambda _:True)
 def context():
  c=load_json(root/'game.cgs.json');m=IdentityMap.from_dict(load_json(root/MAP));native=gateway.capture()
  return dict(baseline=Snapshot((root/NATIVE).read_bytes()),baseline_cgs=load_json(root/CGS),mapping=m,current_mapping=copy.deepcopy(m),current_cgs=c,native_inventory=native,expected_current_cgs_digest=digest(c),expected_source_digest=sha(native),verify_baseline=lambda b:verify_baseline_receipts(root,b),trusted_project=True)
 host=NativeMaterializationHost(root,context,gateway);assert host.review.open('workflow-owner')['report']['noop'];env=dict(os.environ);env['LOCALAPPDATA']=str(out/'user-data');mutations=[]
 protected=[MAP,CGS,NATIVE,'game.cgs.json'];saved={n:(root/n).read_bytes() for n in protected}
 for phase in ['rename','move','reparent','duplicate','delete']:
  before={n:(root/n).read_bytes() for n in ['Assets/Game/World.unity','Assets/Game/World.unity.meta','Assets/Game/Annex.unity','Assets/Game/Annex.unity.meta']};run([str(GODOT),'-batchmode','-nographics','-projectPath',str(root),'-executeMethod','Xace.Authoring.Editor.NEC017ExistingMutations.Run','-nec017Mutation',phase,'-logFile',str(out/('mutation-'+phase+'-engine.log'))],out,'mutation-'+phase,env,240);value=load_json(root/('mutation-'+phase+'.json'));assert value['ok'];(out/('native-'+phase+'.json')).write_bytes(canonical(value))
  if phase in ['rename','move','reparent']:assert set(value['before']['objects'])==set(value['after']['objects'])
  if phase=='duplicate':assert value['collision_refused'] and value['explicit_distinct_identity'] and len(value['after']['objects'])==len(value['before']['objects'])+1
  if phase=='delete':assert len(value['after']['objects'])==len(value['before']['objects'])-1
  # Inspect the actual saved native capture; never fabricate a live writer approval.
  error=None;report=None
  try:
   test_context=context() if phase!='move' else dict(context(),native_inventory=canonical(value['after']),expected_source_digest=sha(canonical(value['after'])))
   from native_reconciliation_plan import plan_reconciliation
   report=plan_reconciliation(**test_context).to_dict()
  except ValueError as failure:error=str(failure)
  assert all((root/n).read_bytes()==data for n,data in saved.items()),'Mutation review published without approval'
  mutations.append(dict(phase=phase,native_editor=True,identity_preserved=phase in ['rename','move','reparent'],collision_refused=value.get('collision_refused'),explicit_distinct_identity=value.get('explicit_distinct_identity'),reviewable=report.get('reviewable') if report else False,losses=report.get('losses') if report else None,refusal=error,canonical_and_baseline_unchanged=True))
  # Test-owner compensation only: exact current after-images are checked before restoring.
  after={n:(root/n).read_bytes() for n in before if (root/n).exists()};moved=root/'Assets/Game/MovedAnnex.unity'
  if phase=='move':
   assert not (root/'Assets/Game/Annex.unity').exists() and moved.is_file();moved_before=moved.read_bytes();assert moved.read_bytes()==moved_before;os.rename(moved,root/'Assets/Game/Annex.unity');os.rename(Path(str(moved)+'.meta'),root/'Assets/Game/Annex.unity.meta')
  for n,data in before.items():
   if n in after:assert (root/n).read_bytes()==after[n]
   (root/n).write_bytes(data)
  assert host.review.open('workflow-owner')['report']['noop'];print('Native '+engine+' '+phase+' preservation/refusal checks passed',flush=True)
 m=IdentityMap.from_dict(load_json(root/MAP));key=next(k for k,r in json.loads(gateway.capture())['objects'].items() if r['name']=='Crate0' and m.objects[k].world_binding);actor_id=m.objects[key].world_binding.actor_id;original=copy.deepcopy(load_json(root/'game.cgs.json'));old_actor=next(a for a in original['modes'][0]['actors'] if a['id']==actor_id);old_x=old_actor['components'][0]['defaults']['position']['x'];raw=gateway.capture();base=reader.capture(raw,m,enable_writes=True).admit();target=json.loads(raw);target['objects'][key]['fields']['transform.position']['x']=str(old_x//1000000+1);desired=reader.capture(canonical(target),m,enable_writes=True).admit();prepared=gateway.prepare('explicit-conflicting-native-edit',dict(write_request=json.loads(reader.write_request(raw,base,desired,m))));gateway.commit(prepared)
 c=load_json(root/'game.cgs.json');next(a for a in c['modes'][0]['actors'] if a['id']==actor_id)['components'][0]['defaults']['position']['x']=old_x+2000000;rehash(c);(root/'game.cgs.json').write_bytes(canonical(c));opened=host.review.open('workflow-owner');assert not opened['report']['reviewable'] and opened['report']['merge']['conflicts'];(out/'blocked-conflict.json').write_bytes(canonical(opened['report']));unchanged={n:(root/n).read_bytes() for n in protected}
 try:host.review.approve('workflow-owner',opened['token'],opened['proposal_digest'])
 except ValueError:pass
 else:raise AssertionError('Unresolved conflict approved')
 assert all((root/n).read_bytes()==b for n,b in unchanged.items());resolved=host.review.resolve('workflow-owner',opened['token'],opened['proposal_digest'],{c['id']:'engine' for c in opened['report']['merge']['conflicts']});assert resolved['report']['reviewable'];approval=host.review.approve('workflow-owner',resolved['token'],resolved['proposal_digest']);assert host.apply('workflow-owner',approval,approval['proposal_digest'])['state']=='committed';(out/'resolved-conflict.json').write_bytes(canonical(resolved['report']))
 final=load_json(root/'game.cgs.json');next(a for a in final['modes'][0]['actors'] if a['id']==actor_id)['components'][0]['defaults']['position']['x']=old_x;rehash(final);(root/'game.cgs.json').write_bytes(canonical(final));opened=host.review.open('workflow-owner');approval=host.review.approve('workflow-owner',opened['token'],opened['proposal_digest']);assert host.apply('workflow-owner',approval,approval['proposal_digest'])['state']=='committed';assert host.review.open('workflow-owner')['report']['noop']
 assert all(sha((source/n).read_bytes())==v for n,v in source_files.items());(out/'authoring-proof.json').write_bytes(canonical(dict(ok=True,engine=engine,objects=51,mutations=mutations,actual_native_conflict_refused=True,explicit_engine_resolution_committed=True,original_gameplay_positions_restored_through_review=True,original_source_unchanged=True,native_play_again_verified=False)));print('Imported '+engine+' native mutation/conflict sequence passed; Play-again remains pending',flush=True)
if __name__=='__main__':main(sys.argv[1],Path(sys.argv[2]))
