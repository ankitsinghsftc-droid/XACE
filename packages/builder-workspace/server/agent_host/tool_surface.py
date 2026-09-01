"""Allowlisted XACE tools for provider-neutral Agent Mode.

AG-005 defines the tool contract that Codex and future agents should see,
preferably transported over MCP where the provider supports it. This module is
not wired into Builder's default API/BYOK path; it is an inert substrate until a
later Agent Mode lifecycle task installs it for an adapter session.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from secret_redaction import redact_exception, redact_text, redact_value

from .context_capsule import (
    READ_ONLY_RETRIEVAL_SCOPES,
    AgentContextRetriever,
    ContextCapsuleError,
    ContextRetrievalRequest,
    ContextRetrievalSource,
)
from .contracts import (
    AgentEvent,
    AgentEventType,
    AgentToolPermission,
    AgentToolSpec,
    JsonValue,
    ToolTransport,
    normalize_json_value,
    utc_now_iso,
)
from .session_store import AgentSessionStore, AgentSessionStoreError, AgentToolCallRecord


AGENT_TOOL_SURFACE_SCHEMA = "xace.agent_tool_surface.v1"
AGENT_TOOL_CALL_RESULT_SCHEMA = "xace.agent_tool_call_result.v1"

TOOL_READ_CGS = "xace.read_cgs"
TOOL_RETRIEVE_CONTEXT = "xace.retrieve_context"
TOOL_SEARCH_PROJECT = "xace.search_project"
TOOL_GET_DIAGNOSTICS = "xace.get_diagnostics"
TOOL_RUNTIME_STATUS = "xace.runtime_status"
TOOL_RUNTIME_SNAPSHOT = "xace.runtime_snapshot"

READ_ONLY_XACE_TOOL_NAMES = (
    TOOL_READ_CGS,
    TOOL_RETRIEVE_CONTEXT,
    TOOL_SEARCH_PROJECT,
    TOOL_GET_DIAGNOSTICS,
    TOOL_RUNTIME_STATUS,
    TOOL_RUNTIME_SNAPSHOT,
)

DENIED_XACE_TOOL_NAMES = (
    "xace.apply_operations",
    "xace.commit_gde",
    "xace.edit_project_file",
    "xace.read_credentials",
    "xace.runtime_mutate",
    "xace.shell",
)

CGS_FRAGMENT_SCOPES = (
    "summary",
    "cgs.metadata",
    "cgs.mode",
    "cgs.actor",
    "cgs.system",
    "cgs.rule",
    "cgs.component_schema",
    "cgs.asset",
    "cgs.binding",
)

MAX_TOOL_RESULT_LIMIT = 25
_TOOL_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")


class RuntimeReadOnlyControl(Protocol):
    """Runtime control shape used by read-only Agent Mode tools."""

    def status(self, *, session_id: str = "") -> dict[str, Any]:
        ...

    def send_control(
        self,
        action: str,
        *,
        session_id: str = "",
        tick: int | None = None,
        version_ids: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ...


class XaceToolSurfaceError(RuntimeError):
    """Raised when the Agent Mode tool surface cannot safely serve a call."""


@dataclass(frozen=True)
class XaceToolCallRequest:
    """Provider-neutral request for one XACE tool invocation."""

    tool_name: str
    xace_session_id: str
    cgs_hash: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    provider_id: str = "xace"
    call_id: str = ""
    transport: ToolTransport = ToolTransport.MCP
    schema: str = AGENT_TOOL_SURFACE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != AGENT_TOOL_SURFACE_SCHEMA:
            raise XaceToolSurfaceError(
                f"schema must equal {AGENT_TOOL_SURFACE_SCHEMA!r}"
            )
        _require_tool_name(self.tool_name)
        _require_identifier(self.xace_session_id, "xace_session_id")
        _require_cgs_hash(self.cgs_hash, "cgs_hash")
        _require_identifier(self.provider_id, "provider_id")
        if self.call_id:
            _require_identifier(self.call_id, "call_id")
        object.__setattr__(
            self,
            "transport",
            self.transport
            if isinstance(self.transport, ToolTransport)
            else ToolTransport(str(self.transport)),
        )
        object.__setattr__(
            self,
            "arguments",
            _json_object(self.arguments, "tool arguments"),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": self.schema,
            "tool_name": self.tool_name,
            "xace_session_id": self.xace_session_id,
            "provider_id": self.provider_id,
            "call_id": self.call_id,
            "cgs_hash": self.cgs_hash,
            "transport": self.transport.value,
            "arguments": dict(self.arguments),
        }


@dataclass(frozen=True)
class XaceToolCallResult:
    """Structured result for an allowlisted or denied XACE tool call."""

    request: XaceToolCallRequest
    status: str
    data: Mapping[str, Any] = field(default_factory=dict)
    reason: str = ""
    permission: AgentToolPermission = AgentToolPermission.READ_ONLY
    read_only: bool = True
    logged: bool = False
    call_id: str = ""
    schema: str = AGENT_TOOL_CALL_RESULT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != AGENT_TOOL_CALL_RESULT_SCHEMA:
            raise XaceToolSurfaceError(
                f"schema must equal {AGENT_TOOL_CALL_RESULT_SCHEMA!r}"
            )
        if self.status not in {"completed", "denied", "not_found", "unavailable", "error"}:
            raise XaceToolSurfaceError("invalid tool call status")
        permission = (
            self.permission
            if isinstance(self.permission, AgentToolPermission)
            else AgentToolPermission(str(self.permission))
        )
        object.__setattr__(self, "permission", permission)
        object.__setattr__(self, "data", _json_object(self.data, "tool result data"))
        object.__setattr__(self, "reason", redact_text(self.reason))
        object.__setattr__(self, "call_id", self.call_id or self.request.call_id)
        if permission is AgentToolPermission.READ_ONLY and self.read_only is not True:
            raise XaceToolSurfaceError("read-only results must set read_only=True")

    @property
    def allowed(self) -> bool:
        return self.status == "completed"

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": self.schema,
            "tool_name": self.request.tool_name,
            "status": self.status,
            "reason": self.reason,
            "permission": self.permission.value,
            "read_only": self.read_only,
            "logged": self.logged,
            "call_id": self.call_id,
            "cgs_hash": self.request.cgs_hash,
            "request": self.request.to_dict(),
            "data": dict(self.data),
        }


class XaceToolSurface:
    """Executes allowlisted read-only XACE tools and logs every call."""

    def __init__(
        self,
        source: ContextRetrievalSource,
        *,
        session_store: AgentSessionStore | None = None,
        runtime_control: RuntimeReadOnlyControl | None = None,
    ) -> None:
        self.source = source
        self.session_store = session_store
        self.runtime_control = runtime_control
        self._context_retriever = AgentContextRetriever()
        self._sequence = 0

    @property
    def tool_names(self) -> tuple[str, ...]:
        return READ_ONLY_XACE_TOOL_NAMES

    def tool_specs(self) -> tuple[AgentToolSpec, ...]:
        return default_xace_tool_specs()

    def catalog(self) -> dict[str, JsonValue]:
        return {
            "schema": AGENT_TOOL_SURFACE_SCHEMA,
            "transport_preference": ToolTransport.MCP.value,
            "tools": [tool.to_dict() for tool in self.tool_specs()],
            "denied_tools": list(DENIED_XACE_TOOL_NAMES),
            "read_only": True,
        }

    def execute(
        self,
        request: XaceToolCallRequest,
        *,
        allowed_tools: Sequence[str] | None = None,
    ) -> XaceToolCallResult:
        call_id = self._next_call_id(request)
        if request.tool_name not in READ_ONLY_XACE_TOOL_NAMES:
            return self._log_result(
                XaceToolCallResult(
                    request=request,
                    status="denied",
                    reason=f"tool {request.tool_name!r} is not allowlisted for Builder Agent Mode",
                    data=_surface_payload(source=self.source, value={}),
                    call_id=call_id,
                )
            )
        if allowed_tools is not None and request.tool_name not in set(allowed_tools):
            return self._log_result(
                XaceToolCallResult(
                    request=request,
                    status="denied",
                    reason=f"tool {request.tool_name!r} is not enabled for this Builder Agent Mode session",
                    data=_surface_payload(source=self.source, value={}),
                    call_id=call_id,
                )
            )
        if request.cgs_hash != self.source.cgs_hash:
            return self._log_result(
                XaceToolCallResult(
                    request=request,
                    status="denied",
                    reason="request cgs_hash does not match the tool surface source",
                    data=_surface_payload(source=self.source, value={}),
                    call_id=call_id,
                )
            )

        try:
            if request.tool_name == TOOL_READ_CGS:
                result = self._read_cgs(request)
            elif request.tool_name == TOOL_RETRIEVE_CONTEXT:
                result = self._retrieve_context(request)
            elif request.tool_name == TOOL_SEARCH_PROJECT:
                result = self._search_project(request)
            elif request.tool_name == TOOL_GET_DIAGNOSTICS:
                result = self._get_diagnostics(request)
            elif request.tool_name == TOOL_RUNTIME_STATUS:
                result = self._runtime_status(request)
            elif request.tool_name == TOOL_RUNTIME_SNAPSHOT:
                result = self._runtime_snapshot(request)
            else:  # pragma: no cover - guarded above
                result = XaceToolCallResult(
                    request=request,
                    status="denied",
                    reason="tool is unavailable",
                    call_id=call_id,
                )
        except (ContextCapsuleError, XaceToolSurfaceError) as exc:
            result = XaceToolCallResult(
                request=request,
                status="denied",
                reason=redact_text(exc),
                data=_surface_payload(source=self.source, value={}),
                call_id=call_id,
            )
        return self._log_result(_with_call_id(result, call_id))

    def _read_cgs(self, request: XaceToolCallRequest) -> XaceToolCallResult:
        scope = str(request.arguments.get("scope") or "summary")
        if scope not in CGS_FRAGMENT_SCOPES:
            return XaceToolCallResult(
                request=request,
                status="denied",
                reason=f"CGS scope {scope!r} is not allowlisted",
                data=_surface_payload(source=self.source, value={}),
            )
        if scope == "summary":
            data = {
                "value": {
                    "metadata": _safe_metadata(self.source.cgs),
                    "catalog": _catalog_ids(self.source.cgs),
                }
            }
            return XaceToolCallResult(
                request=request,
                status="completed",
                data=_surface_payload(source=self.source, value=data),
            )
        retrieval = self._context_retriever.retrieve(
            self.source,
            ContextRetrievalRequest(
                xace_session_id=request.xace_session_id,
                cgs_hash=request.cgs_hash,
                provider_id=request.provider_id,
                scope=scope,
                item_id=str(request.arguments.get("item_id") or ""),
                query=str(request.arguments.get("query") or ""),
                limit=_limit(request.arguments.get("limit"), default=10),
            ),
        )
        return XaceToolCallResult(
            request=request,
            status=_map_retrieval_status(retrieval.status),
            reason=retrieval.reason,
            data=_surface_payload(source=self.source, value=retrieval.data),
        )

    def _retrieve_context(self, request: XaceToolCallRequest) -> XaceToolCallResult:
        scope = str(request.arguments.get("scope") or "")
        retrieval = self._context_retriever.retrieve(
            self.source,
            ContextRetrievalRequest(
                xace_session_id=request.xace_session_id,
                cgs_hash=request.cgs_hash,
                provider_id=request.provider_id,
                scope=scope,
                item_id=str(request.arguments.get("item_id") or ""),
                query=str(request.arguments.get("query") or ""),
                limit=_limit(request.arguments.get("limit"), default=10),
            ),
        )
        return XaceToolCallResult(
            request=request,
            status=_map_retrieval_status(retrieval.status),
            reason=retrieval.reason,
            data=_surface_payload(source=self.source, value=retrieval.data),
        )

    def _search_project(self, request: XaceToolCallRequest) -> XaceToolCallResult:
        query = str(request.arguments.get("query") or "")
        if not query.strip():
            return XaceToolCallResult(
                request=request,
                status="denied",
                reason="xace.search_project requires a non-empty query",
                data=_surface_payload(source=self.source, value={}),
            )
        retrieval = self._context_retriever.retrieve(
            self.source,
            ContextRetrievalRequest(
                xace_session_id=request.xace_session_id,
                cgs_hash=request.cgs_hash,
                provider_id=request.provider_id,
                scope="search",
                query=query,
                limit=_limit(request.arguments.get("limit"), default=10),
            ),
        )
        return XaceToolCallResult(
            request=request,
            status=_map_retrieval_status(retrieval.status),
            reason=retrieval.reason,
            data=_surface_payload(source=self.source, value=retrieval.data),
        )

    def _get_diagnostics(self, request: XaceToolCallRequest) -> XaceToolCallResult:
        retrieval = self._context_retriever.retrieve(
            self.source,
            ContextRetrievalRequest(
                xace_session_id=request.xace_session_id,
                cgs_hash=request.cgs_hash,
                provider_id=request.provider_id,
                scope="diagnostics",
                limit=_limit(request.arguments.get("limit"), default=10),
            ),
        )
        return XaceToolCallResult(
            request=request,
            status=_map_retrieval_status(retrieval.status),
            reason=retrieval.reason,
            data=_surface_payload(source=self.source, value=retrieval.data),
        )

    def _runtime_status(self, request: XaceToolCallRequest) -> XaceToolCallResult:
        if self.runtime_control is None:
            return XaceToolCallResult(
                request=request,
                status="unavailable",
                reason="runtime control client is unavailable",
                data=_surface_payload(source=self.source, value={}),
            )
        try:
            response = self.runtime_control.status(session_id=request.xace_session_id)
        except Exception as exc:  # pragma: no cover - exact runtime type varies
            return XaceToolCallResult(
                request=request,
                status="unavailable",
                reason=f"runtime status unavailable: {redact_exception(exc)}",
                data=_surface_payload(source=self.source, value={}),
            )
        return XaceToolCallResult(
            request=request,
            status="completed",
            data=_surface_payload(
                source=self.source,
                value={
                    "status": _json_object(response.get("status", response), "runtime status"),
                    "accepted": bool(response.get("accepted", True)),
                    "reason": redact_text(response.get("reason", "")),
                },
            ),
        )

    def _runtime_snapshot(self, request: XaceToolCallRequest) -> XaceToolCallResult:
        if self.runtime_control is None:
            return XaceToolCallResult(
                request=request,
                status="unavailable",
                reason="runtime control client is unavailable",
                data=_surface_payload(source=self.source, value={}),
            )
        try:
            tick = _optional_int(request.arguments.get("tick"))
            response = self.runtime_control.send_control(
                "snapshot",
                session_id=request.xace_session_id,
                tick=tick,
            )
        except Exception as exc:  # pragma: no cover - exact runtime type varies
            return XaceToolCallResult(
                request=request,
                status="unavailable",
                reason=f"runtime snapshot unavailable: {redact_exception(exc)}",
                data=_surface_payload(source=self.source, value={}),
            )
        return XaceToolCallResult(
            request=request,
            status="completed" if response.get("accepted", True) else "unavailable",
            reason=redact_text(response.get("reason", "")),
            data=_surface_payload(
                source=self.source,
                value={
                    "status": _json_object(response.get("status", {}), "runtime status"),
                    "snapshot": _json_object(response.get("snapshot", {}), "runtime snapshot"),
                    "accepted": bool(response.get("accepted", True)),
                },
            ),
        )

    def _next_call_id(self, request: XaceToolCallRequest) -> str:
        if request.call_id:
            return request.call_id
        self._sequence += 1
        digest = _sha256_text(_canonical_json(request.to_dict()))[:12]
        return f"xace-tool-{self._sequence:04d}-{digest}"

    def _log_result(self, result: XaceToolCallResult) -> XaceToolCallResult:
        if self.session_store is None:
            return result
        self._sequence += 1
        logged = _with_logged(result, False)
        try:
            self.session_store.record_tool_call(
                AgentToolCallRecord(
                    tool_call_id=result.call_id,
                    xace_session_id=result.request.xace_session_id,
                    provider_id=result.request.provider_id,
                    tool_name=result.request.tool_name,
                    permission=result.permission.value,
                    transport=result.request.transport.value,
                    status=result.status,
                    cgs_hash=result.request.cgs_hash,
                    request=result.request.to_dict(),
                    response=result.to_dict(),
                    created_at=utc_now_iso(),
                    completed_at=utc_now_iso(),
                )
            )
            self.session_store.record_event(
                AgentEvent(
                    event_id=f"{result.call_id}-event",
                    event_type=AgentEventType.TOOL_CALL,
                    session_id=result.request.xace_session_id,
                    provider_id=result.request.provider_id,
                    sequence=self._sequence,
                    message=f"{result.request.tool_name} {result.status}",
                    data={
                        "tool_call_id": result.call_id,
                        "tool_name": result.request.tool_name,
                        "status": result.status,
                        "reason": result.reason,
                        "denied": result.status == "denied",
                    },
                    created_at=utc_now_iso(),
                )
            )
            logged = _with_logged(result, True)
        except AgentSessionStoreError as exc:
            raise XaceToolSurfaceError(
                f"tool call could not be logged: {redact_text(exc)}"
            ) from exc
        return logged


def default_xace_tool_specs() -> tuple[AgentToolSpec, ...]:
    """Return the stable read-only XACE tool catalog for Agent Mode."""

    return (
        AgentToolSpec(
            name=TOOL_READ_CGS,
            description="Read current CGS metadata or an allowlisted scoped CGS fragment.",
            permission=AgentToolPermission.READ_ONLY,
            transport=ToolTransport.MCP,
            read_only=True,
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "scope": {"enum": list(CGS_FRAGMENT_SCOPES), "default": "summary"},
                    "item_id": {"type": "string"},
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": MAX_TOOL_RESULT_LIMIT},
                },
            },
        ),
        AgentToolSpec(
            name=TOOL_RETRIEVE_CONTEXT,
            description="Retrieve controlled read-only XACE/project/system/world/binding/asset/adapter context.",
            permission=AgentToolPermission.READ_ONLY,
            transport=ToolTransport.MCP,
            read_only=True,
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["scope"],
                "properties": {
                    "scope": {"enum": list(READ_ONLY_RETRIEVAL_SCOPES)},
                    "item_id": {"type": "string"},
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": MAX_TOOL_RESULT_LIMIT},
                },
            },
        ),
        AgentToolSpec(
            name=TOOL_SEARCH_PROJECT,
            description="Search XACE indexes and CGS summaries without arbitrary filesystem reads.",
            permission=AgentToolPermission.READ_ONLY,
            transport=ToolTransport.MCP,
            read_only=True,
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "minLength": 1},
                    "limit": {"type": "integer", "minimum": 1, "maximum": MAX_TOOL_RESULT_LIMIT},
                },
            },
        ),
        AgentToolSpec(
            name=TOOL_GET_DIAGNOSTICS,
            description="Read current validation diagnostics and warnings.",
            permission=AgentToolPermission.READ_ONLY,
            transport=ToolTransport.MCP,
            read_only=True,
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": MAX_TOOL_RESULT_LIMIT},
                },
            },
        ),
        AgentToolSpec(
            name=TOOL_RUNTIME_STATUS,
            description="Read runtime status through the existing Builder runtime-control client.",
            permission=AgentToolPermission.READ_ONLY,
            transport=ToolTransport.MCP,
            read_only=True,
            input_schema={"type": "object", "additionalProperties": False},
        ),
        AgentToolSpec(
            name=TOOL_RUNTIME_SNAPSHOT,
            description="Request a read-only runtime snapshot through the existing Builder runtime-control client.",
            permission=AgentToolPermission.READ_ONLY,
            transport=ToolTransport.MCP,
            read_only=True,
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"tick": {"type": "integer", "minimum": 0}},
            },
        ),
    )


def tool_names_from_specs(specs: Sequence[AgentToolSpec]) -> tuple[str, ...]:
    return tuple(spec.name for spec in specs)


def _map_retrieval_status(status: str) -> str:
    if status == "completed":
        return "completed"
    if status == "not_found":
        return "not_found"
    return "denied"


def _surface_payload(
    *,
    source: ContextRetrievalSource,
    value: Mapping[str, Any],
) -> dict[str, JsonValue]:
    return _json_object(
        {
            "schema": AGENT_TOOL_CALL_RESULT_SCHEMA,
            "source_cgs_hash": source.cgs_hash,
            "read_only": True,
            **dict(value),
        },
        "tool result payload",
    )


def _safe_metadata(cgs: Mapping[str, Any]) -> dict[str, JsonValue]:
    metadata = cgs.get("metadata") if isinstance(cgs.get("metadata"), dict) else {}
    return _json_object(
        {
            "name": str(metadata.get("name") or ""),
            "version": str(metadata.get("version") or ""),
            "schema_version": str(metadata.get("schema_version") or ""),
            "cgs_hash": str(metadata.get("cgs_hash") or ""),
        },
        "cgs metadata",
    )


def _catalog_ids(cgs: Mapping[str, Any]) -> dict[str, JsonValue]:
    modes = cgs.get("modes") if isinstance(cgs.get("modes"), list) else []
    actors: list[str] = []
    systems: list[str] = []
    rules: list[str] = []
    mode_ids: list[str] = []
    for mode in modes:
        if not isinstance(mode, dict):
            continue
        mode_ids.append(str(mode.get("id") or ""))
        actors.extend(
            str(actor.get("id") or "")
            for actor in _as_list(mode.get("actors"))
            if isinstance(actor, dict)
        )
        systems.extend(
            str(system.get("id") or "")
            for system in _as_list(mode.get("systems"))
            if isinstance(system, dict)
        )
        rules.extend(
            str(rule.get("id") or "")
            for rule in _as_list(mode.get("rules"))
            if isinstance(rule, dict)
        )
    global_systems = cgs.get("global_systems")
    for system in global_systems if isinstance(global_systems, list) else []:
        if isinstance(system, dict):
            systems.append(str(system.get("id") or ""))
    return {
        "modes": sorted({item for item in mode_ids if item}),
        "actors": sorted({item for item in actors if item}),
        "systems": sorted({item for item in systems if item}),
        "rules": sorted({item for item in rules if item}),
    }


def _with_call_id(result: XaceToolCallResult, call_id: str) -> XaceToolCallResult:
    return XaceToolCallResult(
        request=result.request,
        status=result.status,
        data=result.data,
        reason=result.reason,
        permission=result.permission,
        read_only=result.read_only,
        logged=result.logged,
        call_id=call_id,
    )


def _with_logged(result: XaceToolCallResult, logged: bool) -> XaceToolCallResult:
    return XaceToolCallResult(
        request=result.request,
        status=result.status,
        data=result.data,
        reason=result.reason,
        permission=result.permission,
        read_only=result.read_only,
        logged=logged,
        call_id=result.call_id,
    )


def _limit(value: Any, *, default: int) -> int:
    if value in ("", None):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise XaceToolSurfaceError(f"limit must be an integer: {value!r}") from exc
    if parsed < 1 or parsed > MAX_TOOL_RESULT_LIMIT:
        raise XaceToolSurfaceError(
            f"limit must be between 1 and {MAX_TOOL_RESULT_LIMIT}"
        )
    return parsed


def _optional_int(value: Any) -> int | None:
    if value in ("", None):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise XaceToolSurfaceError(f"tick must be an integer: {value!r}") from exc
    if parsed < 0:
        raise XaceToolSurfaceError("tick must be non-negative")
    return parsed


def _json_object(value: Mapping[str, Any] | None, label: str) -> dict[str, JsonValue]:
    try:
        normalized = normalize_json_value(redact_value(dict(value or {})), label)
    except (TypeError, ValueError) as exc:
        raise XaceToolSurfaceError(f"{label} must be a JSON object") from exc
    if not isinstance(normalized, dict):
        raise XaceToolSurfaceError(f"{label} must be a JSON object")
    return normalized


def _canonical_json(value: Any) -> str:
    return json.dumps(
        redact_value(normalize_json_value(value)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _require_tool_name(value: str) -> None:
    if not isinstance(value, str) or not _TOOL_NAME_RE.fullmatch(value):
        raise XaceToolSurfaceError(f"tool_name must be stable; got {value!r}")


def _require_identifier(value: str, label: str) -> None:
    if not isinstance(value, str) or not _TOOL_NAME_RE.fullmatch(value):
        raise XaceToolSurfaceError(f"{label} must be stable; got {value!r}")


def _require_cgs_hash(value: str, label: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", value):
        raise XaceToolSurfaceError(f"{label} must be a 64-character CGS hash")


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []
