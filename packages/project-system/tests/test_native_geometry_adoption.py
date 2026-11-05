import copy,json,sys,unittest,importlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path[:0]=[str(ROOT),str(ROOT/'packages/project-system'),str(Path(__file__).parent)]
from test_native_adoption import inputs,plan,oid
from authoring_identity import canonical
from native_authoring_geometry import require_adoption_match

class GeometryAdoptionTests(unittest.TestCase):
 def fixture(self,engine):
  data,mapping,cgs,selected,choices=inputs(engine);raw=json.loads(data)
  for key in selected:
   raw['objects'][key]['fields'].update({'collision.shape':'BOX','collision.profile':'world.aabb.v1','collision.size':dict(x='2',y='2',z='2'),'collision.offset':dict(x='0',y='0',z='0'),'collision.trigger':False})
  data=canonical(raw);reader=importlib.import_module(engine+'_authoring');rows=json.loads(reader.capture(data,mapping).payload)['normalized']
  choices['world_contract']['geometry_profiles']=[dict(id='world.aabb.v1',required=True)]
  for key in selected:
   fields=rows[key]['fields'];choices['objects'][key]['geometry_profile']='world.aabb.v1';choices['objects'][key]['components']=[dict(type_id=4,name='COMP_COLLIDER_V1',defaults=dict(shape='BOX',size={a:int(v) for a,v in fields['collision.size'].items()},offset={a:int(v) for a,v in fields['collision.offset'].items()},is_trigger=False))]
  return data,mapping,cgs,selected,choices,rows
 def test_exact_declared_root_box_adopts_and_repeats(self):
  for engine in ['unity']:
   data,mapping,cgs,selected,choices,rows=self.fixture(engine)
   result=plan(data,mapping,cgs,selected,choices).to_dict()
   self.assertTrue(result['candidate_valid'],result['losses']);self.assertTrue(result['saved_pair_eligible'])
   self.assertTrue(plan(data,mapping,result['proposed_cgs'],selected,choices).to_dict()['noop'])
 def test_mismatch_and_parent_geometry_are_not_approximated(self):
  data,mapping,cgs,selected,choices,rows=self.fixture('unity');key=selected[0]
  choices['objects'][key]['components'][0]['defaults']['size']['x']+=2
  self.assertFalse(plan(data,mapping,cgs,selected,choices).to_dict()['candidate_valid'])
  with self.assertRaises(ValueError):require_adoption_match(rows[key]['fields'],oid(3),choices['objects'][key])

 def test_other_engine_readers_do_not_gain_unsupported_geometry(self):
  for engine in ['godot','unreal']:
   data,mapping,cgs,selected,choices=inputs(engine);raw=json.loads(data)
   raw['objects'][selected[0]]['fields']['collision.shape']='BOX'
   report=plan(canonical(raw),mapping,cgs,selected,choices).to_dict()
   self.assertFalse(report['candidate_valid'])

 def test_saved_collider_projection_detects_changes_without_widening_writer(self):
  from authoring_identity import Baseline,WorldBinding,digest
  from native_adoption import actor_id
  from native_reconciliation_plan import plan_reconciliation
  from tools.world_extensibility_proof import rehash
  import hashlib
  data,mapping,cgs,selected,choices,rows=self.fixture('unity')
  cgs=plan(data,mapping,cgs,selected,choices).to_dict()['proposed_cgs']
  for key in selected:
   aid=actor_id(mapping,key);mapping.objects[key].world_binding=WorldBinding(aid,aid,0)
  reader=importlib.import_module('unity_authoring');snapshot=reader.capture(data,mapping,enable_writes=True).admit()
  mapping.baseline=Baseline(digest(cgs),snapshot.sha256,mapping.mapping_digest(),'verified-test-journal','a'*64,'b'*64)
  context=dict(baseline=snapshot,baseline_cgs=cgs,mapping=mapping,current_mapping=copy.deepcopy(mapping),current_cgs=copy.deepcopy(cgs),native_inventory=data,expected_current_cgs_digest=digest(cgs),expected_source_digest=hashlib.sha256(data).hexdigest(),verify_baseline=lambda b:b==mapping.baseline,trusted_project=True)
  self.assertTrue(plan_reconciliation(**context).to_dict()['noop'])
  actor=context['current_cgs']['modes'][0]['actors'][0]
  next(c for c in actor['components'] if c['type_id']==1)['defaults']['position']['x']+=1000000
  rehash(context['current_cgs']);context['expected_current_cgs_digest']=digest(context['current_cgs'])
  self.assertTrue(plan_reconciliation(**context).to_dict()['reviewable'])
  next(c for c in actor['components'] if c['type_id']==4)['defaults']['size']['x']+=2
  rehash(context['current_cgs']);context['expected_current_cgs_digest']=digest(context['current_cgs'])
  report=plan_reconciliation(**context).to_dict()
  self.assertFalse(report['reviewable']);self.assertTrue(any(r['code']=='field_mapping_not_certified' for r in report['losses']))
