import tempfile
import unittest
from pathlib import Path

import sys


SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from cgs_persistence import CGSPersistence, SnapshotRecord  # noqa: E402


class PromptHistoryUndoRedoTests(unittest.TestCase):
    def test_prompt_history_undo_redo_cursor_and_branch_truncation(self):
        with tempfile.TemporaryDirectory(prefix="xace-prompt-history-") as tmp:
            root = Path(tmp)
            persist = CGSPersistence(root)
            for index, cgs_hash in enumerate(("a" * 64, "b" * 64, "c" * 64, "d" * 64), start=1):
                cgs = _sample_cgs(cgs_hash)
                persist.save(cgs)
                persist.snapshot(cgs, _record(cgs_hash, timestamp=float(index)))

            first = persist.record_prompt_history_apply(
                transaction_id="txn-000000000001",
                pre_cgs_hash="a" * 64,
                post_cgs_hash="b" * 64,
                summary="Prompt set speed step 1",
                mutation_count=1,
            )
            second = persist.record_prompt_history_apply(
                transaction_id="txn-000000000002",
                pre_cgs_hash="b" * 64,
                post_cgs_hash="c" * 64,
                summary="Prompt set speed step 2",
                mutation_count=1,
            )
            self.assertEqual(first["sequence"], 1)
            self.assertEqual(second["sequence"], 2)
            self.assertEqual(persist.prompt_history_state()["cursor"], 2)

            undo_1 = persist.plan_prompt_history_restore(
                "undo",
                current_cgs_hash="c" * 64,
                require_proof=False,
            )
            self.assertTrue(undo_1["accepted"], undo_1)
            self.assertEqual(undo_1["target_cgs_hash"], "b" * 64)
            event_1 = persist.complete_prompt_history_restore(
                undo_1,
                transaction_id="txn-000000000003",
            )
            self.assertEqual(event_1["cursor_after"], 1)

            undo_2 = persist.plan_prompt_history_restore(
                "undo",
                current_cgs_hash="b" * 64,
                require_proof=False,
            )
            self.assertTrue(undo_2["accepted"], undo_2)
            self.assertEqual(undo_2["target_cgs_hash"], "a" * 64)
            persist.complete_prompt_history_restore(
                undo_2,
                transaction_id="txn-000000000004",
            )
            self.assertFalse(persist.prompt_history_state()["can_undo"])

            redo = persist.plan_prompt_history_restore(
                "redo",
                current_cgs_hash="a" * 64,
                require_proof=False,
            )
            self.assertTrue(redo["accepted"], redo)
            self.assertEqual(redo["target_cgs_hash"], "b" * 64)
            persist.complete_prompt_history_restore(
                redo,
                transaction_id="txn-000000000005",
            )

            branch = persist.record_prompt_history_apply(
                transaction_id="txn-000000000006",
                pre_cgs_hash="b" * 64,
                post_cgs_hash="d" * 64,
                summary="Prompt branch after undo",
                mutation_count=1,
            )
            state = persist.prompt_history_state()
            self.assertEqual(branch["redo_entries_truncated"], 1)
            self.assertEqual(state["cursor"], 2)
            self.assertEqual(len(state["entries"]), 2)
            self.assertEqual(state["entries"][-1]["post_cgs_hash"], "d" * 64)
            self.assertFalse(state["can_redo"])

    def test_prompt_history_restore_requires_proof_links_by_default(self):
        with tempfile.TemporaryDirectory(prefix="xace-prompt-history-proof-") as tmp:
            root = Path(tmp)
            persist = CGSPersistence(root)
            for index, cgs_hash in enumerate(("a" * 64, "b" * 64), start=1):
                cgs = _sample_cgs(cgs_hash)
                persist.save(cgs)
                persist.snapshot(cgs, _record(cgs_hash, timestamp=float(index)))
            persist.record_prompt_history_apply(
                transaction_id="txn-000000000001",
                pre_cgs_hash="a" * 64,
                post_cgs_hash="b" * 64,
                summary="Prompt proof-required restore",
                mutation_count=1,
            )

            rejected = persist.plan_prompt_history_restore(
                "undo",
                current_cgs_hash="b" * 64,
            )

            self.assertFalse(rejected["accepted"])
            self.assertIn("ExecutionPlan", rejected["reason"])
            self.assertTrue(rejected["proof_status"]["snapshot_available"])
            self.assertFalse(rejected["proof_status"]["execution_plan_available"])


def _sample_cgs(cgs_hash: str) -> dict:
    return {
        "metadata": {
            "name": "Prompt History Test",
            "version": "0.1.0",
            "schema_version": "0.1.0",
            "cgs_hash": cgs_hash,
        },
        "global_systems": [],
        "modes": [
            {
                "id": "default",
                "schema_version": "0.1.0",
                "is_default": True,
                "actors": [],
                "systems": [],
                "rules": [],
            }
        ],
    }


def _record(cgs_hash: str, timestamp: float) -> SnapshotRecord:
    return SnapshotRecord(
        cgs_hash=cgs_hash,
        schema_version="0.1.0",
        turn_index=0,
        mutation_count=1,
        timestamp=timestamp,
        summary="prompt history test",
    )


if __name__ == "__main__":
    unittest.main()
