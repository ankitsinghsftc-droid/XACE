"""
local_provider.py — LocalProvider (Ollama)
============================================
Concrete IProviderClient for local model inference via Ollama.

Ollama exposes an OpenAI-compatible endpoint at localhost:11434.
LocalProvider is a thin wrapper around that endpoint with:
    - Automatic stripping of cache_control directives (unsupported locally)
    - Zero-cost accounting (all tokens cost $0)
    - Health check via Ollama's /api/tags endpoint
    - Configurable base_url for non-standard Ollama setups or vLLM

## When to Use
    - Development: avoid burning real API budget during dev/test
    - CI/CD: deterministic local inference for unit tests
    - Enterprise self-hosted: configure base_url to point at vLLM endpoint
    - Air-gapped environments: no internet required

## Ollama Setup
    brew install ollama          # macOS
    ollama serve                 # start the server
    ollama pull llama3.1:70b     # pull a model

## vLLM / LM Studio Compatibility
Set base_url to any OpenAI-shim endpoint:
    base_url="http://localhost:8000/v1"  # vLLM
    base_url="http://localhost:1234/v1"  # LM Studio

## Model ID Override
The model_id passed from ModelDescriptor is used as-is.
For Ollama, this must match a pulled model name exactly.
Common IDs: "llama3.1:70b", "codellama:34b", "mistral:7b",
"deepseek-coder-v2:16b", "gemma3:27b"
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
    import urllib.error   as _urllib_err
    _USE_REQUESTS = False


_DEFAULT_BASE_URL  = "http://localhost:11434"
_COMPLETIONS_PATH  = "/v1/chat/completions"
_HEALTH_PATH       = "/api/tags"
_DEFAULT_TIMEOUT   = 180    # local models can be slow on first token
_HEALTH_TIMEOUT    = 5


class LocalProvider(IProviderClient):
    """
    Local model inference via Ollama (or any OpenAI-shim at localhost).

    Registered in ProviderRegistry as provider="local".

    Usage (via ProviderRegistry)
    ----------------------------
        registry.register_client("local", LocalProvider())
        # or custom base_url:
        registry.register_client("local", LocalProvider(
            base_url="http://gpu-server:8000",  # vLLM remote
            model_id_override="codellama:34b",  # force a specific model
        ))
    """

    def __init__(
        self,
        base_url:         str        = _DEFAULT_BASE_URL,
        timeout:          int        = _DEFAULT_TIMEOUT,
        model_id_override: str | None = None,
    ) -> None:
        self._base_url         = base_url.rstrip("/")
        self._timeout          = timeout
        self._model_id_override = model_id_override
        self._headers          = {
            "Authorization": "Bearer ollama",   # Ollama ignores auth but needs the header
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
        effective_model = self._model_id_override or model_id
        body = self._build_body(effective_model, prompt, system_prompt,
                                max_tokens, temperature)
        url  = self._base_url + _COMPLETIONS_PATH
        raw  = self._post(url, body, effective_model)
        return self._parse_response(raw)

    def health_check(self) -> bool:
        """Checks if Ollama is running and has at least one model pulled."""
        try:
            url = self._base_url + _HEALTH_PATH
            if _USE_REQUESTS:
                r = _req.get(url, timeout=_HEALTH_TIMEOUT)
                if r.status_code == 200:
                    data = r.json()
                    # Ollama returns {"models": [...]}
                    return len(data.get("models", [])) > 0
                return False
            return True   # can't check without requests
        except Exception:
            return False

    def provider_name(self) -> str:
        return "local"

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _build_body(
        model_id:      str,
        prompt:        dict[str, Any],
        system_prompt: str,
        max_tokens:    int,
        temperature:   float,
    ) -> dict[str, Any]:
        """
        Builds OpenAI-compatible body.
        Strips cache_control from any anthropic-format prompt — Ollama
        doesn't support cache_control and would 400 on unknown fields.
        """
        messages: list[dict[str, str]] = []

        fmt = prompt.get("__format__", "")

        if fmt == "openai":
            # Already in correct format — use directly
            messages = prompt.get("messages", [])
            # Ensure no cache_control remnants
            messages = [
                {k: v for k, v in m.items() if k != "cache_control"}
                for m in messages
            ]
        elif fmt == "anthropic":
            # Extract system from anthropic content blocks (strip cache_control)
            sys_blocks = prompt.get("system", [])
            if sys_blocks or system_prompt:
                sys_text = system_prompt + " " + " ".join(
                    b.get("text", "") for b in sys_blocks
                    if isinstance(b, dict)
                )
                messages.append({"role": "system", "content": sys_text.strip()})
            # Flatten user messages
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
            user_text = prompt.get("text", str(prompt))
            messages.append({"role": "user", "content": user_text})

        return {
            "model":      model_id,
            "messages":   messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream":     False,
        }

    def _post(self, url: str, body: dict[str, Any], model_id: str) -> dict[str, Any]:
        payload = json.dumps(body).encode("utf-8")

        if _USE_REQUESTS:
            try:
                resp = _req.post(
                    url, data=payload, headers=self._headers, timeout=self._timeout,
                )
            except _req.exceptions.Timeout:
                raise InferenceTransportError(
                    provider="local", model_id=model_id, attempts=1,
                    last_error=TimeoutError(
                        f"Local model timed out after {self._timeout}s. "
                        f"Try a smaller model or increase timeout."
                    ),
                )
            except _req.exceptions.ConnectionError:
                raise InferenceTransportError(
                    provider="local", model_id=model_id, attempts=1,
                    last_error=ConnectionError(
                        f"Cannot connect to Ollama at {self._base_url}. "
                        f"Run: ollama serve"
                    ),
                )
            return self._handle_http(resp.status_code, resp.text, model_id)
        else:
            try:
                req = _urllib_req.Request(
                    url, data=payload, headers=self._headers, method="POST",
                )
                with _urllib_req.urlopen(req, timeout=self._timeout) as r:
                    return self._handle_http(r.status, r.read().decode(), model_id)
            except _urllib_err.HTTPError as exc:
                return self._handle_http(
                    exc.code, exc.read().decode("utf-8", errors="replace"), model_id
                )
            except Exception as exc:
                raise InferenceTransportError(
                    provider="local", model_id=model_id, attempts=1, last_error=exc,
                )

    def _handle_http(self, status: int, body_text: str, model_id: str) -> dict[str, Any]:
        if status >= 500:
            raise InferenceTransportError(
                provider="local", model_id=model_id, attempts=1,
                last_error=Exception(f"Ollama server error {status}: {body_text[:200]}"),
            )
        if status >= 400:
            raise InferenceSchemaError(
                f"Ollama 4xx ({status}): {body_text[:500]} "
                f"(Is model '{model_id}' pulled? Run: ollama pull {model_id})"
            )
        try:
            return json.loads(body_text)
        except json.JSONDecodeError as exc:
            raise InferenceSchemaError(
                f"Ollama non-JSON response: {body_text[:200]}"
            ) from exc

    @staticmethod
    def _parse_response(raw: dict[str, Any]) -> dict[str, Any]:
        """Normalises Ollama OpenAI-shim response to XACE standard."""
        choices = raw.get("choices", [])
        text    = ""
        if choices:
            text = choices[0].get("message", {}).get("content", "") or ""

        usage = raw.get("usage", {})
        return {
            "text":               text,
            "input_tokens":       usage.get("prompt_tokens", 0),
            "output_tokens":      usage.get("completion_tokens", 0),
            "cache_read_tokens":  0,   # no caching locally
            "cache_write_tokens": 0,
        }