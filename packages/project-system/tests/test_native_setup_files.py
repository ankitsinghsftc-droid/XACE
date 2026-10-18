import sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system')]
from native_setup_files import NativeSetupFiles
from authoring_apply import file_change
from authoring_transaction_files import sha


class NativeSetupFilesTests(unittest.TestCase):
    def fixture(self,root):
        paths=['Assets/XACE/World.unity','ProjectSettings/ProjectVersion.txt']
        participant=NativeSetupFiles(root,engine='unity',allowed_paths=paths)
        request=dict(files=[file_change(p,None,('native:'+p).encode()) for p in paths])
        directory=root/'.xace/journal/native';directory.mkdir(parents=True)
        return participant,request,directory

    def test_nested_creation_resume_and_rollback_preserves_unowned(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p,r,j=self.fixture(root);(root/'developer.txt').write_bytes(b'keep')
            token=p.prepare('setup',r,j);self.assertFalse((root/'Assets').exists())
            p.publish(token,j);self.assertEqual(p.inspect(token,j),'after')
            # Restart uses the same durable token and does not require restaging.
            p=NativeSetupFiles(root,engine='unity',allowed_paths=p.allowed)
            p.publish(token,j);p.restore(token,j)
            self.assertEqual(p.inspect(token,j),'before')
            self.assertEqual((root/'developer.txt').read_bytes(),b'keep')
            self.assertTrue((root/'Assets/XACE').is_dir())
            self.assertEqual(len(list(j.glob('*.created-rollback'))),2)

    def test_existing_native_file_is_never_adopted_or_replaced(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p,r,j=self.fixture(root);target=root/p.allowed[0]
            target.parent.mkdir(parents=True);target.write_bytes(b'creator')
            with self.assertRaises(ValueError):p.prepare('setup',r,j)
            self.assertEqual(target.read_bytes(),b'creator')

    def test_newer_file_after_prepare_is_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p,r,j=self.fixture(root);token=p.prepare('setup',r,j)
            target=root/p.allowed[0];target.parent.mkdir(parents=True);target.write_bytes(b'newer')
            with self.assertRaises(ValueError):p.publish(token,j)
            self.assertEqual(target.read_bytes(),b'newer')

    def test_partial_publication_can_resume_and_rollback(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p,r,j=self.fixture(root);token=p.prepare('setup',r,j)
            row=token['rows'][0];target=root/row['path'];target.parent.mkdir(parents=True)
            target.write_bytes((j/'0.after').read_bytes())
            self.assertEqual(p.inspect(token,j),'partial');p.publish(token,j)
            p.restore(token,j);self.assertEqual(p.inspect(token,j),'before')

    def test_coordinator_restart_and_explicit_rollback(self):
        from test_authoring_transaction import fixture,Crash
        for action in ['resume','rollback']:
            with self.subTest(action=action),tempfile.TemporaryDirectory() as d:
                root=Path(d);coordinator,request=fixture(root)
                p,r,j=self.fixture(root);coordinator.participants['native']=p
                request.participant_requests['native']=r
                coordinator.verify_pair=lambda *_:p.fingerprint()=={row['path']:sha(('native:'+row['path']).encode()) for row in r['files']}
                def crash(event):
                    if event=='published_before_receipt:native':raise Crash()
                coordinator.checkpoint=crash
                with self.assertRaises(Crash):coordinator.commit(request,authorize=lambda _:True)
                self.assertTrue(coordinator.status()['play_build_blocked'])
                restarted,_=fixture(root,initialize=False)
                restarted.participants['native']=NativeSetupFiles(root,engine='unity',allowed_paths=p.allowed)
                restarted.verify_pair=coordinator.verify_pair
                result=restarted.recover('txn1',action=action)
                self.assertEqual(result['state'],'committed' if action=='resume' else 'rolled_back')
                self.assertEqual((root/'native.scene').read_bytes(),b'old-native')
                self.assertEqual((root/'game.cgs.json').read_bytes(),b'new-cgs' if action=='resume' else b'old-cgs')
                self.assertEqual((root/p.allowed[0]).exists(),action=='resume')

    def test_unsafe_or_ambiguous_path_sets_refused(self):
        with tempfile.TemporaryDirectory() as d:
            for paths in [['Assets/A','assets/a'],['Assets/A','Assets/A/child'],['../escape'],['target/code.cs'],['Assets/.git/config'],['Assets/World.'],['Assets/NUL.asset'],['Assets/scene?.tscn']]:
                with self.subTest(paths=paths),self.assertRaises(ValueError):NativeSetupFiles(d,engine='unity',allowed_paths=paths)

    def test_write_set_and_corrupt_stage_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p,r,j=self.fixture(root)
            with self.assertRaises(ValueError):p.prepare('setup',dict(files=r['files'][:1]),j)
            token=p.prepare('setup',r,j);(j/'0.after').write_bytes(b'tampered')
            with self.assertRaises(ValueError):p.publish(token,j)
            self.assertFalse((root/'Assets').exists())


if __name__=='__main__':unittest.main()
