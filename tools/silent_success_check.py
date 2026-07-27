"""
Validate that unsupported runtime and Builder paths do not report success.

The check is intentionally narrow and high-signal: it pins Task 17/18 regressions
where unsupported, incomplete, or blocked behavior used to look successful.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "xace.silent_success_check.v1"
SKIP_MARKER = "skipped"


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    path: str
    message: str
    code: str
    action: str


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8", errors="ignore")


def _present(rel_path: str, needle: str, *, name: str, code: str, action: str) -> CheckResult:
    text = _read(rel_path)
    ok = needle in text
    return CheckResult(
        name=name,
        ok=ok,
        path=rel_path,
        message="required marker is present" if ok else f"missing required marker: {needle}",
        code=code,
        action=action,
    )


def _absent(rel_path: str, needle: str, *, name: str, code: str, action: str) -> CheckResult:
    text = _read(rel_path)
    ok = needle not in text
    return CheckResult(
        name=name,
        ok=ok,
        path=rel_path,
        message="forbidden marker is absent" if ok else f"forbidden marker remains: {needle}",
        code=code,
        action=action,
    )


def _count_at_least(
    rel_path: str,
    needle: str,
    minimum: int,
    *,
    name: str,
    code: str,
    action: str,
) -> CheckResult:
    count = _read(rel_path).count(needle)
    ok = count >= minimum
    return CheckResult(
        name=name,
        ok=ok,
        path=rel_path,
        message=f"found {count}, expected at least {minimum}",
        code=code,
        action=action,
    )


def run() -> dict[str, Any]:
    sgc_old_log = "SGC " + SKIP_MARKER
    status_skipped_json = '"status": "' + SKIP_MARKER + '"'
    wiring_only_sgc_marker = "fake" + "_sgc_wiring_test_only"
    simple_pipeline_marker = "Simple" + "Pipeline"
    mock_adapter_marker = "_" + "Mock" + "Adapter"
    legacy_apply_marker = "_naive" + "_apply"
    legacy_set_marker = "_naive" + "_set"
    legacy_option_marker = "allow_" + "naive" + "_apply"
    legacy_router_marker = "naive " + "_apply_operations"
    results = [
        _absent(
            "packages/gde/src/gde_orchestrator.py",
            "GDEResult(success=True, error=",
            name="GDE blocked outcome cannot be success",
            code="SILENT_SUCCESS_GDE_RESULT",
            action="Return success=False with code/action/unsupported metadata for blocked GDE outcomes.",
        ),
        _present(
            "packages/gde/src/gde_orchestrator.py",
            "GDE_CLARIFICATION_REPROMPT_REQUIRED",
            name="GDE clarification completion has action code",
            code="SILENT_SUCCESS_GDE_CLARIFICATION",
            action="Keep the clarification completion path explicitly blocked until it commits a CGS mutation.",
        ),
        _absent(
            "packages/builder-workspace/server/ws_message_router.py",
            sgc_old_log,
            name="Builder SGC structural path does not log and continue",
            code="SILENT_SUCCESS_SGC_LOG_CONTINUE",
            action="Reject structural prompt applies when SGC proof is unavailable.",
        ),
        _present(
            "packages/builder-workspace/server/ws_message_router.py",
            'outcome="rejected_recovered"',
            name="Builder audits structural SGC unavailability",
            code="SILENT_SUCCESS_SGC_AUDIT",
            action="Keep structural SGC unavailability on the recovered rollback audit path.",
        ),
        _present(
            "packages/builder-workspace/server/session_manager.py",
            "SGC_UNCONFIGURED",
            name="SGC unconfigured path has a stable code",
            code="SILENT_SUCCESS_SGC_UNCONFIGURED",
            action="Keep SGC_UNCONFIGURED on structural compile results that cannot run the compiler.",
        ),
        _present(
            "packages/builder-workspace/server/session_manager.py",
            "SGC_NO_SYSTEMS",
            name="SGC empty graph path has a stable code",
            code="SILENT_SUCCESS_SGC_NO_SYSTEMS",
            action="Keep SGC_NO_SYSTEMS on empty structural graph results.",
        ),
        _present(
            "packages/builder-workspace/server/ws_message_router.py",
            status_skipped_json,
            name="Builder emits explicit SGC status metadata",
            code="SILENT_SUCCESS_SGC_STATUS",
            action="Return an explicit status/action/code payload instead of a successful mutation update.",
        ),
        _absent(
            "packages/runtime-core/src/dcl/character/animation_layer_manager.rs",
            "return Ok(()); // Silently",
            name="Runtime animation transition refusal is not a no-op",
            code="SILENT_SUCCESS_ANIMATION_NOOP",
            action="Return an actionable animation transition error when force=false cannot interrupt.",
        ),
        _present(
            "packages/runtime-core/src/dcl/character/animation_layer_manager.rs",
            "ANIMATION_TRANSITION_IN_PROGRESS",
            name="Runtime animation transition has stable error code",
            code="SILENT_SUCCESS_ANIMATION_CODE",
            action="Keep the stable animation transition error code in request_transition.",
        ),
        _count_at_least(
            "packages/builder-workspace/server/builder_server.py",
            "ADAPTER_NOT_APPLICABLE",
            4,
            name="Headless adapter responses are explicit",
            code="SILENT_SUCCESS_ADAPTER_HEADLESS",
            action="Keep headless adapter responses marked not_applicable with code and action metadata.",
        ),
        _present(
            "packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py",
            "test_prompt_apply_rolls_back_structural_apply_without_sgc",
            name="Builder structural SGC regression test exists",
            code="SILENT_SUCCESS_BUILDER_TEST",
            action="Keep E2E coverage that proves structural apply rolls back without persistence or UI success.",
        ),
        _present(
            "packages/gde/src/tests/test_gde_orchestrator.py",
            "test_completed_clarification_requires_reprompt_instead_of_success",
            name="GDE clarification regression test exists",
            code="SILENT_SUCCESS_GDE_TEST",
            action="Keep GDE coverage that proves clarification completion is not reported as a commit.",
        ),
        _absent(
            "tools/prompt_pipeline_smoke.py",
            wiring_only_sgc_marker,
            name="Prompt proof uses real SGC",
            code="SILENT_SUCCESS_REAL_SGC_PROMPT_PROOF",
            action="Keep prompt/certification proof on the compiled SGC binary path.",
        ),
        _present(
            "tools/prompt_pipeline_smoke.py",
            "--sgc-bin",
            name="Prompt proof requires SGC binary argument",
            code="SILENT_SUCCESS_PROMPT_SGC_ARG",
            action="Keep the prompt proof command explicit about the SGC binary it invokes.",
        ),
        _present(
            "tools/certify_launch.py",
            "--sgc-bin",
            name="Certification passes SGC binary to prompt proof",
            code="SILENT_SUCCESS_CERTIFY_SGC_ARG",
            action="Keep certification wired to the SGC binary built in the same target directory.",
        ),
        _absent(
            "packages/builder-workspace/server/session_manager.py",
            simple_pipeline_marker,
            name="PIL unavailable has no fallback pipeline",
            code="SILENT_SUCCESS_PIL_FALLBACK_REMOVED",
            action="Keep PIL-unavailable prompt execution blocked with PIL_UNAVAILABLE.",
        ),
        _absent(
            "packages/builder-workspace/server/session_manager.py",
            mock_adapter_marker,
            name="Builder production has no provider test double",
            code="SILENT_SUCCESS_PROVIDER_DOUBLE_REMOVED",
            action="Keep provider test doubles isolated to tests and smokes.",
        ),
        _present(
            "packages/builder-workspace/server/session_manager.py",
            "PIL_UNAVAILABLE",
            name="PIL unavailable path has stable code",
            code="SILENT_SUCCESS_PIL_UNAVAILABLE_CODE",
            action="Keep missing prompt dependencies surfaced as a blocked unsupported prompt result.",
        ),
        _absent(
            "packages/builder-workspace/server/session_manager.py",
            legacy_option_marker,
            name="Builder has no direct CGS fallback option",
            code="SILENT_SUCCESS_BUILDER_DIRECT_CGS_OPTION",
            action="Keep Builder production apply committed exclusively through GDE.",
        ),
        _absent(
            "packages/builder-workspace/server/session_manager.py",
            legacy_apply_marker,
            name="Builder has no legacy direct CGS apply helper",
            code="SILENT_SUCCESS_BUILDER_DIRECT_CGS_APPLY",
            action="Keep direct CGS mutation helpers out of production session management.",
        ),
        _absent(
            "packages/builder-workspace/server/session_manager.py",
            legacy_set_marker,
            name="Builder has no legacy direct CGS setter",
            code="SILENT_SUCCESS_BUILDER_DIRECT_CGS_SETTER",
            action="Keep direct CGS mutation helpers out of production session management.",
        ),
        _absent(
            "packages/builder-workspace/server/ws_message_router.py",
            legacy_router_marker,
            name="Router docs do not reference removed direct apply helper",
            code="SILENT_SUCCESS_BUILDER_ROUTER_DIRECT_CGS_DOC",
            action="Keep Builder routing documentation aligned with the GDE-only apply path.",
        ),
        _present(
            "packages/builder-workspace/server/tests/test_session_manager_authority.py",
            "test_apply_via_gde_rejects_when_gde_unavailable_without_persistable_result",
            name="No-GDE rejection regression test exists",
            code="SILENT_SUCCESS_BUILDER_NO_GDE_TEST",
            action="Keep regression coverage proving no-GDE apply returns no persisted CGS result.",
        ),
    ]
    ok = all(result.ok for result in results)
    return {
        "schema": SCHEMA,
        "ok": ok,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "checks": [result.__dict__ for result in results],
        "failures": [result.__dict__ for result in results if not result.ok],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate no-silent-success guards.")
    parser.add_argument("--output", default="", help="Optional JSON report path.")
    args = parser.parse_args(argv)

    report = run()
    if args.output:
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if report["ok"]:
        print("silent success check PASSED")
        return 0
    print("silent success check FAILED", file=sys.stderr)
    for failure in report["failures"]:
        print(f"{failure['path']}: {failure['code']}: {failure['message']}", file=sys.stderr)
        print(f"  action: {failure['action']}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
