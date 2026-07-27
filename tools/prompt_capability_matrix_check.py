"""
Validate the Task 35 prompt capability matrix across docs and Builder.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = REPO_ROOT / "packages" / "builder-workspace" / "server"
PROMPT_FIXTURE_DIR = SERVER_DIR / "tests" / "fixtures"
for path in (SERVER_DIR, PROMPT_FIXTURE_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from prompt_capability_matrix import (  # noqa: E402
    REQUIRED_CATEGORY_IDS,
    load_prompt_capability_matrix,
    prompt_capability_matrix_hash,
)
from prompt_pipeline_contract import (  # noqa: E402
    blocked_prompt_pipeline_scenario,
    supported_prompt_pipeline_scenarios,
)


DOC_PATH = REPO_ROOT / "docs" / "PROMPT_CAPABILITY_MATRIX.md"
BUILDER_SERVER_PATH = SERVER_DIR / "builder_server.py"
BUILDER_CLIENT_PATH = REPO_ROOT / "packages" / "builder-workspace" / "src" / "api" / "builder_client.ts"
BUILDER_APP_PATH = REPO_ROOT / "packages" / "builder-workspace" / "src" / "app.ts"
BUILDER_UI_STORE_PATH = REPO_ROOT / "packages" / "builder-workspace" / "src" / "state" / "ui_store.ts"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the prompt capability matrix.")
    parser.add_argument("--json", action="store_true", help="Emit the validation report as JSON.")
    args = parser.parse_args(argv)

    findings = run()
    report = {
        "schema": "xace.prompt_capability_matrix_check.v1",
        "ok": not findings,
        "findings": findings,
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif findings:
        print("prompt capability matrix check failed:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
    else:
        print("prompt capability matrix check PASSED")
    return 1 if findings else 0


def run() -> list[str]:
    findings: list[str] = []
    try:
        matrix = load_prompt_capability_matrix()
    except Exception as exc:  # noqa: BLE001 - report first actionable issue.
        return [str(exc)]

    matrix_hash = prompt_capability_matrix_hash(matrix)
    if matrix.get("matrix_hash") != matrix_hash:
        findings.append("Builder matrix_hash does not match canonical JSON hash")
    if matrix.get("category_order") != list(REQUIRED_CATEGORY_IDS):
        findings.append("category_order does not match required Task 35 order")

    categories = {category["id"]: category for category in matrix.get("categories", []) if isinstance(category, dict)}
    for category_id in REQUIRED_CATEGORY_IDS:
        category = categories.get(category_id)
        if not category:
            findings.append(f"missing category {category_id}")
            continue
        if not str(category.get("product_wording", "")).strip():
            findings.append(f"{category_id} missing product_wording")
        if not str(category.get("builder_copy", "")).strip():
            findings.append(f"{category_id} missing builder_copy")
        examples = category.get("examples")
        if not isinstance(examples, list) or len(examples) < 2:
            findings.append(f"{category_id} needs at least two examples")

    findings.extend(_validate_docs(matrix, matrix_hash))
    findings.extend(_validate_builder_wiring())
    findings.extend(_validate_prompt_contract_examples(matrix))
    return findings


def _validate_docs(matrix: dict[str, Any], matrix_hash: str) -> list[str]:
    findings: list[str] = []
    if not DOC_PATH.exists():
        return [f"missing docs page: {DOC_PATH.relative_to(REPO_ROOT)}"]
    text = DOC_PATH.read_text(encoding="utf-8")
    if f"Matrix hash: `{matrix_hash}`" not in text:
        findings.append("docs/PROMPT_CAPABILITY_MATRIX.md does not contain the canonical matrix hash")
    if "GET /api/prompt/capability-matrix" not in text:
        findings.append("docs/PROMPT_CAPABILITY_MATRIX.md does not document the Builder matrix endpoint")
    for category in matrix.get("categories", []):
        label = str(category.get("label", ""))
        wording = str(category.get("product_wording", ""))
        decision = str(category.get("builder_decision", ""))
        if label and label not in text:
            findings.append(f"docs page missing category label {label!r}")
        if wording and wording not in text:
            findings.append(f"docs page missing product wording for {category.get('id')}")
        if decision and decision not in text:
            findings.append(f"docs page missing Builder decision {decision!r}")
    return findings


def _validate_builder_wiring() -> list[str]:
    findings: list[str] = []
    server_text = BUILDER_SERVER_PATH.read_text(encoding="utf-8")
    client_text = BUILDER_CLIENT_PATH.read_text(encoding="utf-8")
    app_text = BUILDER_APP_PATH.read_text(encoding="utf-8")
    ui_store_text = BUILDER_UI_STORE_PATH.read_text(encoding="utf-8")
    if "load_prompt_capability_matrix" not in server_text:
        findings.append("Builder server does not import/use load_prompt_capability_matrix")
    if "/api/prompt/capability-matrix" not in server_text:
        findings.append("Builder server does not expose /api/prompt/capability-matrix")
    if "PromptCapabilityMatrix" not in client_text:
        findings.append("Builder client does not declare PromptCapabilityMatrix")
    if "/api/prompt/capability-matrix" not in client_text:
        findings.append("Builder client does not request /api/prompt/capability-matrix")
    if "fetchPromptCapabilityMatrix" not in app_text:
        findings.append("Builder app boot does not fetch the prompt capability matrix")
    if "setPromptCapabilityMatrix" not in ui_store_text:
        findings.append("Builder UI store does not retain the prompt capability matrix")
    return findings


def _validate_prompt_contract_examples(matrix: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    categories = {category["id"]: category for category in matrix.get("categories", []) if isinstance(category, dict)}
    certified_prompts = {
        str(example.get("prompt", ""))
        for example in categories.get("certified_supported", {}).get("examples", [])
        if isinstance(example, dict)
    }
    blocked_prompts = {
        str(example.get("prompt", ""))
        for example in categories.get("blocked", {}).get("examples", [])
        if isinstance(example, dict)
    }
    for scenario in supported_prompt_pipeline_scenarios():
        if scenario.prompt not in certified_prompts:
            findings.append(f"certified_supported examples missing prompt contract scenario {scenario.scenario_id}")
    blocked = blocked_prompt_pipeline_scenario()
    if blocked.prompt not in blocked_prompts:
        findings.append(f"blocked examples missing prompt contract scenario {blocked.scenario_id}")
    return findings


if __name__ == "__main__":
    raise SystemExit(main())
