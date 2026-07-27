"""
Validate the Task 42 prompt diff preview and approval gate.
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

from session_manager import BuilderSession, SessionManager  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Task 42 prompt diff preview approval.")
    parser.add_argument("--json", action="store_true", help="Emit a JSON report.")
    args = parser.parse_args(argv)

    findings = run()
    report = {
        "schema": "xace.prompt_diff_approval_check.v1",
        "ok": not findings,
        "findings": findings,
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif findings:
        print("prompt diff approval check failed:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
    else:
        print("prompt diff approval check PASSED")
    return 1 if findings else 0


def run() -> list[str]:
    findings: list[str] = []
    sm = SessionManager()
    session_id = "task42-check"
    session = BuilderSession(session_id=session_id, pipeline=None, gde=None)
    session.pending_prompt_preview = {
        "schema": "xace.prompt_diff_preview.v1",
        "preview_id": "preview-check",
        "approval_token": "pat-check",
        "transaction_fingerprint": "fingerprint-check",
    }
    sm._sessions[session_id] = session

    missing = sm.validate_prompt_preview_approval(session_id, {})
    if missing.get("accepted"):
        findings.append("missing preview approval was accepted")
    if missing.get("code") != "PROMPT_PREVIEW_APPROVAL_REQUIRED":
        findings.append(f"missing approval returned {missing.get('code')}, not PROMPT_PREVIEW_APPROVAL_REQUIRED")

    mismatch = sm.validate_prompt_preview_approval(session_id, {
        "approval": {"preview_id": "preview-check", "approval_token": "wrong-token"},
    })
    if mismatch.get("accepted"):
        findings.append("mismatched preview approval token was accepted")

    valid = sm.validate_prompt_preview_approval(session_id, {
        "approval": {
            "preview_id": "preview-check",
            "approval_token": "pat-check",
            "approval_source": "check",
            "approved_by": "check",
        },
    })
    if not valid.get("accepted"):
        findings.append("matching preview approval token was rejected")
    approval = valid.get("approval") if isinstance(valid.get("approval"), dict) else {}
    if approval.get("schema") != "xace.prompt_preview_approval.v1":
        findings.append("accepted approval does not use xace.prompt_preview_approval.v1")
    if not session.prompt_preview_approval_log:
        findings.append("accepted approval was not recorded in the session approval log")

    override_session_id = "task42-override-check"
    override_session = BuilderSession(session_id=override_session_id, pipeline=None, gde=None)
    override_session.pending_prompt_preview = dict(session.pending_prompt_preview)
    sm._sessions[override_session_id] = override_session
    override = sm.validate_prompt_preview_approval(override_session_id, {
        "test_mode_override": True,
        "test_mode_reason": "checker override",
    })
    if not override.get("accepted"):
        findings.append("audited test-mode override was rejected")
    override_approval = override.get("approval") if isinstance(override.get("approval"), dict) else {}
    if override_approval.get("test_mode_override") is not True:
        findings.append("test-mode override approval was not marked as test_mode_override")

    session_text = (SERVER_DIR / "session_manager.py").read_text(encoding="utf-8")
    router_text = (SERVER_DIR / "ws_message_router.py").read_text(encoding="utf-8")
    type_text = (REPO_ROOT / "packages" / "builder-workspace" / "src" / "types" / "pil.ts").read_text(encoding="utf-8")
    diff_text = (REPO_ROOT / "packages" / "builder-workspace" / "src" / "canvas" / "diff_viewer.ts").read_text(encoding="utf-8")

    for needle in (
        "xace.prompt_diff_preview.v1",
        "pending_prompt_preview",
        "validate_prompt_preview_approval",
        "xace.prompt_preview_approval.v1",
    ):
        if needle not in session_text:
            findings.append(f"session_manager.py missing {needle}")
    if "PROMPT_PREVIEW_APPROVAL_REQUIRED" not in router_text:
        findings.append("ws_message_router.py does not reject missing prompt preview approval")
    if "outcome=\"rejected_unapproved\"" not in router_text:
        findings.append("ws_message_router.py does not audit unapproved prompt applies")
    if "approval=approval_record" not in router_text:
        findings.append("ws_message_router.py does not attach approval evidence to mutation audit")
    for section in ("cgs_diff", "system_diff", "asset_diff", "sgc_diff", "runtime_diff", "cost_diff"):
        if section not in type_text:
            findings.append(f"PromptDiffPreview type missing {section}")
    for label in ("CGS", "Systems", "Assets", "SGC/Runtime", "Cost"):
        if label not in diff_text:
            findings.append(f"DiffViewer does not render {label} tab")
    return findings


if __name__ == "__main__":
    raise SystemExit(main())
