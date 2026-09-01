import sys
import tempfile
import unittest
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from credential_store import UnsafeFileCredentialBackend  # noqa: E402
from provider_settings import (  # noqa: E402
    AI_MODE_AGENT,
    AI_MODE_API_BYOK,
    AI_MODE_LOCAL_AGENT,
    PRIMARY_AGENT_ADAPTER,
    ProviderSettingsStore,
)


class AgentModeSettingsTests(unittest.TestCase):
    def test_default_payload_exposes_disabled_agent_mode_without_changing_api_byok(self):
        with tempfile.TemporaryDirectory(prefix="xace-agent-mode-settings-") as tmp:
            store = _store(Path(tmp))

            payload = store.payload()

            self.assertEqual(payload["ai_mode"], AI_MODE_API_BYOK)
            self.assertEqual(payload["requested_ai_mode"], AI_MODE_API_BYOK)
            self.assertEqual(payload["provider"], "auto")
            self.assertEqual(payload["current"], "auto")
            self.assertFalse(payload["ready"])
            self.assertEqual(payload["readiness"]["code"], "PROVIDER_HEALTH_UNTESTED")
            self.assertIn("providers", payload)

            modes = {mode["id"]: mode for mode in payload["ai_modes"]}
            self.assertEqual(set(modes), {AI_MODE_API_BYOK, AI_MODE_AGENT, AI_MODE_LOCAL_AGENT})
            self.assertTrue(modes[AI_MODE_API_BYOK]["enabled"])
            self.assertTrue(modes[AI_MODE_API_BYOK]["active"])
            self.assertFalse(modes[AI_MODE_AGENT]["enabled"])
            self.assertFalse(modes[AI_MODE_AGENT]["available"])
            self.assertEqual(modes[AI_MODE_AGENT]["code"], "AGENT_MODE_DISABLED")

            agent = payload["agent_mode"]
            self.assertEqual(agent["schema"], "xace.ai_mode_status.v1")
            self.assertEqual(agent["primary_adapter"], PRIMARY_AGENT_ADAPTER)
            self.assertEqual(agent["tool_transport_preference"], "mcp")
            self.assertEqual(agent["certified_adapters"], [])
            self.assertFalse(agent["distribution"]["bundling_allowed"])

    def test_agent_mode_can_be_enabled_for_tests_without_provider_side_effects(self):
        with tempfile.TemporaryDirectory(prefix="xace-agent-mode-enable-") as tmp:
            store = _store(Path(tmp))
            before = store.active_selection()

            payload = store.configure_ai_mode(mode=AI_MODE_AGENT, enabled=True)
            after = store.active_selection()

            self.assertEqual(before, after)
            self.assertEqual(payload["requested_ai_mode"], AI_MODE_AGENT)
            self.assertEqual(payload["ai_mode"], AI_MODE_AGENT)
            self.assertEqual(payload["provider"], "auto")
            self.assertEqual(payload["agent_mode"]["code"], "CODEX_NOT_INSTALLED")
            self.assertTrue(payload["agent_mode"]["enabled"])
            self.assertTrue(payload["agent_mode"]["active"])
            self.assertFalse(payload["agent_mode"]["ready"])
            self.assertFalse(payload["agent_mode"]["available"])

    def test_disabled_requested_agent_mode_falls_back_to_api_byok_effective_mode(self):
        with tempfile.TemporaryDirectory(prefix="xace-agent-mode-disabled-") as tmp:
            store = _store(Path(tmp))

            payload = store.configure_ai_mode(mode=AI_MODE_AGENT, enabled=False)

            self.assertEqual(payload["requested_ai_mode"], AI_MODE_AGENT)
            self.assertEqual(payload["ai_mode"], AI_MODE_API_BYOK)
            self.assertFalse(payload["agent_mode"]["active"])
            self.assertEqual(store.active_ai_mode(), AI_MODE_API_BYOK)

    def test_invalid_ai_mode_is_rejected_when_configured(self):
        with tempfile.TemporaryDirectory(prefix="xace-agent-mode-invalid-") as tmp:
            store = _store(Path(tmp))

            with self.assertRaisesRegex(Exception, "Unsupported AI mode"):
                store.configure_ai_mode(mode="raw_shell_agent", enabled=True)


def _store(root: Path) -> ProviderSettingsStore:
    return ProviderSettingsStore(
        root / "provider_settings.json",
        credential_store=UnsafeFileCredentialBackend(root / "unsafe_credentials.json"),
        agent_status_reader=_missing_codex_status,
    )


def _missing_codex_status() -> dict:
    return {
        "schema": "xace.agent_host.v1",
        "provider_id": PRIMARY_AGENT_ADAPTER,
        "display_name": "Codex App Server",
        "provider_kind": "codex_app_server",
        "installed": False,
        "available": False,
        "auth_state": "missing",
        "executable_path": None,
        "version": None,
        "min_supported_version": None,
        "account_label": None,
        "capabilities": {
            "supports_mcp_tools": True,
            "supports_streaming_events": True,
            "supports_thread_resume": True,
            "supports_thread_fork": True,
            "supports_compaction": True,
            "supports_cancellation": True,
            "supports_model_discovery": True,
            "supports_account_state": True,
            "supports_progressive_retrieval": True,
            "supported_tool_transports": ["mcp"],
            "xace_tools": [],
            "security_policy": {
                "allow_raw_shell": False,
                "allow_real_project_writes": False,
                "allow_direct_gde_commit": False,
                "allow_direct_runtime_mutation": False,
                "allow_credential_access": False,
                "builder_safe": True,
            },
            "warnings": [],
        },
        "warnings": ["Codex executable was not found."],
        "last_checked_at": "2026-09-01T00:00:00Z",
        "metadata": {
            "detection_source": "test",
            "app_server_responsive": False,
            "transport": "stdio_jsonl",
        },
    }


if __name__ == "__main__":
    unittest.main()
