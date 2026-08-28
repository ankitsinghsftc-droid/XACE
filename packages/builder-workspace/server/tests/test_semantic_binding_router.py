import asyncio
import copy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import ws_message_router as router_mod  # noqa: E402
from ws_message_router import WSMessageRouter  # noqa: E402


class FakeSession:
    runtime_last_tick = {}
    runtime_last_hash = ""
    runtime_adapter_type = ""


class FakeSessionManager:
    def __init__(self):
        self._sessions = {"session-1": FakeSession()}


class FakePersistence:
    def __init__(self):
        self.saved = []
        self.audit = []
        self._txn_counter = 0
        self.current_hash = "hash-before"

    def save(self, cgs):
        self.saved.append(copy.deepcopy(cgs))
        self.current_hash = cgs["metadata"]["cgs_hash"]

    def current_cgs_hash(self):
        return self.current_hash

    def next_transaction_id(self):
        self._txn_counter += 1
        return f"txn-semantic-{self._txn_counter:04d}"

    def load_execution_plan(self, cgs_hash):
        return None

    def record_mutation_audit(self, *, ledger_entry, dataset_entry):
        self.audit.append((ledger_entry, dataset_entry))


class FakeStaticMutationConflictAnalyzer:
    def validate(self, **kwargs):
        return SimpleNamespace(is_valid=True, errors=[], warnings=[])


def sample_cgs():
    return {
        "metadata": {
            "name": "Semantic Binding Router Fixture",
            "version": "0.1.0",
            "schema_version": "0.1.0",
            "cgs_hash": "hash-before",
        },
        "global_systems": [],
        "modes": [{
            "id": "mode_default",
            "is_default": True,
            "actors": [],
            "systems": [],
            "rules": [],
        }],
    }


def binding_fixture(**overrides):
    binding = {
        "binding_id": "combat.attack_started.animation.hero_slash",
        "event_name": "combat.attack_started",
        "playback_kind": "Animation",
        "asset": {
            "id": "hero_slash_anim",
            "asset_type": "AnimationClip",
            "status": "Linked",
        },
        "semantic_action": "attack_slash",
        "entity_selector": "SourceEntity",
        "parameters": {
            "resource_path": "res://art/hero/hero_slash.anim",
            "asset_path": "res://art/hero/hero_slash.anim",
            "xace_engine_targets": "godot,unity,unreal",
            "state": "attack_slash",
        },
        "enabled": True,
        "priority": 10,
    }
    binding.update(overrides)
    return binding


class SemanticBindingRouterTests(unittest.TestCase):
    def setUp(self):
        self.old_analyzer = router_mod.StaticMutationConflictAnalyzer
        router_mod.StaticMutationConflictAnalyzer = FakeStaticMutationConflictAnalyzer

    def tearDown(self):
        router_mod.StaticMutationConflictAnalyzer = self.old_analyzer

    def test_semantic_binding_update_persists_sanitized_bindings(self):
        async def run():
            sent = []

            async def send_fn(message):
                sent.append(message)

            persistence = FakePersistence()
            cgs = sample_cgs()
            message = {
                "type": "semantic_binding_update",
                "session_id": "session-1",
                "cgs_hash": "hash-before",
                "bindings": [binding_fixture()],
            }

            await WSMessageRouter(FakeSessionManager()).route(
                "session-1",
                message,
                send_fn,
                persistence,
                cgs,
            )

            self.assertEqual(1, len(persistence.saved))
            saved_binding = cgs["semantic_bindings"]["bindings"][0]
            self.assertEqual("combat.attack_started.animation.hero_slash", saved_binding["binding_id"])
            self.assertEqual("AnimationClip", saved_binding["asset"]["asset_type"])
            self.assertEqual("godot,unity,unreal", saved_binding["parameters"]["xace_engine_targets"])
            self.assertEqual("res://art/hero/hero_slash.anim", saved_binding["parameters"]["resource_path"])
            self.assertEqual("cgs_update", sent[-1]["type"])
            self.assertEqual(["semantic_bindings"], sent[-1]["affected_node_ids"])
            self.assertEqual("applied", persistence.audit[-1][1]["outcome"])

        asyncio.run(run())

    def test_semantic_binding_update_rejects_wrong_asset_type(self):
        async def run():
            sent = []

            async def send_fn(message):
                sent.append(message)

            persistence = FakePersistence()
            cgs = sample_cgs()
            bad_binding = binding_fixture(
                playback_kind="Audio",
                asset={
                    "id": "hero_mesh",
                    "asset_type": "Mesh",
                    "status": "Linked",
                },
            )
            message = {
                "type": "semantic_binding_update",
                "session_id": "session-1",
                "cgs_hash": "hash-before",
                "bindings": [bad_binding],
            }

            await WSMessageRouter(FakeSessionManager()).route(
                "session-1",
                message,
                send_fn,
                persistence,
                cgs,
            )

            self.assertEqual([], persistence.saved)
            self.assertEqual("server_error", sent[-1]["type"])
            self.assertEqual("SEMANTIC_BINDING_INVALID", sent[-1]["code"])
            self.assertIn("Audio playback cannot use asset type", sent[-1]["message"])
            self.assertNotIn("semantic_bindings", cgs)

        asyncio.run(run())

    def test_semantic_binding_update_rejects_stale_hash_without_save(self):
        async def run():
            sent = []

            async def send_fn(message):
                sent.append(message)

            persistence = FakePersistence()
            cgs = sample_cgs()
            message = {
                "type": "semantic_binding_update",
                "session_id": "session-1",
                "cgs_hash": "stale-hash",
                "bindings": [binding_fixture()],
            }

            await WSMessageRouter(FakeSessionManager()).route(
                "session-1",
                message,
                send_fn,
                persistence,
                cgs,
            )

            self.assertEqual([], persistence.saved)
            self.assertEqual("server_error", sent[-1]["type"])
            self.assertEqual("STALE_CGS_WRITE", sent[-1]["code"])
            self.assertEqual("rejected_stale", persistence.audit[-1][1]["outcome"])

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
