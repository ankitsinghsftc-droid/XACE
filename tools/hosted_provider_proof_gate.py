"""
Opt-in BYOK proof gate for real hosted and local/self-hosted providers.

Default execution performs no network calls. Live provider calls require both
`--live` and XACE_HOSTED_PROVIDER_PROOF_OPT_IN=1.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = REPO_ROOT / "packages" / "builder-workspace" / "server"
PACKAGES_DIR = REPO_ROOT / "packages"

for path in (SERVER_DIR, PACKAGES_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from provider_settings import (  # noqa: E402
    DEFAULT_OLLAMA_URL,
    ProviderSelection,
    ProviderSettingsStore,
    _build_inference_adapter,
    _fingerprint,
)
from secret_redaction import REDACTED_SECRET, redact_exception, redact_text, redact_value  # noqa: E402


SCHEMA = "xace.hosted_provider_proof_report.v1"
OPT_IN_ENV = "XACE_HOSTED_PROVIDER_PROOF_OPT_IN"
PROVIDERS_ENV = "XACE_HOSTED_PROVIDER_PROOF_PROVIDERS"
LIVE_PROMPT = "Reply with XACE_LIVE_PROVIDER_PROOF only."
LIVE_SYSTEM = "You are a provider proof check. Reply with the requested marker only."

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("anthropic_api_key", re.compile(r"sk-ant-[A-Za-z0-9][A-Za-z0-9_\-]{8,}")),
    ("generic_api_key", re.compile(r"sk-[A-Za-z0-9][A-Za-z0-9_\-]{8,}")),
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z_\-]{20,}")),
    ("bearer_token", re.compile(r"(?i)Bearer\s+[A-Za-z0-9._~+\-/=]{12,}")),
    ("api_key_header", re.compile(r"(?i)(?:x-api-key|api-key)\s*[:=]\s*[A-Za-z0-9._~+\-/=]{12,}")),
)


@dataclass(frozen=True)
class ProviderSpec:
    proof_id: str
    provider: str
    label: str
    kind: str
    key_env: tuple[str, ...]
    model_env: str
    base_url_env: str
    default_base_url: str
    requires_key: bool = True


HOSTED_SPECS: dict[str, ProviderSpec] = {
    "openai_compatible": ProviderSpec(
        proof_id="openai_compatible",
        provider="openai",
        label="OpenAI-compatible",
        kind="hosted",
        key_env=("XACE_OPENAI_COMPATIBLE_API_KEY", "XACE_OPENAI_API_KEY"),
        model_env="XACE_OPENAI_COMPATIBLE_MODEL",
        base_url_env="XACE_OPENAI_COMPATIBLE_BASE_URL",
        default_base_url="https://api.openai.com/v1",
    ),
    "anthropic": ProviderSpec(
        proof_id="anthropic",
        provider="anthropic",
        label="Anthropic",
        kind="hosted",
        key_env=("XACE_ANTHROPIC_API_KEY",),
        model_env="XACE_ANTHROPIC_MODEL",
        base_url_env="XACE_ANTHROPIC_BASE_URL",
        default_base_url="https://api.anthropic.com",
    ),
    "google": ProviderSpec(
        proof_id="google",
        provider="google",
        label="Google Gemini",
        kind="hosted",
        key_env=("XACE_GOOGLE_API_KEY",),
        model_env="XACE_GOOGLE_MODEL",
        base_url_env="XACE_GOOGLE_BASE_URL",
        default_base_url="https://generativelanguage.googleapis.com/v1beta",
    ),
}


@dataclass
class PromptPart:
    text: str
    cacheable: bool = False
    label: str = "provider-proof"


@dataclass
class ProofRequest:
    prompt_parts: list[PromptPart]
    system_prompt: str = LIVE_SYSTEM
    logical_model: str = "cheap_validation"
    complexity_tier: str = "TIER_M"
    max_tokens: int = 24
    temperature: float = 0.0
    session_id: str = "hosted-provider-proof"
    call_label: str = "hosted_provider_prompt_check"
    request_id: str = "hosted-provider-proof"
    cgs_structural_hash: str = ""
    intent_class: str = "HostedProviderProof"
    bypass_response_cache: bool = True

    def full_prompt_text(self) -> str:
        return "\n".join(part.text for part in self.prompt_parts)

    def cacheable_text(self) -> str:
        return "\n".join(part.text for part in self.prompt_parts if part.cacheable)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the opt-in XACE hosted-provider proof gate.")
    parser.add_argument("--output", default="target-hosted-provider-proof/hosted_provider_proof_report.json")
    parser.add_argument("--providers", default="", help="Comma-separated provider proof IDs.")
    parser.add_argument("--live", action="store_true", help="Request live provider calls. Also requires XACE_HOSTED_PROVIDER_PROOF_OPT_IN=1.")
    parser.add_argument("--require-live", action="store_true", help="Fail unless requested providers run live and pass.")
    parser.add_argument("--settings-path", default="", help="Isolated provider settings path for proof state.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    output = Path(args.output).resolve()
    providers = _requested_providers(args.providers)
    live_opt_in = str(os.environ.get(OPT_IN_ENV, "")).strip() == "1"
    live_enabled = bool(args.live and live_opt_in)

    if args.settings_path:
        settings_path = Path(args.settings_path).resolve()
        cleanup: tempfile.TemporaryDirectory[str] | None = None
    else:
        cleanup = tempfile.TemporaryDirectory(prefix="xace-hosted-provider-proof-")
        settings_path = Path(cleanup.name) / "provider_settings.json"

    started = time.perf_counter()
    secrets = _configured_secret_values(providers)
    try:
        if live_enabled:
            report = _run_live_report(providers=providers, settings_path=settings_path)
        else:
            report = _not_run_report(
                providers=providers,
                require_live=bool(args.require_live),
                live_requested=bool(args.live),
                live_opt_in=live_opt_in,
            )
        report["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        report = _finalize_report(report, secrets=secrets)
        if args.require_live and not bool(report.get("live_executed")):
            report["ok"] = False
            report["status"] = "fail"
            report["failure_code"] = "HOSTED_PROVIDER_PROOF_NOT_RUN"
            report["message"] = "Live provider proof was required but opt-in or BYOK configuration was missing."
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(f"hosted provider proof gate {report.get('status')}: {output}")
        return 0 if bool(report.get("ok")) else 1
    finally:
        if cleanup is not None:
            cleanup.cleanup()


def _requested_providers(raw: str) -> list[str]:
    value = raw.strip() or os.environ.get(PROVIDERS_ENV, "").strip()
    if not value:
        return ["openai_compatible", "anthropic", "google", "local_self_hosted"]
    providers = [item.strip().lower() for item in value.split(",") if item.strip()]
    unknown = [item for item in providers if item not in {*HOSTED_SPECS.keys(), "local_self_hosted"}]
    if unknown:
        raise SystemExit(f"unknown provider proof ID(s): {', '.join(unknown)}")
    return providers


def _not_run_report(
    *,
    providers: list[str],
    require_live: bool,
    live_requested: bool,
    live_opt_in: bool,
) -> dict[str, Any]:
    reason = (
        "live proof requires --live and XACE_HOSTED_PROVIDER_PROOF_OPT_IN=1"
        if not live_requested or not live_opt_in else
        "live proof was not executed"
    )
    return {
        "schema": SCHEMA,
        "ok": not require_live,
        "status": "not_run" if not require_live else "fail",
        "live_executed": False,
        "unsupported": True,
        "live_requested": live_requested,
        "live_opt_in": live_opt_in,
        "required_opt_in_env": OPT_IN_ENV,
        "generated_at_utc": _now_utc(),
        "requested_providers": providers,
        "providers": [_not_run_case(provider, reason) for provider in providers],
        "message": reason,
    }


def _not_run_case(provider: str, reason: str) -> dict[str, Any]:
    spec = _provider_spec(provider)
    return {
        "proof_id": provider,
        "provider": spec.provider,
        "label": spec.label,
        "kind": spec.kind,
        "ok": True,
        "status": "not_run",
        "unsupported": True,
        "reason": reason,
        "key_env": list(spec.key_env),
        "model_env": spec.model_env,
        "base_url_env": spec.base_url_env,
    }


def _run_live_report(*, providers: list[str], settings_path: Path) -> dict[str, Any]:
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    if settings_path.exists():
        settings_path.unlink()
    store = ProviderSettingsStore(settings_path)
    cases = [_run_provider_case(store, _provider_spec(provider)) for provider in providers]
    return {
        "schema": SCHEMA,
        "ok": all(bool(case.get("ok")) for case in cases),
        "status": "pass" if all(bool(case.get("ok")) for case in cases) else "fail",
        "live_executed": True,
        "unsupported": False,
        "live_requested": True,
        "live_opt_in": True,
        "generated_at_utc": _now_utc(),
        "settings_path": str(settings_path),
        "requested_providers": providers,
        "providers": cases,
    }


def _run_provider_case(store: ProviderSettingsStore, spec: ProviderSpec) -> dict[str, Any]:
    configured = _configured_provider(spec)
    if configured.get("missing"):
        return {
            "proof_id": spec.proof_id,
            "provider": spec.provider,
            "label": spec.label,
            "kind": spec.kind,
            "ok": False,
            "status": "config_missing",
            "missing": configured["missing"],
            "action": "set required environment variables and rerun with live opt-in",
        }

    started = time.perf_counter()
    selection = ProviderSelection(
        provider=str(configured["provider"]),
        model=str(configured["model"]),
        base_url=str(configured["base_url"]),
        api_key=str(configured.get("api_key") or ""),
    )
    health = _run_health(store, selection)
    prompt = _run_prompt(selection) if bool(health.get("ok")) else {
        "ok": False,
        "status": "not_run",
        "message": "prompt check requires passing health check",
    }
    return {
        "proof_id": spec.proof_id,
        "provider": selection.provider,
        "label": spec.label,
        "kind": spec.kind,
        "model": selection.model,
        "base_url": selection.base_url.rstrip("/"),
        "key_fingerprint": _safe_key_fingerprint(selection.api_key),
        "ok": bool(health.get("ok")) and bool(prompt.get("ok")),
        "status": "pass" if bool(health.get("ok")) and bool(prompt.get("ok")) else "fail",
        "health": health,
        "prompt": prompt,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }


def _run_health(store: ProviderSettingsStore, selection: ProviderSelection) -> dict[str, Any]:
    payload = {
        "provider": selection.provider,
        "model": selection.model,
        "base_url": selection.base_url,
    }
    if selection.api_key:
        payload["api_key"] = selection.api_key
    result = store.test_provider(payload)
    return {
        "ok": bool(result.get("ok")),
        "provider": str(result.get("provider") or selection.provider),
        "model": str(result.get("model") or selection.model),
        "base_url": str(result.get("base_url") or selection.base_url).rstrip("/"),
        "key_fingerprint": _safe_key_fingerprint(selection.api_key),
        "checks": dict(result.get("checks") or {}),
        "latency_ms": int(result.get("latency_ms") or 0),
        "message": redact_text(result.get("message") or ""),
    }


def _run_prompt(selection: ProviderSelection) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        if selection.provider in {"auto", "ollama"}:
            from ollama_adapter import create_ollama_adapter  # type: ignore[import]

            adapter = create_ollama_adapter(model=selection.model, base_url=selection.base_url or DEFAULT_OLLAMA_URL)
        else:
            adapter = _build_inference_adapter(selection)
        response = adapter.call(ProofRequest(prompt_parts=[PromptPart(LIVE_PROMPT)]))
        text = str(getattr(response, "text", "") or "")
        return {
            "ok": bool(text.strip()),
            "status": "pass" if text.strip() else "empty_response",
            "text_sample": redact_text(text[:80]),
            "latency_ms": int(getattr(response, "latency_ms", 0) or ((time.perf_counter() - started) * 1000)),
            "input_tokens": int(getattr(response, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(response, "output_tokens", 0) or 0),
            "cost_cents": float(getattr(response, "cost_cents", 0.0) or 0.0),
            "request_id": str(getattr(response, "request_id", "") or ""),
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "message": redact_exception(exc),
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }


def _provider_spec(provider: str) -> ProviderSpec:
    if provider == "local_self_hosted":
        kind = str(os.environ.get("XACE_LOCAL_PROVIDER_KIND", "ollama") or "ollama").strip().lower()
        if kind in {"openai", "openai_compatible"}:
            return ProviderSpec(
                proof_id="local_self_hosted",
                provider="openai",
                label="Local/self-hosted OpenAI-compatible",
                kind="local_self_hosted",
                key_env=("XACE_LOCAL_API_KEY",),
                model_env="XACE_LOCAL_MODEL",
                base_url_env="XACE_LOCAL_BASE_URL",
                default_base_url="",
                requires_key=True,
            )
        return ProviderSpec(
            proof_id="local_self_hosted",
            provider="ollama",
            label="Local Ollama",
            kind="local_self_hosted",
            key_env=(),
            model_env="XACE_LOCAL_MODEL",
            base_url_env="XACE_LOCAL_BASE_URL",
            default_base_url=DEFAULT_OLLAMA_URL,
            requires_key=False,
        )
    return HOSTED_SPECS[provider]


def _configured_provider(spec: ProviderSpec) -> dict[str, Any]:
    api_key = _first_env_value(spec.key_env)
    model = _model_value(spec)
    base_url = str(os.environ.get(spec.base_url_env, "") or spec.default_base_url).strip().rstrip("/")
    missing: list[str] = []
    if spec.requires_key and not api_key:
        missing.append(" or ".join(spec.key_env))
    if not model:
        missing.append(spec.model_env)
    if not base_url:
        missing.append(spec.base_url_env)
    return {
        "provider": spec.provider,
        "api_key": api_key,
        "model": model,
        "base_url": base_url,
        "missing": missing,
    }


def _model_value(spec: ProviderSpec) -> str:
    value = str(os.environ.get(spec.model_env, "") or "").strip()
    if value:
        return value
    if spec.proof_id == "openai_compatible":
        return str(os.environ.get("XACE_OPENAI_MODEL", "") or "").strip()
    return value


def _first_env_value(names: tuple[str, ...]) -> str:
    for name in names:
        value = str(os.environ.get(name, "") or "").strip()
        if value:
            return value
    return ""


def _configured_secret_values(providers: list[str]) -> list[str]:
    secrets: list[str] = []
    for provider in providers:
        spec = _provider_spec(provider)
        value = _first_env_value(spec.key_env)
        if value:
            secrets.append(value)
    secrets.extend(_redaction_canaries())
    return secrets


def _safe_key_fingerprint(secret: str) -> str:
    if not secret:
        return ""
    raw = _fingerprint(secret)
    digest = raw.rsplit("(", 1)[-1].rstrip(")") if "(" in raw else raw.removeprefix("sha:")
    return "sha256:" + digest


def _finalize_report(report: dict[str, Any], *, secrets: list[str]) -> dict[str, Any]:
    redaction = _redaction_self_check(secrets)
    redacted = _redact_known_secrets(redact_value(report), secrets)
    redacted["redaction"] = redaction
    text = json.dumps(redacted, sort_keys=True, default=str)
    leaks = _secret_findings(text, secrets)
    redacted["redaction"]["report_secret_shape_count"] = len(leaks)
    redacted["redaction"]["report_secret_shape_findings"] = leaks[:10]
    redacted["redaction"]["ok"] = bool(redacted["redaction"].get("ok")) and not leaks
    if leaks:
        redacted["ok"] = False
        redacted["status"] = "fail"
        redacted["failure_code"] = "HOSTED_PROVIDER_REPORT_SECRET_SHAPE"
    return redacted


def _redaction_self_check(secrets: list[str]) -> dict[str, Any]:
    sample = {
        "api_key": secrets[0] if secrets else "",
        "nested": [{"authorization": "Bearer " + (secrets[0] if secrets else "token-not-present")}],
        "text": " ".join(secrets),
    }
    redacted = _redact_known_secrets(redact_value(sample), secrets)
    rendered = json.dumps(redacted, sort_keys=True)
    leaked = [secret for secret in secrets if secret and secret in rendered]
    return {
        "ok": not leaked,
        "known_secret_leak_count": len(leaked),
        "known_secret_values_checked": len([secret for secret in secrets if secret]),
    }


def _redact_known_secrets(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, str):
        text = redact_text(value)
        for secret in secrets:
            if secret:
                text = text.replace(secret, REDACTED_SECRET)
        return text
    if isinstance(value, dict):
        return {key: _redact_known_secrets(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_known_secrets(item, secrets) for item in value]
    return value


def _secret_findings(text: str, secrets: list[str]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for secret in secrets:
        if secret and secret in text:
            findings.append({"kind": "known_secret", "preview": REDACTED_SECRET})
    for kind, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            findings.append({"kind": kind, "preview": _preview(text, match.start(), match.end())})
    return findings


def _preview(text: str, start: int, end: int) -> str:
    snippet = text[max(0, start - 24): min(len(text), end + 24)]
    offset = start - max(0, start - 24)
    return snippet[:offset] + REDACTED_SECRET + snippet[offset + (end - start):]


def _redaction_canaries() -> list[str]:
    return [
        "sk-" + "xace-live-provider-proof-canary",
        "sk-ant-" + "xace-live-provider-proof-canary",
        "AI" + "za" + "XACEProviderProofCanary1234567890",
    ]


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
