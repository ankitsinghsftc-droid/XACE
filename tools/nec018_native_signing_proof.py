"""Native signed-copy rules tested with inert vendor PE bytes, never game execution."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'packages/project-system')]
from native_artifact_signing import finalize_native,verify_native,MANIFEST
from native_executor_contract import canonical,digest
from release_handoff import tree,sha
from windows_authenticode import inspect,POLICY

def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec018') and not out.exists();out.mkdir(parents=True)
 vendor=Path(sys.executable);signature=inspect(vendor);policy=dict(schema='xace.publisher_policy.v1',trust_policy=POLICY,allowed_signer_certificate_sha256=[signature['signer_certificate_sha256']]);unsigned=(ROOT/'evidence/nec018/20261116/signed-proof-b/INERT-VERIFIER-FIXTURE-NOT-A-GAME/xace-player-launcher.exe').read_bytes();checks={}
 for engine in ['godot','unity','unreal']:
  source=out/(engine+'-INERT-NOT-A-GAME');source.mkdir();(source/'Game.exe').write_bytes(unsigned);(source/'NOTICES.txt').write_text('Test-only notice sentinel; retained unchanged.',encoding='utf-8')
  if engine=='unreal':(source/'XACEBuild.json').write_bytes(canonical(dict(schema='xace.unreal.cooked_files.v1',unreal='5.7.4-test-fixture',files={n:r['sha256'] for n,r in tree(source).items()})))
  before=tree(source);target=out/(engine+'-SIGNED-INERT-NOT-A-GAME');args=dict(engine=engine,expected_unsigned_inventory_sha256=digest(before),policy=policy,expected_policy_sha256=digest(policy),replacements={'Game.exe':str(vendor)})
  receipt=finalize_native(source,target,**args);pin=sha(target/MANIFEST);verify_native(target,pin);assert tree(source)==before and (target/'NOTICES.txt').read_bytes()==(source/'NOTICES.txt').read_bytes()
  if engine=='unreal':
   cooked=json.loads((target/'XACEBuild.json').read_bytes());assert cooked['files']['Game.exe']==sha(target/'Game.exe') and MANIFEST not in cooked['files'] and cooked['unreal']=='5.7.4-test-fixture'
  for label,output,modified in [('wrong_unsigned_pin',out/(engine+'-MUST-NOT-EXIST'),dict(expected_unsigned_inventory_sha256='0'*64)),('nested_output',source/'MUST-NOT-EXIST',{})]:
   try:finalize_native(source,output,**{**args,**modified});raise AssertionError('Unexpected acceptance')
   except ValueError:assert not output.exists()
  # A self-consistent final file list must not authorize unrelated source edits.
  (target/'NOTICES.txt').write_bytes(b'changed attribution');changed=json.loads((target/MANIFEST).read_bytes());files=tree(target);files.pop(MANIFEST);changed['files']=files;(target/MANIFEST).write_bytes(canonical(changed))
  try:verify_native(target,sha(target/MANIFEST));raise AssertionError('Unexpected unrelated edit')
  except ValueError:pass
  checks[engine]=dict(actual_windows_signature_verified=True,code_preserving_derivation=True,original_unchanged=True,notice_preserved=True,unsafe_output_and_foreign_pin_refused=True,unrelated_source_edit_refused_even_with_updated_manifest=True,unreal_cooked_inventory_reissued=(engine=='unreal'))
 proof=dict(schema='xace.nec018.native_signing_copy_proof.v1',ok=True,checks=checks,fixture_scope='INERT vendor PE bytes and synthetic checked-build records; not XACE signed games',inert_fixtures_executed=False,actual_native_engine_builds_signed=False,release_certified=False)
 (out/'proof.json').write_text(json.dumps(proof,indent=2),encoding='utf-8');print(json.dumps(proof,indent=2))
if __name__=='__main__':main(Path(sys.argv[1]))
