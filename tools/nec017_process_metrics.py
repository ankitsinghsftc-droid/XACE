"""Low-overhead Windows process accounting for native certification harnesses."""
import ctypes,os,subprocess,time,types
from ctypes import wintypes
class Counters(ctypes.Structure):
 _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(n,ctypes.c_size_t) for n in ['PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage']]
def memory(handle):
 value=Counters();value.cb=ctypes.sizeof(value)
 api=ctypes.WinDLL('kernel32',use_last_error=True).K32GetProcessMemoryInfo;api.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD];api.restype=wintypes.BOOL
 if not api(handle,ctypes.byref(value),value.cb):raise ctypes.WinError(ctypes.get_last_error())
 return dict(peak_working_set_bytes=value.PeakWorkingSetSize,working_set_bytes=value.WorkingSetSize,peak_pagefile_bytes=value.PeakPagefileUsage)
def current_memory():
 api=ctypes.WinDLL('kernel32').GetCurrentProcess;api.restype=wintypes.HANDLE
 return memory(api())
def instrument_gateway(module,samples):
 def measured_run(argv,**kwargs):
  timeout=kwargs.pop('timeout',None);started=time.perf_counter();peak={};process=subprocess.Popen(argv,**kwargs)
  while process.poll() is None:
   peak=memory(int(process._handle))
   if timeout is not None and time.perf_counter()-started>timeout:
    process.kill();process.wait();raise subprocess.TimeoutExpired(argv,timeout)
   time.sleep(0.1)
  try:peak=memory(int(process._handle))
  except OSError:pass
  samples.append(dict(seconds=time.perf_counter()-started,returncode=process.returncode,pid=process.pid,**peak))
  return subprocess.CompletedProcess(argv,process.returncode)
 module.subprocess=types.SimpleNamespace(run=measured_run,STDOUT=subprocess.STDOUT,CREATE_NO_WINDOW=subprocess.CREATE_NO_WINDOW)
