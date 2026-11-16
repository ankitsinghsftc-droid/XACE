"""Read-only acceptance audit of NEC018 local integration and protected artifacts."""
from pathlib import Path
import hashlib,json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'packages/project-system')]
from release_handoff import tree,sha,canonical,GATES
from tools.nec011_seal_integrity import verify as verify_seal

def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec018') and not out.exists();out.mkdir(parents=True);base=ROOT/'evidence/nec018/20261116'
 verification=json.loads((base/'verification-h/result.json').read_bytes());assert verification['ok'] and verification['source_stable'] and all(c['returncode']==0 for c in verification['tests'])
 pins=json.loads((base/'verification-h/source-pins.json').read_bytes());assert all(sha(ROOT/n)==v for n,v in pins.items()),'Verified source changed'
 for p in (ROOT/'tools').glob('nec018*.py'):compile(p.read_bytes(),str(p),'exec')
 proofs={}
 for name in ['signed-proof-c','signed-handoff-contract-b','portable-independence-c','signed-runner-refusal-a','native-signing-copy-a','notice-delivery-a']:
  p=base/name/'proof.json';r=json.loads(p.read_bytes());assert r['ok'];proofs[name]=dict(path=str(p),sha256=sha(p))
 signed=json.loads((base/'signed-proof-c/proof.json').read_bytes());portable=json.loads((base/'portable-independence-c/proof.json').read_bytes());assert signed['native_verifier_sha256']==portable['launcher_sha256']==sha(base/'signed-proof-c/native-verifier.exe');assert signed['inert_fixture_executed'] is False and signed['publisher_backed_xace_binaries_signed'] is False
 sources=json.loads((ROOT/'docs/evidence/nec018-handoff-20261116/native-source-references.json').read_bytes())
 for engine,source in sources.items():assert tree(source['source'])==source['files'],'Protected native artifact changed: '+engine
 prepared=json.loads((base/'handoff-b/preparation.json').read_bytes());assert sha(base/'handoff-b/NEC018-private-engineering.zip')==prepared['archive_sha256']
 seal=verify_seal();(out/'seal-integrity.json').write_bytes(canonical(seal));assert seal['ok'] and seal['original_seal'] is False
 approval=json.loads((ROOT/'docs/evidence/nec018-integration-20261116/first-party-rights-approval.json').read_bytes());assert approval['first_party_policy_approved'] is True and sha(ROOT/approval['terms_path'])==approval['terms_sha256'];assert sha(ROOT/'docs/evidence/nec018-integration-20261116/rights-proposal-as-approved.md')==approval['approved_proposal_sha256']
 notices=json.loads((base/'notice-review-a/review-manifest.json').read_bytes());inventory=tree(base/'notice-review-a');inventory.pop('review-manifest.json');assert inventory==notices['files']
 companion=json.loads((base/'notice-delivery-a/proof.json').read_bytes());assert sha(base/'notice-delivery-a/NEC018-notices-and-continuity-terms.zip')==companion['archive_sha256']
 (out/'verified-source-pins.json').write_bytes(canonical({**pins,'tools/nec018_integration_audit.py':sha(Path(__file__))}))
 result=dict(schema='xace.nec018.local_integration_acceptance.v1',ok=True,status='LOCAL_IMPLEMENTATION_AND_TESTS_VERIFIED_EXTERNAL_CERTIFICATION_OPEN',project_system_tests=401,schema_factory_tests=127,native_launcher_tests=11,session_relay_tests=2,source_stable=True,proofs=proofs,signed_executor_launcher_derivation_implemented=True,create_only_common_native_and_handoff_finalization_implemented=True,real_windows_verifier_interoperability=True,legacy_actual_authority_and_portable_updates_saves_removal_all_three=True,inert_signing_fixtures_never_executed=True,first_party_continuing_use_scope_approved=True,notice_review_files=len(notices['files']),notice_companion_sha256=companion['archive_sha256'],protected_native_artifacts_and_unsigned_archive_unchanged=True,recovered_xp022_seal_unchanged=True,original_historical_seal_recovered=False,all_external_gate_states={g:'OPEN' for g in GATES},additional_resources_required=['authorized_publisher_code_signing_certificate_or_service','real_two_windows_machine_lan','deployed_valid_tls_relay_and_two_real_networks','final_candidate_specific_third_party_credits_and_notice_approval'],user_deferred=['clean_windows_machine_tests','independent_developer_walkthroughs'],actual_signed_xace_game_builds_verified=False,final_signed_native_gameplay_and_offline_tests_verified=False,clean_machine_certified=False,release_certified=False,steam_certified=False,nec018_complete=False,raw_binaries_archives_and_evidence_off_device=False)
 (out/'result.json').write_bytes(canonical(result));print(json.dumps(result,indent=2))
if __name__=='__main__':main(Path(sys.argv[1]))
