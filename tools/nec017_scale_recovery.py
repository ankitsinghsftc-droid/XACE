"""Representative actual process death after native publication at1000 bindings.

Every-boundary certification is separate (14 per engine on small fixtures).
This checks recovery correctness at the unchanged1000-object target.
"""
from pathlib import Path
import importlib,sys,json,subprocess,time,shutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.nec010_playback_host_proof import canonical,sha,load_json,IdentityMap,MAP,verify_baseline_receipts

def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists();out.mkdir(parents=True)
 (out/'source-pins.json').write_bytes(canonical({str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in [Path(__file__),*sorted((ROOT/'packages/project-system').glob('*.py'))]}))
 results=[]
 for engine in ['godot','unity','unreal']:
  assert shutil.disk_usage(ROOT).free>4*1024**3,'Need4GiB reserve; no cleanup performed'
  module=importlib.import_module('tools.nec017_'+engine+'_crash');module.SEED=ROOT/'evidence/nec017/20261028'/(engine+'-scale-a')
  case=out/engine;started=time.perf_counter();root=module.fixture(case)
  mapping=IdentityMap.from_dict(load_json(root/MAP));assert sum(bool(r.world_binding) for r in mapping.objects.values())==1000
  with (case/'crash-child.log').open('wb') as log:child=subprocess.run([sys.executable,'-B',module.__file__,'--child',str(case),'published_before_receipt:native'],stdout=log,stderr=subprocess.STDOUT,timeout=1200,creationflags=subprocess.CREATE_NO_WINDOW)
  assert child.returncode==73,(engine,child.returncode)
  gateway=module.gateway(root);host=module.host(root,gateway);assert host.status()['play_build_blocked']
  transactions=[p.name for p in (root/'.xace/authoring-transactions').iterdir() if p.name.startswith('apply-')];assert len(transactions)==1;transaction=transactions[0]
  state=host.recover(transaction);assert state['state']=='committed' and host.recover(transaction)==state and not host.status()['play_build_blocked']
  mapping=IdentityMap.from_dict(load_json(root/MAP));assert verify_baseline_receipts(root,mapping.baseline)
  observed=module.reader.capture(gateway.capture(),mapping,enable_writes=True).admit().to_dict()['inspection']['normalized'];expected=load_json(case/'expected.json')
  assert observed[expected['key']]['fields']['transform.position']['x']=='73000000' and sha((root/'game.cgs.json').read_bytes())==expected['cgs']
  assert host.review.open('reopened-developer')['report']['noop']
  files=[p for p in (root/'.xace').rglob('*') if p.is_file()]
  result=dict(engine=engine,objects=1000,process_exit=73,boundary='published_before_receipt:native',state='committed',idempotent_recovery=True,reopened_noop=True,history_files=len(files),history_bytes=sum(p.stat().st_size for p in files),seconds=time.perf_counter()-started)
  results.append(result);(case/'proof.json').write_bytes(canonical(result));(out/'progress.json').write_bytes(canonical(dict(complete=False,cases=results)));print(json.dumps(result),flush=True)
 (out/'proof.json').write_bytes(canonical(dict(ok=True,cases=results,full_nec017_certification=False)))
if __name__=='__main__':main(Path(sys.argv[1]))
