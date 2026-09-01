import json
import sys
import tempfile
import unittest
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from agent_host.context_capsule import ContextRetrievalSource  # noqa: E402
from agent_host.contracts import AgentSessionHandle, AgentToolPermission  # noqa: E402
from agent_host.mcp_server import (  # noqa: E402
    AGENT_MCP_BRIDGE_SCHEMA,
    XACE_MCP_SERVER_NAME,
    XaceMcpToolBridge,
    XaceMcpToolContext,
)
from agent_host.session_store import AgentSessionStore, AgentStoredSession  # noqa: E402
from agent_host.tool_surface import (  # noqa: E402
    TOOL_GET_DIAGNOSTICS,
    TOOL_READ_CGS,
    XaceToolSurface,
)


CGS_HASH = "c" * 64
FIXED_TIME = "2026-09-02T00:00:00Z"


def _source() -> ContextRetrievalSource:
    return ContextRetrievalSource(
        cgs={
            "metadata": {"name": "MCP Fixture", "cgs_hash": CGS_HASH},
            "modes": [],
        },
        cgs_hash=CGS_HASH,
        diagnostics=({"severity": "warning", "code": "FIXTURE_WARNING"},),
    )


def _handle() -> AgentSessionHandle:
    return AgentSessionHandle(
        xace_session_id="session-mcp-1",
        provider_id="codex_app_server",
        provider_session_id="codex-thread-mcp-1",
        base_cgs_hash=CGS_HASH,
        latest_cgs_hash=CGS_HASH,
        created_at=FIXED_TIME,
    )


class XaceMcpToolBridgeTests(unittest.TestCase):
    def test_mcp_lists_and_executes_only_read_only_xace_tools(self) -> None:
        with tempfile.TemporaryDirectory(prefix="xace-mcp-bridge-") as temp_dir:
            store = AgentSessionStore(temp_dir)
            store.upsert_session(AgentStoredSession.from_handle(_handle()))
            bridge = XaceMcpToolBridge(
                XaceToolSurface(_source(), session_store=store),
                XaceMcpToolContext(
                    xace_session_id="session-mcp-1",
                    provider_id="codex_app_server",
                    cgs_hash=CGS_HASH,
                ),
            )

            initialized = bridge.handle_mcp_message({"id": 1, "method": "initialize", "params": {}})
            listed = bridge.handle_mcp_message({"id": 2, "method": "tools/list", "params": {}})
            result = bridge.handle_mcp_message(
                {"id": 3, "method": "tools/call", "params": {"name": TOOL_READ_CGS, "arguments": {}}}
            )

            self.assertEqual(initialized["result"]["serverInfo"]["name"], XACE_MCP_SERVER_NAME)
            self.assertEqual(
                {tool["name"] for tool in listed["result"]["tools"]},
                set(bridge.tool_names),
            )
            self.assertTrue(all(tool["annotations"]["readOnlyHint"] for tool in listed["result"]["tools"]))
            self.assertFalse(result["result"]["isError"])
            payload = json.loads(result["result"]["content"][0]["text"])
            self.assertTrue(payload["logged"])
            self.assertEqual(payload["data"]["value"]["metadata"]["name"], "MCP Fixture")

            calls = store.list_tool_calls("session-mcp-1")
            self.assertEqual([call.tool_name for call in calls], [TOOL_READ_CGS])
            self.assertEqual(calls[0].permission, AgentToolPermission.READ_ONLY.value)
            self.assertEqual(calls[0].transport, "mcp")

    def test_bridge_denies_shell_and_file_write_through_the_shared_audit_boundary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="xace-mcp-deny-") as temp_dir:
            store = AgentSessionStore(temp_dir)
            store.upsert_session(AgentStoredSession.from_handle(_handle()))
            bridge = XaceMcpToolBridge(
                XaceToolSurface(_source(), session_store=store),
                XaceMcpToolContext(
                    xace_session_id="session-mcp-1",
                    provider_id="codex_app_server",
                    cgs_hash=CGS_HASH,
                ),
            )

            shell = bridge.handle_mcp_message(
                {"id": 4, "method": "tools/call", "params": {"name": "xace.shell", "arguments": {"command": "dir"}}}
            )
            file_write = bridge.handle_mcp_message(
                {"id": 5, "method": "tools/call", "params": {"name": "xace.edit_project_file", "arguments": {"path": "game.gd"}}}
            )

            self.assertTrue(shell["result"]["isError"])
            self.assertTrue(file_write["result"]["isError"])
            self.assertEqual([call.status for call in store.list_tool_calls("session-mcp-1")], ["denied", "denied"])
            self.assertEqual(bridge.metadata()["schema"], AGENT_MCP_BRIDGE_SCHEMA)

    def test_codex_dynamic_fallback_uses_the_same_contract_and_audit_log(self) -> None:
        with tempfile.TemporaryDirectory(prefix="xace-mcp-dynamic-") as temp_dir:
            store = AgentSessionStore(temp_dir)
            store.upsert_session(AgentStoredSession.from_handle(_handle()))
            bridge = XaceMcpToolBridge(
                XaceToolSurface(_source(), session_store=store),
                XaceMcpToolContext(
                    xace_session_id="session-mcp-1",
                    provider_id="codex_app_server",
                    cgs_hash=CGS_HASH,
                ),
            )

            dynamic_tools = bridge.codex_dynamic_tools()
            response = bridge.handle_codex_dynamic_call(
                {"namespace": "xace", "tool": "get_diagnostics", "arguments": {}, "callId": "call-1"}
            )

            self.assertEqual(dynamic_tools[0]["name"], "xace")
            self.assertIn("get_diagnostics", {tool["name"] for tool in dynamic_tools[0]["tools"]})
            self.assertTrue(response["success"])
            self.assertEqual(store.list_tool_calls("session-mcp-1")[0].tool_name, TOOL_GET_DIAGNOSTICS)
            self.assertEqual(store.list_tool_calls("session-mcp-1")[0].transport, "provider_direct")


if __name__ == "__main__":
    unittest.main()
