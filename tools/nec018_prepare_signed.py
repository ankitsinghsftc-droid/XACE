"""Prepare a new v2 handoff ONLY from reviewed signed native delivery copies.

Needs a certificate-backed signed common release and final engine-signed files;
this tool does not sign, procure credentials or approve any release gate.
"""
from pathlib import Path
import copy,json,shutil,subprocess,sys,zipfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'packages/project-system'))
from release_handoff import verify_handoff,tree,sha,canonical,digest,initial_ledger,need,SIGNED_SCHEMA
from signed_executor import publisher_policy
from native_artifact_signing import verify_native

def prepare(config,expected_config_sha256,out):
 need(sha(config)==expected_config_sha256,'Configuration differs from independent approval');c=json.loads(config.read_bytes())
 need(set(c)=={'schema','unsigned_handoff_root','unsigned_candidate_sha256','publisher_policy','native_verifier','native_verifier_sha256','profiles'} and c['schema']=='xace.nec018.signed_handoff_inputs.v1','Exact reviewed signed handoff inputs required')
 original=verify_handoff(c['unsigned_handoff_root'],c['unsigned_candidate_sha256']);need(original['schema']=='xace.nec018.handoff.v1','Original unsigned handoff context required');policy=publisher_policy(c['publisher_policy']);need(set(c['profiles'])=={'godot','unity','unreal'},'All three final signed engine deliveries required')
 verified={}
 for engine,profile in c['profiles'].items():
  need(set(profile)=={'root','signed_delivery_sha256','common_release_root','common_release_sha256','required_signed_executables'},'Exact signed native source inputs required')
  r=verify_native(profile['root'],profile['signed_delivery_sha256']);need(r['engine']==engine and r['publisher_policy']==policy,'Signed native profile/publisher mismatch');verified[engine]=tree(profile['root'])
 out=out.resolve();need(out.is_relative_to(ROOT/'evidence/nec018') and not out.exists(),'Fresh persistent signed handoff output required');need(shutil.disk_usage(ROOT).free>4*2**30,'4GiB preservation reserve');out.mkdir(parents=True);kit=out/'handoff';kit.mkdir();m=copy.deepcopy(original);m.update(schema=SIGNED_SCHEMA,classification='signed_private_engineering_not_release_certified',publisher_policy=policy,source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())
 for engine,profile in c['profiles'].items():
  target=kit/'payload'/engine;target.parent.mkdir(exist_ok=True);shutil.copytree(profile['root'],target);need(tree(target)==verified[engine] and tree(profile['root'])==verified[engine],'Signed native copy/source changed');p=m['profiles'][engine];p.update(files=verified[engine],signed_delivery_sha256=profile['signed_delivery_sha256'],common_release_root=profile['common_release_root'],common_release_sha256=profile['common_release_sha256'],required_signed_executables=profile['required_signed_executables'],native_proof_scope='unsigned_context_only_fresh_signed_execution_required')
 tools={}
 for tool_source,name in [('nec018_collect_environment.ps1','Collect-Environment.ps1'),('nec018_run_native_checks.ps1','Run-NativeChecks.ps1')]:shutil.copyfile(ROOT/'tools'/tool_source,kit/name);tools[name]=sha(kit/name)
 for name in ['NEC018_EXTERNAL_TEST_PROTOCOL.md','NEC018_SUPPORT_AND_EXIT.md','NEC018_SIGNED_ARTIFACT_CONTRACT.md','NEC018_SIGNING_WORKFLOW.md','XACE_GAME_CONTINUITY_TERMS.md']:
  shutil.copyfile(ROOT/'docs'/name,kit/name);tools[name]=sha(kit/name)
 m['tools']=tools;m['limitations']=['Unsigned predecessor context: '+item for item in m['limitations']]+['Signed delivery derivation/admission verified; no release certification inferred','Prior native_proof_sha256 fields are unsigned context only; rerun signed native probes','Actual fresh Windows, human developers, external networking and rights approval still required','Compatible save admission/refusal only; no automatic state restoration/migration','Pinned XACE runtime remains required; no runtime-free export or Steam certification']
 (kit/'candidate.json').write_bytes(canonical(m));pin=sha(kit/'candidate.json');verify_handoff(kit,pin,native_verifier=c['native_verifier'],native_verifier_sha256=c['native_verifier_sha256']);(out/'gate-ledger.json').write_bytes(canonical(initial_ledger(m)))
 archive=out/'NEC018-signed-engineering.zip'
 with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as z:
  for p in sorted(kit.rglob('*')):
   if p.is_file():z.write(p,p.relative_to(kit).as_posix())
 with zipfile.ZipFile(archive) as z:need(z.testzip() is None,'Signed archive CRC failed')
 result=dict(schema='xace.nec018.signed_preparation.v1',candidate_digest=pin,archive_sha256=sha(archive),archive_bytes=archive.stat().st_size,all_gates='OPEN',signed_native_gameplay_rerun_required=True,external_distribution_authorized=False,release_certified=False);(out/'preparation.json').write_bytes(canonical(result));print(json.dumps(result,indent=2))
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--expected-config-sha256',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();prepare(a.config,a.expected_config_sha256,a.output)
