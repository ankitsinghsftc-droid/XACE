import copy,sys,tempfile,unittest,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'packages/project-system')]
from authoring_identity import canonical
from authoring_transaction_files import sha
from native_setup_plan import NativeSetupPlan
from native_setup_stage import VerifiedNativeSetupStage

class Gateway:
    engine='godot'
    def __init__(self,root,inventory):self.root=root;self.inventory=inventory
    def capture(self):return self.inventory
    def _files(self):return {p.relative_to(self.root).as_posix():sha(p.read_bytes()) for p in self.root.rglob('*') if p.is_file()}

class SetupStageTests(unittest.TestCase):
    def fixture(self,root):
        evidence=ROOT/'docs/evidence/nec010-native-generators-20261018'
        cgs=json.loads((evidence/'godot-source.cgs.json').read_text())
        plan=NativeSetupPlan((evidence/'godot-setup-plan.json').read_bytes())
        native=canonical(json.loads((evidence/'godot-create.json').read_text())['result']['inventory'])
        (root/'scene.tscn').write_bytes(b'fixture')
        return cgs,VerifiedNativeSetupStage(plan,cgs,Gateway(root,native))
    def test_byte_edit_or_addition_invalidates_frozen_stage(self):
        for name in ['scene.tscn','added.tres']:
            with tempfile.TemporaryDirectory() as d:
                root=Path(d);cgs,stage=self.fixture(root)
                (root/name).write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'stage changed'):stage(cgs)
    def test_cgs_change_requires_explicit_restage(self):
        with tempfile.TemporaryDirectory() as d:
            cgs,stage=self.fixture(Path(d));changed=copy.deepcopy(cgs);changed['metadata']['name']='changed'
            with self.assertRaisesRegex(ValueError,'CGS changed'):stage(changed)
    def test_returned_file_set_cannot_change_frozen_stage(self):
        with tempfile.TemporaryDirectory() as d:
            cgs,stage=self.fixture(Path(d));first=stage(cgs);first['files']['scene.tscn']=b'changed'
            self.assertEqual(stage(cgs)['files']['scene.tscn'],b'fixture')
if __name__=='__main__':unittest.main()
