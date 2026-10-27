"""Actual Unreal packaged relocation, read-only install, refusal and activation rollback."""
from pathlib import Path
import base64,json,os,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.nec015_package_proof import sha
from tools.nec013_unity_player_proof import gone

def inventory(root):return {p.relative_to(root).as_posix():sha(p) for p in sorted(root.rglob('*')) if p.is_file()}
def main(source,out,update=None):
 source=source.resolve();out=out.resolve();assert source.is_relative_to(ROOT/'evidence/nec015') and out.is_relative_to(ROOT/'evidence/nec015') and not out.exists()
 assert json.loads((source.parent.parent/'proof.json').read_text())['ok']
 update=update.resolve() if update else source
 assert update.is_relative_to(ROOT/'evidence/nec015') and json.loads((update.parent.parent/'proof.json').read_text())['ok']
 distinct=sha(source/'NEC015/Binaries/Win64/NEC015.exe')!=sha(update/'NEC015/Binaries/Win64/NEC015.exe')
 assert shutil.disk_usage(ROOT).free>6*1024**3
 out.mkdir(parents=True);first=out/'version-a';second=out/'version-b';bad=out/'bad-candidate'
 for dest in [first,second,bad]:
  shutil.copytree(source if dest==first else update,dest)
  marker=dest/'Engine/Build/InstalledProjectBuild.txt';marker.parent.mkdir(parents=True,exist_ok=True)
  if not marker.exists():marker.write_text('NEC015 installed native game\n',encoding='utf-8')
 p=bad/'NEC015/release/native-release.json';p.write_bytes(p.read_bytes()+b'\n')
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
 acl=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',base64.b64encode(script.encode('utf-16-le')).decode()],capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
 (out/'readonly-acl.txt').write_text(acl.stdout+acl.stderr,encoding='utf-8');assert acl.returncode==0
 try:(second/'write-must-be-denied.txt').write_bytes(b'Unexpected write')
 except PermissionError:pass
 else:raise AssertionError('ACL did not deny writing')
 env=dict(os.environ);env['LOCALAPPDATA']=str(out/'user-data');env['PATH']=str(Path(os.environ['SystemRoot'])/'System32')
 def run(folder,name,refusal=False):
  cmd=[str(folder/'NEC015.exe'),'-d3d11','-RenderOffscreen','-unattended',f'-XaceNativeReport={out/(name+".json")}',f'-abslog={out/(name+"-engine.log")}']
  if refusal:cmd.append('-XaceExpectRefusal')
  (out/(name+'-command.json')).write_text(json.dumps(cmd),encoding='utf-8')
  with (out/(name+'.log')).open('xb') as stream:r=subprocess.run(cmd,stdout=stream,stderr=subprocess.STDOUT,env=env,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
  proof=json.loads((out/(name+'.json')).read_text(encoding='utf-8-sig'));assert r.returncode==0 and proof['ok'],proof
  if refusal:assert proof['error'].startswith('Cooked file mismatch:') and proof['owner_pid']==0 and proof['runtime_pid']==0,proof
  else:assert proof['audio'] and proof['animation'] and gone(proof['owner_pid']) and gone(proof['runtime_pid']),proof
  return proof
 run(first,'initial');state=out/'user-data/XACE/NativeGames/game-nec012-proof/release-state';active=state/'active.json';old=active.read_bytes()
 saves=state.parent/'saves';saves.mkdir(exist_ok=True);sentinel=saves/'retained-sentinel.bin';sentinel.write_bytes(b'NEC015 save preservation sentinel')
 updated=run(second,'relocated-readonly');new=active.read_bytes();assert new!=old and any(p.read_bytes()==old for p in state.glob('previous-*.json'))
 run(bad,'refused',True);assert active.read_bytes()==new
 run(first,'rollback');assert active.read_bytes()==old and sentinel.read_bytes()==b'NEC015 save preservation sentinel'
 assert before_a==inventory(first) and before_b==inventory(second)
 proof=dict(ok=True,actual_unreal_package=True,relocation=True,acl_readonly=True,failed_candidate_retains_activation=True,explicit_path_rollback=True,save_sentinel_preserved=True,installations_unchanged=True,process_cleanup=True,clean_machine=False,distinct_gameplay_version_update=False,distinct_native_build_update=distinct,save_compatibility_tested=updated.get("save_compatible_not_restored",False),incompatible_save_schema_refused=updated.get("incompatible_save_schema_refused",False),installed_build_marker=True)
 (out/'proof.json').write_text(json.dumps(proof,indent=2),encoding='utf-8');print(json.dumps(proof))
if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]) if len(sys.argv)>3 else None)
