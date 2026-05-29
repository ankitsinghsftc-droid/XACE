"""
ollama_adapter.py - Local Ollama adapter for the builder PIL pipeline.

This intentionally mirrors the tiny surface SessionManager needs:
    - list_models()
    - is_healthy()
    - call(request)
    - create_ollama_adapter(...)

It talks to Ollama's local HTTP API without adding third-party dependencies.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_TEST_MODELS = ["auto", "llama3.2", "llama3.1"]
AUTO_MODEL_ORDER = [
    "llama3.2",
    "llama3.2:latest",
    "llama3.1",
    "llama3.1:8b",
    "llama3.1:70b",
    "llama3.1:latest",
]


@dataclass
class OllamaResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_cents: float = 0.0
    model_id: str = ""
    provider: str = "ollama"
    latency_ms: float = 0.0
    call_label: str = ""
    request_id: str = ""
    session_id: str = ""
    cached: bool = False


class OllamaAdapter:
    def __init__(
        self,
        model: str = "auto",
        base_url: str = "http://localhost:11434",
        timeout_seconds: float = 120.0,
    ) -> None:
        self._model = model or "auto"
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    def is_healthy(self) -> bool:
        return bool(self.list_models())

    def list_models(self) -> list[str]:
        try:
            data = self._request("GET", "/api/tags")
        except Exception:
            return []

        names: list[str] = []
        for item in data.get("models", []):
            name = item.get("name", "")
            if isinstance(name, str) and name:
                names.append(name)
        return names

    def call(self, request: Any) -> OllamaResponse:
        model = self._resolve_model()
        prompt = _request_prompt(request)
        system_prompt = str(getattr(request, "system_prompt", "") or "")
        started = time.time()

        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": float(getattr(request, "temperature", 0.0) or 0.0),
                "num_predict": int(getattr(request, "max_tokens", 1200) or 1200),
            },
        }
        if system_prompt:
            payload["system"] = system_prompt

        data = self._request("POST", "/api/generate", payload)
        text = str(data.get("response", "") or "").strip()
        latency_ms = (time.time() - started) * 1000.0

        return OllamaResponse(
            text=text,
            input_tokens=int(data.get("prompt_eval_count", 0) or 0),
            output_tokens=int(data.get("eval_count", 0) or 0),
            model_id=model,
            latency_ms=latency_ms,
            call_label=str(getattr(request, "call_label", "") or ""),
            request_id=str(getattr(request, "request_id", "") or ""),
            session_id=str(getattr(request, "session_id", "") or ""),
        )

    def _resolve_model(self) -> str:
        if self._model != "auto":
            return self._model

        installed = self.list_models()
        installed_set = set(installed)
        for candidate in AUTO_MODEL_ORDER:
            if candidate in installed_set:
                return candidate
        if installed:
            return installed[0]
        return "llama3.2"

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._base_url + path,
            data=body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Cannot connect to Ollama at {self._base_url}. "
                "Run: ollama serve"
            ) from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Ollama returned non-JSON: {raw[:200]}") from exc


def create_ollama_adapter(
    model: str = "auto",
    base_url: str = "http://localhost:11434",
) -> OllamaAdapter:
    return OllamaAdapter(model=model, base_url=base_url)


def preferred_model_list(installed: list[str] | None = None) -> list[str]:
    seen: set[str] = set()
    models: list[str] = []
    for model in DEFAULT_TEST_MODELS + (installed or []):
        if model not in seen:
            seen.add(model)
            models.append(model)
    return models


def _request_prompt(request: Any) -> str:
    if hasattr(request, "full_prompt_text"):
        return str(request.full_prompt_text())
    parts = getattr(request, "prompt_parts", [])
    if parts:
        return "\n".join(str(getattr(part, "text", "") or "") for part in parts)
    return str(getattr(request, "prompt", "") or "")
