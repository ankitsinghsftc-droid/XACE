"""Fresh installed-engine contract checks, using recovered persistent projects."""
import sys,json,subprocess,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from tools.xp017_mixed_session_proof import GODOT,UNITY,UNREAL
from tools.xp016_native_proof import FIXTURE
base=ROOT/'recovery-evidence/20261012/xp022';out=base/'native';out.mkdir(exist_ok=False)
project=base/'artifacts/build/target-codex-task65-unity-vertical-slice'
unreal=ROOT/'recovery-evidence/20261012/xp019/native/target-codex-task66-unreal-vertical-slice/XaceTask66.uproject'
commands={
'godot':[str(GODOT),'--headless','--path',str(ROOT/'adapters/godot'),'--script','res://tests/native_contract_proof.gd','--','--fixture='+str(FIXTURE),'--report='+str(out/'godot.json')],
'unity':[str(UNITY),'-batchmode','-nographics','-quit','-projectPath',str(project),'-executeMethod','Xace.Adapter.Unity.Editor.XaceNativeContractProof.Run','-logFile',str(out/'unity-editor.log'),'-xaceFixture',str(FIXTURE),'-xaceReport',str(out/'unity.json')],
'unreal':[str(UNREAL),str(unreal),'-run=XaceNativeContractProof','-unattended','-nullrhi','-nosplash','-XaceFixture='+str(FIXTURE),'-XaceReport='+str(out/'unreal.json'),'-abslog='+str(out/'unreal-editor.log')]}
results={}
for name,cmd in commands.items():
 with (out/(name+'.log')).open('wb') as log:r=subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=600,creationflags=subprocess.CREATE_NO_WINDOW)
 result=json.loads((out/(name+'.json')).read_text(encoding='utf-8-sig'));assert r.returncode==0 and result['ok'],name
 results[name]=dict(command=cmd,returncode=r.returncode,report=result)
 print(name+' native contract passed',flush=True)
(out/'proof.json').write_text(json.dumps(dict(ok=True,fresh_recovery_evidence=True,fixture_sha256=hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),results=results),indent=2))
