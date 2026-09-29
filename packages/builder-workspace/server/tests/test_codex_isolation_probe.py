"""Probe contract tests; mocks are not native isolation certification."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
from codex_isolation_probe import isolated_environment, probe


class IsolationProbeTests(unittest.TestCase):
    def result(self, stdout="", stderr="", code=1):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "runtime.exe"
            executable.write_bytes(b"synthetic runtime")
            result = subprocess.CompletedProcess([], code, stdout, stderr)
            with patch("codex_isolation_probe.subprocess.run", return_value=result):
                return probe(executable)

    def test_child_environment_drops_credentials_and_config(self):
        with patch.dict("os.environ", {"PATH": "system-path", "OPENAI_API_KEY": "secret",
                                      "CODEX_HOME": "user-home", "CUSTOM_TOKEN": "secret"}, clear=True):
            env = isolated_environment(Path("probe-home"), Path("probe-temp"))
        self.assertNotIn("secret", str(env))
        self.assertNotIn("user-home", str(env))
        self.assertEqual(env["PATH"], "system-path")

    def test_windows_backend_refusals_are_distinguished(self):
        for message, code in (
            ("Restricted read-only access requires the elevated Windows sandbox backend", "elevated_backend_required"),
            ("elevated Windows sandbox requires effective `:root` read access", "elevated_root_read_required"),
            ("apply deny-read ACLs", "deny_read_acl_failure"),
        ):
            with self.subTest(code=code):
                value = self.result(stderr=message)
                self.assertEqual(value["error_code"], code)
                self.assertFalse(value["isolation_verified"])

    def test_exit_zero_without_positive_and_negative_evidence_fails(self):
        for body in ("", "invalid", '{"allowed_read":true}', '{"allowed_read":1}'):
            self.assertFalse(self.result(stdout=body, code=0)["isolation_verified"])

    def test_all_checks_required_and_never_account_certificate(self):
        checks = dict.fromkeys(("allowed_read", "outside_read_denied", "credential_read_denied",
                              "capsule_write_denied", "outside_write_denied"), True)
        value = self.result(stdout=json.dumps(checks), code=0)
        self.assertTrue(value["isolation_verified"])
        self.assertFalse(value["real_account_certified"])
        self.assertFalse(value["account_calls_performed"])
        self.assertFalse(self.result(stdout=json.dumps(checks), code=1)["isolation_verified"])
        for key in checks:
            self.assertFalse(self.result(stdout=json.dumps({**checks, key: False}), code=0)["isolation_verified"])

    def test_diagnostics_do_not_export_raw_output(self):
        value = self.result(stdout="SECRET-CANARY", stderr="SECRET-CANARY")
        self.assertNotIn("SECRET-CANARY", str(value))

    def test_unknown_backend_rejected_before_launch(self):
        with self.assertRaises(ValueError):
            probe(Path("not-executed"), backend="unknown")
