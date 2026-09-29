import asyncio
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_setup_routes import AgentRuntimeSetup, setup_router
from test_agent_codex_runtime_lifecycle import _lifecycle, _runtime


class AgentSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.lifecycle = _lifecycle(self.root / "state")
        self.invalidate = Mock()
        self.setup = AgentRuntimeSetup(self.lifecycle, invalidate=self.invalidate)
        self.path = _runtime(self.root / "provider" / "codex.exe", "0.143.0")

    def tearDown(self):
        self.setup.close()
        self.tmp.cleanup()

    def wait(self):
        self.setup._thread.join(3)
        self.assertFalse(self.setup._thread.is_alive())
        return self.setup.status()

    def test_inspection_and_detection_do_not_execute_or_write(self):
        with patch.object(self.lifecycle, "_version_reader") as reader:
            self.assertFalse(self.setup.status()["runtime"]["ready"])
            with patch("agent_setup_routes.shutil.which", return_value=str(self.path)):
                result = self.setup.detect()
                self.assertEqual(result["candidate_path"], str(self.path.resolve()))
                self.assertFalse(result["verified"])
            reader.assert_not_called()
        self.assertFalse((self.root / "state").exists())

    def test_confirmation_and_absolute_path_are_required(self):
        for payload in ({}, {"confirm": False}, {"confirm": True, "executable_path": "relative"},
                        {"confirm": True, "executable_path": str(self.path), "shell": "anything"}):
            with self.assertRaises(ValueError):
                self.setup.start("install", payload)
        self.assertFalse((self.root / "state").exists())

    def test_install_update_rollback_repair_remove_recover(self):
        payload = {"confirm": True, "executable_path": str(self.path)}
        self.setup.start("install", payload)
        self.assertTrue(self.wait()["runtime"]["ready"])
        new = _runtime(self.root / "new" / "codex.exe", "0.144.0")
        self.setup.start("update", {"confirm": True, "executable_path": str(new)})
        self.assertEqual(self.wait()["runtime"]["active"]["version"], "0.144.0")
        self.setup.start("rollback", {"confirm": True})
        self.assertEqual(self.wait()["runtime"]["active"]["version"], "0.143.0")
        self.setup.start("repair", payload)
        self.assertEqual(self.wait()["job"]["state"], "complete")
        self.setup.start("remove", {"confirm": True})
        self.assertFalse(self.wait()["runtime"]["ready"])
        self.assertTrue(self.path.exists())
        self.setup.start("recover", {"confirm": True})
        self.assertEqual(self.wait()["job"]["state"], "complete")
        self.assertEqual(self.invalidate.call_count, 6)

    def test_cancellation_before_commit_preserves_pin_and_rejects_overlap(self):
        self.lifecycle.verify_and_activate(self.path, confirm_official_install=True)
        before = self.lifecycle.state_path.read_bytes()
        entered, release = threading.Event(), threading.Event()
        probe = self.lifecycle._schema_probe
        def slow(path):
            entered.set()
            release.wait(3)
            return probe(path)
        with patch.object(self.lifecycle, "_schema_probe", side_effect=slow):
            self.setup.start("repair", {"confirm": True, "executable_path": str(self.path)})
            self.assertTrue(entered.wait(2))
            try:
                with self.assertRaisesRegex(ValueError, "busy"):
                    self.setup.start("remove", {"confirm": True})
                self.assertEqual(self.setup.cancel()["job"]["state"], "cancelling")
            finally:
                release.set()
            self.assertEqual(self.wait()["job"]["state"], "cancelled")
        self.assertEqual(before, self.lifecycle.state_path.read_bytes())
        self.invalidate.assert_not_called()

    def test_failure_returns_safe_code_not_provider_error_text(self):
        canary = "arbitrary-credential-canary"
        with patch.object(self.lifecycle, "verify_candidate", side_effect=RuntimeError(canary)):
            self.setup.start("install", {"confirm": True, "executable_path": str(self.path)})
            result = self.wait()
        self.assertEqual(result["job"]["error_code"], "runtime_verification_failed")
        self.assertNotIn(canary, json.dumps(result))

    def test_post_completion_cancel_does_not_claim_rollback(self):
        self.setup.start("install", {"confirm": True, "executable_path": str(self.path)})
        self.wait()
        self.assertEqual(self.setup.cancel()["job"]["state"], "complete")
        self.assertTrue(self.setup.status()["runtime"]["ready"])


class SetupRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_routes_validate_payload_and_origin(self):
        from fastapi import FastAPI
        import httpx
        with tempfile.TemporaryDirectory() as tmp:
            setup = AgentRuntimeSetup(_lifecycle(Path(tmp) / "state"))
            app = FastAPI()
            app.include_router(setup_router(setup))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(
                app=app, client=("127.0.0.1", 7)), base_url="http://localhost:8000",
                headers={"X-XACE-Agent-Auth": "1"}) as client:
                response = await client.get("/api/agent-runtime")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["cache-control"], "no-store")
                for headers in ({"origin": "https://evil.example"}, {"X-XACE-Agent-Auth": ""},
                                {"host": "evil.example"}):
                    response = await client.post("/api/agent-runtime/detect", json={}, headers=headers)
                    self.assertEqual(response.status_code, 403)
                for action, payload in (("install", {}), ("shell", {"confirm": True}),
                                        ("detect", {"token": "secret"}), ("cancel", {"id": "wrong"})):
                    response = await client.post("/api/agent-runtime/" + action, json=payload)
                    self.assertEqual(response.status_code, 400)
            setup.close()


if __name__ == "__main__":
    unittest.main()
