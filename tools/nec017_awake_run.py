"""Process-scoped idle-sleep prevention for an authorized NEC017 test worker.
Does not change power settings or override explicit sleep/lid actions.
"""
from pathlib import Path
import ctypes,runpy,sys
ROOT=Path(__file__).resolve().parents[1]
script=(ROOT/sys.argv[1]).resolve()
assert script.parent==ROOT/'tools' and script.name.startswith('nec017_') and script.suffix=='.py'
api=ctypes.WinDLL('kernel32',use_last_error=True).SetThreadExecutionState
api.argtypes=[ctypes.c_uint];api.restype=ctypes.c_uint
assert api(0x80000001),'Could not acquire test-duration idle-sleep prevention'
print('Test worker idle-sleep prevention acquired; explicit sleep/lid policy unchanged',flush=True)
try:
 sys.argv=[str(script),*sys.argv[2:]];sys.path.insert(0,str(ROOT));runpy.run_path(str(script),run_name='__main__')
finally:
 api(0x80000000)
 print('Test worker idle-sleep prevention released',flush=True)
