"""
Editor-free provider-readiness and stale-provider policy check.

This proves the launch gate around normal-user BYOK provider setup without
requiring internet access or a real API key:

    missing key/config -> prompt execution is blocked
    saved provider/key without health proof -> prompt execution is blocked
    matching health proof -> prompt can enter PIL
    stale model/base URL/key proofs -> prompt execution is blocked
    malformed health proof -> prompt execution is blocked
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = REPO_ROOT / "packages" / "builder-workspace" / "server"
PROMPT_FIXTURE_DIR = SERVER_DIR / "tests" / "fixtures"
PROJECT_SYSTEM_DIR = REPO_ROOT / "packages" / "project-system"

for path in (PROMPT_FIXTURE_DIR, SERVER_DIR, PROJECT_SYSTEM_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from prompt_pipeline_contract import DeterministicPromptPipeline, supported_prompt_pipeline_scenarios  # noqa: E402
from project_templates import make_template  # noqa: E402
from credential_store import BACKEND_ENV, UNSAFE_FALLBACK_ENV, UNSAFE_STORE_PATH_ENV  # noqa: E402
from provider_settings import ProviderSettingsStore, _fingerprint  # noqa: E402
from session_manager import BuilderSession, SessionManager  # noqa: E402


PROVIDER = "openai"
MODEL = "xace-cert-model"
ALT_MODEL = "xace-cert-model-stale"
ALT_BASE_URL = "https://proxy.example.test/openai/v1"
FAKE_KEY = "sk-" + "xace-provider-certification"
ALT_KEY = "sk-" + "xace-provider-certification-rotated"
SCHEMA = "xace.provider_health_stale_policy_report.v1"
READINESS_GATED_PROMPT_INDEX = 1


async def run_provider_readiness_smoke(settings_path: Path) -> dict[str, Any]:
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    if settings_path.exists():
        settings_path.unlink()

    previous_env = os.environ.get("XACE_PROVIDER_SETTINGS_PATH")
    previous_backend_env = os.environ.get(BACKEND_ENV)
    previous_unsafe_env = os.environ.get(UNSAFE_FALLBACK_ENV)
    previous_unsafe_path_env = os.environ.get(UNSAFE_STORE_PATH_ENV)
    os.environ["XACE_PROVIDER_SETTINGS_PATH"] = str(settings_path)
    os.environ[BACKEND_ENV] = "unsafe-file"
    os.environ[UNSAFE_FALLBACK_ENV] = "1"
    os.environ[UNSAFE_STORE_PATH_ENV] = str(settings_path.with_suffix(".unsafe_credentials.json"))
    try:
        store = ProviderSettingsStore(settings_path)
        cases: list[dict[str, Any]] = []

        store.configure(provider=PROVIDER, model=MODEL, api_key="")
        cases.append(_case("missing_key", store.active_readiness(), expected_ok=False, expected_code="PROVIDER_KEY_MISSING"))

        store.configure(provider=PROVIDER, model=MODEL, api_key=FAKE_KEY)
        cases.append(_case("untested", store.active_readiness(), expected_ok=False, expected_code="PROVIDER_HEALTH_UNTESTED"))

        sent: list[dict[str, Any]] = []

        async def send_fn(message: dict[str, Any]) -> None:
            sent.append(message)

        sm = SessionManager()
        session = BuilderSession(
            session_id="provider-readiness-smoke",
            pipeline=DeterministicPromptPipeline(supported_prompt_pipeline_scenarios()),
            gde=None,
        )
        sm._sessions[session.session_id] = session
        cgs = make_template("blank_3d", "Provider Readiness Smoke")
        cgs_hash = str(cgs.get("metadata", {}).get("cgs_hash", ""))

        blocked = await _run_prompt(
            sm,
            send_fn,
            cgs,
            cgs_hash,
        )
        _require(blocked.get("kind") == "blocked", "untested provider did not block prompt execution")
        _require(blocked.get("code") == "PROVIDER_HEALTH_UNTESTED", "untested provider block did not carry readiness code")
        _require(
            blocked.get("intent_category") == "ProviderConfiguration",
            "provider block did not identify provider configuration",
        )
        _require(session.pending_txn is None, "unready provider left a pending transaction")

        sm._provider_store._record_test(PROVIDER, _passing_health_result())
        ready = sm.provider_readiness()
        cases.append(_case("ready_exact_tuple", ready, expected_ok=True, expected_code=""))
        _require(ready.get("ok"), f"matching health proof did not mark provider ready: {ready}")

        allowed = await _run_prompt(sm, send_fn, cgs, cgs_hash)
        _require(allowed.get("kind") == "mutation", "ready provider did not let prompt enter PIL")
        _require(session.pending_txn is not None, "ready provider did not create a pending transaction")

        sm.configure_provider(provider=PROVIDER, model_name=ALT_MODEL)
        stale = sm.provider_readiness()
        _require(not stale.get("ok"), "changed model reused stale provider health proof")
        _require(stale.get("code") == "PROVIDER_HEALTH_PROOF_STALE", f"changed model did not report stale proof: {stale}")
        cases.append(_case("stale_model", stale, expected_ok=False, expected_code="PROVIDER_HEALTH_PROOF_STALE"))
        blocked_again = await _run_prompt(sm, send_fn, cgs, cgs_hash)
        _require(blocked_again.get("kind") == "blocked", "stale provider proof did not block prompt execution")
        _require(blocked_again.get("code") == "PROVIDER_HEALTH_PROOF_STALE", "stale provider block did not carry readiness code")

        sm.configure_provider(provider=PROVIDER, model_name=MODEL)
        sm._provider_store._record_test(PROVIDER, _passing_health_result())
        sm.configure_provider(provider=PROVIDER, model_name=MODEL, base_url=ALT_BASE_URL)
        stale_base_url = sm.provider_readiness()
        cases.append(_case("stale_base_url", stale_base_url, expected_ok=False, expected_code="PROVIDER_HEALTH_PROOF_STALE"))
        _require((await _run_prompt(sm, send_fn, cgs, cgs_hash)).get("kind") == "blocked", "stale base URL proof did not block prompt execution")

        sm.configure_provider(provider=PROVIDER, model_name=MODEL, base_url="https://api.openai.com/v1")
        sm._provider_store._record_test(PROVIDER, _passing_health_result())
        sm.configure_provider(provider=PROVIDER, model_name=MODEL, api_key=ALT_KEY)
        stale_key = sm.provider_readiness()
        cases.append(_case("stale_key_fingerprint", stale_key, expected_ok=False, expected_code="PROVIDER_HEALTH_PROOF_STALE"))
        _require((await _run_prompt(sm, send_fn, cgs, cgs_hash)).get("kind") == "blocked", "stale key proof did not block prompt execution")

        sm.configure_provider(provider=PROVIDER, model_name=MODEL, api_key=FAKE_KEY)
        sm._provider_store._record_test(PROVIDER, _passing_health_result())
        providers = sm._provider_store._state.setdefault("providers", {})
        openai_entry = providers.setdefault(PROVIDER, {})
        last_test = dict(openai_entry.get("last_test") or {})
        last_test.pop("config_hash", None)
        openai_entry["last_test"] = last_test
        sm._provider_store._save()
        invalid_proof = sm.provider_readiness()
        cases.append(_case("invalid_missing_config_hash", invalid_proof, expected_ok=False, expected_code="PROVIDER_HEALTH_PROOF_INVALID"))
        _require((await _run_prompt(sm, send_fn, cgs, cgs_hash)).get("kind") == "blocked", "invalid health proof did not block prompt execution")

        sm.configure_provider(provider=PROVIDER, model_name=MODEL, base_url="not-a-url")
        invalid_base_url = sm.provider_readiness()
        cases.append(_case("invalid_base_url", invalid_base_url, expected_ok=False, expected_code="PROVIDER_BASE_URL_INVALID"))

        return {
            "ok": True,
            "schema": SCHEMA,
            "settings_path": str(settings_path),
            "provider": PROVIDER,
            "model": MODEL,
            "blocked_code": blocked.get("code"),
            "ready_message": ready.get("message"),
            "stale_code": stale.get("code"),
            "case_count": len(cases),
            "cases": cases,
        }
    finally:
        if previous_env is None:
            os.environ.pop("XACE_PROVIDER_SETTINGS_PATH", None)
        else:
            os.environ["XACE_PROVIDER_SETTINGS_PATH"] = previous_env
        _restore_env(BACKEND_ENV, previous_backend_env)
        _restore_env(UNSAFE_FALLBACK_ENV, previous_unsafe_env)
        _restore_env(UNSAFE_STORE_PATH_ENV, previous_unsafe_path_env)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check XACE provider readiness and stale-provider prompt gating.")
    parser.add_argument("--settings-path", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--keep-settings", action="store_true")
    args = parser.parse_args(argv)

    cleanup: tempfile.TemporaryDirectory[str] | None = None
    if args.settings_path:
        settings_path = Path(args.settings_path).resolve()
    else:
        cleanup = tempfile.TemporaryDirectory(prefix="xace-provider-readiness-")
        settings_path = Path(cleanup.name) / "provider_settings.json"

    summary = asyncio.run(run_provider_readiness_smoke(settings_path))
    if args.output:
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    if not args.json:
        print("provider readiness stale-policy check PASSED")

    if cleanup is not None and not args.keep_settings:
        cleanup.cleanup()
    return 0


def _passing_health_result() -> dict[str, Any]:
    return {
        "ok": True,
        "provider": PROVIDER,
        "model": MODEL,
        "base_url": "https://api.openai.com/v1",
        "key_fingerprint": _fingerprint(FAKE_KEY),
        "checks": {
            "key_present": True,
            "key_valid": True,
            "model_reachable": True,
            "test_call": True,
        },
        "message": "OpenAI responded with xace-cert-model.",
        "latency_ms": 1,
    }


async def _run_prompt(
    sm: SessionManager,
    send_fn,
    cgs: dict[str, Any],
    cgs_hash: str,
) -> dict[str, Any]:
    return await sm.run_pil(
        "provider-readiness-smoke",
        supported_prompt_pipeline_scenarios()[READINESS_GATED_PROMPT_INDEX].prompt,
        cgs,
        cgs_hash,
        send_fn=send_fn,
    )


def _case(name: str, readiness: dict[str, Any], *, expected_ok: bool, expected_code: str) -> dict[str, Any]:
    _require(bool(readiness.get("ok")) is expected_ok, f"{name}: readiness ok mismatch: {readiness}")
    if expected_code:
        _require(readiness.get("code") == expected_code, f"{name}: expected {expected_code}, got {readiness.get('code')}")
    return {
        "name": name,
        "ok": bool(readiness.get("ok")),
        "code": str(readiness.get("code") or ""),
        "action": str(readiness.get("action") or ""),
        "proof_status": str(readiness.get("proof_status") or ""),
        "provider": str(readiness.get("provider") or ""),
        "model": str(readiness.get("model") or ""),
        "base_url": str(readiness.get("base_url") or ""),
        "config_hash": str(readiness.get("config_hash") or ""),
        "key_fingerprint_present": bool(readiness.get("key_fingerprint")),
    }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _restore_env(key: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
