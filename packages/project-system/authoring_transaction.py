"""NEC-009 recoverable authoring coordinator, separate from runtime epochs.

All source publication follows a durable decision. A missing receipt is recovered
by inspecting the participant, never by guessing whether its call completed.
"""
import copy
from contextlib import contextmanager
import sys
from dataclasses import asdict
from pathlib import Path

from authoring_identity import require
from native_adoption import digest
from authoring_transaction_contract import validate_request,receipt
from authoring_transaction_files import atomic_json,load_json,confined

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'packages/builder-workspace/server'))
from cgs_persistence import CGSPersistence

TERMINAL={'committed','rolled_back','aborted'}


class AuthoringCoordinator:
    def __init__(self,project_root,participants,*,verify_pair,baseline_participant,baseline_request,checkpoint=None,historical_participants=None):
        self.root=Path(project_root).absolute();self.store=CGSPersistence(self.root)
        self.journal=confined(self.root,'.xace/authoring-transactions')
        self.participants=dict(sorted(participants.items()));self.verify_pair=verify_pair
        self.baseline_participant=baseline_participant;self.baseline_request=baseline_request
        self.checkpoint=checkpoint or (lambda event:None)
        self.historical_participants=historical_participants
        require(callable(verify_pair) and callable(baseline_request),'host pair/baseline verification required')
        for name in self.participants:require(name!='baseline' and name.replace('_','').isalnum() and len(name)<=64,'invalid participant name')

    def _save(self,folder,state,event):
        atomic_json(folder/'state.json',state);self.checkpoint(event)

    def _load(self,transaction_id,*,for_status=False):
        folder=confined(self.journal,transaction_id);state=load_json(folder/'state.json');manifest=load_json(folder/'manifest.json')
        require(state['schema']=='xace.authoring_transaction_state.v1' and manifest['schema']=='xace.authoring_transaction.v1','unknown journal version')
        require(state['state'] in TERMINAL|{'preparing','decided','recovery_required','recovery_conflict','rolling_back'},'unknown transaction state')
        require(state['manifest_digest']==digest(manifest),'journal manifest changed')
        registered=self.participants
        if for_status and manifest['participants']!={k:p.identity for k,p in registered.items()} and self.historical_participants is not None:
            # Only host-registered implementations may recognize another authoring
            # operation's journal. Never import code or classes from that journal.
            registered=self.historical_participants(copy.deepcopy(manifest['participants']))
        require(type(registered) is dict and set(registered)==set(self.participants),'registered participant set differs')
        require(manifest['transaction_id']==transaction_id and manifest['participants']=={k:p.identity for k,p in registered.items()},'registered participants differ')
        require(manifest['baseline_participant']==self.baseline_participant.identity,'baseline participant differs')
        for name,token in state['tokens'].items():
            require(name in self.participants and state['token_digests'][name]==digest(token),'prepared token changed')
        if state.get('baseline_token') is not None:require(state['baseline_token_digest']==digest(state['baseline_token']),'baseline token changed')
        return folder,state,manifest

    def status(self):
        """Readiness consumers MUST gate on this result before Play/build publication."""
        with self.store.cgs_write_lock():return self._status()

    def require_ready(self):
        """Mandatory authoring preflight for opt-in host Play/build entry points.

        This does not admit/activate a runtime or replace package readiness checks.
        """
        status=self.status()
        require(not status['play_build_blocked'],'authoring recovery blocks Play/build')
        return status

    @contextmanager
    def publication_gate(self):
        """Hold the shared authoring lock across host Play/build preflight/start.

        The caller still owns package admission and XP-018/019 runtime activation.
        """
        with self.store.cgs_write_lock():
            status=self._status()
            require(not status['play_build_blocked'],'authoring recovery blocks Play/build')
            yield status

    def _status(self):
        pending=[]
        if self.journal.exists():
            for folder in sorted(self.journal.iterdir()):
                if not folder.is_dir():continue
                try:
                    _,state,_=self._load(folder.name,for_status=True)
                    if state['state'] not in TERMINAL:pending.append(dict(transaction_id=folder.name,state=state['state']))
                except (ValueError,OSError,KeyError,TypeError):pending.append(dict(transaction_id=folder.name,state='corrupt_or_incomplete'))
        return dict(schema='xace.authoring_recovery_gate.v1',play_build_blocked=bool(pending),pending=pending,runtime_activation_performed=False)

    def commit(self,request,*,authorize):
        validate_request(request,self.participants)
        require(callable(authorize),'fresh publication approval required')
        with self.store.cgs_write_lock():
            folder=confined(self.journal,request.transaction_id)
            if folder.exists():
                _,state,manifest=self._load(request.transaction_id)
                require(manifest['request']==asdict(request),'transaction ID reused for different request')
                require(state['state']=='committed','transaction requires explicit recovery')
                return self._verify_committed(folder,state,manifest)
            require(not self._status()['play_build_blocked'],'pending recovery blocks authoring publication')
            require(authorize(request) is True,'publication not approved or stale')
            manifest=dict(schema='xace.authoring_transaction.v1',transaction_id=request.transaction_id,request=asdict(request),participants={k:p.identity for k,p in self.participants.items()},baseline_participant=self.baseline_participant.identity,baseline_before=self.baseline_participant.fingerprint())
            folder.mkdir(parents=True,exist_ok=False)
            atomic_json(folder/'manifest.json',manifest)
            state=dict(schema='xace.authoring_transaction_state.v1',manifest_digest=digest(manifest),state='preparing',tokens={},token_digests={},receipts={},baseline_token=None,activation=request.activation_record)
            self._save(folder,state,'intent_durable')
            try:
                for name,participant in self.participants.items():
                    directory=folder/name;directory.mkdir(exist_ok=True)
                    token=participant.prepare(request.transaction_id,copy.deepcopy(request.participant_requests[name]),directory)
                    self.checkpoint('prepared_before_receipt:'+name)
                    require(participant.inspect(token,directory) in {'before','after'},'participant not stable before decision')
                    state['tokens'][name]=token;state['token_digests'][name]=digest(token)
                    self._save(folder,state,'prepared:'+name)
                require(authorize(request) is True,'approval/source changed during staging')
                # Staging must not have changed source. Each participant's contract
                # checks before hashes/dependencies again in its publication call.
                state['state']='decided';self._save(folder,state,'decision_durable')
                return self._finish(folder,state,manifest)
            except Exception as exc:
                state['error']=str(exc)[:1024]
                if state['state']=='preparing':state['state']='aborted'
                elif state['state']!='committed':state['state']='recovery_required'
                self._save(folder,state,'failure_recorded')
                raise

    def _finish(self,folder,state,manifest):
        require(set(state['tokens'])==set(self.participants),'incomplete prepared decision')
        for name,participant in self.participants.items():
            token=state['tokens'][name];directory=folder/name
            observed=participant.inspect(token,directory)
            require(observed!='conflict','newer participant work preserved; recovery conflict')
            if observed!='after':participant.publish(token,directory)
            self.checkpoint('published_before_receipt:'+name)
            require(participant.inspect(token,directory)=='after','participant saved verification failed')
            state['receipts'][name]=receipt(participant,token,'after')
            self._save(folder,state,'published:'+name)
        require(self.verify_pair(copy.deepcopy(manifest),copy.deepcopy(state['tokens'])) is True,'saved CGS/native pair does not verify')
        self.checkpoint('pair_verified')
        if state['baseline_token'] is None:
            require(self.baseline_participant.fingerprint()==manifest['baseline_before'],'baseline changed independently; preserve newer baseline')
            request=self.baseline_request(copy.deepcopy(manifest),copy.deepcopy(state['receipts']))
            directory=folder/'baseline';directory.mkdir(exist_ok=True)
            token=self.baseline_participant.prepare(manifest['transaction_id'],request,directory)
            state['baseline_token']=token;state['baseline_token_digest']=digest(token)
            self._save(folder,state,'baseline_prepared')
        participant=self.baseline_participant;token=state['baseline_token'];directory=folder/'baseline'
        if participant.inspect(token,directory)!='after':participant.publish(token,directory)
        self.checkpoint('baseline_published_before_receipt')
        require(participant.inspect(token,directory)=='after','baseline publication failed')
        require(all(p.inspect(state['tokens'][name],folder/name)=='after' for name,p in self.participants.items()),'store drift before completion')
        require(self.verify_pair(copy.deepcopy(manifest),copy.deepcopy(state['tokens'])) is True,'pair drift before completion')
        state['baseline_receipt']=receipt(participant,token,'after');state['state']='committed'
        self._save(folder,state,'complete_durable')
        return copy.deepcopy(state)

    def _verify_committed(self,folder,state,manifest):
        require(all(p.inspect(state['tokens'][name],folder/name)=='after' for name,p in self.participants.items()),'completed transaction stores have drifted')
        require(self.baseline_participant.inspect(state['baseline_token'],folder/'baseline')=='after','completed baseline drifted')
        require(self.verify_pair(copy.deepcopy(manifest),copy.deepcopy(state['tokens'])) is True,'completed pair mismatch')
        return copy.deepcopy(state)

    @staticmethod
    def _restored(participant,token,directory):
        observed=participant.inspect(token,directory)
        if observed=='before':return True
        # A byte-identical file participant is both before and after; no native
        # gateway may use this exception to skip a compensating restore.
        from authoring_transaction_files import FileParticipant
        return isinstance(participant,FileParticipant) and observed=='after' and all(r['before']==r['after'] for r in token['rows'])

    def recover(self,transaction_id,*,action='resume',configure_verification=None):
        require(action in {'resume','rollback'},'unknown recovery action')
        with self.store.cgs_write_lock():
            folder,state,manifest=self._load(transaction_id)
            if configure_verification is not None:
                configure_verification(copy.deepcopy(state),copy.deepcopy(manifest))
            if state['state']=='committed':return self._verify_committed(folder,state,manifest)
            if state['state'] in {'aborted','rolled_back'}:return copy.deepcopy(state)
            try:
                if state['state']=='preparing':
                    # Prepare has no publication authority. Retain abandoned stages.
                    state['state']='aborted';self._save(folder,state,'aborted_before_decision');return copy.deepcopy(state)
                if state.get('recovery_action')=='rollback':require(action=='rollback','rollback recovery must continue rollback')
                if action=='resume':return self._finish(folder,state,manifest)
                state['recovery_action']='rollback';state['state']='rolling_back';self._save(folder,state,'rollback_decision')
                if state['baseline_token'] is not None:
                    self.baseline_participant.restore(state['baseline_token'],folder/'baseline');self.checkpoint('baseline_restored')
                for name,p in reversed(list(self.participants.items())):
                    p.restore(state['tokens'][name],folder/name);self.checkpoint('restored:'+name)
                require(all(self._restored(p,state['tokens'][name],folder/name) for name,p in self.participants.items()),'rollback verification failed')
                if state['baseline_token'] is not None:require(self._restored(self.baseline_participant,state['baseline_token'],folder/'baseline'),'baseline rollback drift')
                state['state']='rolled_back';self._save(folder,state,'rollback_complete');return copy.deepcopy(state)
            except Exception as exc:
                state['state']='recovery_conflict';state['error']=str(exc)[:1024]
                self._save(folder,state,'recovery_blocked');raise
