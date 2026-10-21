import copy,importlib,json,unittest
from test_native_reconciliation import context,refresh,oid,engine_edit
from authoring_identity import Baseline,canonical
from native_adoption import digest
from native_reconciliation_plan import plan_reconciliation,PARENT
from native_instance_transforms import PROFILE

def hierarchy(engine):
    c=context(engine);raw=json.loads(c['native_inventory']);raw['objects'][oid(2)]['parent_id']=oid(3)
    reader=importlib.import_module(engine+'_authoring');c['native_inventory']=canonical(raw)
    c['baseline']=reader.capture(c['native_inventory'],c['mapping'],enable_writes=True).admit()
    cgs=c['current_cgs'];cgs['native_instance_profile']=PROFILE;mode=cgs['modes'][0];objects=mode['world']['contract']['objects'];objects[0]['relationships'][PARENT]=[objects[1]['id']]
    child=mode['actors'][0]['components'][0]['defaults'];parent=mode['actors'][1]['components'][0]['defaults']
    for axis in 'xyz':child['position'][axis]+=parent['position'][axis]
    refresh(c);c['baseline_cgs']=copy.deepcopy(cgs)
    c['mapping'].baseline=Baseline(digest(cgs),c['baseline'].sha256,c['mapping'].mapping_digest(),'verified-hierarchy-fixture','a'*64,'b'*64)
    c['current_mapping']=copy.deepcopy(c['mapping']);saved=copy.deepcopy(c['mapping'].baseline);c['verify_baseline']=lambda b:b==saved
    return c

class HierarchyReconciliation(unittest.TestCase):
    def test_three_engine_parented_noop_and_native_local_edit(self):
        for engine in ['unity','godot','unreal']:
            with self.subTest(engine=engine):
                c=hierarchy(engine);r=plan_reconciliation(**c).to_dict();self.assertTrue(r['reviewable'],r['losses']);self.assertTrue(r['noop'])
                engine_edit(c,value='7');r=plan_reconciliation(**c).to_dict();self.assertTrue(r['reviewable'],r['losses']);self.assertEqual(len(r['typed_operations']['operations']),1)
                self.assertEqual(r['proposed_cgs']['modes'][0]['actors'][0]['components'][0]['defaults']['parent_entity_id'],0)
    def test_parent_edit_reprojects_child_and_canonical_inverse_is_local(self):
        c=hierarchy('godot');raw=json.loads(c['native_inventory']);raw['objects'][oid(3)]['fields']['transform.position']['x']='9';c['native_inventory']=canonical(raw);refresh(c)
        r=plan_reconciliation(**c).to_dict();self.assertTrue(r['reviewable'],r['losses']);self.assertEqual(len(r['typed_operations']['operations']),2)
        c=hierarchy('godot');c['current_cgs']['modes'][0]['actors'][0]['components'][0]['defaults']['position']['x']+=1000000;refresh(c)
        r=plan_reconciliation(**c).to_dict();self.assertTrue(r['reviewable'],r['losses']);self.assertEqual(len(r['native_write_preview']['edits']),1)
    def test_profile_switch_and_unsupported_parent_scale_refuse(self):
        c=hierarchy('godot');c['current_cgs'].pop('native_instance_profile');refresh(c)
        with self.assertRaises(ValueError):plan_reconciliation(**c)
        c=hierarchy('godot');raw=json.loads(c['native_inventory']);raw['objects'][oid(3)]['fields']['transform.scale']['x']='2';c['native_inventory']=canonical(raw);refresh(c)
        r=plan_reconciliation(**c).to_dict();self.assertFalse(r['reviewable']);self.assertIn('hierarchy_profile_refused',[x['code'] for x in r['losses']])
if __name__=='__main__':unittest.main()
