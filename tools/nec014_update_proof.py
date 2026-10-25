"""Actual Godot exported update/refusal/rollback and ACL-read-only installation."""
from pathlib import Path
import base64,json,os,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.nec014_export import sha,inventory
from tools.nec013_unity_player_proof import gone
def verify(source):
 receipt=json.loads((source.parent/'receipt.json').read_text(encoding='utf-8'))
 assert receipt['status']=='built-not-certified' and receipt['files']==inventory(source)
def main(a,b,out):
 a=a.resolve();b=b.resolve();out=out.resolve();assert all(p.is_relative_to(ROOT/'evidence/nec014') for p in [a,b,out]) and not out.exists()
 verify(a);verify(b);out.mkdir(parents=True)
 first=out/'version-a';second=out/'version-b';bad=out/'bad-candidate'
 shutil.copytree(a,first);shutil.copytree(b,second);shutil.copytree(b,bad)
 p=bad/'release/native-release.json';p.write_bytes(p.read_bytes()+b'\n')
 before_a=inventory(first);before_b=inventory(second)
 script=r"""$ErrorActionPreference='Stop'
$proofPath=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('PATH64'))
$acl=[IO.Directory]::GetAccessControl($proofPath)
[IO.File]::WriteAllText(($proofPath + '.original-acl.txt'),$acl.Sddl)
$identity=[Security.Principal.WindowsIdentity]::GetCurrent().Name
$rule=[Security.AccessControl.FileSystemAccessRule]::new($identity,'Write','ContainerInherit,ObjectInherit','None','Deny')
$acl.AddAccessRule($rule)
[IO.Directory]::SetAccessControl($proofPath,$acl)
([IO.Directory]::GetAccessControl($proofPath)).Sddl
""".replace('PATH64',base64.b64encode(str(second).encode()).decode())
 command=['powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',base64.b64encode(script.encode('utf-16-le')).decode()]
 acl=subprocess.run(command,capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW);(out/'readonly-acl.txt').write_text(acl.stdout+acl.stderr,encoding='utf-8');assert acl.returncode==0,acl.stderr
 try:(second/'write-must-be-denied.txt').write_bytes(b'Unexpected write access')
 except PermissionError:pass
 else:raise AssertionError('Read-only ACL did not deny write')
 env=dict(os.environ);env['LOCALAPPDATA']=str(out/'user-data');env['PATH']=str(Path(os.environ['SystemRoot'])/'System32')
 def run(folder,name,extra=[]):
  command=[str(folder/'NativeGame.exe'),'--headless','--',str(out/(name+'.json'))]+extra
  (out/(name+'-command.json')).write_text(json.dumps(command,indent=2),encoding='utf-8')
  with (out/(name+'.log')).open('wb') as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=60,env=env,creationflags=subprocess.CREATE_NO_WINDOW)
  report=json.loads((out/(name+'.json')).read_text(encoding='utf-8'));assert r.returncode==0 and report['ok'],report
  assert gone(report['runtime_pid']) and gone(report['owner_pid']),report
  return report
 run(first,'initial');state=out/'user-data/XACE/NativeGames/game-nec012-proof/release-state';active=state/'active.json';old=active.read_bytes()
 saves=state.parent/'saves';saves.mkdir(exist_ok=True);sentinel=saves/'retained-sentinel.bin';sentinel.write_bytes(b'NEC014 save preservation sentinel')
 updated=run(second,'update');new=active.read_bytes();assert new!=old and any(p.read_bytes()==old for p in state.glob('previous-*.json'))
 assert updated['save_compatible_not_restored'] and updated['incompatible_save_retained'] and updated['audio_started'] and updated['animation_started']
 run(bad,'refused',['--expect-refusal']);assert active.read_bytes()==new
 run(first,'rollback');assert active.read_bytes()==old and sentinel.read_bytes()==b'NEC014 save preservation sentinel'
 assert before_a==inventory(first) and before_b==inventory(second)
 report=dict(ok=True,actual_godot_export=True,acl_readonly=True,valid_update=True,failed_update_retains_activation=True,explicit_rollback=True,sentinel_retained=True,compatible_save_not_restored=True,incompatible_save_retained=True,installations_unchanged=True,process_cleanup=True,clean_machine=False)
 (out/'proof.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]))
