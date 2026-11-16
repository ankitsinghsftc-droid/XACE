from pathlib import Path
import copy,json,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'packages/project-system'))
from release_handoff import *
class HandoffTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  profiles={}
  for engine,(version,objects) in PROFILES.items():
   base=self.root/'payload'/engine;base.mkdir(parents=True);(base/'Game.exe').write_bytes(('non-executable fixture '+engine).encode());profiles[engine]=dict(engine_version=version,objects=objects,root='payload/'+engine,entry='Game.exe',argv=['--report','{report}'],files=tree(base),native_proof_sha256='b'*64,game_id='fixture-'+engine,save_policy='exact_admission_or_unchanged_refusal_no_state_restore')
  tools={}
  for name in ['Run-NativeChecks.ps1','Collect-Environment.ps1']:(self.root/name).write_bytes(b'fixture, never execute');tools[name]=sha(self.root/name)
  self.m=dict(schema=SCHEMA,classification='unsigned_private_engineering_not_release_certified',source_commit='a'*40,development_machine_id='d'*64,profiles=profiles,tools=tools,required_gates=list(GATES),limitations=['runtime dependency retained']);self.pin=digest(self.m);(self.root/'candidate.json').write_bytes(canonical(self.m))
 def evidence(self,gate='clean_windows',machine='e'*64):
  return dict(schema='xace.nec018.external_evidence.v1',candidate_digest=self.pin,gate=gate,reviewer_id='person-1',machine_id=machine,outcome='pass',checks={name:True for name in CHECKS[gate]},attachments={'environment.json':'a'*64})
 def context(self,e):return ReviewContext(self.pin,frozenset({'person-1'}),frozenset({digest(e)}))
 def test_exact_candidate_payload_and_tools(self):self.assertEqual(verify_handoff(self.root,self.pin),self.m)
 def test_candidate_cannot_self_authorize(self):
  with self.assertRaisesRegex(HandoffError,'trusted digest'):verify_handoff(self.root,'f'*64)
 def test_modified_payload_refused(self):
  (self.root/'payload/unity/Game.exe').write_bytes(b'changed')
  with self.assertRaisesRegex(HandoffError,'Payload changed'):verify_handoff(self.root,self.pin)
 def test_extra_payload_refused(self):
  (self.root/'payload/godot/extra.dll').write_bytes(b'new')
  with self.assertRaisesRegex(HandoffError,'Payload changed'):verify_handoff(self.root,self.pin)
 def test_tool_replacement_refused(self):
  (self.root/'Run-NativeChecks.ps1').write_bytes(b'changed')
  with self.assertRaisesRegex(HandoffError,'tool changed'):verify_handoff(self.root,self.pin)
 def test_secret_file_refused(self):
  (self.root/'payload/unreal/native-ticket.json').write_bytes(b'private')
  with self.assertRaisesRegex(HandoffError,'Sensitive'):verify_handoff(self.root,self.pin)
 def test_unsafe_or_aliased_paths_refused(self):
  for name in ['../escape','CON.exe','a\\b','x:stream','name.','/absolute']:
   m=copy.deepcopy(self.m);m['profiles']['unity']['files'][name]={'sha256':'a'*64,'bytes':1}
   with self.subTest(name=name),self.assertRaises(ValueError):validate(m)
  m=copy.deepcopy(self.m);m['profiles']['unity']['files']['GAME.EXE']={'sha256':'a'*64,'bytes':1}
  with self.assertRaisesRegex(HandoffError,'Aliased'):validate(m)
 def test_no_missing_engine_or_weakened_gate_set(self):
  m=copy.deepcopy(self.m);del m['profiles']['unity']
  with self.assertRaises(HandoffError):validate(m)
  m=copy.deepcopy(self.m);m['required_gates'].remove('signing')
  with self.assertRaises(HandoffError):validate(m)
 def test_same_machine_cannot_be_clean(self):
  e=self.evidence(machine='d'*64)
  with self.assertRaisesRegex(HandoffError,'Development laptop'):assess_evidence(self.m,e,self.context(e))
 def test_unreviewed_or_foreign_candidate_claim_refused(self):
  e=self.evidence()
  with self.assertRaisesRegex(HandoffError,'reviewed'):assess_evidence(self.m,e,ReviewContext(self.pin,frozenset({'person-1'}),frozenset()))
  e['candidate_digest']='c'*64
  with self.assertRaisesRegex(HandoffError,'another candidate'):assess_evidence(self.m,e,self.context(e))
 def test_unknown_and_failed_checks_refused(self):
  for value in [False,None,'true',1]:
   e=self.evidence();e['checks']['fresh_os_provisioning_attached']=value
   with self.subTest(value=value),self.assertRaises(HandoffError):assess_evidence(self.m,e,self.context(e))
 def test_signing_cannot_be_claimed_for_unsigned_kit(self):
  e=self.evidence('signing')
  with self.assertRaisesRegex(HandoffError,'Unsigned candidate'):assess_evidence(self.m,e,self.context(e))
 def test_review_eligibility_is_not_certification(self):
  e=self.evidence();result=assess_evidence(self.m,e,self.context(e));self.assertFalse(result['release_certified']);self.assertTrue(result['attachments_require_manual_validation']);self.assertEqual(result['status'],'eligible_for_owner_review')
 def test_initial_ledger_never_passes_external_gates(self):
  result=initial_ledger(self.m);self.assertEqual(set(result['gates'].values()),{'OPEN'});self.assertFalse(result['steam_certified']);self.assertFalse(result['three_engine_alpha_approved'])
 def test_unknown_argument_interpolation_refused(self):
  m=copy.deepcopy(self.m);m['profiles']['unity']['argv'].append('{execute_arbitrary_script}')
  with self.assertRaisesRegex(HandoffError,'placeholder'):validate(m)
class SignedHandoffTests(unittest.TestCase):
 setUp=HandoffTests.setUp
 def signed_manifest(self):
  from signed_executor import POLICY
  m=copy.deepcopy(self.m);m.update(schema=SIGNED_SCHEMA,classification='signed_private_engineering_not_release_certified',publisher_policy=dict(schema='xace.publisher_policy.v1',trust_policy=POLICY,allowed_signer_certificate_sha256=['a'*64]))
  for p in m['profiles'].values():p.update(signed_delivery_sha256='c'*64,common_release_root='release',common_release_sha256='e'*64,required_signed_executables=['Game.exe'],native_proof_scope='unsigned_context_only_fresh_signed_execution_required')
  return m
 def test_signed_schema_is_explicit_and_retains_open_gates(self):
  m=self.signed_manifest();self.assertEqual(validate(m),m);self.assertEqual(set(initial_ledger(m)['gates'].values()),{'OPEN'})
 def test_signed_declaration_without_real_native_verification_refused(self):
  m=self.signed_manifest();(self.root/'candidate.json').write_bytes(canonical(m))
  with self.assertRaisesRegex(HandoffError,'native verifier'):verify_handoff(self.root,digest(m))
 def test_signed_handoff_cannot_relabel_prior_unsigned_proofs(self):
  m=self.signed_manifest();m['profiles']['godot']['native_proof_scope']='already_signed_and_certified'
  with self.assertRaisesRegex(HandoffError,'relabel'):validate(m)
 def test_signed_profile_requires_entry_signature_and_approved_policy(self):
  m=self.signed_manifest();m['profiles']['unity']['required_signed_executables']=[]
  with self.assertRaises(HandoffError):validate(m)
  m=self.signed_manifest();m['publisher_policy']['allowed_signer_certificate_sha256']=[]
  with self.assertRaises(ValueError):validate(m)
if __name__=='__main__':unittest.main()
