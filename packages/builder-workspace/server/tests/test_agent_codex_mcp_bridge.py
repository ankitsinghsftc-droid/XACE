import asyncio
import sys
import unittest
from pathlib import Path
from typing import Any


SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from agent_host.codex_adapter import (  # noqa: E402
    CODEX_APP_SERVER_PROVIDER_ID,
    CodexAppServerAdapter,
    CodexExecutableCandidate,
)
from agent_host.context_capsule import ContextRetrievalSource  # noqa: E402
from agent_host.mcp_server import XaceMcpToolBridge, XaceMcpToolContext  # noqa: E402
from agent_host.contracts import AgentStartRequest, AgentTurnRequest  # noqa: E402
from agent_host.tool_surface import XaceToolSurface  # noqa: E402


CGS_HASH = "d" * 64


class _DynamicToolClient:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.responses: list[tuple[int | str, dict[str, Any]]] = []
        self.closed = False
        self._notifications = [
            {"method": "turn/started", "params": {"turn": {"id": "turn-mcp"}}},
            {
                "method": "item/tool/call",
                "id": 41,
                "params": {
                    "threadId": "thread-mcp",
                    "turnId": "turn-mcp",
                    "callId": "call-mcp-1",
                    "namespace": "xace",
                    "tool": "get_diagnostics",
                    "arguments": {},
                },
            },
            {"method": "turn/completed", "params": {"turn": {"id": "turn-mcp", "status": "completed"}}},
        ]

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.requests.append((method, dict(params)))
        if method == "initialize":
            return {"userAgent": "test", "platformFamily": "windows", "platformOs": "windows"}
        if method == "thread/start":
            return {"thread": {"id": "thread-mcp"}}
        if method == "turn/start":
            return {"turn": {"id": "turn-mcp", "status": "inProgress"}}
        raise AssertionError(method)

    def optional_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        return self.request(method, params)

    def notify(self, _method: str, _params: dict[str, Any]) -> None:
        pass

    def respond(self, request_id: int | str, result: dict[str, Any]) -> None:
        self.responses.append((request_id, dict(result)))

    def read_notification(self, _timeout_seconds: float = 0.25) -> dict[str, Any] | None:
        return self._notifications.pop(0) if self._notifications else None

    def close(self) -> None:
        self.closed = True


class CodexMcpBridgeTests(unittest.TestCase):
    def test_codex_thread_registers_and_serves_safe_dynamic_fallback_tools(self) -> None:
        async def scenario() -> tuple[_DynamicToolClient, list[str]]:
            client = _DynamicToolClient()

            def factory(request: AgentStartRequest) -> XaceMcpToolBridge:
                source = ContextRetrievalSource(
                    cgs={"metadata": {"name": "Codex Bridge", "cgs_hash": CGS_HASH}, "modes": []},
                    cgs_hash=CGS_HASH,
                    diagnostics=({"code": "BRIDGE_DIAGNOSTIC", "severity": "warning"},),
                )
                return XaceMcpToolBridge(
                    XaceToolSurface(source),
                    XaceMcpToolContext(
                        xace_session_id=request.xace_session_id,
                        provider_id=CODEX_APP_SERVER_PROVIDER_ID,
                        cgs_hash=request.base_cgs_hash,
                    ),
                )

            adapter = CodexAppServerAdapter(
                executable_resolver=lambda: CodexExecutableCandidate("C:/tools/codex.exe", "test"),
                client_factory=lambda _path: client,
                version_reader=lambda _path: "codex 0.91.0",
                tool_bridge_factory=factory,
                notification_idle_seconds=0.01,
            )
            handle = await adapter.start_session(
                AgentStartRequest(
                    xace_session_id="session-mcp-1",
                    user_prompt="Inspect diagnostics.",
                    base_cgs_hash=CGS_HASH,
                )
            )
            events = [
                event.event_type.value
                async for event in adapter.run_turn(
                    AgentTurnRequest(handle=handle, user_prompt="Read diagnostics.", base_cgs_hash=CGS_HASH)
                )
            ]
            return client, events

        client, events = asyncio.run(scenario())

        thread_params = next(params for method, params in client.requests if method == "thread/start")
        self.assertEqual(thread_params["dynamicTools"][0]["name"], "xace")
        self.assertEqual({tool["name"] for tool in thread_params["dynamicTools"][0]["tools"]}, {
            "read_cgs", "retrieve_context", "search_project", "get_diagnostics", "runtime_status", "runtime_snapshot"
        })
        self.assertEqual(events, ["turn_started", "tool_call", "turn_completed"])
        self.assertEqual(client.responses[0][0], 41)
        self.assertTrue(client.responses[0][1]["success"])
        self.assertTrue(client.closed)


if __name__ == "__main__":
    unittest.main()
