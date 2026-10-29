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
class ProcessEntry(ctypes.Structure):
 _fields_=[('dwSize',wintypes.DWORD),('cntUsage',wintypes.DWORD),('th32ProcessID',wintypes.DWORD),('th32DefaultHeapID',ctypes.c_size_t),('th32ModuleID',wintypes.DWORD),('cntThreads',wintypes.DWORD),('th32ParentProcessID',wintypes.DWORD),('pcPriClassBase',wintypes.LONG),('dwFlags',wintypes.DWORD),('szExeFile',wintypes.WCHAR*260)]

def descendants(root_pid):
 api=ctypes.WinDLL('kernel32',use_last_error=True)
 snapshot=api.CreateToolhelp32Snapshot;snapshot.argtypes=[wintypes.DWORD,wintypes.DWORD];snapshot.restype=wintypes.HANDLE
 first=api.Process32FirstW;following=api.Process32NextW
 for call in [first,following]:call.argtypes=[wintypes.HANDLE,ctypes.POINTER(ProcessEntry)];call.restype=wintypes.BOOL
 close=api.CloseHandle;close.argtypes=[wintypes.HANDLE];close.restype=wintypes.BOOL
 handle=snapshot(2,0)
 if handle==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
 rows={};entry=ProcessEntry();entry.dwSize=ctypes.sizeof(entry)
 try:
  more=first(handle,ctypes.byref(entry))
  while more:
   rows[entry.th32ProcessID]=(entry.th32ParentProcessID,entry.szExeFile);more=following(handle,ctypes.byref(entry))
 finally:close(handle)
 found={root_pid};result={}
 while True:
  additions={pid:row for pid,row in rows.items() if pid not in found and row[0] in found}
  if not additions:return result
  found.update(additions);result.update(additions)

class DescendantMemory:
 """Read-only sampled descendants; never controls or terminates other processes."""
 def __init__(self,root_pid):self.root_pid=root_pid;self.handles={};self.rows={};self.sampled_peak=0
 def sample(self):
  api=ctypes.WinDLL('kernel32',use_last_error=True);opened=api.OpenProcess;opened.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];opened.restype=wintypes.HANDLE
  for pid,(parent,name) in descendants(self.root_pid).items():
   if pid not in self.handles:
    handle=opened(0x1000|0x10,False,pid)
    if handle:self.handles[pid]=handle;self.rows[pid]=dict(pid=pid,parent_pid=parent,executable=name)
  total=0
  for pid,handle in self.handles.items():
   try:
    observed=memory(handle);self.rows[pid].update(observed);total+=observed['working_set_bytes']
   except OSError:pass # A process may finish between discovery and sampling.
  self.sampled_peak=max(self.sampled_peak,total)
 def close(self):
  api=ctypes.WinDLL('kernel32').CloseHandle;api.argtypes=[wintypes.HANDLE]
  for handle in self.handles.values():api(handle)
  self.handles.clear()

def instrument_gateway(module,samples):
 def measured_run(argv,**kwargs):
  timeout=kwargs.pop('timeout',None);started=time.perf_counter();peak={};process=subprocess.Popen(argv,**kwargs);tree=DescendantMemory(process.pid)
  try:
   while process.poll() is None:
    peak=memory(int(process._handle));tree.sample()
    if timeout is not None and time.perf_counter()-started>timeout:
     process.kill();process.wait();raise subprocess.TimeoutExpired(argv,timeout)
    time.sleep(0.1)
   try:peak=memory(int(process._handle))
   except OSError:pass
   tree.sample()
   samples.append(dict(seconds=time.perf_counter()-started,returncode=process.returncode,pid=process.pid,**peak,descendants=list(tree.rows.values()),descendant_sampled_peak_working_set_bytes=tree.sampled_peak,memory_scope='root kernel peak plus observed descendant kernel peaks; aggregate descendant working set sampled at 100ms, not guaranteed whole-tree peak'))
  finally:tree.close()
  return subprocess.CompletedProcess(argv,process.returncode)
 module.subprocess=types.SimpleNamespace(run=measured_run,STDOUT=subprocess.STDOUT,CREATE_NO_WINDOW=subprocess.CREATE_NO_WINDOW)
