"""Finalize a NEW common native release from separately signed PE copies."""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'packages/project-system'))
from signed_release import finalize

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for name in ['source','output','policy','unsigned-launcher','signed-launcher','signed-executor','verifier']:p.add_argument('--'+name,type=Path,required=True)
 for name in ['expected-release-sha256','expected-policy-sha256','expected-unsigned-launcher-sha256','expected-verifier-sha256','version']:p.add_argument('--'+name,required=True)
 a=p.parse_args();r=finalize(a.source,a.output,expected_release_sha256=a.expected_release_sha256,policy=json.loads(a.policy.read_bytes()),expected_policy_sha256=a.expected_policy_sha256,unsigned_launcher=a.unsigned_launcher,expected_unsigned_launcher_sha256=a.expected_unsigned_launcher_sha256,signed_launcher=a.signed_launcher,signed_executor=a.signed_executor,verifier=a.verifier,expected_verifier_sha256=a.expected_verifier_sha256,version=a.version)
 proof=a.output.parent/(a.output.name+'-finalization.json')
 with proof.open('x',encoding='utf-8') as stream:json.dump(r,stream,indent=2)
 print(json.dumps(r,indent=2))
if __name__=='__main__':main()
