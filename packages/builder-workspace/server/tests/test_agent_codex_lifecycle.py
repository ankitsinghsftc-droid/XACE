import asyncio
import contextlib
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any


SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from agent_host import (  # noqa: E402
    AgentAdapterRegistry,
    AgentEventStreamManager,
    AgentEventType,
    AgentSessionStore,
    AgentStartRequest,
    AgentTurnRequest,
    CODEX_APP_SERVER_PROVIDER_ID,
    CodexAppServerAdapter,
    CodexExecutableCandidate,
)


CGS_HASH = "a" * 64
NEW_CGS_HASH = "b" * 64
FIXED_TIME = "2026-09-01T00:00:00Z"
FAKE_CODEX_PATH = "C:/tools/codex.exe"


class FakeCodexClient:
    def __init__(
        self,
        *,
        thread_id: str = "codex-thread-1",
        fork_id: str = "codex-thread-fork",
        turn_id: str = "codex-turn-1",
        notifications: list[dict[str, Any]] | None = None,
    ) -> None:
        self.thread_id = thread_id
        self.fork_id = fork_id
        self.turn_id = turn_id
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.notifications_sent: list[tuple[str, dict[str, Any]]] = []
        self.reads = 0
        self.executable_path = ""
        self.closed = False
        self._notifications = list(notifications or [])
        self._lock = threading.RLock()

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            clean_params = _copy(params)
            self.requests.append((method, clean_params))
            if method == "initialize":
                return {
                    "userAgent": "codex-test",
                    "platformFamily": "windows",
                    "platformOs": "windows",
                }
            if method == "thread/start":
                return {
                    "thread": {
                        "id": self.thread_id,
                        "modelProvider": "openai",
                    }
                }
            if method == "thread/resume":
                return {
                    "thread": {
                        "id": str(params["threadId"]),
                        "turns": [],
                    }
                }
            if method == "thread/fork":
                return {
                    "thread": {
                        "id": self.fork_id,
                        "forkedFromId": str(params["threadId"]),
                    }
                }
            if method == "thread/compact/start":
                return {"status": "accepted"}
            if method == "turn/start":
                return {
                    "turn": {
                        "id": self.turn_id,
                        "status": "inProgress",
                    }
                }
            if method == "turn/interrupt":
                return {"status": "interrupted"}
            if method == "thread/backgroundTerminals/clean":
                return {"cleaned": True}
            raise AssertionError(f"unexpected Codex method {method!r}")

    def optional_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.request(method, params)
        except Exception as exc:  # pragma: no cover - helper defensive branch
            return {"unavailable": True, "method": method, "error": str(exc)}

    def notify(self, method: str, params: dict[str, Any]) -> None:
        with self._lock:
            self.notifications_sent.append((method, _copy(params)))

    def read_notification(self, timeout_seconds: float = 0.25) -> dict[str, Any] | None:
        del timeout_seconds
        with self._lock:
            self.reads += 1
            if self._notifications:
                return _copy(self._notifications.pop(0))
            return None

    def close(self) -> None:
        with self._lock:
            self.closed = True


class FakeClientFactory:
    def __init__(self, *clients: FakeCodexClient) -> None:
        self._clients = list(clients)
        self.created: list[FakeCodexClient] = []

    def __call__(self, executable_path: str) -> FakeCodexClient:
        if not self._clients:
            raise AssertionError("no fake Codex clients remain")
        client = self._clients.pop(0)
        client.executable_path = executable_path
        self.created.append(client)
        return client


class CodexLifecycleTests(unittest.TestCase):
    def test_start_session_uses_capsule_cwd_and_safe_thread_params(self) -> None:
        async def scenario() -> tuple[dict[str, Any], FakeCodexClient, str]:
            with tempfile.TemporaryDirectory(prefix="xace-codex-start-") as tmp:
                root = Path(tmp)
                capsule = root / ".xace" / "agent_capsules" / "session-1.json"
                client = FakeCodexClient(thread_id="codex-thread-start")
                adapter = _adapter(FakeClientFactory(client))

                handle = await adapter.start_session(
                    AgentStartRequest(
                        xace_session_id="session-1",
                        user_prompt="Inspect the project.",
                        base_cgs_hash=CGS_HASH,
                        project_id="project-1",
                        context_capsule_path=str(capsule),
                        metadata={
                            "project_path": str(root),
                            "codex_model": "gpt-5.6-terra",
                        },
                    )
                )
                return handle.to_dict(), client, str(capsule.parent)

        handle, client, expected_cwd = asyncio.run(scenario())

        self.assertEqual(handle["provider_session_id"], "codex-thread-start")
        self.assertEqual(handle["provider_id"], CODEX_APP_SERVER_PROVIDER_ID)
        self.assertEqual(handle["metadata"]["operation"], "thread/start")
        self.assertEqual(handle["metadata"]["context_capsule_cwd"], expected_cwd)
        self.assertEqual(client.notifications_sent, [("initialized", {})])

        thread_params = _request_params(client, "thread/start")
        self.assertEqual(thread_params["cwd"], expected_cwd)
        self.assertEqual(thread_params["approvalPolicy"], "never")
        self.assertEqual(thread_params["sandbox"], "readOnly")
        self.assertEqual(thread_params["historyMode"], "paginated")
        self.assertEqual(thread_params["model"], "gpt-5.6-terra")
        self.assertNotIn("thread/shellCommand", _request_methods(client))
        self.assertNotIn("fs/writeFile", _request_methods(client))

    def test_run_turn_maps_codex_notifications_and_closes_client(self) -> None:
        async def scenario() -> tuple[list[str], FakeCodexClient]:
            client = FakeCodexClient(
                thread_id="codex-thread-stream",
                turn_id="codex-turn-stream",
                notifications=[
                    {"method": "thread/started", "params": {"thread": {"id": "codex-thread-stream"}}},
                    {"method": "turn/started", "params": {"turn": {"id": "codex-turn-stream"}}},
                    {"method": "item/completed", "params": {"item": {"id": "item-1", "type": "reasoning"}}},
                    {
                        "method": "item/completed",
                        "params": {
                            "item": {
                                "id": "tool-1",
                                "type": "mcpToolCall",
                                "name": "xace.search_project",
                            }
                        },
                    },
                    {
                        "method": "turn/completed",
                        "params": {"turn": {"id": "codex-turn-stream", "status": "completed"}},
                    },
                ],
            )
            adapter = _adapter(FakeClientFactory(client))
            handle = await adapter.start_session(
                AgentStartRequest(
                    xace_session_id="session-1",
                    user_prompt="Start.",
                    base_cgs_hash=CGS_HASH,
                    project_id="project-1",
                )
            )
            events = [
                event
                async for event in adapter.run_turn(
                    AgentTurnRequest(
                        handle=handle,
                        user_prompt="Use safe XACE tools only.",
                        base_cgs_hash=CGS_HASH,
                    )
                )
            ]
            return [event.event_type.value for event in events], client

        event_types, client = asyncio.run(scenario())

        self.assertEqual(
            event_types,
            ["session_started", "turn_started", "status", "tool_call", "turn_completed"],
        )
        turn_params = _request_params(client, "turn/start")
        self.assertEqual(turn_params["threadId"], "codex-thread-stream")
        self.assertEqual(turn_params["approvalPolicy"], "never")
        self.assertEqual(turn_params["sandboxPolicy"], {"type": "readOnly"})
        self.assertEqual(turn_params["input"], [{"type": "text", "text": "Use safe XACE tools only."}])
        self.assertTrue(client.closed)
        self.assertNotIn("thread/shellCommand", _request_methods(client))

    def test_cancel_turn_interrupts_active_codex_turn_and_closes_client(self) -> None:
        async def scenario() -> tuple[list[str], FakeCodexClient]:
            client = FakeCodexClient(
                thread_id="codex-thread-cancel",
                turn_id="codex-turn-cancel",
                notifications=[
                    {"method": "turn/started", "params": {"turn": {"id": "codex-turn-cancel"}}},
                ],
            )
            adapter = _adapter(FakeClientFactory(client), notification_idle_seconds=0.01)
            handle = await adapter.start_session(
                AgentStartRequest(
                    xace_session_id="session-1",
                    user_prompt="Start.",
                    base_cgs_hash=CGS_HASH,
                    project_id="project-1",
                )
            )
            event_types: list[str] = []
            started = asyncio.Event()

            async def consume() -> None:
                async for event in adapter.run_turn(
                    AgentTurnRequest(
                        handle=handle,
                        user_prompt="Do cancellable work.",
                        base_cgs_hash=CGS_HASH,
                    )
                ):
                    event_types.append(event.event_type.value)
                    if event.event_type is AgentEventType.TURN_STARTED:
                        started.set()

            task = asyncio.create_task(consume())
            await asyncio.wait_for(started.wait(), timeout=1.0)
            await adapter.cancel_turn(handle)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            return event_types, client

        event_types, client = asyncio.run(scenario())

        self.assertIn("turn_started", event_types)
        self.assertEqual(_request_params(client, "turn/interrupt")["turnId"], "codex-turn-cancel")
        self.assertIn("thread/backgroundTerminals/clean", _request_methods(client))
        self.assertTrue(client.closed)

    def test_fork_and_compact_retain_xace_state_references(self) -> None:
        async def scenario() -> tuple[dict[str, Any], dict[str, Any], FakeCodexClient]:
            client = FakeCodexClient(
                thread_id="codex-thread-parent",
                fork_id="codex-thread-branch",
            )
            adapter = _adapter(FakeClientFactory(client))
            handle = await adapter.start_session(
                AgentStartRequest(
                    xace_session_id="session-1",
                    user_prompt="Start.",
                    base_cgs_hash=CGS_HASH,
                    project_id="project-1",
                )
            )
            forked = await adapter.fork_session(
                handle,
                xace_session_id="session-1-branch",
                base_cgs_hash=CGS_HASH,
                latest_cgs_hash=NEW_CGS_HASH,
                last_turn_id="codex-turn-parent",
                branch_name="try-variant",
                ephemeral=True,
            )
            compaction = await adapter.compact_session(forked)
            return forked.to_dict(), compaction.to_dict(), client

        forked, compaction, client = asyncio.run(scenario())

        fork_params = _request_params(client, "thread/fork")
        self.assertEqual(fork_params["threadId"], "codex-thread-parent")
        self.assertEqual(fork_params["lastTurnId"], "codex-turn-parent")
        self.assertTrue(fork_params["excludeTurns"])
        self.assertTrue(fork_params["ephemeral"])
        self.assertEqual(forked["provider_session_id"], "codex-thread-branch")
        self.assertEqual(forked["metadata"]["parent_xace_session_id"], "session-1")
        self.assertEqual(forked["metadata"]["parent_provider_session_id"], "codex-thread-parent")
        self.assertEqual(forked["metadata"]["retained_xace_base_cgs_hash"], CGS_HASH)
        self.assertEqual(forked["metadata"]["retained_xace_latest_cgs_hash"], CGS_HASH)
        self.assertEqual(compaction["provider_session_id"], "codex-thread-branch")
        self.assertTrue(compaction["metadata"]["retains_xace_state_references"])

    def test_event_stream_resumes_codex_thread_after_host_restart(self) -> None:
        async def scenario(project_root: str) -> tuple[dict[str, Any], list[str], list[str], list[str]]:
            store = AgentSessionStore(project_root, audit_jsonl=True)
            first_client = FakeCodexClient(
                thread_id="codex-thread-persisted",
                turn_id="codex-turn-1",
                notifications=[
                    {"method": "turn/started", "params": {"turn": {"id": "codex-turn-1"}}},
                    {
                        "method": "turn/completed",
                        "params": {"turn": {"id": "codex-turn-1", "status": "completed"}},
                    },
                ],
            )
            first_manager = AgentEventStreamManager(
                AgentAdapterRegistry([_adapter(FakeClientFactory(first_client))]),
                session_store=store,
                clock=lambda: 10.0,
            )
            first_messages: list[dict[str, Any]] = []
            result = await first_manager.start_turn(
                session_id="session-1",
                provider_id=CODEX_APP_SERVER_PROVIDER_ID,
                user_prompt="First turn.",
                cgs_hash=CGS_HASH,
                project_id="project-1",
                context_capsule_path=str(Path(project_root) / ".xace" / "agent_capsules" / "session-1.json"),
                metadata={"project_path": project_root},
                send_fn=lambda message: _collecting_send(first_messages, message),
            )
            assert result.accepted
            await first_manager.wait_for_turn("session-1")

            stored = store.get_session("session-1")
            assert stored is not None

            second_client = FakeCodexClient(
                thread_id="unused-new-thread",
                turn_id="codex-turn-2",
                notifications=[
                    {"method": "turn/started", "params": {"turn": {"id": "codex-turn-2"}}},
                    {
                        "method": "turn/completed",
                        "params": {"turn": {"id": "codex-turn-2", "status": "completed"}},
                    },
                ],
            )
            second_manager = AgentEventStreamManager(
                AgentAdapterRegistry([_adapter(FakeClientFactory(second_client))]),
                session_store=store,
                clock=lambda: 20.0,
            )
            second_messages: list[dict[str, Any]] = []
            result = await second_manager.start_turn(
                session_id="session-1",
                provider_id=CODEX_APP_SERVER_PROVIDER_ID,
                user_prompt="Second turn after restart.",
                cgs_hash=CGS_HASH,
                send_fn=lambda message: _collecting_send(second_messages, message),
            )
            assert result.accepted
            await second_manager.wait_for_turn("session-1")

            events = store.list_events("session-1")
            return (
                stored.to_dict(),
                _request_methods(first_client),
                _request_methods(second_client),
                [event.event_type.value for event in events],
            )

        with tempfile.TemporaryDirectory(prefix="xace-codex-resume-") as tmp:
            stored, first_methods, second_methods, persisted_events = asyncio.run(scenario(tmp))

        self.assertEqual(stored["provider_id"], CODEX_APP_SERVER_PROVIDER_ID)
        self.assertEqual(stored["provider_session_id"], "codex-thread-persisted")
        self.assertIn("thread/start", first_methods)
        self.assertIn("thread/resume", second_methods)
        self.assertIn("turn/start", second_methods)
        self.assertNotIn("thread/start", second_methods)
        self.assertGreaterEqual(persisted_events.count("turn_started"), 2)
        self.assertGreaterEqual(persisted_events.count("turn_completed"), 2)


async def _collecting_send(messages: list[dict[str, Any]], message: dict[str, Any]) -> None:
    messages.append(message)


def _adapter(
    factory: FakeClientFactory,
    *,
    notification_idle_seconds: float = 0.05,
) -> CodexAppServerAdapter:
    return CodexAppServerAdapter(
        executable_resolver=lambda: CodexExecutableCandidate(
            path=FAKE_CODEX_PATH,
            source="test",
        ),
        client_factory=factory,
        version_reader=lambda _path: "codex 0.91.0",
        clock=lambda: FIXED_TIME,
        notification_idle_seconds=notification_idle_seconds,
    )


def _request_params(client: FakeCodexClient, method: str) -> dict[str, Any]:
    for item_method, params in reversed(client.requests):
        if item_method == method:
            return params
    raise AssertionError(f"method {method!r} was not requested; saw {_request_methods(client)!r}")


def _request_methods(client: FakeCodexClient) -> list[str]:
    return [method for method, _params in client.requests]


def _copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy(item) for item in value]
    return value


if __name__ == "__main__":
    unittest.main()
