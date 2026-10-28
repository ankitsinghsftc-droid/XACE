"""NEC017 real Godot production-host process death at every journal boundary.

Each case owns a new persistent fixture. Old evidence and failed attempts remain.
This is a small native recovery cell, not the 1000-object scale certification.
"""
from pathlib import Path
import copy,json,os,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.nec010_playback_host_proof import NativeEditorGateway,NativeMaterializationHost,IdentityMap,WorldBinding,canonical,sha,load_json,TransactionRequest,file_change,ACTIVATION,SavedPair,MAP,CGS,NATIVE,verify_baseline_receipts,Snapshot,digest,rehash
from tools.nec014_export_proof import GODOT
import godot_authoring as reader
EVENTS=['intent_durable','prepared_before_receipt:canonical','prepared:canonical','prepared_before_receipt:native','prepared:native','decision_durable','published_before_receipt:canonical','published:canonical','published_before_receipt:native','published:native','pair_verified','baseline_prepared','baseline_published_before_receipt','complete_durable']
SEED=ROOT/'evidence/nec017/20261029/godot-crash-seed-a'

def gateway(root):
 pins={p.relative_to(root).as_posix():sha(p.read_bytes()) for p in (root/'addons').rglob('*') if p.is_file() and p.suffix!='.uid'}
 return NativeEditorGateway(root,engine='godot',executable=str(GODOT),executable_sha256=sha(GODOT.read_bytes()),documents=['res://XACEGenerated/World.tscn'],source_roots=['XACEGenerated','addons','project.godot','xace_protocol.gd'],plugin_hashes=pins,trusted_closed_project=True)

def host(root,g):
 def context():
  c=load_json(root/'game.cgs.json');m=IdentityMap.from_dict(load_json(root/MAP));raw=g.capture()
  return dict(baseline=Snapshot((root/NATIVE).read_bytes()),baseline_cgs=load_json(root/CGS),mapping=m,current_mapping=copy.deepcopy(m),current_cgs=c,native_inventory=raw,expected_current_cgs_digest=digest(c),expected_source_digest=sha(raw),verify_baseline=lambda b:verify_baseline_receipts(root,b),trusted_project=True)
 return NativeMaterializationHost(root,context,g)

def fixture(out):
 root=out/'project';root.mkdir(parents=True,exist_ok=False)
 shutil.copytree(SEED/'godot-project/XACEGenerated',root/'XACEGenerated');shutil.copytree(ROOT/'adapters/godot/authoring',root/'addons/xace_authoring')
 shutil.copyfile(ROOT/'adapters/godot/xace_protocol.gd',root/'xace_protocol.gd')
 (root/'project.godot').write_text('config_version=5\n[application]\nconfig/name="NEC017 crash fixture"\n[editor_plugins]\nenabled=PackedStringArray("res://addons/xace_authoring/plugin.cfg")\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n')
 g=gateway(root);raw=g.capture();c=load_json(SEED/'source.cgs.json');setup=load_json(SEED/'setup-plan.json');m=reader.prepare_identity_map(raw,project_id='nec017-crash',branch_id='b'*32)
 for key,binding in setup['bindings'].items():m.objects[key].world_binding=WorldBinding(**binding)
 rows=reader.capture(raw,m,enable_writes=True).admit().to_dict()['inspection']['normalized']
 (root/'game.cgs.json').write_bytes(canonical(c));pair=SavedPair(root,mapping=m,expected_cgs=c,expected_normalized=rows,recapture=g.capture)
 request=TransactionRequest('explicit-fixture-baseline','a'*64,dict(canonical=dict(files=[file_change('game.cgs.json',sha(canonical(c)),canonical(c))]),native=dict(write_request=None)),ACTIVATION,dict(mapping=m.to_dict(),cgs_digest=digest(c),normalized_digest=digest(rows)),dict(cgs=c,normalized=rows,accepted_loss_digest=None))
 host(root,g)._coordinator(pair).commit(request,authorize=lambda _:True)
 old={p:(root/p).read_bytes() for p in [MAP,CGS,NATIVE]};(out/'before.json').write_bytes(canonical(dict(native=sha((root/'XACEGenerated/World.tscn').read_bytes()),baseline={p:sha(b) for p,b in old.items()})))
 key=sorted(setup['bindings'])[0];actor=next(a for a in c['modes'][0]['actors'] if a['id']==setup['bindings'][key]['actor_id']);actor['components'][0]['defaults']['position']['x']=73000000;rehash(c);(root/'game.cgs.json').write_bytes(canonical(c))
 (out/'expected.json').write_bytes(canonical(dict(cgs=sha(canonical(c)),key=key,x='73')))
 return root

def child(out,event):
 root=out/'project';g=gateway(root);h=host(root,g);opened=h.review.open('crash-developer');assert opened['report']['reviewable'],opened['report']['losses'];approval=h.review.approve('crash-developer',opened['token'],opened['proposal_digest'])
 original=h._coordinator
 def coordinator(*args,**kwargs):
  c=original(*args,**kwargs)
  def checkpoint(name):
   if name==event:os._exit(73)
  c.checkpoint=checkpoint;return c
 h._coordinator=coordinator
 h.apply('crash-developer',approval,approval['proposal_digest']);raise AssertionError('checkpoint not reached')

def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists();out.mkdir(parents=True)
 (out/'source-pins.json').write_bytes(canonical({str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in [Path(__file__),*sorted((ROOT/'packages/project-system').glob('*.py')),*sorted((ROOT/'adapters/godot/authoring').glob('*.gd'))]}))
 results=[]
 for index,event in enumerate(EVENTS):
  case=out/f'{index:02d}';root=fixture(case)
  with (case/'child.log').open('wb') as log:run=subprocess.run([sys.executable,'-B',__file__,'--child',str(case),event],stdout=log,stderr=subprocess.STDOUT,timeout=600,creationflags=subprocess.CREATE_NO_WINDOW)
  assert run.returncode==73,(event,run.returncode)
  g=gateway(root);h=host(root,g);journals=[p for p in (root/'.xace/authoring-transactions').iterdir() if p.name.startswith('apply-')];assert len(journals)==1
  tid=journals[0].name;state=h.recover(tid);wanted='aborted' if index<EVENTS.index('decision_durable') else 'committed';assert state['state']==wanted,(event,state)
  assert h.recover(tid)==state and not h.status()['play_build_blocked']
  expected=load_json(case/'expected.json');assert sha((root/'game.cgs.json').read_bytes())==expected['cgs']
  if wanted=='aborted':
   before=load_json(case/'before.json');assert sha((root/'XACEGenerated/World.tscn').read_bytes())==before['native'];assert all(sha((root/p).read_bytes())==v for p,v in before['baseline'].items())
  else:
   observed=json.loads(g.capture());assert observed['objects'][expected['key']]['fields']['transform.position']['x']==expected['x'];assert verify_baseline_receipts(root,IdentityMap.from_dict(load_json(root/MAP)).baseline)
  result=dict(event=event,process_exit=73,recovered=wanted,idempotent=True,canonical_edit_preserved=True,baseline_verified=True,play_build_unblocked=True);results.append(result);(case/'proof.json').write_bytes(canonical(result));(out/'progress.json').write_bytes(canonical(dict(complete=False,cases=results)));print(json.dumps(result),flush=True)
 (out/'proof.json').write_bytes(canonical(dict(ok=True,cases=results,real_native_editor=True,production_host=True,objects=2,full_nec017_certification=False)))
if __name__=='__main__':
 if sys.argv[1]=='--child':child(Path(sys.argv[2]),sys.argv[3])
 else:main(Path(sys.argv[1]))
