"""Generic, read-only replay inspection with trusted host execution boundaries."""
from __future__ import annotations
import hashlib,json,os,re,secrets,subprocess,threading,uuid
from pathlib import Path
from fastapi import HTTPException,Request
from runtime_control_client import RuntimeControlError

def decode_recording(raw):
    try:
        value=json.loads(raw)
        if not isinstance(value,dict):raise ValueError()
        return value
    except (ValueError,UnicodeError):raise ValueError('This recording is damaged. Open a complete XACE recording.')

class ReplayDebugger:
    def __init__(self,root:Path,hosts:tuple[Path,...],runtime,creator_token:str=''):
        self.root=root.resolve();self.hosts=hosts;self.runtime=runtime;self.creator_token=creator_token
        self.lock=threading.Lock()
        self.verifications={}

    def authorized(self,token:str)->bool:
        return bool(self.creator_token and secrets.compare_digest(token,self.creator_token))

    def catalog(self):
        result=[]
        if self.root.exists():
            for path in sorted(self.root.glob('*.json')):
                if re.fullmatch('[0-9a-f]{64}',path.stem) and path.resolve().parent==self.root:
                    result.append({'id':path.stem,'label':f'Recording {path.stem[:12]}'})
        return result

    def capture(self):
        reply=self.runtime._round_trip({'msg_type':'runtime_control','protocol_version':1,'request_id':'debugger-capture','action':'ruleset','ruleset':{'operation':'export_replay'}})
        if not reply.get('accepted'):raise ValueError('Live recording is unavailable. Enable recording in the host launch settings or open a saved recording.')
        identity=reply['ruleset']['recording_id'];self.read(identity)
        return {'recording_id':identity,'message':'A separate recording is ready. The live game continues.'}

    def import_recording(self,raw):
        if len(raw)>512*1024*1024:raise ValueError('This recording is too large.')
        sealed=decode_recording(raw)
        if sealed.get('schema')!='xace.sealed_epoch_replay.v1' or sealed.get('bundle',{}).get('schema')!='xace.epoch_replay.v1':raise ValueError('Choose an XACE replay recording.')
        self.root.mkdir(parents=True,exist_ok=True)
        identity=hashlib.sha256(raw).hexdigest();path=self.root/(identity+'.json')
        if not path.exists():
            if len(self.catalog())>=64:raise ValueError('Recording storage is full. Archive older recordings first.')
            with path.open('xb') as file:file.write(raw)
        self.read(identity);return {'recording_id':identity}

    def read(self,identity):
        if not isinstance(identity,str) or not re.fullmatch('[0-9a-f]{64}',identity):raise ValueError('Choose a recording from the list.')
        path=(self.root/(identity+'.json')).resolve()
        if path.parent!=self.root or not path.is_file():raise ValueError('This recording is unavailable.')
        if path.stat().st_size>512*1024*1024:raise ValueError('This recording is too large to inspect.')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=identity:raise ValueError('The recording changed. Import a verified copy again.')
        sealed=decode_recording(raw)
        if sealed.get('schema')!='xace.sealed_epoch_replay.v1' or sealed.get('bundle',{}).get('schema')!='xace.epoch_replay.v1':raise ValueError('This recording format is not supported.')
        return path,sealed['bundle']

    def inspect(self,identity,tick=None):
        _,bundle=self.read(identity);ticks=bundle['ticks']
        if not ticks:raise ValueError('This recording has no completed frames.')
        selected=next((row for row in ticks if row['tick']==tick),None) if tick is not None else ticks[0]
        if selected is None:raise ValueError('That frame is not present in this recording.')
        artifacts=bundle['initial_artifacts']
        for epoch in bundle['epochs']:
            if epoch['tick']<=selected['tick']:artifacts=epoch['proposal']['artifacts']
        files=artifacts['files'];world=json.loads(bytes(files['world.json']));cgs=json.loads(bytes(files['game.cgs.json']))
        tables=selected['state']['components']['tables']
        components=[{'id':key,'label':table.get('component_type_name',key),'entities':{entity:json.loads(value) for entity,value in table['rows'].items()}} for key,table in tables.items()]
        events=[]
        for row in ticks:
            for index,event in enumerate(row['events']):
                kind=event['event_type'];name=next(iter(kind.values())) if isinstance(kind,dict) else str(kind)
                labels=cgs.get('metadata',{}).get('event_labels',{})
                events.append({'tick':row['tick'],'index':index,'label':labels.get(name,name),'type':name,'entity':event['source_entity_id']})
        session=bundle['epochs'][0]['proposal']['parent'].get('session') if bundle['epochs'] else None
        return {'schema':'xace.replay_inspection.v1','id':identity,'mode':'replay','live_untouched':True,'verified':False,'session':session,
                'first_tick':ticks[0]['tick'],'last_tick':ticks[-1]['tick'],'tick':selected['tick'],'epoch':selected['epoch'],
                'epochs':[{'tick':e['tick'],'activation_id':e['activation_id'],'migration':sorted(e['proposal']['replace_config_defaults'])} for e in bundle['epochs']],
                'events':events,'selected_events':selected['events'],'inputs':selected['inputs'],'components':components,
                'world':world,'dependencies':selected['schedule']['system_dependencies'],'access':selected['schedule']['system_access'],
                'membership':{'required_peers':selected['required_peers'],'decision':selected['release_decision'],'waited_ticks':selected['waited_ticks']},
                'seed':bundle['world_seed'],'world_hash':selected['world_hash'],
                'trace_note':'Recorded component fields and declared system dependencies. This does not invent unrecorded query or RNG-call traces.'}

    def verify(self,identity,tick):
        path,bundle=self.read(identity)
        if type(tick)!=int or not any(t['tick']==tick for t in bundle['ticks']):raise ValueError('Choose a frame in this recording.')
        host=next((p for p in self.hosts if p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()==bundle['host_executable_digest']),None)
        if host is None:raise ValueError('The original game runtime is unavailable. Install its matching version to replay this recording.')
        if not self.lock.acquire(blocking=False):raise ValueError('A replay is already running. Wait for it to finish.')
        try:
            output=self.root/'forks';output.mkdir(exist_ok=True);report=output/(uuid.uuid4().hex+'.json')
            result=subprocess.run([str(host),'--epoch-replay-in',str(path),'--epoch-replay-report',str(report),'--epoch-replay-through-tick',str(tick)],capture_output=True,text=True,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            if not report.exists():raise ValueError('Replay could not start. The recording or its historical artifacts are incomplete.')
            data=json.loads(report.read_text())
            self.verifications[(identity,tick)]=data
            if len(self.verifications)>64:self.verifications.pop(next(iter(self.verifications)))
            return {'ok':result.returncode==0 and data.get('ok') is True,'report':data,'message':'Replay matches the recording.' if data.get('ok') else 'Replay differs from the recording. Inspect the first differing frame.'}
        except subprocess.TimeoutExpired:raise ValueError('Replay took too long. Try an earlier frame.')
        finally:self.lock.release()

    def live(self):
        try:
            ack=self.runtime.send_control('status')
            try:inspection=self.runtime._round_trip({'msg_type':'runtime_control','protocol_version':1,'request_id':'debugger-inspection','action':'ruleset','ruleset':{'operation':'inspect'}}).get('ruleset')
            except Exception:inspection=None
            return {'mode':'live','status':ack.get('status',{}),'ruleset':inspection}
        except (OSError,RuntimeControlError):return {'mode':'live','status':{},'message':'The live game is unavailable. Recordings are still safe to inspect.'}

    def control(self,action,token,confirmed):
        if not self.authorized(token):raise PermissionError('Only the creator can control the live session.')
        if confirmed is not True:raise ValueError('Confirm that this action affects everyone in the session.')
        if action not in {'pause','play','step'}:raise ValueError('Live restore is unavailable. Open an isolated replay instead.')
        return self.runtime.send_control(action)

def install_debugger_routes(app,debugger):
    async def body(request):
        data=await request.json()
        if not isinstance(data,dict) or set(data)-{'id','tick','action','confirm_session_wide'}:raise HTTPException(400,'Unsupported debugger request.')
        return data
    def call(fn,*args):
        try:return fn(*args)
        except PermissionError as error:raise HTTPException(403,str(error))
        except (ValueError,KeyError,TypeError,IndexError,OSError,RuntimeControlError) as error:raise HTTPException(400,str(error) if isinstance(error,ValueError) else 'The recording or runtime is unavailable. Your live game is unchanged.')
    @app.get('/api/debugger/recordings')
    def recordings():return {'recordings':debugger.catalog()}
    @app.get('/api/debugger/live')
    def live():return call(debugger.live)
    @app.post('/api/debugger/capture')
    def capture():return call(debugger.capture)
    @app.post('/api/debugger/import')
    async def import_recording(request:Request):
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>512*1024*1024:raise HTTPException(413,'This recording is too large.')
        return call(debugger.import_recording,bytes(raw))
    @app.post('/api/debugger/inspect')
    async def inspect(request:Request):
        data=await body(request);return call(debugger.inspect,data.get('id'),data.get('tick'))
    @app.post('/api/debugger/verify')
    async def verify(request:Request):
        import asyncio
        data=await body(request);return await asyncio.to_thread(call,debugger.verify,data.get('id'),data.get('tick'))
    @app.post('/api/debugger/control')
    async def control(request:Request):
        data=await body(request);return call(debugger.control,data.get('action'),request.headers.get('x-xace-creator-token',''),data.get('confirm_session_wide'))
    @app.post('/api/debugger/export')
    async def export(request:Request):
        data=await body(request);view=call(debugger.inspect,data.get('id'),data.get('tick'))
        return {'schema':'xace.debugger_support.v1','recording_id':view['id'],'tick':view['tick'],'epoch':view['epoch'],'world_hash':view['world_hash'],'migration':view['epochs'],'dependencies':view['dependencies'],'membership':view['membership'],'verification':debugger.verifications.get((view['id'],view['tick']))}
