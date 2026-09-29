"""Negative admission tests; temporary records are never production evidence."""
import copy
from datetime import date
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'tools'))
from codex_completion_evidence import AGENT, AREAS, HOST, ISOLATION, SETUP, REVIEW, digest, validate_evidence, production_hashes


class CompletionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for relative in (AGENT, 'tools/ag029_container', 'docs/evidence'):
            shutil.copytree(ROOT / relative, self.root / relative)
        self.host = json.loads((self.root / HOST).read_text())
        self.host['artifact_hashes'] = {p.relative_to(self.root).as_posix(): digest(p)
            for p in (self.root / AGENT).glob('*.py')}
        self.write(HOST, self.host)
        self.review = {'schema': 'xace.codex_completion_review.v1', 'reviewed_at': '2026-09-22',
            'reviewer': 'unit-test-only', 'reviewed_areas': sorted(AREAS), 'review_complete': True,
            'terminal_free_setup_verified': True,
            'image_id': json.loads((self.root / ISOLATION).read_text())['image_id'],
            'evidence_sha256': {p: digest(self.root / p) for p in (HOST, ISOLATION, SETUP)},
            'source_sha256': production_hashes(self.root),
            'issues': [{'id': 'upstream_support', 'severity': 'P2', 'status': 'accepted',
                        'accepted_by': 'unit-test-only', 'acceptance_reference': 'test fixture',
                        'rationale': 'test-only', 'mitigation': 'test-only'}]}
        setup = json.loads((self.root / SETUP).read_text())
        setup['image_id'] = self.review['image_id']
        self.write(SETUP, setup)
        self.review['evidence_sha256'][SETUP] = digest(self.root / SETUP)
        self.write(REVIEW, self.review)

    def write(self, path, value):
        (self.root / path).write_text(json.dumps(value), encoding='utf8')

    def check(self): return validate_evidence(self.root, today=date(2026, 9, 22))

    def test_complete_fixture_validates_only_inside_test_directory(self):
        self.assertEqual(self.check()['blockers'], [])

    def test_changed_source_or_missing_file_is_rejected(self):
        (self.root / AGENT / 'execution_setup.py').write_text('changed')
        self.assertIn('ag029_real_runtime_account_evidence_invalid', self.check()['blockers'])

    def test_partial_live_check_rejected_even_with_rebound_review(self):
        self.host['real_sgc_handoff'] = False; self.write(HOST, self.host)
        self.review['evidence_sha256'][HOST] = digest(self.root / HOST); self.write(REVIEW, self.review)
        self.assertIn('ag029_real_runtime_account_evidence_invalid', self.check()['blockers'])

    def test_empty_defect_review_stale_review_or_unaccepted_risk_blocks(self):
        for changes in ({'issues': []}, {'reviewed_at': '2026-01-01'},
                        {'terminal_free_setup_verified': False}, {'review_complete': False},
                        {'issues': [{'id': 'risk', 'severity': 'P2', 'status': 'pending'}]},
                        {'issues': [{'id': 'defect', 'severity': 'P1', 'status': 'accepted', 'accepted_by': 'anyone'}]}):
            with self.subTest(changes=changes):
                self.write(REVIEW, {**copy.deepcopy(self.review), **changes})
                self.assertTrue(self.check()['blockers'])

    def test_partial_isolation_or_unknown_image_binding_is_rejected(self):
        value = json.loads((self.root / ISOLATION).read_text())
        value['checks'][0]['checks']['write_denied'] = False
        self.write(ISOLATION, value)
        self.assertIn('ag029_isolation_evidence_invalid', self.check()['blockers'])
