"""Bounded create-only native setup bundle using durable file batches."""
from pathlib import Path
from authoring_identity import require,exact,digest
from authoring_transaction_files import atomic_json,load_json
from authoring_transaction_contract import receipt
from native_setup_files import NativeSetupFiles


class NativeSetupBundle:
    def __init__(self,root,*,engine,allowed_paths):
        require(type(allowed_paths) is list and 0<len(allowed_paths)<=256,'setup bundle file limit')
        paths=sorted(allowed_paths);folded=[p.casefold() for p in paths]
        require(len(set(folded))==len(paths),'ambiguous bundle path')
        require(not any(b.startswith(a+'/') for a in folded for b in folded),'bundle file/directory alias')
        self.groups=[NativeSetupFiles(root,engine=engine,allowed_paths=paths[i:i+32]) for i in range(0,len(paths),32)]
        self.identity=dict(schema='xace.native_setup_bundle.v1',groups=[g.identity for g in self.groups])
    def fingerprint(self):return {k:v for g in self.groups for k,v in g.fingerprint().items()}
    def prepare(self,transaction_id,request,directory):
        exact(request,{'files'});require(type(request['files']) is list,'setup files required')
        rows=request['files'];by_path={r['path']:r for r in rows}
        require(len(by_path)==len(rows) and set(by_path)==set(self.fingerprint()),'setup bundle write set')
        directory=Path(directory);directory.mkdir(parents=True,exist_ok=True);saved=directory/'prepared.json'
        if saved.exists():
            token=load_json(saved);require(token['request_digest']==digest(request),'setup bundle request changed');self._check(token);return token
        tokens=[]
        for i,g in enumerate(self.groups):tokens.append(g.prepare(transaction_id,dict(files=[by_path[p] for p in g.allowed]),directory/str(i)))
        token=dict(schema='xace.prepared_setup_bundle.v1',participant=digest(self.identity),request_digest=digest(request),groups=tokens)
        atomic_json(saved,token);return token
    def _check(self,token):
        exact(token,{'schema','participant','request_digest','groups'})
        require(token['schema']=='xace.prepared_setup_bundle.v1' and token['participant']==digest(self.identity) and len(token['groups'])==len(self.groups),'foreign setup bundle token')
    def inspect(self,token,directory):
        self._check(token);states=[g.inspect(t,Path(directory)/str(i)) for i,(g,t) in enumerate(zip(self.groups,token['groups']))]
        if 'conflict' in states:return 'conflict'
        if all(s=='before' for s in states):return 'before'
        if all(s=='after' for s in states):return 'after'
        return 'partial'
    def publish(self,token,directory):
        require(self.inspect(token,directory)!='conflict','setup bundle publication conflict')
        for i,(g,t) in enumerate(zip(self.groups,token['groups'])):g.publish(t,Path(directory)/str(i))
        require(self.inspect(token,directory)=='after','setup bundle readback failed');return receipt(self,token,'after')
    def restore(self,token,directory):
        require(self.inspect(token,directory)!='conflict','newer setup content retained')
        for i in reversed(range(len(self.groups))):self.groups[i].restore(token['groups'][i],Path(directory)/str(i))
        require(self.inspect(token,directory)=='before','setup bundle rollback failed');return receipt(self,token,'before')


def registered_setup_bundle(root,engine,identity):
    """Recognize only this registered create-only implementation and fixed root."""
    require(type(identity) is dict and identity.get('schema')=='xace.native_setup_bundle.v1','unknown native setup participant')
    groups=identity.get('groups');require(type(groups) is list and 0<len(groups)<=8,'setup group limit')
    paths=[]
    for group in groups:
        require(type(group) is dict and type(group.get('allowed_paths')) is list,'invalid setup group')
        paths.extend(group['allowed_paths'])
    participant=NativeSetupBundle(root,engine=engine,allowed_paths=paths)
    require(participant.identity==identity,'foreign setup root, engine or publication policy')
    return participant
