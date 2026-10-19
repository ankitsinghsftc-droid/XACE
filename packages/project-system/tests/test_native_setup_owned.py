import copy,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system'),str(Path(__file__).parent)]
from test_native_playback_reconciliation import context as playback_context
from test_native_input_reconciliation import context as input_context
from test_native_presentation_reconciliation import context as mesh_context
from native_setup_plan import plan_setup
from tools.world_extensibility_proof import rehash

def fixture(engine):
    cgs=copy.deepcopy(playback_context(engine)['current_cgs']);inp=input_context(engine)['current_cgs'];mesh=mesh_context(engine)['current_cgs']
    actor=cgs['modes'][0]['actors'][0];actor['components'].append(copy.deepcopy(inp['modes'][0]['actors'][0]['components'][-1]))
    for key in ['input_profiles','native_input_bindings']:cgs[key]=copy.deepcopy(inp[key])
    obj=cgs['modes'][0]['world']['contract']['objects'][0];obj['asset_bindings']=copy.deepcopy(mesh['modes'][0]['world']['contract']['objects'][0]['asset_bindings'])
    cgs['assets'].append(copy.deepcopy(next(a for a in mesh['assets'] if a['id']=='mesh_a')));rehash(cgs)
    return cgs,{obj['id']:cgs['semantic_bindings']['bindings'][0]['binding_id']}
def plan(cgs,engine,links):return plan_setup(cgs,engine=engine,namespace_id='a'*32,project_id='owned-setup',branch_id='b'*32,mode_id='reference',playback_bindings=links)
class OwnedSetupTests(unittest.TestCase):
    def test_declared_mesh_input_and_playback_are_source_bound_all_engines(self):
        for engine in ['unity','godot','unreal']:
            cgs,links=fixture(engine);p=plan(cgs,engine,links);fields=p.to_dict()['native_request']['objects'][0]['fields']
            self.assertEqual(set(fields),{'transform.position','transform.rotation','transform.scale','presentation.asset','input.action','binding.playback'})
            self.assertEqual(fields['presentation.asset']['asset_id'],'mesh_a');self.assertEqual(fields['input.action'],'move')
            self.assertEqual(fields['binding.playback']['binding_id'],'import.hit');self.assertEqual(p.payload,plan(cgs,engine,links).payload)
    def test_playback_association_is_never_inferred_from_name(self):
        cgs,_=fixture('godot');p=plan(cgs,'godot',{})
        self.assertTrue(all('binding.playback' not in r['fields'] for r in p.to_dict()['native_request']['objects']))
    def test_unknown_or_duplicate_playback_target_refused(self):
        cgs,links=fixture('unity')
        for bad in [{'unknown':'import.hit'},{**links,cgs['modes'][0]['world']['contract']['objects'][1]['id']:'import.hit'},{next(iter(links)):'unknown'}]:
            with self.assertRaises(ValueError):plan(cgs,'unity',bad)
    def test_changed_registered_resource_changes_review_identity(self):
        cgs,links=fixture('unity');before=plan(cgs,'unity',links)
        next(a for a in cgs['assets'] if a['id']=='mesh_a')['source']='Assets/other.asset';rehash(cgs)
        self.assertNotEqual(before.sha256,plan(cgs,'unity',links).sha256)
if __name__=='__main__':unittest.main()
