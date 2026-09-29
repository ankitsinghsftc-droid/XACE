import asyncio
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_host import AgentStartRequest, AgentTurnRequest
from agent_host.codex_adapter import CodexAppServerAdapter, CodexExecutableCandidate, CodexAppServerProtocolError
from test_agent_codex_lifecycle import FakeCodexClient, FakeClientFactory, _adapter
from test_agent_codex_native_mcp import _bridge, _NativeMcpClient
from test_agent_codex_runtime_lifecycle import _lifecycle, _runtime


class RecoveryEdgeTests(unittest.TestCase):
    def test_cancel_while_starting_waits_for_worker_then_closes(self):
        entered, release = threading.Event(), threading.Event()
        class Slow(FakeCodexClient):
            def request(self, method, params):
                if method == 'turn/start':
                    entered.set(); release.wait(2)
                return super().request(method, params)
        async def run():
            client = Slow(); adapter = _adapter(FakeClientFactory(client))
            with tempfile.TemporaryDirectory() as tmp:
                handle = await adapter.start_session(AgentStartRequest(xace_session_id='edge', user_prompt='inspect',
                    base_cgs_hash='a'*64, context_capsule_path=str(Path(tmp)/'.xace/agent_capsules/edge.json'), metadata={'project_path':tmp}))
                async def consume():
                    async for _ in adapter.run_turn(AgentTurnRequest(handle=handle, user_prompt='inspect', base_cgs_hash='a'*64)): pass
                task = asyncio.create_task(consume())
                await asyncio.to_thread(entered.wait, 2)
                task.cancel(); release.set()
                with self.assertRaises(asyncio.CancelledError): await task
                self.assertTrue(client.closed)
                self.assertFalse(adapter._clients)
                self.assertFalse(adapter._active_turns)
        asyncio.run(run())

    def test_mcp_disconnect_before_turn_fails_closed_and_revokes_transport(self):
        async def run():
            bridge = _bridge(); client = _NativeMcpClient(bridge)
            adapter = CodexAppServerAdapter(executable_resolver=lambda: CodexExecutableCandidate('test.exe','test'),
                client_factory=lambda _:client, tool_bridge_factory=lambda _:bridge)
            with tempfile.TemporaryDirectory() as tmp:
                handle = await adapter.start_session(AgentStartRequest(xace_session_id='session-native-mcp-1', user_prompt='inspect',
                    base_cgs_hash='e'*64, context_capsule_path=str(Path(tmp)/'.xace/agent_capsules/edge.json'), metadata={'project_path':tmp}))
                client.runtime_status = 'failed'
                with self.assertRaisesRegex(CodexAppServerProtocolError, 'not connected'):
                    async for _ in adapter.run_turn(AgentTurnRequest(handle=handle, user_prompt='inspect', base_cgs_hash='e'*64)): pass
                self.assertFalse(any(m == 'turn/start' for m,_ in client.requests))
                self.assertTrue(client.closed)
                self.assertFalse(adapter._native_mcp_transports)
        asyncio.run(run())

    def test_pin_persists_fingerprint_artifact_and_old_profile_requires_recheck(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); lifecycle = _lifecycle(root/'state')
            state = lifecycle.verify_and_activate(_runtime(root/'codex.exe','0.143.0'), confirm_official_install=True)
            fingerprint = state['active']['schema_fingerprint']
            self.assertTrue((root/'state/schemas'/f'{fingerprint}.json').is_file())
            record = json.loads(lifecycle.state_path.read_text())
            del record['active']['compatibility_profile']
            lifecycle.state_path.write_text(json.dumps(record))
            self.assertEqual(lifecycle.inspect()['active_health']['code'], 'schema_reverification_required')

    def test_blocked_pipe_write_is_bounded(self):
        # Reuse the actual-subprocess harness without re-registering its tests.
        from test_agent_codex_resilience import StdioResilienceTests
        harness = StdioResilienceTests()
        try:
            session, proc = harness.session('import time; time.sleep(10)')
            with self.assertRaises(CodexAppServerProtocolError):
                session.request('turn/start', {'input': 'x'*200000})
            self.assertIsNotNone(proc.poll())
        finally:
            harness.doCleanups()
