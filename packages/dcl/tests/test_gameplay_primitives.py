from __future__ import annotations

import unittest
from dataclasses import replace

from packages.dcl.gameplay_primitives import (
    GAMEPLAY_PRIMITIVES,
    MULTIPLAYER_AUTHORITATIVE_COMBAT_V1,
    PLATFORMER_KINEMATIC_MOVEMENT_V1,
    REQUIRED_FACETS,
    RUNTIME_SYSTEM_CONTRACTS,
    TASK_REQUIRED_GENRES,
    build_primitive_cgs,
    committed_cgs_hash,
    covered_genres,
    remaining_genres,
    validate_catalog,
)


class GameplayPrimitiveCatalogTests(unittest.TestCase):
    def test_full_catalog_is_internally_valid_and_covers_required_genres(self) -> None:
        self.assertEqual(validate_catalog(), [])
        self.assertEqual(len(GAMEPLAY_PRIMITIVES), len(TASK_REQUIRED_GENRES))
        self.assertEqual(covered_genres(), TASK_REQUIRED_GENRES)
        self.assertEqual(remaining_genres(), ())

    def test_every_primitive_has_all_seven_material_facets(self) -> None:
        for primitive in GAMEPLAY_PRIMITIVES:
            with self.subTest(primitive=primitive.primitive_id):
                self.assertEqual(primitive.facets, REQUIRED_FACETS)
                self.assertTrue(primitive.components)
                self.assertTrue(primitive.systems)
                self.assertTrue(primitive.events)
                self.assertTrue(primitive.inputs)
                self.assertTrue(primitive.assets)
                self.assertTrue(primitive.save.component_type_ids)
                self.assertTrue(primitive.network.component_type_ids)

    def test_every_catalog_system_matches_runtime_access_contract(self) -> None:
        for primitive in GAMEPLAY_PRIMITIVES:
            for index, system in enumerate(primitive.systems):
                with self.subTest(primitive=primitive.primitive_id, system=system.system_id):
                    phase, reads, writes = RUNTIME_SYSTEM_CONTRACTS[system.system_id]
                    self.assertEqual((system.phase, system.reads, system.writes), (phase, reads, writes))
                    if index > 0:
                        self.assertTrue(system.depends_on)

    def test_platformer_primitive_has_all_facets_and_ordered_chain(self) -> None:
        primitive = PLATFORMER_KINEMATIC_MOVEMENT_V1
        self.assertEqual(primitive.facets, REQUIRED_FACETS)
        self.assertEqual(
            [system.system_id for system in primitive.systems],
            ["MovementIntentSystem", "PlatformerMotionSystem", "MovementSystem"],
        )
        self.assertEqual(
            primitive.systems[-1].depends_on,
            ("PlatformerMotionSystem",),
        )

    def test_committed_cgs_hash_is_deterministic_and_authoritative(self) -> None:
        for primitive in GAMEPLAY_PRIMITIVES:
            with self.subTest(primitive=primitive.primitive_id):
                first = build_primitive_cgs(primitive)
                second = build_primitive_cgs(primitive)
                self.assertEqual(first, second)
                self.assertEqual(first["metadata"]["cgs_hash"], committed_cgs_hash(first))
                self.assertEqual(len(first["metadata"]["cgs_hash"]), 64)

    def test_cgs_materializes_every_primitive_facet(self) -> None:
        cgs = build_primitive_cgs(PLATFORMER_KINEMATIC_MOVEMENT_V1)
        self.assertEqual(len(cgs["component_schemas"]), 9)
        self.assertEqual(len(cgs["global_systems"]), 3)
        self.assertEqual(len(cgs["semantic_events"]), 2)
        self.assertEqual(len(cgs["input_bindings"]), 2)
        self.assertEqual(len(cgs["semantic_bindings"]["bindings"]), 2)
        self.assertEqual(cgs["save_contract"]["strategy"], "component_snapshot")
        self.assertEqual(cgs["network_contract"]["scope"], "declarative_policy")

    def test_every_cgs_materializes_catalog_facets_without_platformer_actor_alias(self) -> None:
        for primitive in GAMEPLAY_PRIMITIVES:
            with self.subTest(primitive=primitive.primitive_id):
                cgs = build_primitive_cgs(primitive)
                self.assertEqual(len(cgs["component_schemas"]), len(primitive.components))
                self.assertEqual(len(cgs["global_systems"]), len(primitive.systems))
                self.assertEqual(len(cgs["semantic_events"]), len(primitive.events))
                self.assertEqual(len(cgs["input_bindings"]), len(primitive.inputs))
                self.assertEqual(
                    len(cgs["semantic_bindings"]["bindings"]), len(primitive.assets),
                )
                self.assertEqual(
                    cgs["modes"][0]["actors"][0]["id"],
                    primitive.primitive_id.replace(".", "_") + "_actor",
                )

    def test_multiplayer_combat_declares_server_authoritative_replication(self) -> None:
        primitive = MULTIPLAYER_AUTHORITATIVE_COMBAT_V1
        self.assertEqual(primitive.network.authority, "Server")
        self.assertEqual(primitive.network.replication_mode, "Unreliable")
        self.assertFalse(primitive.network.prediction_enabled)
        self.assertEqual(primitive.network.component_type_ids, (1, 5, 10, 100, 320, 321, 322))

    def test_authoritative_float_defaults_are_rejected(self) -> None:
        primitive = PLATFORMER_KINEMATIC_MOVEMENT_V1
        bad_component = replace(primitive.components[0], defaults={"position_x": 1.5})
        bad = replace(
            primitive,
            primitive_id="platformer.bad_float.v1",
            components=(bad_component,) + primitive.components[1:],
        )
        findings = validate_catalog((bad,))
        self.assertTrue(any("authoritative float" in finding for finding in findings))

    def test_dependency_must_precede_consumer(self) -> None:
        primitive = PLATFORMER_KINEMATIC_MOVEMENT_V1
        bad_motion = replace(
            primitive.systems[1],
            depends_on=("NotYetDeclaredSystem",),
        )
        bad = replace(
            primitive,
            primitive_id="platformer.bad_dependency.v1",
            systems=(primitive.systems[0], bad_motion, primitive.systems[2]),
        )
        findings = validate_catalog((bad,))
        self.assertTrue(any("must precede it" in finding for finding in findings))

    def test_component_id_name_and_source_must_match_frozen_contract(self) -> None:
        primitive = GAMEPLAY_PRIMITIVES[1]
        bad_component = replace(primitive.components[0], name="COMP_INVENTED_V1")
        bad = replace(
            primitive,
            primitive_id="rpg.bad_component_contract.v1",
            components=(bad_component,) + primitive.components[1:],
        )
        findings = validate_catalog((bad,))
        self.assertTrue(any("must be COMP_TRANSFORM_V1 from ucl" in item for item in findings))

    def test_semantic_event_name_and_payload_must_match_registry_contract(self) -> None:
        primitive = GAMEPLAY_PRIMITIVES[1]
        unknown_event = replace(primitive.events[0], name="inventory.invented")
        unknown = replace(
            primitive,
            primitive_id="rpg.bad_event_name.v1",
            events=(unknown_event,) + primitive.events[1:],
        )
        self.assertTrue(
            any("unregistered semantic event" in item for item in validate_catalog((unknown,)))
        )

        bad_payload_event = replace(primitive.events[0], required_payload_keys=("actor_entity_id",))
        bad_payload = replace(
            primitive,
            primitive_id="rpg.bad_event_payload.v1",
            events=(bad_payload_event,) + primitive.events[1:],
        )
        self.assertTrue(
            any("payload contract mismatch" in item for item in validate_catalog((bad_payload,)))
        )

    def test_builtin_access_metadata_cannot_drift_from_runtime_contract(self) -> None:
        primitive = GAMEPLAY_PRIMITIVES[1]
        bad_system = replace(primitive.systems[0], reads=(6,))
        bad = replace(
            primitive,
            primitive_id="rpg.bad_system_access.v1",
            systems=(bad_system,) + primitive.systems[1:],
        )
        findings = validate_catalog((bad,))
        self.assertTrue(any("reads must match runtime" in item for item in findings))

    def test_empty_material_facet_is_rejected(self) -> None:
        primitive = GAMEPLAY_PRIMITIVES[1]
        bad = replace(primitive, primitive_id="rpg.no_assets.v1", assets=())
        findings = validate_catalog((bad,))
        self.assertTrue(any("asset facet must declare" in item for item in findings))


if __name__ == "__main__":
    unittest.main()
