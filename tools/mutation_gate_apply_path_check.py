"""
Validate that MutationGate has one real apply implementation.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
MUTATION_GATE_PATH = REPO_ROOT / "packages" / "runtime-core" / "src" / "mutation_gate" / "mutation_gate.rs"


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


def _body_after_signature(source: str, signature: str) -> str:
    start = source.find(signature)
    if start < 0:
        return ""
    open_brace = source.find("{", start)
    if open_brace < 0:
        return ""
    depth = 0
    for index in range(open_brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[open_brace + 1 : index]
    return ""


def run(root: Path = REPO_ROOT) -> dict[str, Any]:
    path = root / MUTATION_GATE_PATH.relative_to(REPO_ROOT)
    source = path.read_text(encoding="utf-8")

    apply_body = _body_after_signature(source, "pub fn apply_all(")
    runtime_body = _body_after_signature(source, "pub fn apply_all_with_runtime_state(")

    checks = [
        CheckResult(
            "no unreachable-code allowance",
            "#[allow(unreachable_code)]" not in source,
            "MutationGate must not hide old apply code behind unreachable-code allowance.",
        ),
        CheckResult(
            "no early return to old wrapper",
            "return self.apply_all_with_runtime_state" not in source,
            "apply_all must be an ordinary wrapper around the canonical transaction function.",
        ),
        CheckResult(
            "no disabled legacy body marker",
            "removed_legacy_apply_body_marker" not in source and "#[cfg(any())]" not in source,
            "The old apply body must be removed, not disabled.",
        ),
        CheckResult(
            "one transaction implementation",
            source.count("fn apply_all_transaction(") == 1,
            "There must be exactly one private apply implementation.",
        ),
        CheckResult(
            "one state-delta construction site",
            source.count("let mut delta = StateDelta::empty") == 1,
            "Only the canonical transaction implementation may build the StateDelta.",
        ),
        CheckResult(
            "public apply delegates",
            bool(apply_body)
            and "self.apply_all_transaction(" in apply_body
            and "StateDelta::empty" not in apply_body
            and "rollback_after_failure" not in apply_body,
            "apply_all must delegate without carrying apply logic.",
        ),
        CheckResult(
            "runtime-state apply delegates",
            bool(runtime_body)
            and "self.apply_all_transaction(" in runtime_body
            and "StateDelta::empty" not in runtime_body
            and "rollback_after_failure" not in runtime_body,
            "apply_all_with_runtime_state must delegate without carrying apply logic.",
        ),
        CheckResult(
            "queue discard only exposed as explicit API",
            source.count("self.queues.discard_all();") == 1,
            "Apply-time failure must restore queues through rollback, not discard them.",
        ),
    ]

    return {
        "schema": "xace.mutation_gate_apply_path_check.v1",
        "path": str(path.relative_to(root)).replace("\\", "/"),
        "ok": all(check.passed for check in checks),
        "checks": [check.__dict__ for check in checks],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the MutationGate apply path shape.")
    parser.add_argument("--root", default=str(REPO_ROOT), help="Repository root.")
    parser.add_argument("--json", action="store_true", help="Emit the report as JSON.")
    args = parser.parse_args(argv)

    report = run(Path(args.root).resolve())
    if args.json:
        print(json.dumps(report, indent=2))
    elif report["ok"]:
        print("mutation gate apply path check PASSED")
    else:
        print("mutation gate apply path check FAILED", file=sys.stderr)
        for check in report["checks"]:
            if not check["passed"]:
                print(f"- {check['name']}: {check['detail']}", file=sys.stderr)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
