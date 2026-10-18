"""Explicit, pinned closed-editor authoring gateway; no runtime or network service.

Configured by the local host, never by browser paths. Calls and receipts are kept
under the persistent project .xace directory. Native files use engine serializers.
"""
import copy,os,subprocess,threading,uuid
from pathlib import Path
from authoring_identity import require,canonical,digest
from authoring_transaction_files import confined,sha,durable,atomic_json,load_json


class NativeEditorGateway:
    def __init__(self,root,*,engine,executable,executable_sha256,documents,source_roots,plugin_hashes,project_file=None,trusted_closed_project=False):
        require(trusted_closed_project is True,'explicit trusted closed-editor project required')
        require(engine in {'godot','unity','unreal'},'unsupported editor')
        self.root=Path(root).absolute();require(self.root.is_dir(),'registered project root missing')
        self.exe=Path(executable).absolute();require(sha(self.exe.read_bytes())==executable_sha256,'pinned editor mismatch')
        require(type(documents) is list and documents and len(documents)<=32 and len(set(documents))==len(documents),'document scope required')
        require(type(source_roots) is list and source_roots and len(set(source_roots))==len(source_roots),'source roots required')
        self.engine=engine;self.documents=sorted(documents);self.sources=sorted(source_roots);self.plugin_hashes=copy.deepcopy(plugin_hashes)
        require(type(plugin_hashes) is dict and plugin_hashes,'pinned authoring implementation required')
        for p in [*self.sources,*plugin_hashes]:confined(self.root,p)
        if engine=='unreal':require(len(documents)==1 and project_file is not None,'one approved Unreal map/project required');confined(self.root,project_file)
        self.project_file=project_file;self.lock=threading.RLock()
        self.identity=dict(engine=engine,profile='native.closed_editor_authoring.v1',root=str(self.root),editor_sha256=executable_sha256,documents=self.documents,source_roots=self.sources,plugin_hashes=self.plugin_hashes,project_file=project_file)
        config=dict(engine=engine,root=self.root.as_posix(),documents=self.documents)
        path=confined(self.root,'.xace/native-authoring-host.json')
        if path.exists():require(load_json(path)==config,'different native host already configured')
        else:durable(path,canonical(config))
    def _path(self,value):
        require(type(value) is str,'native path required')
        if value.startswith('res://'):value=value[6:]
        p=Path(value)
        if p.is_absolute():value=p.relative_to(self.root).as_posix()
        return confined(self.root,value.replace('\\','/'))
    def _files(self):
        result={}
        for name in self.sources:
            path=confined(self.root,name)
            require(path.exists(),'native source root missing')
            paths=[path] if path.is_file() else sorted(path.rglob('*'))
            for p in paths:
                relative=p.relative_to(self.root).as_posix();confined(self.root,relative)
                # Unity must import staged scene copies inside Assets for native
                # serialization. These reserved transaction artifacts are checked
                # individually through their receipt, not counted as game edits.
                if self.engine=='unity' and (relative=='Assets/__XaceAuthoringStage.meta' or relative.startswith('Assets/__XaceAuthoringStage/')):continue
                if p.is_file():result[relative]=sha(p.read_bytes())
                require(len(result)<=10000,'native source inventory limit')
        return result
    def invoke(self,action,**values):
        require(action in {'capture','prepare','commit','recover'},'unknown native action')
        with self.lock:
            require(sha(self.exe.read_bytes())==self.identity['editor_sha256'],'editor changed')
            for path,expected in self.plugin_hashes.items():require(sha(confined(self.root,path).read_bytes())==expected,'native authoring code changed')
            folder=confined(self.root,'.xace/native-authoring-calls/'+uuid.uuid4().hex);folder.mkdir(parents=True,exist_ok=False)
            command=folder/'command.json';durable(command,canonical(dict(action=action,**values)))
            if self.engine=='unity':argv=[str(self.exe),'-batchmode','-nographics','-projectPath',str(self.root),'-executeMethod','Xace.Authoring.Editor.UnityAuthoringCommand.Run','-xaceAuthoringCommand',str(command),'-logFile',str(folder/'editor.log')]
            elif self.engine=='godot':argv=[str(self.exe),'--headless','--editor','--path',str(self.root),'--','--xace-authoring-command=res://'+command.relative_to(self.root).as_posix()]
            else:argv=[str(self.exe),str(confined(self.root,self.project_file)),'-run=XaceAuthoring',f'-XaceAuthoringCommand={command}','-unattended','-nop4','-nosplash','-NullRHI','-NoSound','-NoShaderCompile','-stdout','-FullStdOutLogOutput',f'-abslog={folder/"editor.log"}']
            durable(folder/'invocation.json',canonical(dict(argv=argv,host=self.identity)))
            with (folder/'process.log').open('wb') as log:
                process=subprocess.run(argv,cwd=self.root,stdout=log,stderr=subprocess.STDOUT,timeout=900 if self.engine=='unity' else 240,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            result=load_json(folder/'result.json');require(process.returncode==0 and result.get('ok') is True,'native authoring failed: '+str(result.get('error','inspect retained call logs')))
            return result['result']
    def capture(self):return canonical(self.invoke('capture'))
    def _rows(self,prepared):
        receipt=prepared['receipt']
        if self.engine=='unity':return [dict(source=r['source'],backup=r['backup'],stage=r['staged'],before=r['before'],after=r['after']) for r in receipt['files']]
        if self.engine=='godot':return [dict(source=r['document'],backup=r['backup'],stage=r['stage'],before=r['before'],after=r['after']) for r in receipt['rows']]
        directory=Path(prepared['directory'])
        return [dict(source='Content/'+receipt['map'][6:]+'.umap',backup=str(directory/'before.umap'),stage=str(directory/'staged.umap'),before=receipt['before'],after=receipt['after'])]
    def prepare(self,transaction_id,request):
        require(set(request)=={'write_request'},'native write request required')
        if request['write_request'] is None:
            capture=self.capture();files=self._files();folder=confined(self.root,'.xace/native-authoring-noops/'+uuid.uuid4().hex)
            receipt=dict(schema='xace.native_authoring_noop.v1',state='prepared',capture_sha256=sha(capture),dependency_hashes=files)
            durable(folder/'receipt.json',canonical(receipt));atomic_json(folder/'state.json',{'state':'before'})
            return dict(directory=str(folder),receipt=receipt,approval_digest=digest(receipt))
        before=self._files();prepared=self.invoke('prepare',transaction_id=sha(transaction_id.encode())[:32],request=request['write_request'])
        require(self._files()==before,'native preparation changed source files')
        documents={self._path(r['source']).relative_to(self.root).as_posix() for r in self._rows(prepared)}
        prepared['dependency_hashes']={p:h for p,h in before.items() if p not in documents};return prepared
    def inspect(self,prepared):
        require(prepared['approval_digest']==digest(prepared['receipt']),'native receipt changed')
        receipt=prepared['receipt']
        if receipt.get('schema')=='xace.native_authoring_noop.v1':
            folder=self._path(prepared['directory']);require(folder.parent==self.root/'.xace/native-authoring-noops','foreign no-op receipt')
            if load_json(folder/'receipt.json')!=receipt or self._files()!=receipt['dependency_hashes']:return 'conflict'
            state=load_json(folder/'state.json')['state'];require(state in {'before','after'},'invalid no-op state');return state
        rows=self._rows(prepared);documents={self._path(r['source']).relative_to(self.root).as_posix() for r in rows}
        if {p:h for p,h in self._files().items() if p not in documents}!=prepared['dependency_hashes']:return 'conflict'
        before=after=True
        for r in rows:
            if not all(self._path(r[k]).is_file() and sha(self._path(r[k]).read_bytes())==r[v] for k,v in [('backup','before'),('stage','after')]):return 'conflict'
            value=sha(self._path(r['source']).read_bytes())
            if value not in {r['before'],r['after']}:return 'conflict'
            before=before and value==r['before'];after=after and value==r['after']
        return 'after' if after else 'before' if before else 'partial'
    def commit(self,prepared):
        require(self.inspect(prepared)!='conflict','native publication conflict')
        if prepared['receipt'].get('schema')=='xace.native_authoring_noop.v1':atomic_json(self._path(prepared['directory'])/'state.json',{'state':'after'});return
        return self.invoke('commit',prepared=prepared)
    def recover(self,prepared):
        require(self.inspect(prepared)!='conflict','native recovery conflict')
        if prepared['receipt'].get('schema')=='xace.native_authoring_noop.v1':atomic_json(self._path(prepared['directory'])/'state.json',{'state':'before'});return
        return self.invoke('recover',prepared=prepared)
