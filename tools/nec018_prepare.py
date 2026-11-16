ï»¿"""Prepare immutable unsigned engineering artifacts; never distribute or sign them."""
from pathlib import Path
import json,shutil,subprocess,sys,zipfile
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'packages/project-system')]
from release_handoff import tree,sha,canonical,digest,verify_handoff,initial_ledger,need,PROFILES,GATES

def prepare(out):
 out=out.resolve();need(out.is_relative_to(ROOT/'evidence/nec018') and not out.exists(),'Fresh persistent NEC018 output required');need(shutil.disk_usage(ROOT).free>4*2**30,'4GiB preservation reserve');out.mkdir(parents=True);kit=out/'handoff';kit.mkdir()
 command=['powershell.exe','-NoProfile','-NonInteractive','-File',str(ROOT/'tools/nec018_collect_environment.ps1'),'-OutputPath',str(out/'development-environment.json')]
 result=subprocess.run(command,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW);(out/'environment-collector.log').write_bytes(result.stdout+result.stderr);need(result.returncode==0,'Environment collector failed; preserved log');environment=json.loads((out/'development-environment.json').read_text(encoding='utf-8-sig'));need(environment['machine_id'],'Development machine fingerprint required')
 profiles={};sources={}
 for engine,attempt,relative,entry,args,release in [
  ('godot','c','relocated','NativeGame.exe',['--headless','--log-file','{log}','--','{report}'],'release'),
  ('unity','b','shipping','NativeGame.exe',['-batchmode','-nographics','-xacePlayerReport','{report}','-logFile','{log}'],'NativeGame_Data/StreamingAssets/XACERelease'),
  ('unreal','b','archive/Windows','NEC015.exe',['-d3d11','-RenderOffscreen','-unattended','-NEC017ExistingReport={report}','-abslog={log}'],'NEC015/release')]:
  evidence=ROOT/'evidence/nec017/20261116'/(engine+'-existing-workflow-'+attempt)/'play-again';proof=json.loads((evidence/'proof.json').read_bytes());need(proof['ok'],'Required native proof missing');source=evidence/relative;files=tree(source)
  if engine=='godot':
   receipt=evidence/'export/receipt.json';record=json.loads(receipt.read_bytes());need(record['status']=='built-not-certified' and {n:r['sha256'] for n,r in files.items()}==record['files'],'Godot export receipt mismatch')
  elif engine=='unity':
   matches=[]
   for receipt in (evidence/'project/XACEEvidence/builds').glob('*.json'):
    record=json.loads(receipt.read_bytes())
    if record['status']=='built-not-certified' and Path(record['output']).resolve()==source/'NativeGame.exe':matches.append((receipt,record))
   need(len(matches)==1,'Unique Unity admitted build required');receipt,record=matches[0];need({n:r['sha256'] for n,r in files.items()}=={r['path']:r['sha256'] for r in record['files']},'Unity native build receipt mismatch')
  else:
   receipt=source/'NEC015/XACEBuild.json';record=json.loads(receipt.read_bytes());actual=tree(source/'NEC015');del actual['XACEBuild.json'];need(record['schema']=='xace.unreal.cooked_files.v1' and {n:r['sha256'] for n,r in actual.items()}==record['files'],'Unreal cooked-file receipt mismatch')
  target=kit/'payload'/engine;target.parent.mkdir(exist_ok=True);shutil.copytree(source,target);need(tree(target)==files and tree(source)==files,'Artifact copy/source changed')
  native_release=json.loads((source/release/'native-release.json').read_bytes());profiles[engine]=dict(engine_version=PROFILES[engine][0],objects=PROFILES[engine][1],root='payload/'+engine,entry=entry,argv=args,files=files,native_proof_sha256=sha(evidence/'proof.json'),game_id=native_release['game_id'],save_policy='exact_admission_or_unchanged_refusal_no_state_restore');sources[engine]=dict(source=str(source),proof=str(evidence/'proof.json'),proof_sha256=sha(evidence/'proof.json'),receipt=str(receipt),receipt_sha256=sha(receipt),files=files);print(engine+' byte-verified source and handoff copied',flush=True)
 tools={}
 for original,name in [('nec018_collect_environment.ps1','Collect-Environment.ps1'),('nec018_run_native_checks.ps1','Run-NativeChecks.ps1')]:shutil.copyfile(ROOT/'tools'/original,kit/name);tools[name]=sha(kit/name)
 for name in ['NEC018_EXTERNAL_TEST_PROTOCOL.md','NEC018_SUPPORT_AND_EXIT.md','NEC018_SIGNING_PREREQUISITE.md']:
  shutil.copyfile(ROOT/'docs'/name,kit/name);tools[name]=sha(kit/name)
 m=dict(schema='xace.nec018.handoff.v1',classification='unsigned_private_engineering_not_release_certified',source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),development_machine_id=environment['machine_id'],profiles=profiles,tools=tools,required_gates=list(GATES),limitations=['Private engineering probes; no external distribution authorized','No clean-machine, signing, human tester or Steam certification','Automated declared input; not physical-device certification','Static selected native profiles; no script/Blueprint translation','Pinned XACE runtime retained; no runtime-free exit','Save admission/refusal only; no automatic state restoration/migration','Reproducible unsigned executor cannot simply be signed under current v1 admission contract'])
 (kit/'candidate.json').write_bytes(canonical(m));candidate_digest=sha(kit/'candidate.json');need(candidate_digest==digest(m),'Noncanonical candidate');verify_handoff(kit,candidate_digest);(out/'source-references.json').write_bytes(canonical(sources));(out/'gate-ledger.json').write_bytes(canonical(initial_ledger(m)))
 readme='''# NEC-018 private engineering handoff

Unsigned. Not release-certified. Do not transfer to testers or publish until owner distribution approval and required signing/identity work is complete. Keep this archive intact; do not edit candidate.json to hide changes. Obtain the archive SHA256 and candidate SHA256 from the trusted owner independently, not only this folder.

This kit needs Windows PowerShell and the declared native Windows prerequisites, not Python, Cargo, Unity/Godot/Unreal editors or Builder. For an actual clean-machine trial use a fresh supported Windows x64 VM/PC, record provisioning and security/SmartScreen observations, and keep it offline using the separately approved lab procedure. The script only observes networking and never disables adapters/firewall/security controls. Do not bypass execution policy or anti-malware to force a pass. Record blockers instead. Local process/TCP sampling is not packet capture or proof that an OS is freshly provisioned.

After independently verifying archive and candidate digests, use Run-NativeChecks.ps1 with -CandidateRoot, -ExpectedCandidateSha256 and a new persistent -EvidenceRoot outside this folder. Default3launches/engine. -Launches1 is a smoke rehearsal only. It checks every payload file before/after launches, source-pinned structured native assertions, reported runtime/launcher cleanup and records environment, Authenticode status and process/TCP samples. Use a standard user token. Script failure leaves evidence in place. No game/editor sources, source compilation or manual source repair belong on the clean player machine.

The native fixtures are engineering observers and exit after their assertions; they are not retail game interfaces or external-human walkthroughs. The tool does not perform update/uninstall or manual developer workflows. Collect those separately under the acceptance script. Compatible save checks are admission, not restoration. All native games retain XACE runtime binaries. Source/build/archive instructions and complete support/loss/exit restrictions are in the included byte-pinned NEC018 documents, not inferred from an ok flag here.
'''
 (kit/'README.md').write_text(readme,encoding='utf-8')
 archive=out/'NEC018-private-engineering.zip'
 with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as z:
  for p in sorted(kit.rglob('*')):
   if p.is_file():z.write(p,p.relative_to(kit).as_posix())
 # Verify archive bytes against prepared files without extracting or executing it.
 with zipfile.ZipFile(archive) as z:
  need(z.testzip() is None,'Archive CRC failed');need(set(z.namelist())=={p.relative_to(kit).as_posix() for p in kit.rglob('*') if p.is_file()},'Archive file set changed')
 receipt=dict(schema='xace.nec018.preparation.v1',ok=True,candidate_digest=candidate_digest,archive_sha256=sha(archive),archive_bytes=archive.stat().st_size,native_payload_bytes=sum(row['bytes'] for p in profiles.values() for row in p['files'].values()),source_unchanged=True,all_gate_states='OPEN',external_distribution_authorized=False,clean_machine_certified=False,release_certified=False,steam_certified=False)
 (out/'preparation.json').write_bytes(canonical(receipt));print(json.dumps(receipt,indent=2),flush=True)
if __name__=='__main__':prepare(Path(sys.argv[1]))
