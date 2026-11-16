"""Real Windows trust and native v2 admission proof, never a signed-game proof.

The positive v2 fixture uses an existing vendor PE as inert bytes, with explicit
synthetic creator receipts. It is NEVER launched as runtime or game/launcher.
"""
from pathlib import Path
import copy,json,os,shutil,struct,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'packages/project-system')]
import native_executor_contract as contract
import playable_package as pp
from release_handoff import tree,sha
from signed_release import finalize,native_verify
import windows_authenticode as windows
from tools.nec012_lifecycle_proof import Host

BASES={
 'godot':ROOT/'evidence/nec017/20261116/godot-existing-workflow-c/play-again/relocated/release',
 'unity':ROOT/'evidence/nec017/20261116/unity-existing-workflow-b/play-again/shipping/NativeGame_Data/StreamingAssets/XACERelease',
 'unreal':ROOT/'evidence/nec017/20261116/unreal-existing-workflow-b/play-again/archive/Windows/NEC015/release'}

def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec018') and not out.exists();out.mkdir(parents=True)
 verifier=out/'native-verifier.exe';shutil.copyfile('C:/Users/ankit/XACE-Recovery/build-output/cargo/debug/xace-player-launcher.exe',verifier);verifier_hash=sha(verifier)
 vendor=Path(sys.executable);raw=vendor.read_bytes();python=windows.inspect(vendor)
 result=subprocess.run([str(verifier),'--authenticode-inspect','--source',str(vendor)],capture_output=True,text=True,timeout=30);(out/'vendor-native-inspection.json').write_text(result.stdout,encoding='utf-8');assert json.loads(result.stdout)==python
 # Derive inert unsigned comparison bytes from the existing signed vendor file.
 # This is NOT a claim about its real build process or our gameplay compilation.
 from pe_derivation import layout
 checksum,security=layout(raw);offset,size=struct.unpack_from('<II',raw,security);unsigned=bytearray(raw[:offset]);struct.pack_into('<I',unsigned,checksum,0);unsigned[security:security+8]=b'\0'*8
 source=out/'INERT-VERIFIER-FIXTURE-NOT-A-GAME';shutil.copytree(BASES['godot'],source)
 receipt=json.loads((source/'executor-receipt.json').read_bytes());receipt['executor_id']='test-only.inert-signature-fixture.v1';receipt['executable_sha256']=contract.sha(unsigned);receipt['shipping']['required_files']['runtime/xace_runtime.exe']=receipt['executable_sha256']
 for build in receipt['build']['independent_outputs']:build['executable_sha256']=receipt['executable_sha256']
 compiled,_=pp.compiled_artifacts(json.loads((source/'package/game.cgs.json').read_bytes()));old_files={p:(source/'package'/p).read_bytes() for p in tree(source/'package')};old_manifest=json.loads(old_files['playable.manifest.json'])
 support=pp.RuntimeSupport(receipt['executable_sha256'],receipt['compatibility']['runtime_abi'],tuple(receipt['systems']),tuple(receipt['compatibility']['geometry_profiles']),tuple(receipt['compatibility']['world_versions']))
 package=pp.read_archive(pp.build_package(json.loads(old_files['game.cgs.json']),old_files['execution_plan.json'],bytes(unsigned),support,package_id=old_manifest['package_id'],version='0.18.0',presentation_files={n:b for n,b in old_files.items() if n.startswith('presentation/')}))
 for name,data in package.items():(source/'package'/name).write_bytes(data)
 (source/'executor-receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8');(source/'xace-player-launcher.exe').write_bytes(unsigned);(source/'FIXTURE-NOTICE.txt').write_text('Inert signature-verifier fixture. Never execute. Not a gameplay or creator build proof.',encoding='utf-8')
 native=json.loads((source/'native-release.json').read_bytes());native.update(game_id='nec018-inert-verifier-only',executor_receipt_sha256=sha(source/'executor-receipt.json'),package_manifest_sha256=sha(source/'package/playable.manifest.json'));(source/'native-release.json').write_bytes(contract.canonical(native))
 policy=dict(schema='xace.publisher_policy.v1',trust_policy=windows.POLICY,allowed_signer_certificate_sha256=[python['signer_certificate_sha256']]);before=tree(source)
 args=dict(expected_release_sha256=sha(source/'native-release.json'),policy=policy,expected_policy_sha256=contract.digest(policy),unsigned_launcher=source/'xace-player-launcher.exe',expected_unsigned_launcher_sha256=contract.sha(unsigned),signed_launcher=vendor,signed_executor=vendor,verifier=verifier,expected_verifier_sha256=verifier_hash,version='0.18.1')
 positive=out/'SIGNED-INERT-FIXTURE-NOT-A-GAME';report=finalize(source,positive,**args);assert tree(source)==before and (positive/'FIXTURE-NOTICE.txt').read_bytes()==(source/'FIXTURE-NOTICE.txt').read_bytes()
 (out/'inert-finalization.json').write_bytes(contract.canonical(report));checks={}
 for label,change in [
  ('missing_publisher',lambda n,r:n.pop('publisher_policy')),
  ('unsigned_release_downgrade',lambda n,r:n.update(schema='xace.native_release.v1')),
  ('forged_capability',lambda n,r:r['capabilities'].append('forged.v1')),
  ('changed_original_receipt',lambda n,r:r['derivation']['unsigned_receipt']['source_files'].update({'Cargo.lock':'0'*64})),
  ('unapproved_publisher',lambda n,r:n['publisher_policy'].update(allowed_signer_certificate_sha256=['0'*64])),
  ('wrong_verified_publisher',lambda n,r:(r['derivation'].update(signer_certificate_sha256='b'*64),n['publisher_policy'].update(allowed_signer_certificate_sha256=['b'*64]))),
  ('missing_launcher_derivation',lambda n,r:n.pop('launcher_derivation')),
  ('wrong_launcher_derivation',lambda n,r:n['launcher_derivation'].update(unsigned_sha256='0'*64))]:
  case=out/('refusal-'+label);shutil.copytree(positive,case);n=json.loads((case/'native-release.json').read_bytes());r=json.loads((case/'executor-receipt.json').read_bytes());change(n,r);(case/'executor-receipt.json').write_bytes(contract.canonical(r));n['executor_receipt_sha256']=sha(case/'executor-receipt.json');(case/'native-release.json').write_bytes(contract.canonical(n))
  result=subprocess.run([str(verifier),'--native-verify','--source',str(case),'--expected',sha(case/'native-release.json')],capture_output=True,text=True,timeout=30);record=json.loads(result.stdout);assert record.get('ok') is False,(label,record);checks[label]=record;(case/'refusal.json').write_text(result.stdout,encoding='utf-8')
 for label,modified in [('wrong_policy_pin',dict(expected_policy_sha256='0'*64)),('wrong_unsigned_launcher_pin',dict(expected_unsigned_launcher_sha256='0'*64))]:
  dest=out/('must-not-exist-'+label)
  try:finalize(source,dest,**{**args,**modified});raise AssertionError('Unexpected acceptance')
  except ValueError as e:assert not dest.exists();checks[label]=str(e)
 legacy={}
 for engine,release in BASES.items():
  identity=tree(release);history=out/('legacy-'+engine)/'history';history.parent.mkdir();host=Host(verifier,release,sha(release/'native-release.json'),history)
  try:
   assert host.initial['state']=='stopped',host.initial;assert host.ask('verify')['ok'];live=host.ask('play');assert live['ok'],live;assert host.ask('stop')['ok'];legacy[engine]=dict(actual_authority_started=True,runtime_pid=live['result']['runtime_pid'],clean_shutdown=True)
  finally:host.close()
  assert tree(release)==identity;legacy[engine]['original_release_unchanged']=True
 result=dict(schema='xace.nec018.signed_integration_proof.v1',ok=True,source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),native_verifier_sha256=verifier_hash,actual_vendor_signature=python,python_rust_signer_hash_timestamp_agree=True,real_windows_signed_inert_fixture_admitted=True,inert_fixture_executed=False,synthetic_creator_receipts_only_for_verifier_test=True,creator_finalization_and_notice_preservation=True,refusals=checks,legacy_actual_authority=legacy,publisher_backed_xace_binaries_signed=False,final_three_engine_signed_builds_verified=False,clean_machine_certified=False,release_certified=False)
 (out/'proof.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))
if __name__=='__main__':main(Path(sys.argv[1]))
