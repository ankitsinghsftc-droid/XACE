import ctypes,json,os,sys,tempfile,threading,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system')]
from authoring_transaction_files import atomic_json,load_json

@unittest.skipUnless(os.name=='nt','Windows native sharing contract')
class JournalSharingTests(unittest.TestCase):
    def hold(self,path):
        api=ctypes.WinDLL('kernel32',use_last_error=True)
        create=api.CreateFileW;create.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p];create.restype=ctypes.c_void_p
        handle=create(str(path),0x80000000,3,None,3,0,None)
        if handle==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
        close=api.CloseHandle;close.argtypes=[ctypes.c_void_p];close.restype=ctypes.c_int
        return lambda:close(handle)
    def test_real_reader_releases_then_exact_journal_replacement(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'state.json';atomic_json(p,dict(state='old'));close=self.hold(p)
            timer=threading.Timer(0.15,close);timer.start()
            try:atomic_json(p,dict(state='new'))
            finally:timer.join()
            self.assertEqual(load_json(p),dict(state='new'));self.assertFalse(p.with_suffix('.next').exists())
    def test_permanent_reader_preserves_old_and_staged_journals(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'state.json';atomic_json(p,dict(state='old'));close=self.hold(p)
            try:
                with self.assertRaises(OSError):atomic_json(p,dict(state='new'))
                self.assertEqual(load_json(p),dict(state='old'));self.assertEqual(load_json(p.with_suffix('.next')),dict(state='new'))
            finally:close()
    def test_concurrent_journal_change_is_never_overwritten_by_retry(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'state.json';atomic_json(p,dict(state='old'));close=self.hold(p)
            def edit():p.write_text('{"state":"external"}')
            timer=threading.Timer(0.1,edit);timer.start()
            try:
                with self.assertRaisesRegex(ValueError,'journal changed'):atomic_json(p,dict(state='new'))
                self.assertEqual(load_json(p),dict(state='external'));self.assertEqual(load_json(p.with_suffix('.next')),dict(state='new'))
            finally:timer.join();close()
if __name__=='__main__':unittest.main()
