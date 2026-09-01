import asyncio
import sys
import tempfile
import unittest
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from agent_host.contracts import (  # noqa: E402
    AgentAuthState,
    AgentCapabilities,
    AgentEvent,
    AgentEventType,
    AgentProviderKind,
    AgentProviderStatus,
    AgentSessionHandle,
    AgentStartRequest,
    AgentTurnRequest,
)
from agent_host.event_stream import (  # noqa: E402
    AGENT_EVENT_STREAM_SCHEMA,
    AgentEventStreamManager,
)
from agent_host.mock_agent import MockAgentAdapter  # noqa: E402
from agent_host.registry import AgentAdapterRegistry  # noqa: E402
from agent_host.session_store import AgentSessionStore  # noqa: E402


CGS_HASH = "c" * 64
FIXED_TIME = "2026-09-01T00:00:00Z"


class SlowCancellableAdapter:
    provider_id = "slow"

    def __init__(self) -> None:
        self.cancel_called = False
        self.started = asyncio.Event()

    async def detect(self) -> AgentProviderStatus:
        return AgentProviderStatus(
            provider_id=self.provider_id,
            display_name="Slow Agent",
            provider_kind=AgentProviderKind.CUSTOM,
            installed=True,
            available=True,
            auth_state=AgentAuthState.NOT_REQUIRED,
            capabilities=AgentCapabilities(
                supports_streaming_events=True,
                supports_cancellation=True,
            ),
        )

    async def list_capabilities(self) -> AgentCapabilities:
        return (await self.detect()).capabilities

    async def start_session(self, request: AgentStartRequest) -> AgentSessionHandle:
        return AgentSessionHandle(
            xace_session_id=request.xace_session_id,
            provider_id=self.provider_id,
            provider_session_id=f"slow-thread-{request.xace_session_id}",
            base_cgs_hash=request.base_cgs_hash,
            latest_cgs_hash=request.base_cgs_hash,
            created_at=FIXED_TIME,
        )

    async def resume_session(self, handle: AgentSessionHandle) -> AgentSessionHandle:
        return handle

    async def cancel_turn(self, handle: AgentSessionHandle) -> None:
        del handle
        self.cancel_called = True

    async def run_turn(self, request: AgentTurnRequest):
        self.started.set()
        yield AgentEvent(
            event_id="slow-event-1",
            event_type=AgentEventType.TURN_STARTED,
            session_id=request.handle.xace_session_id,
            provider_id=self.provider_id,
            sequence=1,
            message="Slow turn started.",
            created_at=FIXED_TIME,
        )
        await asyncio.sleep(60)
        yield AgentEvent(
            event_id="slow-event-2",
            event_type=AgentEventType.TURN_COMPLETED,
            session_id=request.handle.xace_session_id,
            provider_id=self.provider_id,
            sequence=2,
            message="Slow turn completed.",
            created_at=FIXED_TIME,
        )


async def _collecting_send(messages: list[dict], message: dict) -> None:
    messages.append(message)


class AgentEventStreamTests(unittest.TestCase):
    def test_mock_events_stream_in_order_and_are_logged(self) -> None:
        async def scenario() -> tuple[list[dict], list[str]]:
            messages: list[dict] = []
            with tempfile.TemporaryDirectory() as temp_dir:
                store = AgentSessionStore(temp_dir)
                manager = AgentEventStreamManager(
                    AgentAdapterRegistry([MockAgentAdapter(clock=lambda: FIXED_TIME)]),
                    session_store=store,
                    clock=lambda: 123.0,
                )
                result = await manager.start_turn(
                    session_id="session-1",
                    provider_id="mock",
                    user_prompt="Inspect the current project.",
                    cgs_hash=CGS_HASH,
                    allowed_tools=("xace.read_cgs",),
                    send_fn=lambda message: _collecting_send(messages, message),
                )
                self.assertTrue(result.accepted)
                await manager.wait_for_turn("session-1")
                persisted = store.list_events("session-1")
                return messages, [event.event_type.value for event in persisted]

        messages, persisted_event_types = asyncio.run(scenario())
        self.assertEqual(messages[0]["type"], "agent_status")
        self.assertEqual(messages[0]["state"], "running")
        events = [message for message in messages if message["type"] == "agent_event"]
        self.assertEqual(
            [event["event_type"] for event in events],
            ["turn_started", "status", "proposal", "turn_completed"],
        )
        self.assertEqual([event["stream_sequence"] for event in events], [1, 2, 3, 4])
        self.assertEqual(events[0]["schema"], AGENT_EVENT_STREAM_SCHEMA)
        self.assertEqual(messages[-1]["type"], "agent_status")
        self.assertEqual(messages[-1]["state"], "completed")
        self.assertEqual(persisted_event_types, [
            "turn_started",
            "status",
            "proposal",
            "turn_completed",
        ])

    def test_cancel_turn_emits_cancelling_and_cancelled_without_leaving_active_turn(self) -> None:
        async def scenario() -> tuple[list[dict], SlowCancellableAdapter]:
            messages: list[dict] = []
            adapter = SlowCancellableAdapter()
            manager = AgentEventStreamManager(
                AgentAdapterRegistry([adapter]),
                clock=lambda: 456.0,
            )
            await manager.start_turn(
                session_id="session-1",
                provider_id="slow",
                user_prompt="Do slow work.",
                cgs_hash=CGS_HASH,
                send_fn=lambda message: _collecting_send(messages, message),
            )
            await adapter.started.wait()
            await manager.cancel_turn(
                session_id="session-1",
                provider_id="slow",
                send_fn=lambda message: _collecting_send(messages, message),
            )
            await manager.wait_for_turn("session-1")
            await manager.send_status(
                session_id="session-1",
                provider_id="slow",
                send_fn=lambda message: _collecting_send(messages, message),
            )
            return messages, adapter

        messages, adapter = asyncio.run(scenario())
        self.assertTrue(adapter.cancel_called)
        states = [message["state"] for message in messages if message["type"] == "agent_status"]
        self.assertIn("cancelling", states)
        self.assertEqual(states[-1], "cancelled")
        event_types = [
            message["event_type"]
            for message in messages
            if message["type"] == "agent_event"
        ]
        self.assertIn("turn_cancelled", event_types)

    def test_rejects_second_turn_while_one_is_running(self) -> None:
        async def scenario() -> list[dict]:
            messages: list[dict] = []
            adapter = SlowCancellableAdapter()
            manager = AgentEventStreamManager(AgentAdapterRegistry([adapter]))
            await manager.start_turn(
                session_id="session-1",
                provider_id="slow",
                user_prompt="First turn.",
                cgs_hash=CGS_HASH,
                send_fn=lambda message: _collecting_send(messages, message),
            )
            await adapter.started.wait()
            result = await manager.start_turn(
                session_id="session-1",
                provider_id="slow",
                user_prompt="Second turn.",
                cgs_hash=CGS_HASH,
                send_fn=lambda message: _collecting_send(messages, message),
            )
            self.assertFalse(result.accepted)
            await manager.cancel_turn(
                session_id="session-1",
                provider_id="slow",
                send_fn=lambda message: _collecting_send(messages, message),
            )
            await manager.wait_for_turn("session-1")
            return messages

        messages = asyncio.run(scenario())
        self.assertIn(
            "AGENT_TURN_ALREADY_RUNNING",
            [message.get("code") for message in messages],
        )

    def test_unknown_provider_reports_unavailable_status(self) -> None:
        async def scenario() -> list[dict]:
            messages: list[dict] = []
            manager = AgentEventStreamManager(AgentAdapterRegistry([]))
            result = await manager.start_turn(
                session_id="session-1",
                provider_id="codex",
                user_prompt="Inspect.",
                cgs_hash=CGS_HASH,
                send_fn=lambda message: _collecting_send(messages, message),
            )
            self.assertFalse(result.accepted)
            return messages

        messages = asyncio.run(scenario())
        self.assertEqual(messages[-1]["type"], "agent_status")
        self.assertEqual(messages[-1]["state"], "unavailable")
        self.assertEqual(messages[-1]["code"], "AGENT_PROVIDER_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
