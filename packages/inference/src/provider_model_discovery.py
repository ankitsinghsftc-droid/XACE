"""
Provider model discovery helpers.

Task 51 keeps provider HTTP/API access inside packages/inference. Builder can
ask this module for model IDs, but it must not perform provider HTTP itself.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


DEFAULT_MODELS_URLS = {
    "anthropic": "https://api.anthropic.com/v1/models",
    "openai": "https://api.openai.com/v1/models",
    "google": "https://generativelanguage.googleapis.com/v1beta/models",
    "moonshot": "https://api.moonshot.ai/v1/models",
}


def discover_provider_models(
    *,
    provider: str,
    api_key: str,
    base_url: str = "",
    models_url: str = "",
    timeout: float = 8.0,
) -> list[str]:
    provider_id = provider.strip().lower()
    if not api_key:
        raise RuntimeError("Provider API key is missing.")
    url = models_url or _models_url(provider_id, base_url)

    if provider_id == "anthropic":
        data = _request_json(
            "GET",
            url,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            timeout=timeout,
        )
        return _extract_model_ids(data)

    if provider_id == "google":
        query_url = url + "?" + urllib.parse.urlencode({"key": api_key})
        data = _request_json("GET", query_url, headers={}, timeout=timeout)
        models = []
        for item in data.get("models", []):
            name = str(item.get("name") or "")
            if name.startswith("models/"):
                name = name.split("/", 1)[1]
            methods = item.get("supportedGenerationMethods", ["generateContent"])
            if name and "generateContent" in methods:
                models.append(name)
        return sorted(set(models))

    data = _request_json(
        "GET",
        url,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout,
    )
    return _extract_model_ids(data)


def _models_url(provider: str, base_url: str) -> str:
    if base_url:
        value = base_url.rstrip("/")
        if value.endswith("/chat/completions"):
            value = value[: -len("/chat/completions")]
        return value + "/models"
    return DEFAULT_MODELS_URLS.get(provider, "")


def _request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {raw[:220]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(str(exc.reason or exc)) from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Provider returned non-JSON: {raw[:220]}") from exc


def _extract_model_ids(data: dict[str, Any]) -> list[str]:
    models = []
    for item in data.get("data", data.get("models", [])):
        if isinstance(item, dict):
            model_id = str(item.get("id") or item.get("name") or "")
        else:
            model_id = str(item or "")
        if model_id:
            models.append(model_id)
    return sorted(set(models))
