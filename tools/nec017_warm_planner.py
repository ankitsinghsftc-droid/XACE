"""Read-only warm planner lower bound using retained installed-engine captures.
Not a capture-to-review or repeated native build certification.
"""
from pathlib import Path
import sys,json,copy,time,math,hashlib
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'packages/project-system')]
from authoring_identity import IdentityMap,canonical,digest
from authoring_saved_pair import MAP,CGS,NATIVE,verify_baseline_receipts
from native_authoring_contract import Snapshot
from native_reconciliation_plan import plan_reconciliation
from tools.world_extensibility_proof import rehash

def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists();out.mkdir(parents=True)
 results=[]
 for engine,folder in [('godot','godot-repeat-d'),('unity','unity-repeat-a'),('unreal','unreal-repeat-a')]:
  root=ROOT/'evidence/nec017/20261029'/folder/'project';assert json.loads((root.parent/'proof.json').read_bytes())['ok']
  candidates=[p for p in (root/'.xace/native-authoring-calls').glob('*/result.json') if json.loads((p.parent/'command.json').read_bytes())['action']=='capture'];receipt=max(candidates,key=lambda p:p.stat().st_mtime)
  raw=canonical(json.loads(receipt.read_bytes())['result']);m=IdentityMap.from_dict(json.loads((root/MAP).read_bytes()));base=json.loads((root/CGS).read_bytes());snapshot=Snapshot((root/NATIVE).read_bytes());assert verify_baseline_receipts(root,m.baseline)
  samples=[]
  for n in range(30):
   current=copy.deepcopy(base);actors=current['modes'][0]['actors'];assert len(actors)==1000
   for actor in actors[:100]:actor['components'][0]['defaults']['position']['x']+=(n+1)*1000000
   rehash(current);started=time.perf_counter()
   report=plan_reconciliation(baseline=snapshot,baseline_cgs=base,mapping=m,current_mapping=copy.deepcopy(m),current_cgs=current,native_inventory=raw,expected_current_cgs_digest=digest(current),expected_source_digest=hashlib.sha256(raw).hexdigest(),verify_baseline=lambda b:verify_baseline_receipts(root,b),trusted_project=True).to_dict()
   elapsed=time.perf_counter()-started;assert report['reviewable'] and not report['noop'],report['losses'];samples.append(elapsed)
   with (out/'samples.jsonl').open('a') as f:f.write(json.dumps(dict(engine=engine,batch=n,seconds=elapsed,changed_objects=100))+'\n')
  p95=sorted(samples)[math.ceil(.95*len(samples))-1];results.append(dict(engine=engine,objects=1000,batches=30,changed_objects=100,p95_planner_seconds=p95,planner_only_within_2s=p95<2,capture_receipt=str(receipt),capture_sha256=hashlib.sha256(receipt.read_bytes()).hexdigest()))
  print(json.dumps(results[-1]),flush=True)
 (out/'measurement.json').write_text(json.dumps(dict(scope='Planner lower bound only; excludes editor capture and review service',results=results,certifies_capture_to_review=False),indent=2))
if __name__=='__main__':main(Path(sys.argv[1]))
