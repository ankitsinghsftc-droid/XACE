"""Close local handoff preparation only; every external gate remains open."""
from pathlib import Path
import json,shutil,subprocess,sys,zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'packages/project-system')]
from release_handoff import canonical,need,sha,tree,verify_handoff,GATES
from tools.nec011_seal_integrity import verify as verify_seal

def audit(out):
 out=out.resolve();need(out.is_relative_to(ROOT/'evidence/nec018') and not out.exists(),'Fresh persistent audit output required');out.mkdir(parents=True)
 prepared=ROOT/'evidence/nec018/20261116/handoff-b';kit=prepared/'handoff'
 preparation=json.loads((prepared/'preparation.json').read_bytes());pin=preparation['candidate_digest'];manifest=verify_handoff(kit,pin)
 need(sha(prepared/'NEC018-private-engineering.zip')==preparation['archive_sha256'],'Archive changed')
 with zipfile.ZipFile(prepared/'NEC018-private-engineering.zip') as z:
  need(z.testzip() is None,'Archive CRC failure')
  for item in z.infolist():need(sha(kit/item.filename)==__import__('hashlib').sha256(z.read(item)).hexdigest(),'Archive member differs')
 sources=json.loads((prepared/'source-references.json').read_bytes())
 for engine,source in sources.items():need(tree(Path(source['source']))==source['files'],'Original native source changed: '+engine)
 native=json.loads((ROOT/'evidence/nec018/20261116/rehearsal-b/result.json').read_bytes())
 need(native['candidate_digest']==pin and native['technical_checks_passed'] is True,'Native rehearsal did not pass exact candidate')
 need(len(native['runs'])==3 and {r['engine'] for r in native['runs']}=={'godot','unity','unreal'},'Three native launches required')
 need(all(r['technical_pass'] is True and r['exit_code']==0 and r['owned_process_cleanup'] is True and r['installation_unchanged'] is True for r in native['runs']),'Native assertion/cleanup failed')
 need(native['same_development_machine'] is True and all(native[k] is False for k in ['clean_machine_certified','release_certified','steam_certified','human_walkthrough_performed','update_uninstall_matrix_performed']),'Rehearsal overclaims external certification')
 negatives=[]
 # Both failures must occur before evidence-folder creation or any native launch.
 altered=out/'altered-tools';altered.mkdir()
 shutil.copyfile(kit/'candidate.json',altered/'candidate.json')
 for name in manifest['tools']:
  dest=altered/name;dest.parent.mkdir(exist_ok=True,parents=True);shutil.copyfile(kit/name,dest)
 with (altered/'Collect-Environment.ps1').open('ab') as f:f.write(b'\n# deliberate test-only integrity change\n')
 for name,root,expected,message in [('foreign-pin',kit,'0'*64,'independently supplied digest'),('altered-tool',altered,pin,'Handoff tool changed')]:
  evidence=out/(name+'-must-not-exist')
  command=['powershell.exe','-NoProfile','-NonInteractive','-File',str(kit/'Run-NativeChecks.ps1'),'-CandidateRoot',str(root),'-ExpectedCandidateSha256',expected,'-EvidenceRoot',str(evidence),'-Launches','1']
  result=subprocess.run(command,capture_output=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
  raw=result.stdout+result.stderr;(out/(name+'.log')).write_bytes(raw)
  need(result.returncode!=0 and message in raw.decode(errors='replace') and not evidence.exists(),'Integrity failure must precede side effects: '+name)
  negatives.append(dict(name=name,refused=True,before_output_or_launch=True,log_sha256=sha(out/(name+'.log'))))
 seal=verify_seal();(out/'seal-integrity.json').write_bytes(canonical(seal))
 pins=json.loads((ROOT/'evidence/nec018/20261116/verification-c/source-pins.json').read_bytes())
 changed=[name for name,value in pins.items() if sha(ROOT/name)!=value]
 need(set(changed)<={'tools/nec018_prepare.py','tools/nec018_verify.py'},'Unexpected change since passing 385+127 regressions')
 for path in (ROOT/'tools').glob('nec018*.py'):compile(path.read_bytes(),str(path),'exec')
 ledger=json.loads((prepared/'gate-ledger.json').read_bytes());need(ledger['gates']=={gate:'OPEN' for gate in GATES},'External gates must remain open')
 result=dict(schema='xace.nec018.local_handoff_audit.v1',ok=True,status='LOCAL_HANDOFF_PREPARED_NEC018_INCOMPLETE',candidate_digest=pin,candidate_source_commit=manifest['source_commit'],archive_sha256=preparation['archive_sha256'],archive_bytes=preparation['archive_bytes'],project_system_tests=385,schema_factory_tests=127,regression_source_changes=changed,python_entry_points_compile=True,three_native_smoke_launches=True,unchanged_original_native_artifacts=True,negative_integrity_tests=negatives,recovered_xp022_seal_unchanged=True,original_historical_seal_recovered=False,all_external_gates=ledger['gates'],signing_derivation_implemented=False,release_certified=False,steam_certified=False,external_distribution_authorized=False,raw_evidence_off_device=False)
 (out/'result.json').write_bytes(canonical(result));print(json.dumps(result,indent=2))
if __name__=='__main__':audit(Path(sys.argv[1]))
