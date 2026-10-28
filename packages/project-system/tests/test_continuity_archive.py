import copy,dataclasses,hashlib,json,os,shutil,stat,sys,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
import test_continuity_contract as fixture
from continuity_contract import canonical,ContinuityError,Dependency,inventory
from continuity_archive import create_archive,verify_archive,restore_archive,file_hash,MANIFEST

class ContinuityArchiveTests(unittest.TestCase):
    setUp=fixture.ContinuityContractTests.setUp
    def make_archive(self,name='continuity.zip',request=None,**kwargs):
        path=self.base/name;receipt=create_archive(request or self.request,path,**kwargs);return path,receipt
    def changed_zip(self,source,name,transform):
        target=self.base/name
        with zipfile.ZipFile(source) as incoming,zipfile.ZipFile(target,'w') as outgoing:
            for row in incoming.infolist():
                updated,data=transform(copy.copy(row),incoming.read(row));outgoing.writestr(updated,data)
        return target
    def test_deterministic_archive_and_new_workspace_restore(self):
        first,receipt=self.make_archive();second,other=self.make_archive('second.zip');self.assertEqual(receipt,other);self.assertEqual(first.read_bytes(),second.read_bytes())
        destination=self.base/'independent';restored=restore_archive(first,receipt['archive_sha256'],destination)
        self.assertFalse(restored['executed_payload']);self.assertFalse(restored['rebuild_verified']);self.assertTrue(restored['declared_closure_complete'])
        for row in inventory(self.request).manifest['files']:self.assertEqual(file_hash(destination/row['path']),row['sha256'])
        self.assertTrue((destination/'restore.receipt.json').exists())
    def test_existing_destination_and_overlapping_output_never_overwritten(self):
        archive,receipt=self.make_archive();destination=self.base/'existing';destination.mkdir();sentinel=destination/'work.txt';sentinel.write_text('keep')
        with self.assertRaises(ContinuityError):restore_archive(archive,receipt['archive_sha256'],destination)
        self.assertEqual(sentinel.read_text(),'keep')
        with self.assertRaisesRegex(ContinuityError,'overlaps'):create_archive(self.request,self.request.roots[0].path/'archive.zip')
        with self.assertRaises(ContinuityError):create_archive(self.request,archive)
    def test_incomplete_requires_explicit_archive_and_restore_opt_in(self):
        request=dataclasses.replace(self.request,dependencies=(Dependency('essential source',None,True,'not located'),))
        with self.assertRaises(ContinuityError):self.make_archive(request=request)
        archive,receipt=self.make_archive(request=request,allow_incomplete=True)
        self.assertFalse(receipt['declared_closure_complete'])
        with self.assertRaises(ContinuityError):restore_archive(archive,receipt['archive_sha256'],self.base/'blocked')
        self.assertFalse((self.base/'blocked').exists())
        result=restore_archive(archive,receipt['archive_sha256'],self.base/'diagnostic',allow_incomplete=True);self.assertFalse(result['declared_closure_complete'])
    def test_tamper_and_untrusted_archive_hash_refused_before_restore(self):
        archive,receipt=self.make_archive()
        with self.assertRaisesRegex(ContinuityError,'identity mismatch'):verify_archive(archive,'0'*64)
        bad=self.changed_zip(archive,'changed.zip',lambda row,data:(row,b'corrupt' if row.filename.endswith('runtime/input.bin') else data))
        with self.assertRaises(ContinuityError):restore_archive(bad,file_hash(bad),self.base/'bad-restore')
        self.assertFalse((self.base/'bad-restore').exists())
    def test_traversal_and_link_entries_refused(self):
        archive,_=self.make_archive()
        def escape(row,data):
            if row.filename=='payload/executor_source/input.bin':row.filename='../outside'
            return row,data
        bad=self.changed_zip(archive,'escape.zip',escape)
        with self.assertRaises(ContinuityError):verify_archive(bad,file_hash(bad))
        def link(row,data):
            if row.filename!=MANIFEST:row.create_system=3;row.external_attr=(stat.S_IFLNK|0o777)<<16
            return row,data
        bad=self.changed_zip(archive,'link.zip',link)
        with self.assertRaises(ContinuityError):verify_archive(bad,file_hash(bad))
    def test_false_completeness_claim_refused_even_with_rehashed_manifest(self):
        archive,_=self.make_archive(request=dataclasses.replace(self.request,checkpoints=()),allow_incomplete=True)
        def falsify(row,data):
            if row.filename==MANIFEST:
                value=json.loads(data);value['declared_closure_complete']=True;value.pop('content_sha256');value['content_sha256']=hashlib.sha256(canonical(value)).hexdigest();data=canonical(value)
            return row,data
        bad=self.changed_zip(archive,'false.zip',falsify)
        with self.assertRaisesRegex(ContinuityError,'completeness'):verify_archive(bad,file_hash(bad))
    def test_interrupted_restore_retains_started_output_without_success_receipt(self):
        archive,receipt=self.make_archive();destination=self.base/'interrupted'
        with patch('continuity_archive.os.fsync',side_effect=OSError('injected interruption')):
            with self.assertRaises(OSError):restore_archive(archive,receipt['archive_sha256'],destination)
        self.assertTrue((destination/'restore.started.json').exists());self.assertFalse((destination/'restore.receipt.json').exists())
        self.assertTrue(archive.exists())
        with self.assertRaises(ContinuityError):restore_archive(archive,receipt['archive_sha256'],destination)
    def test_source_drift_retains_uncommitted_archive_without_manifest(self):
        first=inventory(self.request);second=copy.deepcopy(first);second.manifest['project_id']='changed'
        path=self.base/'interrupted.zip'
        with patch('continuity_archive.inventory',side_effect=[first,second]):
            with self.assertRaisesRegex(ContinuityError,'source changed'):create_archive(self.request,path)
        self.assertTrue(path.exists())
        with self.assertRaises(ContinuityError):verify_archive(path,file_hash(path))
    def test_low_disk_refuses_before_creating_archive(self):
        from collections import namedtuple
        Disk=namedtuple('Disk','total used free');path=self.base/'no-space.zip'
        with patch('continuity_archive.shutil.disk_usage',return_value=Disk(10,9,1)):
            with self.assertRaisesRegex(ContinuityError,'disk reserve'):create_archive(self.request,path)
        self.assertFalse(path.exists())


    @unittest.skipUnless(os.name=='nt','Windows long-path regression')
    def test_restore_deep_windows_workspace(self):
        archive,receipt=self.make_archive()
        parent=self.base/('a'*80)/('b'*80);parent.mkdir(parents=True)
        destination=parent/('c'*40)
        restored=restore_archive(archive,receipt['archive_sha256'],destination)
        extended=Path('\\\\?\\'+str(destination.absolute()))
        self.assertTrue(destination.absolute().is_relative_to(self.base.absolute()))
        self.addCleanup(shutil.rmtree,extended)
        self.assertTrue((extended/'restore.receipt.json').is_file())
        self.assertEqual(restored['files'],len(inventory(self.request).manifest['files']))

    def test_restored_identity_history_reopens_and_forks_without_rewriting_original(self):
        import test_authoring_identity as identities
        from authoring_identity import IdentityDraft
        from authoring_identity_store import AuthoringIdentityStore
        from continuity_contract import SourceRoot
        fixture_store=identities.StoreTests();fixture_store.setUp();self.addCleanup(fixture_store.tearDown)
        request=dataclasses.replace(self.request,roots=self.request.roots+(SourceRoot('authoring','history',fixture_store.root),))
        archive,receipt=self.make_archive(request=request)
        destination=self.base/'restored-identity';restore_archive(archive,receipt['archive_sha256'],destination)
        restored=AuthoringIdentityStore(destination/'payload/authoring')
        self.assertEqual(restored.load(),fixture_store.store.load())
        self.assertEqual(restored.history(fixture_store.first),fixture_store.store.history(fixture_store.first))
        draft=IdentityDraft(restored.load().mapping);draft.fork(identities.oid(201))
        revision=restored.commit(restored.prepare(draft.snapshot(),expected_revision=fixture_store.current,journal_ref='nec016:explicit-fork',operation='fork'))
        self.assertNotEqual(revision,fixture_store.current)
        self.assertEqual(restored.history(fixture_store.current),fixture_store.store.load())
        self.assertEqual(fixture_store.store.load().mapping.branch_id,identities.oid(200))
        self.assertEqual(restored.load().mapping.branch_id,identities.oid(201))

if __name__=='__main__':unittest.main()
