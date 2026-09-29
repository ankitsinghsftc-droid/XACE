"""Adapter registry for AG-001 AgentHost scaffolding."""

from __future__ import annotations

from collections.abc import Iterable

from .isolated_codex_adapter import create_codex_adapter
from .contracts import AgentAdapter, AgentContractError, AgentProviderStatus


class AgentRegistryError(ValueError):
    """Raised when an agent adapter cannot be registered or resolved."""


class AgentAdapterRegistry:
    """In-memory registry for provider-neutral agent adapters."""

    def __init__(self, adapters: Iterable[AgentAdapter] | None = None) -> None:
        self._adapters: dict[str, AgentAdapter] = {}
        for adapter in adapters or ():
            self.register(adapter)

    def register(self, adapter: AgentAdapter, *, allow_replace: bool = False) -> None:
        provider_id = getattr(adapter, "provider_id", "")
        try:
            from .contracts import _require_identifier  # noqa: WPS433

            _require_identifier(provider_id, "provider_id")
        except AgentContractError as exc:
            raise AgentRegistryError(str(exc)) from exc

        if provider_id in self._adapters and not allow_replace:
            raise AgentRegistryError(f"agent adapter {provider_id!r} already exists")
        self._adapters[provider_id] = adapter

    def provider_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))

    def get(self, provider_id: str) -> AgentAdapter:
        try:
            return self._adapters[provider_id]
        except KeyError as exc:
            raise AgentRegistryError(f"unknown agent adapter {provider_id!r}") from exc

    async def detect(self, provider_id: str) -> AgentProviderStatus:
        return await self.get(provider_id).detect()

    async def list_statuses(self) -> tuple[AgentProviderStatus, ...]:
        statuses = []
        for provider_id in self.provider_ids():
            statuses.append(await self._adapters[provider_id].detect())
        return tuple(statuses)


def create_default_registry(
    *,
    enable_mock: bool = False,
    enable_codex: bool = False,
    codex_adapter: AgentAdapter | None = None,
    mock_adapter: AgentAdapter | None = None,
) -> AgentAdapterRegistry:
    """Return the production default registry.

    The mock adapter is opt-in so importing AG-001 has zero effect on existing
    API/BYOK behavior. Codex registration is explicit until the MCP tool bridge, proposal bridge,
    and conformance gates certify it for default production use.
    """

    adapters: list[AgentAdapter] = []
    if enable_codex:
        adapters.append(codex_adapter or create_codex_adapter())
    if enable_mock:
        if mock_adapter is None:
            raise AgentRegistryError(
                "the deterministic mock must be explicitly injected outside production"
            )
        adapters.append(mock_adapter)
    return AgentAdapterRegistry(adapters)
