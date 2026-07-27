import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from session_manager import SessionManager  # noqa: E402


class SessionManagerAuthorityTests(unittest.TestCase):
    def test_apply_via_gde_rejects_stale_parent_hash_before_gde(self):
        sm = SessionManager()
        sm._sessions["session-1"] = SimpleNamespace(gde=None)
        result = sm.apply_via_gde(
            "session-1",
            {
                "parent_cgs_hash": "a" * 64,
                "operations": [],
            },
            _sample_cgs("b" * 64),
        )

        self.assertFalse(result.success)
        self.assertIn("GDE conflict", result.error)

    def test_apply_via_gde_rejects_when_gde_unavailable_without_persistable_result(self):
        sm = SessionManager()
        sm._sessions["session-1"] = SimpleNamespace(gde=None)
        result = sm.apply_via_gde(
            "session-1",
            {
                "parent_cgs_hash": "a" * 64,
                "operations": [{
                    "op": "SET",
                    "path": "modes.arcade.actors.player.components.Movement.defaults.speed",
                    "value": 12,
                }],
            },
            _sample_cgs("a" * 64),
        )

        self.assertFalse(result.success)
        self.assertIn("GDE is unavailable", result.error)
        self.assertIsNone(result.new_cgs)

    def test_pil_unavailable_blocks_without_fallback_transaction(self):
        sm = SessionManager()
        session = SimpleNamespace(
            pipeline=None,
            pending_txn={"operations": [{"op": "SET"}]},
            current_mode="COLLABORATIVE",
            touch=lambda: None,
        )
        sm._sessions["session-1"] = session
        sm.provider_readiness = lambda: {"ok": True}  # type: ignore[method-assign]

        result = asyncio.run(sm.run_pil(
            "session-1",
            "change the player speed",
            _sample_cgs("a" * 64),
            "a" * 64,
        ))

        self.assertEqual(result["kind"], "blocked")
        self.assertEqual(result["code"], "PIL_UNAVAILABLE")
        self.assertTrue(result["unsupported"])
        self.assertIsNone(session.pending_txn)
        self.assertNotIn("transaction", result)


def _sample_cgs(cgs_hash: str) -> dict:
    return {
        "metadata": {
            "name": "Authority Test",
            "version": "0.1.0",
            "schema_version": "0.1.0",
            "cgs_hash": cgs_hash,
        },
        "global_systems": [],
        "modes": [],
    }


if __name__ == "__main__":
    unittest.main()
