"""NEC-009 confined durable file participant for host-owned authoring stores.

Native editor stores use the native participant bridge instead. Windows replaces
retain the actual displaced bytes to detect an external writer racing the CAS.
"""
import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path

from authoring_identity import require,exact
from native_adoption import encode,digest
from authoring_transaction_contract import receipt


def sha(data):return hashlib.sha256(data).hexdigest()


def confined(root:Path,relative:str):
    require(type(relative) is str and relative and '\\' not in relative and ':' not in relative,'invalid relative path')
    require(all(p not in {'','.','..'} for p in relative.split('/')),'invalid path components')
    root=Path(root).absolute();current=root
    for current in [root,*[root.joinpath(*relative.split('/')[:i]) for i in range(1,len(relative.split('/'))+1)]]:
        if current.exists():require(not current.is_symlink() and not (getattr(current.lstat(),'st_file_attributes',0)&0x400),'reparse point refused')
    target=root/relative;require(target.resolve().is_relative_to(root.resolve()),'path escaped participant root')
    return target


def read_state(path):
    require(not path.is_dir(),'target is directory')
    return sha(path.read_bytes()) if path.exists() else None


def durable(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('wb') as handle:handle.write(data);handle.flush();os.fsync(handle.fileno())


def atomic_json(path,value):
    next_path=path.with_suffix('.next');durable(next_path,encode(value));os.replace(next_path,path)


def load_json(path):
    def pairs(rows):
        result={}
        for key,value in rows:
            require(key not in result,'duplicate journal key');result[key]=value
        return result
    data=path.read_bytes();require(len(data)<=16*1024**2,'journal byte limit')
    return json.loads(data,object_pairs_hook=pairs)


def replace_owned(path,source,expected,displaced):
    require(read_state(path)==expected,'file CAS conflict')
    require(not displaced.exists(),'displaced image already exists')
    temporary=source.with_suffix(source.suffix+'.publish');durable(temporary,source.read_bytes())
    if expected is None:
        # Creation is atomic and refuses an independently created destination.
        os.link(temporary,path);temporary.unlink();return
    require(os.name=='nt','certified replacement profile requires Windows')
    replace=ctypes.WinDLL('kernel32',use_last_error=True).ReplaceFileW
    replace.argtypes=[ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_void_p]
    replace.restype=ctypes.c_int
    if not replace(str(path),str(temporary),str(displaced),0,None,None):raise ctypes.WinError(ctypes.get_last_error())
    require(read_state(displaced)==expected,'concurrent replacement preserved in displaced image; recovery conflict')


class FileParticipant:
    def __init__(self,root:Path,*,name:str,allowed_paths:list[str]):
        self.root=Path(root).absolute();self.allowed=sorted(set(allowed_paths))
        for path in self.allowed:confined(self.root,path)
        self.identity=dict(schema='xace.authoring_file_participant.v1',name=name,root=str(self.root),allowed_paths=self.allowed)

    def fingerprint(self):return {p:read_state(confined(self.root,p)) for p in self.allowed}

    def prepare(self,transaction_id,request,directory):
        exact(request,{'files'});require(type(request['files']) is list and 0<len(request['files'])<=32,'file participant limit')
        directory=Path(directory);directory.mkdir(parents=True,exist_ok=True);saved=directory/'prepared.json'
        if saved.exists():
            token=load_json(saved);require(token['request_digest']==digest(request),'participant request changed');list(self._rows(token,directory));return token
        rows=[];seen=set()
        for i,entry in enumerate(request['files']):
            exact(entry,{'path','before','after_base64'});relative=entry['path'];require(relative in self.allowed and relative not in seen,'unregistered/duplicate target');seen.add(relative)
            path=confined(self.root,relative);require(read_state(path)==entry['before'],'stale file before-image')
            data=base64.b64decode(entry['after_base64'],validate=True);require(len(data)<=16*1024**2,'file stage limit')
            before=path.read_bytes() if path.exists() else b''
            durable(directory/f'{i}.before',before);durable(directory/f'{i}.after',data)
            rows.append(dict(path=relative,before=entry['before'],after=sha(data),index=i))
        token=dict(schema='xace.authoring_prepared_files.v1',participant=digest(self.identity),request_digest=digest(request),rows=rows)
        atomic_json(saved,token);return token

    def _rows(self,token,directory):
        exact(token,{'schema','participant','request_digest','rows'})
        require(token['schema']=='xace.authoring_prepared_files.v1' and token['participant']==digest(self.identity),'foreign participant token')
        require(type(token['rows']) is list and 0<len(token['rows'])<=32,'invalid prepared rows')
        seen=set()
        for i,row in enumerate(token['rows']):
            exact(row,{'path','before','after','index'});require(row['index']==i and row['path'] in self.allowed and row['path'] not in seen,'invalid target/index');seen.add(row['path'])
            require(read_state(Path(directory)/f'{i}.after')==row['after'],'stage artifact corrupted')
            require(read_state(Path(directory)/f'{i}.before')==(row['before'] or sha(b'')),'before-image corrupted')
            yield row,confined(self.root,row['path'])

    def inspect(self,token,directory):
        states=[]
        for row,path in self._rows(token,directory):
            for name,expected in [('displaced',row['before']),('restore-displaced',row['after']),('created-rollback',row['after'])]:
                displaced=Path(directory)/f'{row["index"]}.{name}'
                if displaced.exists() and read_state(displaced)!=expected:return 'conflict'
            value=read_state(path)
            states.append('after' if value==row['after'] else 'before' if value==row['before'] else 'conflict')
        if 'conflict' in states:return 'conflict'
        if all(s=='after' for s in states):return 'after'
        if all(s=='before' for s in states):return 'before'
        return 'partial'

    def publish(self,token,directory):
        require(self.inspect(token,directory)!='conflict','file publication conflict')
        for row,path in self._rows(token,directory):
            if read_state(path)==row['after']:continue
            replace_owned(path,Path(directory)/f'{row["index"]}.after',row['before'],Path(directory)/f'{row["index"]}.displaced')
        require(self.inspect(token,directory)=='after','publication verification failed')
        return receipt(self,token,'after')

    def restore(self,token,directory):
        require(self.inspect(token,directory)!='conflict','newer edit preserved; rollback conflict')
        for row,path in reversed(list(self._rows(token,directory))):
            if read_state(path)==row['before']:continue
            if row['before'] is None:
                retained=Path(directory)/f'{row["index"]}.created-rollback'
                require(not retained.exists() and read_state(path)==row['after'],'created file rollback conflict')
                os.rename(path,retained)
                require(read_state(retained)==row['after'],'newer created file retained for conflict recovery')
                continue
            replace_owned(path,Path(directory)/f'{row["index"]}.before',row['after'],Path(directory)/f'{row["index"]}.restore-displaced')
        require(all(read_state(path)==row['before'] for row,path in self._rows(token,directory)),'rollback verification failed')
        return receipt(self,token,'before')
