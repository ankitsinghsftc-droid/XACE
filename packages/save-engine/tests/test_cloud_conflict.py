"""Cloud conflict detection and resolution tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SAVE_ENGINE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SAVE_ENGINE_ROOT))

from cloud_sync_adapter import CloudSyncError, LocalFolderCloudSyncAdapter
from cloud_sync_conflict_resolver import (
    CloudSyncConflictResolver,
    ConflictResolutionKind,
    SaveVersionInfo,
)


class TestCloudConflict(unittest.TestCase):
    def test_local_folder_adapter_detects_revision_conflict(self) -> None:
        with tempfile.TemporaryDirectory(prefix="xace_cloud_conflict_") as root:
            adapter = LocalFolderCloudSyncAdapter(root)
            first = adapter.upload("slot_1", b"first")
            second = adapter.upload("slot_1", b"second", expected_revision=first.revision)

            self.assertNotEqual(first.revision, second.revision)
            with self.assertRaises(CloudSyncError):
                adapter.upload("slot_1", b"third", expected_revision=first.revision)

    def test_strategy_selects_local_or_cloud_payload(self) -> None:
        local = SaveVersionInfo("local_rev", "local_hash", 100, {"source": "local"})
        cloud = SaveVersionInfo("cloud_rev", "cloud_hash", 101, {"source": "cloud"})

        local_decision = CloudSyncConflictResolver("LOCAL_WINS").resolve(local, cloud)
        cloud_decision = CloudSyncConflictResolver("CLOUD_WINS").resolve(local, cloud)
        ask_decision = CloudSyncConflictResolver("ASK_USER").resolve(local, cloud)

        self.assertEqual(local_decision.kind, ConflictResolutionKind.USE_LOCAL)
        self.assertEqual(local_decision.payload["source"], "local")
        self.assertEqual(cloud_decision.kind, ConflictResolutionKind.USE_CLOUD)
        self.assertEqual(cloud_decision.payload["source"], "cloud")
        self.assertEqual(ask_decision.kind, ConflictResolutionKind.ASK_USER)

    def test_profile_merge_is_deterministic(self) -> None:
        local = {
            "profile_id": "p1",
            "achievements": ["A"],
            "settings": {"volume": 0.8},
            "statistics": {"kills": 2, "deaths": 1},
            "total_play_time": 50,
            "last_played_slot_id": "slot_local",
        }
        cloud = {
            "profile_id": "p1",
            "achievements": ["B", "A"],
            "settings": {"volume": 0.5},
            "statistics": {"kills": 5, "distance": 10},
            "total_play_time": 45,
            "last_played_slot_id": "slot_cloud",
        }

        decision = CloudSyncConflictResolver().merge_player_profile(local, cloud)

        self.assertEqual(decision.kind, ConflictResolutionKind.MERGED)
        self.assertEqual(decision.payload["achievements"], ["A", "B"])
        self.assertEqual(decision.payload["statistics"]["kills"], 5)
        self.assertEqual(decision.payload["statistics"]["distance"], 10)
        self.assertEqual(decision.payload["total_play_time"], 50)
        self.assertEqual(decision.payload["settings"], {"volume": 0.8})


if __name__ == "__main__":
    unittest.main(verbosity=2)
