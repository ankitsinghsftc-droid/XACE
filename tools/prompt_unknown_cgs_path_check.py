#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_SCHEMA = "xace.prompt_unknown_cgs_path_report.v1"
DEFAULT_OUTPUT = REPO_ROOT / "target-prompt-unknown-cgs-path" / "prompt_unknown_cgs_path_report.json"
CORPUS_PATH = REPO_ROOT / "docs" / "prompt_corpus_100.jsonl"
UNKNOWN_PATH = "modes.mode_default.actors.actor_zombie.components.5.defaults.max_linear_speed"


def _configure_imports() -> None:
    src_root = REPO_ROOT / "packages" / "prompt-intelligence" / "src"
    for subdir in (
        "output_parser",
        "validation_loop",
        "llm_orchestrator",
        "context_assembler",
        "intent_intake",
    ):
        sys.path.insert(0, str(src_root / subdir))


def _fixture_cgs() -> dict[str, Any]:
    return {
        "metadata": {
            "name": "Zombie Chase",
            "cgs_hash": "task26",
            "version": "0.1.0",
            "schema_version": "0.1.0",
        },
        "global_systems": [
            {
                "id": "InputSystem",
                "phase": "Simulation",
                "reads": [6],
                "writes": [5],
                "depends_on": [],
                "deterministic": True,
            }
        ],
        "modes": [
            {
                "id": "mode_default",
                "is_default": True,
                "actors": [
                    {
                        "id": "actor_zombie",
                        "actor_type": "Enemy",
                        "control_type": "AiProxy",
                        "components": [
                            {
                                "type_id": 5,
                                "name": "COMP_VELOCITY_V1",
                                "defaults": {
                                    "max_linear_speed": 10.0,
                                    "max_angular_speed": 360.0,
                                },
                            }
                        ],
                    }
                ],
                "systems": [
                    {
                        "id": "MovementSystem",
                        "phase": "Simulation",
                        "reads": [5],
                        "writes": [1],
                        "depends_on": ["InputSystem"],
                        "deterministic": True,
                    }
                ],
                "rules": [],
            }
        ],
    }


def _raw_mutation(path: str) -> str:
    return json.dumps(
        {
            "schema_delta_type": "value_mutation",
            "operations": [
                {
                    "path": path,
                    "op": "SET",
                    "value": 12.0,
                    "type_hint": "float",
                    "field_name": "max_linear_speed",
                    "actor_id": "actor_zombie",
                    "type_id": 5,
                }
            ],
            "confidence": 0.91,
        }
    )


def _load_corpus() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(CORPUS_PATH.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if isinstance(row, dict):
            row["_line_number"] = line_number
            rows.append(row)
    return rows


def _run_behavior_checks() -> tuple[list[dict[str, Any]], list[str]]:
    _configure_imports()
    from schema_path_validator import SchemaPathValidator
    from structured_output_parser import StructuredOutputParser
    from validation_loop import ValidationLoop

    cgs = _fixture_cgs()
    checks: list[dict[str, Any]] = []
    findings: list[str] = []

    path_result = SchemaPathValidator().validate([UNKNOWN_PATH], cgs)
    checks.append(
        {
            "name": "schema_path_validator_unknown_path",
            "passed": (
                not path_result.valid
                and path_result.unknown_paths == (UNKNOWN_PATH,)
                and any("production mutation" in reason for reason in path_result.reasons)
            ),
            "unknown_paths": list(path_result.unknown_paths),
            "reasons": list(path_result.reasons),
        }
    )

    canonical = StructuredOutputParser().parse(_raw_mutation(UNKNOWN_PATH), cgs)
    checks.append(
        {
            "name": "structured_output_parser_marks_invalid",
            "passed": (
                not canonical.is_fully_valid
                and not canonical.path_validation.valid
                and canonical.path_validation.unknown_paths == (UNKNOWN_PATH,)
            ),
            "path_validation_valid": canonical.path_validation.valid,
            "is_fully_valid": canonical.is_fully_valid,
        }
    )

    validation = ValidationLoop().validate(canonical, cgs)
    structural = validation.layer_results.get("structural")
    checks.append(
        {
            "name": "validation_loop_blocks_before_apply",
            "passed": (
                not validation.passed
                and validation.proposed_cgs is None
                and structural is not None
                and bool(structural.errors)
                and not structural.warnings
            ),
            "validation_passed": validation.passed,
            "proposed_cgs_written": validation.proposed_cgs is not None,
            "structural_errors": list(structural.errors) if structural else [],
            "structural_warnings": list(structural.warnings) if structural else [],
        }
    )

    for check in checks:
        if not check["passed"]:
            findings.append(f"behavior check failed: {check['name']}")
    return checks, findings


def _run_corpus_check() -> tuple[dict[str, Any], list[str]]:
    findings: list[str] = []
    rows = _load_corpus()
    matches = [
        row
        for row in rows
        if isinstance(row.get("x10_026_adversarial_case"), dict)
        and row["x10_026_adversarial_case"].get("parser_path") == UNKNOWN_PATH
        and row["x10_026_adversarial_case"].get("expected_production_apply")
        == "blocked_unknown_cgs_path"
    ]
    if not matches:
        findings.append("prompt corpus missing X10-026 adversarial unknown CGS path case")
    else:
        for row in matches:
            if row.get("difficulty_band") != "adversarial":
                findings.append(f"{row.get('prompt_id')}: X10-026 case must use adversarial difficulty")
            if row.get("expected_result_kind") != "blocked":
                findings.append(f"{row.get('prompt_id')}: X10-026 case must expect blocked result")
            if row.get("category_id") not in {"blocked", "unsupported"}:
                findings.append(f"{row.get('prompt_id')}: X10-026 case must use blocked/unsupported category")

    corpus_check = {
        "case_count": len(rows),
        "matching_prompt_ids": [str(row.get("prompt_id")) for row in matches],
        "unknown_path": UNKNOWN_PATH,
    }
    return corpus_check, findings


def run() -> dict[str, Any]:
    behavior_checks, behavior_findings = _run_behavior_checks()
    corpus_check, corpus_findings = _run_corpus_check()
    findings = behavior_findings + corpus_findings
    return {
        "schema": REPORT_SCHEMA,
        "status": "pass" if not findings else "fail",
        "unknown_path": UNKNOWN_PATH,
        "behavior_checks": behavior_checks,
        "corpus_check": corpus_check,
        "findings": findings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate X10-026 unknown CGS path hard failures.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Report JSON output path.")
    parser.add_argument("--json", action="store_true", help="Print the full report JSON.")
    args = parser.parse_args(argv)

    report = run()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif report["findings"]:
        print("prompt unknown CGS path check failed:", file=sys.stderr)
        for finding in report["findings"]:
            print(f"- {finding}", file=sys.stderr)
    else:
        print(f"prompt unknown CGS path check PASSED: {output}")
    return 1 if report["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
