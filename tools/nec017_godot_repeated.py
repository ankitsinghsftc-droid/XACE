"""NEC017 actual1,000-object repeated authoring through production host."""
from pathlib import Path
import copy,json,shutil,sys,time,tracemalloc
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.nec010_playback_host_proof import NativeEditorGateway,NativeMaterializationHost,IdentityMap,WorldBinding,canonical,sha,load_json,TransactionRequest,file_change,ACTIVATION,SavedPair,MAP,CGS,NATIVE,verify_baseline_receipts,Snapshot,digest,rehash
from tools.nec014_export_proof import GODOT
import godot_authoring as reader

def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists();root=out/'project';root.mkdir(parents=True)
 source=ROOT/'evidence/nec017/20261028/godot-scale-a';shutil.copytree(source/'godot-project/XACEGenerated',root/'XACEGenerated');shutil.copytree(ROOT/'adapters/godot/authoring',root/'addons/xace_authoring')
 shutil.copyfile(ROOT/'adapters/godot/xace_protocol.gd',root/'xace_protocol.gd')
 (root/'project.godot').write_text('config_version=5\n[application]\nconfig/name="NEC017 Repeated1000"\n[editor_plugins]\nenabled=PackedStringArray("res://addons/xace_authoring/plugin.cfg")\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n')
 pins={p.relative_to(root).as_posix():sha(p.read_bytes()) for p in (root/'addons').rglob('*') if p.is_file()}
 gateway=NativeEditorGateway(root,engine='godot',executable=str(GODOT),executable_sha256=sha(GODOT.read_bytes()),documents=['res://XACEGenerated/World.tscn'],source_roots=['XACEGenerated','addons','project.godot','xace_protocol.gd'],plugin_hashes=pins,trusted_closed_project=True)
 cgs=load_json(source/'source.cgs.json');setup=load_json(source/'setup-plan.json');raw=gateway.capture();mapping=reader.prepare_identity_map(raw,project_id='nec017-repeated',branch_id='b'*32)
 for key,binding in setup['bindings'].items():mapping.objects[key].world_binding=WorldBinding(**binding)
 rows=reader.capture(raw,mapping,enable_writes=True).admit().to_dict()['inspection']['normalized'];assert len(setup['bindings'])==1000
 (root/'game.cgs.json').write_bytes(canonical(cgs));host=NativeMaterializationHost(root,lambda:None,gateway);pair=SavedPair(root,mapping=mapping,expected_cgs=cgs,expected_normalized=rows,recapture=gateway.capture)
 request=TransactionRequest('explicit-fixture-baseline','a'*64,dict(canonical=dict(files=[file_change('game.cgs.json',sha(canonical(cgs)),canonical(cgs))]),native=dict(write_request=None)),ACTIVATION,dict(mapping=mapping.to_dict(),cgs_digest=digest(cgs),normalized_digest=digest(rows)),dict(cgs=cgs,normalized=rows,accepted_loss_digest=None));host._coordinator(pair).commit(request,authorize=lambda _:True)
 def context():
  current=load_json(root/'game.cgs.json');m=IdentityMap.from_dict(load_json(root/MAP));native=gateway.capture()
  return dict(baseline=Snapshot((root/NATIVE).read_bytes()),baseline_cgs=load_json(root/CGS),mapping=m,current_mapping=copy.deepcopy(m),current_cgs=current,native_inventory=native,expected_current_cgs_digest=digest(current),expected_source_digest=sha(native),verify_baseline=lambda b:verify_baseline_receipts(root,b),trusted_project=True)
 def apply():
  h=NativeMaterializationHost(root,context,gateway);opened=h.review.open('developer-a');assert opened['report']['reviewable'],opened['report']['losses'];approval=h.review.approve('developer-a',opened['token'],opened['proposal_digest']);assert h.apply('developer-a',approval,approval['proposal_digest'])['state']=='committed'
 key=sorted(setup['bindings'])[0];actor_id=setup['bindings'][key]['actor_id'];samples=[];tracemalloc.start()
 for n in range(3):
  started=time.perf_counter();m=IdentityMap.from_dict(load_json(root/MAP));raw=gateway.capture();base=reader.capture(raw,m,enable_writes=True).admit();target=json.loads(raw);target['objects'][key]['fields']['transform.position']['x']=str(10+n)
  desired=reader.capture(canonical(target),m,enable_writes=True).admit();prepared=gateway.prepare('repeated-native-'+str(n),dict(write_request=json.loads(reader.write_request(raw,base,desired,m))));gateway.commit(prepared);apply()
  current=load_json(root/'game.cgs.json');actor=next(a for a in current['modes'][0]['actors'] if a['id']==actor_id);assert actor['components'][0]['defaults']['position']['x']==(10+n)*1000000
  actor['components'][0]['defaults']['position']['x']=(20+n)*1000000;rehash(current);(root/'game.cgs.json').write_bytes(canonical(current));apply()
  final=json.loads(gateway.capture());assert final['objects'][key]['fields']['transform.position']['x']==str(20+n)
  h=NativeMaterializationHost(root,context,gateway);noop=h.review.open('developer-a');assert noop['report']['noop'] and noop['report']['reviewable']
  protected={name:(root/name).read_bytes() for name in ['game.cgs.json','XACEGenerated/World.tscn',MAP,CGS,NATIVE]};states=[h.poll_saved_changes()['state'] for _ in range(3)];assert states==['waiting','review_available','unchanged'];assert protected=={name:(root/name).read_bytes() for name in protected}
  files=[p for p in (root/'.xace').rglob('*') if p.is_file()];sample=dict(cycle=n,seconds=time.perf_counter()-started,history_files=len(files),history_bytes=sum(p.stat().st_size for p in files),python_peak_tracemalloc_bytes=tracemalloc.get_traced_memory()[1]);samples.append(sample);(out/'progress.json').write_bytes(canonical(dict(samples=samples,complete=False)));print(json.dumps(sample),flush=True)
 result=dict(ok=True,objects=1000,cycles=3,engine='godot',real_editor=True,production_review_apply=True,bidirectional_supported_field=True,no_op_and_saved_batching=True,samples=samples,history_retained=True,automatic_cleanup=False,child_native_process_peak_memory_measured=False,full_nec017_certification=False)
 (out/'proof.json').write_bytes(canonical(result));print(json.dumps(result),flush=True)
if __name__=='__main__':main(Path(sys.argv[1]))
