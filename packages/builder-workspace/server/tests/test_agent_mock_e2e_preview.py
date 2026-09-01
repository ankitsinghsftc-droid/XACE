import asyncio
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from agent_host.event_stream import AgentEventStreamManager  # noqa: E402
from agent_host.mock_agent import MockAgentAdapter  # noqa: E402
from agent_host.registry import AgentAdapterRegistry  # noqa: E402
from agent_host.session_store import AgentSessionStore  # noqa: E402
from ws_message_router import WSMessageRouter  # noqa: E402


CGS_HASH = "e" * 64
NEW_CGS_HASH = "f" * 64


def _cgs() -> dict:
    return {
        "metadata": {
            "name": "AG-008 Mock Agent E2E",
            "version": "0.1.0",
            "schema_version": "0.1.0",
            "cgs_hash": CGS_HASH,
        },
        "component_schemas": [],
        "global_systems": [],
        "semantic_events": [],
        "assets": [],
        "modes": [],
    }


def _builder_session() -> SimpleNamespace:
    return SimpleNamespace(
        project_path="C:/tmp/xace-agent-mock-e2e",
        pending_txn=None,
        pending_prompt_preview=None,
        pending_prompt_result=None,
        pending_prompt_clarification=None,
        pending_clar_id=None,
        prompt_preview_approval_log=[],
        engine_edit_log=[],
        runtime_connected=False,
        runtime_adapter_type="",
        runtime_engine_version="",
        runtime_last_tick=None,
        runtime_last_hash="",
        touch=lambda: None,
    )


class _FakePersistence:
    def __init__(self, cgs: dict) -> None:
        self._root = Path("agent-mock-e2e-test")
        self.disk_cgs = copy.deepcopy(cgs)
        self.snapshots: list[tuple[dict, object]] = []
        self.plans: dict[str, str] = {}
        self.proof_bundles: list[tuple[dict, str, dict | None]] = []
        self.audit: list[tuple[dict, dict]] = []
        self.prompt_history: list[dict] = []
        self.transaction_sequence = 0

    def next_transaction_id(self) -> str:
        self.transaction_sequence += 1
        return f"txn.agent.mock.{self.transaction_sequence}"

    def current_cgs_hash(self) -> str:
        return str(self.disk_cgs["metadata"]["cgs_hash"])

    def load_execution_plan(self, cgs_hash: str) -> str | None:
        return self.plans.get(cgs_hash)

    def save(self, cgs: dict) -> None:
        self.disk_cgs = copy.deepcopy(cgs)

    def snapshot(self, cgs: dict, record: object) -> None:
        self.snapshots.append((copy.deepcopy(cgs), record))

    def save_execution_plan(
        self,
        cgs_hash: str,
        plan_json: str,
        *,
        cgs: dict,
        validation: dict | None = None,
    ) -> str:
        del cgs, validation
        self.plans[cgs_hash] = plan_json
        return plan_json

    def save_sgc_proof_bundle(
        self,
        cgs: dict,
        plan_json: str,
        validation: dict | None = None,
    ) -> None:
        self.proof_bundles.append((copy.deepcopy(cgs), plan_json, copy.deepcopy(validation)))

    def record_prompt_history_apply(self, **kwargs) -> dict:
        entry = {
            "schema": "xace.prompt_history.entry.v1",
            "sequence": len(self.prompt_history) + 1,
            "action": "apply",
            **copy.deepcopy(kwargs),
        }
        self.prompt_history.append(entry)
        return entry

    def prompt_history_state(self) -> dict:
        return {
            "schema": "xace.prompt_history.v1",
            "entries": copy.deepcopy(self.prompt_history),
        }

    def record_mutation_audit(self, *, ledger_entry: dict, dataset_entry: dict) -> None:
        self.audit.append((copy.deepcopy(ledger_entry), copy.deepcopy(dataset_entry)))


class _FakeSessionManager:
    def __init__(self) -> None:
        self._sessions = {"session-1": _builder_session()}
        self.applied_txn: dict | None = None
        self.compile_calls = 0
        self.cleared = 0

    def validate_prompt_preview_approval(self, session_id: str, message: dict) -> dict:
        session = self._sessions[session_id]
        preview = session.pending_prompt_preview
        approval = message.get("approval") if isinstance(message.get("approval"), dict) else {}
        if not isinstance(preview, dict):
            return {"accepted": False, "message": "No preview is pending."}
        if approval.get("preview_id") != preview.get("preview_id"):
            return {"accepted": False, "message": "Preview ID does not match."}
        if approval.get("approval_token") != preview.get("approval_token"):
            return {"accepted": False, "message": "Approval token does not match."}
        record = {
            "schema": "xace.prompt_preview_approval.v1",
            "preview_id": approval["preview_id"],
            "approved": True,
            "approval_source": approval.get("approval_source", "test"),
            "approved_by": approval.get("approved_by", "test"),
        }
        session.prompt_preview_approval_log.append(record)
        return {"accepted": True, "approval": record}

    def apply_via_gde(self, session_id: str, txn: dict, cgs_state: dict):
        del session_id
        self.applied_txn = copy.deepcopy(txn)
        from typed_operations import apply_typed_operation_batch, parse_typed_operation_batch

        batch = parse_typed_operation_batch(txn["typed_operation_batch"])
        result = apply_typed_operation_batch(batch, cgs_state)
        new_cgs = copy.deepcopy(result.proposed_cgs)
        new_cgs.setdefault("metadata", {})["cgs_hash"] = NEW_CGS_HASH
        return SimpleNamespace(
            success=True,
            new_cgs=new_cgs,
            new_hash=NEW_CGS_HASH,
            snapshot={"typed_operation_ids": ["declare.mock_resource.0001"]},
            error="",
            warnings=[],
            used_gde=True,
        )

    def compile_sgc_plan(self, cgs: dict):
        del cgs
        self.compile_calls += 1
        return SimpleNamespace(
            ok=True,
            failed=False,
            plan_json='{"schema":"xace.execution_plan.v1","systems":[]}',
            validation={"ok": True, "load_ready": True, "rollback_compatible": True},
            error={},
        )

    def clear_pending(self, session_id: str) -> None:
        session = self._sessions[session_id]
        session.pending_txn = None
        session.pending_prompt_preview = None
        session.pending_prompt_result = None
        session.pending_prompt_clarification = None
        session.pending_clar_id = None
        self.cleared += 1


async def _send(messages: list[dict], message: dict) -> None:
    messages.append(message)


async def _start_mock_turn(store: AgentSessionStore):
    messages: list[dict] = []
    cgs_state = _cgs()
    persist = _FakePersistence(cgs_state)
    session_manager = _FakeSessionManager()
    event_stream = AgentEventStreamManager(
        AgentAdapterRegistry([MockAgentAdapter()]),
        session_store=store,
    )
    router = WSMessageRouter(session_manager, agent_event_stream=event_stream)
    await router.route(
        "session-1",
        {
            "type": "agent_turn",
            "provider_id": "mock",
            "prompt": "Add the deterministic mock resource preview.",
            "cgs_hash": CGS_HASH,
            "allowed_tools": ["xace.read_cgs", "xace.submit_proposal"],
            "mode": "AGENT",
        },
        lambda message: _send(messages, message),
        persist,
        cgs_state,
    )
    await event_stream.wait_for_turn("session-1")
    return router, session_manager, event_stream, persist, cgs_state, messages


def _preview_message(messages: list[dict]) -> dict:
    previews = [message for message in messages if message.get("type") == "pil_result"]
    if len(previews) != 1:
        raise AssertionError(f"expected one preview message, got {previews!r}")
    return previews[0]


def _approval_from_preview(preview: dict) -> dict:
    return {
        "schema": "xace.prompt_preview_approval.v1",
        "preview_id": preview["preview_id"],
        "approval_token": preview["approval_token"],
        "approval_source": "ag008_test",
        "approved_by": "session-1",
    }


class AgentMockE2EPreviewTests(unittest.TestCase):
    def test_mock_turn_reaches_existing_approval_preview_without_mutating_cgs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = AgentSessionStore(temp_dir, audit_jsonl=True)

            _router, session_manager, _event_stream, persist, _cgs_state, messages = asyncio.run(
                _start_mock_turn(store)
            )

            preview_message = _preview_message(messages)
            result = preview_message["result"]
            session = session_manager._sessions["session-1"]

            self.assertEqual(result["kind"], "mutation")
            self.assertEqual(result["source"], "agent_proposal")
            self.assertEqual(result["proposal_id"], "mock-proposal-0001")
            self.assertEqual(result["preview"]["preview_only"], True)
            self.assertEqual(
                result["preview"]["agent_proposal"]["security_route"],
                "agent -> XACE tools -> typed proposal -> preview -> user/XACE approval -> GDE -> SGC -> runtime",
            )
            self.assertEqual(
                result["preview"]["cgs_diff"]["operations"][0]["kind"],
                "declare_component",
            )
            self.assertNotIn("path", result["preview"]["cgs_diff"]["operations"][0])
            self.assertEqual(session.pending_txn["source_kind"], "agent_proposal")
            self.assertEqual(session.pending_txn["operations"], [])
            self.assertFalse(session.pending_txn["authority"]["allow_raw_shell"])
            self.assertEqual(persist.disk_cgs["metadata"]["cgs_hash"], CGS_HASH)

            stored = store.get_proposal("mock-proposal-0001")
            self.assertIsNotNone(stored)
            assert stored is not None
            self.assertEqual(stored["status"], "pending_preview")

    def test_discarded_mock_proposal_is_audited_and_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = AgentSessionStore(temp_dir, audit_jsonl=True)
            router, session_manager, _event_stream, persist, cgs_state, messages = asyncio.run(
                _start_mock_turn(store)
            )
            self.assertEqual(_preview_message(messages)["result"]["proposal_id"], "mock-proposal-0001")

            async def scenario() -> None:
                await router.route(
                    "session-1",
                    {"type": "pil_discard", "actor": "builder_review"},
                    lambda message: _send(messages, message),
                    persist,
                    cgs_state,
                )

            asyncio.run(scenario())

            acks = [message for message in messages if message.get("type") == "pil_discard_ack"]
            self.assertEqual(len(acks), 1)
            self.assertEqual(acks[0]["agent_proposal_discard"]["status"], "discarded")
            self.assertTrue(acks[0]["agent_proposal_discard"]["logged"])
            self.assertIsNone(session_manager._sessions["session-1"].pending_txn)

            stored = store.get_proposal("mock-proposal-0001")
            self.assertIsNotNone(stored)
            assert stored is not None
            self.assertEqual(stored["status"], "discarded")

            _ledger, dataset = persist.audit[-1]
            self.assertEqual(dataset["mutation_path"], "agent_proposal_discard")
            self.assertEqual(dataset["outcome"], "discarded")
            self.assertEqual(dataset["operations"][0]["kind"], "declare_component")

            audit_jsonl = Path(temp_dir) / ".xace" / "agent_sessions" / "agent_sessions.audit.jsonl"
            self.assertIn("proposal_status_updated", audit_jsonl.read_text(encoding="utf-8"))

    def test_approved_mock_proposal_uses_pil_apply_and_records_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = AgentSessionStore(temp_dir, audit_jsonl=True)
            router, session_manager, _event_stream, persist, cgs_state, messages = asyncio.run(
                _start_mock_turn(store)
            )
            preview = _preview_message(messages)["result"]["preview"]

            async def scenario() -> None:
                await router.route(
                    "session-1",
                    {
                        "type": "pil_apply",
                        "approval": _approval_from_preview(preview),
                        "actor": "builder_review",
                    },
                    lambda message: _send(messages, message),
                    persist,
                    cgs_state,
                )

            asyncio.run(scenario())

            updates = [message for message in messages if message.get("type") == "cgs_update"]
            self.assertEqual(len(updates), 1, messages)
            update = updates[0]
            self.assertTrue(update["gde_used"])
            self.assertTrue(update["execution_plan_available"])
            self.assertTrue(update["apply_feedback"]["sgc"]["required"])
            self.assertEqual(update["agent_proposal_apply"]["status"], "applied")
            self.assertEqual(update["agent_proposal_apply"]["proposal_id"], "mock-proposal-0001")
            self.assertEqual(session_manager.compile_calls, 1)
            self.assertIsNotNone(session_manager.applied_txn)
            assert session_manager.applied_txn is not None
            self.assertEqual(
                session_manager.applied_txn["typed_operation_batch"]["operations"][0]["kind"],
                "declare_component",
            )
            self.assertEqual(cgs_state["metadata"]["cgs_hash"], NEW_CGS_HASH)
            self.assertEqual(
                cgs_state["component_schemas"][0]["name"],
                "COMP_MOCK_RESOURCE_0001_V1",
            )
            self.assertIsNone(session_manager._sessions["session-1"].pending_txn)

            stored = store.get_proposal("mock-proposal-0001")
            self.assertIsNotNone(stored)
            assert stored is not None
            self.assertEqual(stored["status"], "applied")
            self.assertEqual(stored["mutation_transaction_id"], update["transaction_id"])

            mutations = store.list_mutations("session-1", proposal_id="mock-proposal-0001")
            self.assertEqual(len(mutations), 1)
            self.assertEqual(mutations[0].status, "applied")
            self.assertEqual(mutations[0].result_cgs_hash, NEW_CGS_HASH)
            self.assertEqual(mutations[0].gde_transaction_id, update["transaction_id"])

            _ledger, dataset = persist.audit[-1]
            self.assertEqual(dataset["mutation_path"], "pil_apply")
            self.assertEqual(dataset["outcome"], "applied")
            self.assertEqual(dataset["typed_operation_provenance"]["operation_kinds"], ["declare_component"])


if __name__ == "__main__":
    unittest.main()
