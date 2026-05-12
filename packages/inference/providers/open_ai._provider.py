"""
openai_provider.py — OpenAICompatibleProvider
===============================================
Concrete IProviderClient implementation for OpenAI Chat Completions API
and any OpenAI-compatible endpoint.

Used directly for:
    - OpenAI (base_url=None → uses openai.com default)

Used via factory functions for OpenAI-compatible providers:
    - DeepSeek   (base_url="https://api.deepseek.com/v1")
    - Z.AI/GLM   (base_url="https://api.z.ai/api/openai/v1")
    - MiniMax    (base_url="https://api.minimax.io/v1")
    - Local vLLM (base_url="http://localhost:8000/v1")

## API Format
POST {base_url}/chat/completions
Headers:
    Authorization: Bearer {api_key}
    Content-Type: application/json
Body:
    {
        "model": "gpt-5.5",
        "messages": [
            {"role": "system", "content": "..."},
            {"role": "user",   "content": "..."}
        ],
        "max_tokens": 4096,
        "temperature": 0.0
    }

## PreparedPrompt Handling
When prompt.__format__ == "openai", messages list is used directly.
When raw text is passed, it's wrapped in a user message.

## DeepSeek / GLM Cache Accounting
These providers return `prompt_cache_hit_tokens` and
`prompt_cache_miss_tokens` in the usage block instead of Anthropic's
cache_creation_input_tokens / cache_read_input_tokens.
The parser handles both conventions.

## Factory Functions
Use the provider-specific factory functions to get pre-configured
client instances for ProviderRegistry:

    registry.register_client("deepseek", make_deepseek_provider("sk-..."))
    registry.register_client("zai",      make_zai_provider("...key..."))
    registry.register_client("minimax",  make_minimax_provider("...key..."))
    registry.register_client("openai",   make_openai_provider("sk-..."))
"""

from __future__ import annotations

import json
from typing import Any

from ..src.provider_registry import IProviderClient
from ..src.inference_retry_policy import InferenceTransportError, InferenceSchemaError

try:
    import requests as _req
    _USE_REQUESTS = True
except ImportError:
    import urllib.request as _urllib_req
    import urllib.error  as _urllib_err
    _USE_REQUESTS = False


# ── Provider Endpoints ────────────────────────────────────────────────────────

_ENDPOINTS = {
    "openai":   "https://api.openai.com/v1/chat/completions",
    "deepseek": "https://api.deepseek.com/v1/chat/completions",
    "zai":      "https://api.z.ai/api/openai/v1/chat/completions",
    "minimax":  "https://api.minimax.io/v1/chat/completions",
}

_DEFAULT_TIMEOUT = 120
_HEALTH_TIMEOUT  = 10


class OpenAICompatibleProvider(IProviderClient):
    """
    OpenAI Chat Completions API client.

    Configurable via base_url to support any OpenAI-compatible endpoint
    (DeepSeek, GLM/Z.AI, MiniMax, local vLLM/Ollama OpenAI shim).

    Use the factory functions at module bottom for named providers.
    """

    def __init__(
        self,
        api_key:       str,
        provider_id:   str          = "openai",
        base_url:      str | None   = None,
        timeout:       int          = _DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key     = api_key
        self._provider_id = provider_id
        self._base_url    = base_url or _ENDPOINTS.get(provider_id,
                                _ENDPOINTS["openai"])
        self._timeout     = timeout
        self._headers     = {
            "Authorization": f"Bearer {api_key}",
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
        body = self._build_body(model_id, prompt, system_prompt,
                                max_tokens, temperature)
        raw  = self._post(body)
        return self._parse_response(raw)

    def health_check(self) -> bool:
        """Tries to list models or hits the base endpoint."""
        try:
            health_url = self._base_url.replace("/chat/completions", "/models")
            if _USE_REQUESTS:
                r = _req.get(health_url, headers=self._headers,
                             timeout=_HEALTH_TIMEOUT)
                return r.status_code in (200, 400, 404)
            return True
        except Exception:
            return False

    def provider_name(self) -> str:
        return self._provider_id

    # ── Internal ──────────────────────────────────────────────────────────────

    def _build_body(
        self,
        model_id:      str,
        prompt:        dict[str, Any],
        system_prompt: str,
        max_tokens:    int,
        temperature:   float,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model":       model_id,
            "max_tokens":  max_tokens,
            "temperature": temperature,
        }

        fmt = prompt.get("__format__", "")
        if fmt == "openai":
            # PreparedPrompt from prompt_cache — messages already structured
            body["messages"] = prompt["messages"]
        else:
            # Raw text or anthropic-format — convert to openai messages
            messages: list[dict[str, str]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})

            # Handle anthropic-format prepared prompt
            if fmt == "anthropic":
                # Flatten anthropic content blocks to text
                user_text = ""
                for msg in prompt.get("messages", []):
                    if msg.get("role") == "user":
                        content = msg.get("content", [])
                        if isinstance(content, list):
                            user_text = " ".join(
                                b.get("text", "") for b in content
                                if isinstance(b, dict) and b.get("type") == "text"
                            )
                        elif isinstance(content, str):
                            user_text = content
                if user_text:
                    messages.append({"role": "user", "content": user_text})
            else:
                user_text = prompt.get("text", str(prompt))
                messages.append({"role": "user", "content": user_text})

            body["messages"] = messages

        return body

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(body).encode("utf-8")
        model   = body.get("model", "")

        if _USE_REQUESTS:
            try:
                resp = _req.post(
                    self._base_url, data=payload,
                    headers=self._headers, timeout=self._timeout,
                )
            except _req.exceptions.Timeout:
                raise InferenceTransportError(
                    provider=self._provider_id, model_id=model, attempts=1,
                    last_error=TimeoutError(f"{self._provider_id} timed out"),
                )
            except _req.exceptions.ConnectionError as exc:
                raise InferenceTransportError(
                    provider=self._provider_id, model_id=model,
                    attempts=1, last_error=exc,
                )
            return self._handle_http(resp.status_code, resp.text, model)
        else:
            try:
                req = _urllib_req.Request(
                    self._base_url, data=payload,
                    headers=self._headers, method="POST",
                )
                with _urllib_req.urlopen(req, timeout=self._timeout) as r:
                    return self._handle_http(r.status, r.read().decode(), model)
            except _urllib_err.HTTPError as exc:
                return self._handle_http(exc.code,
                    exc.read().decode("utf-8", errors="replace"), model)
            except Exception as exc:
                raise InferenceTransportError(
                    provider=self._provider_id, model_id=model,
                    attempts=1, last_error=exc,
                )

    def _handle_http(self, status: int, body_text: str, model_id: str) -> dict[str, Any]:
        if status == 429:
            raise InferenceTransportError(
                provider=self._provider_id, model_id=model_id, attempts=1,
                last_error=Exception(f"429 Rate Limit: {body_text[:200]}"),
            )
        if status >= 500:
            raise InferenceTransportError(
                provider=self._provider_id, model_id=model_id, attempts=1,
                last_error=Exception(f"{status} Server Error: {body_text[:200]}"),
            )
        if status >= 400:
            raise InferenceSchemaError(
                f"{self._provider_id} 4xx error ({status}): {body_text[:500]}"
            )
        try:
            return json.loads(body_text)
        except json.JSONDecodeError as exc:
            raise InferenceSchemaError(
                f"{self._provider_id} non-JSON response: {body_text[:200]}"
            ) from exc

    def _parse_response(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Normalises OpenAI-compatible response to XACE standard format."""
        choices = raw.get("choices", [])
        text    = ""
        if choices:
            msg = choices[0].get("message", {})
            text = msg.get("content", "") or ""

        usage = raw.get("usage", {})
        input_tokens  = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)

        # DeepSeek / GLM cache fields (different convention from Anthropic)
        cache_hit  = usage.get("prompt_cache_hit_tokens", 0)
        cache_miss = usage.get("prompt_cache_miss_tokens", 0)
        # For providers that split prompt_tokens into hit/miss,
        # non-cached input is the cache_miss portion
        if cache_hit or cache_miss:
            input_tokens = cache_miss

        return {
            "text":               text,
            "input_tokens":       input_tokens,
            "output_tokens":      output_tokens,
            "cache_read_tokens":  cache_hit,
            "cache_write_tokens": 0,   # OpenAI-compatible has no write tracking
        }


# ── Provider Factory Functions ────────────────────────────────────────────────

def make_openai_provider(api_key: str, timeout: int = 120) -> OpenAICompatibleProvider:
    """Factory for OpenAI native API."""
    return OpenAICompatibleProvider(api_key=api_key, provider_id="openai",
                                    base_url=_ENDPOINTS["openai"], timeout=timeout)


def make_deepseek_provider(api_key: str, timeout: int = 120) -> OpenAICompatibleProvider:
    """
    Factory for DeepSeek V4 Pro/Flash via OpenAI-compatible API.
    DeepSeek also supports Anthropic-compatible endpoint but we use
    OpenAI format here for consistency.
    """
    return OpenAICompatibleProvider(api_key=api_key, provider_id="deepseek",
                                    base_url=_ENDPOINTS["deepseek"], timeout=timeout)


def make_zai_provider(api_key: str, timeout: int = 120) -> OpenAICompatibleProvider:
    """
    Factory for Z.AI (GLM-5.1, GLM-5) via OpenAI-compatible API.
    GLM also supports Anthropic-compatible endpoint:
        base_url="https://api.z.ai/api/anthropic"
    Use that for cache_control support if Z.AI enables it in future.
    """
    return OpenAICompatibleProvider(api_key=api_key, provider_id="zai",
                                    base_url=_ENDPOINTS["zai"], timeout=timeout)


def make_minimax_provider(api_key: str, timeout: int = 120) -> OpenAICompatibleProvider:
    """
    Factory for MiniMax M2.7/M2.5 via OpenAI-compatible API.
    MiniMax also has an Anthropic-compatible endpoint:
        base_url="https://api.minimax.io/anthropic"
    """
    return OpenAICompatibleProvider(api_key=api_key, provider_id="minimax",
                                    base_url=_ENDPOINTS["minimax"], timeout=timeout)