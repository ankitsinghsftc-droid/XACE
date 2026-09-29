import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[4]/'tools'))
from codex_container_live_check import evaluate, REQUIRED_CHECKS, command


class LiveEvidenceTests(unittest.TestCase):
    def test_empty_and_each_missing_check_fail(self):
        self.assertFalse(evaluate({})['candidate_scenarios_passed'])
        good = dict.fromkeys(REQUIRED_CHECKS,True)
        good.update(auth_state='signed_in',recovery_terminal='turn_completed')
        self.assertTrue(evaluate(good)['candidate_scenarios_passed'])
        for key in REQUIRED_CHECKS:
            self.assertFalse(evaluate({**good,key:False})['candidate_scenarios_passed'],key)
        self.assertFalse(evaluate({**good,'failure_code':'stale_event'})['candidate_scenarios_passed'])

    def test_launcher_never_mounts_real_project_or_docker_socket(self):
        args = command(Path('docker'))
        self.assertIn('--read-only',args)
        self.assertIn('no-new-privileges',args)
        self.assertNotIn('--privileged',args)
        self.assertFalse(any('docker.sock' in arg for arg in args))
        mounts = [args[i+1] for i,arg in enumerate(args) if arg=='--mount']
        self.assertEqual(len(mounts),3)
        self.assertTrue(all(m.endswith(',readonly') for m in mounts if m.startswith('type=bind')))
