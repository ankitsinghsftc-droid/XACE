import asyncio
import sys
import tempfile
import unittest
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from agent_host import (  # noqa: E402
    AgentAdapterRegistry,
    AgentAuthState,
    AgentProviderKind,
    AgentSecurityPolicy,
    CODEX_APP_SERVER_PROVIDER_ID,
    CodexAppServerAdapter,
    CodexAppServerProbeResult,
    CodexExecutableCandidate,
    create_default_registry,
    parse_codex_version,
)
from credential_store import UnsafeFileCredentialBackend  # noqa: E402
from provider_settings import AI_MODE_AGENT, ProviderSettingsStore  # noqa: E402


FIXED_TIME = "2026-09-01T00:00:00Z"
FAKE_CODEX_PATH = "C:/tools/codex.exe"


class FakeCodexProbe:
    def __init__(self, result: CodexAppServerProbeResult | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, float]] = []

    def probe(
        self,
        executable_path: str,
        *,
        timeout_seconds: float = 4.0,
    ) -> CodexAppServerProbeResult:
        self.calls.append((executable_path, timeout_seconds))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class CodexDetectionTests(unittest.TestCase):
    def test_codex_app_server_probe_maps_auth_models_and_capabilities(self) -> None:
        probe = FakeCodexProbe(_successful_probe())
        adapter = _adapter(probe)

        status = adapter.detect_sync()

        self.assertEqual(status.provider_id, CODEX_APP_SERVER_PROVIDER_ID)
        self.assertEqual(status.provider_kind, AgentProviderKind.CODEX_APP_SERVER)
        self.assertTrue(status.installed)
        self.assertTrue(status.available)
        self.assertEqual(status.auth_state, AgentAuthState.SIGNED_IN)
        self.assertEqual(status.version, "0.91.0")
        self.assertEqual(status.account_label, "ChatGPT pro u***@example.com")
        self.assertTrue(status.capabilities.supports_mcp_tools)
        self.assertTrue(status.capabilities.supports_model_discovery)
        self.assertTrue(status.capabilities.supports_account_state)
        self.assertEqual(status.capabilities.security_policy, AgentSecurityPolicy())
        self.assertEqual(probe.calls, [(FAKE_CODEX_PATH, 4.0)])

        metadata = status.metadata
        self.assertTrue(metadata["app_server_responsive"])
        self.assertEqual(metadata["default_model"], "gpt-5.6-terra")
        self.assertEqual(metadata["model_ids"], ["gpt-5.6-terra", "gpt-5.6-luna"])
        self.assertEqual(metadata["account"]["email"], "u***@example.com")
        self.assertIn("account/read", metadata["probed_methods"])
        self.assertIn("model/list", metadata["probed_methods"])
        self.assertNotIn("thread/shellCommand", metadata["probed_methods"])
        self.assertNotIn("fs/writeFile", metadata["probed_methods"])

    def test_missing_codex_binary_reports_structured_unavailable_status(self) -> None:
        probe = FakeCodexProbe(AssertionError("probe should not be called"))
        adapter = CodexAppServerAdapter(
            executable_resolver=lambda: None,
            app_server_probe=probe,
            version_reader=lambda _path: "codex 0.91.0",
            clock=lambda: FIXED_TIME,
        )

        status = adapter.detect_sync()

        self.assertFalse(status.installed)
        self.assertFalse(status.available)
        self.assertEqual(status.auth_state, AgentAuthState.MISSING)
        self.assertIsNone(status.executable_path)
        self.assertEqual(status.last_checked_at, FIXED_TIME)
        self.assertEqual(probe.calls, [])
        self.assertFalse(status.metadata["app_server_responsive"])
        self.assertTrue(status.warnings)

    def test_malformed_model_list_does_not_crash_detection(self) -> None:
        malformed = CodexAppServerProbeResult(
            initialize={"userAgent": "codex-test"},
            account={
                "account": {"type": "chatgpt", "email": "user@example.com"},
                "requiresOpenaiAuth": True,
            },
            models={"data": {"not": "a list"}},
        )
        adapter = _adapter(FakeCodexProbe(malformed))

        status = adapter.detect_sync()

        self.assertTrue(status.installed)
        self.assertFalse(status.available)
        self.assertEqual(status.auth_state, AgentAuthState.UNKNOWN)
        self.assertFalse(status.metadata["app_server_responsive"])
        self.assertIn("model/list result must include data[]", status.warnings[-1])

    def test_auth_required_state_is_not_treated_as_turn_ready(self) -> None:
        probe = FakeCodexProbe(
            CodexAppServerProbeResult(
                initialize={"userAgent": "codex-test"},
                account={"account": None, "requiresOpenaiAuth": True},
                models={"data": [], "nextCursor": None},
                warnings=("Codex App Server requires authentication before model discovery.",),
            )
        )
        adapter = _adapter(probe)

        status = adapter.detect_sync()

        self.assertTrue(status.installed)
        self.assertFalse(status.available)
        self.assertEqual(status.auth_state, AgentAuthState.MISSING)
        self.assertEqual(status.account_label, "Sign in required")
        self.assertIn("missing authentication", " ".join(status.warnings))

    def test_registry_can_opt_into_codex_without_enabling_mock(self) -> None:
        adapter = _adapter(FakeCodexProbe(_successful_probe()))
        registry = create_default_registry(enable_codex=True, codex_adapter=adapter)

        self.assertEqual(registry.provider_ids(), (CODEX_APP_SERVER_PROVIDER_ID,))
        status = asyncio.run(registry.detect(CODEX_APP_SERVER_PROVIDER_ID))
        self.assertTrue(status.available)

    def test_provider_settings_serializes_codex_lifecycle_but_keeps_agent_mode_readiness_gated(self) -> None:
        with tempfile.TemporaryDirectory(prefix="xace-codex-settings-") as tmp:
            root = Path(tmp)
            adapter = _adapter(FakeCodexProbe(_successful_probe()))
            store = ProviderSettingsStore(
                root / "provider_settings.json",
                credential_store=UnsafeFileCredentialBackend(root / "unsafe_credentials.json"),
                agent_status_reader=adapter.detect_sync,
            )

            payload = store.configure_ai_mode(mode=AI_MODE_AGENT, enabled=True)

            self.assertEqual(payload["ai_mode"], AI_MODE_AGENT)
            agent_mode = payload["agent_mode"]
            self.assertTrue(agent_mode["enabled"])
            self.assertTrue(agent_mode["available"])
            self.assertFalse(agent_mode["ready"])
            self.assertEqual(agent_mode["code"], "CODEX_MCP_TOOL_BRIDGE_READY_PROPOSAL_PENDING")
            self.assertEqual(agent_mode["feature_stage"], "ag_011_codex_mcp_tool_bridge")
            self.assertEqual(agent_mode["available_adapters"], [CODEX_APP_SERVER_PROVIDER_ID])
            self.assertEqual(agent_mode["certified_adapters"], [])
            self.assertEqual(
                agent_mode["primary_adapter_status"]["metadata"]["default_model"],
                "gpt-5.6-terra",
            )

    def test_parse_codex_version_extracts_semver_from_cli_text(self) -> None:
        self.assertEqual(parse_codex_version("codex 0.91.0"), "0.91.0")
        self.assertEqual(parse_codex_version("Codex CLI 1.2.3-beta.1"), "1.2.3-beta.1")
        self.assertIsNone(parse_codex_version("codex dev build"))


def _adapter(probe: FakeCodexProbe) -> CodexAppServerAdapter:
    return CodexAppServerAdapter(
        executable_resolver=lambda: CodexExecutableCandidate(
            path=FAKE_CODEX_PATH,
            source="test",
        ),
        app_server_probe=probe,
        version_reader=lambda _path: "codex 0.91.0",
        clock=lambda: FIXED_TIME,
    )


def _successful_probe() -> CodexAppServerProbeResult:
    return CodexAppServerProbeResult(
        initialize={
            "userAgent": "codex/0.91.0",
            "platformFamily": "windows",
            "platformOs": "windows",
        },
        account={
            "account": {
                "type": "chatgpt",
                "email": "user@example.com",
                "planType": "pro",
            },
            "requiresOpenaiAuth": True,
        },
        models={
            "data": [
                {
                    "id": "gpt-5.6-terra",
                    "model": "gpt-5.6-terra",
                    "displayName": "GPT-5.6 Terra",
                    "defaultReasoningEffort": "medium",
                    "supportedReasoningEfforts": [
                        {
                            "reasoningEffort": "low",
                            "description": "Fast responses with lighter reasoning.",
                        },
                        {
                            "reasoningEffort": "medium",
                            "description": "Balanced reasoning.",
                        },
                    ],
                    "inputModalities": ["text", "image"],
                    "supportsPersonality": True,
                    "isDefault": True,
                },
                {
                    "id": "gpt-5.6-luna",
                    "model": "gpt-5.6-luna",
                    "displayName": "GPT-5.6 Luna",
                    "hidden": False,
                    "supportedReasoningEfforts": [],
                    "inputModalities": ["text"],
                },
            ],
            "nextCursor": None,
        },
        provider_capabilities={
            "providers": {
                "openai": {
                    "maxInputTokens": 400000,
                    "supportsVision": True,
                }
            }
        },
        rate_limits={
            "rateLimits": {
                "limitId": "codex",
                "primary": {
                    "usedPercent": 25,
                    "windowDurationMins": 15,
                    "resetsAt": 1730947200,
                },
            }
        },
    )


if __name__ == "__main__":
    unittest.main()
