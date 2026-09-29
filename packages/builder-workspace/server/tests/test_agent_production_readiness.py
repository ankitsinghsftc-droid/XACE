import asyncio
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVER_DIR.parents[2]
TOOLS_DIR = REPO_ROOT / "tools"
for import_root in (str(SERVER_DIR), str(TOOLS_DIR)):
    if import_root not in sys.path:
        sys.path.insert(0, import_root)

from agent_mode_production_readiness import (  # noqa: E402
    _probe_live_stable_thread_lifecycle,
    build_report,
)
from certify_launch import build_checks  # noqa: E402
from provider_settings import (  # noqa: E402
    AGENT_MODE_FEATURE_STAGE,
    AI_MODE_AGENT,
    AI_MODE_API_BYOK,
    CERTIFIED_AGENT_ADAPTERS,
    PRIMARY_AGENT_ADAPTER,
    _agent_mode_launch_status,
    _resolve_agent_mode_status,
)


REQUIRED_CHECKS = {
    "codex_adapter_conformance",
    "agent_security_policy",
    "codex_provider_health_contract",
    "api_byok_rollback",
    "billing_boundaries",
    "functional_agent_ux",
    "approval_boundary",
    "distribution_safety",
    "product_claims",
}


class AgentProductionReadinessTests(unittest.TestCase):
    def test_codex_release_gate_passes_without_claude_or_local(self):
        with tempfile.TemporaryDirectory(prefix="xace-agent-production-gate-") as tmp:
            report = asyncio.run(build_report(work_root=Path(tmp)))

        self.assertTrue(report["ok"])
        self.assertEqual(report["shipping_decision"], "ship_codex_agent_mode")
        self.assertEqual(
            report["shipping_decision_scope"],
            "integration_implementation_only",
        )
        self.assertTrue(report["implementation_certified"])
        self.assertFalse(report["public_product_ready"])
        self.assertEqual(report["public_release_decision"], "outside_codex_integration_scope")
        self.assertFalse(report["codex_integration_complete"])
        self.assertEqual(report["codex_integration_decision"], "continue_ag029_through_ag030")
        self.assertEqual(report["release_scope"]["native_mcp_transport"], "complete")
        self.assertEqual(report["release_scope"]["distribution_decision"], "complete")
        self.assertEqual(len(report["release_scope"]["codex_integration_remaining_tasks"]), 2)
        self.assertEqual(report["default_mode"], AI_MODE_API_BYOK)
        self.assertEqual(report["preferred_mode"], AI_MODE_AGENT)
        self.assertEqual(report["feature_stage"], AGENT_MODE_FEATURE_STAGE)
        self.assertIn(PRIMARY_AGENT_ADAPTER, report["certified_adapters"])
        self.assertEqual(report["disabled_production_adapters"], [])
        self.assertEqual(
            {check["check_id"] for check in report["checks"] if check["required"]},
            REQUIRED_CHECKS,
        )
        self.assertTrue(
            all(check["status"] == "pass" for check in report["checks"])
        )
        self.assertEqual(
            {item["provider_id"] for item in report["deferred_providers"]},
            {"local_agent", "claude_agent"},
        )
        self.assertTrue(
            all(not item["required"] for item in report["deferred_providers"])
        )
        self.assertFalse(report["release_scope"]["managed_runtime_bundled"])
        self.assertFalse(report["release_scope"]["public_distribution_ready"])

    def test_uncertified_adapter_fails_closed_to_api_byok(self):
        resolution = _resolve_agent_mode_status(
            enabled=True,
            certified=False,
            adapter_status={"installed": True, "available": True},
        )
        launch = _agent_mode_launch_status(
            enabled=True,
            active=False,
            fallback_active=True,
            certified=False,
            resolution=resolution,
        )

        self.assertEqual(resolution["code"], "AGENT_ADAPTER_NOT_CERTIFIED")
        self.assertEqual(resolution["action"], "continue_api_byok")
        self.assertFalse(launch["implementation_shippable"])
        self.assertFalse(launch["runtime_ready"])
        self.assertTrue(launch["fallback_available"])

    def test_release_manifest_certifies_only_codex(self):
        self.assertEqual(CERTIFIED_AGENT_ADAPTERS, (PRIMARY_AGENT_ADAPTER,))

    def test_editor_free_launch_certification_includes_agent_gate(self):
        with tempfile.TemporaryDirectory(prefix="xace-agent-certify-launch-") as tmp:
            target = Path(tmp)
            full_labels = {check.label for check in build_checks(target, quick=False)}
            quick_labels = {check.label for check in build_checks(target, quick=True)}

        self.assertIn("Codex Agent Mode production readiness", full_labels)
        self.assertIn("Codex Agent Mode production readiness", quick_labels)


if __name__ == "__main__":
    unittest.main()

    def test_live_smoke_uses_stable_initialize_and_deletes_its_empty_thread(self):
        class FakeClient:
            def __init__(self):
                self.requests = []
                self.notifications = []
                self.closed = False

            def request(self, method, params):
                self.requests.append((method, dict(params)))
                if method == "initialize":
                    return {"platformFamily": "windows", "platformOs": "windows"}
                if method == "thread/start":
                    return {"thread": {"id": "thread-smoke"}}
                if method == "thread/delete":
                    self.assert_delete(params)
                    return {}
                raise AssertionError(method)

            def assert_delete(self, params):
                if params != {"threadId": "thread-smoke"}:
                    raise AssertionError(params)

            def notify(self, method, params):
                self.notifications.append((method, dict(params)))

            def close(self):
                self.closed = True

        client = FakeClient()
        with mock.patch(
            "agent_mode_production_readiness.CodexStdioJsonRpcClient",
            return_value=client,
        ):
            result = _probe_live_stable_thread_lifecycle("C:/tools/codex.exe")

        self.assertTrue(result["passed"])
        self.assertFalse(result["experimental_api"])
        self.assertFalse(result["history_mode_sent"])
        self.assertFalse(result["model_turn_started"])
        initialize = next(params for method, params in client.requests if method == "initialize")
        self.assertNotIn("capabilities", initialize)
        thread_start = next(params for method, params in client.requests if method == "thread/start")
        self.assertNotIn("historyMode", thread_start)
        self.assertEqual(thread_start["sandbox"], "read-only")
        self.assertTrue(client.closed)
