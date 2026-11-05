import copy,json,sys,unittest,hashlib,importlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path[:0]=[str(ROOT),str(ROOT/'packages/project-system'),str(Path(__file__).parent)]
from test_native_adoption import inputs,choices_for,plan,oid
from authoring_identity import canonical,Baseline,WorldBinding,digest
from native_adoption import actor_id
from native_reconciliation_plan import plan_reconciliation
from tools.world_extensibility_proof import rehash

class StaticMaterialTests(unittest.TestCase):
 def fixture(self,engine='unity'):
  data,mapping,cgs,selected,choices=inputs(engine);raw=json.loads(data);prefix='res://' if engine=='godot' else 'Assets/'
  raw['objects'][selected[0]]['fields'].update({'presentation.asset':dict(asset_id='mesh',asset_type='MESH',status='LINKED',resolved_path=prefix+'mesh.asset'),'presentation.material':dict(asset_id='material',asset_type='MATERIAL',status='LINKED',resolved_path=prefix+'material.asset')})
  choices['objects'][selected[0]]['asset_role']='project.mesh.v1';choices['objects'][selected[0]]['material_role']='project.material.v1'
  return canonical(raw),mapping,cgs,selected,choices
 def test_explicit_static_material_role_and_no_inferred_choice(self):
  for engine in ['unity','godot']:
   data,mapping,cgs,selected,choices=self.fixture(engine)
   report=plan(data,mapping,cgs,selected,choices).to_dict();self.assertTrue(report['candidate_valid'],report['losses'])
   self.assertTrue(report['saved_pair_eligible']);self.assertTrue(plan(data,mapping,report['proposed_cgs'],selected,choices).to_dict()['noop'])
   del choices['objects'][selected[0]]['material_role']
   self.assertFalse(plan(data,mapping,cgs,selected,choices).to_dict()['candidate_valid'])
 def context(self):
  data,mapping,cgs,selected,choices=self.fixture();cgs=plan(data,mapping,cgs,selected,choices).to_dict()['proposed_cgs']
  cgs['assets'].extend([dict(id='mesh2',asset_type='MESH',status='LINKED',source='Assets/mesh2.asset'),dict(id='material2',asset_type='MATERIAL',status='LINKED',source='Assets/material2.asset')]);rehash(cgs)
  for key in selected:
   aid=actor_id(mapping,key);mapping.objects[key].world_binding=WorldBinding(aid,aid,0)
  reader=importlib.import_module('unity_authoring');snapshot=reader.capture(data,mapping,enable_writes=True).admit();mapping.baseline=Baseline(digest(cgs),snapshot.sha256,mapping.mapping_digest(),'verified-test-journal','a'*64,'b'*64)
  return dict(baseline=snapshot,baseline_cgs=cgs,mapping=mapping,current_mapping=copy.deepcopy(mapping),current_cgs=copy.deepcopy(cgs),native_inventory=data,expected_current_cgs_digest=digest(cgs),expected_source_digest=hashlib.sha256(data).hexdigest(),verify_baseline=lambda b:b==mapping.baseline,trusted_project=True)
 def test_mesh_edit_preserves_static_material_role(self):
  c=self.context();self.assertTrue(plan_reconciliation(**c).to_dict()['noop'])
  raw=json.loads(c['native_inventory']);raw['objects'][oid(2)]['fields']['presentation.asset'].update(asset_id='mesh2',resolved_path='Assets/mesh2.asset');c['native_inventory']=canonical(raw);c['expected_source_digest']=hashlib.sha256(c['native_inventory']).hexdigest()
  report=plan_reconciliation(**c).to_dict();self.assertTrue(report['reviewable'],report['losses'])
  bindings=report['proposed_cgs']['modes'][0]['world']['contract']['objects'][0]['asset_bindings']
  self.assertEqual(bindings['project.material.v1']['id'],'material');self.assertEqual(bindings['project.mesh.v1']['id'],'mesh2')
 def test_material_changes_are_not_silently_synchronized(self):
  c=self.context();raw=json.loads(c['native_inventory']);raw['objects'][oid(2)]['fields']['presentation.material'].update(asset_id='material2',resolved_path='Assets/material2.asset');c['native_inventory']=canonical(raw);c['expected_source_digest']=hashlib.sha256(c['native_inventory']).hexdigest()
  self.assertFalse(plan_reconciliation(**c).to_dict()['reviewable'])
  c=self.context();obj=c['current_cgs']['modes'][0]['world']['contract']['objects'][0];obj['asset_bindings']['project.material.v1']['id']='material2';rehash(c['current_cgs']);c['expected_current_cgs_digest']=digest(c['current_cgs'])
  self.assertFalse(plan_reconciliation(**c).to_dict()['reviewable'])
