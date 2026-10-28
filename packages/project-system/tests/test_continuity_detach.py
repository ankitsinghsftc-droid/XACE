import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from adapter_installation import install_or_update_adapter,uninstall_adapter,AdapterInstallationError,ADAPTER_ENGINE_INSTALL_MANIFEST,ADAPTER_BACKUP_DIR

class DetachPreservationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'source';self.source.mkdir()
        (self.source/'a.gd').write_text('original a');(self.source/'z.gd').write_text('original z')
        self.game=self.root/'game';self.game.mkdir()
        install_or_update_adapter(source_root=self.source,engine_project_root=self.game,engine_type='godot')
        self.dest=self.game/'addons/xace'
    def snapshot(self):
        return {p.relative_to(self.dest).as_posix():p.read_bytes() for p in self.dest.rglob('*') if p.is_file()}
    def test_modified_file_preserves_every_file_and_history(self):
        (self.dest/'z.gd').write_text('creator change');before=self.snapshot()
        report=uninstall_adapter(engine_project_root=self.game,engine_type='godot')
        self.assertFalse(report['ok']);self.assertEqual(report['removed'],[]);self.assertEqual(before,self.snapshot())
        self.assertIn('a.gd',report['preserved'])
    def test_success_preserves_old_history_and_complete_before_images(self):
        before=self.snapshot();report=uninstall_adapter(engine_project_root=self.game,engine_type='godot')
        self.assertTrue(report['ok']);self.assertFalse((self.dest/'a.gd').exists())
        for rel,data in before.items():
            if rel.startswith(ADAPTER_BACKUP_DIR+'/'):self.assertEqual((self.dest/rel).read_bytes(),data)
        recoveries=list((self.dest/ADAPTER_BACKUP_DIR).glob('uninstall-*'));self.assertEqual(len(recoveries),1)
        self.assertEqual((recoveries[0]/'files/a.gd').read_bytes(),before['a.gd'])
        self.assertEqual((recoveries[0]/ADAPTER_ENGINE_INSTALL_MANIFEST).read_bytes(),before[ADAPTER_ENGINE_INSTALL_MANIFEST])
    def test_interrupted_removal_restores_prior_files(self):
        before=self.snapshot();unlink=Path.unlink
        def fail(path,*args,**kwargs):
            if path==self.dest/'z.gd':raise OSError('injected interruption')
            return unlink(path,*args,**kwargs)
        with patch.object(Path,'unlink',fail):
            with self.assertRaises(OSError):uninstall_adapter(engine_project_root=self.game,engine_type='godot')
        for rel,data in before.items():self.assertEqual((self.dest/rel).read_bytes(),data)
    def test_legacy_and_corrupt_manifests_fail_closed(self):
        for data in ['{broken',json.dumps({'copied':['a.gd','z.gd']})]:
            (self.dest/ADAPTER_ENGINE_INSTALL_MANIFEST).write_text(data);before=self.snapshot()
            with self.assertRaises(AdapterInstallationError):uninstall_adapter(engine_project_root=self.game,engine_type='godot')
            self.assertEqual(before,self.snapshot())

class ReviewedDetachTests(unittest.TestCase):
    def test_create_only_runtime_detach_and_approval_binding(self):
        import test_continuity_contract as fixture
        from continuity_archive import create_archive
        from continuity_contract import ContinuityError
        from continuity_detach import review_detach,apply_detach
        fixture.ContinuityContractTests.setUp(self)
        archive=self.base/'game.zip';receipt=create_archive(self.request,archive)
        destination=self.base/'independent';review=review_detach(archive,receipt['archive_sha256'],destination)
        with self.assertRaises(ContinuityError):apply_detach(archive,review,'not-approved')
        self.assertFalse(destination.exists())
        result=apply_detach(archive,review,review['review_sha256'])
        self.assertTrue(result['ok']);self.assertTrue(result['archive_retained']);self.assertFalse(result['rebuild_verified'])
        with self.assertRaises(ContinuityError):apply_detach(archive,review,review['review_sha256'])

    def test_modified_adapter_detach_preserves_original_and_independent_conflict(self):
        import test_continuity_contract as fixture
        from continuity_archive import create_archive,file_hash
        from continuity_detach import review_detach,apply_detach
        fixture.ContinuityContractTests.setUp(self)
        native=next(r.path for r in self.request.roots if r.role=='native-project')
        source=self.base/'adapter';source.mkdir();(source/'adapter.gd').write_text('original')
        install_or_update_adapter(source_root=source,engine_project_root=native,engine_type='godot')
        installed=native/'addons/xace/adapter.gd';installed.write_text('creator change')
        before={str(p.relative_to(native)):p.read_bytes() for p in native.rglob('*') if p.is_file()}
        archive=self.base/'conflict.zip';receipt=create_archive(self.request,archive)
        destination=self.base/'detached';review=review_detach(archive,receipt['archive_sha256'],destination,mode='remove-adapter',native_root='native_project',engine='godot')
        result=apply_detach(archive,review,review['review_sha256'])
        self.assertFalse(result['ok']);self.assertEqual(result['adapter_report']['removed'],[])
        self.assertEqual(file_hash(archive),receipt['archive_sha256'])
        self.assertEqual(before,{str(p.relative_to(native)):p.read_bytes() for p in native.rglob('*') if p.is_file()})
        self.assertEqual((destination/'payload/native_project/addons/xace/adapter.gd').read_text(),'creator change')

if __name__=='__main__':unittest.main()
