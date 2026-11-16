"""NEC018 immutable private handoff and external-evidence review contracts.
No game execution, signing, certificate purchase or automatic release approval.
"""
from dataclasses import dataclass
from pathlib import Path
import hashlib,json
from continuity_contract import canonical,portable_path,plain,SECRET_NAMES

SCHEMA='xace.nec018.handoff.v1'
GATES=('clean_windows','offline_execution','updates_saves_uninstall','signing','three_developers','external_lan','external_internet','redistribution_approval')
PROFILES={'godot':('4.6.3',50),'unity':('6000.4.9f1',51),'unreal':('5.7.4',50)}
CHECKS={
 'clean_windows':('fresh_os_provisioning_attached','no_builder_or_toolchain','all_three_native_builds','security_controls_unchanged','environment_collection_complete'),
 'offline_execution':('remote_network_blocked','all_three_probe_reports','canonical_state_event_comparisons','owned_process_cleanup','packet_capture_attached'),
 'updates_saves_uninstall':('separate_games_isolated','per_game_saves_preserved','failed_update_retains_active','explicit_rollback_verified','save_migration_or_unchanged_refusal','uninstall_preserves_saves_and_other_games'),
 'signing':('authenticode_chain_valid','publisher_approved','timestamp_valid','signed_identities_reissued','admission_and_launch_rerun'),
 'three_developers':('three_distinct_external_developers','independent_first_time_participants','all_supported_workflows_completed','no_terminal_repair','failures_and_assistance_recorded'),
 'external_lan':('two_distinct_windows_machines','ordinary_invite_join','matching_authority_and_projection','disconnect_rejoin','owned_cleanup'),
 'external_internet':('two_separate_networks','deployed_valid_tls_relay','invite_and_gameplay','loss_reconnect_outage','owned_cleanup'),
 'redistribution_approval':('owner_approval_attached','exact_candidate_approved','redistribution_and_continuing_use_approved','dependency_notices_complete')}
class HandoffError(ValueError):pass

def need(condition,message):
 if not condition:raise HandoffError(message)
def digest_bytes(raw):return hashlib.sha256(raw).hexdigest()
def digest(value):return digest_bytes(canonical(value))
def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as stream:
  for part in iter(lambda:stream.read(1024*1024),b''):h.update(part)
 return h.hexdigest()
def hash_value(value):need(type(value) is str and len(value)==64 and all(c in '0123456789abcdef' for c in value),'SHA256 required')
def tree(root):
 root=Path(root);plain(root);result={}
 def visit(base):
  for p in sorted(base.iterdir()):
   info=plain(p)
   if p.is_dir():visit(p)
   else:
    rel=portable_path(p.relative_to(root).as_posix());need(p.name.casefold() not in SECRET_NAMES,'Sensitive handoff file: '+rel);need(rel.casefold() not in {n.casefold() for n in result},'Aliased handoff path');result[rel]={'sha256':sha(p),'bytes':info.st_size}
 visit(root);need(bool(result),'Empty artifact');return result

def validate(manifest):
 need(type(manifest) is dict and set(manifest)=={'schema','classification','source_commit','development_machine_id','profiles','tools','required_gates','limitations'},'Invalid handoff fields')
 need(manifest['schema']==SCHEMA and manifest['classification']=='unsigned_private_engineering_not_release_certified','Not an approved handoff class')
 need(type(manifest['source_commit']) is str and len(manifest['source_commit'])==40 and all(c in '0123456789abcdef' for c in manifest['source_commit']),'Git source identity required');hash_value(manifest['development_machine_id'])
 need(manifest['required_gates']==list(GATES),'Mandatory gate set changed');need(type(manifest['limitations']) is list and manifest['limitations'],'Support limits required')
 need(type(manifest['profiles']) is dict and set(manifest['profiles'])==set(PROFILES),'All three engine profiles required')
 for engine,p in manifest['profiles'].items():
  need(type(p) is dict and set(p)=={'engine_version','objects','root','entry','argv','files','native_proof_sha256','game_id','save_policy'},'Invalid profile fields')
  need((p['engine_version'],p['objects'])==PROFILES[engine],'Unsupported engine/profile');need(p['root']=='payload/'+engine,'Invalid payload root');portable_path(p['entry']);need(p['entry'].lower().endswith('.exe'),'Native executable required');hash_value(p['native_proof_sha256'])
  need(type(p['argv']) is list and p['argv'] and all(type(v) is str and '"' not in v and not any(c in v for c in ['\r','\n','\0']) for v in p['argv']),'Fixed native argument vector required')
  need(any('{report}' in v for v in p['argv']),'Structured native report required');need(all('{' not in v.replace('{report}','').replace('{log}','') and '}' not in v.replace('{report}','').replace('{log}','') for v in p['argv']),'Unknown argument placeholder')
  need(type(p['files']) is dict and p['entry'] in p['files'],'Native file inventory required');aliases=set()
  for name,row in p['files'].items():
   portable_path(name);need(name.casefold() not in aliases,'Aliased native path');aliases.add(name.casefold());need(type(row) is dict and set(row)=={'bytes','sha256'} and type(row['bytes']) is int and row['bytes']>=0,'Invalid file identity');hash_value(row['sha256'])
  need(type(p['game_id']) is str and p['game_id'] and all(c in 'abcdefghijklmnopqrstuvwxyz0123456789-_' for c in p['game_id']),'Stable per-game identity required');need(p['save_policy']=='exact_admission_or_unchanged_refusal_no_state_restore','Unsupported save claim')
 need(len({p['game_id'] for p in manifest['profiles'].values()})==3,'Separate fixture game identities required')
 for name,value in manifest['tools'].items():portable_path(name);hash_value(value)
 need({'Run-NativeChecks.ps1','Collect-Environment.ps1'}<=set(manifest['tools']),'Self-contained Windows tools required')
 return manifest

def verify_handoff(root,expected_digest):
 root=Path(root);hash_value(expected_digest);p=root/'candidate.json';plain(p);raw=p.read_bytes();need(digest_bytes(raw)==expected_digest,'Candidate differs from independently trusted digest');m=validate(json.loads(raw))
 for engine,profile in m['profiles'].items():need(tree(root/profile['root'])==profile['files'],'Payload changed: '+engine)
 for name,value in m['tools'].items():need(sha(root/name)==value,'Handoff tool changed: '+name)
 return m

@dataclass(frozen=True)
class ReviewContext:
 candidate_digest:str
 allowed_reviewer_ids:frozenset[str]
 trusted_evidence_digests:frozenset[str]


def assess_evidence(manifest,evidence,context):
 """Caller-reviewed digest is authority, not a PASS string in supplied JSON.
 Eligibility for owner review never equals release certification or human identity proof.
 """
 validate(manifest);hash_value(context.candidate_digest);need(digest(manifest)==context.candidate_digest,'Different candidate context')
 need(type(evidence) is dict and set(evidence)=={'schema','candidate_digest','gate','reviewer_id','machine_id','outcome','checks','attachments'},'Invalid external evidence')
 need(evidence['schema']=='xace.nec018.external_evidence.v1','Unsupported evidence schema');need(evidence['candidate_digest']==context.candidate_digest,'Evidence for another candidate');need(evidence['gate'] in GATES,'Unknown gate')
 need(evidence['reviewer_id'] in context.allowed_reviewer_ids and digest(evidence) in context.trusted_evidence_digests,'Evidence not independently reviewed and pinned');hash_value(evidence['machine_id']);need(evidence['outcome']=='pass' and type(evidence['checks']) is dict and set(evidence['checks'])==set(CHECKS[evidence['gate']]) and all(v is True for v in evidence['checks'].values()),'Failed/unknown/missing checks remain open')
 need(type(evidence['attachments']) is dict and evidence['attachments'],'Evidence attachments required')
 for name,value in evidence['attachments'].items():portable_path(name);hash_value(value)
 if evidence['gate'] in ['clean_windows','offline_execution','updates_saves_uninstall']:
  need(evidence['machine_id']!=manifest['development_machine_id'],'Development laptop is not a clean-machine proof')
 if evidence['gate']=='signing':raise HandoffError('Unsigned candidate cannot close signing; signed-derivation/admission and new exact candidate required')
 return dict(status='eligible_for_owner_review',gate=evidence['gate'],candidate_digest=context.candidate_digest,release_certified=False,attachments_require_manual_validation=True)

def initial_ledger(manifest):
 validate(manifest)
 return dict(schema='xace.nec018.gates.v1',candidate_digest=digest(manifest),gates={gate:'OPEN' for gate in GATES},clean_machine_certified=False,release_certified=False,steam_certified=False,three_engine_alpha_approved=False)
