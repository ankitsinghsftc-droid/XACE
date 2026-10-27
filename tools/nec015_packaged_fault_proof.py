"""Kill only a verified proof-owned native runtime or game; verify owned cleanup."""
from pathlib import Path
import ctypes,json,os,subprocess,sys,time
from ctypes import wintypes as W
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.nec013_unity_player_proof import gone
K=ctypes.WinDLL('kernel32',use_last_error=True)
class Entry(ctypes.Structure):
 _fields_=[('size',W.DWORD),('usage',W.DWORD),('pid',W.DWORD),('heap',ctypes.c_size_t),('module',W.DWORD),('threads',W.DWORD),('parent',W.DWORD),('priority',W.LONG),('flags',W.DWORD),('exe',W.WCHAR*260)]
K.CreateToolhelp32Snapshot.argtypes=[W.DWORD,W.DWORD];K.CreateToolhelp32Snapshot.restype=W.HANDLE
K.Process32FirstW.argtypes=[W.HANDLE,ctypes.POINTER(Entry)];K.Process32NextW.argtypes=[W.HANDLE,ctypes.POINTER(Entry)]
K.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];K.OpenProcess.restype=W.HANDLE
K.QueryFullProcessImageNameW.argtypes=[W.HANDLE,W.DWORD,W.LPWSTR,ctypes.POINTER(W.DWORD)]
K.CloseHandle.argtypes=[W.HANDLE];K.TerminateProcess.argtypes=[W.HANDLE,W.UINT]
def image(handle):
 buf=ctypes.create_unicode_buffer(32768);size=W.DWORD(len(buf))
 return Path(buf.value).resolve() if K.QueryFullProcessImageNameW(handle,0,buf,ctypes.byref(size)) else None
def find(exe):
 result=[];snap=K.CreateToolhelp32Snapshot(2,0);assert snap!=ctypes.c_void_p(-1).value
 try:
  row=Entry();row.size=ctypes.sizeof(row);ok=K.Process32FirstW(snap,ctypes.byref(row))
  while ok:
   if row.exe.lower()==exe.name.lower():
    handle=K.OpenProcess(0x1000,False,row.pid)
    if handle:
     try:
      if image(handle)==exe:result.append(row.pid)
     finally:K.CloseHandle(handle)
   ok=K.Process32NextW(snap,ctypes.byref(row))
 finally:K.CloseHandle(snap)
 assert len(result)<=1,'Ambiguous process ownership'
 return result[0] if result else None
def terminate(pid,exe):
 handle=K.OpenProcess(0x1001,False,pid);assert handle
 try:assert image(handle)==exe and K.TerminateProcess(handle,91),'Owned process identity/termination failed'
 finally:K.CloseHandle(handle)
def main(game,out,mode):
 game=game.resolve();out=out.resolve();assert game.is_relative_to(ROOT/'evidence/nec015') and out.is_relative_to(ROOT/'evidence/nec015') and not out.exists();assert mode in ['runtime','engine']
 runtime=game/'NEC015/release/package/runtime/xace_runtime.exe';owner=game/'NEC015/release/xace-player-launcher.exe';engine=game/'NEC015/Binaries/Win64/NEC015.exe'
 assert all(p.is_file() and find(p) is None for p in [runtime,owner,engine]),'Installation is already in use'
 out.mkdir(parents=True);env=dict(os.environ);env['LOCALAPPDATA']=str(out/'user-data');env['PATH']=str(Path(os.environ['SystemRoot'])/'System32')
 cmd=[str(game/'NEC015.exe'),'-d3d11','-RenderOffscreen','-unattended','-ExecCmds=t.MaxFPS 1','-XaceExpectRefusal','-XaceAwaitFault',f'-XaceNativeReport={out/"player.json"}',f'-abslog={out/"engine.log"}']
 if mode=='runtime':cmd.append('-XaceMeasureFreeze')
 (out/'command.json').write_text(json.dumps(cmd),encoding='utf-8');ids={}
 with (out/'run.log').open('xb') as stream:
  proc=subprocess.Popen(cmd,env=env,stdout=stream,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
  end=time.monotonic()+100
  while time.monotonic()<end and proc.poll() is None:
   for name,exe in [('runtime',runtime),('owner',owner),('engine',engine)]:
    if name not in ids:
     pid=find(exe)
     if pid:ids[name]=pid
   ready=any(b'baseline_verified' in p.read_bytes() for p in (out/'user-data/XACE/NativeHistory').rglob('authority.jsonl'))
   native_ready=out/'player.json.ready.json'
   if len(ids)==3 and ready and native_ready.exists():
    native=json.loads(native_ready.read_text(encoding='utf-8-sig'))
    assert native['native_motion'] and native['tick']>=12 and native['runtime_pid']==ids['runtime']
    break
   time.sleep(.05)
  assert len(ids)==3 and ready and (out/'player.json.ready.json').exists(),'No verified live native session before fault'
  (out/'owned-processes.json').write_text(json.dumps(ids,indent=2),encoding='utf-8')
  terminate(ids[mode],runtime if mode=='runtime' else engine)
  proc.wait(timeout=45)
  end=time.monotonic()+15
  while time.monotonic()<end and not all(gone(pid) for pid in ids.values()):time.sleep(.1)
  assert all(gone(pid) for pid in ids.values()),'Owned process leaked after fault'
 if mode=='runtime':
  result=json.loads((out/'player.json').read_text(encoding='utf-8-sig'));assert result['ok'] and result['error'] and result['runtime_pid']==ids['runtime'] and result['projection_freeze_measured'],result
 proof=dict(ok=True,actual_packaged_game=True,fault=mode,verified_owned_pids=ids,baseline_before_fault=True,owned_cleanup=True,projection_freeze_measured=mode=='runtime',clean_machine=False)
 (out/'proof.json').write_text(json.dumps(proof,indent=2),encoding='utf-8');print(json.dumps(proof))
if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3])
