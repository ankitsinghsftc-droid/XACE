import sys
import unittest
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from builder_server import _build_multiplayer_diagnostics_panel  # noqa: E402


class MultiplayerDiagnosticsPanelTests(unittest.TestCase):
    def test_x10_042_diagnostics_payload_exposes_required_panel_fields(self):
        diagnostics = _build_multiplayer_diagnostics_panel()

        self.assertEqual(diagnostics["schema"], "xace.multiplayer_diagnostics_snapshot.v1")
        self.assertEqual(diagnostics["topology_id"], "host_client_authoritative_lockstep_v1")
        self.assertGreaterEqual(len(diagnostics["peers"]), 2)
        self.assertIn("ticks", diagnostics)
        self.assertIn("input_buffers", diagnostics)
        self.assertIn("latency", diagnostics)
        self.assertIn("rollback", diagnostics)
        self.assertIn("resync", diagnostics)
        self.assertIn("hash_comparisons", diagnostics)
        self.assertIn("authority", diagnostics)
        self.assertIn("chaos_report", diagnostics)

        peer_two = next(peer for peer in diagnostics["peers"] if peer["peer_id"] == 2)
        self.assertEqual(peer_two["packet_loss_ppm"], 25000)
        self.assertEqual(peer_two["buffered_input_packets"], 1)
        self.assertEqual(peer_two["missing_input_ranges"], [{"from_tick": 40, "to_tick": 41}])

        self.assertEqual(diagnostics["ticks"]["missing_peers"], [2])
        self.assertFalse(diagnostics["ticks"]["can_release"])
        self.assertEqual(diagnostics["latency"]["worst_peer"], 2)
        self.assertEqual(diagnostics["rollback"]["rollback_count"], 1)
        self.assertEqual(diagnostics["resync"][0]["state"], "AwaitingAck")
        self.assertEqual(diagnostics["hash_comparisons"][0]["divergent_peers"][0]["peer_id"], 2)
        self.assertTrue(any(row["entity_id"] == 501 and row["owner_peer"] == 1 for row in diagnostics["authority"]))
        self.assertEqual(diagnostics["chaos_report"]["resync_status"], "AwaitingAck")
        self.assertIn("X10-043", diagnostics["chaos_report"]["boundary"])


if __name__ == "__main__":
    unittest.main()
