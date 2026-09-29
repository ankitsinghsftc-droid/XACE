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
import re
import shutil
import subprocess
import threading
import time
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from secret_redaction import redact_exception, redact_text, redact_value

from .contracts import (
    AgentAuthState,
    AgentBillingSource,
    AgentBillingUsage,
    AgentCostState,
    AgentTokenTrackingState,
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
from .codex_runtime_lifecycle import (
    CODEX_GUIDED_RUNTIME_SOURCE,
    CODEX_RUNTIME_DIR_ENV,
    resolve_verified_codex_runtime,
    codex_runtime_selection_exists,
)
from .mcp_server import XaceMcpToolBridge
from .mcp_transport import (
    XaceMcpNativeTransport,
    XaceMcpTransportError,
)
from .security_policy import (
    AgentSecurityPolicyEnforcer,
    AgentSecurityPolicyError,
    denial_response_for_provider_request,
)
from .tool_surface import default_xace_tool_specs, proposal_xace_tool_spec


CODEX_APP_SERVER_PROVIDER_ID = "codex_app_server"
CODEX_APP_SERVER_DISPLAY_NAME = "Codex App Server"
CODEX_APP_SERVER_TRANSPORT = "stdio_jsonl"
CODEX_APP_SERVER_COMMAND = ("app-server", "--listen", "stdio://")
CODEX_EXECUTABLE_ENV = "XACE_CODEX_EXECUTABLE"
CODEX_APP_SERVER_ENV = "XACE_CODEX_APP_SERVER_BIN"
CODEX_DEFAULT_TIMEOUT_SECONDS = 4.0
CODEX_VERSION_TIMEOUT_SECONDS = 2.0
CODEX_NOTIFICATION_IDLE_SECONDS = 0.25
CODEX_APP_SERVER_STABLE_API_PROFILE = "stable"
CODEX_DYNAMIC_TOOLS_EXPERIMENT = "app_server_dynamic_tools"
CODEX_RUNTIME_SOURCE_MANAGED = "xace_managed"
CODEX_RUNTIME_SOURCE_EXTERNAL = "external_cli"
CODEX_RUNTIME_SOURCE_HOST_EXTENSION = "host_extension_private"
CODEX_RUNTIME_SOURCE_CUSTOM = "custom"

_VERSION_RE = re.compile(r"(?P<version>\d+\.\d+\.\d+(?:[-+][A-Za-z0-9_.-]+)?)")
_REDACTED_EMAIL_RE = re.compile(r"^([^@\s]+)@([^@\s]+)$")
_EVENT_ID_SAFE_RE = re.compile(r"[^A-Za-z0-9_.:-]+")


from .codex_protocol import CodexAppServerProtocolError, JsonRpcLineSession as _JsonRpcLineSession


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
    usage: Mapping[str, Any] = field(default_factory=dict)
    notifications: tuple[Mapping[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "initialize",
            "account",
            "models",
            "provider_capabilities",
            "rate_limits",
            "usage",
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
        turn_idle_timeout_seconds: float = 120.0,
        tool_bridge_factory: Callable[
            [AgentStartRequest | AgentSessionHandle], XaceMcpToolBridge | None
        ] | None = None,
        security_policy: AgentSecurityPolicy | None = None,
        native_mcp_transport_factory: Callable[
            [XaceMcpToolBridge], XaceMcpNativeTransport
        ] | None = None,
        allow_experimental_dynamic_tools_fallback: bool = False,
    ) -> None:
        self._executable_resolver = executable_resolver or resolve_codex_executable
        self._app_server_probe = app_server_probe or CodexStdioJsonRpcProbe()
        self._client_factory = client_factory
        self._timeout_seconds = timeout_seconds
        self._version_reader = version_reader or read_codex_version
        self._clock = clock or utc_now_iso
        self._notification_idle_seconds = max(0.05, float(notification_idle_seconds))
        self._turn_idle_timeout_seconds = max(0.05, float(turn_idle_timeout_seconds))
        self._tool_bridge_factory = tool_bridge_factory
        self._security_policy: AgentSecurityPolicyEnforcer | None = None
        self._security_policy_error = ""
        self._native_mcp_transport_factory = (
            native_mcp_transport_factory or XaceMcpNativeTransport.start
        )
        self._allow_experimental_dynamic_tools_fallback = bool(
            allow_experimental_dynamic_tools_fallback)
        try:
            self._security_policy = AgentSecurityPolicyEnforcer(
                policy=security_policy,
                tool_specs=_agent_tool_specs(),
            )
        except AgentSecurityPolicyError as exc:
            self._security_policy_error = redact_text(exc)
        self._clients: dict[str, CodexAppServerClient] = {}
        self._tool_bridges: dict[str, XaceMcpToolBridge] = {}
        self._active_turns: dict[str, str] = {}
        self._enabled_tools: dict[str, tuple[str, ...]] = {}
        self._lock = threading.RLock()
        self._native_mcp_transports: dict[str, XaceMcpNativeTransport] = {}
        self._auth_controller = None
        self._diagnostic_error = None
        self._diagnostic_mcp = "not_connected"

    def diagnostic_snapshot(self):
        # Snapshot only; no process launch/provider calls or adapter/auth lock inversion.
        with self._lock:
            result = {
                "state": "connected" if self._clients else "failed" if self._diagnostic_error else "idle",
                "active_connections": len(self._clients), "active_turns": len(self._active_turns),
                "active_bridges": len(self._native_mcp_transports),
                "mcp_state": self._diagnostic_mcp if self._native_mcp_transports or self._diagnostic_mcp == "failed" else "not_connected",
                "error_code": self._diagnostic_error,
            }
            auth = self._auth_controller
        result["auth"] = auth.snapshot() if auth is not None else {}
        return result

    @property
    def authentication(self):
        from .codex_auth import CodexAuthController

        with self._lock:
            if self._auth_controller is None:
                self._auth_controller = CodexAuthController(
                    self._new_auth_client, invalidate_sessions=self._close_session_clients)
            return self._auth_controller

    def _new_auth_client(self):
        candidate = self._safe_resolve_executable()
        if candidate is None:
            raise CodexAppServerProtocolError("Codex executable was not found")
        client = (self._client_factory(candidate.path) if self._client_factory else
                  CodexStdioJsonRpcClient(candidate.path, timeout_seconds=30.0))
        try:
            initialize_codex_client(client)
            return client
        except Exception:
            client.close()
            raise

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
                    "runtime_compatibility": {
                        "schema": "xace.codex_runtime_compatibility.v1",
                        "state": "missing",
                        "basis": "stable_app_server_protocol_probe",
                        "source_kind": "not_found",
                        "support_tier": "unavailable",
                        "public_distribution_ready": False,
                        "native_mcp_transport_implemented": True,
                        "experimental_tool_fallback": CODEX_DYNAMIC_TOOLS_EXPERIMENT,
                    },
                    "transport": CODEX_APP_SERVER_TRANSPORT,
                    "session_lifecycle_implemented": True,
                    "turn_execution_implemented": True,
                    "mcp_tool_bridge_implemented": True,
                    "proposal_submission_implemented": True,
                    "native_mcp_transport_implemented": True,
                    "codex_dynamic_tools_fallback_implemented": True,
                    "experimental_api_required_for_tool_bridge": False,
                },
            )

        version, version_warnings = self._safe_read_version(candidate.path)
        runtime_compatibility = codex_runtime_compatibility(candidate, version)
        runtime_warnings = tuple(runtime_compatibility.pop("warnings", []))
        try:
            if isinstance(self._app_server_probe, CodexStdioJsonRpcProbe):
                _verify_external_protocol(candidate.path)
            probe = self._app_server_probe.probe(
                candidate.path,
                timeout_seconds=self._timeout_seconds,
            )
            return self._status_from_probe(candidate, version, probe, version_warnings)
        except Exception as exc:
            self._diagnostic_error = getattr(exc, "code", "provider_unavailable")
            warning = f"Codex App Server probe failed: {redact_exception(exc)}"
            runtime_compatibility["state"] = "protocol_probe_failed"
            runtime_compatibility["basis"] = (
                "failed_stable_app_server_protocol_probe"
            )
            warnings = (*version_warnings, *runtime_warnings, warning)
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
                    "runtime_compatibility": runtime_compatibility,
                    "transport": CODEX_APP_SERVER_TRANSPORT,
                    "probe_error": warning,
                    "session_lifecycle_implemented": True,
                    "turn_execution_implemented": True,
                    "mcp_tool_bridge_implemented": True,
                    "native_mcp_transport_implemented": True,
                    "codex_dynamic_tools_fallback_implemented": True,
                    "experimental_api_required_for_tool_bridge": False,
                    "proposal_submission_implemented": True,
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
        policy = self._policy_or_raise()
        thread_id = request.handle.provider_session_id
        sequence = 0
        terminal = False
        try:
            starting = asyncio.create_task(asyncio.to_thread(self._start_turn_sync, request))
            try:
                start_result = await asyncio.shield(starting)
            except asyncio.CancelledError:
                # A to_thread worker cannot be cancelled; await its bounded RPC
                # before final cleanup, or it could publish a client after close.
                with contextlib.suppress(Exception):
                    await starting
                raise
            self._diagnostic_error = None
            turn = _turn_from_result(start_result, "turn/start")
            turn_id = str(turn.get("id") or "")
            enabled_tools = self._enabled_tools.get(thread_id) or None
            last_event = time.monotonic()
            last_health = last_event
            while not terminal:
                if time.monotonic() - last_health >= 5.0:
                    await asyncio.to_thread(self._check_thread_mcp_health, thread_id)
                    last_health = time.monotonic()
                notification = await asyncio.to_thread(
                    self._read_thread_notification,
                    thread_id,
                    self._notification_idle_seconds,
                )
                if notification is None:
                    if time.monotonic() - last_event > self._turn_idle_timeout_seconds:
                        raise CodexAppServerProtocolError("Codex turn idle timeout; resume explicitly. No turn was replayed.", code="turn_idle_timeout")
                    await asyncio.sleep(0)
                    continue
                if _validate_turn_notification(notification, thread_id, turn_id) is False:
                    continue
                last_event = time.monotonic()
                decision = policy.inspect_provider_event(
                    notification,
                    enabled_tools=enabled_tools,
                )
                if not decision.allowed:
                    await asyncio.to_thread(
                        self._deny_provider_event,
                        thread_id,
                        turn_id,
                        notification,
                    )
                    sequence += 1
                    yield _security_violation_event(
                        handle=request.handle,
                        sequence=sequence,
                        turn_id=turn_id,
                        code=decision.code,
                        reason=decision.reason,
                        clock=self._clock,
                    )
                    terminal = True
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
                    if event.event_type is AgentEventType.ERROR:
                        self._diagnostic_error = "provider_error"
                    terminal = True
        except Exception as exc:
            self._diagnostic_error = getattr(exc, "code", "provider_error")
            raise
        finally:
            with self._lock:
                self._active_turns.pop(thread_id, None)
            await asyncio.to_thread(self._close_thread_client, thread_id)

    def _policy_or_raise(self) -> AgentSecurityPolicyEnforcer:
        if self._security_policy is None:
            reason = self._security_policy_error or "security policy initialization failed"
            raise CodexAppServerProtocolError(
                f"Codex Agent Mode is disabled: {redact_text(reason)}"
            )
        return self._security_policy

    def _start_session_sync(self, request: AgentStartRequest) -> AgentSessionHandle:
        with self._lock:
            policy = self._policy_or_raise()
            policy.validate_metadata(request.metadata)
            policy.validate_enabled_tools(request.allowed_tools)
            tool_bridge = self._tool_bridge_for(request)
            native_transport, use_dynamic_fallback = self._prepare_tool_transport(
                tool_bridge
            )
            client: CodexAppServerClient | None = None
            try:
                launch = native_transport.launch_config if native_transport else None
                client, initialize = self._new_initialized_client(
                    experimental_api=use_dynamic_fallback,
                    extra_environment=(
                        launch.app_server_environment if launch else None
                    ),
                )
                params = _thread_start_params(
                    request,
                    tool_bridge=tool_bridge,
                    native_mcp_config=launch.thread_config if launch else None,
                    use_dynamic_fallback=use_dynamic_fallback,
                    security_policy=policy,
                )
                policy.require_codex_method("thread/start")
                result = client.request("thread/start", params)
                thread = _thread_from_result(result, "thread/start")
                provider_session_id = str(thread.get("id") or "")
                mcp_status = (
                    self._verify_native_mcp_status(
                        client, provider_session_id, tool_bridge
                    )
                    if native_transport is not None and tool_bridge is not None
                    else {}
                )
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
                        "app_server_api_profile": (
                            "experimental_dynamic_tools"
                            if use_dynamic_fallback
                            else CODEX_APP_SERVER_STABLE_API_PROFILE
                        ),
                        "experimental_features": (
                            [CODEX_DYNAMIC_TOOLS_EXPERIMENT]
                            if use_dynamic_fallback
                            else []
                        ),
                        "tool_transport": (
                            "mcp"
                            if native_transport is not None
                            else (
                                "app_server_dynamic_tools"
                                if use_dynamic_fallback
                                else "none"
                            )
                        ),
                        "native_mcp": {
                            **(
                                native_transport.metadata()
                                if native_transport is not None
                                else {}
                            ),
                            **mcp_status,
                        },
                        "mcp_tool_bridge": _tool_bridge_metadata(tool_bridge),
                    },
                )
                self._clients[provider_session_id] = client
                self._enabled_tools[provider_session_id] = _enabled_tool_names(
                    request, tool_bridge
                )
                if tool_bridge is not None:
                    self._tool_bridges[provider_session_id] = tool_bridge
                if native_transport is not None:
                    self._native_mcp_transports[provider_session_id] = native_transport
                return handle
            except Exception:
                if client is not None:
                    client.close()
                if native_transport is not None:
                    native_transport.close()
                raise

    def _resume_session_sync(self, handle: AgentSessionHandle) -> AgentSessionHandle:
        with self._lock:
            policy = self._policy_or_raise()
            policy.validate_metadata(handle.metadata)
            self._close_thread_client(handle.provider_session_id)
            tool_bridge = self._tool_bridge_for(handle)
            native_transport, use_dynamic_fallback = self._prepare_tool_transport(
                tool_bridge
            )
            client: CodexAppServerClient | None = None
            try:
                launch = native_transport.launch_config if native_transport else None
                client, initialize = self._new_initialized_client(
                    experimental_api=use_dynamic_fallback,
                    extra_environment=(
                        launch.app_server_environment if launch else None
                    ),
                )
                params = _thread_resume_params(
                    handle,
                    tool_bridge=tool_bridge,
                    native_mcp_config=launch.thread_config if launch else None,
                    use_dynamic_fallback=use_dynamic_fallback,
                    security_policy=policy,
                )
                policy.require_codex_method("thread/resume")
                result = client.request("thread/resume", params)
                thread = _thread_from_result(result, "thread/resume")
                provider_session_id = str(thread.get("id") or "")
                if provider_session_id != handle.provider_session_id:
                    raise CodexAppServerProtocolError("Codex resume returned a different thread; start a new session explicitly.", code="stale_session")
                mcp_status = (
                    self._verify_native_mcp_status(
                        client, provider_session_id, tool_bridge
                    )
                    if native_transport is not None and tool_bridge is not None
                    else {}
                )
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
                        "app_server_api_profile": (
                            "experimental_dynamic_tools"
                            if use_dynamic_fallback
                            else CODEX_APP_SERVER_STABLE_API_PROFILE
                        ),
                        "experimental_features": (
                            [CODEX_DYNAMIC_TOOLS_EXPERIMENT]
                            if use_dynamic_fallback
                            else []
                        ),
                        "tool_transport": (
                            "mcp"
                            if native_transport is not None
                            else (
                                "app_server_dynamic_tools"
                                if use_dynamic_fallback
                                else "none"
                            )
                        ),
                        "native_mcp": {
                            **(
                                native_transport.metadata()
                                if native_transport is not None
                                else {}
                            ),
                            **mcp_status,
                        },
                        "mcp_tool_bridge": _tool_bridge_metadata(tool_bridge),
                    },
                )
                self._clients[provider_session_id] = client
                self._enabled_tools[provider_session_id] = _enabled_tool_names(
                    handle, tool_bridge
                )
                if tool_bridge is not None:
                    self._tool_bridges[provider_session_id] = tool_bridge
                if native_transport is not None:
                    self._native_mcp_transports[provider_session_id] = native_transport
                return next_handle
            except Exception:
                if client is not None:
                    client.close()
                if native_transport is not None:
                    native_transport.close()
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
            policy = self._policy_or_raise()
            policy.validate_metadata(handle.metadata)
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
            policy.require_codex_method("thread/fork")
            result = client.request("thread/fork", params)
            thread = _thread_from_result(result, "thread/fork")
            provider_session_id = str(thread.get("id") or "")
            parent_bridge = self._tool_bridges.get(handle.provider_session_id)
            if parent_bridge is not None:
                self._tool_bridges[provider_session_id] = parent_bridge
            self._enabled_tools[provider_session_id] = self._enabled_tools.get(
                handle.provider_session_id, ()
            )
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
            policy = self._policy_or_raise()
            policy.validate_metadata(handle.metadata)
            client = self._client_for_handle(handle)
            policy.require_codex_method("thread/compact/start")
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
            policy = self._policy_or_raise()
            policy.validate_metadata(request.metadata)
            policy.validate_enabled_tools(request.allowed_tools)
            client = self._client_for_handle(request.handle)
            params = _turn_start_params(
                request,
                security_policy=policy,
            )
            policy.require_codex_method("turn/start")
            bridge = self._tool_bridges.get(request.handle.provider_session_id)
            if bridge is not None and request.handle.provider_session_id in self._native_mcp_transports:
                self._verify_native_mcp_status(client, request.handle.provider_session_id, bridge)
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
                    self._policy_or_raise().require_codex_method("turn/interrupt")
                    client.request(
                        "turn/interrupt",
                        {"threadId": thread_id, "turnId": turn_id},
                    )
                with contextlib.suppress(Exception):
                    self._policy_or_raise().require_codex_method(
                        "thread/backgroundTerminals/clean"
                    )
                    client.optional_request(
                        "thread/backgroundTerminals/clean",
                        {"threadId": thread_id},
                    )
            finally:
                self._active_turns.pop(thread_id, None)
                self._close_thread_client(thread_id)

    def _deny_provider_event(
        self,
        thread_id: str,
        turn_id: str,
        notification: Mapping[str, Any],
    ) -> None:
        client = self._clients.get(thread_id)
        if client is None or getattr(client, "closed", False):
            return
        request_id = notification.get("id")
        if isinstance(request_id, (int, str)):
            with contextlib.suppress(Exception):
                client.respond(
                    request_id,
                    denial_response_for_provider_request(notification),
                )
        if turn_id:
            with contextlib.suppress(Exception):
                self._policy_or_raise().require_codex_method("turn/interrupt")
                client.request(
                    "turn/interrupt",
                    {"threadId": thread_id, "turnId": turn_id},
                )

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
        notification = client.read_notification(timeout_seconds)
        if notification and self._auth_controller is not None:
            method = notification.get("method")
            if isinstance(method, str) and method.startswith("account/") and "id" not in notification:
                self._auth_controller.mark_account_dirty()
            if method == "error":
                self._auth_controller.observe_failure(notification.get("params", {}))
            elif method == "turn/completed":
                params = notification.get("params") or {}
                turn = params.get("turn") or {}
                if turn.get("error"):
                    self._auth_controller.observe_failure(turn["error"])
        return notification

    def _check_thread_mcp_health(self, thread_id):
        bridge = self._tool_bridges.get(thread_id)
        if bridge is not None and thread_id in self._native_mcp_transports:
            client = self._clients.get(thread_id)
            if client is None:
                raise CodexAppServerProtocolError("Required XACE MCP connection closed; resume explicitly.")
            self._verify_native_mcp_status(client, thread_id, bridge)

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

    def _new_initialized_client(
        self,
        *,
        experimental_api: bool = False,
        extra_environment: Mapping[str, str] | None = None,
    ) -> tuple[CodexAppServerClient, dict[str, JsonValue]]:
        candidate = self._safe_resolve_executable()
        if candidate is None:
            self._diagnostic_error = "runtime_missing"
            raise CodexAppServerProtocolError("Codex executable was not found.")
        if self._client_factory is None:
            try:
                _verify_external_protocol(candidate.path)
            except Exception as exc:
                self._diagnostic_error = getattr(exc, "code", "provider_unavailable")
                raise
        # Retry only initialization of an otherwise unused process, never a turn.
        for attempt in range(2):
            client = None
            try:
                if self._client_factory is not None:
                    client = self._client_factory(candidate.path)
                else:
                    client = CodexStdioJsonRpcClient(
                        candidate.path, timeout_seconds=self._timeout_seconds,
                        extra_environment=extra_environment,
                    )
                initialize = initialize_codex_client(client, experimental_api=experimental_api)
                self._diagnostic_error = None
                return client, initialize
            except Exception as exc:
                self._diagnostic_error = getattr(exc, "code", "provider_unavailable")
                if client is not None:
                    client.close()
                if attempt or not isinstance(exc, CodexAppServerProtocolError) or not exc.retryable:
                    raise
                time.sleep(0.1)
        raise CodexAppServerProtocolError("Codex initialization failed")

    def _prepare_tool_transport(
        self,
        tool_bridge: XaceMcpToolBridge | None,
    ) -> tuple[XaceMcpNativeTransport | None, bool]:
        if tool_bridge is None:
            return None, False
        transport: XaceMcpNativeTransport | None = None
        try:
            transport = self._native_mcp_transport_factory(tool_bridge)
            if not isinstance(transport, XaceMcpNativeTransport):
                raise XaceMcpTransportError(
                    "Native MCP transport factory returned an invalid transport"
                )
            _ = transport.launch_config
            return transport, False
        except Exception as exc:
            if transport is not None:
                with contextlib.suppress(Exception):
                    transport.close()
            if self._allow_experimental_dynamic_tools_fallback:
                return None, True
            raise CodexAppServerProtocolError(
                "XACE native MCP transport could not start; Codex Agent Mode "
                f"failed closed: {redact_exception(exc)}"
            ) from exc

    def _verify_native_mcp_status(
        self,
        client: CodexAppServerClient,
        thread_id: str,
        tool_bridge: XaceMcpToolBridge,
    ) -> dict[str, JsonValue]:
        policy = self._policy_or_raise()
        self._diagnostic_mcp = "failed"
        policy.require_codex_method("mcpServerStatus/list")
        result = client.request(
            "mcpServerStatus/list",
            {
                "threadId": thread_id,
                "detail": "toolsAndAuthOnly",
                "limit": 100,
            },
        )
        rows = result.get("data")
        if not isinstance(rows, list):
            raise CodexAppServerProtocolError(
                "Codex MCP status response is missing data"
            )
        status = next(
            (
                row
                for row in rows
                if isinstance(row, Mapping)
                and str(row.get("name") or "") == tool_bridge.server_name
            ),
            None,
        )
        if not isinstance(status, Mapping):
            raise CodexAppServerProtocolError(
                "Codex did not register the required XACE MCP server"
            )
        runtime_status = str(status.get("runtimeStatus") or "")
        if runtime_status != "connected":
            raise CodexAppServerProtocolError(
                "Required XACE MCP server is not connected"
            )
        tools = status.get("tools")
        if not isinstance(tools, Mapping):
            raise CodexAppServerProtocolError(
                "Required XACE MCP server returned no tool catalog"
            )
        actual_tools = tuple(sorted(str(name) for name in tools))
        expected_tools = tuple(sorted(tool_bridge.tool_names))
        if actual_tools != expected_tools:
            raise CodexAppServerProtocolError(
                "Required XACE MCP server tool catalog does not match the "
                "session allowlist"
            )
        self._diagnostic_mcp = "connected"
        return {
            "runtime_status": runtime_status,
            "status_verified": True,
            "tools": list(actual_tools),
        }

    def _tool_bridge_for(
        self, request: AgentStartRequest | AgentSessionHandle
    ) -> XaceMcpToolBridge | None:
        if self._tool_bridge_factory is None:
            return None
        bridge = self._tool_bridge_factory(request)
        if bridge is not None and not isinstance(bridge, XaceMcpToolBridge):
            raise CodexAppServerProtocolError("XACE tool bridge factory returned an invalid bridge")
        if bridge is not None:
            policy = self._policy_or_raise()
            policy.register_tool_specs(bridge.surface.tool_specs())
            policy.validate_enabled_tools(bridge.context.allowed_tools)
        return bridge

    def _close_thread_client(self, thread_id: str) -> None:
        self._tool_bridges.pop(thread_id, None)
        client = self._clients.pop(thread_id, None)
        native_transport = self._native_mcp_transports.pop(thread_id, None)
        self._enabled_tools.pop(thread_id, None)
        if client is not None:
            with contextlib.suppress(Exception):
                client.close()
        if native_transport is not None:
            with contextlib.suppress(Exception):
                native_transport.close()

    def close(self) -> None:
        if self._auth_controller is not None:
            self._auth_controller.close()
        self._close_session_clients()

    def _close_session_clients(self) -> None:
        with self._lock:
            thread_ids = tuple(
                set(self._clients).union(self._native_mcp_transports)
            )
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
        usage = _json_object_or_empty(probe.usage)
        runtime_compatibility = codex_runtime_compatibility(candidate, version)
        runtime_compatibility["state"] = "compatible_current_protocol"
        runtime_compatibility["basis"] = (
            "stable_app_server_protocol_probe"
        )
        runtime_warnings = tuple(runtime_compatibility.pop("warnings", []))
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
            *runtime_warnings,
            *tuple(redact_text(str(item)) for item in probe.warnings),
        )
        if auth_state in {AgentAuthState.MISSING, AgentAuthState.EXPIRED}:
            warnings = (*warnings, "Codex App Server reported missing authentication.")
        if not model_catalog.get("models"):
            warnings = (*warnings, "Codex App Server returned no picker-visible models.")

        metadata = {
            "detection_source": candidate.source,
            "app_server_responsive": app_server_responsive,
            "runtime_compatibility": runtime_compatibility,
            "transport": CODEX_APP_SERVER_TRANSPORT,
            "probed_methods": [
                "initialize",
                "account/read",
                "model/list",
                "modelProvider/capabilities/read",
                "account/rateLimits/read",
                "account/usage/read",
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
            "usage": usage,
            "notifications_seen": len(probe.notifications),
            "session_lifecycle_implemented": True,
            "turn_execution_implemented": True,
            "mcp_tool_bridge_implemented": True,
            "proposal_submission_implemented": True,
            "native_mcp_transport_implemented": True,
            "codex_dynamic_tools_fallback_implemented": True,
            "experimental_api_required_for_tool_bridge": False,
        }
        return self._status(
            installed=True,
            available=available,
            auth_state=auth_state,
            executable_path=candidate.path,
            version=version,
            account_label=account_label,
            billing=_codex_billing_status(account, requires_openai_auth, rate_limits, usage),
            capabilities=self._base_capabilities(warnings=warnings),
            warnings=warnings,
            metadata=metadata,
        )

    def _base_capabilities(
        self,
        *,
        warnings: tuple[str, ...] = (),
    ) -> AgentCapabilities:
        security_warnings = (
            (f"Agent security policy failed closed: {self._security_policy_error}",)
            if self._security_policy is None
            else ()
        )
        return AgentCapabilities(
            supports_mcp_tools=self._security_policy is not None,
            supports_streaming_events=self._security_policy is not None,
            supports_thread_resume=self._security_policy is not None,
            supports_thread_fork=self._security_policy is not None,
            supports_compaction=self._security_policy is not None,
            supports_cancellation=self._security_policy is not None,
            supports_model_discovery=True,
            supports_account_state=True,
            supports_progressive_retrieval=self._security_policy is not None,
            supported_tool_transports=(ToolTransport.MCP,) if self._security_policy else (),
            xace_tools=_safe_tool_specs(_agent_tool_specs()) if self._security_policy else (),
            security_policy=(
                self._security_policy.policy if self._security_policy else AgentSecurityPolicy()
            ),
            warnings=tuple(
                redact_text(str(warning)) for warning in (*warnings, *security_warnings)
            ),
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
        billing: AgentBillingUsage | None = None,
    ) -> AgentProviderStatus:
        security_ready = self._security_policy is not None
        security_warnings = (
            (f"Agent security policy failed closed: {self._security_policy_error}",)
            if not security_ready
            else ()
        )
        safe_metadata = {
            **dict(metadata),
            "agent_security_policy_ready": security_ready,
            "agent_security_policy_schema": "xace.agent_security_policy.v1",
        }
        return AgentProviderStatus(
            provider_id=self.provider_id,
            display_name=self.display_name,
            provider_kind=AgentProviderKind.CODEX_APP_SERVER,
            installed=installed,
            available=available and security_ready,
            auth_state=auth_state,
            executable_path=executable_path,
            version=version,
            min_supported_version=None,
            account_label=account_label,
            capabilities=capabilities,
            billing=billing or AgentBillingUsage(),
            warnings=tuple(
                redact_text(str(warning)) for warning in (*warnings, *security_warnings)
            ),
            last_checked_at=self._clock(),
            metadata=_json_object_or_empty(safe_metadata),
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
                usage: Mapping[str, Any] = {}
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
                usage = client.optional_request("account/usage/read", {})
                warnings = ()
            return CodexAppServerProbeResult(
                initialize=initialize,
                account=account,
                models=models,
                provider_capabilities=provider_capabilities,
                rate_limits=rate_limits,
                usage=usage,
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
        extra_environment: Mapping[str, str] | None = None,
    ) -> None:
        environment = None
        if extra_environment:
            environment = {**os.environ, **dict(extra_environment)}
        self._proc = subprocess.Popen(
            [executable_path, *CODEX_APP_SERVER_COMMAND],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
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


def initialize_codex_client(
    client: CodexAppServerClient,
    *,
    experimental_api: bool = False,
) -> dict[str, JsonValue]:
    params: dict[str, Any] = {
        "clientInfo": {
            "name": "xace_builder",
            "title": "XACE Builder",
            "version": "0.1.0",
        },
    }
    if experimental_api:
        params["capabilities"] = {"experimentalApi": True}
    initialize = client.request(
        "initialize",
        params,
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

    verified = resolve_verified_codex_runtime()
    if verified is not None:
        return CodexExecutableCandidate(
            str(verified["executable_path"]),
            CODEX_GUIDED_RUNTIME_SOURCE,
        )

    if codex_runtime_selection_exists():
        return None

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


def codex_runtime_compatibility(
    candidate: CodexExecutableCandidate,
    version: str | None,
) -> dict[str, JsonValue]:
    """Describe compatibility and provenance without trusting version strings alone."""

    normalized_path = str(candidate.path).replace("\\", "/").lower()
    source = str(candidate.source).strip()
    is_host_extension = (
        ("/.vscode/extensions/openai.chatgpt-" in normalized_path)
        or ("/.cursor/extensions/openai.chatgpt-" in normalized_path)
    )
    if is_host_extension:
        source_kind = CODEX_RUNTIME_SOURCE_HOST_EXTENSION
        support_tier = "development_fallback_only"
    elif source == CODEX_GUIDED_RUNTIME_SOURCE:
        source_kind = CODEX_RUNTIME_SOURCE_EXTERNAL
        support_tier = "guided_external_verified"
    elif source in {CODEX_APP_SERVER_ENV, CODEX_EXECUTABLE_ENV, "PATH"}:
        source_kind = CODEX_RUNTIME_SOURCE_EXTERNAL
        support_tier = "external_development_or_fallback"
    else:
        source_kind = CODEX_RUNTIME_SOURCE_CUSTOM
        support_tier = "custom_or_test"

    warnings: list[str] = []
    if is_host_extension:
        warnings.append(
            "Codex was discovered inside another product's private extension directory. "
            "XACE may use it as a development fallback, but it is not a supported public "
            "distribution source."
        )
    if version and "-" in version:
        warnings.append(
            "The detected Codex runtime is a prerelease build; compatibility is established "
            "by the live App Server protocol probe, not by a stable release version."
        )
    warnings.append(
        "XACE uses stable App Server native MCP for the production tool bridge. "
        "App Server dynamicTools remains available only as an explicit development "
        "fallback."
    )

    return {
        "schema": "xace.codex_runtime_compatibility.v1",
        "state": "candidate_unverified",
        "basis": "runtime_provenance_and_version_only",
        "api_profile": CODEX_APP_SERVER_STABLE_API_PROFILE,
        "version": version,
        "version_channel": "prerelease" if version and "-" in version else "stable_or_unknown",

        "source_kind": source_kind,
        "support_tier": support_tier,
        "public_distribution_ready": False,
        "native_mcp_transport_implemented": True,
        "experimental_tool_fallback": CODEX_DYNAMIC_TOOLS_EXPERIMENT,
        "warnings": warnings,
    }


def _thread_start_params(
    request: AgentStartRequest,
    *,
    tool_bridge: XaceMcpToolBridge | None = None,
    native_mcp_config: Mapping[str, Any] | None = None,
    use_dynamic_fallback: bool = False,
    security_policy: AgentSecurityPolicyEnforcer,
) -> dict[str, JsonValue]:
    metadata = dict(request.metadata)
    params: dict[str, Any] = {
        "approvalPolicy": "never",
        "sandbox": "read-only",
        "serviceName": "xace_builder",
        "allowProviderModelFallback": True,
    }
    cwd = _context_cwd(request.context_capsule_path, metadata, security_policy)
    if cwd:
        params["cwd"] = cwd
    model = _metadata_str(metadata, "codex_model") or _metadata_str(metadata, "model")
    if model:
        params["model"] = model
    _apply_tool_transport_params(
        params,
        tool_bridge=tool_bridge,
        native_mcp_config=native_mcp_config,
        use_dynamic_fallback=use_dynamic_fallback,
    )
    return _json_object_or_empty(params)


def _thread_resume_params(
    handle: AgentSessionHandle,
    *,
    tool_bridge: XaceMcpToolBridge | None = None,
    native_mcp_config: Mapping[str, Any] | None = None,
    use_dynamic_fallback: bool = False,
    security_policy: AgentSecurityPolicyEnforcer,
) -> dict[str, JsonValue]:
    params: dict[str, Any] = {
        "threadId": handle.provider_session_id,
        "excludeTurns": True,
        "initialTurnsPage": {
            "limit": 20,
            "sortDirection": "desc",
            "itemsView": "summary",
        },
        "sandbox": "read-only",
        "approvalPolicy": "never",
    }
    cwd = _context_cwd(
        str(handle.metadata.get("context_capsule_path") or ""),
        dict(handle.metadata),
        security_policy,
    )
    if cwd:
        params["cwd"] = cwd
    model = _metadata_str(handle.metadata, "codex_model") or _metadata_str(
        handle.metadata, "model"
    )
    if model:
        params["model"] = model
    _apply_tool_transport_params(
        params,
        tool_bridge=tool_bridge,
        native_mcp_config=native_mcp_config,
        use_dynamic_fallback=use_dynamic_fallback,
    )
    return _json_object_or_empty(params)


def _apply_tool_transport_params(
    params: dict[str, Any],
    *,
    tool_bridge: XaceMcpToolBridge | None,
    native_mcp_config: Mapping[str, Any] | None,
    use_dynamic_fallback: bool,
) -> None:
    if native_mcp_config is not None and use_dynamic_fallback:
        raise CodexAppServerProtocolError(
            "Native MCP and dynamicTools fallback cannot be enabled together"
        )
    config: dict[str, Any] = {
        "features": {
            "shell_tool": False,
            "unified_exec": False,
        },
        "tools": {
            "web_search": False,
            "view_image": False,
        },
        "web_search": "disabled",
    }
    if native_mcp_config is not None:
        for key, value in native_mcp_config.items():
            config[str(key)] = value
    params["config"] = config
    if use_dynamic_fallback:
        if tool_bridge is None:
            raise CodexAppServerProtocolError(
                "dynamicTools fallback requires an XACE tool bridge"
            )
        params["dynamicTools"] = tool_bridge.codex_dynamic_tools()


def _turn_start_params(
    request: AgentTurnRequest,
    *,
    security_policy: AgentSecurityPolicyEnforcer,
) -> dict[str, JsonValue]:
    metadata = dict(request.metadata)
    handle_metadata = dict(request.handle.metadata)
    cwd = _context_cwd(
        str(handle_metadata.get("context_capsule_path") or ""),
        {**handle_metadata, **metadata},
        security_policy,
    )
    params: dict[str, Any] = {
        "threadId": request.handle.provider_session_id,
        "clientUserMessageId": _client_user_message_id(request),
        "input": [{"type": "text", "text": request.user_prompt}],
        "approvalPolicy": "never",
        "sandboxPolicy": security_policy.codex_sandbox_policy(cwd),
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


def _context_cwd(
    context_capsule_path: str | None,
    metadata: Mapping[str, Any],
    security_policy: AgentSecurityPolicyEnforcer,
) -> str:
    return security_policy.resolve_capsule_cwd(context_capsule_path, metadata)


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
    if not isinstance(payload.get("id"), str) or not payload["id"].strip():
        raise CodexAppServerProtocolError(f"{method} response thread is missing id")
    return payload


def _turn_from_result(result: Mapping[str, Any], method: str) -> dict[str, JsonValue]:
    turn = result.get("turn") if isinstance(result, Mapping) else None
    if not isinstance(turn, Mapping):
        raise CodexAppServerProtocolError(f"{method} response is missing turn")
    payload = _json_object_or_empty(turn)
    if not isinstance(payload.get("id"), str) or not payload["id"].strip():
        raise CodexAppServerProtocolError(f"{method} response turn is missing id")
    return payload


def _security_violation_event(
    *,
    handle: AgentSessionHandle,
    sequence: int,
    turn_id: str,
    code: str,
    reason: str,
    clock: Callable[[], str],
) -> AgentEvent:
    digest = hashlib.sha256(
        json.dumps(
            {
                "thread_id": handle.provider_session_id,
                "turn_id": turn_id,
                "sequence": sequence,
                "code": code,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:12]
    return AgentEvent(
        event_id=f"codex-security-{digest}",
        event_type=AgentEventType.ERROR,
        session_id=handle.xace_session_id,
        provider_id=CODEX_APP_SERVER_PROVIDER_ID,
        sequence=sequence,
        message=f"Codex turn stopped by XACE security policy: {redact_text(reason)}",
        data={"security_code": code, "denied": True},
        created_at=clock(),
    )

def _agent_event_from_codex_notification(
    notification: Mapping[str, Any],
    *,
    handle: AgentSessionHandle,
    sequence: int,
    fallback_turn_id: str,
    clock: Callable[[], str],
) -> AgentEvent | None:
    method = str(notification.get("method") or "").strip()
    if not method or method.startswith("account/"):
        return None
    params = notification.get("params") if isinstance(notification.get("params"), Mapping) else {}
    params = _json_object_or_empty(params)
    if method in {"error", "turn/completed"}:
        from .codex_auth import _failure
        turn = params.get("turn") if isinstance(params.get("turn"), dict) else {}
        error = turn.get("error") if method == "turn/completed" else params
        if error:
            code, action = _failure(error)
            if code in {"auth_expired", "workspace_restricted", "rate_limited"}:
                safe_error = {"message": code, "recovery_action": action}
                params = ({"turn": {"id": turn.get("id"), "status": turn.get("status"),
                                    "error": safe_error}} if method == "turn/completed" else safe_error)
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


def _codex_billing_status(
    account: Any,
    requires_openai_auth: bool,
    rate_limits: Mapping[str, Any],
    usage: Mapping[str, Any],
) -> AgentBillingUsage:
    account_type = str(account.get("type") or "").strip() if isinstance(account, Mapping) else ""
    plan = str(account.get("planType") or "").strip() if isinstance(account, Mapping) else ""
    usage_payload = _json_object_or_empty(usage)
    summary = usage_payload.get("summary")
    usage_summary = _json_object_or_empty(summary) if isinstance(summary, Mapping) else {}
    safe_limits = _json_object_or_empty(rate_limits)

    if account_type in {"chatgpt", "chatgptAuthTokens"}:
        plan_text = f" {plan}" if plan else ""
        return AgentBillingUsage(
            source=AgentBillingSource.PROVIDER_ACCOUNT,
            cost_state=AgentCostState.PROVIDER_MANAGED,
            token_tracking=AgentTokenTrackingState.PROVIDER_REPORTED,
            label=f"Provider-managed ChatGPT{plan_text} usage",
            detail=(
                "Codex reports account usage and limits when available; "
                "XACE does not convert subscription usage into an API cost estimate."
            ),
            usage_summary=usage_summary,
            rate_limits=safe_limits,
        )

    if account_type:
        return AgentBillingUsage(
            source=AgentBillingSource.PROVIDER_ACCOUNT,
            cost_state=AgentCostState.PROVIDER_MANAGED,
            token_tracking=(
                AgentTokenTrackingState.PROVIDER_REPORTED
                if usage_summary
                else AgentTokenTrackingState.UNKNOWN
            ),
            label="Provider-managed Codex usage",
            detail=(
                "Codex owns this account's billing and limit state; "
                "XACE does not estimate App Server turn cost."
            ),
            usage_summary=usage_summary,
            rate_limits=safe_limits,
        )

    detail = (
        "Sign in to Codex to load provider-managed billing and usage state."
        if requires_openai_auth
        else "The active Codex provider did not report a billing source."
    )
    return AgentBillingUsage(
        source=AgentBillingSource.UNKNOWN,
        cost_state=AgentCostState.UNKNOWN,
        token_tracking=AgentTokenTrackingState.UNKNOWN,
        label="Cost unavailable",
        detail=detail,
        usage_summary=usage_summary,
        rate_limits=safe_limits,
    )


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


def _agent_tool_specs() -> tuple[AgentToolSpec, ...]:
    return default_xace_tool_specs() + (proposal_xace_tool_spec(),)


def _enabled_tool_names(
    request: AgentStartRequest | AgentSessionHandle,
    bridge: XaceMcpToolBridge | None,
) -> tuple[str, ...]:
    if bridge is not None:
        return bridge.tool_names
    return tuple(getattr(request, "allowed_tools", ()) or ())


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
    "CODEX_APP_SERVER_STABLE_API_PROFILE",
    "CODEX_DYNAMIC_TOOLS_EXPERIMENT",
    "CODEX_RUNTIME_SOURCE_CUSTOM",
    "CODEX_RUNTIME_SOURCE_EXTERNAL",
    "CODEX_RUNTIME_SOURCE_HOST_EXTENSION",
    "CODEX_RUNTIME_SOURCE_MANAGED",
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
    "codex_runtime_compatibility",
    "CodexStdioJsonRpcProbe",
    "initialize_codex_client",
    "parse_codex_version",
    "read_codex_version",
    "resolve_codex_executable",
]


def _validate_turn_notification(notification, thread_id, turn_id):
    """Reject malformed/stale consumed events before mapping or tool dispatch."""
    if not isinstance(notification, Mapping) or not isinstance(notification.get("method"), str):
        raise CodexAppServerProtocolError("Malformed Codex notification", code="malformed_event")
    method = notification["method"]
    params = notification.get("params", {})
    if not isinstance(params, Mapping):
        raise CodexAppServerProtocolError("Malformed Codex event parameters", code="malformed_event")
    if "threadId" in params and params["threadId"] != thread_id:
        raise CodexAppServerProtocolError("Codex event belongs to a different thread", code="stale_event")
    if "turnId" in params and params["turnId"] != turn_id:
        # Resume replays the last turn\u0027s accounting snapshot. It must neither
        # abort the new turn nor be attributed to it. Never skip tool requests.
        if method == "thread/tokenUsage/updated" and "id" not in notification and params.get("threadId") == thread_id:
            return False
        raise CodexAppServerProtocolError("Codex event belongs to a different turn", code="stale_event")
    if method in {"turn/started", "turn/completed"}:
        turn = params.get("turn")
        if not isinstance(turn, Mapping) or turn.get("id") != turn_id:
            raise CodexAppServerProtocolError("Malformed or stale Codex turn", code="stale_event")
        if method == "turn/completed" and turn.get("status") not in {"completed", "interrupted", "failed"}:
            raise CodexAppServerProtocolError("Unknown Codex terminal state", code="malformed_event")
    if method.startswith("item/") and "item" in params and not isinstance(params["item"], Mapping):
        raise CodexAppServerProtocolError("Malformed Codex item", code="malformed_event")


_PROTOCOL_CACHE = {}
_PROTOCOL_CACHE_LOCK = threading.Lock()


def _verify_external_protocol(executable_path):
    # Cache only exact executable bytes, never a mutable path/version claim.
    from .codex_runtime_lifecycle import _sha256_file, _probe_stable_app_server, _is_revoked
    from .codex_compatibility import validate_schema, version_policy
    with _PROTOCOL_CACHE_LOCK:
        digest = _sha256_file(Path(executable_path))
        version = parse_codex_version(read_codex_version(executable_path))
        if _is_revoked(version or "", digest):
            raise CodexAppServerProtocolError("Codex runtime is revoked; update or switch to API/BYOK.", code="runtime_revoked")
        try:
            version_policy(version)
            if digest in _PROTOCOL_CACHE:
                return _PROTOCOL_CACHE[digest]
            result = validate_schema(_probe_stable_app_server(executable_path))
            if _sha256_file(Path(executable_path)) != digest:
                raise ValueError("Executable changed during schema verification")
        except Exception as exc:
            raise CodexAppServerProtocolError(
                "Codex schema/version is incompatible; verify a supported runtime or roll back.",
                code="schema_incompatible",
            ) from exc
        if len(_PROTOCOL_CACHE) >= 8:
            _PROTOCOL_CACHE.clear()
        _PROTOCOL_CACHE[digest] = result
        return result
