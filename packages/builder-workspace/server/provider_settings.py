"""
provider_settings.py - local BYOK provider settings for XACE Builder.

This module owns the normal-user provider flow:
  - provider/model selection lives outside project folders;
  - API keys are stored only in local machine settings;
  - hosted providers can be tested with a real one-token-ish completion;
  - the prompt pipeline receives a real InferenceAdapter, not a mock success.
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import json
import logging
import os
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from credential_store import (
    CredentialBackend,
    CredentialStoreError,
    credential_ref,
    create_credential_store,
)
from secret_redaction import redact_exception, redact_text, redact_value

log = logging.getLogger(__name__)

_PACKAGES_ROOT = Path(__file__).resolve().parents[2]
if str(_PACKAGES_ROOT) not in sys.path:
    sys.path.insert(0, str(_PACKAGES_ROOT))

SETTINGS_VERSION = 1
DEFAULT_SETTINGS_PATH = (Path.home() / ".xace" / "provider_settings.json").resolve()
SETTINGS_PATH_ENV = "XACE_PROVIDER_SETTINGS_PATH"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
UNRESOLVED_MODEL = "unresolved"
PROVIDER_HEALTH_PROOF_SCHEMA = "xace.provider_health_proof.v1"
PROVIDER_UX_STATE_SCHEMA = "xace.provider_ux_state.v1"
AI_MODE_STATUS_SCHEMA = "xace.ai_mode_status.v1"
AI_MODE_API_BYOK = "api_byok"
AI_MODE_AGENT = "agent"
AI_MODE_LOCAL_AGENT = "local_agent"
DEFAULT_AI_MODE = AI_MODE_API_BYOK
AI_MODE_IDS = (AI_MODE_API_BYOK, AI_MODE_AGENT, AI_MODE_LOCAL_AGENT)
PRIMARY_AGENT_ADAPTER = "codex_app_server"
STORAGE_NOTE = (
    "API keys are stored in the operating system credential vault. "
    "The JSON settings file stores provider/model metadata, key fingerprints, "
    "and credential references only."
)

PROVIDER_UX_READY = "ready"
PROVIDER_UX_NO_KEY = "no_key"
PROVIDER_UX_INVALID_KEY = "invalid_key"
PROVIDER_UX_STALE_HEALTH_PROOF = "stale_health_proof"
PROVIDER_UX_QUOTA_FAILURE = "quota_failure"
PROVIDER_UX_RATE_LIMIT = "rate_limit"
PROVIDER_UX_PROVIDER_OUTAGE = "provider_outage"
PROVIDER_UX_UNTESTED = "untested"
PROVIDER_UX_INVALID_CONFIG = "invalid_config"

_PROVIDER_UX_COPY: dict[str, dict[str, str]] = {
    PROVIDER_UX_READY: {
        "label": "Ready",
        "message": "Provider is ready for prompts.",
        "action": "",
        "severity": "ok",
    },
    PROVIDER_UX_NO_KEY: {
        "label": "No provider key",
        "message": "Add a provider API key, save it, then run Test before prompting.",
        "action": "save_key_and_test",
        "severity": "blocked",
    },
    PROVIDER_UX_INVALID_KEY: {
        "label": "Invalid provider key",
        "message": "The saved provider key was rejected. Replace it, save, then run Test.",
        "action": "save_key_and_test",
        "severity": "blocked",
    },
    PROVIDER_UX_STALE_HEALTH_PROOF: {
        "label": "Stale health proof",
        "message": "Provider settings changed. Run Test again before prompting.",
        "action": "test_provider",
        "severity": "blocked",
    },
    PROVIDER_UX_QUOTA_FAILURE: {
        "label": "Quota failure",
        "message": "Provider quota or billing blocked the last Test. Add quota or choose another provider.",
        "action": "resolve_quota_or_choose_provider",
        "severity": "blocked",
    },
    PROVIDER_UX_RATE_LIMIT: {
        "label": "Rate limit",
        "message": "Provider rate limit blocked the last Test. Wait, lower traffic, or choose another provider.",
        "action": "wait_or_choose_provider",
        "severity": "blocked",
    },
    PROVIDER_UX_PROVIDER_OUTAGE: {
        "label": "Provider outage",
        "message": "Provider is unreachable or returned a service error. Try again or choose another provider.",
        "action": "retry_or_choose_provider",
        "severity": "blocked",
    },
    PROVIDER_UX_UNTESTED: {
        "label": "Health test required",
        "message": "Run Test before prompting with this provider and model.",
        "action": "test_provider",
        "severity": "blocked",
    },
    PROVIDER_UX_INVALID_CONFIG: {
        "label": "Provider setup needs attention",
        "message": "Fix provider settings, save them, then run Test before prompting.",
        "action": "save_provider_settings",
        "severity": "blocked",
    },
}

_PROVIDER_UX_STATE_BY_CODE = {
    "PROVIDER_KEY_MISSING": PROVIDER_UX_NO_KEY,
    "PROVIDER_KEY_FINGERPRINT_MISSING": PROVIDER_UX_NO_KEY,
    "PROVIDER_KEY_INVALID": PROVIDER_UX_INVALID_KEY,
    "PROVIDER_HEALTH_PROOF_STALE": PROVIDER_UX_STALE_HEALTH_PROOF,
    "PROVIDER_QUOTA_FAILURE": PROVIDER_UX_QUOTA_FAILURE,
    "PROVIDER_RATE_LIMITED": PROVIDER_UX_RATE_LIMIT,
    "PROVIDER_OUTAGE": PROVIDER_UX_PROVIDER_OUTAGE,
    "PROVIDER_LOCAL_UNREACHABLE": PROVIDER_UX_PROVIDER_OUTAGE,
    "PROVIDER_HEALTH_FAILED": PROVIDER_UX_PROVIDER_OUTAGE,
    "PROVIDER_HEALTH_UNTESTED": PROVIDER_UX_UNTESTED,
    "PROVIDER_HEALTH_PROOF_INVALID": PROVIDER_UX_INVALID_CONFIG,
    "PROVIDER_MODEL_UNRESOLVED": PROVIDER_UX_INVALID_CONFIG,
    "PROVIDER_BASE_URL_INVALID": PROVIDER_UX_INVALID_CONFIG,
}

_PROVIDER_CODE_BY_UX_STATE = {
    PROVIDER_UX_NO_KEY: "PROVIDER_KEY_MISSING",
    PROVIDER_UX_INVALID_KEY: "PROVIDER_KEY_INVALID",
    PROVIDER_UX_STALE_HEALTH_PROOF: "PROVIDER_HEALTH_PROOF_STALE",
    PROVIDER_UX_QUOTA_FAILURE: "PROVIDER_QUOTA_FAILURE",
    PROVIDER_UX_RATE_LIMIT: "PROVIDER_RATE_LIMITED",
    PROVIDER_UX_PROVIDER_OUTAGE: "PROVIDER_OUTAGE",
    PROVIDER_UX_UNTESTED: "PROVIDER_HEALTH_UNTESTED",
    PROVIDER_UX_INVALID_CONFIG: "PROVIDER_HEALTH_PROOF_INVALID",
}


@dataclass(frozen=True)
class ProviderDefinition:
    id: str
    label: str
    kind: str
    requires_key: bool
    default_model: str
    fallback_models: tuple[str, ...]
    base_url: str = ""
    chat_url: str = ""
    models_url: str = ""


@dataclass(frozen=True)
class ProviderSelection:
    provider: str
    model: str
    base_url: str
    api_key: str = ""


@dataclass(frozen=True)
class AiModeDefinition:
    id: str
    label: str
    description: str
    enabled_by_default: bool = False
    reserved: bool = False


PROVIDER_DEFINITIONS: dict[str, ProviderDefinition] = {
    "auto": ProviderDefinition(
        id="auto",
        label="Auto",
        kind="local",
        requires_key=False,
        default_model="auto",
        fallback_models=("auto",),
        base_url=DEFAULT_OLLAMA_URL,
    ),
    "ollama": ProviderDefinition(
        id="ollama",
        label="Ollama",
        kind="local",
        requires_key=False,
        default_model="auto",
        fallback_models=("auto",),
        base_url=DEFAULT_OLLAMA_URL,
    ),
    "anthropic": ProviderDefinition(
        id="anthropic",
        label="Anthropic Claude",
        kind="hosted",
        requires_key=True,
        default_model=UNRESOLVED_MODEL,
        fallback_models=(),
        base_url="https://api.anthropic.com",
        chat_url="https://api.anthropic.com/v1/messages",
        models_url="https://api.anthropic.com/v1/models",
    ),
    "openai": ProviderDefinition(
        id="openai",
        label="OpenAI",
        kind="hosted",
        requires_key=True,
        default_model=UNRESOLVED_MODEL,
        fallback_models=(),
        base_url="https://api.openai.com/v1",
        chat_url="https://api.openai.com/v1/chat/completions",
        models_url="https://api.openai.com/v1/models",
    ),
    "google": ProviderDefinition(
        id="google",
        label="Google Gemini",
        kind="hosted",
        requires_key=True,
        default_model=UNRESOLVED_MODEL,
        fallback_models=(),
        base_url="https://generativelanguage.googleapis.com/v1beta",
        models_url="https://generativelanguage.googleapis.com/v1beta/models",
    ),
    "moonshot": ProviderDefinition(
        id="moonshot",
        label="Kimi (Moonshot)",
        kind="hosted",
        requires_key=True,
        default_model=UNRESOLVED_MODEL,
        fallback_models=(),
        base_url="https://api.moonshot.ai/v1",
        chat_url="https://api.moonshot.ai/v1/chat/completions",
        models_url="https://api.moonshot.ai/v1/models",
    ),
}

AI_MODE_DEFINITIONS: dict[str, AiModeDefinition] = {
    AI_MODE_API_BYOK: AiModeDefinition(
        id=AI_MODE_API_BYOK,
        label="API / BYOK",
        description="Use the existing provider API path through InferenceAdapter.",
        enabled_by_default=True,
    ),
    AI_MODE_AGENT: AiModeDefinition(
        id=AI_MODE_AGENT,
        label="Agent Mode",
        description="Use a provider-native agent runtime when a certified adapter is wired.",
    ),
    AI_MODE_LOCAL_AGENT: AiModeDefinition(
        id=AI_MODE_LOCAL_AGENT,
        label="Local Agent Mode",
        description="Reserved for a future local XACE agent loop.",
        reserved=True,
    ),
}


HOSTED_PROVIDER_IDS = {
    provider_id
    for provider_id, definition in PROVIDER_DEFINITIONS.items()
    if definition.kind == "hosted"
}


class ProviderConfigError(RuntimeError):
    """Raised when the selected provider cannot be used for real inference."""


class ProviderSettingsStore:
    def __init__(
        self,
        path: Path | None = None,
        credential_store: CredentialBackend | None = None,
        agent_status_reader: Callable[[], Any] | None = None,
    ) -> None:
        self.path = (path or _settings_path_from_env() or DEFAULT_SETTINGS_PATH).resolve()
        self._credential_store = credential_store or create_credential_store()
        self._agent_status_reader = agent_status_reader
        self._agent_status_cache: dict[str, Any] | None = None
        self._agent_status_cache_epoch = 0.0
        self._state = self._load()

    def active_selection(self) -> ProviderSelection:
        provider = _clean_provider_id(str(self._state.get("active_provider") or "auto"))
        if provider not in PROVIDER_DEFINITIONS:
            provider = "auto"
        return self.selection(provider=provider)

    def requested_ai_mode(self) -> str:
        return _clean_ai_mode_id(str(self._state.get("ai_mode") or DEFAULT_AI_MODE))

    def active_ai_mode(self) -> str:
        requested = self.requested_ai_mode()
        if requested == AI_MODE_API_BYOK:
            return AI_MODE_API_BYOK
        if self._ai_mode_enabled(requested):
            return requested
        return AI_MODE_API_BYOK

    def configure_ai_mode(
        self,
        *,
        mode: str,
        enabled: bool | None = None,
        make_active: bool = True,
    ) -> dict[str, Any]:
        mode = _clean_ai_mode_id(mode, strict=True)
        if mode != AI_MODE_API_BYOK:
            modes = self._state.setdefault("ai_modes", {})
            entry = dict(self._ai_mode_entry(mode))
            if enabled is not None:
                entry["enabled"] = bool(enabled)
            entry["updated_at_epoch"] = int(time.time())
            modes[mode] = entry
        if make_active:
            self._state["ai_mode"] = mode
        self._state["version"] = SETTINGS_VERSION
        self._save()
        return self.payload()

    def ai_mode_options(
        self,
        *,
        provider_readiness: dict[str, Any] | None = None,
        agent_status: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        readiness = provider_readiness or self.active_readiness(refresh_models=False)
        active_mode = self.active_ai_mode()
        agent_status = agent_status or self.agent_mode_status(refresh=False)
        local_status = self._local_agent_mode_status()
        api_definition = AI_MODE_DEFINITIONS[AI_MODE_API_BYOK]
        return [
            {
                "schema": AI_MODE_STATUS_SCHEMA,
                "id": AI_MODE_API_BYOK,
                "label": api_definition.label,
                "description": api_definition.description,
                "enabled": True,
                "available": True,
                "ready": bool(readiness.get("ok")),
                "active": active_mode == AI_MODE_API_BYOK,
                "code": "" if readiness.get("ok") else str(readiness.get("code") or "PROVIDER_NOT_READY"),
                "message": str(readiness.get("message") or "Use the existing provider API path."),
                "action": str(readiness.get("action") or ""),
                "reserved": False,
            },
            agent_status,
            local_status,
        ]

    def agent_mode_status(self, *, refresh: bool = False) -> dict[str, Any]:
        enabled = self._ai_mode_enabled(AI_MODE_AGENT)
        active = self.active_ai_mode() == AI_MODE_AGENT
        adapter_status = (
            self._codex_agent_status(refresh=refresh)
            if enabled
            else _codex_agent_status_placeholder()
        )
        resolution = _resolve_agent_mode_status(enabled=enabled, adapter_status=adapter_status)
        available_adapters = [PRIMARY_AGENT_ADAPTER] if bool(adapter_status.get("available")) else []
        return {
            "schema": AI_MODE_STATUS_SCHEMA,
            "id": AI_MODE_AGENT,
            "mode": AI_MODE_AGENT,
            "label": AI_MODE_DEFINITIONS[AI_MODE_AGENT].label,
            "description": AI_MODE_DEFINITIONS[AI_MODE_AGENT].description,
            "enabled": enabled,
            "available": bool(resolution["available"]),
            "ready": bool(resolution["ready"]),
            "active": active,
            "code": str(resolution["code"]),
            "message": str(resolution["message"]),
            "action": str(resolution["action"]),
            "reserved": False,
            "primary_adapter": PRIMARY_AGENT_ADAPTER,
            "selected_adapter": PRIMARY_AGENT_ADAPTER,
            "certified_adapters": [],
            "available_adapters": available_adapters,
            "adapters": [adapter_status],
            "primary_adapter_status": adapter_status,
            "completion_scope": "codex_agent_mode",
            "feature_stage": "ag_011_codex_mcp_tool_bridge",
            "tool_transport_preference": "mcp",
            "distribution": {
                "preferred_eventual": "xace_managed_pinned_codex_runtime",
                "external_detection": "development_fallback",
                "bundling_allowed": False,
                "verification_required": [
                    "redistribution",
                    "packaging",
                    "auth_storage",
                    "updates",
                    "compatibility",
                ],
            },
        }

    def _codex_agent_status(self, *, refresh: bool = False) -> dict[str, Any]:
        now = time.time()
        if (
            self._agent_status_cache is not None
            and not refresh
            and now - self._agent_status_cache_epoch < 15.0
        ):
            return _json_clone(self._agent_status_cache)
        try:
            if self._agent_status_reader is not None:
                raw_status = self._agent_status_reader()
            else:
                from agent_host.codex_adapter import CodexAppServerAdapter  # noqa: PLC0415

                raw_status = CodexAppServerAdapter().detect_sync()
            status = raw_status.to_dict() if hasattr(raw_status, "to_dict") else dict(raw_status)
            status = _json_clone(redact_value(status))
        except Exception as exc:
            status = _codex_agent_status_error(redact_exception(exc))
        self._agent_status_cache = _json_clone(status)
        self._agent_status_cache_epoch = now
        return status

    def _local_agent_mode_status(self) -> dict[str, Any]:
        enabled = self._ai_mode_enabled(AI_MODE_LOCAL_AGENT)
        active = self.active_ai_mode() == AI_MODE_LOCAL_AGENT
        definition = AI_MODE_DEFINITIONS[AI_MODE_LOCAL_AGENT]
        return {
            "schema": AI_MODE_STATUS_SCHEMA,
            "id": AI_MODE_LOCAL_AGENT,
            "mode": AI_MODE_LOCAL_AGENT,
            "label": definition.label,
            "description": definition.description,
            "enabled": enabled,
            "available": False,
            "ready": False,
            "active": active,
            "code": "LOCAL_AGENT_DEFERRED",
            "message": "Local Agent Mode is reserved for a later implementation window.",
            "action": "continue_api_byok",
            "reserved": True,
            "adapters": [],
        }

    def _ai_mode_enabled(self, mode: str) -> bool:
        mode = _clean_ai_mode_id(mode)
        definition = AI_MODE_DEFINITIONS[mode]
        if definition.enabled_by_default:
            return True
        return bool(self._ai_mode_entry(mode).get("enabled", False))

    def _ai_mode_entry(self, mode: str) -> dict[str, Any]:
        modes = self._state.setdefault("ai_modes", {})
        entry = modes.get(_clean_ai_mode_id(mode))
        return entry if isinstance(entry, dict) else {}

    def selection(
        self,
        *,
        provider: str,
        model: str = "",
        api_key: str = "",
        base_url: str = "",
        ollama_url: str = "",
    ) -> ProviderSelection:
        provider = _clean_provider_id(provider)
        definition = _definition(provider)
        entry = self._entry(provider)
        selected_model = (
            str(model or "").strip()
            or str(entry.get("model") or "").strip()
            or definition.default_model
            or UNRESOLVED_MODEL
        )
        selected_base_url = (
            str(base_url or "").strip()
            or str(ollama_url or "").strip()
            or str(entry.get("base_url") or "").strip()
            or definition.base_url
        )
        selected_key = str(api_key or "").strip()
        if not selected_key:
            selected_key = self.secret_for(provider)
        return ProviderSelection(
            provider=provider,
            model=selected_model,
            base_url=selected_base_url.rstrip("/"),
            api_key=selected_key,
        )

    def apply_launch_overrides(
        self,
        *,
        provider: str = "auto",
        model: str = "",
        api_key: str = "",
        ollama_url: str = DEFAULT_OLLAMA_URL,
    ) -> ProviderSelection:
        provider = _clean_provider_id(provider or "auto")
        has_explicit_provider = provider != "auto"
        has_explicit_model = bool(str(model or "").strip())
        has_explicit_key = bool(str(api_key or "").strip())
        has_explicit_ollama_url = (
            bool(str(ollama_url or "").strip())
            and str(ollama_url).strip().rstrip("/") != DEFAULT_OLLAMA_URL
        )

        if has_explicit_key and not has_explicit_provider:
            provider = "anthropic"
            has_explicit_provider = True

        if has_explicit_provider or has_explicit_model or has_explicit_key or has_explicit_ollama_url:
            self.configure(
                provider=provider,
                model=model,
                api_key=api_key,
                base_url=ollama_url if provider in ("auto", "ollama") else "",
                make_active=True,
            )
        elif "active_provider" not in self._state:
            self.configure(provider="auto", model="auto", make_active=True)

        return self.active_selection()

    def configure(
        self,
        *,
        provider: str,
        model: str = "",
        api_key: str | None = None,
        base_url: str = "",
        clear_key: bool = False,
        make_active: bool = True,
    ) -> dict[str, Any]:
        provider = _clean_provider_id(provider)
        definition = _definition(provider)
        providers = self._state.setdefault("providers", {})
        entry = dict(providers.get(provider) or {})

        if model.strip():
            next_model = model.strip()
            entry["model"] = next_model
        elif "model" not in entry:
            entry["model"] = definition.default_model

        if base_url.strip():
            next_base_url = base_url.strip().rstrip("/")
            entry["base_url"] = next_base_url
        elif "base_url" not in entry and definition.base_url:
            entry["base_url"] = definition.base_url

        if clear_key and (api_key is None or not api_key.strip()):
            self._delete_credential(provider, entry)
            entry.pop("key_fingerprint", None)
            entry.pop("last_test", None)
        elif api_key is not None:
            clean_key = api_key.strip()
            if clean_key:
                ref = str(entry.get("credential_ref") or credential_ref(provider))
                try:
                    self._credential_store.set_secret(ref, clean_key)
                except CredentialStoreError:
                    raise
                except Exception as exc:
                    raise CredentialStoreError(
                        f"Could not store API key for {provider}: {redact_exception(exc)}"
                    ) from exc
                entry["credential_ref"] = ref
                entry["credential_backend"] = self._credential_store.name
                entry["credential_unsafe"] = bool(getattr(self._credential_store, "unsafe", False))
                entry.pop("secret", None)
                entry["key_fingerprint"] = _fingerprint(clean_key)

        entry["updated_at_epoch"] = int(time.time())
        providers[provider] = entry
        if make_active:
            self._state["active_provider"] = provider
        self._state["version"] = SETTINGS_VERSION
        self._save()
        return self.payload()

    def secret_for(self, provider: str) -> str:
        provider = _clean_provider_id(provider)
        entry = self._entry(provider)
        ref = str(entry.get("credential_ref") or "")
        if ref:
            try:
                return self._credential_store.get_secret(ref)
            except Exception as exc:
                log.warning(
                    "Could not read API key for provider %s from credential backend: %s",
                    provider,
                    redact_exception(exc),
                )
                return ""

        secret = entry.get("secret")
        if not isinstance(secret, str) or not secret:
            return ""
        try:
            migrated = _unprotect_secret(secret)
        except Exception:
            log.warning("Could not decode local API key for provider %s", provider)
            return ""
        if migrated:
            try:
                ref = credential_ref(provider)
                self._credential_store.set_secret(ref, migrated)
                providers = self._state.setdefault("providers", {})
                next_entry = dict(entry)
                next_entry["credential_ref"] = ref
                next_entry["credential_backend"] = self._credential_store.name
                next_entry["credential_unsafe"] = bool(getattr(self._credential_store, "unsafe", False))
                next_entry["key_fingerprint"] = str(next_entry.get("key_fingerprint") or _fingerprint(migrated))
                next_entry.pop("secret", None)
                providers[provider] = next_entry
                self._save()
            except Exception as exc:
                log.warning(
                    "Could not migrate API key for provider %s to credential backend: %s",
                    provider,
                    redact_exception(exc),
                )
        return migrated

    def payload(self, *, refresh_models: bool = False) -> dict[str, Any]:
        active = self.active_selection()
        readiness = self.active_readiness(refresh_models=refresh_models)
        agent_mode = self.agent_mode_status(refresh=refresh_models)
        provider_payloads = []
        for provider_id, definition in PROVIDER_DEFINITIONS.items():
            option = self._provider_payload(provider_id, refresh_models=refresh_models)
            provider_payloads.append(option)
        active_option = next(
            (item for item in provider_payloads if item["id"] == active.provider),
            provider_payloads[0],
        )
        return {
            "ok": True,
            "provider": active.provider,
            "current": active.model,
            "model": active.model,
            "models": active_option.get("models", []),
            "healthy": bool(active_option.get("healthy")),
            "ready": bool(readiness.get("ok")),
            "readiness": readiness,
            "url": active.base_url,
            "providers": provider_payloads,
            "settings_path": str(self.path),
            "storage_note": STORAGE_NOTE,
            "credential_backend": self._credential_store.name,
            "credential_unsafe": bool(getattr(self._credential_store, "unsafe", False)),
            "ai_mode": self.active_ai_mode(),
            "requested_ai_mode": self.requested_ai_mode(),
            "ai_modes": self.ai_mode_options(provider_readiness=readiness, agent_status=agent_mode),
            "agent_mode": agent_mode,
            "status_message": str(readiness.get("message") or active_option.get("message") or ""),
        }

    def active_readiness(self, *, refresh_models: bool = False) -> dict[str, Any]:
        selection = self.active_selection()
        return self.readiness_for(selection.provider, refresh_models=refresh_models)

    def readiness_for(self, provider: str, *, refresh_models: bool = False) -> dict[str, Any]:
        provider = _clean_provider_id(provider)
        definition = _definition(provider)
        entry = self._entry(provider)
        selection = self.selection(provider=provider)
        option = self._provider_payload(provider, refresh_models=refresh_models)
        checks = dict(option.get("checks") or {})
        base_url = _canonical_base_url(selection.base_url)

        if _model_is_unresolved(selection.model):
            return _readiness_failure(
                provider=provider,
                model=selection.model,
                kind=definition.kind,
                base_url=base_url,
                key_fingerprint=str(entry.get("key_fingerprint") or ""),
                checks=checks,
                code="PROVIDER_MODEL_UNRESOLVED",
                proof_status="missing_model",
                message=(
                    f"{definition.label} has no resolved model selected. "
                    "Choose a model manually or refresh models after saving provider access."
                ),
                action="select_model",
            )

        if not _base_url_is_valid(base_url):
            return _readiness_failure(
                provider=provider,
                model=selection.model,
                kind=definition.kind,
                base_url=base_url,
                key_fingerprint=str(entry.get("key_fingerprint") or ""),
                checks=checks,
                code="PROVIDER_BASE_URL_INVALID",
                proof_status="invalid_base_url",
                message=f"{definition.label} needs a valid http(s) base URL before prompting.",
                action="save_provider_settings",
            )

        if provider == "auto" and not bool(entry.get("last_test", {}).get("ok")):
            return _readiness_failure(
                provider=provider,
                model=selection.model,
                kind=definition.kind,
                base_url=base_url,
                key_fingerprint="",
                checks=checks,
                code="PROVIDER_HEALTH_UNTESTED",
                proof_status="untested",
                message="Choose and test a concrete prompt provider before prompting.",
                action="test_provider",
            )

        if definition.kind == "local":
            ok = bool(option.get("healthy"))
            message = (
                f"{definition.label} is ready."
                if ok else
                f"{definition.label} is not reachable. Start Ollama or choose a hosted provider."
            )
            return _attach_provider_ux_state({
                "ok": ok,
                "provider": provider,
                "model": selection.model,
                "kind": definition.kind,
                "base_url": base_url,
                "key_fingerprint": "",
                "config_hash": _provider_config_hash(selection, ""),
                "proof_status": "ready" if ok else "health_failed",
                "code": "" if ok else "PROVIDER_LOCAL_UNREACHABLE",
                "checks": checks,
                "message": message,
                "action": "" if ok else "start_ollama_or_choose_provider",
            })

        if not selection.api_key:
            return _readiness_failure(
                provider=provider,
                model=selection.model,
                kind=definition.kind,
                base_url=base_url,
                key_fingerprint=str(entry.get("key_fingerprint") or ""),
                checks={**checks, "key_present": False},
                code="PROVIDER_KEY_MISSING",
                proof_status="missing_key",
                message=f"{definition.label} needs an API key. Save a key, then run Test.",
                action="save_key_and_test",
            )

        expected_fingerprint = str(entry.get("key_fingerprint") or "").strip()
        if not expected_fingerprint:
            return _readiness_failure(
                provider=provider,
                model=selection.model,
                kind=definition.kind,
                base_url=base_url,
                key_fingerprint="",
                checks=checks,
                code="PROVIDER_KEY_FINGERPRINT_MISSING",
                proof_status="missing_key_fingerprint",
                message=f"{definition.label} needs a stored key fingerprint before prompting. Save the key, then run Test.",
                action="save_key_and_test",
            )

        last_test = entry.get("last_test") if isinstance(entry.get("last_test"), dict) else {}
        expected_hash = _provider_config_hash(selection, expected_fingerprint)
        if not last_test:
            return _readiness_failure(
                provider=provider,
                model=selection.model,
                kind=definition.kind,
                base_url=base_url,
                key_fingerprint=expected_fingerprint,
                config_hash=expected_hash,
                checks=checks,
                code="PROVIDER_HEALTH_UNTESTED",
                proof_status="untested",
                message=(
                    f"{definition.label} has not passed a health test for "
                    f"{selection.model}. Run Test before prompting."
                ),
                action="test_provider",
            )

        test_checks = last_test.get("checks") if isinstance(last_test.get("checks"), dict) else {}
        proof_missing = [
            key for key in (
                "health_proof_schema",
                "provider",
                "model",
                "base_url",
                "key_fingerprint",
                "config_hash",
                "checks",
                "tested_at_epoch",
            )
            if not last_test.get(key)
        ]
        required_checks = ("key_present", "key_valid", "model_reachable", "test_call")
        failed_checks = [key for key in required_checks if not bool(test_checks.get(key))]
        if proof_missing:
            return _readiness_failure(
                provider=provider,
                model=selection.model,
                kind=definition.kind,
                base_url=base_url,
                key_fingerprint=expected_fingerprint,
                config_hash=expected_hash,
                checks={**checks, **test_checks},
                code="PROVIDER_HEALTH_PROOF_INVALID",
                proof_status="invalid_proof",
                message=f"{definition.label} has an invalid health proof (missing {', '.join(proof_missing)}). Run Test before prompting.",
                action="test_provider",
            )

        proof_mismatch = (
            str(last_test.get("health_proof_schema") or "") != PROVIDER_HEALTH_PROOF_SCHEMA
            or str(last_test.get("provider") or "") != provider
            or str(last_test.get("model") or "") != selection.model
            or _canonical_base_url(str(last_test.get("base_url") or "")) != base_url
            or str(last_test.get("key_fingerprint") or "") != expected_fingerprint
            or str(last_test.get("config_hash") or "") != expected_hash
        )
        if proof_mismatch:
            return _readiness_failure(
                provider=provider,
                model=selection.model,
                kind=definition.kind,
                base_url=base_url,
                key_fingerprint=expected_fingerprint,
                config_hash=expected_hash,
                checks={**checks, **test_checks},
                code="PROVIDER_HEALTH_PROOF_STALE",
                proof_status="stale_proof",
                message=(
                    f"{definition.label} health proof no longer matches the exact provider, "
                    "model, base URL, or key fingerprint. Run Test before prompting."
                ),
                action="test_provider",
            )

        if not bool(last_test.get("ok")):
            failure_state = _last_test_failure_state(last_test)
            failure_code = _PROVIDER_CODE_BY_UX_STATE.get(failure_state, "PROVIDER_HEALTH_FAILED")
            failure_ux = _provider_ux_state(
                ok=False,
                code=failure_code,
                state=failure_state,
                action="test_provider",
            )
            return _readiness_failure(
                provider=provider,
                model=selection.model,
                kind=definition.kind,
                base_url=base_url,
                key_fingerprint=expected_fingerprint,
                config_hash=expected_hash,
                checks={**checks, **test_checks},
                code=failure_code,
                proof_status="health_failed",
                message=failure_ux["message"],
                action=failure_ux["action"] or "test_provider",
            )

        if failed_checks:
            return _readiness_failure(
                provider=provider,
                model=selection.model,
                kind=definition.kind,
                base_url=base_url,
                key_fingerprint=expected_fingerprint,
                config_hash=expected_hash,
                checks={**checks, **test_checks},
                code="PROVIDER_HEALTH_PROOF_INVALID",
                proof_status="invalid_proof",
                message=f"{definition.label} has an invalid health proof (failed {', '.join(failed_checks)}). Run Test before prompting.",
                action="test_provider",
            )

        return _attach_provider_ux_state({
            "ok": True,
            "provider": provider,
            "model": selection.model,
            "kind": definition.kind,
            "base_url": base_url,
            "key_fingerprint": expected_fingerprint,
            "config_hash": expected_hash,
            "proof_status": "ready",
            "code": "",
            "checks": checks,
            "message": f"{definition.label} is ready for prompts.",
            "action": "",
        })

    def test_provider(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        provider = _clean_provider_id(str(payload.get("provider") or self.active_selection().provider))
        model = str(payload.get("model") or "").strip()
        api_key = str(payload.get("api_key") or "").strip()
        base_url = str(payload.get("base_url") or payload.get("ollama_url") or "").strip()
        selection = self.selection(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
        )
        key_fingerprint = _fingerprint(selection.api_key) if selection.api_key else ""
        config_hash = _provider_config_hash(selection, key_fingerprint)
        checks = {
            "key_present": provider not in HOSTED_PROVIDER_IDS or bool(selection.api_key),
            "key_valid": False,
            "model_reachable": False,
            "test_call": False,
        }
        started = time.time()
        message = ""
        text = ""
        ok = False
        failure: dict[str, str] | None = None

        try:
            _validate_provider_selection(selection)
            if provider in ("auto", "ollama"):
                text = _probe_ollama(selection)
            else:
                if _model_is_unresolved(selection.model):
                    raise ProviderConfigError(
                        f"{_definition(provider).label} has no resolved model selected. "
                        "Choose a model manually or refresh models after saving provider access."
                    )
                if not selection.api_key:
                    raise ProviderConfigError(f"{_definition(provider).label} needs an API key.")
                checks["key_valid"] = True
                text = _probe_hosted(selection)
            ok = bool(text.strip())
            checks["model_reachable"] = ok
            checks["test_call"] = ok
            message = f"{_definition(provider).label} responded with {selection.model}."
        except Exception as exc:
            failure = _classify_provider_failure(redact_exception(exc))
            message = _human_error(exc)
            if provider in HOSTED_PROVIDER_IDS and failure["state"] == PROVIDER_UX_INVALID_KEY:
                checks["key_valid"] = False

        duration_ms = int((time.time() - started) * 1000)
        if ok:
            ux_state = _provider_ux_state(ok=True, message=message)
            failure_code = ""
            failure_state = ""
        else:
            failure = failure or _classify_provider_failure(message)
            ux_state = _provider_ux_state(
                ok=False,
                code=failure["code"],
                state=failure["state"],
                action=failure["action"],
            )
            failure_code = ux_state["code"]
            failure_state = ux_state["state"]
        result = {
            "ok": ok,
            "provider": provider,
            "model": selection.model,
            "base_url": _canonical_base_url(selection.base_url),
            "key_fingerprint": key_fingerprint,
            "config_hash": config_hash,
            "health_proof_schema": PROVIDER_HEALTH_PROOF_SCHEMA,
            "checks": checks,
            "message": redact_text(message),
            "latency_ms": duration_ms,
            "text_sample": redact_text(text[:80]),
            "failure_code": failure_code,
            "failure_state": failure_state,
            "ux_state": ux_state,
        }

        if not api_key:
            self._record_test(provider, result)
        return result

    def build_adapter(self, *, provider: str = "", model: str = "", ollama_url: str = "") -> Any:
        selection = self.selection(
            provider=provider or self.active_selection().provider,
            model=model,
            ollama_url=ollama_url,
        )
        if selection.provider in ("auto", "ollama"):
            from ollama_adapter import create_ollama_adapter  # type: ignore[import]

            if _model_is_unresolved(selection.model):
                raise ProviderConfigError(
                    f"{_definition(selection.provider).label} has no resolved model selected."
                )
            local_model = selection.model or "auto"
            return create_ollama_adapter(model=local_model, base_url=selection.base_url or DEFAULT_OLLAMA_URL)

        if not selection.api_key:
            raise ProviderConfigError(f"{_definition(selection.provider).label} needs an API key.")
        return _build_inference_adapter(selection)

    def list_models(self, provider: str = "") -> list[str]:
        provider = _clean_provider_id(provider or self.active_selection().provider)
        return list(self._provider_payload(provider, refresh_models=True).get("models", []))

    def _provider_payload(self, provider: str, *, refresh_models: bool = False) -> dict[str, Any]:
        definition = _definition(provider)
        entry = self._entry(provider)
        secret = self.secret_for(provider)
        key_present = provider not in HOSTED_PROVIDER_IDS or bool(secret)
        models = list(definition.fallback_models)
        message = ""
        model_list_ok = False

        if provider in ("auto", "ollama"):
            try:
                from ollama_adapter import OllamaAdapter, preferred_model_list  # type: ignore[import]

                adapter = OllamaAdapter(base_url=str(entry.get("base_url") or definition.base_url))
                installed = adapter.list_models()
                models = preferred_model_list(installed)
                model_list_ok = bool(installed)
                message = "Ollama is reachable." if model_list_ok else "Ollama is not reachable."
            except Exception as exc:
                message = _human_error(exc)
                model_list_ok = False
        elif refresh_models and secret:
            try:
                discovered = _discover_models(provider, secret, str(entry.get("base_url") or definition.base_url))
                if discovered:
                    models = _merge_models(discovered, models)
                    model_list_ok = True
                    message = "Model list loaded."
            except Exception as exc:
                message = _human_error(exc)
        elif definition.requires_key and not secret:
            message = "API key missing."

        last_test = entry.get("last_test") if isinstance(entry.get("last_test"), dict) else {}
        checks = dict(last_test.get("checks") or {})
        checks.setdefault("key_present", key_present)
        checks.setdefault("key_valid", False)
        checks.setdefault("model_reachable", model_list_ok)
        checks.setdefault("test_call", False)
        healthy = bool(checks.get("test_call")) if definition.kind == "hosted" else model_list_ok
        if last_test.get("message"):
            message = redact_text(str(last_test.get("message")))
        selection = self.selection(provider=provider)
        key_fingerprint = str(entry.get("key_fingerprint") or "")
        config_hash = _provider_config_hash(selection, key_fingerprint)
        hosted_ready = (
            bool(last_test.get("ok"))
            and str(last_test.get("health_proof_schema") or "") == PROVIDER_HEALTH_PROOF_SCHEMA
            and str(last_test.get("provider") or "") == provider
            and str(last_test.get("model") or "") == selection.model
            and _canonical_base_url(str(last_test.get("base_url") or "")) == _canonical_base_url(selection.base_url)
            and str(last_test.get("key_fingerprint") or "") == key_fingerprint
            and str(last_test.get("config_hash") or "") == config_hash
            and all(bool(checks.get(key)) for key in ("key_present", "key_valid", "model_reachable", "test_call"))
        )

        return {
            "id": provider,
            "label": definition.label,
            "kind": definition.kind,
            "requires_key": definition.requires_key,
            "default_model": definition.default_model,
            "base_url": str(entry.get("base_url") or definition.base_url),
            "models": models,
            "key_present": key_present,
            "key_fingerprint": str(entry.get("key_fingerprint") or ""),
            "credential_backend": str(entry.get("credential_backend") or self._credential_store.name),
            "credential_unsafe": bool(entry.get("credential_unsafe", False)),
            "healthy": healthy,
            "ready": hosted_ready if definition.kind == "hosted" else healthy,
            "checks": checks,
            "message": redact_text(message),
            "last_test_at_epoch": int(last_test.get("tested_at_epoch") or 0),
            "config_hash": config_hash,
            "proof_status": "ready" if (hosted_ready if definition.kind == "hosted" else healthy) else "not_ready",
        }

    def _record_test(self, provider: str, result: dict[str, Any]) -> None:
        providers = self._state.setdefault("providers", {})
        entry = dict(providers.get(provider) or {})
        key_fingerprint = str(result.get("key_fingerprint") or entry.get("key_fingerprint") or "")
        selection = self.selection(
            provider=provider,
            model=str(result.get("model") or ""),
            base_url=str(result.get("base_url") or ""),
        )
        config_hash = str(result.get("config_hash") or _provider_config_hash(selection, key_fingerprint))
        entry["last_test"] = {
            "health_proof_schema": PROVIDER_HEALTH_PROOF_SCHEMA,
            "ok": bool(result.get("ok")),
            "provider": provider,
            "model": str(result.get("model") or ""),
            "base_url": str(result.get("base_url") or "").rstrip("/"),
            "key_fingerprint": key_fingerprint,
            "config_hash": config_hash,
            "checks": dict(result.get("checks") or {}),
            "message": redact_text(str(result.get("message") or "")),
            "tested_at_epoch": int(time.time()),
            "latency_ms": int(result.get("latency_ms") or 0),
        }
        ux_state = result.get("ux_state") if isinstance(result.get("ux_state"), dict) else {}
        if ux_state:
            entry["last_test"]["ux_state"] = dict(ux_state)
        if not bool(result.get("ok")):
            failure_state = str(result.get("failure_state") or ux_state.get("state") or PROVIDER_UX_PROVIDER_OUTAGE)
            failure_code = str(
                result.get("failure_code")
                or ux_state.get("code")
                or _PROVIDER_CODE_BY_UX_STATE.get(failure_state, "PROVIDER_HEALTH_FAILED")
            )
            entry["last_test"]["failure_state"] = failure_state
            entry["last_test"]["failure_code"] = failure_code
        providers[provider] = entry
        self._save()

    def _entry(self, provider: str) -> dict[str, Any]:
        providers = self._state.setdefault("providers", {})
        entry = providers.get(provider)
        if isinstance(entry, dict):
            return entry
        return {}

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("version", SETTINGS_VERSION)
        data.setdefault("providers", {})
        data.setdefault("active_provider", "auto")
        data.setdefault("ai_mode", DEFAULT_AI_MODE)
        data.setdefault("ai_modes", {})
        return data

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = _sanitized_settings_payload(self._state)
        payload["storage_note"] = STORAGE_NOTE
        payload["credential_backend"] = self._credential_store.name
        payload["credential_unsafe"] = bool(getattr(self._credential_store, "unsafe", False))
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)

    def _delete_credential(self, provider: str, entry: dict[str, Any]) -> None:
        ref = str(entry.get("credential_ref") or credential_ref(provider))
        try:
            self._credential_store.delete_secret(ref)
        except Exception as exc:
            log.warning(
                "Could not delete API key for provider %s from credential backend: %s",
                provider,
                redact_exception(exc),
            )
        entry.pop("credential_ref", None)
        entry.pop("credential_backend", None)
        entry.pop("credential_unsafe", None)
        entry.pop("secret", None)


def _resolve_agent_mode_status(
    *,
    enabled: bool,
    adapter_status: dict[str, Any],
) -> dict[str, Any]:
    if not enabled:
        return {
            "available": False,
            "ready": False,
            "code": "AGENT_MODE_DISABLED",
            "message": "Agent Mode is disabled in this build; API/BYOK remains the active prompt path.",
            "action": "continue_api_byok",
        }

    installed = bool(adapter_status.get("installed"))
    metadata = adapter_status.get("metadata") or {}
    metadata = metadata if isinstance(metadata, dict) else {}
    responsive = bool(metadata.get("app_server_responsive"))
    auth_state = str(adapter_status.get("auth_state") or "unknown")
    version = str(adapter_status.get("version") or "").strip()
    model_ids = (metadata.get("model_ids") or [])
    model_count = len(model_ids) if isinstance(model_ids, list) else 0

    if not installed:
        return {
            "available": False,
            "ready": False,
            "code": "CODEX_NOT_INSTALLED",
            "message": "Codex App Server was not found. Install Codex or configure the future XACE-managed runtime path.",
            "action": "install_or_configure_codex",
        }
    if auth_state in {"missing", "expired"}:
        return {
            "available": False,
            "ready": False,
            "code": "CODEX_AUTH_REQUIRED",
            "message": "Codex is installed, but App Server reports that sign-in or API-key auth is required.",
            "action": "sign_in_to_codex",
        }
    if not responsive or not bool(adapter_status.get("available")):
        return {
            "available": False,
            "ready": False,
            "code": "CODEX_APP_SERVER_UNAVAILABLE",
            "message": "Codex was detected, but its App Server capability probe did not return a usable account/model state.",
            "action": "retry_codex_detection",
        }

    suffix = f" Version {version}." if version else ""
    model_text = f" {model_count} model(s) visible." if model_count else ""
    lifecycle_ready = bool(metadata.get("session_lifecycle_implemented"))
    turns_ready = bool(metadata.get("turn_execution_implemented"))
    bridge_ready = bool(metadata.get("mcp_tool_bridge_implemented"))
    if lifecycle_ready and turns_ready and bridge_ready:
        return {
            "available": True,
            "ready": False,
            "code": "CODEX_MCP_TOOL_BRIDGE_READY_PROPOSAL_PENDING",
            "message": (
                "Codex App Server lifecycle, turn streaming, and read-only MCP tool bridge "
                "are available; proposal ingress remains gated to AG-012."
                + suffix
                + model_text
            ),
            "action": "complete_ag_012",
        }

    if lifecycle_ready and turns_ready:
        return {
            "available": True,
            "ready": False,
            "code": "CODEX_SESSION_LIFECYCLE_READY_TOOL_BRIDGE_PENDING",
            "message": (
                "Codex App Server lifecycle and turn streaming are available; read-only "
                "MCP tool bridge remains gated to AG-011."
                + suffix
                + model_text
            ),
            "action": "complete_ag_011",
        }

    return {
        "available": True,
        "ready": False,
        "code": "CODEX_DETECTED_SESSION_LIFECYCLE_PENDING",
        "message": (
            "Codex App Server detection succeeded; session lifecycle and turns are still gated to AG-010."
            + suffix
            + model_text
        ),
        "action": "complete_ag_010",
    }


def _codex_agent_status_placeholder() -> dict[str, Any]:
    return {
        "schema": "xace.agent_host.v1",
        "provider_id": PRIMARY_AGENT_ADAPTER,
        "display_name": "Codex App Server",
        "provider_kind": "codex_app_server",
        "installed": False,
        "available": False,
        "auth_state": "unknown",
        "executable_path": None,
        "version": None,
        "min_supported_version": None,
        "account_label": None,
        "capabilities": _agent_capabilities_payload(),
        "warnings": [],
        "last_checked_at": "",
        "metadata": {
            "probe_skipped": "agent_mode_disabled",
            "app_server_responsive": False,
            "transport": "stdio_jsonl",
        },
    }


def _codex_agent_status_error(message: str) -> dict[str, Any]:
    clean = redact_text(str(message or "Codex App Server status probe failed."))
    return {
        **_codex_agent_status_placeholder(),
        "installed": True,
        "auth_state": "unknown",
        "warnings": [clean],
        "last_checked_at": "",
        "metadata": {
            "probe_error": clean,
            "app_server_responsive": False,
            "transport": "stdio_jsonl",
        },
    }


def _agent_capabilities_payload() -> dict[str, Any]:
    return {
        "supports_mcp_tools": True,
        "supports_streaming_events": True,
        "supports_thread_resume": True,
        "supports_thread_fork": True,
        "supports_compaction": True,
        "supports_cancellation": True,
        "supports_model_discovery": True,
        "supports_account_state": True,
        "supports_progressive_retrieval": True,
        "supported_tool_transports": ["mcp"],
        "xace_tools": [],
        "security_policy": {
            "allow_raw_shell": False,
            "allow_real_project_writes": False,
            "allow_direct_gde_commit": False,
            "allow_direct_runtime_mutation": False,
            "allow_credential_access": False,
            "builder_safe": True,
        },
        "warnings": [],
    }


def _json_clone(value: Any) -> dict[str, Any]:
    return json.loads(json.dumps(value))


def build_provider_adapter(
    *,
    provider: str = "auto",
    model_name: str = "",
    ollama_url: str = DEFAULT_OLLAMA_URL,
) -> Any:
    store = ProviderSettingsStore()
    return store.build_adapter(provider=provider, model=model_name, ollama_url=ollama_url)


def _readiness_failure(
    *,
    provider: str,
    model: str,
    kind: str,
    base_url: str,
    key_fingerprint: str,
    checks: dict[str, Any],
    code: str,
    proof_status: str,
    message: str,
    action: str,
    config_hash: str = "",
) -> dict[str, Any]:
    selection = ProviderSelection(provider=provider, model=model, base_url=base_url, api_key="")
    return _attach_provider_ux_state({
        "ok": False,
        "provider": provider,
        "model": model,
        "kind": kind,
        "base_url": _canonical_base_url(base_url),
        "key_fingerprint": key_fingerprint,
        "config_hash": config_hash or _provider_config_hash(selection, key_fingerprint),
        "proof_status": proof_status,
        "code": code,
        "checks": checks,
        "message": message,
        "action": action,
    })


def _attach_provider_ux_state(payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(payload)
    payload["ux_state"] = _provider_ux_state(
        ok=bool(payload.get("ok")),
        code=str(payload.get("code") or ""),
        message=str(payload.get("message") or ""),
        action=str(payload.get("action") or ""),
    )
    return payload


def _provider_ux_state(
    *,
    ok: bool,
    code: str = "",
    state: str = "",
    message: str = "",
    action: str = "",
) -> dict[str, str]:
    state = str(state or "").strip()
    if not state:
        state = PROVIDER_UX_READY if ok else _PROVIDER_UX_STATE_BY_CODE.get(code, PROVIDER_UX_PROVIDER_OUTAGE)
    copy = _PROVIDER_UX_COPY.get(state, _PROVIDER_UX_COPY[PROVIDER_UX_PROVIDER_OUTAGE])
    normalized_code = str(code or "")
    if not normalized_code and not ok:
        normalized_code = _PROVIDER_CODE_BY_UX_STATE.get(state, "PROVIDER_NOT_READY")
    return {
        "schema": PROVIDER_UX_STATE_SCHEMA,
        "state": state,
        "code": normalized_code,
        "label": copy["label"],
        "message": message if ok and message else copy["message"],
        "action": action or copy["action"],
        "severity": copy["severity"],
    }


def _last_test_failure_state(last_test: dict[str, Any]) -> str:
    ux_state = last_test.get("ux_state")
    if isinstance(ux_state, dict):
        state = str(ux_state.get("state") or "").strip()
        if state in _PROVIDER_UX_COPY:
            return state
    state = str(last_test.get("failure_state") or "").strip()
    if state in _PROVIDER_UX_COPY:
        return state
    code = str(last_test.get("failure_code") or "").strip()
    return _PROVIDER_UX_STATE_BY_CODE.get(code, PROVIDER_UX_PROVIDER_OUTAGE)


def _validate_provider_selection(selection: ProviderSelection) -> None:
    definition = _definition(selection.provider)
    if _model_is_unresolved(selection.model):
        raise ProviderConfigError(
            f"{definition.label} has no resolved model selected. "
            "Choose a model manually or refresh models after saving provider access."
        )
    if not _base_url_is_valid(selection.base_url):
        raise ProviderConfigError(f"{definition.label} needs a valid http(s) base URL.")
    if definition.kind == "hosted" and not selection.api_key:
        raise ProviderConfigError(f"{definition.label} needs an API key.")


def _canonical_base_url(base_url: str) -> str:
    return str(base_url or "").strip().rstrip("/")


def _base_url_is_valid(base_url: str) -> bool:
    parsed = urlparse(_canonical_base_url(base_url))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _provider_config_identity(selection: ProviderSelection, key_fingerprint: str) -> dict[str, str]:
    return {
        "provider": _clean_provider_id(selection.provider),
        "model": str(selection.model or "").strip(),
        "base_url": _canonical_base_url(selection.base_url),
        "key_fingerprint": str(key_fingerprint or "").strip(),
    }


def _provider_config_hash(selection: ProviderSelection, key_fingerprint: str) -> str:
    identity = _provider_config_identity(selection, key_fingerprint)
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return "sha256:" + digest[:16]


def _build_inference_adapter(selection: ProviderSelection) -> Any:
    from inference.providers.anthropic_provider import AnthropicProvider
    from inference.providers.google_provider import GoogleProvider
    from inference.providers.openai_provider import OpenAICompatibleProvider
    from inference.src.cache_key_builder import CacheKeyBuilder
    from inference.src.inference_adapter import InferenceAdapter
    from inference.src.inference_budget import InferenceBudget
    from inference.src.inference_retry_policy import InferenceRetryPolicy
    from inference.src.model_descriptor import ComplexityTier, ModelCapability, ModelDescriptor
    from inference.src.prompt_cache import PromptCache
    from inference.src.provider_registry import ProviderRegistry
    from inference.src.response_cache import ResponseCache
    from inference.src.telemetry_pipeline import TelemetryPipeline

    provider = selection.provider
    if _model_is_unresolved(selection.model):
        raise ProviderConfigError(
            f"{_definition(provider).label} has no resolved model selected. "
            "Choose a model manually or refresh models after saving provider access."
        )

    if provider == "anthropic":
        definition = _definition(provider)
        client = AnthropicProvider(
            api_key=selection.api_key,
            base_url=_anthropic_messages_url(selection.base_url or definition.base_url),
        )
    elif provider == "google":
        definition = _definition(provider)
        client = GoogleProvider(
            api_key=selection.api_key,
            thinking_level="none",
            base_url=selection.base_url or definition.base_url,
        )
    elif provider in {"openai", "moonshot"}:
        definition = _definition(provider)
        chat_url = _chat_url(selection.base_url or definition.base_url)
        client = OpenAICompatibleProvider(
            api_key=selection.api_key,
            provider_id=provider,
            base_url=chat_url,
        )
    else:
        raise ProviderConfigError(f"Unsupported provider: {provider}")

    registry = ProviderRegistry(
        config={
            "default_provider": provider,
            "logical_model_map": {
                "cheap_validation": provider,
                "standard_mutation": provider,
                "premium_reasoning": provider,
            },
            "fallback_chains": {
                provider: [],
            },
        },
        clients={provider: client},
    )

    caps = frozenset({
        ModelCapability.GENERATION,
        ModelCapability.CODE_GEN,
        ModelCapability.CRITIQUE,
        ModelCapability.REASONING,
        ModelCapability.FUNCTION_CALL,
    })
    if provider in {"anthropic", "google", "openai"}:
        caps = frozenset({*caps, ModelCapability.STRUCTURED_OUTPUT})
    for logical_name, tier in (
        ("cheap_validation", ComplexityTier.M),
        ("standard_mutation", ComplexityTier.L),
        ("premium_reasoning", ComplexityTier.XL),
    ):
        registry.register_descriptor(ModelDescriptor(
            logical_name=logical_name,
            provider=provider,
            model_id=selection.model,
            context_window_tokens=200_000,
            max_output_tokens=8_192,
            input_price_per_1k=0.0,
            output_price_per_1k=0.0,
            cache_write_price_per_1k=0.0,
            cache_read_price_per_1k=0.0,
            supports_cache_control=(provider == "anthropic"),
            default_tier=tier,
            capabilities=caps,
            notes="User selected BYOK provider/model from XACE Builder settings.",
        ))

    return InferenceAdapter(
        provider_registry=registry,
        telemetry=TelemetryPipeline(),
        budget=InferenceBudget(),
        retry_policy=InferenceRetryPolicy(),
        prompt_cache=PromptCache(),
        response_cache=ResponseCache(),
        cache_key_builder=CacheKeyBuilder(),
    )


def _probe_ollama(selection: ProviderSelection) -> str:
    from ollama_adapter import create_ollama_adapter  # type: ignore[import]

    adapter = create_ollama_adapter(
        model=selection.model or "auto",
        base_url=selection.base_url or DEFAULT_OLLAMA_URL,
    )
    request = _ProbeRequest(
        prompt_parts=[_ProbePart("Reply with XACE_READY only.")],
        system_prompt="You are a connection test. Reply with XACE_READY only.",
        max_tokens=16,
        call_label="provider_health_check",
    )
    return str(adapter.call(request).text or "")


def _probe_hosted(selection: ProviderSelection) -> str:
    adapter = _build_inference_adapter(selection)
    request = _ProbeRequest(
        prompt_parts=[_ProbePart("Reply with XACE_READY only.")],
        system_prompt="You are a connection test. Reply with XACE_READY only.",
        logical_model="cheap_validation",
        complexity_tier="TIER_M",
        max_tokens=16,
        call_label="provider_health_check",
        bypass_response_cache=True,
    )
    response = adapter.call(request)
    return str(response.text or "")


@dataclass
class _ProbePart:
    text: str
    cacheable: bool = False
    label: str = "probe"


@dataclass
class _ProbeRequest:
    prompt_parts: list[_ProbePart]
    system_prompt: str = ""
    logical_model: str = "cheap_validation"
    complexity_tier: str = "TIER_M"
    max_tokens: int = 16
    temperature: float = 0.0
    session_id: str = "provider-health"
    call_label: str = "provider_health_check"
    request_id: str = "provider-health"
    cgs_structural_hash: str = ""
    intent_class: str = "ProviderHealthCheck"
    bypass_response_cache: bool = True

    def full_prompt_text(self) -> str:
        return "\n".join(part.text for part in self.prompt_parts)

    def cacheable_text(self) -> str:
        return "\n".join(part.text for part in self.prompt_parts if part.cacheable)


def _discover_models(provider: str, api_key: str, base_url: str) -> list[str]:
    from inference.src.provider_model_discovery import discover_provider_models

    definition = _definition(provider)
    models_url = definition.models_url
    if provider in {"openai", "moonshot"}:
        models_url = _models_url(base_url or definition.base_url)
    return discover_provider_models(
        provider=provider,
        api_key=api_key,
        base_url=base_url or definition.base_url,
        models_url=models_url,
        timeout=8.0,
    )


def _merge_models(primary: list[str], fallback: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for model in primary + fallback:
        if model and model not in seen:
            seen.add(model)
            merged.append(model)
    return merged


def _model_is_unresolved(model: str) -> bool:
    value = str(model or "").strip().lower()
    return not value or value == UNRESOLVED_MODEL


def _definition(provider: str) -> ProviderDefinition:
    provider = _clean_provider_id(provider)
    definition = PROVIDER_DEFINITIONS.get(provider)
    if definition is None:
        raise ProviderConfigError(f"Unsupported provider: {provider}")
    return definition


def _clean_ai_mode_id(mode: str, *, strict: bool = False) -> str:
    mode = str(mode or DEFAULT_AI_MODE).strip().lower().replace("-", "_")
    aliases = {
        "api": AI_MODE_API_BYOK,
        "byok": AI_MODE_API_BYOK,
        "api_byok_mode": AI_MODE_API_BYOK,
        "agent_mode": AI_MODE_AGENT,
        "codex": AI_MODE_AGENT,
        "codex_agent": AI_MODE_AGENT,
        "local": AI_MODE_LOCAL_AGENT,
        "local_agent_mode": AI_MODE_LOCAL_AGENT,
    }
    cleaned = aliases.get(mode, mode)
    if cleaned in AI_MODE_DEFINITIONS:
        return cleaned
    if strict:
        raise ProviderConfigError(f"Unsupported AI mode: {mode}")
    return DEFAULT_AI_MODE


def _clean_provider_id(provider: str) -> str:
    provider = str(provider or "auto").strip().lower()
    aliases = {
        "claude": "anthropic",
        "anthropic_claude": "anthropic",
        "gemini": "google",
        "google_gemini": "google",
        "kimi": "moonshot",
        "kimi_moonshot": "moonshot",
    }
    return aliases.get(provider, provider)


def _chat_url(base_url: str) -> str:
    value = (base_url or "").rstrip("/")
    if value.endswith("/chat/completions"):
        return value
    return value + "/chat/completions"


def _anthropic_messages_url(base_url: str) -> str:
    value = (base_url or "").rstrip("/")
    if value.endswith("/v1/messages"):
        return value
    if value.endswith("/v1"):
        return value + "/messages"
    return value + "/v1/messages"


def _models_url(base_url: str) -> str:
    value = (base_url or "").rstrip("/")
    if value.endswith("/models"):
        return value
    if value.endswith("/chat/completions"):
        value = value[: -len("/chat/completions")]
    return value + "/models"


def _settings_path_from_env() -> Path | None:
    configured = os.environ.get(SETTINGS_PATH_ENV, "").strip()
    if not configured:
        return None
    return Path(configured).expanduser()


def _sanitized_settings_payload(state: dict[str, Any]) -> dict[str, Any]:
    payload = redact_value(json.loads(json.dumps(state)))
    providers = payload.get("providers")
    if isinstance(providers, dict):
        for entry in providers.values():
            if isinstance(entry, dict):
                entry.pop("secret", None)
    return payload


def _protect_secret(secret: str) -> str:
    data = secret.encode("utf-8")
    protected = _xor_with_local_key(data)
    return "xace1." + base64.urlsafe_b64encode(protected).decode("ascii")


def _unprotect_secret(token: str) -> str:
    if not token.startswith("xace1."):
        return ""
    data = base64.urlsafe_b64decode(token.split(".", 1)[1].encode("ascii"))
    return _xor_with_local_key(data).decode("utf-8")


def _xor_with_local_key(data: bytes) -> bytes:
    key_material = "|".join([
        "xace-provider-settings-v1",
        getpass.getuser(),
        socket.gethostname(),
    ]).encode("utf-8", errors="ignore")
    key = hashlib.sha256(key_material).digest()
    return bytes(byte ^ key[index % len(key)] for index, byte in enumerate(data))


def _fingerprint(secret: str) -> str:
    clean = secret.strip()
    digest = hashlib.sha256(clean.encode("utf-8")).hexdigest()[:8]
    if len(clean) <= 8:
        return f"sha:{digest}"
    return f"{clean[:4]}...{clean[-4:]} ({digest})"


def _classify_provider_failure(text: str) -> dict[str, str]:
    lower = str(text or "").lower()
    if (
        "needs an api key" in lower
        or "api key missing" in lower
        or "missing api key" in lower
        or "no api key" in lower
    ):
        return _provider_ux_state(
            ok=False,
            code="PROVIDER_KEY_MISSING",
            state=PROVIDER_UX_NO_KEY,
            action="save_key_and_test",
        )
    if (
        "401" in lower
        or "403" in lower
        or "unauthorized" in lower
        or "unauthorised" in lower
        or "authentication" in lower
        or "invalid api key" in lower
        or "invalid key" in lower
        or "permission denied" in lower
    ):
        return _provider_ux_state(
            ok=False,
            code="PROVIDER_KEY_INVALID",
            state=PROVIDER_UX_INVALID_KEY,
            action="save_key_and_test",
        )
    if (
        "insufficient_quota" in lower
        or "quota" in lower
        or "billing" in lower
        or "credit" in lower
        or "payment required" in lower
    ):
        return _provider_ux_state(
            ok=False,
            code="PROVIDER_QUOTA_FAILURE",
            state=PROVIDER_UX_QUOTA_FAILURE,
            action="resolve_quota_or_choose_provider",
        )
    if (
        "429" in lower
        or "rate limit" in lower
        or "rate-limit" in lower
        or "too many requests" in lower
        or "requests per minute" in lower
    ):
        return _provider_ux_state(
            ok=False,
            code="PROVIDER_RATE_LIMITED",
            state=PROVIDER_UX_RATE_LIMIT,
            action="wait_or_choose_provider",
        )
    return _provider_ux_state(
        ok=False,
        code="PROVIDER_OUTAGE",
        state=PROVIDER_UX_PROVIDER_OUTAGE,
        action="retry_or_choose_provider",
    )


def _human_error(exc: Exception) -> str:
    text = redact_exception(exc)
    failure = _classify_provider_failure(text)
    if failure["state"] in {
        PROVIDER_UX_NO_KEY,
        PROVIDER_UX_INVALID_KEY,
        PROVIDER_UX_QUOTA_FAILURE,
        PROVIDER_UX_RATE_LIMIT,
    }:
        return failure["message"]
    if "404" in text:
        return "The selected model or endpoint was not found."
    if (
        "timed out" in text.lower()
        or "timeout" in text.lower()
        or "connection" in text.lower()
        or "unreachable" in text.lower()
        or "503" in text
        or "502" in text
        or "500" in text
        or "service unavailable" in text.lower()
    ):
        return failure["message"]
    if len(text) > 240:
        return text[:237] + "..."
    return text
