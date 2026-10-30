"""Installed-engine 100-edit atomic batches at 1000 bound objects."""
from pathlib import Path
import sys,importlib,copy,json,time,shutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.nec010_playback_host_proof import canonical,sha,load_json,IdentityMap,MAP,verify_baseline_receipts,rehash

def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists();out.mkdir(parents=True)
 (out/'source-pins.json').write_bytes(canonical({str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in [Path(__file__),*sorted((ROOT/'packages/project-system').glob('*.py'))]}))
 cases=[]
 for engine in ['godot','unity','unreal']:
  assert shutil.disk_usage(ROOT).free>4*1024**3,'4GiB reserve required; no cleanup'
  module=importlib.import_module('tools.nec017_'+engine+'_crash');module.SEED=ROOT/'evidence/nec017/20261028'/(engine+'-scale-a');case=out/engine;root=module.fixture(case);g=module.gateway(root);h=module.host(root,g)
  c=load_json(root/'.xace/authoring-baseline.cgs.json');assert len(c['modes'][0]['actors'])==1000
  ids=[]
  for actor in c['modes'][0]['actors'][:100]:actor['components'][0]['defaults']['position']['x']=41000000;ids.append(actor['id'])
  rehash(c);(root/'game.cgs.json').write_bytes(canonical(c))
  def apply(direction):
   start=time.perf_counter();review=h.review.open('batch-developer');assert review['report']['reviewable'],review['report']['losses'];count=len(review['report']['merge']['native_proposals'] if direction=='to_native' else review['report']['typed_operations']['operations']);assert count==100,count
   approval=h.review.approve('batch-developer',review['token'],review['proposal_digest']);assert h.apply('batch-developer',approval,approval['proposal_digest'])['state']=='committed';return time.perf_counter()-start
  outward=apply('to_native');m=IdentityMap.from_dict(load_json(root/MAP));raw=g.capture();base=module.reader.capture(raw,m,enable_writes=True).admit();target=json.loads(raw);keys=[k for k,r in m.objects.items() if r.world_binding and r.world_binding.actor_id in ids];assert len(keys)==100
  for key in keys:
   fields=target['objects'][key]['fields']['transform.position'];fields['y' if engine=='unreal' else 'x']='4200' if engine=='unreal' else '42'
  desired=module.reader.capture(canonical(target),m,enable_writes=True).admit();prepared=g.prepare('hundred-native-edits',dict(write_request=json.loads(module.reader.write_request(raw,base,desired,m))));g.commit(prepared)
  inward=apply('to_cgs');c=load_json(root/'game.cgs.json');assert all(a['components'][0]['defaults']['position']['x']==42000000 for a in c['modes'][0]['actors'] if a['id'] in ids)
  assert h.review.open('batch-developer')['report']['noop'];m=IdentityMap.from_dict(load_json(root/MAP));assert verify_baseline_receipts(root,m.baseline)
  result=dict(ok=True,engine=engine,objects=1000,edits_per_batch=100,outward_seconds=outward,inward_seconds=inward,reopened_noop=True,scope='One actual bidirectional 100-edit pair; not 30-batch latency or build certification');cases.append(result);(case/'proof.json').write_bytes(canonical(result));print(json.dumps(result),flush=True)
 (out/'proof.json').write_bytes(canonical(dict(ok=True,cases=cases)))
if __name__=='__main__':main(Path(sys.argv[1]))
