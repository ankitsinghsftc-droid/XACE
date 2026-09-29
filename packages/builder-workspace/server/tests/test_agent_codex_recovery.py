import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_host import AgentStartRequest, AgentTurnRequest
from agent_host.codex_adapter import CodexAppServerProtocolError
from test_agent_codex_lifecycle import FakeCodexClient, FakeClientFactory, _adapter


class FaultClient(FakeCodexClient):
    def __init__(self, method, *, wrong_thread=False):
        super().__init__()
        self.fail_method = method
        self.wrong_thread = wrong_thread

    def request(self, method, params):
        if method == self.fail_method:
            self.requests.append((method, params))
            raise CodexAppServerProtocolError('fixture failure', code='process_exited', retryable=True)
        value = super().request(method, params)
        if self.wrong_thread and method == 'thread/resume': value['thread']['id'] = 'wrong-thread'
        return value


class AdapterRecoveryTests(unittest.TestCase):
    def request(self, root):
        return AgentStartRequest(xace_session_id='session-1', user_prompt='Inspect', base_cgs_hash='a'*64,
                                 context_capsule_path=str(root / '.xace/agent_capsules/session-1.json'),
                                 metadata={'project_path': str(root)})

    def test_initialization_retries_once_and_reaps_failed_process(self):
        async def run():
            failed, good = FaultClient('initialize'), FakeCodexClient()
            factory = FakeClientFactory(failed, good); adapter = _adapter(factory)
            with tempfile.TemporaryDirectory() as tmp:
                await adapter.start_session(self.request(Path(tmp)))
            self.assertTrue(failed.closed)
            self.assertEqual(len(factory.created), 2)
            adapter.close(); self.assertTrue(good.closed)
        asyncio.run(run())

    def test_initialization_budget_is_two_processes(self):
        async def run():
            clients = [FaultClient('initialize'), FaultClient('initialize'), FakeCodexClient()]
            factory = FakeClientFactory(*clients); adapter = _adapter(factory)
            with tempfile.TemporaryDirectory() as tmp, self.assertRaises(CodexAppServerProtocolError):
                await adapter.start_session(self.request(Path(tmp)))
            self.assertEqual(len(factory.created), 2)
            self.assertTrue(all(c.closed for c in factory.created))
            adapter.close()
        asyncio.run(run())

    def test_failed_turn_start_is_not_replayed_and_closes_client(self):
        async def run():
            client = FaultClient('turn/start'); factory = FakeClientFactory(client); adapter = _adapter(factory)
            with tempfile.TemporaryDirectory() as tmp:
                handle = await adapter.start_session(self.request(Path(tmp)))
                with self.assertRaises(CodexAppServerProtocolError):
                    async for _ in adapter.run_turn(AgentTurnRequest(handle=handle, user_prompt='Inspect', base_cgs_hash='a'*64)): pass
            self.assertEqual(sum(m == 'turn/start' for m,_ in client.requests), 1)
            self.assertTrue(client.closed)
            self.assertFalse(adapter._clients)
        asyncio.run(run())

    def test_idle_turn_terminates_and_can_be_explicitly_resumed(self):
        async def run():
            first, resumed = FakeCodexClient(), FakeCodexClient()
            adapter = _adapter(FakeClientFactory(first, resumed)); adapter._turn_idle_timeout_seconds = .05
            with tempfile.TemporaryDirectory() as tmp:
                handle = await adapter.start_session(self.request(Path(tmp)))
                with self.assertRaisesRegex(CodexAppServerProtocolError, 'idle timeout'):
                    async for _ in adapter.run_turn(AgentTurnRequest(handle=handle, user_prompt='Inspect', base_cgs_hash='a'*64)): pass
                self.assertTrue(first.closed)
                next_handle = await adapter.resume_session(handle)
                self.assertEqual(next_handle.provider_session_id, handle.provider_session_id)
                self.assertFalse(any(m == 'turn/start' for m,_ in resumed.requests))
            adapter.close()
        asyncio.run(run())

    def test_stale_resume_never_silently_creates_a_different_thread(self):
        async def run():
            first, wrong = FakeCodexClient(), FaultClient('none', wrong_thread=True)
            adapter = _adapter(FakeClientFactory(first, wrong))
            with tempfile.TemporaryDirectory() as tmp:
                handle = await adapter.start_session(self.request(Path(tmp)))
                with self.assertRaisesRegex(CodexAppServerProtocolError, 'different thread'):
                    await adapter.resume_session(handle)
            self.assertTrue(first.closed and wrong.closed)
            self.assertFalse(adapter._clients)
        asyncio.run(run())


if __name__ == '__main__': unittest.main()
