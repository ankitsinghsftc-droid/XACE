import asyncio
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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
from agent_host.contracts import AgentSessionHandle, AgentStartRequest, AgentTurnRequest  # noqa: E402
from agent_host.mcp_server import XaceMcpToolBridge, XaceMcpToolContext  # noqa: E402
from agent_host.proposal_ingress import AgentProposalIngressGate  # noqa: E402
from agent_host.session_store import AgentSessionStore, AgentStoredSession  # noqa: E402
from agent_host.tool_surface import (  # noqa: E402
    READ_ONLY_XACE_TOOL_NAMES,
    TOOL_SUBMIT_PROPOSAL,
    XaceToolSurface,
)


CGS_HASH = "a" * 64
STALE_CGS_HASH = "b" * 64


def _cgs() -> dict[str, Any]:
    return {
        "metadata": {"name": "Codex Proposal Fixture", "cgs_hash": CGS_HASH},
        "component_schemas": [
            {
                "type_id": 1,
                "name": "COMP_TRANSFORM_V1",
                "defaults": {"x": 0, "y": 0},
                "source": "ucl",
            }
        ],
        "global_systems": [],
        "semantic_events": [],
        "assets": [],
        "modes": [
            {
                "id": "mode_gameplay",
                "is_default": True,
                "actors": [
                    {
                        "id": "actor_player",
                        "actor_type": "PlayerCharacter",
                        "control_type": "Human",
                        "components": [
                            {
                                "type_id": 1,
                                "name": "COMP_TRANSFORM_V1",
                                "defaults": {"x": 0, "y": 0},
                            }
                        ],
                    }
                ],
                "systems": [],
                "rules": [],
            }
        ],
    }


def _proposal(*, base_cgs_hash: str = CGS_HASH) -> dict[str, Any]:
    return {
        "proposal_id": "proposal-codex-energy",
        "session_id": "session-codex-proposal-1",
        "provider_id": CODEX_APP_SERVER_PROVIDER_ID,
        "base_cgs_hash": base_cgs_hash,
        "intent": "Add a deterministic energy resource.",
        "summary": "Declare and attach deterministic typed energy state.",
        "proposal_kind": "mutation",
        "risk_level": "medium",
        "operations": [
            {
                "operation_id": "declare.energy",
                "kind": "declare_component",
                "explanation": "Declare deterministic fixed-point energy state.",
                "component_type_id": 10000,
                "component_name": "COMP_ENERGY_V1",
                "version": "1.0.0",
                "fields": [
                    {"name": "current", "field_type": "fixed", "default": 1000000},
                    {"name": "maximum", "field_type": "fixed", "default": 1000000},
                ],
            },
            {
                "operation_id": "attach.energy",
                "kind": "add_component",
                "explanation": "Attach energy state to the player.",
                "mode_id": "mode_gameplay",
                "actor_id": "actor_player",
                "component_type_id": 10000,
                "component_name": "COMP_ENERGY_V1",
                "defaults": [
                    {"field_name": "current", "field_type": "fixed", "value": 750000}
                ],
                "use_schema_defaults": True,
            },
        ],
    }


def _session() -> SimpleNamespace:
    return SimpleNamespace(
        pending_txn=None,
        pending_prompt_preview=None,
        pending_prompt_result=None,
    )


def _handle() -> AgentSessionHandle:
    return AgentSessionHandle(
        xace_session_id="session-codex-proposal-1",
        provider_id=CODEX_APP_SERVER_PROVIDER_ID,
        provider_session_id="thread-codex-proposal-1",
        base_cgs_hash=CGS_HASH,
        latest_cgs_hash=CGS_HASH,
    )


def _bridge(
    *,
    store: AgentSessionStore,
    session: SimpleNamespace,
    allowed_tools: tuple[str, ...] = READ_ONLY_XACE_TOOL_NAMES + (TOOL_SUBMIT_PROPOSAL,),
) -> XaceMcpToolBridge:
    source = ContextRetrievalSource(cgs=_cgs(), cgs_hash=CGS_HASH)
    return XaceMcpToolBridge(
        XaceToolSurface(
            source,
            session_store=store,
            proposal_ingress=AgentProposalIngressGate(
                session_store=store,
                clock=lambda: 1.0,
                token_factory=lambda: "apt-codex-proposal",
            ),
            proposal_session=session,
        ),
        XaceMcpToolContext(
            xace_session_id="session-codex-proposal-1",
            provider_id=CODEX_APP_SERVER_PROVIDER_ID,
            cgs_hash=CGS_HASH,
            allowed_tools=allowed_tools,
        ),
    )


class _ProposalToolClient:
    def __init__(self, proposal: dict[str, Any]) -> None:
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.responses: list[tuple[int | str, dict[str, Any]]] = []
        self.closed = False
        self._notifications = [
            {"method": "turn/started", "params": {"turn": {"id": "turn-proposal"}}},
            {
                "method": "item/tool/call",
                "id": 73,
                "params": {
                    "threadId": "thread-proposal",
                    "turnId": "turn-proposal",
                    "callId": "call-proposal-1",
                    "namespace": "xace",
                    "tool": "submit_proposal",
                    "arguments": {"proposal": proposal},
                },
            },
            {
                "method": "turn/completed",
                "params": {"turn": {"id": "turn-proposal", "status": "completed"}},
            },
        ]

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.requests.append((method, dict(params)))
        if method == "initialize":
            return {"userAgent": "test", "platformFamily": "windows", "platformOs": "windows"}
        if method == "thread/start":
            return {"thread": {"id": "thread-proposal"}}
        if method == "turn/start":
            return {"turn": {"id": "turn-proposal", "status": "inProgress"}}
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


class CodexProposalSubmissionTests(unittest.TestCase):
    def test_submission_is_session_enabled_and_creates_only_pending_preview(self) -> None:
        with tempfile.TemporaryDirectory(prefix="xace-codex-proposal-") as temp_dir:
            store = AgentSessionStore(temp_dir)
            store.upsert_session(AgentStoredSession.from_handle(_handle()))
            session = _session()
            bridge = _bridge(store=store, session=session)
            before = json.dumps(_cgs(), sort_keys=True)

            listed = bridge.handle_mcp_message({"id": 1, "method": "tools/list", "params": {}})
            result = bridge.handle_mcp_message(
                {
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": TOOL_SUBMIT_PROPOSAL, "arguments": {"proposal": _proposal()}},
                }
            )

            tool = next(item for item in listed["result"]["tools"] if item["name"] == TOOL_SUBMIT_PROPOSAL)
            payload = json.loads(result["result"]["content"][0]["text"])
            self.assertFalse(tool["annotations"]["readOnlyHint"])
            self.assertTrue(tool["_meta"]["proposal_preview_only"])
            self.assertFalse(result["result"]["isError"])
            self.assertEqual(payload["data"]["proposal_ingress"]["status"], "preview_created")
            self.assertTrue(payload["data"]["proposal_ingress"]["accepted"])
            self.assertTrue(payload["data"]["preview_only"])
            self.assertFalse(payload["data"]["project_mutated"])
            self.assertIsNotNone(session.pending_prompt_preview)
            self.assertTrue(session.pending_prompt_result["approval_required"])
            self.assertEqual(before, json.dumps(_cgs(), sort_keys=True))
            self.assertEqual(store.get_proposal("proposal-codex-energy")["status"], "pending_preview")
            recorded = store.list_tool_calls("session-codex-proposal-1")
            self.assertEqual(recorded[0].tool_name, TOOL_SUBMIT_PROPOSAL)
            self.assertEqual(recorded[0].permission, "proposal_write")
            self.assertEqual(recorded[0].status, "completed")

    def test_submission_is_hidden_until_explicitly_allowed_and_rejects_stale_cgs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="xace-codex-proposal-denied-") as temp_dir:
            store = AgentSessionStore(temp_dir)
            store.upsert_session(AgentStoredSession.from_handle(_handle()))
            session = _session()
            read_only_bridge = _bridge(
                store=store,
                session=session,
                allowed_tools=READ_ONLY_XACE_TOOL_NAMES,
            )
            listed = read_only_bridge.handle_mcp_message({"id": 1, "method": "tools/list", "params": {}})
            self.assertNotIn(TOOL_SUBMIT_PROPOSAL, {item["name"] for item in listed["result"]["tools"]})

            bridge = _bridge(store=store, session=session)
            stale = bridge.handle_mcp_message(
                {
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": TOOL_SUBMIT_PROPOSAL,
                        "arguments": {"proposal": _proposal(base_cgs_hash=STALE_CGS_HASH)},
                    },
                }
            )
            payload = json.loads(stale["result"]["content"][0]["text"])
            self.assertTrue(stale["result"]["isError"])
            self.assertEqual(payload["data"]["proposal_ingress"]["code"], "STALE_CGS_HASH")
            self.assertIsNone(session.pending_prompt_preview)
            self.assertEqual(store.get_proposal("proposal-codex-energy")["status"], "rejected_stale_cgs_hash")

            spoof = _proposal()
            spoof["proposal_id"] = "proposal-spoofed-provider"
            spoof["provider_id"] = "other_provider"
            spoofed = bridge.handle_mcp_message(
                {
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": TOOL_SUBMIT_PROPOSAL,
                        "arguments": {"proposal": spoof},
                    },
                }
            )
            spoofed_payload = json.loads(spoofed["result"]["content"][0]["text"])
            self.assertTrue(spoofed["result"]["isError"])
            self.assertEqual(spoofed_payload["data"]["proposal_ingress"]["code"], "PROVIDER_MISMATCH")
            self.assertIsNone(session.pending_prompt_preview)
    def test_mocked_app_server_dynamic_call_returns_a_preview_only_result(self) -> None:
        async def scenario() -> tuple[_ProposalToolClient, SimpleNamespace, AgentSessionStore]:
            temp_dir = tempfile.TemporaryDirectory(prefix="xace-codex-dynamic-proposal-")
            self.addCleanup(temp_dir.cleanup)
            store = AgentSessionStore(temp_dir.name)
            session = _session()
            client = _ProposalToolClient(_proposal())

            def factory(request: AgentStartRequest) -> XaceMcpToolBridge:
                return _bridge(
                    store=store,
                    session=session,
                    allowed_tools=tuple(request.allowed_tools),
                )

            def unavailable_native_transport(_bridge: XaceMcpToolBridge) -> None:
                raise RuntimeError("native MCP deliberately unavailable in fallback test")

            adapter = CodexAppServerAdapter(
                executable_resolver=lambda: CodexExecutableCandidate("C:/tools/codex.exe", "test"),
                client_factory=lambda _path: client,
                version_reader=lambda _path: "codex 0.91.0",
                tool_bridge_factory=factory,
                notification_idle_seconds=0.01,
                native_mcp_transport_factory=unavailable_native_transport,
                allow_experimental_dynamic_tools_fallback=True,
            )
            handle = await adapter.start_session(
                AgentStartRequest(
                    xace_session_id="session-codex-proposal-1",
                    user_prompt="Create an energy proposal.",
                    base_cgs_hash=CGS_HASH,
                    allowed_tools=READ_ONLY_XACE_TOOL_NAMES + (TOOL_SUBMIT_PROPOSAL,),
                )
            )
            store.upsert_session(AgentStoredSession.from_handle(handle))
            _ = [
                event
                async for event in adapter.run_turn(
                    AgentTurnRequest(
                        handle=handle,
                        user_prompt="Submit the typed proposal.",
                        base_cgs_hash=CGS_HASH,
                    )
                )
            ]
            return client, session, store

        client, session, store = asyncio.run(scenario())

        thread_params = next(params for method, params in client.requests if method == "thread/start")
        dynamic_tools = thread_params["dynamicTools"][0]["tools"]
        self.assertIn("submit_proposal", {tool["name"] for tool in dynamic_tools})
        self.assertEqual(client.responses[0][0], 73)
        self.assertTrue(client.responses[0][1]["success"])
        self.assertIsNotNone(session.pending_prompt_preview)
        self.assertTrue(session.pending_prompt_result["approval_required"])
        self.assertEqual(store.list_tool_calls("session-codex-proposal-1")[0].permission, "proposal_write")
        self.assertTrue(client.closed)


if __name__ == "__main__":
    unittest.main()
