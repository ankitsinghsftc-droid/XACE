"""
ws_message_router.py — WebSocket Message Router
================================================
Routes incoming WebSocket messages from the browser to the correct
session operation. Returns response dicts to be sent back.

## Routing Table

    pil_process     → session_manager.run_pil()
    pil_answer      → session_manager.submit_clarification_answer()
    pil_apply       → apply pending mutation to CGS + persist
    pil_discard     → clear pending mutation
    cgs_request     → load CGS from disk + send session_init
    mode_change     → update session mode
    asset_link      → write asset path ref to CGS + persist
    cgs_rollback    → load snapshot + set as current CGS
    ping            → pong

## Error Handling

    All handlers are wrapped in try/except. Errors produce
    server_error messages, never crash the WebSocket connection.

## CGS Mutations

    pil_apply and asset_link modify the CGS in-memory and on disk.
    Both use atomic writes via CGSPersistence.
    Both emit cgs_update back to the client.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Awaitable, Callable

from packages.workspace.src.server.cgs_persistence import CGSPersistence, SnapshotRecord
from packages.workspace.src.server.session_manager import SessionManager, _serialize_pil_result

log = logging.getLogger(__name__)

SendFn = Callable[[dict], Awaitable[None]]


class WSMessageRouter:
    """
    Stateless router — all state lives in SessionManager and CGSPersistence.

    Usage (in builder_server.py):
        router = WSMessageRouter(session_manager)
        await router.route(session_id, message, send_fn)
    """

    def __init__(self, session_manager: SessionManager) -> None:
        self._sm = session_manager

    async def route(
        self,
        session_id: str,
        message:    dict,
        send_fn:    SendFn,
        persist:    CGSPersistence,
        cgs_state:  dict,     # mutable ref — updated by pil_apply / asset_link
    ) -> None:
        """
        Routes one incoming message.

        Parameters
        ----------
        session_id : str
        message    : dict — parsed JSON from WebSocket
        send_fn    : callable — sends a dict as JSON to the client
        persist    : CGSPersistence — for disk operations
        cgs_state  : dict — mutable, passed by reference from builder_server
        """
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
        session = self._sm._sessions.get(session_id)
        if session is None or session.pending_txn is None:
            await send_fn({
                "type": "server_error", "code": "NO_PENDING_TXN",
                "message": "No pending mutation to apply.",
            })
            return

        txn = session.pending_txn
        # Apply operations to in-memory CGS
        new_cgs = _apply_operations(cgs_state, txn.get("operations", []))

        # Compute new hash
        new_hash = _compute_hash(new_cgs)
        new_cgs["metadata"]["cgs_hash"] = new_hash

        # Persist
        persist.save(new_cgs)

        # Record snapshot
        record = SnapshotRecord(
            cgs_hash       = new_hash,
            schema_version = new_cgs["metadata"].get("schema_version", "0.0.0"),
            turn_index     = 0,
            mutation_count = 0,
            timestamp      = time.time(),
            summary        = txn.get("mutation_summary", ""),
            version_bump   = "patch",
            risk_level     = txn.get("risk_level", "low"),
        )
        persist.snapshot(new_cgs, record)

        # Update in-memory reference
        cgs_state.clear()
        cgs_state.update(new_cgs)

        # Clear pending
        self._sm.clear_pending(session_id)

        # Compute affected node IDs for graph highlight
        affected = txn.get("affected_systems", [])
        affected_node_ids = [f"sys:*:{sid}" for sid in affected]

        await send_fn({
            "type":             "cgs_update",
            "cgs":              new_cgs,
            "hash":             new_hash,
            "snapshot":         record.to_dict(),
            "affected_node_ids": affected_node_ids,
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
                    "name": "New Project", "cgs_hash": "0" * 64,
                    "version": "0.1.0", "schema_version": "0.1.0",
                },
                "global_systems": [], "modes": [],
            })

        snapshots = persist.list_snapshots(limit=50)

        await send_fn({
            "type":      "session_init",
            "session_id": session_id,
            "cgs":        cgs_state,
            "hash":       cgs_state.get("metadata", {}).get("cgs_hash", ""),
            "snapshots":  [s.to_dict() for s in snapshots],
            "version":    cgs_state.get("metadata", {}).get("schema_version", "0.0.0"),
        })

    async def _handle_mode_change(
        self,
        session_id: str,
        message:    dict,
        send_fn:    SendFn,
    ) -> None:
        mode = message.get("mode", "COLLABORATIVE")
        session = self._sm._sessions.get(session_id)
        if session:
            session.current_mode = mode
        await send_fn({"type": "mode_change_ack", "mode": mode})

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

        # Write the path ref into CGS defaults
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
                "type": "server_error", "code": "SNAPSHOT_NOT_FOUND",
                "message": str(exc),
            })
            return

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


# ── CGS mutation helpers ──────────────────────────────────────────────────────

def _apply_operations(cgs: dict, ops: list[dict]) -> dict:
    """
    Applies a list of MutationOp dicts to a CGS.
    Returns a deep-copied modified CGS.
    Supports SET/SCALE operations on component fields.
    Structural ops (ADD_ACTOR etc.) require more complex handling
    and are left for a future iteration — they currently no-op safely.
    """
    import copy
    new_cgs = copy.deepcopy(cgs)

    for op in ops:
        op_type = op.get("op", "")
        path    = op.get("path", "")
        value   = op.get("value")

        if op_type in ("SET", "SCALE"):
            _apply_set_op(new_cgs, path, value, op_type)
        # Structural ops: ADD_ACTOR, REMOVE_ACTOR etc. — complex path resolution
        # deferred to a dedicated PathApplicator class in a future commit

    return new_cgs


def _apply_set_op(cgs: dict, path: str, value: Any, op_type: str) -> None:
    """
    Resolves a CGS path like:
        modes[mode_default].actors[actor_zombie].components[5].defaults.max_linear_speed
    and applies the value (SET) or multiplies (SCALE).
    """
    import re
    try:
        # Parse path segments
        segments = re.split(r'\.|(?=\[)', path)
        obj = cgs
        for i, seg in enumerate(segments[:-1]):
            if seg.startswith("[") and seg.endswith("]"):
                key = seg[1:-1]
                if isinstance(obj, list):
                    # Find by id field or numeric index
                    if key.isdigit():
                        obj = obj[int(key)]
                    else:
                        obj = next((x for x in obj if str(x.get("id", x.get("type_id", ""))) == key), obj)
                elif isinstance(obj, dict):
                    obj = obj.get(key, obj)
            else:
                if isinstance(obj, dict):
                    obj = obj.get(seg, {})

        # Apply final segment
        last = segments[-1]
        if last.startswith("["):
            last = last[1:-1]

        if isinstance(obj, dict) and last in obj:
            if op_type == "SCALE":
                current = obj[last]
                if isinstance(current, (int, float)):
                    obj[last] = current * value
            else:
                obj[last] = value

    except Exception as exc:
        log.warning("Failed to apply op path=%r: %s", path, exc)


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
    """Canonical SHA-256 hash of CGS content, excluding the hash field itself."""
    import copy
    stripped = copy.deepcopy(cgs)
    stripped.get("metadata", {}).pop("cgs_hash", None)
    canonical = json.dumps(stripped, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()
