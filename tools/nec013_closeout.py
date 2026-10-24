"""Collect immutable NEC-013 local acceptance evidence; never certifies clean machine."""
from pathlib import Path
import hashlib,json,shutil,subprocess
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 out=ROOT/'docs/evidence/nec013-local-acceptance-20261024';assert not out.exists()
 day=ROOT/'evidence/nec013/20261024'
 cases=['playback-editor-d','build-preflight-e','player-final-e','player-update-final-e','player-scene-c','player-crash-a']
 for name in cases:assert json.loads((day/name/'proof.json').read_text(encoding='utf-8-sig'))['ok'],name
 sources=json.loads((day/'build-preflight-e/sources.json').read_text())
 assert all(sha(ROOT/p)==h for p,h in sources.items()),'Production adapter drift after final build'
 assert json.loads((day/'playback-editor-d/sources.json').read_text())==sources
 out.mkdir(parents=True);(out/'.gitattributes').write_text('* -text\n')
 records=[]
 def copy(p,dest):
  target=out/dest;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
  records.append(dict(source=str(p),path=dest,sha256=sha(p),bytes=p.stat().st_size))
 for name in cases:
  for p in sorted((day/name).glob('*.json')):copy(p,name+'/'+p.name)
 for p in sorted((day/'build-preflight-e/project/XACEEvidence/builds').glob('*.json')):copy(p,'build-receipts/'+p.name)
 copy(day/'build-preflight-e/project/XACEApproval.json','source-approval.json')
 copy(day/'reference-tests-a/tests.log','reference-tests.log')
 copy(day/'playback-editor-d/editor.log','editor-final.log')
 for name in ['nec013-reference-presentation-a','nec013-reference-admission-b']:
  for p in sorted((ROOT/'evidence/nec011/20261024'/name).glob('*.json')):copy(p,name+'/'+p.name)
 copy(ROOT/'evidence/nec011/20261024/nec013-closeout-seal-a.json','seal-integrity.json')
 for f in ['native-release.json','executor-receipt.json','package/playable.manifest.json']:
  copy(day/'playback-package-c/release'/f,'release/'+f)
 paths=list((ROOT/'adapters/unity').glob('*.cs'))+list((ROOT/'tools').glob('*nec013*.py'))+list((ROOT/'tools').glob('NEC013*.cs'))+[ROOT/'tools/nec011_reference_admission.py',ROOT/'examples/reference-mechanic/src/lib.rs',ROOT/'examples/reference-mechanic/tests/proof.rs']
 identity={p.relative_to(ROOT).as_posix():dict(checkout_sha256=sha(p),git_blob=subprocess.check_output(['git','hash-object','--path',p.relative_to(ROOT).as_posix(),str(p)],cwd=ROOT,text=True).strip()) for p in sorted(paths)}
 (out/'source-identities.json').write_text(json.dumps(identity,indent=2))
 (out/'copied-evidence.json').write_text(json.dumps(records,indent=2))
 summary=dict(schema='xace.nec013.local_acceptance.v1',status='local_declared_profile_verified_clean_machine_blocked',task_complete=False,previous_checkpoint='c987a80',cases=cases,rust_tests_passed=22,rust_tests_filtered=['endurance_route_stays_on_fixture_floor_past_previous_failure_tick'],independent_executor_builds=2,executor_sha256='1ebd23b90c64f40c76fd19bb97abe053b1befa92e4c677bcabbe98ad458bab9d',limitations_document='docs/NEC013_UNITY_STATUS.md',mandatory_remaining=['Same inventoried package on clean offline Windows without XACE/development tools; retain environment and execution evidence'],external_release_gates='signing, first-time tester, external networking, Steam unverified',invalidated_attempts={'player-playback-b':'Missing live player presentation variant; headless startup did not exercise ticket creation','player-update-a':'Same missing presentation variant; excluded','build-preflight-d':'Editor test assembly could not access internal serializer; fixture corrected in e','playback-package-a':'Custom event name not accepted by fixed semantic binding catalog; not an unrestricted event extension proof'},notes=['Scene reload proves fail-stop, not seamless continuation','Update retains sentinel bytes; save checks do not restore or migrate gameplay','AudioSource/Animation execution observed; no human audible-output certification','Unity Editor search indexing exceptions occurred in c and final d inside UnityEditor.Search; native gameplay assertions and all three cycles passed, logs retained; editor-internal warning remains','No historical evidence or sealed baseline modified'],backup='Source and compact evidence checkpoint pending push; raw binaries/native fixtures and sealed archives local-only')
 (out/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary))
if __name__=='__main__':main()
