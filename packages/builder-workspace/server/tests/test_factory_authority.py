import copy
import importlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))
from session_manager import SessionManager, GDEApplyResult
from types import SimpleNamespace
from unittest.mock import Mock
from dcl.gameplay_primitives import build_primitive_cgs, PLATFORMER_KINEMATIC_MOVEMENT_V1

factory = importlib.import_module("schema-factory.src.portable_compilation")

class FactoryAuthorityTests(unittest.TestCase):
    def test_real_factory_projection_preserves_source_and_orders_systems(self):
        cgs = build_primitive_cgs(PLATFORMER_KINEMATIC_MOVEMENT_V1)
        before = copy.deepcopy(cgs)
        package = factory.compile_portable_cgs(cgs)
        self.assertTrue(package.is_valid)
        self.assertEqual(cgs, before)
        self.assertEqual(package.cgs_hash, cgs["metadata"]["cgs_hash"])
        self.assertEqual([s["id"] for s in package.to_sgc_input()], sorted(s["id"] for s in package.to_sgc_input()))

    def _reject_before_sgc(self, modify):
        cgs = build_primitive_cgs(PLATFORMER_KINEMATIC_MOVEMENT_V1)
        modify(cgs)
        before = copy.deepcopy(cgs)
        manager = object.__new__(SessionManager)
        manager._sgc_bin, manager._sgc_args = "must-not-execute", []
        with patch("subprocess.run") as run:
            result = manager.compile_sgc_plan(cgs)
        run.assert_not_called()
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error["code"], "SCHEMA_FACTORY_VALIDATION_FAILED")
        self.assertEqual(cgs, before)

    def test_invalid_world_never_reaches_sgc(self):
        self._reject_before_sgc(lambda c: c["modes"][0].update(world="engine_scene_path"))

    def test_invalid_world_size_never_reaches_sgc(self):
        self._reject_before_sgc(lambda c: c["modes"][0].update(world={"size": {"width": -1, "height": 1, "depth": 1}}))

    def test_undeclared_component_never_reaches_sgc(self):
        self._reject_before_sgc(lambda c: c["modes"][0]["actors"][0]["components"].append({"type_id": 9999, "name": "COMP_UNKNOWN_V1", "defaults": {}}))

    def test_gcl_cannot_redefine_core(self):
        self._reject_before_sgc(lambda c: c["component_schemas"][0].update(source="gcl"))

    def test_export_cannot_extend_frozen_component_fields(self):
        self._reject_before_sgc(lambda c: c["component_schemas"][0]["defaults"].update(invented_authority=True))

    def test_invalid_global_phase_is_not_coerced_to_simulation(self):
        self._reject_before_sgc(lambda c: c["global_systems"].append({"id": "InjectedSystem", "phase": "wrong", "reads": [], "writes": []}))

    def test_missing_factory_has_no_extraction_fallback(self):
        cgs = build_primitive_cgs(PLATFORMER_KINEMATIC_MOVEMENT_V1)
        manager = object.__new__(SessionManager)
        manager._sgc_bin, manager._sgc_args = "must-not-execute", []
        with patch("subprocess.run") as run, patch("importlib.import_module", side_effect=ImportError("factory unavailable")):
            result = manager.compile_sgc_plan(cgs)
        run.assert_not_called()
        self.assertEqual(result.error["code"], "SCHEMA_FACTORY_VALIDATION_FAILED")

    def test_component_value_type_rejected_before_sgc(self):
        def modify(c):
            comp = next(x for x in c["modes"][0]["actors"][0]["components"] if x["type_id"] == 5)
            comp["defaults"]["max_linear_speed"] = "untyped"
        self._reject_before_sgc(modify)

    def test_shipped_field_type_cannot_be_redeclared(self):
        def modify(c):
            comp = next(x for x in c["component_schemas"] if x["type_id"] == 5)
            comp["defaults"]["max_linear_speed"] = "untyped"
        self._reject_before_sgc(modify)

    def test_nonfinite_component_value_rejected(self):
        def modify(c):
            comp = next(x for x in c["modes"][0]["actors"][0]["components"] if x["type_id"] == 5)
            comp["defaults"]["max_linear_speed"] = float("inf")
        self._reject_before_sgc(modify)

    def test_failed_candidate_restore_disables_gde(self):
        cgs = build_primitive_cgs(PLATFORMER_KINEMATIC_MOVEMENT_V1)
        invalid = copy.deepcopy(cgs)
        invalid["modes"][0]["world"] = "invalid"
        gde = Mock()
        gde.load_cgs.side_effect = RuntimeError("restore failed")
        session = SimpleNamespace(gde=gde)
        manager = object.__new__(SessionManager)
        manager._sessions = {"test": session}
        with patch("session_manager._apply_via_gde", return_value=GDEApplyResult(new_cgs=invalid)):
            result = manager.apply_via_gde("test", {}, cgs)
        self.assertFalse(result.success)
        self.assertIsNone(session.gde)
        self.assertIn("GDE disabled", result.error)

    def test_generated_gcl_uses_declared_field_types(self):
        cgs = build_primitive_cgs(PLATFORMER_KINEMATIC_MOVEMENT_V1)
        schema = {"type_id": 10000, "name": "COMP_TEST_V1", "source": "generated",
                  "defaults": {"value": 0, "data": {}}, "fields": [
                      {"name": "value", "field_type": "uint", "default": 0},
                      {"name": "data", "field_type": "object", "default": {}}]}
        cgs["component_schemas"].append(schema)
        cgs["modes"][0]["actors"][0]["components"].append(
            {"type_id": 10000, "name": "COMP_TEST_V1", "defaults": {"value": 1, "data": {}}})
        self.assertTrue(factory.compile_portable_cgs(cgs).is_valid)
        cgs["modes"][0]["actors"][0]["components"][-1]["defaults"]["value"] = -1
        with self.assertRaises(factory.SchemaFactoryError):
            factory.compile_portable_cgs(cgs)

    def test_empty_gcl_schema_cannot_accept_arbitrary_actor_fields(self):
        def modify(c):
            c["component_schemas"].append({"type_id": 10000, "name": "COMP_EMPTY_V1", "source": "gcl", "defaults": {}})
            c["modes"][0]["actors"][0]["components"].append({"type_id": 10000, "name": "COMP_EMPTY_V1", "defaults": {"injected": True}})
        self._reject_before_sgc(modify)
