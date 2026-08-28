"""Focused X10-031 tests for prompt-authored generated-system definitions."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC))

from typed_operations import (  # noqa: E402
    AddGeneratedSystemOperation,
    OperationKind,
    TypedOperationError,
    apply_typed_operation_batch,
    compile_typed_operation_batch,
    normalized_typed_operation_batch,
    parse_typed_operation_batch,
    serialize_typed_operation_batch,
    typed_operation_batch_json_schema,
)


def _provider_payload() -> dict:
    return {
        "schema": "xace.typed_cgs_operation_batch.v1",
        "request_id": "request.generated.counter",
        "prompt_id": "prompt.generated.counter",
        "summary": "Increment the generated counter deterministically.",
        "operations": [
            {
                "operation_id": "generate.counter.system",
                "kind": "add_generated_system",
                "explanation": "Increment every generated counter once per tick.",
                "system_id": "GeneratedCounterSystem",
                "phase": "Simulation",
                "reads": [10000],
                "writes": [10000],
                "depends_on": [],
                "behavior": {
                    "kind": "increment_numeric_field",
                    "component_type_id": 10000,
                    "field": "count",
                    "amount": 1,
                },
            }
        ],
    }


def _runtime_executor(*, rollback_event_hook: str = "event_bus_phase_buffered") -> dict:
    return {
        "kind": "generated.increment_numeric_field",
        "component_type_id": 10000,
        "field": "count",
        "amount": 1,
        "abi": {
            "schema": "xace.generated_system_abi.v1",
            "version": 1,
            "inputs": {
                "query_components": [10000],
                "component_reads": [10000],
                "current_tick": False,
            },
            "events": {"emits": []},
            "rng": {"allowed": False, "max_calls_per_entity": 0},
            "errors": {"policy": "halt_and_rollback"},
            "rollback": {
                "mutation_hook": "mutation_gate_deferred",
                "event_hook": rollback_event_hook,
                "rng_hook": "rng_windowed",
            },
        },
        "compile_artifact": {
            "schema": "xace.generated_system_compile_artifact.v1",
            "system_id": "GeneratedCounterSystem",
            "signature": "0" * 64,
        },
    }


def _materialized_payload() -> dict:
    payload = _provider_payload()
    payload["operations"][0]["runtime_executor"] = _runtime_executor()
    return payload


def _current_cgs(*, field_type: str = "fixed", include_field: bool = True) -> dict:
    fields = []
    if include_field:
        fields.append(
            {
                "name": "count",
                "field_type": field_type,
                "default": 0,
            }
        )
    return {
        "component_schemas": [
            {
                "type_id": 10000,
                "name": "COMP_COUNTER_V1",
                "version": "1.0.0",
                "fields": fields,
                "defaults": {"count": 0},
                "source": "generated",
            }
        ],
        "global_systems": [],
        "modes": [
            {
                "id": "mode_gameplay",
                "actors": [],
                "systems": [],
                "rules": [],
            }
        ],
    }


class TestGeneratedSystemTypedOperation(unittest.TestCase):
    def test_provider_definition_defaults_without_materializing_executor(self) -> None:
        batch = parse_typed_operation_batch(_provider_payload())
        operation = batch.operations[0]

        self.assertIsInstance(operation, AddGeneratedSystemOperation)
        self.assertIs(operation.kind, OperationKind.ADD_GENERATED_SYSTEM)
        self.assertEqual(operation.scope.value, "global")
        self.assertEqual(operation.version, "1.0.0")
        self.assertTrue(operation.deterministic)
        self.assertFalse(operation.parallel)
        self.assertIsNone(operation.runtime_executor)

        normalized = normalized_typed_operation_batch(batch)
        self.assertNotIn("runtime_executor", normalized["operations"][0])
        record = compile_typed_operation_batch(batch).global_systems[0]
        self.assertEqual(record["source"], "generated")
        self.assertEqual(record["description"], operation.explanation)
        self.assertEqual(record["version"], "1.0.0")
        self.assertTrue(record["deterministic"])
        self.assertNotIn("runtime_executor", record)

    def test_provider_schema_is_closed_and_excludes_internal_executor(self) -> None:
        schema = typed_operation_batch_json_schema()
        variants = schema["properties"]["operations"]["items"]["anyOf"]
        variant = next(
            item
            for item in variants
            if item["properties"]["kind"].get("const")
            == "add_generated_system"
        )

        self.assertNotIn("runtime_executor", variant["properties"])
        self.assertEqual(set(variant["required"]), set(variant["properties"]))
        self.assertFalse(variant["additionalProperties"])
        behavior = variant["properties"]["behavior"]
        self.assertFalse(behavior["additionalProperties"])
        self.assertEqual(set(behavior["required"]), set(behavior["properties"]))
        self.assertEqual(behavior["properties"]["amount"]["type"], "integer")
        self.assertNotIn("oneOf", json.dumps(schema, sort_keys=True))
        self.assertNotIn("uniqueItems", json.dumps(schema, sort_keys=True))
        self.assertNotIn('"$id"', json.dumps(schema, sort_keys=True))

    def test_executor_is_rejected_from_provider_and_allowed_only_explicitly(self) -> None:
        payload = _materialized_payload()
        with self.assertRaisesRegex(TypedOperationError, "internal-only"):
            parse_typed_operation_batch(payload)

        batch = parse_typed_operation_batch(
            payload,
            allow_materialized_generated_systems=True,
        )
        operation = batch.operations[0]
        self.assertEqual(operation.runtime_executor, _runtime_executor())
        normalized = normalized_typed_operation_batch(batch)
        self.assertEqual(
            normalized["operations"][0]["runtime_executor"],
            _runtime_executor(),
        )
        self.assertEqual(
            serialize_typed_operation_batch(batch).count('"runtime_executor"'),
            1,
        )

    def test_materialized_system_enters_cgs_with_full_metadata_and_abi(self) -> None:
        batch = parse_typed_operation_batch(
            _materialized_payload(),
            allow_materialized_generated_systems=True,
        )
        result = apply_typed_operation_batch(batch, _current_cgs())

        self.assertTrue(result.validation.valid, result.validation.errors)
        self.assertIsNotNone(result.proposed_cgs)
        system = result.proposed_cgs["global_systems"][0]
        self.assertEqual(system["id"], "GeneratedCounterSystem")
        self.assertEqual(system["source"], "generated")
        self.assertEqual(system["version"], "1.0.0")
        self.assertEqual(
            system["description"],
            "Increment every generated counter once per tick.",
        )
        self.assertTrue(system["deterministic"])
        self.assertEqual(system["runtime_executor"], _runtime_executor())

    def test_unmaterialized_system_cannot_enter_cgs(self) -> None:
        batch = parse_typed_operation_batch(_provider_payload())
        result = apply_typed_operation_batch(batch, _current_cgs())

        self.assertFalse(result.validation.valid)
        self.assertIsNone(result.proposed_cgs)
        self.assertTrue(
            any("locally materialized" in error for error in result.validation.errors),
            result.validation.errors,
        )

    def test_behavior_requires_sorted_access_and_read_write_ownership(self) -> None:
        unsorted = _provider_payload()
        unsorted["operations"][0]["reads"] = [10001, 10000]
        with self.assertRaisesRegex(TypedOperationError, "reads must be sorted"):
            parse_typed_operation_batch(unsorted)

        not_read = _provider_payload()
        not_read["operations"][0]["reads"] = [10001]
        with self.assertRaisesRegex(TypedOperationError, "declared in reads"):
            parse_typed_operation_batch(not_read)

        not_written = _provider_payload()
        not_written["operations"][0]["writes"] = [10001]
        with self.assertRaisesRegex(TypedOperationError, "declared in writes"):
            parse_typed_operation_batch(not_written)

    def test_behavior_is_closed_and_integer_only(self) -> None:
        extra = _provider_payload()
        extra["operations"][0]["behavior"]["formula"] = "count + 1"
        with self.assertRaisesRegex(TypedOperationError, "unknown fields"):
            parse_typed_operation_batch(extra)

        for invalid in (True, 1.5, float("nan"), float("inf")):
            payload = _provider_payload()
            payload["operations"][0]["behavior"]["amount"] = invalid
            with self.subTest(amount=invalid):
                with self.assertRaisesRegex(TypedOperationError, "must be an integer"):
                    parse_typed_operation_batch(payload)

    def test_generated_target_requires_explicit_exact_fixed_schema_field(self) -> None:
        batch = parse_typed_operation_batch(
            _materialized_payload(),
            allow_materialized_generated_systems=True,
        )
        wrong_type = apply_typed_operation_batch(
            batch,
            _current_cgs(field_type="int"),
        )
        self.assertFalse(wrong_type.validation.valid)
        self.assertTrue(
            any("exact type 'fixed'" in error for error in wrong_type.validation.errors),
            wrong_type.validation.errors,
        )

        missing_field = apply_typed_operation_batch(
            batch,
            _current_cgs(include_field=False),
        )
        self.assertFalse(missing_field.validation.valid)
        self.assertTrue(
            any(
                "field type metadata" in error
                for error in missing_field.validation.errors
            ),
            missing_field.validation.errors,
        )

        missing_component_cgs = _current_cgs()
        missing_component_cgs["component_schemas"] = []
        missing_component = apply_typed_operation_batch(
            batch,
            missing_component_cgs,
        )
        self.assertFalse(missing_component.validation.valid)
        self.assertTrue(
            any("undeclared component" in error for error in missing_component.validation.errors),
            missing_component.validation.errors,
        )

    def test_executor_must_match_behavior_and_exact_rollback_abi(self) -> None:
        mismatched = _materialized_payload()
        mismatched["operations"][0]["runtime_executor"]["field"] = "other"
        with self.assertRaisesRegex(TypedOperationError, "does not match behavior"):
            parse_typed_operation_batch(
                mismatched,
                allow_materialized_generated_systems=True,
            )

        bad_rollback = _materialized_payload()
        bad_rollback["operations"][0]["runtime_executor"] = _runtime_executor(
            rollback_event_hook="immediate"
        )
        batch = parse_typed_operation_batch(
            bad_rollback,
            allow_materialized_generated_systems=True,
        )
        result = apply_typed_operation_batch(batch, _current_cgs())
        self.assertFalse(result.validation.valid)
        self.assertTrue(
            any("rollback contract" in error for error in result.validation.errors),
            result.validation.errors,
        )

    def test_generated_and_builtin_system_ids_share_one_batch_namespace(self) -> None:
        payload = _provider_payload()
        payload["operations"][0]["system_id"] = "InputSystem"
        payload["operations"].append({
            "operation_id": "add.builtin.input",
            "kind": "add_system",
            "explanation": "Register the built-in input system.",
            "system_id": "InputSystem",
            "phase": "Input",
            "reads": [5, 6],
            "writes": [5],
            "depends_on": [],
            "implementation_ref": "builtin.InputSystem.v1",
        })

        with self.assertRaisesRegex(TypedOperationError, "declared system IDs"):
            parse_typed_operation_batch(payload)


if __name__ == "__main__":
    unittest.main()
