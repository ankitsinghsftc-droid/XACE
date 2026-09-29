import json
from pathlib import Path
import sys,tempfile,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/"packages"),str(ROOT/"packages/project-system")]
import playable_package as pp
from tools.xp007_package_proof import package_fixture,compile_plan
from tools.xp008_player_build import prepare_player

class PlayerPreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cgs=package_fixture();cls.plan,compiled=compile_plan(cls.cgs)
        cls.runtime=b"inert trusted test build"
        cls.support=pp.RuntimeSupport(pp.digest(cls.runtime),"xace.runtime_executor.v1",tuple(compiled.to_sgc_input()))

    def prepare(self,root,settings):
        blob=pp.build_package(self.cgs,self.plan,self.runtime,self.support,package_id="space.test",version="1.0.0",presentation_files={"presentation/player/settings.json":json.dumps(settings).encode()})
        installed,_=pp.install_archive(blob,root/"install",self.support)
        return installed

    def settings(self):
        return {"schema":"xace.player.controls.v1","controller_id":7,"bindings":[{"action":"project.docking_thrust.v1","kind":"axis_1d","positive":68,"negative":65}]}

    def test_arbitrary_action_and_world_metadata_survive_preparation_without_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);installed=self.prepare(root,self.settings())
            with patch("subprocess.Popen",side_effect=AssertionError("must not execute payloads")):
                receipt=prepare_player(installed,self.support,root/"player")
            self.assertEqual(receipt["manifest_sha256"],pp.digest((installed/pp.MANIFEST).read_bytes()))
            self.assertEqual((installed/"world.json").read_bytes(),(root/"player/package/world.json").read_bytes())
            self.assertTrue((root/"player/adapter/xace_adapter.gd").is_file())
            self.assertFalse((root/"player/adapter/xace_godot_main.gd").exists())

    def test_tamper_rejects_before_receipt_or_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);installed=self.prepare(root,self.settings());(installed/"world.json").write_bytes(b"{}")
            with self.assertRaises(pp.PackageError):prepare_player(installed,self.support,root/"player")
            self.assertFalse((root/"player").exists())

    def test_invalid_control_contracts_reject_before_output(self):
        cases=[{},[],{**self.settings(),"controller_id":False},{**self.settings(),"bindings":[{}]},{**self.settings(),"bindings":[self.settings()["bindings"][0]]*2},{**self.settings(),"bindings":["bad"]}]
        for settings in cases:
            with self.subTest(settings=settings),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);installed=self.prepare(root,settings)
                with self.assertRaises(ValueError):prepare_player(installed,self.support,root/"player")
                self.assertFalse((root/"player").exists())

if __name__=="__main__":unittest.main()
