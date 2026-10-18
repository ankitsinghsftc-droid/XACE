"""Explicit review/approve/apply for a registered, verified native setup stage."""
import copy,secrets,threading,time
from pathlib import Path
from authoring_identity import require,exact,digest
from authoring_apply import file_change,ACTIVATION
from authoring_transaction_contract import TransactionRequest
from authoring_transaction_files import sha,load_json
from authoring_saved_pair import SavedPair,MAP,CGS,NATIVE
from native_setup_plan import NativeSetupPlan,verify_setup
from native_setup_bundle import NativeSetupBundle


class NativeSetupReview:
    def __init__(self,host,stage_provider,*,lifetime_seconds=900):
        require(callable(stage_provider),'registered native stage provider required')
        self.host=host;self.provider=stage_provider;self.lifetime=lifetime_seconds;self.sessions={};self.lock=threading.RLock()
    def _candidate(self):
        self.host._coordinator().require_ready()
        root=self.host.root;raw=(root/'game.cgs.json').read_bytes();cgs=load_json(root/'game.cgs.json')
        stage=self.provider(copy.deepcopy(cgs));exact(stage,{'plan','native_inventory','files'})
        require(type(stage['plan']) is NativeSetupPlan and type(stage['native_inventory']) is bytes,'typed verified stage required')
        plan=stage['plan'];require(plan.to_dict()['engine']==self.host.gateway.identity['engine'],'setup engine differs from host')
        mapping,rows=verify_setup(plan,cgs,stage['native_inventory'])
        files=stage['files'];require(type(files) is dict and all(type(v) is bytes for v in files.values()),'native file bytes required')
        require(sum(len(v) for v in files.values())<=8*1024**2,'setup publication byte limit')
        native=NativeSetupBundle(root,engine=mapping.engine,allowed_paths=list(files))
        require(all(v is None for v in native.fingerprint().values()),'setup would replace existing native files')
        require(not any((root/p).exists() for p in [MAP,CGS,NATIVE]),'project already has an authoring baseline')
        preview=[]
        for path,data in sorted(files.items()):
            try:text=data.decode('utf-8') if len(data)<=65536 else None
            except UnicodeDecodeError:text=None
            preview.append(dict(path=path,operation='create',bytes=len(data),sha256=sha(data),text=text))
        report=dict(schema='xace.native_setup_review.v1',plan=plan.to_dict(),cgs_file_sha256=sha(raw),native_inventory_sha256=sha(stage['native_inventory']),files=preview,baseline_files=[MAP,CGS,NATIVE],runtime_activation=False)
        return dict(report=report,digest=digest(report),cgs=cgs,raw=raw,mapping=mapping,rows=rows,files=copy.deepcopy(files),native=native)
    def open(self,principal):
        require(type(principal) is str and 0<len(principal)<=256,'authenticated principal required')
        with self.lock:
            now=time.monotonic();self.sessions={k:v for k,v in self.sessions.items() if now-v['created']<=self.lifetime}
            require(len(self.sessions)<32,'setup session limit');candidate=self._candidate();token=secrets.token_urlsafe(32)
            self.sessions[token]=dict(principal=principal,created=now,digest=candidate['digest'],approval=None)
            return dict(token=token,proposal_digest=candidate['digest'],report=candidate['report'])
    def _get(self,principal,token,expected_digest):
        session=self.sessions.get(token)
        require(session is not None and session['principal']==principal,'unknown setup review')
        require(time.monotonic()-session['created']<=self.lifetime,'setup review expired')
        candidate=self._candidate()
        require(session['digest']==expected_digest==candidate['digest'],'setup source or reviewed files changed')
        return session,candidate
    def approve(self,principal,token,expected_digest):
        with self.lock:
            session,_=self._get(principal,token,expected_digest);session['approval']=secrets.token_urlsafe(32)
            return dict(token=token,proposal_digest=expected_digest,approval=session['approval'],can_commit=False)
    def cancel(self,principal,token):
        with self.lock:
            require(token in self.sessions and self.sessions[token]['principal']==principal,'unknown setup review');del self.sessions[token]
    def apply(self,principal,token,expected_digest,approval):
        with self.lock:
            session,c=self._get(principal,token,expected_digest)
            require(type(approval) is str and session['approval'] is not None and secrets.compare_digest(approval,session['approval']),'separate setup approval required')
            pair=SavedPair(self.host.root,mapping=c['mapping'],expected_cgs=c['cgs'],expected_normalized=c['rows'],recapture=self.host.gateway.capture)
            coordinator=self.host._coordinator(pair,native=c['native'])
            verification=dict(mapping=c['mapping'].to_dict(),cgs_digest=digest(c['cgs']),normalized_digest=digest(c['rows']))
            tx='setup-'+sha((token+approval).encode())[:32]
            request=TransactionRequest(tx,expected_digest,dict(canonical=dict(files=[file_change('game.cgs.json',sha(c['raw']),c['raw'])]),native=dict(files=[file_change(p,None,b) for p,b in sorted(c['files'].items())])),copy.deepcopy(ACTIVATION),verification,dict(cgs=c['cgs'],normalized=c['rows'],accepted_loss_digest=None))
            def authorize(_):
                # The coordinator already holds the project lock. Recheck bytes
                # directly; invoking readiness here would acquire that lock twice.
                require((self.host.root/'game.cgs.json').read_bytes()==c['raw'],'CGS changed after setup review')
                fresh=self.provider(copy.deepcopy(c['cgs']))
                require(type(fresh['plan']) is NativeSetupPlan and fresh['plan'].to_dict()==c['report']['plan'],'setup plan changed')
                require(sha(fresh['native_inventory'])==c['report']['native_inventory_sha256'] and fresh['files']==c['files'],'native stage changed after review')
                return True
            result=coordinator.commit(request,authorize=authorize)
            del self.sessions[token]
            return dict(state=result['state'],transaction_id=tx,files_written=True,runtime_activation=False)
