"""Decision measurement of actual capture-to-review; three samples are not p95 certification.
Each engine uses a new1000-object fixture; no apply or original fixture mutation.
"""
from pathlib import Path
import importlib,json,sys,time,platform,shutil,os,math
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.nec010_playback_host_proof import canonical,sha,load_json,rehash

def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists();out.mkdir(parents=True)
 count=int(os.environ.get('NEC017_REVIEW_SAMPLES','3'));assert count in [3,30]
 sources=[Path(__file__),*sorted((ROOT/'packages/project-system').glob('*.py')),*sorted((ROOT/'adapters').rglob('*.gd')),*sorted((ROOT/'adapters').rglob('*.cs')),*sorted((ROOT/'adapters').rglob('*.cpp')),*sorted((ROOT/'adapters').rglob('*.h'))]
 pins={p.relative_to(ROOT).as_posix():sha(p.read_bytes()) for p in sources}
 (out/'source-pins.json').write_bytes(canonical(pins));cases=[]
 engines=sys.argv[2:] or ['godot','unity','unreal'];assert engines and set(engines)<={'godot','unity','unreal'} and len(set(engines))==len(engines)
 for engine in engines:
  assert shutil.disk_usage(ROOT).free>4*1024**3,'4GiB reserve; no cleanup performed'
  module=importlib.import_module('tools.nec017_'+engine+'_crash');module.SEED=ROOT/'evidence/nec017/20261028'/(engine+'-scale-a')
  if engine=='unity':
   # New seed COPY: preserve native1000-object data, explicitly upgrade copied authoring code.
   original=module.SEED;stage=out/'unity-current-source';stage.mkdir()
   for name in ['source.cgs.json','setup-plan.json']:shutil.copyfile(original/name,stage/name)
   for name in ['Assets/XACEGenerated','Assets/XaceAuthoring','Packages','ProjectSettings']:
    shutil.copytree(original/'unity-project'/name,stage/'unity-project'/name)
   shutil.copyfile(original/'unity-project/Assets/XACEGenerated.meta',stage/'unity-project/Assets/XACEGenerated.meta')
   upgrade={}
   for p in (ROOT/'adapters/unity/Authoring').rglob('*'):
    if p.is_file():
     dest=stage/'unity-project/Assets/XaceAuthoring'/p.relative_to(ROOT/'adapters/unity/Authoring');upgrade[p.relative_to(ROOT).as_posix()]=sha(p.read_bytes());dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest)
   (stage/'explicit-source-upgrade.json').write_bytes(canonical(dict(original=str(original),current_plugin=upgrade,native_scene_changed=False)))
   module.SEED=stage
  case=out/engine;started=time.perf_counter();root=module.fixture(case);setup_seconds=time.perf_counter()-started;g=module.gateway(root);h=module.host(root,g)
  original_capture=g.capture;capture_samples=[]
  def measured_capture():
   start=time.perf_counter();value=original_capture();capture_samples.append(time.perf_counter()-start);return value
  g.capture=measured_capture
  base=load_json(root/'.xace/authoring-baseline.cgs.json');assert len(base['modes'][0]['actors'])==1000
  samples=[]
  for n in range(count):
   c=load_json(root/'.xace/authoring-baseline.cgs.json')
   for actor in c['modes'][0]['actors'][:100]:actor['components'][0]['defaults']['position']['x']=(41+n)*1000000
   rehash(c);(root/'game.cgs.json').write_bytes(canonical(c));capture_samples.clear()
   started=time.perf_counter();review=h.review.open('nec017-latency-review');elapsed=time.perf_counter()-started
   assert review['report']['reviewable'] and len(review['report']['merge']['native_proposals'])==100
   assert len(capture_samples)==1
   row=dict(batch=n,full_capture_to_review_seconds=elapsed,native_capture_seconds=capture_samples[0],other_review_seconds=elapsed-capture_samples[0]);samples.append(row)
   with (case/'samples.jsonl').open('a',encoding='utf-8') as log:log.write(json.dumps(row)+'\n')
   print(json.dumps(dict(engine=engine,**row)),flush=True)
  result=dict(engine=engine,objects=1000,edits=100,samples=samples,fixture_setup_seconds_excluded=setup_seconds,minimum_seconds=min(r['full_capture_to_review_seconds'] for r in samples),maximum_seconds=max(r['full_capture_to_review_seconds'] for r in samples),editor_process_start_included=True,import_compile_time_subtracted=False,p95_certified=False,sample_count=count,measured_p95_seconds=sorted(r['full_capture_to_review_seconds'] for r in samples)[math.ceil(.95*count)-1],speed_target_deferred=True)
  cases.append(result);(case/'measurement.json').write_bytes(canonical(result))
 assert all(sha((ROOT/p).read_bytes())==v for p,v in pins.items())
 (out/'measurement.json').write_bytes(canonical(dict(scope='Actual saved CGS100-edit capture/review samples; startup included; speed target deferred; no apply/build timing claim',sample_count_per_engine=count,cases=cases,os=platform.platform(),processor=platform.processor(),source_stable=True,p95_certified=False)))
if __name__=='__main__':main(Path(sys.argv[1]))
