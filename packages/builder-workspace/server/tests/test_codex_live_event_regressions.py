"""Regressions from AG-029 real App Server lifecycle evidence."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_host.codex_adapter import _validate_turn_notification, CodexAppServerProtocolError


class LiveEventRegressionTests(unittest.TestCase):
    def test_resume_accounting_snapshot_is_not_current_turn_usage(self):
        event = {'method':'thread/tokenUsage/updated','params':{'threadId':'thread','turnId':'old'}}
        self.assertIs(_validate_turn_notification(event,'thread','new'),False)

    def test_stale_tool_and_cross_thread_events_still_fail_closed(self):
        for event in (
            {'method':'item/completed','params':{'threadId':'thread','turnId':'old'}},
            {'method':'thread/tokenUsage/updated','params':{'threadId':'other','turnId':'old'}},
            {'id':1,'method':'thread/tokenUsage/updated','params':{'threadId':'thread','turnId':'old'}},
        ):
            with self.assertRaises(CodexAppServerProtocolError):
                _validate_turn_notification(event,'thread','new')
