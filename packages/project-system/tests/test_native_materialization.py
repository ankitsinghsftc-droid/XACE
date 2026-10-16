"""NEC010 materialization ownership regressions; no native write permission."""
import copy
import json
import unittest
from test_native_reconciliation import rows, context, engine_edit, refresh, oid
from authoring_identity import canonical
from native_reconciliation import reconcile_records
from native_reconciliation_plan import plan_reconciliation


def opaque(critical=False):
    return [dict(id='native.properties',sha256='d'*64,critical=critical,reason='Native retained content')]


class MaterializationOwnershipTests(unittest.TestCase):
    def test_native_opaque_refresh_is_not_structural_cgs_change(self):
        b,x,e,p=rows();e[oid(2)]['opaque']=opaque()
        r=reconcile_records(b,x,e,p).to_dict()
        self.assertEqual(r['merged'][oid(2)]['opaque'],opaque())
        self.assertEqual(r['canonical_proposals'],[])
        self.assertEqual(r['native_proposals'],[])
        self.assertTrue(any(v['code']=='native_code_retained' for v in r['losses']))

    def test_native_field_edit_with_opaque_refresh_retains_typed_change(self):
        for engine in ['unity','godot','unreal']:
            with self.subTest(engine=engine):
                c=context(engine);engine_edit(c)
                raw=json.loads(c['native_inventory']);raw['objects'][oid(2)]['opaque']=opaque()
                c['native_inventory']=canonical(raw);refresh(c)
                r=plan_reconciliation(**c).to_dict()
                self.assertTrue(r['reviewable'],r['losses'])
                self.assertEqual(len(r['typed_operations']['operations']),1)
                self.assertIsNone(r['native_write_preview'])
                self.assertFalse(r['can_commit'])

    def test_critical_behavior_still_blocks(self):
        c=context();raw=json.loads(c['native_inventory']);raw['objects'][oid(2)]['opaque']=opaque(True)
        c['native_inventory']=canonical(raw);refresh(c)
        r=plan_reconciliation(**c).to_dict()
        self.assertFalse(r['reviewable'])
        self.assertTrue(any(v['severity']=='blocking' for v in r['losses']))

    def test_canonical_attempt_to_change_opaque_still_blocks(self):
        b,x,e,p=rows();x[oid(2)]['opaque']=opaque()
        r=reconcile_records(b,x,e,p).to_dict()
        self.assertTrue(any(v['code']=='native_code_is_not_cgs' for v in r['losses']))
        self.assertEqual(r['merged'][oid(2)]['opaque'],e[oid(2)]['opaque'])

    def test_real_structure_with_opaque_refresh_still_requires_review(self):
        b,x,e,p=rows();e[oid(2)]['opaque']=opaque();e[oid(2)]['parent_id']=oid(3)
        r=reconcile_records(b,x,e,p).to_dict()
        self.assertTrue(any(v['kind']=='review_structure' for v in r['canonical_proposals']))


if __name__=='__main__':unittest.main()
