"""Local operator-only support routes; not model tools or remote telemetry."""
import asyncio
import json
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from agent_auth_routes import is_local_agent_operator


def support_router(service, *, dev_mode=False):
    router = APIRouter()
    headers = {"Cache-Control": "no-store", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff"}

    @router.get('/api/agent-support/diagnostics')
    async def diagnostics(request: Request):
        if not is_local_agent_operator(request, dev_mode=dev_mode):
            return JSONResponse({"error": "local_operator_required"}, 403, headers=headers)
        return JSONResponse(await asyncio.to_thread(service.diagnostics), headers=headers)

    @router.post('/api/agent-support/{action}')
    async def control(action: str, request: Request):
        if not is_local_agent_operator(request, dev_mode=dev_mode):
            return JSONResponse({"error": "local_operator_required"}, 403, headers=headers)
        try:
            if request.headers.get('content-type', '').split(';')[0] != 'application/json':
                raise ValueError()
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 2048: raise ValueError()
            payload = json.loads(body)
            fields = {'confirm', 'preview_id', 'sha256'} if action == 'export' else {'confirm'}
            if not isinstance(payload, dict) or set(payload) != fields or payload.get('confirm') is not True:
                raise ValueError()
            if action == 'preview':
                return JSONResponse(await asyncio.to_thread(service.prepare, confirm=True), headers=headers)
            if action == 'export':
                content = await asyncio.to_thread(service.export, **payload)
                return Response(content, media_type='application/json', headers={**headers,
                    'Content-Disposition': 'attachment; filename="xace-agent-support.json"'})
            if action == 'clear':
                service.clear()
                return JSONResponse({'cleared': True}, headers=headers)
            raise ValueError()
        except (ValueError, TypeError):
            return JSONResponse({'error': 'invalid_consent_or_preview'}, 400, headers=headers)

    return router
