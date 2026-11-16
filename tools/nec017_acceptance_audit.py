"""NEC017 source/evidence audit. Missing cells stay OPEN; historical receipts immutable."""
from pathlib import Path
import hashlib,json,sys,subprocess,re
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.nec011_seal_integrity import verify as verify_seal

def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()
def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists();out.mkdir(parents=True);checks=[];references={}
 def proof(label,name,predicate=lambda x:x.get('ok') is True):
  p=ROOT/name
  if not p.is_file():checks.append(dict(cell=label,status='OPEN',reason='No corresponding proof located',path=name));return None
  data=json.loads(p.read_bytes());assert predicate(data),'Failed retained evidence: '+name;references[name]=sha(p);checks.append(dict(cell=label,status='PASS',path=name,sha256=references[name]));return data
 regression=ROOT/'evidence/nec017/20261106/verification-d';pins=json.loads((regression/'source-pins.json').read_bytes());assert len(pins)==185 and all(sha(ROOT/n)==v for n,v in pins.items());references[str((regression/'source-pins.json').relative_to(ROOT))]=sha(regression/'source-pins.json')
 for index,count in [(0,370),(1,127)]:
  p=regression/(str(index)+'.log');text=p.read_text(encoding='utf-8');assert (f'Ran {count} tests' in text and '\nOK' in text) if index==0 else f'{count} passed' in text;references[str(p.relative_to(ROOT))]=sha(p)
 checks.append(dict(cell='Current project-system/schema-factory regressions',status='PASS',python_source_test_files=185,test_counts=[370,127],rerun=False,reason='All exact tested source hashes unchanged'))
 shared=ROOT/'docs/evidence/nec012-completion-20261024/summary.json';d=json.loads(shared.read_bytes());assert all(sha(ROOT/n)==v for n,v in d['source_files'].items());launcher=ROOT/'evidence/nec012/20261024/lifecycle-listener-final/xace-player-launcher.exe';assert sha(launcher)==d['launcher_sha256'];references[str(shared.relative_to(ROOT))]=sha(shared)
 proof('Shared lifecycle19fault/compatibility checks','docs/evidence/nec012-completion-20261024/lifecycle.json',lambda d:d['ok'] and len(d['checks'])==19 and all(d['checks'].values()))
 proof('Failed native update, active-release retention and rollback','docs/evidence/nec012-completion-20261024/updates.json',lambda d:d['ok'] and d['working_pointer_unchanged_on_failure'] and d['explicit_rollback_to_retained_release'])
 proof('Interrupted update and incompatible-save refusal; no automatic migration','docs/evidence/nec016-continuity-20261028/update-save-proof.json',lambda d:d['ok'] and d['interrupted_before_readiness_preserves_active'] and d['automatic_migration'] is False)
 proof('Imported selected gameplay execution/replay50/51/50','evidence/nec017/20261106/existing-execution-b/proof.json')
 proof('Thirty native review samples per engine at1,000objects/100edits','evidence/nec017/20261106/native-review-30-a/measurement.json',lambda d:d['source_stable'] and d['sample_count_per_engine']==30 and len(d['cases'])==3 and all(c['objects']==1000 and c['edits']==100 for c in d['cases']))
 proof('Representative1,000-object recovery all engines','docs/evidence/nec017-collaboration-20261030/scale-recovery.json',lambda d:d['ok'] and len(d['cases'])==3 and all(c['objects']==1000 and c['idempotent_recovery'] for c in d['cases']))
 for engine,name in [('godot','docs/evidence/nec017-process-tree-20261029/crash-14.json'),('unity','docs/evidence/nec017-cross-engine-crash-20261029/unity-proof.json'),('unreal','docs/evidence/nec017-cross-engine-crash-20261029/unreal-proof.json')]:
  proof(engine+' all14durable process-death boundaries',name,lambda d:d['ok'] and len(d['cases'])==14 and all(c['idempotent'] and c['baseline_verified'] and c['process_exit']==73 for c in d['cases']))
 for engine,merge,rebase in [('godot','docs/evidence/nec017-collaboration-20261030/godot-merge.json','docs/evidence/nec017-collaboration-20261030/godot-rebase.json'),('unity','docs/evidence/nec017-collaboration-20261030/unity-merge.json','docs/evidence/nec017-batch-validation-20261030/unity-rebase.json'),('unreal','docs/evidence/nec017-continuation-20261104/unreal-merge.json','docs/evidence/nec017-continuation-20261104/unreal-rebase.json')]:
  proof(engine+' independent local Git branches/merge/conflict/recovery',merge,lambda d:d['ok'] and d['independent_git_branches'] and d['conflict_refused_until_explicit_choice'] and d['idempotent_recovery'] and d['process_death_after_native_publication']==73)
  proof(engine+' actual Git rebase/native preservation',rebase,lambda d:d['ok'] and d['actual_git_rebase'] and d['identity_and_baseline_preserved'] and d['native_and_canonical_bytes_preserved'])
 historical=json.loads((ROOT/'docs/evidence/nec011-completion-20261023/acceptance-audit/audit.json').read_bytes())
 for name,expected in historical['proof_receipts'].items():
  assert sha(ROOT/name)==expected;references[name]=expected
 checks.append(dict(cell='18 preserved unusual-mechanic/structured/state/replay/input/native-contract receipts',status='PASS',scope='Historical pinned executors/profile; not unrestricted mechanics or new compiler reruns',count=18))
 for engine,name in [('godot','docs/evidence/nec017-godot-repeated-20261029/proof.json'),('unity','docs/evidence/nec017-cross-engine-crash-20261029/unity-repeated-proof.json'),('unreal','docs/evidence/nec017-collaboration-20261030/unreal-repeated.json')]:
  proof(engine+' repeated edits/history/resources at1,000objects',name,lambda d:d['ok'] and d['objects']==1000 and d['cycles']==3 and d['history_retained'] and d['no_op_and_saved_batching'])
 for engine,name in [('godot','evidence/nec017/20261116/godot-scale-builds-a/proof.json'),('unity','evidence/nec017/20261116/unity-scale-builds-b/proof.json'),('unreal','evidence/nec017/20261116/unreal-scale-builds-c/proof.json')]:
  proof(engine+' three actual native data build/readbacks at1,000objects',name,lambda d:d['ok'] and d['objects']==1000 and d['rebuilds']==3 and all(s['player']['ok'] and s['player']['objects']==1000 and s['player']['exported'] for s in d['samples']) and not d['gameplay_runtime_scale_certified'])
 for engine,name in [('godot','evidence/nec017/20261106/godot-existing-play-b/proof.json'),('unity','evidence/nec017/20261116/unity-existing-play-e/proof.json'),('unreal','evidence/nec017/20261116/unreal-cooked-integrity-c/proof.json')]:proof(engine+' imported real native Play/build/gameplay',name)
 for engine,name in [('godot','evidence/nec017/20261116/godot-existing-continuity-b/proof.json'),('unity','evidence/nec017/20261116/unity-imported-continuity-a/proof.json'),('unreal','evidence/nec017/20261116/unreal-short-build-b/proof.json')]:proof(engine+' imported archive/restore/native rebuild/gameplay',name)
 for engine,attempt in [('godot','c'),('unity','b'),('unreal','b')]:
  proof(engine+' integrated existing-project native identity/refusal/conflict/Play-again chain','evidence/nec017/20261116/'+engine+'-existing-workflow-'+attempt+'/proof.json',lambda d:d['ok'] and len(d['native_mutations'])==5 and d['native_edit_and_canonical_conflict_refused'] and d['explicit_resolution_and_reviewed_restore'] and d['gameplay_execution_replay']['replayed_ticks']==12 and d['native_play_again_build']['ok'])
 native_sources={}
 for engine,attempt,prefix,target in [('godot','c','adapters/godot/authoring','addons/xace_authoring'),('unity','b','adapters/unity/Authoring','Assets/XaceAuthoring'),('unreal','b','adapters/unreal/Authoring','Plugins/XACEAuthoring')]:
  fixture=ROOT/'evidence/nec017/20261116'/(engine+'-existing-workflow-'+attempt)/'project'
  for source in (ROOT/prefix).rglob('*'):
   if not source.is_file():continue
   if engine=='godot' and source.name=='plugin.cfg':continue # Explicit test-only subclass; production reader/writer/plugin implementation still exact.
   copied=fixture/target/source.relative_to(ROOT/prefix);assert copied.is_file() and sha(source)==sha(copied),'Native authoring source differs: '+str(source)
   native_sources[source.relative_to(ROOT).as_posix()]=sha(source)
  played=ROOT/'evidence/nec017/20261116'/(engine+'-existing-workflow-'+attempt)/'play-again/source-pins.json'
  if played.exists():
   for name,expected in json.loads(played.read_bytes()).items():
    if name.startswith('adapters/') or name.startswith('packages/project-system/'):
     assert sha(ROOT/name)==expected,'Native Play production source differs: '+name;native_sources[name]=expected
 checks.append(dict(cell='Current production authoring/native Play source copies',status='PASS',files=len(native_sources),godot_test_plugin_cfg_explicit=True))
 seal=verify_seal();(out/'seal.json').write_text(json.dumps(seal,indent=2));checks.append(dict(cell='Recovered XP022 immutable baseline',status='PASS',protected_files=len(seal['protected_files']),source_archive_entries=seal['source_archive_entries'],original_seal=False,manifest_sha256=seal['baseline_manifest_sha256']))
 checks.append(dict(cell='External clean-machine/signing/tester/network/Steam certification',status='EXTERNAL_OPEN',reason='User-deferred availability; required for release; no pass claimed'))
 checks.append(dict(cell='p95 capture/review under2seconds',status='DEFERRED',reason='Only dated conditional-user-decision acceptance amendment; actual timings retained, target not passed'))
 tracked=[n for n in subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode('utf-8').split('\0') if n];tree={}
 for name in tracked:
  path=ROOT/name;assert path.is_file() and not path.is_symlink(),'Missing/link tracked file: '+name;tree[name]=sha(path)
 tree_bytes=json.dumps(tree,sort_keys=True,separators=(',',':')).encode();(out/'tracked-worktree-source-manifest.json').write_text(json.dumps(tree,sort_keys=True,indent=2))
 open_cells=[c for c in checks if c['status']=='OPEN'];result=dict(schema='xace.nec017.acceptance_audit.v1',source_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),local_acceptance_complete=not open_cells,release_certified=False,tracked_worktree_files=len(tree),tracked_worktree_digest=hashlib.sha256(tree_bytes).hexdigest(),checks=checks,open_cells=open_cells,references=references,native_source_hashes=native_sources,source_hashes=pins,shared_launcher_source_hashes=d['source_files'] if 'source_files' in d else json.loads(shared.read_bytes())['source_files'],launcher_sha256=sha(launcher),raw_artifacts_off_device=False,nec018_started=False)
 (out/'audit.json').write_text(json.dumps(result,indent=2));print(json.dumps(dict(passed=sum(c['status']=='PASS' for c in checks),open_cells=open_cells,local_acceptance_complete=not open_cells),indent=2))
if __name__=='__main__':main(Path(sys.argv[1]))
