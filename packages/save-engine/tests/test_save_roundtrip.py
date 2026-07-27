"""Save -> load -> identical world state tests for Audit 7."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SAVE_ENGINE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SAVE_ENGINE_ROOT))

from save_compression import SaveCompression
from save_engine_orchestrator import SaveEngineOrchestrator
from save_serializer import SaveLayer, SaveSerializer

TEST_CGS_HASH = "b" * 64
TEST_WORLD_HASH = "a" * 64


class TestSaveRoundtrip(unittest.TestCase):
    def test_serializer_is_deterministic_for_same_world_state(self) -> None:
        serializer = SaveSerializer()
        payload_a = {"entities": {"zombie": {"hp": 10.1234567}}, "tick": 42}
        payload_b = {"tick": 42, "entities": {"zombie": {"hp": 10.1234567}}}

        envelope_a = serializer.build_envelope(
            schema_version="0.1.0",
            layer=SaveLayer.SESSION,
            payload=payload_a,
            slot_id="slot_1",
            cgs_hash=TEST_CGS_HASH,
            created_at="2026-05-30T00:00:00Z",
            saved_at="2026-05-30T00:00:01Z",
        )
        envelope_b = serializer.build_envelope(
            schema_version="0.1.0",
            layer=SaveLayer.SESSION,
            payload=payload_b,
            slot_id="slot_1",
            cgs_hash=TEST_CGS_HASH,
            created_at="2026-05-30T00:00:00Z",
            saved_at="2026-05-30T00:00:01Z",
        )

        self.assertEqual(serializer.dumps(envelope_a), serializer.dumps(envelope_b))
        self.assertIn('"hp":10.123457', serializer.dumps(envelope_a))

    def test_orchestrator_roundtrips_all_three_layers(self) -> None:
        with tempfile.TemporaryDirectory(prefix="xace_save_roundtrip_") as root:
            engine = SaveEngineOrchestrator(root, current_schema_version="0.1.0")

            engine.save_session("slot_1", {"tick": 10, "world_hash": TEST_WORLD_HASH})
            engine.save_progress("slot_1", {"level": 3, "achievements": ["intro"]})
            engine.save_world("slot_1", {"doors": {"door_a": "open"}})

            self.assertEqual(engine.load_session("slot_1").save.payload["tick"], 10)
            self.assertEqual(engine.load_progress("slot_1").save.payload["level"], 3)
            self.assertEqual(
                engine.load_world("slot_1").save.payload["doors"]["door_a"],
                "open",
            )
            self.assertEqual(
                engine.list_slot_metadata()[0]["layers"],
                ["SESSION", "PROGRESS", "WORLD"],
            )

    def test_compressed_save_bytes_roundtrip(self) -> None:
        serializer = SaveSerializer()
        envelope = serializer.build_envelope(
            schema_version="0.1.0",
            layer="WORLD",
            payload={"state": {"door": True}, "tick": 99},
        )
        raw = serializer.dump_bytes(envelope)
        compressed, report = SaveCompression().compress(raw)

        self.assertGreater(report.compressed_bytes, 0)
        self.assertEqual(SaveCompression().decompress(compressed), raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
