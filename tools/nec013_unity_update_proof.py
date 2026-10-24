"""Actual Unity player update/refusal/explicit rollback; creates only new retained fixtures."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.nec013_unity_player_proof import inventory,gone

def verify_build(source):
 rows=[json.loads(p.read_text(encoding='utf-8-sig')) for p in (source.parent/'project/XACEEvidence/builds').glob('*.json')]
 admitted=[r for r in rows if r['status']=='built-not-certified' and Path(r['output']).resolve()==source/'NativeGame.exe']
 assert len(admitted)==1 and inventory(source)=={r['path']:r['sha256'] for r in admitted[0]['files']},'Source lacks a matching cooked build receipt'

def main(a,b,out):
 a=a.resolve();b=b.resolve();out=out.resolve()
 assert all(p.is_relative_to(ROOT/'evidence/nec013') for p in [a,b,out]) and not out.exists()
 verify_build(a);verify_build(b);out.mkdir(parents=True)
 installed_a=out/'version-a';installed_b=out/'version-b';bad=out/'refused-candidate'
 shutil.copytree(a,installed_a);shutil.copytree(b,installed_b);shutil.copytree(b,bad)
 receipt=bad/'NativeGame_Data/StreamingAssets/XACERelease/native-release.json';receipt.write_bytes(receipt.read_bytes()+b'\n')
 before_a=inventory(installed_a);before_b=inventory(installed_b)
 env=dict(os.environ);env['PATH']=str(Path(os.environ['SystemRoot'])/'System32');env['LOCALAPPDATA']=str(out/'user-data')
 def run(folder,name,mode):
  command=[str(folder/'NativeGame.exe'),'-batchmode','-nographics','-xacePlayerReport',str(out/(name+'.json')),'-xaceFailure',mode,'-logFile',str(out/(name+'.log'))]
  (out/(name+'-command.json')).write_text(json.dumps(command,indent=2),encoding='utf-8')
  with (out/(name+'-run.txt')).open('wb') as log:r=subprocess.run(command,cwd=out,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=80,creationflags=subprocess.CREATE_NO_WINDOW)
  proof=json.loads((out/(name+'.json')).read_text(encoding='utf-8-sig'));assert r.returncode==0 and proof['ok'],proof
  assert gone(proof['runtime_pid']) and gone(proof['owner_pid']),proof
  return proof
 first=run(installed_a,'initial','smoke');saves=Path(first['save_root']);saves.mkdir(parents=True,exist_ok=True)
 marker=saves/'retained-save-sentinel.bin';marker.write_bytes(b'NEC013 unique save preservation sentinel')
 state=saves.parent/'release-state';active=state/'active.json';original=active.read_bytes()
 replacement=run(installed_b,'update','smoke');assert replacement['save_root']==first['save_root']
 updated=active.read_bytes();assert updated!=original and any(p.read_bytes()==original for p in state.glob('previous-*.json'))
 rejected=run(bad,'refused','startup');assert active.read_bytes()==updated
 rollback=run(installed_a,'rollback','smoke');assert active.read_bytes()==original
 assert marker.read_bytes()==b'NEC013 unique save preservation sentinel'
 assert inventory(installed_a)==before_a and inventory(installed_b)==before_b
 proof=dict(ok=True,actual_unity_players=True,valid_update=True,same_per_game_save_namespace=True,save_sentinel_retained=True,failed_update_keeps_working_activation=True,explicit_rollback=True,previous_receipt_retained=True,installations_unchanged=True,process_cleanup=True,automatic_installer=False,save_restoration=False,clean_machine=False)
 (out/'proof.json').write_text(json.dumps(proof,indent=2),encoding='utf-8');print(json.dumps(proof))
if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]))
