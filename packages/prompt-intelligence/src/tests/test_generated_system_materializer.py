"""Focused X10-031 tests for local generated-system materialization."""

from __future__ import annotations

import copy
import json
import os
import sys
import unittest
from types import SimpleNamespace


SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for location in (
    SRC,
    os.path.join(SRC, "code_generation"),
    os.path.join(SRC, "output_parser"),
    os.path.join(SRC, "llm_orchestrator"),
    os.path.join(SRC, "context_assembler"),
):
    if location not in sys.path:
        sys.path.insert(0, location)

from generated_system_materializer import (  # noqa: E402
    GeneratedSystemMaterializationError,
    GeneratedSystemMaterializer,
)
from generated_system_safe_compiler import (  # noqa: E402
    build_compile_artifact,
)
from structured_output_parser import ParseError, StructuredOutputParser  # noqa: E402
from system_spec_builder import SystemSpecBuilder, VALID_PHASES  # noqa: E402
from typed_operations import (  # noqa: E402
    normalized_typed_operation_batch,
    parse_typed_operation_batch,
)


def _base_cgs(field_type: str = "fixed") -> dict:
    return {
        "metadata": {
            "name": "Generated Materializer Test",
            "version": "0.1.0",
            "schema_version": "0.1.0",
            "cgs_hash": "a" * 64,
        },
        "component_schemas": [
            {
                "type_id": 300,
                "name": "COMP_COUNTER_V1",
                "version": "1.0.0",
                "fields": [
                    {
                        "name": "count",
                        "field_type": field_type,
                        "default": 0,
                        "description": "Fixed64 raw micro-units.",
                    }
                ],
                "defaults": {"count": 0},
                "source": "generated",
            }
        ],
        "global_systems": [],
        "semantic_events": [],
        "assets": [],
        "modes": [
            {
                "id": "default",
                "is_default": True,
                "actors": [
                    {
                        "id": "counter",
                        "components": [
                            {
                                "type_id": 300,
                                "name": "COMP_COUNTER_V1",
                                "defaults": {"count": 0},
                            }
                        ],
                    }
                ],
                "systems": [],
                "rules": [],
            }
        ],
    }


def _provider_batch(phase: str = "Simulation") -> dict:
    raw = {
        "schema": "xace.typed_cgs_operation_batch.v1",
        "request_id": "request.generated.test",
        "prompt_id": "prompt.generated.test",
        "summary": "Add a locally compiled generated counter system",
        "operations": [
            {
                "operation_id": "op.generated.counter",
                "kind": "add_generated_system",
                "explanation": "Increment the fixed counter every tick.",
                "system_id": "GeneratedCounterSystem",
                "phase": phase,
                "reads": [300],
                "writes": [300],
                "depends_on": [],
                "behavior": {
                    "kind": "increment_numeric_field",
                    "component_type_id": 300,
                    "field": "count",
                    "amount": 1,
                },
            }
        ],
    }
    parsed = parse_typed_operation_batch(json.dumps(raw))
    return normalized_typed_operation_batch(parsed)


def _system(cgs: dict, system_id: str = "GeneratedCounterSystem") -> dict:
    return next(item for item in cgs["global_systems"] if item["id"] == system_id)


def _has_float(value: object) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, list):
        return any(_has_float(item) for item in value)
    if isinstance(value, dict):
        return any(_has_float(item) for item in value.values())
    return False


class _SuccessfulEngine:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate_system(self, **kwargs):
        self.calls.append(kwargs)
        staged = kwargs["cgs"]
        system = _system(staged, kwargs["system_id"])
        executor = copy.deepcopy(system["runtime_executor"])
        spec = SystemSpecBuilder().build(kwargs["system_id"], staged)
        assert spec.is_valid, spec.validation_errors
        count_field = next(
            field
            for component in spec.writes
            for field in component.fields
            if field.field_name == "count"
        )
        assert count_field.rust_type == "i64"
        artifact = build_compile_artifact(
            system_id=kwargs["system_id"],
            cgs_hash=staged["metadata"]["cgs_hash"],
            rust_source="impl ISystem for GeneratedCounterSystem {}",
            runtime_executor=executor,
            sgc_plan_hash="b" * 64,
            cargo_duration_ms=1.25,
            cargo_warnings=0,
        )
        signed = copy.deepcopy(executor)
        signed["compile_artifact"] = artifact
        return SimpleNamespace(
            succeeded=True,
            error="",
            safe_compile_result=SimpleNamespace(succeeded=True),
            signed_runtime_executor=signed,
            diff_text="=== NEW SYSTEM: GeneratedCounterSystem ===",
        )


class GeneratedSystemMaterializerTests(unittest.TestCase):
    def test_materializes_signed_executor_then_trusted_parser_accepts(self) -> None:
        cgs = _base_cgs()
        batch = _provider_batch()
        cgs_before = json.dumps(cgs, sort_keys=True)
        batch_before = json.dumps(batch, sort_keys=True)
        engine = _SuccessfulEngine()
        materializer = GeneratedSystemMaterializer(
            enabled=True,
            sgc_bin_path="test-sgc",
            code_generation_engine=engine,
            sgc_path_checker=lambda _: True,
        )

        result = materializer.materialize(batch, cgs, session_id="test-session")

        self.assertEqual(json.dumps(cgs, sort_keys=True), cgs_before)
        self.assertEqual(json.dumps(batch, sort_keys=True), batch_before)
        self.assertEqual(result.generated_system_ids, ("GeneratedCounterSystem",))
        executor = result.normalized_batch["operations"][0]["runtime_executor"]
        self.assertEqual(executor["kind"], "generated.increment_numeric_field")
        self.assertEqual(executor["abi"]["errors"]["policy"], "halt_and_rollback")
        self.assertEqual(
            executor["abi"]["rollback"],
            {
                "mutation_hook": "mutation_gate_deferred",
                "event_hook": "event_bus_phase_buffered",
                "rng_hook": "rng_windowed",
            },
        )
        self.assertEqual(
            executor["compile_artifact"]["cargo"]["duration_ms"], 0
        )
        self.assertFalse(_has_float(result.normalized_batch))
        self.assertEqual(len(engine.calls), 1)

        materialized_json = json.dumps(result.normalized_batch, sort_keys=True)
        with self.assertRaises(ParseError):
            StructuredOutputParser().parse_typed(materialized_json, cgs)
        canonical = StructuredOutputParser().parse_typed(
            materialized_json,
            cgs,
            allow_materialized_generated_systems=True,
        )
        self.assertTrue(canonical.is_fully_valid, canonical.validation.errors)
        committed_system = _system(canonical.proposed_cgs)
        self.assertEqual(committed_system["runtime_executor"], executor)

    def test_rejects_non_fixed_target_without_calling_engine(self) -> None:
        cgs = _base_cgs(field_type="int")
        batch = _provider_batch()
        engine = _SuccessfulEngine()
        materializer = GeneratedSystemMaterializer(
            enabled=True,
            sgc_bin_path="test-sgc",
            code_generation_engine=engine,
            sgc_path_checker=lambda _: True,
        )

        with self.assertRaises(GeneratedSystemMaterializationError) as caught:
            materializer.materialize(batch, cgs)

        self.assertEqual(caught.exception.code, "component_field_not_fixed")
        self.assertEqual(engine.calls, [])

    def test_fails_closed_when_disabled_missing_sgc_or_compile_fails(self) -> None:
        cgs = _base_cgs()
        batch = _provider_batch()
        cases = [
            (
                GeneratedSystemMaterializer(enabled=False),
                "code_generation_disabled",
            ),
            (
                GeneratedSystemMaterializer(
                    enabled=True,
                    code_generation_engine=_SuccessfulEngine(),
                ),
                "sgc_path_required",
            ),
            (
                GeneratedSystemMaterializer(
                    enabled=True,
                    sgc_bin_path="test-sgc",
                    code_generation_engine=SimpleNamespace(
                        generate_system=lambda **_: SimpleNamespace(
                            succeeded=False,
                            error="compile failed",
                        )
                    ),
                    sgc_path_checker=lambda _: True,
                ),
                "code_generation_failed",
            ),
        ]
        for materializer, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                with self.assertRaises(GeneratedSystemMaterializationError) as caught:
                    materializer.materialize(batch, cgs)
                self.assertEqual(caught.exception.code, expected_code)

    def test_system_spec_supports_canonical_phases_and_rejects_generated_stub(self) -> None:
        self.assertEqual(
            VALID_PHASES,
            frozenset({
                "Initialization",
                "Input",
                "Simulation",
                "PostSimulation",
                "Cleanup",
            }),
        )
        base = _base_cgs()
        for phase in sorted(VALID_PHASES):
            cgs = copy.deepcopy(base)
            operation = _provider_batch(phase)["operations"][0]
            cgs["global_systems"].append({
                "id": operation["system_id"],
                "phase": phase,
                "reads": [300],
                "writes": [300],
                "depends_on": [],
                "deterministic": True,
                "runtime_executor": {
                    "kind": "generated.increment_numeric_field",
                    "component_type_id": 300,
                    "field": "count",
                    "amount": 1,
                },
            })
            self.assertTrue(
                SystemSpecBuilder().build(operation["system_id"], cgs).is_valid,
                phase,
            )

        missing = _base_cgs()
        missing["component_schemas"] = []
        missing["modes"][0]["actors"][0]["components"] = []
        missing["global_systems"].append({
            "id": "GeneratedMissingComponentSystem",
            "phase": "Simulation",
            "reads": [999],
            "writes": [999],
            "depends_on": [],
            "deterministic": True,
            "runtime_executor": {
                "kind": "generated.increment_numeric_field",
                "component_type_id": 999,
                "field": "count",
                "amount": 1,
            },
        })
        spec = SystemSpecBuilder().build("GeneratedMissingComponentSystem", missing)
        self.assertFalse(spec.is_valid)
        self.assertTrue(
            any("placeholder component types are forbidden" in error for error in spec.validation_errors)
        )


if __name__ == "__main__":
    unittest.main()
