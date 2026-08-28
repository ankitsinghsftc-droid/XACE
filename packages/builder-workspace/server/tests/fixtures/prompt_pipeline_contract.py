"""
Test fixture for deterministic prompt pipeline contract scenarios.

These scenarios are used by launch-readiness tests and smoke certification to
prove that supported prompt categories travel through the real Builder apply route:

    pil_process -> pending transaction -> pil_apply -> GDE -> CGS save

They are intentionally general. They do not encode one demo game or one engine,
and they are not imported by production Builder code.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PromptMutationOp:
    path: str
    op: str
    value: Any
    type_hint: str = ""
    field_name: str = ""
    actor_id: str = ""
    type_id: int | str = ""

    def clone(self) -> "PromptMutationOp":
        return PromptMutationOp(
            path=self.path,
            op=self.op,
            value=copy.deepcopy(self.value),
            type_hint=self.type_hint,
            field_name=self.field_name,
            actor_id=self.actor_id,
            type_id=self.type_id,
        )


@dataclass(frozen=True)
class PromptMutationTransaction:
    operations: tuple[PromptMutationOp, ...]
    schema_delta_type: str
    confidence_score: float
    risk_level: str
    required_recompile: bool
    affected_systems: tuple[str, ...] = field(default_factory=tuple)
    mutation_summary: str = ""

    def clone(self) -> "PromptMutationTransaction":
        return PromptMutationTransaction(
            operations=tuple(op.clone() for op in self.operations),
            schema_delta_type=self.schema_delta_type,
            confidence_score=self.confidence_score,
            risk_level=self.risk_level,
            required_recompile=self.required_recompile,
            affected_systems=tuple(self.affected_systems),
            mutation_summary=self.mutation_summary,
        )


@dataclass(frozen=True)
class PromptTypedMutation:
    normalized_batch: dict[str, Any]
    parser_confidence: float = 1.0

    def clone(self) -> "PromptTypedMutation":
        return PromptTypedMutation(
            normalized_batch=copy.deepcopy(self.normalized_batch),
            parser_confidence=self.parser_confidence,
        )


@dataclass(frozen=True)
class PromptPipelineResult:
    kind: str
    turn_index: int
    intent_category: str
    confidence: float
    mode_profile_warnings: tuple[str, ...] = field(default_factory=tuple)
    auto_committed: bool = False
    diff_text: str = ""
    transaction: PromptMutationTransaction | None = None
    typed_mutation: PromptTypedMutation | None = None
    reason: str = ""
    guard: str = ""


@dataclass(frozen=True)
class PromptPipelineScenario:
    scenario_id: str
    category: str
    prompt: str
    result: PromptPipelineResult
    expected_path: str = ""
    expected_value: Any = None
    expected_actor_id: str = ""
    expected_component_type_id: int | None = None
    expects_execution_plan: bool = False


class DeterministicPromptPipeline:
    """Small PIL-compatible pipeline used by tests and smoke certification."""

    def __init__(self, scenarios: list[PromptPipelineScenario] | None = None) -> None:
        items = scenarios or all_prompt_pipeline_scenarios()
        self._by_prompt = {scenario.prompt.lower(): scenario for scenario in items}
        self._turn_index = 0

    def process(self, prompt: str, cgs: dict, cgs_hash: str, mode: str = "COLLABORATIVE") -> PromptPipelineResult:
        del cgs, cgs_hash, mode
        self._turn_index += 1
        scenario = self._by_prompt.get(prompt.lower())
        if scenario is None:
            return _blocked_result(
                self._turn_index,
                "This prompt is outside the deterministic supported prompt contract.",
            )

        result = scenario.result
        transaction = result.transaction.clone() if result.transaction is not None else None
        typed_mutation = (
            result.typed_mutation.clone()
            if result.typed_mutation is not None
            else None
        )
        return PromptPipelineResult(
            kind=result.kind,
            turn_index=self._turn_index,
            intent_category=result.intent_category,
            confidence=result.confidence,
            mode_profile_warnings=tuple(result.mode_profile_warnings),
            auto_committed=result.auto_committed,
            diff_text=result.diff_text,
            transaction=transaction,
            typed_mutation=typed_mutation,
            reason=result.reason,
            guard=result.guard,
        )


def supported_prompt_pipeline_scenarios() -> list[PromptPipelineScenario]:
    return [
        PromptPipelineScenario(
            scenario_id="value_player_speed",
            category="value_mutation",
            prompt="Set the player movement speed to 6.5.",
            expected_path="modes.mode_gameplay.actors.actor_player.components.5.defaults.max_linear_speed",
            expected_value=6.5,
            result=_mutation_result(
                PromptMutationTransaction(
                    operations=(
                        PromptMutationOp(
                            path="modes.mode_gameplay.actors.actor_player.components.5.defaults.max_linear_speed",
                            op="SET",
                            value=6.5,
                            type_hint="float",
                            field_name="max_linear_speed",
                            actor_id="actor_player",
                            type_id=5,
                        ),
                    ),
                    schema_delta_type="value_mutation",
                    confidence_score=0.99,
                    risk_level="low",
                    required_recompile=False,
                    affected_systems=("MovementSystem",),
                    mutation_summary="Set player movement speed to 6.5.",
                )
            ),
        ),
        PromptPipelineScenario(
            scenario_id="structural_add_inventory_component",
            category="structural_add_component",
            prompt="Add a general inventory component to the player.",
            expected_actor_id="actor_player",
            expected_component_type_id=10000,
            expects_execution_plan=True,
            result=_typed_mutation_result(
                PromptTypedMutation(
                    normalized_batch=_inventory_component_batch(),
                    parser_confidence=1.0,
                ),
                confidence=0.98,
            ),
        ),
        PromptPipelineScenario(
            scenario_id="structural_add_pickup_actor",
            category="structural_add_actor",
            prompt="Add one generic pickup object near the player.",
            expected_actor_id="actor_prompt_pickup",
            expects_execution_plan=True,
            result=_mutation_result(
                PromptMutationTransaction(
                    operations=(
                        PromptMutationOp(
                            path="modes.mode_gameplay.actors",
                            op="ADD_ACTOR",
                            value=_pickup_actor(),
                            type_hint="dict",
                            field_name="actors",
                            actor_id="actor_prompt_pickup",
                        ),
                    ),
                    schema_delta_type="structural_add",
                    confidence_score=0.98,
                    risk_level="low",
                    required_recompile=True,
                    affected_systems=("InteractionSystem", "InventorySystem"),
                    mutation_summary="Add one generic pickup object near the player.",
                )
            ),
        ),
    ]


def blocked_prompt_pipeline_scenario() -> PromptPipelineScenario:
    return PromptPipelineScenario(
        scenario_id="unsupported_arbitrary_full_game",
        category="unsupported_prompt",
        prompt="Create any complete online game with all art, audio, animation, servers, and stores.",
        result=_blocked_result(
            0,
            (
                "This request is too broad for a safe CGS mutation. Start with a "
                "specific gameplay, actor, system, asset-link, audio-link, or animation-link edit."
            ),
        ),
    )


def all_prompt_pipeline_scenarios() -> list[PromptPipelineScenario]:
    scenarios = supported_prompt_pipeline_scenarios()
    scenarios.append(blocked_prompt_pipeline_scenario())
    return scenarios


def _mutation_result(txn: PromptMutationTransaction) -> PromptPipelineResult:
    return PromptPipelineResult(
        kind="mutation",
        turn_index=0,
        intent_category="MutationRequest",
        confidence=txn.confidence_score,
        auto_committed=False,
        diff_text="",
        transaction=txn,
    )


def _typed_mutation_result(
    typed_mutation: PromptTypedMutation,
    *,
    confidence: float,
) -> PromptPipelineResult:
    return PromptPipelineResult(
        kind="mutation",
        turn_index=0,
        intent_category="MutationRequest",
        confidence=confidence,
        auto_committed=False,
        diff_text="",
        transaction=None,
        typed_mutation=typed_mutation,
    )


def _blocked_result(turn_index: int, reason: str) -> PromptPipelineResult:
    return PromptPipelineResult(
        kind="blocked",
        turn_index=turn_index,
        intent_category="MutationRequest",
        confidence=0.0,
        reason=reason,
        guard="prompt_pipeline_contract",
    )


def _component(type_id: int, name: str, defaults: dict[str, Any]) -> dict[str, Any]:
    return {"type_id": type_id, "name": name, "defaults": defaults}


def _inventory_component_batch() -> dict[str, Any]:
    return {
        "schema": "xace.typed_cgs_operation_batch.v1",
        "request_id": "request.prompt.inventory",
        "prompt_id": "prompt.add.inventory",
        "operations": [
            {
                "operation_id": "declare.prompt_inventory",
                "kind": "declare_component",
                "explanation": "Declare portable inventory state for the player.",
                "component_type_id": 10000,
                "component_name": "COMP_PROMPT_INVENTORY_V1",
                "version": "1.0.0",
                "fields": [
                    {
                        "name": "slots",
                        "field_type": "string_list",
                        "default": [],
                        "description": "Stable item identifiers in inventory order.",
                    },
                    {
                        "name": "max_capacity",
                        "field_type": "uint",
                        "default": 20,
                        "description": "Maximum item capacity.",
                    },
                    {
                        "name": "current_count",
                        "field_type": "uint",
                        "default": 0,
                        "description": "Current item count.",
                    },
                    {
                        "name": "equipped_slot_id",
                        "field_type": "string",
                        "default": "",
                        "description": "Equipped inventory slot identifier.",
                    },
                    {
                        "name": "equipped_item_entity_id",
                        "field_type": "entity_id",
                        "default": 0,
                        "description": "Equipped authoritative entity identifier.",
                    },
                ],
                "source": "generated",
            },
            {
                "operation_id": "attach.prompt_inventory",
                "kind": "add_component",
                "explanation": "Attach inventory state to the player.",
                "mode_id": "mode_gameplay",
                "actor_id": "actor_player",
                "component_type_id": 10000,
                "component_name": "COMP_PROMPT_INVENTORY_V1",
                "use_schema_defaults": True,
            },
        ],
        "summary": "Add a general inventory component to the player.",
    }


def _pickup_actor() -> dict[str, Any]:
    return {
        "id": "actor_prompt_pickup",
        "actor_type": "Item",
        "control_type": "WorldObject",
        "components": [
            _component(
                1,
                "COMP_TRANSFORM_V1",
                {
                    "position_x": 2.0,
                    "position_y": 0.0,
                    "position_z": 1.0,
                    "rotation_y": 0.0,
                },
            ),
            _component(
                2,
                "COMP_IDENTITY_V1",
                {
                    "name": "Prompt Pickup",
                    "mesh_id": "prompt_pickup_mesh",
                    "mesh_id_path": "",
                },
            ),
            _component(
                205,
                "COMP_ITEM_V1",
                {
                    "item_id": "prompt_pickup",
                    "display_name": "Prompt Pickup",
                    "quantity": 1,
                    "slot_type": "generic",
                    "weight": 1.0,
                    "is_pickable": True,
                    "owner_entity_id": 0,
                    "inventory_slot_id": "",
                    "is_equipped": False,
                    "is_in_world": True,
                },
            ),
            _component(
                260,
                "COMP_INTERACTION_V1",
                {
                    "is_interactable": True,
                    "interaction_type": "PickUp",
                    "prompt_text": "Pick up Prompt Pickup",
                    "range": 2.0,
                    "interaction_count": 0,
                    "max_interactions": 0,
                },
            ),
        ],
    }
