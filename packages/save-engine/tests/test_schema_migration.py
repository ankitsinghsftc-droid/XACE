"""Schema migration tests for old saves loaded by new game versions."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SAVE_ENGINE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SAVE_ENGINE_ROOT))

from save_deserializer import SaveDeserializer, SaveMigrationRequired
from save_engine_orchestrator import SaveEngineOrchestrator
from save_migration_engine import SaveMigrationEngine
from save_serializer import SaveSerializer


def migration_plan() -> dict:
    return {
        "from_version": "0.1.0",
        "to_version": "0.2.0",
        "is_breaking": False,
        "rules": [
            {
                "rule_type": "add_field",
                "target_path": "actors.player.components.100.fields.max_hp",
                "params": {"field_name": "max_hp", "default_value": 100},
            },
            {
                "rule_type": "modify_field",
                "target_path": "actors.player.components.100.fields.hp",
                "params": {"field_name": "hp", "old_value": 50, "new_value": 75},
            },
        ],
    }


class TestSchemaMigration(unittest.TestCase):
    def test_version_mismatch_requires_migration_plan(self) -> None:
        serializer = SaveSerializer()
        envelope = serializer.build_envelope(
            schema_version="0.1.0",
            layer="SESSION",
            payload={"actors": {}},
        )
        text = serializer.dumps(envelope)

        with self.assertRaises(SaveMigrationRequired):
            SaveDeserializer(current_schema_version="0.2.0").loads(text)

    def test_migration_plan_updates_payload_and_history(self) -> None:
        serializer = SaveSerializer()
        envelope = serializer.build_envelope(
            schema_version="0.1.0",
            layer="SESSION",
            payload={
                "actors": {
                    "player": {
                        "components": {
                            "100": {"fields": {"hp": 50}},
                        },
                    },
                },
            },
        )
        text = serializer.dumps(envelope)
        loaded = SaveDeserializer(
            current_schema_version="0.2.0",
            migration_engine=SaveMigrationEngine(),
        ).loads(text, migration_plan=migration_plan())

        fields = loaded.payload["actors"]["player"]["components"]["100"]["fields"]
        self.assertTrue(loaded.migrated)
        self.assertEqual(loaded.schema_version, "0.2.0")
        self.assertEqual(fields["hp"], 75)
        self.assertEqual(fields["max_hp"], 100)
        self.assertEqual(loaded.envelope["migration_history"][0]["rule_count"], 2)

    def test_orchestrator_persists_migrated_save(self) -> None:
        with tempfile.TemporaryDirectory(prefix="xace_save_migration_") as root:
            old_engine = SaveEngineOrchestrator(root, current_schema_version="0.1.0")
            old_engine.save_session(
                "slot_1",
                {
                    "actors": {
                        "player": {
                            "components": {
                                "100": {"fields": {"hp": 50}},
                            },
                        },
                    },
                },
            )

            new_engine = SaveEngineOrchestrator(root, current_schema_version="0.2.0")
            loaded = new_engine.load_session("slot_1", migration_plan=migration_plan())
            reloaded = new_engine.load_session("slot_1")

            self.assertTrue(loaded.save.migrated)
            self.assertFalse(reloaded.save.migrated)
            self.assertEqual(reloaded.save.schema_version, "0.2.0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
