"""
ws_message_router.py — WebSocket Message Router (Phase 14.5)
=============================================================
Routes incoming WebSocket messages from the browser to the correct
session operation. Returns response dicts to be sent back.

## Phase 14.5 changes vs Phase 14
    - pil_apply calls SessionManager.apply_via_gde(), so production
      mutation commits route through:
          PIL MutationTransaction
              → session_manager.apply_via_gde()
                  → GDEOrchestrator.process_transaction()  [if available]
                      → TransactionExecutor.execute()
                      → ConsistencyValidator.validate()
                      → CGSManager.commit()
                  → hard failure if GDE unavailable
              → SGC recompile if required_recompile=True
              → CGSPersistence.save() + snapshot()
              → cgs_update sent to UI

## Routing Table
    pil_process     → session_manager.run_pil()
    pil_answer      → session_manager.submit_clarification_answer()
    pil_apply       → GDE commit + SGC recompile + persist
    pil_discard     → clear pending mutation
    cgs_request     → load CGS from disk + send session_init
    prompt_history_request → return durable prompt undo/redo history
    prompt_undo      → restore previous prompt history state with proof links
    prompt_redo      → restore next prompt history state with proof links
    mode_change     → update session mode
    asset_link      → write asset path ref to CGS + persist
    cgs_rollback    → load snapshot + set as current CGS
    ping            → pong
"""

from __future__ import annotations

import hashlib
import copy
import json
import logging
import time
from typing import Any, Awaitable, Callable

from cgs_persistence import CGSPersistence, SnapshotRecord
from agent_host.event_stream import AgentEventStreamManager
from agent_host.session_store import AgentMutationLineageRecord
from prompt_classifier_gate import classify_prompt
from session_manager import SessionManager, _serialize_pil_result
from state_authority import (
    SUPPORTED_ENGINE_EDIT_COMMIT_KINDS,
    SUPPORTED_ENGINE_EDIT_KINDS,
    can_merge_engine_default_edit,
    engine_edit_commit_class,
)
from runtime_control_client import RuntimeControlClient, RuntimeControlError

try:
    from src.consistency_validator.static_mutation_conflict_analyzer import (  # type: ignore[import]
        StaticMutationConflictAnalyzer,
    )
except ImportError:
    StaticMutationConflictAnalyzer = None  # type: ignore[assignment,misc]

log = logging.getLogger(__name__)

SendFn = Callable[[dict], Awaitable[None]]
_FALLBACK_TXN_SEQUENCE = 0


class WSMessageRouter:
    """
    Stateless router — all state lives in SessionManager and CGSPersistence.
    """

    def __init__(
        self,
        session_manager: SessionManager,
        runtime_control: RuntimeControlClient | None = None,
        agent_event_stream: AgentEventStreamManager | None = None,
    ) -> None:
        self._sm = session_manager
        self._runtime_control = runtime_control
        self._agent_event_stream = agent_event_stream or AgentEventStreamManager()

    async def route(
        self,
        session_id: str,
        message:    dict,
        send_fn:    SendFn,
        persist:    CGSPersistence,
        cgs_state:  dict,
    ) -> None:
        msg_type = message.get("type", "")

        try:
            if msg_type == "pil_process":
                await self._handle_pil_process(session_id, message, send_fn, cgs_state)

            elif msg_type == "pil_answer":
                await self._handle_pil_answer(session_id, message, send_fn)

            elif msg_type == "pil_apply":
                await self._handle_pil_apply(session_id, message, send_fn, persist, cgs_state)

            elif msg_type == "pil_discard":
                await self._handle_pil_discard(
                    session_id,
                    message,
                    send_fn,
                    persist,
                    cgs_state,
                )

            elif msg_type == "cgs_request":
                await self._handle_cgs_request(session_id, message, send_fn, persist, cgs_state)

            elif msg_type == "mode_change":
                await self._handle_mode_change(session_id, message, send_fn)

            elif msg_type == "model_change":
                await self._handle_model_change(session_id, message, send_fn)

            elif msg_type == "agent_turn":
                await self._handle_agent_turn(session_id, message, send_fn, cgs_state)

            elif msg_type == "agent_cancel":
                await self._handle_agent_cancel(session_id, message, send_fn)

            elif msg_type == "agent_status":
                await self._handle_agent_status(session_id, message, send_fn)

            elif msg_type == "asset_link":
                await self._handle_asset_link(session_id, message, send_fn, persist, cgs_state)

            elif msg_type == "semantic_binding_update":
                await self._handle_semantic_binding_update(session_id, message, send_fn, persist, cgs_state)

            elif msg_type == "cgs_rollback":
                await self._handle_cgs_rollback(session_id, message, send_fn, persist, cgs_state)

            elif msg_type == "prompt_history_request":
                await self._handle_prompt_history_request(send_fn, persist)

            elif msg_type == "prompt_undo":
                await self._handle_prompt_history_restore("undo", session_id, message, send_fn, persist, cgs_state)

            elif msg_type == "prompt_redo":
                await self._handle_prompt_history_restore("redo", session_id, message, send_fn, persist, cgs_state)

            elif msg_type == "runtime_control":
                await self._handle_runtime_control(session_id, message, send_fn, persist, cgs_state)

            elif msg_type == "engine_edit":
                await self._handle_engine_edit(session_id, message, send_fn, cgs_state)

            elif msg_type == "engine_edit_commit":
                await self._handle_engine_edit_commit(session_id, message, send_fn, persist, cgs_state)

            elif msg_type == "terminal_command":
                await self._handle_terminal_command(message, send_fn)

            elif msg_type == "ping":
                await send_fn({"type": "pong", "server_time": time.time() * 1000})

            else:
                log.warning("Unknown message type: %r", msg_type)
                await send_fn({
                    "type":    "server_error",
                    "code":    "UNKNOWN_MESSAGE",
                    "message": f"Unknown message type: {msg_type!r}",
                })

        except Exception as exc:
            log.exception("Error handling %r from session %s", msg_type, session_id[:12])
            error_message = f"Error processing {msg_type!r}: {str(exc)[:200]}"
            response = {
                "type":    "server_error",
                "code":    "HANDLER_ERROR",
                "message": error_message,
            }
            if msg_type == "pil_apply":
                session = self._sm._sessions.get(session_id)
                txn = getattr(session, "pending_txn", None)
                if not isinstance(txn, dict):
                    txn = {}
                response["apply_feedback"] = _prompt_apply_feedback(
                    session=session,
                    txn=txn,
                    message=message,
                    ok=False,
                    stage="handler",
                    code="HANDLER_ERROR",
                    reason=error_message,
                    transaction_id=str(txn.get("transaction_id", "") or ""),
                    rollback_status="unknown",
                    started_at=time.time(),
                )
            await send_fn(response)

    # ── Handlers ──────────────────────────────────────────────────────────────

    async def _handle_pil_process(
        self,
        session_id: str,
        message:    dict,
        send_fn:    SendFn,
        cgs_state:  dict,
    ) -> None:
        prompt   = message.get("prompt", "")
        cgs_hash = message.get("cgs_hash", "")
        mode     = message.get("mode", "COLLABORATIVE")

        classifier = classify_prompt(str(prompt))
        if not classifier.may_continue_to_pil:
            self._sm.clear_pending(session_id)
            if classifier.category_id == "clarification_required":
                result = self._sm.start_prompt_clarification(
                    session_id,
                    str(prompt),
                    classifier,
                )
            else:
                result = classifier.to_pil_result()
            await send_fn({"type": "pil_result", "result": result})
            return

        result = await self._sm.run_pil(
            session_id = session_id,
            prompt     = prompt,
            cgs        = cgs_state,
            cgs_hash   = cgs_hash,
            mode       = mode,
            send_fn    = send_fn,
        )
        result["classifier"] = classifier.to_dict()
        session = self._sm._sessions.get(session_id)
        if session is not None and result.get("kind") == "mutation":
            session.pending_prompt_result = copy.deepcopy(result)
        await send_fn({"type": "pil_result", "result": result})

    async def _handle_pil_answer(
        self,
        session_id: str,
        message:    dict,
        send_fn:    SendFn,
    ) -> None:
        clar_id = message.get("clarification_id", "")
        answer  = message.get("answer", "")

        response = self._sm.submit_prompt_clarification_answer(
            session_id, clar_id, answer
        )
        if response is not None:
            await send_fn({"type": "pil_answer_ack", **response})
            return

        response = await self._sm.submit_clarification_answer(
            session_id, clar_id, answer
        )
        await send_fn({"type": "pil_answer_ack", **response})

    async def _handle_agent_turn(
        self,
        session_id: str,
        message: dict,
        send_fn: SendFn,
        cgs_state: dict,
    ) -> None:
        metadata = message.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        allowed_tools = message.get("allowed_tools")
        if not isinstance(allowed_tools, list):
            allowed_tools = []
        cgs_metadata = cgs_state.get("metadata") if isinstance(cgs_state, dict) else {}
        if not isinstance(cgs_metadata, dict):
            cgs_metadata = {}
        cgs_hash = str(message.get("cgs_hash") or cgs_metadata.get("cgs_hash") or "")
        session = self._sm._sessions.get(session_id)
        project_path = str(getattr(session, "project_path", "") or "")
        project_id = str(message.get("project_id") or "")
        if project_path and "project_path" not in metadata:
            metadata = {**metadata, "project_path": project_path}
        context_capsule_path = str(message.get("context_capsule_path") or "")
        await self._agent_event_stream.start_turn(
            session_id=session_id,
            provider_id=str(message.get("provider_id") or ""),
            user_prompt=str(message.get("prompt") or message.get("user_prompt") or ""),
            cgs_hash=cgs_hash,
            send_fn=send_fn,
            project_id=project_id,
            context_capsule_path=context_capsule_path or None,
            allowed_tools=tuple(str(tool) for tool in allowed_tools if isinstance(tool, str)),
            metadata=metadata,
            current_cgs=cgs_state,
            xace_session=session,
            mode=str(message.get("mode") or "AGENT"),
        )

    async def _handle_agent_cancel(
        self,
        session_id: str,
        message: dict,
        send_fn: SendFn,
    ) -> None:
        await self._agent_event_stream.cancel_turn(
            session_id=session_id,
            provider_id=str(message.get("provider_id") or ""),
            send_fn=send_fn,
        )

    async def _handle_agent_status(
        self,
        session_id: str,
        message: dict,
        send_fn: SendFn,
    ) -> None:
        await self._agent_event_stream.send_status(
            session_id=session_id,
            provider_id=str(message.get("provider_id") or ""),
            send_fn=send_fn,
        )

    async def _handle_pil_discard(
        self,
        session_id: str,
        message: dict,
        send_fn: SendFn,
        persist: CGSPersistence,
        cgs_state: dict,
    ) -> None:
        session = self._sm._sessions.get(session_id)
        txn = getattr(session, "pending_txn", None)
        agent_discard = _record_agent_proposal_discard(
            self._agent_event_stream.session_store,
            persist=persist,
            session_id=session_id,
            session=session,
            txn=txn,
            message=message,
            cgs_state=cgs_state,
        )
        self._sm.clear_pending(session_id)
        ack = {"type": "pil_discard_ack"}
        if agent_discard:
            ack["agent_proposal_discard"] = agent_discard
        await send_fn(ack)

    async def _handle_pil_apply(
        self,
        session_id: str,
        message:    dict,
        send_fn:    SendFn,
        persist:    CGSPersistence,
        cgs_state:  dict,
    ) -> None:
        """
        Phase 14.5: Applies the pending PIL MutationTransaction via GDE.

        Pipeline:
            pending_txn (dict)
                → session_manager.apply_via_gde()
                    → GDEOrchestrator.process_transaction()  [if GDE available]
                    → hard failure if GDE unavailable
                → SGC recompile (if required_recompile=True and sgc_bin set)
                → persist to disk
                → cgs_update → UI
        """
        apply_started_at = time.time()
        session = self._sm._sessions.get(session_id)
        if session is not None and session.pending_prompt_clarification is not None:
            message_text = (
                "Answer the active prompt clarification before applying a "
                "mutation. Ambiguous prompts cannot mutate CGS without a "
                "recorded resolution."
            )
            await send_fn({
                "type":    "server_error",
                "code":    "PROMPT_CLARIFICATION_REQUIRED",
                "message": message_text,
                "apply_feedback": _prompt_apply_feedback(
                    session=session,
                    txn={},
                    message=message,
                    ok=False,
                    stage="precondition",
                    code="PROMPT_CLARIFICATION_REQUIRED",
                    reason=message_text,
                    rollback_status="not_started",
                    started_at=apply_started_at,
                ),
            })
            return
        if session is None or session.pending_txn is None:
            message_text = "No pending mutation to apply."
            await send_fn({
                "type":    "server_error",
                "code":    "NO_PENDING_TXN",
                "message": message_text,
                "apply_feedback": _prompt_apply_feedback(
                    session=session,
                    txn={},
                    message=message,
                    ok=False,
                    stage="precondition",
                    code="NO_PENDING_TXN",
                    reason=message_text,
                    rollback_status="not_started",
                    started_at=apply_started_at,
                ),
            })
            return

        txn       = session.pending_txn
        audit_operations = _prompt_apply_audit_operations(txn)
        operation_count = _prompt_apply_operation_count(txn)
        sgc_required = _prompt_apply_requires_sgc(txn)
        typed_operation_batch = _prompt_apply_typed_operation_batch(txn)
        typed_operation_provenance = _prompt_apply_typed_operation_provenance(txn)
        transaction_id = _ensure_transaction_id(persist, txn)
        authority = _prepare_mutation_authority(
            persist,
            session,
            cgs_state,
            message,
            txn,
            mutation_path="pil_apply",
        )
        approval_check = self._sm.validate_prompt_preview_approval(session_id, message)
        approval_record = approval_check.get("approval") if isinstance(approval_check.get("approval"), dict) else {}
        if not approval_check.get("accepted"):
            _record_mutation_audit(
                persist,
                session_id=session_id,
                mutation_path="pil_apply",
                actor=_mutation_actor(message, txn, "prompt"),
                outcome="rejected_unapproved",
                transaction_id=transaction_id,
                version_ids=authority["version_ids"],
                pre_hash=authority["pre_hash"],
                post_hash=authority["pre_hash"],
                submitted_hash=authority["submitted_hash"],
                operations=audit_operations,
                summary=str(txn.get("mutation_summary", "")),
                error=str(approval_check.get("message") or "Prompt preview approval is required."),
                rollback_status="not_started",
                runtime_context=_runtime_context(session),
                approval=approval_record,
                typed_operation_provenance=typed_operation_provenance,
            )
            await send_fn({
                "type": "server_error",
                "code": str(approval_check.get("code") or "PROMPT_PREVIEW_APPROVAL_REQUIRED"),
                "message": str(approval_check.get("message") or "Prompt preview approval is required."),
                "transaction_id": transaction_id,
                "approval": approval_record,
                "apply_feedback": _prompt_apply_feedback(
                    session=session,
                    txn=txn,
                    message=message,
                    ok=False,
                    stage="approval",
                    code=str(approval_check.get("code") or "PROMPT_PREVIEW_APPROVAL_REQUIRED"),
                    reason=str(approval_check.get("message") or "Prompt preview approval is required."),
                    transaction_id=transaction_id,
                    authority=authority,
                    approval=approval_record,
                    rollback_status="not_started",
                    started_at=apply_started_at,
                ),
            })
            return
        if authority["rejected"]:
            _record_mutation_audit(
                persist,
                session_id=session_id,
                mutation_path="pil_apply",
                actor=_mutation_actor(message, txn, "prompt"),
                outcome="rejected_stale",
                transaction_id=transaction_id,
                version_ids=authority["version_ids"],
                pre_hash=authority["pre_hash"],
                post_hash=authority["pre_hash"],
                submitted_hash=authority["submitted_hash"],
                operations=audit_operations,
                summary=str(txn.get("mutation_summary", "")),
                error=authority["reason"],
                rollback_status="not_started",
                runtime_context=_runtime_context(session),
                approval=approval_record,
                typed_operation_provenance=typed_operation_provenance,
            )
            await send_fn({
                "type": "server_error",
                "code": "STALE_CGS_WRITE",
                "message": authority["reason"],
                "transaction_id": transaction_id,
                "approval": approval_record,
                "apply_feedback": _prompt_apply_feedback(
                    session=session,
                    txn=txn,
                    message=message,
                    ok=False,
                    stage="authority",
                    code="STALE_CGS_WRITE",
                    reason=authority["reason"],
                    transaction_id=transaction_id,
                    authority=authority,
                    approval=approval_record,
                    rollback_status="not_started",
                    started_at=apply_started_at,
                ),
            })
            return
        summary   = txn.get("mutation_summary", "")
        risk      = txn.get("risk_level", "low")
        affected  = txn.get("affected_systems", [])
        schema_delta_type = txn.get("schema_delta_type", "value_mutation")
        recovery_state = _capture_prompt_apply_recovery_state(
            session=session,
            cgs_state=cgs_state,
            version_ids=authority["version_ids"],
        )

        # ── Step 1: Apply via GDE ─────────────────────────────────────────────
        import asyncio
        loop = asyncio.get_event_loop()

        def _run_gde():
            return self._sm.apply_via_gde(session_id, txn, cgs_state)

        gde_result = await loop.run_in_executor(None, _run_gde)

        if not gde_result.success:
            log.error("GDE apply failed for session %s: %s", session_id[:12], gde_result.error)
            _record_mutation_audit(
                persist,
                session_id=session_id,
                mutation_path="pil_apply",
                actor=_mutation_actor(message, txn, "prompt"),
                outcome="rejected",
                transaction_id=transaction_id,
                version_ids=authority["version_ids"],
                pre_hash=authority["pre_hash"],
                post_hash=authority["pre_hash"],
                submitted_hash=authority["submitted_hash"],
                operations=audit_operations,
                summary=summary,
                error=gde_result.error or "GDE could not apply this mutation.",
                rollback_status="not_started",
                runtime_context=_runtime_context(session),
                approval=approval_record,
                typed_operation_provenance=typed_operation_provenance,
            )
            await send_fn({
                "type":    "server_error",
                "code":    "GDE_APPLY_FAILED",
                "message": gde_result.error or "GDE could not apply this mutation.",
                "warnings": gde_result.warnings,
                "transaction_id": transaction_id,
                "approval": approval_record,
                "apply_feedback": _prompt_apply_feedback(
                    session=session,
                    txn=txn,
                    message=message,
                    ok=False,
                    stage="gde_apply",
                    code="GDE_APPLY_FAILED",
                    reason=gde_result.error or "GDE could not apply this mutation.",
                    transaction_id=transaction_id,
                    authority=authority,
                    approval=approval_record,
                    rollback_status="not_started",
                    warnings=gde_result.warnings,
                    started_at=apply_started_at,
                ),
            })
            return

        new_cgs  = gde_result.new_cgs
        new_hash = gde_result.new_hash

        log.info("GDE committed mutation: hash=%s", new_hash[:8])

        # ── Step 2: SGC recompile (structural mutations only) ─────────────────
        execution_plan: str | None = None
        sgc_validation: dict[str, Any] | None = None
        if sgc_required:
            def _run_sgc():
                return self._sm.compile_sgc_plan(new_cgs)
            sgc_result = await loop.run_in_executor(None, _run_sgc)
            if sgc_result.ok:
                execution_plan = sgc_result.plan_json
                sgc_validation = sgc_result.validation
                log.info("SGC recompile complete for session %s", session_id[:12])
            elif sgc_result.failed:
                error = sgc_result.error or {}
                reason = str(error.get("message") or "SGC failed to compile the updated system graph.")
                action = str(error.get("action") or "Fix the CGS SystemDefinition and retry.")
                await send_fn(_prompt_apply_recovery_error(
                    persist=persist,
                    session=session,
                    cgs_state=cgs_state,
                    recovery_state=recovery_state,
                    failed_cgs_hash=new_hash,
                    transaction_id=transaction_id,
                    stage="sgc_compile",
                    code=str(error.get("code") or "SGC_COMPILE_FAILED"),
                    message=reason,
                    action=action,
                    authority=authority,
                    txn=txn,
                    summary=summary,
                    approval=approval_record,
                    runtime_control=self._runtime_control,
                    session_id=session_id,
                    apply_message=message,
                    started_at=apply_started_at,
                    sgc_required=True,
                    sgc_validation=sgc_result.validation,
                    sgc_error=error,
                ))
                return
            else:
                error = sgc_result.error or {}
                reason = str(error.get("message") or "SGC was skipped for this structural mutation.")
                action = str(error.get("action") or "Configure SGC and retry before applying this mutation.")
                skipped_error = {
                    **error,
                    "unsupported": True,
                    "status": "skipped",
                }
                await send_fn(_prompt_apply_recovery_error(
                    persist=persist,
                    session=session,
                    cgs_state=cgs_state,
                    recovery_state=recovery_state,
                    failed_cgs_hash=new_hash,
                    transaction_id=transaction_id,
                    stage="sgc_compile",
                    code=str(error.get("code") or "SGC_SKIPPED_UNSUPPORTED"),
                    message=reason,
                    action=action,
                    authority=authority,
                    txn=txn,
                    summary=summary,
                    approval=approval_record,
                    runtime_control=self._runtime_control,
                    session_id=session_id,
                    apply_message=message,
                    started_at=apply_started_at,
                    sgc_required=True,
                    sgc_validation=sgc_result.validation,
                    sgc_error=skipped_error,
                ))
                return

        # ── Step 3: Determine version bump ────────────────────────────────────
        if typed_operation_batch is not None or schema_delta_type.startswith("structural"):
            version_bump = "minor"
        elif schema_delta_type == "rule_change":
            version_bump = "patch"
        else:
            version_bump = "patch"

        # ── Step 4: Persist CGS + snapshot ────────────────────────────────────
        record = SnapshotRecord(
            cgs_hash       = new_hash,
            schema_version = new_cgs.get("metadata", {}).get("version", "0.1.0"),
            turn_index     = 0,
            mutation_count = operation_count,
            timestamp      = time.time(),
            summary        = summary,
            version_bump   = version_bump,
            risk_level     = risk,
        )
        try:
            _persist_prompt_apply_artifacts(
                persist=persist,
                new_cgs=new_cgs,
                new_hash=new_hash,
                record=record,
                execution_plan=execution_plan,
                sgc_validation=sgc_validation,
            )
        except PromptApplyRecoveryError as exc:
            await send_fn(_prompt_apply_recovery_error(
                persist=persist,
                session=session,
                cgs_state=cgs_state,
                recovery_state=recovery_state,
                failed_cgs_hash=new_hash,
                transaction_id=transaction_id,
                stage=exc.stage,
                code=exc.code,
                message=exc.message,
                authority=authority,
                txn=txn,
                summary=summary,
                approval=approval_record,
                runtime_control=self._runtime_control,
                session_id=session_id,
                apply_message=message,
                started_at=apply_started_at,
                sgc_required=sgc_required,
                sgc_validation=sgc_validation,
                execution_plan=execution_plan,
            ))
            return

        # ── Step 5: Update in-memory state ────────────────────────────────────
        cgs_state.clear()
        cgs_state.update(new_cgs)
        post_version_ids = _version_ids_for(session, new_cgs, persist, message, txn)
        try:
            apply_validation = _run_prompt_apply_validation_hooks(
                runtime_control=self._runtime_control,
                session=session,
                session_id=session_id,
                message=message,
                post_version_ids=post_version_ids,
            )
        except PromptApplyRecoveryError as exc:
            await send_fn(_prompt_apply_recovery_error(
                persist=persist,
                session=session,
                cgs_state=cgs_state,
                recovery_state=recovery_state,
                failed_cgs_hash=new_hash,
                transaction_id=transaction_id,
                stage=exc.stage,
                code=exc.code,
                message=exc.message,
                authority=authority,
                txn=txn,
                summary=summary,
                approval=approval_record,
                runtime_control=self._runtime_control,
                session_id=session_id,
                apply_message=message,
                started_at=apply_started_at,
                sgc_required=sgc_required,
                sgc_validation=sgc_validation,
                execution_plan=execution_plan,
                apply_validation=exc.details,
            ))
            return
        apply_feedback = _prompt_apply_feedback(
            session=session,
            txn=txn,
            message=message,
            ok=True,
            stage="applied",
            code="PROMPT_APPLY_OK",
            reason="Prompt apply validated and persisted.",
            transaction_id=transaction_id,
            authority=authority,
            approval=approval_record,
            sgc_required=sgc_required,
            sgc_validation=sgc_validation,
            execution_plan=execution_plan,
            apply_validation=apply_validation,
            rollback_status="not_needed",
            persist=persist,
            cgs_hash=new_hash,
            started_at=apply_started_at,
        )
        prompt_history_entry: dict[str, Any] = {}
        prompt_history: dict[str, Any] = {}
        try:
            prompt_history_entry = persist.record_prompt_history_apply(
                transaction_id=transaction_id,
                pre_cgs_hash=authority["pre_hash"],
                post_cgs_hash=new_hash,
                summary=summary,
                mutation_count=operation_count,
                version_ids=post_version_ids,
                proof_links=apply_feedback.get("proof_links") if isinstance(apply_feedback, dict) else None,
                typed_operation_provenance=typed_operation_provenance,
                composite_prompt_plan=_prompt_apply_composite_prompt_plan(txn),
            )
            prompt_history = persist.prompt_history_state()
        except Exception as exc:  # noqa: BLE001 - prompt apply has already persisted; surface evidence failure.
            log.warning("Failed to record prompt undo/redo history: %s", exc)
            prompt_history = getattr(persist, "prompt_history_state", lambda: {})()
        agent_proposal_apply = _record_agent_proposal_applied(
            self._agent_event_stream.session_store,
            session_id=session_id,
            txn=txn,
            approval=approval_record,
            transaction_id=transaction_id,
            pre_hash=authority["pre_hash"],
            post_hash=new_hash,
            summary=summary,
            apply_feedback=apply_feedback,
            typed_operation_provenance=typed_operation_provenance,
        )
        self._sm.clear_pending(session_id)
        _record_mutation_audit(
            persist,
            session_id=session_id,
            mutation_path="pil_apply",
            actor=_mutation_actor(message, txn, "prompt"),
            outcome="applied",
            transaction_id=transaction_id,
            version_ids=post_version_ids,
            pre_hash=authority["pre_hash"],
            post_hash=new_hash,
            submitted_hash=authority["submitted_hash"],
            operations=audit_operations,
            summary=summary,
            error="",
            rollback_status="not_needed",
            runtime_context=_runtime_context(session),
            approval=approval_record,
            typed_operation_provenance=typed_operation_provenance,
            proof_links=apply_feedback.get("proof_links") if isinstance(apply_feedback, dict) else None,
            prompt_history=prompt_history_entry,
        )

        # ── Step 6: Build affected node IDs for graph highlight ───────────────
        affected_node_ids = [f"sys:*:{sid}" for sid in affected]
        # Also highlight any actors that were structurally changed
        if typed_operation_batch is not None or schema_delta_type in ("structural_add", "structural_remove"):
            for op in audit_operations:
                if not isinstance(op, dict):
                    continue
                actor_id = op.get("actor_id", "")
                if actor_id:
                    affected_node_ids.append(f"actor:*:{actor_id}")

        # ── Step 7: Send cgs_update to UI ─────────────────────────────────────
        await send_fn({
            "type":              "cgs_update",
            "cgs":               new_cgs,
            "hash":              new_hash,
            "snapshot":          record.to_dict(),
            "affected_node_ids": list(set(affected_node_ids)),
            "gde_used":          gde_result.used_gde,
            "warnings":          gde_result.warnings,
            "execution_plan_available": execution_plan is not None,
            "sgc_validation":    sgc_validation,
            "transaction_id":    transaction_id,
            "version_ids":       post_version_ids,
            "approval":          approval_record,
            "apply_validation":   apply_validation,
            "apply_feedback":     apply_feedback,
            "typed_operation_provenance": typed_operation_provenance,
            "composite_prompt_plan": _prompt_apply_composite_prompt_plan(txn),
            "prompt_history": prompt_history,
            "prompt_history_entry": prompt_history_entry,
            "agent_proposal_apply": agent_proposal_apply,
        })

    async def _handle_cgs_request(
        self,
        session_id: str,
        message:    dict,
        send_fn:    SendFn,
        persist:    CGSPersistence,
        cgs_state:  dict,
    ) -> None:
        try:
            cgs = persist.load()
            cgs_state.clear()
            cgs_state.update(cgs)
        except Exception as exc:
            log.error("CGS load failed: %s", exc)
            cgs_state.update({
                "metadata": {
                    "name": "New Project",
                    "cgs_hash": "0" * 64,
                    "version": "0.1.0",
                    "schema_version": "0.1.0",
                },
                "global_systems": [], "modes": [],
            })

        snapshots = persist.list_snapshots(limit=50)

        # Also send execution plan availability if one exists
        latest_hash = cgs_state.get("metadata", {}).get("cgs_hash", "")
        has_plan    = persist.has_execution_plan(latest_hash)

        await send_fn({
            "type":                     "session_init",
            "session_id":               session_id,
            "cgs":                      cgs_state,
            "hash":                     latest_hash,
            "snapshots":                [s.to_dict() for s in snapshots],
            "version":                  cgs_state.get("metadata", {}).get("schema_version", "0.0.0"),
            "execution_plan_available": has_plan,
            "prompt_history":           persist.prompt_history_state(),
        })

    async def _handle_prompt_history_request(
        self,
        send_fn: SendFn,
        persist: CGSPersistence,
    ) -> None:
        await send_fn({
            "type": "prompt_history",
            "prompt_history": persist.prompt_history_state(),
        })

    async def _handle_prompt_history_restore(
        self,
        action: str,
        session_id: str,
        message: dict,
        send_fn: SendFn,
        persist: CGSPersistence,
        cgs_state: dict,
    ) -> None:
        started_at = time.time()
        mutation_path = f"prompt_{action}"
        session = self._sm._sessions.get(session_id)
        current_hash = str(
            (cgs_state.get("metadata", {}) if isinstance(cgs_state, dict) else {}).get("cgs_hash")
            or persist.current_cgs_hash()
            or ""
        )
        txn = {
            "source": "prompt_history",
            "mutation_path": mutation_path,
            "operations": [{"op": f"PROMPT_{action.upper()}", "path": "prompt_history", "value": current_hash}],
            "mutation_summary": f"Prompt {action} from {current_hash}",
            "risk_level": "medium",
            "required_recompile": False,
        }
        transaction_id = _ensure_transaction_id(persist, txn)
        authority = _prepare_mutation_authority(
            persist,
            session,
            cgs_state,
            message,
            txn,
            mutation_path=mutation_path,
        )
        audit_operations = _prompt_apply_audit_operations(txn)
        if authority["rejected"]:
            _record_mutation_audit(
                persist,
                session_id=session_id,
                mutation_path=mutation_path,
                actor=_mutation_actor(message, txn, "builder"),
                outcome="rejected_stale",
                transaction_id=transaction_id,
                version_ids=authority["version_ids"],
                pre_hash=authority["pre_hash"],
                post_hash=authority["pre_hash"],
                submitted_hash=authority["submitted_hash"],
                operations=audit_operations,
                summary=txn["mutation_summary"],
                error=authority["reason"],
                rollback_status="not_started",
                runtime_context=_runtime_context(session),
            )
            await send_fn({
                "type": "prompt_history_ack",
                "action": action,
                "accepted": False,
                "reason": authority["reason"],
                "transaction_id": transaction_id,
                "prompt_history": persist.prompt_history_state(),
            })
            return

        plan = persist.plan_prompt_history_restore(
            action,
            current_cgs_hash=authority["pre_hash"],
            require_proof=True,
        )
        if not plan.get("accepted"):
            reason = str(plan.get("reason") or f"Prompt {action} is not available.")
            _record_mutation_audit(
                persist,
                session_id=session_id,
                mutation_path=mutation_path,
                actor=_mutation_actor(message, txn, "builder"),
                outcome="rejected",
                transaction_id=transaction_id,
                version_ids=authority["version_ids"],
                pre_hash=authority["pre_hash"],
                post_hash=authority["pre_hash"],
                submitted_hash=authority["submitted_hash"],
                operations=audit_operations,
                summary=txn["mutation_summary"],
                error=reason,
                rollback_status="not_started",
                runtime_context=_runtime_context(session),
                prompt_history=plan,
            )
            await send_fn({
                "type": "prompt_history_ack",
                "action": action,
                "accepted": False,
                "reason": reason,
                "transaction_id": transaction_id,
                "prompt_history": persist.prompt_history_state(),
                "restore_plan": plan,
            })
            return

        target_hash = str(plan.get("target_cgs_hash") or "")
        try:
            snap = persist.load_snapshot(target_hash)
            snap.setdefault("metadata", {})["cgs_hash"] = target_hash
            if session and session.gde is not None:
                session.gde.load_cgs(snap, session_id=session_id)
                log.info("GDE prompt %s restored hash=%s", action, target_hash[:8])
            persist.save(snap)
            restore_event = persist.complete_prompt_history_restore(
                plan,
                transaction_id=transaction_id,
            )
        except Exception as exc:  # noqa: BLE001 - restore must fail visibly.
            reason = str(exc)
            _record_mutation_audit(
                persist,
                session_id=session_id,
                mutation_path=mutation_path,
                actor=_mutation_actor(message, txn, "builder"),
                outcome="rejected",
                transaction_id=transaction_id,
                version_ids=authority["version_ids"],
                pre_hash=authority["pre_hash"],
                post_hash=authority["pre_hash"],
                submitted_hash=authority["submitted_hash"],
                operations=audit_operations,
                summary=txn["mutation_summary"],
                error=reason,
                rollback_status="restore_failed",
                runtime_context=_runtime_context(session),
                prompt_history=plan,
            )
            await send_fn({
                "type": "prompt_history_ack",
                "action": action,
                "accepted": False,
                "reason": reason,
                "transaction_id": transaction_id,
                "restore_plan": plan,
                "prompt_history": persist.prompt_history_state(),
            })
            return

        cgs_state.clear()
        cgs_state.update(snap)
        post_version_ids = _version_ids_for(session, snap, persist, message, txn)
        history_state = persist.prompt_history_state()
        proof_links = plan.get("proof_links") if isinstance(plan.get("proof_links"), dict) else {}
        _record_mutation_audit(
            persist,
            session_id=session_id,
            mutation_path=mutation_path,
            actor=_mutation_actor(message, txn, "builder"),
            outcome="applied",
            transaction_id=transaction_id,
            version_ids=post_version_ids,
            pre_hash=authority["pre_hash"],
            post_hash=target_hash,
            submitted_hash=authority["submitted_hash"],
            operations=audit_operations,
            summary=txn["mutation_summary"],
            error="",
            rollback_status=f"prompt_{action}_restored",
            runtime_context=_runtime_context(session),
            proof_links=proof_links,
            prompt_history=restore_event,
        )
        await send_fn({
            "type": "prompt_history_ack",
            "action": action,
            "accepted": True,
            "reason": "",
            "hash": target_hash,
            "transaction_id": transaction_id,
            "restore_plan": plan,
            "restore_event": restore_event,
            "proof_links": proof_links,
            "prompt_history": history_state,
            "latency_ms": int((time.time() - started_at) * 1000),
        })
        await send_fn({
            "type": "cgs_update",
            "cgs": snap,
            "hash": target_hash,
            "snapshot": _snapshot_record_for_hash(persist, target_hash),
            "affected_node_ids": [],
            "transaction_id": transaction_id,
            "version_ids": post_version_ids,
            "execution_plan_available": bool((plan.get("proof_status") or {}).get("execution_plan_available")),
            "proof_links": proof_links,
            "prompt_history": history_state,
            "prompt_history_restore": restore_event,
        })

    async def _handle_mode_change(
        self,
        session_id: str,
        message:    dict,
        send_fn:    SendFn,
    ) -> None:
        mode    = message.get("mode", "COLLABORATIVE")
        session = self._sm._sessions.get(session_id)
        if session:
            session.current_mode = mode
            if session.gde is not None:
                try:
                    session.gde.set_mode(mode)
                except Exception:
                    pass
        await send_fn({"type": "mode_change_ack", "mode": mode})

    async def _handle_model_change(
        self,
        session_id: str,
        message:    dict,
        send_fn:    SendFn,
    ) -> None:
        """
        Hot-swaps the inference adapter for the session.

        Triggered when the designer selects a different model in the
        ModelSelector dropdown. Rebuilds the PIL pipeline with the new
        adapter without dropping the session or losing CGS state.
        """
        provider = message.get("provider", "anthropic")
        model    = message.get("model", "")
        session  = self._sm._sessions.get(session_id)

        if session is None:
            await send_fn({"type": "server_error", "code": "NO_SESSION",
                           "message": "Session not found."})
            return

        import asyncio, logging
        _log = logging.getLogger(__name__)

        try:
            settings = self._sm.configure_provider(
                provider=provider,
                model_name=model,
                api_key=None,
            )

            # Rebuild pipeline with new adapter
            from session_manager import StreamingInferenceAdapter
            loop         = asyncio.get_event_loop()

            async def send_proxy(msg: dict) -> None:
                await send_fn(msg)

            real_adapter = self._sm.build_active_adapter()
            streaming = StreamingInferenceAdapter(real_adapter, send_proxy, loop)

            if session.pipeline is not None:
                session.pipeline._adapter = real_adapter
                session.pipeline._llm_orch._adapter = streaming
                _log.info("Hot-swapped model: %s/%s for session %s",
                          provider, model, session_id[:12])

            await send_fn({
                "type":     "model_change_ack",
                "provider": settings.get("provider", provider),
                "model":    settings.get("current", model),
            })

        except Exception as exc:
            _log.error("Model hot-swap failed: %s", exc)
            await send_fn({"type": "server_error", "code": "MODEL_CHANGE_FAILED",
                           "message": str(exc)[:200]})

    async def _handle_asset_link(
        self,
        session_id: str,
        message:    dict,
        send_fn:    SendFn,
        persist:    CGSPersistence,
        cgs_state:  dict,
    ) -> None:
        placeholder_id = message.get("placeholder_id", "")
        asset_path     = message.get("asset_path", "")
        actor_id       = message.get("actor_id", "")
        comp_name      = message.get("component_name", "")
        session        = self._sm._sessions.get(session_id)
        txn = {
            "source": "manual",
            "mutation_path": "asset_link",
            "operations": [{
                "op": "LINK_ASSET",
                "path": f"actors.{actor_id}.components.{comp_name}",
                "value": {
                    "placeholder_id": placeholder_id,
                    "asset_path": asset_path,
                },
                "actor_id": actor_id,
            }],
            "mutation_summary": f"Link asset {asset_path} to {actor_id}.{comp_name}",
            "risk_level": "low",
        }
        transaction_id = _ensure_transaction_id(persist, txn)
        authority = _prepare_mutation_authority(
            persist,
            session,
            cgs_state,
            message,
            txn,
            mutation_path="asset_link",
        )
        if authority["rejected"]:
            _record_mutation_audit(
                persist,
                session_id=session_id,
                mutation_path="asset_link",
                actor=_mutation_actor(message, txn, "builder"),
                outcome="rejected_stale",
                transaction_id=transaction_id,
                version_ids=authority["version_ids"],
                pre_hash=authority["pre_hash"],
                post_hash=authority["pre_hash"],
                submitted_hash=authority["submitted_hash"],
                operations=txn["operations"],
                summary=txn["mutation_summary"],
                error=authority["reason"],
                rollback_status="not_started",
                runtime_context=_runtime_context(session),
            )
            await send_fn({
                "type": "server_error",
                "code": "STALE_CGS_WRITE",
                "message": authority["reason"],
                "transaction_id": transaction_id,
            })
            return

        new_cgs  = _link_asset(cgs_state, actor_id, comp_name, placeholder_id, asset_path)
        new_hash = _compute_hash(new_cgs)
        new_cgs["metadata"]["cgs_hash"] = new_hash
        static_conflict_reason = _static_precommit_conflict_reason(cgs_state, new_cgs, txn)
        if static_conflict_reason:
            _record_mutation_audit(
                persist,
                session_id=session_id,
                mutation_path="asset_link",
                actor=_mutation_actor(message, txn, "builder"),
                outcome="rejected_static_conflict",
                transaction_id=transaction_id,
                version_ids=authority["version_ids"],
                pre_hash=authority["pre_hash"],
                post_hash=authority["pre_hash"],
                submitted_hash=authority["submitted_hash"],
                operations=txn["operations"],
                summary=txn["mutation_summary"],
                error=static_conflict_reason,
                rollback_status="not_started",
                runtime_context=_runtime_context(session),
            )
            await send_fn({
                "type": "server_error",
                "code": "STATIC_MUTATION_CONFLICT",
                "message": static_conflict_reason,
                "transaction_id": transaction_id,
            })
            return

        persist.save(new_cgs)
        cgs_state.clear()
        cgs_state.update(new_cgs)
        post_version_ids = _version_ids_for(session, new_cgs, persist, message, txn)
        _record_mutation_audit(
            persist,
            session_id=session_id,
            mutation_path="asset_link",
            actor=_mutation_actor(message, txn, "builder"),
            outcome="applied",
            transaction_id=transaction_id,
            version_ids=post_version_ids,
            pre_hash=authority["pre_hash"],
            post_hash=new_hash,
            submitted_hash=authority["submitted_hash"],
            operations=txn["operations"],
            summary=txn["mutation_summary"],
            error="",
            rollback_status="not_needed",
            runtime_context=_runtime_context(session),
        )

        await send_fn({
            "type":              "cgs_update",
            "cgs":               new_cgs,
            "hash":              new_hash,
            "snapshot":          {},
            "affected_node_ids": [f"actor:*:{actor_id}"],
            "transaction_id":    transaction_id,
            "version_ids":       post_version_ids,
        })

    async def _handle_semantic_binding_update(
        self,
        session_id: str,
        message:    dict,
        send_fn:    SendFn,
        persist:    CGSPersistence,
        cgs_state:  dict,
    ) -> None:
        session = self._sm._sessions.get(session_id)
        try:
            bindings = _sanitize_semantic_bindings(message.get("bindings"))
        except ValueError as exc:
            await send_fn({
                "type": "server_error",
                "code": "SEMANTIC_BINDING_INVALID",
                "message": str(exc),
            })
            return

        txn = {
            "source": "builder_ui",
            "mutation_path": "semantic_binding_update",
            "operations": [{
                "op": "SET_SEMANTIC_BINDINGS",
                "path": "semantic_bindings.bindings",
                "value": bindings,
            }],
            "mutation_summary": f"Update {len(bindings)} semantic playback binding(s)",
            "risk_level": "low",
        }
        transaction_id = _ensure_transaction_id(persist, txn)
        authority = _prepare_mutation_authority(
            persist,
            session,
            cgs_state,
            message,
            txn,
            mutation_path="semantic_binding_update",
        )
        if authority["rejected"]:
            _record_mutation_audit(
                persist,
                session_id=session_id,
                mutation_path="semantic_binding_update",
                actor=_mutation_actor(message, txn, "builder"),
                outcome="rejected_stale",
                transaction_id=transaction_id,
                version_ids=authority["version_ids"],
                pre_hash=authority["pre_hash"],
                post_hash=authority["pre_hash"],
                submitted_hash=authority["submitted_hash"],
                operations=txn["operations"],
                summary=txn["mutation_summary"],
                error=authority["reason"],
                rollback_status="not_started",
                runtime_context=_runtime_context(session),
            )
            await send_fn({
                "type": "server_error",
                "code": "STALE_CGS_WRITE",
                "message": authority["reason"],
                "transaction_id": transaction_id,
            })
            return

        new_cgs = _set_semantic_bindings(cgs_state, bindings)
        new_hash = _compute_hash(new_cgs)
        new_cgs.setdefault("metadata", {})["cgs_hash"] = new_hash
        static_conflict_reason = _static_precommit_conflict_reason(cgs_state, new_cgs, txn)
        if static_conflict_reason:
            _record_mutation_audit(
                persist,
                session_id=session_id,
                mutation_path="semantic_binding_update",
                actor=_mutation_actor(message, txn, "builder"),
                outcome="rejected_static_conflict",
                transaction_id=transaction_id,
                version_ids=authority["version_ids"],
                pre_hash=authority["pre_hash"],
                post_hash=authority["pre_hash"],
                submitted_hash=authority["submitted_hash"],
                operations=txn["operations"],
                summary=txn["mutation_summary"],
                error=static_conflict_reason,
                rollback_status="not_started",
                runtime_context=_runtime_context(session),
            )
            await send_fn({
                "type": "server_error",
                "code": "STATIC_MUTATION_CONFLICT",
                "message": static_conflict_reason,
                "transaction_id": transaction_id,
            })
            return

        persist.save(new_cgs)
        cgs_state.clear()
        cgs_state.update(new_cgs)
        post_version_ids = _version_ids_for(session, new_cgs, persist, message, txn)
        _record_mutation_audit(
            persist,
            session_id=session_id,
            mutation_path="semantic_binding_update",
            actor=_mutation_actor(message, txn, "builder"),
            outcome="applied",
            transaction_id=transaction_id,
            version_ids=post_version_ids,
            pre_hash=authority["pre_hash"],
            post_hash=new_hash,
            submitted_hash=authority["submitted_hash"],
            operations=txn["operations"],
            summary=txn["mutation_summary"],
            error="",
            rollback_status="not_needed",
            runtime_context=_runtime_context(session),
        )

        await send_fn({
            "type":              "cgs_update",
            "cgs":               new_cgs,
            "hash":              new_hash,
            "snapshot":          {},
            "affected_node_ids": ["semantic_bindings"],
            "transaction_id":    transaction_id,
            "version_ids":       post_version_ids,
        })

    async def _handle_cgs_rollback(
        self,
        session_id: str,
        message:    dict,
        send_fn:    SendFn,
        persist:    CGSPersistence,
        cgs_state:  dict,
    ) -> None:
        target_hash = message.get("target_hash", "")
        session = self._sm._sessions.get(session_id)
        txn = {
            "source": "rollback",
            "mutation_path": "cgs_rollback",
            "operations": [{"op": "ROLLBACK", "path": "snapshots", "value": target_hash}],
            "mutation_summary": f"Rollback CGS to snapshot {target_hash}",
            "risk_level": "medium",
        }
        transaction_id = _ensure_transaction_id(persist, txn)
        authority = _prepare_mutation_authority(
            persist,
            session,
            cgs_state,
            message,
            txn,
            mutation_path="cgs_rollback",
        )
        if authority["rejected"]:
            _record_mutation_audit(
                persist,
                session_id=session_id,
                mutation_path="cgs_rollback",
                actor=_mutation_actor(message, txn, "builder"),
                outcome="rejected_stale",
                transaction_id=transaction_id,
                version_ids=authority["version_ids"],
                pre_hash=authority["pre_hash"],
                post_hash=authority["pre_hash"],
                submitted_hash=authority["submitted_hash"],
                operations=txn["operations"],
                summary=txn["mutation_summary"],
                error=authority["reason"],
                rollback_status="not_started",
                runtime_context=_runtime_context(session),
            )
            await send_fn({
                "type": "server_error",
                "code": "STALE_CGS_WRITE",
                "message": authority["reason"],
                "transaction_id": transaction_id,
            })
            return
        try:
            snap = persist.load_snapshot(target_hash)
        except Exception as exc:
            _record_mutation_audit(
                persist,
                session_id=session_id,
                mutation_path="cgs_rollback",
                actor=_mutation_actor(message, txn, "builder"),
                outcome="rejected",
                transaction_id=transaction_id,
                version_ids=authority["version_ids"],
                pre_hash=authority["pre_hash"],
                post_hash=authority["pre_hash"],
                submitted_hash=authority["submitted_hash"],
                operations=txn["operations"],
                summary=txn["mutation_summary"],
                error=str(exc),
                rollback_status="not_started",
                runtime_context=_runtime_context(session),
            )
            await send_fn({
                "type":    "server_error",
                "code":    "SNAPSHOT_NOT_FOUND",
                "message": str(exc),
            })
            return

        # If GDE session is active, roll it back too
        if session and session.gde is not None:
            try:
                session.gde.load_cgs(snap, session_id=session_id)
                log.info("GDE rolled back to hash=%s", target_hash[:8])
            except Exception as exc:
                log.warning("GDE rollback failed (will re-sync on next apply): %s", exc)

        snap["metadata"]["cgs_hash"] = target_hash
        persist.save(snap)
        cgs_state.clear()
        cgs_state.update(snap)
        post_version_ids = _version_ids_for(session, snap, persist, message, txn)
        _record_mutation_audit(
            persist,
            session_id=session_id,
            mutation_path="cgs_rollback",
            actor=_mutation_actor(message, txn, "builder"),
            outcome="applied",
            transaction_id=transaction_id,
            version_ids=post_version_ids,
            pre_hash=authority["pre_hash"],
            post_hash=target_hash,
            submitted_hash=authority["submitted_hash"],
            operations=txn["operations"],
            summary=txn["mutation_summary"],
            error="",
            rollback_status="restored_snapshot",
            runtime_context=_runtime_context(session),
        )

        await send_fn({
            "type":              "cgs_update",
            "cgs":               snap,
            "hash":              target_hash,
            "snapshot":          {},
            "affected_node_ids": [],
            "transaction_id":    transaction_id,
            "version_ids":       post_version_ids,
        })

    async def _handle_runtime_control(
        self,
        session_id: str,
        message:    dict,
        send_fn:    SendFn,
        persist:    CGSPersistence,
        cgs_state:  dict,
    ) -> None:
        action = str(message.get("action", ""))
        if action not in {
            "play",
            "pause",
            "step",
            "reset",
            "reload_cgs",
            "status",
            "snapshot",
            "replay_record",
            "replay_validate",
            "shutdown",
        }:
            await send_fn({
                "type": "runtime_control_ack",
                "action": action,
                "accepted": False,
                "reason": f"Unknown runtime control: {action}",
            })
            return

        if self._runtime_control is None:
            await send_fn({
                "type": "runtime_control_ack",
                "action": action,
                "accepted": False,
                "reason": "Runtime control client is disabled in builder server.",
            })
            return

        session = self._sm._sessions.get(session_id)
        version_ids = None
        if action == "reload_cgs":
            version_ids = _version_ids_for(session, cgs_state, persist, message, {})
            supplied = message.get("version_ids")
            if isinstance(supplied, dict):
                version_ids.update({k: v for k, v in supplied.items() if v not in ("", None)})

        try:
            response = self._runtime_control.send_control(
                action,
                session_id=session_id,
                tick=message.get("tick"),
                version_ids=version_ids,
            )
        except (OSError, RuntimeControlError) as exc:
            await send_fn({
                "type": "runtime_control_ack",
                "action": action,
                "accepted": False,
                "reason": f"Runtime control unavailable at {self._runtime_control.endpoint}: {exc}",
            })
            return

        if session is not None:
            status = response.get("status", {})
            if isinstance(status, dict):
                session.update_runtime_status(
                    connected=bool(status.get("engine_connected", False)),
                    last_tick=status,
                    last_hash=str(
                        status.get("latest_world_hash")
                        or status.get("runtime_world_hash")
                        or status.get("world_hash")
                        or ""
                    ),
                )

        engine_tick = _runtime_snapshot_to_engine_tick(response)
        if engine_tick is not None:
            if session is not None:
                session.update_runtime_status(
                    connected=True,
                    last_tick=engine_tick,
                    last_hash=engine_tick.get("world_hash", ""),
                )
            await send_fn(engine_tick)

        await send_fn({
            "type": "runtime_control_ack",
            "action": action,
            "accepted": bool(response.get("accepted", False)),
            "reason": str(response.get("reason", "")),
            "status": response.get("status", {}),
            "snapshot": response.get("snapshot"),
        })

    async def _handle_engine_edit(
        self,
        session_id: str,
        message:    dict,
        send_fn:    SendFn,
        cgs_state:  dict,
    ) -> None:
        kind = str(message.get("kind", ""))
        entity_id = str(message.get("entity_id", ""))
        if kind not in SUPPORTED_ENGINE_EDIT_KINDS:
            await send_fn({
                "type": "engine_edit_ack",
                "accepted": False,
                "reason": f"Unsupported engine edit kind: {kind}",
                "affected_entity_ids": [],
            })
            return

        session = self._sm._sessions.get(session_id)
        if session is None:
            await send_fn({
                "type": "engine_edit_ack",
                "accepted": False,
                "reason": "Session not found.",
                "affected_entity_ids": [],
            })
            return

        if self._runtime_control is None:
            await send_fn({
                "type": "engine_edit_ack",
                "accepted": False,
                "reason": "Runtime edit bridge is disabled in builder server.",
                "affected_entity_ids": [entity_id] if entity_id else [],
            })
            return

        try:
            response = self._runtime_control.send_engine_edit(
                kind,
                entity_id=entity_id,
                session_id=session_id,
                component_type_id=message.get("component_type_id"),
                field_path=str(message.get("field_path", "")),
                value=message.get("value"),
            )
        except (OSError, RuntimeControlError) as exc:
            await send_fn({
                "type": "engine_edit_ack",
                "accepted": False,
                "reason": f"Runtime edit bridge unavailable at {self._runtime_control.endpoint}: {exc}",
                "affected_entity_ids": [entity_id] if entity_id else [],
            })
            return

        status = response.get("status", {})
        if isinstance(status, dict):
            session.update_runtime_status(
                connected=bool(status.get("engine_connected", False)),
                last_tick=status,
            )

        affected = [
            str(item)
            for item in response.get("affected_entity_ids", [])
            if item is not None
        ]
        accepted = bool(response.get("accepted", False))
        meta = cgs_state.get("metadata", {}) if isinstance(cgs_state, dict) else {}
        runtime_context = _runtime_context_from_status(session, status if isinstance(status, dict) else {})
        preview_cgs_hash = str(message.get("cgs_hash") or meta.get("cgs_hash", "") or "")
        preview_schema_version = str(
            message.get("schema_version")
            or meta.get("schema_version")
            or meta.get("version")
            or ""
        )
        preview_id = _engine_edit_preview_id(
            session_id=session_id,
            kind=kind,
            entity_id=entity_id,
            message=message,
            preview_cgs_hash=preview_cgs_hash,
            runtime_context=runtime_context,
        ) if accepted else ""
        audit_record = {
            "kind": kind,
            "entity_id": entity_id,
            "mode_id": message.get("mode_id", ""),
            "actor_id": message.get("actor_id", ""),
            "component_type_id": message.get("component_type_id"),
            "component_name": message.get("component_name", ""),
            "field_path": message.get("field_path", ""),
            "value": message.get("value"),
            "accepted": accepted,
            "reason": str(response.get("reason", "")),
            "affected_entity_ids": affected,
            "runtime_tick": runtime_context.get("runtime_tick"),
            "runtime_world_hash": runtime_context.get("runtime_world_hash", ""),
            "runtime_cgs_hash": runtime_context.get("cgs_hash", ""),
            "runtime_schema_version": runtime_context.get("schema_version", ""),
            "engine_adapter_sequence": runtime_context.get("engine_adapter_sequence"),
            "preview_id": preview_id,
            "preview_cgs_hash": preview_cgs_hash,
            "preview_schema_version": preview_schema_version,
            "commit_class": engine_edit_commit_class(kind, str(message.get("field_path", "")), message.get("value")),
            "commit_supported": kind in SUPPORTED_ENGINE_EDIT_COMMIT_KINDS,
            "source": str(message.get("source", "builder")),
        }
        session.record_engine_edit(audit_record)

        await send_fn({
            "type": "engine_edit_ack",
            "accepted": accepted,
            "reason": str(response.get("reason", "")),
            "affected_entity_ids": affected,
            "status": status if isinstance(status, dict) else {},
            "audit": session.engine_edit_log[-1] if session.engine_edit_log else audit_record,
        })

    async def _handle_engine_edit_commit(
        self,
        session_id: str,
        message:    dict,
        send_fn:    SendFn,
        persist:    CGSPersistence,
        cgs_state:  dict,
    ) -> None:
        session = self._sm._sessions.get(session_id)
        if session is None:
            await _send_engine_edit_commit_ack(send_fn, False, "Session not found.", message)
            return

        mode_id = str(message.get("mode_id", ""))
        actor_id = str(message.get("actor_id", ""))
        component_name = str(message.get("component_name", ""))
        field_path = str(message.get("field_path", ""))
        value = message.get("value")
        commit_kind = str(message.get("kind") or "set_component_field")
        if commit_kind not in SUPPORTED_ENGINE_EDIT_COMMIT_KINDS:
            await _send_engine_edit_commit_ack(
                send_fn,
                False,
                (
                    f"Engine edit kind {commit_kind!r} is preview-only or unsupported for "
                    "durable CGS commits."
                ),
                message,
            )
            return
        try:
            component_type_id = int(message.get("component_type_id"))
        except (TypeError, ValueError):
            await _send_engine_edit_commit_ack(send_fn, False, "Component type id is required.", message)
            return

        if not _is_primitive_live_value(value):
            await _send_engine_edit_commit_ack(
                send_fn,
                False,
                "Only primitive live edit values can be committed.",
                message,
            )
            return

        preview_id = str(message.get("preview_id") or "")
        if not preview_id:
            await _send_engine_edit_commit_ack(
                send_fn,
                False,
                "Live edit commit requires the accepted preview_id from the audit row.",
                message,
            )
            return

        matched_live_edit = _matching_accepted_live_edit(session.engine_edit_log, message)
        if matched_live_edit is None:
            await _send_engine_edit_commit_ack(
                send_fn,
                False,
                "Run Live Edit first, then commit the accepted audit row.",
                message,
            )
            return
        if matched_live_edit.get("committed"):
            await _send_engine_edit_commit_ack(
                send_fn,
                False,
                "That live edit preview has already been committed.",
                message,
            )
            return

        current_meta = cgs_state.get("metadata", {}) if isinstance(cgs_state, dict) else {}
        current_cgs_hash = str(current_meta.get("cgs_hash", "") or "")
        current_schema_version = str(
            current_meta.get("schema_version") or current_meta.get("version") or ""
        )
        stale_reason = _engine_edit_commit_envelope_conflict_reason(
            message,
            matched_live_edit,
            session,
            current_cgs_hash,
            current_schema_version,
        )
        if stale_reason:
            await _send_engine_edit_commit_ack(send_fn, False, stale_reason, message)
            return

        resolved = _resolve_component_default_path(
            cgs_state,
            mode_id=mode_id,
            actor_id=actor_id,
            component_type_id=component_type_id,
            field_path=field_path,
        )
        if resolved is None:
            await _send_engine_edit_commit_ack(
                send_fn,
                False,
                "This live edit no longer matches a CGS component field.",
                message,
            )
            return

        cgs_path, _current_value = resolved
        preview_cgs_hash = str(
            message.get("preview_cgs_hash")
            or matched_live_edit.get("preview_cgs_hash", "")
            or ""
        )
        merging_after_newer_cgs = bool(preview_cgs_hash and preview_cgs_hash != current_cgs_hash)
        if merging_after_newer_cgs and not can_merge_engine_default_edit(cgs_path, value):
            await _send_engine_edit_commit_ack(
                send_fn,
                False,
                (
                    "Live edit conflict: newer CGS mutations exist and this edit is not "
                    "a primitive component default. Use PIL/GDE for structural edits."
                ),
                message,
            )
            return
        type_hint = _type_hint_for_live_value(value)
        summary = (
            f"Commit live edit: {actor_id}.{component_name or component_type_id}."
            f"{field_path} = {_short_value(value)}"
        )
        txn = {
            "source": "manual",
            "mutation_path": "engine_edit_commit",
            "operations": [{
                "op": "SET",
                "path": cgs_path,
                "value": value,
                "type_hint": type_hint,
                "field_name": field_path,
                "actor_id": actor_id,
                "type_id": component_type_id,
            }],
            "schema_delta_type": "value_mutation",
            "confidence_score": 1.0,
            "risk_level": "low",
            "required_recompile": False,
            "affected_systems": _systems_touching_component(cgs_state, component_type_id),
            "mutation_summary": summary[:200],
            "preview_id": preview_id,
            "preview_cgs_hash": preview_cgs_hash,
            "preview_schema_version": matched_live_edit.get("preview_schema_version", ""),
            "runtime_world_hash": matched_live_edit.get("runtime_world_hash", ""),
            "engine_adapter_sequence": matched_live_edit.get("engine_adapter_sequence"),
            "merged_after_newer_cgs": merging_after_newer_cgs,
        }
        transaction_id = _ensure_transaction_id(persist, txn)
        authority = _prepare_mutation_authority(
            persist,
            session,
            cgs_state,
            message,
            txn,
            mutation_path="engine_edit_commit",
        )
        if authority["rejected"]:
            _record_mutation_audit(
                persist,
                session_id=session_id,
                mutation_path="engine_edit_commit",
                actor=_mutation_actor(message, txn, "engine_adapter"),
                outcome="rejected_stale",
                transaction_id=transaction_id,
                version_ids=authority["version_ids"],
                pre_hash=authority["pre_hash"],
                post_hash=authority["pre_hash"],
                submitted_hash=authority["submitted_hash"],
                operations=txn["operations"],
                summary=summary,
                error=authority["reason"],
                rollback_status="not_started",
                runtime_context=_runtime_context(session),
            )
            await _send_engine_edit_commit_ack(send_fn, False, authority["reason"], message)
            return

        import asyncio
        loop = asyncio.get_event_loop()

        def _run_gde():
            return self._sm.apply_via_gde(session_id, txn, cgs_state)

        gde_result = await loop.run_in_executor(None, _run_gde)
        if not gde_result.success:
            reason = gde_result.error or "GDE could not commit the live edit."
            _record_mutation_audit(
                persist,
                session_id=session_id,
                mutation_path="engine_edit_commit",
                actor=_mutation_actor(message, txn, "engine_adapter"),
                outcome="rejected",
                transaction_id=transaction_id,
                version_ids=authority["version_ids"],
                pre_hash=authority["pre_hash"],
                post_hash=authority["pre_hash"],
                submitted_hash=authority["submitted_hash"],
                operations=txn["operations"],
                summary=summary,
                error=reason,
                rollback_status="not_started",
                runtime_context=_runtime_context(session),
            )
            await _send_engine_edit_commit_ack(send_fn, False, reason, message)
            return

        new_cgs = gde_result.new_cgs
        new_hash = gde_result.new_hash
        matched_live_edit["committed"] = True
        matched_live_edit["commit_cgs_hash"] = new_hash
        matched_live_edit["commit_transaction_id"] = transaction_id
        record = SnapshotRecord(
            cgs_hash       = new_hash,
            schema_version = new_cgs.get("metadata", {}).get("version", "0.1.0"),
            turn_index     = 0,
            mutation_count = 1,
            timestamp      = time.time(),
            summary        = summary,
            version_bump   = "patch",
            risk_level     = "low",
        )
        persist.save(new_cgs)
        persist.snapshot(new_cgs, record)

        cgs_state.clear()
        cgs_state.update(new_cgs)
        post_version_ids = _version_ids_for(session, new_cgs, persist, message, txn)
        _record_mutation_audit(
            persist,
            session_id=session_id,
            mutation_path="engine_edit_commit",
            actor=_mutation_actor(message, txn, "engine_adapter"),
            outcome="applied",
            transaction_id=transaction_id,
            version_ids=post_version_ids,
            pre_hash=authority["pre_hash"],
            post_hash=new_hash,
            submitted_hash=authority["submitted_hash"],
            operations=txn["operations"],
            summary=summary,
            error="",
            rollback_status="not_needed",
            runtime_context=_runtime_context(session),
        )

        await send_fn({
            "type":              "cgs_update",
            "cgs":               new_cgs,
            "hash":              new_hash,
            "snapshot":          record.to_dict(),
            "affected_node_ids": [f"actor:{mode_id}:{actor_id}", f"comp:{component_type_id}"],
            "gde_used":          gde_result.used_gde,
            "warnings":          gde_result.warnings,
            "transaction_id":    transaction_id,
            "version_ids":       post_version_ids,
        })
        await _send_engine_edit_commit_ack(
            send_fn,
            True,
            "Live edit committed to CGS.",
            message,
            cgs_hash=new_hash,
        )

    async def _handle_terminal_command(
        self,
        message: dict,
        send_fn: SendFn,
    ) -> None:
        command = str(message.get("command", "")).strip()
        await send_fn({
            "type": "terminal_output",
            "stream": "system",
            "text": (
                "Open the embedded terminal socket for shell commands. "
                f"Ignored command on main builder channel: {command[:80]}"
            ),
        })


# ── CGS helpers ───────────────────────────────────────────────────────────────

def _link_asset(
    cgs:            dict,
    actor_id:       str,
    comp_name:      str,
    placeholder_id: str,
    asset_path:     str,
) -> dict:
    import copy
    new_cgs = copy.deepcopy(cgs)
    for mode in new_cgs.get("modes", []):
        for actor in mode.get("actors", []):
            if actor.get("id") != actor_id:
                continue
            for comp in actor.get("components", []):
                if comp.get("name") != comp_name:
                    continue
                defaults = comp.setdefault("defaults", {})
                for k, v in list(defaults.items()):
                    if str(v) == placeholder_id:
                        defaults[k + "_path"] = asset_path
                        break
    return new_cgs


_SEMANTIC_EVENT_TARGETS: dict[str, set[str]] = {
    "movement.jump_started": {"Animation", "Audio", "Vfx"},
    "movement.landed": {"Animation", "Audio", "Vfx"},
    "interaction.interacted": {"Animation", "Audio", "Vfx"},
    "interaction.accepted": {"Animation", "Audio", "Vfx"},
    "inventory.pickup_accepted": {"Animation", "Audio", "Vfx"},
    "inventory.equipped": {"Animation", "Audio", "Vfx"},
    "inventory.dropped": {"Animation", "Audio", "Vfx"},
    "combat.attack_started": {"Animation", "Audio", "Vfx"},
    "combat.hit_confirmed": {"Animation", "Audio", "Vfx"},
    "combat.blocked": {"Animation", "Audio", "Vfx"},
    "combat.parried": {"Animation", "Audio", "Vfx"},
    "combat.killed": {"Animation", "Audio", "Vfx"},
    "animation.command_requested": {"Animation"},
    "animation.playback_started": {"Animation"},
    "animation.playback_completed": {"Animation"},
    "audio.playback_requested": {"Audio"},
    "audio.playback_completed": {"Audio"},
    "vfx.playback_requested": {"Vfx"},
    "vfx.playback_completed": {"Vfx"},
}

_PLAYBACK_ASSET_TYPES: dict[str, set[str]] = {
    "Animation": {"AnimationClip", "AnimationController"},
    "Audio": {"AudioClip", "AudioMusic"},
    "Vfx": {"Particle"},
}

_ASSET_STATUS_VALUES = {"Placeholder", "Linked", "Missing", "Unresolved"}
_ENGINE_TARGET_VALUES = {"godot", "unity", "unreal"}


def _set_semantic_bindings(cgs: dict, bindings: list[dict[str, Any]]) -> dict:
    new_cgs = copy.deepcopy(cgs)
    new_cgs["semantic_bindings"] = {"bindings": copy.deepcopy(bindings)}
    return new_cgs


def _sanitize_semantic_bindings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("semantic binding update requires bindings array")
    if len(value) > 512:
        raise ValueError("semantic binding update contains more than 512 bindings")
    seen: set[str] = set()
    sanitized: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        binding = _sanitize_semantic_binding(item, index)
        binding_id = binding["binding_id"]
        if binding_id in seen:
            raise ValueError(f"semantic binding {index}: duplicate binding_id {binding_id!r}")
        seen.add(binding_id)
        sanitized.append(binding)
    sanitized.sort(key=lambda item: (int(item.get("priority", 0)), str(item.get("binding_id", ""))))
    return sanitized


def _sanitize_semantic_binding(value: Any, index: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"semantic binding {index}: must be an object")
    binding_id = _required_semantic_string(value, "binding_id", index, max_len=128)
    event_name = _required_semantic_string(value, "event_name", index, max_len=128)
    playback_kind = _required_semantic_string(value, "playback_kind", index, max_len=32)
    if playback_kind not in _PLAYBACK_ASSET_TYPES:
        raise ValueError(f"semantic binding {index}: unsupported playback_kind {playback_kind!r}")
    event_targets = _SEMANTIC_EVENT_TARGETS.get(event_name)
    if event_targets is None:
        raise ValueError(f"semantic binding {index}: unknown semantic event {event_name!r}")
    if playback_kind not in event_targets:
        raise ValueError(
            f"semantic binding {index}: event {event_name!r} does not support {playback_kind} playback"
        )

    asset = value.get("asset")
    if not isinstance(asset, dict):
        raise ValueError(f"semantic binding {index}: asset must be an object")
    asset_id = _required_semantic_string(asset, "id", index, max_len=256, label="asset.id")
    asset_type = _required_semantic_string(asset, "asset_type", index, max_len=64, label="asset.asset_type")
    asset_status = _required_semantic_string(asset, "status", index, max_len=32, label="asset.status")
    if asset_type not in _PLAYBACK_ASSET_TYPES[playback_kind]:
        raise ValueError(
            f"semantic binding {index}: {playback_kind} playback cannot use asset type {asset_type!r}"
        )
    if asset_status not in _ASSET_STATUS_VALUES:
        raise ValueError(f"semantic binding {index}: invalid asset status {asset_status!r}")
    if asset_status == "Unresolved":
        raise ValueError(f"semantic binding {index}: unresolved asset references cannot be saved")

    semantic_action = _optional_semantic_string(value, "semantic_action", max_len=128)
    entity_selector = _sanitize_entity_selector(value.get("entity_selector"), index)
    parameters = _sanitize_semantic_parameters(value.get("parameters"), index)
    engine_targets = _engine_targets_from_parameters(parameters, index)
    if engine_targets:
        parameters["xace_engine_targets"] = ",".join(engine_targets)
    priority = value.get("priority", 0)
    if not isinstance(priority, int):
        raise ValueError(f"semantic binding {index}: priority must be an integer")
    enabled = value.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError(f"semantic binding {index}: enabled must be a boolean")

    return {
        "binding_id": binding_id,
        "event_name": event_name,
        "playback_kind": playback_kind,
        "asset": {
            "id": asset_id,
            "asset_type": asset_type,
            "status": asset_status,
        },
        "semantic_action": semantic_action,
        "entity_selector": entity_selector,
        "parameters": parameters,
        "enabled": enabled,
        "priority": priority,
    }


def _required_semantic_string(
    value: dict[str, Any],
    key: str,
    index: int,
    *,
    max_len: int,
    label: str | None = None,
) -> str:
    raw = value.get(key)
    text = raw.strip() if isinstance(raw, str) else ""
    display = label or key
    if not text:
        raise ValueError(f"semantic binding {index}: {display} must be a non-empty string")
    if len(text) > max_len:
        raise ValueError(f"semantic binding {index}: {display} exceeds {max_len} characters")
    return text


def _optional_semantic_string(value: dict[str, Any], key: str, *, max_len: int) -> str:
    raw = value.get(key, "")
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise ValueError(f"semantic binding: {key} must be a string when present")
    text = raw.strip()
    if len(text) > max_len:
        raise ValueError(f"semantic binding: {key} exceeds {max_len} characters")
    return text


def _sanitize_entity_selector(value: Any, index: int) -> Any:
    if value in ("SourceEntity", "TargetEntity"):
        return value
    if isinstance(value, dict) and isinstance(value.get("PayloadEntity"), dict):
        key = value["PayloadEntity"].get("key")
        if isinstance(key, str) and key.strip():
            return {"PayloadEntity": {"key": key.strip()}}
    if isinstance(value, dict) and isinstance(value.get("FixedEntity"), int) and value["FixedEntity"] > 0:
        return {"FixedEntity": value["FixedEntity"]}
    raise ValueError(f"semantic binding {index}: entity_selector must be SourceEntity, TargetEntity, PayloadEntity, or FixedEntity")


def _sanitize_semantic_parameters(value: Any, index: int) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"semantic binding {index}: parameters must be an object")
    result: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        if not isinstance(raw_key, str) or not raw_key.strip():
            raise ValueError(f"semantic binding {index}: parameter keys must be non-empty strings")
        key = raw_key.strip()
        if len(key) > 64:
            raise ValueError(f"semantic binding {index}: parameter key {key!r} exceeds 64 characters")
        if isinstance(raw_value, (str, int, float, bool)):
            text = str(raw_value).strip()
        elif raw_value is None:
            text = ""
        else:
            raise ValueError(f"semantic binding {index}: parameter {key!r} must be a scalar value")
        if text:
            result[key] = text[:512]
    return result


def _engine_targets_from_parameters(parameters: dict[str, str], index: int) -> list[str]:
    raw = parameters.get("xace_engine_targets", "")
    if not raw:
        return []
    targets = [item.strip().lower() for item in raw.split(",") if item.strip()]
    unknown = sorted(set(targets) - _ENGINE_TARGET_VALUES)
    if unknown:
        raise ValueError(f"semantic binding {index}: unknown engine target(s) {unknown}")
    return sorted(set(targets), key=targets.index)


def _compute_hash(cgs: dict) -> str:
    """Canonical SHA-256 hash of CGS content, excluding the hash field itself."""
    import copy
    stripped = copy.deepcopy(cgs)
    stripped.get("metadata", {}).pop("cgs_hash", None)
    canonical = json.dumps(stripped, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _static_precommit_conflict_reason(
    original_cgs: dict,
    proposed_cgs: dict,
    txn: dict | None = None,
) -> str:
    if StaticMutationConflictAnalyzer is None:
        return (
            "Static mutation conflict analyzer is unavailable; CGS persistence "
            "was refused before write."
        )
    report = StaticMutationConflictAnalyzer().validate(
        proposed_cgs=proposed_cgs,
        original_cgs=original_cgs,
        transaction=txn,
    )
    if report.is_valid:
        return ""
    return (report.errors or report.warnings or ["Static mutation conflict detected."])[0]


def _ensure_transaction_id(persist: Any, txn: dict) -> str:
    transaction_id = str(txn.get("transaction_id", "") or "")
    if transaction_id:
        return transaction_id
    if persist is not None and hasattr(persist, "next_transaction_id"):
        transaction_id = str(persist.next_transaction_id())
    else:
        transaction_id = _fallback_transaction_id()
    txn["transaction_id"] = transaction_id
    return transaction_id


def _fallback_transaction_id() -> str:
    global _FALLBACK_TXN_SEQUENCE
    _FALLBACK_TXN_SEQUENCE += 1
    return f"txn-fallback-{int(time.time() * 1000):013d}-{_FALLBACK_TXN_SEQUENCE:06d}"


def _prepare_mutation_authority(
    persist: Any,
    session: Any,
    cgs_state: dict,
    message: dict,
    txn: dict,
    *,
    mutation_path: str,
) -> dict[str, Any]:
    pre_hash = str(cgs_state.get("metadata", {}).get("cgs_hash", "") or "")
    disk_hash = _disk_cgs_hash(persist)
    submitted_hash = _submitted_cgs_hash(message, txn)
    version_ids = _version_ids_for(session, cgs_state, persist, message, txn)
    version_ids["cgs_hash"] = pre_hash
    txn["mutation_path"] = mutation_path
    txn["cgs_hash"] = pre_hash
    txn["parent_cgs_hash"] = submitted_hash or pre_hash
    txn["version_ids"] = version_ids

    reason = ""
    if submitted_hash and submitted_hash != pre_hash:
        reason = (
            "Stale CGS write rejected: submitted cgs_hash "
            f"{_short_hash(submitted_hash)} does not match current state {_short_hash(pre_hash)}."
        )
    elif disk_hash and pre_hash and disk_hash != pre_hash:
        reason = (
            "Stale CGS write rejected: in-memory state "
            f"{_short_hash(pre_hash)} differs from disk state {_short_hash(disk_hash)}."
        )
    elif submitted_hash and disk_hash and submitted_hash != disk_hash:
        reason = (
            "Stale CGS write rejected: submitted cgs_hash "
            f"{_short_hash(submitted_hash)} does not match disk state {_short_hash(disk_hash)}."
        )

    return {
        "rejected": bool(reason),
        "reason": reason,
        "pre_hash": pre_hash,
        "disk_hash": disk_hash,
        "submitted_hash": submitted_hash,
        "version_ids": version_ids,
    }


def _submitted_cgs_hash(message: dict, txn: dict) -> str:
    for value in (
        message.get("cgs_hash"),
        message.get("parent_cgs_hash"),
        (message.get("version_ids") or {}).get("cgs_hash") if isinstance(message.get("version_ids"), dict) else "",
        txn.get("parent_cgs_hash"),
        txn.get("cgs_hash"),
        (txn.get("version_ids") or {}).get("cgs_hash") if isinstance(txn.get("version_ids"), dict) else "",
    ):
        if value:
            return str(value)
    return ""


def _disk_cgs_hash(persist: Any) -> str:
    if persist is not None and hasattr(persist, "current_cgs_hash"):
        try:
            return str(persist.current_cgs_hash())
        except Exception:
            return ""
    return ""


def _version_ids_for(
    session: Any,
    cgs_state: dict,
    persist: Any,
    message: dict,
    txn: dict,
) -> dict[str, Any]:
    meta = cgs_state.get("metadata", {}) if isinstance(cgs_state, dict) else {}
    cgs_hash = str(meta.get("cgs_hash", "") or "")
    runtime = _runtime_context(session)
    return {
        "cgs_hash": cgs_hash,
        "schema_version": str(meta.get("schema_version") or meta.get("version") or ""),
        "execution_plan_version": _execution_plan_version(persist, cgs_hash),
        "runtime_world_hash": runtime.get("runtime_world_hash") or "unresolved",
        "runtime_tick": runtime.get("runtime_tick"),
        "engine_adapter_sequence": _engine_adapter_sequence(message, runtime),
    }


def _execution_plan_version(persist: Any, cgs_hash: str) -> str:
    if not cgs_hash or persist is None or not hasattr(persist, "load_execution_plan"):
        return "unresolved"
    try:
        plan = persist.load_execution_plan(cgs_hash)
    except Exception:
        plan = None
    if not plan:
        return "unresolved"
    return hashlib.sha256(str(plan).encode("utf-8")).hexdigest()


def _runtime_context(session: Any) -> dict[str, Any]:
    if session is None:
        return {
            "runtime_world_hash": "",
            "runtime_tick": None,
            "runtime_adapter_type": "",
            "engine_adapter_sequence": None,
            "cgs_hash": "",
            "schema_version": "",
        }
    last_tick = getattr(session, "runtime_last_tick", None)
    if not isinstance(last_tick, dict):
        last_tick = {}
    return {
        "runtime_world_hash": str(getattr(session, "runtime_last_hash", "") or last_tick.get("world_hash", "")),
        "runtime_tick": last_tick.get("tick"),
        "runtime_adapter_type": str(getattr(session, "runtime_adapter_type", "") or last_tick.get("adapter_type", "")),
        "engine_adapter_sequence": _first_present(
            last_tick.get("engine_adapter_sequence"),
            last_tick.get("adapter_sequence"),
            last_tick.get("sequence_id"),
            last_tick.get("sequence"),
        ),
        "cgs_hash": str(last_tick.get("cgs_hash", "") or ""),
        "schema_version": str(last_tick.get("schema_version", "") or ""),
    }


def _engine_adapter_sequence(message: dict, runtime: dict[str, Any]) -> Any:
    return _first_present(
        message.get("engine_adapter_sequence"),
        message.get("adapter_sequence"),
        runtime.get("engine_adapter_sequence"),
    )


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _prompt_apply_feedback(
    *,
    session: Any,
    txn: dict,
    message: dict,
    ok: bool,
    stage: str,
    code: str,
    reason: str,
    transaction_id: str = "",
    authority: dict[str, Any] | None = None,
    approval: dict[str, Any] | None = None,
    sgc_required: bool | None = None,
    sgc_validation: dict[str, Any] | None = None,
    sgc_error: dict[str, Any] | None = None,
    execution_plan: str | None = None,
    apply_validation: dict[str, Any] | None = None,
    rollback: dict[str, Any] | None = None,
    rollback_status: str = "",
    persist: Any | None = None,
    cgs_hash: str = "",
    warnings: list[Any] | None = None,
    started_at: float | None = None,
) -> dict[str, Any]:
    preview = _pending_prompt_preview(session)
    pending_result = _pending_prompt_result(session)
    classifier = pending_result.get("classifier") if isinstance(pending_result.get("classifier"), dict) else None
    result_preview = pending_result.get("preview") if isinstance(pending_result.get("preview"), dict) else None
    diff = preview or result_preview
    txn_id = transaction_id or str(txn.get("transaction_id", "") or "")
    sgc_is_required = bool(sgc_required) if sgc_required is not None else _prompt_apply_requires_sgc(txn)
    now = time.time()
    feedback = {
        "schema": "xace.prompt_apply_feedback.v1",
        "ok": bool(ok),
        "stage": str(stage),
        "code": str(code),
        "message": str(reason),
        "transaction_id": txn_id,
        "classifier": copy.deepcopy(classifier),
        "diff": copy.deepcopy(diff),
        "sgc": _prompt_apply_sgc_feedback(
            required=sgc_is_required,
            validation=sgc_validation,
            error=sgc_error,
            execution_plan=execution_plan,
        ),
        "runtime_load": _prompt_apply_validation_feedback(
            key="runtime_reload",
            label="runtime_load",
            apply_validation=apply_validation,
            message=message,
            session=session,
        ),
        "replay": _prompt_apply_validation_feedback(
            key="replay",
            label="replay",
            apply_validation=apply_validation,
            message=message,
            session=session,
        ),
        "adapter": _prompt_apply_validation_feedback(
            key="adapter",
            label="adapter",
            apply_validation=apply_validation,
            message=message,
            session=session,
        ),
        "rollback": _prompt_apply_rollback_feedback(
            rollback=rollback,
            fallback_status=rollback_status or ("not_needed" if ok else "not_started"),
        ),
        "cost": _prompt_apply_cost_feedback(preview=diff, pending_result=pending_result),
        "latency": _prompt_apply_latency_feedback(preview=diff, started_at=started_at, now=now),
        "proof_links": _prompt_apply_proof_links(
            persist=persist,
            cgs_hash=cgs_hash or str(authority.get("pre_hash", "") if authority else ""),
            transaction_id=txn_id,
            execution_plan=execution_plan,
            rollback=rollback,
        ),
        "approval": copy.deepcopy(approval or {}),
        "typed_operation_provenance": _prompt_apply_typed_operation_provenance(txn),
        "composite_prompt_plan": _prompt_apply_composite_prompt_plan(txn),
        "authority": {
            "pre_hash": str((authority or {}).get("pre_hash", "") or ""),
            "submitted_hash": str((authority or {}).get("submitted_hash", "") or ""),
            "version_ids": copy.deepcopy((authority or {}).get("version_ids", {})),
        },
        "warnings": list(warnings or []),
        "error": {
            "stage": str(stage),
            "code": str(code),
            "message": str(reason),
        },
    }
    return feedback


def _record_agent_proposal_discard(
    store: Any,
    *,
    persist: Any,
    session_id: str,
    session: Any,
    txn: Any,
    message: dict,
    cgs_state: dict,
) -> dict[str, Any]:
    if not isinstance(txn, dict):
        return {}
    proposal = _agent_proposal_record(txn)
    proposal_id = str(proposal.get("proposal_id") or "")
    if not proposal_id:
        return {}
    transaction_id = _ensure_transaction_id(persist, txn)
    pre_hash = str(cgs_state.get("metadata", {}).get("cgs_hash", "") or "")
    submitted_hash = str(txn.get("parent_cgs_hash") or txn.get("cgs_hash") or pre_hash)
    version_ids = _version_ids_for(session, cgs_state, persist, message, txn)
    typed_operation_provenance = _prompt_apply_typed_operation_provenance(txn)
    _record_mutation_audit(
        persist,
        session_id=session_id,
        mutation_path="agent_proposal_discard",
        actor=_mutation_actor(message, txn, "agent"),
        outcome="discarded",
        transaction_id=transaction_id,
        version_ids=version_ids,
        pre_hash=pre_hash,
        post_hash=pre_hash,
        submitted_hash=submitted_hash,
        operations=_prompt_apply_audit_operations(txn),
        summary=str(txn.get("mutation_summary", "")),
        error="",
        rollback_status="not_started",
        runtime_context=_runtime_context(session),
        typed_operation_provenance=typed_operation_provenance,
    )
    logged = False
    error = ""
    if store is not None:
        try:
            store.update_proposal_status(
                proposal_id,
                status="discarded",
                mutation_transaction_id=transaction_id,
            )
            logged = True
        except Exception as exc:  # noqa: BLE001 - audit must not block discard.
            error = str(exc)[:300]
            log.warning("Failed to update agent proposal discard status: %s", exc)
    return {
        "schema": "xace.agent_proposal_disposition.v1",
        "proposal_id": proposal_id,
        "status": "discarded",
        "transaction_id": transaction_id,
        "logged": logged,
        "audit_recorded": bool(persist is not None and hasattr(persist, "record_mutation_audit")),
        "error": error,
    }


def _record_agent_proposal_applied(
    store: Any,
    *,
    session_id: str,
    txn: dict,
    approval: dict[str, Any],
    transaction_id: str,
    pre_hash: str,
    post_hash: str,
    summary: str,
    apply_feedback: dict[str, Any],
    typed_operation_provenance: dict[str, Any],
) -> dict[str, Any]:
    proposal = _agent_proposal_record(txn)
    proposal_id = str(proposal.get("proposal_id") or "")
    if not proposal_id:
        return {}
    approval_id = str(
        approval.get("approval_id")
        or approval.get("preview_id")
        or approval.get("id")
        or ""
    )
    provider_id = str(proposal.get("provider_id") or "agent")
    logged = False
    error = ""
    if store is not None:
        try:
            store.update_proposal_status(
                proposal_id,
                status="applied",
                approval_id=approval_id,
                mutation_transaction_id=transaction_id,
            )
            store.record_mutation_lineage(
                AgentMutationLineageRecord(
                    mutation_id=_agent_mutation_id(proposal_id, transaction_id, post_hash),
                    proposal_id=proposal_id,
                    xace_session_id=session_id,
                    provider_id=provider_id,
                    base_cgs_hash=pre_hash,
                    result_cgs_hash=post_hash,
                    gde_transaction_id=transaction_id,
                    status="applied",
                    summary=summary or "Applied agent proposal through Builder approval.",
                    sgc_plan_id=str(
                        (apply_feedback.get("proof_links", {}) or {})
                        .get("execution_plan", {})
                        .get("path", "")
                    ),
                    runtime_validation_id=str(
                        (apply_feedback.get("runtime_load", {}) or {}).get("status", "")
                    ),
                    metadata={
                        "typed_operation_provenance": typed_operation_provenance,
                        "proof_links": apply_feedback.get("proof_links", {}),
                    },
                )
            )
            logged = True
        except Exception as exc:  # noqa: BLE001 - apply already succeeded.
            error = str(exc)[:300]
            log.warning("Failed to record agent proposal apply lineage: %s", exc)
    return {
        "schema": "xace.agent_proposal_disposition.v1",
        "proposal_id": proposal_id,
        "status": "applied",
        "transaction_id": transaction_id,
        "approval_id": approval_id,
        "logged": logged,
        "error": error,
    }


def _agent_proposal_record(txn: Any) -> dict[str, Any]:
    if not isinstance(txn, dict):
        return {}
    proposal = txn.get("agent_proposal")
    return copy.deepcopy(proposal) if isinstance(proposal, dict) else {}


def _agent_mutation_id(proposal_id: str, transaction_id: str, cgs_hash: str) -> str:
    digest = hashlib.sha256(
        json.dumps(
            {
                "proposal_id": proposal_id,
                "transaction_id": transaction_id,
                "cgs_hash": cgs_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:16]
    return f"agent-mutation-{digest}"


def _pending_prompt_preview(session: Any) -> dict[str, Any] | None:
    preview = getattr(session, "pending_prompt_preview", None)
    return copy.deepcopy(preview) if isinstance(preview, dict) else None


def _pending_prompt_result(session: Any) -> dict[str, Any]:
    result = getattr(session, "pending_prompt_result", None)
    return copy.deepcopy(result) if isinstance(result, dict) else {}


def _prompt_apply_typed_operation_batch(txn: dict) -> dict[str, Any] | None:
    batch = txn.get("typed_operation_batch")
    return batch if isinstance(batch, dict) else None


def _prompt_apply_composite_prompt_plan(txn: dict) -> dict[str, Any]:
    plan = txn.get("composite_prompt_plan")
    return copy.deepcopy(plan) if isinstance(plan, dict) else {}


def _prompt_apply_audit_operations(txn: dict) -> list[Any]:
    """Return the submitted operation records without lowering typed IDs to paths."""
    if "typed_operation_batch" in txn:
        batch = _prompt_apply_typed_operation_batch(txn)
        operations = batch.get("operations") if batch is not None else None
    else:
        operations = txn.get("operations")
    return copy.deepcopy(operations) if isinstance(operations, list) else []


def _prompt_apply_operation_count(txn: dict) -> int:
    return len(_prompt_apply_audit_operations(txn))


def _prompt_apply_typed_operation_provenance(txn: dict) -> dict[str, Any]:
    batch = _prompt_apply_typed_operation_batch(txn)
    if batch is None:
        return {}
    operations = _prompt_apply_audit_operations(txn)
    canonical = json.dumps(
        batch,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    provenance = {
        "schema": str(batch.get("schema", "")),
        "request_id": str(batch.get("request_id", "")),
        "prompt_id": str(batch.get("prompt_id", "")),
        "batch_hash": hashlib.sha256(canonical).hexdigest(),
        "operation_ids": [
            str(operation.get("operation_id", ""))
            for operation in operations
            if isinstance(operation, dict)
        ],
        "operation_kinds": [
            str(operation.get("kind", ""))
            for operation in operations
            if isinstance(operation, dict)
        ],
    }
    composite_plan = _prompt_apply_composite_prompt_plan(txn)
    if composite_plan:
        composite_hash = hashlib.sha256(
            json.dumps(
                composite_plan,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        provenance["composite_prompt_plan_hash"] = composite_hash
        provenance["composite_prompt_plan_schema"] = str(
            composite_plan.get("schema", "")
        )
        provenance["composite_operation_order"] = list(
            composite_plan.get("operation_order") or []
        )
        rollback = composite_plan.get("rollback_plan")
        if isinstance(rollback, dict):
            provenance["composite_rollback_pre_hash"] = str(
                rollback.get("pre_cgs_hash", "")
            )
    return provenance


def _prompt_apply_requires_sgc(txn: dict) -> bool:
    return (
        "typed_operation_batch" in txn
        or bool(txn.get("required_recompile", False))
        or str(txn.get("schema_delta_type", "")).startswith("structural")
    )


def _prompt_apply_sgc_feedback(
    *,
    required: bool,
    validation: dict[str, Any] | None,
    error: dict[str, Any] | None,
    execution_plan: str | None,
) -> dict[str, Any]:
    validation_copy = copy.deepcopy(validation) if isinstance(validation, dict) else None
    error_copy = copy.deepcopy(error) if isinstance(error, dict) else None
    if error_copy:
        status = str(error_copy.get("status") or "failed")
        ok = False
    elif validation_copy:
        ok = bool(validation_copy.get("ok", True)) and bool(validation_copy.get("load_ready", True))
        status = "passed" if ok else "failed"
    elif required:
        ok = None
        status = "not_run"
    else:
        ok = True
        status = "not_required"
    return {
        "schema": "xace.prompt_apply_feedback.sgc.v1",
        "required": bool(required),
        "ok": ok,
        "status": status,
        "validation": validation_copy,
        "error": error_copy,
        "execution_plan_available": bool(execution_plan),
    }


def _prompt_apply_validation_feedback(
    *,
    key: str,
    label: str,
    apply_validation: dict[str, Any] | None,
    message: dict,
    session: Any,
) -> dict[str, Any]:
    if isinstance(apply_validation, dict) and isinstance(apply_validation.get(key), dict):
        result = copy.deepcopy(apply_validation[key])
        result.setdefault("schema", f"xace.prompt_apply_feedback.{label}.v1")
        return result
    requirements = message.get("validation_requirements") if isinstance(message, dict) else {}
    if not isinstance(requirements, dict):
        requirements = {}
    required = bool(requirements.get(label)) or bool(requirements.get(key))
    if key == "runtime_reload":
        required = required or bool(getattr(session, "runtime_connected", False))
    return {
        "schema": f"xace.prompt_apply_feedback.{label}.v1",
        "required": required,
        "attempted": False,
        "accepted": None,
        "reason": "not_reached" if required else "",
    }


def _prompt_apply_rollback_feedback(
    *,
    rollback: dict[str, Any] | None,
    fallback_status: str,
) -> dict[str, Any]:
    if not isinstance(rollback, dict):
        return {
            "schema": "xace.prompt_apply_feedback.rollback.v1",
            "status": fallback_status,
            "restored": None,
            "report": None,
        }
    restored = bool(rollback.get("restored", False))
    return {
        "schema": "xace.prompt_apply_feedback.rollback.v1",
        "status": "restored_pre_apply" if restored else "restore_failed",
        "restored": restored,
        "restored_cgs_hash": str(rollback.get("restored_cgs_hash", "") or ""),
        "failed_cgs_hash": str(rollback.get("failed_cgs_hash", "") or ""),
        "report": copy.deepcopy(rollback),
    }


def _prompt_apply_cost_feedback(
    *,
    preview: dict[str, Any] | None,
    pending_result: dict[str, Any],
) -> dict[str, Any]:
    cost_diff = preview.get("cost_diff") if isinstance(preview, dict) and isinstance(preview.get("cost_diff"), dict) else {}
    observed = _as_float(cost_diff.get("observed_cost_cents"), _as_float(pending_result.get("cost_cents"), 0.0))
    tokens = int(_as_float(cost_diff.get("token_count"), _as_float(pending_result.get("tokens"), 0.0)))
    apply_cost = _as_float(cost_diff.get("estimated_apply_cost_cents"), 0.0)
    return {
        "schema": "xace.prompt_apply_feedback.cost.v1",
        "provider": str(cost_diff.get("provider", "") or ""),
        "model": str(cost_diff.get("model", "") or ""),
        "observed_prompt_cost_cents": observed,
        "estimated_apply_cost_cents": apply_cost,
        "total_cost_cents": observed + apply_cost,
        "token_count": tokens,
        "source": str(cost_diff.get("source", "prompt_diff_preview") or "prompt_diff_preview"),
    }


def _prompt_apply_latency_feedback(
    *,
    preview: dict[str, Any] | None,
    started_at: float | None,
    now: float,
) -> dict[str, Any]:
    generated_at = _as_float(preview.get("generated_at"), 0.0) if isinstance(preview, dict) else 0.0
    apply_started = float(started_at or now)
    return {
        "schema": "xace.prompt_apply_feedback.latency.v1",
        "apply_started_at": apply_started,
        "completed_at": now,
        "apply_latency_ms": max(0, int((now - apply_started) * 1000)),
        "prompt_to_apply_ms": max(0, int((now - generated_at) * 1000)) if generated_at > 0 else None,
    }


def _prompt_apply_proof_links(
    *,
    persist: Any | None,
    cgs_hash: str,
    transaction_id: str,
    execution_plan: str | None,
    rollback: dict[str, Any] | None,
) -> dict[str, Any]:
    failed_hash = str((rollback or {}).get("failed_cgs_hash", "") or "") if isinstance(rollback, dict) else ""
    hash_for_artifacts = cgs_hash or failed_hash
    return {
        "schema": "xace.prompt_apply_feedback.proof_links.v1",
        "project_root": str(getattr(persist, "_root", "") or ""),
        "transaction_id": transaction_id,
        "audit_dataset": ".xace/audit/mutations.jsonl",
        "audit_ledger": ".xace/audit/transactions.jsonl",
        "cgs": "game.cgs.json",
        "snapshot": f".xace/snapshots/{hash_for_artifacts}.json" if hash_for_artifacts else "",
        "execution_plan": {
            "available": bool(execution_plan),
            "path": f".xace/execution_plans/{hash_for_artifacts}.plan.json" if hash_for_artifacts else "",
        },
        "sgc_proof_bundle": {
            "available": bool(execution_plan),
            "path": f".xace/proof/sgc/{hash_for_artifacts}" if hash_for_artifacts else "",
        },
        "rollback": {
            "available": isinstance(rollback, dict),
            "failed_cgs_hash": failed_hash,
            "restored_cgs_hash": str((rollback or {}).get("restored_cgs_hash", "") or "") if isinstance(rollback, dict) else "",
        },
    }


def _as_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


class PromptApplyRecoveryError(RuntimeError):
    def __init__(self, stage: str, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.stage = stage
        self.code = code
        self.message = message
        self.details = copy.deepcopy(details) if isinstance(details, dict) else None


def _capture_prompt_apply_recovery_state(
    *,
    session: Any,
    cgs_state: dict,
    version_ids: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": "xace.prompt_apply_recovery_state.v1",
        "pre_apply_cgs": copy.deepcopy(cgs_state),
        "version_ids": dict(version_ids),
        "session": _capture_prompt_apply_session_state(session),
        "runtime": _capture_session_runtime_state(session),
    }


def _capture_prompt_apply_session_state(session: Any) -> dict[str, Any]:
    if session is None:
        return {
            "pending_txn": None,
            "pending_clar_id": None,
            "pending_prompt_clarification": None,
            "pending_prompt_preview": None,
            "pending_prompt_result": None,
            "engine_edit_log": [],
        }
    return {
        "pending_txn": copy.deepcopy(getattr(session, "pending_txn", None)),
        "pending_clar_id": copy.deepcopy(getattr(session, "pending_clar_id", None)),
        "pending_prompt_clarification": copy.deepcopy(getattr(session, "pending_prompt_clarification", None)),
        "pending_prompt_preview": copy.deepcopy(getattr(session, "pending_prompt_preview", None)),
        "pending_prompt_result": copy.deepcopy(getattr(session, "pending_prompt_result", None)),
        "engine_edit_log": copy.deepcopy(getattr(session, "engine_edit_log", [])),
    }


def _capture_session_runtime_state(session: Any) -> dict[str, Any]:
    if session is None:
        return {
            "runtime_connected": False,
            "runtime_adapter_type": "",
            "runtime_engine_version": "",
            "runtime_last_tick": None,
            "runtime_last_hash": "",
        }
    return {
        "runtime_connected": bool(getattr(session, "runtime_connected", False)),
        "runtime_adapter_type": str(getattr(session, "runtime_adapter_type", "") or ""),
        "runtime_engine_version": str(getattr(session, "runtime_engine_version", "") or ""),
        "runtime_last_tick": copy.deepcopy(getattr(session, "runtime_last_tick", None)),
        "runtime_last_hash": str(getattr(session, "runtime_last_hash", "") or ""),
    }


def _restore_prompt_apply_session_state(session: Any, session_state: dict[str, Any]) -> dict[str, Any]:
    report = {
        "schema": "xace.prompt_apply_session_restore.v1",
        "restored": False,
        "ui_status_restored": False,
        "prompt_pending_restored": False,
        "adapter_edit_log_restored": False,
        "engine_edit_log_length": 0,
        "error": "",
    }
    if session is None:
        report["error"] = "session unavailable for prompt apply rollback"
        return report
    if not isinstance(session_state, dict):
        session_state = {}
    try:
        session.pending_txn = copy.deepcopy(session_state.get("pending_txn"))
        session.pending_clar_id = copy.deepcopy(session_state.get("pending_clar_id"))
        session.pending_prompt_clarification = copy.deepcopy(session_state.get("pending_prompt_clarification"))
        session.pending_prompt_preview = copy.deepcopy(session_state.get("pending_prompt_preview"))
        session.pending_prompt_result = copy.deepcopy(session_state.get("pending_prompt_result"))
        engine_edit_log = session_state.get("engine_edit_log")
        session.engine_edit_log = copy.deepcopy(engine_edit_log if isinstance(engine_edit_log, list) else [])
        report["engine_edit_log_length"] = len(session.engine_edit_log)
        report["prompt_pending_restored"] = session.pending_txn is not None
        report["ui_status_restored"] = True
        report["adapter_edit_log_restored"] = True
        report["restored"] = True
        try:
            session.touch()
        except Exception:
            pass
    except Exception as exc:  # noqa: BLE001
        report["error"] = str(exc)
    return report


def _restore_session_runtime_state(session: Any, runtime_state: dict[str, Any]) -> None:
    if session is None:
        return
    session.runtime_connected = bool(runtime_state.get("runtime_connected", False))
    session.runtime_adapter_type = str(runtime_state.get("runtime_adapter_type", "") or "")
    session.runtime_engine_version = str(runtime_state.get("runtime_engine_version", "") or "")
    session.runtime_last_tick = copy.deepcopy(runtime_state.get("runtime_last_tick"))
    session.runtime_last_hash = str(runtime_state.get("runtime_last_hash", "") or "")


def _prompt_apply_recovery_error(
    *,
    persist: Any,
    session: Any,
    cgs_state: dict,
    recovery_state: dict[str, Any],
    failed_cgs_hash: str,
    transaction_id: str,
    stage: str,
    code: str,
    message: str,
    authority: dict[str, Any],
    txn: dict,
    summary: str,
    approval: dict[str, Any],
    runtime_control: RuntimeControlClient | None,
    session_id: str,
    apply_message: dict | None = None,
    started_at: float | None = None,
    sgc_required: bool = False,
    sgc_validation: dict[str, Any] | None = None,
    sgc_error: dict[str, Any] | None = None,
    execution_plan: str | None = None,
    apply_validation: dict[str, Any] | None = None,
    action: str = "",
) -> dict[str, Any]:
    rollback = _restore_failed_prompt_apply(
        persist=persist,
        session=session,
        cgs_state=cgs_state,
        recovery_state=recovery_state,
        failed_cgs_hash=failed_cgs_hash,
        transaction_id=transaction_id,
        reason=message,
        runtime_control=runtime_control,
        session_id=session_id,
    )
    _record_mutation_audit(
        persist,
        session_id=session_id,
        mutation_path="pil_apply",
        actor=_mutation_actor({}, txn, "prompt"),
        outcome="rejected_recovered",
        transaction_id=transaction_id,
        version_ids=authority["version_ids"],
        pre_hash=authority["pre_hash"],
        post_hash=authority["pre_hash"],
        submitted_hash=authority["submitted_hash"],
        operations=_prompt_apply_audit_operations(txn),
        summary=summary,
        error=message,
        rollback_status="restored_pre_apply" if rollback.get("restored") else "restore_failed",
        runtime_context=_runtime_context(session),
        approval=approval,
        rollback=rollback,
        typed_operation_provenance=_prompt_apply_typed_operation_provenance(txn),
    )
    apply_feedback = _prompt_apply_feedback(
        session=session,
        txn=txn,
        message=apply_message or {},
        ok=False,
        stage=stage,
        code=code,
        reason=message,
        transaction_id=transaction_id,
        authority=authority,
        approval=approval,
        sgc_required=sgc_required,
        sgc_validation=sgc_validation,
        sgc_error=sgc_error,
        execution_plan=execution_plan,
        apply_validation=apply_validation,
        rollback=rollback,
        persist=persist,
        cgs_hash=failed_cgs_hash,
        started_at=started_at,
    )
    response = {
        "type": "server_error",
        "code": code,
        "message": message,
        "stage": stage,
        "transaction_id": transaction_id,
        "rollback": rollback,
        "approval": approval,
        "apply_feedback": apply_feedback,
        "typed_operation_provenance": _prompt_apply_typed_operation_provenance(txn),
    }
    if action:
        response["action"] = action
    if sgc_error is not None:
        response["sgc_error"] = copy.deepcopy(sgc_error)
    if sgc_validation is not None:
        response["sgc_validation"] = copy.deepcopy(sgc_validation)
    if apply_validation is not None:
        response["apply_validation"] = copy.deepcopy(apply_validation)
    return response


def _restore_failed_prompt_apply(
    *,
    persist: Any,
    session: Any,
    cgs_state: dict,
    recovery_state: dict[str, Any],
    failed_cgs_hash: str,
    transaction_id: str,
    reason: str,
    runtime_control: RuntimeControlClient | None,
    session_id: str,
) -> dict[str, Any]:
    pre_cgs = copy.deepcopy(recovery_state.get("pre_apply_cgs") or {})
    if persist is not None and hasattr(persist, "restore_prompt_apply_failure"):
        rollback = persist.restore_prompt_apply_failure(
            pre_cgs,
            failed_cgs_hash=failed_cgs_hash,
            transaction_id=transaction_id,
            reason=reason,
        )
    else:
        rollback = {
            "schema": "xace.prompt_apply_recovery.v1",
            "transaction_id": transaction_id,
            "restored": False,
            "restored_cgs_hash": str(pre_cgs.get("metadata", {}).get("cgs_hash", "")),
            "failed_cgs_hash": str(failed_cgs_hash or ""),
            "artifacts_removed": {},
            "errors": ["persistence_recovery_unavailable"],
        }
    cgs_state.clear()
    cgs_state.update(pre_cgs)
    session_restore = _restore_prompt_apply_session_state(
        session,
        recovery_state.get("session", {}),
    )
    rollback["session_restore"] = session_restore
    rollback["ui_status_restored"] = bool(session_restore.get("ui_status_restored", False))
    if session_restore.get("error"):
        rollback.setdefault("errors", []).append(str(session_restore["error"]))
    _restore_session_runtime_state(session, recovery_state.get("runtime", {}))
    if session is not None and getattr(session, "gde", None) is not None:
        try:
            session.gde.load_cgs(pre_cgs, session_id=session_id)
            rollback["gde_restored"] = True
        except Exception as exc:  # noqa: BLE001
            rollback.setdefault("errors", []).append(f"gde_restore_failed: {exc}")
            rollback["gde_restored"] = False
            rollback["restored"] = False
    rollback["runtime_restore"] = _restore_runtime_after_prompt_failure(
        runtime_control=runtime_control,
        session_id=session_id,
        version_ids=dict(recovery_state.get("version_ids") or {}),
        attempted=bool(recovery_state.get("runtime", {}).get("runtime_connected")),
    )
    if rollback["runtime_restore"].get("error"):
        rollback.setdefault("errors", []).append(str(rollback["runtime_restore"]["error"]))
    rollback["adapter_visible_effects_restored"] = bool(session_restore.get("adapter_edit_log_restored")) and (
        not rollback["runtime_restore"].get("attempted") or bool(rollback["runtime_restore"].get("accepted"))
    )
    rollback["restored"] = bool(rollback.get("restored")) and not rollback.get("errors")
    return rollback


def _restore_runtime_after_prompt_failure(
    *,
    runtime_control: RuntimeControlClient | None,
    session_id: str,
    version_ids: dict[str, Any],
    attempted: bool,
) -> dict[str, Any]:
    report = {
        "schema": "xace.prompt_apply_runtime_restore.v1",
        "attempted": False,
        "accepted": False,
        "error": "",
    }
    if not attempted:
        return report
    report["attempted"] = True
    if runtime_control is None:
        report["error"] = "runtime control client unavailable for restore"
        return report
    try:
        response = runtime_control.send_control(
            "reload_cgs",
            session_id=session_id,
            version_ids=version_ids,
        )
    except (OSError, RuntimeControlError) as exc:
        report["error"] = str(exc)
        return report
    report["accepted"] = bool(response.get("accepted", False))
    if not report["accepted"]:
        report["error"] = str(response.get("reason") or "runtime rejected restored CGS reload")
    return report


def _persist_prompt_apply_artifacts(
    *,
    persist: Any,
    new_cgs: dict,
    new_hash: str,
    record: SnapshotRecord,
    execution_plan: str | None,
    sgc_validation: dict[str, Any] | None,
) -> None:
    try:
        persist.save(new_cgs)
    except Exception as exc:  # noqa: BLE001
        raise PromptApplyRecoveryError(
            "cgs_persist",
            "PROMPT_APPLY_PERSIST_FAILED",
            f"CGS persistence failed after prompt apply: {exc}",
        ) from exc
    try:
        persist.snapshot(new_cgs, record)
    except Exception as exc:  # noqa: BLE001
        raise PromptApplyRecoveryError(
            "snapshot_persist",
            "PROMPT_APPLY_SNAPSHOT_FAILED",
            f"Snapshot persistence failed after prompt apply: {exc}",
        ) from exc
    if not execution_plan:
        return
    try:
        persisted_plan_json = persist.save_execution_plan(
            new_hash,
            execution_plan,
            cgs=new_cgs,
            validation=sgc_validation,
        )
    except Exception as exc:  # noqa: BLE001
        raise PromptApplyRecoveryError(
            "execution_plan_persist",
            "PROMPT_APPLY_PLAN_PERSIST_FAILED",
            f"ExecutionPlan persistence failed after prompt apply: {exc}",
        ) from exc
    if hasattr(persist, "save_sgc_proof_bundle"):
        try:
            persist.save_sgc_proof_bundle(new_cgs, persisted_plan_json, validation=sgc_validation)
        except Exception as exc:  # noqa: BLE001
            raise PromptApplyRecoveryError(
                "sgc_proof_persist",
                "PROMPT_APPLY_PROOF_PERSIST_FAILED",
                f"SGC proof persistence failed after prompt apply: {exc}",
            ) from exc


def _run_prompt_apply_validation_hooks(
    *,
    runtime_control: RuntimeControlClient | None,
    session: Any,
    session_id: str,
    message: dict,
    post_version_ids: dict[str, Any],
) -> dict[str, Any]:
    requirements = message.get("validation_requirements")
    if not isinstance(requirements, dict):
        requirements = {}
    runtime_required = bool(requirements.get("runtime_reload")) or bool(getattr(session, "runtime_connected", False))
    replay_required = bool(requirements.get("replay"))
    adapter_required = bool(requirements.get("adapter"))
    report: dict[str, Any] = {
        "schema": "xace.prompt_apply_validation.v1",
        "runtime_reload": {"required": runtime_required, "attempted": False, "accepted": None, "reason": ""},
        "replay": {"required": replay_required, "attempted": False, "accepted": None, "reason": ""},
        "adapter": {"required": adapter_required, "attempted": False, "accepted": None, "reason": ""},
    }
    if not any((runtime_required, replay_required, adapter_required)):
        return report
    if runtime_control is None:
        raise PromptApplyRecoveryError(
            "runtime_validation",
            "PROMPT_APPLY_RUNTIME_VALIDATION_FAILED",
            "Runtime validation was required but the runtime control client is unavailable.",
            copy.deepcopy(report),
        )

    status: dict[str, Any] = {}
    if runtime_required or adapter_required:
        report["runtime_reload"]["attempted"] = True
        try:
            reload_ack = runtime_control.send_control(
                "reload_cgs",
                session_id=session_id,
                version_ids=post_version_ids,
            )
        except (OSError, RuntimeControlError) as exc:
            report["runtime_reload"]["reason"] = str(exc)
            raise PromptApplyRecoveryError(
                "runtime_validation",
                "PROMPT_APPLY_RUNTIME_VALIDATION_FAILED",
                f"Runtime reload failed after prompt apply: {exc}",
                copy.deepcopy(report),
            ) from exc
        status = reload_ack.get("status") if isinstance(reload_ack.get("status"), dict) else {}
        report["runtime_reload"]["accepted"] = bool(reload_ack.get("accepted", False))
        report["runtime_reload"]["reason"] = str(reload_ack.get("reason") or "")
        if session is not None:
            session.update_runtime_status(
                connected=bool(status.get("engine_connected", getattr(session, "runtime_connected", False))),
                last_tick=status,
            )
        if not report["runtime_reload"]["accepted"]:
            raise PromptApplyRecoveryError(
                "runtime_validation",
                "PROMPT_APPLY_RUNTIME_VALIDATION_FAILED",
                report["runtime_reload"]["reason"] or "Runtime rejected the prompt-mutated CGS reload.",
                copy.deepcopy(report),
            )

    if replay_required:
        report["replay"]["attempted"] = True
        for action in ("replay_record", "replay_validate"):
            try:
                replay_ack = runtime_control.send_control(action, session_id=session_id)
            except (OSError, RuntimeControlError) as exc:
                report["replay"]["reason"] = str(exc)
                raise PromptApplyRecoveryError(
                    "replay_validation",
                    "PROMPT_APPLY_REPLAY_VALIDATION_FAILED",
                    f"{action} failed after prompt apply: {exc}",
                    copy.deepcopy(report),
                ) from exc
            if not bool(replay_ack.get("accepted", False)):
                report["replay"]["accepted"] = False
                report["replay"]["reason"] = str(replay_ack.get("reason") or f"{action} rejected")
                raise PromptApplyRecoveryError(
                    "replay_validation",
                    "PROMPT_APPLY_REPLAY_VALIDATION_FAILED",
                    report["replay"]["reason"],
                    copy.deepcopy(report),
                )
        report["replay"]["accepted"] = True

    if adapter_required:
        report["adapter"]["attempted"] = True
        if not status:
            try:
                snapshot_ack = runtime_control.send_control("snapshot", session_id=session_id)
            except (OSError, RuntimeControlError) as exc:
                report["adapter"]["reason"] = str(exc)
                raise PromptApplyRecoveryError(
                    "adapter_validation",
                    "PROMPT_APPLY_ADAPTER_VALIDATION_FAILED",
                    f"Adapter validation snapshot failed after prompt apply: {exc}",
                    copy.deepcopy(report),
                ) from exc
            status = snapshot_ack.get("status") if isinstance(snapshot_ack.get("status"), dict) else {}
        adapter_connected = bool(status.get("engine_connected", False))
        report["adapter"]["accepted"] = adapter_connected
        if not adapter_connected:
            report["adapter"]["reason"] = "Runtime did not report an engine adapter connection after prompt apply."
            raise PromptApplyRecoveryError(
                "adapter_validation",
                "PROMPT_APPLY_ADAPTER_VALIDATION_FAILED",
                report["adapter"]["reason"],
                copy.deepcopy(report),
            )

    return report


def _mutation_actor(message: dict, txn: dict, fallback: str) -> str:
    return str(
        message.get("actor")
        or message.get("source")
        or txn.get("actor")
        or txn.get("source")
        or fallback
    )


def _record_mutation_audit(
    persist: Any,
    *,
    session_id: str,
    mutation_path: str,
    actor: str,
    outcome: str,
    transaction_id: str,
    version_ids: dict[str, Any],
    pre_hash: str,
    post_hash: str,
    submitted_hash: str,
    operations: list[Any],
    summary: str,
    error: str,
    rollback_status: str,
    runtime_context: dict[str, Any],
    approval: dict[str, Any] | None = None,
    rollback: dict[str, Any] | None = None,
    typed_operation_provenance: dict[str, Any] | None = None,
    proof_links: dict[str, Any] | None = None,
    prompt_history: dict[str, Any] | None = None,
) -> None:
    if persist is None or not hasattr(persist, "record_mutation_audit"):
        return
    timestamp = time.time()
    timestamp_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp))
    typed_audit = bool(typed_operation_provenance)
    operation_summaries = [
        _operation_audit_summary(op, idx, typed=typed_audit)
        for idx, op in enumerate(operations)
    ]
    ledger_entry = {
        "timestamp": timestamp,
        "timestamp_iso": timestamp_iso,
        "transaction_id": transaction_id,
        "mutation_path": mutation_path,
        "pre_state_hash": pre_hash,
        "post_state_hash": post_hash,
        "submitted_cgs_hash": submitted_hash,
        "outcome": outcome,
        "operation_count": len(operation_summaries),
    }
    dataset_entry = {
        "schema": "xace.mutation_audit.v1",
        "timestamp": timestamp,
        "timestamp_iso": timestamp_iso,
        "session_id": session_id,
        "actor": actor,
        "mutation_path": mutation_path,
        "outcome": outcome,
        "transaction_id": transaction_id,
        "applied_transaction_id": transaction_id if outcome == "applied" else "",
        "pre_state_hash": pre_hash,
        "post_state_hash": post_hash,
        "submitted_cgs_hash": submitted_hash,
        "version_ids": dict(version_ids),
        "operation_count": len(operation_summaries),
        "operations": operation_summaries,
        "summary": str(summary)[:500],
        "error": str(error)[:1000],
        "rollback_status": rollback_status,
        "runtime": dict(runtime_context),
    }
    if approval:
        dataset_entry["approval"] = dict(approval)
    if rollback:
        dataset_entry["rollback"] = dict(rollback)
    if proof_links:
        dataset_entry["proof_links"] = copy.deepcopy(proof_links)
    if prompt_history:
        history_payload = copy.deepcopy(prompt_history)
        dataset_entry["prompt_history"] = history_payload
        if isinstance(history_payload, dict):
            sequence = history_payload.get("sequence") or history_payload.get("entry_sequence")
            if sequence:
                ledger_entry["prompt_history_sequence"] = int(sequence)
            action = history_payload.get("action")
            if action:
                ledger_entry["prompt_history_action"] = str(action)
    if typed_operation_provenance:
        provenance = copy.deepcopy(typed_operation_provenance)
        ledger_entry["typed_operation_batch_hash"] = str(provenance.get("batch_hash", ""))
        dataset_entry["typed_operation_provenance"] = provenance
    try:
        persist.record_mutation_audit(ledger_entry=ledger_entry, dataset_entry=dataset_entry)
    except Exception as exc:
        log.warning("Failed to persist mutation audit record: %s", exc)


def _snapshot_record_for_hash(persist: Any, cgs_hash: str) -> dict[str, Any]:
    if persist is None or not hasattr(persist, "list_snapshots"):
        return {}
    target = str(cgs_hash or "")
    try:
        for record in persist.list_snapshots(limit=100):
            if getattr(record, "cgs_hash", "") == target:
                return record.to_dict() if hasattr(record, "to_dict") else {}
    except Exception:
        return {}
    return {}


def _operation_audit_summary(op: Any, index: int, *, typed: bool = False) -> dict[str, Any]:
    if not isinstance(op, dict):
        if typed:
            return {"index": index, "type": "invalid", "kind": "", "operation_id": ""}
        return {"index": index, "type": "invalid", "path": "", "entity": "", "component": ""}
    if typed or "kind" in op or "operation_id" in op:
        kind = str(op.get("kind", ""))
        summary = {
            "index": index,
            "type": kind,
            "kind": kind,
            "operation_id": str(op.get("operation_id", "")),
            "explanation": str(op.get("explanation", ""))[:500],
        }
        for key in (
            "mode_id",
            "actor_id",
            "component_type_id",
            "component_name",
            "system_id",
            "event_name",
            "rule_id",
            "asset_id",
        ):
            value = op.get(key)
            if value not in (None, ""):
                summary[key] = value
        return summary
    return {
        "index": index,
        "type": str(op.get("op", "")),
        "path": str(op.get("path", "")),
        "entity": str(op.get("actor_id") or op.get("entity_id") or ""),
        "component": str(op.get("type_id") or op.get("component_type_id") or ""),
    }


def _short_hash(value: str) -> str:
    return value[:12] + ("..." if len(value) > 12 else "")


async def _send_engine_edit_commit_ack(
    send_fn: SendFn,
    accepted: bool,
    reason: str,
    message: dict,
    cgs_hash: str = "",
) -> None:
    payload = {
        "type": "engine_edit_commit_ack",
        "accepted": accepted,
        "reason": reason,
        "audit_ts": message.get("audit_ts"),
        "preview_id": message.get("preview_id"),
    }
    if cgs_hash:
        payload["cgs_hash"] = cgs_hash
    await send_fn(payload)


def _has_matching_accepted_live_edit(log_entries: list[dict], message: dict) -> bool:
    return _matching_accepted_live_edit(log_entries, message) is not None


def _matching_accepted_live_edit(log_entries: list[dict], message: dict) -> dict | None:
    preview_id = str(message.get("preview_id") or "")
    audit_ts = message.get("audit_ts")
    for entry in reversed(log_entries):
        if not entry.get("accepted"):
            continue
        if entry.get("kind") != "set_component_field":
            continue
        if preview_id and str(entry.get("preview_id") or "") != preview_id:
            continue
        if audit_ts is not None and entry.get("ts") != audit_ts:
            continue
        if str(entry.get("mode_id", "")) != str(message.get("mode_id", "")):
            continue
        if str(entry.get("actor_id", "")) != str(message.get("actor_id", "")):
            continue
        if str(entry.get("component_type_id", "")) != str(message.get("component_type_id", "")):
            continue
        if str(entry.get("field_path", "")) != str(message.get("field_path", "")):
            continue
        if not _same_json_value(entry.get("value"), message.get("value")):
            continue
        return entry
    return None


def _same_json_value(left: Any, right: Any) -> bool:
    return json.dumps(left, sort_keys=True, separators=(",", ":")) == json.dumps(
        right,
        sort_keys=True,
        separators=(",", ":"),
    )


def _runtime_context_from_status(session: Any, status: dict[str, Any]) -> dict[str, Any]:
    base = _runtime_context(session)
    if not isinstance(status, dict):
        status = {}
    return {
        "runtime_world_hash": str(
            status.get("latest_world_hash")
            or status.get("runtime_world_hash")
            or status.get("world_hash")
            or base.get("runtime_world_hash")
            or ""
        ),
        "runtime_tick": status.get("tick", base.get("runtime_tick")),
        "runtime_adapter_type": str(
            status.get("adapter_type") or base.get("runtime_adapter_type") or ""
        ),
        "engine_adapter_sequence": _engine_adapter_sequence(status, base),
        "cgs_hash": str(status.get("cgs_hash") or base.get("cgs_hash") or ""),
        "schema_version": str(status.get("schema_version") or base.get("schema_version") or ""),
    }


def _engine_edit_preview_id(
    *,
    session_id: str,
    kind: str,
    entity_id: str,
    message: dict,
    preview_cgs_hash: str,
    runtime_context: dict[str, Any],
) -> str:
    core = {
        "session_id": session_id,
        "kind": kind,
        "entity_id": entity_id,
        "mode_id": message.get("mode_id", ""),
        "actor_id": message.get("actor_id", ""),
        "component_type_id": message.get("component_type_id"),
        "field_path": message.get("field_path", ""),
        "value": message.get("value"),
        "preview_cgs_hash": preview_cgs_hash,
        "runtime_world_hash": runtime_context.get("runtime_world_hash", ""),
        "engine_adapter_sequence": runtime_context.get("engine_adapter_sequence"),
        "issued_at_ms": int(time.time() * 1000),
    }
    digest = hashlib.sha256(
        json.dumps(core, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return f"engine-preview-{core['issued_at_ms']:013d}-{digest}"


def _engine_edit_commit_envelope_conflict_reason(
    message: dict,
    audit: dict,
    session: Any,
    current_cgs_hash: str,
    current_schema_version: str,
) -> str:
    preview_id = str(message.get("preview_id") or "")
    if preview_id != str(audit.get("preview_id") or ""):
        return "Stale live edit rejected: preview_id does not match the accepted audit row."

    preview_cgs_hash = _message_version_value(message, "preview_cgs_hash")
    if not preview_cgs_hash:
        return "Stale live edit rejected: preview_cgs_hash is required."
    if preview_cgs_hash != str(audit.get("preview_cgs_hash") or ""):
        return "Stale live edit rejected: preview_cgs_hash changed since preview."

    submitted_cgs_hash = _message_version_value(message, "cgs_hash")
    if not submitted_cgs_hash:
        return "Stale CGS write rejected: cgs_hash is required for live edit commit."
    if submitted_cgs_hash != current_cgs_hash:
        return (
            "Stale CGS write rejected: submitted cgs_hash "
            f"{_short_hash(submitted_cgs_hash)} does not match current {_short_hash(current_cgs_hash)}."
        )

    submitted_schema = _message_version_value(message, "schema_version")
    if not submitted_schema:
        return "Stale live edit rejected: schema_version is required."
    if submitted_schema != current_schema_version:
        return (
            "Stale live edit rejected: submitted schema_version "
            f"{submitted_schema!r} does not match current {current_schema_version!r}."
        )
    preview_schema = str(audit.get("preview_schema_version") or "")
    if preview_schema and preview_schema != current_schema_version:
        return (
            "Stale live edit rejected: schema_version changed since preview "
            f"({preview_schema!r} -> {current_schema_version!r})."
        )

    runtime_hash = _message_version_value(message, "runtime_world_hash")
    audit_runtime_hash = str(audit.get("runtime_world_hash") or "")
    if not runtime_hash:
        return "Stale live edit rejected: runtime_world_hash is required."
    if audit_runtime_hash and runtime_hash != audit_runtime_hash:
        return "Stale live edit rejected: runtime_world_hash changed since preview."
    current_runtime_hash = str(_runtime_context(session).get("runtime_world_hash") or "")
    if current_runtime_hash and runtime_hash != current_runtime_hash:
        return "Stale live edit rejected: runtime hash no longer matches the previewed state."

    submitted_sequence = _message_version_value(message, "engine_adapter_sequence")
    if submitted_sequence == "":
        return "Stale live edit rejected: engine_adapter_sequence is required."
    audit_sequence = _version_to_string(audit.get("engine_adapter_sequence"))
    if audit_sequence != "" and submitted_sequence != audit_sequence:
        return "Stale live edit rejected: adapter sequence changed since preview."
    current_sequence = _version_to_string(_runtime_context(session).get("engine_adapter_sequence"))
    if current_sequence != "" and submitted_sequence != current_sequence:
        return "Stale live edit rejected: adapter sequence no longer matches runtime state."

    return ""


def _message_version_value(message: dict, field: str) -> str:
    value = message.get(field)
    if value in (None, "") and isinstance(message.get("version_ids"), dict):
        value = message["version_ids"].get(field)
    return _version_to_string(value)


def _version_to_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _resolve_component_default_path(
    cgs: dict,
    *,
    mode_id: str,
    actor_id: str,
    component_type_id: int,
    field_path: str,
) -> tuple[str, Any] | None:
    if not mode_id or not actor_id or not _is_portable_field_path(field_path):
        return None
    for mode in cgs.get("modes", []):
        if str(mode.get("id", "")) != mode_id:
            continue
        for actor in mode.get("actors", []):
            if str(actor.get("id", "")) != actor_id:
                continue
            for component in actor.get("components", []):
                if int(component.get("type_id", -1)) != component_type_id:
                    continue
                defaults = component.get("defaults", {})
                value = _read_nested_default(defaults, field_path)
                if value is None:
                    return None
                return (
                    f"modes.{mode_id}.actors.{actor_id}.components."
                    f"{component_type_id}.defaults.{field_path}",
                    value,
                )
    return None


def _read_nested_default(defaults: Any, field_path: str) -> Any:
    current = defaults
    for segment in field_path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current


def _is_portable_field_path(field_path: str) -> bool:
    if not field_path or len(field_path) > 160:
        return False
    for segment in field_path.split("."):
        if not segment:
            return False
        if not all(char.isalnum() or char in {"_", "-"} for char in segment):
            return False
    return True


def _is_primitive_live_value(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    return isinstance(value, (str, int, float))


def _type_hint_for_live_value(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    return "str"


def _systems_touching_component(cgs: dict, component_type_id: int) -> list[str]:
    touched: list[str] = []
    systems = list(cgs.get("global_systems", []))
    for mode in cgs.get("modes", []):
        systems.extend(mode.get("systems", []))
    for system in systems:
        reads = system.get("reads", [])
        writes = system.get("writes", [])
        if component_type_id in reads or component_type_id in writes:
            sid = str(system.get("id", ""))
            if sid and sid not in touched:
                touched.append(sid)
    return touched


def _short_value(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 48 else text[:45] + "..."


def _runtime_snapshot_to_engine_tick(response: dict[str, Any]) -> dict[str, Any] | None:
    snapshot = response.get("snapshot")
    if not isinstance(snapshot, dict):
        return None
    status = response.get("status")
    if not isinstance(status, dict):
        status = {}
    entities = snapshot.get("entities", [])
    if not isinstance(entities, list):
        entities = []
    canonical = json.dumps(
        {
            "tick": snapshot.get("tick", 0),
            "entities": entities,
            "spawned_ids": snapshot.get("spawned_ids", []),
            "destroyed_ids": snapshot.get("destroyed_ids", []),
            "events": snapshot.get("events", []),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    world_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    adapter_type = str(status.get("adapter_type") or "headless").lower()
    if adapter_type not in {"unity", "godot", "unreal", "webgl", "headless"}:
        adapter_type = "headless"
    return {
        "type": "engine_tick",
        "tick": int(snapshot.get("tick") or 0),
        "fps": 60,
        "world_hash": world_hash,
        "ms_per_tick": 1000.0 / 60.0,
        "entity_count": len(entities),
        "system_timings": {},
        "is_deterministic": True,
        "adapter_type": adapter_type,
        "entities": entities,
        "spawned_ids": snapshot.get("spawned_ids", []),
        "destroyed_ids": snapshot.get("destroyed_ids", []),
        "events": snapshot.get("events", []),
    }
