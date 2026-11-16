"""Whole signed-delivery/handoff contract path, with INERT vendor-byte fixtures.
No fixture is executed as a game, launcher or runtime. No real signing gate passes.
"""
from pathlib import Path
import json,shutil,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'packages/project-system')]
from native_artifact_signing import finalize_native,verify_native,MANIFEST
from release_handoff import *
from native_executor_contract import digest
from tools.nec018_prepare_signed import prepare
from windows_authenticode import inspect,POLICY

def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec018') and not out.exists();out.mkdir(parents=True)
 vendor=Path(sys.executable);signature=inspect(vendor);policy=dict(schema='xace.publisher_policy.v1',trust_policy=POLICY,allowed_signer_certificate_sha256=[signature['signer_certificate_sha256']]);common=ROOT/'evidence/nec018/20261116/signed-proof-b/SIGNED-INERT-FIXTURE-NOT-A-GAME';unsigned=(ROOT/'evidence/nec018/20261116/signed-proof-b/INERT-VERIFIER-FIXTURE-NOT-A-GAME/xace-player-launcher.exe').read_bytes()
 context=out/'UNSIGNED-INERT-CONTEXT';context.mkdir();profiles={};signed_inputs={};checks={}
 for engine in PROFILES:
  source=context/'payload'/engine;source.mkdir(parents=True);(source/'Game.exe').write_bytes(unsigned);(source/'NOTICE.txt').write_text('Inert verifier-only fixture; never execute.',encoding='utf-8');shutil.copytree(common,source/'release')
  if engine=='unreal':(source/'XACEBuild.json').write_bytes(canonical(dict(schema='xace.unreal.cooked_files.v1',unreal='5.7.4-VERIFIER-ONLY',files={n:r['sha256'] for n,r in tree(source).items()})))
  before=tree(source);target=out/(engine+'-SIGNED-INERT');receipt=finalize_native(source,target,engine=engine,expected_unsigned_inventory_sha256=digest(before),policy=policy,expected_policy_sha256=digest(policy),replacements={'Game.exe':str(vendor)});pin=sha(target/MANIFEST)
  verify_native(target,pin);assert tree(source)==before
  profiles[engine]=dict(engine_version=PROFILES[engine][0],objects=PROFILES[engine][1],root='payload/'+engine,entry='Game.exe',argv=['--INERT-DO-NOT-RUN','{report}'],files=before,native_proof_sha256='f'*64,game_id='inert-'+engine,save_policy='exact_admission_or_unchanged_refusal_no_state_restore')
  signed_inputs[engine]=dict(root=str(target),signed_delivery_sha256=pin,common_release_root='release',common_release_sha256=sha(target/'release/native-release.json'),required_signed_executables=['Game.exe'])
  # Mutate a separate negative copy; retain the passing derivative intact.
  negative=out/(engine+'-TAMPERED-INERT');shutil.copytree(target,negative);(negative/'NOTICE.txt').write_bytes(b'wrong notice');r=json.loads((negative/MANIFEST).read_bytes());files=tree(negative);files.pop(MANIFEST);r['files']=files;(negative/MANIFEST).write_bytes(canonical(r))
  try:verify_native(negative,sha(negative/MANIFEST));raise AssertionError('Unrelated edit accepted')
  except ValueError:checks[engine]=dict(native_derivation_passed=True,unrelated_edit_refused=True,positive_copy_retained=True)
 tools={}
 for original,name in [('nec018_collect_environment.ps1','Collect-Environment.ps1'),('nec018_run_native_checks.ps1','Run-NativeChecks.ps1')]:shutil.copyfile(ROOT/'tools'/original,context/name);tools[name]=sha(context/name)
 m=dict(schema=SCHEMA,classification='unsigned_private_engineering_not_release_certified',source_commit='a'*40,development_machine_id='d'*64,profiles=profiles,tools=tools,required_gates=list(GATES),limitations=['INERT synthetic creator/engine metadata for contract testing only; never run as gameplay'])
 (context/'candidate.json').write_bytes(canonical(m));config=out/'TEST-ONLY-inputs.json';config.write_bytes(canonical(dict(schema='xace.nec018.signed_handoff_inputs.v1',unsigned_handoff_root=str(context),unsigned_candidate_sha256=sha(context/'candidate.json'),publisher_policy=policy,native_verifier=str(ROOT/'evidence/nec018/20261116/signed-proof-b/native-verifier.exe'),native_verifier_sha256=sha(ROOT/'evidence/nec018/20261116/signed-proof-b/native-verifier.exe'),profiles=signed_inputs)))
 destination=out/'INERT-HANDOFF-DO-NOT-EXECUTE';prepare(config,sha(config),destination);prepared=json.loads((destination/'preparation.json').read_bytes());verify_handoff(destination/'handoff',prepared['candidate_digest'],native_verifier=ROOT/'evidence/nec018/20261116/signed-proof-b/native-verifier.exe',native_verifier_sha256=sha(ROOT/'evidence/nec018/20261116/signed-proof-b/native-verifier.exe'))
 ledger=json.loads((destination/'gate-ledger.json').read_bytes());assert set(ledger['gates'].values())=={'OPEN'};manifest=json.loads((destination/'handoff/candidate.json').read_bytes());assert any('INERT' in item for item in manifest['limitations'])
 result=dict(schema='xace.nec018.signed_handoff_contract_proof.v1',ok=True,real_windows_signature_native_common_and_delivery_verification=True,all_three_delivery_layouts=checks,signed_archive_preparation_verified=True,original_limits_retained=True,all_gates_remain_open=True,inert_fixture_executed=False,synthetic_creator_and_engine_metadata=True,actual_signed_xace_gameplay=False,clean_machine_certified=False,release_certified=False)
 (out/'proof.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))
if __name__=='__main__':main(Path(sys.argv[1]))
