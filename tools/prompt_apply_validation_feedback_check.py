"""
Validate the Task 45 prompt apply validation feedback gate.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = REPO_ROOT / "packages" / "builder-workspace" / "server"
BUILDER_SRC = REPO_ROOT / "packages" / "builder-workspace" / "src"
TEST_PATH = "packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Task 45 prompt apply validation feedback.")
    parser.add_argument("--json", action="store_true", help="Emit a JSON report.")
    args = parser.parse_args(argv)

    findings = run()
    report = {
        "schema": "xace.prompt_apply_validation_feedback_check.v1",
        "ok": not findings,
        "findings": findings,
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif findings:
        print("prompt apply validation feedback check failed:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
    else:
        print("prompt apply validation feedback check PASSED")
    return 1 if findings else 0


def run() -> list[str]:
    findings: list[str] = []
    findings.extend(_static_findings())
    findings.extend(_test_findings())
    return findings


def _static_findings() -> list[str]:
    findings: list[str] = []
    router_text = (SERVER_DIR / "ws_message_router.py").read_text(encoding="utf-8")
    session_text = (SERVER_DIR / "session_manager.py").read_text(encoding="utf-8")
    pil_types_text = (BUILDER_SRC / "types" / "pil.ts").read_text(encoding="utf-8")
    message_types_text = (BUILDER_SRC / "api" / "message_types.ts").read_text(encoding="utf-8")
    state_machine_text = (BUILDER_SRC / "state" / "console_state_machine.ts").read_text(encoding="utf-8")
    client_text = (BUILDER_SRC / "api" / "builder_client.ts").read_text(encoding="utf-8")
    processing_view_text = (BUILDER_SRC / "views" / "processing_view.ts").read_text(encoding="utf-8")
    test_text = (REPO_ROOT / TEST_PATH).read_text(encoding="utf-8")

    for needle in (
        "xace.prompt_apply_feedback.v1",
        "_prompt_apply_feedback",
        '"classifier"',
        '"runtime_load"',
        '"proof_links"',
        '"apply_feedback"',
        "PromptApplyRecoveryError",
    ):
        if needle not in router_text:
            findings.append(f"ws_message_router.py missing {needle}")

    for needle in ("pending_prompt_result", "pending_prompt_preview"):
        if needle not in session_text:
            findings.append(f"session_manager.py missing {needle}")

    for needle in ("PromptApplyFeedback", "PromptApplyFeedbackSection"):
        if needle not in pil_types_text:
            findings.append(f"types/pil.ts missing {needle}")

    for needle in ("apply_feedback?: PromptApplyFeedback", "ServerErrorMessage", "CgsUpdateMessage"):
        if needle not in message_types_text:
            findings.append(f"message_types.ts missing {needle}")

    for needle in ("ApplyingMutation", "completeApply", "receiveServerError", "applyFeedback"):
        if needle not in state_machine_text:
            findings.append(f"console_state_machine.ts missing {needle}")

    for needle in ("consoleSM.completeApply", "consoleSM.receiveServerError", "message.apply_feedback"):
        if needle not in client_text:
            findings.append(f"builder_client.ts missing {needle}")

    for needle in ("_appendApplyFeedback", "runtime_load", "proof_links"):
        if needle not in processing_view_text:
            findings.append(f"processing_view.ts missing {needle}")

    for needle in (
        "test_prompt_apply_validation_feedback_success_includes_full_contract",
        "test_prompt_apply_validation_feedback_sgc_failure_is_not_generic",
        "test_prompt_apply_validation_feedback_runtime_rollback_includes_partial_report",
        "_assert_apply_feedback_contract",
    ):
        if needle not in test_text:
            findings.append(f"prompt pipeline e2e tests missing {needle}")
    return findings


def _test_findings() -> list[str]:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "unittest",
            TEST_PATH,
            "-k",
            "validation_feedback",
        ],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=180,
        check=False,
    )
    if completed.returncode == 0:
        return []
    tail = completed.stdout[-4000:] if completed.stdout else ""
    return [f"validation feedback e2e tests failed with exit {completed.returncode}:\n{tail}"]


if __name__ == "__main__":
    raise SystemExit(main())
