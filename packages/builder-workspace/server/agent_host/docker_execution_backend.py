"""First isolated execution backend. Docker details stay below AgentAdapter."""
from __future__ import annotations
import contextlib
import hashlib
import copy
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import threading

from .execution_backend import ExecutionBackendStatus
from .execution_pin import pinned_image
from .codex_protocol import JsonRpcLineSession, MAX_FRAME_CHARS
from .codex_linux_profile import adapt_params

IMAGE = 'sha256:7b59fe353f2416fd2ef2b5088830b2168689a4b89bf93ffe8af973e49e9eb506'
PROVIDER_VOLUME = 'xace-ag029-provider'  # Retain the existing provider-owned login; never copy tokens.
RUNTIME_ROOT = '/opt/codex/package/vendor/x86_64-unknown-linux-musl'
SERVER = Path(__file__).resolve().parents[1]
POLICY = Path(__file__).with_name('container_seccomp.json')


def docker_executable():
    found = shutil.which('docker')
    if found: return str(Path(found).resolve())
    for root in (os.environ.get('LOCALAPPDATA',''),os.environ.get('ProgramFiles','')):
        if not root: continue
        for suffix in ('Programs/DockerDesktop/resources/bin/docker.exe','Docker/Docker/resources/bin/docker.exe'):
            path = Path(root)/suffix
            if path.is_file(): return str(path.resolve())
    return ''


class DockerExecutionBackend:
    backend_id = 'docker_wsl_v1'

    def _command(self,*args):
        executable = docker_executable()
        if not executable: raise RuntimeError('Docker Desktop is not installed')
        return [executable,'--context','desktop-linux',*args]

    def _run(self,*args):
        return subprocess.run(self._command(*args),capture_output=True,text=True,encoding='utf8',
                              timeout=12,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))

    def inspect(self):
        def status(ready,code,message):
            return ExecutionBackendStatus(self.backend_id,ready,code,message,'0.155.1')
        if os.name!='nt':
            return status(False,'backend_platform_unsupported','This backend currently supports Windows with Docker Desktop and WSL 2. API/BYOK is unchanged.')
        if not docker_executable():
            return status(False,'backend_dependency_missing','Install Docker Desktop with its WSL 2 Linux backend to use Codex Agent Mode. API/BYOK remains available.')
        try:
            context = self._run('context','inspect','desktop-linux','--format','{{.Endpoints.docker.Host}}')
            if context.returncode or context.stdout.strip()!='npipe:////./pipe/dockerDesktopLinuxEngine':
                return status(False,'backend_context_untrusted','Use the local Docker Desktop Linux context; remote daemons are not supported.')
            daemon = self._run('info','--format','{{.OSType}}')
            if daemon.returncode or daemon.stdout.strip()!='linux':
                return status(False,'backend_unavailable','Start Docker Desktop using WSL 2 / Linux containers. API/BYOK remains available.')
            selected=pinned_image(IMAGE)
            image = self._run('image','inspect',selected,'--format','{{.Id}}')
            if image.returncode or image.stdout.strip()!=selected:
                return status(False,'backend_runtime_missing','The verified Codex isolation image is missing. Follow the XACE runtime setup guide; no global CLI fallback will be used.')
            if not POLICY.is_file() or hashlib.sha256(POLICY.read_bytes()).hexdigest()!='cb584107039743dbdfd16ca124b8813d21fc3b2ea9b3e8ca86c9233233dad859' or not (SERVER/'agent_host/container_worker.py').is_file():
                return status(False,'backend_files_missing','Repair the XACE installation: isolation resources are missing.')
            return status(True,'ready','Codex isolated execution backend is ready.')
        except (ValueError,TypeError):
            return status(False,'backend_pin_invalid','The isolated runtime pin is invalid. Repeat verified local setup; API/BYOK remains available.')
        except (OSError,subprocess.TimeoutExpired):
            return status(False,'backend_unavailable','Docker Desktop is unavailable or timed out. Start its WSL 2 backend; API/BYOK remains available.')

    def open_client(self,capsule_root,*,extra_environment=None):
        health = self.inspect()
        if not health.ready: raise RuntimeError(health.message)
        root = Path(capsule_root).resolve(strict=True)
        if root.name!='agent_capsules' or root.parent.name!='.xace':
            raise ValueError('Execution requires the XACE capsule tree, never a project root')
        if Path(capsule_root).is_symlink() or Path(capsule_root).absolute()!=root or ',' in str(root): raise ValueError('Unsafe capsule mount path')
        if set(extra_environment or {})-{'XACE_MCP_SESSION_TOKEN'}:
            raise ValueError('Unexpected execution environment')
        name = 'xace-agent-'+secrets.token_hex(16)
        command = self._command('run','--rm','-i','--name',name,'--label','xace.owner=agent-execution',
            '--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
            '--security-opt','seccomp='+str(POLICY),'--pids-limit','256','--memory','2g',
            '--mount',f'type=volume,source={PROVIDER_VOLUME},target=/provider',
            '--tmpfs','/tmp:rw,nosuid,nodev,size=256m',
            '--mount',f'type=bind,source={root},target=/capsules,readonly',
            '--mount',f'type=bind,source={SERVER},target=/xace,readonly',
            '--entrypoint','python',pinned_image(IMAGE),'/xace/agent_host/container_worker.py')
        process = subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            text=True,encoding='utf8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        return DockerProfileClient(self,process,name,root,(extra_environment or {}).get('XACE_MCP_SESSION_TOKEN',''))


class _Input:
    def __init__(self,owner): self.owner=owner
    def write(self,line): self.owner.send('provider',json.loads(line))
    def flush(self): pass
    def close(self): self.owner.process.stdin.close()


class _Output:
    def __init__(self,owner): self.owner=owner
    def readline(self,limit):
        while True:
            line = self.owner.process.stdout.readline(limit)
            if not line: return line
            if len(line)>=limit or not line.endswith('\n'): raise ValueError('Oversized execution frame')
            frame = json.loads(line)
            if frame.get('channel')=='provider':
                return json.dumps(frame['value'])+'\n'
            if frame.get('channel')!='mcp' or not isinstance(frame.get('value'),dict):
                raise ValueError('Invalid execution channel')
            self.owner.relay(frame)
    def close(self): self.owner.process.stdout.close()


class _ProcessChannel:
    def __init__(self,backend,process,name,token):
        self.backend,self.process,self.name,self.token = backend,process,name,token
        self.stdin,self.stdout = _Input(self),_Output(self)
        self.lock = threading.Lock()
        self.relay_lock = threading.BoundedSemaphore(4)
        self.endpoint = None
        self.stopped = False
    def send(self,channel,value,request_id=None):
        line = json.dumps({'channel':channel,'value':value,'id':request_id},separators=(',',':'))+'\n'
        if len(line)>MAX_FRAME_CHARS: raise ValueError('Oversized execution frame')
        with self.lock:
            self.process.stdin.write(line); self.process.stdin.flush()
    def relay(self,frame):
        # The endpoint is fixed by the host's trusted session transport, never
        # accepted from the container, provider, model or tool arguments.
        if not self.endpoint or not self.token: raise ValueError('MCP not bound to this session')
        if not self.relay_lock.acquire(blocking=False): raise ValueError('Concurrent MCP relay overflow')
        def work():
            try:
                with socket.create_connection(self.endpoint,timeout=5) as conn:
                    conn.settimeout(60)
                    stream = conn.makefile('rwb')
                    def exchange(value):
                        stream.write((json.dumps(value)+'\n').encode()); stream.flush()
                        line=stream.readline(MAX_FRAME_CHARS+1)
                        if len(line)>MAX_FRAME_CHARS or not line.endswith(b'\n'): raise ValueError('MCP relay frame invalid')
                        return json.loads(line)
                    if exchange({'token':self.token}).get('ok') is not True: raise ValueError('MCP authentication failed')
                    result = exchange({'message':frame['value']})
                    if 'error' in result: raise ValueError('MCP relay failed')
                    self.send('mcp_response',result.get('response'),frame['id'])
            except Exception:
                self.terminate()
            finally: self.relay_lock.release()
        threading.Thread(target=work,daemon=True,name='xace-isolated-mcp-relay').start()
    def poll(self): return self.process.poll()
    def wait(self,timeout=None): return self.process.wait(timeout=timeout)
    def terminate(self):
        if self.stopped: return
        self.stopped=True
        # Only this unguessable, owned container; never remove the auth volume.
        with contextlib.suppress(Exception): self.backend._run('stop','--time','1',self.name)
        with contextlib.suppress(Exception): self.process.terminate()
    def kill(self):
        self.terminate()
        with contextlib.suppress(Exception): self.process.kill()


class DockerProfileClient:
    def __init__(self,backend,process,name,root,token):
        self.root=root
        self.bindings={}
        self.channel=_ProcessChannel(backend,process,name,token)
        self.session=JsonRpcLineSession(self.channel,timeout_seconds=45)
    @property
    def closed(self): return self.channel.poll() is not None
    def request(self,method,params):
        if method=='account/login/start' and (params or {}).get('type')!='chatgptDeviceCode':
            raise ValueError('Browser callback is unavailable in this isolated backend; use device code')
        value=copy.deepcopy(params or {})
        if method in {'thread/start','thread/resume','thread/fork','turn/start'}:
            binding=self.bindings.get(value.get('threadId'))
            host_cwd=value.get('cwd') or (binding[0] if binding else '')
            resolved=Path(host_cwd).resolve(strict=True)
            if resolved==self.root or not resolved.is_relative_to(self.root): raise ValueError('Invalid capsule scope')
            cwd='/capsules/'+resolved.relative_to(self.root).as_posix()
            if method=='turn/start':
                expected={'type':'readOnly','access':{'type':'restricted','includePlatformDefaults':False,'readableRoots':[host_cwd]}}
                if not binding or value.get('sandboxPolicy')!=expected: raise ValueError('Invalid turn isolation')
                value['sandboxPolicy']['access']['readableRoots']=[cwd]
            value['cwd']=cwd
            servers=value.get('config',{}).get('mcp_servers',binding[1] if binding else {})
            if servers:
                spec=servers.get('xace',{})
                args=spec.get('args',[])
                if len(args)!=5 or args[1:4]!=['--host','127.0.0.1','--port']:
                    raise ValueError('Invalid host MCP endpoint')
                port=int(args[4])
                if not 1<=port<=65535: raise ValueError('Invalid host MCP port')
                self.channel.endpoint=('127.0.0.1',port)
            value=adapt_params(method,value,cwd=cwd,runtime_root=RUNTIME_ROOT,mcp_servers=servers)
        result=self.session.request(method,value)
        if method in {'thread/start','thread/resume','thread/fork'}:
            self.bindings[result['thread']['id']]=(host_cwd,servers)
        return result
    def optional_request(self,method,params):
        from .codex_protocol import CodexAppServerProtocolError
        try: return self.request(method,params)
        except CodexAppServerProtocolError as exc:
            if exc.code!='provider_error': raise
            return {'unavailable':True,'method':method}
    def notify(self,method,params): self.session.notify(method,params)
    def respond(self,request_id,result): self.session.respond(request_id,result)
    def read_notification(self,timeout_seconds=.25): return self.session.read_notification(timeout_seconds)
    def close(self): self.session.close(); self.channel.terminate()
