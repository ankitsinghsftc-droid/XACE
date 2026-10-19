import copy,hashlib,importlib,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system'),str(Path(__file__).parent)]
from test_native_reconciliation import context as base_context,refresh
from test_native_adoption import oid
from native_reconciliation_plan import plan_reconciliation,gde,factory
from authoring_identity import Baseline,canonical
from native_adoption import digest
from tools.world_extensibility_proof import rehash

def context(engine):
    c=base_context(engine);raw=json.loads(c['native_inventory']);raw['objects'][oid(2)]['fields']['input.action']='move'
    cgs=c['current_cgs'];actor=cgs['modes'][0]['actors'][0]
    actor['components'].append(dict(type_id=6,name='COMP_INPUT_V1',defaults=dict(controller_id=1,control_type='HUMAN',input_profile_id='explicit.input.v1')))
    cgs['input_profiles']=[dict(id='explicit.input.v1',schema='xace.input_profile.v1',network_ready=True,actions=[dict(id='move',kind='axis2',packet_fields=['move_x','move_z'])])]
    obj=cgs['modes'][0]['world']['contract']['objects'][0]
    cgs['native_input_bindings']=dict(schema=gde.native_input_bindings.SCHEMA,bindings=[dict(binding_id='input.player',mode_id='reference',world_object_id=obj['id'],input_profile_id='explicit.input.v1',action_id='move',native_actions={engine:'move'})])
    rehash(cgs);c['baseline_cgs']=copy.deepcopy(cgs);c['native_inventory']=canonical(raw)
    reader=importlib.import_module(engine+'_authoring');c['baseline']=reader.capture(c['native_inventory'],c['mapping'],enable_writes=True).admit()
    c['mapping'].baseline=Baseline(digest(cgs),c['baseline'].sha256,c['mapping'].mapping_digest(),'fixture','a'*64,'b'*64)
    c['current_mapping']=copy.deepcopy(c['mapping']);saved=copy.deepcopy(c['mapping'].baseline);c['verify_baseline']=lambda b:b==saved;refresh(c);return c

class InputTests(unittest.TestCase):
    def test_forward_is_explicit_native_selector_not_gameplay_remap(self):
        for engine in ['unity','godot','unreal']:
            c=context(engine);c['current_cgs']['native_input_bindings']['bindings'][0]['native_actions'][engine]='alternate';refresh(c)
            r=plan_reconciliation(**c).to_dict();self.assertTrue(r['reviewable'],r['losses'])
            self.assertEqual(r['native_write_preview']['edits'][0]['fields']['input.action'],'alternate')
            self.assertEqual(r['proposed_cgs']['input_profiles'],c['baseline_cgs']['input_profiles'])
    def test_reverse_preserves_profile_action_and_controller(self):
        for engine in ['unity','godot','unreal']:
            c=context(engine);raw=json.loads(c['native_inventory']);raw['objects'][oid(2)]['fields']['input.action']='alternate';c['native_inventory']=canonical(raw);refresh(c)
            r=plan_reconciliation(**c).to_dict();self.assertTrue(r['reviewable'],r['losses']);self.assertEqual(r['typed_operations']['operations'][0]['kind'],'set_native_input')
            binding=r['proposed_cgs']['native_input_bindings']['bindings'][0];self.assertEqual(binding['action_id'],'move');self.assertEqual(binding['native_actions'][engine],'alternate')
            self.assertEqual(r['proposed_cgs']['modes'],c['current_cgs']['modes'])
    def test_missing_or_ambiguous_declaration_refused(self):
        for change in ['profile','component','duplicate']:
            c=context('unity');current=copy.deepcopy(c['current_cgs'])
            if change=='profile':current['input_profiles']=[]
            elif change=='component':current['modes'][0]['actors'][0]['components'].pop()
            else:
                binding=copy.deepcopy(current['native_input_bindings']['bindings'][0]);binding['binding_id']='second';current['native_input_bindings']['bindings'].append(binding)
            with self.assertRaises(ValueError):gde.native_input_bindings.validate(current)
    def test_stale_input_operation_atomic(self):
        c=context('unity');current=c['current_cgs'];before=canonical(current)
        op=dict(operation_id='input',kind='set_native_input',binding_id='input.player',expected_binding_digest='0'*64,engine='unity',native_action='alternate')
        with self.assertRaises(ValueError):gde.preview(dict(schema=gde.SCHEMA,expected_cgs_digest=digest(current),operations=[op]),current,validate=factory.compile_portable_cgs)
        self.assertEqual(before,canonical(current))
if __name__=='__main__':unittest.main()
