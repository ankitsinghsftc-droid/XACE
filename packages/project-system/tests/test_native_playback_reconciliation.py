import copy,sys,json,hashlib,importlib,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system'),str(Path(__file__).parent)]
from test_native_adoption import inputs,plan,oid
from test_native_reconciliation import refresh
from authoring_identity import Baseline,WorldBinding,canonical
from native_adoption import digest
from native_reconciliation_plan import plan_reconciliation,gde,factory
from tools.world_extensibility_proof import rehash

def context(engine):
    data,mapping,cgs,selected,choices=inputs(engine);raw=json.loads(data)
    path={'unity':'Assets/hit.wav','godot':'res://hit.wav','unreal':'/Game/Hit.Hit'}[engine]
    raw['objects'][oid(2)]['fields']['binding.playback']=dict(binding_id='import.hit',event_name='combat.hit',playback_kind='Audio',asset=dict(asset_id='audio_hit',asset_type='AUDIO_CLIP',status='LINKED',resolved_path=path))
    choices['objects'][oid(2)]['playback']=dict(semantic_action='play',entity_selector='SourceEntity',parameters={},enabled=True,priority=1)
    cgs['semantic_events']=[dict(name=n,payload_fields=[],version='1.0.0') for n in ['combat.hit','combat.other']];rehash(cgs);data=canonical(raw)
    adopted=plan(data,mapping,cgs,selected,choices).to_dict()['proposed_cgs']
    for key,actor in zip(selected,adopted['modes'][0]['actors']):mapping.objects[key].world_binding=WorldBinding(actor['id'],actor['id'],0)
    reader=importlib.import_module(engine+'_authoring');base=reader.capture(data,mapping,enable_writes=True).admit()
    mapping.baseline=Baseline(digest(adopted),base.sha256,mapping.mapping_digest(),'fixture','a'*64,'b'*64);saved=copy.deepcopy(mapping.baseline)
    return dict(baseline=base,baseline_cgs=adopted,mapping=mapping,current_mapping=copy.deepcopy(mapping),current_cgs=copy.deepcopy(adopted),native_inventory=data,expected_current_cgs_digest=digest(adopted),expected_source_digest=hashlib.sha256(data).hexdigest(),verify_baseline=lambda b:b==saved,trusted_project=True)

class PlaybackTests(unittest.TestCase):
    def test_canonical_event_change_emits_native_write_without_semantic_inference(self):
        for engine in ['unity','godot','unreal']:
            c=context(engine);c['current_cgs']['semantic_bindings']['bindings'][0]['event_name']='combat.other';refresh(c)
            r=plan_reconciliation(**c).to_dict();self.assertTrue(r['reviewable'],r['losses'])
            self.assertEqual(r['native_write_preview']['edits'][0]['fields']['binding.playback']['event_name'],'combat.other')
            self.assertEqual(r['typed_operations']['operations'],[])
    def test_native_event_change_uses_typed_gde_and_preserves_gameplay_semantics(self):
        for engine in ['unity','godot','unreal']:
            c=context(engine);raw=json.loads(c['native_inventory']);raw['objects'][oid(2)]['fields']['binding.playback']['event_name']='combat.other';c['native_inventory']=canonical(raw);refresh(c)
            r=plan_reconciliation(**c).to_dict();self.assertTrue(r['reviewable'],r['losses']);binding=r['proposed_cgs']['semantic_bindings']['bindings'][0]
            self.assertEqual(binding['event_name'],'combat.other');self.assertEqual(binding['semantic_action'],'play');self.assertEqual(binding['entity_selector'],'SourceEntity')
            self.assertEqual(r['typed_operations']['operations'][0]['kind'],'set_native_playback')
    def test_undeclared_event_unknown_asset_or_identity_change_blocks(self):
        for field,value in [('event_name','not.declared'),('binding_id','new.identity'),('asset_id','unknown')]:
            c=context('unity');raw=json.loads(c['native_inventory']);binding=raw['objects'][oid(2)]['fields']['binding.playback']
            if field=='asset_id':binding['asset'][field]=value
            else:binding[field]=value
            c['native_inventory']=canonical(raw);refresh(c);self.assertFalse(plan_reconciliation(**c).to_dict()['reviewable'])
    def test_typed_operation_rejects_gameplay_changes_atomically(self):
        c=context('unity');old=c['current_cgs']['semantic_bindings']['bindings'][0];new=copy.deepcopy(old);new['semantic_action']='invented'
        batch=dict(schema=gde.SCHEMA,expected_cgs_digest=digest(c['current_cgs']),operations=[dict(operation_id='change',kind='set_native_playback',binding_id=old['binding_id'],expected_binding_digest=digest(old),binding=new)])
        before=canonical(c['current_cgs'])
        with self.assertRaises(ValueError):gde.preview(batch,c['current_cgs'],validate=factory.compile_portable_cgs)
        self.assertEqual(before,canonical(c['current_cgs']))
if __name__=='__main__':unittest.main()
