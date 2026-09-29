"""AG-025 provider-managed auth. No credential files, persistence, or logging.

Only the operator HTTP control plane may call this controller. Its dedicated
App Server connection never starts a thread, model turn, shell, or tool.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import re
import threading
import time
from dataclasses import replace
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit, parse_qsl

from .auth_contracts import AgentAuthSnapshot, AgentLoginFlow

_PLANS = {"free", "go", "plus", "pro", "prolite", "team", "business",
          "enterprise", "edu", "edu_plus", "edu_pro", "unknown",
          "self_serve_business_prolite", "self_serve_business_usage_based",
          "ent26", "enterprise_cbp_automation", "enterprise_cbp_usage_based"}
_FLOWS = {"browser": "chatgpt", "device_code": "chatgptDeviceCode"}


class CodexAuthController:
    def __init__(self, client_factory: Callable[[], Any], *,
                 invalidate_sessions: Callable[[], None] = lambda: None,
                 clock: Callable[[], float] = time.monotonic,
                 login_timeout: float = 300.0) -> None:
        self._factory = client_factory
        self._invalidate = invalidate_sessions
        self._clock = clock
        self._timeout = login_timeout
        self._client = None
        self._lock = threading.RLock()
        self._status = AgentAuthSnapshot(provider_id="codex_app_server")
        self._login_id: str | None = None
        self._deadline = 0.0
        self._identity = ""
        self._last_refresh = 0.0

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._status.to_dict()

    def _set(self, **changes: Any) -> None:
        self._status = replace(self._status, revision=self._status.revision + 1, **changes)

    def _connect(self) -> Any:
        if self._client is None:
            self._client = self._factory()
        if self._client.closed:
            raise RuntimeError("provider_disconnected")
        return self._client

    def refresh(self) -> dict[str, Any]:
        with self._lock:
            try:
                self._refresh(force=True)
            except Exception as exc:
                self._fail(exc)
            return self.snapshot()

    def _refresh(self, *, force: bool = False) -> None:
        client = self._connect()
        result = client.request("account/read", {"refreshToken": force})
        account = result.get("account")
        if account is not None and not isinstance(account, Mapping):
            raise ValueError("malformed_provider_response")
        account = account or {}
        kind = account.get("type")
        state = ("signed_in" if kind == "chatgpt" else
                 "api_key" if kind == "apiKey" else
                 "signed_out" if result.get("requiresOpenaiAuth") is True else "unknown")
        # Account identifiers are used only for invalidation, never exposed or saved.
        identity = hashlib.sha256(json.dumps(
            [kind, account.get("email"), account.get("workspaceId"),
             account.get("accountId"), account.get("planType")],
            sort_keys=True, default=str).encode()).hexdigest()
        keep_failure = (
            not force and identity == self._identity
            and self._status.error_code in {"auth_expired", "workspace_restricted"}
        )
        if self._identity and identity != self._identity:
            self._invalidate()
            self._set(limits={}, usage={})
        self._identity = identity
        email = str(account.get("email") or "")
        masked = ""
        if re.fullmatch(r"[A-Za-z0-9._+%-]{1,128}@[A-Za-z0-9.-]{1,128}", email):
            local, domain = email.split("@")
            masked = local[:1] + "***@" + domain
        self._set(state="expired" if keep_failure and self._status.error_code == "auth_expired" else state, account={
            "type": kind if kind in {"chatgpt", "apiKey"} else "unknown",
            "email": masked,
            "plan_type": account.get("planType") if account.get("planType") in _PLANS else "unknown",
        }, error_code=self._status.error_code if keep_failure else None,
           recovery_action=self._status.recovery_action if keep_failure else None)
        self._last_refresh = self._clock()
        if state == "signed_in":
            limits = client.optional_request("account/rateLimits/read", {})
            self._set(limits=_limits(limits), usage=_usage(client.optional_request("account/usage/read", {})))
        else:
            self._set(limits={}, usage={})

    def start_login(self, flow: str) -> dict[str, Any]:
        flow = AgentLoginFlow(flow).value
        with self._lock:
            if self._login_id:
                return {**self.snapshot(), "action_error": "login_already_pending"}
            try:
                client = self._connect()
                result = client.request("account/login/start", {"type": _FLOWS[flow]})
                login_id = result.get("loginId")
                if not isinstance(login_id, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,128}", login_id):
                    raise ValueError("malformed_provider_response")
                self._login_id = login_id
                if result.get("type") != _FLOWS[flow]:
                    raise ValueError("malformed_provider_response")
                url = _login_url(result.get("authUrl") if flow == "browser" else result.get("verificationUrl"))
                challenge = {"flow": flow, "url": url, "ephemeral": True,
                             "browser_launch": "client_owned_manual_link_available"}
                if flow == "device_code":
                    code = result.get("userCode")
                    if not isinstance(code, str) or not re.fullmatch(r"[A-Z0-9-]{4,32}", code):
                        raise ValueError("malformed_provider_response")
                    challenge["user_code"] = code
                self._deadline = self._clock() + self._timeout
                self._set(login_state="pending", error_code=None, recovery_action=None)
                # Challenge is returned once, never kept in status/history/logs.
                return {**self.snapshot(), "challenge": challenge}
            except Exception as exc:
                self._fail(exc)
                return self.snapshot()

    def cancel_login(self) -> dict[str, Any]:
        with self._lock:
            if not self._login_id:
                return self.snapshot()
            try:
                result = self._connect().request("account/login/cancel", {"loginId": self._login_id})
                if result.get("status") not in {"canceled", "notFound"}:
                    raise ValueError("malformed_provider_response")
                self._login_id = None
                self._set(login_state="cancelled", error_code=None, recovery_action="retry_login")
                self._refresh()
            except Exception as exc:
                self._fail(exc)
            return self.snapshot()

    def logout(self) -> dict[str, Any]:
        with self._lock:
            # Close cached model connections even if logout fails.
            self._invalidate()
            try:
                if self._login_id:
                    self._connect().request("account/login/cancel", {"loginId": self._login_id})
                self._login_id = None
                self._connect().request("account/logout", {})
                self._identity = ""
                self._set(state="signed_out", login_state="idle", account={}, limits={}, usage={},
                          error_code=None, recovery_action="sign_in")
            except Exception as exc:
                self._fail(exc)
            return self.snapshot()

    def poll(self) -> dict[str, Any]:
        with self._lock:
            if self._client is None:
                return self.snapshot()
            try:
                if self._login_id and self._clock() >= self._deadline:
                    self.cancel_login()
                    self._set(login_state="expired", error_code="login_expired",
                              recovery_action="retry_login")
                    return self.snapshot()
                for _ in range(64):
                    event = self._connect().read_notification(0.01)
                    if event is None:
                        break
                    if "id" in event:
                        # This connection never accepts host-managed tokens or tools.
                        raise RuntimeError("unsupported_provider_request")
                    self._event(event)
                    if self._client is None:
                        return self.snapshot()
                if not self._login_id and self._clock() - self._last_refresh >= 2.0:
                    self._refresh()
            except Exception as exc:
                self._fail(exc)
            return self.snapshot()

    def _event(self, event: Mapping[str, Any]) -> None:
        method = event.get("method")
        params = event.get("params") or {}
        if not isinstance(params, Mapping):
            raise ValueError("malformed_provider_response")
        if method == "account/login/completed":
            if not self._login_id or params.get("loginId") != self._login_id:
                return
            self._login_id = None
            if params.get("success") is True:
                self._refresh(force=True)
                if self._status.state != "signed_in":
                    raise RuntimeError("reauth required after login")
                self._set(login_state="completed")
            else:
                self._fail(RuntimeError(str(params.get("error") or "login_failed")))
        elif method == "account/updated":
            self._invalidate()
            self._refresh()
        elif method == "account/rateLimits/updated":
            self._set(limits=_limits(params))

    def mark_account_dirty(self) -> None:
        with self._lock:
            self._last_refresh = float("-inf")

    def observe_failure(self, error: Any) -> None:
        """Map turn authorization/quota failures without retaining provider text."""
        with self._lock:
            code, action = _failure(error)
            if code in {"auth_expired", "workspace_restricted", "rate_limited"}:
                if code in {"auth_expired", "workspace_restricted"}:
                    self._invalidate()
                self._set(error_code=code, recovery_action=action,
                          state="expired" if code == "auth_expired" else self._status.state)

    def _fail(self, error: Any) -> None:
        code, action = _failure(error)
        self._drop_client()
        if code in {"auth_expired", "workspace_restricted"}:
            self._invalidate()
        self._set(state="expired" if code == "auth_expired" else "unavailable",
                  login_state="failed", account={}, limits={}, usage={}, error_code=code,
                  recovery_action=action)

    def _drop_client(self) -> None:
        if self._client is not None:
            with contextlib.suppress(Exception):
                if self._login_id and not self._client.closed:
                    self._client.request("account/login/cancel", {"loginId": self._login_id})
            with contextlib.suppress(Exception):
                self._client.close()
        self._client = None
        self._login_id = None

    def close(self) -> None:
        with self._lock:
            self._drop_client()
            self._identity = ""
            self._set(state="unknown", login_state="idle", account={}, limits={}, usage={},
                      error_code=None, recovery_action=None)


def _failure(error: Any) -> tuple[str, str]:
    text = str(error).lower()
    if any(word in text for word in ("expired", "unauthorized", "401", "reauth")):
        return "auth_expired", "sign_in"
    if any(word in text for word in ("workspace", "organization", "forbidden", "403", "entitlement")):
        return "workspace_restricted", "contact_workspace_admin"
    if any(word in text for word in ("429", "rate limit", "quota", "usagelimit")):
        return "rate_limited", "wait_or_switch_api_byok"
    if any(word in text for word in ("unsupported", "unknown variant", "method not found", "-32601", "-32602")):
        return "flow_unsupported", "try_other_flow_or_update_runtime"
    if "browser" in text:
        return "browser_unavailable", "try_device_code"
    if "not found" in text:
        return "runtime_missing", "configure_runtime"
    return "provider_unavailable", "retry"


def _login_url(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 8192:
        raise ValueError("malformed_provider_response")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or parsed.hostname not in {"auth.openai.com", "chatgpt.com"}
            or parsed.username or parsed.password or parsed.port not in {None, 443}
            or parsed.fragment or any(ord(c) < 32 for c in value)):
        raise ValueError("unsafe_provider_login_url")
    for key, _ in parse_qsl(parsed.query):
        normalized = key.lower().replace("_", "").replace("-", "")
        if normalized in {"token", "accesstoken", "refreshtoken", "idtoken",
                          "secret", "password", "apikey", "authorization"}:
            raise ValueError("unsafe_provider_login_url")
    return value


def _limits(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("unavailable"):
        return {"available": False}
    result: dict[str, Any] = {"available": isinstance(value.get("rateLimits"), Mapping)}
    source = value.get("rateLimits") or {}
    if not isinstance(source, Mapping):
        return {"available": False}
    for window in ("primary", "secondary"):
        raw = source.get(window)
        if isinstance(raw, Mapping):
            result[window] = {key: raw[key] for key in
                              ("usedPercent", "windowDurationMins", "resetsAt")
                              if type(raw.get(key)) in {int, float} and math.isfinite(raw[key])
                              and raw[key] >= 0}
    result["limit_reached"] = any(result.get(w, {}).get("usedPercent", 0) >= 100
                                  for w in ("primary", "secondary"))
    return result



def _usage(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("unavailable"):
        return {"available": False}
    raw = value.get("usage", value)
    if not isinstance(raw, Mapping):
        return {"available": False}
    counts = {key: raw[key] for key in ("inputTokens", "outputTokens", "totalTokens", "cachedInputTokens")
              if type(raw.get(key)) is int and raw[key] >= 0}
    return {"available": bool(counts), "provider_reported": True, **counts}
