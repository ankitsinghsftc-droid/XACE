"""
anthropic_provider.py — AnthropicProvider
==========================================
Concrete IProviderClient implementation for the Anthropic Messages API.

Handles:
    - cache_control directive injection (from prompt_cache.py prepared prompts)
    - streaming responses (disabled by default for deterministic output)
    - error normalisation → uniform exception types
    - health check via lightweight model list call

## API Format
POST https://api.anthropic.com/v1/messages
Headers:
    x-api-key: {api_key}
    anthropic-version: 2023-06-01
    content-type: application/json
Body:
    {
        "model": "claude-sonnet-4-6",
        "max_tokens": 8192,
        "system": [...],    # list of content blocks (may have cache_control)
        "messages": [...],  # list of message dicts
        "temperature": 0.0
    }

## Cache Control
When prepared prompt contains "system" and "messages" with cache_control
blocks, those are passed through verbatim to the API.
Anthropic charges cache_write_price on first occurrence and
cache_read_price on subsequent hits within the 5-minute TTL window.

## Error Handling
Anthropic API errors are normalised into:
    429 → InferenceTransportError (signal for backoff retry)
    5xx → InferenceTransportError (signal for retry)
    4xx → InferenceSchemaError (bad request — don't retry)
    Connection error → InferenceTransportError

## Dependencies
Uses `requests` (stdlib-adjacent, always available in Python environments).
Production deployment should switch to `httpx` for async compatibility.
"""

from __future__ import annotations

import json
import time
from typing import Any

from ..src.provider_registry import IProviderClient
from ..src.structured_output import StructuredOutputContract, anthropic_tool_config
from ..src.inference_retry_policy import InferenceTransportError, InferenceSchemaError

# Try requests, fall back to urllib for zero-dependency environments
try:
    import requests as _req
    _USE_REQUESTS = True
except ImportError:
    import urllib.request as _urllib_req
    import urllib.error  as _urllib_err
    _USE_REQUESTS = False


# ── Constants ─────────────────────────────────────────────────────────────────

_API_URL           = "https://api.anthropic.com/v1/messages"
_API_VERSION       = "2023-06-01"
_HEALTH_CHECK_URL  = "https://api.anthropic.com/v1/models"
_DEFAULT_TIMEOUT   = 120    # seconds
_HEALTH_TIMEOUT    = 10


class AnthropicProvider(IProviderClient):
    """
    Anthropic Messages API client.

    Registered in ProviderRegistry as provider="anthropic".

    Usage (via ProviderRegistry)
    ----------------------------
        registry.register_client("anthropic", AnthropicProvider(api_key=...))
    """

    def __init__(
        self,
        api_key:       str,
        timeout:       int  = _DEFAULT_TIMEOUT,
        base_url:      str  = _API_URL,
    ) -> None:
        self._api_key  = api_key
        self._timeout  = timeout
        self._base_url = base_url
        self._headers  = {
            "x-api-key":         api_key,
            "anthropic-version": _API_VERSION,
            "content-type":      "application/json",
        }

    # ── IProviderClient ───────────────────────────────────────────────────────

    def complete(
        self,
        model_id:      str,
        prompt:        dict[str, Any],
        system_prompt: str,
        max_tokens:    int,
        temperature:   float,
        structured_output: StructuredOutputContract | None = None,
    ) -> dict[str, Any]:
        """
        Dispatches a completion request to the Anthropic Messages API.

        Accepts both raw string prompts and PreparedPrompt.payload dicts
        (from prompt_cache.py). When payload has "__format__" = "anthropic",
        the system and messages fields are used directly.

        Returns
        -------
        dict with keys: text, input_tokens, output_tokens,
                        cache_read_tokens, cache_write_tokens
        """
        body = self._build_body(model_id, prompt, system_prompt, max_tokens, temperature, structured_output)
        raw  = self._post(body)
        return self._parse_response(raw)

    def health_check(self) -> bool:
        """Returns True if the Anthropic API is reachable with this key."""
        try:
            if _USE_REQUESTS:
                r = _req.get(
                    _HEALTH_CHECK_URL,
                    headers={
                        "x-api-key":         self._api_key,
                        "anthropic-version": _API_VERSION,
                    },
                    timeout=_HEALTH_TIMEOUT,
                )
                return r.status_code in (200, 400)   # 400 = auth works, params wrong
            return True   # can't check without requests; assume OK
        except Exception:
            return False

    def provider_name(self) -> str:
        return "anthropic"

    # ── Internal ──────────────────────────────────────────────────────────────

    def _build_body(
        self,
        model_id:      str,
        prompt:        dict[str, Any],
        system_prompt: str,
        max_tokens:    int,
        temperature:   float,
        structured_output: StructuredOutputContract | None = None,
    ) -> dict[str, Any]:
        """
        Builds the Anthropic API request body.
        Handles both raw string prompts and PreparedPrompt payloads.
        """
        body: dict[str, Any] = {
            "model":       model_id,
            "max_tokens":  max_tokens,
            "temperature": temperature,
        }

        fmt = prompt.get("__format__", "")
        if structured_output is not None:
            body.update(anthropic_tool_config(structured_output))

        if fmt == "anthropic":
            # PreparedPrompt from prompt_cache.py — use structured blocks directly
            system_blocks = prompt.get("system", [])
            messages      = prompt.get("messages", [])

            if system_blocks:
                body["system"] = system_blocks
            elif system_prompt:
                body["system"] = [{"type": "text", "text": system_prompt}]

            body["messages"] = messages

        else:
            # Plain text prompt from a simple call
            if system_prompt:
                body["system"] = [{"type": "text", "text": system_prompt}]
            user_text = prompt.get("text", str(prompt))
            body["messages"] = [
                {"role": "user", "content": [{"type": "text", "text": user_text}]}
            ]

        return body

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        """Posts to Anthropic API and returns parsed JSON response."""
        payload = json.dumps(body).encode("utf-8")

        if _USE_REQUESTS:
            try:
                resp = _req.post(
                    self._base_url,
                    data=payload,
                    headers=self._headers,
                    timeout=self._timeout,
                )
            except _req.exceptions.Timeout:
                raise InferenceTransportError(
                    provider="anthropic", model_id=body.get("model", ""),
                    attempts=1, last_error=TimeoutError("Anthropic request timed out"),
                    call_label="anthropic_post",
                )
            except _req.exceptions.ConnectionError as exc:
                raise InferenceTransportError(
                    provider="anthropic", model_id=body.get("model", ""),
                    attempts=1, last_error=exc, call_label="anthropic_post",
                )
            return self._handle_http(resp.status_code, resp.text, body.get("model", ""))

        else:
            # Fallback: urllib
            try:
                req = _urllib_req.Request(
                    self._base_url,
                    data=payload,
                    headers=self._headers,
                    method="POST",
                )
                with _urllib_req.urlopen(req, timeout=self._timeout) as r:
                    return self._handle_http(r.status, r.read().decode("utf-8"),
                                            body.get("model", ""))
            except _urllib_err.HTTPError as exc:
                body_text = exc.read().decode("utf-8", errors="replace")
                return self._handle_http(exc.code, body_text, body.get("model", ""))
            except Exception as exc:
                raise InferenceTransportError(
                    provider="anthropic", model_id=body.get("model", ""),
                    attempts=1, last_error=exc, call_label="anthropic_post",
                )

    def _handle_http(
        self, status: int, body_text: str, model_id: str
    ) -> dict[str, Any]:
        """Handles HTTP status and returns parsed response or raises."""
        if status == 429:
            raise InferenceTransportError(
                provider="anthropic", model_id=model_id, attempts=1,
                last_error=Exception(f"429 Rate Limit: {body_text[:200]}"),
                call_label="anthropic_post",
            )
        if status >= 500:
            raise InferenceTransportError(
                provider="anthropic", model_id=model_id, attempts=1,
                last_error=Exception(f"{status} Server Error: {body_text[:200]}"),
                call_label="anthropic_post",
            )
        if status >= 400:
            raise InferenceSchemaError(
                f"Anthropic 4xx error ({status}): {body_text[:500]}"
            )
        try:
            return json.loads(body_text)
        except json.JSONDecodeError as exc:
            raise InferenceSchemaError(
                f"Anthropic returned non-JSON response: {body_text[:200]}"
            ) from exc

    @staticmethod
    def _parse_response(raw: dict[str, Any]) -> dict[str, Any]:
        """Normalises Anthropic response to XACE standard format."""
        # Extract text content
        text = ""
        content = raw.get("content", [])
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text += block.get("text", "")
            elif isinstance(block, dict) and block.get("type") == "tool_use":
                tool_input = block.get("input")
                if isinstance(tool_input, dict):
                    text += json.dumps(tool_input, separators=(",", ":"))

        usage = raw.get("usage", {})
        return {
            "text":               text,
            "input_tokens":       usage.get("input_tokens", 0),
            "output_tokens":      usage.get("output_tokens", 0),
            "cache_read_tokens":  usage.get("cache_read_input_tokens", 0),
            "cache_write_tokens": usage.get("cache_creation_input_tokens", 0),
        }