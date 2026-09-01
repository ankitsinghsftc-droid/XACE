"""Deterministic mock adapter for AG-001 contract tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from .contracts import (
    AgentAuthState,
    AgentCapabilities,
    AgentEvent,
    AgentEventType,
    AgentProposalEnvelope,
    AgentProposalKind,
    AgentProviderKind,
    AgentRiskLevel,
    AgentProviderStatus,
    AgentSecurityPolicy,
    AgentSessionHandle,
    AgentStartRequest,
    AgentTurnRequest,
    ToolTransport,
    utc_now_iso,
)
from .tool_surface import default_xace_tool_specs


class MockAgentAdapter:
    """Small deterministic adapter used before real provider integrations exist."""

    provider_id = "mock"
    display_name = "Mock Agent"

    def __init__(self, clock: Callable[[], str] | None = None) -> None:
        self._clock = clock or utc_now_iso
        self._event_counter = 0
        self._proposal_counter = 0
        self._sessions: dict[str, AgentSessionHandle] = {}
        self._cancelled_sessions: set[str] = set()

    async def detect(self) -> AgentProviderStatus:
        return AgentProviderStatus(
            provider_id=self.provider_id,
            display_name=self.display_name,
            provider_kind=AgentProviderKind.MOCK,
            installed=True,
            available=True,
            auth_state=AgentAuthState.NOT_REQUIRED,
            version="0.1.0",
            capabilities=await self.list_capabilities(),
            last_checked_at=self._clock(),
            metadata={"external_provider_calls": False},
        )

    async def list_capabilities(self) -> AgentCapabilities:
        return AgentCapabilities(
            supports_mcp_tools=True,
            supports_streaming_events=True,
            supports_thread_resume=True,
            supports_thread_fork=False,
            supports_compaction=False,
            supports_cancellation=True,
            supports_model_discovery=False,
            supports_account_state=False,
            supports_progressive_retrieval=True,
            supported_tool_transports=(ToolTransport.MCP,),
            xace_tools=default_xace_tool_specs(),
            security_policy=AgentSecurityPolicy(),
        )

    async def start_session(self, request: AgentStartRequest) -> AgentSessionHandle:
        handle = AgentSessionHandle(
            xace_session_id=request.xace_session_id,
            provider_id=self.provider_id,
            provider_session_id=f"mock-thread-{request.xace_session_id}",
            base_cgs_hash=request.base_cgs_hash,
            latest_cgs_hash=request.base_cgs_hash,
            created_at=self._clock(),
            metadata={
                "project_id": request.project_id,
                "context_capsule_path": request.context_capsule_path,
            },
        )
        self._sessions[handle.provider_session_id] = handle
        self._cancelled_sessions.discard(handle.provider_session_id)
        return handle

    async def resume_session(self, handle: AgentSessionHandle) -> AgentSessionHandle:
        self._sessions[handle.provider_session_id] = handle
        return handle

    async def cancel_turn(self, handle: AgentSessionHandle) -> None:
        self._cancelled_sessions.add(handle.provider_session_id)

    async def run_turn(self, request: AgentTurnRequest) -> AsyncIterator[AgentEvent]:
        handle = request.handle
        if handle.provider_session_id not in self._sessions:
            self._sessions[handle.provider_session_id] = handle

        yield self._event(
            AgentEventType.TURN_STARTED,
            handle,
            1,
            "Mock agent turn started.",
            {"prompt": request.user_prompt},
        )

        if handle.provider_session_id in self._cancelled_sessions:
            yield self._event(
                AgentEventType.TURN_CANCELLED,
                handle,
                2,
                "Mock agent turn cancelled.",
            )
            return

        yield self._event(
            AgentEventType.STATUS,
            handle,
            2,
            "Mock agent inspected the context capsule.",
            {"allowed_tools": list(request.allowed_tools)},
        )

        proposal = self._typed_component_proposal(request)
        yield self._event(
            AgentEventType.PROPOSAL,
            handle,
            3,
            "Mock agent submitted a typed component proposal.",
            {"proposal": proposal.to_dict()},
        )
        yield self._event(
            AgentEventType.TURN_COMPLETED,
            handle,
            4,
            "Mock agent turn completed.",
        )

    def _typed_component_proposal(self, request: AgentTurnRequest) -> AgentProposalEnvelope:
        self._proposal_counter += 1
        component_type_id = 10_000 + self._proposal_counter
        component_name = f"COMP_MOCK_RESOURCE_{self._proposal_counter:04d}_V1"
        return AgentProposalEnvelope(
            proposal_id=f"mock-proposal-{self._proposal_counter:04d}",
            session_id=request.handle.xace_session_id,
            provider_id=self.provider_id,
            base_cgs_hash=request.base_cgs_hash,
            intent="mock_agent_preview_validation",
            summary="Mock adapter proposes one generated component schema.",
            proposal_kind=AgentProposalKind.MUTATION,
            risk_level=AgentRiskLevel.MEDIUM,
            operations=(
                {
                    "operation_id": f"declare.mock_resource.{self._proposal_counter:04d}",
                    "kind": "declare_component",
                    "explanation": "Declare a deterministic mock resource for Agent Mode preview.",
                    "component_type_id": component_type_id,
                    "component_name": component_name,
                    "version": "1.0.0",
                    "fields": [
                        {
                            "name": "current",
                            "field_type": "fixed",
                            "default": 1_000_000,
                        }
                    ],
                },
            ),
            requires_structural_regeneration=True,
            metadata={
                "external_provider_calls": False,
                "model": "mock-agent",
                "confidence": 0.91,
            },
        )

    def _event(
        self,
        event_type: AgentEventType,
        handle: AgentSessionHandle,
        sequence: int,
        message: str,
        data: dict | None = None,
    ) -> AgentEvent:
        self._event_counter += 1
        return AgentEvent(
            event_id=f"mock-event-{self._event_counter:04d}",
            event_type=event_type,
            session_id=handle.xace_session_id,
            provider_id=self.provider_id,
            sequence=sequence,
            message=message,
            data=data or {},
            created_at=self._clock(),
        )
