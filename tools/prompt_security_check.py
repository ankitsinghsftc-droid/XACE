"""
Validate Task 50 prompt security cases and write proof artifacts.

This checker is deterministic and local-only. It exercises the real Builder
prompt classifier for prompt-level attacks, then applies narrow quarantine
validators for model-response, mutation, capability, and CGS-fragment payloads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = REPO_ROOT / "packages" / "builder-workspace" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from prompt_classifier_gate import RESULT_SCHEMA, classify_prompt  # noqa: E402
from prompt_capability_matrix import load_prompt_capability_matrix  # noqa: E402


CASES_PATH = REPO_ROOT / "docs" / "prompt_security_cases.jsonl"
DEFAULT_ARTIFACT_DIR = REPO_ROOT / "target-prompt-security"
CASE_SCHEMA = "xace.prompt_security_case.v1"
CASE_RESULT_SCHEMA = "xace.prompt_security_case_result.v1"
REPORT_SCHEMA = "xace.prompt_security_report.v1"
REQUIRED_ATTACK_TYPES = {
    "prompt_injection",
    "adversarial_instructions",
    "malformed_model_response",
    "unsafe_mutation",
    "hallucinated_capability",
    "schema_corruption",
    "secret_exfiltration",
}
BLOCKING_CATEGORIES = {"blocked", "unsupported"}
FORBIDDEN_MUTATION_OPS = {
    "delete_file",
    "exec",
    "http_request",
    "network_call",
    "read_file",
    "shell",
    "upload",
    "write_file",
}
FORBIDDEN_TEXT_FRAGMENTS = (
    "../",
    "..\\",
    ".env",
    "api key",
    "cmd.exe",
    "curl ",
    "environment secret",
    "powershell",
    "subprocess",
)


@dataclass
class CaseResult:
    case_id: str
    attack_type: str
    surface: str
    status: str
    expected_outcome: str
    reasons: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    finding: str = ""

    @property
    def ok(self) -> bool:
        return not self.finding and self.status in {"blocked", "quarantined"} and self.status == self.expected_outcome

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CASE_RESULT_SCHEMA,
            "case_id": self.case_id,
            "attack_type": self.attack_type,
            "surface": self.surface,
            "status": self.status,
            "expected_outcome": self.expected_outcome,
            "ok": self.ok,
            "reasons": self.reasons,
            "evidence": self.evidence,
            "finding": self.finding,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate prompt security attack cases.")
    parser.add_argument("--cases", default=str(CASES_PATH), help="JSONL prompt security case file.")
    parser.add_argument("--artifact-dir", default=str(DEFAULT_ARTIFACT_DIR), help="Directory for proof artifacts.")
    parser.add_argument("--json", action="store_true", help="Emit the JSON report.")
    args = parser.parse_args(argv)

    report = run(Path(args.cases), Path(args.artifact_dir))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif report["ok"]:
        print(f"prompt security check PASSED: {report['case_count']} attack cases blocked or quarantined")
    else:
        print("prompt security check failed:", file=sys.stderr)
        for finding in report["findings"]:
            print(f"- {finding}", file=sys.stderr)
    return 0 if report["ok"] else 1


def run(cases_path: Path, artifact_dir: Path) -> dict[str, Any]:
    cases_path = _resolve(cases_path)
    artifact_dir = _resolve(artifact_dir)
    findings: list[str] = []
    cases = _load_cases(cases_path, findings)
    results: list[CaseResult] = []
    matrix = _load_matrix(findings)
    supported_capabilities = _supported_capabilities(matrix)

    if cases:
        findings.extend(_validate_case_set(cases))
        for case in cases:
            results.append(_run_case(case, supported_capabilities))

    for result in results:
        if not result.ok:
            detail = result.finding or f"{result.case_id} produced {result.status}, expected {result.expected_outcome}"
            findings.append(detail)

    attack_counts: dict[str, int] = {}
    for result in results:
        attack_counts[result.attack_type] = attack_counts.get(result.attack_type, 0) + 1

    artifact_dir.mkdir(parents=True, exist_ok=True)
    result_rows_path = artifact_dir / "prompt_security_cases.jsonl"
    report_path = artifact_dir / "prompt_security_report.json"
    markdown_path = artifact_dir / "prompt_security_report.md"
    _write_jsonl(result_rows_path, [result.to_dict() for result in results])

    report = {
        "schema": REPORT_SCHEMA,
        "ok": not findings,
        "case_count": len(results),
        "blocked_count": sum(1 for result in results if result.status == "blocked"),
        "quarantined_count": sum(1 for result in results if result.status == "quarantined"),
        "failed_count": sum(1 for result in results if not result.ok),
        "attack_type_counts": dict(sorted(attack_counts.items())),
        "required_attack_types": sorted(REQUIRED_ATTACK_TYPES),
        "cases_sha256": _sha256(cases_path),
        "provider_calls": 0,
        "mutations_allowed": 0,
        "security_scope": (
            "Deterministic local coverage for prompt injection, adversarial instructions, "
            "malformed model responses, unsafe mutations, hallucinated capabilities, schema "
            "corruption, and secret exfiltration cases."
        ),
        "artifacts": {
            "case_results": _display(result_rows_path),
            "report_json": _display(report_path),
            "report_markdown": _display(markdown_path),
        },
        "findings": findings,
        "results": [result.to_dict() for result in results],
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return report


def _run_case(case: dict[str, Any], supported_capabilities: set[str]) -> CaseResult:
    surface = str(case.get("surface") or "")
    if surface == "prompt_classifier":
        return _run_prompt_classifier_case(case)
    if surface == "model_response_validator":
        return _run_model_response_case(case)
    if surface == "mutation_validator":
        return _run_mutation_case(case)
    if surface == "capability_validator":
        return _run_capability_case(case, supported_capabilities)
    if surface == "cgs_fragment_validator":
        return _run_cgs_fragment_case(case)
    return _failure_result(case, "unsupported test surface")


def _run_prompt_classifier_case(case: dict[str, Any]) -> CaseResult:
    prompt = str((case.get("input") or {}).get("prompt") or "")
    classifier = classify_prompt(prompt)
    payload = classifier.to_dict()
    reasons: list[str] = []
    status = "blocked" if classifier.category_id in BLOCKING_CATEGORIES and not classifier.provider_call_allowed and not classifier.mutation_allowed else "failed"
    if payload.get("schema") != RESULT_SCHEMA:
        reasons.append("classifier_schema_mismatch")
    expected_category = str(case.get("expected_category") or "")
    if expected_category and classifier.category_id != expected_category:
        reasons.append("category_mismatch")
    expected_signals = {str(signal) for signal in case.get("expected_signals", [])}
    signals = set(classifier.signals)
    if not expected_signals.issubset(signals):
        reasons.append("signal_mismatch")
    if classifier.provider_call_allowed:
        reasons.append("provider_call_allowed")
    if classifier.mutation_allowed:
        reasons.append("mutation_allowed")

    finding = ""
    if status != str(case.get("expected_outcome")) or reasons:
        finding = f"{case.get('id')}: classifier did not block safely ({', '.join(reasons) or status})"
    return CaseResult(
        case_id=str(case.get("id") or ""),
        attack_type=str(case.get("attack_type") or ""),
        surface=str(case.get("surface") or ""),
        status=status,
        expected_outcome=str(case.get("expected_outcome") or ""),
        reasons=reasons or ["classifier_blocked_before_provider_or_mutation"],
        evidence={
            "category_id": classifier.category_id,
            "route": classifier.route,
            "signals": sorted(signals),
            "provider_call_allowed": classifier.provider_call_allowed,
            "mutation_allowed": classifier.mutation_allowed,
            "classifier_schema": payload.get("schema"),
        },
        finding=finding,
    )


def _run_model_response_case(case: dict[str, Any]) -> CaseResult:
    text = str((case.get("input") or {}).get("response_text") or "")
    reason = _validate_model_response(text)
    return _quarantine_result(case, reason)


def _run_mutation_case(case: dict[str, Any]) -> CaseResult:
    mutation = (case.get("input") or {}).get("mutation")
    reason = _validate_mutation(mutation)
    return _quarantine_result(case, reason)


def _run_capability_case(case: dict[str, Any], supported_capabilities: set[str]) -> CaseResult:
    capability_id = str((case.get("input") or {}).get("capability_id") or "")
    reason = "" if capability_id in supported_capabilities else "unsupported_capability"
    return _quarantine_result(case, reason, evidence={"capability_id": capability_id})


def _run_cgs_fragment_case(case: dict[str, Any]) -> CaseResult:
    fragment = (case.get("input") or {}).get("cgs_fragment")
    reason = _validate_cgs_fragment(fragment)
    return _quarantine_result(case, reason)


def _quarantine_result(case: dict[str, Any], reason: str, *, evidence: dict[str, Any] | None = None) -> CaseResult:
    expected_reason = str(case.get("expected_reason") or "")
    reasons = [reason] if reason else ["payload_allowed"]
    finding = ""
    status = "quarantined" if reason else "failed"
    if status != str(case.get("expected_outcome")):
        finding = f"{case.get('id')}: expected quarantine but payload was not quarantined"
    elif expected_reason and reason != expected_reason:
        finding = f"{case.get('id')}: expected reason {expected_reason}, got {reason}"
    return CaseResult(
        case_id=str(case.get("id") or ""),
        attack_type=str(case.get("attack_type") or ""),
        surface=str(case.get("surface") or ""),
        status=status,
        expected_outcome=str(case.get("expected_outcome") or ""),
        reasons=reasons,
        evidence={
            "provider_call_allowed": False,
            "mutation_allowed": False,
            **(evidence or {}),
        },
        finding=finding,
    )


def _failure_result(case: dict[str, Any], reason: str) -> CaseResult:
    return CaseResult(
        case_id=str(case.get("id") or ""),
        attack_type=str(case.get("attack_type") or ""),
        surface=str(case.get("surface") or ""),
        status="failed",
        expected_outcome=str(case.get("expected_outcome") or ""),
        reasons=[reason],
        finding=f"{case.get('id')}: {reason}",
    )


def _validate_model_response(text: str) -> str:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return "invalid_json"
    if not isinstance(payload, dict):
        return "non_object_response"
    kind = payload.get("kind")
    schema = payload.get("schema")
    if not isinstance(schema, str) or not isinstance(kind, str):
        return "missing_schema_or_kind"
    if kind not in {"mutation", "clarification", "blocked"}:
        return "unknown_response_kind"
    if kind == "mutation" and not isinstance(payload.get("transaction"), dict):
        return "mutation_missing_transaction"
    return ""


def _validate_mutation(mutation: Any) -> str:
    if not isinstance(mutation, dict):
        return "mutation_not_object"
    ops = mutation.get("ops")
    if not isinstance(ops, list) or not ops:
        return "mutation_ops_missing"
    for op in ops:
        if not isinstance(op, dict):
            return "mutation_op_not_object"
        op_name = str(op.get("op") or "").lower()
        if op_name in FORBIDDEN_MUTATION_OPS:
            return "forbidden_mutation_op"
        if _contains_forbidden_text(op):
            return "forbidden_mutation_payload"
    return ""


def _validate_cgs_fragment(fragment: Any) -> str:
    if not isinstance(fragment, dict):
        return "fragment_not_object"
    if fragment.get("schema") != "xace.cgs.fragment.v1":
        return "schema_mismatch"
    entity_id = fragment.get("entity_id")
    if not isinstance(entity_id, str) or not entity_id.strip():
        return "missing_entity_id"
    components = fragment.get("components")
    if not isinstance(components, list):
        return "components_not_list"
    seen: set[str] = set()
    for component in components:
        if not isinstance(component, dict):
            return "component_not_object"
        component_id = component.get("id")
        component_type = component.get("type")
        if not isinstance(component_id, str) or not isinstance(component_type, str):
            return "component_missing_identity"
        if component_id in seen:
            return "duplicate_component_id"
        seen.add(component_id)
    declared_hash = fragment.get("declared_hash")
    if declared_hash is not None and declared_hash != _canonical_hash({k: v for k, v in fragment.items() if k != "declared_hash"}):
        return "declared_hash_mismatch"
    return ""


def _contains_forbidden_text(value: Any) -> bool:
    if isinstance(value, str):
        lowered = value.lower()
        return any(fragment in lowered for fragment in FORBIDDEN_TEXT_FRAGMENTS)
    if isinstance(value, dict):
        return any(_contains_forbidden_text(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_forbidden_text(item) for item in value)
    return False


def _supported_capabilities(matrix: dict[str, Any] | None) -> set[str]:
    supported: set[str] = set()
    if not matrix:
        return supported
    for category in matrix.get("categories", []):
        if not isinstance(category, dict):
            continue
        category_id = str(category.get("id") or "")
        if category_id not in {"certified_supported", "constrained"}:
            continue
        for example in category.get("examples", []):
            if isinstance(example, dict) and example.get("id"):
                supported.add(f"{category_id}.{example['id']}")
                supported.add(str(example["id"]))
    return supported


def _load_cases(path: Path, findings: list[str]) -> list[dict[str, Any]]:
    if not path.exists():
        findings.append(f"missing prompt security cases file: {_display(path)}")
        return []
    cases: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            case = json.loads(raw)
        except json.JSONDecodeError as exc:
            findings.append(f"{_display(path)}:{line_number}: invalid JSONL: {exc}")
            continue
        if not isinstance(case, dict):
            findings.append(f"{_display(path)}:{line_number}: case must be a JSON object")
            continue
        cases.append(case)
    return cases


def _load_matrix(findings: list[str]) -> dict[str, Any] | None:
    try:
        return load_prompt_capability_matrix()
    except Exception as exc:  # noqa: BLE001
        findings.append(f"cannot load prompt capability matrix: {exc}")
        return None


def _validate_case_set(cases: list[dict[str, Any]]) -> list[str]:
    findings: list[str] = []
    seen_ids: set[str] = set()
    attack_types: set[str] = set()
    for case in cases:
        case_id = str(case.get("id") or "")
        if case.get("schema") != CASE_SCHEMA:
            findings.append(f"{case_id or '<missing id>'}: schema must be {CASE_SCHEMA}")
        if not case_id:
            findings.append("prompt security case missing id")
        elif case_id in seen_ids:
            findings.append(f"{case_id}: duplicate case id")
        seen_ids.add(case_id)
        attack_type = str(case.get("attack_type") or "")
        attack_types.add(attack_type)
        if attack_type not in REQUIRED_ATTACK_TYPES:
            findings.append(f"{case_id}: unsupported attack_type {attack_type}")
        if str(case.get("expected_outcome") or "") not in {"blocked", "quarantined"}:
            findings.append(f"{case_id}: expected_outcome must be blocked or quarantined")
        if not isinstance(case.get("input"), dict):
            findings.append(f"{case_id}: input must be an object")
    missing = REQUIRED_ATTACK_TYPES - attack_types
    for attack_type in sorted(missing):
        findings.append(f"missing required attack type: {attack_type}")
    return findings


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def _render_markdown(report: dict[str, Any]) -> str:
    rows = [
        "# Prompt Security Report",
        "",
        f"Schema: `{report['schema']}`",
        "",
        f"Status: {'PASS' if report['ok'] else 'FAIL'}",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Cases | {report['case_count']} |",
        f"| Blocked | {report['blocked_count']} |",
        f"| Quarantined | {report['quarantined_count']} |",
        f"| Failed | {report['failed_count']} |",
        f"| Provider calls | {report['provider_calls']} |",
        f"| Mutations allowed | {report['mutations_allowed']} |",
        "",
        "## Cases",
        "",
        "| Case | Attack | Surface | Status | Reasons |",
        "| --- | --- | --- | --- | --- |",
    ]
    for result in report["results"]:
        rows.append(
            "| {case_id} | {attack_type} | {surface} | {status} | {reasons} |".format(
                case_id=result["case_id"],
                attack_type=result["attack_type"],
                surface=result["surface"],
                status=result["status"],
                reasons=", ".join(result["reasons"]),
            )
        )
    if report["findings"]:
        rows.extend(["", "## Findings", ""])
        rows.extend(f"- {finding}" for finding in report["findings"])
    return "\n".join(rows) + "\n"


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def _display(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
