"""Local operator auth endpoints, separate from model tools and session storage."""

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse


def is_local_agent_operator(request: Request, *, dev_mode: bool = False) -> bool:
    if request.client is None or request.client.host not in {"127.0.0.1", "::1", "localhost"}:
        return False
    if request.headers.get("x-xace-agent-auth") != "1":
        return False
    if request.url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return False
    origin = request.headers.get("origin")
    if origin:
        expected = str(request.base_url).rstrip("/")
        permitted = {expected}
        if dev_mode:
            permitted.update({"http://localhost:5173", "http://127.0.0.1:5173"})
        if origin not in permitted:
            return False
    return request.headers.get("sec-fetch-site") != "cross-site"


def auth_router(controller_factory, *, dev_mode: bool = False) -> APIRouter:
    router = APIRouter()
    headers = {"Cache-Control": "no-store", "Pragma": "no-cache"}

    @router.get("/api/agent-auth")
    async def status(request: Request):
        if not is_local_agent_operator(request, dev_mode=dev_mode):
            return JSONResponse({"error": "local_operator_required"}, status_code=403, headers=headers)
        result = await asyncio.to_thread(controller_factory().poll)
        return JSONResponse(result, headers=headers)

    @router.post("/api/agent-auth/{action}")
    async def control(action: str, request: Request):
        if not is_local_agent_operator(request, dev_mode=dev_mode):
            return JSONResponse({"error": "local_operator_required"}, status_code=403, headers=headers)
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            return JSONResponse({"error": "json_required"}, status_code=415, headers=headers)
        # No arbitrary provider methods, login IDs, URLs, tokens, or API keys accepted.
        try:
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 1024:
                    raise ValueError()
            import json
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError()
            fields = {"flow"} if action == "start" else {"confirm"} if action == "logout" else set()
            if set(payload) - fields:
                raise ValueError()
            if action == "start" and payload.get("flow") not in {"browser", "device_code"}:
                raise ValueError()
            if action == "logout" and payload.get("confirm") is not True:
                raise ValueError()
            if action not in {"start", "cancel", "logout", "refresh"}:
                raise ValueError()
        except (ValueError, TypeError):
            return JSONResponse({"error": "invalid_auth_action"}, status_code=400, headers=headers)
        controller = controller_factory()
        if action == "start":
            result = await asyncio.to_thread(controller.start_login, payload["flow"])
        else:
            method = {"cancel": controller.cancel_login, "logout": controller.logout,
                      "refresh": controller.refresh}[action]
            result = await asyncio.to_thread(method)
        return JSONResponse(result, headers=headers)

    return router
