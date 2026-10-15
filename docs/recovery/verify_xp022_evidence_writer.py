"""Actual Unreal read-sharing regression and mixed session using unchanged authority."""
from pathlib import Path
import ctypes,json,subprocess,sys
from ctypes import wintypes
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from tools import xp017_mixed_session_proof as proof
BASE=ROOT/'recovery-evidence/20261015/xp022-ingress-batch'
NATIVE=ROOT/'recovery-evidence/ue022'
PROJECT=NATIVE/'target-codex-task66-unreal-vertical-slice/XaceTask66.uproject'
OUT=BASE/'evidence-writer-regression';OUT.mkdir(exist_ok=False)
kernel=ctypes.WinDLL('kernel32',use_last_error=True)
kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE];kernel.CreateFileW.restype=wintypes.HANDLE
kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
handles=[]
def hold_reader(path):
    path.touch(exist_ok=False)
    handle=kernel.CreateFileW(str(path),0x80000000,3,None,3,0x80,None)
    if handle==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
    handles.append(handle)
try:
    target=OUT/'held-reader.jsonl';hold_reader(target)
    command=[str(proof.UNREAL),str(PROJECT),'-run=XaceNativeContractProof','-unattended','-nullrhi','-nosplash','-XaceEvidenceWrite='+str(target),'-XaceReport='+str(OUT/'sharing.json'),'-abslog='+str(OUT/'sharing-editor.log')]
    with (OUT/'sharing.log').open('xb') as log:run=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
    result=json.loads((OUT/'sharing.json').read_text(encoding='utf-8-sig'));assert run.returncode==0 and result['ok'],result
    assert json.loads(target.read_text())['kind']=='sharing_probe'
    for h in handles:kernel.CloseHandle(h)
    handles.clear()
    original=proof.write
    def write(path,value):
        if Path(path).name=='unreal-config.json':hold_reader(Path(value['transcript']))
        original(path,value)
    proof.write=write
    result=proof.scenario(OUT/'mixed-held-reader',['unity','godot','unreal','player'],BASE/'artifacts/build',PROJECT,dict(parent=BASE/'artifacts/parent',candidate=BASE/'artifacts/candidate',record_replay=True))
    assert result['ok']
    proof.write=original
    (OUT/'summary.json').write_text(json.dumps(dict(ok=True,legacy_append_fails_with_open_reader=True,repaired_append_succeeds=True,mixed_40_ticks_with_reader_held=True,production_runtime_changed=False),indent=2))
    print('Evidence writer and mixed held-reader regression passed')
finally:
    for h in handles:kernel.CloseHandle(h)
