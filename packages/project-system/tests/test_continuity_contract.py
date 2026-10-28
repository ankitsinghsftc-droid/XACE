import dataclasses,hashlib,shutil,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'packages/project-system'))
from continuity_contract import ArchiveRequest,SourceRoot,Omission,Dependency,Checkpoint,Prerequisite,Limits,ContinuityError,ROLES,inventory,portable_path

class ContinuityContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        roots=[]
        for role in sorted(ROLES):
            key=role.replace('-','_');path=self.base/key;path.mkdir();(path/'input.bin').write_bytes(role.encode());roots.append(SourceRoot(key,role,path))
        self.request=ArchiveRequest('game.example',tuple(roots),(Dependency('executor inputs','payload/executor_source/input.bin'),),(Checkpoint('payload/history/input.bin',hashlib.sha256(b'history').hexdigest()),),(Prerequisite('engine','declared-test-version','Install the declared creator toolchain separately.'),),reviewed_declared_closure=True)
    def test_relocation_stable_inventory_never_claims_rebuild(self):
        first=inventory(self.request);other=self.base/'relocated';other.mkdir();roots=[]
        for root in self.request.roots:
            target=other/root.key;shutil.copytree(root.path,target);roots.append(dataclasses.replace(root,path=target))
        second=inventory(dataclasses.replace(self.request,roots=tuple(roots)))
        self.assertEqual(first.manifest,second.manifest);self.assertTrue(first.manifest['declared_closure_complete']);self.assertFalse(first.manifest['rebuild_verified'])
        self.assertNotIn(str(self.base),str(first.manifest))
    def test_essential_unavailable_dependency_blocks_completeness(self):
        request=dataclasses.replace(self.request,dependencies=(Dependency('licensed mesh',None,True,'Original source asset not supplied'),))
        result=inventory(request).manifest;self.assertFalse(result['declared_closure_complete']);self.assertEqual(result['unavailable'][0]['name'],'licensed mesh')
    def test_unreviewed_closure_cannot_claim_complete(self):
        self.assertFalse(inventory(dataclasses.replace(self.request,reviewed_declared_closure=False)).manifest['declared_closure_complete'])
    def test_missing_role_and_checkpoint_are_explicit(self):
        result=inventory(dataclasses.replace(self.request,roots=tuple(r for r in self.request.roots if r.role!='notices'),checkpoints=())).manifest
        self.assertFalse(result['declared_closure_complete']);self.assertEqual({x['name'] for x in result['unavailable']},{'role:notices','protected-checkpoint'})
    def test_known_secret_requires_reported_deliberate_omission(self):
        root=self.request.roots[0];(root.path/'.env').write_text('PRIVATE_TOKEN=do-not-copy',encoding='utf-8')
        with self.assertRaisesRegex(ContinuityError,'sensitive'):inventory(self.request)
        request=dataclasses.replace(self.request,omissions=(Omission(root.key,'.env','Local credentials re-entered separately',False),))
        result=inventory(request);self.assertTrue(result.manifest['declared_closure_complete']);self.assertEqual(len(result.manifest['omissions']),1)
        self.assertFalse(any(p.endswith('/.env') for p in result.sources))
    def test_checkpoint_tamper_refuses_inventory(self):
        next(r for r in self.request.roots if r.role=='history').path.joinpath('input.bin').write_bytes(b'changed')
        with self.assertRaisesRegex(ContinuityError,'checkpoint mismatch'):inventory(self.request)
    def test_missing_dependency_and_unused_omission_refuse(self):
        with self.assertRaisesRegex(ContinuityError,'absent archive'):inventory(dataclasses.replace(self.request,dependencies=(Dependency('missing','payload/runtime/no.bin'),)))
        with self.assertRaisesRegex(ContinuityError,'does not match'):inventory(dataclasses.replace(self.request,omissions=(Omission('runtime','not-there','Cache omission',False),)))
    def test_streaming_limits_refuse_before_large_inventory(self):
        with self.assertRaisesRegex(ContinuityError,'limit'):inventory(self.request,Limits(files=1))
        with self.assertRaisesRegex(ContinuityError,'limit'):inventory(self.request,Limits(file_bytes=1))
    def test_portable_paths_support_native_asset_spaces_but_reject_escapes(self):
        self.assertEqual(portable_path('Scenes/My Level.tscn'),'Scenes/My Level.tscn')
        for path in ['.','../escape','a/../b','/absolute','a//b','a\\b','C:/file','CON.txt','a:stream','name.','a/../','e\u0301']:
            with self.subTest(path=path),self.assertRaises(ContinuityError):portable_path(path)
    def test_inventory_does_not_modify_source_bytes(self):
        before={p:p.read_bytes() for root in self.request.roots for p in root.path.rglob('*') if p.is_file()}
        inventory(self.request);self.assertEqual(before,{p:p.read_bytes() for p in before})

if __name__=='__main__':unittest.main()
