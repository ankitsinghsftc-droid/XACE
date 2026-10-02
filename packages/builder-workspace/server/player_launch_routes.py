"""Capability-bound local operator routes for the native Player broker."""
import asyncio,json,secrets
from fastapi import APIRouter,Request
from fastapi.responses import JSONResponse
from agent_auth_routes import is_local_agent_operator

def player_router(service,*,dev_mode=False):
    router=APIRouter();headers={"Cache-Control":"no-store"}
    @router.get("/api/player")
    async def status(request:Request):
        if not is_local_agent_operator(request,dev_mode=dev_mode):return JSONResponse({"message":"Local operator required"},403,headers=headers)
        return JSONResponse({"capability":service.capability},headers=headers)
    @router.post("/api/player/{action}")
    async def control(action:str,request:Request):
        if not is_local_agent_operator(request,dev_mode=dev_mode) or not secrets.compare_digest(request.headers.get("x-xace-player-capability",""),service.capability):
            return JSONResponse({"message":"Refresh Builder to reconnect to Player control."},403,headers=headers)
        if request.headers.get("content-type","").split(";")[0]!="application/json":return JSONResponse({"message":"JSON required"},415)
        try:
            body=bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body)>(8192 if action=="join" else 1024):raise ValueError("Invalid Play request")
            value=json.loads(body)
            if not isinstance(value,dict) or set(value)-({"cgs_hash","code"} if action=="join" else {"cgs_hash"}) or not isinstance(value.get("cgs_hash",""),str) or not isinstance(value.get("code",""),str) or len(value.get("code",""))>4096:raise ValueError("Invalid Play request")
            args=(action,value.get("cgs_hash",""),value.get("code","")) if action=="join" else (action,value.get("cgs_hash",""))
            result=await asyncio.to_thread(service.control,*args)
            return JSONResponse({"ok":True,**result},headers=headers)
        except (ValueError,OSError) as error:
            return JSONResponse({"ok":False,"state":"failed","message":str(error)},400,headers=headers)
    return router
