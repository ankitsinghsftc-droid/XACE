"""Focused producer/parser integration tests for X10-030."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


SRC = Path(__file__).resolve().parents[1]
for path in (
    SRC,
    SRC / "context_assembler",
    SRC / "llm_orchestrator",
    SRC / "output_parser",
):
    sys.path.insert(0, str(path))

from llm_context_packet import (  # noqa: E402
    AllowedMutationScope,
    LLMContextPacket,
    SimplifiedActor,
    SimplifiedSystem,
)
from pass1_planning import OutputParseError, ReasoningPlan  # noqa: E402
from pass2_dsl_draft import (  # noqa: E402
    TYPED_OPERATION_MUTATION_TYPES,
    Pass2DSLDraft,
    requires_typed_operations,
)
from pil_pipeline import PILPipeline  # noqa: E402
from structured_output_parser import ParseError, StructuredOutputParser  # noqa: E402
from typed_operations import (  # noqa: E402
    TYPED_OPERATION_BATCH_SCHEMA,
    apply_typed_operation_batch,
    normalized_typed_operation_batch,
    parse_typed_operation_batch,
    serialize_typed_operation_batch,
)


def _cgs() -> dict:
    return {
        "metadata": {
            "name": "Typed Boundary Test",
            "version": "0.1.0",
            "schema_version": "0.1.0",
        },
        "component_schemas": [
            {
                "type_id": 1,
                "name": "COMP_TRANSFORM_V1",
                "defaults": {"x": 0, "y": 0},
                "source": "ucl",
            },
            {
                "type_id": 5,
                "name": "COMP_VELOCITY_V1",
                "defaults": {"max_linear_speed": 1000000},
                "source": "ucl",
            },
        ],
        "global_systems": [
            {
                "id": "InputSystem",
                "phase": "Input",
                "reads": [5, 6],
                "writes": [5],
                "depends_on": [],
                "deterministic": True,
            }
        ],
        "semantic_events": [],
        "assets": [],
        "modes": [
            {
                "id": "mode_gameplay",
                "is_default": True,
                "actors": [
                    {
                        "id": "actor_player",
                        "actor_type": "PlayerCharacter",
                        "control_type": "Human",
                        "components": [
                            {
                                "type_id": 1,
                                "name": "COMP_TRANSFORM_V1",
                                "defaults": {"x": 0, "y": 0},
                            },
                            {
                                "type_id": 5,
                                "name": "COMP_VELOCITY_V1",
                                "defaults": {"max_linear_speed": 1000000},
                            },
                        ],
                    }
                ],
                "systems": [],
                "rules": [],
            }
        ],
    }


def _production_batch_payload() -> dict:
    return {
        "schema": TYPED_OPERATION_BATCH_SCHEMA,
        "request_id": "request.x10-030-production",
        "prompt_id": "pc030",
        "summary": "Add an energy slice and registered movement system.",
        "operations": [
            {
                "operation_id": "declare.energy",
                "kind": "declare_component",
                "explanation": "Declare deterministic fixed-point energy state.",
                "component_type_id": 10000,
                "component_name": "COMP_ENERGY_V1",
                "version": "1.0.0",
                "fields": [
                    {
                        "name": "current",
                        "field_type": "fixed",
                        "default": 1000000,
                    },
                    {
                        "name": "maximum",
                        "field_type": "fixed",
                        "default": 1000000,
                    },
                ],
            },
            {
                "operation_id": "attach.energy",
                "kind": "add_component",
                "explanation": "Attach energy state to the player.",
                "mode_id": "mode_gameplay",
                "actor_id": "actor_player",
                "component_type_id": 10000,
                "component_name": "COMP_ENERGY_V1",
                "defaults": [
                    {
                        "field_name": "current",
                        "field_type": "fixed",
                        "value": 750000,
                    }
                ],
                "use_schema_defaults": True,
            },
            {
                "operation_id": "add.movement",
                "kind": "add_system",
                "explanation": "Bind the registered deterministic movement runtime.",
                "system_id": "MovementSystem",
                "phase": "Simulation",
                "reads": [1, 5],
                "writes": [1],
                "depends_on": ["InputSystem"],
                "implementation_ref": "builtin.MovementSystem.v1",
            },
            {
                "operation_id": "add.energy_event",
                "kind": "add_event",
                "explanation": "Declare the energy depleted semantic event.",
                "event_name": "energy.depleted",
                "payload_fields": [
                    {
                        "name": "actor_entity_id",
                        "field_type": "entity_id",
                        "required": True,
                    }
                ],
            },
            {
                "operation_id": "add.energy_rule",
                "kind": "add_rule",
                "explanation": "Disable sprint when energy is depleted.",
                "mode_id": "mode_gameplay",
                "rule_id": "rule.energy_depleted",
                "condition": "energy.current <= 0",
                "effect": "movement.sprint_enabled = false",
                "priority": 20,
            },
            {
                "operation_id": "add.energy_asset",
                "kind": "add_asset",
                "explanation": "Reserve deterministic depleted feedback.",
                "asset_id": "energy_depleted_sfx_v1",
                "asset_type": "AUDIO_CLIP",
                "status": "PLACEHOLDER",
            },
            {
                "operation_id": "set.energy_maximum",
                "kind": "set_defaults",
                "explanation": "Set the player's initial maximum energy.",
                "mode_id": "mode_gameplay",
                "actor_id": "actor_player",
                "component_type_id": 10000,
                "assignments": [
                    {
                        "field_name": "maximum",
                        "field_type": "fixed",
                        "value": 1250000,
                    }
                ],
            },
        ],
    }


def _system_plan() -> ReasoningPlan:
    return ReasoningPlan(
        target_entities=["MovementSystem"],
        intended_mutation_type="system_add",
        component_targets=[],
        risk_assessment="medium",
        reasoning="Add registered movement execution.",
        requires_recompile=True,
    )


def _packet() -> LLMContextPacket:
    cgs = _cgs()
    actor = cgs["modes"][0]["actors"][0]
    system = cgs["global_systems"][0]
    return LLMContextPacket(
        intent_category="AddFeature",
        normalized_prompt="add the registered movement system",
        assistance_mode="ARCHITECT_MODE",
        game_metadata={"name": "Typed Boundary Test", "version": "0.1.0"},
        relevant_actors=(
            SimplifiedActor(
                actor_id=actor["id"],
                actor_type=actor["actor_type"],
                control_type=actor["control_type"],
                components=tuple(actor["components"]),
                mode_id="mode_gameplay",
            ),
        ),
        relevant_systems=(
            SimplifiedSystem(
                system_id=system["id"],
                phase=system["phase"],
                reads=tuple(system["reads"]),
                writes=tuple(system["writes"]),
                depends_on=tuple(system["depends_on"]),
                deterministic=True,
            ),
        ),
        constraints=("All systems must be deterministic.",),
        allowed_scope=AllowedMutationScope(
            allowed_paths=(),
            forbidden_paths=("metadata.cgs_hash",),
            structural_change_allowed=True,
            max_mutation_depth=5,
            mode="ARCHITECT_MODE",
        ),
        simplified_schema=cgs,
    )


class _TypedSystemAdapter:
    def __init__(self, *, legacy_payload: bool = False) -> None:
        self.legacy_payload = legacy_payload
        self.calls: list[object] = []

    def call(self, request: object) -> SimpleNamespace:
        self.calls.append(request)
        if self.legacy_payload:
            return SimpleNamespace(text=json.dumps({
                "schema_delta_type": "structural_add",
                "operations": [
                    {
                        "path": "global_systems",
                        "op": "ADD_SYSTEM",
                        "value": {"id": "MovementSystem"},
                    }
                ],
            }))
        contract = request.structured_output
        request_id = contract.schema["properties"]["request_id"]["const"]
        prompt_id = contract.schema["properties"]["prompt_id"]["const"]
        return SimpleNamespace(text=json.dumps({
            "schema": TYPED_OPERATION_BATCH_SCHEMA,
            "request_id": request_id,
            "prompt_id": prompt_id,
            "summary": "Add the registered movement system.",
            "operations": [
                {
                    "operation_id": "add.movement",
                    "kind": "add_system",
                    "explanation": "Use the registered deterministic movement runtime.",
                    "system_id": "MovementSystem",
                    "phase": "Simulation",
                    "reads": [1, 5],
                    "writes": [1],
                    "depends_on": ["InputSystem"],
                    "implementation_ref": "builtin.MovementSystem.v1",
                }
            ],
        }))


class _TypedGeneratedSystemAdapter:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def call(self, request: object) -> SimpleNamespace:
        self.calls.append(request)
        contract = request.structured_output
        request_id = contract.schema["properties"]["request_id"]["const"]
        prompt_id = contract.schema["properties"]["prompt_id"]["const"]
        return SimpleNamespace(text=json.dumps({
            "schema": TYPED_OPERATION_BATCH_SCHEMA,
            "request_id": request_id,
            "prompt_id": prompt_id,
            "summary": "Add a deterministic generated speed system.",
            "operations": [
                {
                    "operation_id": "add.generated.speed",
                    "kind": "add_generated_system",
                    "explanation": (
                        "Increment the fixed-point speed field once per tick."
                    ),
                    "system_id": "GeneratedSpeedSystem",
                    "phase": "Simulation",
                    "reads": [5],
                    "writes": [5],
                    "depends_on": [],
                    "behavior": {
                        "kind": "increment_numeric_field",
                        "component_type_id": 5,
                        "field": "max_linear_speed",
                        "amount": 1,
                    },
                    "scope": "global",
                    "mode_id": "",
                    "version": "1.0.0",
                    "deterministic": True,
                    "parallel": False,
                }
            ],
        }))


class _TypedCompositeFeatureAdapter:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def call(self, request: object) -> SimpleNamespace:
        self.calls.append(request)
        contract = request.structured_output
        request_id = contract.schema["properties"]["request_id"]["const"]
        prompt_id = contract.schema["properties"]["prompt_id"]["const"]
        return SimpleNamespace(text=json.dumps({
            "schema": TYPED_OPERATION_BATCH_SCHEMA,
            "request_id": request_id,
            "prompt_id": prompt_id,
            "summary": "Add a composite movement slice.",
            "operations": [
                {
                    "operation_id": "attach.save_policy",
                    "kind": "add_component",
                    "explanation": "Attach save policy state.",
                    "mode_id": "mode_gameplay",
                    "actor_id": "actor_player",
                    "component_type_id": 232,
                    "component_name": "COMP_PERSISTENCE_V1",
                    "defaults": [],
                    "use_schema_defaults": True,
                },
                {
                    "operation_id": "attach.network_policy",
                    "kind": "add_component",
                    "explanation": "Attach network replication state.",
                    "mode_id": "mode_gameplay",
                    "actor_id": "actor_player",
                    "component_type_id": 320,
                    "component_name": "COMP_REPLICATION_V1",
                    "defaults": [],
                    "use_schema_defaults": True,
                },
                {
                    "operation_id": "system.intent",
                    "kind": "add_system",
                    "explanation": "Bind movement intent execution.",
                    "system_id": "MovementIntentSystem",
                    "phase": "Input",
                    "reads": [6, 120],
                    "writes": [120],
                    "depends_on": [],
                    "implementation_ref": "builtin.MovementIntentSystem.v1",
                    "scope": "global",
                    "mode_id": "",
                    "version": "1.0.0",
                    "deterministic": True,
                    "parallel": False,
                },
                {
                    "operation_id": "system.platformer",
                    "kind": "add_system",
                    "explanation": "Bind platformer movement execution.",
                    "system_id": "PlatformerMotionSystem",
                    "phase": "Simulation",
                    "reads": [5, 120, 125],
                    "writes": [5, 125],
                    "depends_on": ["MovementIntentSystem"],
                    "implementation_ref": "builtin.PlatformerMotionSystem.v1",
                    "scope": "global",
                    "mode_id": "",
                    "version": "1.0.0",
                    "deterministic": True,
                    "parallel": False,
                },
                {
                    "operation_id": "asset.jump",
                    "kind": "add_asset",
                    "explanation": "Reserve jump feedback.",
                    "asset_id": "jump_audio_v1",
                    "asset_type": "AUDIO_CLIP",
                    "status": "PLACEHOLDER",
                    "source": "",
                },
            ],
        }))


class _NoCallAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def call(self, request: object) -> SimpleNamespace:
        self.calls += 1
        raise AssertionError("adapter must not be called")


class _LiveTypedPipelineAdapter:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def call(self, request: object) -> SimpleNamespace:
        self.calls.append(request)
        if request.call_label == "pass1_planning":
            return SimpleNamespace(text=json.dumps({
                "target_entities": ["MovementSystem"],
                "intended_mutation_type": "system_add",
                "component_targets": [],
                "risk_assessment": "medium",
                "reasoning": "Add the registered movement runtime.",
                "requires_recompile": True,
            }))
        if (
            request.call_label == "pass2_dsl_draft"
            and request.structured_output is not None
        ):
            schema = request.structured_output.schema
            return SimpleNamespace(text=json.dumps({
                "schema": TYPED_OPERATION_BATCH_SCHEMA,
                "request_id": schema["properties"]["request_id"]["const"],
                "prompt_id": schema["properties"]["prompt_id"]["const"],
                "summary": "Add the registered movement system.",
                "operations": [
                    {
                        "operation_id": "add.movement",
                        "kind": "add_system",
                        "explanation": "Bind the registered deterministic runtime.",
                        "system_id": "MovementSystem",
                        "phase": "Simulation",
                        "reads": [1, 5],
                        "writes": [1],
                        "depends_on": ["InputSystem"],
                        "implementation_ref": "builtin.MovementSystem.v1",
                    }
                ],
            }))
        raise AssertionError(f"unexpected live pipeline call {request.call_label!r}")


class TestTypedOperationBoundary(unittest.TestCase):
    def test_all_task30_add_plan_kinds_route_to_typed_operations(self) -> None:
        self.assertEqual(
            TYPED_OPERATION_MUTATION_TYPES,
            {
                "component_add",
                "system_add",
                "rule_add",
                "event_add",
                "asset_add",
                "component_schema_add",
                "defaults_set",
                "composite_feature_add",
            },
        )
        for kind in sorted(TYPED_OPERATION_MUTATION_TYPES):
            with self.subTest(kind=kind):
                plan = ReasoningPlan(
                    target_entities=["target"],
                    intended_mutation_type=kind,
                    risk_assessment="low",
                )
                self.assertTrue(plan.is_valid())
                self.assertTrue(requires_typed_operations(plan))

    def test_normalized_serializer_is_deterministic_and_path_free(self) -> None:
        batch = parse_typed_operation_batch(_production_batch_payload())
        normalized = normalized_typed_operation_batch(batch)
        serialized = serialize_typed_operation_batch(batch)

        self.assertEqual(parse_typed_operation_batch(serialized), batch)
        self.assertEqual(serialized, serialize_typed_operation_batch(batch))
        self.assertEqual(
            normalized["operations"][2]["implementation_ref"],
            "builtin.MovementSystem.v1",
        )
        for operation in normalized["operations"]:
            self.assertNotIn("path", operation)
            self.assertNotIn("op", operation)

    def test_parser_returns_validated_deep_copied_proposed_cgs(self) -> None:
        current = _cgs()
        raw = json.dumps(_production_batch_payload())

        canonical = StructuredOutputParser().parse_typed(raw, current)

        self.assertTrue(canonical.is_fully_valid, canonical.validation.errors)
        self.assertIsNot(canonical.proposed_cgs, current)
        self.assertEqual(len(current["component_schemas"]), 2)
        self.assertEqual(len(canonical.proposed_cgs["component_schemas"]), 3)
        energy_schema = canonical.proposed_cgs["component_schemas"][-1]
        self.assertEqual(energy_schema["version"], "1.0.0")
        self.assertEqual(
            energy_schema["fields"][0],
            {
                "name": "current",
                "field_type": "fixed",
                "default": 1000000,
                "description": "",
            },
        )
        actor = canonical.proposed_cgs["modes"][0]["actors"][0]
        energy = next(c for c in actor["components"] if c["type_id"] == 10000)
        self.assertEqual(energy["defaults"]["current"], 750000)
        self.assertEqual(energy["defaults"]["maximum"], 1250000)
        movement = canonical.proposed_cgs["global_systems"][-1]
        self.assertEqual(movement["id"], "MovementSystem")
        self.assertEqual(movement["reads"], [1, 5])
        self.assertEqual(movement["writes"], [1])
        self.assertEqual(
            canonical.normalized_batch["operations"][2]["implementation_ref"],
            "builtin.MovementSystem.v1",
        )

    def test_unknown_system_executor_is_grammar_valid_but_cgs_invalid(self) -> None:
        payload = _production_batch_payload()
        system = payload["operations"][2]
        system.update({
            "system_id": "StaminaSystem",
            "reads": [6, 10000],
            "writes": [10000],
            "implementation_ref": "builtin.StaminaSystem.v1",
        })
        batch = parse_typed_operation_batch(payload)

        result = apply_typed_operation_batch(batch, _cgs())

        self.assertFalse(result.validation.valid)
        self.assertIsNone(result.proposed_cgs)
        self.assertIn(
            "unregistered runtime implementation",
            " ".join(result.validation.errors),
        )

    def test_parser_rejects_all_legacy_structural_delta_envelopes(self) -> None:
        parser = StructuredOutputParser()
        for delta in ("structural_add", "structural_remove", "rule_change"):
            with self.subTest(delta=delta):
                raw = json.dumps({
                    "schema_delta_type": delta,
                    "operations": [
                        {
                            "path": "modes[mode_gameplay].rules[rule.new]",
                            "op": "ADD_RULE",
                            "value": {"id": "rule.new"},
                            "type_hint": "dict",
                        }
                    ],
                })
                with self.assertRaisesRegex(
                    ParseError, "Legacy path/op/value structural mutations"
                ):
                    parser.parse(raw, _cgs())

    def test_parser_rejects_structural_op_disguised_as_value_mutation(self) -> None:
        raw = json.dumps({
            "schema_delta_type": "value_mutation",
            "operations": [
                {
                    "path": "modes[mode_gameplay].actors[actor_player].components",
                    "op": "ADD_COMPONENT",
                    "value": {"type_id": 10000},
                    "type_hint": "dict",
                }
            ],
        })
        with self.assertRaisesRegex(ParseError, "SET and SCALE only"):
            StructuredOutputParser().parse(raw, _cgs())

    def test_legacy_scalar_value_mutation_remains_compatible(self) -> None:
        raw = json.dumps({
            "schema_delta_type": "value_mutation",
            "confidence": 1.0,
            "operations": [
                {
                    "path": (
                        "modes[mode_gameplay].actors[actor_player]."
                        "components[5].defaults.max_linear_speed"
                    ),
                    "op": "SET",
                    "value": 1100000,
                    "type_hint": "int",
                    "field_name": "max_linear_speed",
                    "actor_id": "actor_player",
                    "type_id": 5,
                }
            ],
        })
        canonical = StructuredOutputParser().parse(raw, _cgs())
        self.assertTrue(canonical.is_fully_valid)

    def test_typed_producer_requests_schema_and_parses_provider_output(self) -> None:
        adapter = _TypedSystemAdapter()

        batch = Pass2DSLDraft(adapter).run_typed(
            _packet(), _system_plan(), prompt_id="pc030"
        )

        self.assertEqual(batch.operations[0].system_id, "MovementSystem")
        self.assertEqual(
            batch.operations[0].implementation_ref,
            "builtin.MovementSystem.v1",
        )
        request = adapter.calls[0]
        self.assertTrue(request.structured_output.strict)
        self.assertEqual(
            request.structured_output.schema_id,
            TYPED_OPERATION_BATCH_SCHEMA,
        )
        self.assertEqual(
            request.structured_output.schema["properties"]["prompt_id"]["const"],
            "pc030",
        )

    def test_system_add_plan_accepts_generated_system_provider_kind(self) -> None:
        adapter = _TypedGeneratedSystemAdapter()

        batch = Pass2DSLDraft(adapter).run_typed(
            _packet(), _system_plan(), prompt_id="pc031"
        )

        operation = batch.operations[0]
        self.assertEqual(operation.kind.value, "add_generated_system")
        self.assertEqual(operation.system_id, "GeneratedSpeedSystem")
        self.assertEqual(operation.behavior.field, "max_linear_speed")
        self.assertIsNone(operation.runtime_executor)

        contract = adapter.calls[0].structured_output
        variants = contract.schema["properties"]["operations"]["items"]["anyOf"]
        generated_variant = next(
            variant
            for variant in variants
            if variant["properties"]["kind"].get("const")
            == "add_generated_system"
        )
        self.assertIn("behavior", generated_variant["properties"])
        self.assertNotIn("runtime_executor", generated_variant["properties"])
        self.assertFalse(
            generated_variant["properties"]["behavior"]["additionalProperties"]
        )

    def test_composite_feature_plan_requires_full_typed_facets(self) -> None:
        adapter = _TypedCompositeFeatureAdapter()
        plan = ReasoningPlan(
            target_entities=["MovementIntentSystem", "PlatformerMotionSystem"],
            intended_mutation_type="composite_feature_add",
            component_targets=[],
            risk_assessment="medium",
            reasoning="Add a multi-system movement slice.",
            requires_recompile=True,
        )

        batch = Pass2DSLDraft(adapter).run_typed(
            _packet(), plan, prompt_id="pc032"
        )

        self.assertEqual(len(batch.operations), 5)
        self.assertEqual(batch.operations[0].kind.value, "add_component")
        self.assertEqual(batch.operations[2].system_id, "MovementIntentSystem")
        self.assertEqual(batch.operations[3].depends_on, ("MovementIntentSystem",))
        self.assertEqual(adapter.calls[0].call_label, "pass2_dsl_draft")

    def test_typed_producer_rejects_ad_hoc_path_value_provider_output(self) -> None:
        adapter = _TypedSystemAdapter(legacy_payload=True)
        with self.assertRaisesRegex(OutputParseError, "typed operation validation"):
            Pass2DSLDraft(adapter).run_typed(
                _packet(), _system_plan(), prompt_id="pc030"
            )

    def test_legacy_producer_refuses_typed_add_plan_before_provider_call(self) -> None:
        adapter = _NoCallAdapter()
        with self.assertRaisesRegex(OutputParseError, "must use run_typed"):
            Pass2DSLDraft(adapter).run(_packet(), _system_plan())
        self.assertEqual(adapter.calls, 0)

    def test_live_pil_dispatch_carries_typed_mutation_without_legacy_transaction(
        self,
    ) -> None:
        adapter = _LiveTypedPipelineAdapter()
        current = _cgs()

        result = PILPipeline(
            adapter,
            session_id="typed-boundary",
        ).process(
            prompt="add the registered MovementSystem",
            cgs=current,
            mode="ARCHITECT_MODE",
        )

        self.assertEqual(result.kind, "mutation", result.reason)
        self.assertIsNone(result.transaction)
        self.assertIsNotNone(result.typed_mutation)
        self.assertTrue(result.typed_mutation.is_fully_valid)
        self.assertEqual(
            result.typed_mutation.normalized_batch["operations"][0][
                "implementation_ref"
            ],
            "builtin.MovementSystem.v1",
        )
        self.assertEqual(
            result.typed_mutation.proposed_cgs["global_systems"][-1]["id"],
            "MovementSystem",
        )
        self.assertFalse(result.auto_committed)
        self.assertEqual(
            [request.call_label for request in adapter.calls],
            ["pass1_planning", "pass2_dsl_draft"],
        )


if __name__ == "__main__":
    unittest.main()
