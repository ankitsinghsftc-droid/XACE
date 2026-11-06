"""Fresh execution/replay from NEC017 existing-project captures and explicit gameplay choice.
Reuses saved installed-editor captures read-only. Does not claim native Play/build.
"""
from pathlib import Path
import copy,hashlib,importlib,json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system'),str(ROOT/'packages/project-system/tests')]
from test_native_adoption import inputs,choices_for,plan
from authoring_identity import canonical,IdentityMap
from authoring_saved_pair import MAP,verify_baseline_receipts
from native_executor_contract import TrustedExecutor,digest,admit
from tools.cgs_schema_validate import compute_cgs_hash
import playable_package as packages
from native_package_resources import prepare_resources

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists();out.mkdir(parents=True)
 build=ROOT/'evidence/nec011/20261021/reference-admission-a';receipt=json.loads((build/'executor-receipt.json').read_bytes());exe=build/'relocated-game/runtime/xace_runtime.exe'
 trusted=TrustedExecutor(receipt,expected_receipt_digest=digest(receipt),executable=exe,expected_compatibility=receipt['compatibility'])
 reference=json.loads((ROOT/'examples/reference-mechanic/fixtures/player/game.cgs.json').read_bytes())
 sgc=Path('C:/Users/ankit/XACE-Recovery/build-output/cargo/debug/xace-system-graph-compiler.exe');cases={}
 pins={p.relative_to(ROOT).as_posix():sha(p) for p in [Path(__file__),*sorted((ROOT/'packages/project-system').glob('*.py'))]};(out/'source-pins.json').write_bytes(canonical(pins))
 for engine,folder in [('godot','godot-material-publish-a'),('unity','unity-existing-publish-b'),('unreal','unreal-existing-publish-b')]:
  source=ROOT/'evidence/nec017/20261105'/folder;assert json.loads((source/'editing-proof.json').read_bytes())['ok'];root=source/'project'
  original=IdentityMap.from_dict(json.loads((root/MAP).read_bytes()));assert verify_baseline_receipts(root,original.baseline)
  selected=sorted(k for k,r in original.objects.items() if r.world_binding);assert len(selected)==(51 if engine=='unity' else 50)
  captures=[p for p in (root/'.xace/native-authoring-calls').glob('*/result.json') if json.loads((p.parent/'command.json').read_bytes())['action']=='capture']
  capture=max(captures,key=lambda p:p.stat().st_mtime_ns);observed=json.loads(capture.read_bytes());assert observed['ok'];raw=canonical(observed['result']);value=json.loads(raw)
  dest=out/engine;dest.mkdir();(dest/'native-inventory.json').write_bytes(raw)
  reader=importlib.import_module(engine+'_authoring');mapping=reader.prepare_identity_map(raw,project_id='nec017-explicit-gameplay',branch_id='c'*32)
  cgs=inputs(engine)[2];saved=json.loads((root/'game.cgs.json').read_bytes())
  if 'native_instance_profile' in saved:cgs['native_instance_profile']=saved['native_instance_profile']
  cgs['component_schemas']=copy.deepcopy(reference['component_schemas']);cgs['global_systems']=copy.deepcopy(reference['global_systems']);cgs['modes'][0]['systems']=copy.deepcopy(reference['modes'][0]['systems'])
  choices=choices_for(selected)
  for key in selected:
   fields=value['objects'][key]['fields']
   if 'presentation.asset' in fields:choices['objects'][key]['asset_role']='project.visual.v1'
   if 'presentation.material' in fields:choices['objects'][key]['material_role']='project.material.v1'
  chosen=next(k for k in selected if value['objects'][k]['name']=='Crate0')
  player=next(a for a in reference['modes'][0]['actors'] if a['id']=='player')
  choices['objects'][chosen].update(actor_type='PLAYER',control_type='HUMAN',components=[copy.deepcopy(c) for c in player['components'] if c['type_id']!=1])
  cgs['metadata']['cgs_hash']=compute_cgs_hash(cgs)
  (dest/'explicit-gameplay-choice.json').write_bytes(canonical(dict(scope='Test owner explicitly chooses trusted reference traversal on Crate0; not automatic original-code conversion',choices=choices,executor_receipt_digest=digest(receipt))))
  result=plan(raw,mapping,cgs,selected,choices,trusted_executor=trusted).to_dict();(dest/'adoption.json').write_bytes(canonical(result));assert result['candidate_valid'] and result['saved_pair_eligible'],result['losses']
  candidate=result['proposed_cgs'];package,_=packages.compiled_artifacts(candidate);trusted.require_structured_transform(package)
  envelope=dict(systems=package.to_sgc_input(),schema_version=package.schema_version,cgs_hash=package.cgs_hash,plan_version=1)
  compiled=subprocess.run([str(sgc)],input=canonical(envelope),capture_output=True,check=True).stdout
  support=admit(receipt,expected_receipt_digest=digest(receipt),executable=exe,required_capabilities=['native.structured_transform.v1'],expected_compatibility=receipt['compatibility'],package=package)
  resources={}
  for asset in candidate.get('assets',[]):
   location=asset.get('source')
   if location:
    packages.safe_path(location);resource=(root/location).resolve();assert resource.is_relative_to(root.resolve()) and resource.is_file()
    resources[location]=resource.read_bytes()
  presentation=prepare_resources(candidate,engine,resources)
  (dest/'explicit-resource-plan.json').write_bytes(canonical(dict(action='Archive exact native resource bytes without rewriting CGS; no cross-engine conversion',resources={p:hashlib.sha256(data).hexdigest() for p,data in resources.items()})))
  archive=packages.build_package(candidate,compiled,exe.read_bytes(),support,package_id='nec017.existing.'+engine,version='0.1.0',presentation_files=presentation);(dest/'game.xacepkg').write_bytes(archive)
  installed=dest/'relocated';installed.mkdir()
  for name,data in packages.read_archive(archive).items():
   p=installed/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
  command=packages.runtime_command(installed,support,ticks=12)+['--port','0','--print-every','1','--epoch-replay-out',str(dest/'replay.xacer')];(dest/'command.json').write_bytes(canonical(command))
  with (dest/'runtime.log').open('wb') as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
  assert r.returncode==0,engine+' runtime failed'
  replay=[str(installed/'runtime/xace_runtime.exe'),'--epoch-replay-in',str(dest/'replay.xacer'),'--epoch-replay-report',str(dest/'replay-report.json')]
  with (dest/'replay.log').open('wb') as log:r=subprocess.run(replay,stdout=log,stderr=subprocess.STDOUT,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
  assert r.returncode==0,engine+' replay failed'
  proof=json.loads((dest/'replay-report.json').read_bytes());assert proof['ok'] and proof['verified_ticks']==12
  ticks=json.loads((dest/'replay.xacer').read_bytes())['bundle']['ticks'];assert len(ticks)==12
  first=ticks[0]['state'];last=ticks[-1]['state'];assert first['entities']==last['entities']
  a={k:json.loads(v) for k,v in first['components']['tables']['1']['rows'].items()};b={k:json.loads(v) for k,v in last['components']['tables']['1']['rows'].items()}
  assert set(a)==set(b) and len(a)==len(selected)
  moving=[key for key in a if a[key]!=b[key]];assert len(moving)==1 and b[moving[0]]['position']['y']<a[moving[0]]['position']['y']
  assert all(row['parent_entity_id']==0 for row in b.values())
  assert all(len(tick['state']['entities']['entities'])==len(selected) for tick in ticks)
  cases[engine]=dict(ok=True,objects=len(selected),native_capture=str(capture),native_capture_sha256=sha(capture),explicit_trusted_gameplay_choice=True,stable_entities=True,moving_entities=1,replayed_ticks=12,world_hashes=[t['world_hash'] for t in ticks],native_editor_play_verified=False)
  (dest/'proof.json').write_bytes(canonical(cases[engine]));print(json.dumps(dict(engine=engine,ok=True,objects=len(selected),replayed_ticks=12)),flush=True)
 assert all(sha(ROOT/p)==h for p,h in pins.items())
 (out/'proof.json').write_bytes(canonical(dict(ok=True,cases=cases,executor_sha256=receipt['executable_sha256'],sgc_sha256=sha(sgc),native_editor_rerun=False,full_nec017_certification=False)))
if __name__=='__main__':main(Path(sys.argv[1]))
