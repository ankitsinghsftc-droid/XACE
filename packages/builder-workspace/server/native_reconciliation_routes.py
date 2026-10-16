"""Opt-in NEC-008 review on the XP-021 local-operator surface; no apply route."""
import asyncio
import json
import secrets
import sys
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from agent_auth_routes import is_local_agent_operator

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'packages/project-system'))
from native_reconciliation_review import ReconciliationReview


def install_reconciliation_routes(app, context_provider, *, dev_mode=False):
    """Call from an explicitly configured Builder host with fresh trusted inputs.

    Prepend routes ahead of Builder's static fallback, without changing the sealed
    default app or allowing the browser to supply native paths, CGS or receipts.
    """
    service=ReconciliationReview(context_provider);router=APIRouter()
    headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}

    @router.get('/native-review')
    async def page():
        return FileResponse(Path(__file__).with_name('native_reconciliation_review.html'),headers=headers)

    @router.get('/native-review.js')
    async def script():
        return FileResponse(Path(__file__).with_name('native_reconciliation_review.js'),media_type='text/javascript',headers=headers)

    @router.get('/api/native-reconciliation')
    async def open_review(request:Request):
        if not is_local_agent_operator(request,dev_mode=dev_mode):return JSONResponse({'message':'Local operator required'},403,headers=headers)
        principal=request.cookies.get('xace_native_review') or secrets.token_urlsafe(32)
        try:result=await asyncio.to_thread(service.open,principal)
        except ValueError as exc:return JSONResponse({'message':str(exc)},409,headers=headers)
        response=JSONResponse(result,headers=headers)
        response.set_cookie('xace_native_review',principal,httponly=True,samesite='strict',path='/api/native-reconciliation')
        return response

    @router.post('/api/native-reconciliation/{action}')
    async def review_action(action:str,request:Request):
        if not is_local_agent_operator(request,dev_mode=dev_mode):return JSONResponse({'message':'Local operator required'},403,headers=headers)
        if request.headers.get('content-type','').split(';')[0]!='application/json':return JSONResponse({'message':'JSON required'},415,headers=headers)
        try:
            data=bytearray()
            async for chunk in request.stream():
                data.extend(chunk)
                if len(data)>65536:raise ValueError('Review request too large')
            def pairs(rows):
                value={}
                for key,item in rows:
                    if key in value:raise ValueError('Duplicate request key')
                    value[key]=item
                return value
            body=json.loads(data,object_pairs_hook=pairs)
            expected={'token'} if action=='cancel' else {'token','proposal_digest','resolutions'} if action=='resolve' else {'token','proposal_digest'}
            if type(body) is not dict or set(body)!=expected or action not in {'cancel','resolve','approve'}:raise ValueError('Invalid review action')
            if type(body['token']) is not str:raise ValueError('Invalid review token')
            principal=request.cookies.get('xace_native_review','')
            args=[principal,body['token']]
            if action!='cancel':args.append(body['proposal_digest'])
            if action=='resolve':args.append(body['resolutions'])
            result=await asyncio.to_thread(getattr(service,action),*args)
            return JSONResponse(result if result is not None else {'cancelled':True},headers=headers)
        except (ValueError,TypeError,KeyError) as exc:return JSONResponse({'message':str(exc)},409,headers=headers)

    app.router.routes[0:0]=router.routes
    app.state.native_reconciliation=service
    return service


def create_reconciliation_app(context_provider, **builder_options):
    from builder_server import create_app
    app=create_app(**builder_options)
    install_reconciliation_routes(app,context_provider,dev_mode=builder_options.get('dev_mode',False))
    return app
