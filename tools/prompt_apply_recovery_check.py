"""
Validate the Task 44 / X10-019 prompt apply atomic rollback gate.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = REPO_ROOT / "packages" / "builder-workspace" / "server"
TEST_PATH = "packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate prompt apply atomic rollback recovery.")
    parser.add_argument("--json", action="store_true", help="Emit a JSON report.")
    args = parser.parse_args(argv)

    findings = run()
    report = {
        "schema": "xace.prompt_apply_recovery_check.v1",
        "ok": not findings,
        "findings": findings,
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif findings:
        print("prompt apply recovery check failed:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
    else:
        print("prompt apply recovery check PASSED")
    return 1 if findings else 0


def run() -> list[str]:
    findings: list[str] = []
    findings.extend(_static_findings())
    findings.extend(_test_findings())
    return findings


def _static_findings() -> list[str]:
    findings: list[str] = []
    persistence_text = (SERVER_DIR / "cgs_persistence.py").read_text(encoding="utf-8")
    router_text = (SERVER_DIR / "ws_message_router.py").read_text(encoding="utf-8")
    test_text = (REPO_ROOT / TEST_PATH).read_text(encoding="utf-8")

    for needle in (
        "restore_prompt_apply_failure",
        "xace.prompt_apply_recovery.v1",
        "artifacts_removed",
        "snapshot_index_entry",
        "sgc_proof_bundle",
    ):
        if needle not in persistence_text:
            findings.append(f"cgs_persistence.py missing {needle}")

    for needle in (
        "xace.prompt_apply_recovery.v1",
        "rejected_recovered",
        "rollback=rollback",
        "apply_validation",
        "PROMPT_APPLY_RUNTIME_VALIDATION_FAILED",
        "PROMPT_APPLY_REPLAY_VALIDATION_FAILED",
        "PROMPT_APPLY_ADAPTER_VALIDATION_FAILED",
        "PROMPT_APPLY_PERSIST_FAILED",
        "_persist_prompt_apply_artifacts",
        "_restore_prompt_apply_session_state",
        "session_restore",
        "ui_status_restored",
        "adapter_visible_effects_restored",
        "_run_prompt_apply_validation_hooks",
    ):
        if needle not in router_text:
            findings.append(f"ws_message_router.py missing {needle}")

    for needle in (
        "test_prompt_apply_rolls_back_sgc_failure_without_persisting_cgs",
        "test_prompt_apply_rolls_back_structural_apply_without_sgc",
        "test_prompt_apply_rolls_back_cgs_save_failure_without_ui_success",
        "test_prompt_apply_rolls_back_snapshot_failure_without_ui_success",
        "test_prompt_apply_rolls_back_plan_and_proof_artifacts_without_ui_success",
        "test_prompt_apply_rolls_back_runtime_validation_failure_and_restores_runtime_state",
        "test_prompt_apply_rolls_back_replay_validation_failure_without_ui_success",
        "test_prompt_apply_rolls_back_adapter_validation_failure_without_ui_success",
        "test_prompt_apply_rolls_back_provider_failure_without_pending_state",
        "_assert_prompt_apply_recovered",
        "session.gde.current_hash",
        "adapter_visible_effects_restored",
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
            "rolls_back",
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
    return [f"rollback e2e tests failed with exit {completed.returncode}:\n{tail}"]


if __name__ == "__main__":
    raise SystemExit(main())
