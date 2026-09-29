#!/usr/bin/env python3
"""AG-020 production-readiness gate for Codex Agent Mode.

The default gate is deterministic and safe for CI. It certifies the shipped
implementation while keeping per-machine Codex install/auth health as runtime
state. ``--live-codex`` adds a non-blocking installed-runtime probe;
``--require-live-codex`` makes that local probe release-blocking.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "tools"
SERVER_DIR = REPO_ROOT / "packages" / "builder-workspace" / "server"
for import_root in (str(SERVER_DIR), str(TOOLS_DIR)):
    if import_root not in sys.path:
        sys.path.insert(0, import_root)

from agent_host.codex_adapter import (  # noqa: E402
    CodexAppServerAdapter,
    CodexStdioJsonRpcClient,
    initialize_codex_client,
)
from credential_store import UnsafeFileCredentialBackend  # noqa: E402
from provider_settings import (  # noqa: E402
    AGENT_MODE_FEATURE_STAGE,
    AGENT_MODE_LAUNCH_STATUS_SCHEMA,
    AI_MODE_AGENT,
    AI_MODE_API_BYOK,
    CERTIFIED_AGENT_ADAPTERS,
    PRIMARY_AGENT_ADAPTER,
    ProviderSettingsStore,
)
from agent_provider_conformance import build_report as build_conformance_report  # noqa: E402
from agent_security_check import run_check as run_agent_security_check  # noqa: E402
from forbidden_claims_check import run as run_forbidden_claims_check  # noqa: E402


REPORT_SCHEMA = "xace.agent_mode_production_readiness.v1"
PASS = "pass"
FAIL = "fail"
UNSUPPORTED = "unsupported"
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "target-codex-agent-readiness"
    / "agent_mode_production_readiness.json"
)
DEFERRED_PROVIDERS = (
    {
        "provider_id": "local_agent",
        "roadmap_task": "AG-016",
        "required": False,
        "status": "deferred",
    },
    {
        "provider_id": "claude_agent",
        "roadmap_tasks": ["AG-017", "AG-018"],
        "required": False,
        "status": "deferred",
    },
)


@dataclass(frozen=True)
class ReadinessCheck:
    check_id: str
    status: str
    required: bool
    detail: str
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "status": self.status,
            "required": self.required,
            "detail": self.detail,
            "evidence": json.loads(json.dumps(dict(self.evidence), default=str)),
        }


async def build_report(
    *,
    work_root: Path,
    live_codex: bool = False,
    require_live_codex: bool = False,
) -> dict[str, Any]:
    work_root.mkdir(parents=True, exist_ok=True)
    checks: list[ReadinessCheck] = []
    required_checks: Sequence[
        tuple[str, Callable[[Path], Awaitable[Mapping[str, Any]]]]
    ] = (
        ("codex_adapter_conformance", _check_conformance),
        ("agent_security_policy", _check_security_policy),
        ("codex_provider_health_contract", _check_provider_health),
        ("api_byok_rollback", _check_api_byok_rollback),
        ("billing_boundaries", _check_billing_boundaries),
        ("functional_agent_ux", _check_functional_ux),
        ("approval_boundary", _check_approval_boundary),
        ("distribution_safety", _check_distribution_safety),
        ("product_claims", _check_product_claims),
    )
    for check_id, check_fn in required_checks:
        checks.append(await _capture_required(check_id, check_fn, work_root / check_id))

    if live_codex or require_live_codex:
        live = await _check_live_codex(required=require_live_codex)
        checks.append(live)

    ok = all(check.status == PASS for check in checks if check.required)
    conformance = next(
        (check.evidence for check in checks if check.check_id == "codex_adapter_conformance"),
        {},
    )
    certified = list(conformance.get("certified_adapters", []))
    codex_certified = PRIMARY_AGENT_ADAPTER in certified
    return {
        "schema": REPORT_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ok": ok,
        "shipping_decision": "ship_codex_agent_mode" if ok else "fallback_to_api_byok",
        "shipping_decision_scope": "integration_implementation_only",
        "implementation_certified": ok,
        "public_product_ready": False,
        "public_release_decision": "outside_codex_integration_scope",
        "codex_integration_complete": False,
        "codex_integration_decision": "continue_ag029_through_ag030",
        "codex_integration_roadmap": "docs/CODEX_PUBLIC_READINESS_ROADMAP.md",
        "default_mode": AI_MODE_API_BYOK,
        "preferred_mode": AI_MODE_AGENT,
        "primary_adapter": PRIMARY_AGENT_ADAPTER,
        "certified_adapters": certified,
        "disabled_production_adapters": [] if codex_certified and ok else [PRIMARY_AGENT_ADAPTER],
        "feature_stage": AGENT_MODE_FEATURE_STAGE,
        "launch_status_schema": AGENT_MODE_LAUNCH_STATUS_SCHEMA,
        "checks": [check.to_dict() for check in checks],
        "required_failures": [
            check.check_id
            for check in checks
            if check.required and check.status != PASS
        ],
        "deferred_providers": list(DEFERRED_PROVIDERS),
        "release_scope": {
            "current_distribution": "guided_official_external_install",
            "preferred_eventual_distribution": "xace_managed_official_package_acquisition",
            "distribution_decision": "complete",
            "distribution_policy": "xace.codex_distribution_policy.v1",
            "public_distribution_ready": False,
            "managed_runtime_bundled": False,
            "native_mcp_transport": "complete",
            "schema_and_process_resilience": "complete",
            "agent_privacy_diagnostics_support": "complete",
            "real_runtime_schema_certified": False,
            "provider_app_server_support": "official_docs_experimental_not_production_supported",
            "provider_native_auth_lifecycle": "complete",
            "functional_setup_and_recovery_ux": "complete_for_guided_external_runtime",
            "codex_integration_remaining_tasks": [
                "AG-029",
                "AG-030",
            ],
            "codex_integration_blockers": [
                "real_account_end_to_end_certification",
                "final_codex_integration_gate",
            ],
            "whole_xace_launch_readiness": "outside_codex_integration_scope",
            "managed_runtime_implementation_pending": [
                "certified_platform_artifact_matrix",
                "supported_sdk_runtime_launch_surface",
                "locked_artifact_hashes",
            ],
            "live_codex_required": require_live_codex,
        },
    }


async def _capture_required(
    check_id: str,
    check_fn: Callable[[Path], Awaitable[Mapping[str, Any]]],
    root: Path,
) -> ReadinessCheck:
    root.mkdir(parents=True, exist_ok=True)
    try:
        evidence = await check_fn(root)
        return ReadinessCheck(
            check_id=check_id,
            status=PASS,
            required=True,
            detail="Required production-readiness check passed.",
            evidence=evidence,
        )
    except Exception as exc:
        return ReadinessCheck(
            check_id=check_id,
            status=FAIL,
            required=True,
            detail=f"{type(exc).__name__}: {exc}",
        )


async def _check_conformance(root: Path) -> Mapping[str, Any]:
    report = await build_conformance_report(
        provider_names=("mock", "codex"),
        work_root=root,
    )
    providers = list(report["providers"])
    by_provider = {provider["provider_id"]: provider for provider in providers}
    _require(PRIMARY_AGENT_ADAPTER in by_provider, "Codex conformance report is missing")
    _require(by_provider[PRIMARY_AGENT_ADAPTER]["certified"], "Codex adapter is not certified")
    _require(by_provider["mock"]["certified"], "Mock reference adapter is not certified")
    return {
        "certified_adapters": list(report["certified_adapters"]),
        "providers": providers,
        "claude_or_local_required": False,
    }


async def _check_security_policy(_root: Path) -> Mapping[str, Any]:
    report = run_agent_security_check()
    _require(bool(report.get("ok")), "static Agent security policy check failed")
    _require(not report.get("findings"), "Agent security findings are present")
    return report


async def _check_provider_health(root: Path) -> Mapping[str, Any]:
    payload = await _healthy_agent_payload(root)
    agent = payload["agent_mode"]
    adapter = agent["primary_adapter_status"]
    metadata = adapter.get("metadata", {})
    launch = agent["launch_status"]
    _require(agent["ready"], "healthy Codex status did not become ready")
    _require(agent["code"] == "CODEX_AGENT_MODE_READY", "unexpected ready code")
    _require(PRIMARY_AGENT_ADAPTER in agent["certified_adapters"], "Codex is not certified")
    _require(launch["release_certified"], "release certification is missing")
    _require(launch["runtime_ready"], "healthy runtime is not marked ready")
    _require(launch["status"] == "production_ready", "launch status is not production ready")
    _require(bool(metadata.get("model_ids")), "provider-native model discovery is empty")
    _require(adapter.get("auth_state") == "signed_in", "provider auth is not signed in")
    return {
        "code": agent["code"],
        "launch_status": launch,
        "auth_state": adapter["auth_state"],
        "model_ids": metadata["model_ids"],
    }


async def _check_api_byok_rollback(root: Path) -> Mapping[str, Any]:
    store = _settings_store(root, _missing_codex_status)
    default_payload = store.payload()
    _require(default_payload["ai_mode"] == AI_MODE_API_BYOK, "API/BYOK is not the default")
    _require(default_payload["requested_ai_mode"] == AI_MODE_API_BYOK, "default request changed")
    agent_payload = store.configure_ai_mode(mode=AI_MODE_AGENT, enabled=True)
    _require(agent_payload["agent_mode"]["code"] == "CODEX_NOT_INSTALLED", "missing Codex was hidden")
    api_modes = {item["id"]: item for item in agent_payload["ai_modes"]}
    _require(api_modes[AI_MODE_API_BYOK]["available"], "API/BYOK fallback is unavailable")
    rolled_back = store.configure_ai_mode(mode=AI_MODE_API_BYOK)
    _require(rolled_back["ai_mode"] == AI_MODE_API_BYOK, "rollback did not activate API/BYOK")
    launch = rolled_back["agent_mode"]["launch_status"]
    _require(launch["fallback_available"], "launch contract hides the fallback")
    _require(launch["fallback_active"], "launch contract did not record active fallback")
    return {
        "default_mode": default_payload["ai_mode"],
        "missing_codex_code": agent_payload["agent_mode"]["code"],
        "rollback_mode": rolled_back["ai_mode"],
        "fallback_available": launch["fallback_available"],
    }


async def _check_billing_boundaries(root: Path) -> Mapping[str, Any]:
    payload = await _healthy_agent_payload(root)
    billing = payload["agent_mode"]["billing"]
    _require(billing["source"] == "provider_account", "Codex billing source is mislabeled")
    _require(billing["cost_state"] == "provider_managed", "Codex cost is not provider-managed")
    _require(billing["token_tracking"] == "provider_reported", "Codex usage provenance is wrong")
    _require(billing["estimated_cost_cents"] is None, "XACE invented a Codex dollar estimate")
    return billing


async def _check_functional_ux(_root: Path) -> Mapping[str, Any]:
    files = {
        "prompt": REPO_ROOT / "packages/builder-workspace/src/canvas/prompt_input.ts",
        "selector": REPO_ROOT / "packages/builder-workspace/src/canvas/model_selector.ts",
        "panel": REPO_ROOT / "packages/builder-workspace/src/panels/agent_mode_panel.ts",
        "store": REPO_ROOT / "packages/builder-workspace/src/state/agent_mode_store.ts",
    }
    required = {
        "prompt": ("makeAgentTurn", "_submitAgent", "xace.submit_proposal"),
        "selector": ("'/api/agent-mode'", "certified_adapters", "launch_status"),
        "panel": ("Codex Agent Mode", "Production ready", "Refresh status"),
        "store": ("AgentModeLaunchStatus", "xace.agent_mode_launch_status.v1"),
    }
    for label, path in files.items():
        text = path.read_text(encoding="utf-8-sig")
        for marker in required[label]:
            _require(marker in text, f"{label} UI is missing {marker!r}")
    return {"files": [path.relative_to(REPO_ROOT).as_posix() for path in files.values()]}


async def _check_approval_boundary(_root: Path) -> Mapping[str, Any]:
    panel = (
        REPO_ROOT / "packages/builder-workspace/src/panels/agent_mode_panel.ts"
    ).read_text(encoding="utf-8-sig")
    for marker in (
        "PreviewPending",
        "Approve preview",
        "Discard preview",
        "approval_token",
        "builder_agent_panel",
        "Codex cannot commit it directly",
    ):
        _require(marker in panel, f"approval UX is missing {marker!r}")
    return {
        "boundary": "agent -> XACE tools -> typed proposal -> preview -> approval -> GDE -> SGC -> runtime",
        "direct_commit": False,
    }


async def _check_distribution_safety(root: Path) -> Mapping[str, Any]:
    payload = _settings_store(root, _missing_codex_status).payload()
    distribution = payload["agent_mode"]["distribution"]
    _require(
        distribution["decision_status"] == "complete_guided_lifecycle_ag024",
        "AG-024 guided lifecycle decision is missing",
    )
    _require(
        distribution["preferred_runtime_source"] == "official_pinned_python_sdk_runtime",
        "preferred managed runtime source changed",
    )
    redistribution = distribution["redistribution"]
    _require(
        redistribution["bundling_allowed"] is False,
        "unverified Codex bundling was enabled",
    )
    _require(
        redistribution["raw_binary_redistribution_allowed"] is False,
        "raw Codex redistribution was enabled",
    )
    _require(
        redistribution["automatic_acquisition_enabled"] is False,
        "AG-024 acquisition was enabled prematurely",
    )
    auth = distribution["authentication"]
    _require(
        auth["owner"] == "codex_provider",
        "XACE took ownership of Codex credentials",
    )
    _require(
        auth["xace_reads_credentials"] is False,
        "XACE credential access was enabled",
    )
    _require(tuple(payload["agent_mode"]["certified_adapters"]) == CERTIFIED_AGENT_ADAPTERS, "certification manifest drifted")
    return distribution


async def _check_product_claims(_root: Path) -> Mapping[str, Any]:
    findings = run_forbidden_claims_check(REPO_ROOT)
    _require(not findings, "forbidden product claims are present")
    matrix = (REPO_ROOT / "docs/XACE_PRODUCT_CLAIMS_MATRIX.md").read_text(encoding="utf-8-sig")
    _require("| Codex Agent Mode |" in matrix, "claims matrix has no Codex Agent Mode row")
    _require("API/BYOK remains available" in matrix, "claims matrix omits the fallback")
    return {"forbidden_findings": 0, "claims_matrix_row": "Codex Agent Mode"}


async def _check_live_codex(*, required: bool) -> ReadinessCheck:
    adapter = CodexAppServerAdapter()
    try:
        status = await adapter.detect()
        lifecycle: Mapping[str, Any] = {}
        passed = status.installed and status.available and status.auth_state.value == "signed_in"
        if passed and status.executable_path:
            lifecycle = await asyncio.to_thread(
                _probe_live_stable_thread_lifecycle,
                status.executable_path,
            )
            passed = bool(lifecycle.get("passed"))
        check_status = PASS if passed else (FAIL if required else UNSUPPORTED)
        return ReadinessCheck(
            check_id="live_codex_runtime",
            status=check_status,
            required=required,
            detail=(
                "Installed Codex App Server is healthy."
                if passed
                else "Installed Codex App Server is unavailable, unsigned-in, or session-incompatible."
            ),
            evidence={
                "installed": status.installed,
                "available": status.available,
                "auth_state": status.auth_state.value,
                "version": status.version,
                "model_count": len(status.metadata.get("model_ids", [])),
                "warnings": list(status.warnings),
                "runtime_compatibility": status.metadata.get("runtime_compatibility", {}),
                "stable_thread_lifecycle": lifecycle,
            },
        )
    except Exception as exc:
        return ReadinessCheck(
            check_id="live_codex_runtime",
            status=FAIL if required else UNSUPPORTED,
            required=required,
            detail=f"{type(exc).__name__}: {exc}",
        )
    finally:
        adapter.close()


def _probe_live_stable_thread_lifecycle(executable_path: str) -> dict[str, Any]:
    """Start and delete an empty thread without enabling experiments or running a turn."""

    client = CodexStdioJsonRpcClient(executable_path, timeout_seconds=10.0)
    thread_id = ""
    deleted = False
    try:
        initialize_codex_client(client)
        params = {
            "approvalPolicy": "never",
            "sandbox": "read-only",
            "serviceName": "xace_compatibility_smoke",
        }
        result = client.request("thread/start", params)
        thread = result.get("thread") if isinstance(result, Mapping) else None
        if not isinstance(thread, Mapping) or not str(thread.get("id") or "").strip():
            raise RuntimeError("Codex App Server thread/start returned no thread id")
        thread_id = str(thread["id"])
        client.request("thread/delete", {"threadId": thread_id})
        deleted = True
        return {
            "passed": True,
            "api_profile": "stable",
            "experimental_api": False,
            "history_mode_sent": False,
            "model_turn_started": False,
            "thread_started": True,
            "thread_deleted": True,
        }
    except Exception as exc:
        return {
            "passed": False,
            "api_profile": "stable",
            "experimental_api": False,
            "history_mode_sent": False,
            "model_turn_started": False,
            "thread_started": bool(thread_id),
            "thread_deleted": deleted,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        client.close()


async def _healthy_agent_payload(root: Path) -> dict[str, Any]:
    report = await build_conformance_report(
        provider_names=("codex",),
        work_root=root / "conformance",
    )
    provider = report["providers"][0]
    detection = next(
        check for check in provider["checks"] if check["check_id"] == "detection"
    )
    status = detection["evidence"].get("status")
    _require(isinstance(status, Mapping), "Codex detection evidence has no status")
    store = _settings_store(root, lambda: status)
    return store.configure_ai_mode(mode=AI_MODE_AGENT, enabled=True)


def _settings_store(
    root: Path,
    status_reader: Callable[[], Any],
) -> ProviderSettingsStore:
    root.mkdir(parents=True, exist_ok=True)
    return ProviderSettingsStore(
        root / "provider_settings.json",
        credential_store=UnsafeFileCredentialBackend(root / "unsafe_credentials.json"),
        agent_status_reader=status_reader,
    )


def _missing_codex_status() -> dict[str, Any]:
    return {
        "schema": "xace.agent_host.v1",
        "provider_id": PRIMARY_AGENT_ADAPTER,
        "display_name": "Codex App Server",
        "provider_kind": "codex_app_server",
        "installed": False,
        "available": False,
        "auth_state": "missing",
        "executable_path": None,
        "version": None,
        "min_supported_version": None,
        "account_label": None,
        "capabilities": {},
        "warnings": ["Codex executable was not found."],
        "last_checked_at": "",
        "metadata": {"app_server_responsive": False},
    }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--live-codex", action="store_true")
    parser.add_argument("--require-live-codex", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    output = args.output.resolve()
    report = asyncio.run(
        build_report(
            work_root=output.parent / "work",
            live_codex=args.live_codex,
            require_live_codex=args.require_live_codex,
        )
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("Codex Agent Mode production readiness:", "PASS" if report["ok"] else "FAIL")
        for check in report["checks"]:
            print(f"- {check['check_id']}: {check['status'].upper()}")
        print(f"Decision: {report['shipping_decision']}")
        print(f"Report: {output}")
        print(f"Public release: {report['public_release_decision']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
