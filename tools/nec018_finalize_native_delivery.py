"""Create or verify a signed native delivery COPY, retaining old build evidence."""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'packages/project-system'))
from native_artifact_signing import finalize_native,verify_native,MANIFEST
from release_handoff import sha

def main():
 p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
 f=sub.add_parser('finalize')
 for name in ['source','output','policy','replacements']:f.add_argument('--'+name,type=Path,required=True)
 f.add_argument('--engine',choices=['godot','unity','unreal'],required=True)
 for name in ['expected-unsigned-inventory-sha256','expected-policy-sha256']:f.add_argument('--'+name,required=True)
 v=sub.add_parser('verify');v.add_argument('--source',type=Path,required=True);v.add_argument('--expected-receipt-sha256',required=True);a=p.parse_args()
 if a.action=='verify':r=verify_native(a.source,a.expected_receipt_sha256);pin=a.expected_receipt_sha256
 else:
  r=finalize_native(a.source,a.output,engine=a.engine,expected_unsigned_inventory_sha256=a.expected_unsigned_inventory_sha256,policy=json.loads(a.policy.read_bytes()),expected_policy_sha256=a.expected_policy_sha256,replacements=json.loads(a.replacements.read_bytes()));pin=sha(a.output/MANIFEST)
 print(json.dumps(dict(status=r['status'],receipt_sha256=pin,engine=r['engine'],files=len(r['files']),signed_executables=list(r['signed_executables']),release_certified=False),indent=2))
if __name__=='__main__':main()
