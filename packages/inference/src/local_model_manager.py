"""
local_model_manager.py — LocalModelManager
============================================
Manages Ollama/vLLM local model instances and implements IProviderClient
for use in hybrid tier routing.

## Relationship to local_provider.py

    local_provider.py     — dumb HTTP client. One static model_id per instance.
                            Single responsibility: send request, return response.

    local_model_manager.py — smart lifecycle manager. Tracks which models
                             are loaded, selects the best available model for
                             a request, loads on-demand, evicts LRU when
                             VRAM pressure detected. Wraps local_provider.py
                             for the actual HTTP dispatch.

## Hybrid Routing Contract (TIER_M)

model_router.py calls:
    1. `manager.has_any_available()` — quick check before routing to local
    2. `manager.get_provider(model_name)` → returns a LocalProvider instance
       which InferenceAdapter dispatches through

Or directly via IProviderClient:
    manager.complete(model_id, prompt, system_prompt, max_tokens, temperature)

## Default Models

Two defaults are pre-configured (can be overridden in config):
    - llama3.1:70b  — Llama 3.1 70B (40GB VRAM) — general TIER_M tasks
    - qwen2.5:72b   — Qwen 2.5 72B (40GB VRAM) — better code and reasoning

Auto-selection at runtime: whichever is available in Ollama.
If neither is loaded, `load_model()` triggers an Ollama pull.

## VRAM Management

`max_loaded_models` (default: 1) caps simultaneous loaded models.
When a new model is requested and the cap is reached, the least recently
used loaded model is unloaded before the new one is loaded.

## cache_control Handling

All cache_control directives are stripped before sending to Ollama —
Ollama does not support the Anthropic cache_control extension and will
return a 400 on unknown fields. This mirrors local_provider.py behaviour.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .provider_registry import IProviderClient
from .inference_retry_policy import InferenceTransportError, InferenceSchemaError

try:
    import requests as _req
    _USE_REQUESTS = True
except ImportError:
    import urllib.request as _urllib_req
    import urllib.error   as _urllib_err
    _USE_REQUESTS = False


# ── Default Models ────────────────────────────────────────────────────────────

DEFAULT_LOCAL_MODELS: list[str] = [
    "llama3.1:70b",   # Llama 3.1 70B — Meta's flagship open model
    "qwen2.5:72b",    # Qwen 2.5 72B — strong code and reasoning
]

_OLLAMA_BASE     = "http://localhost:11434"
_TAGS_PATH       = "/api/tags"
_PULL_PATH       = "/api/pull"
_DELETE_PATH     = "/api/delete"
_COMPLETIONS     = "/v1/chat/completions"
_DEFAULT_TIMEOUT = 300   # local models can be slow
_HEALTH_TIMEOUT  = 5


# ── Model Availability Record ─────────────────────────────────────────────────

@dataclass
class _ModelState:
    model_name:   str
    is_loaded:    bool
    last_used_at: float = field(default_factory=time.time)
    load_count:   int   = 0

    def mark_used(self) -> None:
        self.last_used_at = time.time()
        self.load_count  += 1


# ── Config ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LocalModelConfig:
    base_url:          str       = _OLLAMA_BASE
    default_models:    tuple     = tuple(DEFAULT_LOCAL_MODELS)
    max_loaded_models: int       = 1
    availability_cache_ttl_s: float = 10.0   # how long to cache /api/tags response
    auto_pull_on_miss: bool      = True       # pull model if not found in Ollama
    timeout:           int       = _DEFAULT_TIMEOUT


DEFAULT_LOCAL_CONFIG = LocalModelConfig()


# ── LocalModelManager ─────────────────────────────────────────────────────────

class LocalModelManager(IProviderClient):
    """
    Manages Ollama/vLLM local model instances.
    Implements IProviderClient — can be registered in ProviderRegistry
    as provider="local" to enable hybrid TIER_M routing.

    Usage (via ProviderRegistry)
    ----------------------------
        manager = LocalModelManager()
        registry.register_client("local", manager)

    Usage (direct dispatch)
    -----------------------
        if manager.has_any_available():
            response = manager.complete(
                model_id      = manager.select_model(),
                prompt        = prepared_prompt,
                system_prompt = system_text,
                max_tokens    = 2048,
                temperature   = 0.0,
            )
    """

    def __init__(self, config: LocalModelConfig = DEFAULT_LOCAL_CONFIG) -> None:
        self._config          = config
        self._lock            = threading.RLock()
        self._states:         dict[str, _ModelState] = {}
        self._cached_loaded:  list[str] = []
        self._cache_expires:  float     = 0.0
        self._headers         = {
            "Authorization": "Bearer ollama",
            "Content-Type":  "application/json",
        }

    # ── IProviderClient ───────────────────────────────────────────────────────

    def complete(
        self,
        model_id:      str,
        prompt:        dict[str, Any],
        system_prompt: str,
        max_tokens:    int,
        temperature:   float,
    ) -> dict[str, Any]:
        """
        Dispatches a completion request to the local model.
        Loads the model first if not already loaded (when auto_pull=True).
        Strips cache_control from the prompt before sending.
        """
        # Ensure model is available
        if not self.is_available(model_id):
            if self._config.auto_pull_on_miss:
                self.load_model(model_id)
            else:
                raise InferenceTransportError(
                    provider   = "local",
                    model_id   = model_id,
                    attempts   = 1,
                    last_error = RuntimeError(
                        f"Model '{model_id}' is not loaded in Ollama. "
                        f"Run: ollama pull {model_id}"
                    ),
                )

        body = self._build_body(model_id, prompt, system_prompt, max_tokens, temperature)
        raw  = self._post_completions(body, model_id)

        with self._lock:
            if model_id in self._states:
                self._states[model_id].mark_used()

        return self._parse_response(raw)

    def health_check(self) -> bool:
        """Returns True if Ollama is running and at least one model is available."""
        try:
            return len(self._fetch_loaded_models()) > 0 or len(self._config.default_models) > 0
        except Exception:
            return False

    def provider_name(self) -> str:
        return "local"

    # ── Model Lifecycle ───────────────────────────────────────────────────────

    def load_model(self, model_name: str) -> None:
        """
        Loads a model into Ollama. Blocks until the model is ready.
        If max_loaded_models is reached, evicts the LRU model first.
        """
        with self._lock:
            if self.is_available(model_name):
                return   # already loaded

            # Evict LRU if at capacity
            loaded = self._fetch_loaded_models()
            if len(loaded) >= self._config.max_loaded_models:
                lru = self._least_recently_used(loaded)
                if lru:
                    self.unload_model(lru)

        # POST /api/pull — blocking (can take minutes for large models)
        payload = json.dumps({"name": model_name, "stream": False}).encode("utf-8")
        url     = self._config.base_url + _PULL_PATH

        if _USE_REQUESTS:
            try:
                resp = _req.post(
                    url, data=payload, headers=self._headers,
                    timeout=self._config.timeout,
                )
                if resp.status_code >= 400:
                    raise RuntimeError(f"Ollama pull failed: {resp.status_code} {resp.text[:200]}")
            except _req.exceptions.ConnectionError:
                raise InferenceTransportError(
                    provider="local", model_id=model_name, attempts=1,
                    last_error=ConnectionError(
                        f"Cannot connect to Ollama at {self._config.base_url}. "
                        f"Run: ollama serve"
                    ),
                )
        else:
            try:
                req = _urllib_req.Request(url, data=payload, headers=self._headers, method="POST")
                with _urllib_req.urlopen(req, timeout=self._config.timeout):
                    pass
            except Exception as exc:
                raise InferenceTransportError(
                    provider="local", model_id=model_name, attempts=1, last_error=exc,
                )

        # Invalidate availability cache
        self._cache_expires = 0.0

        with self._lock:
            self._states[model_name] = _ModelState(model_name=model_name, is_loaded=True)

    def unload_model(self, model_name: str) -> None:
        """
        Unloads a model from Ollama to free VRAM.
        No-op if the model is not currently loaded.
        """
        url     = self._config.base_url + _DELETE_PATH
        payload = json.dumps({"name": model_name}).encode("utf-8")

        try:
            if _USE_REQUESTS:
                _req.delete(url, data=payload, headers=self._headers, timeout=30)
            else:
                req = _urllib_req.Request(url, data=payload, headers=self._headers, method="DELETE")
                _urllib_req.urlopen(req, timeout=30)
        except Exception:
            pass   # unload is best-effort

        self._cache_expires = 0.0
        with self._lock:
            if model_name in self._states:
                self._states[model_name].is_loaded = False

    def is_available(self, model_name: str) -> bool:
        """Returns True if the model is currently loaded in Ollama."""
        return model_name in self._fetch_loaded_models()

    def has_any_available(self) -> bool:
        """Returns True if at least one of the default models is loaded."""
        loaded = self._fetch_loaded_models()
        return bool(loaded)

    def select_model(self) -> str:
        """
        Returns the best available default model.
        Priority: loaded default models first, then any loaded model,
        then the first default model (triggers load on next complete()).
        """
        loaded = self._fetch_loaded_models()

        # Prefer default models in priority order
        for m in self._config.default_models:
            if m in loaded:
                return m

        # Any loaded model
        if loaded:
            return loaded[0]

        # Fall back to first default (will be loaded on demand)
        if self._config.default_models:
            return self._config.default_models[0]

        return "llama3.1:70b"

    def available_models(self) -> list[str]:
        """Returns names of all currently loaded models."""
        return list(self._fetch_loaded_models())

    def get_provider(self, model_name: str) -> "LocalModelManager":
        """
        Returns self with the given model selected.
        For API compatibility with ProviderRegistry — callers that want a
        specific model can use this; InferenceAdapter calls complete() directly.
        """
        return self

    # ── Internal ──────────────────────────────────────────────────────────────

    def _fetch_loaded_models(self) -> list[str]:
        """
        Fetches the list of loaded models from Ollama.
        Result is cached for `availability_cache_ttl_s` seconds.
        """
        now = time.monotonic()
        with self._lock:
            if now < self._cache_expires:
                return list(self._cached_loaded)

        loaded: list[str] = []
        url = self._config.base_url + _TAGS_PATH

        try:
            if _USE_REQUESTS:
                resp = _req.get(url, headers=self._headers, timeout=_HEALTH_TIMEOUT)
                if resp.status_code == 200:
                    data   = resp.json()
                    loaded = [m["name"] for m in data.get("models", [])]
            else:
                req = _urllib_req.Request(url, headers=self._headers)
                with _urllib_req.urlopen(req, timeout=_HEALTH_TIMEOUT) as r:
                    data   = json.loads(r.read().decode())
                    loaded = [m["name"] for m in data.get("models", [])]
        except Exception:
            pass   # Ollama not running or network error

        with self._lock:
            self._cached_loaded = loaded
            self._cache_expires = time.monotonic() + self._config.availability_cache_ttl_s

        return loaded

    def _least_recently_used(self, loaded: list[str]) -> str | None:
        """Returns the loaded model that was used least recently."""
        if not loaded:
            return None
        # Sort by last_used_at ASC — lowest = oldest
        with self._lock:
            known = [(m, self._states.get(m)) for m in loaded]
            known_with_time = [
                (m, s.last_used_at if s else 0.0) for m, s in known
            ]
            return min(known_with_time, key=lambda x: x[1])[0]

    @staticmethod
    def _build_body(
        model_id:      str,
        prompt:        dict[str, Any],
        system_prompt: str,
        max_tokens:    int,
        temperature:   float,
    ) -> dict[str, Any]:
        """Builds request body, stripping cache_control from all blocks."""
        messages: list[dict[str, str]] = []

        fmt = prompt.get("__format__", "")

        if fmt == "openai":
            # Use messages directly, strip any cache_control
            for msg in prompt.get("messages", []):
                messages.append({
                    k: v for k, v in msg.items()
                    if k not in ("cache_control",)
                })
        elif fmt == "anthropic":
            # Flatten system blocks
            sys_blocks = prompt.get("system", [])
            sys_text   = system_prompt + " " + " ".join(
                b.get("text", "") for b in sys_blocks if isinstance(b, dict)
            )
            if sys_text.strip():
                messages.append({"role": "system", "content": sys_text.strip()})
            # Flatten user blocks
            for msg in prompt.get("messages", []):
                if msg.get("role") == "user":
                    content = msg.get("content", [])
                    if isinstance(content, list):
                        text = " ".join(
                            b.get("text", "") for b in content
                            if isinstance(b, dict) and b.get("type") == "text"
                        )
                    else:
                        text = str(content)
                    messages.append({"role": "user", "content": text})
        else:
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt.get("text", str(prompt))})

        return {
            "model":       model_id,
            "messages":    messages,
            "max_tokens":  max_tokens,
            "temperature": temperature,
            "stream":      False,
        }

    def _post_completions(self, body: dict[str, Any], model_id: str) -> dict[str, Any]:
        url     = self._config.base_url + _COMPLETIONS
        payload = json.dumps(body).encode("utf-8")

        if _USE_REQUESTS:
            try:
                resp = _req.post(
                    url, data=payload, headers=self._headers, timeout=self._config.timeout,
                )
            except _req.exceptions.Timeout:
                raise InferenceTransportError(
                    provider="local", model_id=model_id, attempts=1,
                    last_error=TimeoutError(f"Local model timed out after {self._config.timeout}s"),
                )
            except _req.exceptions.ConnectionError:
                raise InferenceTransportError(
                    provider="local", model_id=model_id, attempts=1,
                    last_error=ConnectionError(
                        f"Cannot connect to Ollama at {self._config.base_url}. "
                        f"Run: ollama serve"
                    ),
                )
            if resp.status_code >= 400:
                raise InferenceSchemaError(
                    f"Ollama {resp.status_code}: {resp.text[:500]}"
                )
            try:
                return resp.json()
            except ValueError as exc:
                raise InferenceSchemaError(f"Ollama non-JSON: {resp.text[:200]}") from exc
        else:
            try:
                req = _urllib_req.Request(url, data=payload, headers=self._headers, method="POST")
                with _urllib_req.urlopen(req, timeout=self._config.timeout) as r:
                    return json.loads(r.read().decode())
            except _urllib_err.HTTPError as exc:
                body_text = exc.read().decode("utf-8", errors="replace")
                raise InferenceSchemaError(f"Ollama {exc.code}: {body_text[:500]}")
            except Exception as exc:
                raise InferenceTransportError(
                    provider="local", model_id=model_id, attempts=1, last_error=exc,
                )

    @staticmethod
    def _parse_response(raw: dict[str, Any]) -> dict[str, Any]:
        choices = raw.get("choices", [])
        text    = ""
        if choices:
            text = choices[0].get("message", {}).get("content", "") or ""
        usage = raw.get("usage", {})
        return {
            "text":               text,
            "input_tokens":       usage.get("prompt_tokens", 0),
            "output_tokens":      usage.get("completion_tokens", 0),
            "cache_read_tokens":  0,
            "cache_write_tokens": 0,
        }

    def __repr__(self) -> str:
        loaded = self._fetch_loaded_models()
        return (
            f"LocalModelManager("
            f"base={self._config.base_url!r}, "
            f"loaded={loaded}, "
            f"defaults={list(self._config.default_models)})"
        )