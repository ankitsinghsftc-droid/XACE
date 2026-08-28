"""X10-031 GDE trust-boundary tests for prompt-generated systems."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest

from ..cgs.cgs_serializer import CGSSerializer
from ..domain_dsl.mutation_metadata.mutation_metadata_model import MutationMetadata
from ..domain_dsl.typed_operations import (
    TypedOperationExecutionError,
    TypedOperationExecutor,
)
from ..gde_orchestrator import GDEOrchestrator


_VALIDATION_STEPS = [
    "system_spec_validation",
    "runtime_abi_validation",
    "unsupported_api_rejection",
    "code_contract_validation",
    "determinism_static_check",
    "cargo_check_sandbox",
    "sgc_compile",
    "artifact_signature",
    "runtime_registration",
]
_UNSUPPORTED_POLICY_HASH = (
    "3306f82262ec3e951b9d8d7de53dac45f3e69fac8b6b00d0959c89877c5e47c5"
)


def _base_cgs(*, field_type: str = "fixed") -> dict:
    cgs = {
        "format": "xace.cgs.export",
        "format_version": "1.0.0",
        "metadata": {
            "name": "Generated typed operation proof",
            "version": "0.1.0",
            "schema_version": "0.1.0",
            "execution_plan_version": 1,
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
                        "description": "Deterministic counter value.",
                    },
                    {
                        "name": "label",
                        "field_type": "string",
                        "default": "",
                        "description": "Non-numeric proof field.",
                    },
                ],
                "defaults": {"count": 0, "label": ""},
                "source": "generated",
            }
        ],
        "global_systems": [],
        "semantic_events": [],
        "assets": [],
        "modes": [
            {
                "id": "mode_gameplay",
                "schema_version": "0.1.0",
                "is_default": True,
                "actors": [
                    {
                        "id": "actor_counter",
                        "spawn_count": 1,
                        "components": [
                            {
                                "type_id": 300,
                                "name": "COMP_COUNTER_V1",
                                "defaults": {"count": 0, "label": ""},
                            }
                        ],
                    }
                ],
                "systems": [],
                "rules": [],
            }
        ],
    }
    without_hash = copy.deepcopy(cgs)
    cgs["metadata"]["cgs_hash"] = CGSSerializer.compute_hash(without_hash)
    return cgs


def _stable_hash(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _signature(artifact: dict) -> str:
    fields = [
        "schema",
        "system_id",
        "cgs_hash",
        "source_hash",
        "runtime_executor_hash",
        "abi_hash",
        "sgc_plan_hash",
        "unsupported_policy_hash",
        "sandbox_hash",
        "signing_key_id",
    ]
    lines = [f"{field}={artifact[field]}" for field in fields]
    lines.append("validation_steps=" + ",".join(artifact["validation_steps"]))
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _signed_executor(system_id: str, source_cgs_hash: str) -> dict:
    abi = {
        "schema": "xace.generated_system_abi.v1",
        "version": 1,
        "inputs": {
            "query_components": [300],
            "component_reads": [300],
            "current_tick": False,
        },
        "events": {"emits": []},
        "rng": {"allowed": False, "max_calls_per_entity": 0},
        "errors": {"policy": "halt_and_rollback"},
        "rollback": {
            "mutation_hook": "mutation_gate_deferred",
            "event_hook": "event_bus_phase_buffered",
            "rng_hook": "rng_windowed",
        },
    }
    executor = {
        "kind": "generated.increment_numeric_field",
        "component_type_id": 300,
        "field": "count",
        "amount": 1,
        "abi": abi,
    }
    artifact = {
        "schema": "xace.generated_system_compile_artifact.v1",
        "system_id": system_id,
        "cgs_hash": source_cgs_hash,
        "source_hash": "b" * 64,
        "runtime_executor_hash": _stable_hash(executor),
        "abi_hash": _stable_hash(abi),
        "sgc_plan_hash": "c" * 64,
        "unsupported_policy_hash": _UNSUPPORTED_POLICY_HASH,
        "sandbox_hash": "d" * 64,
        "validation_steps": list(_VALIDATION_STEPS),
        "cargo": {
            "sandbox": "temp_cargo_project_no_workspace_writes",
            "duration_ms": 1,
            "warnings": 0,
        },
        "signing_key_id": "xace-local-generated-system-v1",
    }
    artifact["signature"] = _signature(artifact)
    executor["compile_artifact"] = artifact
    return executor


def _batch(cgs: dict) -> dict:
    system_id = "GeneratedCounterSystem"
    return {
        "schema": "xace.typed_cgs_operation_batch.v1",
        "request_id": "request.task31",
        "prompt_id": "prompt.task31",
        "summary": "Generate a deterministic counter system.",
        "operations": [
            {
                "operation_id": "op.generated.counter",
                "kind": "add_generated_system",
                "explanation": "Increment the counter by one every simulation tick.",
                "system_id": system_id,
                "phase": "Simulation",
                "reads": [300],
                "writes": [300],
                "depends_on": [],
                "behavior": {
                    "kind": "increment_numeric_field",
                    "component_type_id": 300,
                    "field": "count",
                    "amount": 1,
                },
                "runtime_executor": _signed_executor(
                    system_id, cgs["metadata"]["cgs_hash"]
                ),
                "scope": "global",
                "mode_id": "",
                "version": "1.2.3",
                "deterministic": True,
                "parallel": False,
            }
        ],
    }


def _metadata(orchestrator: GDEOrchestrator) -> MutationMetadata:
    return MutationMetadata.create(
        source="prompt",
        parent_cgs_hash=orchestrator.current_hash,
        schema_version_target="0.1.0",
        prompt_text="generate a counter system",
        confidence=0.99,
        description="Generate deterministic counter behavior.",
        risk_level="medium",
        session_id="task31-gde-test",
    )


def test_signed_generated_system_is_materialized_with_complete_contract() -> None:
    before = _base_cgs()
    result = TypedOperationExecutor().execute(_batch(before), before)

    assert before["global_systems"] == []
    assert result.operation_kinds == ("add_generated_system",)
    system = result.proposed_cgs["global_systems"][0]
    assert system["id"] == "GeneratedCounterSystem"
    assert system["phase"] == "Simulation"
    assert system["reads"] == [300]
    assert system["writes"] == [300]
    assert system["depends_on"] == []
    assert system["version"] == "1.2.3"
    assert system["deterministic"] is True
    assert system["source"] == "generated"
    assert system["description"] == (
        "Increment the counter by one every simulation tick."
    )
    assert system["runtime_executor"] == _batch(before)["operations"][0][
        "runtime_executor"
    ]


def test_signed_generated_system_commits_through_full_consistency_validation() -> None:
    orchestrator = GDEOrchestrator(session_id="task31-gde-test")
    cgs = _base_cgs()
    orchestrator.load_cgs(cgs)

    result = orchestrator.process_typed_operation_batch(
        _batch(cgs), _metadata(orchestrator)
    )

    assert result.success, result.error
    assert result.typed_operation_kinds == ("add_generated_system",)
    assert orchestrator.current_cgs["global_systems"][0]["source"] == "generated"


def test_tampered_compile_artifact_is_rejected_atomically_by_full_validator() -> None:
    orchestrator = GDEOrchestrator(session_id="task31-gde-test")
    cgs = _base_cgs()
    orchestrator.load_cgs(cgs)
    before = orchestrator.current_cgs
    before_hash = orchestrator.current_hash
    batch = _batch(cgs)
    batch["operations"][0]["runtime_executor"]["compile_artifact"]["signature"] = "f" * 64

    result = orchestrator.process_typed_operation_batch(
        batch, _metadata(orchestrator)
    )

    assert not result.success
    assert "signature" in result.error
    assert orchestrator.current_hash == before_hash
    assert orchestrator.current_cgs == before


def _invalid_phase(batch: dict, cgs: dict) -> None:
    del cgs
    batch["operations"][0]["phase"] = "Physics"


def _unknown_dependency(batch: dict, cgs: dict) -> None:
    del cgs
    batch["operations"][0]["depends_on"] = ["MissingSystem"]


def _mode_scope_without_mode(batch: dict, cgs: dict) -> None:
    del cgs
    batch["operations"][0]["scope"] = "mode"


def _invalid_semver(batch: dict, cgs: dict) -> None:
    del cgs
    batch["operations"][0]["version"] = "v1"


def _duplicate_system(batch: dict, cgs: dict) -> None:
    cgs["global_systems"].append(
        {
            "id": batch["operations"][0]["system_id"],
            "phase": "Simulation",
            "reads": [],
            "writes": [],
            "depends_on": [],
            "deterministic": True,
        }
    )


def _unsigned_executor(batch: dict, cgs: dict) -> None:
    del cgs
    del batch["operations"][0]["runtime_executor"]["compile_artifact"]


def _behavior_executor_mismatch(batch: dict, cgs: dict) -> None:
    del cgs
    batch["operations"][0]["runtime_executor"]["amount"] = 2


def _missing_rollback_hook(batch: dict, cgs: dict) -> None:
    del cgs
    del batch["operations"][0]["runtime_executor"]["abi"]["rollback"]["event_hook"]


def _behavior_component_not_written(batch: dict, cgs: dict) -> None:
    del cgs
    batch["operations"][0]["writes"] = []


def _non_fixed_target(batch: dict, cgs: dict) -> None:
    cgs["component_schemas"][0]["fields"][0]["field_type"] = "int"


def _unknown_behavior_field(batch: dict, cgs: dict) -> None:
    del cgs
    operation = batch["operations"][0]
    operation["behavior"]["field"] = "missing"
    operation["runtime_executor"]["field"] = "missing"


class TestGeneratedSystemTypedOperationExecutor(unittest.TestCase):
    def test_signed_generated_system_materializes_complete_contract(self) -> None:
        test_signed_generated_system_is_materialized_with_complete_contract()

    def test_signed_generated_system_commits_through_validator(self) -> None:
        test_signed_generated_system_commits_through_full_consistency_validation()

    def test_tampered_compile_artifact_is_rejected_atomically(self) -> None:
        test_tampered_compile_artifact_is_rejected_atomically_by_full_validator()

    def test_generated_system_envelope_constraints_fail_closed(self) -> None:
        cases = [
            (_invalid_phase, "invalid system phase"),
            (_unknown_dependency, "unknown or forward dependencies"),
            (_mode_scope_without_mode, "mode system must set mode_id"),
            (_invalid_semver, "MAJOR.MINOR.PATCH"),
            (_duplicate_system, "already exists"),
        ]
        for mutator, expected in cases:
            with self.subTest(mutator=mutator.__name__):
                cgs = _base_cgs()
                batch = _batch(cgs)
                mutator(batch, cgs)
                with self.assertRaisesRegex(TypedOperationExecutionError, expected):
                    TypedOperationExecutor().execute(batch, cgs)

    def test_generated_behavior_abi_and_signature_basics_fail_closed(self) -> None:
        cases = [
            (_unsigned_executor, "missing fields"),
            (_behavior_executor_mismatch, "exactly match"),
            (_missing_rollback_hook, "missing fields"),
            (_behavior_component_not_written, "both reads and writes"),
            (_non_fixed_target, "exact type 'fixed'"),
            (_unknown_behavior_field, "is not declared"),
        ]
        for mutator, expected in cases:
            with self.subTest(mutator=mutator.__name__):
                cgs = _base_cgs()
                batch = _batch(cgs)
                mutator(batch, cgs)
                with self.assertRaisesRegex(TypedOperationExecutionError, expected):
                    TypedOperationExecutor().execute(batch, cgs)
