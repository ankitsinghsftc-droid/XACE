#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_SCHEMA = "xace.provider_structured_output_report.v1"
DEFAULT_OUTPUT = REPO_ROOT / "target-provider-structured-output" / "provider_structured_output_report.json"


CHECKS = [
    {
        "path": "packages/inference/src/structured_output.py",
        "needles": [
            "MUTATION_TRANSACTION_SCHEMA",
            "openai_response_format",
            "anthropic_tool_config",
            "google_generation_config",
            "repair_quarantine_prompt",
            "validate_structured_output_text",
        ],
    },
    {
        "path": "packages/inference/src/inference_adapter.py",
        "needles": [
            "structured_output_plan_for",
            "repair_quarantine_prompt",
            "validate_structured_output_text",
            "structured_plan.telemetry_fields",
            "use_response_cache = not request.structured_output",
        ],
    },
    {
        "path": "packages/inference/providers/openai_provider.py",
        "needles": ["response_format", "openai_response_format(structured_output)"],
    },
    {
        "path": "packages/inference/providers/google_provider.py",
        "needles": ["google_generation_config", "structured_output"],
    },
    {
        "path": "packages/inference/providers/anthropic_provider.py",
        "needles": ["anthropic_tool_config", "structured_output", "tool_use"],
    },
    {
        "path": "packages/prompt-intelligence/src/llm_orchestrator/pass5_final_output.py",
        "needles": ["mutation_transaction_contract", "structured_output=mutation_transaction_contract()"],
    },
    {
        "path": "packages/inference/src/telemetry_pipeline.py",
        "needles": [
            "structured_output_requested",
            "structured_output_enforced",
            "structured_output_schema_hash",
            "structured_output_quarantined",
        ],
    },
    {
        "path": "packages/inference/tests/test_structured_output_constraints.py",
        "needles": [
            "test_openai_request_uses_json_schema_response_format",
            "test_google_request_uses_json_mime_and_response_schema",
            "test_anthropic_request_forces_structured_tool_choice",
            "test_unsupported_provider_uses_repair_quarantine_and_schema_retry",
        ],
    },
]


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    findings: list[dict[str, object]] = []
    checks: list[dict[str, object]] = []

    for spec in CHECKS:
        rel = spec["path"]
        path = REPO_ROOT / str(rel)
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        missing = [needle for needle in spec["needles"] if needle not in text]
        checks.append({
            "path": rel,
            "status": "pass" if not missing else "fail",
            "missing": missing,
        })
        for needle in missing:
            findings.append({
                "path": rel,
                "missing": needle,
            })

    report = {
        "schema": REPORT_SCHEMA,
        "status": "pass" if not findings else "fail",
        "checks": checks,
        "findings": findings,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    if findings:
        print("provider structured output check failed:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding['path']}: missing {finding['missing']}", file=sys.stderr)
        return 1
    print(f"provider structured output check PASSED: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
