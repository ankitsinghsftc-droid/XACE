"""Run reconstructed NEC001 Python acceptance into fresh persistent evidence."""
from pathlib import Path
import subprocess,sys,json,hashlib,re,os
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'recovery-evidence/20261015/nec001/tests';OUT.mkdir(parents=True,exist_ok=False)
cases=[]
for directory,patterns in [('packages/project-system/tests',['test_project_system.py','test_playable_package.py']),('packages/builder-workspace/server/tests',['test_engine_edit_router.py','test_world_contract.py','test_world_extensibility.py','test_replay_debugger.py','test_gameplay_package_authoring.py']),('packages/asset-registry/tests',['test_asset_import_workflow.py','test_semantic_binding_status.py'])]:
 for pattern in patterns:cases.append((pattern.removesuffix('.py'),[sys.executable,'-B','-m','unittest','discover','-s',directory,'-p',pattern,'-v']))
results=[];env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1'
for name,cmd in cases:
 log=OUT/(name+'.log')
 with log.open('xb') as stream:run=subprocess.run(cmd,cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=600,creationflags=subprocess.CREATE_NO_WINDOW)
 text=log.read_text(errors='replace');count=re.search(r'Ran (\d+) tests?',text)
 result=dict(name=name,command=cmd,returncode=run.returncode,tests=int(count[1]) if count else 0,log=str(log),sha256=hashlib.sha256(log.read_bytes()).hexdigest());results.append(result)
 (OUT/'runs.json').write_text(json.dumps(results,indent=2));print(name,run.returncode,result['tests'],flush=True)
 assert run.returncode==0 and result['tests']>0,str(log)
(OUT/'summary.json').write_text(json.dumps(dict(ok=True,tests=sum(r['tests'] for r in results),suites=len(results)),indent=2))
