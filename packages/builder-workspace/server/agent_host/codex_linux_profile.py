"""AG-029 opt-in Linux permission-profile candidate; not default/launch certified.

The existing adapter contract remains unchanged. This explicit adapter maps its
restricted-read intent to pinned Codex permission profiles instead of sending
the unsupported SandboxPolicy.access field. Normal API/BYOK is never changed.
"""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from .codex_adapter import (
    CodexAppServerAdapter, CodexAppServerProbeResult, CodexAppServerProtocolError,
    CodexExecutableCandidate, initialize_codex_client, _JsonRpcLineSession,
)
from .codex_compatibility import REQUESTS, _accepts, _resolve

PROFILE = 'xace.codex_linux_permissions.v1'
RUNTIME_SHA256 = '0753dfe1d8b87a52436deb13eb1c549661ef4c84fee2c5aa688385eebeccb761'
DISABLED_FEATURES = tuple(('shell_tool unified_exec shell_snapshot view_image image_generation '
    'apps plugins remote_plugin plugin_sharing hooks multi_agent multi_agent_v2 browser_use '
    'browser_use_external computer_use in_app_browser in_app_local_automation code_mode '
    'memories goals skill_mcp_dependency_install skill_search tool_suggest workspace_dependencies').split())


def profile_config(cwd: str, runtime_root: str, mcp_servers: dict | None = None) -> dict:
    filesystem = {':minimal':'read', runtime_root:'read'}
    if cwd: filesystem[cwd] = 'read'
    return {'default_permissions':'xace_capsule', 'approval_policy':'never', 'web_search':'disabled',
            'features':{**dict.fromkeys(DISABLED_FEATURES,False),'code_mode_host':True},
            'permissions':{'xace_capsule':{'filesystem':filesystem,'network':{'enabled':False}}},
            'mcp_servers':mcp_servers or {}}


def adapt_params(method: str, params: dict, *, cwd: str, runtime_root: str, mcp_servers=None) -> dict:
    value = copy.deepcopy(params)
    if method in {'thread/start','thread/resume','thread/fork'}:
        if value.get('sandbox','read-only') != 'read-only' or value.get('approvalPolicy','never') != 'never':
            raise ValueError('Privileged sandbox or approval override rejected')
        value.pop('sandbox',None)
        # Optional fallback and response paging are absent from the pinned
        # stable schema. excludeTurns still prevents full history responses.
        value.pop('allowProviderModelFallback',None)
        value.pop('initialTurnsPage',None)
        if 'beforeTurnId' in value:
            raise ValueError('beforeTurnId is unsupported by this pinned stable runtime; no fork was performed')
        value['cwd'] = cwd
        value['approvalPolicy'] = 'never'
        supplied = value.pop('config',{})
        servers = supplied.get('mcp_servers',mcp_servers or {})
        if set(servers) - {'xace'}:
            raise ValueError('Only the XACE MCP server may be configured')
        value['config'] = profile_config(cwd,runtime_root,servers)
    elif method == 'turn/start':
        expected = {'type':'readOnly','access':{'type':'restricted','includePlatformDefaults':False,'readableRoots':[cwd]}}
        if value.get('sandboxPolicy') != expected or value.get('approvalPolicy') != 'never' or value.get('cwd') != cwd:
            raise ValueError('Turn isolation intent differs from the established capsule')
        value.pop('sandboxPolicy')
    return value


def validate_profile_schema(documents: dict, runtime_root: str) -> dict:
    doc = documents['ClientRequest.json']
    methods = {}
    for branch in doc.get('oneOf',doc.get('anyOf',[])):
        branch = _resolve(branch,doc)
        name = _resolve(branch['properties']['method'],doc)
        for method in name.get('enum',[name.get('const')]):
            if method in methods: raise ValueError('Duplicate method schema')
            methods[method] = branch
    for method, params in REQUESTS.items():
        params = copy.deepcopy(params)
        if method == 'thread/fork': params.pop('beforeTurnId',None)
        actual = adapt_params(method,params,cwd='/capsule',runtime_root=runtime_root)
        if method not in methods or not _accepts({'id':1,'method':method,'params':actual},methods[method],doc):
            raise ValueError(f'Pinned Linux contract mismatch: {method}')
    canonical = json.dumps(documents,sort_keys=True,separators=(',',':')).encode()
    return {'profile':PROFILE,'schema_fingerprint':hashlib.sha256(canonical).hexdigest(),
            'real_account_certified':False}


class LinuxProfiledClient:
    def __init__(self, executable, provider_home, capsule_root, *, extra_environment=None):
        self.runtime_root = str(Path(executable).resolve().parent.parent)
        self.capsule_root = Path(capsule_root).resolve(strict=True)
        self._threads = {}
        config = profile_config('',self.runtime_root)
        # Command-line config has precedence over inherited project/user config.
        arguments = []
        for key,value in config.items():
            def toml(v):
                if isinstance(v,dict): return '{'+','.join(json.dumps(k)+'='+toml(x) for k,x in v.items())+'}'
                return json.dumps(v)
            arguments.extend(['-c',key+'='+toml(value)])
        env = {'PATH':os.environ.get('PATH','/usr/local/bin:/usr/bin:/bin'),
               'HOME':str(provider_home),'CODEX_HOME':str(provider_home),'LANG':'C.UTF-8'}
        if extra_environment:
            if set(extra_environment) != {'XACE_MCP_SESSION_TOKEN'}:
                raise ValueError('Unexpected provider environment')
            env.update(extra_environment)
        self._proc = subprocess.Popen([executable,*arguments,'app-server','--strict-config'],
            cwd=provider_home,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,text=True,encoding='utf8')
        self._session = _JsonRpcLineSession(self._proc,timeout_seconds=30)

    @property
    def closed(self): return self._proc.poll() is not None

    def request(self, method, params):
        params = copy.deepcopy(params)
        binding = self._threads.get(params.get('threadId')) if isinstance(params,dict) else None
        cwd = params.get('cwd','') if isinstance(params,dict) else ''
        if method in {'thread/start','thread/resume','thread/fork','turn/start'}:
            cwd = cwd or (binding[0] if binding else '')
            path = Path(cwd).resolve(strict=True)
            if not cwd or not path.is_relative_to(self.capsule_root) or path == self.capsule_root:
                raise ValueError('Session requires a concrete XACE-owned capsule directory')
            cwd = str(path)
            if method == 'turn/start' and (not binding or binding[0] != cwd):
                raise ValueError('Turn must use its established capsule')
            actual = adapt_params(method,params,cwd=cwd,runtime_root=self.runtime_root,
                                  mcp_servers=binding[1] if binding else None)
        else: actual = params
        result = self._session.request(method,actual)
        if method in {'thread/start','thread/resume','thread/fork'}:
            self._threads[result['thread']['id']] = (cwd,actual['config']['mcp_servers'])
        return result

    def optional_request(self, method, params):
        return self._session.optional_request(method,params)
    def notify(self, method, params): self._session.notify(method,params)
    def respond(self, request_id, result): self._session.respond(request_id,result)
    def read_notification(self, timeout_seconds=.25): return self._session.read_notification(timeout_seconds)
    def close(self): self._session.close()


class CodexLinuxProfileAdapter(CodexAppServerAdapter):
    """Explicit certification candidate. Registry/default selection is unchanged."""
    def __init__(self, *, executable: str, provider_home: Path, capsule_root: Path, **kwargs):
        if any(key in kwargs for key in ('client_factory','app_server_probe','executable_resolver')):
            raise ValueError('The profiled adapter cannot accept substitute runtime factories')
        if sys.platform != 'linux': raise ValueError('Linux permission-profile backend required')
        expected = Path('/opt/codex/package/vendor/x86_64-unknown-linux-musl/bin/codex')
        if Path(executable).resolve() != expected or not Path('/.dockerenv').is_file():
            raise ValueError('This candidate requires the verified container runtime layout')
        if hashlib.sha256(Path(executable).read_bytes()).hexdigest() != RUNTIME_SHA256:
            raise ValueError('Unverified runtime artifact')
        self._profile_executable = str(Path(executable).resolve())
        self._provider_home = provider_home.resolve(strict=True)
        self._capsule_root = capsule_root.resolve(strict=True)
        if self._provider_home.is_relative_to(self._capsule_root) or self._capsule_root.is_relative_to(self._provider_home):
            raise ValueError('Provider storage and capsule tree must be separate')
        from .codex_runtime_lifecycle import _probe_stable_app_server, _is_revoked
        if _is_revoked('0.155.1',RUNTIME_SHA256): raise ValueError('Runtime revoked')
        self.profile_evidence = validate_profile_schema(_probe_stable_app_server(executable),
                                                        str(Path(executable).resolve().parent.parent))
        super().__init__(executable_resolver=lambda: CodexExecutableCandidate(executable,PROFILE),**kwargs)

    def _fork_session_sync(self, handle, **kwargs):
        with self._lock:
            if self._active_turns:
                raise ValueError('Cannot fork while a turn is active')
            child = super()._fork_session_sync(handle, **kwargs)
            # Fork emits notifications for both threads. Reopen each on its own
            # transport, with its own session-scoped MCP capability on next use.
            self._close_thread_client(child.provider_session_id)
            self._close_thread_client(handle.provider_session_id)
            return child

    def _make_profile_client(self, extra_environment=None):
        if hashlib.sha256(Path(self._profile_executable).read_bytes()).hexdigest() != RUNTIME_SHA256:
            raise ValueError('Runtime artifact changed since admission')
        return LinuxProfiledClient(self._profile_executable,self._provider_home,self._capsule_root,
                                    extra_environment=extra_environment)

    def _new_initialized_client(self, *, experimental_api=False, extra_environment=None):
        if experimental_api: raise ValueError('Experimental tools are disabled for this profile')
        client = self._make_profile_client(extra_environment)
        try: return client, initialize_codex_client(client)
        except Exception: client.close(); raise

    def _new_auth_client(self):
        return self._new_initialized_client()[0]

    def detect_sync(self):
        client = self._make_profile_client()
        try:
            initialized = initialize_codex_client(client)
            account = client.request('account/read',{'refreshToken':False})
            models = client.request('model/list',{'limit':100,'includeHidden':False})
            rate_limits = client.optional_request('account/rateLimits/read',{})
            result = CodexAppServerProbeResult(initialize=initialized,account=account,models=models,rate_limits=rate_limits)
            return self._status_from_probe(CodexExecutableCandidate(self._profile_executable,PROFILE),'0.155.1',result,())
        finally: client.close()
