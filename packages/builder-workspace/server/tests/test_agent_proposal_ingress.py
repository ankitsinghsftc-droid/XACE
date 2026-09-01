import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from agent_host.contracts import (  # noqa: E402
    AgentProposalEnvelope,
    AgentProposalKind,
    AgentRiskLevel,
    AgentSessionHandle,
)
from agent_host.proposal_ingress import (  # noqa: E402
    AGENT_PENDING_PREVIEW_SCHEMA,
    AGENT_PROPOSAL_INGRESS_SCHEMA,
    AgentProposalIngressGate,
    PROMPT_DIFF_PREVIEW_SCHEMA,
)
from agent_host.session_store import AgentSessionStore, AgentStoredSession  # noqa: E402


CGS_HASH = "a" * 64
STALE_CGS_HASH = "b" * 64
FAKE_SECRET = "sk-agentproposal000000000000"


def _cgs() -> dict:
    return {
        "metadata": {
            "name": "Agent Proposal Test",
            "version": "0.1.0",
            "schema_version": "0.1.0",
            "cgs_hash": CGS_HASH,
        },
        "component_schemas": [
            {
                "type_id": 1,
                "name": "COMP_TRANSFORM_V1",
                "defaults": {"x": 0, "y": 0},
                "source": "ucl",
            },
            {
                "type_id": 5,
                "name": "COMP_VELOCITY_V1",
                "defaults": {"max_linear_speed": 1000000},
                "source": "ucl",
            },
        ],
        "global_systems": [],
        "semantic_events": [],
        "assets": [],
        "modes": [
            {
                "id": "mode_gameplay",
                "is_default": True,
                "actors": [
                    {
                        "id": "actor_player",
                        "actor_type": "PlayerCharacter",
                        "control_type": "Human",
                        "components": [
                            {
                                "type_id": 1,
                                "name": "COMP_TRANSFORM_V1",
                                "defaults": {"x": 0, "y": 0},
                            },
                            {
                                "type_id": 5,
                                "name": "COMP_VELOCITY_V1",
                                "defaults": {"max_linear_speed": 1000000},
                            },
                        ],
                    }
                ],
                "systems": [],
                "rules": [],
            }
        ],
    }


def _typed_operations() -> list[dict]:
    return [
        {
            "operation_id": "declare.energy",
            "kind": "declare_component",
            "explanation": "Declare deterministic fixed-point energy state.",
            "component_type_id": 10000,
            "component_name": "COMP_ENERGY_V1",
            "version": "1.0.0",
            "fields": [
                {"name": "current", "field_type": "fixed", "default": 1000000},
                {"name": "maximum", "field_type": "fixed", "default": 1000000},
            ],
        },
        {
            "operation_id": "attach.energy",
            "kind": "add_component",
            "explanation": "Attach energy state to the player.",
            "mode_id": "mode_gameplay",
            "actor_id": "actor_player",
            "component_type_id": 10000,
            "component_name": "COMP_ENERGY_V1",
            "defaults": [
                {"field_name": "current", "field_type": "fixed", "value": 750000}
            ],
            "use_schema_defaults": True,
        },
        {
            "operation_id": "set.energy_maximum",
            "kind": "set_defaults",
            "explanation": "Set the player's initial maximum energy.",
            "mode_id": "mode_gameplay",
            "actor_id": "actor_player",
            "component_type_id": 10000,
            "assignments": [
                {"field_name": "maximum", "field_type": "fixed", "value": 1250000}
            ],
        },
    ]


def _proposal(**overrides) -> AgentProposalEnvelope:
    fields = {
        "proposal_id": "proposal-energy",
        "session_id": "session-1",
        "provider_id": "mock",
        "base_cgs_hash": CGS_HASH,
        "intent": "Add a small deterministic energy resource.",
        "summary": "Add a typed energy component and player defaults.",
        "operations": tuple(_typed_operations()),
        "proposal_kind": AgentProposalKind.MUTATION,
        "risk_level": AgentRiskLevel.MEDIUM,
        "metadata": {"confidence": 0.88, "model": "mock-agent"},
    }
    fields.update(overrides)
    return AgentProposalEnvelope(**fields)


def _store(temp_dir: str) -> AgentSessionStore:
    store = AgentSessionStore(temp_dir)
    handle = AgentSessionHandle(
        xace_session_id="session-1",
        provider_id="mock",
        provider_session_id="mock-thread-session-1",
        base_cgs_hash=CGS_HASH,
        latest_cgs_hash=CGS_HASH,
    )
    store.upsert_session(AgentStoredSession.from_handle(handle))
    return store


class AgentProposalIngressTests(unittest.TestCase):
    def test_rejects_malformed_raw_proposal_without_mutating_session(self) -> None:
        session = SimpleNamespace(
            pending_txn=None,
            pending_prompt_preview=None,
            pending_prompt_result=None,
        )
        gate = AgentProposalIngressGate(clock=lambda: 1.0, token_factory=lambda: "apt-test")

        result = gate.ingest(
            {"proposal_id": "bad", "session_id": "session-1"},
            current_cgs=_cgs(),
            xace_session_id="session-1",
            session=session,
        )

        self.assertFalse(result.accepted)
        self.assertEqual(result.code, "MALFORMED_PROPOSAL")
        self.assertIsNone(session.pending_txn)
        self.assertEqual(result.schema, AGENT_PROPOSAL_INGRESS_SCHEMA)

    def test_rejects_stale_base_cgs_hash_and_logs_rejected_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = _store(temp_dir)
            gate = AgentProposalIngressGate(session_store=store)

            result = gate.ingest(
                _proposal(base_cgs_hash=STALE_CGS_HASH),
                current_cgs=_cgs(),
                current_cgs_hash=CGS_HASH,
                xace_session_id="session-1",
            )

            self.assertFalse(result.accepted)
            self.assertEqual(result.code, "STALE_CGS_HASH")
            stored = store.get_proposal("proposal-energy")
            self.assertIsNotNone(stored)
            assert stored is not None
            self.assertEqual(stored["status"], "rejected_stale_cgs_hash")

    def test_rejects_unsupported_legacy_or_direct_commit_operations(self) -> None:
        gate = AgentProposalIngressGate()
        legacy = _proposal(
            operations=(
                {
                    "operation_id": "legacy.path",
                    "kind": "set_defaults",
                    "op": "SET",
                    "path": "modes.mode_gameplay",
                    "explanation": "Try to use path patching.",
                },
            )
        )
        direct = _proposal(
            proposal_id="proposal-direct",
            metadata={"direct_gde_commit": True},
        )
        unsupported = _proposal(
            proposal_id="proposal-unsupported",
            operations=(
                {
                    "operation_id": "shell.try",
                    "kind": "run_shell",
                    "explanation": "Attempt a shell command.",
                },
            ),
        )

        legacy_result = gate.ingest(legacy, current_cgs=_cgs(), xace_session_id="session-1")
        direct_result = gate.ingest(direct, current_cgs=_cgs(), xace_session_id="session-1")
        unsupported_result = gate.ingest(
            unsupported,
            current_cgs=_cgs(),
            xace_session_id="session-1",
        )

        self.assertEqual(legacy_result.code, "DIRECT_COMMIT_DENIED")
        self.assertEqual(direct_result.code, "DIRECT_COMMIT_DENIED")
        self.assertEqual(unsupported_result.code, "UNSUPPORTED_OPERATION")
        self.assertFalse(legacy_result.accepted)
        self.assertFalse(direct_result.accepted)
        self.assertFalse(unsupported_result.accepted)

    def test_creates_preview_only_pending_transaction_matching_prompt_preview_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_cgs = _cgs()
            before = json.dumps(original_cgs, sort_keys=True)
            store = _store(temp_dir)
            session = SimpleNamespace(
                pending_txn=None,
                pending_prompt_preview=None,
                pending_prompt_result=None,
                pending_prompt_clarification={"state": "old"},
                pending_clar_id="clar-old",
                runtime_connected=True,
                runtime_adapter_type="headless",
                runtime_last_hash="runtime-old",
                runtime_last_tick={"tick": 12},
                touched=False,
                touch=lambda: None,
            )
            gate = AgentProposalIngressGate(
                session_store=store,
                clock=lambda: 123.0,
                token_factory=lambda: "apt-test-token",
            )

            result = gate.ingest(
                _proposal(),
                current_cgs=original_cgs,
                xace_session_id="session-1",
                mode="AGENT",
                session=session,
            )

            self.assertTrue(result.preview_created)
            self.assertTrue(result.installed_on_session)
            self.assertEqual(result.preview["schema"], PROMPT_DIFF_PREVIEW_SCHEMA)
            self.assertEqual(result.preview["approval_required"], True)
            self.assertEqual(result.preview["direct_commit_allowed"], False)
            self.assertEqual(result.preview["preview_only"], True)
            self.assertEqual(
                result.preview["agent_proposal"]["schema"],
                AGENT_PENDING_PREVIEW_SCHEMA,
            )
            self.assertEqual(
                result.preview["agent_proposal"]["security_route"],
                "agent -> XACE tools -> typed proposal -> preview -> user/XACE approval -> GDE -> SGC -> runtime",
            )
            self.assertEqual(
                result.preview["cgs_diff"]["operations"][0]["operation_format"],
                "typed_cgs_v1",
            )
            self.assertEqual(
                result.preview["cgs_diff"]["operations"][0]["kind"],
                "declare_component",
            )
            self.assertNotIn("path", result.preview["cgs_diff"]["operations"][0])
            self.assertEqual(
                result.pending_txn["typed_operation_batch"]["operations"][1]["kind"],
                "add_component",
            )
            self.assertEqual(result.pending_txn["operations"], [])
            self.assertEqual(result.pending_txn["source"], "prompt")
            self.assertEqual(result.pending_txn["source_kind"], "agent_proposal")
            self.assertEqual(result.pending_txn["authority"]["direct_commit_allowed"], False)

            self.assertEqual(session.pending_txn, result.pending_txn)
            self.assertEqual(session.pending_prompt_preview, result.preview)
            self.assertEqual(session.pending_prompt_result["approval_required"], True)
            self.assertIsNone(session.pending_prompt_clarification)
            self.assertIsNone(session.pending_clar_id)
            self.assertEqual(json.dumps(original_cgs, sort_keys=True), before)

            stored = store.get_proposal("proposal-energy")
            self.assertIsNotNone(stored)
            assert stored is not None
            self.assertEqual(stored["status"], "pending_preview")

    def test_no_op_is_recorded_without_preview_or_pending_txn(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = _store(temp_dir)
            session = SimpleNamespace(
                pending_txn="unchanged",
                pending_prompt_preview="unchanged",
                pending_prompt_result="unchanged",
            )
            gate = AgentProposalIngressGate(session_store=store)

            result = gate.ingest(
                AgentProposalEnvelope(
                    proposal_id="proposal-noop",
                    session_id="session-1",
                    provider_id="mock",
                    base_cgs_hash=CGS_HASH,
                    intent="Inspect the project.",
                    summary="No changes needed.",
                    proposal_kind=AgentProposalKind.NO_OP,
                ),
                current_cgs=_cgs(),
                xace_session_id="session-1",
                session=session,
            )

            self.assertTrue(result.accepted)
            self.assertEqual(result.status, "no_op")
            self.assertEqual(result.preview, {})
            self.assertEqual(session.pending_txn, "unchanged")
            self.assertEqual(store.get_proposal("proposal-noop")["status"], "no_op")

    def test_redacts_secrets_from_preview_result_and_persistent_store(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = _store(temp_dir)
            gate = AgentProposalIngressGate(
                session_store=store,
                clock=lambda: 123.0,
                token_factory=lambda: "apt-test-token",
            )
            proposal = _proposal(
                proposal_id="proposal-secret",
                intent=f"Do not leak {FAKE_SECRET}",
                summary=f"Use a safe summary {FAKE_SECRET}",
                metadata={"model": "mock-agent", "secret": FAKE_SECRET},
            )

            result = gate.ingest(
                proposal,
                current_cgs=_cgs(),
                xace_session_id="session-1",
            )

            encoded = json.dumps(result.to_dict(), sort_keys=True)
            self.assertNotIn(FAKE_SECRET, encoded)

            persisted = b"".join(
                path.read_bytes()
                for path in (Path(temp_dir) / ".xace" / "agent_sessions").iterdir()
                if path.name.startswith("agent_sessions.sqlite3")
            )
            self.assertNotIn(FAKE_SECRET.encode("utf-8"), persisted)


if __name__ == "__main__":
    unittest.main()
