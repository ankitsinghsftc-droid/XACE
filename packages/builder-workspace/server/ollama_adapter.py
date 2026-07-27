"""
Inference-backed local Ollama adapter for Builder prompt flows.

The HTTP client lives in packages/inference. This module preserves the small
Builder-facing surface while keeping all model dispatch behind InferenceAdapter.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


_PACKAGES_ROOT = Path(__file__).resolve().parents[2]
if str(_PACKAGES_ROOT) not in sys.path:
    sys.path.insert(0, str(_PACKAGES_ROOT))

from inference.src.cache_key_builder import CacheKeyBuilder  # noqa: E402
from inference.src.inference_adapter import InferenceAdapter, InferenceResponse  # noqa: E402
from inference.src.inference_budget import InferenceBudget  # noqa: E402
from inference.src.inference_retry_policy import InferenceRetryPolicy  # noqa: E402
from inference.src.local_model_manager import LocalModelConfig, LocalModelManager  # noqa: E402
from inference.src.model_descriptor import ComplexityTier, ModelCapability, ModelDescriptor  # noqa: E402
from inference.src.prompt_cache import PromptCache  # noqa: E402
from inference.src.provider_registry import ProviderRegistry  # noqa: E402
from inference.src.response_cache import ResponseCache  # noqa: E402
from inference.src.telemetry_pipeline import TelemetryPipeline  # noqa: E402


DEFAULT_TEST_MODELS = ["auto"]


class OllamaAdapter:
    def __init__(
        self,
        model: str = "auto",
        base_url: str = "http://localhost:11434",
        timeout_seconds: float = 120.0,
    ) -> None:
        self._model = model or "auto"
        self._manager = LocalModelManager(
            LocalModelConfig(
                base_url=base_url.rstrip("/"),
                default_models=(),
                auto_pull_on_miss=False,
                timeout=int(timeout_seconds),
            )
        )
        self._adapters: dict[str, InferenceAdapter] = {}

    def is_healthy(self) -> bool:
        return bool(self.list_models())

    def list_models(self) -> list[str]:
        return self._manager.available_models()

    def call(self, request: Any) -> InferenceResponse:
        model = self._resolve_model()
        return self._adapter_for(model).call(request)

    def _resolve_model(self) -> str:
        if self._model != "auto":
            return self._model
        installed = self.list_models()
        if installed:
            return installed[0]
        raise RuntimeError(
            "Ollama model is unresolved. Pull a local model or choose a hosted provider."
        )

    def _adapter_for(self, model: str) -> InferenceAdapter:
        adapter = self._adapters.get(model)
        if adapter is not None:
            return adapter

        provider = "local"
        registry = ProviderRegistry(
            config={
                "default_provider": provider,
                "logical_model_map": {
                    "cheap_validation": provider,
                    "standard_mutation": provider,
                    "premium_reasoning": provider,
                },
                "fallback_chains": {provider: []},
            },
            clients={provider: self._manager},
        )
        caps = frozenset({
            ModelCapability.GENERATION,
            ModelCapability.CODE_GEN,
            ModelCapability.CRITIQUE,
            ModelCapability.REASONING,
            ModelCapability.FUNCTION_CALL,
        })
        for logical_name, tier in (
            ("cheap_validation", ComplexityTier.M),
            ("standard_mutation", ComplexityTier.L),
            ("premium_reasoning", ComplexityTier.XL),
        ):
            registry.register_descriptor(ModelDescriptor(
                logical_name=logical_name,
                provider=provider,
                model_id=model,
                context_window_tokens=128_000,
                max_output_tokens=8_192,
                input_price_per_1k=0.0,
                output_price_per_1k=0.0,
                cache_write_price_per_1k=0.0,
                cache_read_price_per_1k=0.0,
                supports_cache_control=False,
                default_tier=tier,
                capabilities=caps,
                notes="Local model selected from XACE Builder settings.",
            ))

        adapter = InferenceAdapter(
            provider_registry=registry,
            telemetry=TelemetryPipeline(),
            budget=InferenceBudget(),
            retry_policy=InferenceRetryPolicy(),
            prompt_cache=PromptCache(),
            response_cache=ResponseCache(),
            cache_key_builder=CacheKeyBuilder(),
        )
        self._adapters[model] = adapter
        return adapter


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
