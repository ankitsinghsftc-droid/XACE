"""Opt-in native review and explicitly configured materialization/recovery routes."""
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


def install_reconciliation_routes(app, context_provider, *, dev_mode=False, materialization_host=None):
    """Call from an explicitly configured Builder host with fresh trusted inputs.

    Prepend routes ahead of Builder's static fallback, without changing the sealed
    default app or allowing the browser to supply native paths, CGS or receipts.
    """
    service=materialization_host.review if materialization_host else ReconciliationReview(context_provider);router=APIRouter()
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
        result['apply_available']=materialization_host is not None
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
            expected=set() if action in {'status','saved-changes'} else {'transaction_id','recovery_action'} if action=='recover' else {'approval','proposal_digest'} if action=='apply' else {'token'} if action=='cancel' else {'token','proposal_digest','resolutions'} if action=='resolve' else {'token','proposal_digest'}
            if type(body) is not dict or set(body)!=expected or action not in {'cancel','resolve','approve','apply','recover','status','saved-changes'}:raise ValueError('Invalid review action')
            if action=='saved-changes':
                if materialization_host is None:raise ValueError('Saved-change monitoring is not configured')
                result=await asyncio.to_thread(materialization_host.poll_saved_changes)
                return JSONResponse(result,headers=headers)
            if action=='status':
                result=await asyncio.to_thread(materialization_host.status) if materialization_host else dict(play_build_blocked=False,pending=[])
                return JSONResponse(result,headers=headers)
            if action=='recover':
                if materialization_host is None:raise ValueError('Native recovery is not configured')
                if type(body['transaction_id']) is not str or body['recovery_action'] not in {'resume','rollback'}:raise ValueError('Invalid recovery action')
                result=await asyncio.to_thread(materialization_host.recover,body['transaction_id'],action=body['recovery_action'])
                return JSONResponse(result,headers=headers)
            if action=='apply':
                if materialization_host is None:raise ValueError('Native publication is not configured')
                result=await asyncio.to_thread(materialization_host.apply,request.cookies.get('xace_native_review',''),body['approval'],body['proposal_digest'])
                return JSONResponse(result,headers=headers)
            if type(body['token']) is not str:raise ValueError('Invalid review token')
            principal=request.cookies.get('xace_native_review','')
            args=[principal,body['token']]
            if action!='cancel':args.append(body['proposal_digest'])
            if action=='resolve':args.append(body['resolutions'])
            result=await asyncio.to_thread(getattr(service,action),*args)
            return JSONResponse(result if result is not None else {'cancelled':True},headers=headers)
        except (ValueError,TypeError,KeyError,OSError) as exc:return JSONResponse({'message':str(exc)},409,headers=headers)

    app.router.routes[0:0]=router.routes
    app.state.native_reconciliation=service
    return service


def create_reconciliation_app(context_provider, **builder_options):
    from builder_server import create_app
    app=create_app(**builder_options)
    install_reconciliation_routes(app,context_provider,dev_mode=builder_options.get('dev_mode',False))
    return app


class GatedPlayerService:
    """Keep the actual local Player control route behind authoring recovery."""
    def __init__(self,service,host):self.service=service;self.host=host
    @property
    def capability(self):return self.service.capability
    def control(self,action,*args):
        if action in {'stop','status'}:return self.service.control(action,*args)
        with self.host.player_gate():return self.service.control(action,*args)


def create_materialization_app(host,*,setup_provider=None,**builder_options):
    from builder_server import create_app
    from player_launch_routes import player_router
    if Path(builder_options['project_path']).resolve()!=host.root:
        raise ValueError('Builder and native authoring roots must match')
    app=create_app(**builder_options)
    install_reconciliation_routes(app,None,dev_mode=builder_options.get('dev_mode',False),materialization_host=host)
    app.router.routes[0:0]=player_router(GatedPlayerService(app.state.player_launch,host),dev_mode=builder_options.get('dev_mode',False)).routes
    app.state.native_materialization=host
    if setup_provider is not None:
        from native_setup_review import NativeSetupReview
        from native_setup_routes import install_setup_routes
        install_setup_routes(app,NativeSetupReview(host,setup_provider),dev_mode=builder_options.get('dev_mode',False))
    return app
