import asyncio
import copy
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_host.codex_protocol import JsonRpcLineSession, CodexAppServerProtocolError
from agent_host.codex_compatibility import validate_schema, version_policy
from agent_host.codex_adapter import _validate_turn_notification
from codex_schema_fixture import schema_fixture


class SchemaCompatibilityTests(unittest.TestCase):
    def test_additive_changes_preserve_compatibility_but_change_evidence(self):
        original = schema_fixture()
        changed = copy.deepcopy(original)
        changed['ClientRequest.json']['oneOf'][0]['properties']['optionalFuture'] = {'type': 'boolean'}
        self.assertNotEqual(validate_schema(original)['schema_fingerprint'], validate_schema(changed)['schema_fingerprint'])

    def test_breaking_request_shape_required_field_or_enum_fails_closed(self):
        for mutation in ('missing', 'type', 'required', 'enum'):
            schema = schema_fixture()
            branch = next(x for x in schema['ClientRequest.json']['oneOf'] if x['properties']['method']['const'] == 'turn/start')
            params = branch['properties']['params']
            if mutation == 'missing': del params['properties']['sandboxPolicy']
            if mutation == 'type': params['properties']['threadId'] = {'type': 'integer'}
            if mutation == 'required': params['required'].append('newRequired')
            if mutation == 'enum': params['properties']['approvalPolicy']['enum'] = ['always']
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, 'turn/start'):
                validate_schema(schema)

    def test_prereleases_unknown_major_and_out_of_window_fail(self):
        for version in ('0.154.0-alpha.6.2', '1.0.0', '0.155.0', '0.142.9', 'unknown'):
            with self.subTest(version=version), self.assertRaises(ValueError): version_policy(version)
        self.assertIn('schema_verified', version_policy('0.143.0')['certification'])

    def test_stale_and_malformed_events_rejected(self):
        for event in ({'method':'turn/completed','params':{'turn':{'id':'other','status':'completed'}}},
                      {'method':'turn/completed','params':{'turn':{'id':'turn','status':'unknown'}}},
                      {'method':'item/started','params':{'threadId':'other'}},
                      {'method':'item/started','params':[]}):
            with self.assertRaises(CodexAppServerProtocolError): _validate_turn_notification(event, 'thread', 'turn')


class StdioResilienceTests(unittest.TestCase):
    def session(self, code, timeout=.25):
        proc = subprocess.Popen([sys.executable, '-u', '-c', code], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf8')
        session = JsonRpcLineSession(proc, timeout_seconds=timeout)
        self.addCleanup(session.close)
        return session, proc

    def test_success_and_unit_logout_wire_shape(self):
        session, _ = self.session("import sys,json; r=json.loads(sys.stdin.readline()); print(json.dumps({'id':r['id'],'result':{'null':r['params'] is None}})); sys.stdin.read()")
        self.assertTrue(session.request('account/logout', {})['null'])

    def test_malformed_frames_and_response_ids_close_process(self):
        for frame in ('not-json', '[]', '{"id":1,"result":{},"result":{}}',
                      '{"id":1,"result":{},"error":{}}', '{"id":99,"result":{}}',
                      '{"id":true,"result":{}}', '{"id":1,"result":{"value":NaN}}'):
            with self.subTest(frame=frame):
                session, proc = self.session(f'import sys,time; sys.stdin.readline(); print({frame!r},flush=True); time.sleep(10)')
                with self.assertRaises(CodexAppServerProtocolError): session.request('initialize', {})
                self.assertIsNotNone(proc.poll())
                self.assertFalse(session._reader.is_alive())

    def test_timeout_and_crash_are_bounded_and_reaped(self):
        for code in ('import time; time.sleep(10)', 'raise SystemExit(3)'):
            session, proc = self.session(code)
            started = time.monotonic()
            with self.assertRaises(CodexAppServerProtocolError): session.request('turn/start', {})
            self.assertLess(time.monotonic()-started, 3)
            self.assertIsNotNone(proc.poll())

    def test_oversized_frame_and_backpressure_fail_instead_of_dropping(self):
        for payload in ("print('x'*300000,flush=True)",
                        "\nfor i in range(2000): print('{\"method\":\"event\",\"params\":{}}',flush=True)"):
            session, proc = self.session('import time\n'+payload+'\ntime.sleep(10)')
            session._reader.join(timeout=2)
            with self.assertRaises(CodexAppServerProtocolError): session.read_notification()
            self.assertIsNotNone(proc.poll())

    def test_notification_buffer_during_rpc_is_bounded(self):
        session, proc = self.session("import sys,time; sys.stdin.readline()\nfor i in range(100):\n print('{\"method\":\"event\",\"params\":{}}',flush=True); time.sleep(.002)\ntime.sleep(10)", timeout=2)
        with self.assertRaises(CodexAppServerProtocolError): session.request('initialize', {})
        self.assertIsNotNone(proc.poll())

    def test_provider_errors_are_sanitized_without_retrying(self):
        session, _ = self.session("import sys,json; r=json.loads(sys.stdin.readline()); print(json.dumps({'id':r['id'],'error':{'code':429,'message':'rate limit SECRET-CANARY'}})); sys.stdin.read()")
        with self.assertRaisesRegex(CodexAppServerProtocolError, 'rate limit') as raised: session.request('turn/start', {})
        self.assertNotIn('SECRET-CANARY', str(raised.exception))

    def test_idle_close_does_not_deadlock_reader(self):
        session, proc = self.session('import time; time.sleep(10)')
        started = time.monotonic(); session.close(); session.close()
        self.assertLess(time.monotonic()-started, 3)
        self.assertFalse(session._reader.is_alive())
        self.assertIsNotNone(proc.poll())


if __name__ == '__main__': unittest.main()
