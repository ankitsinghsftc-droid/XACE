"""
ws_message_router.py — WebSocket Message Router (Phase 14.5)
=============================================================
Routes incoming WebSocket messages from the browser to the correct
session operation. Returns response dicts to be sent back.

## Phase 14.5 changes vs Phase 14
    - pil_apply now calls SessionManager.apply_via_gde() instead of
      the naive _apply_operations() helper. This routes through:
          PIL MutationTransaction
              → session_manager.apply_via_gde()
                  → GDEOrchestrator.process_transaction()  [if available]
                      → TransactionExecutor.execute()
                      → ConsistencyValidator.validate()
                      → CGSManager.commit()
                  → _naive_apply() fallback if GDE unavailable
              → SGC recompile if required_recompile=True
              → CGSPersistence.save() + snapshot()
              → cgs_update sent to UI

## Routing Table
    pil_process     → session_manager.run_pil()
    pil_answer      → session_manager.submit_clarification_answer()
    pil_apply       → GDE commit + SGC recompile + persist
    pil_discard     → clear pending mutation
    cgs_request     → load CGS from disk + send session_init
    mode_change     → update session mode
    asset_link      → write asset path ref to CGS + persist
    cgs_rollback    → load snapshot + set as current CGS
    ping            → pong
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Awaitable, Callable

from cgs_persistence import CGSPersistence, SnapshotRecord
from session_manager import SessionManager, _serialize_pil_result

log = logging.getLogger(__name__)

SendFn = Callable[[dict], Awaitable[None]]


class WSMessageRouter:
    """
    Stateless router — all state lives in SessionManager and CGSPersistence.
    """

    def __init__(self, session_manager: SessionManager) -> None:
        self._sm = session_manager

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
                await self._handle_pil_apply(session_id, send_fn, persist, cgs_state)

            elif msg_type == "pil_discard":
                self._sm.clear_pending(session_id)
                await send_fn({"type": "pil_discard_ack"})

            elif msg_type == "cgs_request":
                await self._handle_cgs_request(session_id, message, send_fn, persist, cgs_state)

            elif msg_type == "mode_change":
                await self._handle_mode_change(session_id, message, send_fn)

            elif msg_type == "model_change":
                await self._handle_model_change(session_id, message, send_fn)

            elif msg_type == "asset_link":
                await self._handle_asset_link(session_id, message, send_fn, persist, cgs_state)

            elif msg_type == "cgs_rollback":
                await self._handle_cgs_rollback(session_id, message, send_fn, persist, cgs_state)

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
            await send_fn({
                "type":    "server_error",
                "code":    "HANDLER_ERROR",
                "message": f"Error processing {msg_type!r}: {str(exc)[:200]}",
            })

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

        result = await self._sm.run_pil(
            session_id = session_id,
            prompt     = prompt,
            cgs        = cgs_state,
            cgs_hash   = cgs_hash,
            mode       = mode,
            send_fn    = send_fn,
        )
        await send_fn({"type": "pil_result", "result": result})

    async def _handle_pil_answer(
        self,
        session_id: str,
        message:    dict,
        send_fn:    SendFn,
    ) -> None:
        clar_id = message.get("clarification_id", "")
        answer  = message.get("answer", "")

        response = await self._sm.submit_clarification_answer(
            session_id, clar_id, answer
        )
        await send_fn({"type": "pil_answer_ack", **response})

    async def _handle_pil_apply(
        self,
        session_id: str,
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
                    → _naive_apply() fallback
                → SGC recompile (if required_recompile=True and sgc_bin set)
                → persist to disk
                → cgs_update → UI
        """
        session = self._sm._sessions.get(session_id)
        if session is None or session.pending_txn is None:
            await send_fn({
                "type":    "server_error",
                "code":    "NO_PENDING_TXN",
                "message": "No pending mutation to apply.",
            })
            return

        txn       = session.pending_txn
        required_recompile = txn.get("required_recompile", False)
        summary   = txn.get("mutation_summary", "")
        risk      = txn.get("risk_level", "low")
        affected  = txn.get("affected_systems", [])
        schema_delta_type = txn.get("schema_delta_type", "value_mutation")

        # ── Step 1: Apply via GDE (or naive fallback) ─────────────────────────
        import asyncio
        loop = asyncio.get_event_loop()

        def _run_gde():
            return self._sm.apply_via_gde(session_id, txn, cgs_state)

        gde_result = await loop.run_in_executor(None, _run_gde)

        if not gde_result.success:
            log.error("GDE apply failed for session %s: %s", session_id[:12], gde_result.error)
            await send_fn({
                "type":    "server_error",
                "code":    "GDE_APPLY_FAILED",
                "message": gde_result.error or "GDE could not apply this mutation.",
                "warnings": gde_result.warnings,
            })
            return

        new_cgs  = gde_result.new_cgs
        new_hash = gde_result.new_hash

        # Log GDE path taken
        if gde_result.used_gde:
            log.info("GDE committed mutation: hash=%s", new_hash[:8])
        else:
            log.warning("Naive apply used for session %s (GDE unavailable)", session_id[:12])

        # ── Step 2: SGC recompile (structural mutations only) ─────────────────
        execution_plan: str | None = None
        if required_recompile or schema_delta_type.startswith("structural"):
            def _run_sgc():
                return self._sm.recompile_sgc(new_cgs)
            execution_plan = await loop.run_in_executor(None, _run_sgc)
            if execution_plan:
                log.info("SGC recompile complete for session %s", session_id[:12])
            else:
                log.info("SGC skipped (no binary or no systems)")

        # ── Step 3: Determine version bump ────────────────────────────────────
        if schema_delta_type.startswith("structural"):
            version_bump = "minor"
        elif schema_delta_type == "rule_change":
            version_bump = "patch"
        else:
            version_bump = "patch"

        # ── Step 4: Persist CGS + snapshot ────────────────────────────────────
        persist.save(new_cgs)

        record = SnapshotRecord(
            cgs_hash       = new_hash,
            schema_version = new_cgs.get("metadata", {}).get("version", "0.1.0"),
            turn_index     = 0,
            mutation_count = len(txn.get("operations", [])),
            timestamp      = time.time(),
            summary        = summary,
            version_bump   = version_bump,
            risk_level     = risk,
        )
        persist.snapshot(new_cgs, record)

        # Save ExecutionPlan alongside snapshot if SGC ran
        if execution_plan:
            try:
                persist.save_execution_plan(new_hash, execution_plan)
            except Exception as exc:
                log.warning("Failed to persist ExecutionPlan: %s", exc)

        # ── Step 5: Update in-memory state ────────────────────────────────────
        cgs_state.clear()
        cgs_state.update(new_cgs)
        self._sm.clear_pending(session_id)

        # ── Step 6: Build affected node IDs for graph highlight ───────────────
        affected_node_ids = [f"sys:*:{sid}" for sid in affected]
        # Also highlight any actors that were structurally changed
        if schema_delta_type in ("structural_add", "structural_remove"):
            for op in txn.get("operations", []):
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
                    "cgs_hash": "0000000000000000",
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
            self._sm._model_provider = provider
            self._sm._model_name     = model

            # Rebuild pipeline with new adapter
            from session_manager import StreamingInferenceAdapter, _build_adapter
            loop         = asyncio.get_event_loop()

            async def send_proxy(msg: dict) -> None:
                await send_fn(msg)

            real_adapter = _build_adapter(
                provider   = provider,
                model_name = model,
                ollama_url = self._sm._ollama_url,
            )
            streaming = StreamingInferenceAdapter(real_adapter, send_proxy, loop)

            if session.pipeline is not None:
                session.pipeline._adapter = real_adapter
                session.pipeline._llm_orch._adapter = streaming
                _log.info("Hot-swapped model: %s/%s for session %s",
                          provider, model, session_id[:12])

            await send_fn({
                "type":     "model_change_ack",
                "provider": provider,
                "model":    model,
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

        new_cgs  = _link_asset(cgs_state, actor_id, comp_name, placeholder_id, asset_path)
        new_hash = _compute_hash(new_cgs)
        new_cgs["metadata"]["cgs_hash"] = new_hash

        persist.save(new_cgs)
        cgs_state.clear()
        cgs_state.update(new_cgs)

        await send_fn({
            "type":              "cgs_update",
            "cgs":               new_cgs,
            "hash":              new_hash,
            "snapshot":          {},
            "affected_node_ids": [f"actor:*:{actor_id}"],
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
        try:
            snap = persist.load_snapshot(target_hash)
        except Exception as exc:
            await send_fn({
                "type":    "server_error",
                "code":    "SNAPSHOT_NOT_FOUND",
                "message": str(exc),
            })
            return

        # If GDE session is active, roll it back too
        session = self._sm._sessions.get(session_id)
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

        await send_fn({
            "type":              "cgs_update",
            "cgs":               snap,
            "hash":              target_hash,
            "snapshot":          {},
            "affected_node_ids": [],
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


def _compute_hash(cgs: dict) -> str:
    """Stable SHA-256 hash of the CGS content (excluding the hash field itself)."""
    import copy
    stripped = copy.deepcopy(cgs)
    stripped.get("metadata", {}).pop("cgs_hash", None)
    canonical = json.dumps(stripped, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]
