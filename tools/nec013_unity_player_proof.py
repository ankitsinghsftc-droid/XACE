"""Relocate and execute an actual Unity build with no development tools on PATH.
Same-machine proof only: neither an ACL-enforced read-only nor a clean-machine claim.
"""
from pathlib import Path
import base64,ctypes,hashlib,json,os,shutil,subprocess,sys
from ctypes import wintypes
ROOT=Path(__file__).resolve().parents[1]
def inventory(root):return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file()}
def gone(pid):
 kernel=ctypes.WinDLL('kernel32',use_last_error=True)
 kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
 kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)];kernel.CloseHandle.argtypes=[wintypes.HANDLE]
 handle=kernel.OpenProcess(0x1000,False,pid)
 if not handle:return ctypes.get_last_error()==87
 try:
  code=wintypes.DWORD();assert kernel.GetExitCodeProcess(handle,ctypes.byref(code));return code.value!=259
 finally:kernel.CloseHandle(handle)
def main(source,out,readonly=False,failure=None):
 source=source.resolve();out=out.resolve();assert source.is_relative_to(ROOT/'evidence/nec013') and out.is_relative_to(ROOT/'evidence/nec013') and not out.exists()
 receipts=[json.loads(p.read_text(encoding='utf-8-sig')) for p in (source.parent/'project/XACEEvidence/builds').glob('*.json')]
 approved=[r for r in receipts if r['status']=='built-not-certified' and Path(r['output']).resolve()==source/'NativeGame.exe']
 assert len(approved)==1,'No unique admitted XACE build receipt; Unity success alone is insufficient'
 assert inventory(source)=={r['path']:r['sha256'] for r in approved[0]['files']},'Cooked build differs from receipt'
 out.mkdir(parents=True);game=out/'relocated game';shutil.copytree(source,game);before=inventory(game)
 if readonly:
  # Only this newly created proof copy is restricted. Source release is never touched.
  script=r"""$ErrorActionPreference='Stop'
$gamePath=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('PATH64'))
$acl=Get-Acl -LiteralPath $gamePath
$acl.Sddl | Set-Content -LiteralPath ($gamePath + '.original-acl.txt')
$identity=[Security.Principal.WindowsIdentity]::GetCurrent().Name
$rule=New-Object Security.AccessControl.FileSystemAccessRule($identity,'Write','ContainerInherit,ObjectInherit','None','Deny')
$acl.AddAccessRule($rule)
Set-Acl -LiteralPath $gamePath -AclObject $acl
(Get-Acl -LiteralPath $gamePath).Sddl
""".replace('PATH64',base64.b64encode(str(game).encode()).decode())
  encoded=base64.b64encode(script.encode('utf-16-le')).decode()
  acl=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',encoded],capture_output=True,text=True,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
  (out/'readonly-acl.txt').write_text(acl.stdout,encoding='utf-8')
  try:
   with (game/'write-must-be-denied.txt').open('xb') as denied:denied.write(b'Unexpected writable install; proof failed')
  except PermissionError:pass
  else:raise AssertionError('Read-only ACL did not deny writes')
 env=dict(os.environ);env['PATH']=str(Path(os.environ['SystemRoot'])/'System32');env['LOCALAPPDATA']=str(out/'user-data')
 command=[str(game/'NativeGame.exe'),'-batchmode','-nographics','-xacePlayerReport',str(out/'player.json'),'-logFile',str(out/'player.log')]
 if failure:command+=['-xaceFailure',failure]
 (out/'command.json').write_text(json.dumps(command,indent=2),encoding='utf-8')
 with (out/'run.txt').open('wb') as log:run=subprocess.run(command,env=env,cwd=out,stdout=log,stderr=subprocess.STDOUT,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
 report=json.loads((out/'player.json').read_text(encoding='utf-8-sig'));report.update(exit_code=run.returncode,install_unchanged=before==inventory(game),clean_machine=False,acl_readonly=readonly,process_cleanup=gone(report['runtime_pid']) and gone(report['owner_pid']))
 report['ok']=report['ok'] and run.returncode==0 and report['install_unchanged'] and report['process_cleanup']
 (out/'inventory.json').write_text(json.dumps(before,indent=2),encoding='utf-8');(out/'proof.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report));assert report['ok']
if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]),readonly="--readonly" in sys.argv,failure=sys.argv[sys.argv.index("--failure")+1] if "--failure" in sys.argv else None)
