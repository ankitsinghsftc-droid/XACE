import asyncio
import copy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from ws_message_router import WSMessageRouter, _static_precommit_conflict_reason  # noqa: E402
from state_authority import can_merge_engine_default_edit  # noqa: E402

LIVE_COMMIT_HASH = "a" * 64
RUNTIME_HASH = "b" * 64
PREVIEW_ID = "engine-preview-test"
ADAPTER_SEQUENCE = 41
SCHEMA_VERSION = "0.1.0"


class FakeSession:
    def __init__(self):
        self.engine_edit_log = []
        self.runtime_status_updates = []
        self.runtime_connected = False
        self.runtime_adapter_type = ""
        self.runtime_last_tick = None
        self.runtime_last_hash = ""

    def update_runtime_status(self, **kwargs):
        self.runtime_status_updates.append(kwargs)
        self.runtime_connected = bool(kwargs.get("connected", self.runtime_connected))
        if kwargs.get("adapter_type"):
            self.runtime_adapter_type = str(kwargs["adapter_type"])
        if kwargs.get("last_tick") is not None:
            self.runtime_last_tick = kwargs["last_tick"]
        if kwargs.get("last_hash"):
            self.runtime_last_hash = str(kwargs["last_hash"])

    def record_engine_edit(self, edit):
        self.engine_edit_log.append({"ts": 123.0, **edit})


class FakeSessionManager:
    def __init__(self):
        self.session = FakeSession()
        self._sessions = {"session-1": self.session}
        self.apply_calls = []

    def apply_via_gde(self, session_id, txn, current_cgs):
        self.apply_calls.append((session_id, txn))
        new_cgs = {
            **current_cgs,
            "metadata": {
                **current_cgs["metadata"],
                "cgs_hash": LIVE_COMMIT_HASH,
            },
        }
        for mode in new_cgs["modes"]:
            if mode["id"] != "mode_default":
                continue
            for actor in mode["actors"]:
                if actor["id"] != "actor_player":
                    continue
                for component in actor["components"]:
                    if component["type_id"] == 100:
                        component["defaults"]["current"] = 72
        return SimpleNamespace(
            success=True,
            new_cgs=new_cgs,
            new_hash=LIVE_COMMIT_HASH,
            error="",
            warnings=[],
            used_gde=True,
        )


class FakeRuntimeControl:
    endpoint = "127.0.0.1:7778"

    def __init__(self, accepted=True):
        self.accepted = accepted
        self.calls = []

    def send_engine_edit(self, kind, **kwargs):
        self.calls.append({"kind": kind, **kwargs})
        return {
            "msg_type": "runtime_engine_edit_ack",
            "kind": kind,
            "accepted": self.accepted,
            "reason": "preview component field updated" if self.accepted else "entity 7 is not alive",
            "affected_entity_ids": [kwargs["entity_id"]] if self.accepted else [],
            "status": {
                "tick": 4,
                "alive_count": 1,
                "engine_connected": True,
                "adapter_type": "headless",
                "pending_engine_inputs": 0,
                "registered_systems": 2,
                "latest_world_hash": RUNTIME_HASH,
                "cgs_hash": "hash-before",
                "schema_version": SCHEMA_VERSION,
                "engine_adapter_sequence": ADAPTER_SEQUENCE,
                "phase_count": 4,
                "paused": True,
                "step_budget": 0,
            },
        }


class FakePersistence:
    def __init__(self):
        self.saved = []
        self.snapshots = []
        self.audit = []
        self._txn_counter = 0
        self.current_hash = "hash-before"

    def save(self, cgs):
        self.saved.append(cgs)
        self.current_hash = cgs["metadata"]["cgs_hash"]

    def snapshot(self, cgs, record):
        self.snapshots.append((cgs, record))

    def current_cgs_hash(self):
        return self.current_hash

    def next_transaction_id(self):
        self._txn_counter += 1
        return f"txn-{self._txn_counter:012d}"

    def load_execution_plan(self, cgs_hash):
        return None

    def record_mutation_audit(self, *, ledger_entry, dataset_entry):
        self.audit.append((ledger_entry, dataset_entry))


def sample_cgs():
    return {
        "metadata": {
            "name": "Test",
            "cgs_hash": "hash-before",
            "version": "0.1.0",
            "schema_version": "0.1.0",
        },
        "global_systems": [],
        "modes": [{
            "id": "mode_default",
            "is_default": True,
            "actors": [{
                "id": "actor_player",
                "actor_type": "PlayerCharacter",
                "control_type": "Human",
                "components": [{
                    "type_id": 100,
                    "name": "COMP_HEALTH_V1",
                    "defaults": {"current": 80, "max": 100},
                }],
            }],
            "systems": [{
                "id": "health_system",
                "phase": "Simulation",
                "reads": [100],
                "writes": [100],
                "depends_on": [],
                "deterministic": True,
            }],
            "rules": [],
        }],
    }


def accepted_live_edit(**overrides):
    edit = {
        "kind": "set_component_field",
        "accepted": True,
        "mode_id": "mode_default",
        "actor_id": "actor_player",
        "component_type_id": 100,
        "component_name": "COMP_HEALTH_V1",
        "field_path": "current",
        "value": 72,
        "reason": "preview component field updated",
        "preview_id": PREVIEW_ID,
        "preview_cgs_hash": "hash-before",
        "preview_schema_version": SCHEMA_VERSION,
        "runtime_world_hash": RUNTIME_HASH,
        "engine_adapter_sequence": ADAPTER_SEQUENCE,
    }
    edit.update(overrides)
    return edit


def commit_payload(**overrides):
    payload = {
        "type": "engine_edit_commit",
        "kind": "set_component_field",
        "preview_id": PREVIEW_ID,
        "preview_cgs_hash": "hash-before",
        "cgs_hash": "hash-before",
        "schema_version": SCHEMA_VERSION,
        "runtime_world_hash": RUNTIME_HASH,
        "engine_adapter_sequence": ADAPTER_SEQUENCE,
        "mode_id": "mode_default",
        "actor_id": "actor_player",
        "component_type_id": 100,
        "component_name": "COMP_HEALTH_V1",
        "field_path": "current",
        "value": 72,
        "audit_ts": 123.0,
    }
    payload.update(overrides)
    return payload


class EngineEditRouterTests(unittest.TestCase):
    def test_static_precommit_conflict_reason_blocks_graph_hazard(self):
        original = sample_cgs()
        proposed = copy.deepcopy(original)
        proposed["modes"][0]["systems"].append({
            "id": "other_health_system",
            "phase": "Simulation",
            "reads": [100],
            "writes": [100],
            "depends_on": [],
            "deterministic": True,
        })

        reason = _static_precommit_conflict_reason(original, proposed, {"operations": []})

        self.assertIn("StaticMutationConflict", reason)
        self.assertIn("Same-phase systems", reason)

    def test_engine_edit_ack_includes_audit_record(self):
        sm = FakeSessionManager()
        runtime = FakeRuntimeControl(accepted=True)
        router = WSMessageRouter(sm, runtime)
        sent = []

        async def send_fn(message):
            sent.append(message)

        asyncio.run(router.route(
            "session-1",
            {
                "type": "engine_edit",
                "kind": "set_component_field",
                "entity_id": "7",
                "component_type_id": 1,
                "field_path": "position.x",
                "value": 12.5,
                "source": "test",
            },
            send_fn,
            None,
            {},
        ))

        self.assertEqual(len(runtime.calls), 1)
        self.assertEqual(sent[-1]["type"], "engine_edit_ack")
        self.assertTrue(sent[-1]["accepted"])
        self.assertEqual(sent[-1]["audit"]["entity_id"], "7")
        self.assertEqual(sent[-1]["audit"]["field_path"], "position.x")
        self.assertEqual(sent[-1]["audit"]["value"], 12.5)
        self.assertEqual(sent[-1]["audit"]["source"], "test")
        self.assertEqual(sm.session.engine_edit_log[-1]["runtime_tick"], 4)
        self.assertEqual(sm.session.engine_edit_log[-1]["runtime_world_hash"], RUNTIME_HASH)
        self.assertEqual(sm.session.engine_edit_log[-1]["engine_adapter_sequence"], ADAPTER_SEQUENCE)
        self.assertTrue(sm.session.engine_edit_log[-1]["preview_id"].startswith("engine-preview-"))
        self.assertEqual(sent[-1]["audit"]["mode_id"], "")

    def test_unknown_engine_edit_kind_is_rejected_before_runtime(self):
        sm = FakeSessionManager()
        runtime = FakeRuntimeControl()
        router = WSMessageRouter(sm, runtime)
        sent = []

        async def send_fn(message):
            sent.append(message)

        asyncio.run(router.route(
            "session-1",
            {"type": "engine_edit", "kind": "teleport_everything", "entity_id": "7"},
            send_fn,
            None,
            {},
        ))

        self.assertEqual(runtime.calls, [])
        self.assertEqual(sent[-1]["type"], "engine_edit_ack")
        self.assertFalse(sent[-1]["accepted"])

    def test_engine_edit_commit_builds_gde_value_mutation_and_updates_cgs(self):
        sm = FakeSessionManager()
        sm.session.engine_edit_log.append({"ts": 123.0, **accepted_live_edit()})
        router = WSMessageRouter(sm, FakeRuntimeControl())
        persist = FakePersistence()
        cgs = sample_cgs()
        sent = []

        async def send_fn(message):
            sent.append(message)

        asyncio.run(router.route(
            "session-1",
            commit_payload(),
            send_fn,
            persist,
            cgs,
        ))

        self.assertEqual(len(sm.apply_calls), 1)
        txn = sm.apply_calls[0][1]
        self.assertEqual(
            txn["operations"][0]["path"],
            "modes.mode_default.actors.actor_player.components.100.defaults.current",
        )
        self.assertEqual(txn["operations"][0]["value"], 72)
        self.assertEqual(txn["affected_systems"], ["health_system"])
        self.assertEqual(len(persist.saved), 1)
        self.assertEqual(len(persist.snapshots), 1)
        self.assertEqual(sent[-2]["type"], "cgs_update")
        self.assertEqual(sent[-2]["transaction_id"], "txn-000000000001")
        self.assertEqual(sent[-2]["version_ids"]["cgs_hash"], LIVE_COMMIT_HASH)
        self.assertEqual(sent[-1]["type"], "engine_edit_commit_ack")
        self.assertTrue(sent[-1]["accepted"])
        self.assertEqual(sent[-1]["cgs_hash"], LIVE_COMMIT_HASH)
        self.assertEqual(persist.audit[-1][1]["outcome"], "applied")
        self.assertEqual(persist.audit[-1][1]["pre_state_hash"], "hash-before")
        self.assertEqual(persist.audit[-1][1]["post_state_hash"], LIVE_COMMIT_HASH)
        self.assertEqual(txn["preview_id"], PREVIEW_ID)
        self.assertEqual(sent[-1]["preview_id"], PREVIEW_ID)
        self.assertTrue(sm.session.engine_edit_log[-1]["committed"])

    def test_engine_edit_commit_merges_primitive_default_after_newer_cgs(self):
        sm = FakeSessionManager()
        sm.session.engine_edit_log.append({"ts": 123.0, **accepted_live_edit(preview_cgs_hash="older-hash")})
        router = WSMessageRouter(sm, FakeRuntimeControl())
        persist = FakePersistence()
        cgs = sample_cgs()
        sent = []

        async def send_fn(message):
            sent.append(message)

        asyncio.run(router.route(
            "session-1",
            commit_payload(preview_cgs_hash="older-hash"),
            send_fn,
            persist,
            cgs,
        ))

        self.assertEqual(len(sm.apply_calls), 1)
        self.assertTrue(sm.apply_calls[0][1]["merged_after_newer_cgs"])
        self.assertEqual(sent[-1]["type"], "engine_edit_commit_ack")
        self.assertTrue(sent[-1]["accepted"])

    def test_engine_edit_commit_requires_matching_accepted_audit(self):
        sm = FakeSessionManager()
        router = WSMessageRouter(sm, FakeRuntimeControl())
        sent = []

        async def send_fn(message):
            sent.append(message)

        asyncio.run(router.route(
            "session-1",
            commit_payload(component_name=""),
            send_fn,
            FakePersistence(),
            sample_cgs(),
        ))

        self.assertEqual(sm.apply_calls, [])
        self.assertEqual(sent[-1]["type"], "engine_edit_commit_ack")
        self.assertFalse(sent[-1]["accepted"])

    def test_engine_edit_commit_rejects_stale_cgs_hash_before_gde(self):
        sm = FakeSessionManager()
        sm.session.engine_edit_log.append({"ts": 123.0, **accepted_live_edit()})
        router = WSMessageRouter(sm, FakeRuntimeControl())
        persist = FakePersistence()
        cgs = sample_cgs()
        sent = []

        async def send_fn(message):
            sent.append(message)

        asyncio.run(router.route(
            "session-1",
            commit_payload(cgs_hash="0" * 64),
            send_fn,
            persist,
            cgs,
        ))

        self.assertEqual(sm.apply_calls, [])
        self.assertEqual(sent[-1]["type"], "engine_edit_commit_ack")
        self.assertFalse(sent[-1]["accepted"])
        self.assertIn("Stale CGS write rejected", sent[-1]["reason"])
        self.assertEqual(persist.audit, [])

    def test_engine_edit_commit_requires_preview_id_envelope(self):
        sm = FakeSessionManager()
        sm.session.engine_edit_log.append({"ts": 123.0, **accepted_live_edit()})
        router = WSMessageRouter(sm, FakeRuntimeControl())
        sent = []

        async def send_fn(message):
            sent.append(message)

        payload = commit_payload()
        payload.pop("preview_id")
        asyncio.run(router.route("session-1", payload, send_fn, FakePersistence(), sample_cgs()))

        self.assertEqual(sm.apply_calls, [])
        self.assertFalse(sent[-1]["accepted"])
        self.assertIn("preview_id", sent[-1]["reason"])

    def test_engine_edit_commit_rejects_stale_runtime_hash_before_gde(self):
        sm = FakeSessionManager()
        sm.session.update_runtime_status(
            connected=True,
            last_tick={"tick": 4, "world_hash": "new-runtime-hash", "engine_adapter_sequence": ADAPTER_SEQUENCE},
            last_hash="new-runtime-hash",
        )
        sm.session.engine_edit_log.append({"ts": 123.0, **accepted_live_edit()})
        router = WSMessageRouter(sm, FakeRuntimeControl())
        sent = []

        async def send_fn(message):
            sent.append(message)

        asyncio.run(router.route("session-1", commit_payload(), send_fn, FakePersistence(), sample_cgs()))

        self.assertEqual(sm.apply_calls, [])
        self.assertFalse(sent[-1]["accepted"])
        self.assertIn("runtime hash", sent[-1]["reason"])

    def test_engine_edit_commit_rejects_stale_adapter_sequence_before_gde(self):
        sm = FakeSessionManager()
        sm.session.update_runtime_status(
            connected=True,
            last_tick={"tick": 4, "world_hash": RUNTIME_HASH, "engine_adapter_sequence": ADAPTER_SEQUENCE + 1},
            last_hash=RUNTIME_HASH,
        )
        sm.session.engine_edit_log.append({"ts": 123.0, **accepted_live_edit()})
        router = WSMessageRouter(sm, FakeRuntimeControl())
        sent = []

        async def send_fn(message):
            sent.append(message)

        asyncio.run(router.route("session-1", commit_payload(), send_fn, FakePersistence(), sample_cgs()))

        self.assertEqual(sm.apply_calls, [])
        self.assertFalse(sent[-1]["accepted"])
        self.assertIn("adapter sequence", sent[-1]["reason"])

    def test_engine_edit_commit_rejects_stale_schema_and_preview_id_before_gde(self):
        sm = FakeSessionManager()
        sm.session.engine_edit_log.append({"ts": 123.0, **accepted_live_edit(preview_schema_version="0.0.9")})
        router = WSMessageRouter(sm, FakeRuntimeControl())
        sent = []

        async def send_fn(message):
            sent.append(message)

        asyncio.run(router.route("session-1", commit_payload(), send_fn, FakePersistence(), sample_cgs()))
        self.assertEqual(sm.apply_calls, [])
        self.assertFalse(sent[-1]["accepted"])
        self.assertIn("schema_version", sent[-1]["reason"])

        sent.clear()
        sm.session.engine_edit_log[-1] = {"ts": 123.0, **accepted_live_edit()}
        asyncio.run(router.route(
            "session-1",
            commit_payload(preview_id="engine-preview-stale"),
            send_fn,
            FakePersistence(),
            sample_cgs(),
        ))
        self.assertEqual(sm.apply_calls, [])
        self.assertFalse(sent[-1]["accepted"])
        self.assertIn("accepted audit row", sent[-1]["reason"])

    def test_engine_edit_commit_rejects_preview_only_commit_classes(self):
        sm = FakeSessionManager()
        router = WSMessageRouter(sm, FakeRuntimeControl())
        sent = []

        async def send_fn(message):
            sent.append(message)

        asyncio.run(router.route(
            "session-1",
            commit_payload(kind="focus_entity"),
            send_fn,
            FakePersistence(),
            sample_cgs(),
        ))

        self.assertEqual(sm.apply_calls, [])
        self.assertFalse(sent[-1]["accepted"])
        self.assertIn("preview-only", sent[-1]["reason"])

    def test_engine_edit_commit_failure_leaves_preview_recoverable(self):
        class FailingSessionManager(FakeSessionManager):
            def apply_via_gde(self, session_id, txn, current_cgs):
                self.apply_calls.append((session_id, txn))
                return SimpleNamespace(
                    success=False,
                    new_cgs=current_cgs,
                    new_hash="",
                    error="simulated GDE failure",
                    warnings=[],
                    used_gde=True,
                )

        sm = FailingSessionManager()
        sm.session.engine_edit_log.append({"ts": 123.0, **accepted_live_edit()})
        router = WSMessageRouter(sm, FakeRuntimeControl())
        persist = FakePersistence()
        sent = []

        async def send_fn(message):
            sent.append(message)

        asyncio.run(router.route("session-1", commit_payload(), send_fn, persist, sample_cgs()))

        self.assertEqual(len(sm.apply_calls), 1)
        self.assertFalse(sent[-1]["accepted"])
        self.assertEqual(persist.saved, [])
        self.assertFalse(sm.session.engine_edit_log[-1].get("committed", False))

    def test_merge_rules_allow_only_primitive_component_defaults(self):
        self.assertTrue(
            can_merge_engine_default_edit(
                "modes.mode_default.actors.actor_player.components.100.defaults.current",
                72,
            )
        )
        self.assertFalse(
            can_merge_engine_default_edit(
                "modes.mode_default.actors.actor_player.components.100",
                {"defaults": {"current": 72}},
            )
        )
        self.assertFalse(can_merge_engine_default_edit("global_systems.health_system", True))


if __name__ == "__main__":
    unittest.main()
