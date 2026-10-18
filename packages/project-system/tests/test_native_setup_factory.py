import sys,tempfile,unittest,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'packages/project-system')]
from native_setup_factory import create_native_setup_stage
from native_setup_plan import NativeSetupPlan
from authoring_transaction_files import sha

class SetupFactoryTests(unittest.TestCase):
    def fixture(self,root):
        evidence=ROOT/'docs/evidence/nec010-native-generators-20261018'
        cgs=json.loads((evidence/'godot-source.cgs.json').read_text());plan=NativeSetupPlan((evidence/'godot-setup-plan.json').read_bytes())
        exe=root/'editor.exe';exe.write_bytes(b'not executed')
        config=dict(engine='godot',executable=str(exe),executable_sha256=sha(exe.read_bytes()),plugin_hashes={'addons/xace_authoring/plugin.cfg':sha(b'authoring_plugin.gd')})
        return cgs,plan,config
    def test_disposable_stage_refused_before_creation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cgs,plan,config=self.fixture(root);stage=root/'stage'
            with self.assertRaisesRegex(ValueError,'persistent stage'):
                create_native_setup_stage(plan,cgs,stage,template_files={'addons/xace_authoring/plugin.cfg':b'authoring_plugin.gd'},gateway_config=config)
            self.assertFalse(stage.exists())
    def test_existing_directory_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cgs,plan,config=self.fixture(root);stage=root/'stage';stage.mkdir();(stage/'user.txt').write_bytes(b'keep')
            with self.assertRaisesRegex(ValueError,'fresh stage'):
                create_native_setup_stage(plan,cgs,stage,template_files={},gateway_config=config)
            self.assertEqual((stage/'user.txt').read_bytes(),b'keep')
    def test_changed_cgs_rejected_before_any_stage_writes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cgs,plan,config=self.fixture(root);cgs['metadata']['name']='drift';stage=root/'stage'
            with self.assertRaises(ValueError):create_native_setup_stage(plan,cgs,stage,template_files={},gateway_config=config)
            self.assertFalse(stage.exists())
if __name__=='__main__':unittest.main()
