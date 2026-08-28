import asyncio
import copy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import ws_message_router as router_module  # noqa: E402
from ws_message_router import WSMessageRouter  # noqa: E402


OLD_HASH = "a" * 64
NEW_HASH = "b" * 64


def _typed_batch() -> dict:
    return {
        "schema": "xace.typed_cgs_operation_batch.v1",
        "request_id": "request.router.x10-030",
        "prompt_id": "prompt.router.x10-030",
        "summary": "Add a typed stamina gameplay slice.",
        "operations": [
            {
                "operation_id": "declare.stamina",
                "kind": "declare_component",
                "explanation": "Declare stamina state.",
                "component_type_id": 10000,
                "component_name": "COMP_STAMINA_V1",
            },
            {
                "operation_id": "attach.stamina",
                "kind": "add_component",
                "explanation": "Attach stamina to the player.",
                "mode_id": "mode_gameplay",
                "actor_id": "actor_player",
                "component_type_id": 10000,
                "component_name": "COMP_STAMINA_V1",
            },
            {
                "operation_id": "system.stamina",
                "kind": "add_system",
                "explanation": "Add deterministic stamina execution.",
                "system_id": "StaminaSystem",
            },
            {
                "operation_id": "event.stamina",
                "kind": "add_event",
                "explanation": "Declare the stamina event.",
                "event_name": "stamina.depleted",
            },
            {
                "operation_id": "rule.stamina",
                "kind": "add_rule",
                "explanation": "Add the depleted-state rule.",
                "mode_id": "mode_gameplay",
                "rule_id": "rule.stamina_depleted",
            },
            {
                "operation_id": "asset.stamina",
                "kind": "add_asset",
                "explanation": "Add depleted feedback.",
                "asset_id": "stamina_depleted_sfx_v1",
            },
            {
                "operation_id": "defaults.stamina",
                "kind": "set_defaults",
                "explanation": "Set player stamina defaults.",
                "mode_id": "mode_gameplay",
                "actor_id": "actor_player",
                "component_type_id": 10000,
            },
        ],
    }


def _typed_transaction() -> dict:
    return {
        "operation_format": "typed_cgs_v1",
        "typed_operation_batch": _typed_batch(),
        "operations": [],
        "required_recompile": False,
        "schema_delta_type": "value_mutation",
        "mutation_summary": "Add a typed stamina gameplay slice.",
        "risk_level": "medium",
        "affected_systems": [],
    }


def _session(txn: dict) -> SimpleNamespace:
    return SimpleNamespace(
        pending_txn=txn,
        pending_prompt_clarification=None,
        pending_clar_id=None,
        pending_prompt_preview={
            "preview_id": "preview.typed.router",
            "approval_token": "approval.typed.router",
        },
        pending_prompt_result={},
        prompt_preview_approval_log=[],
        engine_edit_log=[],
        runtime_connected=False,
        runtime_adapter_type="",
        runtime_engine_version="",
        runtime_last_tick=None,
        runtime_last_hash="",
    )


class _FakePersistence:
    def __init__(self, cgs: dict) -> None:
        self._root = Path("router-typed-test")
        self.disk_cgs = copy.deepcopy(cgs)
        self.snapshots = []
        self.plans: dict[str, str] = {}
        self.audit: list[tuple[dict, dict]] = []

    def next_transaction_id(self) -> str:
        return "txn.router.typed.1"

    def current_cgs_hash(self) -> str:
        return str(self.disk_cgs["metadata"]["cgs_hash"])

    def load_execution_plan(self, cgs_hash: str) -> str | None:
        return self.plans.get(cgs_hash)

    def save(self, cgs: dict) -> None:
        self.disk_cgs = copy.deepcopy(cgs)

    def snapshot(self, cgs: dict, record) -> None:
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
        del cgs, plan_json, validation

    def record_mutation_audit(self, *, ledger_entry: dict, dataset_entry: dict) -> None:
        self.audit.append((copy.deepcopy(ledger_entry), copy.deepcopy(dataset_entry)))


class _FakeSessionManager:
    def __init__(self, session: SimpleNamespace, new_cgs: dict) -> None:
        self._sessions = {"session-typed": session}
        self._new_cgs = copy.deepcopy(new_cgs)
        self.applied_txn: dict | None = None
        self.compile_calls = 0

    def validate_prompt_preview_approval(self, session_id: str, message: dict) -> dict:
        del session_id, message
        return {
            "accepted": True,
            "approval": {
                "schema": "xace.prompt_preview_approval.v1",
                "preview_id": "preview.typed.router",
                "approved": True,
            },
        }

    def apply_via_gde(self, session_id: str, txn: dict, cgs_state: dict):
        del session_id, cgs_state
        self.applied_txn = copy.deepcopy(txn)
        return SimpleNamespace(
            success=True,
            new_cgs=copy.deepcopy(self._new_cgs),
            new_hash=NEW_HASH,
            snapshot={},
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
            plan_json='{"kind":"ExecutionPlan"}',
            validation={"ok": True, "load_ready": True, "rollback_compatible": True},
            error={},
        )

    def clear_pending(self, session_id: str) -> None:
        session = self._sessions[session_id]
        session.pending_txn = None
        session.pending_prompt_preview = None
        session.pending_prompt_result = None


class TypedOperationRouterTests(unittest.TestCase):
    def test_typed_apply_forces_sgc_and_preserves_path_free_audit_provenance(self) -> None:
        txn = _typed_transaction()
        session = _session(txn)
        old_cgs = {
            "metadata": {
                "cgs_hash": OLD_HASH,
                "version": "0.1.0",
                "schema_version": "0.1.0",
            },
            "modes": [],
            "systems": [],
        }
        new_cgs = {
            "metadata": {
                "cgs_hash": NEW_HASH,
                "version": "0.2.0",
                "schema_version": "0.2.0",
            },
            "modes": [],
            "systems": [],
        }
        persist = _FakePersistence(old_cgs)
        session_manager = _FakeSessionManager(session, new_cgs)
        router = WSMessageRouter(session_manager)
        sent: list[dict] = []

        async def send_fn(message: dict) -> None:
            sent.append(message)

        asyncio.run(
            router.route(
                "session-typed",
                {"type": "pil_apply"},
                send_fn,
                persist,
                old_cgs,
            )
        )

        updates = [message for message in sent if message.get("type") == "cgs_update"]
        self.assertEqual(len(updates), 1, sent)
        update = updates[0]
        self.assertEqual(session_manager.compile_calls, 1)
        self.assertTrue(update["apply_feedback"]["sgc"]["required"])
        self.assertEqual(update["snapshot"]["mutation_count"], 7)
        self.assertEqual(update["snapshot"]["version_bump"], "minor")
        self.assertIn("actor:*:actor_player", update["affected_node_ids"])

        self.assertIsNotNone(session_manager.applied_txn)
        applied_operations = session_manager.applied_txn["typed_operation_batch"]["operations"]
        self.assertTrue(all("path" not in operation for operation in applied_operations))

        self.assertEqual(len(persist.audit), 1)
        ledger, dataset = persist.audit[0]
        self.assertEqual(ledger["operation_count"], 7)
        self.assertEqual(dataset["operation_count"], 7)
        self.assertTrue(all("path" not in operation for operation in dataset["operations"]))
        self.assertEqual(
            [operation["kind"] for operation in dataset["operations"]],
            [operation["kind"] for operation in _typed_batch()["operations"]],
        )
        provenance = dataset["typed_operation_provenance"]
        self.assertEqual(provenance["request_id"], "request.router.x10-030")
        self.assertEqual(provenance["prompt_id"], "prompt.router.x10-030")
        self.assertEqual(len(provenance["batch_hash"]), 64)
        self.assertEqual(ledger["typed_operation_batch_hash"], provenance["batch_hash"])
        self.assertEqual(update["typed_operation_provenance"], provenance)

    def test_recovery_audits_nested_typed_operations_without_legacy_paths(self) -> None:
        txn = _typed_transaction()
        session = _session(txn)
        persist = _FakePersistence({"metadata": {"cgs_hash": OLD_HASH}})
        rollback = {
            "restored": True,
            "failed_cgs_hash": NEW_HASH,
            "restored_cgs_hash": OLD_HASH,
        }
        with patch.object(
            router_module,
            "_restore_failed_prompt_apply",
            return_value=rollback,
        ):
            response = router_module._prompt_apply_recovery_error(
                persist=persist,
                session=session,
                cgs_state={"metadata": {"cgs_hash": OLD_HASH}},
                recovery_state={},
                failed_cgs_hash=NEW_HASH,
                transaction_id="txn.router.typed.recovery",
                stage="sgc_compile",
                code="SGC_COMPILE_FAILED",
                message="typed structural compile failed",
                authority={
                    "pre_hash": OLD_HASH,
                    "submitted_hash": OLD_HASH,
                    "version_ids": {"cgs_hash": OLD_HASH},
                },
                txn=txn,
                summary=txn["mutation_summary"],
                approval={"approved": True},
                runtime_control=None,
                session_id="session-typed",
                sgc_required=router_module._prompt_apply_requires_sgc(txn),
            )

        self.assertEqual(response["type"], "server_error")
        self.assertTrue(response["apply_feedback"]["sgc"]["required"])
        ledger, dataset = persist.audit[0]
        self.assertEqual(ledger["operation_count"], 7)
        self.assertEqual(dataset["outcome"], "rejected_recovered")
        self.assertEqual(dataset["operation_count"], 7)
        self.assertTrue(all("path" not in operation for operation in dataset["operations"]))
        self.assertEqual(
            response["typed_operation_provenance"],
            dataset["typed_operation_provenance"],
        )

    def test_typed_helpers_do_not_fall_back_to_legacy_paths(self) -> None:
        txn = {
            "typed_operation_batch": None,
            "operations": [{"op": "SET", "path": "modes.0.name", "value": "bad fallback"}],
            "required_recompile": False,
            "schema_delta_type": "value_mutation",
        }
        self.assertTrue(router_module._prompt_apply_requires_sgc(txn))
        self.assertEqual(router_module._prompt_apply_audit_operations(txn), [])
        self.assertEqual(router_module._prompt_apply_operation_count(txn), 0)


if __name__ == "__main__":
    unittest.main()
