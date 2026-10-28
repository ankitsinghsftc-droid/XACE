"""Real shared planner scale; native editor certification is separate."""
import copy,hashlib,importlib,json,sys,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system'),str(Path(__file__).parent)]
from test_native_adoption import inputs,choices_for,plan,oid
from authoring_identity import canonical,Baseline,WorldBinding
from native_adoption import digest
from native_setup_plan import plan_setup
from native_reconciliation_plan import plan_reconciliation

def scaled(engine,count):
 data,_,cgs,_,_=inputs(engine);raw=json.loads(data);prototype=raw['objects'][oid(2)];raw['objects']={oid(1):raw['objects'][oid(1)]}
 for n in range(2,count+2):
  row=copy.deepcopy(prototype);row['metadata']['authoring_id']=oid(n);row['locator']['object_id']='native'+str(n);raw['objects'][oid(n)]=row
 data=canonical(raw);reader=importlib.import_module(engine+'_authoring');mapping=reader.prepare_identity_map(data,project_id='adoption',branch_id=oid(200));selected=[oid(n) for n in range(2,count+2)]
 return data,mapping,cgs,selected,choices_for(selected)

class NativeScaleTests(unittest.TestCase):
 def test_thousand_object_adoption_setup_and_noop_reconciliation(self):
  for engine in ['godot','unity','unreal']:
   with self.subTest(engine=engine):
    started=time.perf_counter();data,mapping,cgs,selected,choices=scaled(engine,1000);before=data
    adopted=plan(data,mapping,cgs,selected,choices).to_dict();self.assertTrue(adopted['candidate_valid'],[r for r in adopted['losses'] if r['severity']=='blocking']);cgs=adopted['proposed_cgs']
    setup=plan_setup(cgs,engine=engine,namespace_id=oid(100),project_id='adoption',branch_id=oid(200),mode_id='reference');self.assertEqual(len(setup.to_dict()['bindings']),1000)
    for key,actor in zip(selected,cgs['modes'][0]['actors']):mapping.objects[key].world_binding=WorldBinding(actor['id'],actor['id'],0)
    reader=importlib.import_module(engine+'_authoring');baseline=reader.capture(data,mapping,enable_writes=True).admit();mapping.baseline=Baseline(digest(cgs),baseline.sha256,mapping.mapping_digest(),'scale:verified-fixture','a'*64,'b'*64);saved=copy.deepcopy(mapping.baseline)
    report=plan_reconciliation(baseline=baseline,baseline_cgs=cgs,mapping=mapping,current_mapping=copy.deepcopy(mapping),current_cgs=copy.deepcopy(cgs),native_inventory=data,expected_current_cgs_digest=digest(cgs),expected_source_digest=hashlib.sha256(data).hexdigest(),verify_baseline=lambda b:b==saved,trusted_project=True).to_dict()
    self.assertTrue(report['reviewable']);self.assertTrue(report['noop']);self.assertTrue(report['merge']['resolved']);self.assertFalse(report['merge']['native_proposals']);self.assertFalse(report['merge']['canonical_proposals']);self.assertEqual(data,before)
    print(json.dumps(dict(engine=engine,objects=1000,planning_seconds=time.perf_counter()-started,inventory_bytes=len(data),native_editor_certified=False)),flush=True)
 def test_above_declared_profile_refuses_adoption(self):
  data,mapping,cgs,selected,choices=scaled('godot',1001)
  with self.assertRaisesRegex(ValueError,'1..1000'):plan(data,mapping,cgs,selected,choices)
