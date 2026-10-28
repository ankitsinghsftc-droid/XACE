import copy
import hashlib
import importlib
import itertools
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system'),str(Path(__file__).parent)]
from test_native_adoption import inputs,plan,oid
from authoring_identity import Baseline,WorldBinding,canonical
from native_adoption import digest,encode
from native_reconciliation import reconcile_records
from native_reconciliation_plan import plan_reconciliation, _native_transform
from native_reconciliation_review import ReconciliationReview
from tools.world_extensibility_proof import rehash


def context(engine='unity'):
    data,mapping,cgs,selected,choices=inputs(engine)
    adopted=plan(data,mapping,cgs,selected,choices).to_dict()['proposed_cgs']
    for key,actor in zip(selected,adopted['modes'][0]['actors']):mapping.objects[key].world_binding=WorldBinding(actor['id'],actor['id'],0)
    reader=importlib.import_module(engine+'_authoring')
    baseline=reader.capture(data,mapping,enable_writes=True).admit()
    mapping.baseline=Baseline(digest(adopted),baseline.sha256,mapping.mapping_digest(),'verified-test-journal','a'*64,'b'*64)
    saved=copy.deepcopy(mapping.baseline)
    return dict(baseline=baseline,baseline_cgs=adopted,mapping=mapping,current_mapping=copy.deepcopy(mapping),current_cgs=copy.deepcopy(adopted),native_inventory=data,expected_current_cgs_digest=digest(adopted),expected_source_digest=hashlib.sha256(data).hexdigest(),verify_baseline=lambda b:b==saved,trusted_project=True)


def refresh(c):
    rehash(c['current_cgs']);c['expected_current_cgs_digest']=digest(c['current_cgs']);c['expected_source_digest']=hashlib.sha256(c['native_inventory']).hexdigest()


def engine_edit(c,field='transform.position',axis='x',value='4'):
    raw=json.loads(c['native_inventory']);raw['objects'][oid(2)]['fields'][field][axis]=value
    raw['source']['documents'][0]['before']=raw['source']['documents'][0]['after']='c'*64
    c['native_inventory']=canonical(raw);refresh(c)


def xace_edit(c,axis='x',value=5000000):
    c['current_cgs']['modes'][0]['actors'][0]['components'][0]['defaults']['position'][axis]=value;refresh(c)


def rows():
    c=context();b=c['baseline'].to_dict()['inspection']['normalized']
    return b,copy.deepcopy(b),copy.deepcopy(b),importlib.import_module('unity_authoring').policy(enable_writes=True)


class MergeTests(unittest.TestCase):
    def test_deterministic_merge_corpus(self):
        b,x,e,p=rows()
        for bx,xx,ex,by,xy,ey in itertools.product(['1','2'],repeat=6):
            for row,vx,vy in [(b,bx,by),(x,xx,xy),(e,ex,ey)]:row[oid(2)]['fields']['transform.position'].update(x=vx,y=vy)
            before=encode([b,x,e]);first=reconcile_records(b,x,e,p);self.assertEqual(first,reconcile_records(b,x,e,p));self.assertEqual(before,encode([b,x,e]))
            report=first.to_dict()
            for axis,bv,xv,ev in [('x',bx,xx,ex),('y',by,xy,ey)]:
                expected=xv if xv==ev or ev==bv else ev if xv==bv else bv
                self.assertEqual(report['merged'][oid(2)]['fields']['transform.position'][axis],expected)

    def test_parent_change_conflicts_with_descendant_edit(self):
        b,x,e,p=rows();b[oid(3)]['parent_id']=oid(2);x=copy.deepcopy(b);e=copy.deepcopy(b)
        x[oid(2)]['parent_id']=oid(1);e[oid(3)]['fields']['transform.position']['x']='2'
        r=reconcile_records(b,x,e,p).to_dict();self.assertTrue(any(c['object_id']==oid(2) and c['reason']=='reparent_interaction' for c in r['conflicts']))

    def test_same_value_and_disjoint_axes(self):
        b,x,e,p=rows();x[oid(2)]['fields']['transform.position']['x']='2';e[oid(2)]['fields']['transform.position']['y']='3'
        r=reconcile_records(b,x,e,p).to_dict();self.assertTrue(r['resolved']);self.assertEqual(r['merged'][oid(2)]['fields']['transform.position'],dict(x='2',y='3',z='-3000000'))
        e=copy.deepcopy(x);r=reconcile_records(b,x,e,p).to_dict();self.assertTrue(r['resolved']);self.assertFalse(r['native_proposals']);self.assertFalse(r['canonical_proposals'])

    def test_same_field_preserves_three_versions_and_requires_choice(self):
        b,x,e,p=rows();x[oid(2)]['fields']['transform.position']['x']='2';e[oid(2)]['fields']['transform.position']['x']='3'
        r=reconcile_records(b,x,e,p).to_dict();self.assertFalse(r['resolved']);conflict=r['conflicts'][0]
        self.assertEqual((conflict['base'],conflict['xace'],conflict['engine']),('1000000','2','3'))
        for winner,value in [('xace','2'),('engine','3')]:
            resolved=reconcile_records(b,x,e,p,resolutions={conflict['id']:winner}).to_dict()
            self.assertTrue(resolved['resolved']);self.assertEqual(resolved['merged'][oid(2)]['fields']['transform.position']['x'],value)

    def test_stale_conflict_choice_refused(self):
        b,x,e,p=rows();x[oid(2)]['fields']['transform.position']['x']='2';e[oid(2)]['fields']['transform.position']['x']='3'
        r=reconcile_records(b,x,e,p).to_dict();e[oid(2)]['fields']['transform.position']['x']='4'
        with self.assertRaisesRegex(ValueError,'stale'):reconcile_records(b,x,e,p,resolutions={r['conflicts'][0]['id']:'engine'})

    def test_permutations_and_repeat_are_identical(self):
        b,x,e,p=rows();x[oid(2)]['fields']['transform.scale']['x']='2000000';e[oid(3)]['fields']['transform.position']['x']='4'
        expected=reconcile_records(b,x,e,p)
        for keys in itertools.permutations(b):
            supplied=[{key:copy.deepcopy(source[key]) for key in keys} for source in (b,x,e)]
            self.assertEqual(expected,reconcile_records(*supplied,p))
        merged=expected.to_dict()['merged'];again=reconcile_records(merged,merged,merged,p).to_dict()
        self.assertFalse(again['native_proposals']);self.assertFalse(again['canonical_proposals'])

    def test_native_owned_name_and_code_never_overwritten(self):
        b,x,e,p=rows();x[oid(2)]['fields']['native.name']='X';e[oid(2)]['fields']['native.name']='Engine'
        r=reconcile_records(b,x,e,p).to_dict();self.assertEqual(r['merged'][oid(2)]['fields']['native.name'],'Engine');self.assertEqual(r['conflicts'][0]['allowed'],['engine'])
        with self.assertRaisesRegex(ValueError,'ownership'):reconcile_records(b,x,e,p,resolutions={r['conflicts'][0]['id']:'xace'})
        e[oid(2)]['opaque']=[dict(id='code',sha256='c'*64,critical=True,reason='Native script')]
        r=reconcile_records(b,x,e,p).to_dict();self.assertTrue(any(a['code']=='critical_native_behavior' for a in r['losses']))
        self.assertEqual(r['merged'][oid(2)]['opaque'],e[oid(2)]['opaque'])

    def test_delete_edit_and_missing_not_deletion(self):
        b,x,e,p=rows();x[oid(2)]=dict(generation='1',deleted=True,parent_id=None,fields={},dependencies=[],opaque=[]);e[oid(2)]['fields']['transform.position']['x']='2'
        r=reconcile_records(b,x,e,p).to_dict();self.assertEqual(r['conflicts'][0]['reason'],'delete_edit');self.assertEqual(r['conflicts'][0]['xace'],x[oid(2)])
        del e[oid(2)]
        with self.assertRaisesRegex(ValueError,'scope'):reconcile_records(b,x,e,p)

    def test_reparent_interaction_and_combined_cycle(self):
        b,x,e,p=rows();x[oid(2)]['parent_id']=oid(3);e[oid(2)]['fields']['transform.position']['x']='2'
        r=reconcile_records(b,x,e,p).to_dict();self.assertEqual(r['conflicts'][0]['reason'],'reparent_interaction')
        e=copy.deepcopy(b);e[oid(3)]['parent_id']=oid(2)
        r=reconcile_records(b,x,e,p).to_dict();self.assertTrue(any(a['code']=='parent_cycle' for a in r['losses']))

    def test_dependency_delete_and_generation_collision(self):
        b,x,e,p=rows();b[oid(2)]['dependencies']=[dict(kind='resource',target=oid(3))];x=copy.deepcopy(b);e=copy.deepcopy(b)
        e[oid(3)]=dict(generation='1',deleted=True,parent_id=None,fields={},dependencies=[],opaque=[])
        r=reconcile_records(b,x,e,p).to_dict();self.assertTrue(any(a['code']=='dangling_dependency' for a in r['losses']))
        e=copy.deepcopy(b);e[oid(2)]['generation']='2'
        with self.assertRaisesRegex(ValueError,'generation'):reconcile_records(b,x,e,p)

    def test_quaternion_is_atomic(self):
        b,x,e,p=rows();x[oid(2)]['fields']['transform.rotation']=dict(x='1000000',y='0',z='0',w='0');e[oid(2)]['fields']['transform.rotation']=dict(x='0',y='1000000',z='0',w='0')
        r=reconcile_records(b,x,e,p).to_dict();self.assertEqual(len(r['conflicts']),1);self.assertEqual(r['conflicts'][0]['path'],['fields','transform.rotation'])


class PlanTests(unittest.TestCase):
    def test_unprojected_world_change_and_transform_system_block(self):
        for kind in ['world','system']:
            c=context()
            if kind=='world':c['current_cgs']['modes'][0]['world']['contract']['objects'][0]['relationships']['project.related.v1']=[c['current_cgs']['modes'][0]['world']['contract']['objects'][1]['id']]
            else:c['current_cgs']['modes'][0]['systems']=[dict(id='MovementSystem',phase='Simulation',reads=[1,5],writes=[1],depends_on=[],deterministic=True)]
            refresh(c);r=plan_reconciliation(**c).to_dict();self.assertFalse(r['reviewable'])

    def test_three_engine_disjoint_merge_and_exact_write(self):
        for engine in ['unity','godot','unreal']:
            c=context(engine);xace_edit(c);engine_edit(c,axis='z',value='8')
            # Unreal Z maps to canonical Y; Unity/Godot Z maps to canonical Z.
            before=encode([c['current_cgs'],c['mapping'].to_dict()]);r=plan_reconciliation(**c).to_dict()
            self.assertTrue(r['reviewable'],r['losses']);self.assertTrue(r['typed_operations']['operations']);self.assertTrue(r['native_write_preview']['edits'])
            self.assertEqual(r['proposed_cgs']['modes'][0]['actors'][0]['components'][0]['defaults']['position']['x'],5000000)
            self.assertFalse(r['can_commit']);self.assertEqual(before,encode([c['current_cgs'],c['mapping'].to_dict()]))

    def test_noop_and_same_value(self):
        c=context();r=plan_reconciliation(**c).to_dict();self.assertTrue(r['noop']);self.assertTrue(r['reviewable'])
        xace_edit(c,value=4000000);engine_edit(c);r=plan_reconciliation(**c).to_dict();self.assertTrue(r['noop']);self.assertTrue(r['reviewable'])

    def test_conflict_resolution_and_cgs_only_work_preserved(self):
        c=context();xace_edit(c);engine_edit(c);c['current_cgs']['metadata']['name']='Unrelated CGS work';refresh(c)
        r=plan_reconciliation(**c).to_dict();self.assertFalse(r['reviewable']);conflict=r['merge']['conflicts'][0]
        r=plan_reconciliation(**c,resolutions={conflict['id']:'engine'}).to_dict();self.assertTrue(r['reviewable'],r['losses'])
        self.assertEqual(r['proposed_cgs']['metadata']['name'],'Unrelated CGS work');self.assertEqual(r['proposed_cgs']['modes'][0]['actors'][0]['components'][0]['defaults']['position']['x'],4000000)

    def test_receipts_source_hash_and_cgs_hash_required(self):
        for field,value in [('trusted_project',False),('expected_source_digest','0'*64),('expected_current_cgs_digest','0'*64),('verify_baseline',lambda b:False)]:
            c=context();c[field]=value
            with self.assertRaises(ValueError):plan_reconciliation(**c)

    def test_branch_identity_and_baseline_collision_refused(self):
        for mutation in ['branch','locator','baseline']:
            c=context()
            if mutation=='branch':c['current_mapping'].branch_id='d'*32
            elif mutation=='locator':c['current_mapping'].objects[oid(2)].display_name='Relocated identity'
            else:c['current_mapping'].baseline=None
            with self.assertRaisesRegex(ValueError,'identity/baseline'):plan_reconciliation(**c)

    def test_dirty_play_unknown_code_and_uncertified_input_block(self):
        for kind in ['dirty','play','code','input']:
            c=context();raw=json.loads(c['native_inventory'])
            if kind=='dirty':raw['source']['documents'][0]['dirty']=True
            elif kind=='play':raw['source']['play_mode']=True
            elif kind=='input':raw['objects'][oid(2)]['fields']['input.action']='Jump'
            else:raw['objects'][oid(2)]['opaque']=[dict(id='code',sha256='d'*64,critical=True,reason='Opaque native code')]
            c['native_inventory']=canonical(raw);refresh(c);r=plan_reconciliation(**c).to_dict();self.assertFalse(r['reviewable'],kind)

    def test_structural_parent_gate_retained(self):
        c=context();raw=json.loads(c['native_inventory']);raw['objects'][oid(2)]['parent_id']=oid(3);c['native_inventory']=canonical(raw);refresh(c)
        r=plan_reconciliation(**c).to_dict();self.assertFalse(r['reviewable']);self.assertTrue(any(x['code']=='runtime_parent_binding_required' for x in r['losses']))

    def test_tampered_baseline_and_projection_refused(self):
        c=context();c['baseline_cgs']['modes'][0]['actors'][0]['components'][0]['defaults']['position']['x']+=1
        with self.assertRaisesRegex(ValueError,'baseline identity'):plan_reconciliation(**c)

    def test_typed_gde_atomicity_and_unsupported_kind(self):
        from native_reconciliation_plan import gde,factory
        c=context();engine_edit(c);r=plan_reconciliation(**c).to_dict();batch=r['typed_operations'];before=encode(c['current_cgs'])
        batch['operations'].append(dict(batch['operations'][0],operation_id='bad',expected_actor_digest='0'*64))
        with self.assertRaises(ValueError):gde.preview(batch,c['current_cgs'],validate=factory.compile_portable_cgs)
        self.assertEqual(before,encode(c['current_cgs']))


class ReviewTests(unittest.TestCase):
    def test_approval_signature_principal_and_staleness(self):
        c=context();engine_edit(c);service=ReconciliationReview(lambda:c);opened=service.open('alice')
        approval=service.approve('alice',opened['token'],opened['proposal_digest']);self.assertFalse(approval['can_commit'])
        self.assertEqual(service.verify_approval('alice',approval).sha256,opened['proposal_digest'])
        with self.assertRaises(ValueError):service.verify_approval('bob',approval)
        altered=dict(approval,proposal_digest='0'*64)
        with self.assertRaises(ValueError):service.verify_approval('alice',altered)
        engine_edit(c,value='6')
        with self.assertRaisesRegex(ValueError,'changed'):service.verify_approval('alice',approval)

    def test_concurrent_review_cas_and_conflicts(self):
        c=context();xace_edit(c);engine_edit(c);service=ReconciliationReview(lambda:c);opened=service.open('alice');conflict=opened['report']['merge']['conflicts'][0]['id']
        with self.assertRaisesRegex(ValueError,'blocked'):service.approve('alice',opened['token'],opened['proposal_digest'])
        reviewed=service.resolve('alice',opened['token'],opened['proposal_digest'],{conflict:'engine'})
        with self.assertRaisesRegex(ValueError,'concurrent'):service.resolve('alice',opened['token'],opened['proposal_digest'],{conflict:'xace'})
        self.assertTrue(service.approve('alice',reviewed['token'],reviewed['proposal_digest'])['requires_coordinator'])

    def test_two_users_stale_after_external_cgs_change(self):
        c=context();engine_edit(c);service=ReconciliationReview(lambda:c);a=service.open('alice');b=service.open('bob')
        first=service.approve('alice',a['token'],a['proposal_digest'])
        xace_edit(c,axis='y')
        with self.assertRaises(ValueError):service.approve('bob',b['token'],b['proposal_digest'])
        with self.assertRaises(ValueError):service.verify_approval('alice',first)

    def test_cancel_and_expiration_preserve_state(self):
        c=context();before=encode([c['current_cgs'],c['mapping'].to_dict()]);service=ReconciliationReview(lambda:c);opened=service.open('alice');service.cancel('alice',opened['token'])
        with self.assertRaises(ValueError):service.approve('alice',opened['token'],opened['proposal_digest'])
        service=ReconciliationReview(lambda:c,lifetime_seconds=-1);opened=service.open('alice')
        with self.assertRaisesRegex(ValueError,'expired'):service.approve('alice',opened['token'],opened['proposal_digest'])
        self.assertEqual(before,encode([c['current_cgs'],c['mapping'].to_dict()]))


class FreshApprovalBoundaryTests(unittest.TestCase):
    def test_single_fresh_capture_per_boundary_and_no_cross_call_cache(self):
        c=context();engine_edit(c);calls=[]
        def provide():calls.append(1);return c
        service=ReconciliationReview(provide);opened=service.open('alice');approval=service.approve('alice',opened['token'],opened['proposal_digest'])
        calls.clear();first,observed=service.approved_context('alice',approval)
        self.assertEqual(len(calls),1);self.assertEqual(first.sha256,approval['proposal_digest'])
        observed['current_cgs']['metadata']['cgs_hash']='changed copy'
        self.assertNotEqual(c['current_cgs']['metadata']['cgs_hash'],'changed copy')
        engine_edit(c,value='9')
        with self.assertRaises(ValueError):service.verify_approval('alice',approval)
        self.assertEqual(len(calls),2)

    def test_expiration_during_fresh_capture_refuses_without_extending_lifetime(self):
        from unittest.mock import patch
        c=context();engine_edit(c);clock=[100.0];slow=[False]
        def provide():
            if slow[0]:clock[0]+=901
            return c
        with patch('native_reconciliation_review.time.monotonic',side_effect=lambda:clock[0]):
            service=ReconciliationReview(provide);opened=service.open('alice')
            approval=service.approve('alice',opened['token'],opened['proposal_digest'])
            before=encode([c['current_cgs'],c['mapping'].to_dict()]);slow[0]=True
            with self.assertRaisesRegex(ValueError,'expired'):
                service.approved_context('alice',approval)
            self.assertEqual(before,encode([c['current_cgs'],c['mapping'].to_dict()]))
            self.assertEqual(service._sessions[opened['token']]['created'],100.0)

    def test_resolved_conflict_still_requires_original_and_signed_choice(self):
        c=context();engine_edit(c);xace_edit(c);service=ReconciliationReview(lambda:c);opened=service.open('alice')
        conflict=opened['report']['merge']['conflicts'][0]
        resolved=service.resolve('alice',opened['token'],opened['proposal_digest'],{conflict['id']:'engine'})
        approval=service.approve('alice',resolved['token'],resolved['proposal_digest'])
        self.assertEqual(service.approved_context('alice',approval)[0].sha256,resolved['proposal_digest'])
        altered=copy.deepcopy(approval);altered['principal']='bob'
        with self.assertRaises(ValueError):service.verify_approval('bob',altered)
        engine_edit(c,value='8')
        with self.assertRaises(ValueError):service.approved_context('alice',approval)

if __name__=='__main__':unittest.main()
