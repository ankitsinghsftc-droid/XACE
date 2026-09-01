import sys
import tempfile
import unittest
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from agent_host.contracts import (  # noqa: E402
    AgentEvent,
    AgentEventType,
    AgentProposalEnvelope,
    AgentProposalKind,
    AgentRiskLevel,
    AgentSessionHandle,
)
from agent_host.session_store import (  # noqa: E402
    AGENT_SESSION_AUDIT_FILENAME,
    AGENT_SESSION_DB_FILENAME,
    AGENT_SESSION_STORE_SCHEMA,
    AgentMutationLineageRecord,
    AgentSessionStore,
    AgentSessionStoreError,
    AgentStoredSession,
    AgentToolCallRecord,
)
from secret_redaction import REDACTED_SECRET  # noqa: E402


CGS_HASH = "a" * 64
NEXT_CGS_HASH = "b" * 64
FIXED_TIME = "2026-08-31T00:00:00Z"
FAKE_SECRET = "sk-testsecret000000000000"


def _handle(
    xace_session_id: str = "session-1",
    provider_session_id: str = "mock-thread-session-1",
) -> AgentSessionHandle:
    return AgentSessionHandle(
        xace_session_id=xace_session_id,
        provider_id="mock",
        provider_session_id=provider_session_id,
        base_cgs_hash=CGS_HASH,
        latest_cgs_hash=CGS_HASH,
        created_at=FIXED_TIME,
        metadata={"source": "unit-test"},
    )


def _store_session(store: AgentSessionStore) -> None:
    store.upsert_session(
        AgentStoredSession.from_handle(
            _handle(),
            title="Main agent chat",
            summary="Session used by AG-003 tests.",
        )
    )


def _proposal(proposal_id: str = "proposal-1") -> AgentProposalEnvelope:
    return AgentProposalEnvelope(
        proposal_id=proposal_id,
        session_id="session-1",
        provider_id="mock",
        base_cgs_hash=CGS_HASH,
        intent="Inspect the project and propose nothing.",
        summary="No mutation is required.",
        proposal_kind=AgentProposalKind.NO_OP,
        risk_level=AgentRiskLevel.LOW,
        metadata={"source": "unit-test"},
    )


class AgentSessionStoreTests(unittest.TestCase):
    def test_sessions_survive_restart_and_branch_lineage_is_indexed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            store = AgentSessionStore(project_root)
            store.upsert_session(
                AgentStoredSession.from_handle(
                    _handle(),
                    title="Main agent chat",
                    summary="Root session.",
                    branch_name="main",
                )
            )
            store.upsert_session(
                AgentStoredSession.from_handle(
                    _handle(
                        xace_session_id="session-2",
                        provider_session_id="mock-thread-session-2",
                    ),
                    parent_xace_session_id="session-1",
                    parent_provider_session_id="mock-thread-session-1",
                    branch_name="fork-1",
                    title="Forked chat",
                )
            )

            self.assertTrue(
                (
                    project_root
                    / ".xace"
                    / "agent_sessions"
                    / AGENT_SESSION_DB_FILENAME
                ).exists()
            )

            reopened = AgentSessionStore(project_root)
            root = reopened.get_session("session-1")
            self.assertIsNotNone(root)
            assert root is not None
            self.assertEqual(root.to_handle(), _handle())

            by_provider = reopened.find_session_by_provider(
                "mock",
                "mock-thread-session-2",
            )
            self.assertIsNotNone(by_provider)
            assert by_provider is not None
            self.assertEqual(by_provider.parent_xace_session_id, "session-1")

            forks = reopened.list_sessions(parent_xace_session_id="session-1")
            self.assertEqual([session.xace_session_id for session in forks], ["session-2"])
            self.assertEqual(forks[0].branch_name, "fork-1")

    def test_events_tool_calls_proposals_and_mutations_are_queryable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = AgentSessionStore(temp_dir)
            _store_session(store)

            event = AgentEvent(
                event_id="event-1",
                event_type=AgentEventType.STATUS,
                session_id="session-1",
                provider_id="mock",
                sequence=1,
                message="Reading controlled XACE context.",
                data={"phase": "context"},
                created_at=FIXED_TIME,
            )
            store.record_event(event)
            self.assertEqual(store.list_events("session-1"), (event,))
            self.assertEqual(
                store.list_events(
                    "session-1",
                    event_type=AgentEventType.STATUS.value,
                ),
                (event,),
            )

            tool_call = AgentToolCallRecord(
                tool_call_id="toolcall-1",
                xace_session_id="session-1",
                provider_id="mock",
                tool_name="xace.read_cgs",
                permission="read_only",
                transport="mcp",
                status="completed",
                event_id="event-1",
                cgs_hash=CGS_HASH,
                request={"scope": "world"},
                response={"ok": True},
                created_at=FIXED_TIME,
                completed_at=FIXED_TIME,
            )
            store.record_tool_call(tool_call)
            self.assertEqual(
                store.list_tool_calls("session-1", tool_name="xace.read_cgs"),
                (tool_call,),
            )

            store.record_proposal(_proposal(), status="pending")
            store.update_proposal_status(
                "proposal-1",
                status="approved",
                approval_id="approval-1",
                mutation_transaction_id="txn-1",
            )
            proposal = store.get_proposal("proposal-1")
            self.assertIsNotNone(proposal)
            assert proposal is not None
            self.assertEqual(proposal["status"], "approved")
            self.assertEqual(proposal["approval_id"], "approval-1")
            self.assertEqual(proposal["payload"]["proposal_kind"], "no_op")

            mutation = AgentMutationLineageRecord(
                mutation_id="mutation-1",
                proposal_id="proposal-1",
                xace_session_id="session-1",
                provider_id="mock",
                base_cgs_hash=CGS_HASH,
                result_cgs_hash=NEXT_CGS_HASH,
                gde_transaction_id="gde-txn-1",
                status="applied",
                summary="Applied approved typed proposal through GDE.",
                sgc_plan_id="sgc-plan-1",
                runtime_validation_id="runtime-validation-1",
                created_at=FIXED_TIME,
            )
            store.record_mutation_lineage(mutation)
            self.assertEqual(store.list_mutations("session-1"), (mutation,))
            self.assertEqual(
                store.list_mutations("session-1", proposal_id="proposal-1"),
                (mutation,),
            )

            exported = store.export_session("session-1")
            self.assertEqual(exported["schema"], AGENT_SESSION_STORE_SCHEMA)
            self.assertEqual(exported["session"]["xace_session_id"], "session-1")
            self.assertEqual(len(exported["events"]), 1)
            self.assertEqual(len(exported["tool_calls"]), 1)
            self.assertEqual(len(exported["proposals"]), 1)
            self.assertEqual(len(exported["mutations"]), 1)

    def test_payloads_are_redacted_in_sqlite_and_audit_jsonl(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            store = AgentSessionStore(project_root, audit_jsonl=True)
            store.upsert_session(
                AgentStoredSession.from_handle(
                    _handle(),
                    metadata={"api_key": FAKE_SECRET},
                )
            )
            store.record_event(
                AgentEvent(
                    event_id="event-1",
                    event_type=AgentEventType.STATUS,
                    session_id="session-1",
                    provider_id="mock",
                    sequence=1,
                    message=f"never persist {FAKE_SECRET}",
                    data={"authorization": f"Bearer {FAKE_SECRET}"},
                    created_at=FIXED_TIME,
                )
            )
            store.record_tool_call(
                AgentToolCallRecord(
                    tool_call_id="toolcall-1",
                    xace_session_id="session-1",
                    provider_id="mock",
                    tool_name="xace.read_cgs",
                    permission="read_only",
                    transport="mcp",
                    status="completed",
                    request={"token": FAKE_SECRET},
                    response={"detail": f"api-key: {FAKE_SECRET}"},
                    created_at=FIXED_TIME,
                )
            )
            store.record_proposal(
                AgentProposalEnvelope(
                    proposal_id="proposal-1",
                    session_id="session-1",
                    provider_id="mock",
                    base_cgs_hash=CGS_HASH,
                    intent=f"avoid leaking {FAKE_SECRET}",
                    summary="No mutation is required.",
                    proposal_kind=AgentProposalKind.NO_OP,
                    metadata={"secret": FAKE_SECRET},
                )
            )
            store.record_mutation_lineage(
                AgentMutationLineageRecord(
                    mutation_id="mutation-1",
                    proposal_id="proposal-1",
                    xace_session_id="session-1",
                    provider_id="mock",
                    base_cgs_hash=CGS_HASH,
                    result_cgs_hash=NEXT_CGS_HASH,
                    gde_transaction_id="gde-txn-1",
                    status="applied",
                    summary="Applied proposal.",
                    metadata={"refresh_token": FAKE_SECRET},
                    created_at=FIXED_TIME,
                )
            )

            persisted = b"".join(
                path.read_bytes()
                for path in (project_root / ".xace" / "agent_sessions").iterdir()
                if path.name.startswith(AGENT_SESSION_DB_FILENAME)
                or path.name == AGENT_SESSION_AUDIT_FILENAME
            )
            self.assertNotIn(FAKE_SECRET.encode("utf-8"), persisted)
            self.assertIn(REDACTED_SECRET.encode("utf-8"), persisted)

    def test_corrupt_sqlite_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            store_dir = project_root / ".xace" / "agent_sessions"
            store_dir.mkdir(parents=True)
            (store_dir / AGENT_SESSION_DB_FILENAME).write_text(
                "not sqlite",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                AgentSessionStoreError,
                "unavailable or corrupt",
            ):
                AgentSessionStore(project_root)

    def test_history_rejects_unknown_sessions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = AgentSessionStore(temp_dir)
            with self.assertRaisesRegex(AgentSessionStoreError, "unknown agent session"):
                store.record_event(
                    AgentEvent(
                        event_id="event-1",
                        event_type=AgentEventType.STATUS,
                        session_id="session-1",
                        provider_id="mock",
                        sequence=1,
                        message="No session exists yet.",
                        created_at=FIXED_TIME,
                    )
                )


if __name__ == "__main__":
    unittest.main()
