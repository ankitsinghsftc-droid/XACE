"""X10-030 atomic GDE tests for path-free typed CGS operation batches."""

from __future__ import annotations

import copy

from ..cgs.cgs_serializer import CGSSerializer
from ..domain_dsl.mutation_metadata.mutation_metadata_model import MutationMetadata
from ..gde_orchestrator import GDEOrchestrator


def _base_cgs() -> dict:
    cgs = {
        "format": "xace.cgs.export",
        "format_version": "1.0.0",
        "metadata": {
            "name": "Typed operation proof",
            "version": "0.1.0",
            "schema_version": "0.1.0",
            "execution_plan_version": 1,
        },
        "component_schemas": [
            {
                "type_id": 1,
                "name": "COMP_TRANSFORM_V1",
                "defaults": {"x": 0, "y": 0, "z": 0},
                "source": "ucl",
            },
            {
                "type_id": 5,
                "name": "COMP_VELOCITY_V1",
                "defaults": {"x": 0, "y": 0, "z": 0},
                "source": "ucl",
            },
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
                        "id": "actor_player",
                        "spawn_count": 1,
                        "components": [
                            {"type_id": 1, "name": "COMP_TRANSFORM_V1", "defaults": {"x": 0, "y": 0, "z": 0}},
                            {"type_id": 5, "name": "COMP_VELOCITY_V1", "defaults": {"x": 0, "y": 0, "z": 0}},
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


def _batch() -> dict:
    return {
        "schema": "xace.typed_cgs_operation_batch.v1",
        "request_id": "request.task30",
        "prompt_id": "prompt.task30",
        "summary": "Add a typed stamina feature",
        "operations": [
            {
                "operation_id": "op.declare.stamina",
                "kind": "declare_component",
                "explanation": "Declare deterministic stamina state.",
                "component_type_id": 10000,
                "component_name": "COMP_STAMINA_V1",
                "version": "1.0.0",
                "fields": [
                    {"name": "current", "field_type": "int", "default": 100},
                    {"name": "maximum", "field_type": "int", "default": 100},
                ],
            },
            {
                "operation_id": "op.attach.stamina",
                "kind": "add_component",
                "explanation": "Attach stamina to the player.",
                "mode_id": "mode_gameplay",
                "actor_id": "actor_player",
                "component_type_id": 10000,
                "component_name": "COMP_STAMINA_V1",
                "defaults": [],
                "use_schema_defaults": True,
            },
            {
                "operation_id": "op.defaults.stamina",
                "kind": "set_defaults",
                "explanation": "Tune the starting stamina.",
                "mode_id": "mode_gameplay",
                "actor_id": "actor_player",
                "component_type_id": 10000,
                "assignments": [
                    {"field_name": "current", "field_type": "int", "value": 80}
                ],
            },
            {
                "operation_id": "op.system.movement",
                "kind": "add_system",
                "explanation": "Use the registered movement executor.",
                "system_id": "MovementSystem",
                "phase": "Simulation",
                "reads": [1, 5],
                "writes": [1],
                "depends_on": [],
                "implementation_ref": "builtin.MovementSystem.v1",
                "scope": "global",
                "version": "1.0.0",
                "deterministic": True,
                "parallel": False,
            },
            {
                "operation_id": "op.event.stamina",
                "kind": "add_event",
                "explanation": "Declare the stamina depleted event.",
                "event_name": "stamina.depleted",
                "payload_fields": [
                    {"name": "actor_entity_id", "field_type": "entity_id", "required": True}
                ],
                "version": "1.0.0",
            },
            {
                "operation_id": "op.rule.stamina",
                "kind": "add_rule",
                "explanation": "Disable sprint when stamina is empty.",
                "mode_id": "mode_gameplay",
                "rule_id": "rule.stamina.sprint",
                "condition": "stamina.current == 0",
                "effect": "movement.sprint = false",
                "priority": 10,
                "is_active": True,
            },
            {
                "operation_id": "op.asset.stamina",
                "kind": "add_asset",
                "explanation": "Create a placeholder stamina icon.",
                "asset_id": "asset.stamina.icon",
                "asset_type": "TEXTURE",
                "status": "PLACEHOLDER",
            },
        ],
    }


def _metadata(orchestrator: GDEOrchestrator, parent_hash: str | None = None) -> MutationMetadata:
    return MutationMetadata.create(
        source="prompt",
        parent_cgs_hash=parent_hash or orchestrator.current_hash,
        schema_version_target="0.1.0",
        prompt_text="add stamina",
        confidence=0.99,
        description="Add typed stamina feature",
        risk_level="medium",
        session_id="task30-test",
    )


def test_all_typed_families_commit_atomically_and_rollback() -> None:
    orchestrator = GDEOrchestrator(session_id="task30-test")
    before = _base_cgs()
    orchestrator.load_cgs(before)
    before_hash = orchestrator.current_hash

    result = orchestrator.process_typed_operation_batch(_batch(), _metadata(orchestrator))

    assert result.success, result.error
    assert result.typed_operation_kinds == (
        "declare_component", "add_component", "set_defaults", "add_system",
        "add_event", "add_rule", "add_asset",
    )
    assert len(result.typed_operation_batch_hash) == 64
    assert orchestrator.current_cgs["metadata"]["version"] == "0.2.0"
    assert orchestrator.current_cgs["modes"][0]["actors"][0]["components"][2]["defaults"] == {
        "current": 80,
        "maximum": 100,
    }
    assert orchestrator.current_cgs["global_systems"][0]["id"] == "MovementSystem"
    assert orchestrator.current_cgs["semantic_events"][0]["name"] == "stamina.depleted"
    assert orchestrator.current_cgs["modes"][0]["rules"][0]["id"] == "rule.stamina.sprint"
    assert orchestrator.current_cgs["assets"][0]["id"] == "asset.stamina.icon"

    orchestrator._cgs_manager.rollback_to_hash(before_hash, before)
    assert orchestrator.current_hash == before_hash
    assert orchestrator.current_cgs == before


def test_mid_batch_failure_leaves_authoritative_cgs_unchanged() -> None:
    orchestrator = GDEOrchestrator(session_id="task30-test")
    orchestrator.load_cgs(_base_cgs())
    before = orchestrator.current_cgs
    before_hash = orchestrator.current_hash
    bad = _batch()
    bad["operations"][-1]["asset_id"] = "../outside"

    result = orchestrator.process_typed_operation_batch(bad, _metadata(orchestrator))

    assert not result.success
    assert orchestrator.current_hash == before_hash
    assert orchestrator.current_cgs == before


def test_stale_typed_batch_is_rejected_after_validation_without_commit() -> None:
    orchestrator = GDEOrchestrator(session_id="task30-test")
    orchestrator.load_cgs(_base_cgs())
    before = orchestrator.current_cgs

    result = orchestrator.process_typed_operation_batch(
        _batch(), _metadata(orchestrator, parent_hash="0" * 64)
    )

    assert not result.success
    assert "Stale mutation" in result.error
    assert orchestrator.current_cgs == before


def test_unknown_runtime_implementation_is_rejected_without_commit() -> None:
    orchestrator = GDEOrchestrator(session_id="task30-test")
    orchestrator.load_cgs(_base_cgs())
    before_hash = orchestrator.current_hash
    bad = _batch()
    system = bad["operations"][3]
    system["system_id"] = "StaminaSystem"
    system["implementation_ref"] = "builtin.StaminaSystem.v1"

    result = orchestrator.process_typed_operation_batch(bad, _metadata(orchestrator))

    assert not result.success
    assert "X10-031" in result.error
    assert orchestrator.current_hash == before_hash


def test_gde_rejects_every_numeric_assignment_type_interchange_atomically() -> None:
    numeric_types = ("fixed", "int", "uint", "entity_id")
    for expected in numeric_types:
        for declared in numeric_types:
            if declared == expected:
                continue
            orchestrator = GDEOrchestrator(session_id="task30-type-test")
            orchestrator.load_cgs(_base_cgs())
            before = orchestrator.current_cgs
            before_hash = orchestrator.current_hash
            bad = _batch()
            field = bad["operations"][0]["fields"][0]
            field["field_type"] = expected
            field["default"] = 1
            bad["operations"][1]["defaults"] = [
                {
                    "field_name": "current",
                    "field_type": declared,
                    "value": 1,
                }
            ]

            result = orchestrator.process_typed_operation_batch(
                bad, _metadata(orchestrator)
            )

            assert not result.success, (expected, declared)
            assert "does not match schema type" in result.error
            assert orchestrator.current_hash == before_hash
            assert orchestrator.current_cgs == before


def test_gde_rejects_negative_uint_and_entity_id_values_atomically() -> None:
    for field_type in ("uint", "entity_id"):
        orchestrator = GDEOrchestrator(session_id="task30-sign-test")
        orchestrator.load_cgs(_base_cgs())
        before = orchestrator.current_cgs
        before_hash = orchestrator.current_hash
        bad = _batch()
        field = bad["operations"][0]["fields"][0]
        field["field_type"] = field_type
        field["default"] = 0
        bad["operations"][1]["defaults"] = [
            {
                "field_name": "current",
                "field_type": field_type,
                "value": -1,
            }
        ]

        result = orchestrator.process_typed_operation_batch(
            bad, _metadata(orchestrator)
        )

        assert not result.success, field_type
        assert "does not match type" in result.error
        assert orchestrator.current_hash == before_hash
        assert orchestrator.current_cgs == before


def test_gde_set_defaults_uses_exact_schema_type_metadata_atomically() -> None:
    orchestrator = GDEOrchestrator(session_id="task30-default-type-test")
    orchestrator.load_cgs(_base_cgs())
    before = orchestrator.current_cgs
    before_hash = orchestrator.current_hash
    bad = _batch()
    bad["operations"][2]["assignments"][0]["field_type"] = "uint"

    result = orchestrator.process_typed_operation_batch(
        bad, _metadata(orchestrator)
    )

    assert not result.success
    assert "does not match schema type" in result.error
    assert orchestrator.current_hash == before_hash
    assert orchestrator.current_cgs == before


def test_gde_existing_attachment_requires_explicit_exact_schema_metadata() -> None:
    attachment = copy.deepcopy(_batch()["operations"][1])
    attachment["component_type_id"] = 201
    attachment["component_name"] = "COMP_INVENTORY_V1"
    attachment["defaults"] = []
    wire_batch = _batch()
    wire_batch["operations"] = [attachment]

    missing_schema = GDEOrchestrator(session_id="task30-schema-test")
    missing_schema.load_cgs(_base_cgs())
    before_hash = missing_schema.current_hash
    result = missing_schema.process_typed_operation_batch(
        wire_batch, _metadata(missing_schema)
    )
    assert not result.success
    assert "component type 201 is not declared" in result.error
    assert missing_schema.current_hash == before_hash

    missing_types_cgs = _base_cgs()
    missing_types_cgs["component_schemas"].append(
        {
            "type_id": 201,
            "name": "COMP_INVENTORY_V1",
            "defaults": {"max_capacity": 10},
            "source": "dcl.rpg",
        }
    )
    missing_types = GDEOrchestrator(session_id="task30-schema-test")
    missing_types.load_cgs(missing_types_cgs)
    before_hash = missing_types.current_hash
    result = missing_types.process_typed_operation_batch(
        wire_batch, _metadata(missing_types)
    )
    assert not result.success
    assert "exact field type metadata" in result.error
    assert missing_types.current_hash == before_hash

    negative_schema_cgs = _base_cgs()
    negative_schema_cgs["component_schemas"].append(
        {
            "type_id": 201,
            "name": "COMP_INVENTORY_V1",
            "fields": [
                {
                    "name": "max_capacity",
                    "field_type": "uint",
                    "default": -1,
                }
            ],
            "defaults": {"max_capacity": -1},
            "source": "dcl.rpg",
        }
    )
    negative_schema = GDEOrchestrator(session_id="task30-schema-test")
    negative_schema.load_cgs(negative_schema_cgs)
    before_hash = negative_schema.current_hash
    result = negative_schema.process_typed_operation_batch(
        wire_batch, _metadata(negative_schema)
    )
    assert not result.success
    assert "does not match type 'uint'" in result.error
    assert negative_schema.current_hash == before_hash
