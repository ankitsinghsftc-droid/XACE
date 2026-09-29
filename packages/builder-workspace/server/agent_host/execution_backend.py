"""Versioned host execution boundary; independent of Agent/Builder wire contracts."""
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Any


@dataclass(frozen=True)
class ExecutionBackendStatus:
    backend_id: str
    ready: bool
    code: str
    message: str
    runtime_version: str = ''
    schema: str = 'xace.agent_execution_backend.v1'

    def to_dict(self):
        return dict(vars(self))


class AgentExecutionBackend(Protocol):
    """Own isolation, artifacts, storage and process transport, never game state."""
    backend_id: str
    def inspect(self) -> ExecutionBackendStatus: ...
    def open_client(self, capsule_root: Path, *, extra_environment: dict | None = None) -> Any: ...


def default_execution_backend() -> AgentExecutionBackend:
    # Future native backends implement this boundary, not new Agent APIs.
    from .docker_execution_backend import DockerExecutionBackend
    return DockerExecutionBackend()
