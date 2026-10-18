"""Local-operator routes for an explicitly registered native setup stage."""
import asyncio,json,secrets
from pathlib import Path
from fastapi import APIRouter,Request
from fastapi.responses import FileResponse,JSONResponse
from agent_auth_routes import is_local_agent_operator


def install_setup_routes(app,service,*,dev_mode=False):
    router=APIRouter();headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}
    @router.get('/native-setup')
    async def page():return FileResponse(Path(__file__).with_name('native_setup.html'),headers=headers)
    @router.get('/native-setup.js')
    async def script():return FileResponse(Path(__file__).with_name('native_setup.js'),media_type='text/javascript',headers=headers)
    @router.post('/api/native-setup/{action}')
    async def operate(action:str,request:Request):
        if not is_local_agent_operator(request,dev_mode=dev_mode):return JSONResponse({'message':'Local operator required'},403,headers=headers)
        if request.headers.get('content-type','').split(';')[0]!='application/json':return JSONResponse({'message':'JSON required'},415,headers=headers)
        try:
            data=bytearray()
            async for chunk in request.stream():
                data.extend(chunk)
                if len(data)>65536:raise ValueError('Setup request too large')
            def pairs(rows):
                result={}
                for key,value in rows:
                    if key in result:raise ValueError('Duplicate request key')
                    result[key]=value
                return result
            body=json.loads(data,object_pairs_hook=pairs)
            expected={'open':set(),'cancel':{'token'},'approve':{'token','proposal_digest'},'apply':{'token','proposal_digest','approval'}}
            if action not in expected or type(body) is not dict or set(body)!=expected[action]:raise ValueError('Invalid setup action')
            principal=request.cookies.get('xace_native_setup')
            if action=='open':principal=principal or secrets.token_urlsafe(32)
            if not principal:raise ValueError('Open a setup review first')
            args=[principal]
            if action!='open':args.append(body['token'])
            if action in {'approve','apply'}:args.append(body['proposal_digest'])
            if action=='apply':args.append(body['approval'])
            result=await asyncio.to_thread(getattr(service,action),*args)
            response=JSONResponse(result if result is not None else {'cancelled':True},headers=headers)
            if action=='open':response.set_cookie('xace_native_setup',principal,httponly=True,samesite='strict',path='/api/native-setup')
            return response
        except (ValueError,KeyError,TypeError,OSError) as exc:return JSONResponse({'message':str(exc)},409,headers=headers)
    app.router.routes[0:0]=router.routes;app.state.native_setup=service
