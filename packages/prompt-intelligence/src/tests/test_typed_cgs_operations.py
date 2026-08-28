"""Focused contract tests for X10-030's typed-operation first tranche."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC))
INFERENCE_SRC = SRC.parents[1] / "inference" / "src"
sys.path.insert(0, str(INFERENCE_SRC))

from structured_output import (  # noqa: E402
    StructuredOutputContract,
    validate_structured_output_text,
)

from typed_operations import (  # noqa: E402
    OPERATION_REGISTRY,
    OperationKind,
    TypedOperationError,
    apply_typed_operation_batch,
    build_composite_prompt_plan,
    compile_typed_operation_batch,
    composite_plan_has_required_facets,
    normalized_typed_operation_batch,
    parse_typed_operation_batch,
    typed_operation_batch_json_schema,
    validate_composite_prompt_plan,
)


_OPENAI_STRICT_SCHEMA_KEYWORDS = frozenset({
    "type",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "minItems",
    "maxItems",
    "minLength",
    "maxLength",
    "pattern",
    "format",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "enum",
    "const",
    "anyOf",
    "description",
    "$defs",
    "$ref",
})


def _full_batch() -> dict:
    return {
        "schema": "xace.typed_cgs_operation_batch.v1",
        "request_id": "request.x10-030",
        "prompt_id": "pc002",
        "summary": "Add a typed stamina gameplay slice.",
        "operations": [
            {
                "operation_id": "declare.stamina",
                "kind": "declare_component",
                "explanation": "Declare authoritative fixed-point stamina state.",
                "component_type_id": 10000,
                "component_name": "COMP_STAMINA_V1",
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
                "operation_id": "attach.stamina",
                "kind": "add_component",
                "explanation": "Attach stamina to the player actor.",
                "mode_id": "mode_gameplay",
                "actor_id": "actor_player",
                "component_type_id": 10000,
                "component_name": "COMP_STAMINA_V1",
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
                "operation_id": "add.stamina_system",
                "kind": "add_system",
                "explanation": "Run the registered deterministic stamina executor.",
                "system_id": "StaminaSystem",
                "phase": "Simulation",
                "reads": [6, 10000],
                "writes": [10000],
                "depends_on": [],
                "implementation_ref": "builtin.StaminaSystem.v1",
            },
            {
                "operation_id": "add.stamina_event",
                "kind": "add_event",
                "explanation": "Declare the stamina depleted semantic event.",
                "event_name": "stamina.depleted",
                "payload_fields": [
                    {
                        "name": "actor_entity_id",
                        "field_type": "entity_id",
                        "required": True,
                    }
                ],
            },
            {
                "operation_id": "add.stamina_rule",
                "kind": "add_rule",
                "explanation": "Disable sprint when stamina is depleted.",
                "mode_id": "mode_gameplay",
                "rule_id": "rule.stamina_depleted",
                "condition": "stamina.current <= 0",
                "effect": "movement.sprint_enabled = false",
                "priority": 20,
            },
            {
                "operation_id": "add.stamina_asset",
                "kind": "add_asset",
                "explanation": "Reserve a placeholder for depleted feedback.",
                "asset_id": "stamina_depleted_sfx_v1",
                "asset_type": "AUDIO_CLIP",
                "status": "PLACEHOLDER",
            },
            {
                "operation_id": "set.stamina_defaults",
                "kind": "set_defaults",
                "explanation": "Set the player's initial stamina maximum.",
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


def _existing_attachment_payload(
    *,
    field_type: str = "uint",
    value: int = 10,
    include_assignment: bool = True,
) -> dict:
    defaults = []
    if include_assignment:
        defaults.append(
            {
                "field_name": "max_capacity",
                "field_type": field_type,
                "value": value,
            }
        )
    return {
        "schema": "xace.typed_cgs_operation_batch.v1",
        "request_id": "request.existing",
        "prompt_id": "prompt.existing",
        "summary": "Attach one existing component through its exact schema.",
        "operations": [
            {
                "operation_id": "attach.inventory",
                "kind": "add_component",
                "explanation": "Attach the registered inventory component.",
                "mode_id": "mode_gameplay",
                "actor_id": "actor_player",
                "component_type_id": 201,
                "component_name": "COMP_INVENTORY_V1",
                "defaults": defaults,
                "use_schema_defaults": True,
            }
        ],
    }


def _existing_attachment_cgs(
    *,
    include_schema: bool = True,
    include_fields: bool = True,
    field_type: str = "uint",
    default: int = 10,
) -> dict:
    schemas = []
    if include_schema:
        schema = {
            "type_id": 201,
            "name": "COMP_INVENTORY_V1",
            "defaults": {"max_capacity": default},
            "source": "dcl.rpg",
        }
        if include_fields:
            schema["fields"] = [
                {
                    "name": "max_capacity",
                    "field_type": field_type,
                    "default": default,
                }
            ]
        schemas.append(schema)
    return {
        "component_schemas": schemas,
        "global_systems": [],
        "modes": [
            {
                "id": "mode_gameplay",
                "actors": [{"id": "actor_player", "components": []}],
                "systems": [],
                "rules": [],
            }
        ],
    }


def _composite_batch() -> dict:
    return {
        "schema": "xace.typed_cgs_operation_batch.v1",
        "request_id": "request.x10-032",
        "prompt_id": "prompt.x10-032",
        "summary": "Add a composite traversal slice with save and network policy.",
        "operations": [
            {
                "operation_id": "declare.dash_resource",
                "kind": "declare_component",
                "explanation": "Declare exact dash resource state.",
                "component_type_id": 10010,
                "component_name": "COMP_DASH_RESOURCE_V1",
                "version": "1.0.0",
                "fields": [
                    {"name": "charges", "field_type": "int", "default": 1},
                    {"name": "cooldown_ticks", "field_type": "uint", "default": 30},
                ],
            },
            {
                "operation_id": "attach.dash_resource",
                "kind": "add_component",
                "explanation": "Attach dash resource to the player.",
                "mode_id": "mode_gameplay",
                "actor_id": "actor_player",
                "component_type_id": 10010,
                "component_name": "COMP_DASH_RESOURCE_V1",
                "defaults": [],
                "use_schema_defaults": True,
            },
            {
                "operation_id": "system.movement_intent",
                "kind": "add_system",
                "explanation": "Plan deterministic input-to-intent execution.",
                "system_id": "MovementIntentSystem",
                "phase": "Input",
                "reads": [6, 120],
                "writes": [120],
                "depends_on": [],
                "implementation_ref": "builtin.MovementIntentSystem.v1",
            },
            {
                "operation_id": "system.platformer_motion",
                "kind": "add_system",
                "explanation": "Plan deterministic platformer motion.",
                "system_id": "PlatformerMotionSystem",
                "phase": "Simulation",
                "reads": [5, 120, 125],
                "writes": [5, 125],
                "depends_on": ["MovementIntentSystem"],
                "implementation_ref": "builtin.PlatformerMotionSystem.v1",
            },
            {
                "operation_id": "asset.dash_audio",
                "kind": "add_asset",
                "explanation": "Reserve dash feedback.",
                "asset_id": "dash_audio_v1",
                "asset_type": "AUDIO_CLIP",
                "status": "PLACEHOLDER",
            },
            {
                "operation_id": "save.persistence_layer",
                "kind": "set_defaults",
                "explanation": "Keep dash state in the progress save layer.",
                "mode_id": "mode_gameplay",
                "actor_id": "actor_player",
                "component_type_id": 232,
                "assignments": [
                    {"field_name": "save_layer", "field_type": "string", "value": "Session"}
                ],
            },
            {
                "operation_id": "network.authority_policy",
                "kind": "set_defaults",
                "explanation": "Make dash state use owner prediction policy.",
                "mode_id": "mode_gameplay",
                "actor_id": "actor_player",
                "component_type_id": 10,
                "assignments": [
                    {"field_name": "replication_mode", "field_type": "string", "value": "Unreliable"},
                    {"field_name": "prediction_enabled", "field_type": "bool", "value": True},
                ],
            },
        ],
    }


class TestTypedCgsOperations(unittest.TestCase):
    def test_registry_covers_every_x10_030_operation_family(self) -> None:
        self.assertEqual(set(OPERATION_REGISTRY), set(OperationKind))
        self.assertEqual(
            {kind.value for kind in OPERATION_REGISTRY},
            {
                "declare_component",
                "add_component",
                "add_system",
                "add_generated_system",
                "add_event",
                "add_rule",
                "add_asset",
                "set_defaults",
            },
        )

    def test_full_batch_parses_and_compiles_without_provider_paths(self) -> None:
        batch = parse_typed_operation_batch(json.dumps(_full_batch()))
        plan = compile_typed_operation_batch(batch)

        self.assertEqual(batch.prompt_id, "pc002")
        self.assertEqual(plan.component_schemas[0]["type_id"], 10000)
        self.assertEqual(plan.actor_components[0][0:2], ("mode_gameplay", "actor_player"))
        self.assertEqual(plan.actor_components[0][2:4], (10000, "COMP_STAMINA_V1"))
        self.assertTrue(plan.actor_components[0][5])
        self.assertEqual(plan.global_systems[0]["id"], "StaminaSystem")
        self.assertEqual(plan.semantic_events[0]["name"], "stamina.depleted")
        self.assertEqual(plan.mode_rules[0][1]["id"], "rule.stamina_depleted")
        self.assertEqual(plan.assets[0]["status"], "PLACEHOLDER")
        self.assertEqual(
            plan.default_updates[0],
            ("mode_gameplay", "actor_player", 10000, "maximum", 1250000),
        )
        self.assertNotIn('"path"', plan.canonical_json())

    def test_parser_rejects_ad_hoc_path_value_patch(self) -> None:
        payload = _full_batch()
        payload["operations"][0]["path"] = "component_schemas"
        payload["operations"][0]["value"] = {"anything": "goes"}

        with self.assertRaisesRegex(TypedOperationError, "unknown fields"):
            parse_typed_operation_batch(payload)

    def test_parser_rejects_bool_for_fixed_authoritative_default(self) -> None:
        payload = _full_batch()
        payload["operations"][0]["fields"][0]["default"] = True

        with self.assertRaisesRegex(TypedOperationError, "does not match"):
            parse_typed_operation_batch(payload)

    def test_parser_rejects_nested_authoritative_float(self) -> None:
        payload = _full_batch()
        payload["operations"][0]["fields"].append(
            {
                "name": "metadata",
                "field_type": "object",
                "default": {"rate": 0.5},
            }
        )

        with self.assertRaisesRegex(TypedOperationError, "without floats"):
            parse_typed_operation_batch(payload)

    def test_parser_rejects_component_override_type_drift(self) -> None:
        payload = _full_batch()
        payload["operations"][1]["defaults"][0]["field_type"] = "string"
        payload["operations"][1]["defaults"][0]["value"] = "750000"

        with self.assertRaisesRegex(TypedOperationError, "type does not match"):
            parse_typed_operation_batch(payload)

    def test_existing_schema_rejects_every_numeric_type_interchange(self) -> None:
        numeric_types = ("fixed", "int", "uint", "entity_id")
        for expected in numeric_types:
            for declared in numeric_types:
                if declared == expected:
                    continue
                with self.subTest(expected=expected, declared=declared):
                    batch = parse_typed_operation_batch(
                        _existing_attachment_payload(field_type=declared, value=1)
                    )
                    result = apply_typed_operation_batch(
                        batch,
                        _existing_attachment_cgs(field_type=expected, default=1),
                    )
                    self.assertFalse(result.validation.valid)
                    self.assertTrue(
                        any(
                            "type does not match the schema" in error
                            for error in result.validation.errors
                        ),
                        result.validation.errors,
                    )

    def test_set_defaults_uses_exact_schema_type_metadata(self) -> None:
        payload = _existing_attachment_payload(field_type="uint", value=1)
        payload["operations"] = [
            {
                "operation_id": "defaults.inventory",
                "kind": "set_defaults",
                "explanation": "Update one existing inventory default.",
                "mode_id": "mode_gameplay",
                "actor_id": "actor_player",
                "component_type_id": 201,
                "assignments": [
                    {
                        "field_name": "max_capacity",
                        "field_type": "uint",
                        "value": 1,
                    }
                ],
            }
        ]
        current_cgs = _existing_attachment_cgs(field_type="int", default=1)
        current_cgs["modes"][0]["actors"][0]["components"].append(
            {
                "type_id": 201,
                "name": "COMP_INVENTORY_V1",
                "defaults": {"max_capacity": 1},
            }
        )

        result = apply_typed_operation_batch(
            parse_typed_operation_batch(payload),
            current_cgs,
        )

        self.assertFalse(result.validation.valid)
        self.assertTrue(
            any(
                "type does not match the schema" in error
                for error in result.validation.errors
            ),
            result.validation.errors,
        )

    def test_existing_attachment_fails_closed_without_explicit_exact_schema(self) -> None:
        batch = parse_typed_operation_batch(
            _existing_attachment_payload(include_assignment=False)
        )

        missing_schema = apply_typed_operation_batch(
            batch,
            _existing_attachment_cgs(include_schema=False),
        )
        self.assertFalse(missing_schema.validation.valid)
        self.assertTrue(
            any(
                "explicit component schema is unavailable" in error
                for error in missing_schema.validation.errors
            ),
            missing_schema.validation.errors,
        )

        missing_types = apply_typed_operation_batch(
            batch,
            _existing_attachment_cgs(include_fields=False),
        )
        self.assertFalse(missing_types.validation.valid)
        self.assertTrue(
            any(
                "exact field type metadata" in error
                for error in missing_types.validation.errors
            ),
            missing_types.validation.errors,
        )

    def test_uint_and_entity_id_reject_negative_values_and_schema_defaults(self) -> None:
        for field_type in ("uint", "entity_id"):
            with self.subTest(field_type=field_type, boundary="provider"):
                with self.assertRaisesRegex(TypedOperationError, "does not match"):
                    parse_typed_operation_batch(
                        _existing_attachment_payload(
                            field_type=field_type,
                            value=-1,
                        )
                    )

            with self.subTest(field_type=field_type, boundary="existing-schema"):
                batch = parse_typed_operation_batch(
                    _existing_attachment_payload(
                        field_type=field_type,
                        value=0,
                        include_assignment=False,
                    )
                )
                result = apply_typed_operation_batch(
                    batch,
                    _existing_attachment_cgs(
                        field_type=field_type,
                        default=-1,
                    ),
                )
                self.assertFalse(result.validation.valid)
                self.assertTrue(
                    any(
                        "does not match exact type" in error
                        for error in result.validation.errors
                    ),
                    result.validation.errors,
                )

    def test_prompt_declared_component_cannot_claim_reserved_id_or_source(self) -> None:
        reserved = _full_batch()
        reserved["operations"][0]["component_type_id"] = 9999
        with self.assertRaisesRegex(TypedOperationError, "GCL type-id range"):
            parse_typed_operation_batch(reserved)

        wrong_source = _full_batch()
        wrong_source["operations"][0]["source"] = "plugin"
        with self.assertRaisesRegex(TypedOperationError, "must be 'generated'"):
            parse_typed_operation_batch(wrong_source)

    def test_batch_rejects_duplicate_typed_identity(self) -> None:
        payload = _full_batch()
        duplicate = copy.deepcopy(payload["operations"][3])
        duplicate["operation_id"] = "add.stamina_event_again"
        payload["operations"].append(duplicate)

        with self.assertRaisesRegex(TypedOperationError, "declared event names"):
            parse_typed_operation_batch(payload)

    def test_parser_rejects_unknown_operation_kind_and_extra_root_keys(self) -> None:
        unknown = _full_batch()
        unknown["operations"][0]["kind"] = "json_patch"
        with self.assertRaisesRegex(TypedOperationError, "not registered"):
            parse_typed_operation_batch(unknown)

        extra = _full_batch()
        extra["raw_patch"] = []
        with self.assertRaisesRegex(TypedOperationError, "unknown fields"):
            parse_typed_operation_batch(extra)

    def test_linked_asset_requires_safe_project_relative_source(self) -> None:
        linked = _full_batch()
        asset = linked["operations"][5]
        asset["status"] = "LINKED"
        asset["source"] = "../outside.wav"
        with self.assertRaisesRegex(TypedOperationError, "project-relative"):
            parse_typed_operation_batch(linked)

    def test_compilation_is_deterministic_and_defensively_copies_values(self) -> None:
        payload = _full_batch()
        batch = parse_typed_operation_batch(payload)
        first = compile_typed_operation_batch(batch)
        second = compile_typed_operation_batch(batch)
        self.assertEqual(first.canonical_json(), second.canonical_json())

        payload["operations"][0]["fields"][0]["default"] = 1
        self.assertEqual(first.component_schemas[0]["defaults"]["current"], 1000000)

    def test_provider_schema_is_closed_and_contains_no_generic_patch_fields(self) -> None:
        schema = typed_operation_batch_json_schema()
        self.assertFalse(schema["additionalProperties"])
        variants = schema["properties"]["operations"]["items"]["anyOf"]
        self.assertEqual(len(variants), len(OPERATION_REGISTRY))
        for variant in variants:
            self.assertFalse(variant["additionalProperties"])
            self.assertNotIn("path", variant["properties"])
            self.assertNotIn("op", variant["properties"])
            self.assertNotIn("value", variant["properties"])

        self._assert_openai_strict_schema(schema)
        self._assert_supported_provider_keywords(schema)

    def test_provider_schema_locally_validates_every_normalized_variant(self) -> None:
        normalized = normalized_typed_operation_batch(
            parse_typed_operation_batch(_full_batch())
        )
        contract = StructuredOutputContract(
            schema_id="xace.typed_cgs_operation_batch.v1",
            name="xace_typed_cgs_operation_batch_v1",
            schema=typed_operation_batch_json_schema(),
        )

        for operation in normalized["operations"]:
            with self.subTest(kind=operation["kind"]):
                payload = copy.deepcopy(normalized)
                payload["operations"] = [copy.deepcopy(operation)]
                errors = validate_structured_output_text(
                    json.dumps(payload), contract
                )
                self.assertEqual(errors, [])

    def test_provider_schema_rejects_wrong_variant_missing_fields_and_bad_values(self) -> None:
        normalized = normalized_typed_operation_batch(
            parse_typed_operation_batch(_full_batch())
        )
        contract = StructuredOutputContract(
            schema_id="xace.typed_cgs_operation_batch.v1",
            name="xace_typed_cgs_operation_batch_v1",
            schema=typed_operation_batch_json_schema(),
        )

        wrong_kind = copy.deepcopy(normalized)
        wrong_kind["operations"] = [copy.deepcopy(wrong_kind["operations"][0])]
        wrong_kind["operations"][0]["kind"] = "add_asset"
        self.assertTrue(
            validate_structured_output_text(json.dumps(wrong_kind), contract)
        )

        missing_source = copy.deepcopy(normalized)
        missing_source["operations"] = [
            copy.deepcopy(missing_source["operations"][5])
        ]
        del missing_source["operations"][0]["source"]
        self.assertTrue(
            validate_structured_output_text(json.dumps(missing_source), contract)
        )

        bad_component_id = copy.deepcopy(normalized)
        bad_component_id["operations"] = [
            copy.deepcopy(bad_component_id["operations"][0])
        ]
        bad_component_id["operations"][0]["component_type_id"] = 9999
        self.assertTrue(
            validate_structured_output_text(json.dumps(bad_component_id), contract)
        )

        bad_default_type = copy.deepcopy(normalized)
        bad_default_type["operations"] = [
            copy.deepcopy(bad_default_type["operations"][0])
        ]
        bad_default_type["operations"][0]["fields"][0]["default"] = True
        self.assertTrue(
            validate_structured_output_text(json.dumps(bad_default_type), contract)
        )

    def _assert_openai_strict_schema(self, node: object) -> None:
        if isinstance(node, dict):
            self.assertNotIn("oneOf", node)
            if node.get("type") == "object":
                properties = node.get("properties")
                self.assertIsInstance(properties, dict)
                self.assertIs(node.get("additionalProperties"), False)
                self.assertEqual(
                    set(node.get("required", [])),
                    set(properties),
                )
            for value in node.values():
                self._assert_openai_strict_schema(value)
        elif isinstance(node, list):
            for value in node:
                self._assert_openai_strict_schema(value)

    def _assert_supported_provider_keywords(self, schema: dict) -> None:
        self.assertLessEqual(
            set(schema),
            _OPENAI_STRICT_SCHEMA_KEYWORDS,
            f"unsupported provider schema keywords: "
            f"{sorted(set(schema) - _OPENAI_STRICT_SCHEMA_KEYWORDS)}",
        )
        properties = schema.get("properties", {})
        for child in properties.values():
            self._assert_supported_provider_keywords(child)
        items = schema.get("items")
        if isinstance(items, dict):
            self._assert_supported_provider_keywords(items)
        for branch in schema.get("anyOf", []):
            self._assert_supported_provider_keywords(branch)
        for definition in schema.get("$defs", {}).values():
            self._assert_supported_provider_keywords(definition)

    def test_prompt_corpus_case_pc002_has_typed_batch_provenance(self) -> None:
        corpus_path = SRC.parents[2] / "docs" / "prompt_corpus_100.jsonl"
        rows = [
            json.loads(line)
            for line in corpus_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        pc002 = next(row for row in rows if row["prompt_id"] == "pc002")
        self.assertIn("inventory component", pc002["prompt"].lower())

        payload = {
            "schema": "xace.typed_cgs_operation_batch.v1",
            "request_id": "request.pc002",
            "prompt_id": pc002["prompt_id"],
            "summary": "Add the catalog inventory component to the player.",
            "operations": [
                {
                    "operation_id": "attach.inventory",
                    "kind": "add_component",
                    "explanation": "Attach the registered inventory schema defaults.",
                    "mode_id": "mode_gameplay",
                    "actor_id": "actor_player",
                    "component_type_id": 201,
                    "component_name": "COMP_INVENTORY_V1",
                    "defaults": [],
                    "use_schema_defaults": True,
                }
            ],
        }
        batch = parse_typed_operation_batch(payload)
        self.assertEqual(batch.prompt_id, pc002["prompt_id"])
        plan = compile_typed_operation_batch(batch)
        self.assertEqual(plan.actor_components[0][2], 201)
        self.assertTrue(plan.actor_components[0][5])

    def test_composite_prompt_plan_derives_order_graph_facets_and_rollback(self) -> None:
        batch = parse_typed_operation_batch(_composite_batch())
        base_cgs = {"metadata": {"cgs_hash": "a" * 64}}

        plan = build_composite_prompt_plan(batch, base_cgs)
        plan_dict = plan.to_dict()

        self.assertTrue(composite_plan_has_required_facets(plan), plan_dict)
        self.assertEqual(
            plan_dict["operation_order"],
            [operation["operation_id"] for operation in _composite_batch()["operations"]],
        )
        self.assertEqual(plan_dict["rollback_plan"]["pre_cgs_hash"], "a" * 64)
        self.assertIn(
            {
                "from": "system.movement_intent",
                "to": "system.platformer_motion",
                "reason": "system_depends_on",
            },
            plan_dict["dependency_graph"]["edges"],
        )
        self.assertEqual(plan_dict["save_plan"]["policy"]["save_layer"], "Session")
        self.assertEqual(
            plan_dict["network_plan"]["policy"]["replication_mode"],
            "Unreliable",
        )
        self.assertTrue(plan_dict["network_plan"]["policy"]["prediction_enabled"])
        self.assertTrue(validate_composite_prompt_plan(plan_dict, batch).valid)

        tampered = copy.deepcopy(plan_dict)
        tampered["operation_order"] = list(reversed(tampered["operation_order"]))
        self.assertFalse(validate_composite_prompt_plan(tampered, batch).valid)


if __name__ == "__main__":
    unittest.main()
