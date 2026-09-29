"""AG-028 content-free local diagnostics and immutable, consented exports.

Never import/read chat history, provider auth files, logs, or project contents.
Raw collector values are projected onto a fixed schema, never recursively copied.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .codex_compatibility import PROFILE

DIAGNOSTICS_SCHEMA = "xace.agent_diagnostics.v1"
SUPPORT_SCHEMA = "xace.agent_support_bundle.v1"
AGENT_BUILD = "ag_028_privacy_support.v1"
PREVIEW_TTL_SECONDS = 300
MAX_PREVIEWS = 4
MAX_BUNDLE_BYTES = 16384
CATEGORIES = ("runtime", "auth", "compatibility", "provider", "mcp", "persistence", "validation")
ERROR_CODES = frozenset({
    "not_active", "invalid_record_schema", "runtime_revoked", "executable_missing", "platform_mismatch",
    "architecture_mismatch", "digest_mismatch", "executable_unreadable", "verified_active",
    "schema_reverification_required", "unsupported_version", "schema_incompatible", "schema_mismatch",
    "runtime_verification_failed", "cancelled", "auth_expired", "workspace_restricted", "rate_limited",
    "flow_unsupported", "browser_unavailable", "provider_unavailable", "login_expired", "runtime_missing",
    "protocol_error", "process_exited", "request_timeout", "write_timeout", "write_failed", "read_failed",
    "stream_backpressure", "notification_backpressure", "malformed_frame", "response_id_mismatch",
    "unexpected_response", "oversized_or_truncated_frame", "outbound_frame_too_large", "stale_session",
    "stale_event", "malformed_event", "turn_idle_timeout", "provider_error", "mcp_unavailable",
    "store_unavailable", "store_schema_mismatch", "store_operation_failed", "validation_rejected",
    "PREVIEW_CREATED", "SESSION_MISMATCH", "PROVIDER_MISMATCH", "STALE_CGS_HASH", "DIRECT_COMMIT_DENIED",
    "NO_OP", "MALFORMED_PROPOSAL", "unknown_error",
})


@dataclass(frozen=True)
class SupportPreview:
    payload: bytes
    digest: str
    expires_at: float


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _choice(value: Any, allowed, fallback="unknown") -> str:
    return value if isinstance(value, str) and value in allowed else fallback


def _code(value: Any) -> str | None:
    return None if value is None or value == "" else _choice(value, ERROR_CODES, "unknown_error")


def _count(value: Any) -> int | None:
    return min(value, 10000) if type(value) is int and value >= 0 else None


class AgentSupportDiagnostics:
    def __init__(self, *, runtime: Callable[[], Any], adapter: Callable[[], Any],
                 persistence: Callable[[], Any], validation: Callable[[], Any],
                 clock: Callable[[], float] = time.monotonic):
        self._collectors = dict(runtime=runtime, adapter=adapter, persistence=persistence, validation=validation)
        self._clock = clock
        self._previews: dict[str, SupportPreview] = {}
        self._lock = threading.RLock()

    def diagnostics(self) -> dict[str, Any]:
        values = {}
        for name, collector in self._collectors.items():
            try:
                values[name] = _mapping(collector())
            except Exception:
                # Neither exception text nor traceback is a support-bundle input.
                values[name] = {"collector_failed": True}
        setup, adapter, store, validation = (values[k] for k in ("runtime", "adapter", "persistence", "validation"))
        runtime = _mapping(setup.get("runtime"))
        active = _mapping(runtime.get("active"))
        health = _mapping(runtime.get("active_health"))
        job = _mapping(setup.get("job"))
        auth = _mapping(adapter.get("auth"))
        version = active.get("version")
        fingerprint = active.get("schema_fingerprint")
        health_code = _code(health.get("code"))
        adapter_code = _code(adapter.get("error_code"))
        checks = {
            "runtime": {"state": "unavailable" if setup.get("collector_failed") else "ready" if runtime.get("ready") is True else "not_ready",
                        "error_code": _code(job.get("error_code")) or health_code,
                        "metadata_error": bool(runtime.get("state_error")),
                        "job_state": _choice(job.get("state"), {"idle", "running", "cancelling", "cancelled", "complete", "failed"})},
            "auth": {"state": _choice(auth.get("state"), {"unknown", "signed_in", "signed_out", "expired", "api_key", "unavailable"}),
                     "login_state": _choice(auth.get("login_state"), {"idle", "pending", "completed", "cancelled", "failed", "expired"}),
                     "error_code": _code(auth.get("error_code"))},
            "compatibility": {"state": "blocked" if health_code in {"schema_reverification_required", "unsupported_version", "runtime_revoked", "schema_mismatch"} or adapter_code == "schema_incompatible" else
                              "verified_pin" if active.get("compatibility_profile") == PROFILE and runtime.get("ready") is True else "unverified",
                              "required_profile": PROFILE, "real_account_certified": False},
            "provider": {"state": "unavailable" if adapter.get("collector_failed") else _choice(adapter.get("state"), {"idle", "connected", "failed"}),
                         "error_code": adapter_code, "active_connections": _count(adapter.get("active_connections")),
                         "active_turns": _count(adapter.get("active_turns"))},
            "mcp": {"state": _choice(adapter.get("mcp_state"), {"not_connected", "connected", "failed", "checking"}),
                    "active_bridges": _count(adapter.get("active_bridges"))},
            "persistence": {"state": _choice(store.get("state"), {"ready", "unavailable", "schema_mismatch"}),
                            "error_code": _code(store.get("error_code")) or ("store_unavailable" if store.get("collector_failed") else None),
                            "last_operation_failed": store.get("last_operation_failed") is True},
            "validation": {"state": _choice(validation.get("state"), {"not_observed", "preview_created", "no_op", "rejected"}),
                           "error_code": _code(validation.get("error_code"))},
        }
        return {
            "schema": DIAGNOSTICS_SCHEMA, "agent_build": AGENT_BUILD, "provider": "codex_app_server",
            "runtime": {"version": version if isinstance(version, str) and re.fullmatch(r"\d{1,4}\.\d{1,4}\.\d{1,4}", version) else None,
                        "provenance": _choice(active.get("provenance_basis"), {"user_confirmed_official_install"}),
                        "schema_fingerprint": fingerprint if isinstance(fingerprint, str) and re.fullmatch(r"[0-9a-f]{64}", fingerprint) else None,
                        "developer_override_active": setup.get("override_active") is True},
            "checks": checks,
            "collection": "local_cached_state_and_store_metadata_only_no_provider_probe",
            "excluded": ["prompts", "project_content", "proposals", "chat_history", "tool_payloads", "credentials",
                         "account_identity", "auth_files", "login_challenges", "paths", "logs", "environment", "session_ids"],
        }

    def _prune(self):
        now = self._clock()
        self._previews = {key: value for key, value in self._previews.items() if value.expires_at > now}

    def prepare(self, *, confirm: bool) -> dict[str, Any]:
        if confirm is not True:
            raise ValueError("consent_required")
        payload = (json.dumps({"schema": SUPPORT_SCHEMA, "diagnostics": self.diagnostics(),
                               "sharing": "local_download_only_no_automatic_upload"}, sort_keys=True, indent=2) + "\n").encode()
        if len(payload) > MAX_BUNDLE_BYTES:
            raise ValueError("bundle_limit")
        digest = hashlib.sha256(payload).hexdigest()
        with self._lock:
            self._prune()
            while len(self._previews) >= MAX_PREVIEWS:
                self._previews.pop(next(iter(self._previews)))
            identifier = secrets.token_urlsafe(24)
            self._previews[identifier] = SupportPreview(payload, digest, self._clock() + PREVIEW_TTL_SECONDS)
        return {"preview_id": identifier, "sha256": digest, "expires_in_seconds": PREVIEW_TTL_SECONDS,
                "content": payload.decode(), "bytes": len(payload)}

    def export(self, *, preview_id: str, sha256: str, confirm: bool) -> bytes:
        if confirm is not True or not isinstance(preview_id, str) or not isinstance(sha256, str):
            raise ValueError("consent_required")
        with self._lock:
            self._prune()
            preview = self._previews.get(preview_id)
            if preview is None or not secrets.compare_digest(preview.digest, sha256):
                raise ValueError("preview_missing_expired_or_changed")
            self._previews.pop(preview_id)
            return preview.payload

    def clear(self) -> None:
        with self._lock:
            self._previews.clear()
