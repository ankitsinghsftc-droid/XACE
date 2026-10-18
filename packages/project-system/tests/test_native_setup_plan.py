import copy,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system'),str(Path(__file__).parent)]
from test_native_reconciliation import context,refresh
from native_setup_plan import plan_setup,verify_setup
from authoring_identity import canonical

class SetupPlanTests(unittest.TestCase):
    def make(self,engine='godot'):
        c=context(engine);cgs=c['current_cgs']
        p=plan_setup(cgs,engine=engine,namespace_id='a'*32,project_id='new-project',branch_id='b'*32,mode_id=cgs['modes'][0]['id'])
        return c,p
    def test_deterministic_all_engine_native_requests(self):
        for engine in ['unity','godot','unreal']:
            c,p=self.make(engine);c2,p2=self.make(engine);self.assertEqual(p.payload,p2.payload)
            self.assertFalse(p.to_dict()['runtime_activation']);self.assertTrue(p.to_dict()['bindings'])
    def test_ambiguous_spawn_and_runtime_parent_refused(self):
        for field,value in [('spawn_count',2),('parent_entity_id',42)]:
            c,p=self.make();actor=c['current_cgs']['modes'][0]['actors'][0]
            if field=='spawn_count':actor[field]=value
            else:actor['components'][0]['defaults'][field]=value
            refresh(c)
            with self.assertRaises(ValueError):plan_setup(c['current_cgs'],engine='godot',namespace_id='a'*32,project_id='p',branch_id='b'*32,mode_id=c['current_cgs']['modes'][0]['id'])
    def test_existing_capture_cannot_impersonate_generated_identities(self):
        c,p=self.make()
        with self.assertRaises(ValueError):verify_setup(p,c['current_cgs'],c['native_inventory'])
    def test_changed_cgs_invalidates_setup(self):
        c,p=self.make();c['current_cgs']['modes'][0]['actors'][0]['components'][0]['defaults']['position']['x']+=1000000;refresh(c)
        with self.assertRaisesRegex(ValueError,'plan/source'):verify_setup(p,c['current_cgs'],c['native_inventory'])
if __name__=='__main__':unittest.main()
