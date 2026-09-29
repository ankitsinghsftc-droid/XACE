"""AG-029 schema-only evidence. Never starts account sessions or model turns.

This is a diagnostic prerequisite, not a runtime activation or certificate.
Keep every consumed request failure visible instead of reporting only the first.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from codex_schema_check import inspect
from agent_host.codex_compatibility import REQUESTS, _accepts, _resolve


def request_findings(documents: dict) -> list[dict]:
    findings = []
    doc = documents.get("ClientRequest.json", {})
    try:
        methods = {}
        for raw in doc.get("oneOf", doc.get("anyOf", [])):
            branch = _resolve(raw, doc)
            method = _resolve(branch.get("properties", {}).get("method", {}), doc)
            for name in method.get("enum", [method.get("const")]):
                if isinstance(name, str):
                    if name in methods:
                        raise ValueError("duplicate method")
                    methods[name] = branch
        for name, params in sorted(REQUESTS.items()):
            branch = methods.get(name)
            accepted = branch is not None and _accepts({"id": 1, "method": name, "params": params}, branch, doc)
            if not accepted:
                findings.append({"method": name, "code": "consumed_request_incompatible"})
        # This diagnostic asks about the explicit restricted-read field without
        # trusting ignored additional properties or changing the production gate.
        turn = methods.get("turn/start")
        supported = False
        if turn:
            params = _resolve(turn.get("properties", {}).get("params", {}), doc)
            sandbox = _resolve(params.get("properties", {}).get("sandboxPolicy", {}), doc)
            supported = _accepts(REQUESTS["turn/start"]["sandboxPolicy"], sandbox, doc)
        if not supported:
            findings.append({"method": "turn/start", "code": "restricted_read_contract_unverified"})
    except (KeyError, TypeError, ValueError, RecursionError, AttributeError):
        findings.append({"method": "schema", "code": "schema_diagnostic_unavailable"})
    return findings


def preflight_report(evidence: dict, documents: dict) -> dict:
    # Copy only known, content-free schema evidence. No paths, provider identity,
    # auth values, arbitrary error strings, prompts or raw events enter this file.
    fields = ("profile", "version", "sha256", "schema_fingerprint", "document_count")
    findings = request_findings(documents)
    admitted = evidence.get("version_admitted") is True
    compatible = evidence.get("compatible") is True and not findings
    return {
        "schema": "xace.codex_certification_preflight.v1",
        "runtime": {key: evidence.get(key) for key in fields},
        "version_admitted": admitted,
        "schema_compatible": compatible,
        "findings": findings,
        "schema_preflight_passed": admitted and compatible,
        "real_account_certified": False,
        "account_calls_performed": False,
        "model_turns_performed": 0,
        "runtime_activated": False,
        "remaining_requirements": ["verified_official_provenance_and_native_runtime",
                                   "opt_in_real_account_scenarios", "reviewed_certification_evidence"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence, documents = inspect(args.executable.resolve())
    report = preflight_report(evidence, documents)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["schema_preflight_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
