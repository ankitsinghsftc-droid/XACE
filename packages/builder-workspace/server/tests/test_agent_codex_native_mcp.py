import asyncio
import json
import os
import subprocess
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
    CodexAppServerProtocolError,
    CodexExecutableCandidate,
)
from agent_host.context_capsule import ContextRetrievalSource  # noqa: E402
from agent_host.contracts import AgentStartRequest, AgentTurnRequest  # noqa: E402
from agent_host.mcp_server import XaceMcpToolBridge, XaceMcpToolContext  # noqa: E402
from agent_host.mcp_transport import (  # noqa: E402
    XACE_MCP_SESSION_TOKEN_ENV,
    XaceMcpNativeTransport,
)
from agent_host.tool_surface import XaceToolSurface  # noqa: E402


CGS_HASH = "e" * 64


def _bridge() -> XaceMcpToolBridge:
    source = ContextRetrievalSource(
        cgs={
            "metadata": {"name": "Native MCP", "cgs_hash": CGS_HASH},
            "modes": [],
        },
        cgs_hash=CGS_HASH,
        diagnostics=(
            {"code": "NATIVE_MCP_READY", "severity": "info"},
        ),
    )
    return XaceMcpToolBridge(
        XaceToolSurface(source),
        XaceMcpToolContext(
            xace_session_id="session-native-mcp-1",
            provider_id=CODEX_APP_SERVER_PROVIDER_ID,
            cgs_hash=CGS_HASH,
        ),
    )


class _NativeMcpClient:
    def __init__(self, bridge: XaceMcpToolBridge, *, runtime_status: str = "connected") -> None:
        self.bridge = bridge
        self.runtime_status = runtime_status
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.closed = False
        self._notifications = [
            {
                "method": "turn/started",
                "params": {"turn": {"id": "turn-native-mcp"}},
            },
            {
                "method": "item/started",
                "params": {
                    "threadId": "thread-native-mcp",
                    "turnId": "turn-native-mcp",
                    "item": {
                        "type": "mcpToolCall",
                        "id": "mcp-call-1",
                        "server": "xace",
                        "tool": "xace.get_diagnostics",
                        "arguments": {},
                        "status": "inProgress",
                    },
                },
            },
            {
                "method": "turn/completed",
                "params": {
                    "turn": {"id": "turn-native-mcp", "status": "completed"}
                },
            },
        ]

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.requests.append((method, dict(params)))
        if method == "initialize":
            return {
                "userAgent": "native-mcp-test",
                "platformFamily": "windows",
                "platformOs": "windows",
            }
        if method == "thread/start":
            return {"thread": {"id": "thread-native-mcp"}}
        if method == "mcpServerStatus/list":
            return {
                "data": [
                    {
                        "name": "xace",
                        "authStatus": "unsupported",
                        "runtimeStatus": self.runtime_status,
                        "tools": {
                            name: {"name": name, "inputSchema": {}}
                            for name in self.bridge.tool_names
                        },
                        "resources": [],
                        "resourceTemplates": [],
                    }
                ]
            }
        if method == "turn/start":
            return {
                "turn": {"id": "turn-native-mcp", "status": "inProgress"}
            }
        raise AssertionError(method)

    def optional_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        return self.request(method, params)

    def notify(self, _method: str, _params: dict[str, Any]) -> None:
        pass

    def respond(self, _request_id: int | str, _result: dict[str, Any]) -> None:
        raise AssertionError("native MCP calls must be handled by the MCP server")

    def read_notification(self, _timeout_seconds: float = 0.25) -> dict[str, Any] | None:
        return self._notifications.pop(0) if self._notifications else None

    def close(self) -> None:
        self.closed = True


class CodexNativeMcpTests(unittest.TestCase):
    def test_stdio_proxy_serves_the_live_xace_tool_surface(self) -> None:
        bridge = _bridge()
        transport = XaceMcpNativeTransport.start(bridge)
        proc: subprocess.Popen[str] | None = None
        try:
            launch = transport.launch_config
            server = launch.thread_config["mcp_servers"]["xace"]
            serialized_config = json.dumps(launch.thread_config, sort_keys=True)
            self.assertNotIn(launch.app_server_environment[XACE_MCP_SESSION_TOKEN_ENV], serialized_config)
            self.assertEqual(server["env_vars"], [XACE_MCP_SESSION_TOKEN_ENV])
            self.assertTrue(server["required"])
            self.assertEqual(set(server["enabled_tools"]), set(bridge.tool_names))

            environment = {**os.environ, **launch.app_server_environment}
            proc = subprocess.Popen(
                [server["command"], *server["args"]],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                env=environment,
            )
            assert proc.stdin is not None
            assert proc.stdout is not None

            def exchange(message: dict[str, Any]) -> dict[str, Any]:
                proc.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
                proc.stdin.flush()
                response = proc.stdout.readline()
                self.assertTrue(response)
                return json.loads(response)

            initialized = exchange(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                }
            )
            listed = exchange(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                    "params": {},
                }
            )
            called = exchange(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "xace.get_diagnostics",
                        "arguments": {},
                    },
                }
            )

            self.assertEqual(initialized["jsonrpc"], "2.0")
            self.assertEqual(initialized["result"]["serverInfo"]["name"], "xace")
            self.assertEqual(
                {item["name"] for item in listed["result"]["tools"]},
                set(bridge.tool_names),
            )
            self.assertFalse(called["result"]["isError"])
            payload = called["result"]["structuredContent"]
            self.assertEqual(payload["tool_name"], "xace.get_diagnostics")
            self.assertEqual(payload["status"], "completed")
        finally:
            if proc is not None:
                if proc.stdin is not None:
                    proc.stdin.close()
                try:
                    proc.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3.0)
                if proc.stdout is not None:
                    proc.stdout.close()
                if proc.stderr is not None:
                    proc.stderr.close()
            transport.close()

    def test_codex_session_uses_stable_required_native_mcp(self) -> None:
        async def scenario() -> tuple[_NativeMcpClient, dict[str, Any], list[str]]:
            bridge = _bridge()
            client = _NativeMcpClient(bridge)
            adapter = CodexAppServerAdapter(
                executable_resolver=lambda: CodexExecutableCandidate(
                    "C:/tools/codex.exe", "test"
                ),
                client_factory=lambda _path: client,
                version_reader=lambda _path: "codex 0.91.0",
                tool_bridge_factory=lambda _request: bridge,
                notification_idle_seconds=0.01,
            )
            handle = await adapter.start_session(
                AgentStartRequest(
                    xace_session_id="session-native-mcp-1",
                    user_prompt="Inspect diagnostics.",
                    base_cgs_hash=CGS_HASH,
                )
            )
            events = [
                event.event_type.value
                async for event in adapter.run_turn(
                    AgentTurnRequest(
                        handle=handle,
                        user_prompt="Read diagnostics.",
                        base_cgs_hash=CGS_HASH,
                    )
                )
            ]
            return client, dict(handle.metadata), events

        client, metadata, events = asyncio.run(scenario())
        initialize_params = next(
            params for method, params in client.requests if method == "initialize"
        )
        thread_params = next(
            params for method, params in client.requests if method == "thread/start"
        )
        status_params = next(
            params
            for method, params in client.requests
            if method == "mcpServerStatus/list"
        )
        config = thread_params["config"]
        server = config["mcp_servers"]["xace"]

        self.assertNotIn("capabilities", initialize_params)
        self.assertNotIn("dynamicTools", thread_params)
        self.assertTrue(server["required"])
        self.assertTrue(server["enabled"])
        self.assertEqual(set(server["enabled_tools"]), set(_bridge().tool_names))
        self.assertFalse(config["features"]["shell_tool"])
        self.assertFalse(config["features"]["unified_exec"])
        self.assertFalse(config["tools"]["web_search"])
        self.assertFalse(config["tools"]["view_image"])
        self.assertEqual(config["web_search"], "disabled")
        self.assertEqual(status_params["threadId"], "thread-native-mcp")
        self.assertEqual(metadata["app_server_api_profile"], "stable")
        self.assertEqual(metadata["tool_transport"], "mcp")
        self.assertTrue(metadata["native_mcp"]["status_verified"])
        self.assertNotIn(XACE_MCP_SESSION_TOKEN_ENV, json.dumps(metadata))
        self.assertEqual(events, ["turn_started", "tool_call", "turn_completed"])
        self.assertTrue(client.closed)

    def test_required_native_mcp_status_fails_closed(self) -> None:
        async def scenario() -> _NativeMcpClient:
            bridge = _bridge()
            client = _NativeMcpClient(bridge, runtime_status="failed")
            adapter = CodexAppServerAdapter(
                executable_resolver=lambda: CodexExecutableCandidate(
                    "C:/tools/codex.exe", "test"
                ),
                client_factory=lambda _path: client,
                tool_bridge_factory=lambda _request: bridge,
            )
            with self.assertRaisesRegex(
                CodexAppServerProtocolError,
                "not connected",
            ):
                await adapter.start_session(
                    AgentStartRequest(
                        xace_session_id="session-native-mcp-1",
                        user_prompt="Inspect diagnostics.",
                        base_cgs_hash=CGS_HASH,
                    )
                )
            return client

        client = asyncio.run(scenario())
        self.assertTrue(client.closed)


if __name__ == "__main__":
    unittest.main()
