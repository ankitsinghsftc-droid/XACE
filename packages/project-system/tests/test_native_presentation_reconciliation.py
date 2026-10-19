import copy, hashlib, importlib, json, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system'),str(Path(__file__).parent)]
from test_native_adoption import inputs, plan, oid
from test_native_reconciliation import refresh
from authoring_identity import Baseline, WorldBinding, canonical
from native_adoption import digest, _asset_source
from native_reconciliation_plan import plan_reconciliation, gde, factory
from tools.world_extensibility_proof import rehash

def context(engine):
    data,mapping,cgs,selected,choices=inputs(engine);raw=json.loads(data)
    paths={'unity':'Assets/mesh.asset','godot':'res://mesh.tres','unreal':'/Game/Mesh.Mesh'}
    ref=dict(asset_id='mesh_a',asset_type='MESH',status='LINKED',resolved_path=paths[engine])
    raw['objects'][oid(2)]['fields']['presentation.asset']=ref
    choices['objects'][oid(2)]['asset_role']='project.visual.v1';data=canonical(raw)
    result=plan(data,mapping,cgs,selected,choices).to_dict();assert result['candidate_valid'],result['losses']
    adopted=result['proposed_cgs'];other=copy.deepcopy(next(a for a in adopted['assets'] if a['id']=='mesh_a'))
    other['id']='mesh_b';other['source']=_asset_source(engine,paths[engine].replace('mesh','other').replace('Mesh','Other'));adopted['assets'].append(other);rehash(adopted)
    for key,actor in zip(selected,adopted['modes'][0]['actors']):mapping.objects[key].world_binding=WorldBinding(actor['id'],actor['id'],0)
    reader=importlib.import_module(engine+'_authoring');base=reader.capture(data,mapping,enable_writes=True).admit()
    mapping.baseline=Baseline(digest(adopted),base.sha256,mapping.mapping_digest(),'fixture','a'*64,'b'*64);saved=copy.deepcopy(mapping.baseline)
    return dict(baseline=base,baseline_cgs=adopted,mapping=mapping,current_mapping=copy.deepcopy(mapping),current_cgs=copy.deepcopy(adopted),native_inventory=data,expected_current_cgs_digest=digest(adopted),expected_source_digest=hashlib.sha256(data).hexdigest(),verify_baseline=lambda b:b==saved,trusted_project=True)

class PresentationTests(unittest.TestCase):
    def test_forward_registered_mesh_all_engines(self):
        for engine in ['unity','godot','unreal']:
            with self.subTest(engine=engine):
                c=context(engine);obj=c['current_cgs']['modes'][0]['world']['contract']['objects'][0]
                obj['asset_bindings']['project.visual.v1']['id']='mesh_b';refresh(c)
                r=plan_reconciliation(**c).to_dict();self.assertTrue(r['reviewable'],r['losses'])
                self.assertEqual(r['native_write_preview']['edits'][0]['fields']['presentation.asset']['asset_id'],'mesh_b')
                self.assertEqual(r['typed_operations']['operations'],[])
    def test_reverse_registered_mesh_preserves_world_semantics(self):
        for engine in ['unity','godot','unreal']:
            with self.subTest(engine=engine):
                c=context(engine);raw=json.loads(c['native_inventory']);ref=raw['objects'][oid(2)]['fields']['presentation.asset']
                ref['asset_id']='mesh_b';ref['resolved_path']=ref['resolved_path'].replace('mesh','other').replace('Mesh','Other')
                c['native_inventory']=canonical(raw);refresh(c);r=plan_reconciliation(**c).to_dict()
                self.assertTrue(r['reviewable'],r['losses']);self.assertEqual(r['typed_operations']['operations'][0]['kind'],'set_native_presentation')
                old=copy.deepcopy(c['current_cgs']['modes'][0]['world']['contract']['objects'][0]);new=r['proposed_cgs']['modes'][0]['world']['contract']['objects'][0]
                old['asset_bindings']['project.visual.v1']['id']='mesh_b';self.assertEqual(old,new)
    def test_unknown_or_mislocated_mesh_refused(self):
        for field,value in [('asset_id','unknown'),('resolved_path','Assets/unregistered.asset')]:
            c=context('unity');raw=json.loads(c['native_inventory']);raw['objects'][oid(2)]['fields']['presentation.asset'][field]=value
            c['native_inventory']=canonical(raw);refresh(c);self.assertFalse(plan_reconciliation(**c).to_dict()['reviewable'])
    def test_typed_mesh_operation_stale_and_wrong_role_are_atomic(self):
        c=context('unity');current=c['current_cgs'];obj=current['modes'][0]['world']['contract']['objects'][0];before=canonical(current)
        op=dict(operation_id='mesh',kind='set_native_presentation',mode_id='reference',object_id=obj['id'],expected_object_digest=digest(obj),role='project.visual.v1',asset=dict(id='mesh_b',asset_type='MESH',status='LINKED'))
        for field,value in [('expected_object_digest','0'*64),('role','unowned')]:
            changed=dict(op,**{field:value});batch=dict(schema=gde.SCHEMA,expected_cgs_digest=digest(current),operations=[changed])
            with self.assertRaises(ValueError):gde.preview(batch,current,validate=factory.compile_portable_cgs)
            self.assertEqual(before,canonical(current))
if __name__=='__main__':unittest.main()
