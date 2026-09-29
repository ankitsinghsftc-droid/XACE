"""AG-026 local operator runtime controls. Never exposed as agent tools."""

import asyncio
import os
import shutil
import threading
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from agent_auth_routes import is_local_agent_operator
from agent_host.codex_runtime_lifecycle import CodexRuntimeLifecycle, CodexRuntimeLifecycleError


class AgentRuntimeSetup:
    def __init__(self, lifecycle=None, *, invalidate=lambda: None):
        self.lifecycle = lifecycle or CodexRuntimeLifecycle()
        self.invalidate = invalidate
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._thread = None
        self._job = {"state": "idle", "operation": "", "error_code": None}

    def status(self):
        with self._lock:
            job = dict(self._job)
        try:
            runtime = self.lifecycle.inspect()
        except Exception:
            runtime = {"ready": False, "active": None, "state_error": "runtime_unreadable"}
        return {"schema": "xace.agent_runtime_setup.v1", "runtime": runtime, "job": job,
                "override_active": any(os.environ.get(name, "").strip() for name in
                                       ("XACE_CODEX_EXECUTABLE", "XACE_CODEX_APP_SERVER_BIN")),
                "automatic_acquisition": False}

    def detect(self):
        # Discovery never runs or activates a binary.
        candidate = shutil.which("codex")
        return {"candidate_path": str(Path(candidate).resolve()) if candidate else "",
                "verified": False}

    def start(self, action, payload):
        if action not in {"install", "update", "repair", "rollback", "remove", "recover"}:
            raise ValueError("invalid_runtime_action")
        permitted = {"confirm", "executable_path"} if action in {"install", "update", "repair"} else {"confirm"}
        if not isinstance(payload, dict) or set(payload) - permitted or payload.get("confirm") is not True:
            raise ValueError("confirmation_required")
        path = payload.get("executable_path", "")
        if action in {"install", "update", "repair"}:
            if not isinstance(path, str) or not path or len(path) > 4096 or not Path(path).is_absolute():
                raise ValueError("absolute_executable_path_required")
        with self._lock:
            if self._job["state"] in {"running", "cancelling"}:
                raise ValueError("runtime_operation_busy")
            self._cancel.clear()
            self._job = {"state": "running", "operation": action, "error_code": None}
            self._thread = threading.Thread(target=self._run, args=(action, path),
                                            name="xace-runtime-setup", daemon=True)
            self._thread.start()
        return self.status()

    def _check_cancel(self):
        if self._cancel.is_set():
            raise CodexRuntimeLifecycleError("Runtime operation cancelled")

    def _run(self, action, path):
        try:
            self._check_cancel()
            if action in {"install", "update", "repair"}:
                self.lifecycle.verify_and_activate(path, operation=action, confirm_official_install=True,
                                                   before_commit=self._check_cancel)
            elif action == "rollback":
                self.lifecycle.rollback(before_commit=self._check_cancel)
            elif action == "remove":
                self.lifecycle.deactivate()
            else:
                self.lifecycle.recover_interrupted()
            self.invalidate()
            result = {"state": "complete", "operation": action, "error_code": None}
        except Exception as exc:
            text = str(exc).lower()
            code = next((code for marker, code in (
                ("cancelled", "cancelled"), ("sha-256", "digest_mismatch"),
                ("schema", "schema_mismatch"), ("private editor", "private_runtime"),
                ("prerelease", "prerelease_runtime"), ("revoked", "runtime_revoked"),
                ("platform", "unsupported_platform"), ("not found", "executable_missing"),
                ("last-known-good", "rollback_unavailable"), ("repair requires", "repair_requires_pin"),
                ("already in progress", "runtime_operation_busy"),
            ) if marker in text), "runtime_verification_failed")
            result = {"state": "cancelled" if code == "cancelled" else "failed",
                      "operation": action, "error_code": code}
        with self._lock:
            self._job = result

    def cancel(self):
        with self._lock:
            if self._job["state"] in {"running", "cancelling"}:
                if self._job["operation"] not in {"install", "update", "repair", "rollback"}:
                    return self.status()
                self._cancel.set()
                self._job["state"] = "cancelling"
        return self.status()

    def close(self):
        self._cancel.set()
        if self._thread:
            self._thread.join(timeout=40)


def setup_router(setup: AgentRuntimeSetup, *, dev_mode=False):
    router = APIRouter()
    headers = {"Cache-Control": "no-store"}

    @router.get("/api/agent-runtime")
    async def status(request: Request):
        if not is_local_agent_operator(request, dev_mode=dev_mode):
            return JSONResponse({"error": "local_operator_required"}, 403, headers=headers)
        return JSONResponse(await asyncio.to_thread(setup.status), headers=headers)

    @router.post("/api/agent-runtime/{action}")
    async def control(action: str, request: Request):
        if not is_local_agent_operator(request, dev_mode=dev_mode):
            return JSONResponse({"error": "local_operator_required"}, 403, headers=headers)
        try:
            if request.headers.get("content-type", "").split(";")[0] != "application/json":
                raise ValueError("json_required")
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 8192:
                    raise ValueError("invalid_runtime_action")
            import json
            payload = json.loads(body)
            if action in {"detect", "cancel"}:
                if payload != {}:
                    raise ValueError("invalid_runtime_action")
                result = await asyncio.to_thread(setup.detect if action == "detect" else setup.cancel)
            else:
                result = await asyncio.to_thread(setup.start, action, payload)
            return JSONResponse(result, headers=headers)
        except (ValueError, TypeError):
            return JSONResponse({"error": "invalid_or_busy_runtime_action"}, 400, headers=headers)

    return router
