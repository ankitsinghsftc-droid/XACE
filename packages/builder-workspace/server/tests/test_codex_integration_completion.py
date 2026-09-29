"""AG-030 aggregation tests; not real-account certification."""
import subprocess
import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
from codex_integration_completion import REQUIRED_CHECKS, completion_report, run_check


class CompletionGateTests(unittest.TestCase):
    def passing(self):
        return [{"check_id": name, "status": "pass"} for name in REQUIRED_CHECKS]

    def test_green_engineering_never_substitutes_for_ag029(self):
        with tempfile.TemporaryDirectory() as directory:
            report = completion_report(self.passing(), root=Path(directory))
        self.assertTrue(report["engineering_checks_passed"])
        self.assertFalse(report["codex_integration_complete"])
        self.assertEqual(report["decision"], "blocked_pending_certification")
        self.assertEqual(report["certified_runtime_account_configurations"], [])
        self.assertIn("ag029_real_runtime_account_evidence_invalid", report["blockers"])
        self.assertIn("integration_defect_and_residual_risk_signoff_pending", report["blockers"])
        self.assertEqual(report["whole_xace_launch_readiness"], "outside_scope")
        self.assertFalse(report["claude_local_required"])

    def test_missing_failed_duplicate_or_non_boolean_evidence_fails_closed(self):
        for records in ([], self.passing()[1:], self.passing() + self.passing()[:1],
                        [{"check_id": name, "status": True} for name in REQUIRED_CHECKS]):
            with self.subTest(records=records):
                self.assertFalse(completion_report(records)["engineering_checks_passed"])

    def test_old_shipping_decision_or_untrusted_extras_cannot_certify(self):
        records = self.passing() + [{"check_id": "ag029", "status": "pass",
                                    "shipping_decision": "ship_codex_agent_mode",
                                    "codex_integration_complete": True, "secret": "CANARY"}]
        with tempfile.TemporaryDirectory() as directory:
            report = completion_report(records, root=Path(directory))
        self.assertFalse(report["codex_integration_complete"])
        self.assertNotIn("CANARY", str(report))

    def test_complete_decision_requires_both_engineering_and_validated_review(self):
        with patch("codex_integration_completion.validate_evidence", return_value={
                "blockers": [], "configurations": [{"scope": "unit-test-only"}]}):
            self.assertTrue(completion_report(self.passing())["codex_integration_complete"])
            self.assertFalse(completion_report(self.passing()[1:])["codex_integration_complete"])

    def test_command_failure_timeout_and_missing_executable_are_safe_failures(self):
        for error in (OSError("CANARY"), subprocess.TimeoutExpired("CANARY", 1)):
            with patch("codex_integration_completion.subprocess.run", side_effect=error):
                self.assertEqual(run_check("test", ["fixed"], Path.cwd()),
                                 {"check_id": "test", "status": "fail"})
        with patch("codex_integration_completion.subprocess.run") as call:
            call.return_value.returncode = 2
            self.assertEqual(run_check("test", ["fixed"], Path.cwd())["status"], "fail")
            self.assertEqual(call.call_args.kwargs["stdin"], subprocess.DEVNULL)
            self.assertFalse(call.call_args.kwargs.get("shell", False))


if __name__ == "__main__":
    unittest.main()
