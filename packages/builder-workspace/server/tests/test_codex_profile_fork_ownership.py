"""Profile-specific branch transports must not share MCP authority or queues."""
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agent_host.codex_linux_profile import CodexLinuxProfileAdapter
from agent_host.codex_adapter import CodexAppServerAdapter


class ProfileForkOwnershipTests(unittest.TestCase):
    def adapter(self):
        adapter = object.__new__(CodexLinuxProfileAdapter)
        adapter._lock = threading.RLock()
        adapter._active_turns = {}
        return adapter

    def test_both_shared_bindings_are_closed_after_fork(self):
        adapter = self.adapter()
        parent = SimpleNamespace(provider_session_id='parent')
        child = SimpleNamespace(provider_session_id='child')
        closed = []
        adapter._close_thread_client = closed.append
        with patch.object(CodexAppServerAdapter,'_fork_session_sync',return_value=child):
            self.assertIs(adapter._fork_session_sync(parent),child)
        self.assertEqual(closed,['child','parent'])

    def test_active_turn_is_never_closed_by_fork(self):
        adapter = self.adapter()
        adapter._active_turns['parent'] = 'turn'
        with patch.object(CodexAppServerAdapter,'_fork_session_sync') as fork:
            with self.assertRaises(ValueError): adapter._fork_session_sync(SimpleNamespace())
        fork.assert_not_called()
