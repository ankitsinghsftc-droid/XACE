import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from agent_host.event_stream import AgentEventStreamManager  # noqa: E402
from agent_host.mock_agent import MockAgentAdapter  # noqa: E402
from agent_host.registry import AgentAdapterRegistry  # noqa: E402
from ws_message_router import WSMessageRouter  # noqa: E402


CGS_HASH = "d" * 64


class FakeSessionManager:
    def __init__(self) -> None:
        self._sessions = {
            "session-1": SimpleNamespace(
                project_path="C:/tmp/xace-project",
                pending_txn=None,
                pending_prompt_preview=None,
                pending_prompt_result=None,
                pending_prompt_clarification=None,
                pending_clar_id=None,
                runtime_connected=False,
                runtime_adapter_type="",
                runtime_last_hash="",
                runtime_last_tick=None,
            )
        }


def _cgs() -> dict:
    return {
        "metadata": {
            "name": "Agent WS Test",
            "schema_version": "0.1.0",
            "cgs_hash": CGS_HASH,
        },
        "component_schemas": [],
        "modes": [],
        "global_systems": [],
        "semantic_events": [],
        "assets": [],
    }


async def _send(messages: list[dict], message: dict) -> None:
    messages.append(message)


class AgentWsEventStreamTests(unittest.TestCase):
    def test_router_streams_agent_turn_and_installs_preview(self) -> None:
        async def scenario() -> list[dict]:
            messages: list[dict] = []
            manager = AgentEventStreamManager(
                AgentAdapterRegistry([MockAgentAdapter()])
            )
            router = WSMessageRouter(
                FakeSessionManager(),
                agent_event_stream=manager,
            )
            await router.route(
                "session-1",
                {
                    "type": "agent_turn",
                    "provider_id": "mock",
                    "prompt": "Inspect project.",
                    "cgs_hash": CGS_HASH,
                    "allowed_tools": ["xace.read_cgs"],
                },
                lambda message: _send(messages, message),
                persist=None,
                cgs_state=_cgs(),
            )
            await manager.wait_for_turn("session-1")
            return messages

        messages = asyncio.run(scenario())
        self.assertEqual(messages[0]["type"], "agent_status")
        self.assertEqual(messages[0]["state"], "running")
        self.assertEqual(
            [message["event_type"] for message in messages if message["type"] == "agent_event"],
            ["turn_started", "status", "proposal", "turn_completed"],
        )
        previews = [message for message in messages if message["type"] == "pil_result"]
        self.assertEqual(len(previews), 1)
        result = previews[0]["result"]
        self.assertEqual(result["kind"], "mutation")
        self.assertEqual(result["source"], "agent_proposal")
        self.assertEqual(
            result["preview"]["cgs_diff"]["operations"][0]["kind"],
            "declare_component",
        )

    def test_router_agent_status_reports_unavailable_when_no_adapter_is_registered(self) -> None:
        async def scenario() -> list[dict]:
            messages: list[dict] = []
            router = WSMessageRouter(FakeSessionManager())
            await router.route(
                "session-1",
                {"type": "agent_status"},
                lambda message: _send(messages, message),
                persist=None,
                cgs_state=_cgs(),
            )
            return messages

        messages = asyncio.run(scenario())
        self.assertEqual(messages, [
            {
                "type": "agent_status",
                "schema": "xace.agent_event_stream.v1",
                "session_id": "session-1",
                "provider_id": "",
                "turn_id": "",
                "state": "unavailable",
                "code": "AGENT_PROVIDER_REQUIRED",
                "message": "No certified agent provider is active.",
                "running": False,
                "cancellable": False,
                "last_event_sequence": 0,
                "event_count": 0,
                "updated_at": messages[0]["updated_at"],
                "ui_state": {
                    "state": "unavailable",
                    "label": "Agent unavailable",
                    "severity": "warning",
                    "busy": False,
                    "terminal": True,
                },
            }
        ])

    def test_router_agent_cancel_without_turn_is_structured_status_not_server_error(self) -> None:
        async def scenario() -> list[dict]:
            messages: list[dict] = []
            router = WSMessageRouter(
                FakeSessionManager(),
                agent_event_stream=AgentEventStreamManager(
                    AgentAdapterRegistry([MockAgentAdapter()])
                ),
            )
            await router.route(
                "session-1",
                {"type": "agent_cancel", "provider_id": "mock"},
                lambda message: _send(messages, message),
                persist=None,
                cgs_state=_cgs(),
            )
            return messages

        messages = asyncio.run(scenario())
        self.assertEqual(messages[-1]["type"], "agent_status")
        self.assertEqual(messages[-1]["code"], "NO_ACTIVE_AGENT_TURN")
        self.assertFalse([message for message in messages if message["type"] == "server_error"])


if __name__ == "__main__":
    unittest.main()
