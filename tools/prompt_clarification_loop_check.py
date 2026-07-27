"""
Validate the Task 37 prompt clarification loop.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = REPO_ROOT / "packages" / "builder-workspace" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from prompt_classifier_gate import classify_prompt  # noqa: E402
from session_manager import BuilderSession, SessionManager  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the Task 37 prompt clarification loop.")
    parser.add_argument("--json", action="store_true", help="Emit a JSON report.")
    args = parser.parse_args(argv)

    findings = run()
    report = {
        "schema": "xace.prompt_clarification_loop_check.v1",
        "ok": not findings,
        "findings": findings,
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif findings:
        print("prompt clarification loop check failed:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
    else:
        print("prompt clarification loop check PASSED")
    return 1 if findings else 0


def run() -> list[str]:
    findings: list[str] = []
    sm = SessionManager()
    session_id = "clarification-check"
    sm._sessions[session_id] = BuilderSession(session_id=session_id, pipeline=None, gde=None)

    classifier = classify_prompt("Make enemies harder.")
    if classifier.category_id != "clarification_required":
        findings.append(f"ambiguous prompt classified as {classifier.category_id}, not clarification_required")
        return findings

    result = sm.start_prompt_clarification(session_id, "Make enemies harder.", classifier)
    session = sm._sessions[session_id]
    clar_id = str(result.get("clarification_session_id") or "")
    if not clar_id.startswith("prompt-clar-"):
        findings.append("prompt clarification result does not expose a prompt-clar-* session id")
    if session.pending_txn is not None:
        findings.append("start_prompt_clarification left a pending mutation transaction")
    if not session.pending_prompt_clarification:
        findings.append("start_prompt_clarification did not record a pending clarification session")
    if not result.get("resolution_required_before_mutation"):
        findings.append("clarification result does not declare resolution_required_before_mutation")

    invalid_ack = sm.submit_prompt_clarification_answer(session_id, clar_id, "unlisted option")
    if not invalid_ack or invalid_ack.get("accepted"):
        findings.append("unlisted clarification answer was accepted")

    question = result["questions"][0]
    answer = question["options"][0]
    ack = sm.submit_prompt_clarification_answer(session_id, clar_id, answer)
    if not ack or not ack.get("accepted"):
        findings.append("listed clarification answer was not accepted")
    elif not ack.get("clarification_result"):
        findings.append("accepted clarification answer did not include clarification_result")
    elif ack["clarification_result"].get("mutation_generation_allowed") is not False:
        findings.append("clarification answer incorrectly allows immediate mutation generation")
    if session.pending_txn is not None:
        findings.append("accepted clarification answer created a pending mutation transaction")
    if session.pending_prompt_clarification is not None:
        findings.append("accepted clarification answer did not clear the pending clarification session")
    if not session.prompt_clarification_log:
        findings.append("accepted clarification answer was not recorded in prompt_clarification_log")

    router_text = (SERVER_DIR / "ws_message_router.py").read_text(encoding="utf-8")
    if "start_prompt_clarification" not in router_text:
        findings.append("WSMessageRouter does not start classifier clarification sessions")
    if "submit_prompt_clarification_answer" not in router_text:
        findings.append("WSMessageRouter does not resolve classifier clarification answers before PIL answers")
    if "PROMPT_CLARIFICATION_REQUIRED" not in router_text:
        findings.append("WSMessageRouter does not block pil_apply while prompt clarification is pending")
    return findings


if __name__ == "__main__":
    raise SystemExit(main())
