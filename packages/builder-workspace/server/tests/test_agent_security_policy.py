import asyncio
import sys
import tempfile
import unittest
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from agent_host.codex_adapter import (  # noqa: E402
    CodexAppServerAdapter,
    CodexAppServerProtocolError,
)
from agent_host.context_capsule import ContextRetrievalSource  # noqa: E402
from agent_host.contracts import (  # noqa: E402
    AgentEvent,
    AgentEventType,
    AgentSecurityPolicy,
    AgentStartRequest,
    AgentToolPermission,
    AgentToolSpec,
)
from agent_host.event_stream import AgentEventStreamManager  # noqa: E402
from agent_host.mock_agent import MockAgentAdapter  # noqa: E402
from agent_host.registry import AgentAdapterRegistry  # noqa: E402
from agent_host.security_policy import (  # noqa: E402
    AgentSecurityPolicyEnforcer,
    AgentSecurityPolicyError,
)
from agent_host.tool_surface import (  # noqa: E402
    XaceToolCallRequest,
    XaceToolSurface,
    default_xace_tool_specs,
    proposal_xace_tool_spec,
)


CGS_HASH = "9" * 64


class MaliciousAgentAdapter(MockAgentAdapter):
    provider_id = "malicious_agent"
    display_name = "Malicious Agent Fixture"

    def __init__(self) -> None:
        super().__init__()
        self.cancel_called = False

    async def cancel_turn(self, handle) -> None:
        self.cancel_called = True
        await super().cancel_turn(handle)

    async def run_turn(self, request):
        yield AgentEvent(
            event_id="malicious-shell-event",
            event_type=AgentEventType.TOOL_CALL,
            session_id=request.handle.xace_session_id,
            provider_id=self.provider_id,
            sequence=1,
            message="Attempted raw shell access.",
            data={"tool_name": "xace.shell", "command": "write project files"},
        )
        yield AgentEvent(
            event_id="malicious-completed-event",
            event_type=AgentEventType.TURN_COMPLETED,
            session_id=request.handle.xace_session_id,
            provider_id=self.provider_id,
            sequence=2,
            message="This event must never be reached.",
        )


class AgentSecurityPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = AgentSecurityPolicyEnforcer(
            tool_specs=default_xace_tool_specs() + (proposal_xace_tool_spec(),)
        )

    def test_privileged_policy_configuration_fails_closed(self) -> None:
        adapter = CodexAppServerAdapter(
            security_policy=AgentSecurityPolicy(allow_raw_shell=True)
        )

        capabilities = asyncio.run(adapter.list_capabilities())
        self.assertFalse(capabilities.supports_streaming_events)
        self.assertFalse(capabilities.supports_mcp_tools)
        self.assertTrue(
            any("failed closed" in warning.lower() for warning in capabilities.warnings)
        )

        with self.assertRaisesRegex(
            CodexAppServerProtocolError,
            "Agent Mode is disabled",
        ):
            asyncio.run(
                adapter.start_session(
                    AgentStartRequest(
                        xace_session_id="security-session",
                        user_prompt="Inspect safely.",
                        base_cgs_hash=CGS_HASH,
                    )
                )
            )

    def test_only_exact_registered_xace_tools_are_authorized(self) -> None:
        self.assertEqual(
            self.policy.require_tool(
                "xace.read_cgs",
                enabled_tools=("xace.read_cgs",),
            ).name,
            "xace.read_cgs",
        )
        for tool_name in (
            "xace.shell",
            "xace.write_file",
            "xace.commit_gde",
            "xace.runtime_mutate",
            "provider.read_cgs",
        ):
            with self.subTest(tool_name=tool_name):
                with self.assertRaises(AgentSecurityPolicyError):
                    self.policy.require_tool(tool_name)

        direct_commit = AgentToolSpec(
            name="xace.commit_gde",
            description="Forbidden direct GDE commit fixture.",
            permission=AgentToolPermission.PROPOSAL_WRITE,
            read_only=False,
        )
        with self.assertRaisesRegex(
            AgentSecurityPolicyError,
            "reserved for xace.submit_proposal",
        ):
            AgentSecurityPolicyEnforcer(tool_specs=(direct_commit,))

    def test_metadata_rejects_credentials_and_enabled_authority(self) -> None:
        self.policy.validate_metadata(
            {
                "raw_shell": False,
                "allow_real_project_writes": False,
                "nested": {"runtime_mutation": False},
            }
        )
        for metadata in (
            {"api_key": "credential-fixture"},
            {"nested": {"password": "credential-fixture"}},
            {"allow_direct_gde_commit": True},
            {"raw_shell": True},
        ):
            with self.subTest(metadata=metadata):
                with self.assertRaises(AgentSecurityPolicyError):
                    self.policy.validate_metadata(metadata)

    def test_capsule_cwd_cannot_escape_to_the_real_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "game"
            capsule = project / ".xace" / "agent_capsules" / "capsule-1"
            outside = Path(temporary) / "outside"
            capsule.mkdir(parents=True)
            outside.mkdir()

            resolved = self.policy.resolve_capsule_cwd(
                str(capsule),
                {"project_path": str(project)},
            )
            self.assertEqual(Path(resolved), capsule.resolve())

            for candidate in (str(project), str(outside), None):
                with self.subTest(candidate=candidate):
                    with self.assertRaises(AgentSecurityPolicyError):
                        self.policy.resolve_capsule_cwd(
                            candidate,
                            {"project_path": str(project)},
                        )

            sandbox = self.policy.codex_sandbox_policy(resolved)
            self.assertEqual(sandbox["type"], "readOnly")
            self.assertEqual(sandbox["access"]["readableRoots"], [resolved])
            self.assertFalse(sandbox["access"]["includePlatformDefaults"])

    def test_codex_provider_events_deny_shell_writes_and_approvals(self) -> None:
        forbidden = (
            {"method": "command/exec", "params": {"command": "whoami"}},
            {
                "method": "item/started",
                "params": {"item": {"type": "commandExecution"}},
            },
            {
                "method": "item/completed",
                "params": {"item": {"type": "fileChange"}},
            },
            {
                "id": 7,
                "method": "item/commandExecution/requestApproval",
                "params": {},
            },
            {
                "id": 8,
                "method": "item/tool/call",
                "params": {"namespace": "xace", "name": "shell"},
            },
        )
        for notification in forbidden:
            with self.subTest(notification=notification):
                decision = self.policy.inspect_provider_event(
                    notification,
                    enabled_tools=("xace.read_cgs",),
                )
                self.assertFalse(decision.allowed)

        allowed = self.policy.inspect_provider_event(
            {
                "id": 9,
                "method": "item/tool/call",
                "params": {"namespace": "xace", "name": "read_cgs"},
            },
            enabled_tools=("xace.read_cgs",),
        )
        self.assertTrue(allowed.allowed)
        self.assertEqual(allowed.tool_name, "xace.read_cgs")

    def test_tool_surface_denies_unregistered_mutation_tools(self) -> None:
        surface = XaceToolSurface(
            ContextRetrievalSource(cgs={"metadata": {}}, cgs_hash=CGS_HASH)
        )
        for tool_name in ("xace.shell", "xace.write_file", "xace.runtime_mutate"):
            result = surface.execute(
                XaceToolCallRequest(
                    tool_name=tool_name,
                    xace_session_id="security-session",
                    provider_id="malicious_agent",
                    cgs_hash=CGS_HASH,
                ),
                allowed_tools=(tool_name,),
            )
            self.assertEqual(result.status, "denied")
            self.assertTrue(result.read_only)
            self.assertFalse(result.data.get("project_mutated", False))

    def test_malicious_adapter_event_is_cancelled_before_forwarding(self) -> None:
        async def scenario():
            adapter = MaliciousAgentAdapter()
            messages: list[dict] = []

            async def send(message: dict) -> None:
                messages.append(message)

            manager = AgentEventStreamManager(
                AgentAdapterRegistry([adapter]),
            )
            result = await manager.start_turn(
                session_id="security-session",
                provider_id=adapter.provider_id,
                user_prompt="Try to escape the boundary.",
                cgs_hash=CGS_HASH,
                send_fn=send,
                allowed_tools=("xace.read_cgs",),
            )
            self.assertTrue(result.accepted)
            await manager.wait_for_turn("security-session")
            return adapter, messages

        adapter, messages = asyncio.run(scenario())
        self.assertTrue(adapter.cancel_called)
        agent_events = [item for item in messages if item.get("type") == "agent_event"]
        self.assertEqual([item["event_type"] for item in agent_events], ["error"])
        self.assertNotIn("malicious-shell-event", {item.get("event_id") for item in agent_events})
        self.assertEqual(messages[-1]["state"], "error")
        self.assertEqual(messages[-1]["code"], "AGENT_SECURITY_POLICY_DENIED")


if __name__ == "__main__":
    unittest.main()
