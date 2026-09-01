"""AG-007 WebSocket-facing stream manager for provider agent events.

This module is deliberately provider-neutral. It turns adapter ``AgentEvent``
objects into compact UI messages, persists them when a session store is
available, and manages cancellation without granting mutation authority.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import hashlib
import json
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from secret_redaction import redact_exception, redact_text, redact_value

from .contracts import (
    AgentAdapter,
    AgentContractError,
    AgentEvent,
    AgentEventType,
    AgentSessionHandle,
    AgentStartRequest,
    AgentTurnRequest,
    JsonValue,
    normalize_json_value,
    utc_now_iso,
)
from .proposal_ingress import AgentProposalIngressError, AgentProposalIngressGate
from .registry import AgentAdapterRegistry, AgentRegistryError, create_default_registry
from .session_store import AgentSessionStore, AgentSessionStoreError, AgentStoredSession


AGENT_EVENT_STREAM_SCHEMA = "xace.agent_event_stream.v1"

AGENT_WS_TURN = "agent_turn"
AGENT_WS_CANCEL = "agent_cancel"
AGENT_WS_EVENT = "agent_event"
AGENT_WS_STATUS = "agent_status"

AGENT_STATUS_IDLE = "idle"
AGENT_STATUS_STARTING = "starting"
AGENT_STATUS_RUNNING = "running"
AGENT_STATUS_CANCELLING = "cancelling"
AGENT_STATUS_CANCELLED = "cancelled"
AGENT_STATUS_COMPLETED = "completed"
AGENT_STATUS_ERROR = "error"
AGENT_STATUS_UNAVAILABLE = "unavailable"

SendFn = Callable[[dict[str, JsonValue]], Awaitable[None]]


class AgentEventStreamError(RuntimeError):
    """Raised when the Agent Event Stream cannot fail closed safely."""


@dataclass(frozen=True)
class AgentTurnCommandResult:
    """Acknowledgement for an ``agent_turn`` or ``agent_cancel`` command."""

    accepted: bool
    code: str
    message: str
    status: Mapping[str, Any]
    task: asyncio.Task[Any] | None = field(default=None, compare=False, repr=False)
    schema: str = AGENT_EVENT_STREAM_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != AGENT_EVENT_STREAM_SCHEMA:
            raise AgentEventStreamError(
                f"schema must equal {AGENT_EVENT_STREAM_SCHEMA!r}"
            )
        object.__setattr__(self, "message", redact_text(self.message))
        object.__setattr__(self, "status", _json_object(self.status, "status"))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": self.schema,
            "accepted": self.accepted,
            "code": self.code,
            "message": self.message,
            "status": dict(self.status),
        }


@dataclass
class _ActiveAgentTurn:
    session_id: str
    provider_id: str
    turn_id: str
    handle: AgentSessionHandle
    adapter: AgentAdapter
    request: AgentTurnRequest
    send_fn: SendFn
    current_cgs: Mapping[str, Any] | None = None
    xace_session: Any | None = None
    mode: str = "AGENT"
    task: asyncio.Task[Any] | None = None
    stream_sequence: int = 0
    last_event_sequence: int = 0
    event_count: int = 0
    state: str = AGENT_STATUS_STARTING
    cancel_requested: bool = False


class AgentEventStreamManager:
    """Own active provider-agent turns and emit compact WebSocket messages."""

    def __init__(
        self,
        registry: AgentAdapterRegistry | None = None,
        *,
        session_store: AgentSessionStore | None = None,
        proposal_ingress: AgentProposalIngressGate | None = None,
        clock: Callable[[], float] = time.time,
        iso_clock: Callable[[], str] = utc_now_iso,
    ) -> None:
        self.registry = registry or create_default_registry()
        self.session_store = session_store
        self.proposal_ingress = proposal_ingress or AgentProposalIngressGate(
            session_store=session_store
        )
        self.clock = clock
        self.iso_clock = iso_clock
        self._active: dict[str, _ActiveAgentTurn] = {}
        self._last_tasks: dict[str, asyncio.Task[Any]] = {}
        self._last_status: dict[str, dict[str, JsonValue]] = {}

    async def start_turn(
        self,
        *,
        session_id: str,
        provider_id: str = "",
        user_prompt: str,
        cgs_hash: str,
        send_fn: SendFn,
        project_id: str = "",
        context_capsule_path: str | None = None,
        allowed_tools: Sequence[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
        current_cgs: Mapping[str, Any] | None = None,
        xace_session: Any | None = None,
        mode: str = "AGENT",
    ) -> AgentTurnCommandResult:
        """Start a provider turn and stream events asynchronously."""

        provider_id = self._resolve_provider_id(provider_id)
        if not provider_id:
            return await self._send_command_status(
                send_fn,
                accepted=False,
                code="AGENT_PROVIDER_REQUIRED",
                message="agent_turn requires a provider_id until a primary adapter is certified.",
                status=_status_message(
                    session_id=session_id,
                    state=AGENT_STATUS_UNAVAILABLE,
                    code="AGENT_PROVIDER_REQUIRED",
                    message="No provider_id was supplied.",
                    updated_at=self.clock(),
                ),
            )
        if session_id in self._active:
            active = self._active[session_id]
            if active.task is not None and not active.task.done():
                return await self._send_command_status(
                    send_fn,
                    accepted=False,
                    code="AGENT_TURN_ALREADY_RUNNING",
                    message="An agent turn is already running for this session.",
                    status=self._status_for_active(
                        active,
                        code="AGENT_TURN_ALREADY_RUNNING",
                        message="An agent turn is already running for this session.",
                    ),
                )
            self._active.pop(session_id, None)

        if not str(user_prompt or "").strip():
            return await self._send_command_status(
                send_fn,
                accepted=False,
                code="AGENT_PROMPT_REQUIRED",
                message="agent_turn requires a non-empty prompt.",
                status=_status_message(
                    session_id=session_id,
                    provider_id=provider_id,
                    state=AGENT_STATUS_IDLE,
                    code="AGENT_PROMPT_REQUIRED",
                    message="No agent prompt was supplied.",
                    updated_at=self.clock(),
                ),
            )
        if not _is_cgs_hash(cgs_hash):
            return await self._send_command_status(
                send_fn,
                accepted=False,
                code="AGENT_CGS_HASH_REQUIRED",
                message="agent_turn requires the current 64-character CGS hash.",
                status=_status_message(
                    session_id=session_id,
                    provider_id=provider_id,
                    state=AGENT_STATUS_IDLE,
                    code="AGENT_CGS_HASH_REQUIRED",
                    message="No valid CGS hash was supplied.",
                    updated_at=self.clock(),
                ),
            )

        try:
            adapter = self.registry.get(provider_id)
        except AgentRegistryError as exc:
            return await self._send_command_status(
                send_fn,
                accepted=False,
                code="AGENT_PROVIDER_UNAVAILABLE",
                message=f"Agent provider is unavailable: {redact_exception(exc)}",
                status=_status_message(
                    session_id=session_id,
                    provider_id=provider_id,
                    state=AGENT_STATUS_UNAVAILABLE,
                    code="AGENT_PROVIDER_UNAVAILABLE",
                    message=str(exc),
                    updated_at=self.clock(),
                ),
            )

        try:
            handle = await self._handle_for_turn(
                adapter=adapter,
                session_id=session_id,
                provider_id=provider_id,
                user_prompt=user_prompt,
                cgs_hash=cgs_hash,
                project_id=project_id,
                context_capsule_path=context_capsule_path,
                allowed_tools=tuple(allowed_tools or ()),
                metadata=metadata or {},
            )
            request = AgentTurnRequest(
                handle=handle,
                user_prompt=redact_text(user_prompt),
                base_cgs_hash=cgs_hash,
                allowed_tools=tuple(allowed_tools or ()),
                metadata=_json_object(metadata or {}, "agent turn metadata"),
            )
        except Exception as exc:
            return await self._send_command_status(
                send_fn,
                accepted=False,
                code="AGENT_TURN_START_FAILED",
                message=f"Agent turn could not start: {redact_exception(exc)}",
                status=_status_message(
                    session_id=session_id,
                    provider_id=provider_id,
                    state=AGENT_STATUS_ERROR,
                    code="AGENT_TURN_START_FAILED",
                    message=redact_exception(exc),
                    updated_at=self.clock(),
                ),
            )

        turn_id = _turn_id(session_id, provider_id, cgs_hash, self.clock())
        active = _ActiveAgentTurn(
            session_id=session_id,
            provider_id=provider_id,
            turn_id=turn_id,
            handle=handle,
            adapter=adapter,
            request=request,
            send_fn=send_fn,
            current_cgs=(
                copy.deepcopy(dict(current_cgs))
                if isinstance(current_cgs, Mapping)
                else None
            ),
            xace_session=xace_session,
            mode=str(mode or "AGENT"),
        )
        self._active[session_id] = active
        status = self._status_for_active(
            active,
            state=AGENT_STATUS_RUNNING,
            code="",
            message="Agent turn is running.",
        )
        await send_fn(status)
        active.task = asyncio.create_task(self._run_turn(active))
        self._last_tasks[session_id] = active.task
        return AgentTurnCommandResult(
            accepted=True,
            code="AGENT_TURN_STARTED",
            message="Agent turn started.",
            status=status,
            task=active.task,
        )

    async def cancel_turn(
        self,
        *,
        session_id: str,
        send_fn: SendFn,
        provider_id: str = "",
    ) -> AgentTurnCommandResult:
        """Cancel the active provider turn for a XACE session."""

        active = self._active.get(session_id)
        if active is None or active.task is None or active.task.done():
            status = _status_message(
                session_id=session_id,
                provider_id=provider_id,
                state=AGENT_STATUS_IDLE,
                code="NO_ACTIVE_AGENT_TURN",
                message="No active agent turn is running for this session.",
                updated_at=self.clock(),
            )
            await send_fn(status)
            return AgentTurnCommandResult(
                accepted=False,
                code="NO_ACTIVE_AGENT_TURN",
                message="No active agent turn is running for this session.",
                status=status,
            )
        active.cancel_requested = True
        cancelling = self._status_for_active(
            active,
            state=AGENT_STATUS_CANCELLING,
            code="AGENT_CANCEL_REQUESTED",
            message="Agent cancellation was requested.",
        )
        await send_fn(cancelling)
        try:
            await active.adapter.cancel_turn(active.handle)
        except Exception as exc:  # pragma: no cover - adapter-specific
            error_status = self._status_for_active(
                active,
                state=AGENT_STATUS_ERROR,
                code="AGENT_CANCEL_FAILED",
                message=f"Agent cancellation failed: {redact_exception(exc)}",
            )
            await send_fn(error_status)
            return AgentTurnCommandResult(
                accepted=False,
                code="AGENT_CANCEL_FAILED",
                message=f"Agent cancellation failed: {redact_exception(exc)}",
                status=error_status,
                task=active.task,
            )
        active.task.cancel()
        return AgentTurnCommandResult(
            accepted=True,
            code="AGENT_CANCEL_REQUESTED",
            message="Agent cancellation was requested.",
            status=cancelling,
            task=active.task,
        )

    async def send_status(
        self,
        *,
        session_id: str,
        send_fn: SendFn,
        provider_id: str = "",
    ) -> dict[str, JsonValue]:
        """Send the current agent status for a session."""

        status = self.status(session_id=session_id, provider_id=provider_id)
        await send_fn(status)
        return status

    def status(self, *, session_id: str, provider_id: str = "") -> dict[str, JsonValue]:
        active = self._active.get(session_id)
        if active is not None and active.task is not None and not active.task.done():
            return self._status_for_active(active)
        prior = self._last_status.get(session_id)
        if prior is not None:
            return dict(prior)
        provider_id = provider_id or self._resolve_provider_id("")
        return _status_message(
            session_id=session_id,
            provider_id=provider_id,
            state=AGENT_STATUS_IDLE if provider_id else AGENT_STATUS_UNAVAILABLE,
            code="" if provider_id else "AGENT_PROVIDER_REQUIRED",
            message=(
                "No active agent turn."
                if provider_id
                else "No certified agent provider is active."
            ),
            updated_at=self.clock(),
        )

    async def wait_for_turn(self, session_id: str) -> None:
        """Testing helper: wait for the most recently started turn."""

        task = self._last_tasks.get(session_id)
        if task is None:
            return
        with contextlib.suppress(asyncio.CancelledError):
            await task

    def _resolve_provider_id(self, provider_id: str) -> str:
        provider_id = str(provider_id or "").strip()
        if provider_id:
            return provider_id
        provider_ids = self.registry.provider_ids()
        return provider_ids[0] if len(provider_ids) == 1 else ""

    async def _handle_for_turn(
        self,
        *,
        adapter: AgentAdapter,
        session_id: str,
        provider_id: str,
        user_prompt: str,
        cgs_hash: str,
        project_id: str,
        context_capsule_path: str | None,
        allowed_tools: tuple[str, ...],
        metadata: Mapping[str, Any],
    ) -> AgentSessionHandle:
        stored = (
            self.session_store.get_session(session_id)
            if self.session_store is not None
            else None
        )
        if stored is not None and stored.provider_id == provider_id:
            handle = await adapter.resume_session(stored.to_handle())
        else:
            handle = await adapter.start_session(
                AgentStartRequest(
                    xace_session_id=session_id,
                    user_prompt=redact_text(user_prompt),
                    base_cgs_hash=cgs_hash,
                    project_id=project_id,
                    context_capsule_path=context_capsule_path,
                    allowed_tools=allowed_tools,
                    metadata=_json_object(metadata, "agent start metadata"),
                )
            )
        if self.session_store is not None:
            self.session_store.upsert_session(AgentStoredSession.from_handle(handle))
        return handle

    async def _run_turn(self, active: _ActiveAgentTurn) -> None:
        final_state = AGENT_STATUS_COMPLETED
        final_code = ""
        final_message = "Agent turn completed."
        try:
            async for event in active.adapter.run_turn(active.request):
                await self._emit_event(active, event)
                if event.event_type is AgentEventType.TURN_CANCELLED:
                    final_state = AGENT_STATUS_CANCELLED
                    final_code = "AGENT_TURN_CANCELLED"
                    final_message = event.message or "Agent turn cancelled."
                    break
                if event.event_type is AgentEventType.ERROR:
                    final_state = AGENT_STATUS_ERROR
                    final_code = "AGENT_EVENT_ERROR"
                    final_message = event.message or "Agent turn failed."
                    break
                if event.event_type is AgentEventType.TURN_COMPLETED:
                    final_state = AGENT_STATUS_COMPLETED
                    final_message = event.message or "Agent turn completed."
                    break
        except asyncio.CancelledError:
            final_state = AGENT_STATUS_CANCELLED
            final_code = "AGENT_TURN_CANCELLED"
            final_message = "Agent turn cancelled."
            await self._emit_event(
                active,
                _synthetic_event(
                    active,
                    event_type=AgentEventType.TURN_CANCELLED,
                    message=final_message,
                ),
            )
        except Exception as exc:  # pragma: no cover - exact adapter errors vary
            final_state = AGENT_STATUS_ERROR
            final_code = "AGENT_TURN_FAILED"
            final_message = f"Agent turn failed: {redact_exception(exc)}"
            await self._emit_event(
                active,
                _synthetic_event(
                    active,
                    event_type=AgentEventType.ERROR,
                    message=final_message,
                ),
            )
        finally:
            status = self._status_for_active(
                active,
                state=final_state,
                code=final_code,
                message=final_message,
            )
            with contextlib.suppress(Exception):
                await active.send_fn(status)
            if self._active.get(active.session_id) is active:
                self._active.pop(active.session_id, None)

    async def _emit_event(self, active: _ActiveAgentTurn, event: AgentEvent) -> None:
        active.stream_sequence += 1
        active.last_event_sequence = max(active.last_event_sequence, event.sequence)
        active.event_count += 1
        if self.session_store is not None:
            try:
                self.session_store.record_event(event)
            except AgentSessionStoreError as exc:
                raise AgentEventStreamError(
                    f"agent event could not be logged: {redact_exception(exc)}"
                ) from exc
        await active.send_fn(
            agent_event_message(
                event,
                turn_id=active.turn_id,
                stream_sequence=active.stream_sequence,
            )
        )
        await self._maybe_ingest_agent_proposal(active, event)

    async def _maybe_ingest_agent_proposal(
        self,
        active: _ActiveAgentTurn,
        event: AgentEvent,
    ) -> None:
        if event.event_type is not AgentEventType.PROPOSAL:
            return
        if active.current_cgs is None or active.xace_session is None:
            return
        data = event.data if isinstance(event.data, Mapping) else {}
        proposal = data.get("proposal") if isinstance(data, Mapping) else None
        if not isinstance(proposal, Mapping):
            return
        try:
            result = self.proposal_ingress.ingest(
                proposal,
                current_cgs=active.current_cgs,
                current_cgs_hash=active.request.base_cgs_hash,
                xace_session_id=active.session_id,
                mode=active.mode,
                session=active.xace_session,
            )
        except AgentProposalIngressError as exc:
            raise AgentEventStreamError(
                f"agent proposal ingress failed: {redact_exception(exc)}"
            ) from exc
        if not result.accepted:
            raise AgentEventStreamError(
                f"agent proposal rejected: {result.code} {result.message}"
            )
        pending_result = getattr(active.xace_session, "pending_prompt_result", None)
        if result.preview_created and isinstance(pending_result, Mapping):
            await active.send_fn(
                _json_object(
                    {
                        "type": "pil_result",
                        "result": copy.deepcopy(dict(pending_result)),
                        "agent_proposal_ingress": result.to_dict(),
                    },
                    "agent proposal pil result",
                )
            )

    def _status_for_active(
        self,
        active: _ActiveAgentTurn,
        *,
        state: str | None = None,
        code: str = "",
        message: str = "",
    ) -> dict[str, JsonValue]:
        active.state = state or active.state
        status = _status_message(
            session_id=active.session_id,
            provider_id=active.provider_id,
            turn_id=active.turn_id,
            state=active.state,
            code=code,
            message=message or _status_label(active.state),
            last_event_sequence=active.last_event_sequence,
            event_count=active.event_count,
            cancellable=active.state in {AGENT_STATUS_STARTING, AGENT_STATUS_RUNNING},
            updated_at=self.clock(),
        )
        self._last_status[active.session_id] = status
        return status

    async def _send_command_status(
        self,
        send_fn: SendFn,
        *,
        accepted: bool,
        code: str,
        message: str,
        status: Mapping[str, Any],
    ) -> AgentTurnCommandResult:
        clean_status = _json_object(status, "agent command status")
        await send_fn(clean_status)
        self._last_status[str(clean_status.get("session_id") or "")] = clean_status
        return AgentTurnCommandResult(
            accepted=accepted,
            code=code,
            message=message,
            status=clean_status,
        )


def agent_event_message(
    event: AgentEvent,
    *,
    turn_id: str,
    stream_sequence: int,
) -> dict[str, JsonValue]:
    """Convert one provider-neutral ``AgentEvent`` into a UI message."""

    return _json_object(
        {
            "type": AGENT_WS_EVENT,
            "schema": AGENT_EVENT_STREAM_SCHEMA,
            "session_id": event.session_id,
            "provider_id": event.provider_id,
            "turn_id": turn_id,
            "event_id": event.event_id,
            "event_type": event.event_type.value,
            "sequence": event.sequence,
            "stream_sequence": stream_sequence,
            "message": redact_text(event.message),
            "data": redact_value(event.data),
            "created_at": event.created_at,
            "ui_state": _ui_state_for_event(event),
        },
        "agent event message",
    )


def _status_message(
    *,
    session_id: str,
    state: str,
    provider_id: str = "",
    turn_id: str = "",
    code: str = "",
    message: str = "",
    last_event_sequence: int = 0,
    event_count: int = 0,
    cancellable: bool = False,
    updated_at: float | None = None,
) -> dict[str, JsonValue]:
    return _json_object(
        {
            "type": AGENT_WS_STATUS,
            "schema": AGENT_EVENT_STREAM_SCHEMA,
            "session_id": session_id,
            "provider_id": provider_id,
            "turn_id": turn_id,
            "state": state,
            "code": code,
            "message": redact_text(message or _status_label(state)),
            "running": state
            in {AGENT_STATUS_STARTING, AGENT_STATUS_RUNNING, AGENT_STATUS_CANCELLING},
            "cancellable": cancellable,
            "last_event_sequence": last_event_sequence,
            "event_count": event_count,
            "updated_at": time.time() if updated_at is None else updated_at,
            "ui_state": {
                "state": state,
                "label": _status_label(state),
                "severity": _status_severity(state),
                "busy": state in {AGENT_STATUS_STARTING, AGENT_STATUS_RUNNING},
                "terminal": state
                in {
                    AGENT_STATUS_CANCELLED,
                    AGENT_STATUS_COMPLETED,
                    AGENT_STATUS_ERROR,
                    AGENT_STATUS_UNAVAILABLE,
                },
            },
        },
        "agent status message",
    )


def _ui_state_for_event(event: AgentEvent) -> dict[str, JsonValue]:
    state = {
        AgentEventType.SESSION_STARTED: AGENT_STATUS_RUNNING,
        AgentEventType.TURN_STARTED: AGENT_STATUS_RUNNING,
        AgentEventType.STATUS: AGENT_STATUS_RUNNING,
        AgentEventType.TOOL_CALL: "tool_call",
        AgentEventType.PROPOSAL: "proposal",
        AgentEventType.TURN_COMPLETED: AGENT_STATUS_COMPLETED,
        AgentEventType.TURN_CANCELLED: AGENT_STATUS_CANCELLED,
        AgentEventType.ERROR: AGENT_STATUS_ERROR,
    }[event.event_type]
    return {
        "state": state,
        "label": _event_label(event.event_type),
        "severity": _event_severity(event.event_type),
        "busy": event.event_type
        in {
            AgentEventType.SESSION_STARTED,
            AgentEventType.TURN_STARTED,
            AgentEventType.STATUS,
            AgentEventType.TOOL_CALL,
            AgentEventType.PROPOSAL,
        },
        "terminal": event.event_type
        in {
            AgentEventType.TURN_COMPLETED,
            AgentEventType.TURN_CANCELLED,
            AgentEventType.ERROR,
        },
    }


def _synthetic_event(
    active: _ActiveAgentTurn,
    *,
    event_type: AgentEventType,
    message: str,
) -> AgentEvent:
    sequence = max(active.last_event_sequence + 1, active.event_count + 1)
    digest = hashlib.sha256(
        json.dumps(
            {
                "turn_id": active.turn_id,
                "event_type": event_type.value,
                "sequence": sequence,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:12]
    return AgentEvent(
        event_id=f"agent-synthetic-{digest}",
        event_type=event_type,
        session_id=active.session_id,
        provider_id=active.provider_id,
        sequence=sequence,
        message=message,
        data={"synthetic": True},
        created_at=utc_now_iso(),
    )


def _turn_id(session_id: str, provider_id: str, cgs_hash: str, now: float) -> str:
    digest = hashlib.sha256(
        json.dumps(
            {
                "session_id": session_id,
                "provider_id": provider_id,
                "cgs_hash": cgs_hash,
                "now": now,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:12]
    return f"agent-turn-{int(now * 1000):013d}-{digest}"


def _status_label(state: str) -> str:
    return {
        AGENT_STATUS_IDLE: "Agent idle",
        AGENT_STATUS_STARTING: "Agent starting",
        AGENT_STATUS_RUNNING: "Agent running",
        AGENT_STATUS_CANCELLING: "Agent cancelling",
        AGENT_STATUS_CANCELLED: "Agent cancelled",
        AGENT_STATUS_COMPLETED: "Agent completed",
        AGENT_STATUS_ERROR: "Agent error",
        AGENT_STATUS_UNAVAILABLE: "Agent unavailable",
    }.get(state, "Agent status")


def _status_severity(state: str) -> str:
    if state == AGENT_STATUS_ERROR:
        return "error"
    if state == AGENT_STATUS_UNAVAILABLE:
        return "warning"
    if state == AGENT_STATUS_CANCELLED:
        return "info"
    return "info"


def _event_label(event_type: AgentEventType) -> str:
    return {
        AgentEventType.SESSION_STARTED: "Session started",
        AgentEventType.TURN_STARTED: "Turn started",
        AgentEventType.STATUS: "Status",
        AgentEventType.TOOL_CALL: "Tool call",
        AgentEventType.PROPOSAL: "Proposal",
        AgentEventType.TURN_COMPLETED: "Turn completed",
        AgentEventType.TURN_CANCELLED: "Turn cancelled",
        AgentEventType.ERROR: "Error",
    }[event_type]


def _event_severity(event_type: AgentEventType) -> str:
    if event_type is AgentEventType.ERROR:
        return "error"
    if event_type is AgentEventType.TURN_CANCELLED:
        return "warning"
    return "info"


def _json_object(value: Mapping[str, Any] | None, label: str) -> dict[str, JsonValue]:
    try:
        normalized = normalize_json_value(redact_value(dict(value or {})), label)
    except (AgentContractError, TypeError, ValueError) as exc:
        raise AgentEventStreamError(f"{label} must be a JSON object") from exc
    if not isinstance(normalized, dict):
        raise AgentEventStreamError(f"{label} must be a JSON object")
    return normalized


def _is_cgs_hash(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        char in "0123456789abcdefABCDEF" for char in value
    )


__all__ = [
    "AGENT_EVENT_STREAM_SCHEMA",
    "AGENT_STATUS_CANCELLED",
    "AGENT_STATUS_CANCELLING",
    "AGENT_STATUS_COMPLETED",
    "AGENT_STATUS_ERROR",
    "AGENT_STATUS_IDLE",
    "AGENT_STATUS_RUNNING",
    "AGENT_STATUS_STARTING",
    "AGENT_STATUS_UNAVAILABLE",
    "AGENT_WS_CANCEL",
    "AGENT_WS_EVENT",
    "AGENT_WS_STATUS",
    "AGENT_WS_TURN",
    "AgentEventStreamError",
    "AgentEventStreamManager",
    "AgentTurnCommandResult",
    "agent_event_message",
]
