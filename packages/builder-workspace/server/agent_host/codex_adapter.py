"""Codex App Server adapter for Agent Mode detection and lifecycle.

AG-009 added read-only install/auth/model capability detection. AG-010 adds the
provider-native App Server session lifecycle: start, resume, fork, compact,
turn start, streamed notification mapping, and cancellation.

The adapter does not expose Codex shell-command APIs, file-write APIs, GDE
commits, runtime mutation, or credential access. Codex remains a proposal
producer for Builder Agent Mode.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from secret_redaction import redact_exception, redact_text, redact_value

from .contracts import (
    AgentAuthState,
    AgentCapabilities,
    AgentEvent,
    AgentEventType,
    AgentProviderKind,
    AgentProviderStatus,
    AgentSecurityPolicy,
    AgentSessionHandle,
    AgentStartRequest,
    AgentToolSpec,
    AgentTurnRequest,
    JsonValue,
    ToolTransport,
    normalize_json_value,
    utc_now_iso,
)
from .mcp_server import XaceMcpToolBridge
from .tool_surface import default_xace_tool_specs


CODEX_APP_SERVER_PROVIDER_ID = "codex_app_server"
CODEX_APP_SERVER_DISPLAY_NAME = "Codex App Server"
CODEX_APP_SERVER_TRANSPORT = "stdio_jsonl"
CODEX_APP_SERVER_COMMAND = ("app-server", "--listen", "stdio://")
CODEX_EXECUTABLE_ENV = "XACE_CODEX_EXECUTABLE"
CODEX_APP_SERVER_ENV = "XACE_CODEX_APP_SERVER_BIN"
CODEX_RUNTIME_DIR_ENV = "XACE_CODEX_RUNTIME_DIR"
CODEX_DEFAULT_TIMEOUT_SECONDS = 4.0
CODEX_VERSION_TIMEOUT_SECONDS = 2.0
CODEX_NOTIFICATION_IDLE_SECONDS = 0.25

_VERSION_RE = re.compile(r"(?P<version>\d+\.\d+\.\d+(?:[-+][A-Za-z0-9_.-]+)?)")
_REDACTED_EMAIL_RE = re.compile(r"^([^@\s]+)@([^@\s]+)$")
_EVENT_ID_SAFE_RE = re.compile(r"[^A-Za-z0-9_.:-]+")


class CodexAppServerProtocolError(RuntimeError):
    """Raised when Codex App Server protocol data cannot be trusted."""


@dataclass(frozen=True)
class CodexExecutableCandidate:
    path: str
    source: str

    def __post_init__(self) -> None:
        if not str(self.path or "").strip():
            raise CodexAppServerProtocolError("Codex executable path is empty")
        if not str(self.source or "").strip():
            raise CodexAppServerProtocolError("Codex executable source is empty")


@dataclass(frozen=True)
class CodexAppServerProbeResult:
    initialize: Mapping[str, Any] = field(default_factory=dict)
    account: Mapping[str, Any] = field(default_factory=dict)
    models: Mapping[str, Any] = field(default_factory=dict)
    provider_capabilities: Mapping[str, Any] = field(default_factory=dict)
    rate_limits: Mapping[str, Any] = field(default_factory=dict)
    notifications: tuple[Mapping[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "initialize",
            "account",
            "models",
            "provider_capabilities",
            "rate_limits",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, Mapping):
                raise CodexAppServerProtocolError(
                    f"Codex probe {field_name} result must be an object"
                )
        for notification in self.notifications:
            if not isinstance(notification, Mapping):
                raise CodexAppServerProtocolError(
                    "Codex probe notifications must be objects"
                )
        for warning in self.warnings:
            if not str(warning or "").strip():
                raise CodexAppServerProtocolError(
                    "Codex probe warnings must be non-empty strings"
                )


@dataclass(frozen=True)
class CodexCompactionResult:
    accepted: bool
    xace_session_id: str
    provider_session_id: str
    base_cgs_hash: str
    latest_cgs_hash: str
    requested_at: str
    response: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, JsonValue]:
        return _json_object_or_empty(
            {
                "accepted": self.accepted,
                "xace_session_id": self.xace_session_id,
                "provider_session_id": self.provider_session_id,
                "base_cgs_hash": self.base_cgs_hash,
                "latest_cgs_hash": self.latest_cgs_hash,
                "requested_at": self.requested_at,
                "response": dict(self.response),
                "metadata": dict(self.metadata),
            }
        )


class CodexAppServerProbe(Protocol):
    def probe(
        self,
        executable_path: str,
        *,
        timeout_seconds: float = CODEX_DEFAULT_TIMEOUT_SECONDS,
    ) -> CodexAppServerProbeResult:
        """Read App Server capability state without starting an agent turn."""


class CodexAppServerClient(Protocol):
    @property
    def closed(self) -> bool:
        ...

    def request(self, method: str, params: Mapping[str, Any]) -> dict[str, JsonValue]:
        ...

    def optional_request(
        self,
        method: str,
        params: Mapping[str, Any],
    ) -> dict[str, JsonValue]:
        ...

    def notify(self, method: str, params: Mapping[str, Any]) -> None:
        ...

    def respond(self, request_id: int | str, result: Mapping[str, Any]) -> None:
        ...

    def read_notification(
        self,
        timeout_seconds: float = CODEX_NOTIFICATION_IDLE_SECONDS,
    ) -> dict[str, JsonValue] | None:
        ...

    def close(self) -> None:
        ...


class CodexAppServerAdapter:
    """Codex App Server adapter with XACE-safe lifecycle methods."""

    provider_id = CODEX_APP_SERVER_PROVIDER_ID
    display_name = CODEX_APP_SERVER_DISPLAY_NAME

    def __init__(
        self,
        *,
        executable_resolver: Callable[[], CodexExecutableCandidate | None] | None = None,
        app_server_probe: CodexAppServerProbe | None = None,
        client_factory: Callable[[str], CodexAppServerClient] | None = None,
        version_reader: Callable[[str], str | None] | None = None,
        clock: Callable[[], str] | None = None,
        timeout_seconds: float = CODEX_DEFAULT_TIMEOUT_SECONDS,
        notification_idle_seconds: float = CODEX_NOTIFICATION_IDLE_SECONDS,
        tool_bridge_factory: Callable[
            [AgentStartRequest | AgentSessionHandle], XaceMcpToolBridge | None
        ] | None = None,
    ) -> None:
        self._executable_resolver = executable_resolver or resolve_codex_executable
        self._app_server_probe = app_server_probe or CodexStdioJsonRpcProbe()
        self._client_factory = client_factory or (
            lambda path: CodexStdioJsonRpcClient(
                path,
                timeout_seconds=timeout_seconds,
            )
        )
        self._version_reader = version_reader or read_codex_version
        self._clock = clock or utc_now_iso
        self._timeout_seconds = timeout_seconds
        self._notification_idle_seconds = max(0.05, float(notification_idle_seconds))
        self._tool_bridge_factory = tool_bridge_factory
        self._clients: dict[str, CodexAppServerClient] = {}
        self._tool_bridges: dict[str, XaceMcpToolBridge] = {}
        self._active_turns: dict[str, str] = {}
        self._lock = threading.RLock()

    async def detect(self) -> AgentProviderStatus:
        return self.detect_sync()

    def detect_sync(self) -> AgentProviderStatus:
        candidate = self._safe_resolve_executable()
        if candidate is None:
            return self._status(
                installed=False,
                available=False,
                auth_state=AgentAuthState.MISSING,
                executable_path=None,
                version=None,
                capabilities=self._base_capabilities(
                    warnings=("Codex executable was not found.",)
                ),
                warnings=("Codex executable was not found.",),
                metadata={
                    "detection_source": "not_found",
                    "app_server_responsive": False,
                    "transport": CODEX_APP_SERVER_TRANSPORT,
                    "session_lifecycle_implemented": True,
                    "turn_execution_implemented": True,
                    "mcp_tool_bridge_implemented": True,
                },
            )

        version, version_warnings = self._safe_read_version(candidate.path)
        try:
            probe = self._app_server_probe.probe(
                candidate.path,
                timeout_seconds=self._timeout_seconds,
            )
            return self._status_from_probe(candidate, version, probe, version_warnings)
        except Exception as exc:
            warning = f"Codex App Server probe failed: {redact_exception(exc)}"
            warnings = (*version_warnings, warning)
            return self._status(
                installed=True,
                available=False,
                auth_state=AgentAuthState.UNKNOWN,
                executable_path=candidate.path,
                version=version,
                capabilities=self._base_capabilities(warnings=warnings),
                warnings=warnings,
                metadata={
                    "detection_source": candidate.source,
                    "app_server_responsive": False,
                    "transport": CODEX_APP_SERVER_TRANSPORT,
                    "probe_error": warning,
                    "session_lifecycle_implemented": True,
                    "turn_execution_implemented": True,
                    "mcp_tool_bridge_implemented": True,
                },
            )

    async def list_capabilities(self) -> AgentCapabilities:
        return self._base_capabilities()

    async def start_session(self, request: AgentStartRequest) -> AgentSessionHandle:
        return await asyncio.to_thread(self._start_session_sync, request)

    async def resume_session(self, handle: AgentSessionHandle) -> AgentSessionHandle:
        return await asyncio.to_thread(self._resume_session_sync, handle)

    async def fork_session(
        self,
        handle: AgentSessionHandle,
        *,
        xace_session_id: str,
        base_cgs_hash: str | None = None,
        latest_cgs_hash: str | None = None,
        last_turn_id: str = "",
        before_turn_id: str = "",
        branch_name: str = "",
        ephemeral: bool = False,
    ) -> AgentSessionHandle:
        return await asyncio.to_thread(
            self._fork_session_sync,
            handle,
            xace_session_id=xace_session_id,
            base_cgs_hash=base_cgs_hash,
            latest_cgs_hash=latest_cgs_hash,
            last_turn_id=last_turn_id,
            before_turn_id=before_turn_id,
            branch_name=branch_name,
            ephemeral=ephemeral,
        )

    async def compact_session(
        self,
        handle: AgentSessionHandle,
    ) -> CodexCompactionResult:
        return await asyncio.to_thread(self._compact_session_sync, handle)

    async def cancel_turn(self, handle: AgentSessionHandle) -> None:
        await asyncio.to_thread(self._cancel_turn_sync, handle)

    async def run_turn(self, request: AgentTurnRequest) -> AsyncIterator[AgentEvent]:
        start_result = await asyncio.to_thread(self._start_turn_sync, request)
        turn = _turn_from_result(start_result, "turn/start")
        thread_id = request.handle.provider_session_id
        turn_id = str(turn.get("id") or "")
        sequence = 0
        terminal = False
        try:
            while not terminal:
                notification = await asyncio.to_thread(
                    self._read_thread_notification,
                    thread_id,
                    self._notification_idle_seconds,
                )
                if notification is None:
                    await asyncio.sleep(0)
                    continue
                if _is_codex_dynamic_tool_request(notification):
                    response = await asyncio.to_thread(
                        self._respond_to_dynamic_tool_call, thread_id, notification
                    )
                    notification = _with_xace_tool_response(notification, response)
                event = _agent_event_from_codex_notification(
                    notification,
                    handle=request.handle,
                    sequence=sequence + 1,
                    fallback_turn_id=turn_id,
                    clock=self._clock,
                )
                if event is None:
                    continue
                sequence += 1
                yield event
                if event.event_type in {
                    AgentEventType.TURN_COMPLETED,
                    AgentEventType.TURN_CANCELLED,
                    AgentEventType.ERROR,
                }:
                    terminal = True
        finally:
            with self._lock:
                self._active_turns.pop(thread_id, None)
            await asyncio.to_thread(self._close_thread_client, thread_id)

    def _start_session_sync(self, request: AgentStartRequest) -> AgentSessionHandle:
        with self._lock:
            tool_bridge = self._tool_bridge_for(request)
            client, initialize = self._new_initialized_client()
            try:
                params = _thread_start_params(request, tool_bridge=tool_bridge)
                result = client.request("thread/start", params)
                thread = _thread_from_result(result, "thread/start")
                provider_session_id = str(thread.get("id") or "")
                handle = AgentSessionHandle(
                    xace_session_id=request.xace_session_id,
                    provider_id=self.provider_id,
                    provider_session_id=provider_session_id,
                    base_cgs_hash=request.base_cgs_hash,
                    latest_cgs_hash=request.base_cgs_hash,
                    created_at=self._clock(),
                    metadata={
                        "operation": "thread/start",
                        "project_id": request.project_id,
                        "context_capsule_path": request.context_capsule_path,
                        "context_capsule_cwd": params.get("cwd", ""),
                        "codex_thread": thread,
                        "initialize": _initialize_metadata(initialize),
                        "transport": CODEX_APP_SERVER_TRANSPORT,
                        "approval_policy": params.get("approvalPolicy", ""),
                        "sandbox": params.get("sandbox", ""),
                        "mcp_tool_bridge": _tool_bridge_metadata(tool_bridge),
                    },
                )
                self._clients[provider_session_id] = client
                if tool_bridge is not None:
                    self._tool_bridges[provider_session_id] = tool_bridge
                return handle
            except Exception:
                client.close()
                raise

    def _resume_session_sync(self, handle: AgentSessionHandle) -> AgentSessionHandle:
        with self._lock:
            tool_bridge = self._tool_bridge_for(handle)
            client, initialize = self._new_initialized_client()
            try:
                params = _thread_resume_params(handle)
                result = client.request("thread/resume", params)
                thread = _thread_from_result(result, "thread/resume")
                provider_session_id = str(thread.get("id") or handle.provider_session_id)
                next_handle = AgentSessionHandle(
                    xace_session_id=handle.xace_session_id,
                    provider_id=self.provider_id,
                    provider_session_id=provider_session_id,
                    base_cgs_hash=handle.base_cgs_hash,
                    latest_cgs_hash=handle.latest_cgs_hash or handle.base_cgs_hash,
                    created_at=handle.created_at,
                    metadata={
                        **dict(handle.metadata),
                        "operation": "thread/resume",
                        "codex_thread": thread,
                        "initialize": _initialize_metadata(initialize),
                        "transport": CODEX_APP_SERVER_TRANSPORT,
                        "resume_exclude_turns": True,
                        "mcp_tool_bridge": _tool_bridge_metadata(tool_bridge),
                    },
                )
                self._clients[provider_session_id] = client
                if tool_bridge is not None:
                    self._tool_bridges[provider_session_id] = tool_bridge
                return next_handle
            except Exception:
                client.close()
                raise

    def _fork_session_sync(
        self,
        handle: AgentSessionHandle,
        *,
        xace_session_id: str,
        base_cgs_hash: str | None,
        latest_cgs_hash: str | None,
        last_turn_id: str,
        before_turn_id: str,
        branch_name: str,
        ephemeral: bool,
    ) -> AgentSessionHandle:
        with self._lock:
            client = self._client_for_handle(handle)
            params: dict[str, Any] = {
                "threadId": handle.provider_session_id,
                "excludeTurns": True,
                "ephemeral": bool(ephemeral),
            }
            if last_turn_id:
                params["lastTurnId"] = last_turn_id
            if before_turn_id:
                params["beforeTurnId"] = before_turn_id
            result = client.request("thread/fork", params)
            thread = _thread_from_result(result, "thread/fork")
            provider_session_id = str(thread.get("id") or "")
            forked_handle = AgentSessionHandle(
                xace_session_id=xace_session_id,
                provider_id=self.provider_id,
                provider_session_id=provider_session_id,
                base_cgs_hash=base_cgs_hash or handle.base_cgs_hash,
                latest_cgs_hash=latest_cgs_hash or handle.latest_cgs_hash or handle.base_cgs_hash,
                created_at=self._clock(),
                metadata={
                    **dict(handle.metadata),
                    "operation": "thread/fork",
                    "codex_thread": thread,
                    "parent_xace_session_id": handle.xace_session_id,
                    "parent_provider_session_id": handle.provider_session_id,
                    "branch_name": branch_name,
                    "ephemeral": bool(ephemeral),
                    "retained_xace_base_cgs_hash": handle.base_cgs_hash,
                    "retained_xace_latest_cgs_hash": handle.latest_cgs_hash or handle.base_cgs_hash,
                },
            )
            self._clients[provider_session_id] = client
            return forked_handle

    def _compact_session_sync(self, handle: AgentSessionHandle) -> CodexCompactionResult:
        with self._lock:
            client = self._client_for_handle(handle)
            response = client.request(
                "thread/compact/start",
                {"threadId": handle.provider_session_id},
            )
            return CodexCompactionResult(
                accepted=True,
                xace_session_id=handle.xace_session_id,
                provider_session_id=handle.provider_session_id,
                base_cgs_hash=handle.base_cgs_hash,
                latest_cgs_hash=handle.latest_cgs_hash or handle.base_cgs_hash,
                requested_at=self._clock(),
                response=response,
                metadata={
                    "operation": "thread/compact/start",
                    "retains_xace_state_references": True,
                    "context_capsule_path": str(handle.metadata.get("context_capsule_path") or ""),
                },
            )

    def _start_turn_sync(self, request: AgentTurnRequest) -> dict[str, JsonValue]:
        with self._lock:
            client = self._client_for_handle(request.handle)
            params = _turn_start_params(request)
            result = client.request("turn/start", params)
            turn = _turn_from_result(result, "turn/start")
            turn_id = str(turn.get("id") or "")
            if turn_id:
                self._active_turns[request.handle.provider_session_id] = turn_id
            return result

    def _cancel_turn_sync(self, handle: AgentSessionHandle) -> None:
        with self._lock:
            thread_id = handle.provider_session_id
            client = self._clients.get(thread_id)
            turn_id = self._active_turns.get(thread_id)
            if client is None or getattr(client, "closed", False):
                return
            try:
                if turn_id:
                    client.request(
                        "turn/interrupt",
                        {"threadId": thread_id, "turnId": turn_id},
                    )
                with contextlib.suppress(Exception):
                    client.optional_request(
                        "thread/backgroundTerminals/clean",
                        {"threadId": thread_id},
                    )
            finally:
                self._active_turns.pop(thread_id, None)
                self._close_thread_client(thread_id)

    def _respond_to_dynamic_tool_call(
        self,
        thread_id: str,
        notification: Mapping[str, Any],
    ) -> dict[str, JsonValue]:
        client = self._clients.get(thread_id)
        request_id = notification.get("id")
        if client is None or not isinstance(request_id, (int, str)):
            raise CodexAppServerProtocolError("Codex dynamic tool request cannot be answered")
        params = _json_object_or_empty(notification.get("params", {}))
        bridge = self._tool_bridges.get(thread_id)
        if bridge is None:
            response: dict[str, JsonValue] = {
                "contentItems": [{"type": "inputText", "text": "XACE tool bridge is unavailable."}],
                "success": False,
            }
        else:
            response = bridge.handle_codex_dynamic_call(params)
        client.respond(request_id, response)
        return response
    def _read_thread_notification(
        self,
        thread_id: str,
        timeout_seconds: float,
    ) -> dict[str, JsonValue] | None:
        client = self._clients.get(thread_id)
        if client is None or getattr(client, "closed", False):
            raise CodexAppServerProtocolError(
                f"Codex App Server client is closed for thread {thread_id!r}"
            )
        return client.read_notification(timeout_seconds)

    def _client_for_handle(self, handle: AgentSessionHandle) -> CodexAppServerClient:
        thread_id = handle.provider_session_id
        client = self._clients.get(thread_id)
        if client is not None and not getattr(client, "closed", False):
            return client
        resumed = self._resume_session_sync(handle)
        client = self._clients.get(resumed.provider_session_id)
        if client is None:
            raise CodexAppServerProtocolError("Codex App Server resume did not create a client")
        return client

    def _new_initialized_client(self) -> tuple[CodexAppServerClient, dict[str, JsonValue]]:
        candidate = self._safe_resolve_executable()
        if candidate is None:
            raise CodexAppServerProtocolError("Codex executable was not found.")
        client = self._client_factory(candidate.path)
        try:
            initialize = initialize_codex_client(client)
            return client, initialize
        except Exception:
            client.close()
            raise

    def _tool_bridge_for(
        self, request: AgentStartRequest | AgentSessionHandle
    ) -> XaceMcpToolBridge | None:
        if self._tool_bridge_factory is None:
            return None
        bridge = self._tool_bridge_factory(request)
        if bridge is not None and not isinstance(bridge, XaceMcpToolBridge):
            raise CodexAppServerProtocolError("XACE tool bridge factory returned an invalid bridge")
        return bridge

    def _close_thread_client(self, thread_id: str) -> None:
        self._tool_bridges.pop(thread_id, None)
        client = self._clients.pop(thread_id, None)
        if client is not None:
            with contextlib.suppress(Exception):
                client.close()

    def close(self) -> None:
        with self._lock:
            thread_ids = tuple(self._clients)
            for thread_id in thread_ids:
                self._close_thread_client(thread_id)
            self._active_turns.clear()

    def _status_from_probe(
        self,
        candidate: CodexExecutableCandidate,
        version: str | None,
        probe: CodexAppServerProbeResult,
        version_warnings: tuple[str, ...],
    ) -> AgentProviderStatus:
        initialize = _require_mapping(probe.initialize, "initialize")
        account_result = _require_mapping(probe.account, "account")
        account = account_result.get("account")
        requires_openai_auth = bool(account_result.get("requiresOpenaiAuth", False))
        auth_state = _auth_state(account, requires_openai_auth)
        account_label = _account_label(account, requires_openai_auth)

        model_catalog = _normalize_model_catalog(probe.models)
        provider_capabilities = _json_object_or_empty(probe.provider_capabilities)
        rate_limits = _json_object_or_empty(probe.rate_limits)
        app_server_responsive = True
        available = (
            auth_state
            in {
                AgentAuthState.SIGNED_IN,
                AgentAuthState.API_KEY,
                AgentAuthState.NOT_REQUIRED,
            }
            and bool(model_catalog.get("models"))
        )
        warnings = (
            *version_warnings,
            *tuple(redact_text(str(item)) for item in probe.warnings),
        )
        if auth_state in {AgentAuthState.MISSING, AgentAuthState.EXPIRED}:
            warnings = (*warnings, "Codex App Server reported missing authentication.")
        if not model_catalog.get("models"):
            warnings = (*warnings, "Codex App Server returned no picker-visible models.")

        metadata = {
            "detection_source": candidate.source,
            "app_server_responsive": app_server_responsive,
            "transport": CODEX_APP_SERVER_TRANSPORT,
            "probed_methods": [
                "initialize",
                "account/read",
                "model/list",
                "modelProvider/capabilities/read",
                "account/rateLimits/read",
            ],
            "initialize": {
                "platformFamily": initialize.get("platformFamily"),
                "platformOs": initialize.get("platformOs"),
                "userAgent": initialize.get("userAgent"),
            },
            "account": _account_metadata(account, requires_openai_auth),
            "models": model_catalog["models"],
            "model_ids": model_catalog["model_ids"],
            "default_model": model_catalog["default_model"],
            "provider_capabilities": provider_capabilities,
            "rate_limits": rate_limits,
            "notifications_seen": len(probe.notifications),
            "session_lifecycle_implemented": True,
            "turn_execution_implemented": True,
            "mcp_tool_bridge_implemented": True,
        }
        return self._status(
            installed=True,
            available=available,
            auth_state=auth_state,
            executable_path=candidate.path,
            version=version,
            account_label=account_label,
            capabilities=self._base_capabilities(warnings=warnings),
            warnings=warnings,
            metadata=metadata,
        )

    def _base_capabilities(
        self,
        *,
        warnings: tuple[str, ...] = (),
    ) -> AgentCapabilities:
        return AgentCapabilities(
            supports_mcp_tools=True,
            supports_streaming_events=True,
            supports_thread_resume=True,
            supports_thread_fork=True,
            supports_compaction=True,
            supports_cancellation=True,
            supports_model_discovery=True,
            supports_account_state=True,
            supports_progressive_retrieval=True,
            supported_tool_transports=(ToolTransport.MCP,),
            xace_tools=_safe_tool_specs(default_xace_tool_specs()),
            security_policy=AgentSecurityPolicy(),
            warnings=tuple(redact_text(str(warning)) for warning in warnings),
        )

    def _status(
        self,
        *,
        installed: bool,
        available: bool,
        auth_state: AgentAuthState,
        executable_path: str | None,
        version: str | None,
        capabilities: AgentCapabilities,
        warnings: tuple[str, ...],
        metadata: Mapping[str, Any],
        account_label: str | None = None,
    ) -> AgentProviderStatus:
        return AgentProviderStatus(
            provider_id=self.provider_id,
            display_name=self.display_name,
            provider_kind=AgentProviderKind.CODEX_APP_SERVER,
            installed=installed,
            available=available,
            auth_state=auth_state,
            executable_path=executable_path,
            version=version,
            min_supported_version=None,
            account_label=account_label,
            capabilities=capabilities,
            warnings=tuple(redact_text(str(warning)) for warning in warnings),
            last_checked_at=self._clock(),
            metadata=_json_object_or_empty(metadata),
        )

    def _safe_resolve_executable(self) -> CodexExecutableCandidate | None:
        try:
            candidate = self._executable_resolver()
        except Exception:
            return None
        if candidate is None:
            return None
        if isinstance(candidate, CodexExecutableCandidate):
            return candidate
        return CodexExecutableCandidate(
            path=str(getattr(candidate, "path", "")),
            source=str(getattr(candidate, "source", "custom")),
        )

    def _safe_read_version(self, executable_path: str) -> tuple[str | None, tuple[str, ...]]:
        try:
            version_text = self._version_reader(executable_path)
            version = parse_codex_version(version_text or "")
            if version:
                return version, ()
            return None, ("Codex version could not be parsed.",)
        except Exception as exc:
            return None, (f"Codex version probe failed: {redact_exception(exc)}",)


class CodexStdioJsonRpcProbe:
    """Short-lived stdio JSONL probe for Codex App Server metadata."""

    def probe(
        self,
        executable_path: str,
        *,
        timeout_seconds: float = CODEX_DEFAULT_TIMEOUT_SECONDS,
    ) -> CodexAppServerProbeResult:
        client = CodexStdioJsonRpcClient(
            executable_path,
            timeout_seconds=timeout_seconds,
        )
        try:
            initialize = initialize_codex_client(client)
            account = client.request("account/read", {"refreshToken": False})
            if _auth_state(
                account.get("account") if isinstance(account, Mapping) else None,
                bool(account.get("requiresOpenaiAuth", False))
                if isinstance(account, Mapping)
                else False,
            ) is AgentAuthState.MISSING:
                models: Mapping[str, Any] = {"data": [], "nextCursor": None}
                provider_capabilities: Mapping[str, Any] = {}
                rate_limits: Mapping[str, Any] = {}
                warnings = ("Codex App Server requires authentication before model discovery.",)
            else:
                models = client.request(
                    "model/list",
                    {"limit": 100, "includeHidden": False},
                )
                provider_capabilities = client.optional_request(
                    "modelProvider/capabilities/read",
                    {},
                )
                rate_limits = client.optional_request("account/rateLimits/read", {})
                warnings = ()
            return CodexAppServerProbeResult(
                initialize=initialize,
                account=account,
                models=models,
                provider_capabilities=provider_capabilities,
                rate_limits=rate_limits,
                notifications=(),
                warnings=warnings,
            )
        finally:
            client.close()


class CodexStdioJsonRpcClient:
    """Persistent JSON-RPC-over-stdio client for one App Server connection."""

    def __init__(
        self,
        executable_path: str,
        *,
        timeout_seconds: float = CODEX_DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._proc = subprocess.Popen(
            [executable_path, *CODEX_APP_SERVER_COMMAND],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self._session = _JsonRpcLineSession(
            self._proc,
            timeout_seconds=timeout_seconds,
        )

    @property
    def closed(self) -> bool:
        return self._proc.poll() is not None

    def request(self, method: str, params: Mapping[str, Any]) -> dict[str, JsonValue]:
        return self._session.request(method, params)

    def optional_request(
        self,
        method: str,
        params: Mapping[str, Any],
    ) -> dict[str, JsonValue]:
        return self._session.optional_request(method, params)

    def notify(self, method: str, params: Mapping[str, Any]) -> None:
        self._session.notify(method, params)

    def respond(self, request_id: int | str, result: Mapping[str, Any]) -> None:
        self._session.respond(request_id, result)

    def read_notification(
        self,
        timeout_seconds: float = CODEX_NOTIFICATION_IDLE_SECONDS,
    ) -> dict[str, JsonValue] | None:
        return self._session.read_notification(timeout_seconds)

    def close(self) -> None:
        self._session.close()


class _JsonRpcLineSession:
    def __init__(
        self,
        proc: subprocess.Popen[str],
        *,
        timeout_seconds: float,
    ) -> None:
        self._proc = proc
        self._timeout_seconds = max(0.25, float(timeout_seconds))
        self._next_id = 1
        self._messages: queue.Queue[str] = queue.Queue()
        self.notifications: list[dict[str, JsonValue]] = []
        self._io_lock = threading.RLock()
        self._reader = threading.Thread(
            target=self._read_stdout,
            name="codex-app-server-stdio-reader",
            daemon=True,
        )
        self._reader.start()

    def request(self, method: str, params: Mapping[str, Any]) -> dict[str, JsonValue]:
        with self._io_lock:
            request_id = self._next_id
            self._next_id += 1
            self._send({"method": method, "id": request_id, "params": dict(params)})
            return self._read_response(request_id, method)

    def optional_request(
        self,
        method: str,
        params: Mapping[str, Any],
    ) -> dict[str, JsonValue]:
        try:
            return self.request(method, params)
        except CodexAppServerProtocolError as exc:
            return {
                "unavailable": True,
                "method": method,
                "error": redact_text(str(exc)),
            }

    def notify(self, method: str, params: Mapping[str, Any]) -> None:
        with self._io_lock:
            self._send({"method": method, "params": dict(params)})

    def respond(self, request_id: int | str, result: Mapping[str, Any]) -> None:
        with self._io_lock:
            self._send({"id": request_id, "result": dict(result)})

    def read_notification(
        self,
        timeout_seconds: float = CODEX_NOTIFICATION_IDLE_SECONDS,
    ) -> dict[str, JsonValue] | None:
        deadline = time.monotonic() + max(0.01, float(timeout_seconds))
        with self._io_lock:
            if self.notifications:
                return self.notifications.pop(0)
            while time.monotonic() < deadline:
                message = self._next_message(deadline, "notification")
                if message is None:
                    return None
                if "id" in message:
                    return message
                if isinstance(message.get("method"), str):
                    return message
            return None

    def close(self) -> None:
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
        except Exception:
            pass
        try:
            if self._proc.stdout:
                self._proc.stdout.close()
        except Exception:
            pass
        if self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=1.0)
            except Exception:
                with contextlib.suppress(Exception):
                    self._proc.kill()
                    self._proc.wait(timeout=1.0)

    def _send(self, message: Mapping[str, Any]) -> None:
        if self._proc.stdin is None:
            raise CodexAppServerProtocolError("Codex App Server stdin is unavailable")
        try:
            self._proc.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
            self._proc.stdin.flush()
        except Exception as exc:
            raise CodexAppServerProtocolError(
                f"Could not write to Codex App Server: {redact_exception(exc)}"
            ) from exc

    def _read_response(self, request_id: int, method: str) -> dict[str, JsonValue]:
        deadline = time.monotonic() + self._timeout_seconds
        while time.monotonic() < deadline:
            message = self._next_message(deadline, method)
            if message is None:
                continue
            if isinstance(message.get("method"), str) or "id" not in message:
                self.notifications.append(message)
                continue
            if message.get("id") != request_id:
                continue
            if "error" in message:
                error = message.get("error")
                if isinstance(error, Mapping):
                    message_text = str(error.get("message") or error)
                else:
                    message_text = str(error or "unknown error")
                raise CodexAppServerProtocolError(
                    f"{method} failed: {redact_text(message_text)}"
                )
            result = message.get("result")
            if not isinstance(result, Mapping):
                raise CodexAppServerProtocolError(
                    f"{method} returned a malformed result"
                )
            return _json_object_or_empty(result)
        raise CodexAppServerProtocolError(f"Timed out waiting for {method}")

    def _next_message(
        self,
        deadline: float,
        method: str,
    ) -> dict[str, JsonValue] | None:
        if self._proc.poll() is not None and self._messages.empty():
            raise CodexAppServerProtocolError(
                f"Codex App Server exited while waiting for {method}"
            )
        try:
            remaining = max(0.01, min(0.05, deadline - time.monotonic()))
            line = self._messages.get(timeout=remaining)
        except queue.Empty:
            return None
        line = line.strip()
        if not line:
            return None
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CodexAppServerProtocolError(
                f"Codex App Server returned non-JSON output for {method}"
            ) from exc
        if not isinstance(message, Mapping):
            raise CodexAppServerProtocolError(
                f"Codex App Server returned a non-object message for {method}"
            )
        return _json_object_or_empty(message)

    def _read_stdout(self) -> None:
        stdout = self._proc.stdout
        if stdout is None:
            return
        try:
            for line in stdout:
                self._messages.put(line)
        except Exception:
            return


def initialize_codex_client(
    client: CodexAppServerClient,
) -> dict[str, JsonValue]:
    initialize = client.request(
        "initialize",
        {
            "clientInfo": {
                "name": "xace_builder",
                "title": "XACE Builder",
                "version": "0.1.0",
            },
            "capabilities": {
                "experimentalApi": True,
            },
        },
    )
    client.notify("initialized", {})
    return initialize


def resolve_codex_executable() -> CodexExecutableCandidate | None:
    for env_name in (CODEX_APP_SERVER_ENV, CODEX_EXECUTABLE_ENV):
        configured = os.environ.get(env_name, "").strip()
        if configured:
            path = Path(configured).expanduser()
            if path.exists() and path.is_file():
                return CodexExecutableCandidate(str(path.resolve()), env_name)
            return None

    runtime_dir = os.environ.get(CODEX_RUNTIME_DIR_ENV, "").strip()
    for candidate in _bundled_codex_candidates(runtime_dir):
        if candidate.exists() and candidate.is_file():
            return CodexExecutableCandidate(str(candidate.resolve()), "bundled")

    discovered = shutil.which("codex")
    if discovered:
        return CodexExecutableCandidate(str(Path(discovered).resolve()), "PATH")
    return None


def read_codex_version(executable_path: str) -> str | None:
    completed = subprocess.run(
        [executable_path, "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=CODEX_VERSION_TIMEOUT_SECONDS,
        check=False,
    )
    output = (completed.stdout or "").strip()
    if not output:
        return None
    return output.splitlines()[0].strip()


def parse_codex_version(version_text: str) -> str | None:
    match = _VERSION_RE.search(str(version_text or ""))
    return match.group("version") if match else None


def _thread_start_params(
    request: AgentStartRequest,
    *,
    tool_bridge: XaceMcpToolBridge | None = None,
) -> dict[str, JsonValue]:
    metadata = dict(request.metadata)
    params: dict[str, Any] = {
        "approvalPolicy": "never",
        "sandbox": "readOnly",
        "historyMode": "paginated",
        "allowProviderModelFallback": True,
    }
    cwd = _context_cwd(request.context_capsule_path, metadata)
    if cwd:
        params["cwd"] = cwd
    model = _metadata_str(metadata, "codex_model") or _metadata_str(metadata, "model")
    if model:
        params["model"] = model
    if tool_bridge is not None:
        params["dynamicTools"] = tool_bridge.codex_dynamic_tools()
    return _json_object_or_empty(params)


def _thread_resume_params(handle: AgentSessionHandle) -> dict[str, JsonValue]:
    params: dict[str, Any] = {
        "threadId": handle.provider_session_id,
        "excludeTurns": True,
        "initialTurnsPage": {
            "limit": 20,
            "sortDirection": "desc",
            "itemsView": "summary",
        },
        "approvalPolicy": "never",
    }
    cwd = _context_cwd(
        str(handle.metadata.get("context_capsule_path") or ""),
        dict(handle.metadata),
    )
    if cwd:
        params["cwd"] = cwd
    model = _metadata_str(handle.metadata, "codex_model") or _metadata_str(handle.metadata, "model")
    if model:
        params["model"] = model
    return _json_object_or_empty(params)


def _turn_start_params(request: AgentTurnRequest) -> dict[str, JsonValue]:
    metadata = dict(request.metadata)
    handle_metadata = dict(request.handle.metadata)
    cwd = _context_cwd(
        str(handle_metadata.get("context_capsule_path") or ""),
        {**handle_metadata, **metadata},
    )
    params: dict[str, Any] = {
        "threadId": request.handle.provider_session_id,
        "clientUserMessageId": _client_user_message_id(request),
        "input": [{"type": "text", "text": request.user_prompt}],
        "approvalPolicy": "never",
        "sandboxPolicy": {"type": "readOnly"},
        "summary": "concise",
        "personality": "pragmatic",
    }
    if cwd:
        params["cwd"] = cwd
    model = _metadata_str(metadata, "codex_model") or _metadata_str(handle_metadata, "codex_model")
    if model:
        params["model"] = model
    effort = _metadata_str(metadata, "reasoning_effort") or _metadata_str(handle_metadata, "reasoning_effort")
    if effort:
        params["effort"] = effort
    return _json_object_or_empty(params)


def _context_cwd(context_capsule_path: str | None, metadata: Mapping[str, Any]) -> str:
    configured = str(context_capsule_path or "").strip()
    if configured:
        path = Path(configured)
        if path.suffix:
            return str(path.parent)
        return str(path)
    capsule_dir = str(metadata.get("context_capsule_dir") or "").strip()
    if capsule_dir:
        return capsule_dir
    project_path = str(metadata.get("project_path") or "").strip()
    return project_path


def _client_user_message_id(request: AgentTurnRequest) -> str:
    digest = hashlib.sha256(
        json.dumps(
            {
                "session_id": request.handle.xace_session_id,
                "thread_id": request.handle.provider_session_id,
                "prompt": request.user_prompt,
                "base_cgs_hash": request.base_cgs_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:16]
    return f"xace-agent-{digest}"


def _thread_from_result(result: Mapping[str, Any], method: str) -> dict[str, JsonValue]:
    thread = result.get("thread") if isinstance(result, Mapping) else None
    if not isinstance(thread, Mapping):
        raise CodexAppServerProtocolError(f"{method} response is missing thread")
    payload = _json_object_or_empty(thread)
    if not str(payload.get("id") or "").strip():
        raise CodexAppServerProtocolError(f"{method} response thread is missing id")
    return payload


def _turn_from_result(result: Mapping[str, Any], method: str) -> dict[str, JsonValue]:
    turn = result.get("turn") if isinstance(result, Mapping) else None
    if not isinstance(turn, Mapping):
        raise CodexAppServerProtocolError(f"{method} response is missing turn")
    payload = _json_object_or_empty(turn)
    if not str(payload.get("id") or "").strip():
        raise CodexAppServerProtocolError(f"{method} response turn is missing id")
    return payload


def _agent_event_from_codex_notification(
    notification: Mapping[str, Any],
    *,
    handle: AgentSessionHandle,
    sequence: int,
    fallback_turn_id: str,
    clock: Callable[[], str],
) -> AgentEvent | None:
    method = str(notification.get("method") or "").strip()
    if not method:
        return None
    params = notification.get("params") if isinstance(notification.get("params"), Mapping) else {}
    params = _json_object_or_empty(params)
    event_type = _codex_event_type(method, params)
    turn_id = _codex_turn_id(params) or fallback_turn_id
    message = _codex_event_message(method, params, event_type)
    event_id = _codex_event_id(method, handle.provider_session_id, sequence, turn_id)
    return AgentEvent(
        event_id=event_id,
        event_type=event_type,
        session_id=handle.xace_session_id,
        provider_id=CODEX_APP_SERVER_PROVIDER_ID,
        sequence=sequence,
        message=message,
        data={
            "codex_method": method,
            "provider_thread_id": handle.provider_session_id,
            "provider_turn_id": turn_id,
            "params": params,
            "safe_transport": CODEX_APP_SERVER_TRANSPORT,
        },
        created_at=clock(),
    )


def _codex_event_type(method: str, params: Mapping[str, Any]) -> AgentEventType:
    if method == "thread/started":
        return AgentEventType.SESSION_STARTED
    if method == "turn/started":
        return AgentEventType.TURN_STARTED
    if method == "turn/completed":
        turn = params.get("turn") if isinstance(params.get("turn"), Mapping) else {}
        status = str(turn.get("status") or "")
        if status == "interrupted":
            return AgentEventType.TURN_CANCELLED
        if status == "failed":
            return AgentEventType.ERROR
        return AgentEventType.TURN_COMPLETED
    if method.startswith("item/") and _codex_item_is_tool_like(method, params):
        return AgentEventType.TOOL_CALL
    return AgentEventType.STATUS


def _codex_item_is_tool_like(method: str, params: Mapping[str, Any]) -> bool:
    if method == "item/tool/call":
        return True
    item = params.get("item") if isinstance(params.get("item"), Mapping) else {}
    item_type = str(item.get("type") or params.get("type") or "")
    if item_type in {
        "commandExecution",
        "fileChange",
        "mcpToolCall",
        "toolCall",
        "dynamicToolCall",
        "webSearch",
    }:
        return True
    return any(
        token in method
        for token in (
            "commandExecution",
            "fileChange",
            "mcpToolCall",
            "toolCall",
            "applyPatch",
        )
    )


def _codex_event_message(
    method: str,
    params: Mapping[str, Any],
    event_type: AgentEventType,
) -> str:
    if method == "thread/started":
        return "Codex thread started."
    if method == "turn/started":
        return "Codex turn started."
    if method == "turn/completed":
        turn = params.get("turn") if isinstance(params.get("turn"), Mapping) else {}
        status = str(turn.get("status") or "")
        if status == "interrupted":
            return "Codex turn interrupted."
        if status == "failed":
            error = turn.get("error") if isinstance(turn.get("error"), Mapping) else {}
            return f"Codex turn failed: {redact_text(str(error.get('message') or 'unknown error'))}"
        return "Codex turn completed."
    if method == "item/agentMessage/delta":
        delta = str(params.get("delta") or params.get("text") or "")
        return f"Codex message delta: {redact_text(delta[:120])}" if delta else "Codex message delta."
    if method.startswith("item/"):
        item = params.get("item") if isinstance(params.get("item"), Mapping) else {}
        item_type = str(item.get("type") or "item")
        if event_type is AgentEventType.TOOL_CALL:
            return f"Codex tool event: {item_type}."
        return f"Codex item event: {item_type}."
    if method == "thread/tokenUsage/updated":
        return "Codex token usage updated."
    if method == "thread/compact/start" or method == "compacted":
        return "Codex thread compaction updated."
    if method in {"warning", "configWarning"}:
        return redact_text(str(params.get("message") or params.get("summary") or "Codex warning."))
    return f"Codex event: {method}."


def _codex_turn_id(params: Mapping[str, Any]) -> str:
    turn = params.get("turn") if isinstance(params.get("turn"), Mapping) else {}
    turn_id = str(params.get("turnId") or turn.get("id") or "")
    return turn_id


def _codex_event_id(
    method: str,
    provider_thread_id: str,
    sequence: int,
    turn_id: str,
) -> str:
    safe_method = _EVENT_ID_SAFE_RE.sub("-", method).strip("-") or "event"
    digest = hashlib.sha256(
        json.dumps(
            {
                "method": method,
                "thread_id": provider_thread_id,
                "turn_id": turn_id,
                "sequence": sequence,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:10]
    return f"codex-{safe_method}-{sequence:04d}-{digest}"


def _initialize_metadata(initialize: Mapping[str, Any]) -> dict[str, JsonValue]:
    return _json_object_or_empty(
        {
            "platformFamily": initialize.get("platformFamily"),
            "platformOs": initialize.get("platformOs"),
            "userAgent": initialize.get("userAgent"),
        }
    )


def _metadata_str(metadata: Mapping[str, Any], key: str) -> str:
    value = metadata.get(key) if isinstance(metadata, Mapping) else ""
    return str(value or "").strip()


def _bundled_codex_candidates(runtime_dir: str) -> tuple[Path, ...]:
    names = ("codex.exe", "codex.cmd", "codex") if sys.platform == "win32" else ("codex",)
    roots: list[Path] = []
    if runtime_dir:
        roots.append(Path(runtime_dir).expanduser())
    repo_root = Path(__file__).resolve().parents[4]
    roots.extend(
        [
            repo_root / "vendor" / "codex",
            repo_root / "bin" / "codex",
            repo_root / ".xace" / "codex-runtime",
        ]
    )
    return tuple(root / name for root in roots for name in names)


def _normalize_model_catalog(models_result: Mapping[str, Any]) -> dict[str, JsonValue]:
    result = _require_mapping(models_result, "models")
    data = result.get("data")
    if not isinstance(data, list):
        raise CodexAppServerProtocolError("model/list result must include data[]")
    models: list[dict[str, JsonValue]] = []
    model_ids: list[str] = []
    default_model = ""
    for index, item in enumerate(data):
        if not isinstance(item, Mapping):
            raise CodexAppServerProtocolError(
                f"model/list data[{index}] must be an object"
            )
        model_id = str(item.get("id") or item.get("model") or "").strip()
        if not model_id:
            raise CodexAppServerProtocolError(
                f"model/list data[{index}] is missing an id"
            )
        supported_efforts = item.get("supportedReasoningEfforts")
        if not isinstance(supported_efforts, list):
            supported_efforts = []
        input_modalities = item.get("inputModalities")
        if not isinstance(input_modalities, list):
            input_modalities = ["text", "image"]
        model_payload = {
            "id": model_id,
            "model": str(item.get("model") or model_id),
            "displayName": str(item.get("displayName") or model_id),
            "hidden": bool(item.get("hidden", False)),
            "isDefault": bool(item.get("isDefault", False)),
            "defaultReasoningEffort": str(item.get("defaultReasoningEffort") or ""),
            "supportedReasoningEfforts": _json_list(supported_efforts),
            "inputModalities": [str(value) for value in input_modalities],
            "supportsPersonality": bool(item.get("supportsPersonality", False)),
            "upgrade": _optional_str(item.get("upgrade")),
            "upgradeInfo": _json_object_or_empty(item.get("upgradeInfo", {})),
        }
        models.append(_json_object_or_empty(model_payload))
        model_ids.append(model_id)
        if item.get("isDefault") and not default_model:
            default_model = model_id
    if not default_model and model_ids:
        default_model = model_ids[0]
    return {
        "models": models,
        "model_ids": model_ids,
        "default_model": default_model,
    }


def _auth_state(account: Any, requires_openai_auth: bool) -> AgentAuthState:
    if isinstance(account, Mapping):
        account_type = str(account.get("type") or "").strip()
        if account_type == "apiKey":
            return AgentAuthState.API_KEY
        if account_type in {"chatgpt", "chatgptAuthTokens"}:
            return AgentAuthState.SIGNED_IN
        if account_type:
            return AgentAuthState.SIGNED_IN
    if requires_openai_auth:
        return AgentAuthState.MISSING
    return AgentAuthState.NOT_REQUIRED


def _account_label(account: Any, requires_openai_auth: bool) -> str | None:
    if isinstance(account, Mapping):
        account_type = str(account.get("type") or "").strip()
        plan = str(account.get("planType") or "").strip()
        if account_type == "apiKey":
            return "Codex API key"
        if account_type in {"chatgpt", "chatgptAuthTokens"}:
            email = _redacted_email(str(account.get("email") or "").strip())
            pieces = ["ChatGPT"]
            if plan:
                pieces.append(plan)
            if email:
                pieces.append(email)
            return " ".join(pieces)
        if account_type:
            return account_type
    if requires_openai_auth:
        return "Sign in required"
    return None


def _account_metadata(account: Any, requires_openai_auth: bool) -> dict[str, JsonValue]:
    metadata: dict[str, Any] = {
        "requires_openai_auth": requires_openai_auth,
        "auth_state": _auth_state(account, requires_openai_auth).value,
    }
    if isinstance(account, Mapping):
        metadata["type"] = str(account.get("type") or "")
        metadata["plan_type"] = str(account.get("planType") or "")
        metadata["email"] = _redacted_email(str(account.get("email") or ""))
        metadata["credential_source"] = str(account.get("credentialSource") or "")
    return _json_object_or_empty(metadata)


def _redacted_email(email: str) -> str:
    match = _REDACTED_EMAIL_RE.match(str(email or "").strip())
    if not match:
        return ""
    local, domain = match.groups()
    if len(local) <= 1:
        redacted_local = "*"
    else:
        redacted_local = f"{local[0]}***"
    return f"{redacted_local}@{domain}"


def _require_mapping(value: Mapping[str, Any], label: str) -> dict[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise CodexAppServerProtocolError(f"{label} result must be an object")
    return _json_object_or_empty(value)


def _json_object_or_empty(value: Any) -> dict[str, JsonValue]:
    if not isinstance(value, Mapping):
        return {}
    normalized = normalize_json_value(redact_value(dict(value)), "codex_adapter")
    return normalized if isinstance(normalized, dict) else {}


def _json_list(values: list[Any]) -> list[JsonValue]:
    normalized = normalize_json_value(redact_value(values), "codex_adapter_list")
    return normalized if isinstance(normalized, list) else []


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_tool_specs(specs: tuple[AgentToolSpec, ...]) -> tuple[AgentToolSpec, ...]:
    return tuple(specs)


def _is_codex_dynamic_tool_request(notification: Mapping[str, Any]) -> bool:
    return (
        str(notification.get("method") or "") == "item/tool/call"
        and isinstance(notification.get("id"), (int, str))
    )


def _with_xace_tool_response(
    notification: Mapping[str, Any], response: Mapping[str, Any]
) -> dict[str, JsonValue]:
    params = _json_object_or_empty(notification.get("params", {}))
    return _json_object_or_empty(
        {**dict(notification), "params": {**params, "xace_tool_response": dict(response)}}
    )


def _tool_bridge_metadata(bridge: XaceMcpToolBridge | None) -> dict[str, JsonValue]:
    if bridge is None:
        return {"configured": False, "preferred_transport": ToolTransport.MCP.value}
    return bridge.metadata()


__all__ = [
    "CODEX_APP_SERVER_COMMAND",
    "CODEX_APP_SERVER_DISPLAY_NAME",
    "CODEX_APP_SERVER_PROVIDER_ID",
    "CODEX_APP_SERVER_TRANSPORT",
    "CODEX_APP_SERVER_ENV",
    "CODEX_EXECUTABLE_ENV",
    "CODEX_NOTIFICATION_IDLE_SECONDS",
    "CODEX_RUNTIME_DIR_ENV",
    "CodexAppServerAdapter",
    "CodexAppServerClient",
    "CodexAppServerProbe",
    "CodexAppServerProbeResult",
    "CodexAppServerProtocolError",
    "CodexCompactionResult",
    "CodexExecutableCandidate",
    "CodexStdioJsonRpcClient",
    "CodexStdioJsonRpcProbe",
    "initialize_codex_client",
    "parse_codex_version",
    "read_codex_version",
    "resolve_codex_executable",
]
