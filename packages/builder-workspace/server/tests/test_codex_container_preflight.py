from pathlib import Path
import json
import subprocess
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[4] / 'tools'))
from codex_container_preflight import command, normalize, IMAGE


class ContainerPreflightTests(unittest.TestCase):
    def result(self, value, code=0):
        return subprocess.CompletedProcess([],code,json.dumps(value),'secret-stderr')

    def test_fixed_command_has_no_host_data_or_network(self):
        value = command(Path('docker'), 'probe.py')
        self.assertIn(IMAGE,value)
        self.assertIn('--read-only',value)
        self.assertEqual(value[value.index('--network')+1],'none')
        self.assertEqual(value[value.index('--cap-drop')+1],'ALL')
        self.assertNotIn('unconfined',' '.join(value))
        self.assertNotIn('--privileged',value)
        self.assertEqual(value.count('--mount'),1)
        self.assertTrue(value[value.index('--mount')+1].endswith('target=/probe.py,readonly'))

    def test_unknown_probe_cannot_be_executed(self):
        with self.assertRaises(ValueError): command(Path('docker'),'../../arbitrary.py')

    def test_missing_malformed_and_failed_evidence_fail_closed(self):
        for probe in ('probe.py','native_probe.py'):
            for data in ({},None,[],{'account_calls_performed':False}):
                self.assertFalse(normalize(probe,self.result(data))['passed'])
            self.assertFalse(normalize(probe,subprocess.CompletedProcess([],0,'invalid',''))['passed'])

    def test_sandbox_pass_requires_every_check(self):
        checks = dict.fromkeys(('allowed_read','outside_read_denied','write_denied'),True)
        value = {'exit_code':0,'stdout':json.dumps(checks),'account_calls_performed':False}
        self.assertTrue(normalize('probe.py',self.result(value))['passed'])
        for key in checks:
            bad = {**value,'stdout':json.dumps({**checks,key:False})}
            self.assertFalse(normalize('probe.py',self.result(bad))['passed'])
        self.assertFalse(normalize('probe.py',self.result(value,1))['passed'])

    def test_native_pass_requires_observed_execution_and_no_leak(self):
        value = {'private_content_exposed':False,'private_file_unchanged':True,
                 'fake_model_requests':2,'tool_outputs':[{}],'event_methods':['turn/completed'],
                 'error':None,'account_calls_performed':False}
        report = normalize('native_probe.py',self.result(value))
        self.assertTrue(report['passed'])
        self.assertNotIn('secret',str(report))
        for key,bad in [('private_content_exposed',True),('private_file_unchanged',False),
                        ('fake_model_requests',0),('tool_outputs',[]),('event_methods',[]),
                        ('error','failure'),('account_calls_performed',True)]:
            self.assertFalse(normalize('native_probe.py',self.result({**value,key:bad}))['passed'])
