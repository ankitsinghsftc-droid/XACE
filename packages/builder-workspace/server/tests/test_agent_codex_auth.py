import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))

from agent_host.codex_auth import CodexAuthController
from agent_host.codex_adapter import CodexAppServerAdapter, CodexExecutableCandidate
from agent_auth_routes import auth_router


CANARY = "opaque-private-credential-canary-AG025"


class Client:
    def __init__(self):
        self.closed = False
        self.calls = []
        self.events = []
        self.account = None
        self.failure = None
        self.extra = {}
        self.serial = 0
        self.limits = {"rateLimits": {"primary": {"usedPercent": 25, "resetsAt": 500}}}

    def request(self, method, params):
        self.calls.append((method, params))
        if self.failure:
            raise RuntimeError(self.failure)
        if method == "initialize":
            return {}
        if method == "account/read":
            return {"account": self.account, "requiresOpenaiAuth": True, **self.extra}
        if method == "account/login/start":
            self.serial += 1
            result = {"type": params["type"], "loginId": f"login-{self.serial}", **self.extra}
            if params["type"] == "chatgpt":
                result["authUrl"] = "https://auth.openai.com/oauth/authorize?state=nonce"
            else:
                result.update(verificationUrl="https://auth.openai.com/codex/device",
                              userCode="ABCD-1234")
            return result
        if method == "account/login/cancel":
            return {"status": "canceled"}
        if method == "account/logout":
            self.account = None
            return {}
        raise AssertionError(method)

    def optional_request(self, method, params):
        self.calls.append((method, params))
        return self.limits if method == "account/rateLimits/read" else {"unavailable": True}

    def read_notification(self, timeout_seconds):
        if self.closed:
            raise RuntimeError("provider_disconnected")
        return self.events.pop(0) if self.events else None

    def notify(self, method, params):
        self.calls.append((method, params))

    def close(self):
        self.closed = True


class CodexAuthTests(unittest.TestCase):
    def setUp(self):
        self.client = Client()
        self.invalidate = Mock()
        self.now = 0.0
        self.controller = CodexAuthController(lambda: self.client,
            invalidate_sessions=self.invalidate, clock=lambda: self.now, login_timeout=10)

    def test_idle_poll_never_starts_provider(self):
        factory = Mock()
        controller = CodexAuthController(factory)
        self.assertEqual(controller.poll()["state"], "unknown")
        factory.assert_not_called()

    def test_browser_start_challenge_is_not_kept_in_snapshot(self):
        result = self.controller.start_login("browser")
        self.assertEqual(result["login_state"], "pending")
        self.assertEqual(result["challenge"]["flow"], "browser")
        self.assertNotIn("challenge", self.controller.snapshot())
        self.assertNotIn("auth.openai.com", json.dumps(self.controller.snapshot()))
        self.assertNotIn("login-1", json.dumps(result))

    def test_device_flow_is_provider_owned(self):
        result = self.controller.start_login("device_code")
        self.assertEqual(result["challenge"]["user_code"], "ABCD-1234")
        self.assertEqual(self.client.calls[0], ("account/login/start", {"type": "chatgptDeviceCode"}))
        self.assertNotIn("ABCD-1234", json.dumps(self.controller.snapshot()))

    def test_duplicate_start_does_not_replace_pending_login(self):
        self.controller.start_login("browser")
        result = self.controller.start_login("device_code")
        self.assertEqual(result["action_error"], "login_already_pending")
        self.assertEqual(self.client.serial, 1)

    def test_cancel_retry_and_stale_completion(self):
        self.controller.start_login("browser")
        self.assertEqual(self.controller.cancel_login()["login_state"], "cancelled")
        self.controller.start_login("device_code")
        self.client.events.append({"method": "account/login/completed",
                                   "params": {"loginId": "login-1", "success": True}})
        self.assertEqual(self.controller.poll()["login_state"], "pending")
        self.assertEqual(self.client.serial, 2)

    def test_completion_refreshes_identity_without_restart(self):
        self.controller.start_login("browser")
        self.client.account = {"type": "chatgpt", "email": "alice@example.com", "planType": "plus"}
        self.client.events.append({"method": "account/login/completed",
                                   "params": {"loginId": "login-1", "success": True}})
        result = self.controller.poll()
        self.assertEqual(result["login_state"], "completed")
        self.assertEqual(result["state"], "signed_in")
        self.assertEqual(result["account"]["email"], "a***@example.com")
        self.assertEqual(result["limits"]["primary"]["usedPercent"], 25)
        self.assertIn(("account/read", {"refreshToken": True}), self.client.calls)

    def test_expiration_cancels_provider_login(self):
        self.controller.start_login("browser")
        self.now = 11
        self.assertEqual(self.controller.poll()["login_state"], "expired")
        self.assertIn(("account/login/cancel", {"loginId": "login-1"}), self.client.calls)

    def test_account_change_invalidates_existing_sessions_and_limits(self):
        self.client.account = {"type": "chatgpt", "email": "a@example.com", "planType": "plus"}
        self.controller.refresh()
        self.client.account = {"type": "chatgpt", "email": "b@example.com", "planType": "pro"}
        self.client.events.append({"method": "account/updated", "params": {"authMode": "chatgpt"}})
        result = self.controller.poll()
        self.assertEqual(result["account"]["email"], "b***@example.com")
        self.assertEqual(result["account"]["plan_type"], "pro")
        self.invalidate.assert_called()

    def test_logout_closes_active_sessions_and_clears_account(self):
        self.client.account = {"type": "chatgpt", "email": "a@example.com"}
        self.controller.refresh()
        result = self.controller.logout()
        self.assertEqual(result["state"], "signed_out")
        self.assertEqual(result["limits"], {})
        self.assertEqual(result["account"], {})
        self.invalidate.assert_called_once()

    def test_rate_limit_event_updates_numeric_fields_only(self):
        self.controller.refresh()
        self.client.events.append({"method": "account/rateLimits/updated", "params": {
            "rateLimits": {"primary": {"usedPercent": 100, "resetsAt": 42,
                                     "accessToken": CANARY}, "secret": CANARY}}})
        result = self.controller.poll()
        self.assertTrue(result["limits"]["limit_reached"])
        self.assertNotIn(CANARY, json.dumps(result))

    def test_credentials_never_enter_status_or_error_payloads(self):
        self.client.extra = {"accessToken": CANARY, "refreshToken": CANARY,
                             "password": CANARY, "unknown": {"token": CANARY}}
        self.client.account = {"type": "chatgpt", "email": "a@example.com",
                               "planType": "plus", "accessToken": CANARY}
        self.assertNotIn(CANARY, json.dumps(self.controller.refresh()))
        self.assertNotIn(CANARY, json.dumps(self.controller.start_login("browser")))
        self.client.events.append({"method": "account/login/completed", "params": {
            "loginId": "login-1", "success": False, "error": "401 " + CANARY}})
        result = self.controller.poll()
        self.assertEqual(result["error_code"], "auth_expired")
        self.assertNotIn(CANARY, json.dumps(result))

    def test_unsupported_flow_is_actionable_and_retryable(self):
        self.client.failure = "unknown variant chatgptDeviceCode " + CANARY
        result = self.controller.start_login("device_code")
        self.assertEqual(result["error_code"], "flow_unsupported")
        self.assertTrue(self.client.closed)
        self.client = Client()
        self.assertEqual(self.controller.start_login("browser")["login_state"], "pending")

    def test_workspace_and_browser_errors_are_safe(self):
        for message, code in [("workspace forbidden", "workspace_restricted"),
                              ("browser unavailable", "browser_unavailable")]:
            self.client = Client()
            self.client.failure = message + CANARY
            result = self.controller.start_login("browser")
            self.assertEqual(result["error_code"], code)
            self.assertNotIn(CANARY, json.dumps(result))

    def test_disconnect_fails_closed_and_retry_reconnects(self):
        self.controller.start_login("browser")
        self.client.closed = True
        self.assertEqual(self.controller.poll()["state"], "unavailable")
        self.client = Client()
        self.assertEqual(self.controller.start_login("browser")["login_state"], "pending")

    def test_token_refresh_server_request_is_never_serviced(self):
        self.controller.refresh()
        self.client.events.append({"id": 7, "method": "account/chatgptAuthTokens/refresh",
                                   "params": {"accessToken": CANARY}})
        result = self.controller.poll()
        self.assertTrue(self.client.closed)
        self.assertNotIn(CANARY, json.dumps(result))
        self.assertFalse(any("AuthTokens" in method for method, _ in self.client.calls))

    def test_shutdown_cancels_pending_login_without_logout(self):
        self.controller.start_login("browser")
        self.controller.close()
        self.assertTrue(self.client.closed)
        self.assertIn(("account/login/cancel", {"loginId": "login-1"}), self.client.calls)
        self.assertFalse(any(method == "account/logout" for method, _ in self.client.calls))

    def test_adapter_owns_lazy_auth_controller_and_cleanup(self):
        adapter = CodexAppServerAdapter(
            executable_resolver=lambda: CodexExecutableCandidate("test", "custom"),
            client_factory=lambda path: self.client)
        self.assertEqual(self.client.calls, [])
        auth = adapter.authentication
        auth.refresh()
        self.assertEqual(self.client.calls[0][0], "initialize")
        self.assertEqual(self.client.calls[1][0], "initialized")
        adapter.close()
        self.assertTrue(self.client.closed)

    def test_turn_failure_state_does_not_retain_error_text(self):
        self.controller.observe_failure({"message": "401 unauthorized " + CANARY})
        result = self.controller.snapshot()
        self.assertEqual(result["state"], "expired")
        self.assertNotIn(CANARY, json.dumps(result))

    def test_login_url_accepts_provider_flags_but_rejects_tokens_and_other_hosts(self):
        from agent_host.codex_auth import _login_url
        valid = "https://auth.openai.com/oauth/authorize?id_token_add_organizations=true&state=nonce"
        self.assertEqual(_login_url(valid), valid)
        for value in ("https://evil.example/login", "http://auth.openai.com/login",
                      "https://auth.openai.com/login?access_token=" + CANARY,
                      "https://auth.openai.com/login#token", "javascript:alert(1)"):
            with self.assertRaises(ValueError):
                _login_url(value)

    def test_provider_usage_is_numeric_and_optional(self):
        from agent_host.codex_auth import _usage
        result = _usage({"usage": {"totalTokens": 23, "inputTokens": True,
                                   "outputTokens": -1, "accessToken": CANARY}})
        self.assertEqual(result["totalTokens"], 23)
        self.assertNotIn("inputTokens", result)
        self.assertNotIn("outputTokens", result)
        self.assertNotIn(CANARY, json.dumps(result))
        self.assertFalse(_usage({"unavailable": True})["available"])

    def test_auth_events_and_errors_never_put_credentials_in_project_history(self):
        import tempfile
        from agent_host.codex_adapter import _agent_event_from_codex_notification
        from agent_host.contracts import AgentSessionHandle
        from agent_host.session_store import AgentSessionStore
        handle = AgentSessionHandle(xace_session_id="session-auth",
            provider_id="codex_app_server", provider_session_id="thread-auth",
            base_cgs_hash="a" * 64, latest_cgs_hash="a" * 64,
            created_at="2026-09-20T00:00:00Z")
        kwargs = dict(handle=handle, sequence=1, fallback_turn_id="turn-auth",
                      clock=lambda: "2026-09-20T00:00:00Z")
        for method in ("account/login/completed", "account/updated", "account/rateLimits/updated"):
            self.assertIsNone(_agent_event_from_codex_notification(
                {"method": method, "params": {"accessToken": CANARY, "authUrl": CANARY}},
                **kwargs))
        event = _agent_event_from_codex_notification({"method": "turn/completed",
            "params": {"turn": {"id": "turn-auth", "status": "failed",
                                "error": {"message": "401 " + CANARY, "accessToken": CANARY}}}},
            **kwargs)
        self.assertNotIn(CANARY, json.dumps(event.to_dict()))
        with tempfile.TemporaryDirectory() as tmp:
            store = AgentSessionStore(tmp, audit_jsonl=True)
            store.upsert_session(handle)
            store.record_event(event)
            self.assertNotIn(CANARY, json.dumps(store.export_session("session-auth")))
            for path in Path(tmp).rglob("*"):
                if path.is_file():
                    self.assertNotIn(CANARY.encode(), path.read_bytes())

    def test_auth_operations_do_not_open_files_or_log_provider_errors(self):
        self.client.failure = "401 " + CANARY
        with patch("builtins.open") as file_open, patch("logging.Logger._log") as log:
            self.controller.start_login("browser")
            self.controller.snapshot()
            self.controller.close()
        file_open.assert_not_called()
        log.assert_not_called()

    def test_cached_account_read_does_not_clear_authorization_failure(self):
        self.client.account = {"type": "chatgpt", "email": "a@example.com"}
        self.controller.refresh()
        self.controller.observe_failure("401 unauthorized")
        self.now = 3.0
        self.assertEqual(self.controller.poll()["error_code"], "auth_expired")
        self.assertEqual(self.controller.snapshot()["state"], "expired")
        self.assertIsNone(self.controller.refresh()["error_code"])

    def test_success_notification_requires_confirmed_signed_in_account(self):
        self.controller.start_login("browser")
        self.client.events.append({"method": "account/login/completed",
                                   "params": {"loginId": "login-1", "success": True}})
        result = self.controller.poll()
        self.assertEqual(result["login_state"], "failed")
        self.assertEqual(result["error_code"], "auth_expired")


class AuthRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from fastapi import FastAPI
        import httpx
        self.provider = Client()
        self.auth = CodexAuthController(lambda: self.provider)
        self.app = FastAPI()
        self.app.include_router(auth_router(lambda: self.auth))
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(
            app=self.app, client=("127.0.0.1", 1234)), base_url="http://localhost:8000",
            headers={"x-xace-agent-auth": "1"})

    async def asyncTearDown(self):
        await self.http.aclose()
        self.auth.close()

    async def test_start_poll_cancel_logout_and_no_store_headers(self):
        result = await self.http.post("/api/agent-auth/start", json={"flow": "device_code"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers["cache-control"], "no-store")
        self.assertEqual(result.json()["challenge"]["user_code"], "ABCD-1234")
        status = await self.http.get("/api/agent-auth")
        self.assertNotIn("challenge", status.json())
        result = await self.http.post("/api/agent-auth/cancel", json={})
        self.assertEqual(result.json()["login_state"], "cancelled")
        result = await self.http.post("/api/agent-auth/logout", json={"confirm": True})
        self.assertEqual(result.json()["state"], "signed_out")

    async def test_cross_origin_and_missing_header_are_rejected_before_provider(self):
        for headers in ({"origin": "https://evil.example"},
                        {"x-xace-agent-auth": ""},
                        {"host": "evil.example"}):
            result = await self.http.post("/api/agent-auth/start", json={"flow": "browser"},
                                          headers=headers)
            self.assertEqual(result.status_code, 403)
        self.assertEqual(self.provider.calls, [])

    async def test_tokens_arbitrary_methods_and_unconfirmed_logout_rejected(self):
        for action, payload in [("start", {"flow": "apiKey", "apiKey": CANARY}),
                                ("start", {"flow": "browser", "token": CANARY}),
                                ("logout", {}), ("command", {})]:
            response = await self.http.post("/api/agent-auth/" + action, json=payload)
            self.assertEqual(response.status_code, 400)
            self.assertNotIn(CANARY, response.text)
        self.assertEqual(self.provider.calls, [])

    async def test_nonlocal_operator_is_denied(self):
        import httpx
        async with httpx.AsyncClient(transport=httpx.ASGITransport(
                app=self.app, client=("192.0.2.1", 42)), base_url="http://localhost:8000",
                headers={"x-xace-agent-auth": "1"}) as client:
            response = await client.get("/api/agent-auth")
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
