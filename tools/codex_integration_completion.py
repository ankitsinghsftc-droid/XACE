"""AG-030 Codex-only completion gate with source-bound live evidence.

Runs local engineering checks only: no login, account probe or model turn.
Passing fixtures cannot certify a real runtime/account. Completion requires
current AG-029 artifacts and an accountable residual-risk review; no force flag.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
from codex_completion_evidence import validate_evidence

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "packages" / "builder-workspace"
SCHEMA = "xace.codex_integration_completion.v1"
REQUIRED_CHECKS = (
    "agent_implementation", "builder_regression", "setup_support_browser",
    "builder_build", "api_byok_regression", "handoff_documentation",
)
REQUIRED_DOCS = (
    "docs/CODEX_INTEGRATION_HANDOFF.md", "docs/AGENT_SETUP_UX.md",
    "docs/CODEX_RUNTIME_GUIDE.md", "docs/CODEX_AUTH_LIFECYCLE.md",
    "docs/CODEX_COMPATIBILITY_RESILIENCE.md", "docs/AGENT_PRIVACY_SUPPORT.md",
)


def completion_report(checks: list[dict], *, root: Path = ROOT) -> dict:
    """Normalize local results; never inherit an older gate's shipping decision."""
    normalized = []
    for identifier in REQUIRED_CHECKS:
        matches = [item for item in checks if item.get("check_id") == identifier]
        passed = len(matches) == 1 and matches[0].get("status") == "pass"
        normalized.append({"check_id": identifier, "status": "pass" if passed else "fail"})
    engineering_ok = all(item["status"] == "pass" for item in normalized)
    blockers = [item["check_id"] for item in normalized if item["status"] != "pass"]
    evidence = validate_evidence(root)
    blockers.extend(evidence['blockers'])
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "codex_integration_only",
        "engineering_checks_passed": engineering_ok,
        "checks": normalized,
        "codex_integration_complete": not blockers,
        "decision": "complete_for_declared_configuration" if not blockers else "blocked_pending_certification" if engineering_ok else "blocked_engineering_and_certification",
        "blockers": blockers,
        "certified_runtime_account_configurations": evidence["configurations"] if not blockers else [],
        "ag029_evidence_status": "rejected" if any(b.startswith("ag029_") for b in evidence["blockers"]) else "validated",
        "defect_review": "reviewed" if not evidence["blockers"] else "pending_no_zero_defect_claim",
        "whole_xace_launch_readiness": "outside_scope",
        "default_and_fallback": "API_BYOK",
        "claude_local_required": False,
        "provider_calls_performed": False,
        "handoff": REQUIRED_DOCS[0],
    }


def run_check(identifier: str, command: list[str], cwd: Path) -> dict:
    # Fixed maintainer commands, not provider/user-generated commands. Never
    # persist raw subprocess output in the completion report or support bundle.
    try:
        result = subprocess.run(command, cwd=cwd, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=900, check=False)
        status = "pass" if result.returncode == 0 else "fail"
    except (OSError, subprocess.TimeoutExpired):
        status = "fail"
    return {"check_id": identifier, "status": status}


def build_report(output: Path) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    npm = shutil.which("npm.cmd") or shutil.which("npm") or "npm"
    commands = (
        ("agent_implementation", [sys.executable, "tools/agent_mode_production_readiness.py",
                                  "--output", str(output.parent / "implementation.json")], ROOT),
        ("builder_regression", [npm, "test"], BUILDER),
        ("setup_support_browser", [npm, "run", "test:agent-setup"], BUILDER),
        ("builder_build", [npm, "run", "build"], BUILDER),
        ("api_byok_regression", [sys.executable, "tools/python_test_gate.py", "--suite", "inference",
                                 "--output", str(output.parent / "inference.json")], ROOT),
    )
    checks = []
    for identifier, command, cwd in commands:
        print(f"Running {identifier}...", flush=True)
        check = run_check(identifier, command, cwd)
        checks.append(check)
        print(f"{identifier}: {check['status']}", flush=True)
    checks.append({"check_id": "handoff_documentation",
                   "status": "pass" if all((ROOT / name).is_file() for name in REQUIRED_DOCS) else "fail"})
    report = completion_report(checks)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "target-codex-agent-readiness" / "completion" / "completion.json")
    args = parser.parse_args()
    report = build_report(args.output.resolve())
    print(f"Decision: {report['decision']}")
    print(f"Report: {args.output.resolve()}")
    return 0 if report["codex_integration_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
