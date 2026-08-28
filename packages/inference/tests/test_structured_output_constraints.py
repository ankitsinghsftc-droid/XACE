from __future__ import annotations

import json
import unittest
from typing import Any

from ..providers.anthropic_provider import AnthropicProvider
from ..providers.google_provider import GoogleProvider
from ..providers.openai_provider import OpenAICompatibleProvider
from ..src.cache_key_builder import CacheKeyBuilder
from ..src.inference_adapter import InferenceAdapter, InferenceRequest, PromptPart
from ..src.inference_budget import InferenceBudget
from ..src.inference_retry_policy import InferenceRetryPolicy
from ..src.model_descriptor import ComplexityTier, ModelCapability, ModelDescriptor
from ..src.prompt_cache import PromptCache
from ..src.provider_registry import IProviderClient, ProviderRegistry
from ..src.response_cache import ResponseCache
from ..src.structured_output import (
    StructuredOutputContract,
    mutation_transaction_contract,
    validate_structured_output_text,
)
from ..src.telemetry_pipeline import InMemoryBackend, TelemetryPipeline


_VALID_TXT = json.dumps({
    "schema_delta_type": "value_mutation",
    "confidence_score": 0.91,
    "risk_level": "low",
    "required_recompile": False,
    "mutation_summary": "Sets enemy speed.",
})


class _CaptureClient(IProviderClient):
    def __init__(self, provider: str, responses: list[dict[str, Any]]) -> None:
        self._provider = provider
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        model_id: str,
        prompt: dict[str, Any],
        system_prompt: str,
        max_tokens: int,
        temperature: float,
        structured_output: Any | None = None,
    ) -> dict[str, Any]:
        self.calls.append({
            "model_id": model_id,
            "prompt": prompt,
            "structured_output": structured_output,
        })
        return self._responses.pop(0)

    def health_check(self) -> bool:
        return True

    def provider_name(self) -> str:
        return self._provider


def _response(text: str) -> dict[str, Any]:
    return {
        "text": text,
        "input_tokens": 12,
        "output_tokens": 7,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }


def _adapter(
    *,
    provider: str,
    client: IProviderClient,
    structured_capability: bool,
) -> tuple[InferenceAdapter, InMemoryBackend]:
    registry = ProviderRegistry(
        config={
            "default_provider": provider,
            "logical_model_map": {"cheap_validation": provider},
            "fallback_chains": {provider: []},
        },
        clients={provider: client},
    )
    capabilities = {ModelCapability.GENERATION}
    if structured_capability:
        capabilities.add(ModelCapability.STRUCTURED_OUTPUT)
    registry.register_descriptor(ModelDescriptor(
        logical_name="cheap_validation",
        provider=provider,
        model_id=f"{provider}-test-model",
        context_window_tokens=4096,
        max_output_tokens=256,
        input_price_per_1k=0.0,
        output_price_per_1k=0.0,
        cache_write_price_per_1k=0.0,
        cache_read_price_per_1k=0.0,
        supports_cache_control=False,
        default_tier=ComplexityTier.M,
        capabilities=frozenset(capabilities),
    ))
    telemetry = TelemetryPipeline()
    backend = InMemoryBackend()
    telemetry.add_backend(backend)
    return InferenceAdapter(
        provider_registry=registry,
        telemetry=telemetry,
        budget=InferenceBudget(),
        retry_policy=InferenceRetryPolicy(sleep_fn=lambda _: None),
        prompt_cache=PromptCache(),
        response_cache=ResponseCache(),
        cache_key_builder=CacheKeyBuilder(),
    ), backend


def _request() -> InferenceRequest:
    return InferenceRequest(
        prompt_parts=[PromptPart("Return the final mutation JSON.")],
        logical_model="cheap_validation",
        complexity_tier=ComplexityTier.M,
        call_label="pass5_final_output",
        structured_output=mutation_transaction_contract(),
        cgs_structural_hash="sha256:test-cgs",
        intent_class="BalanceAdjustment",
    )


class TestStructuredOutputConstraints(unittest.TestCase):
    def test_local_validator_enforces_strict_variant_keywords(self) -> None:
        contract = StructuredOutputContract(
            schema_id="xace.strict_keyword_test.v1",
            name="xace_strict_keyword_test_v1",
            schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["kind", "count", "code", "tags"],
                "properties": {
                    "kind": {
                        "anyOf": [
                            {"type": "string", "const": "alpha"},
                            {"type": "string", "const": "beta"},
                        ]
                    },
                    "count": {"type": "integer", "minimum": 1, "maximum": 3},
                    "code": {"type": "string", "pattern": r"^[A-Z]{2}$"},
                    "tags": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 2,
                        "uniqueItems": True,
                        "items": {"type": "string"},
                    },
                },
            },
        )
        valid = {"kind": "alpha", "count": 2, "code": "OK", "tags": ["x"]}
        self.assertEqual(
            validate_structured_output_text(json.dumps(valid), contract),
            [],
        )

        invalid_values = {
            "anyOf/const": {**valid, "kind": "gamma"},
            "integer": {**valid, "count": True},
            "minimum": {**valid, "count": 0},
            "maximum": {**valid, "count": 4},
            "pattern": {**valid, "code": "bad"},
            "minItems": {**valid, "tags": []},
            "maxItems": {**valid, "tags": ["x", "y", "z"]},
            "uniqueItems": {**valid, "tags": ["x", "x"]},
        }
        for keyword, payload in invalid_values.items():
            with self.subTest(keyword=keyword):
                self.assertTrue(
                    validate_structured_output_text(json.dumps(payload), contract)
                )

        unsupported = StructuredOutputContract(
            schema_id="xace.unsupported_one_of.v1",
            name="xace_unsupported_one_of_v1",
            schema={"oneOf": [{"type": "string"}]},
        )
        self.assertTrue(validate_structured_output_text('"value"', unsupported))

    def test_openai_request_uses_json_schema_response_format(self) -> None:
        contract = mutation_transaction_contract()
        body = OpenAICompatibleProvider(api_key="sk-test")._build_body(
            "gpt-test",
            {"text": "make final transaction"},
            "system",
            128,
            0.0,
            contract,
        )

        response_format = body["response_format"]
        self.assertEqual(response_format["type"], "json_schema")
        self.assertEqual(response_format["json_schema"]["name"], contract.name)
        self.assertIs(response_format["json_schema"]["strict"], True)
        self.assertEqual(
            response_format["json_schema"]["schema"]["required"],
            contract.schema["required"],
        )

    def test_google_request_uses_json_mime_and_response_schema(self) -> None:
        contract = mutation_transaction_contract()
        body = GoogleProvider(api_key="AIza-test", thinking_level="none")._build_body(
            {"text": "make final transaction"},
            "system",
            128,
            0.0,
            contract,
        )

        generation_config = body["generationConfig"]
        self.assertEqual(generation_config["responseMimeType"], "application/json")
        self.assertEqual(generation_config["responseSchema"], contract.schema)

    def test_anthropic_request_forces_structured_tool_choice(self) -> None:
        contract = mutation_transaction_contract()
        body = AnthropicProvider(api_key="sk-ant-test")._build_body(
            "claude-test",
            {"text": "make final transaction"},
            "system",
            128,
            0.0,
            contract,
        )

        self.assertEqual(body["tools"][0]["name"], contract.name)
        self.assertEqual(body["tools"][0]["input_schema"], contract.schema)
        self.assertEqual(body["tool_choice"], {"type": "tool", "name": contract.name})

        parsed = AnthropicProvider._parse_response({
            "content": [{"type": "tool_use", "input": json.loads(_VALID_TXT)}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        })
        self.assertEqual(json.loads(parsed["text"])["schema_delta_type"], "value_mutation")

    def test_adapter_passes_native_contract_and_records_telemetry(self) -> None:
        client = _CaptureClient("openai", [_response(_VALID_TXT)])
        adapter, backend = _adapter(
            provider="openai",
            client=client,
            structured_capability=True,
        )

        response = adapter.call(_request())

        self.assertEqual(json.loads(response.text)["risk_level"], "low")
        self.assertEqual(
            client.calls[0]["structured_output"].schema_id,
            "xace.mutation_transaction.v1",
        )
        event = backend.all_events()[0]
        self.assertIs(event.structured_output_requested, True)
        self.assertIs(event.structured_output_supported, True)
        self.assertIs(event.structured_output_enforced, True)
        self.assertEqual(event.structured_output_mode, "openai_json_schema")
        self.assertEqual(
            event.structured_output_schema_hash,
            mutation_transaction_contract().schema_hash,
        )

    def test_unsupported_provider_uses_repair_quarantine_and_schema_retry(self) -> None:
        client = _CaptureClient("local", [_response("not json"), _response(_VALID_TXT)])
        adapter, backend = _adapter(
            provider="local",
            client=client,
            structured_capability=False,
        )

        response = adapter.call(_request())

        self.assertIs(json.loads(response.text)["required_recompile"], False)
        self.assertEqual(len(client.calls), 2)
        self.assertIsNone(client.calls[0]["structured_output"])
        self.assertIsNone(client.calls[1]["structured_output"])
        event = backend.all_events()[0]
        self.assertIs(event.structured_output_requested, True)
        self.assertIs(event.structured_output_supported, False)
        self.assertIs(event.structured_output_enforced, False)
        self.assertEqual(event.structured_output_mode, "repair_quarantine")
        self.assertGreaterEqual(event.retry_count, 1)


if __name__ == "__main__":
    unittest.main()
