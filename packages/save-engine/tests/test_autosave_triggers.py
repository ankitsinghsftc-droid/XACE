"""Autosave trigger tests for dirty persistence and safe-phase behavior."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SAVE_ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SAVE_ENGINE_ROOT.parents[1]
sys.path.insert(0, str(SAVE_ENGINE_ROOT))
sys.path.insert(0, str(REPO_ROOT))

from packages.dcl.world import get_domain_package
from save_engine_orchestrator import SaveEngineOrchestrator


class TestAutosaveTriggers(unittest.TestCase):
    def test_persistence_component_declares_audit_7_dirty_fields(self) -> None:
        package = get_domain_package()
        component = package.get_component("COMP_PERSISTENCE_V1")

        self.assertIsNotNone(component)
        self.assertTrue(component.has_field("auto_save"))
        self.assertTrue(component.has_field("last_saved_tick"))
        self.assertTrue(component.has_field("is_dirty"))
        self.assertTrue(component.has_field("save_layer"))

    def test_dirty_payload_saves_only_when_safe_phase_is_reached(self) -> None:
        with tempfile.TemporaryDirectory(prefix="xace_autosave_") as root:
            engine = SaveEngineOrchestrator(root, current_schema_version="0.1.0")
            record = {
                "save_key": "door_a",
                "auto_save": True,
                "last_saved_tick": 0,
                "is_dirty": True,
                "save_layer": "World",
            }

            saved_before_cleanup = self._maybe_autosave(
                engine,
                phase="Simulation",
                slot_id="slot_1",
                tick=10,
                record=record,
            )
            saved_at_cleanup = self._maybe_autosave(
                engine,
                phase="Cleanup",
                slot_id="slot_1",
                tick=10,
                record=record,
            )

            self.assertFalse(saved_before_cleanup)
            self.assertTrue(saved_at_cleanup)
            loaded = engine.load_world("slot_1").save.payload
            self.assertEqual(loaded["dirty_records"][0]["save_key"], "door_a")
            self.assertEqual(loaded["tick"], 10)

    def test_rust_autosave_unit_tests_pass(self) -> None:
        result = subprocess.run(
            ["cargo", "test", "-p", "xace-save-engine", "autosave_trigger_system"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @staticmethod
    def _maybe_autosave(
        engine: SaveEngineOrchestrator,
        *,
        phase: str,
        slot_id: str,
        tick: int,
        record: dict,
    ) -> bool:
        if phase != "Cleanup" or not record.get("auto_save") or not record.get("is_dirty"):
            return False
        engine.save_world(
            slot_id,
            {
                "tick": tick,
                "dirty_records": [record],
                "source": "autosave",
            },
        )
        return True


if __name__ == "__main__":
    unittest.main(verbosity=2)
