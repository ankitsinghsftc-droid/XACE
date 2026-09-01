import asyncio
import json
import sys
import unittest
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from agent_host import (  # noqa: E402
    AgentAdapterRegistry,
    AgentCapabilities,
    AgentContractError,
    AgentEventType,
    AgentProposalEnvelope,
    AgentProposalKind,
    AgentProviderKind,
    AgentSecurityPolicy,
    AgentStartRequest,
    AgentToolPermission,
    AgentToolSpec,
    AgentTurnRequest,
    MockAgentAdapter,
    ToolTransport,
    create_default_registry,
)


CGS_HASH = "a" * 64
FIXED_TIME = "2026-08-31T00:00:00Z"


class AgentHostContractTests(unittest.TestCase):
    def test_capabilities_round_trip_as_json_safe_contract(self):
        capabilities = AgentCapabilities(
            supports_mcp_tools=True,
            supports_streaming_events=True,
            supports_thread_resume=True,
            supports_cancellation=True,
            supports_progressive_retrieval=True,
            supported_tool_transports=(ToolTransport.MCP,),
            xace_tools=(
                AgentToolSpec(
                    name="xace.retrieve_context",
                    description="Retrieve controlled read-only context.",
                    permission=AgentToolPermission.READ_ONLY,
                    input_schema={"type": "object", "additionalProperties": False},
                ),
                AgentToolSpec(
                    name="xace.submit_proposal",
                    description="Submit typed operations to the XACE preview gate.",
                    permission=AgentToolPermission.PROPOSAL_WRITE,
                    read_only=False,
                    input_schema={"type": "object"},
                ),
            ),
            security_policy=AgentSecurityPolicy(),
            warnings=("mock only",),
        )

        encoded = capabilities.to_dict()
        self.assertEqual(encoded["supported_tool_transports"], ["mcp"])
        self.assertTrue(encoded["security_policy"]["builder_safe"])
        json.dumps(encoded, sort_keys=True)

        decoded = AgentCapabilities.from_dict(encoded)
        self.assertEqual(capabilities, decoded)

    def test_proposal_envelope_allows_no_op_and_requires_ops_for_mutation(self):
        no_op = AgentProposalEnvelope(
            proposal_id="proposal-1",
            session_id="session-1",
            provider_id="mock",
            base_cgs_hash=CGS_HASH,
            intent="inspect",
            summary="No mutation is needed.",
            proposal_kind=AgentProposalKind.NO_OP,
        )

        encoded = no_op.to_dict()
        self.assertEqual(encoded["proposal_kind"], "no_op")
        self.assertEqual(encoded["operations"], [])
        self.assertEqual(no_op, AgentProposalEnvelope.from_dict(encoded))

        with self.assertRaisesRegex(AgentContractError, "mutation proposals require"):
            AgentProposalEnvelope(
                proposal_id="proposal-2",
                session_id="session-1",
                provider_id="mock",
                base_cgs_hash=CGS_HASH,
                intent="mutate",
                summary="Invalid mutation proposal.",
                proposal_kind=AgentProposalKind.MUTATION,
            )

        with self.assertRaisesRegex(AgentContractError, "must not include operations"):
            AgentProposalEnvelope(
                proposal_id="proposal-3",
                session_id="session-1",
                provider_id="mock",
                base_cgs_hash=CGS_HASH,
                intent="inspect",
                summary="Invalid no-op proposal.",
                proposal_kind=AgentProposalKind.NO_OP,
                operations=({"kind": "set_defaults"},),
            )

    def test_default_registry_does_not_enable_mock_unless_requested(self):
        self.assertEqual(create_default_registry().provider_ids(), ())

        registry = create_default_registry(enable_mock=True)
        self.assertEqual(registry.provider_ids(), ("mock",))

        status = asyncio.run(registry.detect("mock"))
        self.assertEqual(status.provider_kind, AgentProviderKind.MOCK)
        self.assertTrue(status.available)
        self.assertTrue(status.capabilities.security_policy.builder_safe)

    def test_registry_rejects_duplicate_provider_ids(self):
        registry = AgentAdapterRegistry([MockAgentAdapter()])

        with self.assertRaisesRegex(Exception, "already exists"):
            registry.register(MockAgentAdapter())

    def test_mock_adapter_streams_deterministic_typed_proposal_turn(self):
        async def scenario():
            adapter = MockAgentAdapter(clock=lambda: FIXED_TIME)
            handle = await adapter.start_session(
                AgentStartRequest(
                    xace_session_id="session-1",
                    user_prompt="Inspect the project.",
                    base_cgs_hash=CGS_HASH,
                    project_id="project-1",
                    allowed_tools=("xace.read_cgs",),
                )
            )
            request = AgentTurnRequest(
                handle=handle,
                user_prompt="Inspect the project.",
                base_cgs_hash=CGS_HASH,
                allowed_tools=("xace.read_cgs",),
            )
            return [event async for event in adapter.run_turn(request)]

        events = asyncio.run(scenario())

        self.assertEqual(
            [event.event_type for event in events],
            [
                AgentEventType.TURN_STARTED,
                AgentEventType.STATUS,
                AgentEventType.PROPOSAL,
                AgentEventType.TURN_COMPLETED,
            ],
        )
        self.assertEqual([event.event_id for event in events], [
            "mock-event-0001",
            "mock-event-0002",
            "mock-event-0003",
            "mock-event-0004",
        ])
        self.assertTrue(all(event.created_at == FIXED_TIME for event in events))

        proposal_payload = events[2].data["proposal"]
        self.assertEqual(proposal_payload["proposal_id"], "mock-proposal-0001")
        self.assertEqual(proposal_payload["proposal_kind"], "mutation")
        self.assertEqual(proposal_payload["risk_level"], "medium")
        self.assertEqual(len(proposal_payload["operations"]), 1)
        self.assertEqual(proposal_payload["operations"][0]["kind"], "declare_component")
        self.assertNotIn("path", proposal_payload["operations"][0])


if __name__ == "__main__":
    unittest.main()
