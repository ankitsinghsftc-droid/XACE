import sys
import unittest
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from agent_host.codex_distribution import (  # noqa: E402
    CODEX_DISTRIBUTION_POLICY_SCHEMA,
    CODEX_EXTERNAL_RUNTIME_SOURCE,
    CODEX_MANAGED_RUNTIME_SOURCE,
    codex_distribution_policy,
    validate_codex_distribution_policy,
)


class CodexDistributionPolicyTests(unittest.TestCase):
    def test_preferred_source_is_official_pinned_sdk_runtime(self):
        policy = codex_distribution_policy()

        self.assertEqual(policy["schema"], CODEX_DISTRIBUTION_POLICY_SCHEMA)
        self.assertEqual(policy["preferred_runtime_source"], CODEX_MANAGED_RUNTIME_SOURCE)
        self.assertEqual(policy["official_package"]["name"], "openai-codex")
        self.assertEqual(policy["official_package"]["version_policy"], "exact_certified_pin")
        self.assertTrue(policy["official_package"]["includes_pinned_codex_runtime"])

    def test_decision_does_not_enable_download_or_redistribution(self):
        policy = codex_distribution_policy()
        redistribution = policy["redistribution"]

        self.assertFalse(redistribution["bundling_allowed"])
        self.assertFalse(redistribution["raw_binary_redistribution_allowed"])
        self.assertFalse(redistribution["repackaging_allowed"])
        self.assertFalse(redistribution["automatic_acquisition_enabled"])
        self.assertEqual(redistribution["implementation_owner"], "AG-024")

    def test_authentication_remains_provider_owned_and_secret_free(self):
        policy = codex_distribution_policy()
        auth = policy["authentication"]

        self.assertEqual(auth["owner"], "codex_provider")
        self.assertEqual(auth["managed_credential_store"], "os_keyring")
        self.assertFalse(auth["xace_reads_credentials"])
        self.assertFalse(auth["xace_copies_auth_cache"])
        self.assertFalse(auth["xace_persists_credentials"])

    def test_external_cli_remains_supported_fallback(self):
        policy = codex_distribution_policy()
        sources = {entry["source"]: entry for entry in policy["supported_sources"]}

        self.assertIn(CODEX_EXTERNAL_RUNTIME_SOURCE, sources)
        self.assertEqual(
            sources[CODEX_EXTERNAL_RUNTIME_SOURCE]["support_tier"],
            "supported_fallback_after_compatibility_probe",
        )
        self.assertTrue(policy["external_detection_enabled"])
        self.assertEqual(policy["fallback_mode"], "api_byok")

    def test_policy_validation_fails_closed_on_boundary_weakening(self):
        policy = codex_distribution_policy()
        policy["redistribution"]["bundling_allowed"] = True

        with self.assertRaisesRegex(ValueError, "bundling is not approved"):
            validate_codex_distribution_policy(policy)

    def test_callers_receive_detached_policy_payloads(self):
        first = codex_distribution_policy()
        first["authentication"]["owner"] = "xace"

        second = codex_distribution_policy()
        self.assertEqual(second["authentication"]["owner"], "codex_provider")


if __name__ == "__main__":
    unittest.main()
