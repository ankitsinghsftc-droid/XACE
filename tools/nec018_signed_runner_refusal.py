"""Signed-runner publisher refusal before any inert fixture can be executed."""
from pathlib import Path
import json,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'packages/project-system')]
from release_handoff import sha,canonical

def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec018') and not out.exists();out.mkdir(parents=True)
 original=ROOT/'evidence/nec018/20261116/signed-handoff-contract-a/INERT-HANDOFF-DO-NOT-EXECUTE/handoff';kit=out/'WRONG-PUBLISHER-INERT-KIT';shutil.copytree(original,kit)
 # Update only the test kit's pinned runner to the exact current source version.
 shutil.copyfile(ROOT/'tools/nec018_run_native_checks.ps1',kit/'Run-NativeChecks.ps1');m=json.loads((kit/'candidate.json').read_bytes());m['tools']['Run-NativeChecks.ps1']=sha(kit/'Run-NativeChecks.ps1');m['publisher_policy']['allowed_signer_certificate_sha256']=['b'*64];(kit/'candidate.json').write_bytes(canonical(m))
 evidence=out/'refusal';r=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-File',str(kit/'Run-NativeChecks.ps1'),'-CandidateRoot',str(kit),'-ExpectedCandidateSha256',sha(kit/'candidate.json'),'-EvidenceRoot',str(evidence),'-Launches','1'],capture_output=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW);(out/'runner.log').write_bytes(r.stdout+r.stderr)
 result=json.loads((evidence/'result.json').read_bytes());assert r.returncode!=0 and result['technical_checks_passed'] is False and not result['runs'] and 'Publisher differs' in result['failure'],result;assert not (evidence/'godot-0').exists()
 proof=dict(schema='xace.nec018.signed_runner_refusal.v1',ok=True,wrong_publisher_refused_before_native_launch=True,inert_fixture_executed=False,release_certified=False);(out/'proof.json').write_bytes(canonical(proof));print(json.dumps(proof,indent=2))
if __name__=='__main__':main(Path(sys.argv[1]))
