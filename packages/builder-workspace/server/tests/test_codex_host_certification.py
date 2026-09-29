"""The live certificate must not turn a partial pass into completion."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'tools'))
from codex_host_backend_probe import REQUIRED_CHECKS, certify


class HostCertificationTests(unittest.TestCase):
    def test_every_required_live_check_is_mandatory(self):
        valid = {key: True for key in REQUIRED_CHECKS}
        valid.update(model_count=5, errors=[])
        self.assertTrue(certify(valid))
        for key in REQUIRED_CHECKS:
            for missing in (False, None, 'true'):
                with self.subTest(key=key, missing=missing):
                    self.assertFalse(certify({**valid, key: missing}))
        self.assertFalse(certify({**valid, 'model_count': 0}))
        self.assertFalse(certify({**valid, 'errors': ['provider error']}))

