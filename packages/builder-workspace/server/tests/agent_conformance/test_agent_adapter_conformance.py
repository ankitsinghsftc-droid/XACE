import asyncio
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parents[2]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

TOOL_PATH = SERVER_DIR.parents[2] / "tools" / "agent_provider_conformance.py"

from tests.agent_conformance.fixtures import (  # noqa: E402
    CodexConformanceFixture,
    MockConformanceFixture,
)
from tests.agent_conformance.suite import (  # noqa: E402
    AGENT_CONFORMANCE_REPORT_SCHEMA,
    certify_fixtures,
)


REQUIRED_CHECKS = {
    "contract_surface",
    "detection",
    "safe_capabilities",
    "session_lifecycle",
    "event_ordering",
    "mcp_tool_permissions",
    "proposal_ingress",
    "cancellation",
    "failure_recovery",
}


class _BrokenFixture(MockConformanceFixture):
    provider_id = "broken_provider"
    display_name = "Broken Provider"


class AgentAdapterConformanceTests(unittest.TestCase):
    def test_mock_and_codex_certify_independently(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reports = asyncio.run(
                certify_fixtures(
                    (MockConformanceFixture(), CodexConformanceFixture()),
                    Path(temp_dir),
                )
            )

        by_provider = {report.provider_id: report for report in reports}
        self.assertEqual(set(by_provider), {"mock", "codex_app_server"})
        for report in by_provider.values():
            self.assertTrue(report.certified)
            required = {check.check_id for check in report.checks if check.required}
            self.assertEqual(required, REQUIRED_CHECKS)
            self.assertTrue(
                all(check.status == "pass" for check in report.checks if check.required)
            )
            json.dumps(report.to_dict(), sort_keys=True)

        mock = by_provider["mock"].to_dict()
        unsupported = {
            item["capability"] for item in mock["unsupported_optional_capabilities"]
        }
        self.assertIn("supports_thread_fork", unsupported)
        self.assertIn("supports_compaction", unsupported)
        self.assertEqual(
            by_provider["codex_app_server"].to_dict()[
                "unsupported_optional_capabilities"
            ],
            [],
        )

    def test_provider_failure_does_not_invalidate_a_certified_adapter(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reports = asyncio.run(
                certify_fixtures(
                    (MockConformanceFixture(), _BrokenFixture()),
                    Path(temp_dir),
                )
            )

        by_provider = {report.provider_id: report for report in reports}
        self.assertTrue(by_provider["mock"].certified)
        self.assertFalse(by_provider["broken_provider"].certified)
        self.assertIn(
            "contract_surface",
            by_provider["broken_provider"].to_dict()["required_failures"],
        )

    def test_report_schema_is_stable_and_provider_scoped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report = asyncio.run(
                certify_fixtures((MockConformanceFixture(),), Path(temp_dir))
            )[0].to_dict()

        self.assertEqual(report["schema"], AGENT_CONFORMANCE_REPORT_SCHEMA)
        self.assertEqual(report["provider_id"], "mock")
        self.assertNotIn("claude", json.dumps(report).lower())
        self.assertNotIn("local_agent", json.dumps(report).lower())

    def test_ci_gate_reports_deferred_providers_as_non_blocking(self):
        spec = importlib.util.spec_from_file_location("agent_provider_conformance", TOOL_PATH)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as temp_dir:
            report = asyncio.run(
                module.build_report(
                    work_root=Path(temp_dir),
                    provider_names=("mock", "codex"),
                )
            )

        self.assertTrue(report["ok"])
        self.assertEqual(
            set(report["certified_adapters"]), {"mock", "codex_app_server"}
        )
        self.assertEqual(report["disabled_production_adapters"], [])
        self.assertEqual(
            {item["provider_id"] for item in report["deferred_providers"]},
            {"local_agent", "claude_agent"},
        )
        self.assertTrue(
            all(not item["required"] for item in report["deferred_providers"])
        )


if __name__ == "__main__":
    unittest.main()
