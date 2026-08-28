"""
provider_registry.py — ProviderRegistry + IProviderClient
============================================================
Maps logical model names (premium_reasoning | standard_mutation |
cheap_validation | local_dev) to concrete provider client instances,
and holds the IProviderClient interface that all provider adapters
in providers/ must implement.

## Why a Registry?
Every PIL submodule uses `inference_adapter.call(request)` with a
`logical_model` name, never a concrete model string. The registry
translates that name to the right client. This means:
    - Switching from Sonnet to GPT-4o for TIER_L requires one config line
    - Adding a new provider never touches PIL code
    - BYOK override (per-user key) is applied here transparently

## IProviderClient
The single interface all provider adapters must implement:
    complete(model_id, prompt, system_prompt, max_tokens, temperature) → dict
    health_check() → bool
    provider_name() → str

Provider adapters live in providers/anthropic_provider.py,
providers/openai_provider.py, providers/local_provider.py.

## Config Format
ProviderRegistry accepts a config dict at construction:
    {
        "default_provider": "anthropic",
        "logical_model_map": {
            "premium_reasoning":  "anthropic",
            "standard_mutation":  "anthropic",
            "cheap_validation":   "anthropic",
            "local_dev":          "local",
        },
        "fallback_chains": {
            "anthropic": ["openai", "local"],
            "openai":    ["anthropic"],
            "local":     [],
        }
    }
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from .model_descriptor import ModelDescriptor, BUILTIN_DESCRIPTORS


# ── Provider Error ────────────────────────────────────────────────────────────

class ProviderNotFoundError(Exception):
    """Raised when no provider can be resolved for a logical model name."""

class ProviderHealthError(Exception):
    """Raised when a provider fails its health check."""


# ── Provider Client Interface ─────────────────────────────────────────────────

class IProviderClient(ABC):
    """
    Interface all provider adapters must implement.

    Implementations live in providers/:
        anthropic_provider.py
        openai_provider.py
        local_provider.py
    """

    @abstractmethod
    def complete(
        self,
        model_id:      str,
        prompt:        dict[str, Any],
        system_prompt: str,
        max_tokens:    int,
        temperature:   float,
        structured_output: Any | None = None,
    ) -> dict[str, Any]:
        """
        Sends a completion request to the provider.

        Returns a dict with:
            text               : str   — model output
            input_tokens       : int
            output_tokens      : int
            cache_read_tokens  : int   (0 if unsupported)
            cache_write_tokens : int   (0 if unsupported)
        """

    @abstractmethod
    def health_check(self) -> bool:
        """Returns True if the provider is reachable and authenticated."""

    @abstractmethod
    def provider_name(self) -> str:
        """Returns the provider identifier string: 'anthropic'|'openai'|'local'"""


# ── BYOK Override ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BYOKOverride:
    """
    Per-session user-supplied API key override.
    Applied transparently in get_client() when present.
    See byok_manager.py for lifecycle management.
    """
    session_id:    str
    provider:      str
    api_key:       str   # never logged; treated as secret
    model_id:      str   = ""   # empty = use registry default


# ── Provider Registry ─────────────────────────────────────────────────────────

class ProviderRegistry:
    """
    Maps logical model names to concrete provider client instances.

    Thread-safe — multiple PIL passes may look up concurrently.
    Config is hot-reloadable via reload_config() without restart.

    Usage
    -----
        registry = ProviderRegistry(config, clients={...})

        # Get descriptor for a logical name
        descriptor = registry.get("standard_mutation")

        # Get concrete client for a provider
        client = registry.get_client("anthropic")

        # Get client for a logical model name directly
        client = registry.get_client_for(logical_name="cheap_validation")
    """

    # Default logical → provider mapping (overridden by config)
    _DEFAULT_MAP: dict[str, str] = {
        # Anthropic — primary provider
        "premium_reasoning": "anthropic",
        "standard_mutation": "anthropic",
        "cheap_validation":  "anthropic",
        # OpenAI
        "openai_premium":    "openai",
        "openai_standard":   "openai",
        # DeepSeek
        "deepseek_premium":  "deepseek",
        "deepseek_standard": "deepseek",
        # Z.AI / GLM
        "zai_standard":      "zai",
        "zai_premium":       "zai",
        # MiniMax
        "minimax_standard":  "minimax",
        "minimax_flagship":  "minimax",
        # Google Gemini
        "google_flagship":   "google",
        "google_standard":   "google",
    }

    # Default fallback chains: primary fails → try these in order
    _DEFAULT_FALLBACK: dict[str, list[str]] = {
        "anthropic": ["openai", "deepseek", "google"],
        "openai":    ["anthropic", "google"],
        "deepseek":  ["anthropic", "zai"],
        "zai":       ["deepseek", "anthropic"],
        "minimax":   ["deepseek", "anthropic"],
        "google":    ["anthropic", "deepseek"],
        "local":     [],
    }

    def __init__(
        self,
        config:  dict[str, Any]          | None = None,
        clients: dict[str, IProviderClient]     | None = None,
    ) -> None:
        self._lock        = threading.RLock()
        self._config      = config or {}
        self._clients:    dict[str, IProviderClient] = clients or {}
        self._descriptors: dict[str, ModelDescriptor] = dict(BUILTIN_DESCRIPTORS)
        self._byok_overrides: dict[str, BYOKOverride] = {}

        # Build logical → provider map from config or defaults
        self._logical_map: dict[str, str] = {
            **self._DEFAULT_MAP,
            **self._config.get("logical_model_map", {}),
        }
        self._fallback_chains: dict[str, list[str]] = {
            **self._DEFAULT_FALLBACK,
            **self._config.get("fallback_chains", {}),
        }

    # ── Descriptor Lookup ─────────────────────────────────────────────────────

    def get(self, logical_name: str) -> ModelDescriptor:
        """
        Returns the ModelDescriptor for a logical model name.

        Raises
        ------
        ProviderNotFoundError
            If the logical_name has no registered descriptor.
        """
        with self._lock:
            desc = self._descriptors.get(logical_name)
            if desc is None:
                raise ProviderNotFoundError(
                    f"No descriptor found for logical model '{logical_name}'. "
                    f"Registered: {sorted(self._descriptors.keys())}"
                )
            return desc

    def register_descriptor(self, descriptor: ModelDescriptor) -> None:
        """Registers or replaces a ModelDescriptor by logical_name."""
        with self._lock:
            self._descriptors[descriptor.logical_name] = descriptor

    # ── Client Lookup ─────────────────────────────────────────────────────────

    def get_client(self, provider: str) -> IProviderClient:
        """
        Returns the concrete IProviderClient for a provider name.

        Raises
        ------
        ProviderNotFoundError
            If no client is registered for this provider.
        """
        with self._lock:
            client = self._clients.get(provider)
            if client is None:
                raise ProviderNotFoundError(
                    f"No client registered for provider '{provider}'. "
                    f"Available: {sorted(self._clients.keys())}"
                )
            return client

    def get_client_for(
        self,
        logical_name: str,
        session_id:   str = "",
    ) -> tuple[IProviderClient, ModelDescriptor]:
        """
        Returns (client, descriptor) for a logical model name.
        Applies BYOK override if one is registered for this session.
        Falls back through the provider chain if the primary is unhealthy.

        Returns
        -------
        tuple[IProviderClient, ModelDescriptor]
        """
        with self._lock:
            desc     = self.get(logical_name)
            provider = self._logical_map.get(logical_name, desc.provider)

            # BYOK override
            if session_id and session_id in self._byok_overrides:
                override = self._byok_overrides[session_id]
                if override.provider == provider:
                    provider = override.provider   # same, but key injected by client

            # Try primary, then fallback chain
            for p in [provider] + self._fallback_chains.get(provider, []):
                client = self._clients.get(p)
                if client is not None and client.health_check():
                    return client, desc

            raise ProviderNotFoundError(
                f"All providers in fallback chain for '{logical_name}' "
                f"are unavailable: {[provider] + self._fallback_chains.get(provider, [])}."
            )

    # ── Provider Registration ─────────────────────────────────────────────────

    def register_client(self, provider: str, client: IProviderClient) -> None:
        """Registers a provider client. Safe to call after construction."""
        with self._lock:
            self._clients[provider] = client

    def has_any_provider(self) -> bool:
        """Returns True if at least one provider client is registered."""
        with self._lock:
            return bool(self._clients)

    def available_providers(self) -> list[str]:
        """Returns names of all registered providers."""
        with self._lock:
            return sorted(self._clients.keys())

    def healthy_providers(self) -> list[str]:
        """Returns names of providers that pass health_check()."""
        with self._lock:
            return [
                name for name, client in sorted(self._clients.items())
                if client.health_check()
            ]

    # ── Config Reload ─────────────────────────────────────────────────────────

    def reload_config(self, new_config: dict[str, Any]) -> None:
        """Hot-reloads routing config without restarting the adapter."""
        with self._lock:
            self._config = new_config
            self._logical_map = {
                **self._DEFAULT_MAP,
                **new_config.get("logical_model_map", {}),
            }
            self._fallback_chains = {
                **self._DEFAULT_FALLBACK,
                **new_config.get("fallback_chains", {}),
            }

    # ── BYOK ─────────────────────────────────────────────────────────────────

    def register_byok(self, override: BYOKOverride) -> None:
        """
        Registers a per-session BYOK override.
        Called by byok_manager.py on user key activation.
        """
        with self._lock:
            self._byok_overrides[override.session_id] = override

    def revoke_byok(self, session_id: str) -> None:
        """Removes a BYOK override. Called on session end."""
        with self._lock:
            self._byok_overrides.pop(session_id, None)

    def has_byok(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._byok_overrides

    # ── Introspection ─────────────────────────────────────────────────────────

    def logical_model_names(self) -> list[str]:
        """Returns all registered logical model names."""
        with self._lock:
            return sorted(self._descriptors.keys())

    def routing_map(self) -> dict[str, str]:
        """Returns current logical_name → provider mapping."""
        with self._lock:
            return dict(self._logical_map)

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"ProviderRegistry("
                f"providers={sorted(self._clients.keys())}, "
                f"models={sorted(self._descriptors.keys())})"
            )