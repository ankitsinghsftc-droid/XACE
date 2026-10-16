"""NEC-009 adapter for registered NEC-004/005/006 editor gateways.

The gateway is host code with pinned editor identity. It owns native load/unload,
dependency checks, staged saves and recovery. No gateway is loaded from a journal.
"""
import copy
from pathlib import Path
from authoring_identity import require
from native_adoption import digest
from authoring_transaction_contract import receipt
from authoring_transaction_files import atomic_json,load_json


class NativeParticipant:
    def __init__(self,gateway):
        self.gateway=gateway
        require(gateway.identity['engine'] in {'unity','godot','unreal'},'unknown engine gateway')
        self.identity=dict(schema='xace.authoring_native_participant.v1',gateway=copy.deepcopy(gateway.identity))

    def prepare(self,transaction_id,request,directory):
        directory=Path(directory);saved=directory/'prepared.json'
        if saved.exists():
            token=load_json(saved);require(token['request_digest']==digest(request),'native request changed');self._check(token);return token
        prepared=self.gateway.prepare(transaction_id,copy.deepcopy(request))
        require(type(prepared) is dict and {'directory','approval_digest','receipt'}<=set(prepared),'missing native prepared receipt')
        require(prepared['approval_digest']==digest(prepared['receipt']),'native receipt approval mismatch')
        require(prepared['receipt']['state']=='prepared','native stage not prepared')
        token=dict(schema='xace.authoring_prepared_native.v1',participant=digest(self.identity),request_digest=digest(request),prepared=prepared)
        require(self.gateway.inspect(copy.deepcopy(prepared))=='before','native preparation modified the source')
        atomic_json(saved,token);return token

    def _check(self,token):
        require(token['schema']=='xace.authoring_prepared_native.v1' and token['participant']==digest(self.identity),'foreign native receipt')
        require(token['prepared']['approval_digest']==digest(token['prepared']['receipt']),'native prepared receipt corrupted')

    def inspect(self,token,directory):
        self._check(token);state=self.gateway.inspect(copy.deepcopy(token['prepared']))
        require(state in {'before','after','partial','conflict'},'invalid native verification state');return state

    def publish(self,token,directory):
        self._check(token)
        state=self.inspect(token,directory)
        require(state!='conflict','native source conflict; newer work preserved')
        if state!='after':self.gateway.commit(copy.deepcopy(token['prepared']))
        require(self.inspect(token,directory)=='after','native saved recapture failed')
        return receipt(self,token,'after')

    def restore(self,token,directory):
        self._check(token)
        state=self.inspect(token,directory)
        require(state!='conflict','native rollback conflict; newer work preserved')
        if state!='before':self.gateway.recover(copy.deepcopy(token['prepared']))
        require(self.inspect(token,directory)=='before','native recovery conflict')
        return receipt(self,token,'before')
