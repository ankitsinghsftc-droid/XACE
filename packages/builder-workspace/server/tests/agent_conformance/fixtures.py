"""Deterministic Mock and Codex fixtures for the reusable conformance suite."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from agent_host.codex_adapter import (
    CODEX_APP_SERVER_PROVIDER_ID,
    CodexAppServerAdapter,
    CodexAppServerProbeResult,
    CodexExecutableCandidate,
)
from agent_host.context_capsule import ContextRetrievalSource
from agent_host.contracts import AgentStartRequest
from agent_host.mcp_server import XaceMcpToolBridge, XaceMcpToolContext
from agent_host.mock_agent import MockAgentAdapter
from agent_host.proposal_ingress import AgentProposalIngressGate
from agent_host.tool_surface import (
    READ_ONLY_XACE_TOOL_NAMES,
    TOOL_SUBMIT_PROPOSAL,
    XaceToolSurface,
)

from .suite import AdapterScenario


CGS_HASH = "c" * 64
FIXED_TIME = "2026-09-17T00:00:00Z"
FAKE_CODEX_PATH = "C:/tools/codex-conformance.exe"


def conformance_cgs() -> dict[str, Any]:
    return {
        "metadata": {
            "name": "Agent Adapter Conformance",
            "version": "0.1.0",
            "schema_version": "0.1.0",
            "cgs_hash": CGS_HASH,
        },
        "component_schemas": [],
        "global_systems": [],
        "semantic_events": [],
        "assets": [],
        "modes": [],
    }


class MockConformanceFixture:
    provider_id = "mock"
    display_name = "Mock Agent"
    production = False

    def create_scenario(self, name: str, root: Path) -> AdapterScenario:
        root.mkdir(parents=True, exist_ok=True)
        adapter = MockAgentAdapter(clock=lambda: FIXED_TIME)
        session_id = f"conformance-mock-{name}"
        proposal_session = _proposal_session()

        def observe() -> Mapping[str, Any]:
            return {
                "cancel_observed": bool(adapter._cancelled_sessions),
                "project_mutated": False,
                "provider_session_count": len(adapter._sessions),
                "request_methods": [],
            }

        return AdapterScenario(
            adapter=adapter,
            start_request=AgentStartRequest(
                xace_session_id=session_id,
                user_prompt="Start deterministic Mock conformance.",
                base_cgs_hash=CGS_HASH,
                project_id="agent-conformance",
                allowed_tools=READ_ONLY_XACE_TOOL_NAMES,
            ),
            current_cgs=conformance_cgs(),
            proposal_session=proposal_session,
            observe=observe,
        )


class CodexConformanceFixture:
    provider_id = CODEX_APP_SERVER_PROVIDER_ID
    display_name = "Codex App Server"
    production = True

    def create_scenario(self, name: str, root: Path) -> AdapterScenario:
        root.mkdir(parents=True, exist_ok=True)
        session_id = f"conformance-codex-{name}"
        capsule = root / ".xace" / "agent_capsules" / session_id
        capsule.mkdir(parents=True, exist_ok=True)
        current_cgs = conformance_cgs()
        proposal_session = _proposal_session()
        allowed_tools = READ_ONLY_XACE_TOOL_NAMES
        bridge: XaceMcpToolBridge | None = None

        if name == "proposal":
            allowed_tools = READ_ONLY_XACE_TOOL_NAMES + (TOOL_SUBMIT_PROPOSAL,)
            bridge = _proposal_bridge(
                root=root,
                session_id=session_id,
                current_cgs=current_cgs,
                proposal_session=proposal_session,
                allowed_tools=allowed_tools,
            )

        clients = _scenario_clients(
            name=name,
            session_id=session_id,
            proposal=_proposal(session_id=session_id),
        )
        factory = _CodexClientFactory(*clients)
        adapter = CodexAppServerAdapter(
            executable_resolver=lambda: CodexExecutableCandidate(
                path=FAKE_CODEX_PATH,
                source="conformance_fixture",
            ),
            app_server_probe=_StaticCodexProbe(),
            client_factory=factory,
            version_reader=lambda _path: "codex 0.91.0",
            clock=lambda: FIXED_TIME,
            notification_idle_seconds=0.01,
            tool_bridge_factory=(
                (lambda _request: bridge) if bridge is not None else None
            ),
            native_mcp_transport_factory=_unavailable_native_transport,
            allow_experimental_dynamic_tools_fallback=True,
        )

        def observe() -> Mapping[str, Any]:
            methods = [method for client in factory.created for method, _ in client.requests]
            return {
                "cancel_observed": "turn/interrupt" in methods,
                "clients_closed": bool(factory.created)
                and all(client.closed for client in factory.created),
                "project_mutated": False,
                "request_methods": methods,
                "tool_responses": sum(len(client.responses) for client in factory.created),
            }

        return AdapterScenario(
            adapter=adapter,
            start_request=AgentStartRequest(
                xace_session_id=session_id,
                user_prompt="Start deterministic Codex conformance.",
                base_cgs_hash=CGS_HASH,
                project_id="agent-conformance",
                context_capsule_path=str(capsule),
                allowed_tools=allowed_tools,
                metadata={"project_path": str(root), "tool_transport": "mcp"},
            ),
            current_cgs=current_cgs,
            proposal_session=proposal_session,
            observe=observe,
        )


class _StaticCodexProbe:
    def probe(
        self,
        executable_path: str,
        *,
        timeout_seconds: float,
    ) -> CodexAppServerProbeResult:
        del executable_path, timeout_seconds
        return CodexAppServerProbeResult(
            initialize={
                "userAgent": "codex/0.91.0",
                "platformFamily": "windows",
                "platformOs": "windows",
            },
            account={
                "account": {
                    "type": "chatgpt",
                    "email": "conformance@example.invalid",
                    "planType": "test",
                },
                "requiresOpenaiAuth": True,
            },
            models={
                "data": [
                    {
                        "id": "gpt-conformance",
                        "model": "gpt-conformance",
                        "displayName": "Conformance Model",
                        "defaultReasoningEffort": "medium",
                        "supportedReasoningEfforts": [],
                        "inputModalities": ["text"],
                        "isDefault": True,
                    }
                ],
                "nextCursor": None,
            },
            provider_capabilities={
                "providers": {"openai": {"maxInputTokens": 100000}}
            },
            rate_limits={"rateLimits": {"limitId": "conformance"}},
            usage={"summary": {"lifetimeTokens": 1000}},
        )


class _CodexClient:
    def __init__(
        self,
        *,
        thread_id: str,
        turn_id: str,
        notifications: list[dict[str, Any]] | None = None,
        fork_id: str = "",
    ) -> None:
        self.thread_id = thread_id
        self.turn_id = turn_id
        self.fork_id = fork_id or f"{thread_id}-fork"
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.responses: list[tuple[int | str, dict[str, Any]]] = []
        self.notifications_sent: list[tuple[str, dict[str, Any]]] = []
        self.closed = False
        self._notifications = list(notifications or [])

    def request(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        clean = _copy_mapping(params)
        self.requests.append((method, clean))
        if method == "initialize":
            return {
                "userAgent": "codex-conformance",
                "platformFamily": "windows",
                "platformOs": "windows",
            }
        if method == "thread/start":
            return {"thread": {"id": self.thread_id, "modelProvider": "openai"}}
        if method == "thread/resume":
            return {"thread": {"id": str(params["threadId"]), "turns": []}}
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
            return {"turn": {"id": self.turn_id, "status": "inProgress"}}
        if method == "turn/interrupt":
            return {"status": "interrupted"}
        if method == "thread/backgroundTerminals/clean":
            return {"cleaned": True}
        raise AssertionError(f"unexpected Codex conformance method {method!r}")

    def optional_request(
        self,
        method: str,
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self.request(method, params)

    def notify(self, method: str, params: Mapping[str, Any]) -> None:
        self.notifications_sent.append((method, _copy_mapping(params)))

    def respond(self, request_id: int | str, result: Mapping[str, Any]) -> None:
        self.responses.append((request_id, _copy_mapping(result)))

    def read_notification(self, timeout_seconds: float = 0.25) -> dict[str, Any] | None:
        del timeout_seconds
        return self._notifications.pop(0) if self._notifications else None

    def close(self) -> None:
        self.closed = True


class _CodexClientFactory:
    def __init__(self, *clients: _CodexClient) -> None:
        self._clients = list(clients)
        self.created: list[_CodexClient] = []

    def __call__(self, executable_path: str) -> _CodexClient:
        del executable_path
        if not self._clients:
            raise AssertionError("no deterministic Codex conformance clients remain")
        client = self._clients.pop(0)
        self.created.append(client)
        return client


def _scenario_clients(
    *,
    name: str,
    session_id: str,
    proposal: Mapping[str, Any],
) -> list[_CodexClient]:
    thread_id = f"thread-{session_id}"
    turn_id = f"turn-{session_id}"
    if name == "lifecycle":
        return [
            _CodexClient(thread_id=thread_id, turn_id=turn_id),
            _CodexClient(
                thread_id=thread_id,
                turn_id=turn_id,
                fork_id=f"{thread_id}-fork",
            ),
        ]
    if name == "proposal":
        notifications = [
            {"method": "turn/started", "params": {"turn": {"id": turn_id}}},
            {
                "id": 73,
                "method": "item/tool/call",
                "params": {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "callId": "call-conformance-proposal",
                    "namespace": "xace",
                    "tool": "submit_proposal",
                    "arguments": {"proposal": dict(proposal)},
                },
            },
            {
                "method": "turn/completed",
                "params": {"turn": {"id": turn_id, "status": "completed"}},
            },
        ]
    elif name == "cancel":
        notifications = [
            {"method": "turn/started", "params": {"turn": {"id": turn_id}}}
        ]
    else:
        notifications = [
            {"method": "turn/started", "params": {"turn": {"id": turn_id}}},
            {
                "method": "item/completed",
                "params": {"item": {"id": "reason-1", "type": "reasoning"}},
            },
            {
                "method": "item/completed",
                "params": {
                    "item": {
                        "id": "tool-1",
                        "type": "mcpToolCall",
                        "name": "xace.read_cgs",
                    }
                },
            },
            {
                "method": "turn/completed",
                "params": {"turn": {"id": turn_id, "status": "completed"}},
            },
        ]
    return [
        _CodexClient(
            thread_id=thread_id,
            turn_id=turn_id,
            notifications=notifications,
        )
    ]


def _proposal_bridge(
    *,
    root: Path,
    session_id: str,
    current_cgs: Mapping[str, Any],
    proposal_session: SimpleNamespace,
    allowed_tools: tuple[str, ...],
) -> XaceMcpToolBridge:
    del root
    surface = XaceToolSurface(
        ContextRetrievalSource(cgs=current_cgs, cgs_hash=CGS_HASH),
        proposal_ingress=AgentProposalIngressGate(
            clock=lambda: 1.0,
            token_factory=lambda: "apt-codex-conformance",
        ),
        proposal_session=proposal_session,
    )
    return XaceMcpToolBridge(
        surface,
        XaceMcpToolContext(
            xace_session_id=session_id,
            provider_id=CODEX_APP_SERVER_PROVIDER_ID,
            cgs_hash=CGS_HASH,
            allowed_tools=allowed_tools,
        ),
    )


def _proposal(*, session_id: str) -> dict[str, Any]:
    return {
        "proposal_id": f"proposal-{session_id}",
        "session_id": session_id,
        "provider_id": CODEX_APP_SERVER_PROVIDER_ID,
        "base_cgs_hash": CGS_HASH,
        "intent": "Prove preview-only Codex proposal ingress.",
        "summary": "Declare a deterministic conformance component.",
        "proposal_kind": "mutation",
        "risk_level": "medium",
        "operations": [
            {
                "operation_id": "declare.conformance_resource",
                "kind": "declare_component",
                "explanation": "Declare deterministic conformance state.",
                "component_type_id": 19001,
                "component_name": "COMP_CONFORMANCE_RESOURCE_V1",
                "version": "1.0.0",
                "fields": [
                    {
                        "name": "current",
                        "field_type": "fixed",
                        "default": 1000000,
                    }
                ],
            }
        ],
    }


def _unavailable_native_transport(_bridge: XaceMcpToolBridge) -> None:
    raise RuntimeError("native MCP is intentionally unavailable in fallback fixture")


def _proposal_session() -> SimpleNamespace:
    return SimpleNamespace(
        pending_txn=None,
        pending_prompt_preview=None,
        pending_prompt_result=None,
        pending_prompt_clarification=None,
        pending_clar_id=None,
        touch=lambda: None,
    )


def _copy_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): (
            _copy_mapping(item)
            if isinstance(item, Mapping)
            else [
                _copy_mapping(child) if isinstance(child, Mapping) else child
                for child in item
            ]
            if isinstance(item, list)
            else item
        )
        for key, item in value.items()
    }


__all__ = [
    "CGS_HASH",
    "CodexConformanceFixture",
    "MockConformanceFixture",
    "conformance_cgs",
]
