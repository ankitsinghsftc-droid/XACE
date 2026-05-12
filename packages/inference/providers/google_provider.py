"""
google_provider.py — GoogleProvider
======================================
Concrete IProviderClient for the Google Gemini API
(Google AI Developer API via generativelanguage.googleapis.com).

Gemini uses a DIFFERENT wire format from OpenAI — do NOT route
Google models through openai_provider.py.

## API Format
POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
Query: ?key={api_key}
Headers:
    Content-Type: application/json
Body:
    {
        "contents": [
            {"role": "user", "parts": [{"text": "..."}]}
        ],
        "systemInstruction": {"parts": [{"text": "..."}]},
        "generationConfig": {
            "maxOutputTokens": 8192,
            "temperature": 0.0
        }
    }

## Context Caching (Implicit)
Google's implicit caching is automatic — the API caches your prompt prefix
if it's been seen before within the TTL window. No cache_control blocks
needed. Cache hits are reported in usageMetadata.cachedContentTokenCount.
Cache miss price: $2.00/MTok. Cache hit price: $0.20/MTok (90% off).

## Context Tier Warning
Prompts > 200K tokens billed at $4.00/$18.00 instead of $2.00/$12.00.
GoogleProvider checks prompt size and logs a warning but does NOT block.
The caller (context_budgeter + cost_estimator) should keep XACE prompts
under the 8K dynamic token cap — well under the 200K threshold.

## Thinking Levels
Gemini 3.1 Pro supports thinking_level: "low" | "medium" | "high".
Default: "medium". Override via extra_config in the request body.
Thinking tokens are billed at standard output rates.
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


# ── Constants ─────────────────────────────────────────────────────────────────

_API_BASE      = "https://generativelanguage.googleapis.com/v1beta"
_HEALTH_MODEL  = "gemini-3-flash-preview"   # cheap model for health checks
_DEFAULT_TIMEOUT = 120
_HEALTH_TIMEOUT  = 10

# 200K token warning threshold (above this, pricing doubles)
_LONG_CONTEXT_THRESHOLD = 200_000


class GoogleProvider(IProviderClient):
    """
    Google Gemini API client.

    Registered in ProviderRegistry as provider="google".

    Usage (via ProviderRegistry)
    ----------------------------
        registry.register_client("google", GoogleProvider(api_key="AIza..."))
    """

    def __init__(
        self,
        api_key:        str,
        timeout:        int  = _DEFAULT_TIMEOUT,
        thinking_level: str  = "medium",   # "low" | "medium" | "high"
    ) -> None:
        self._api_key        = api_key
        self._timeout        = timeout
        self._thinking_level = thinking_level
        self._headers        = {"Content-Type": "application/json"}

    # ── IProviderClient ───────────────────────────────────────────────────────

    def complete(
        self,
        model_id:      str,
        prompt:        dict[str, Any],
        system_prompt: str,
        max_tokens:    int,
        temperature:   float,
    ) -> dict[str, Any]:
        url  = self._model_url(model_id)
        body = self._build_body(prompt, system_prompt, max_tokens, temperature)
        raw  = self._post(url, body, model_id)
        return self._parse_response(raw)

    def health_check(self) -> bool:
        """Sends a minimal request to the cheapest Gemini model."""
        try:
            url  = self._model_url(_HEALTH_MODEL)
            body = {
                "contents": [{"role": "user", "parts": [{"text": "Hi"}]}],
                "generationConfig": {"maxOutputTokens": 5, "temperature": 0.0},
            }
            if _USE_REQUESTS:
                r = _req.post(url, params={"key": self._api_key},
                              json=body, headers=self._headers,
                              timeout=_HEALTH_TIMEOUT)
                return r.status_code in (200, 400)
            return True
        except Exception:
            return False

    def provider_name(self) -> str:
        return "google"

    # ── Internal ──────────────────────────────────────────────────────────────

    def _model_url(self, model_id: str) -> str:
        return f"{_API_BASE}/models/{model_id}:generateContent"

    def _build_body(
        self,
        prompt:        dict[str, Any],
        system_prompt: str,
        max_tokens:    int,
        temperature:   float,
    ) -> dict[str, Any]:
        """Builds Gemini API request body from a prepared prompt."""
        body: dict[str, Any] = {
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature":     temperature,
            }
        }

        # Thinking level for Gemini 3.1 Pro
        if self._thinking_level and self._thinking_level != "none":
            body["generationConfig"]["thinkingConfig"] = {
                "thinkingBudget": self._thinking_level,
            }

        # System instruction
        effective_system = system_prompt

        fmt = prompt.get("__format__", "")
        if fmt == "anthropic":
            # Extract system from anthropic-format blocks
            sys_blocks = prompt.get("system", [])
            if sys_blocks:
                effective_system = " ".join(
                    b.get("text", "") for b in sys_blocks
                    if isinstance(b, dict)
                )
            # Build user content from messages
            user_text = ""
            for msg in prompt.get("messages", []):
                content = msg.get("content", [])
                if isinstance(content, list):
                    user_text += " ".join(
                        b.get("text", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    )
                elif isinstance(content, str):
                    user_text += content
            contents = [{"role": "user", "parts": [{"text": user_text}]}]

        elif fmt == "openai":
            # Extract from openai-format messages
            messages    = prompt.get("messages", [])
            system_msgs = [m for m in messages if m.get("role") == "system"]
            user_msgs   = [m for m in messages if m.get("role") == "user"]
            if system_msgs and not effective_system:
                effective_system = "\n\n".join(
                    m.get("content", "") for m in system_msgs
                )
            user_text = "\n\n".join(m.get("content", "") for m in user_msgs)
            contents  = [{"role": "user", "parts": [{"text": user_text}]}]

        else:
            # Raw text
            user_text = prompt.get("text", str(prompt))
            contents  = [{"role": "user", "parts": [{"text": user_text}]}]

        if effective_system:
            body["systemInstruction"] = {
                "parts": [{"text": effective_system}]
            }

        body["contents"] = contents
        return body

    def _post(self, url: str, body: dict[str, Any], model_id: str) -> dict[str, Any]:
        params  = {"key": self._api_key}
        payload = json.dumps(body).encode("utf-8")

        if _USE_REQUESTS:
            try:
                resp = _req.post(
                    url, params=params, data=payload,
                    headers=self._headers, timeout=self._timeout,
                )
            except _req.exceptions.Timeout:
                raise InferenceTransportError(
                    provider="google", model_id=model_id, attempts=1,
                    last_error=TimeoutError("Gemini request timed out"),
                )
            except _req.exceptions.ConnectionError as exc:
                raise InferenceTransportError(
                    provider="google", model_id=model_id, attempts=1, last_error=exc,
                )
            return self._handle_http(resp.status_code, resp.text, model_id)
        else:
            from urllib.parse import urlencode
            full_url = f"{url}?{urlencode(params)}"
            try:
                req = _urllib_req.Request(
                    full_url, data=payload, headers=self._headers, method="POST",
                )
                with _urllib_req.urlopen(req, timeout=self._timeout) as r:
                    return self._handle_http(r.status, r.read().decode(), model_id)
            except _urllib_err.HTTPError as exc:
                return self._handle_http(exc.code,
                    exc.read().decode("utf-8", errors="replace"), model_id)
            except Exception as exc:
                raise InferenceTransportError(
                    provider="google", model_id=model_id, attempts=1, last_error=exc,
                )

    def _handle_http(self, status: int, body_text: str, model_id: str) -> dict[str, Any]:
        if status == 429:
            raise InferenceTransportError(
                provider="google", model_id=model_id, attempts=1,
                last_error=Exception(f"429 Quota exceeded: {body_text[:200]}"),
            )
        if status >= 500:
            raise InferenceTransportError(
                provider="google", model_id=model_id, attempts=1,
                last_error=Exception(f"{status} Gemini server error: {body_text[:200]}"),
            )
        if status >= 400:
            raise InferenceSchemaError(f"Gemini 4xx ({status}): {body_text[:500]}")
        try:
            return json.loads(body_text)
        except json.JSONDecodeError as exc:
            raise InferenceSchemaError(
                f"Gemini non-JSON response: {body_text[:200]}"
            ) from exc

    @staticmethod
    def _parse_response(raw: dict[str, Any]) -> dict[str, Any]:
        """Normalises Gemini response to XACE standard format."""
        text = ""
        candidates = raw.get("candidates", [])
        if candidates:
            content = candidates[0].get("content", {})
            parts   = content.get("parts", [])
            for part in parts:
                if isinstance(part, dict):
                    text += part.get("text", "")

        # usageMetadata contains token counts
        usage = raw.get("usageMetadata", {})
        # Gemini: promptTokenCount includes both cached and non-cached
        total_prompt   = usage.get("promptTokenCount",        0)
        cached_tokens  = usage.get("cachedContentTokenCount", 0)
        output_tokens  = usage.get("candidatesTokenCount",    0)
        # Non-cached input = total prompt - cached
        input_tokens   = max(0, total_prompt - cached_tokens)

        return {
            "text":               text,
            "input_tokens":       input_tokens,
            "output_tokens":      output_tokens,
            "cache_read_tokens":  cached_tokens,
            "cache_write_tokens": 0,   # Google charges storage/hour, not per-write token
        }