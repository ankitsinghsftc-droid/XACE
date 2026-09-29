"""Codex lifecycle on a replaceable isolated execution backend."""
import asyncio
from dataclasses import replace
from pathlib import Path
import tempfile

from .execution_backend import AgentExecutionBackend, default_execution_backend
from .codex_adapter import (CodexAppServerAdapter, CodexAppServerProbeResult,
    CodexExecutableCandidate, initialize_codex_client)
from .contracts import AgentAuthState


class IsolatedCodexAdapter(CodexAppServerAdapter):
    def __init__(self, *, project_path=None, execution_backend: AgentExecutionBackend | None=None, **kwargs):
        if any(k in kwargs for k in ('client_factory','app_server_probe','executable_resolver')):
            raise ValueError('Configure the execution backend, not a substitute provider process')
        self.execution_backend=execution_backend or default_execution_backend()
        self._temporary=None
        if project_path is None:
            self._temporary=tempfile.TemporaryDirectory(prefix='xace-agent-execution-')
            project_path=self._temporary.name
        self._capsule_root=Path(project_path).resolve()/'.xace/agent_capsules'
        super().__init__(**kwargs)

    def _new_initialized_client(self,*,experimental_api=False,extra_environment=None):
        if experimental_api: raise ValueError('Experimental provider tools are not supported')
        self._capsule_root.mkdir(parents=True,exist_ok=True)
        client=self.execution_backend.open_client(self._capsule_root,extra_environment=extra_environment)
        try: return client,initialize_codex_client(client)
        except Exception: client.close(); raise

    def close(self):
        super().close()
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None

    def _new_auth_client(self): return self._new_initialized_client()[0]

    async def detect(self): return await asyncio.to_thread(self.detect_sync)

    def detect_sync(self):
        health=self.execution_backend.inspect()
        if not health.ready:
            return self._status(installed=False,available=False,auth_state=AgentAuthState.MISSING,
                executable_path=None,version=None,capabilities=self._base_capabilities(),warnings=(health.message,),
                metadata={'app_server_responsive':False,'execution_backend':health.to_dict(),
                          'probe_error':health.message,'runtime_compatibility':{'state':health.code}})
        client=None
        try:
            client,initialized=self._new_initialized_client()
            result=CodexAppServerProbeResult(initialize=initialized,
                account=client.request('account/read',{'refreshToken':False}),
                models=client.request('model/list',{'limit':100,'includeHidden':False}),
                rate_limits=client.optional_request('account/rateLimits/read',{}))
            status=self._status_from_probe(CodexExecutableCandidate('isolated-provider',health.backend_id),
                                           health.runtime_version,result,())
            metadata={**status.metadata,'execution_backend':health.to_dict(),
                'probed_methods':['initialize','account/read','model/list','account/rateLimits/read']}
            return replace(status,executable_path=None,metadata=metadata)
        except Exception:
            return self._status(installed=True,available=False,auth_state=AgentAuthState.UNKNOWN,
                executable_path=None,version=health.runtime_version,capabilities=self._base_capabilities(),
                warnings=('Isolated Codex could not start. Check backend setup; no operation was replayed.',),
                metadata={'app_server_responsive':False,'execution_backend':health.to_dict(),
                          'probe_error':'isolated_provider_unavailable'})
        finally:
            if client is not None: client.close()

    def _fork_session_sync(self,handle,**kwargs):
        with self._lock:
            if self._active_turns: raise ValueError('Cannot fork during an active turn')
            child=super()._fork_session_sync(handle,**kwargs)
            self._close_thread_client(child.provider_session_id)
            self._close_thread_client(handle.provider_session_id)
            return child


def create_codex_adapter(*,project_path=None,**kwargs):
    return IsolatedCodexAdapter(project_path=project_path,**kwargs)
