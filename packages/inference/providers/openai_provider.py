"""
openai_provider.py - OpenAI-compatible chat completions provider.

This canonical module mirrors the provider contract used by the inference
registry and supports OpenAI plus compatible hosts such as Moonshot.
"""

from __future__ import annotations

import json
from typing import Any

from ..src.inference_retry_policy import InferenceSchemaError, InferenceTransportError
from ..src.provider_registry import IProviderClient
from ..src.structured_output import StructuredOutputContract, openai_response_format

try:
    import requests as _req

    _USE_REQUESTS = True
except ImportError:
    import urllib.error as _urllib_err
    import urllib.request as _urllib_req

    _USE_REQUESTS = False


_DEFAULT_CHAT_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_TIMEOUT = 120
_HEALTH_TIMEOUT = 10


class OpenAICompatibleProvider(IProviderClient):
    def __init__(
        self,
        api_key: str,
        provider_id: str = "openai",
        base_url: str | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = api_key
        self._provider_id = provider_id
        self._base_url = (base_url or _DEFAULT_CHAT_URL).rstrip("/")
        self._timeout = timeout
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def complete(
        self,
        model_id: str,
        prompt: dict[str, Any],
        system_prompt: str,
        max_tokens: int,
        temperature: float,
        structured_output: StructuredOutputContract | None = None,
    ) -> dict[str, Any]:
        body = self._build_body(model_id, prompt, system_prompt, max_tokens, temperature, structured_output)
        raw = self._post(body)
        return self._parse_response(raw)

    def health_check(self) -> bool:
        try:
            health_url = self._base_url.replace("/chat/completions", "/models")
            if _USE_REQUESTS:
                response = _req.get(health_url, headers=self._headers, timeout=_HEALTH_TIMEOUT)
                return response.status_code in (200, 400, 404)
            return True
        except Exception:
            return False

    def provider_name(self) -> str:
        return self._provider_id

    def _build_body(
        self,
        model_id: str,
        prompt: dict[str, Any],
        system_prompt: str,
        max_tokens: int,
        temperature: float,
        structured_output: StructuredOutputContract | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model_id,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        fmt = prompt.get("__format__", "")
        if structured_output is not None:
            body["response_format"] = openai_response_format(structured_output)
        if fmt == "openai":
            body["messages"] = prompt.get("messages", [])
            return body

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        if fmt == "anthropic":
            user_text = ""
            for message in prompt.get("messages", []):
                if message.get("role") != "user":
                    continue
                content = message.get("content", [])
                if isinstance(content, list):
                    user_text += "\n".join(
                        block.get("text", "")
                        for block in content
                        if isinstance(block, dict) and block.get("type") == "text"
                    )
                elif isinstance(content, str):
                    user_text += content
            messages.append({"role": "user", "content": user_text or "Continue."})
        else:
            messages.append({"role": "user", "content": str(prompt.get("text", prompt))})

        body["messages"] = messages
        return body

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(body).encode("utf-8")
        model = str(body.get("model") or "")
        if _USE_REQUESTS:
            try:
                response = _req.post(
                    self._base_url,
                    data=payload,
                    headers=self._headers,
                    timeout=self._timeout,
                )
            except _req.exceptions.Timeout:
                raise InferenceTransportError(
                    provider=self._provider_id,
                    model_id=model,
                    attempts=1,
                    last_error=TimeoutError(f"{self._provider_id} timed out"),
                )
            except _req.exceptions.ConnectionError as exc:
                raise InferenceTransportError(
                    provider=self._provider_id,
                    model_id=model,
                    attempts=1,
                    last_error=exc,
                )
            return self._handle_http(response.status_code, response.text, model)

        try:
            request = _urllib_req.Request(
                self._base_url,
                data=payload,
                headers=self._headers,
                method="POST",
            )
            with _urllib_req.urlopen(request, timeout=self._timeout) as response:
                return self._handle_http(response.status, response.read().decode("utf-8"), model)
        except _urllib_err.HTTPError as exc:
            return self._handle_http(
                exc.code,
                exc.read().decode("utf-8", errors="replace"),
                model,
            )
        except Exception as exc:
            raise InferenceTransportError(
                provider=self._provider_id,
                model_id=model,
                attempts=1,
                last_error=exc,
            )

    def _handle_http(self, status: int, body_text: str, model_id: str) -> dict[str, Any]:
        if status == 429:
            raise InferenceTransportError(
                provider=self._provider_id,
                model_id=model_id,
                attempts=1,
                last_error=Exception(f"429 rate limit: {body_text[:200]}"),
            )
        if status >= 500:
            raise InferenceTransportError(
                provider=self._provider_id,
                model_id=model_id,
                attempts=1,
                last_error=Exception(f"{status} server error: {body_text[:200]}"),
            )
        if status >= 400:
            raise InferenceSchemaError(
                f"{self._provider_id} HTTP {status}: {body_text[:500]}"
            )
        try:
            return json.loads(body_text)
        except json.JSONDecodeError as exc:
            raise InferenceSchemaError(
                f"{self._provider_id} returned non-JSON: {body_text[:200]}"
            ) from exc

    @staticmethod
    def _parse_response(raw: dict[str, Any]) -> dict[str, Any]:
        choices = raw.get("choices", [])
        text = ""
        if choices:
            message = choices[0].get("message", {})
            text = message.get("content", "") or ""

        usage = raw.get("usage", {})
        input_tokens = int(usage.get("prompt_tokens", 0) or 0)
        output_tokens = int(usage.get("completion_tokens", 0) or 0)
        cache_hit = int(usage.get("prompt_cache_hit_tokens", 0) or 0)
        cache_miss = int(usage.get("prompt_cache_miss_tokens", 0) or 0)
        if cache_hit or cache_miss:
            input_tokens = cache_miss

        return {
            "text": text,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_hit,
            "cache_write_tokens": 0,
        }


def make_openai_provider(api_key: str, timeout: int = 120) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(api_key=api_key, provider_id="openai", timeout=timeout)
