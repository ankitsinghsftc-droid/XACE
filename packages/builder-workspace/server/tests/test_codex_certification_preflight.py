import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
from codex_certification_preflight import preflight_report, request_findings
from codex_schema_fixture import schema_fixture


class CertificationPreflightTests(unittest.TestCase):
    def evidence(self):
        return {"compatible": True, "version_admitted": True, "version": "0.154.0"}

    def test_schema_pass_is_never_account_certification(self):
        value = preflight_report(self.evidence(), schema_fixture())
        self.assertTrue(value["schema_preflight_passed"])
        self.assertFalse(value["real_account_certified"])
        self.assertFalse(value["account_calls_performed"])
        self.assertFalse(value["runtime_activated"])
        self.assertEqual(value["model_turns_performed"], 0)

    def test_reports_all_rejected_requests(self):
        schema = schema_fixture()
        for branch in schema["ClientRequest.json"]["oneOf"]:
            if branch["properties"]["method"]["const"] in ("thread/start", "thread/resume"):
                branch["properties"]["params"]["required"].append("newRequired")
        failures = request_findings(schema)
        self.assertEqual([item["method"] for item in failures], ["thread/resume", "thread/start"])
        self.assertFalse(preflight_report(self.evidence(), schema)["schema_preflight_passed"])

    def test_absent_restricted_read_cannot_be_accepted_as_ignored_extra_field(self):
        schema = copy.deepcopy(schema_fixture())
        turn = next(b for b in schema["ClientRequest.json"]["oneOf"]
                    if b["properties"]["method"]["const"] == "turn/start")
        sandbox = turn["properties"]["params"]["properties"]["sandboxPolicy"]
        del sandbox["properties"]["access"]
        sandbox["required"].remove("access")
        sandbox["additionalProperties"] = True
        self.assertIn({"method": "turn/start", "code": "restricted_read_contract_unverified"},
                      request_findings(schema))

    def test_version_or_malformed_schema_fails_closed(self):
        evidence = self.evidence(); evidence["version_admitted"] = False
        self.assertFalse(preflight_report(evidence, schema_fixture())["schema_preflight_passed"])
        self.assertFalse(preflight_report(self.evidence(), {})["schema_preflight_passed"])

    def test_extra_evidence_does_not_leak_or_claim_certification(self):
        evidence = self.evidence()
        evidence.update(error="SECRET-CANARY", auth="SECRET-CANARY", real_account_certified=True)
        value = preflight_report(evidence, schema_fixture())
        self.assertNotIn("SECRET-CANARY", str(value))
        self.assertFalse(value["real_account_certified"])


if __name__ == "__main__":
    unittest.main()
