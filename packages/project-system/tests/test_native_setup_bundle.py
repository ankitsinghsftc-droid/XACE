import sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system')]
from native_setup_bundle import NativeSetupBundle
from authoring_apply import file_change

class SetupBundleTests(unittest.TestCase):
    def fixture(self,root):
        paths=[f'Assets/Generated/object{i:03}.asset' for i in range(40)]
        p=NativeSetupBundle(root,engine='unity',allowed_paths=paths)
        r=dict(files=[file_change(path,None,path.encode()) for path in paths]);j=root/'.xace/journal/native'
        return p,r,j
    def test_restart_after_first_batch_then_rollback_retains_all_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p,r,j=self.fixture(root);t=p.prepare('setup',r,j)
            p.groups[0].publish(t['groups'][0],j/'0');self.assertEqual(p.inspect(t,j),'partial')
            p,_,_=self.fixture(root);p.publish(t,j);self.assertEqual(p.inspect(t,j),'after')
            p.restore(t,j);self.assertEqual(p.inspect(t,j),'before')
            self.assertEqual(len(list(j.rglob('*.created-rollback'))),40)
    def test_conflicting_later_batch_prevents_further_publication(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p,r,j=self.fixture(root);t=p.prepare('setup',r,j)
            path=root/r['files'][-1]['path'];path.parent.mkdir(parents=True);path.write_bytes(b'creator')
            with self.assertRaises(ValueError):p.publish(t,j)
            self.assertEqual(path.read_bytes(),b'creator');self.assertFalse((root/r['files'][0]['path']).exists())
    def test_cross_batch_alias_refused(self):
        with tempfile.TemporaryDirectory() as d:
            paths=[f'Assets/{i:03}' for i in range(33)]+['assets/000/child']
            with self.assertRaises(ValueError):NativeSetupBundle(d,engine='unity',allowed_paths=paths)
    def test_foreign_or_changed_request_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p,r,j=self.fixture(root);t=p.prepare('setup',r,j)
            r['files'][0]=file_change(r['files'][0]['path'],None,b'changed')
            with self.assertRaises(ValueError):p.prepare('setup',r,j)
            t['participant']='0'*64
            with self.assertRaises(ValueError):p.publish(t,j)
if __name__=='__main__':unittest.main()
